"""Allow running the CLI with ``python -m jobhunter``."""

from jobhunter.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
