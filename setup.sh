#!/usr/bin/env bash
# Streamlit Cloud entry point.
#
# Dependencies come from the exact pins in requirements.txt (python ~3.11).
# Playwright's browser is intentionally NOT installed here: scraping degrades
# gracefully to keyword/API search when no browser is present, keeping the
# image small enough for the free tier.
set -euo pipefail
cd "$(dirname "$0")"

pip install -r requirements.txt
pip install --no-deps -e .

exec streamlit run src/jobhunter/web.py
