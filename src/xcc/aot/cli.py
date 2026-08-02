import subprocess
from pathlib import Path

from xcc.aot.ir import IrModule, validate_ir_module
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.slice import AotSliceInput, lower_named_slice, render_native_reachability
from xcc.aot.source_contract import (
    CachePolicy,
    render_source_manifest,
    resolve_subset_source_set,
)

int32 = int

_USAGE = (
    "usage: xcc-aot build --source-root PATH --entry MODULE:FUNCTION "
    "--output PATH --parser=subset [options]"
)
_VERSION = "xcc-aot 0.2 native-contract"


def main(argc: int32, argv: tuple[str, ...]) -> int32:
    if argc <= 1:
        print(_USAGE)
        return 2
    command = argv[1]
    if command in {"-h", "--help"}:
        print(_USAGE)
        return 0
    if command == "--version":
        print(_VERSION)
        return 0
    if command != "build":
        print(f"xcc-aot: unknown command: {command}")
        return 2
    wants_help = False
    index: int32 = 2
    while index < argc:
        argument = argv[index]
        parser = ""
        if argument.startswith("--parser="):
            parser = argument.split("=", 1)[1]
        elif argument == "--parser":
            index += 1
            if index < argc:
                parser = argv[index]
        elif argument in {"-h", "--help"}:
            wants_help = True
        if parser == "cpython":
            print("xcc-aot: native mode rejects --parser=cpython")
            return 2
        if argument.startswith("--parser") and parser != "subset":
            print(f"xcc-aot: native mode rejects parser: {parser}")
            return 2
        index += 1
    if wants_help:
        print(_USAGE)
        return 0
    value_options = (
        "--assembler",
        "--emit-llvm",
        "--emit-normalized-ir",
        "--entry",
        "--linker",
        "--llc",
        "--output",
        "--parser",
        "--source-manifest",
        "--source-root",
        "--tool-log",
    )
    seen_options: tuple[str, ...] = ()
    source_root = ""
    entry = ""
    output = ""
    parser = ""
    emit_llvm = ""
    emit_normalized_ir = ""
    source_manifest = ""
    tool_log = ""
    llc = "/opt/homebrew/opt/llvm/bin/llc"
    assembler = ""
    linker = "cc"
    index = 2
    while index < argc:
        argument = argv[index]
        if argument == "--no-cache":
            if argument in seen_options:
                print(f"xcc-aot: duplicate option: {argument}")
                return 2
            seen_options += (argument,)
            index += 1
            continue
        option = argument
        value = ""
        if "=" in argument:
            parts = argument.split("=", 1)
            option = parts[0]
            value = parts[1]
        elif option in value_options:
            index += 1
            if index >= argc:
                print(f"xcc-aot: missing value for {option}")
                return 2
            value = argv[index]
        else:
            print(f"xcc-aot: unknown option: {option}")
            return 2
        if option not in value_options:
            print(f"xcc-aot: unknown option: {option}")
            return 2
        if option in seen_options:
            print(f"xcc-aot: duplicate option: {option}")
            return 2
        if not value:
            print(f"xcc-aot: empty value for {option}")
            return 2
        if option == "--source-root":
            source_root = value
        elif option == "--entry":
            entry = value
        elif option == "--output":
            output = value
        elif option == "--parser":
            parser = value
        elif option == "--emit-llvm":
            emit_llvm = value
        elif option == "--emit-normalized-ir":
            emit_normalized_ir = value
        elif option == "--source-manifest":
            source_manifest = value
        elif option == "--tool-log":
            tool_log = value
        elif option == "--llc":
            llc = value
        elif option == "--assembler":
            assembler = value
        elif option == "--linker":
            linker = value
        seen_options += (option,)
        index += 1
    for required in ("--source-root", "--entry", "--output", "--parser"):
        if required not in seen_options:
            print(f"xcc-aot: missing required option: {required}")
            return 2
    if parser != "subset":
        print(f"xcc-aot: native mode rejects parser: {parser}")
        return 2
    return _run_native_build(
        source_root,
        entry,
        output,
        emit_llvm,
        emit_normalized_ir,
        source_manifest,
        tool_log,
        llc,
        assembler,
        linker,
        "--no-cache" in seen_options,
    )


def _run_native_build(
    source_root: str,
    entry: str,
    output: str,
    emit_llvm: str,
    emit_normalized_ir: str,
    source_manifest: str,
    tool_log: str,
    llc: str,
    assembler: str,
    linker: str,
    no_cache: bool,
) -> int32:
    if entry.count(":") != 1:
        print(f"xcc-aot: invalid entry: {entry}")
        return 2
    module_name, function_name = entry.split(":", 1)
    source_set = resolve_subset_source_set(
        Path(source_root),
        module_name,
        CachePolicy(no_cache),
    )
    qualified_entry = module_name + "." + function_name
    slice_inputs: list[AotSliceInput] = []
    for unit in source_set.units:
        slice_inputs.append(
            AotSliceInput(unit.module, Path(unit.canonical_path), unit.source, unit.parsed)
        )
    lowered = lower_named_slice(
        tuple(slice_inputs),
        root_targets=(qualified_entry,),
    )
    ir_module = IrModule(
        lowered.filename,
        lowered.records,
        lowered.functions,
        qualified_entry,
    )
    validate_ir_module(ir_module)
    reachability_path = output + ".reachability"
    if not _write_native_reachability(
        reachability_path,
        ir_module,
        qualified_entry,
    ):
        print(f"xcc-aot: cannot write native reachability: {reachability_path}")
        return 1
    llvm_text = emit_llvm_text(ir_module)
    llvm_path = emit_llvm or output + ".ll"
    if not _write_text(llvm_path, llvm_text):
        print(f"xcc-aot: cannot write LLVM: {llvm_path}")
        return 1
    if emit_normalized_ir and not _write_text(
        emit_normalized_ir,
        _normalize_llvm(llvm_text, source_set.source_root),
    ):
        print(f"xcc-aot: cannot write normalized LLVM: {emit_normalized_ir}")
        return 1
    if source_manifest:
        manifest = render_source_manifest(source_set)
        if not _write_text(source_manifest, manifest):
            print(f"xcc-aot: cannot write source manifest: {source_manifest}")
            return 1
    object_path = output + ".o"
    commands: tuple[tuple[str, ...], ...] = ()
    command: tuple[str, ...]
    if assembler:
        assembly_path = output + ".s"
        command = (llc, "-filetype=asm", llvm_path, "-o", assembly_path)
        commands += (command,)
        if _run_tool(command) != 0:
            print("xcc-aot: llc failed")
            return 1
        command = (assembler, assembly_path, "-o", object_path)
        commands += (command,)
        if _run_tool(command) != 0:
            print("xcc-aot: assembler failed")
            return 1
    else:
        command = (llc, "-filetype=obj", llvm_path, "-o", object_path)
        commands += (command,)
        if _run_tool(command) != 0:
            print("xcc-aot: llc failed")
            return 1
    command = (linker, object_path, "-o", output)
    commands += (command,)
    if _run_tool(command) != 0:
        print("xcc-aot: linker failed")
        return 1
    if tool_log and not _write_text(tool_log, _render_tool_log(commands)):
        print(f"xcc-aot: cannot write tool log: {tool_log}")
        return 1
    return 0


def _module_source_path(source_root: str, module_name: str) -> str:
    root = Path(source_root)
    package = root.name
    if module_name == package:
        return str(root / "__init__.py")
    prefix = package + "."
    if not module_name.startswith(prefix):
        return ""
    relative = module_name.removeprefix(prefix).replace(".", "/") + ".py"
    return str(root / relative)


def _write_native_reachability(
    path: str,
    module: IrModule,
    root: str,
) -> bool:
    reachability = render_native_reachability(
        module,
        root=root,
        parser="subset",
    )
    return _write_text(path, reachability)


def _llvm_is_already_normalized(llvm_text: str, source_root: str) -> bool:
    if not llvm_text.endswith("\n") or source_root in llvm_text:
        return False
    index = 0
    while index < len(llvm_text):
        character = llvm_text[index]
        if character in "\r\v\f":
            return False
        if character == "\n" and index > 0 and llvm_text[index - 1] in " \t":
            return False
        index += 1
    return True


def _normalize_llvm(llvm_text: str, source_root: str) -> str:
    if _llvm_is_already_normalized(llvm_text, source_root):
        return llvm_text
    normalized: list[str] = []
    for line in llvm_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("; ModuleID =", "source_filename =", "!DIFile(")):
            line = line.replace(source_root, "$SOURCE_ROOT")
        normalized.append(line.rstrip())
    return "\n".join(normalized) + "\n"


def _render_tool_log(commands: tuple[tuple[str, ...], ...]) -> str:
    text = "format=xcc-aot-tool-log-v1\n"
    for command in commands:
        text += "command=" + "\t".join(command) + "\n"
    return text


def _write_text(path: str, text: str) -> bool:
    return Path(path).write_text(text, encoding="utf-8") >= 0


def _run_tool(argv: tuple[str, ...]) -> int32:
    return subprocess.call(argv)
