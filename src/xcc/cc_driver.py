import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from xcc.codegen import generate_llvm_ir
from xcc.diag import CodegenError, Diagnostic
from xcc.frontend import (
    AotFrontendTimings,
    FrontendError,
    FrontendResult,
    _aot_compile_source_unchecked,
    _aot_monotonic_ns,
    compile_path,
    compile_source,
    read_source,
)
from xcc.lexer import LexerError
from xcc.llvm_tools import (
    find_llc,
    is_llvm_llc,
    llc_candidates,
    llvm_config_bindir,
    unique_tool_candidates,
)
from xcc.options import FrontendOptions, StdMode, TargetOS
from xcc.parser import ParserError
from xcc.preprocessor import PreprocessorError
from xcc.sema import SemaError

int32 = int

TargetName = Literal["llvm", "aarch64-apple-darwin", "x86_64-linux-gnu", "evm"]
DriverAction = Literal["link", "compile", "assembly", "delegate"]

_AOT_BOOTSTRAP_LLC = "/opt/homebrew/opt/llvm/bin/llc"


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
    debug_info: bool = False
    frame_pointer: bool = False
    unwind_tables: bool = False


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


def _frontend_target_identity(target: TargetName) -> tuple[TargetOS | None, str | None]:
    if target == "aarch64-apple-darwin":
        return "darwin", "arm64"
    if target == "x86_64-linux-gnu":
        return "linux", "x86_64"
    if target == "llvm":
        target_os: TargetOS = "linux" if sys.platform.startswith("linux") else "darwin"
        return target_os, platform.machine().lower()
    if target == "evm":
        return "evm", "evm"
    return None, None


def _llvm_config_bindir(llvm_config: str) -> str | None:
    return llvm_config_bindir(llvm_config)


def _unique_tool_candidates(candidates: list[str]) -> tuple[str, ...]:
    return unique_tool_candidates(candidates)


def _llc_candidates() -> tuple[str, ...]:
    return llc_candidates()


def _is_llvm_llc(path: str) -> bool:
    return is_llvm_llc(path)


def _find_llc() -> str:
    return find_llc()


def _llvm_target_triple(config: DriverConfig) -> str:
    if config.target == "x86_64-linux-gnu":
        return "x86_64-unknown-linux-gnu"
    if config.target == "aarch64-apple-darwin":
        return "arm64-apple-macosx11.0.0"
    if sys.platform.startswith("linux") and platform.machine().lower() in {"x86_64", "amd64"}:
        return "x86_64-unknown-linux-gnu"
    return "arm64-apple-macosx11.0.0"


def _llvm_object_argv(
    config: DriverConfig,
    llc_path: str,
    source: Path,
    output: Path,
) -> list[str]:
    command = [llc_path, "-O0", "-filetype=obj"]
    if config.frame_pointer:
        command.append("--frame-pointer=all")
    if config.unwind_tables:
        command.append("--emit-dwarf-unwind=always")
    if config.debug_info:
        command.append("--dwarf-version=4")
    command.extend((str(source), "-o", str(output)))
    return command


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
    debug_info = False
    frame_pointer = False
    unwind_tables = False

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
        if arg in {"-g", "-g1", "-g2", "-g3", "-ggdb", "-gline-tables-only"} or arg.startswith(
            "-gdwarf-"
        ):
            debug_info = True
            frame_pointer = True
            unwind_tables = True
            clang_argv.append(arg)
            continue
        if arg == "-g0":
            debug_info = False
            frame_pointer = False
            unwind_tables = False
            clang_argv.append(arg)
            continue
        if arg == "-fno-omit-frame-pointer":
            frame_pointer = True
            clang_argv.append(arg)
            continue
        if arg == "-fomit-frame-pointer":
            frame_pointer = False
            clang_argv.append(arg)
            continue
        if arg in {"-fasynchronous-unwind-tables", "-funwind-tables"}:
            unwind_tables = True
            clang_argv.append(arg)
            continue
        if arg in {"-fno-asynchronous-unwind-tables", "-fno-unwind-tables"}:
            unwind_tables = False
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
            or arg in {"-pipe", "-pthread", "-fno-strict-aliasing", "-fPIC", "-fpic"}
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

    target_os, host_machine = _frontend_target_identity(target)
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
        host_machine=host_machine,
        target_os=target_os,
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
        debug_info=debug_info,
        frame_pointer=frame_pointer,
        unwind_tables=unwind_tables,
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


def _aot_smoke_llvm_path(object_path: str) -> str:
    return object_path + ".ll"


def _aot_smoke_llc_argv(
    llvm_path: str,
    object_path: str,
    debug: bool = False,
) -> tuple[str, ...]:
    argv: tuple[str, ...] = (
        "/opt/homebrew/opt/llvm/bin/llc",
        "-O0",
        "-filetype=obj",
    )
    if debug:
        argv = argv + (
            "--frame-pointer=all",
            "--emit-dwarf-unwind=always",
            "--dwarf-version=4",
        )
    return argv + (llvm_path, "-o", object_path)


def _aot_render_timing_json(
    success: bool,
    failed_stage: str,
    total_ns: int,
    preprocessing_ns: int,
    parser_ns: int,
    sema_ns: int,
    codegen_ns: int,
    llc_ns: int,
) -> str:
    preprocessing_status = "ok"
    parser_status = "ok"
    sema_status = "ok"
    codegen_status = "ok"
    llc_status = "ok"
    if failed_stage == "preprocessing":
        preprocessing_status = "error"
        parser_status = "not_run"
        sema_status = "not_run"
        codegen_status = "not_run"
        llc_status = "not_run"
    elif failed_stage == "parser":
        parser_status = "error"
        sema_status = "not_run"
        codegen_status = "not_run"
        llc_status = "not_run"
    elif failed_stage == "sema":
        sema_status = "error"
        codegen_status = "not_run"
        llc_status = "not_run"
    elif failed_stage == "codegen":
        codegen_status = "error"
        llc_status = "not_run"
    elif failed_stage == "llc":
        llc_status = "error"
    success_text = "true" if success else "false"
    failed_stage_text = "null" if failed_stage == "" else '"' + failed_stage + '"'
    return (
        '{"schema":"xcc.compile-timing.v1","clock":"monotonic",'
        '"unit":"nanoseconds","success":'
        + success_text
        + ',"failed_stage":'
        + failed_stage_text
        + ',"total_ns":'
        + str(total_ns)
        + ',"phases":{'
        + '"preprocessing":{"duration_ns":'
        + str(preprocessing_ns)
        + ',"status":"'
        + preprocessing_status
        + '"},"parser":{"duration_ns":'
        + str(parser_ns)
        + ',"status":"'
        + parser_status
        + '"},"sema":{"duration_ns":'
        + str(sema_ns)
        + ',"status":"'
        + sema_status
        + '"},"codegen":{"duration_ns":'
        + str(codegen_ns)
        + ',"status":"'
        + codegen_status
        + '"},"llc":{"duration_ns":'
        + str(llc_ns)
        + ',"status":"'
        + llc_status
        + '"}}}\n'
    )


def _aot_arg_is_c_source(arg: str) -> bool:
    return arg.endswith(".c")


def _aot_arg_is_object_file(arg: str) -> bool:
    return arg.endswith(".o")


def _aot_arg_is_existing_link_input(arg: str) -> bool:
    return arg.endswith(".o") or arg.endswith(".a") or arg.endswith(".so") or arg.endswith(".dylib")


def _aot_existing_link_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = ["cc"]
    index = 1
    while index < len(argv):
        result.append(argv[index])
        index += 1
    return tuple(result)


def _aot_default_object_path(source_path: str) -> str:
    if source_path.endswith(".c"):
        return source_path[:-2] + ".o"
    return source_path + ".o"


def _aot_link_object_path(output_path: str) -> str:
    return output_path + ".o"


def _aot_is_linker_flag(arg: str) -> bool:
    return (
        arg.startswith("-L")
        or arg.startswith("-F")
        or arg.startswith("-l")
        or arg.startswith("-Wl,")
    )


def _aot_link_argv(
    object_path: str,
    output_path: str,
    link_flags: tuple[str, ...],
) -> tuple[str, ...]:
    argv: tuple[str, ...] = ("cc", object_path, "-o", output_path)
    for flag in link_flags:
        argv = argv + (flag,)
    return argv


def _aot_dsymutil_argv(executable_path: str) -> tuple[str, ...]:
    return ("/usr/bin/dsymutil", executable_path)


def _aot_read_text_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _aot_write_text_file(path: str, text: str) -> bool:
    Path(path).write_text(text, encoding="utf-8")
    return True


def _aot_default_system_include_dirs() -> tuple[str, ...]:
    return (
        "/Applications/Xcode.app/Contents/Developer/Toolchains/"
        "XcodeDefault.xctoolchain/usr/lib/clang/21/include",
        "/Applications/Xcode.app/Contents/Developer/Platforms/"
        "MacOSX.platform/Developer/SDKs/MacOSX.sdk/usr/include",
        "/Applications/Xcode.app/Contents/Developer/Platforms/"
        "MacOSX.platform/Developer/SDKs/MacOSX26.5.sdk/usr/include",
        "/usr/include",
    )


def _aot_bootstrap_frontend_options(
    include_dirs: tuple[str, ...],
    defines: tuple[str, ...],
    undefs: tuple[str, ...],
    std: str,
) -> FrontendOptions:
    return FrontendOptions(
        std="gnu11" if std == "gnu11" else "c11",
        target_os="darwin",
        host_machine="arm64",
        include_dirs=include_dirs,
        system_include_dirs=_aot_default_system_include_dirs(),
        defines=defines,
        undefs=undefs,
    )


def _aot_compile_source_to_llvm_ir_unchecked(
    source_path: str,
    source_text: str,
    include_dirs: tuple[str, ...],
    defines: tuple[str, ...],
    undefs: tuple[str, ...],
    std: str,
    debug: bool = False,
) -> str:
    options = _aot_bootstrap_frontend_options(include_dirs, defines, undefs, std)
    result: FrontendResult = _aot_compile_source_unchecked(source_text, source_path, options)
    return generate_llvm_ir(result, debug=debug)


def _aot_compile_source_to_llvm_ir_timed(
    source_path: str,
    source_text: str,
    include_dirs: tuple[str, ...],
    defines: tuple[str, ...],
    undefs: tuple[str, ...],
    std: str,
    debug: bool = False,
) -> tuple[str, int, int, int, int, str]:
    options = _aot_bootstrap_frontend_options(include_dirs, defines, undefs, std)
    timings = AotFrontendTimings()
    try:
        result = _aot_compile_source_unchecked(
            source_text,
            source_path,
            options,
            timings,
        )
    except PreprocessorError:
        return "", timings.preprocessing_ns, 0, 0, 0, "preprocessing"
    except (LexerError, ParserError):
        return (
            "",
            timings.preprocessing_ns,
            timings.parser_ns,
            0,
            0,
            "parser",
        )
    except SemaError:
        return (
            "",
            timings.preprocessing_ns,
            timings.parser_ns,
            timings.sema_ns,
            0,
            "sema",
        )
    codegen_start = _aot_monotonic_ns()
    try:
        llvm_text = generate_llvm_ir(result, debug=debug)
    except CodegenError:
        codegen_ns = _aot_monotonic_ns() - codegen_start
        return (
            "",
            timings.preprocessing_ns,
            timings.parser_ns,
            timings.sema_ns,
            codegen_ns,
            "codegen",
        )
    codegen_ns = _aot_monotonic_ns() - codegen_start
    return (
        llvm_text,
        timings.preprocessing_ns,
        timings.parser_ns,
        timings.sema_ns,
        codegen_ns,
        "",
    )


def _aot_compile_source_to_llvm_ir(
    source_path: str,
    source_text: str,
    include_dirs: tuple[str, ...],
    defines: tuple[str, ...],
    undefs: tuple[str, ...],
    std: str,
    debug: bool = False,
) -> str:
    try:
        return _aot_compile_source_to_llvm_ir_unchecked(
            source_path,
            source_text,
            include_dirs,
            defines,
            undefs,
            std,
            debug,
        )
    except (FrontendError, CodegenError, PreprocessorError, LexerError, ParserError, SemaError):
        return ""


def _aot_exec_argv(argv: tuple[str, ...]) -> int32:
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode


def _aot_compile_source_path_to_object(
    source_path: str,
    object_path: str,
    include_dirs: tuple[str, ...],
    defines: tuple[str, ...],
    undefs: tuple[str, ...],
    std: str,
    timing_path: str = "",
    debug: bool = False,
) -> bool:
    source_text: str = _aot_read_text_file(source_path)
    timing_start = 0
    preprocessing_ns = 0
    parser_ns = 0
    sema_ns = 0
    codegen_ns = 0
    failed_stage = ""
    if timing_path:
        timing_start = _aot_monotonic_ns()
        (
            llvm_text,
            preprocessing_ns,
            parser_ns,
            sema_ns,
            codegen_ns,
            failed_stage,
        ) = _aot_compile_source_to_llvm_ir_timed(
            source_path,
            source_text,
            include_dirs,
            defines,
            undefs,
            std,
            debug,
        )
    else:
        llvm_text = _aot_compile_source_to_llvm_ir(
            source_path,
            source_text,
            include_dirs,
            defines,
            undefs,
            std,
            debug,
        )
    llvm_path: str = _aot_smoke_llvm_path(object_path)
    if llvm_text == "":
        if timing_path and not _aot_write_text_file(
            timing_path,
            _aot_render_timing_json(
                False,
                failed_stage or "codegen",
                _aot_monotonic_ns() - timing_start,
                preprocessing_ns,
                parser_ns,
                sema_ns,
                codegen_ns,
                0,
            ),
        ):
            return False
        return False
    write_start = _aot_monotonic_ns() if timing_path else 0
    if not _aot_write_text_file(llvm_path, llvm_text):
        if timing_path:
            codegen_ns += _aot_monotonic_ns() - write_start
            _aot_write_text_file(
                timing_path,
                _aot_render_timing_json(
                    False,
                    "codegen",
                    _aot_monotonic_ns() - timing_start,
                    preprocessing_ns,
                    parser_ns,
                    sema_ns,
                    codegen_ns,
                    0,
                ),
            )
        return False
    if timing_path:
        codegen_ns += _aot_monotonic_ns() - write_start
    llc_argv: tuple[str, ...] = _aot_smoke_llc_argv(llvm_path, object_path, debug)
    llc_start = _aot_monotonic_ns() if timing_path else 0
    llc_status = _aot_exec_argv(llc_argv)
    if not timing_path:
        return llc_status == 0
    llc_ns = _aot_monotonic_ns() - llc_start
    success = llc_status == 0
    timing_text = _aot_render_timing_json(
        success,
        "" if success else "llc",
        _aot_monotonic_ns() - timing_start,
        preprocessing_ns,
        parser_ns,
        sema_ns,
        codegen_ns,
        llc_ns,
    )
    return _aot_write_text_file(timing_path, timing_text) and success


def _aot_compile_smoke_source_to_object(argc: int32, argv: tuple[str, ...]) -> int32:
    count: int = len(argv)
    if argc < 2 or count < 2:
        return 1
    scan_compile_only = False
    scan_has_source = False
    scan_has_link_input = False
    scan_has_timing = False
    scan_index = 1
    while scan_index < count:
        scan_arg = argv[scan_index]
        if scan_arg == "--timing-json":
            scan_has_timing = True
            scan_index += 2
            continue
        if scan_arg.startswith("--timing-json="):
            scan_has_timing = True
        elif scan_arg == "-c":
            scan_compile_only = True
        elif _aot_arg_is_c_source(scan_arg):
            scan_has_source = True
        elif _aot_arg_is_existing_link_input(scan_arg):
            scan_has_link_input = True
        scan_index += 1
    if scan_has_timing and not scan_has_source:
        return 1
    if not scan_compile_only and not scan_has_source and scan_has_link_input:
        return _aot_exec_argv(_aot_existing_link_argv(argv))
    compile_only = False
    source_path = ""
    object_input = ""
    output_path = ""
    link_flags: tuple[str, ...] = ()
    include_dirs: tuple[str, ...] = ()
    defines: tuple[str, ...] = ()
    undefs: tuple[str, ...] = ()
    std = "c11"
    timing_path = ""
    debug_info = False
    index = 1
    while index < count:
        arg: str = argv[index]
        if arg == "-c":
            compile_only = True
        elif arg == "-o":
            index += 1
            if index >= count:
                return 1
            output_path = argv[index]
        elif arg.startswith("-o") and len(arg) > 2:
            output_path = arg[2:]
        elif arg == "-I" or arg == "-D" or arg == "-U":
            index += 1
            if index >= count:
                return 1
            if arg == "-I":
                include_dirs = include_dirs + (argv[index],)
            elif arg == "-D":
                defines = defines + (argv[index],)
            else:
                undefs = undefs + (argv[index],)
        elif arg.startswith("-I") and len(arg) > 2:
            include_dirs = include_dirs + (arg[2:],)
        elif arg.startswith("-D") and len(arg) > 2:
            defines = defines + (arg[2:],)
        elif arg.startswith("-U") and len(arg) > 2:
            undefs = undefs + (arg[2:],)
        elif arg == "-framework":
            index += 1
            if index >= count:
                return 1
            link_flags = link_flags + (arg, argv[index])
        elif arg == "--timing-json":
            index += 1
            if index >= count or timing_path != "":
                return 1
            timing_path = argv[index]
        elif arg.startswith("--timing-json="):
            if timing_path != "":
                return 1
            timing_path = arg.split("=", 1)[1]
            if timing_path == "":
                return 1
        elif arg in ("-g", "-g1", "-g2", "-g3", "-ggdb", "-gline-tables-only") or arg.startswith(
            "-gdwarf-"
        ):
            debug_info = True
        elif arg == "-g0":
            debug_info = False
        elif arg == "-std=c11":
            std = "c11"
        elif arg == "-std=gnu11":
            std = "gnu11"
        elif arg in ("-O0", "-O1", "-O2", "-O3", "-Os", "-Oz") or arg.startswith("-W"):
            pass
        elif _aot_arg_is_c_source(arg):
            if source_path != "" or object_input != "":
                return 1
            source_path = arg
        elif _aot_arg_is_object_file(arg):
            if object_input != "" or source_path != "":
                return 1
            object_input = arg
        elif _aot_is_linker_flag(arg):
            link_flags = link_flags + (arg,)
        elif arg.startswith("-"):
            return 1
        else:
            return 1
        index += 1
    if compile_only:
        if source_path == "" or object_input != "":
            return 1
        object_path = output_path if output_path != "" else _aot_default_object_path(source_path)
        if _aot_compile_source_path_to_object(
            source_path,
            object_path,
            include_dirs,
            defines,
            undefs,
            std,
            timing_path,
            debug_info,
        ):
            return 0
        return 1
    executable_path = output_path if output_path != "" else "a.out"
    if object_input != "":
        link_argv = _aot_link_argv(object_input, executable_path, link_flags)
        return _aot_exec_argv(link_argv)
    if source_path == "":
        return 1
    object_path = _aot_link_object_path(executable_path)
    if not _aot_compile_source_path_to_object(
        source_path,
        object_path,
        include_dirs,
        defines,
        undefs,
        std,
        timing_path,
        debug_info,
    ):
        return 1
    link_argv = _aot_link_argv(object_path, executable_path, link_flags)
    link_status = _aot_exec_argv(link_argv)
    if link_status != 0 or not debug_info:
        return link_status
    return _aot_exec_argv(_aot_dsymutil_argv(executable_path))


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
        if config.debug_info and sys.platform == "darwin" and config.target != "x86_64-linux-gnu":
            dsymutil = shutil.which("dsymutil") or "/usr/bin/dsymutil"
            executable = config.output or "a.out"
            debug_result = subprocess.run(
                (dsymutil, executable),
                check=False,
                capture_output=True,
                text=True,
            )
            if debug_result.returncode != 0:
                stderr = (debug_result.stderr or "").strip()
                raise CodegenError(Diagnostic("codegen", executable, f"dsymutil failed: {stderr}"))
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

            def generate_configured_llvm(result: FrontendResult) -> str:
                return generate_llvm_ir(
                    result,
                    debug=config.debug_info,
                    target_triple=_llvm_target_triple(config),
                )

            if config.action == "assembly":
                return _emit_assembly_outputs(config, results, generate_configured_llvm)

            llc_path = _find_llc()

            def llvm_object_cmd(source: Path, obj: Path) -> list[str]:
                return _llvm_object_argv(config, llc_path, source, obj)

            def llvm_link_cmd(objects: list[str]) -> list[str]:
                return _link_argv_with_objects(config, objects)

            return _compile_or_link_generated_outputs(
                config,
                results,
                suffix="ll",
                generate=generate_configured_llvm,
                object_cmd=llvm_object_cmd,
                tool_error="llc failed",
                link_cmd=llvm_link_cmd,
            )

        if (
            config.debug_info
            and config.action != "assembly"
            and config.target in {"aarch64-apple-darwin", "x86_64-linux-gnu"}
        ):
            from xcc.codegen import generate_llvm_ir

            llc_path = _find_llc()

            def generate_debug_llvm(result: FrontendResult) -> str:
                return generate_llvm_ir(
                    result,
                    debug=True,
                    target_triple=_llvm_target_triple(config),
                )

            def debug_object_cmd(source: Path, obj: Path) -> list[str]:
                return _llvm_object_argv(config, llc_path, source, obj)

            def debug_link_cmd(objects: list[str]) -> list[str]:
                if config.target == "x86_64-linux-gnu":
                    return _drop_x86_64_linux_latomic(
                        _link_argv_with_objects(config, objects, linker="cc")
                    )
                command = _link_argv_with_objects(config, objects)
                command[1:1] = ["-target", config.target]
                return command

            return _compile_or_link_generated_outputs(
                config,
                results,
                suffix="ll",
                generate=generate_debug_llvm,
                object_cmd=debug_object_cmd,
                tool_error="llc failed",
                link_cmd=debug_link_cmd,
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
