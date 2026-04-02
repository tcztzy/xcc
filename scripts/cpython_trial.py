#!/usr/bin/env python3
"""Run the CPython integration gate as a single compile-only verdict."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xcc.cpython_harness import (
    CPythonTrialSummary,
    bucket_location,
    summarize_trial_results,
    top_failure_bucket,
    trial_gate_verdict,
)

import cpython_file_trial


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the pinned CPython compile-only integration gate."
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=cpython_file_trial.DEFAULT_CACHE_DIR,
        help="cache directory for the pinned CPython archive",
    )
    parser.add_argument(
        "--archive-path",
        type=Path,
        default=None,
        help="use this local archive instead of the pinned download URL",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="run only the named case path (repeatable)",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="list the curated case paths and exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print all blocker buckets instead of only the top blocker",
    )
    parser.add_argument(
        "--emit-failure-lines",
        action="store_true",
        help="emit machine-readable failure lines for internal tooling",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return a failing exit status when the integration gate is not green",
    )
    return parser.parse_args()


def _print_gate_report(
    *,
    summary: CPythonTrialSummary,
    verbose: bool,
) -> None:
    verdict = trial_gate_verdict(summary)
    print("CPython Integration Gate")
    print(f"Pinned archive: {cpython_file_trial.ARCHIVE_NAME}")
    print(f"Curated file set: {summary.total} translation units")
    print(f"Passed files: {summary.passed}")
    print(f"Failed files: {summary.failed}")
    print(f"Verdict: {verdict.upper()}")

    top_bucket = top_failure_bucket(summary)
    if top_bucket is None:
        print("Top blocker: none")
        return

    examples = ", ".join(top_bucket.case_paths[:3])
    print(
        f"Top blocker: {top_bucket.code} [{top_bucket.stage}] x{top_bucket.count}"
    )
    print(f"Location: {bucket_location(top_bucket)}")
    print(f"Message: {top_bucket.detail}")
    print(f"Affected cases: {examples}")

    if not verbose:
        return

    print("All blocker buckets:")
    for bucket in summary.buckets:
        affected = ", ".join(bucket.case_paths[:3])
        print(
            f"- {bucket.code} [{bucket.stage}] x{bucket.count}: "
            f"{bucket.detail} @ {bucket_location(bucket)} ({affected})"
        )


def main() -> int:
    args = _parse_args()
    cases = cpython_file_trial.select_cases(tuple(args.case))
    if args.list_cases:
        for case in cases:
            print(case.path)
        return 0

    results = cpython_file_trial.run_curated_trial(
        cache_dir=args.cache_dir,
        archive_path_override=args.archive_path,
        cases=cases,
    )
    if args.emit_failure_lines:
        for result in results:
            if result.ok:
                continue
            print(f"FAIL [{result.stage}] {result.path}: {result.detail}")

    summary = summarize_trial_results(results)
    _print_gate_report(summary=summary, verbose=args.verbose)
    if args.strict and summary.failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
