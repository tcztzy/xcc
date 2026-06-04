#!/usr/bin/env python3
"""Build XCC modules as Cython extension modules for performance experiments."""

import argparse
import os
import shutil
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_build_deps():
    try:
        from Cython.Build import cythonize
        from setuptools import Distribution, Extension
        from setuptools.command.build_ext import build_ext
    except ModuleNotFoundError as error:
        message = (
            "missing Cython build dependency; run with "
            "`uv run --with cython --with setuptools python scripts/cythonize_xcc.py`"
        )
        raise SystemExit(message) from error
    return cythonize, Distribution, Extension, build_ext


def _module_name(src_dir: Path, path: Path) -> str:
    return ".".join(path.relative_to(src_dir).with_suffix("").parts)


def _python_modules(src_dir: Path) -> list[Path]:
    package_dir = src_dir / "xcc"
    return sorted(path for path in package_dir.rglob("*.py") if path.name != "__init__.py")


def _copy_package(src_dir: Path, build_lib: Path) -> None:
    source = src_dir / "xcc"
    destination = build_lib / "xcc"
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def build_cython_package(
    *,
    src_dir: Path,
    build_root: Path,
    force: bool,
    annotate: bool,
    binding: bool,
) -> Path:
    cythonize, distribution_cls, extension_cls, build_ext_cls = _load_build_deps()

    src_dir = src_dir.resolve()
    build_root = build_root.resolve()
    build_lib = build_root / "lib"
    build_temp = build_root / "temp"
    cython_temp = build_root / "cythonized"
    build_lib.mkdir(parents=True, exist_ok=True)
    build_temp.mkdir(parents=True, exist_ok=True)
    cython_temp.mkdir(parents=True, exist_ok=True)
    _copy_package(src_dir, build_lib)

    modules = _python_modules(src_dir)
    extensions = [extension_cls(_module_name(src_dir, path), [str(path)]) for path in modules]
    ext_modules = cythonize(
        extensions,
        annotate=annotate,
        build_dir=str(cython_temp),
        compiler_directives={"binding": binding, "language_level": "3"},
        nthreads=max(1, os.cpu_count() or 1),
        quiet=True,
    )

    distribution = distribution_cls({"ext_modules": ext_modules})
    command = build_ext_cls(distribution)
    command.build_lib = str(build_lib)
    command.build_temp = str(build_temp)
    command.force = force
    command.inplace = False
    command.ensure_finalized()
    command.run()
    return build_lib


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(
        description="Build a temporary Cython-compiled import tree for XCC.",
    )
    parser.add_argument("--src-dir", type=Path, default=root / "src", help="source tree root")
    parser.add_argument(
        "--build-root",
        type=Path,
        default=root / "build" / "cython",
        help="directory for generated C files, objects, and extension modules",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="delete the build root before compiling",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="force recompilation even when extension outputs exist",
    )
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="write Cython HTML annotation files under the build root",
    )
    parser.add_argument(
        "--binding",
        action="store_true",
        help="preserve Python function binding semantics; slower but closer to Cython defaults",
    )
    args = parser.parse_args(argv)

    if args.clean and args.build_root.exists():
        shutil.rmtree(args.build_root)
    build_lib = build_cython_package(
        src_dir=args.src_dir,
        build_root=args.build_root,
        force=args.force,
        annotate=args.annotate,
        binding=args.binding,
    )
    print(build_lib)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
