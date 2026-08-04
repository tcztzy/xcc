import sys
from dataclasses import dataclass, replace
from pathlib import Path

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import validate_ir_module
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.module import AotModule
from xcc.aot.native import compile_llvm_executable
from xcc.aot.slice import AotSliceInput, lower_named_slice, render_native_reachability
from xcc.aot.source_contract import (
    HOSTED_ONLY_MODULES,
    CachePolicy,
    ParserBackend,
    render_source_manifest,
    resolve_source_set,
)

int32 = int

_HOSTED_VERSION = "xcc-aot 0.2 hosted"
_USAGE = (
    "usage: python -m xcc.aot build --source-root PATH "
    "--entry MODULE:FUNCTION --output PATH --parser=cpython|subset [options]\n"
    "       python -m xcc.aot parser-oracle --source-root PATH "
    "--entry MODULE:FUNCTION"
)


@dataclass(frozen=True)
class BuildOptions:
    source_root: Path
    entry: str
    output: Path
    parser: str
    no_cache: bool
    emit_llvm: Path | None
    emit_normalized_ir: Path | None
    source_manifest: Path | None
    tool_log: Path | None
    llc: str | None
    assembler: str | None
    linker: str
    debug: bool
    profile: bool


def hosted_main(argc: int32, argv: tuple[str, ...]) -> int32:
    try:
        return _hosted_main(argc, argv)
    except AotError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError as error:
        print(f"xcc-aot: {error}", file=sys.stderr)
        return 1


def _hosted_main(argc: int32, argv: tuple[str, ...]) -> int32:
    if argc <= 1:
        print(_USAGE)
        return 2
    command = argv[1]
    if command in {"-h", "--help"}:
        print(_USAGE)
        return 0
    if command == "--version":
        print(_HOSTED_VERSION)
        return 0
    if command == "parser-oracle":
        if any(argument in {"-h", "--help"} for argument in argv[2:]):
            print(_USAGE)
            return 0
        try:
            source_root, entry_module = _parse_parser_oracle_options(argv[2:])
        except ValueError as error:
            print(f"xcc-aot: {error}", file=sys.stderr)
            return 2
        return _run_parser_oracle(source_root, entry_module)
    if command != "build":
        print(f"xcc-aot: unknown command: {command}", file=sys.stderr)
        return 2
    if any(argument in {"-h", "--help"} for argument in argv[2:]):
        print(_USAGE)
        return 0
    try:
        options = _parse_build_options(argv[2:])
    except ValueError as error:
        print(f"xcc-aot: {error}", file=sys.stderr)
        return 2
    _run_hosted_build(options)
    return 0


def _parse_build_options(arguments: tuple[str, ...]) -> BuildOptions:
    values: dict[str, str] = {}
    no_cache = False
    debug = False
    profile = False
    index = 0
    value_names = {
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
    }
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"--debug", "--no-cache", "--profile"}:
            already_set = (
                no_cache
                if argument == "--no-cache"
                else debug
                if argument == "--debug"
                else profile
            )
            if already_set:
                raise ValueError(f"duplicate option: {argument}")
            if argument == "--no-cache":
                no_cache = True
            elif argument == "--debug":
                debug = True
            else:
                profile = True
            index += 1
            continue
        name = argument
        value = ""
        if "=" in argument:
            name, value = argument.split("=", 1)
        elif name in value_names:
            index += 1
            if index >= len(arguments):
                raise ValueError(f"missing value for {name}")
            value = arguments[index]
        else:
            raise ValueError(f"unknown option: {argument}")
        if name not in value_names:
            raise ValueError(f"unknown option: {name}")
        if name in values:
            raise ValueError(f"duplicate option: {name}")
        if not value:
            raise ValueError(f"empty value for {name}")
        values[name] = value
        index += 1
    for required in ("--source-root", "--entry", "--output", "--parser"):
        if required not in values:
            raise ValueError(f"missing required option: {required}")
    parser = values["--parser"]
    if parser not in {"cpython", "subset"}:
        raise ValueError(f"unsupported parser: {parser}")
    entry = values["--entry"]
    if entry.count(":") != 1:
        raise ValueError(f"invalid entry: {entry}")
    module_name, function_name = entry.split(":", 1)
    if not module_name or not function_name.isidentifier():
        raise ValueError(f"invalid entry: {entry}")
    return BuildOptions(
        Path(values["--source-root"]),
        entry,
        Path(values["--output"]),
        parser,
        no_cache,
        Path(values["--emit-llvm"]) if "--emit-llvm" in values else None,
        Path(values["--emit-normalized-ir"]) if "--emit-normalized-ir" in values else None,
        Path(values["--source-manifest"]) if "--source-manifest" in values else None,
        Path(values["--tool-log"]) if "--tool-log" in values else None,
        values.get("--llc"),
        values.get("--assembler"),
        values.get("--linker", "cc"),
        debug,
        profile,
    )


def _parse_parser_oracle_options(arguments: tuple[str, ...]) -> tuple[Path, str]:
    values: dict[str, str] = {}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        name = argument
        value = ""
        if "=" in argument:
            name, value = argument.split("=", 1)
        elif name in {"--entry", "--source-root"}:
            index += 1
            if index >= len(arguments):
                raise ValueError(f"missing value for {name}")
            value = arguments[index]
        else:
            raise ValueError(f"unknown option: {argument}")
        if name not in {"--entry", "--source-root"}:
            raise ValueError(f"unknown option: {name}")
        if name in values:
            raise ValueError(f"duplicate option: {name}")
        if not value:
            raise ValueError(f"empty value for {name}")
        values[name] = value
        index += 1
    for required in ("--source-root", "--entry"):
        if required not in values:
            raise ValueError(f"missing required option: {required}")
    entry = values["--entry"]
    if entry.count(":") != 1:
        raise ValueError(f"invalid entry: {entry}")
    module_name, function_name = entry.split(":", 1)
    if not module_name or not function_name.isidentifier():
        raise ValueError(f"invalid entry: {entry}")
    return Path(values["--source-root"]), module_name


def _run_hosted_build(options: BuildOptions) -> None:
    module_name, function_name = options.entry.split(":", 1)
    backend = (
        ParserBackend("subset", _subset_parser)
        if options.parser == "subset"
        else ParserBackend("cpython", _hosted_parser)
    )
    source_set = resolve_source_set(
        options.source_root,
        module_name,
        backend,
        CachePolicy(options.no_cache),
    )
    entry_unit = next(
        (unit for unit in source_set.units if unit.module == module_name),
        None,
    )
    if entry_unit is None:
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-CLI-0001",
                    f"Entry module missing from source set: {module_name}",
                    filename="<cli>",
                ),
            )
        )
    qualified_entry = f"{module_name}.{function_name}"
    slice_inputs = tuple(
        AotSliceInput(unit.module, Path(unit.canonical_path), unit.source, unit.parsed)
        for unit in source_set.units
        if unit.module not in HOSTED_ONLY_MODULES
    )
    ir_module = lower_named_slice(
        slice_inputs,
        root_targets=(qualified_entry,),
    )
    ir_module = replace(ir_module, entry=qualified_entry)
    validate_ir_module(ir_module)
    llvm_text = emit_llvm_text(ir_module, options.debug or options.profile)
    if options.emit_llvm is not None:
        _write_text(options.emit_llvm, llvm_text)
    if options.emit_normalized_ir is not None:
        _write_text(
            options.emit_normalized_ir,
            normalize_llvm(llvm_text, source_set.source_root),
        )
    if options.source_manifest is not None:
        _write_text(options.source_manifest, render_source_manifest(source_set))
    reachability = render_native_reachability(
        ir_module,
        root=qualified_entry,
        parser=options.parser,
    )
    reachability_path = options.output.with_suffix(".reachability")
    _write_text(reachability_path, reachability)
    if options.emit_normalized_ir is not None:
        normalized_reachability_path = options.emit_normalized_ir.with_suffix(".reachability")
        if normalized_reachability_path != reachability_path:
            _write_text(normalized_reachability_path, reachability)
    compile_llvm_executable(
        llvm_text,
        options.output,
        filename=entry_unit.canonical_path,
        llc=options.llc,
        assembler=options.assembler,
        linker=options.linker,
        tool_log=options.tool_log,
        debug=options.debug,
        profile=options.profile,
    )


def normalize_llvm(llvm_text: str, source_root: str) -> str:
    normalized: list[str] = []
    for line in llvm_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("; ModuleID =", "source_filename =", "!DIFile(")):
            line = line.replace(source_root, "$SOURCE_ROOT")
        normalized.append(line.rstrip())
    return "\n".join(normalized) + "\n"


def _hosted_parser(source: str, filename: str) -> AotModule:
    from xcc.aot.cpython_ast_adapter import parse_cpython_source

    return AotModule(
        filename,
        source,
        parse_cpython_source(source, filename=filename),
    )


def _subset_parser(source: str, filename: str) -> AotModule:
    from xcc.aot.py_parser import parse_subset_source

    return parse_subset_source(source, filename=filename)


def _run_parser_oracle(source_root: Path, entry_module: str) -> int32:
    from xcc.aot.parser_oracle import render_parser_oracle_report, run_parser_oracle

    report = run_parser_oracle(source_root, entry_module)
    print(render_parser_oracle_report(report), end="")
    return 0 if not report.failures else 1


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
