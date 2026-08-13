"""JobHunter AI — Streamlit dashboard shell.

Applies global page config and CSS, renders the sidebar, and dispatches to the
page views in :mod:`jobhunter.ui.views`.
"""

from __future__ import annotations

import streamlit as st

from jobhunter.storage.history import clear_all_history, export_history_csv, list_all_histories
from jobhunter.ui import views
from jobhunter.ui.components import _CSS

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="JobHunter AI",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def render_sidebar() -> str:
    """Render the sidebar and return the selected page name."""
    with st.sidebar:
        st.markdown("## 🤖 JobHunter AI")
        st.markdown("### 📋 Application History")

        histories = list_all_histories()
        total_applied = sum(len(h.get("applied_job_ids", [])) for h in histories)
        st.metric("Total Applications", total_applied)

        if histories:
            for h in histories:
                rid = h.get("resume_id", "?")
                count = len(h.get("applied_job_ids", []))
                st.markdown(f"- `{rid}`: {count} job(s)")
        else:
            st.info("No applications yet.")

        st.markdown("---")
        page = st.radio(
            "Navigate",
            ["🎯 Job Search", "🤖 Auto Apply", "📊 Dashboard", "📝 Resumes", "⚙️ Settings"],
            label_visibility="collapsed",
        )

        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ Clear History", use_container_width=True):
                clear_all_history()
                st.rerun()
        with col2:
            if histories:
                csv_data = export_history_csv()
                st.download_button(
                    "📥 Export CSV",
                    data=csv_data,
                    file_name="jobhunter_history.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
    return page


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    page = render_sidebar()

    if page == "🎯 Job Search":
        views.job_search_page()
    elif page == "🤖 Auto Apply":
        views.auto_apply_page()
    elif page == "📊 Dashboard":
        views.dashboard_page()
    elif page == "📝 Resumes":
        views.resumes_page()
    else:
        views.settings_page()

    st.markdown("---")
    st.caption(
        "JobHunter AI v3.0.0 • Indian job search • AI matching • "
        "Playwright scraping • Dashboard analytics • Open source"
    )


if __name__ == "__main__":
    main()
