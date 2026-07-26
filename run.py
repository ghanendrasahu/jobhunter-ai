"""CLI entry point — pass a PDF path or run interactively."""

import json
import sys
from pathlib import Path

from agent import run_job_hunter


def resolve_pdf(raw: str) -> Path:
    p = Path(raw)
    if not p.exists():
        print(f"  ✗ File not found: {raw}")
        sys.exit(1)
    if p.suffix.lower() != ".pdf":
        print(f"  ✗ Not a PDF file: {raw}")
        sys.exit(1)
    return p


def main() -> None:
    print("=" * 60)
    print("  JobHunter AI — Resume Processing Pipeline")
    print("=" * 60)

    if len(sys.argv) > 1:
        pdf_path = resolve_pdf(sys.argv[1])
    else:
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
            break

    print(f"\n  ✓ Processing: {pdf_path.name}")
    print("  Running pipeline (extract → query → search → apply)...\n")

    try:
        result = run_job_hunter(str(pdf_path))
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