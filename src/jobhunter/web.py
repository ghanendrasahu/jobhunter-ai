"""Console entry point for the Streamlit dashboard.

Launches the UI via ``streamlit run`` on the dashboard module. Extra arguments
(e.g. ``--server.port``) are forwarded to Streamlit.

Run with:
    jobhunter-web
    python -m jobhunter.web
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

UI_PATH = Path(__file__).resolve().parent / "ui" / "dashboard.py"


def main() -> int:
    """Launch the Streamlit dashboard, forwarding any CLI arguments."""
    cmd = [sys.executable, "-m", "streamlit", "run", str(UI_PATH), *sys.argv[1:]]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
