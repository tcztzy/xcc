import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from xcc.diag import Diagnostic
from xcc.frontend import FrontendError, FrontendResult, compile_path, compile_source, read_source
from xcc.options import FrontendOptions

BackendMode = Literal["auto", "xcc", "clang"]
DriverAction = Literal["link", "compile", "assembly", "delegate"]


@dataclass(frozen=True)
class DriverConfig:
    frontend_options: FrontendOptions
    clang_argv: tuple[str, ...]
    c_inputs: tuple[str, ...]
    non_c_inputs: tuple[str, ...]
    backend: BackendMode
    no_backend_fallback: bool
    action: DriverAction
    output: str | None
    native_unsupported_flags: tuple[str, ...]


def looks_like_cc_driver(argv: tuple[str, ...] | list[str]) -> bool:
    if not argv:
        return False
    index = 0
    c_inputs = 0
    while index < len(argv):
        arg = argv[index]
        index += 1
        if arg == "--frontend":
            return False
        if arg.startswith("--dump-"):
            return False
        if arg == "--diag-format" or arg.startswith("--diag-format="):
            return False
        if arg in {
            "-c",
            "-S",
            "-E",
            "-M",
            "-MM",
            "--version",
            "-v",
            "-V",
            "--backend",
            "--no-backend-fallback",
        } or arg.startswith("--backend="):
            return True
        if arg in {"-o", "-x"}:
            return True
        if arg.startswith("-o") and arg != "-o":
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
        if not arg.startswith("-") and arg.endswith(".c"):
            c_inputs += 1
    return c_inputs > 0


def _take_value(argv: tuple[str, ...] | list[str], index: int, opt: str) -> tuple[str, int]:
    if index >= len(argv):
        raise ValueError(f"Missing value for {opt}")
    return argv[index], index + 1


def _take_joined_or_value(
    argv: tuple[str, ...] | list[str],
    index: int,
    arg: str,
    opt: str,
) -> tuple[str, int] | None:
    if arg == opt:
        return _take_value(argv, index, opt)
    if arg.startswith(opt) and arg != opt:
        return arg[len(opt):], index
    return None


def _parse_std(arg: str) -> str:
    if arg in {"c11", "gnu11"}:
        return arg
    raise ValueError(f"Unsupported language standard: {arg}")


def _parse_backend(arg: str) -> BackendMode:
    if arg in {"auto", "xcc", "clang"}:
        return arg  # type: ignore[return-value]
    raise ValueError(f"Unsupported backend: {arg}")


def _parse_driver_config(argv: tuple[str, ...] | list[str]) -> DriverConfig:
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
    backend: BackendMode = "auto"
    no_backend_fallback = False
    action: DriverAction = "link"
    output: str | None = None
    language: str | None = None
    c_inputs: list[str] = []
    non_c_inputs: list[str] = []
    clang_argv: list[str] = []
    native_unsupported_flags: list[str] = []

    index = 0
    while index < len(argv):
        arg = argv[index]
        index += 1
        if arg == "--":
            clang_argv.append(arg)
            for rest in argv[index:]:
                clang_argv.append(rest)
                if not rest.startswith("-") and (rest.endswith(".c") or language == "c"):
                    c_inputs.append(rest)
                elif not rest.startswith("-"):
                    non_c_inputs.append(rest)
            break
        if arg == "--backend":
            backend_value, index = _take_value(argv, index, "--backend")
            backend = _parse_backend(backend_value)
            continue
        if arg.startswith("--backend="):
            backend = _parse_backend(arg.split("=", 1)[1])
            continue
        if arg == "--no-backend-fallback":
            no_backend_fallback = True
            continue
        if arg in {"-E", "-M", "-MM"}:
            action = "delegate"
            clang_argv.append(arg)
            continue
        if arg == "-S":
            if action != "delegate":
                action = "assembly"
            clang_argv.append(arg)
            continue
        if arg == "-c":
            if action != "delegate":
                action = "compile"
            clang_argv.append(arg)
            continue
        if arg in {"--version", "-v", "-V"}:
            action = "delegate"
            clang_argv.append(arg)
            continue
        if arg == "-x":
            language, index = _take_value(argv, index, "-x")
            if language == "none":
                language = None
            clang_argv.extend((arg, argv[index - 1]))
            continue
        if arg.startswith("-x") and arg != "-x":
            language = arg[2:]
            if language == "none":
                language = None
            clang_argv.append(arg)
            continue
        if arg == "-std":
            std_value, index = _take_value(argv, index, "-std")
            _parse_std(std_value)
            clang_argv.extend((arg, std_value))
            continue
        if arg.startswith("-std="):
            _parse_std(arg.split("=", 1)[1])
            clang_argv.append(arg)
            continue
        if arg == "-fhosted":
            hosted = True
            clang_argv.append(arg)
            continue
        if arg == "-ffreestanding":
            hosted = False
            clang_argv.append(arg)
            continue
        if arg == "-nostdinc":
            no_standard_includes = True
            clang_argv.append(arg)
            continue
        taken = _take_joined_or_value(argv, index, arg, "-o")
        if taken is not None:
            output, index = taken
            if arg == "-o":
                clang_argv.extend((arg, output))
            else:
                clang_argv.append(arg)
            continue
        matched = False
        for opt, target in (
            ("-I", include_dirs),
            ("-iquote", quote_include_dirs),
            ("-isystem", system_include_dirs),
            ("-idirafter", after_include_dirs),
            ("-include", forced_includes),
            ("-imacros", macro_includes),
            ("-D", defines),
            ("-U", undefs),
        ):
            taken = _take_joined_or_value(argv, index, arg, opt)
            if taken is None:
                continue
            value, index = taken
            target.append(value)
            if arg == opt:
                clang_argv.extend((arg, value))
            else:
                clang_argv.append(arg)
            matched = True
            break
        if matched:
            continue
        clang_argv.append(arg)
        if arg == "-":
            if language == "c":
                c_inputs.append(arg)
            else:
                non_c_inputs.append(arg)
            continue
        if not arg.startswith("-"):
            if arg.endswith(".c") or language == "c":
                c_inputs.append(arg)
            else:
                non_c_inputs.append(arg)
            continue
        native_unsupported_flags.append(arg)

    options = FrontendOptions(
        std="gnu11",
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
    return DriverConfig(
        frontend_options=options,
        clang_argv=tuple(clang_argv),
        c_inputs=tuple(c_inputs),
        non_c_inputs=tuple(non_c_inputs),
        backend=backend,
        no_backend_fallback=no_backend_fallback,
        action=action,
        output=output,
        native_unsupported_flags=tuple(native_unsupported_flags),
    )


def _run_clang(argv: tuple[str, ...] | list[str]) -> int:
    try:
        completed = subprocess.run(("clang", *argv), check=False)
    except OSError as error:
        print(f"xcc: failed to execute clang: {error}", file=sys.stderr)
        return 1
    return completed.returncode


def _compile_frontend_inputs(
    config: DriverConfig,
    *,
    stdin: TextIO | None,
) -> list[FrontendResult]:
    results: list[FrontendResult] = []
    stdin_consumed = False
    for path in config.c_inputs:
        if path == "-":
            if stdin_consumed:
                raise ValueError("stdin can only be compiled once")
            filename, source = read_source("-", stdin=stdin)
            results.append(
                compile_source(source, filename=filename, options=config.frontend_options)
            )
            stdin_consumed = True
            continue
        results.append(compile_path(path, options=config.frontend_options))
    return results


def main(argv: tuple[str, ...] | list[str], *, stdin: TextIO | None = None) -> int:
    try:
        config = _parse_driver_config(argv)
    except ValueError as error:
        print(f"xcc: driver error: {error}", file=sys.stderr)
        return 1

    if not config.c_inputs:
        return _run_clang(config.clang_argv)

    # Always run frontend for validation
    try:
        results = _compile_frontend_inputs(config, stdin=stdin)
    except FrontendError as error:
        if config.backend == "xcc":
            print(error, file=sys.stderr)
            return 1
        print(f"xcc: falling back to clang: {error}", file=sys.stderr)
        return _run_clang(config.clang_argv)
    except ValueError as error:
        print(f"xcc: driver error: {error}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError) as error:
        print(f"xcc: I/O error: {error}", file=sys.stderr)
        return 1

    # ClangIR backend
    if config.backend == "xcc" or config.backend == "auto":
        from xcc.cir_codegen import generate_cir

        for result in results:
            cir_text = generate_cir(result)
            if config.action == "assembly":
                output = config.output or "-"
                if output == "-":
                    sys.stdout.write(cir_text)
                else:
                    Path(output).write_text(cir_text, encoding="utf-8")
                continue
            # For compile/link: write .cir, shell out to cir-translate + llc
            # For now: just print the CIR and fall back to clang
            print(
                f"xcc: CIR generated, but cir-translate not yet available. "
                f"Falling back to clang.",
                file=sys.stderr,
            )
            return _run_clang(config.clang_argv)
        return 0

    # clang: frontend passed, delegate to clang
    return _run_clang(config.clang_argv)
