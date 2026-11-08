"""JobHunter AI - Streamlit dashboard shell.

Applies the shared design system, renders the sidebar, and dispatches to the
page views in :mod:`jobhunter.ui.views`.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from jobhunter.storage.history import clear_all_history, export_history_csv, list_all_histories
from jobhunter.ui import control_center, views
from jobhunter.ui import design as ui
from jobhunter.ui.components import _CSS

ROOT_DIR = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
ui.setup("JobHunter AI", icon=ROOT_DIR / "assets" / "icon.png", layout="wide")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def render_sidebar() -> str:
    """Render the sidebar and return the selected page name."""
    with st.sidebar:
        ui.sidebar_brand("JobHunter AI", "Search, score and apply")

        st.markdown('<div class="jh-side-label">Application history</div>', unsafe_allow_html=True)
        histories = list_all_histories()
        total_applied = sum(len(h.get("applied_job_ids", [])) for h in histories)
        st.metric("Total applications", total_applied)

        if histories:
            rows = "".join(
                f'<div class="jh-hist"><span class="jh-hist-date">{str(h.get("last_updated", ""))[:10] or "Earlier"}</span>'
                f'<span class="jh-hist-count">{len(h.get("applied_job_ids", []))} jobs</span></div>'
                for h in histories
            )
            st.markdown(f'<div class="jh-hist-list">{rows}</div>', unsafe_allow_html=True)
        else:
            st.caption("No applications recorded yet.")

        st.markdown('<div class="jh-side-label">Workspace</div>', unsafe_allow_html=True)
        page = st.radio(
            "Navigate",
            [
                "Job Search",
                "Auto Apply",
                "Dashboard",
                "Resumes",
                "Q&A Memory",
                "Needs Review",
                "History",
                "Settings",
            ],
            label_visibility="collapsed",
        )

        st.markdown("---")
        if st.button("Clear history", width="stretch"):
            clear_all_history()
            st.rerun()
        if histories:
            csv_data = export_history_csv()
            st.download_button(
                "Export CSV",
                data=csv_data,
                file_name="jobhunter_history.csv",
                mime="text/csv",
                width="stretch",
            )
    return page


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    page = render_sidebar()

    if page == "Job Search":
        views.job_search_page()
    elif page == "Auto Apply":
        views.auto_apply_page()
    elif page == "Dashboard":
        views.dashboard_page()
    elif page == "Resumes":
        views.resumes_page()
    elif page == "Q&A Memory":
        control_center.qa_memory_page()
    elif page == "Needs Review":
        control_center.needs_review_page()
    elif page == "History":
        control_center.history_page()
    else:
        views.settings_page()


if __name__ == "__main__":
    main()
