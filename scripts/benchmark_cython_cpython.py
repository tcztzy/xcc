#!/usr/bin/env python3
"""Compare pure-Python XCC against a Cython-compiled import tree on CPython C files."""

import argparse
import json
import os
import statistics
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

RUNNER = r"""
import contextlib
import io
import json
import sys
import time

from xcc import main

jobs = json.loads(sys.argv[1])
started = time.perf_counter()
for argv in jobs:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    if code != 0:
        sys.stderr.write(stderr.getvalue())
        sys.stderr.write(stdout.getvalue())
        raise SystemExit(code)
elapsed = time.perf_counter() - started
print(f"{elapsed:.9f}")
"""

DEFAULT_SOURCES = (
    "Objects/listobject.c",
    "Objects/dictobject.c",
    "Python/compile.c",
    "Parser/parser.c",
    "Modules/_json.c",
)


@dataclass(frozen=True)
class Variant:
    name: str
    pythonpath: Path


@dataclass(frozen=True)
class VariantResult:
    name: str
    times: tuple[float, ...]

    @property
    def median(self) -> float:
        return statistics.median(self.times)

    @property
    def minimum(self) -> float:
        return min(self.times)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_sources(cpython_root: Path, requested: list[str]) -> list[Path]:
    names = requested or list(DEFAULT_SOURCES)
    sources: list[Path] = []
    missing: list[str] = []
    for name in names:
        path = Path(name)
        if not path.is_absolute():
            path = cpython_root / path
        if path.exists():
            sources.append(path)
        else:
            missing.append(str(path))
    if missing:
        raise SystemExit("missing CPython source file(s): " + ", ".join(missing))
    return sources


def _common_frontend_flags(cpython_root: Path, extra_cflags: list[str]) -> list[str]:
    return [
        "--frontend",
        "-std=gnu11",
        "-DPy_BUILD_CORE",
        "-I",
        str(cpython_root),
        "-I",
        str(cpython_root / "Include"),
        "-I",
        str(cpython_root / "Include" / "internal"),
        *extra_cflags,
    ]


def _jobs(cpython_root: Path, sources: list[Path], extra_cflags: list[str]) -> list[list[str]]:
    common = _common_frontend_flags(cpython_root, extra_cflags)
    return [[*common, str(source)] for source in sources]


def _run_variant(
    *,
    python: str,
    variant: Variant,
    jobs: list[list[str]],
    warmups: int,
    runs: int,
) -> VariantResult:
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(variant.pythonpath)
        if not env.get("PYTHONPATH")
        else str(variant.pythonpath) + os.pathsep + env["PYTHONPATH"]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    encoded_jobs = json.dumps(jobs, separators=(",", ":"))
    times: list[float] = []
    total = warmups + runs
    for index in range(total):
        completed = subprocess.run(
            [python, "-c", RUNNER, encoded_jobs],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )
        if completed.returncode != 0:
            raise SystemExit(
                f"{variant.name} run failed with exit {completed.returncode}\n"
                f"{completed.stderr}{completed.stdout}"
            )
        if index >= warmups:
            times.append(float(completed.stdout.strip()))
    return VariantResult(variant.name, tuple(times))


def _build_cython_import_tree(
    *,
    python: str,
    build_root: Path,
    clean: bool,
    force: bool,
) -> Path:
    root = _repo_root()
    command = [
        python,
        str(root / "scripts" / "cythonize_xcc.py"),
        "--build-root",
        str(build_root),
    ]
    if clean:
        command.append("--clean")
    if force:
        command.append("--force")
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr + completed.stdout)
    output = completed.stdout.strip().splitlines()
    if not output:
        raise SystemExit("cython build produced no import path")
    return Path(output[-1])


def _print_results(results: list[VariantResult]) -> None:
    print("variant  runs  median_s  min_s")
    for result in results:
        print(
            f"{result.name:<8} {len(result.times):>4}  "
            f"{result.median:>8.3f}  {result.minimum:>6.3f}"
        )
    by_name = {result.name: result for result in results}
    if "pure" in by_name and "cython" in by_name:
        speedup = by_name["pure"].median / by_name["cython"].median
        print(f"speedup: {speedup:.2f}x median (pure / cython)")


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark XCC frontend throughput on configured CPython source files, "
            "comparing src/ imports with a Cython-compiled import tree."
        ),
    )
    parser.add_argument(
        "--cpython",
        type=Path,
        default=root.parent / "cpython",
        help="configured CPython source tree",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="CPython .c path, relative to --cpython or absolute; repeatable",
    )
    parser.add_argument("--cflag", action="append", default=[], help="extra XCC frontend flag")
    parser.add_argument("--runs", type=int, default=5, help="measured runs per variant")
    parser.add_argument("--warmups", type=int, default=1, help="warmup runs per variant")
    parser.add_argument("--python", default=sys.executable, help="Python executable for runs")
    parser.add_argument(
        "--variant",
        choices=("pure", "cython", "both"),
        default="both",
        help="which import tree to benchmark",
    )
    parser.add_argument(
        "--build-root",
        type=Path,
        default=root / "build" / "cython",
        help="Cython build root",
    )
    parser.add_argument(
        "--skip-cython-build",
        action="store_true",
        help="reuse --build-root/lib for the Cython variant",
    )
    parser.add_argument(
        "--clean-cython-build",
        action="store_true",
        help="delete --build-root before building the Cython variant",
    )
    parser.add_argument(
        "--force-cython-build",
        action="store_true",
        help="force Cython extension recompilation",
    )
    parser.add_argument("--json", type=Path, help="write machine-readable results")
    args = parser.parse_args(argv)

    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    if args.warmups < 0:
        raise SystemExit("--warmups must be >= 0")
    cpython_root = args.cpython.resolve()
    if not (cpython_root / "pyconfig.h").exists():
        raise SystemExit(f"{cpython_root} is not configured; expected pyconfig.h")

    sources = _resolve_sources(cpython_root, args.source)
    jobs = _jobs(cpython_root, sources, args.cflag)
    print("sources:")
    for source in sources:
        print(f"  {source.relative_to(cpython_root)}")

    variants: list[Variant] = []
    if args.variant in {"pure", "both"}:
        variants.append(Variant("pure", root / "src"))
    if args.variant in {"cython", "both"}:
        if args.skip_cython_build:
            cython_path = args.build_root.resolve() / "lib"
        else:
            cython_path = _build_cython_import_tree(
                python=args.python,
                build_root=args.build_root,
                clean=args.clean_cython_build,
                force=args.force_cython_build,
            )
        variants.append(Variant("cython", cython_path))

    results = [
        _run_variant(
            python=args.python,
            variant=variant,
            jobs=jobs,
            warmups=args.warmups,
            runs=args.runs,
        )
        for variant in variants
    ]
    _print_results(results)
    if args.json is not None:
        payload = {
            "sources": [str(source) for source in sources],
            "runs": {
                result.name: {
                    "times": list(result.times),
                    "median": result.median,
                    "min": result.minimum,
                }
                for result in results
            },
        }
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
