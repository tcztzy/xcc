#!/usr/bin/env python3
"""Run a clean CPython configure and make build with XCC as CC."""

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LLC = Path("/opt/homebrew/opt/llvm/bin/llc")


@dataclass(frozen=True)
class BuildOptions:
    cpython_root: Path
    build_dir: Path
    cc: str
    jobs: int
    pythonpath: tuple[Path, ...]
    configure_args: tuple[str, ...]
    make_args: tuple[str, ...]
    skip_configure: bool
    keep_going: bool
    timeout: float | None


@dataclass(frozen=True)
class CommandStep:
    command: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    timeout: float | None


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


RunStep = Callable[[CommandStep], CommandResult]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def detect_default_llc() -> Path | None:
    return DEFAULT_LLC if DEFAULT_LLC.exists() else None


def default_cc() -> str:
    sibling = Path(sys.executable).with_name("xcc")
    if sibling.exists():
        return str(sibling)
    return shutil.which("xcc") or "xcc"


def build_steps(
    options: BuildOptions,
    *,
    base_env: Mapping[str, str] | None = None,
    llc: Path | None = None,
) -> list[CommandStep]:
    env = dict(base_env or os.environ)
    env["CC"] = options.cc
    if options.pythonpath:
        pythonpath = [str(path) for path in options.pythonpath]
        existing_pythonpath = env.get("PYTHONPATH")
        if existing_pythonpath:
            pythonpath.append(existing_pythonpath)
        env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    if llc is not None:
        env["XCC_LLC"] = str(llc)

    steps: list[CommandStep] = []
    if not options.skip_configure:
        steps.append(
            CommandStep(
                (str(options.cpython_root / "configure"), *options.configure_args),
                options.build_dir,
                env,
                options.timeout,
            )
        )

    make_command = ["make", f"-j{options.jobs}"]
    if options.keep_going:
        make_command.append("-k")
    make_command.extend(options.make_args)
    steps.append(CommandStep(tuple(make_command), options.build_dir, env, options.timeout))
    return steps


def run_step(step: CommandStep) -> CommandResult:
    try:
        completed = subprocess.run(
            step.command,
            cwd=step.cwd,
            env=step.env,
            timeout=step.timeout,
            check=False,
        )
    except FileNotFoundError as error:
        return CommandResult(step.command, 127, "", str(error))
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return CommandResult(step.command, 124, stdout, stderr or f"timeout after {step.timeout}s")
    return CommandResult(step.command, completed.returncode, "", "")


def _jobs_default() -> int:
    return max(1, os.cpu_count() or 1)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate XCC against a real CPython configure && make build.",
    )
    parser.add_argument(
        "--cpython",
        type=Path,
        default=_repo_root().parent / "cpython",
        help="CPython source checkout",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=_repo_root() / "build" / "cpython-xcc",
        help="out-of-tree CPython build directory",
    )
    parser.add_argument("--cc", default=default_cc(), help="compiler command assigned to CC")
    parser.add_argument("--jobs", type=int, default=_jobs_default(), help="make parallelism")
    parser.add_argument(
        "--pythonpath",
        type=Path,
        action="append",
        default=[],
        help="prepend a Python import path for the xcc command, for example build/mypyc/lib",
    )
    parser.add_argument("--configure-arg", action="append", default=[], help="extra configure arg")
    parser.add_argument("--make-arg", action="append", default=[], help="extra make arg")
    parser.add_argument("--skip-configure", action="store_true", help="run make only")
    parser.add_argument("--keep-going", action="store_true", help="pass -k to make")
    parser.add_argument("--clean", action="store_true", help="delete the build directory first")
    parser.add_argument("--timeout", type=float, help="timeout per configure/make command")
    parser.add_argument(
        "--llc",
        type=Path,
        help="LLVM llc path to expose through XCC_LLC; defaults to Homebrew llc if present",
    )
    return parser


def _print_result(result: CommandResult) -> None:
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")


def main(argv: Sequence[str] | None = None, *, run_step: RunStep = run_step) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.jobs < 1:
        raise SystemExit("--jobs must be >= 1")

    cpython_root = args.cpython.resolve()
    configure = cpython_root / "configure"
    if not configure.exists():
        raise SystemExit(f"{configure} does not exist")

    build_dir = args.build_dir.resolve()
    if args.clean and build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    llc = args.llc if args.llc is not None else detect_default_llc()
    options = BuildOptions(
        cpython_root=cpython_root,
        build_dir=build_dir,
        cc=args.cc,
        jobs=args.jobs,
        pythonpath=tuple(path.resolve() for path in args.pythonpath),
        configure_args=tuple(args.configure_arg),
        make_args=tuple(args.make_arg),
        skip_configure=args.skip_configure,
        keep_going=args.keep_going,
        timeout=args.timeout,
    )

    for step in build_steps(options, llc=llc):
        print("running:", " ".join(step.command))
        result = run_step(step)
        _print_result(result)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
