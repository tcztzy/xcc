#!/usr/bin/env python3
"""Run XCC correctness and boundary validation checks."""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

XCC_RUNNER = "import sys; from xcc import main; raise SystemExit(main(sys.argv[1:]))"


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ProgramCase:
    name: str
    source: str
    xcc_args: tuple[str, ...] = ()
    clang_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class BoundaryCase:
    name: str
    xcc_args: tuple[str, ...]
    source: str
    stderr_contains: str


@dataclass(frozen=True)
class ValidationResult:
    kind: str
    name: str
    status: str
    details: str


PROGRAM_CASES = (
    ProgramCase(
        "arithmetic-and-control-flow",
        """
int add(int a, int b) { return a + b; }
int main(void)
{
  int total = 0;
  for (int i = 0; i < 5; i = i + 1)
    total = add(total, i);
  return total == 10 ? 0 : 1;
}
""",
    ),
    ProgramCase(
        "pointer-array-scaling",
        """
int main(void)
{
  int values[3] = { 1, 2, 3 };
  int *p = values;
  p[1] = 7;
  return values[0] + values[1] + values[2] == 11 ? 0 : 1;
}
""",
    ),
    ProgramCase(
        "unsigned-char-promotion",
        """
struct Box { unsigned char byte; int guard; };
int main(void)
{
  struct Box box = { 250, 1 };
  return box.byte == 250 && (int)box.byte > 0 ? 0 : 1;
}
""",
    ),
)


BOUNDARY_CASES = (
    BoundaryCase(
        "c11-rejects-gnu-alignof-expression",
        ("--target=llvm", "-std=c11", "-S"),
        "int f(void){int x; return _Alignof(x);}",
        "Invalid alignof operand",
    ),
    BoundaryCase(
        "removed-backend-option-rejected",
        ("--backend=clang",),
        "int main(void){return 0;}",
        "--backend has been removed",
    ),
    BoundaryCase(
        "unsupported-target-rejected",
        ("--target=not-a-target",),
        "int main(void){return 0;}",
        "Unsupported target",
    ),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_xcc_command() -> tuple[str, ...]:
    return (sys.executable, "-c", XCC_RUNNER)


def _split_command(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    command = tuple(shlex.split(value))
    if not command:
        raise SystemExit("empty command")
    return command


def _validation_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    src = str(_repo_root() / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing
    return env


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            tuple(command),
            cwd=cwd,
            env=None if env is None else dict(env),
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        return CommandResult(tuple(command), 127, "", str(error))
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return CommandResult(tuple(command), 124, stdout, stderr or f"timeout after {timeout}s")
    return CommandResult(tuple(command), completed.returncode, completed.stdout, completed.stderr)


def _case_dir(work_root: Path, name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)
    path = work_root / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _format_command(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _run_program_case(
    case: ProgramCase,
    *,
    work_root: Path,
    xcc_command: tuple[str, ...],
    clang_command: tuple[str, ...],
    run: Callable[..., CommandResult] = _run_command,
    timeout: float,
    env: Mapping[str, str],
) -> ValidationResult:
    root = _case_dir(work_root, case.name)
    source = root / "case.c"
    xcc_exe = root / "xcc.out"
    clang_exe = root / "clang.out"
    source.write_text(case.source.strip() + "\n", encoding="utf-8")

    xcc_compile = run(
        (*xcc_command, "--target=llvm", *case.xcc_args, str(source), "-o", str(xcc_exe)),
        cwd=root,
        env=env,
        timeout=timeout,
    )
    if xcc_compile.returncode != 0:
        return ValidationResult(
            "program",
            case.name,
            "fail",
            f"xcc compile failed rc={xcc_compile.returncode}: {xcc_compile.stderr.strip()}",
        )

    clang_compile = run(
        (*clang_command, *case.clang_args, str(source), "-o", str(clang_exe)),
        cwd=root,
        env=env,
        timeout=timeout,
    )
    if clang_compile.returncode != 0:
        return ValidationResult(
            "program",
            case.name,
            "fail",
            f"clang compile failed rc={clang_compile.returncode}: {clang_compile.stderr.strip()}",
        )

    xcc_run = run((str(xcc_exe),), cwd=root, env=env, timeout=timeout)
    clang_run = run((str(clang_exe),), cwd=root, env=env, timeout=timeout)
    xcc_observed = (xcc_run.returncode, xcc_run.stdout, xcc_run.stderr)
    clang_observed = (clang_run.returncode, clang_run.stdout, clang_run.stderr)
    if xcc_observed != clang_observed:
        return ValidationResult(
            "program",
            case.name,
            "fail",
            "xcc "
            f"rc={xcc_run.returncode} stdout={xcc_run.stdout!r} stderr={xcc_run.stderr!r}; "
            "clang "
            f"rc={clang_run.returncode} stdout={clang_run.stdout!r} stderr={clang_run.stderr!r}",
        )
    return ValidationResult(
        "program",
        case.name,
        "ok",
        f"returncode={xcc_run.returncode} stdout={xcc_run.stdout!r} stderr={xcc_run.stderr!r}",
    )


def _run_boundary_case(
    case: BoundaryCase,
    *,
    work_root: Path,
    xcc_command: tuple[str, ...],
    run: Callable[..., CommandResult] = _run_command,
    timeout: float,
    env: Mapping[str, str],
) -> ValidationResult:
    root = _case_dir(work_root, case.name)
    source = root / "case.c"
    source.write_text(case.source.strip() + "\n", encoding="utf-8")

    result = run(
        (*xcc_command, *case.xcc_args, str(source)),
        cwd=root,
        env=env,
        timeout=timeout,
    )
    if result.returncode == 0:
        return ValidationResult("boundary", case.name, "fail", "accepted invalid input")
    if case.stderr_contains not in result.stderr:
        return ValidationResult(
            "boundary",
            case.name,
            "fail",
            f"stderr did not contain {case.stderr_contains!r}: {result.stderr!r}",
        )
    return ValidationResult(
        "boundary",
        case.name,
        "ok",
        f"rejected with rc={result.returncode} stderr={result.stderr.strip()!r}",
    )


def _clang_available(clang_command: tuple[str, ...]) -> bool:
    first = clang_command[0]
    return Path(first).exists() or shutil.which(first) is not None


def run_validation(
    *,
    xcc_command: tuple[str, ...],
    clang_command: tuple[str, ...],
    timeout: float,
    work_root: Path,
    keep_work: bool,
    env: Mapping[str, str] | None = None,
) -> list[ValidationResult]:
    effective_env = _validation_env(env)
    results: list[ValidationResult] = []

    if _clang_available(clang_command):
        for case in PROGRAM_CASES:
            results.append(
                _run_program_case(
                    case,
                    work_root=work_root,
                    xcc_command=xcc_command,
                    clang_command=clang_command,
                    timeout=timeout,
                    env=effective_env,
                )
            )
    else:
        for case in PROGRAM_CASES:
            results.append(
                ValidationResult(
                    "program",
                    case.name,
                    "skip",
                    f"clang command not found: {_format_command(clang_command)}",
                )
            )

    for case in BOUNDARY_CASES:
        results.append(
            _run_boundary_case(
                case,
                work_root=work_root,
                xcc_command=xcc_command,
                timeout=timeout,
                env=effective_env,
            )
        )

    if keep_work:
        results.append(ValidationResult("workdir", str(work_root), "ok", "kept validation files"))
    return results


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that XCC preserves C program behavior against clang and rejects "
            "inputs outside its driver/frontend contract."
        )
    )
    parser.add_argument(
        "--xcc-command",
        help="command used to run xcc; default imports xcc from this source tree",
    )
    parser.add_argument("--clang-command", default="clang", help="reference C compiler command")
    parser.add_argument("--timeout", type=float, default=20.0, help="seconds per subprocess")
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="directory for generated validation files; defaults to a temporary directory",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="keep generated validation files instead of deleting the temporary directory",
    )
    return parser


def _print_results(results: Sequence[ValidationResult]) -> None:
    for result in results:
        print(f"{result.status.upper()} {result.kind}:{result.name} {result.details}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    xcc_command = _split_command(args.xcc_command, _default_xcc_command())
    clang_command = _split_command(args.clang_command, ("clang",))

    if args.work_dir is not None:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        results = run_validation(
            xcc_command=xcc_command,
            clang_command=clang_command,
            timeout=args.timeout,
            work_root=args.work_dir,
            keep_work=args.keep_work,
        )
        _print_results(results)
        return 1 if any(result.status == "fail" for result in results) else 0

    if args.keep_work:
        work_root = Path(tempfile.mkdtemp(prefix="xcc-validate-"))
        work_root.mkdir(parents=True, exist_ok=True)
        results = run_validation(
            xcc_command=xcc_command,
            clang_command=clang_command,
            timeout=args.timeout,
            work_root=work_root,
            keep_work=args.keep_work,
        )
        _print_results(results)
        return 1 if any(result.status == "fail" for result in results) else 0

    with tempfile.TemporaryDirectory() as tmp:
        work_root = Path(tmp)
        results = run_validation(
            xcc_command=xcc_command,
            clang_command=clang_command,
            timeout=args.timeout,
            work_root=work_root,
            keep_work=False,
        )
        _print_results(results)
        return 1 if any(result.status == "fail" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
