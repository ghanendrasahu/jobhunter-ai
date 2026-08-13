"""JobHunter AI — Auto-apply CLI.

Runs the semi-autonomous application agent from the terminal.

Examples:
    python -m jobhunter.automation.apply --query "Python Developer" --resume resume.pdf
    python -m jobhunter.automation.apply -q "Data Analyst" -r resume.pdf --mode auto --portals indeed --max 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jobhunter.automation import run_application_pipeline
from jobhunter.config import warn_missing_keys
from jobhunter.domains.resume import extract_text_from_pdf


def _status_line(level: str, stage: str, message: str) -> None:
    icon = {"error": "✖", "warning": "!", "info": "•"}.get(level, "•")
    print(f"[{icon}] {stage}: {message}", flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="jobhunter-apply", description="JobHunter AI auto-apply agent")
    parser.add_argument("-q", "--query", required=True, help="Job search query, e.g. 'Python Developer'")
    parser.add_argument("-r", "--resume", required=True, type=Path, help="Path to resume PDF")
    parser.add_argument("--mode", choices=["human", "auto", "off"], default=None,
                        help="human=pre-fill only (default), auto=submit automatically, off=disabled")
    parser.add_argument("--portals", nargs="*", default=None, help="Portals to use (naukri, indeed)")
    parser.add_argument("--max", type=int, default=None, help="Max applications per cycle")
    parser.add_argument("--roles", nargs="*", default=None,
                        help="Priority role titles to search (e.g. 'Data Scientist' 'Data Analyst')")
    parser.add_argument("--continuous", action="store_true",
                        help="Keep running cycles until Ctrl+C instead of a single batch")
    parser.add_argument("--cooldown", type=int, default=None,
                        help="Seconds between cycles in continuous mode (default: from settings)")
    parser.add_argument("--batch", type=int, default=None,
                        help="Applications per cycle (default: from settings)")
    parser.add_argument("--no-remote", action="store_true", help="Don't prioritize work-from-home roles")
    args = parser.parse_args(argv)

    warn_missing_keys("JobHunter apply")

    if not args.resume.exists():
        print(f"Resume not found: {args.resume}", file=sys.stderr)
        return 1

    resume_text = extract_text_from_pdf(str(args.resume))
    print(f"Resume parsed: {len(resume_text)} characters", flush=True)

    result = run_application_pipeline(
        query=args.query,
        resume_text=resume_text,
        resume_pdf=str(args.resume),
        portals=args.portals,
        mode=args.mode,
        max_applications=args.max,
        on_status=_status_line,
        roles=args.roles,
        continuous=args.continuous,
        cooldown_seconds=args.cooldown,
        batch_size=args.batch,
        prioritize_remote=not args.no_remote,
    )

    print("\n=== Results ===")
    if not result["results"]:
        print("No applications attempted. See log above.")
    print(f"Cycles: {result.get('cycles', 1)}")
    for item in result["results"]:
        score = item.get("evaluation", {}).get("score")
        print(f"- {item.get('status')}: {item.get('title')} @ {item.get('company')} "
              f"(score {score}%) — {item.get('detail')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
