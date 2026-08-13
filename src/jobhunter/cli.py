"""Command-line entry point for the JobHunter pipeline.

Usage:
    python -m jobhunter                      # interactive prompt
    python -m jobhunter /path/to/resume.pdf  # run a specific PDF
    python -m jobhunter --schedule --query "Python Developer" --interval 360  # scheduled loop
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jobhunter.agent import run_job_hunter


def _resolve_pdf(raw: str) -> str:
    """Validate a PDF path, exiting with a message on failure."""
    pdf_path = Path(raw)
    if not pdf_path.exists():
        print(f"  ✗ File not found: {raw}")
        sys.exit(1)
    if pdf_path.suffix.lower() != ".pdf":
        print(f"  ✗ Not a PDF file: {raw}")
        sys.exit(1)
    return str(pdf_path)


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
        if not raw:
            continue
        return _resolve_pdf(raw)


def _schedule(args: argparse.Namespace) -> None:
    """Run the pipeline in a scheduled loop using the scheduler module."""
    from jobhunter.scheduler import schedule

    if not args.query:
        print("  ✗ --query is required when using --schedule")
        sys.exit(1)
    try:
        schedule(
            query=args.query,
            interval_minutes=args.interval,
            resume_pdf=args.pdf,
            max_runs=args.max_runs,
        )
    except FileNotFoundError as exc:
        print(f"  ✗ {exc}")
        sys.exit(1)


def _run_pipeline(pdf_path: str) -> None:
    """Run the pipeline once for a resume PDF and print the results."""
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


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the scheduler or single-run pipeline."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="jobhunter", description="JobHunter AI pipeline")
    parser.add_argument("pdf", nargs="?", default=None, help="Path to a PDF resume")
    parser.add_argument("--schedule", action="store_true", help="Run as a scheduled loop")
    parser.add_argument("--query", default=None, help="Search query for --schedule")
    parser.add_argument("--interval", type=int, default=360, help="Minutes between scheduled runs")
    parser.add_argument("--max-runs", type=int, default=None, help="Stop after N scheduled runs")
    args = parser.parse_args(argv)

    if args.schedule:
        _schedule(args)
        return 0

    pdf_path = _resolve_pdf(args.pdf) if args.pdf else _prompt_for_pdf()
    _run_pipeline(pdf_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
