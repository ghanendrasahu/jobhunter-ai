"""CLI entry point that prompts for a PDF resume path and runs the pipeline.

Usage: ``python run.py``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jobhunter.agent import run_job_hunter


def _prompt_for_pdf() -> str:
    """Loop until the user provides an existing PDF path (or quits)."""
    print("=" * 60)
    print("  JobHunter AI — Resume Processing Pipeline")
    print("=" * 60)

    while True:
        raw = input("\nEnter the path to your PDF resume (or 'q' to quit): ").strip()
        if raw.lower() in ("q", "quit", "exit"):
            print("Goodbye.")
            sys.exit(0)

        pdf_path = Path(raw)
        if not pdf_path.exists():
            print(f"  ✗ File not found: {raw}")
            continue
        if pdf_path.suffix.lower() != ".pdf":
            print(f"  ✗ Not a PDF file: {raw}")
            continue
        return str(pdf_path)


def main() -> None:
    pdf_path = _prompt_for_pdf()

    print(f"\n  ✓ Processing: {Path(pdf_path).name}")
    print("  Running pipeline (extract → query → search → apply)...\n")

    try:
        result = run_job_hunter(pdf_path)
    except Exception as exc:
        print(f"\n  ✗ Pipeline failed: {exc}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)

    if result.get("error"):
        print(f"\n  ⚠ Pipeline error: {result['error']}")
    else:
        print(f"\n  Resume text preview: {result.get('resume_text', '')[:200]}...")
        print(f"  Search query:        {result.get('search_query', 'N/A')}")
        print(f"  Jobs found:          {len(result.get('jobs', []))}")
        print(f"  Applications:        {len(result.get('applications', []))}")

    print("\n" + "-" * 60)
    print("Full output:")
    print(json.dumps(result, indent=2, default=str))
    print("-" * 60)


if __name__ == "__main__":
    main()
