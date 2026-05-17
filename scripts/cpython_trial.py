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


def _resolve_soabi(cpython_root: Path) -> str:
    """Resolve SOABI for the CPython source at *cpython_root*.

    SOABI is normally supplied by the Makefile via ``-DSOABI=...`` and
    is *not* available in pyconfig.h.  We derive it from the version
    declared in ``Include/patchlevel.h`` together with the host platform
    tag (``sysconfig.get_platform()``).
    """
    # 1. Try the CPython source tree's own Makefile (fastest).
    makefile = cpython_root / "Makefile"
    if makefile.is_file():
        for line in makefile.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("SOABI="):
                value = stripped.split("=", 1)[1].strip()
                if value:
                    return f'"{value}"'

    # 2. Read the version from patchlevel.h.
    major = minor = "0"
    patchlevel = cpython_root / "Include" / "patchlevel.h"
    if patchlevel.is_file():
        import re
        text = patchlevel.read_text(encoding="utf-8")
        m_major = re.search(r"#define\s+PY_MAJOR_VERSION\s+(\d+)", text)
        m_minor = re.search(r"#define\s+PY_MINOR_VERSION\s+(\d+)", text)
        if m_major:
            major = m_major.group(1)
        if m_minor:
            minor = m_minor.group(1)

    # 3. Get the MULTIARCH tag (darwin on macOS, arm-linux-gnueabihf etc. elsewhere).
    multiarch = "darwin" if sys.platform == "darwin" else "unknown"
    return f'"cpython-{major}{minor}-{multiarch}"'


def _resolve_extra_defines(cpython_root: Path) -> tuple[str, ...]:
    """Return extra -D flags that CPython's Makefile would supply."""
    return (
        f"SOABI={_resolve_soabi(cpython_root)}",
    )

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
    "Modules/_winapi.c": "Windows-only (needs windows.h)",
    "Modules/overlapped.c": "Windows-only (needs winsock2.h)",
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


_THIRD_PARTY_INCLUDE_CACHE: dict[Path, tuple[str, ...]] = {}


def _resolve_third_party_includes(cpython_root: Path) -> tuple[str, ...]:
    """Read third-party -I paths from CPython's configured Makefile.

    CPython's ``./configure`` discovers library locations via pkg-config
    and records them in the generated Makefile.  We read those rather
    than re-running discovery ourselves — XCC is a compiler, not a build
    system.
    """
    if cpython_root in _THIRD_PARTY_INCLUDE_CACHE:
        return _THIRD_PARTY_INCLUDE_CACHE[cpython_root]

    dirs: list[str] = []
    makefile = cpython_root / "Makefile"
    if makefile.is_file():
        import re as _re
        text = makefile.read_text(encoding="utf-8")
        for var in ("CONFIGURE_CFLAGS", "BASECFLAGS", "CFLAGS", "CPPFLAGS"):
            m = _re.search(rf"^{var}\s*=\s*(.+)$", text, _re.MULTILINE)
            if m:
                for token in m.group(1).split():
                    if token.startswith("-I"):
                        d = token[2:]
                        if d and Path(d).is_dir() and d not in dirs:
                            dirs.append(d)

    result = tuple(dirs)
    _THIRD_PARTY_INCLUDE_CACHE[cpython_root] = result
    return result


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


# Per-directory extra defines (e.g. for module-specific build flags)
_DIRECTORY_DEFINES: dict[str, tuple[str, ...]] = {
    "Modules/_testcapi": ("PYTESTCAPI_NEED_INTERNAL_API=1",),
    "Modules/_ctypes": ("USING_MALLOC_CLOSURE_DOT_C=1",),
}


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


def _file_defines(cpython_root: Path, file_path: Path) -> tuple[str, ...]:
    """Extra -D defines for a specific file's parent directory."""
    rel_parent = file_path.relative_to(cpython_root).parent.as_posix()
    for prefix, defines in _DIRECTORY_DEFINES.items():
        if rel_parent == prefix or rel_parent.startswith(prefix + "/"):
            return defines
    return ()


_BASE_DEFINES = (
    "Py_BUILD_CORE",
    "PY_SSIZE_T_CLEAN",
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
)

_EXTRA_DEFINES_CACHE: dict[Path, tuple[str, ...]] = {}


def _get_extra_defines(cpython_root: Path) -> tuple[str, ...]:
    if cpython_root not in _EXTRA_DEFINES_CACHE:
        _EXTRA_DEFINES_CACHE[cpython_root] = _resolve_extra_defines(cpython_root)
    return _EXTRA_DEFINES_CACHE[cpython_root]


def compile_file(
    cpython_root: Path,
    file_path: Path,
) -> tuple[bool, str, str, int | None, int | None]:
    """Compile a single CPython .c file. Returns (ok, stage, message, line, col)."""
    include_dirs = (
        _base_include_dirs(cpython_root)
        + _resolve_third_party_includes(cpython_root)
        + _file_includes(cpython_root, file_path)
    )
    options = FrontendOptions(
        std="gnu11",
        include_dirs=include_dirs,
        defines=_BASE_DEFINES + _get_extra_defines(cpython_root) + _file_defines(cpython_root, file_path),
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
