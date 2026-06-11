#!/usr/bin/env python3
"""Benchmark XCC frontend throughput across Python and compiled import variants."""

import argparse
import json
import os
import shlex
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
    kind: str
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


def _run_build_command(command: list[str], build_name: str) -> Path:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr + completed.stdout)
    output = completed.stdout.strip().splitlines()
    if not output:
        raise SystemExit(f"{build_name} build produced no import path")
    return Path(output[-1])


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
    return _run_build_command(command, "cython")


def _build_mypyc_import_tree(
    *,
    python: str,
    build_root: Path,
    profile: str,
    clean: bool,
    force: bool,
) -> Path:
    root = _repo_root()
    command = [
        python,
        str(root / "scripts" / "mypycize_xcc.py"),
        "--build-root",
        str(build_root),
        "--profile",
        profile,
    ]
    if clean:
        command.append("--clean")
    if force:
        command.append("--force")
    return _run_build_command(command, "mypyc")


def _build_import_tree(kind: str, *, python: str, args: argparse.Namespace) -> Path:
    if kind == "cython":
        if args.skip_build or args.skip_cython_build:
            return args.cython_build_root.resolve() / "lib"
        return _build_cython_import_tree(
            python=python,
            build_root=args.cython_build_root,
            clean=args.clean_build or args.clean_cython_build,
            force=args.force_build or args.force_cython_build,
        )
    if kind == "mypyc":
        if args.skip_build or args.skip_mypyc_build:
            return args.mypyc_build_root.resolve() / "lib"
        return _build_mypyc_import_tree(
            python=python,
            build_root=args.mypyc_build_root,
            profile=args.profile,
            clean=args.clean_build or args.clean_mypyc_build,
            force=args.force_build or args.force_mypyc_build,
        )
    raise ValueError(f"unknown compiled variant: {kind}")


def _variant_kinds(requested: str, both_kind: str | None) -> tuple[str, ...]:
    if requested == "all":
        return ("pure", "cython", "mypyc")
    if requested == "both":
        if both_kind is None:
            return ("pure", "cython", "mypyc")
        return ("pure", both_kind)
    return (requested,)


def _variants(
    *,
    root: Path,
    args: argparse.Namespace,
    both_kind: str | None,
) -> list[Variant]:
    kinds = _variant_kinds(args.variant, both_kind)
    variants: list[Variant] = []
    for kind in kinds:
        name = args.label if args.label is not None and len(kinds) == 1 else kind
        if kind == "pure":
            variants.append(Variant(name, "pure", root / "src"))
        elif kind in {"cython", "mypyc"}:
            variants.append(
                Variant(
                    name,
                    kind,
                    _build_import_tree(kind, python=args.python, args=args),
                ),
            )
        else:
            raise ValueError(f"unknown variant: {kind}")
    return variants


def _print_results(results: list[VariantResult]) -> None:
    print("variant      runs  median_s  min_s")
    for result in results:
        print(
            f"{result.name:<12} {len(result.times):>4}  "
            f"{result.median:>8.3f}  {result.minimum:>6.3f}"
        )
    by_name = {result.name: result for result in results}
    if "pure" in by_name:
        for name in ("cython", "mypyc"):
            if name in by_name:
                speedup = by_name["pure"].median / by_name[name].median
                print(f"{name} speedup: {speedup:.2f}x median (pure / {name})")


def _write_json(
    *,
    path: Path,
    sources: list[Path],
    profile: str,
    python: str,
    results: list[tuple[Variant, VariantResult]],
) -> None:
    payload = {
        "sources": [str(source) for source in sources],
        "profile": profile,
        "runs": {
            result.name: {
                "variant": variant.kind,
                "python": python,
                "pythonpath": str(variant.pythonpath),
                "times": list(result.times),
                "median": result.median,
                "min": result.minimum,
            }
            for variant, result in results
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _parser(root: Path, default_variant: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark XCC frontend throughput on configured CPython source files "
            "using pure Python, Cython, or mypyc import trees."
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
        choices=("pure", "cython", "mypyc", "both", "all"),
        default=default_variant,
        help="which import tree or trees to benchmark",
    )
    parser.add_argument(
        "--label",
        help="result label for a single requested variant, used by the tox matrix",
    )
    parser.add_argument(
        "--profile",
        choices=("preprocessor", "frontend"),
        default="frontend",
        help="mypy-compiled module selection",
    )
    parser.add_argument(
        "--cython-build-root",
        type=Path,
        default=root / "build" / "cython",
        help="Cython build root",
    )
    parser.add_argument(
        "--mypyc-build-root",
        type=Path,
        default=root / "build" / "mypyc",
        help="mypyc build root",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="reuse compiled build roots for Cython or mypyc variants",
    )
    parser.add_argument(
        "--clean-build",
        action="store_true",
        help="delete compiled build roots before building Cython or mypyc variants",
    )
    parser.add_argument(
        "--force-build",
        action="store_true",
        help="force extension recompilation for Cython or mypyc variants",
    )
    parser.add_argument(
        "--skip-cython-build",
        action="store_true",
        help="reuse --cython-build-root/lib for the Cython variant",
    )
    parser.add_argument(
        "--clean-cython-build",
        action="store_true",
        help="delete --cython-build-root before building the Cython variant",
    )
    parser.add_argument(
        "--force-cython-build",
        action="store_true",
        help="force Cython extension recompilation",
    )
    parser.add_argument(
        "--skip-mypyc-build",
        action="store_true",
        help="reuse --mypyc-build-root/lib for the mypyc variant",
    )
    parser.add_argument(
        "--clean-mypyc-build",
        action="store_true",
        help="delete --mypyc-build-root before building the mypyc variant",
    )
    parser.add_argument(
        "--force-mypyc-build",
        action="store_true",
        help="force mypyc extension recompilation",
    )
    parser.add_argument("--json", type=Path, help="write machine-readable results")
    return parser


def _normalized_argv(argv: list[str] | None) -> list[str]:
    values = sys.argv[1:] if argv is None else argv
    normalized: list[str] = []
    for value in values:
        if value == "":
            continue
        if value.startswith("-") and " " in value:
            normalized.extend(shlex.split(value))
        else:
            normalized.append(value)
    return normalized


def main(
    argv: list[str] | None = None,
    *,
    default_variant: str = "pure",
    both_kind: str | None = None,
) -> int:
    root = _repo_root()
    parser = _parser(root, default_variant)
    args = parser.parse_args(_normalized_argv(argv))

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

    variants = _variants(root=root, args=args, both_kind=both_kind)
    measured: list[tuple[Variant, VariantResult]] = []
    for variant in variants:
        result = _run_variant(
            python=args.python,
            variant=variant,
            jobs=jobs,
            warmups=args.warmups,
            runs=args.runs,
        )
        measured.append((variant, result))

    _print_results([result for _, result in measured])
    if args.json is not None:
        _write_json(
            path=args.json,
            sources=sources,
            profile=args.profile,
            python=args.python,
            results=measured,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
