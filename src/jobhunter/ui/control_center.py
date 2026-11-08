"""Dashboard control-center pages: Q&A memory, needs-review queue, history.

These pages are read-mostly views over the durable stores. Nothing here can
submit, auto-apply, or change safety gates — the most any action does is
delete or save a Q&A answer, or clear a history file. Deletion buttons are
explicit, one-per-row, and never touch the browser.
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from jobhunter.domains.qa_catalog import INTENT_BY_NAME
from jobhunter.services.analytics import application_metrics
from jobhunter.storage import qa as qa_store
from jobhunter.storage import run_state
from jobhunter.storage.history import export_history_csv, list_all_histories
from jobhunter.ui import design as ui
from jobhunter.ui import state as ui_state

_MASK = "••••••••"


# ---------------------------------------------------------------------------
# Q&A memory management
# ---------------------------------------------------------------------------
def qa_memory_page() -> None:
    """View, add, edit and delete stored Q&A answers (the apply agent's memory)."""
    ui.page_header(
        "Q&A Memory",
        "Answers the agent remembers for application questions. Stored answers are only used "
        "when a field matches a known question — sensitive fields are never auto-filled from memory.",
        eyebrow="JobHunter AI",
        icon_name="database",
    )

    stored = {row["intent"]: row for row in qa_store.load_all_answers()}
    reveal = st.toggle("Reveal answers", value=False, key="qa_reveal")

    ui.section("Stored answers", f"{len(stored)} answer(s) remembered on this device.")

    if not stored:
        ui.empty_state(
            "No saved answers yet",
            "Answers you confirm in the browser are remembered for next time — or add one below.",
            icon_name="database",
        )
    else:
        for intent_name in sorted(stored):
            row = stored[intent_name]
            intent = INTENT_BY_NAME.get(intent_name)
            sensitive = bool(intent and intent.sensitive)
            label = intent.question if intent else intent_name
            with st.expander(f"{escape(label)}", expanded=False):
                meta = f"source: {row.get('source', '?')} · saved {str(row.get('confirmed_at', ''))[:10]}"
                st.caption(meta)
                if sensitive:
                    st.warning(
                        "Sensitive question. The agent never answers this automatically — "
                        "it only reuses what you explicitly save here."
                    )
                st.text_input(
                    "Answer",
                    value=row.get("answer", "") if reveal else _MASK,
                    key=f"qa_answer_{intent_name}",
                    disabled=not reveal,
                )
                if st.button("Delete this answer", key=f"qa_del_{intent_name}", width="stretch"):
                    qa_store.delete_answer(intent_name)
                    st.rerun()

    ui.section("Add or update an answer", "Pick the question, type your answer, and save it.")
    intent_options = {
        f"{'[sensitive] ' if INTENT_BY_NAME[name].sensitive else ''}{INTENT_BY_NAME[name].question}": name
        for name in sorted(INTENT_BY_NAME)
    }
    choice = st.selectbox("Question", options=list(intent_options.keys()), key="qa_pick_intent")
    intent_name = intent_options[choice]
    sensitive = INTENT_BY_NAME[intent_name].sensitive
    if sensitive:
        st.caption("Sensitive question — stored only for explicit reuse, never auto-filled.")
    answer = st.text_input("Answer", key="qa_new_answer")
    if st.button("Save answer", type="primary", width="stretch"):
        if not answer.strip():
            st.error("Type an answer first (use Delete to remove one instead).")
        else:
            qa_store.save_answer(intent_name, answer.strip(), "user")
            st.success("Answer saved. It will be reused for matching questions.")
            st.rerun()


# ---------------------------------------------------------------------------
# Needs-review queue
# ---------------------------------------------------------------------------
def needs_review_page() -> None:
    """Everything that stopped before submission and needs the user's attention."""
    ui.page_header(
        "Needs Review",
        "Applications that stopped before submission, and submit attempts that were never verified. "
        "Nothing on this page was marked as applied.",
        eyebrow="JobHunter AI",
        icon_name="alert",
    )

    histories = list_all_histories()
    queue = ui_state.needs_review_queue(histories)
    attempts = run_state.list_all_submission_attempts()

    ui.metric_grid(
        [
            {"label": "Needs your step", "value": str(len(queue)), "caption": "stopped before submit"},
            {
                "label": "Unverified attempts",
                "value": str(len(attempts)),
                "caption": "may have been submitted — verify in the portal",
            },
        ]
    )

    if attempts:
        ui.section(
            "Unverified submission attempts",
            "A previous run may have clicked submit before crashing. The agent will never auto-retry these.",
        )
        for attempt in attempts:
            st.markdown(
                f'<div class="jh-app-row"><div>'
                f'<span class="jh-status skipped">Unverified</span> '
                f"<code>{escape(str(attempt.get('job_id', '')))}</code>"
                f'<span class="jh-job-meta"> · {escape(str(attempt.get("attempted_at", ""))[:19])}</span></div>'
                f'<a class="jh-apply" href="{escape(str(attempt.get("url", "")))}" target="_blank" '
                f'rel="noopener">Verify</a></div>',
                unsafe_allow_html=True,
            )
        st.caption(
            "Clearing a marker is not offered here — verify in the portal, then it will age out of the list."
        )

    if queue:
        ui.section(
            "Stopped before submission", "Each entry tells you why it stopped — finish it in the portal."
        )
        for item in queue:
            label = ui_state.status_label(item["status"])
            css = ui_state.status_css(item["status"])
            reasons = item.get("detail") or "No reason recorded"
            link = (
                f'<a class="jh-apply" href="{escape(str(item.get("url") or ""))}" target="_blank" '
                f'rel="noopener">Open</a>'
                if item.get("url")
                else ""
            )
            st.markdown(
                f'<div class="jh-job"><div class="jh-job-top"><div>'
                f'<div class="jh-job-title">{escape(str(item["title"]))}'
                f'<span class="jh-source">{escape(str(item["source"]))}</span></div>'
                f'<div class="jh-job-company">{escape(str(item["company"]))}</div>'
                f'<div class="jh-job-meta"><span class="jh-status {css}">{escape(label)}</span> '
                f"· {escape(str(item.get('applied_at', ''))[:16])}</div>"
                f'<div class="jh-job-meta">{escape(reasons)}</div>'
                f"</div><div>{link}</div></div></div>",
                unsafe_allow_html=True,
            )
    else:
        ui.empty_state(
            "Nothing waiting for you",
            "Applications that stop before submission will appear here with the reason.",
            icon_name="check",
        )


# ---------------------------------------------------------------------------
# Application history
# ---------------------------------------------------------------------------
def history_page() -> None:
    """Full, filterable history of every recorded outcome."""
    ui.page_header(
        "Application History",
        "Every recorded outcome, newest first. Only verification-backed submissions count as applied.",
        eyebrow="JobHunter AI",
        icon_name="clock",
    )

    histories = list_all_histories()
    rows: list[dict] = []
    for history in histories:
        for job in history.get("applied_jobs", []):
            rows.append(
                {
                    "Date": str(job.get("applied_at", ""))[:16],
                    "Title": job.get("title", ""),
                    "Company": job.get("company", ""),
                    "Source": job.get("source", ""),
                    "Status": ui_state.status_label(job.get("status")),
                    "Detail": job.get("detail", ""),
                    "URL": job.get("url", ""),
                    "Resume": str(history.get("resume_id", ""))[:8],
                }
            )
    rows.sort(key=lambda row: row["Date"], reverse=True)

    metrics = application_metrics()
    by_status = metrics.get("by_status", {})
    ui.metric_grid(
        [
            {"label": "Total outcomes", "value": f"{metrics['total_attempts']:,}"},
            {"label": "Submitted", "value": f"{metrics['submitted']:,}", "caption": "verified only"},
            {
                "label": "Submission rate",
                "value": f"{metrics['submission_rate'] * 100:.0f}%" if metrics["total_attempts"] else "—",
            },
        ]
    )

    if by_status:
        st.caption(
            "By status: " + " · ".join(f"{ui_state.status_label(s)}: {n}" for s, n in by_status.items())
        )

    if not rows:
        ui.empty_state(
            "No history yet",
            "Run a search or the apply agent — every outcome it records will appear here.",
            icon_name="clock",
        )
        return

    status_options = ["All", *sorted({row["Status"] for row in rows})]
    source_options = ["All", *sorted({row["Source"] for row in rows if row["Source"]})]
    col_a, col_b = st.columns(2)
    with col_a:
        status_filter = st.selectbox("Status", status_options, key="hist_status")
    with col_b:
        source_filter = st.selectbox("Source", source_options, key="hist_source")

    filtered = [
        row
        for row in rows
        if (status_filter == "All" or row["Status"] == status_filter)
        and (source_filter == "All" or row["Source"] == source_filter)
    ]
    st.dataframe(pd.DataFrame(filtered), width="stretch", hide_index=True)

    st.download_button(
        "Export history CSV",
        data=export_history_csv(),
        file_name="jobhunter_history.csv",
        mime="text/csv",
        width="stretch",
    )
