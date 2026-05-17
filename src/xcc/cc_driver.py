import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from xcc.codegen import generate_native_assembly, native_backend_error
from xcc.diag import CodegenError, Diagnostic
from xcc.frontend import FrontendError, FrontendResult, compile_path, compile_source, read_source
from xcc.options import FrontendOptions, StdMode

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
        return arg[len(opt) :], index
    return None


def _parse_std(arg: str) -> StdMode:
    if arg in {"c11", "gnu11"}:
        return arg  # type: ignore[return-value]
    raise ValueError(f"Unsupported language standard: {arg}")


def _parse_backend(arg: str) -> BackendMode:
    if arg in {"auto", "xcc", "clang"}:
        return arg  # type: ignore[return-value]
    raise ValueError(f"Unsupported backend: {arg}")


def _parse_driver_config(argv: tuple[str, ...] | list[str]) -> DriverConfig:
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
            std = _parse_std(std_value)
            clang_argv.extend((arg, std_value))
            continue
        if arg.startswith("-std="):
            std = _parse_std(arg.split("=", 1)[1])
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
        std="gnu11",  # Always use gnu11 frontend mode for system-header compatibility
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


def _native_shape_error(config: DriverConfig, result: FrontendResult) -> CodegenError | None:
    if config.action == "delegate":
        return native_backend_error(
            result.filename,
            "Native backend does not support this driver action",
            code="XCC-CG-0004",
        )
    if len(config.c_inputs) != 1:
        return native_backend_error(
            result.filename,
            "Native backend currently supports exactly one C input",
            code="XCC-CG-0004",
        )
    if config.non_c_inputs:
        return native_backend_error(
            result.filename,
            "Native backend does not support additional non-C inputs",
            code="XCC-CG-0004",
        )
    if config.native_unsupported_flags:
        return native_backend_error(
            result.filename,
            f"Native backend does not support driver flag: {config.native_unsupported_flags[0]}",
            code="XCC-CG-0004",
        )
    return None


def _default_output(path: str, action: DriverAction) -> str:
    if action == "link":
        return "a.out"
    if path == "-":
        return "out.s" if action == "assembly" else "out.o"
    suffix = ".s" if action == "assembly" else ".o"
    return str(Path(path).with_suffix(suffix))


def _run_native_backend(config: DriverConfig, result: FrontendResult) -> int:
    shape_error = _native_shape_error(config, result)
    if shape_error is not None:
        raise shape_error
    assembly = generate_native_assembly(result)
    output = (
        config.output
        if config.output is not None
        else _default_output(config.c_inputs[0], config.action)
    )
    if config.action == "assembly":
        if output == "-":
            sys.stdout.write(assembly)
            return 0
        Path(output).write_text(assembly, encoding="utf-8")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        asm_path = Path(tmp) / "input.s"
        asm_path.write_text(assembly, encoding="utf-8")
        cmd = ["clang"]
        if config.action == "compile":
            cmd.extend(("-c", str(asm_path), "-o", output))
        else:
            cmd.extend((str(asm_path), "-o", output))
        try:
            completed = subprocess.run(tuple(cmd), check=False)
        except OSError as error:
            raise CodegenError(
                Diagnostic(
                    "codegen",
                    result.filename,
                    f"Failed to execute clang for native backend: {error}",
                    code="XCC-CG-0002",
                )
            ) from error
        if completed.returncode != 0:
            raise CodegenError(
                Diagnostic(
                    "codegen",
                    result.filename,
                    f"Native backend tool invocation failed with exit code {completed.returncode}",
                    code="XCC-CG-0002",
                )
            )
    return 0


def main(argv: tuple[str, ...] | list[str], *, stdin: TextIO | None = None) -> int:
    try:
        config = _parse_driver_config(argv)
    except ValueError as error:
        print(f"xcc: driver error: {error}", file=sys.stderr)
        return 1

    if not config.c_inputs:
        return _run_clang(config.clang_argv)

    try:
        results = _compile_frontend_inputs(config, stdin=stdin)
    except FrontendError as error:
        if config.backend == "clang":
            print(f"xcc: warning: {error}", file=sys.stderr)
            return _run_clang(config.clang_argv)
        print(error, file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"xcc: driver error: {error}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError) as error:
        print(f"xcc: I/O error: {error}", file=sys.stderr)
        return 1

    if config.backend == "clang":
        return _run_clang(config.clang_argv)

    if config.backend == "xcc":
        try:
            return _run_native_backend(config, results[0])
        except CodegenError as error:
            print(error, file=sys.stderr)
            return 1

    try:
        return _run_native_backend(config, results[0])
    except CodegenError as error:
        if config.no_backend_fallback or error.diagnostic.code == "XCC-CG-0002":
            print(error, file=sys.stderr)
            return 1
        print(
            f"xcc: falling back to clang backend: {error.diagnostic.message}",
            file=sys.stderr,
        )
        return _run_clang(config.clang_argv)
