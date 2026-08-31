#!/usr/bin/env python3
"""Run XCC unittest modules in parallel, with optional combined coverage."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class ModuleResult:
    module: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    elapsed: float
    timed_out: bool = False


RunCommand = Callable[..., CommandResult]

_COVERAGE_SKIP_NATIVE_BOOTSTRAP = "XCC_SKIP_NATIVE_BOOTSTRAP_TESTS"
_COVERAGE_DETACHED_TESTS = {
    "tests.test_aot_bootstrap": ("tests.test_aot_bootstrap.AotBootstrapNativeBuildTests",),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def discover_test_modules(
    *,
    root: Path,
    start_dir: Path,
    pattern: str = "test*.py",
) -> list[str]:
    root = root.resolve()
    start_dir = start_dir.resolve()
    modules: list[str] = []
    for path in sorted(start_dir.rglob(pattern)):
        if path.name == "__init__.py":
            continue
        relative = path.with_suffix("").relative_to(root)
        modules.append(".".join(relative.parts))
    return modules


def _path_to_module(root: Path, value: str) -> str:
    if not value.endswith(".py"):
        return value
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return ".".join(path.resolve().with_suffix("").relative_to(root.resolve()).parts)


def build_module_command(
    *,
    module: str,
    use_coverage: bool,
    verbose: bool,
) -> list[str]:
    if use_coverage:
        command = [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--parallel-mode",
            "-m",
            "unittest",
        ]
    else:
        command = [sys.executable, "-m", "unittest"]
    if verbose:
        command.append("-v")
    command.append(module)
    return command


def coverage_erase_command() -> list[str]:
    return [sys.executable, "-m", "coverage", "erase"]


def coverage_combine_command() -> list[str]:
    return [sys.executable, "-m", "coverage", "combine"]


def coverage_report_command() -> list[str]:
    return [sys.executable, "-m", "coverage", "report"]


def coverage_detached_tests(modules: Sequence[str]) -> list[str]:
    detached: list[str] = []
    for module in modules:
        for target in _COVERAGE_DETACHED_TESTS.get(module, ()):
            if target not in detached:
                detached.append(target)
    return detached


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            tuple(command),
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        stdout = _output_text(error.stdout)
        stderr = _output_text(error.stderr)
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += f"test command timed out after {timeout:g}s\n"
        return CommandResult(tuple(command), 124, stdout, stderr, timed_out=True)
    return CommandResult(
        tuple(command),
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )


def _output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _env_with_pythonpath(
    *,
    root: Path,
    pythonpaths: Sequence[Path],
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(base or os.environ)
    paths = [str(path) for path in pythonpaths]
    paths.append(str(root / "src"))
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _run_module(
    module: str,
    *,
    root: Path,
    use_coverage: bool,
    pythonpaths: Sequence[Path],
    verbose: bool,
    run_command: RunCommand,
    base_env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> ModuleResult:
    command = build_module_command(module=module, use_coverage=use_coverage, verbose=verbose)
    env = _env_with_pythonpath(root=root, pythonpaths=pythonpaths, base=base_env)
    started = time.perf_counter()
    if timeout is None:
        result = run_command(command, cwd=root, env=env)
    else:
        result = run_command(command, cwd=root, env=env, timeout=timeout)
    elapsed = time.perf_counter() - started
    return ModuleResult(
        module,
        result.command,
        result.returncode,
        result.stdout,
        result.stderr,
        elapsed,
        result.timed_out,
    )


def run_modules(
    *,
    modules: Sequence[str],
    jobs: int,
    use_coverage: bool,
    pythonpath: Path | None,
    verbose: bool,
    root: Path,
    base_env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    run_command: RunCommand = _run_command,
) -> list[ModuleResult]:
    pythonpaths = () if pythonpath is None else (pythonpath,)
    if jobs == 1:
        return [
            _run_module(
                module,
                root=root,
                use_coverage=use_coverage,
                pythonpaths=pythonpaths,
                verbose=verbose,
                run_command=run_command,
                base_env=base_env,
                timeout=timeout,
            )
            for module in modules
        ]

    order = {module: index for index, module in enumerate(modules)}
    results: list[ModuleResult] = []
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = [
            executor.submit(
                _run_module,
                module,
                root=root,
                use_coverage=use_coverage,
                pythonpaths=pythonpaths,
                verbose=verbose,
                run_command=run_command,
                base_env=base_env,
                timeout=timeout,
            )
            for module in modules
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda result: order[result.module])


def _parse_jobs(value: str) -> int:
    if value == "auto":
        return max(1, os.cpu_count() or 1)
    try:
        jobs = int(value)
    except ValueError as error:
        raise SystemExit("--jobs must be 'auto' or a positive integer") from error
    if jobs < 1:
        raise SystemExit("--jobs must be >= 1")
    return jobs


def _parse_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--timeout must be a positive number") from error
    if timeout <= 0:
        raise argparse.ArgumentTypeError("--timeout must be > 0")
    return timeout


def _print_command_result(result: CommandResult) -> None:
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)


def _print_module_result(result: ModuleResult, *, show_output: bool) -> None:
    status = "TIMEOUT" if result.timed_out else "PASS" if result.returncode == 0 else "FAIL"
    print(f"{status} {result.module} ({result.elapsed:.2f}s)", flush=True)
    if result.stdout and (show_output or result.returncode != 0):
        print(result.stdout, end="")
    if result.stderr and (show_output or result.returncode != 0):
        print(result.stderr, end="", file=sys.stderr)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run XCC unittest modules in parallel subprocesses.",
    )
    parser.add_argument(
        "tests",
        nargs="*",
        help="optional test module names or test file paths; defaults to discovery",
    )
    parser.add_argument(
        "--jobs",
        default=os.environ.get("XCC_TEST_JOBS", "1"),
        help="parallel module workers: auto or a positive integer",
    )
    parser.add_argument(
        "--timeout",
        type=_parse_timeout,
        default=os.environ.get("XCC_TEST_TIMEOUT_SECONDS", "1800"),
        help="maximum seconds for each test module (default: 1800)",
    )
    parser.add_argument("--coverage", action="store_true", help="collect combined coverage data")
    parser.add_argument(
        "--pythonpath",
        type=Path,
        help="additional import root to prepend, such as build/mypyc/lib",
    )
    parser.add_argument(
        "--start-dir",
        type=Path,
        default=Path("tests"),
        help="test discovery directory",
    )
    parser.add_argument("--pattern", default="test*.py", help="test discovery file pattern")
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="use non-verbose unittest output",
    )
    parser.add_argument(
        "--show-output",
        action="store_true",
        help="print stdout/stderr for passing modules as well as failures",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    root = _repo_root()
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    jobs = _parse_jobs(args.jobs)
    verbose = not args.quiet

    if args.tests:
        modules = [_path_to_module(root, value) for value in args.tests]
    else:
        modules = discover_test_modules(
            root=root,
            start_dir=root / args.start_dir,
            pattern=args.pattern,
        )
    if not modules:
        raise SystemExit("no test modules selected")

    detached_tests = coverage_detached_tests(modules) if args.coverage else []

    pythonpaths = () if args.pythonpath is None else (args.pythonpath,)
    coverage_tmp: tempfile.TemporaryDirectory[str] | None = None
    base_env: dict[str, str] | None = None
    if args.coverage:
        coverage_tmp = tempfile.TemporaryDirectory(prefix="xcc-coverage-")
        base_env = dict(os.environ)
        base_env["COVERAGE_FILE"] = str(Path(coverage_tmp.name) / ".coverage")
        if detached_tests:
            base_env[_COVERAGE_SKIP_NATIVE_BOOTSTRAP] = "1"

    try:
        env = _env_with_pythonpath(root=root, pythonpaths=pythonpaths, base=base_env)
        if args.coverage:
            erased = _run_command(coverage_erase_command(), cwd=root, env=env)
            if erased.returncode != 0:
                _print_command_result(erased)
                return erased.returncode

        print(f"running {len(modules)} test module(s) with {jobs} worker(s)", flush=True)
        results = run_modules(
            modules=modules,
            jobs=jobs,
            use_coverage=args.coverage,
            pythonpath=args.pythonpath,
            verbose=verbose,
            root=root,
            base_env=base_env,
            timeout=args.timeout,
        )
        if detached_tests:
            detached_env = dict(base_env or os.environ)
            detached_env.pop(_COVERAGE_SKIP_NATIVE_BOOTSTRAP, None)
            results.extend(
                run_modules(
                    modules=detached_tests,
                    jobs=jobs,
                    use_coverage=False,
                    pythonpath=args.pythonpath,
                    verbose=verbose,
                    root=root,
                    base_env=detached_env,
                    timeout=args.timeout,
                )
            )
        for result in results:
            _print_module_result(result, show_output=args.show_output)

        failed = [result for result in results if result.returncode != 0]
        if failed:
            print(f"{len(failed)} test module(s) failed", file=sys.stderr)
            return 1

        if args.coverage:
            combined = _run_command(coverage_combine_command(), cwd=root, env=env)
            _print_command_result(combined)
            if combined.returncode != 0:
                return combined.returncode
            coverage_file = Path(env["COVERAGE_FILE"])
            if coverage_file.exists():
                shutil.copyfile(coverage_file, root / ".coverage")
            reported = _run_command(
                coverage_report_command(),
                cwd=root,
                env=env,
            )
            _print_command_result(reported)
            if reported.returncode != 0:
                return reported.returncode

        return 0
    finally:
        if coverage_tmp is not None:
            coverage_tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
