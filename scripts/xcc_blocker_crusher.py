#!/usr/bin/env python3
"""Deterministic cron runner for CPython trial blocker crushing."""

import argparse
import hashlib
import os
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SEMA_PATH = ROOT / "src/xcc/sema.py"

FAILURE_LINE_RE = re.compile(r"^FAIL \[(?P<stage>[^\]]+)\] (?P<case>[^:]+): (?P<message>.+)$")
UNDECLARED_FUNCTION_RE = re.compile(r"^Undeclared function: `(?P<name>[^`]+)`$")

DEFAULT_TRIAL_COMMAND = (sys.executable, "scripts/cpython_trial.py")
DEFAULT_VERIFY_COMMAND = ("tox", "-q")
DEFAULT_STASH_MESSAGE = "xcc-blocker-crusher:auto-stash"

EXPECT_BUILTIN_SNIPPET = """        self._function_signatures["__builtin_expect"] = FunctionSignature(
            return_type=LONG, params=(LONG, LONG), is_variadic=False
        )
"""
UNREACHABLE_BUILTIN_SNIPPET = """        self._function_signatures["__builtin_unreachable"] = FunctionSignature(
            return_type=VOID, params=(), is_variadic=False
        )
"""


class RunnerError(RuntimeError):
    """Raised when the blocker crusher cannot complete safely."""


@dataclass(frozen=True)
class TrialFailure:
    stage: str
    case_name: str
    message: str


@dataclass(frozen=True)
class BlockerRule:
    code: str
    stage: str
    pattern: re.Pattern[str]
    summary: str


@dataclass(frozen=True)
class BlockerBucket:
    code: str
    stage: str
    count: int
    messages: tuple[str, ...]
    cases: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class FixResult:
    summary: str
    changed_paths: tuple[Path, ...]


BLOCKER_RULES = (
    BlockerRule(
        code="B001",
        stage="parse",
        pattern=re.compile(r"Expected `;`"),
        summary="Expected ';' in declaration/expression parsing",
    ),
    BlockerRule(
        code="B002",
        stage="parse",
        pattern=re.compile(r"Expected identifier before `;`"),
        summary="Anonymous/implicit declarator parsing requires identifier support",
    ),
    BlockerRule(
        code="B003",
        stage="parse",
        pattern=re.compile(r"Unknown declaration type name: `__attribute__`"),
        summary="GNU attribute declaration handling is incomplete",
    ),
    BlockerRule(
        code="B004",
        stage="parse",
        pattern=re.compile(r"Array size is required in this context"),
        summary="Flexible/unsized array declarator parsing is incomplete",
    ),
    BlockerRule(
        code="B005",
        stage="parse",
        pattern=re.compile(r"Expected `]`"),
        summary="Array designator/declarator bracket parsing is incomplete",
    ),
    BlockerRule(
        code="B006",
        stage="parse",
        pattern=re.compile(r"Expression cannot start with keyword `struct`: expected an operand"),
        summary="Type-name operands in expression context are incomplete",
    ),
    BlockerRule(
        code="B007",
        stage="parse",
        pattern=re.compile(r"Unknown declaration type name: `a`"),
        summary="K&R-style declaration parsing is incomplete",
    ),
    BlockerRule(
        code="B008",
        stage="parse",
        pattern=re.compile(r"Array size must be positive"),
        summary="GNU zero-length array handling is incomplete",
    ),
    BlockerRule(
        code="B009",
        stage="parse",
        pattern=re.compile(r"Expected member declaration"),
        summary="Empty/extension struct member parsing is incomplete",
    ),
    BlockerRule(
        code="B010",
        stage="sema",
        pattern=re.compile(r"Initializer index out of range"),
        summary="GNU label/designated initializer index semantics are incomplete",
    ),
    BlockerRule(
        code="B011",
        stage="sema",
        pattern=re.compile(r"Duplicate declaration: `py_counter`"),
        summary="Extern-to-definition merge logic for globals is incomplete",
    ),
    BlockerRule(
        code="B012",
        stage="sema",
        pattern=re.compile(r"Duplicate declaration: `tls_counter`"),
        summary="Thread-local extern merge logic is incomplete",
    ),
    BlockerRule(
        code="B013",
        stage="sema",
        pattern=re.compile(r"Duplicate definition: `struct _object`"),
        summary="Struct tag definition merge rules are incomplete",
    ),
    BlockerRule(
        code="B014",
        stage="sema",
        pattern=re.compile(r"Undeclared function: `WRAP`"),
        summary="Macro-expanded identifier handling in sema is incomplete",
    ),
    BlockerRule(
        code="B015",
        stage="sema",
        pattern=re.compile(r"Undeclared function: `__builtin_expect`"),
        summary="GNU builtin registration is missing __builtin_expect",
    ),
    BlockerRule(
        code="B016",
        stage="sema",
        pattern=re.compile(r"Undeclared function: `__builtin_unreachable`"),
        summary="GNU builtin registration is missing __builtin_unreachable",
    ),
    BlockerRule(
        code="B017",
        stage="sema",
        pattern=re.compile(r"Variable length array not allowed at file scope"),
        summary="File-scope initializer VLA evaluation needs tightening",
    ),
)

BLOCKER_SUMMARY_BY_CODE = {rule.code: rule.summary for rule in BLOCKER_RULES}


def _format_command(command: tuple[str, ...] | list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _merge_output(stdout: str | None, stderr: str | None) -> str:
    chunks = [part for part in (stdout, stderr) if part]
    return "\n".join(chunks).strip()


def _run_command(
    command: tuple[str, ...] | list[str],
    *,
    capture_output: bool = False,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=ROOT,
            text=True,
            capture_output=capture_output,
            env=env,
            check=check,
        )
    except FileNotFoundError as error:
        raise RunnerError(f"Required command is not available: {_format_command(command)}") from error
    except subprocess.CalledProcessError as error:
        output = _merge_output(error.stdout, error.stderr)
        if output:
            raise RunnerError(f"Command failed: {_format_command(command)}\n{output}") from error
        raise RunnerError(f"Command failed: {_format_command(command)}") from error


def _run_git(*args: str, capture_output: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run_command(("git", *args), capture_output=capture_output, check=check)


def _git_status_lines() -> list[str]:
    completed = _run_git("status", "--porcelain", "--untracked-files=all", capture_output=True)
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _ensure_clean_git_state(policy: str) -> str | None:
    status_lines = _git_status_lines()
    if not status_lines:
        return None
    if policy == "fail":
        preview = "\n".join(status_lines[:10])
        raise RunnerError(
            "Working tree is not clean. Commit/stash changes or rerun with "
            f"'--dirty-policy stash'.\n{preview}"
        )
    completed = _run_git(
        "stash",
        "push",
        "--include-untracked",
        "--message",
        DEFAULT_STASH_MESSAGE,
        capture_output=True,
    )
    return completed.stdout.strip() or DEFAULT_STASH_MESSAGE


def _trial_env() -> dict[str, str]:
    env = dict(os.environ)
    src = str(ROOT / "src")
    current = env.get("PYTHONPATH")
    if current:
        paths = current.split(os.pathsep)
        if src not in paths:
            env["PYTHONPATH"] = os.pathsep.join([src, *paths])
    else:
        env["PYTHONPATH"] = src
    return env


def _print_trial_output(output: str, failures: list[TrialFailure]) -> None:
    if failures:
        print(output, end="" if output.endswith("\n") else "\n")
        return
    marker = "CPython Frontend Trial Summary"
    index = output.find(marker)
    if index >= 0:
        summary = output[index:].strip()
        if summary:
            print(summary)
        return
    if output.strip():
        print(output.strip())


def _parse_failures(output: str) -> list[TrialFailure]:
    failures: list[TrialFailure] = []
    for line in output.splitlines():
        match = FAILURE_LINE_RE.match(line.strip())
        if match is None:
            continue
        failures.append(
            TrialFailure(
                stage=match.group("stage"),
                case_name=match.group("case"),
                message=" ".join(match.group("message").split()),
            )
        )
    return failures


def _run_trial(command: tuple[str, ...]) -> list[TrialFailure]:
    completed = _run_command(command, capture_output=True, env=_trial_env(), check=False)
    output = _merge_output(completed.stdout, completed.stderr)
    failures = _parse_failures(output)
    _print_trial_output(output, failures)
    if completed.returncode != 0:
        raise RunnerError(
            "scripts/cpython_trial.py failed "
            f"(exit code {completed.returncode}).\n{output}"
        )
    return failures


def _classify_failure(failure: TrialFailure) -> str:
    for rule in BLOCKER_RULES:
        if failure.stage != rule.stage:
            continue
        if rule.pattern.fullmatch(failure.message):
            return rule.code
    digest = hashlib.sha1(f"{failure.stage}:{failure.message}".encode("utf-8")).hexdigest()[:8].upper()
    return f"BX_{failure.stage.upper()}_{digest}"


def _build_blocker_buckets(failures: list[TrialFailure]) -> list[BlockerBucket]:
    grouped: dict[str, list[TrialFailure]] = defaultdict(list)
    for failure in failures:
        grouped[_classify_failure(failure)].append(failure)
    buckets: list[BlockerBucket] = []
    for code, entries in grouped.items():
        stage = entries[0].stage
        messages = tuple(sorted({entry.message for entry in entries}))
        cases = tuple(sorted(entry.case_name for entry in entries))
        summary = BLOCKER_SUMMARY_BY_CODE.get(code, messages[0])
        buckets.append(
            BlockerBucket(
                code=code,
                stage=stage,
                count=len(entries),
                messages=messages,
                cases=cases,
                summary=summary,
            )
        )
    return sorted(
        buckets,
        key=lambda item: (
            -item.count,
            item.code,
            item.stage,
            item.messages[0] if item.messages else "",
        ),
    )


def _print_blocker_summary(buckets: list[BlockerBucket]) -> None:
    print("Detected blocker buckets:")
    for bucket in buckets:
        examples = ", ".join(bucket.cases[:3])
        print(f"- {bucket.code} [{bucket.stage}] x{bucket.count}: {bucket.summary} (examples: {examples})")


def _patch_gcc_builtin_registration(builtin_name: str, snippet: str) -> bool:
    source = SEMA_PATH.read_text(encoding="utf-8")
    start = source.find("    def _register_gcc_builtins(self) -> None:\n")
    if start < 0:
        raise RunnerError(f"Could not locate _register_gcc_builtins in {SEMA_PATH}")
    end = source.find("\n    def analyze(", start)
    if end < 0:
        raise RunnerError(f"Could not locate _register_gcc_builtins end in {SEMA_PATH}")
    block = source[start:end]
    if f'"{builtin_name}"' in block:
        return False
    SEMA_PATH.write_text(source[:end] + snippet + source[end:], encoding="utf-8")
    return True


def _apply_builtin_fix(bucket: BlockerBucket, *, builtin_name: str, snippet: str) -> FixResult:
    declared: set[str] = set()
    for message in bucket.messages:
        match = UNDECLARED_FUNCTION_RE.fullmatch(message)
        if match is None:
            raise RunnerError(
                f"Blocker {bucket.code} does not match undeclared-function diagnostic: {message}"
            )
        declared.add(match.group("name"))
    if declared != {builtin_name}:
        names = ", ".join(sorted(declared))
        raise RunnerError(
            f"Blocker {bucket.code} expected only {builtin_name}, but saw undeclared function(s): {names}"
        )
    if not _patch_gcc_builtin_registration(builtin_name, snippet):
        raise RunnerError(
            f"Builtin {builtin_name} is already registered in gnu11 sema; no deterministic patch to apply."
        )
    return FixResult(
        summary=f"Registered missing GNU builtin signature for {builtin_name}",
        changed_paths=(SEMA_PATH,),
    )


def _fix_b015(bucket: BlockerBucket) -> FixResult:
    return _apply_builtin_fix(bucket, builtin_name="__builtin_expect", snippet=EXPECT_BUILTIN_SNIPPET)


def _fix_b016(bucket: BlockerBucket) -> FixResult:
    return _apply_builtin_fix(
        bucket,
        builtin_name="__builtin_unreachable",
        snippet=UNREACHABLE_BUILTIN_SNIPPET,
    )


FIXER = Callable[[BlockerBucket], FixResult]
FIXERS: dict[str, FIXER] = {
    "B015": _fix_b015,
    "B016": _fix_b016,
}


def _apply_fix(bucket: BlockerBucket) -> FixResult:
    fixer = FIXERS.get(bucket.code)
    if fixer is None:
        raise RunnerError(
            f"No deterministic fixer is registered for blocker {bucket.code}. "
            "Add a dedicated fixer before running this blocker in cron mode."
        )
    return fixer(bucket)


def _run_verification(command: tuple[str, ...]) -> None:
    try:
        _run_command(command)
    except RunnerError as error:
        if command != DEFAULT_VERIFY_COMMAND or "not available" not in str(error):
            raise
        fallback = (sys.executable, "-m", "tox", "-q")
        print(f"verify command fallback: {_format_command(fallback)}")
        _run_command(fallback)


def _rollback_worktree() -> None:
    _run_git("reset", "--hard", "HEAD")


def _has_worktree_changes() -> bool:
    return bool(_git_status_lines())


def _commit_changes(message: str) -> None:
    if not _has_worktree_changes():
        raise RunnerError("No local changes were produced; refusing to create an empty commit.")
    _run_git("add", "-A")
    _run_git("commit", "-m", message)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deterministic cron runner: trial -> classify -> fix -> verify -> commit."
    )
    parser.add_argument(
        "--dirty-policy",
        choices=("fail", "stash"),
        default="fail",
        help="How to handle a dirty working tree before running (default: fail).",
    )
    parser.add_argument(
        "--trial-command",
        nargs="+",
        default=list(DEFAULT_TRIAL_COMMAND),
        help="Command used to run scripts/cpython_trial.py.",
    )
    parser.add_argument(
        "--verify-command",
        nargs="+",
        default=list(DEFAULT_VERIFY_COMMAND),
        help="Command used to run project verification checks.",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Apply fix and run verification, but do not create a commit.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    trial_command = tuple(args.trial_command)
    verify_command = tuple(args.verify_command)

    stash_note = _ensure_clean_git_state(args.dirty_policy)
    if stash_note:
        print(f"Stashed local changes: {stash_note}")

    failures = _run_trial(trial_command)
    if not failures:
        print("No CPython trial failures were detected.")
        _run_verification(verify_command)
        print("Verification passed; no blocker fix required.")
        return 0

    buckets = _build_blocker_buckets(failures)
    _print_blocker_summary(buckets)
    top = buckets[0]
    examples = ", ".join(top.cases[:3])
    print(f"Top blocker: {top.code} [{top.stage}] x{top.count} (examples: {examples})")

    fix_applied = False
    try:
        fix_result = _apply_fix(top)
        fix_applied = True
        print(f"Applied fix: {fix_result.summary}")
        _run_verification(verify_command)
    except RunnerError:
        if fix_applied and _has_worktree_changes():
            print("Verification failed after applying a fix; rolling back local changes.")
            _rollback_worktree()
        raise

    if args.no_commit:
        print("Skipping commit because --no-commit was provided.")
        return 0

    case_suffix = "case" if top.count == 1 else "cases"
    commit_message = f"cron: fix {top.code} ({top.count} trial {case_suffix})"
    _commit_changes(commit_message)
    print(f"Committed: {commit_message}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunnerError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
