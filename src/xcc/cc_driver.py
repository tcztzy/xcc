import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from xcc.diag import CodegenError, Diagnostic
from xcc.frontend import FrontendError, FrontendResult, compile_path, compile_source, read_source
from xcc.options import FrontendOptions, StdMode

TargetName = Literal["llvm", "aarch64-apple-darwin", "x86_64-linux-gnu", "evm"]
DriverAction = Literal["link", "compile", "assembly", "delegate"]

_LLVM_LLC_OVERVIEW = "OVERVIEW: llvm system compiler"
_LLVM_LLC_USAGE = "USAGE: llc [options] <input bitcode>"


@dataclass(frozen=True)
class DriverConfig:
    frontend_options: FrontendOptions
    clang_argv: tuple[str, ...]
    c_inputs: tuple[str, ...]
    non_c_inputs: tuple[str, ...]
    target: TargetName
    action: DriverAction
    output: str | None
    native_unsupported_flags: tuple[str, ...]
    evm_initcode: bool


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
            "--evm-initcode",
            "--target",
        } or arg.startswith("--target="):
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
    if arg.startswith("gnu"):
        return "gnu11"
    if arg.startswith("c") or arg in {"iso9899:1990", "iso9899:1999", "iso9899:2011"}:
        return "c11"
    raise ValueError(f"Unsupported language standard: {arg}")


def _parse_target(arg: str) -> TargetName:
    if arg == "llvm":
        return "llvm"
    if arg == "aarch64-apple-darwin":
        return "aarch64-apple-darwin"
    if arg == "x86_64-linux-gnu":
        return "x86_64-linux-gnu"
    if arg == "evm":
        return "evm"
    raise ValueError(f"Unsupported target: {arg}")


def _default_target() -> TargetName:
    machine = platform.machine().lower()
    if sys.platform.startswith("linux") and machine in {"x86_64", "amd64"}:
        return "x86_64-linux-gnu"
    return "llvm"


def _unique_tool_candidates(candidates: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return tuple(result)


def _llvm_config_bindir(llvm_config: str) -> str | None:
    try:
        completed = subprocess.run(
            (llvm_config, "--bindir"),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    bindir = (completed.stdout or "").strip().splitlines()
    if not bindir:
        return None
    return bindir[0]


def _llc_candidates() -> tuple[str, ...]:
    candidates: list[str] = []

    llvm_config = os.environ.get("LLVM_CONFIG") or shutil.which("llvm-config")
    if llvm_config:
        bindir = _llvm_config_bindir(llvm_config)
        if bindir:
            candidates.append(str(Path(bindir) / "llc"))

    path_llc = shutil.which("llc")
    if path_llc:
        candidates.append(path_llc)

    return _unique_tool_candidates(candidates)


def _is_llvm_llc(path: str) -> bool:
    try:
        completed = subprocess.run(
            (path, "--help"),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    stdout = completed.stdout or ""
    return completed.returncode == 0 and _LLVM_LLC_OVERVIEW in stdout and _LLVM_LLC_USAGE in stdout


def _find_llc() -> str:
    explicit = os.environ.get("XCC_LLC")
    if explicit:
        return explicit

    for candidate in _llc_candidates():
        if _is_llvm_llc(candidate):
            return candidate
    raise ValueError("unable to find LLVM llc; set XCC_LLC or put LLVM llc on PATH")


def _parse_driver_config(argv: tuple[str, ...] | list[str]) -> DriverConfig:
    hosted = True
    std: StdMode = "gnu11"
    include_dirs: list[str] = []
    quote_include_dirs: list[str] = []
    system_include_dirs: list[str] = []
    after_include_dirs: list[str] = []
    forced_includes: list[str] = []
    macro_includes: list[str] = []
    defines: list[str] = []
    undefs: list[str] = []
    no_standard_includes = False
    target = _default_target()
    action: DriverAction = "link"
    output: str | None = None
    evm_initcode = False
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
        if arg == "--backend" or arg.startswith("--backend="):
            raise ValueError("--backend has been removed; use --target=llvm (default)")
        if arg == "--no-backend-fallback":
            raise ValueError("--no-backend-fallback has been removed; XCC no longer falls back")
        if arg == "--target":
            target_value, index = _take_value(argv, index, "--target")
            target = _parse_target(target_value)
            continue
        if arg.startswith("--target="):
            target = _parse_target(arg.split("=", 1)[1])
            continue
        if arg == "--evm-initcode":
            evm_initcode = True
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
        if arg in {"--version", "-V"}:
            # Handled in main() early; skip here.
            clang_argv.append(arg)
            continue
        if arg == "-v":
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
        for opt, option_values in (
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
            option_values.append(value)
            if arg == opt:
                clang_argv.extend((arg, value))
            else:
                clang_argv.append(arg)
            matched = True
            break
        if matched:
            continue
        for opt in ("-L", "-l"):
            taken = _take_joined_or_value(argv, index, arg, opt)
            if taken is None:
                continue
            value, index = taken
            if arg == opt:
                clang_argv.extend((arg, value))
            else:
                clang_argv.append(arg)
            matched = True
            break
        if matched:
            continue
        if arg == "-framework":
            value, index = _take_value(argv, index, "-framework")
            clang_argv.extend((arg, value))
            continue
        if (
            arg.startswith("-Wl,")
            or arg.startswith("-O")
            or arg.startswith("-W")
            or arg in {"-g", "-pipe", "-pthread", "-fno-strict-aliasing", "-fPIC", "-fpic"}
        ):
            clang_argv.append(arg)
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
        std=std,
        hosted=False if target == "evm" else hosted,
        include_dirs=tuple(include_dirs),
        quote_include_dirs=tuple(quote_include_dirs),
        system_include_dirs=tuple(system_include_dirs),
        after_include_dirs=tuple(after_include_dirs),
        forced_includes=tuple(forced_includes),
        macro_includes=tuple(macro_includes),
        defines=tuple(defines),
        undefs=tuple(undefs),
        no_standard_includes=no_standard_includes,
        host_machine=(
            "arm64"
            if target == "aarch64-apple-darwin"
            else "x86_64"
            if target == "x86_64-linux-gnu"
            else None
        ),
        target_os=(
            "darwin"
            if target == "aarch64-apple-darwin"
            else "linux"
            if target == "x86_64-linux-gnu"
            else None
        ),
        strip_gnu_asm_statements=target == "x86_64-linux-gnu",
    )
    return DriverConfig(
        frontend_options=options,
        clang_argv=tuple(clang_argv),
        c_inputs=tuple(c_inputs),
        non_c_inputs=tuple(non_c_inputs),
        target=target,
        action=action,
        output=output,
        native_unsupported_flags=tuple(native_unsupported_flags),
        evm_initcode=evm_initcode,
    )


def _run_tool(tool: str, argv: tuple[str, ...] | list[str]) -> int:
    try:
        completed = subprocess.run((tool, *argv), check=False)
    except OSError as error:
        print(f"xcc: failed to execute {tool}: {error}", file=sys.stderr)
        return 1
    return completed.returncode


def _delegate_tool(target: TargetName) -> str:
    return "cc" if target == "x86_64-linux-gnu" else "clang"


def _drop_x86_64_linux_latomic(argv: list[str] | tuple[str, ...]) -> list[str]:
    filtered: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        index += 1
        if arg == "-latomic":
            continue
        if arg == "-l" and index < len(argv) and argv[index] == "atomic":
            index += 1
            continue
        filtered.append(arg)
    return filtered


def _delegate_argv(config: DriverConfig) -> tuple[str, ...] | list[str]:
    if config.target == "x86_64-linux-gnu":
        return _drop_x86_64_linux_latomic(config.clang_argv)
    return config.clang_argv


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


def _output_for_input(config: DriverConfig, path: str) -> str:
    return config.output or _default_output(
        path,
        config.action,
        config.target,
        evm_initcode=config.evm_initcode,
    )


def _write_text_output(output: str, text: str) -> None:
    if output == "-":
        sys.stdout.write(text)
    else:
        Path(output).write_text(text, encoding="utf-8")


def _emit_assembly_outputs(
    config: DriverConfig,
    results: list[FrontendResult],
    generate: Callable[[FrontendResult], str],
) -> int:
    for path, result in zip(config.c_inputs, results, strict=True):
        _write_text_output(_output_for_input(config, path), generate(result))
    return 0


def _compile_or_link_generated_outputs(
    config: DriverConfig,
    results: list[FrontendResult],
    *,
    suffix: str,
    generate: Callable[[FrontendResult], str],
    object_cmd: Callable[[Path, Path], list[str]],
    tool_error: str,
    link_cmd: Callable[[list[str]], list[str]],
) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        objects: list[str] = []
        for index, (path, result) in enumerate(zip(config.c_inputs, results, strict=True)):
            generated_path = Path(tmp) / f"input{index}.{suffix}"
            generated_path.write_text(generate(result), encoding="utf-8")
            obj_path = Path(tmp) / f"input{index}.o"
            compile_result = subprocess.run(
                object_cmd(generated_path, obj_path),
                check=False,
                capture_output=True,
                text=True,
            )
            if compile_result.returncode != 0:
                stderr = (compile_result.stderr or "").strip()
                raise CodegenError(
                    Diagnostic("codegen", result.filename, f"{tool_error}: {stderr}")
                )
            if config.action == "compile":
                shutil.copy(str(obj_path), _output_for_input(config, path))
                continue
            objects.append(str(obj_path))
        if config.action == "compile":
            return 0
        link_result = subprocess.run(link_cmd(objects), check=False)
        if link_result.returncode != 0:
            print(f"xcc: link failed with exit code {link_result.returncode}", file=sys.stderr)
            return 1
    return 0


def _link_argv_with_objects(
    config: DriverConfig,
    objects: list[str],
    *,
    linker: str = "clang",
) -> list[str]:
    replacements = iter(objects)
    link_args: list[str] = []
    c_inputs = list(config.c_inputs)
    skip_next = False
    for arg in config.clang_argv:
        if skip_next:
            skip_next = False
            continue
        if arg == "-x":
            skip_next = True
            continue
        if arg.startswith("-x") and arg != "-x":
            continue
        if c_inputs and arg == c_inputs[0]:
            link_args.append(next(replacements))
            c_inputs.pop(0)
            continue
        link_args.append(arg)
    return [linker, *link_args]


def main(argv: tuple[str, ...] | list[str], *, stdin: TextIO | None = None) -> int:
    if set(argv) & {"--version", "-V"}:
        print("xcc 0.2.0a1", file=sys.stderr)
        print(f"Target: {_default_target()}", file=sys.stderr)
        return 0

    try:
        config = _parse_driver_config(argv)
    except ValueError as error:
        print(f"xcc: driver error: {error}", file=sys.stderr)
        return 1

    if config.evm_initcode and (config.target != "evm" or config.action != "compile"):
        print(
            "xcc: driver error: --evm-initcode requires --target=evm -c",
            file=sys.stderr,
        )
        return 1

    if not config.c_inputs:
        return _run_tool(_delegate_tool(config.target), _delegate_argv(config))

    if config.action == "delegate":
        return _run_tool(_delegate_tool(config.target), _delegate_argv(config))

    if config.native_unsupported_flags:
        flags = " ".join(config.native_unsupported_flags)
        print(f"xcc: unsupported option(s) for target {config.target}: {flags}", file=sys.stderr)
        return 1

    if (
        config.action in {"assembly", "compile"}
        and config.output is not None
        and len(config.c_inputs) > 1
    ):
        print(
            "xcc: driver error: cannot specify -o when generating multiple output files",
            file=sys.stderr,
        )
        return 1

    try:
        results = _compile_frontend_inputs(config, stdin=stdin)
    except FrontendError as error:
        print(error, file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"xcc: driver error: {error}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError) as error:
        print(f"xcc: I/O error: {error}", file=sys.stderr)
        return 1

    try:
        if config.target == "llvm":
            from xcc.codegen import generate_llvm_ir

            if config.action == "assembly":
                return _emit_assembly_outputs(config, results, generate_llvm_ir)

            llc_path = _find_llc()

            def llvm_object_cmd(source: Path, obj: Path) -> list[str]:
                return [
                    llc_path,
                    "-O0",
                    "-filetype=obj",
                    str(source),
                    "-o",
                    str(obj),
                ]

            def llvm_link_cmd(objects: list[str]) -> list[str]:
                return _link_argv_with_objects(config, objects)

            return _compile_or_link_generated_outputs(
                config,
                results,
                suffix="ll",
                generate=generate_llvm_ir,
                object_cmd=llvm_object_cmd,
                tool_error="llc failed",
                link_cmd=llvm_link_cmd,
            )

        if config.target == "aarch64-apple-darwin":
            from xcc.aarch64_asm import generate_aarch64_asm

            if config.action == "assembly":
                return _emit_assembly_outputs(config, results, generate_aarch64_asm)

            def aarch64_object_cmd(source: Path, obj: Path) -> list[str]:
                return [
                    "clang",
                    "-target",
                    config.target,
                    "-c",
                    str(source),
                    "-o",
                    str(obj),
                ]

            def aarch64_link_cmd(objects: list[str]) -> list[str]:
                command = _link_argv_with_objects(config, objects)
                command[1:1] = ["-target", config.target]
                return command

            return _compile_or_link_generated_outputs(
                config,
                results,
                suffix="s",
                generate=generate_aarch64_asm,
                object_cmd=aarch64_object_cmd,
                tool_error="clang assembler failed",
                link_cmd=aarch64_link_cmd,
            )

        if config.target == "x86_64-linux-gnu":
            from xcc.x86_64_asm import generate_x86_64_asm

            if config.action == "assembly":
                return _emit_assembly_outputs(config, results, generate_x86_64_asm)

            def x86_64_object_cmd(source: Path, obj: Path) -> list[str]:
                return [
                    "cc",
                    "-c",
                    str(source),
                    "-o",
                    str(obj),
                ]

            def x86_64_link_cmd(objects: list[str]) -> list[str]:
                return _drop_x86_64_linux_latomic(
                    _link_argv_with_objects(config, objects, linker="cc")
                )

            return _compile_or_link_generated_outputs(
                config,
                results,
                suffix="s",
                generate=generate_x86_64_asm,
                object_cmd=x86_64_object_cmd,
                tool_error="cc assembler failed",
                link_cmd=x86_64_link_cmd,
            )

        if config.target == "evm":
            from xcc.evm import generate_evm_asm, generate_evm_bytecode, generate_evm_initcode

            if config.action == "link":
                raise ValueError("EVM target does not support link action")
            if config.action == "assembly":
                return _emit_assembly_outputs(config, results, generate_evm_asm)
            if config.evm_initcode:

                def generate_evm_initcode_text(result: FrontendResult) -> str:
                    return generate_evm_initcode(result) + "\n"

                return _emit_assembly_outputs(
                    config,
                    results,
                    generate_evm_initcode_text,
                )

            def generate_evm_bytecode_text(result: FrontendResult) -> str:
                return generate_evm_bytecode(result) + "\n"

            return _emit_assembly_outputs(
                config,
                results,
                generate_evm_bytecode_text,
            )
    except Exception as error:
        print(f"xcc: {error}", file=sys.stderr)
        return 1

    raise AssertionError(f"unhandled target: {config.target}")


def _default_output(
    path: str,
    action: str,
    target: TargetName,
    *,
    evm_initcode: bool = False,
) -> str:
    if action == "link":
        return "a.out"
    if action == "assembly" and target == "llvm":
        return str(Path(path).with_suffix(".ll"))
    if action == "assembly" and target in {"aarch64-apple-darwin", "x86_64-linux-gnu"}:
        return str(Path(path).with_suffix(".s"))
    if action == "assembly" and target == "evm":
        return str(Path(path).with_suffix(".evmasm"))
    if action == "compile" and target == "evm" and evm_initcode:
        return str(Path(path).with_suffix(".init.bin"))
    if action == "compile" and target == "evm":
        return str(Path(path).with_suffix(".bin"))
    return str(Path(path).with_suffix(".o"))
