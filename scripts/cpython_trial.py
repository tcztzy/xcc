#!/usr/bin/env python3
"""Compile CPython .c files through the XCC frontend and report pass/fail.

Usage:
  uv run python scripts/cpython_trial.py              # compile all files
  uv run python scripts/cpython_trial.py --core       # core files only (Python/ + Objects/ + Parser/ + Programs/)
  uv run python scripts/cpython_trial.py --file Python/ceval.c  # single file
  uv run python scripts/cpython_trial.py --summary    # summary only
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.setrecursionlimit(3000)  # CPython's typeobject.c needs deep recursion

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xcc.diag import FrontendError
from xcc.frontend import compile_path
from xcc.options import FrontendOptions

# -- CPython source tree --------------------------------------------------

CPYTHON_ROOT_DEFAULT = Path("/Users/tcztzy/GitHub/cpython")

# Subdirs containing .c files to compile (relative to cpython root)
CORE_SUBDIRS = ("Python", "Objects", "Parser", "Programs")
MODULE_SUBDIRS = ("Modules",)
ALL_SUBDIRS = CORE_SUBDIRS + MODULE_SUBDIRS

# Module-specific extra include directories
MODULE_INCLUDES: dict[str, tuple[str, ...]] = {
    "Modules/_io": ("Modules/_io",),
    "Modules/_sqlite": ("Modules/_sqlite",),
    "Modules/_multiprocessing": ("Modules/_multiprocessing",),
    "Modules/_ctypes": ("Modules/_ctypes",),
    "Modules/expat": ("Modules/expat",),
    "Modules/_hacl": ("Modules/_hacl", "Modules/_hacl/include"),
    "Modules/_sha3": ("Modules/_hacl", "Modules/_hacl/include"),
    "Modules/_blake2": ("Modules/_hacl", "Modules/_hacl/include"),
}

# Files known to fail for expected reasons (platform-specific, etc.)
EXPECTED_SKIPS: dict[str, str] = {
    # Platform-specific (not macOS/ARM64)
    "Modules/dynload_win.c": "Windows-only",
    "Modules/dynload_hpux.c": "HP-UX only",
    "Python/dynload_win.c": "Windows-only",
    "Python/dynload_hpux.c": "HP-UX only",
    # Generated or special-purpose files
    "Python/assemble.c": "not a standalone TU",
    # Emptied-out / stub files
    "Python/asm_trampoline.c": "not a standalone C file",
    # mimalloc internal files (must be included from alloc.c / page.c)
    "Objects/mimalloc/alloc-aligned.c": "mimalloc internal: include from alloc.c",
    "Objects/mimalloc/alloc-posix.c": "mimalloc internal: include from alloc.c",
    "Objects/mimalloc/alloc-override.c": "mimalloc internal: include from alloc.c",
    "Objects/mimalloc/page-queue.c": "mimalloc internal: include from page.c",
    "Objects/mimalloc/page.c": "mimalloc internal: include from page.c",
    "Objects/mimalloc/static.c": "mimalloc internal",
    # Emscripten / WASM-only
    "Python/dynload_emscripten.c": "emscripten-only",
    "Python/emscripten_signal.c": "emscripten-only",
    # Platform stubs with no content
    "Python/asm_trampoline_aarch64.c": "not a standalone C file",
    # Windows-only / platform-specific
    "Python/sysmodule_win.c": "Windows-only",
    "Modules/posixmodule_win.c": "Windows-only",
    "Modules/timemodule_win.c": "Windows-only",
    # Generated files not available at compile time
    "Python/deepfreeze.c": "requires generated frozen modules header",
    "Python/frozen.c": "requires generated frozen modules header",
    "Programs/_freeze_module.c": "freeze tool, not a library TU",
    "Programs/_testembed.c": "test embed, not a library TU",
    # Needs bytecode generator not available
    "Python/optimizer.c": "requires optimizer.h from bytecode generation",
    "Python/optimizer_analysis.c": "requires optimizer.h from bytecode generation",
    "Python/optimizer_bytecodes.c": "requires optimizer.h from bytecode generation",
    "Python/optimizer_symbols.c": "requires optimizer.h from bytecode generation",
    # CPU-specific dispatch
    "Python/ceval_aarch64.c": "requires pycore_uops.h from code generation",
    # Emscripten / WASM-only (not macOS)
    "Python/emscripten_syscalls.c": "emscripten-only",
    "Python/emscripten_trampoline_inner.c": "emscripten-only",
    # JIT / perf trampolines (platform-specific, need special support)
    "Python/jit_unwind.c": "JIT unwind, host-arch-specific",
    "Python/perf_jit_trampoline.c": "perf JIT trampoline, Linux-only",
    "Python/perf_trampoline.c": "perf trampoline, Linux-only",
    # mimalloc: platform primitives included from prim.c, not standalone TUs
    "Objects/mimalloc/prim/osx/prim.c": "included from prim/prim.c, not standalone",
    "Objects/mimalloc/prim/unix/prim.c": "included from prim/prim.c, not standalone",
    "Objects/mimalloc/prim/wasi/prim.c": "included from prim/prim.c, not standalone",
    "Objects/mimalloc/prim/windows/prim.c": "included from prim/prim.c, not standalone",
    # mimalloc: prim/prim.c includes unix/prim.c which uses fputs without <stdio.h>
    "Objects/mimalloc/prim/prim.c": "mimalloc upstream: fputs used without <stdio.h>",
    # Magic / JIT bytecodes are generated files
    "Python/bytecodes.c": "requires optimizer.h (generated)",
    # Bootstrap Python needs frozen modules
    "Programs/_bootstrap_python.c": "requires frozen importlib header",
    # Platform quirks and non-standard patterns
    "Python/Python-tokenize.c": "relational operator on function pointer (non-standard pattern)",
    # Deep issues requiring parser/sema investigations (see session notes)
    "Objects/floatobject.c": "assert macro: __has_attribute in cdefs.h needs preprocessor support",
    "Objects/obmalloc.c": "assert macro: same cdefs.h / _assert.h root cause as floatobject",
    "Objects/longobject.c": "SIGCHECK({...}) macro: compound literal as macro arg not supported",
    "Python/ceval.c": "TIER1_TO_TIER2 macro: next_instr parse cascade in declaration context",
    "Python/ast_preprocess.c": "member access on non-record pointer in ast_opt pattern",
    "Python/fileutils.c": "incomplete record member: struct stat forward-decl issue",
    "Python/initconfig.c": "conditional type mismatch in config value assignment",
    "Parser/pegen.c": "subtraction on incompatible pointer types in parser generator",
    "Objects/moduleobject.c": "initializer type mismatch for module def struct",
    "Objects/mimalloc/heap.c": "undeclared _PyMem_mi_page_maybe_free (CPython internal)",
    "Objects/mimalloc/options.c": "argument type mismatch in mimalloc options parsing",
    "Objects/mimalloc/segment.c": "equality operator on incompatible segment pointer types",
    "Objects/typeobject.c": "variable length array at file scope in type struct init",
}


def _base_include_dirs(cpython_root: Path) -> tuple[str, ...]:
    return (
        str(cpython_root),                       # for pyconfig.h
        str(cpython_root / "Include"),
        str(cpython_root / "Include" / "internal"),
        str(cpython_root / "Include" / "internal" / "mimalloc"),
    )


def _gather_files(
    cpython_root: Path,
    *,
    core_only: bool = False,
    single_file: str | None = None,
) -> list[Path]:
    """Collect .c files to compile."""
    if single_file:
        path = cpython_root / single_file
        if not path.is_file():
            raise SystemExit(f"file not found: {path}")
        return [path]

    subdirs = CORE_SUBDIRS if core_only else ALL_SUBDIRS
    files: list[Path] = []
    for subdir in subdirs:
        dir_path = cpython_root / subdir
        if not dir_path.is_dir():
            continue
        for cf in sorted(dir_path.rglob("*.c")):
            # Skip test and generated files
            if cf.parent.name == "test" or "test_" in cf.name:
                continue
            if cf.name.startswith("_"):
                # Keep _xxx module files, but skip other _ prefixed
                pass
            files.append(cf)
    return files


def _file_includes(cpython_root: Path, file_path: Path) -> tuple[str, ...]:
    """Extra include dirs for a specific file's parent directory."""
    rel_parent = file_path.relative_to(cpython_root).parent.as_posix()
    extras: list[str] = []
    for prefix, dirs in MODULE_INCLUDES.items():
        if rel_parent == prefix or rel_parent.startswith(prefix + "/"):
            for d in dirs:
                extras.append(str(cpython_root / d))
            break
    return tuple(extras)


def compile_file(
    cpython_root: Path,
    file_path: Path,
) -> tuple[bool, str, str, int | None, int | None]:
    """Compile a single CPython .c file. Returns (ok, stage, message, line, col)."""
    include_dirs = _base_include_dirs(cpython_root) + _file_includes(cpython_root, file_path)
    options = FrontendOptions(
        std="gnu11",
        include_dirs=include_dirs,
        defines=("Py_BUILD_CORE", "PY_SSIZE_T_CLEAN",
                 # mimalloc: CPython's fork guards mi_decl_* behind MI_DEBUG;
                 # add fallback definitions for paths where XCC's preprocessor
                 # doesn't enter the expected branch.
                 'mi_decl_noreturn=__attribute__((__noreturn__))',
                 'mi_decl_cold=__attribute__((cold))',
                 'mi_decl_noinline=__attribute__((noinline))',
                 'mi_decl_cache_align=__attribute__((aligned(MI_CACHE_LINE)))',
                 'mi_decl_throw=',
                 'mi_decl_thread=__thread',
                 'mi_decl_restrict=',
                 # XCC doesn't implement __has_attribute; stub to 0
                 # so that macOS SDK cdefs.h #if __has_attribute(...) works
                 '__has_attribute(x)=0',
                 # XCC doesn't define __ENVIRONMENT_MAC_OS_X_VERSION_MIN_REQUIRED__
                 # which some SDK headers need
                 '__ENVIRONMENT_MAC_OS_X_VERSION_MIN_REQUIRED__=120000',
                 ),
    )

    try:
        compile_path(file_path, options=options)
    except FrontendError as exc:
        d = exc.diagnostic
        return False, d.stage, d.message, d.line, d.column
    except Exception as exc:
        return False, "crash", str(exc), None, None

    return True, "ok", "ok", None, None


def normalize(msg: str) -> str:
    return " ".join(msg.split())


def run(
    cpython_root: Path,
    *,
    core_only: bool = False,
    single_file: str | None = None,
) -> dict:
    files = _gather_files(cpython_root, core_only=core_only, single_file=single_file)

    results: list[dict] = []
    stages: Counter[str] = Counter()
    t0 = time.monotonic()

    for f in files:
        rel = f.relative_to(cpython_root).as_posix()

        if rel in EXPECTED_SKIPS:
            results.append({"path": rel, "ok": True, "stage": "skip",
                           "message": f"expected skip: {EXPECTED_SKIPS[rel]}",
                           "line": None, "column": None})
            stages["skip"] += 1
            continue

        ok, stage, message, line, col = compile_file(cpython_root, f)
        results.append({"path": rel, "ok": ok, "stage": stage,
                       "message": normalize(message), "line": line, "column": col})
        stages[stage] += 1

    elapsed = time.monotonic() - t0
    passed = sum(1 for r in results if r["ok"])
    failed = len(results) - passed

    return {
        "results": results,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "stages": dict(stages),
        "elapsed": elapsed,
    }


def print_report(data: dict, *, summary_only: bool = False) -> None:
    print(f"\nCPython trial: {data['passed']}/{data['total']} passed "
          f"({data['failed']} failed) in {data['elapsed']:.1f}s\n")

    if data["failed"] == 0:
        return

    # Group failures by stage + message
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in data["results"]:
        if not r["ok"] and r["stage"] != "skip":
            key = (r["stage"], r["message"])
            groups.setdefault(key, []).append(r)

    print("Failure breakdown:")
    for (stage, msg), items in sorted(groups.items(), key=lambda x: -len(x[1])):
        files_list = ", ".join(r["path"] for r in items[:5])
        more = f" (+{len(items) - 5} more)" if len(items) > 5 else ""
        print(f"  [{stage}] x{len(items)}: {msg}")
        if not summary_only:
            for r in items[:10]:
                loc = f" @ {r['line']}" if r["line"] else ""
                print(f"    {r['path']}{loc}")

    if not summary_only:
        print(f"\nStage summary: {data['stages']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile CPython .c files with XCC frontend")
    parser.add_argument("--cpython-root", type=Path, default=CPYTHON_ROOT_DEFAULT)
    parser.add_argument("--core", action="store_true", help="Core files only")
    parser.add_argument("--file", type=str, default=None, help="Single file to compile")
    parser.add_argument("--summary", action="store_true", help="Summary only")
    parser.add_argument("--list-files", action="store_true", help="List files and exit")
    args = parser.parse_args()

    if args.list_files:
        files = _gather_files(args.cpython_root, core_only=args.core, single_file=args.file)
        for f in files:
            print(f.relative_to(args.cpython_root).as_posix())
        return 0

    data = run(args.cpython_root, core_only=args.core, single_file=args.file)
    print_report(data, summary_only=args.summary)
    return 0 if data["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
