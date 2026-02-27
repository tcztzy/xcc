import os
import subprocess
import sys
from collections.abc import Sequence
from typing import TextIO

from xcc.frontend import FrontendError, compile_path, compile_source, read_source
from xcc.options import FrontendOptions, StdMode


def looks_like_cc_driver(argv: Sequence[str]) -> bool:
    if not argv:
        return False
    for arg in argv:
        if arg == "--frontend":
            return False
        if arg.startswith("--dump-"):
            return False
        if arg == "--diag-format" or arg.startswith("--diag-format="):
            return False
    index = 0
    c_inputs = 0
    while index < len(argv):
        arg = argv[index]
        index += 1
        if arg in {"-c", "-S", "-E", "-M", "-MM", "--version", "-v", "-V"}:
            return True
        if arg == "-o":
            return True
        if arg.startswith("-o") and arg != "-o":
            return True
        if arg == "-x":
            return True
        if arg.startswith("-x") and arg != "-x":
            return True
        if arg in {
            "-D",
            "-U",
            "-I",
            "-iquote",
            "-isystem",
            "-idirafter",
            "-include",
            "-imacros",
            "-std",
        }:
            index += 1
            continue
        if arg.endswith(".c") and not arg.startswith("-"):
            c_inputs += 1
    return c_inputs > 0


def _take_value(argv: Sequence[str], index: int, opt: str) -> tuple[str, int]:
    if index >= len(argv):
        raise ValueError(f"Missing value for {opt}")
    return argv[index], index + 1


def _take_joined_or_value(
    argv: Sequence[str],
    index: int,
    arg: str,
    opt: str,
) -> tuple[str, int] | None:
    if arg == opt:
        return _take_value(argv, index, opt)
    if arg.startswith(opt) and arg != opt:
        return arg[len(opt) :], index
    return None


def _parse_std(arg: str) -> StdMode:
    if arg in {"c11", "gnu11"}:
        return arg  # type: ignore[return-value]
    raise ValueError(f"Unsupported language standard: {arg}")


def _frontend_options_from_cc_argv(argv: Sequence[str]) -> tuple[FrontendOptions, list[str], bool]:
    std: StdMode = "gnu11"
    hosted = True
    include_dirs: list[str] = []
    quote_include_dirs: list[str] = []
    system_include_dirs: list[str] = []
    after_include_dirs: list[str] = []
    forced_includes: list[str] = []
    macro_includes: list[str] = []
    defines: list[str] = []
    undefs: list[str] = []
    no_standard_includes = False
    language: str | None = None
    c_inputs: list[str] = []
    needs_stdin = False

    index = 0
    while index < len(argv):
        arg = argv[index]
        index += 1
        if arg == "--":
            language = None
            for rest in argv[index:]:
                if rest.endswith(".c"):
                    c_inputs.append(rest)
            break
        if arg == "-x":
            language, index = _take_value(argv, index, "-x")
            if language == "none":
                language = None
            continue
        if arg.startswith("-x") and arg != "-x":
            language = arg[2:]
            if language == "none":
                language = None
            continue
        if arg == "-std":
            std_value, index = _take_value(argv, index, "-std")
            std = _parse_std(std_value)
            continue
        if arg.startswith("-std="):
            std = _parse_std(arg.split("=", 1)[1])
            continue
        if arg == "-fhosted":
            hosted = True
            continue
        if arg == "-ffreestanding":
            hosted = False
            continue
        if arg == "-nostdinc":
            no_standard_includes = True
            continue

        for opt, target in (
            ("-I", include_dirs),
            ("-iquote", quote_include_dirs),
            ("-isystem", system_include_dirs),
            ("-idirafter", after_include_dirs),
            ("-include", forced_includes),
            ("-imacros", macro_includes),
            ("-D", defines),
            ("-U", undefs),
            ("-o", None),
        ):
            taken = _take_joined_or_value(argv, index, arg, opt)
            if taken is None:
                continue
            value, index = taken
            if target is not None:
                target.append(value)
            break
        else:
            if arg == "-":
                if language == "c":
                    needs_stdin = True
                continue
            if not arg.startswith("-") and (arg.endswith(".c") or language == "c"):
                c_inputs.append(arg)

    options = FrontendOptions(
        std=std,
        hosted=hosted,
        include_dirs=tuple(include_dirs),
        quote_include_dirs=tuple(quote_include_dirs),
        system_include_dirs=tuple(system_include_dirs),
        after_include_dirs=tuple(after_include_dirs),
        forced_includes=tuple(forced_includes),
        macro_includes=tuple(macro_includes),
        defines=tuple(defines),
        undefs=tuple(undefs),
        no_standard_includes=no_standard_includes,
    )
    return options, c_inputs, needs_stdin


def _run_clang(argv: Sequence[str]) -> int:
    try:
        completed = subprocess.run(("clang", *argv), check=False)
    except OSError as error:
        print(f"xcc: failed to execute clang: {error}", file=sys.stderr)
        return 1
    return completed.returncode


def _frontend_validation_enabled() -> bool:
    raw = os.environ.get("XCC_VALIDATE_FRONTEND", "").strip().lower()
    return raw not in {"", "0", "false", "no", "off"}


def main(argv: Sequence[str], *, stdin: TextIO | None = None) -> int:
    if not _frontend_validation_enabled():
        return _run_clang(argv)
    try:
        options, c_inputs, needs_stdin = _frontend_options_from_cc_argv(argv)
    except ValueError as error:
        print(f"xcc: driver error: {error}", file=sys.stderr)
        return 1

    try:
        for path in c_inputs:
            compile_path(path, options=options)
        if needs_stdin:
            filename, source = read_source("-", stdin=stdin)
            compile_source(source, filename=filename, options=options)
    except (OSError, UnicodeError) as error:
        print(f"xcc: I/O error: {error}", file=sys.stderr)
        return 1
    except FrontendError as error:
        print(error, file=sys.stderr)
        return 1

    return _run_clang(argv)
