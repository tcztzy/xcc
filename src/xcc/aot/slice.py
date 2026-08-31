from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from xcc.aot.analysis import AotAnalysis, analyze_module, analyze_source
from xcc.aot.binder import bind_class_types, bind_function_signatures, bind_types
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrBranch,
    IrBreak,
    IrCall,
    IrConstBool,
    IrConstBytes,
    IrConstFloat,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrContinue,
    IrDictType,
    IrEnumMember,
    IrExceptHandler,
    IrExpr,
    IrForEach,
    IrFunction,
    IrGetField,
    IrIf,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrPrint,
    IrRaise,
    IrRecord,
    IrRecordType,
    IrReraise,
    IrReturn,
    IrSetItem,
    IrStmt,
    IrStringConcat,
    IrStringJoin,
    IrStringType,
    IrTry,
    IrTuple,
    IrTupleSlice,
    IrTupleType,
    IrWhile,
)
from xcc.aot.lower import (
    _collect_global_annotations,
    _collect_global_scalar_constants,
    _collect_global_string_constants,
    _collect_global_string_container_constants,
    _Lowerer,
    _prepare_analysis_lowerer,
    lower_analysis_to_ir,
    lower_source_to_ir,
)
from xcc.aot.module import AotModule, parse_source
from xcc.aot.subset import AotModuleSummary, check_subset
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotType

from . import py_ast as ast

_NATIVE_EMITTED_LEAF_FUNCTIONS = {
    "xcc.cc_driver._aot_exec_argv",
    "xcc.frontend._aot_monotonic_ns",
    "xcc.cc_driver._aot_read_text_file",
    "xcc.cc_driver._aot_write_text_file",
    "xcc.codegen._llvm_print_module_to_string",
    "xcc.lexer._aot_error_summary_for_source",
    "xcc.lexer._aot_header_summary_for_source",
    "xcc.lexer._aot_token_summary_for_source",
    "xcc.lexer.translate_source",
    "xcc.llvm_api.optional_zero_ptr_array",
    "xcc.llvm_api.ptr_array",
    "xcc.llvm_api.zero_ptr_array",
    "xcc.parser.type_specs.ParserError.__str__",
    "xcc.preprocessor.__init__._Preprocessor.__init__",
    "xcc.preprocessor.__init__._Preprocessor._expand_line",
    "xcc.preprocessor.__init__._Preprocessor._expand_macro_text",
    "xcc.preprocessor.__init__._Preprocessor._handle_define",
    "xcc.preprocessor.__init__._Preprocessor._handle_pragma_operator",
    "xcc.preprocessor.__init__._Preprocessor._should_collect_function_macro_continuation",
    "xcc.preprocessor.__init__._Preprocessor._handle_undef",
    "xcc.sema.symbols.TypeMap.get",
    "xcc.sema.symbols.TypeMap.set",
    "xcc.sema.type_helpers._aot_integer_type_summary",
    "xcc.types.Type.__str__",
}
_NATIVE_EMITTED_LEAF_DEPENDENCIES: dict[str, tuple[str, ...]] = {}
_NORETURN_CALL_PREFIX = "__noreturn__:"
_RECORD_INIT_PREFIX = "__record_init__:"
_CALL_TARGET_OVERRIDES = {
    "xcc.preprocessor.__init__.preprocess_source": (
        "xcc.preprocessor.__init__.preprocess_source_no_callback"
    ),
    "xcc.preprocessor.__init__._Preprocessor._expand_line": (
        "xcc.preprocessor.__init__._Preprocessor._expand_line_no_callback"
    ),
    "xcc.preprocessor.__init__._Preprocessor._handle_conditional": (
        "xcc.preprocessor.__init__._Preprocessor._handle_conditional_no_callback"
    ),
    "xcc.preprocessor.__init__._Preprocessor._handle_conditional_for_process": (
        "xcc.preprocessor.__init__._Preprocessor._handle_conditional_for_process_no_callback"
    ),
    "xcc.preprocessor.__init__._Preprocessor._handle_define": (
        "xcc.preprocessor.__init__._Preprocessor._handle_define_no_callback"
    ),
    "xcc.preprocessor.__init__._Preprocessor._handle_undef": (
        "xcc.preprocessor.__init__._Preprocessor._handle_undef_no_callback"
    ),
    "xcc.preprocessor.__init__._Preprocessor._parse_include_target": (
        "xcc.preprocessor.__init__._Preprocessor._parse_include_target_no_macro"
    ),
    "xcc.preprocessor.__init__._Preprocessor._parse_header_name_operand": (
        "xcc.preprocessor.__init__._Preprocessor._parse_header_name_operand_no_macro"
    ),
    "xcc.preprocessor.__init__._Preprocessor._skip_guarded_include": (
        "xcc.preprocessor.__init__._Preprocessor._skip_guarded_include_no_callback"
    ),
}
_INTERNAL_RECORD_TYPES = frozenset({"LLVMApi"})


@dataclass(frozen=True)
class AotSliceInput:
    name: str
    path: Path
    source: str | None = None
    parsed: AotModule | None = None


@dataclass(frozen=True)
class _SliceGlobalContext:
    annotations: dict[str, str]
    module_annotations: dict[str, dict[str, str]]
    string_constants: dict[str, str]
    module_string_constants: dict[str, dict[str, str]]
    scalar_constants: dict[str, IrExpr]
    module_scalar_constants: dict[str, dict[str, IrExpr]]
    string_container_constants: dict[str, IrTuple]
    module_string_container_constants: dict[str, dict[str, IrTuple]]


def collect_slice_inputs(paths: tuple[Path, ...]) -> tuple[AotSliceInput, ...]:
    root = (Path.cwd() / "src" / "xcc").resolve()
    modules: list[AotSliceInput] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise AotError(
                (
                    AotDiagnostic(
                        "XCC-AOT-SLICE-0001",
                        f"Module is outside src/xcc: {resolved}",
                        filename=str(resolved),
                    ),
                )
            ) from exc
        if relative.suffix != ".py":
            raise AotError(
                (
                    AotDiagnostic(
                        "XCC-AOT-SLICE-0001",
                        f"Module is not Python source: {resolved}",
                        filename=str(resolved),
                    ),
                )
            )
        modules.append(AotSliceInput("xcc." + ".".join(relative.with_suffix("").parts), resolved))
    return tuple(sorted(modules, key=_slice_input_name))


def lower_core_slice(
    paths: tuple[Path, ...],
    *,
    root_targets: tuple[str, ...] = (),
    required_records: tuple[str, ...] = (),
) -> IrModule:
    if root_targets:
        return _lower_core_slice_from_roots(paths, root_targets, required_records)
    return _lower_core_slice_all(paths)


def lower_named_slice(
    modules: tuple[AotSliceInput, ...],
    *,
    root_targets: tuple[str, ...],
    required_records: tuple[str, ...] = (),
) -> IrModule:
    ordered = tuple(sorted(modules, key=_slice_input_name))
    return _lower_named_slice_from_roots(ordered, root_targets, required_records)


def render_native_reachability(
    module: IrModule,
    *,
    root: str,
    parser: str,
) -> str:
    functions = {function.name: function for function in module.functions}
    if root not in functions:
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-SLICE-0003",
                    f"Native reachability root is missing: {root}",
                    filename=module.filename,
                ),
            )
        )
    records = {record.name: record for record in module.records}
    ordered_function_names = sorted(functions)
    ordered_record_names = sorted(records)
    lines = [
        "format=xcc-aot-native-reachability-v1",
        f"parser={parser}",
        "native_call_graph=true",
        f"root={root}",
    ]
    for name in ordered_function_names:
        reason = "root" if name == root else "reachable-call"
        lines.append(f"function={name};reason={reason}")
    for caller in ordered_function_names:
        targets: set[str] = set()
        for target in _function_call_targets(functions[caller]):
            if target in functions:
                targets.add(target)
        for target in sorted(targets):
            lines.append(f"edge=function:{caller}->function:{target};reason=call")
    for name in ordered_record_names:
        lines.append(f"record={name};reason=reachable-type")
    for function_name in ordered_function_names:
        used_records: set[str] = set()
        for record_name in _function_record_names(functions[function_name]):
            if record_name in records:
                used_records.add(record_name)
        for record_name in sorted(used_records):
            lines.append(f"edge=function:{function_name}->record:{record_name};reason=type-use")
    for record_name in ordered_record_names:
        related: set[str] = set()
        for target in records[record_name].bases:
            if target in records:
                related.add(target)
        for field in records[record_name].fields:
            for target in _type_record_names(field.type):
                if target in records:
                    related.add(target)
        for target in sorted(related):
            lines.append(f"edge=record:{record_name}->record:{target};reason=layout")
    return "\n".join(lines) + "\n"


def lower_core_entry_slice(paths: tuple[Path, ...], wrapper: IrFunction) -> IrModule:
    module = lower_core_slice(
        paths,
        root_targets=_function_call_targets(wrapper),
        required_records=_function_record_names(wrapper),
    )
    return core_slice_entry_module(module, wrapper)


def _lower_core_slice_all(paths: tuple[Path, ...]) -> IrModule:
    module_inputs = collect_slice_inputs(paths)
    source_cache = {
        module.name: (
            module.source if module.source is not None else module.path.read_text(encoding="utf-8")
        )
        for module in module_inputs
    }
    parsed_cache = _slice_parsed_module_cache(module_inputs, source_cache)
    summary_cache = _slice_module_summary_cache(parsed_cache)
    function_types = _slice_method_signature_table(
        module_inputs,
        source_cache,
        parsed_cache=parsed_cache,
        summary_cache=summary_cache,
    )
    module_names = frozenset(source_cache)
    rename_maps = {
        module.name: _module_rename_map(
            module.name,
            source_cache[module.name],
            module_names,
            tree=parsed_cache[module.name].tree,
        )
        for module in module_inputs
    }
    module_function_types = _module_function_alias_tables(function_types, rename_maps)
    class_types, _ = _slice_class_tables(
        module_inputs,
        source_cache,
        function_types,
        parsed_cache=parsed_cache,
        summary_cache=summary_cache,
        rename_maps=rename_maps,
        module_function_types=module_function_types,
    )
    analysis_cache = _slice_lowering_analysis_cache(
        module_inputs,
        parsed_cache,
        class_types,
        module_function_types,
        summary_cache=summary_cache,
    )
    aliases = _slice_type_aliases(
        module_inputs,
        source_cache,
        parsed_cache=parsed_cache,
        analysis_cache=analysis_cache,
    )
    global_context = _slice_global_context(
        module_inputs,
        source_cache,
        parsed_cache=parsed_cache,
    )
    global_annotations = global_context.annotations
    global_string_constants = global_context.string_constants
    global_scalar_constants = global_context.scalar_constants
    global_string_container_constants = global_context.string_container_constants
    records: list[IrRecord] = []
    functions: list[IrFunction] = []
    lowerer_cache = _slice_lowerer_cache(
        module_inputs,
        analysis_cache,
        class_types,
        module_function_types,
        function_types,
        aliases,
        global_context,
    )
    for module_input in module_inputs:
        rename_map = rename_maps[module_input.name]
        module = lower_analysis_to_ir(
            analysis_cache[module_input.name],
            extra_classes=class_types,
            extra_functions=module_function_types[module_input.name],
            fallback_function_types=function_types,
            extra_aliases=aliases,
            extra_global_annotations=global_annotations,
            extra_global_string_constants=global_string_constants,
            extra_global_scalar_constants=global_scalar_constants,
            extra_global_string_container_constants=global_string_container_constants,
            prepared_lowerer=lowerer_cache[module_input.name],
        )
        records.extend(module.records)
        for function in module.functions:
            functions.append(
                IrFunction(
                    rename_map[function.name],
                    function.params,
                    function.return_type,
                    _rename_statement_calls(function.body, rename_map),
                    function.source_filename,
                    function.source_span,
                )
            )
    return IrModule("<core-slice>", tuple(records), tuple(functions))


def _lower_core_slice_from_roots(
    paths: tuple[Path, ...],
    root_targets: tuple[str, ...],
    required_records: tuple[str, ...],
) -> IrModule:
    module_inputs = collect_slice_inputs(paths)
    return _lower_named_slice_from_roots(module_inputs, root_targets, required_records)


def _lower_named_slice_from_roots(
    module_inputs: tuple[AotSliceInput, ...],
    root_targets: tuple[str, ...],
    required_records: tuple[str, ...],
) -> IrModule:
    inputs_by_name = {module.name: module for module in module_inputs}
    source_cache = {
        module.name: (
            module.source if module.source is not None else module.path.read_text(encoding="utf-8")
        )
        for module in module_inputs
    }
    parsed_cache = _slice_parsed_module_cache(module_inputs, source_cache)
    summary_cache = _slice_module_summary_cache(parsed_cache)
    function_types = _slice_method_signature_table(
        module_inputs,
        source_cache,
        parsed_cache=parsed_cache,
        summary_cache=summary_cache,
    )
    module_names = frozenset(source_cache)
    rename_maps = {
        module.name: _module_rename_map(
            module.name,
            source_cache[module.name],
            module_names,
            tree=parsed_cache[module.name].tree,
        )
        for module in module_inputs
    }
    module_function_types = _module_function_alias_tables(function_types, rename_maps)
    class_types, class_modules = _slice_class_tables(
        module_inputs,
        source_cache,
        function_types,
        parsed_cache=parsed_cache,
        summary_cache=summary_cache,
        rename_maps=rename_maps,
        module_function_types=module_function_types,
    )
    analysis_cache = _slice_lowering_analysis_cache(
        module_inputs,
        parsed_cache,
        class_types,
        module_function_types,
        summary_cache=summary_cache,
    )
    aliases = _slice_type_aliases(
        module_inputs,
        source_cache,
        parsed_cache=parsed_cache,
        analysis_cache=analysis_cache,
    )
    global_context = _slice_global_context(
        module_inputs,
        source_cache,
        parsed_cache=parsed_cache,
    )
    global_annotations = global_context.annotations
    global_string_constants = global_context.string_constants
    global_scalar_constants = global_context.scalar_constants
    global_string_container_constants = global_context.string_container_constants
    lowerer_cache = _slice_lowerer_cache(
        module_inputs,
        analysis_cache,
        class_types,
        module_function_types,
        function_types,
        aliases,
        global_context,
    )
    records_by_name: dict[str, IrRecord] = {}
    functions: dict[str, IrFunction] = {}
    record_names = set(required_records)
    pending = list(root_targets)
    while pending:
        target = pending.pop()
        if target in functions:
            continue
        module_name, local_name = _split_module_function(target, inputs_by_name)
        if module_name is None or local_name is None:
            continue
        bodyless = (
            frozenset({local_name}) if target in _NATIVE_EMITTED_LEAF_FUNCTIONS else frozenset()
        )
        include_records = record_names.difference(records_by_name)
        if "." in local_name:
            owner_record = local_name.split(".", 1)[0]
            if owner_record not in records_by_name:
                include_records.add(owner_record)
        rename_map = rename_maps[module_name]
        module = lower_analysis_to_ir(
            analysis_cache[module_name],
            include_records=include_records,
            include_functions={local_name},
            bodyless_functions=bodyless,
            extra_classes=class_types,
            extra_functions=module_function_types[module_name],
            fallback_function_types=function_types,
            extra_aliases=aliases,
            extra_global_annotations=global_annotations,
            extra_global_string_constants=global_string_constants,
            extra_global_scalar_constants=global_scalar_constants,
            extra_global_string_container_constants=global_string_container_constants,
            prepared_lowerer=lowerer_cache[module_name],
        )
        for record in module.records:
            records_by_name.setdefault(record.name, record)
        missing_required_records = record_names.difference(records_by_name)
        if missing_required_records:
            _add_missing_records(
                missing_required_records,
                records_by_name,
                class_modules,
                inputs_by_name,
                source_cache,
                class_types,
                function_types,
                aliases,
                global_annotations,
                global_string_constants,
                global_scalar_constants,
                global_string_container_constants,
                parsed_cache=parsed_cache,
                analysis_cache=analysis_cache,
                module_function_types=module_function_types,
                lowerer_cache=lowerer_cache,
            )
        for function in module.functions:
            full_name = rename_map[function.name]
            lowered = IrFunction(
                full_name,
                function.params,
                function.return_type,
                _rename_statement_calls(function.body, rename_map),
                function.source_filename,
                function.source_span,
            )
            functions[full_name] = lowered
            if lowered.name in _NATIVE_EMITTED_LEAF_FUNCTIONS:
                pending.extend(_native_leaf_dependencies(lowered.name))
                continue
            discovered_records = set(_function_record_names(lowered))
            record_names.update(discovered_records)
            missing_records = discovered_records.difference(records_by_name)
            if missing_records:
                _add_missing_records(
                    missing_records,
                    records_by_name,
                    class_modules,
                    inputs_by_name,
                    source_cache,
                    class_types,
                    function_types,
                    aliases,
                    global_annotations,
                    global_string_constants,
                    global_scalar_constants,
                    global_string_container_constants,
                    parsed_cache=parsed_cache,
                    analysis_cache=analysis_cache,
                    module_function_types=module_function_types,
                    lowerer_cache=lowerer_cache,
                )
            pending.extend(
                _rename_call_target(call_target, rename_map)
                for call_target in _function_call_targets(lowered)
            )
    return IrModule("<core-slice>", tuple(records_by_name.values()), tuple(functions.values()))


def _slice_parsed_module_cache(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
) -> dict[str, AotModule]:
    parsed_cache: dict[str, AotModule] = {}
    for module_input in module_inputs:
        parsed = module_input.parsed
        if parsed is None:
            parsed = parse_source(
                source_cache[module_input.name],
                filename=str(module_input.path),
            )
        parsed_cache[module_input.name] = parsed
    return parsed_cache


def _slice_module_summary_cache(
    parsed_cache: dict[str, AotModule],
) -> dict[str, AotModuleSummary]:
    return {name: check_subset(module) for name, module in parsed_cache.items()}


def _analyze_slice_module(
    module_input: AotSliceInput,
    source_cache: dict[str, str],
    *,
    parsed_cache: dict[str, AotModule] | None = None,
    extra_classes: dict[str, AotClassInfo] | None = None,
    extra_functions: dict[str, AotFunctionInfo] | None = None,
) -> AotAnalysis:
    if parsed_cache is None:
        return analyze_source(
            source_cache[module_input.name],
            filename=str(module_input.path),
            extra_classes=extra_classes,
            extra_functions=extra_functions,
        )
    return analyze_module(
        parsed_cache[module_input.name],
        extra_classes=extra_classes,
        extra_functions=extra_functions,
    )


def _slice_lowering_analysis_cache(
    module_inputs: tuple[AotSliceInput, ...],
    parsed_cache: dict[str, AotModule],
    class_types: dict[str, AotClassInfo],
    module_function_types: dict[str, dict[str, AotFunctionInfo]],
    *,
    summary_cache: dict[str, AotModuleSummary] | None = None,
) -> dict[str, AotAnalysis]:
    analyses: dict[str, AotAnalysis] = {}
    for module_input in module_inputs:
        module = parsed_cache[module_input.name]
        if summary_cache is None:
            analyses[module_input.name] = analyze_module(
                module,
                extra_classes=class_types,
                extra_functions=module_function_types[module_input.name],
            )
        else:
            summary = summary_cache[module_input.name]
            analyses[module_input.name] = AotAnalysis(
                module,
                summary,
                bind_types(
                    summary,
                    module,
                    extra_classes=class_types,
                    extra_functions=module_function_types[module_input.name],
                ),
            )
    return analyses


def _slice_lowerer_cache(
    module_inputs: tuple[AotSliceInput, ...],
    analysis_cache: dict[str, AotAnalysis],
    class_types: dict[str, AotClassInfo],
    module_function_types: dict[str, dict[str, AotFunctionInfo]],
    fallback_function_types: dict[str, AotFunctionInfo],
    aliases: dict[str, AotType],
    global_context: _SliceGlobalContext,
) -> dict[str, _Lowerer]:
    lowerers: dict[str, _Lowerer] = {}
    for module_input in module_inputs:
        lowerers[module_input.name] = _prepare_analysis_lowerer(
            analysis_cache[module_input.name],
            extra_classes=class_types,
            extra_functions=module_function_types[module_input.name],
            fallback_function_types=fallback_function_types,
            extra_aliases=aliases,
            extra_global_annotations=global_context.annotations,
            extra_global_string_constants=global_context.string_constants,
            extra_global_scalar_constants=global_context.scalar_constants,
            extra_global_string_container_constants=global_context.string_container_constants,
            local_global_annotations=global_context.module_annotations[module_input.name],
            local_global_string_constants=global_context.module_string_constants[module_input.name],
            local_global_scalar_constants=global_context.module_scalar_constants[module_input.name],
            local_global_string_container_constants=(
                global_context.module_string_container_constants[module_input.name]
            ),
        )
    return lowerers


def _slice_class_tables(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
    function_types: dict[str, AotFunctionInfo],
    *,
    parsed_cache: dict[str, AotModule] | None = None,
    summary_cache: dict[str, AotModuleSummary] | None = None,
    rename_maps: dict[str, dict[str, str]] | None = None,
    module_function_types: dict[str, dict[str, AotFunctionInfo]] | None = None,
) -> tuple[dict[str, AotClassInfo], dict[str, str]]:
    class_types: dict[str, AotClassInfo] = {}
    class_modules: dict[str, str] = {}
    if rename_maps is None:
        module_names = frozenset(source_cache)
        rename_maps = {
            module.name: _module_rename_map(
                module.name,
                source_cache[module.name],
                module_names,
                tree=(parsed_cache[module.name].tree if parsed_cache is not None else None),
            )
            for module in module_inputs
        }
    if module_function_types is None:
        module_function_types = _module_function_alias_tables(function_types, rename_maps)
    for module_input in module_inputs:
        classes = _bind_slice_class_types(
            module_input,
            source_cache,
            parsed_cache=parsed_cache,
            summary_cache=summary_cache,
            extra_functions=module_function_types[module_input.name],
        )
        for class_name, class_info in classes.items():
            class_types.setdefault(class_name, class_info)
            class_modules.setdefault(class_name, module_input.name)
    for module_input in module_inputs:
        classes = _bind_slice_class_types(
            module_input,
            source_cache,
            parsed_cache=parsed_cache,
            summary_cache=summary_cache,
            extra_classes=class_types,
            extra_functions=module_function_types[module_input.name],
        )
        for class_name, class_info in classes.items():
            if class_modules.get(class_name) == module_input.name:
                class_types[class_name] = class_info
    return class_types, class_modules


def _bind_slice_class_types(
    module_input: AotSliceInput,
    source_cache: dict[str, str],
    *,
    parsed_cache: dict[str, AotModule] | None = None,
    summary_cache: dict[str, AotModuleSummary] | None = None,
    extra_classes: dict[str, AotClassInfo] | None = None,
    extra_functions: dict[str, AotFunctionInfo] | None = None,
) -> dict[str, AotClassInfo]:
    module = (
        parsed_cache[module_input.name]
        if parsed_cache is not None
        else parse_source(
            source_cache[module_input.name],
            filename=str(module_input.path),
        )
    )
    summary = (
        summary_cache[module_input.name] if summary_cache is not None else check_subset(module)
    )
    return bind_class_types(
        summary,
        module,
        extra_classes=extra_classes,
        extra_functions=extra_functions,
    )


def _slice_method_signature_table(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
    *,
    parsed_cache: dict[str, AotModule] | None = None,
    summary_cache: dict[str, AotModuleSummary] | None = None,
) -> dict[str, AotFunctionInfo]:
    function_types: dict[str, AotFunctionInfo] = {}
    for module_input in module_inputs:
        module = (
            parsed_cache[module_input.name]
            if parsed_cache is not None
            else parse_source(
                source_cache[module_input.name],
                filename=str(module_input.path),
            )
        )
        summary = (
            summary_cache[module_input.name] if summary_cache is not None else check_subset(module)
        )
        for function_name, function_info in bind_function_signatures(
            summary,
            module,
        ).items():
            function_types.setdefault(function_name, function_info)
            function_types.setdefault(f"{module_input.name}.{function_name}", function_info)
    for protocol_target, concrete_target in _CALL_TARGET_OVERRIDES.items():
        concrete_info = function_types.get(concrete_target)
        if concrete_info is not None:
            function_types[protocol_target] = concrete_info
    return function_types


def _slice_type_aliases(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
    *,
    parsed_cache: dict[str, AotModule] | None = None,
    analysis_cache: dict[str, AotAnalysis] | None = None,
) -> dict[str, AotType]:
    aliases: dict[str, AotType] = {}
    for module_input in module_inputs:
        analysis = (
            analysis_cache[module_input.name]
            if analysis_cache is not None
            else _analyze_slice_module(
                module_input,
                source_cache,
                parsed_cache=parsed_cache,
            )
        )
        for alias_name, alias_type in analysis.types.aliases.items():
            aliases.setdefault(alias_name, alias_type)
    return aliases


def _slice_global_context(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
    *,
    parsed_cache: dict[str, AotModule] | None = None,
) -> _SliceGlobalContext:
    annotations: dict[str, str] = {}
    module_annotations: dict[str, dict[str, str]] = {}
    string_constants: dict[str, str] = {}
    module_string_constants: dict[str, dict[str, str]] = {}
    scalar_constants: dict[str, IrExpr] = {}
    module_scalar_constants: dict[str, dict[str, IrExpr]] = {}
    string_container_constants: dict[str, IrTuple] = {}
    module_string_container_constants: dict[str, dict[str, IrTuple]] = {}
    for module_input in module_inputs:
        tree = (
            parsed_cache[module_input.name].tree
            if parsed_cache is not None
            else parse_source(
                source_cache[module_input.name],
                filename=str(module_input.path),
            ).tree
        )
        local_annotations = _collect_global_annotations(tree)
        local_string_constants = _collect_global_string_constants(tree)
        local_scalar_constants = _collect_global_scalar_constants(tree)
        local_string_container_constants = _collect_global_string_container_constants(tree)
        module_annotations[module_input.name] = local_annotations
        module_string_constants[module_input.name] = local_string_constants
        module_scalar_constants[module_input.name] = local_scalar_constants
        module_string_container_constants[module_input.name] = local_string_container_constants
        for name, annotation in local_annotations.items():
            annotations.setdefault(name, annotation)
        for name, string_value in local_string_constants.items():
            string_constants.setdefault(name, string_value)
        for name, scalar_value in local_scalar_constants.items():
            scalar_constants.setdefault(name, scalar_value)
        for name, container_value in local_string_container_constants.items():
            string_container_constants.setdefault(name, container_value)
    return _SliceGlobalContext(
        annotations,
        module_annotations,
        string_constants,
        module_string_constants,
        scalar_constants,
        module_scalar_constants,
        string_container_constants,
        module_string_container_constants,
    )


def _add_missing_records(
    missing_records: set[str],
    records_by_name: dict[str, IrRecord],
    class_modules: dict[str, str],
    inputs_by_name: dict[str, AotSliceInput],
    source_cache: dict[str, str],
    class_types: dict[str, AotClassInfo],
    function_types: dict[str, AotFunctionInfo],
    aliases: dict[str, AotType] | None = None,
    global_annotations: dict[str, str] | None = None,
    global_string_constants: dict[str, str] | None = None,
    global_scalar_constants: dict[str, IrExpr] | None = None,
    global_string_container_constants: dict[str, IrTuple] | None = None,
    *,
    parsed_cache: dict[str, AotModule] | None = None,
    analysis_cache: dict[str, AotAnalysis] | None = None,
    module_function_types: dict[str, dict[str, AotFunctionInfo]] | None = None,
    lowerer_cache: dict[str, _Lowerer] | None = None,
) -> None:
    pending = sorted(missing_records)
    requested: set[str] = set()
    while pending:
        records_by_module: dict[str, set[str]] = {}
        current = pending
        pending = []
        for record_name in current:
            if record_name in requested or record_name in records_by_name:
                continue
            requested.add(record_name)
            module_name = class_modules.get(record_name)
            if module_name is None:
                continue
            records_by_module.setdefault(module_name, set()).add(record_name)
        for module_name in sorted(records_by_module):
            module_input = inputs_by_name[module_name]
            include_records = records_by_module[module_name]
            if module_function_types is None:
                rename_map = _module_rename_map(
                    module_name,
                    source_cache[module_name],
                    frozenset(source_cache),
                    tree=(parsed_cache[module_name].tree if parsed_cache is not None else None),
                )
                extra_functions = _function_types_with_module_aliases(
                    function_types,
                    rename_map,
                )
            else:
                extra_functions = module_function_types[module_name]
            if analysis_cache is None:
                records_module = lower_source_to_ir(
                    source_cache[module_name],
                    filename=str(module_input.path),
                    include_records=include_records,
                    include_functions=frozenset(),
                    extra_classes=class_types,
                    extra_functions=extra_functions,
                    fallback_function_types=function_types,
                    extra_aliases=aliases,
                    extra_global_annotations=global_annotations,
                    extra_global_string_constants=global_string_constants,
                    extra_global_scalar_constants=global_scalar_constants,
                    extra_global_string_container_constants=global_string_container_constants,
                )
            else:
                records_module = lower_analysis_to_ir(
                    analysis_cache[module_name],
                    include_records=include_records,
                    include_functions=frozenset(),
                    extra_classes=class_types,
                    extra_functions=extra_functions,
                    fallback_function_types=function_types,
                    extra_aliases=aliases,
                    extra_global_annotations=global_annotations,
                    extra_global_string_constants=global_string_constants,
                    extra_global_scalar_constants=global_scalar_constants,
                    extra_global_string_container_constants=global_string_container_constants,
                    prepared_lowerer=(
                        lowerer_cache[module_name] if lowerer_cache is not None else None
                    ),
                )
            for record in records_module.records:
                if record.name in records_by_name:
                    continue
                records_by_name[record.name] = record
                layout_records = set(record.bases)
                for field in record.fields:
                    layout_records.update(_type_record_names(field.type))
                pending.extend(sorted(layout_records.difference(records_by_name)))


def _module_rename_map(
    module_name: str,
    source: str,
    module_names: frozenset[str] | set[str] | None = None,
    *,
    tree: ast.Module | None = None,
) -> dict[str, str]:
    if tree is None:
        tree = parse_source(source, filename=module_name).tree
    rename_map = {name: f"{module_name}.{name}" for name in _local_function_names_from_tree(tree)}
    rename_map.update(
        _imported_project_function_names(
            module_name,
            tree,
            frozenset(module_names or ()),
        )
    )
    rename_map.update(
        _assigned_project_function_aliases(
            tree,
            rename_map,
            frozenset(module_names or ()),
        )
    )
    return rename_map


def _local_function_names_from_tree(tree: ast.Module) -> tuple[str, ...]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    names.append(f"{node.name}.{child.name}")
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            names.append(node.name)
    return tuple(names)


def _imported_project_function_names(
    module_name: str,
    tree: ast.Module,
    module_names: frozenset[str],
) -> dict[str, str]:
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        imported_module = _resolved_import_module(module_name, node)
        if imported_module is None:
            continue
        package_module = f"{imported_module}.__init__"
        package_is_project = (
            _is_project_target(imported_module, module_names) or package_module in module_names
        )
        for alias in node.names:
            if alias.name == "*":
                continue
            local_name = alias.asname or alias.name
            submodule = f"{imported_module}.{alias.name}"
            if submodule in module_names:
                names[local_name] = submodule
                continue
            if not package_is_project:
                continue
            target_module = package_module if package_module in module_names else imported_module
            names[local_name] = f"{target_module}.{alias.name}"
    return names


def _resolved_import_module(module_name: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    current_parts = module_name.split(".")
    package_parts = current_parts[:-1]
    if module_name.endswith(".__init__"):
        package_parts = current_parts[:-1]
    parent_count = node.level - 1
    if parent_count > len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - parent_count]
    if node.module is not None:
        base_parts = base_parts + node.module.split(".")
    return ".".join(base_parts)


def _assigned_project_function_aliases(
    tree: ast.Module,
    rename_map: dict[str, str],
    module_names: frozenset[str] | set[str],
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    known_names = dict(rename_map)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        qualified_name = _qualified_alias_value_name(node.value, known_names)
        if qualified_name is None or not _is_project_target(qualified_name, module_names):
            continue
        aliases[target.id] = qualified_name
        known_names[target.id] = qualified_name
    return aliases


def _is_project_target(
    target: str,
    module_names: frozenset[str] | set[str],
) -> bool:
    if not module_names:
        return target == "xcc" or target.startswith("xcc.")
    for module_name in module_names:
        if target == module_name or target.startswith(module_name + "."):
            return True
    return False


def _qualified_alias_value_name(
    node: ast.expr,
    known_names: dict[str, str],
) -> str | None:
    if isinstance(node, ast.Name):
        return known_names.get(node.id)
    if isinstance(node, ast.Attribute):
        prefix = _qualified_alias_value_name(node.value, known_names)
        if prefix is None:
            return None
        return f"{prefix}.{node.attr}"
    return None


def _function_types_with_module_aliases(
    function_types: dict[str, AotFunctionInfo],
    rename_map: dict[str, str],
) -> dict[str, AotFunctionInfo]:
    aliased: dict[str, AotFunctionInfo] = {}
    for local_name, target_name in rename_map.items():
        if "." in local_name:
            continue
        target_info = function_types.get(target_name)
        if target_info is not None:
            aliased.setdefault(local_name, target_info)
        target_prefix = f"{target_name}."
        local_prefix = f"{local_name}."
        for function_name, function_info in function_types.items():
            if function_name.startswith(target_prefix):
                aliased.setdefault(
                    local_prefix + function_name[len(target_prefix) :],
                    function_info,
                )
    return aliased


def _module_function_alias_tables(
    function_types: dict[str, AotFunctionInfo],
    rename_maps: dict[str, dict[str, str]],
) -> dict[str, dict[str, AotFunctionInfo]]:
    return {
        module_name: _function_types_with_module_aliases(function_types, rename_map)
        for module_name, rename_map in rename_maps.items()
    }


def _split_module_function(
    target: str,
    inputs_by_name: dict[str, AotSliceInput],
) -> tuple[str | None, str | None]:
    for module_name in sorted(inputs_by_name, key=_string_length, reverse=True):
        prefix = f"{module_name}."
        if target.startswith(prefix):
            return module_name, target[len(prefix) :]
    return None, None


def _slice_input_name(module: AotSliceInput) -> str:
    return module.name


def _string_length(value: str) -> int:
    return len(value)


def core_slice_entry_module(module: IrModule, wrapper: IrFunction) -> IrModule:
    functions_by_name = {function.name: function for function in module.functions}
    reachable: set[str] = set()
    pending = list(_function_call_targets(wrapper))
    while pending:
        target = pending.pop()
        if target in reachable:
            continue
        function = functions_by_name.get(target)
        if function is None:
            continue
        reachable.add(target)
        if function.name in _NATIVE_EMITTED_LEAF_FUNCTIONS:
            pending.extend(_native_leaf_dependencies(function.name))
            continue
        pending.extend(_function_call_targets(function))
    return IrModule(
        module.filename,
        module.records,
        tuple(function for function in module.functions if function.name in reachable) + (wrapper,),
        entry=wrapper.name,
    )


def core_entry_wrapper(entry: str, fixture: str) -> IrFunction:
    if entry == "xcc.diag:Diagnostic.__str__" and fixture == "diag_with_location":
        return _diagnostic_str_wrapper()
    if entry == "xcc.options:FrontendOptions.__post_init__" and fixture == "bad_std":
        return _frontend_options_bad_std_wrapper()
    if entry == "xcc.types:Type.pointer_array_str" and fixture == "int_pointer_array":
        return _type_pointer_array_str_wrapper()
    if entry == "xcc.lexer:translate_source" and fixture == "trigraph_splice":
        return _lexer_translate_source_wrapper()
    if entry == "xcc.lexer:lex" and fixture == "simple_declaration":
        return _lexer_lex_simple_declaration_wrapper()
    if entry == "xcc.lexer:lex_pp" and fixture == "header_name":
        return _lexer_header_name_wrapper()
    if entry == "xcc.lexer:lex_error" and fixture == "unterminated_string":
        return _lexer_unterminated_string_wrapper()
    if entry == "xcc.parser.type_specs:ParserError.__str__" and fixture == "missing_type_name":
        return _parser_error_str_wrapper()
    if entry == "xcc.sema.type_helpers:is_integer_type" and fixture == "int_and_void":
        return _sema_integer_type_summary_wrapper()
    raise AotError(
        (
            AotDiagnostic(
                "XCC-AOT-SLICE-0002",
                f"Unsupported core entry fixture: {entry} / {fixture}",
                filename="<core-slice>",
            ),
        )
    )


def _diagnostic_str_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    diagnostic_type = IrRecordType("Diagnostic")
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrPrint(
                IrCall(
                    "xcc.diag.Diagnostic.__str__",
                    (
                        IrConstructRecord(
                            "Diagnostic",
                            (
                                IrConstString("parse"),
                                IrConstString("input.c"),
                                IrConstString("expected ';'"),
                                IrConstInt(7, IrIntType(64, signed=True)),
                                IrConstInt(3, IrIntType(64, signed=True)),
                                IrConstNone(),
                            ),
                            diagnostic_type,
                        ),
                    ),
                    IrStringType(),
                ),
            ),
            IrReturn(IrConstInt(0, int32)),
        ),
    )


def _lexer_translate_source_wrapper() -> IrFunction:
    return _string_call_wrapper(
        "xcc.lexer.translate_source",
        (IrConstString("int??=x\\\n=1;"),),
    )


def _lexer_lex_simple_declaration_wrapper() -> IrFunction:
    return _string_call_wrapper(
        "xcc.lexer._aot_token_summary_for_source",
        (IrConstString("int main() { return 0; }"),),
    )


def _lexer_header_name_wrapper() -> IrFunction:
    return _string_call_wrapper(
        "xcc.lexer._aot_header_summary_for_source",
        (IrConstString("<stdio.h>"),),
    )


def _lexer_unterminated_string_wrapper() -> IrFunction:
    return _string_call_wrapper(
        "xcc.lexer._aot_error_summary_for_source",
        (IrConstString('"'),),
        status=2,
    )


def _parser_error_str_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    int64 = IrIntType(64, signed=True)
    token_type = IrRecordType("Token")
    error_type = IrRecordType("ParserError")
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrPrint(
                IrCall(
                    "xcc.parser.type_specs.ParserError.__str__",
                    (
                        IrConstructRecord(
                            "ParserError",
                            (
                                IrConstString("Type name is missing before ';'"),
                                IrConstructRecord(
                                    "Token",
                                    (
                                        IrConstNone(),
                                        IrConstString(";"),
                                        IrConstInt(4, int64),
                                        IrConstInt(9, int64),
                                    ),
                                    token_type,
                                ),
                            ),
                            error_type,
                        ),
                    ),
                    IrStringType(),
                ),
            ),
            IrReturn(IrConstInt(0, int32)),
        ),
    )


def _sema_integer_type_summary_wrapper() -> IrFunction:
    return _string_call_wrapper("xcc.sema.type_helpers._aot_integer_type_summary", ())


def _string_call_wrapper(
    target: str,
    args: tuple[IrExpr, ...],
    *,
    status: int = 0,
) -> IrFunction:
    int32 = IrIntType(32, signed=True)
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrPrint(IrCall(target, args, IrStringType())),
            IrReturn(IrConstInt(status, int32)),
        ),
    )


def _rename_statement_calls(
    statements: tuple[IrStmt, ...],
    rename_map: dict[str, str],
) -> tuple[IrStmt, ...]:
    return tuple(_rename_statement_call(statement, rename_map) for statement in statements)


def _rename_statement_call(statement: IrStmt, rename_map: dict[str, str]) -> IrStmt:
    if isinstance(statement, IrAssign):
        return IrAssign(
            statement.target,
            _rename_expr_call(statement.value, rename_map),
            statement.span,
            statement.chain,
        )
    if isinstance(statement, IrSetItem):
        return IrSetItem(
            _rename_expr_call(statement.target, rename_map),
            _rename_expr_call(statement.index, rename_map),
            _rename_expr_call(statement.value, rename_map),
            statement.span,
        )
    if isinstance(statement, IrReturn):
        return IrReturn(_rename_expr_call(statement.value, rename_map), statement.span)
    if isinstance(statement, IrIf):
        return IrIf(
            _rename_expr_call(statement.condition, rename_map),
            _rename_branch_calls(statement.then_branch, rename_map),
            (
                _rename_branch_calls(statement.else_branch, rename_map)
                if statement.else_branch is not None
                else None
            ),
            statement.span,
        )
    if isinstance(statement, IrForEach):
        return IrForEach(
            statement.target,
            _rename_expr_call(statement.iterable, rename_map),
            _rename_branch_calls(statement.body, rename_map),
            statement.span,
        )
    if isinstance(statement, IrWhile):
        return IrWhile(
            _rename_expr_call(statement.condition, rename_map),
            _rename_branch_calls(statement.body, rename_map),
            statement.span,
        )
    if isinstance(statement, (IrBreak, IrContinue)):
        return statement
    if isinstance(statement, IrPrint):
        return IrPrint(_rename_expr_call(statement.value, rename_map), statement.span)
    if isinstance(statement, IrRaise):
        return IrRaise(
            statement.exception,
            _rename_expr_call(statement.message, rename_map),
            statement.span,
            (
                _rename_expr_call(statement.payload, rename_map)
                if statement.payload is not None
                else None
            ),
        )
    if isinstance(statement, IrReraise):
        return statement
    if isinstance(statement, IrTry):
        return IrTry(
            _rename_branch_calls(statement.body, rename_map),
            tuple(
                IrExceptHandler(
                    handler.exceptions,
                    handler.target,
                    _rename_branch_calls(handler.body, rename_map),
                )
                for handler in statement.handlers
            ),
            _rename_branch_calls(statement.orelse, rename_map),
            _rename_branch_calls(statement.finalbody, rename_map),
            statement.span,
        )
    assert_never(statement)


def _rename_branch_calls(branch: IrBranch, rename_map: dict[str, str]) -> IrBranch:
    return IrBranch(_rename_statement_calls(branch.statements, rename_map))


def _rename_expr_call(expr: IrExpr, rename_map: dict[str, str]) -> IrExpr:
    if isinstance(
        expr,
        IrConstInt
        | IrConstBytes
        | IrConstString
        | IrConstFloat
        | IrConstBool
        | IrConstNone
        | IrEnumMember
        | IrName,
    ):
        return expr
    if isinstance(expr, IrBinary):
        return IrBinary(
            expr.op,
            _rename_expr_call(expr.left, rename_map),
            _rename_expr_call(expr.right, rename_map),
            expr.type,
        )
    if isinstance(expr, IrGetField):
        return IrGetField(_rename_expr_call(expr.value, rename_map), expr.field, expr.type)
    if isinstance(expr, IrConstructRecord):
        return IrConstructRecord(
            expr.record,
            tuple(_rename_expr_call(arg, rename_map) for arg in expr.args),
            expr.type,
        )
    if isinstance(expr, IrCall):
        return IrCall(
            _rename_call_target(expr.target, rename_map),
            tuple(_rename_expr_call(arg, rename_map) for arg in expr.args),
            expr.type,
        )
    if isinstance(expr, IrTuple):
        return IrTuple(
            tuple(_rename_expr_call(element, rename_map) for element in expr.elements),
            expr.type,
        )
    if isinstance(expr, IrTupleSlice):
        return IrTupleSlice(
            _rename_expr_call(expr.value, rename_map),
            (_rename_expr_call(expr.start, rename_map) if expr.start is not None else None),
            _rename_expr_call(expr.stop, rename_map) if expr.stop is not None else None,
        )
    if isinstance(expr, IrStringConcat):
        return IrStringConcat(tuple(_rename_expr_call(part, rename_map) for part in expr.parts))
    if isinstance(expr, IrStringJoin):
        return IrStringJoin(
            _rename_expr_call(expr.separator, rename_map),
            _rename_expr_call(expr.values, rename_map),
        )
    assert_never(expr)


def _rename_call_target(target: str, rename_map: dict[str, str]) -> str:
    if target.startswith(_NORETURN_CALL_PREFIX):
        call_target = target.removeprefix(_NORETURN_CALL_PREFIX)
        return _NORETURN_CALL_PREFIX + _rename_call_target(call_target, rename_map)
    if target.startswith(_RECORD_INIT_PREFIX):
        init_target = target.removeprefix(_RECORD_INIT_PREFIX)
        return _RECORD_INIT_PREFIX + _rename_call_target(init_target, rename_map)
    protocol_target = _CALL_TARGET_OVERRIDES.get(target)
    if protocol_target is not None:
        return protocol_target
    renamed = rename_map.get(target)
    if renamed is not None:
        return _CALL_TARGET_OVERRIDES.get(renamed, renamed)
    for local_name, target_name in rename_map.items():
        prefix = f"{local_name}."
        if target.startswith(prefix):
            renamed_target = f"{target_name}.{target[len(prefix) :]}"
            return _CALL_TARGET_OVERRIDES.get(renamed_target, renamed_target)
    return target


def _function_record_names(function: IrFunction) -> tuple[str, ...]:
    names: set[str] = set()
    for param in function.params:
        _add_type_record_names(param.type, names)
    _add_type_record_names(function.return_type, names)
    for statement in function.body:
        _add_statement_record_names(statement, names)
    return tuple(sorted(names))


def _statement_record_names(statement: IrStmt) -> tuple[str, ...]:
    names: set[str] = set()
    _add_statement_record_names(statement, names)
    return tuple(sorted(names))


def _add_statement_record_names(statement: IrStmt, names: set[str]) -> None:
    if isinstance(statement, IrAssign):
        _add_expr_record_names(statement.value, names)
        return
    if isinstance(statement, IrSetItem):
        _add_expr_record_names(statement.target, names)
        _add_expr_record_names(statement.index, names)
        _add_expr_record_names(statement.value, names)
        return
    if isinstance(statement, IrReturn):
        _add_expr_record_names(statement.value, names)
        return
    if isinstance(statement, IrIf):
        _add_expr_record_names(statement.condition, names)
        _add_branch_record_names(statement.then_branch, names)
        if statement.else_branch is not None:
            _add_branch_record_names(statement.else_branch, names)
        return
    if isinstance(statement, IrForEach):
        _add_expr_record_names(statement.iterable, names)
        _add_branch_record_names(statement.body, names)
        return
    if isinstance(statement, IrWhile):
        _add_expr_record_names(statement.condition, names)
        _add_branch_record_names(statement.body, names)
        return
    if isinstance(statement, (IrBreak, IrContinue)):
        return
    if isinstance(statement, IrPrint):
        _add_expr_record_names(statement.value, names)
        return
    if isinstance(statement, IrRaise):
        _add_expr_record_names(statement.message, names)
        if statement.payload is not None:
            _add_expr_record_names(statement.payload, names)
        return
    if isinstance(statement, IrReraise):
        return
    if isinstance(statement, IrTry):
        _add_branch_record_names(statement.body, names)
        _add_branch_record_names(statement.orelse, names)
        _add_branch_record_names(statement.finalbody, names)
        for handler in statement.handlers:
            _add_branch_record_names(handler.body, names)
        return
    assert_never(statement)


def _branch_record_names(branch: IrBranch) -> tuple[str, ...]:
    names: set[str] = set()
    _add_branch_record_names(branch, names)
    return tuple(sorted(names))


def _add_branch_record_names(branch: IrBranch, names: set[str]) -> None:
    for statement in branch.statements:
        _add_statement_record_names(statement, names)


def _expr_record_names(expr: IrExpr) -> tuple[str, ...]:
    names: set[str] = set()
    _add_expr_record_names(expr, names)
    return tuple(sorted(names))


def _add_expr_record_names(expr: IrExpr, names: set[str]) -> None:
    _add_type_record_names(expr.type, names)
    if isinstance(expr, IrName) and _record_constructor_type_base_name(expr.type) is not None:
        names.add(expr.name)
    if isinstance(
        expr,
        IrConstInt
        | IrConstBytes
        | IrConstString
        | IrConstFloat
        | IrConstBool
        | IrConstNone
        | IrEnumMember
        | IrName,
    ):
        return
    if isinstance(expr, IrBinary):
        _add_expr_record_names(expr.left, names)
        _add_expr_record_names(expr.right, names)
        return
    if isinstance(expr, IrGetField):
        _add_expr_record_names(expr.value, names)
        return
    if isinstance(expr, IrConstructRecord):
        names.add(expr.record)
        _add_expr_tuple_record_names(expr.args, names)
        return
    if isinstance(expr, IrCall):
        _add_expr_tuple_record_names(expr.args, names)
        if expr.target == "isinstance" and len(expr.args) == 2:
            _add_isinstance_marker_record_names(expr.args[1], names)
        return
    if isinstance(expr, IrTuple):
        _add_expr_tuple_record_names(expr.elements, names)
        return
    if isinstance(expr, IrTupleSlice):
        _add_expr_record_names(expr.value, names)
        if expr.start is not None:
            _add_expr_record_names(expr.start, names)
        if expr.stop is not None:
            _add_expr_record_names(expr.stop, names)
        return
    if isinstance(expr, IrStringConcat):
        _add_expr_tuple_record_names(expr.parts, names)
        return
    if isinstance(expr, IrStringJoin):
        _add_expr_record_names(expr.separator, names)
        _add_expr_record_names(expr.values, names)
        return
    assert_never(expr)


def _expr_tuple_record_names(expressions: tuple[IrExpr, ...]) -> tuple[str, ...]:
    names: set[str] = set()
    _add_expr_tuple_record_names(expressions, names)
    return tuple(sorted(names))


def _add_expr_tuple_record_names(expressions: tuple[IrExpr, ...], names: set[str]) -> None:
    for expression in expressions:
        _add_expr_record_names(expression, names)


def _isinstance_marker_record_names(marker: IrExpr) -> tuple[str, ...]:
    names: set[str] = set()
    _add_isinstance_marker_record_names(marker, names)
    return tuple(sorted(names))


def _add_isinstance_marker_record_names(marker: IrExpr, names: set[str]) -> None:
    if isinstance(marker, IrName):
        names.add(marker.name)
        return
    if isinstance(marker, IrTuple):
        for element in marker.elements:
            if isinstance(element, IrName):
                names.add(element.name)


def _type_record_names(
    type_info: IrDictType | IrRecordType | IrTupleType | object,
) -> tuple[str, ...]:
    names: set[str] = set()
    _add_type_record_names(type_info, names)
    return tuple(sorted(names))


def _add_type_record_names(
    type_info: IrDictType | IrRecordType | IrTupleType | object,
    names: set[str],
) -> None:
    if isinstance(type_info, IrRecordType):
        if type_info.name in _INTERNAL_RECORD_TYPES:
            return
        if _record_constructor_type_base_name(type_info) is not None:
            return
        names.add(type_info.name)
        return
    if isinstance(type_info, IrTupleType):
        for element in type_info.elements:
            _add_type_record_names(element, names)
        return
    if isinstance(type_info, IrDictType):
        _add_type_record_names(type_info.key, names)
        _add_type_record_names(type_info.value, names)


def _record_constructor_type_base_name(type_info: object) -> str | None:
    if not isinstance(type_info, IrRecordType):
        return None
    name = type_info.name
    if not name.startswith("type[") or not name.endswith("]"):
        return None
    return name[5:-1]


def _function_call_targets(function: IrFunction) -> tuple[str, ...]:
    targets: list[str] = []
    for statement in function.body:
        _add_statement_call_targets(statement, targets)
    return tuple(targets)


def _native_leaf_dependencies(function_name: str) -> tuple[str, ...]:
    return _NATIVE_EMITTED_LEAF_DEPENDENCIES.get(function_name, ())


def _statement_call_targets(statement: IrStmt) -> tuple[str, ...]:
    targets: list[str] = []
    _add_statement_call_targets(statement, targets)
    return tuple(targets)


def _add_statement_call_targets(statement: IrStmt, targets: list[str]) -> None:
    if isinstance(statement, IrAssign):
        _add_expr_call_targets(statement.value, targets)
        return
    if isinstance(statement, IrSetItem):
        _add_expr_call_targets(statement.target, targets)
        _add_expr_call_targets(statement.index, targets)
        _add_expr_call_targets(statement.value, targets)
        return
    if isinstance(statement, IrReturn):
        _add_expr_call_targets(statement.value, targets)
        return
    if isinstance(statement, IrIf):
        _add_expr_call_targets(statement.condition, targets)
        _add_branch_call_targets(statement.then_branch, targets)
        if statement.else_branch is not None:
            _add_branch_call_targets(statement.else_branch, targets)
        return
    if isinstance(statement, IrForEach):
        _add_expr_call_targets(statement.iterable, targets)
        _add_branch_call_targets(statement.body, targets)
        return
    if isinstance(statement, IrWhile):
        _add_expr_call_targets(statement.condition, targets)
        _add_branch_call_targets(statement.body, targets)
        return
    if isinstance(statement, (IrBreak, IrContinue)):
        return
    if isinstance(statement, IrPrint):
        _add_expr_call_targets(statement.value, targets)
        return
    if isinstance(statement, IrRaise):
        _add_expr_call_targets(statement.message, targets)
        if statement.payload is not None:
            _add_expr_call_targets(statement.payload, targets)
        return
    if isinstance(statement, IrReraise):
        return
    if isinstance(statement, IrTry):
        _add_branch_call_targets(statement.body, targets)
        _add_branch_call_targets(statement.orelse, targets)
        _add_branch_call_targets(statement.finalbody, targets)
        for handler in statement.handlers:
            _add_branch_call_targets(handler.body, targets)
        return
    assert_never(statement)


def _branch_call_targets(branch: IrBranch) -> tuple[str, ...]:
    targets: list[str] = []
    _add_branch_call_targets(branch, targets)
    return tuple(targets)


def _add_branch_call_targets(branch: IrBranch, targets: list[str]) -> None:
    for statement in branch.statements:
        _add_statement_call_targets(statement, targets)


def _expr_call_targets(expr: IrExpr) -> tuple[str, ...]:
    targets: list[str] = []
    _add_expr_call_targets(expr, targets)
    return tuple(targets)


def _add_expr_call_targets(expr: IrExpr, targets: list[str]) -> None:
    if isinstance(
        expr,
        IrConstInt
        | IrConstString
        | IrConstBytes
        | IrConstFloat
        | IrConstBool
        | IrConstNone
        | IrEnumMember
        | IrName,
    ):
        return
    if isinstance(expr, IrBinary):
        _add_expr_call_targets(expr.left, targets)
        _add_expr_call_targets(expr.right, targets)
        return
    if isinstance(expr, IrGetField):
        _add_expr_call_targets(expr.value, targets)
        return
    if isinstance(expr, IrConstructRecord):
        targets.append(f"{expr.record}.__init__")
        _add_expr_tuple_call_targets(expr.args, targets)
        return
    if isinstance(expr, IrCall):
        if expr.target.startswith(_NORETURN_CALL_PREFIX):
            targets.append(expr.target.removeprefix(_NORETURN_CALL_PREFIX))
        elif expr.target.startswith(_RECORD_INIT_PREFIX):
            targets.append(expr.target.removeprefix(_RECORD_INIT_PREFIX))
        else:
            targets.append(expr.target)
        _add_expr_tuple_call_targets(expr.args, targets)
        return
    if isinstance(expr, IrTuple):
        _add_expr_tuple_call_targets(expr.elements, targets)
        return
    if isinstance(expr, IrTupleSlice):
        _add_expr_call_targets(expr.value, targets)
        if expr.start is not None:
            _add_expr_call_targets(expr.start, targets)
        if expr.stop is not None:
            _add_expr_call_targets(expr.stop, targets)
        return
    if isinstance(expr, IrStringConcat):
        _add_expr_tuple_call_targets(expr.parts, targets)
        return
    if isinstance(expr, IrStringJoin):
        _add_expr_call_targets(expr.separator, targets)
        _add_expr_call_targets(expr.values, targets)
        return
    assert_never(expr)


def _expr_tuple_call_targets(expressions: tuple[IrExpr, ...]) -> tuple[str, ...]:
    targets: list[str] = []
    _add_expr_tuple_call_targets(expressions, targets)
    return tuple(targets)


def _add_expr_tuple_call_targets(expressions: tuple[IrExpr, ...], targets: list[str]) -> None:
    for expression in expressions:
        _add_expr_call_targets(expression, targets)


def _frontend_options_bad_std_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    options_type = IrRecordType("FrontendOptions")
    string_tuple = IrConstNone()
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrAssign(
                "__expr",
                IrCall(
                    "xcc.options.FrontendOptions.__post_init__",
                    (
                        IrConstructRecord(
                            "FrontendOptions",
                            (
                                IrConstString("c99"),
                                IrConstBool(True),
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                string_tuple,
                                IrConstBool(False),
                                IrConstString("human"),
                                IrConstBool(False),
                                IrConstNone(),
                                IrConstNone(),
                                IrConstBool(True),
                            ),
                            options_type,
                        ),
                    ),
                    IrNoneType(),
                ),
            ),
            IrReturn(IrConstInt(2, int32)),
        ),
    )


def _type_pointer_array_str_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    int64 = IrIntType(64, signed=True)
    type_type = IrRecordType("Type")
    op_type = IrTupleType((IrStringType(), int64))
    declarator_ops = IrTuple(
        (
            IrTuple((IrConstString("arr"), IrConstInt(4, int64)), op_type),
            IrTuple((IrConstString("ptr"), IrConstInt(0, int64)), op_type),
        ),
        IrTupleType((op_type, op_type)),
    )
    array = IrConstructRecord(
        "Type",
        (
            IrConstString("int"),
            declarator_ops,
            IrTuple((), IrTupleType((IrStringType(),))),
        ),
        type_type,
    )
    rendered = IrCall("xcc.types.Type.__str__", (array,), IrStringType())
    return IrFunction(
        "__xcc_aot_core_entry",
        (),
        int32,
        (
            IrPrint(rendered),
            IrReturn(IrConstInt(0, int32)),
        ),
    )
