"""OpenClaw cron smoke check entrypoint for milestone validation."""

import argparse
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

EXIT_OK: Final[int] = 0
EXIT_FAIL: Final[int] = 1
EXIT_TIMEOUT: Final[int] = 2
DEFAULT_TIMEOUT_SECONDS: Final[int] = 900
DEFAULT_MAX_LOG_LINES: Final[int] = 20


@dataclass(frozen=True)
class SmokeCheck:
    name: str
    cwd: Path
    command: tuple[str, ...]
    extra_env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SmokeResult:
    check: SmokeCheck
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float
    timed_out: bool


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def select_smoke_check(repo_root: Path, cpython_dir: Path | None = None) -> SmokeCheck:
    candidates: list[Path] = []
    if cpython_dir is not None:
        candidates.append(cpython_dir)
    candidates.extend((repo_root / "cpython", repo_root.parent / "cpython"))
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if (resolved / "configure").is_file():
            build_dir = (repo_root / ".openclaw" / "cpython-build").resolve()
            build_dir.mkdir(parents=True, exist_ok=True)
            return SmokeCheck(
                name="cpython-configure",
                cwd=build_dir,
                command=(str(resolved / "configure"),),
                extra_env=(("CC", "xcc"),),
            )
    return SmokeCheck(
        name="xcc-tests",
        cwd=repo_root,
        command=(sys.executable, "-m", "unittest", "discover", "-v"),
    )


def _coerce_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def run_smoke_check(check: SmokeCheck, *, timeout_seconds: int) -> SmokeResult:
    env = os.environ.copy()
    env.update(dict(check.extra_env))
    start = time.monotonic()
    try:
        completed = subprocess.run(
            check.command,
            cwd=check.cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        return SmokeResult(
            check=check,
            returncode=None,
            stdout=_coerce_output(error.stdout),
            stderr=_coerce_output(error.stderr),
            elapsed_seconds=time.monotonic() - start,
            timed_out=True,
        )
    return SmokeResult(
        check=check,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        elapsed_seconds=time.monotonic() - start,
        timed_out=False,
    )


def result_exit_code(result: SmokeResult) -> int:
    if result.timed_out:
        return EXIT_TIMEOUT
    if result.returncode == 0:
        return EXIT_OK
    return EXIT_FAIL


def _tail_non_empty_lines(text: str, max_log_lines: int) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return "<empty>"
    return "\n".join(lines[-max_log_lines:])


def format_report(result: SmokeResult, *, max_log_lines: int = DEFAULT_MAX_LOG_LINES) -> str:
    exit_code = result_exit_code(result)
    status = "ok" if exit_code == EXIT_OK else "fail"
    report_lines = [
        f"openclaw-smoke: {status} ({result.check.name})",
        f"exit={exit_code} elapsed={result.elapsed_seconds:.2f}s",
        f"cwd={result.check.cwd}",
        f"cmd={shlex.join(result.check.command)}",
    ]
    if result.check.extra_env:
        exports = " ".join(f"{key}={value}" for key, value in result.check.extra_env)
        report_lines.append(f"env={exports}")
    if result.timed_out:
        report_lines.append("reason=timeout")
    report_lines.extend(
        [
            "stdout:",
            _tail_non_empty_lines(result.stdout, max_log_lines),
            "stderr:",
            _tail_non_empty_lines(result.stderr, max_log_lines),
        ]
    )
    return "\n".join(report_lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the OpenClaw smoke check for the current xcc milestone."
    )
    parser.add_argument(
        "--repo-root",
        default=str(_default_repo_root()),
        help="repository root used for fallback test execution",
    )
    parser.add_argument(
        "--cpython-dir",
        default=None,
        help="optional CPython source checkout containing ./configure",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="timeout per smoke command",
    )
    parser.add_argument(
        "--max-log-lines",
        type=int,
        default=DEFAULT_MAX_LOG_LINES,
        help="number of non-empty stdout/stderr lines shown in the report",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    cpython_dir = Path(args.cpython_dir).expanduser() if args.cpython_dir else None
    check = select_smoke_check(Path(args.repo_root).expanduser().resolve(), cpython_dir)
    result = run_smoke_check(check, timeout_seconds=args.timeout_seconds)
    print(format_report(result, max_log_lines=args.max_log_lines))
    return result_exit_code(result)
