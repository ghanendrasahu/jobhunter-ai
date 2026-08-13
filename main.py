import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    app = Path(__file__).parent / "streamlit_app.py"
    sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)]))
