#!/usr/bin/env python3
"""Build selected XCC modules as mypyc extension modules."""

import argparse
import shutil
from pathlib import Path

_PREPROCESSOR_MODULES = (
    Path("xcc/preprocessor/conditionals.py"),
    Path("xcc/preprocessor/expressions.py"),
    Path("xcc/preprocessor/includes.py"),
    Path("xcc/preprocessor/macro_expansion.py"),
    Path("xcc/preprocessor/macros.py"),
    Path("xcc/preprocessor/pragmas.py"),
    Path("xcc/preprocessor/probes.py"),
    Path("xcc/preprocessor/process.py"),
    Path("xcc/preprocessor/text.py"),
)

_PROFILE_MODULES = {
    "preprocessor": _PREPROCESSOR_MODULES,
    "frontend": (Path("xcc/lexer.py"), *_PREPROCESSOR_MODULES),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_build_deps():
    try:
        from mypyc.build import mypycify
        from setuptools import Distribution
        from setuptools.command.build_ext import build_ext
    except ModuleNotFoundError as error:
        message = (
            "missing mypyc build dependency; run with "
            "`uv run --with 'mypy[mypyc]' --with setuptools "
            "python scripts/mypycize_xcc.py`"
        )
        raise SystemExit(message) from error
    return mypycify, Distribution, build_ext


def _copy_package(src_dir: Path, build_lib: Path) -> None:
    source = src_dir / "xcc"
    destination = build_lib / "xcc"
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def _selected_modules(src_dir: Path, profile: str) -> list[Path]:
    modules = [src_dir / path for path in _PROFILE_MODULES[profile]]
    missing = [str(path) for path in modules if not path.exists()]
    if missing:
        raise SystemExit("missing mypyc input module(s): " + ", ".join(missing))
    return modules


def build_mypyc_package(
    *,
    src_dir: Path,
    build_root: Path,
    profile: str,
    force: bool,
    opt_level: str,
    debug_level: str,
) -> Path:
    mypycify, distribution_cls, build_ext_cls = _load_build_deps()

    src_dir = src_dir.resolve()
    build_root = build_root.resolve()
    build_lib = build_root / "lib"
    build_temp = build_root / "temp"
    generated = build_root / "generated"
    build_lib.mkdir(parents=True, exist_ok=True)
    build_temp.mkdir(parents=True, exist_ok=True)
    generated.mkdir(parents=True, exist_ok=True)
    _copy_package(src_dir, build_lib)

    modules = _selected_modules(src_dir, profile)
    ext_modules = mypycify(
        [str(path) for path in modules],
        opt_level=opt_level,
        debug_level=debug_level,
        strict_dunder_typing=False,
        target_dir=str(generated),
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
        description="Build a temporary mypyc-compiled import tree for XCC.",
    )
    parser.add_argument("--src-dir", type=Path, default=root / "src", help="source tree root")
    parser.add_argument(
        "--build-root",
        type=Path,
        default=root / "build" / "mypyc",
        help="directory for generated C files, objects, and extension modules",
    )
    parser.add_argument(
        "--profile",
        choices=tuple(_PROFILE_MODULES),
        default="frontend",
        help="module selection to compile with mypyc",
    )
    parser.add_argument("--opt-level", choices=("0", "1", "2", "3"), default="3")
    parser.add_argument("--debug-level", choices=("0", "1", "2"), default="1")
    parser.add_argument("--clean", action="store_true", help="delete the build root first")
    parser.add_argument(
        "--force",
        action="store_true",
        help="force recompilation even when extension outputs exist",
    )
    args = parser.parse_args(argv)

    if args.clean and args.build_root.exists():
        shutil.rmtree(args.build_root)
    build_lib = build_mypyc_package(
        src_dir=args.src_dir,
        build_root=args.build_root,
        profile=args.profile,
        force=args.force,
        opt_level=args.opt_level,
        debug_level=args.debug_level,
    )
    print(build_lib)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
