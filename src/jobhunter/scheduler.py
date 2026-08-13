"""Scheduled/background runner for the JobHunter pipeline.

Re-runs the pipeline for a configured query on an interval and emails a summary.
Useful for daily job monitoring without opening the dashboard.

Usage:
    python -m jobhunter.scheduler --query "Python Developer" --interval 360
    python -m jobhunter.scheduler --query "Data Analyst" --interval 360 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from jobhunter.agent import run_job_hunter
from jobhunter.domains.resume import extract_text_from_pdf
from jobhunter.services.notifications import send_job_alert_email

logger = logging.getLogger(__name__)


def _load_resume_text(resume_pdf: str | None) -> str:
    """Read the resume PDF, falling back to the first saved resume."""
    if resume_pdf:
        if not Path(resume_pdf).exists():
            raise FileNotFoundError(f"Resume not found: {resume_pdf}")
        return extract_text_from_pdf(resume_pdf)

    from jobhunter.storage.history import list_resumes

    resumes = list_resumes()
    if not resumes:
        raise FileNotFoundError(
            "No --resume path given and no saved resumes found. "
            "Upload a resume in the dashboard or pass --resume resume.pdf."
        )
    return extract_text_from_pdf(resumes[0]["file_path"])


def _first_resume_path() -> str:
    from jobhunter.storage.history import list_resumes

    resumes = list_resumes()
    return resumes[0]["file_path"] if resumes else ""


def schedule(
    query: str,
    interval_minutes: int,
    resume_pdf: str | None = None,
    dry_run: bool = False,
    max_runs: int | None = None,
) -> None:
    """Loop forever (or ``max_runs`` times), running the pipeline each interval."""
    resume_path = resume_pdf or _first_resume_path()
    if not resume_path or not Path(resume_path).exists():
        raise FileNotFoundError(
            f"Resume not found: {resume_path or '<none>'}. "
            "Upload a resume in the dashboard or pass --resume resume.pdf."
        )

    if dry_run:
        print(f"[dry-run] Query: {query!r} | Interval: {interval_minutes} min | Resume: {resume_path or '<saved>'}")
        print("[dry-run] Would run the pipeline and email a summary on each tick.")
        return

    logger.info("Scheduler started for %r every %d minutes (resume: %s)", query, interval_minutes, resume_path)
    run = 0
    while max_runs is None or run < max_runs:
        run += 1
        started = datetime.now().isoformat(timespec="seconds")
        print(f"\n[{started}] Run #{run} — searching '{query}'…", flush=True)

        try:
            result = run_job_hunter(resume_path)
        except Exception as exc:
            logger.exception("Scheduled run failed")
            print(f"  ✗ Pipeline failed: {exc}", flush=True)
        else:
            jobs = result.get("jobs", [])
            apps = result.get("applications", [])
            submitted = sum(1 for a in apps if a.get("status") == "applied")
            print(f"  ✓ {len(jobs)} jobs found, {submitted} applications recorded", flush=True)
            if result.get("error"):
                print(f"  ⚠ Pipeline error: {result['error']}", flush=True)
            try:
                send_job_alert_email(query, len(jobs), submitted)
            except Exception as exc:
                logger.warning("Scheduler email failed: %s", exc)

        if max_runs is None or run < max_runs:
            print(f"  Sleeping {interval_minutes} min…", flush=True)
            time.sleep(interval_minutes * 60)

    print(f"\nScheduler finished after {run} run(s).")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="jobhunter-scheduler", description="Scheduled JobHunter pipeline runner")
    parser.add_argument("-q", "--query", required=True, help="Job search query, e.g. 'Python Developer'")
    parser.add_argument("-i", "--interval", type=int, default=360,
                        help="Minutes between runs (default 360 = 6h)")
    parser.add_argument("-r", "--resume", type=str, default=None,
                        help="Path to resume PDF (default: first saved resume)")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without running the pipeline")
    parser.add_argument("--max-runs", type=int, default=None,
                        help="Stop after N runs (default: run forever)")
    args = parser.parse_args(argv)

    if args.interval <= 0:
        print(f"Interval must be positive (got {args.interval}).", file=sys.stderr)
        return 1

    try:
        schedule(
            query=args.query,
            interval_minutes=args.interval,
            resume_pdf=args.resume,
            dry_run=args.dry_run,
            max_runs=args.max_runs,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    raise SystemExit(main())
