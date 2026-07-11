import ast
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from xcc.aot.analysis import analyze_source
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrBranch,
    IrBreak,
    IrCall,
    IrConstBool,
    IrConstFloat,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrContinue,
    IrEnumMember,
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
    IrReturn,
    IrSetItem,
    IrStmt,
    IrStringConcat,
    IrStringJoin,
    IrStringType,
    IrTuple,
    IrTupleSlice,
    IrTupleType,
    IrWhile,
)
from xcc.aot.lower import (
    _collect_global_string_constants,
    _collect_global_string_container_constants,
    lower_source_to_ir,
)
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotType

_NATIVE_EMITTED_LEAF_FUNCTIONS = {
    "xcc.cc_driver._aot_compile_source_to_llvm_ir",
    "xcc.cc_driver._aot_exec_argv",
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
    "xcc.preprocessor.__init__._Preprocessor._expand_line",
    "xcc.preprocessor.__init__._Preprocessor._expand_macro_text",
    "xcc.preprocessor.__init__._Preprocessor._handle_define",
    "xcc.preprocessor.__init__._Preprocessor._handle_pragma_operator",
    "xcc.preprocessor.__init__._Preprocessor._should_collect_function_macro_continuation",
    "xcc.preprocessor.__init__._Preprocessor._handle_undef",
    "xcc.sema.type_helpers._aot_integer_type_summary",
    "xcc.types.Type.__str__",
}
_BOOTSTRAP_REAL_COMPILER_TARGETS = (
    "xcc.cc_driver._aot_compile_source_to_llvm_ir_unchecked",
    "xcc.frontend._aot_compile_source_unchecked",
    "xcc.codegen.generate_llvm_ir",
    "xcc.codegen._LLVMGen.generate",
)
_NATIVE_EMITTED_LEAF_DEPENDENCIES = {
    "xcc.cc_driver._aot_compile_source_to_llvm_ir": _BOOTSTRAP_REAL_COMPILER_TARGETS,
}
_PROTOCOL_METHOD_TARGETS = {
    "xcc.preprocessor.__init__.preprocess_source": (
        "xcc.preprocessor.__init__.preprocess_source_no_callback"
    ),
    "xcc.parser.statements._StatementParser._advance": "xcc.parser.__init__.Parser._advance",
    "xcc.parser.statements._StatementParser._check_keyword": (
        "xcc.parser.__init__.Parser._check_keyword"
    ),
    "xcc.parser.statements._StatementParser._check_punct": (
        "xcc.parser.__init__.Parser._check_punct"
    ),
    "xcc.parser.statements._StatementParser._current": "xcc.parser.__init__.Parser._current",
    "xcc.parser.statements._StatementParser._expect": "xcc.parser.__init__.Parser._expect",
    "xcc.parser.statements._StatementParser._expect_punct": (
        "xcc.parser.__init__.Parser._expect_punct"
    ),
    "xcc.parser.statements._StatementParser._is_declaration_start": (
        "xcc.parser.__init__.Parser._is_declaration_start"
    ),
    "xcc.parser.statements._StatementParser._is_label_start": (
        "xcc.parser.__init__.Parser._is_label_start"
    ),
    "xcc.parser.statements._StatementParser._is_typedef_name": (
        "xcc.parser.__init__.Parser._is_typedef_name"
    ),
    "xcc.parser.statements._StatementParser._make_error": (
        "xcc.parser.__init__.Parser._make_error"
    ),
    "xcc.parser.statements._StatementParser._parse_assignment": (
        "xcc.parser.__init__.Parser._parse_assignment"
    ),
    "xcc.parser.statements._StatementParser._parse_case_stmt": (
        "xcc.parser.__init__.Parser._parse_case_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_compound_stmt": (
        "xcc.parser.__init__.Parser._parse_compound_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_conditional": (
        "xcc.parser.__init__.Parser._parse_conditional"
    ),
    "xcc.parser.statements._StatementParser._parse_decl_stmt": (
        "xcc.parser.__init__.Parser._parse_decl_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_default_stmt": (
        "xcc.parser.__init__.Parser._parse_default_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_designator_list": (
        "xcc.parser.__init__.Parser._parse_designator_list"
    ),
    "xcc.parser.statements._StatementParser._parse_do_while_stmt": (
        "xcc.parser.__init__.Parser._parse_do_while_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_expression": (
        "xcc.parser.__init__.Parser._parse_expression"
    ),
    "xcc.parser.statements._StatementParser._parse_for_stmt": (
        "xcc.parser.__init__.Parser._parse_for_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_goto_stmt": (
        "xcc.parser.__init__.Parser._parse_goto_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_if_stmt": (
        "xcc.parser.__init__.Parser._parse_if_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_initializer": (
        "xcc.parser.__init__.Parser._parse_initializer"
    ),
    "xcc.parser.statements._StatementParser._parse_initializer_list": (
        "xcc.parser.__init__.Parser._parse_initializer_list"
    ),
    "xcc.parser.statements._StatementParser._parse_label_stmt": (
        "xcc.parser.__init__.Parser._parse_label_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_return_stmt": (
        "xcc.parser.__init__.Parser._parse_return_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_static_assert_decl": (
        "xcc.parser.__init__.Parser._parse_static_assert_decl"
    ),
    "xcc.parser.statements._StatementParser._parse_statement": (
        "xcc.parser.__init__.Parser._parse_statement"
    ),
    "xcc.parser.statements._StatementParser._parse_string_literal": (
        "xcc.parser.__init__.Parser._parse_string_literal"
    ),
    "xcc.parser.statements._StatementParser._parse_switch_stmt": (
        "xcc.parser.__init__.Parser._parse_switch_stmt"
    ),
    "xcc.parser.statements._StatementParser._parse_while_stmt": (
        "xcc.parser.__init__.Parser._parse_while_stmt"
    ),
    "xcc.parser.statements._StatementParser._peek_punct": (
        "xcc.parser.__init__.Parser._peek_punct"
    ),
    "xcc.parser.statements._StatementParser._pop_scope": ("xcc.parser.__init__.Parser._pop_scope"),
    "xcc.parser.statements._StatementParser._push_scope": (
        "xcc.parser.__init__.Parser._push_scope"
    ),
    "xcc.parser.statements._StatementParser._skip_decl_attributes": (
        "xcc.parser.__init__.Parser._skip_decl_attributes"
    ),
    "xcc.parser.statements._StatementParser._skip_extension_markers": (
        "xcc.parser.__init__.Parser._skip_extension_markers"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._alignof_type": (
        "xcc.sema.__init__.Analyzer._alignof_type"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._analyze_file_scope_decl": (
        "xcc.sema.__init__.Analyzer._analyze_file_scope_decl"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._analyze_initializer": (
        "xcc.sema.__init__.Analyzer._analyze_initializer"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._check_static_assert": (
        "xcc.sema.__init__.Analyzer._check_static_assert"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._define_enum_members": (
        "xcc.sema.__init__.Analyzer._define_enum_members"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._ensure_array_size_limit": (
        "xcc.sema.__init__.Analyzer._ensure_array_size_limit"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._extern_initializer_message": (
        "xcc.sema.__init__.Analyzer._extern_initializer_message"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._infer_array_size_from_init": (
        "xcc.sema.__init__.Analyzer._infer_array_size_from_init"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._invalid_alignment_message": (
        "xcc.sema.__init__.Analyzer._invalid_alignment_message"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._invalid_object_type_message": (
        "xcc.sema.__init__.Analyzer._invalid_object_type_message"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._invalid_typedef_type_message": (
        "xcc.sema.__init__.Analyzer._invalid_typedef_type_message"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._is_const_qualified": (
        "xcc.sema.__init__.Analyzer._is_const_qualified"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._is_file_scope_vla_type_spec": (
        "xcc.sema.__init__.Analyzer._is_file_scope_vla_type_spec"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._is_function_object_type": (
        "xcc.sema.__init__.Analyzer._is_function_object_type"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._is_invalid_atomic_type_spec": (
        "xcc.sema.__init__.Analyzer._is_invalid_atomic_type_spec"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._is_invalid_incomplete_record_object_type": (
        "xcc.sema.__init__.Analyzer._is_invalid_incomplete_record_object_type"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._is_invalid_void_object_type": (
        "xcc.sema.__init__.Analyzer._is_invalid_void_object_type"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._is_valid_explicit_alignment": (
        "xcc.sema.__init__.Analyzer._is_valid_explicit_alignment"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._missing_identifier_for_alignment_message": (
        "xcc.sema.__init__.Analyzer._missing_identifier_for_alignment_message"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._missing_object_identifier_message": (
        "xcc.sema.__init__.Analyzer._missing_object_identifier_message"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._register_function_typed_file_scope_decl": (
        "xcc.sema.__init__.Analyzer._register_function_typed_file_scope_decl"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._register_transparent_union_typedef": (
        "xcc.sema.__init__.Analyzer._register_transparent_union_typedef"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._register_type_spec": (
        "xcc.sema.__init__.Analyzer._register_type_spec"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._resolve_type": (
        "xcc.sema.__init__.Analyzer._resolve_type"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._thread_local_storage_class_message": (
        "xcc.sema.__init__.Analyzer._thread_local_storage_class_message"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._try_eval_scalar_initializer": (
        "xcc.sema.__init__.Analyzer._try_eval_scalar_initializer"
    ),
    "xcc.sema.declarations._FileScopeAnalyzer._typedef_storage_class_object_message": (
        "xcc.sema.__init__.Analyzer._typedef_storage_class_object_message"
    ),
    (
        "xcc.preprocessor.process._ProcessTextPreprocessor."
        "_should_collect_function_macro_continuation"
    ): "xcc.preprocessor.__init__._Preprocessor._should_collect_function_macro_continuation",
    "xcc.preprocessor.process._ProcessTextPreprocessor._expand_line": (
        "xcc.preprocessor.__init__._Preprocessor._expand_line_no_callback"
    ),
    "xcc.preprocessor.process._ProcessTextPreprocessor._handle_conditional": (
        "xcc.preprocessor.__init__._Preprocessor._handle_conditional_no_callback"
    ),
    "xcc.preprocessor.process._ProcessTextPreprocessor._handle_conditional_for_process": (
        "xcc.preprocessor.__init__._Preprocessor._handle_conditional_for_process_no_callback"
    ),
    "xcc.preprocessor.process._ProcessTextPreprocessor._handle_define": (
        "xcc.preprocessor.__init__._Preprocessor._handle_define_no_callback"
    ),
    "xcc.preprocessor.process._ProcessTextPreprocessor._handle_undef": (
        "xcc.preprocessor.__init__._Preprocessor._handle_undef_no_callback"
    ),
    "xcc.preprocessor.process._ProcessTextPreprocessor._handle_include": (
        "xcc.preprocessor.__init__._Preprocessor._handle_include"
    ),
    "xcc.preprocessor.process._ProcessTextPreprocessor._parse_line_directive": (
        "xcc.preprocessor.__init__._Preprocessor._parse_line_directive"
    ),
    "xcc.preprocessor.process._ProcessTextPreprocessor._handle_pack_pragma": (
        "xcc.preprocessor.__init__._Preprocessor._handle_pack_pragma"
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
        module.name: module.path.read_text(encoding="utf-8") for module in module_inputs
    }
    class_types, _ = _slice_class_tables(module_inputs, source_cache)
    function_types = _slice_method_signature_table(module_inputs, source_cache)
    aliases = _slice_type_aliases(module_inputs, source_cache)
    global_annotations = _slice_global_annotations(module_inputs, source_cache)
    global_string_constants = _slice_global_string_constants(module_inputs, source_cache)
    global_string_container_constants = _slice_global_string_container_constants(
        module_inputs,
        source_cache,
    )
    records: list[IrRecord] = []
    functions: list[IrFunction] = []
    module_names = frozenset(source_cache)
    for module_input in module_inputs:
        source = source_cache[module_input.name]
        rename_map = _module_rename_map(module_input.name, source, module_names)
        module = lower_source_to_ir(
            source,
            filename=str(module_input.path),
            extra_classes=class_types,
            extra_functions=_function_types_with_module_aliases(
                function_types,
                rename_map,
            ),
            extra_aliases=aliases,
            extra_global_annotations=global_annotations,
            extra_global_string_constants=global_string_constants,
            extra_global_string_container_constants=global_string_container_constants,
        )
        records.extend(module.records)
        for function in module.functions:
            functions.append(
                IrFunction(
                    rename_map[function.name],
                    function.params,
                    function.return_type,
                    _rename_statement_calls(function.body, rename_map),
                )
            )
    return IrModule("<core-slice>", tuple(records), tuple(functions))


def _lower_core_slice_from_roots(
    paths: tuple[Path, ...],
    root_targets: tuple[str, ...],
    required_records: tuple[str, ...],
) -> IrModule:
    module_inputs = collect_slice_inputs(paths)
    inputs_by_name = {module.name: module for module in module_inputs}
    source_cache = {
        module.name: module.path.read_text(encoding="utf-8") for module in module_inputs
    }
    class_types, class_modules = _slice_class_tables(module_inputs, source_cache)
    function_types = _slice_method_signature_table(module_inputs, source_cache)
    aliases = _slice_type_aliases(module_inputs, source_cache)
    global_annotations = _slice_global_annotations(module_inputs, source_cache)
    global_string_constants = _slice_global_string_constants(module_inputs, source_cache)
    global_string_container_constants = _slice_global_string_container_constants(
        module_inputs,
        source_cache,
    )
    module_names = frozenset(source_cache)
    rename_maps = {
        module.name: _module_rename_map(module.name, source_cache[module.name], module_names)
        for module in module_inputs
    }
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
        module_input = inputs_by_name[module_name]
        bodyless = (
            frozenset({local_name}) if target in _NATIVE_EMITTED_LEAF_FUNCTIONS else frozenset()
        )
        include_records = set(record_names)
        if "." in local_name:
            include_records.add(local_name.split(".", 1)[0])
        rename_map = rename_maps[module_name]
        module = lower_source_to_ir(
            source_cache[module_name],
            filename=str(module_input.path),
            include_records=include_records,
            include_functions={local_name},
            bodyless_functions=bodyless,
            extra_classes=class_types,
            extra_functions=_function_types_with_module_aliases(
                function_types,
                rename_map,
            ),
            extra_aliases=aliases,
            extra_global_annotations=global_annotations,
            extra_global_string_constants=global_string_constants,
            extra_global_string_container_constants=global_string_container_constants,
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
                aliases,
                global_annotations,
                global_string_constants,
                global_string_container_constants,
            )
        for function in module.functions:
            full_name = rename_map[function.name]
            lowered = IrFunction(
                full_name,
                function.params,
                function.return_type,
                _rename_statement_calls(function.body, rename_map),
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
                    aliases,
                    global_annotations,
                    global_string_constants,
                    global_string_container_constants,
                )
            pending.extend(_function_call_targets(lowered))
    return IrModule("<core-slice>", tuple(records_by_name.values()), tuple(functions.values()))


def _slice_class_tables(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
) -> tuple[dict[str, AotClassInfo], dict[str, str]]:
    class_types: dict[str, AotClassInfo] = {}
    class_modules: dict[str, str] = {}
    for module_input in module_inputs:
        analysis = analyze_source(
            source_cache[module_input.name],
            filename=str(module_input.path),
        )
        for class_name, class_info in analysis.types.classes.items():
            class_types.setdefault(class_name, class_info)
            class_modules.setdefault(class_name, module_input.name)
    return class_types, class_modules


def _slice_method_signature_table(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
) -> dict[str, AotFunctionInfo]:
    function_types: dict[str, AotFunctionInfo] = {}
    for module_input in module_inputs:
        analysis = analyze_source(
            source_cache[module_input.name],
            filename=str(module_input.path),
        )
        for function_name, function_info in analysis.types.functions.items():
            function_types.setdefault(function_name, function_info)
            function_types.setdefault(f"{module_input.name}.{function_name}", function_info)
    return function_types


def _slice_type_aliases(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
) -> dict[str, AotType]:
    aliases: dict[str, AotType] = {}
    for module_input in module_inputs:
        analysis = analyze_source(
            source_cache[module_input.name],
            filename=str(module_input.path),
        )
        for alias_name, alias_type in analysis.types.aliases.items():
            aliases.setdefault(alias_name, alias_type)
    return aliases


def _slice_global_annotations(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
) -> dict[str, str]:
    annotations: dict[str, str] = {}
    for module_input in module_inputs:
        tree = ast.parse(source_cache[module_input.name])
        for statement in tree.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                annotations.setdefault(statement.target.id, ast.unparse(statement.annotation))
    return annotations


def _slice_global_string_constants(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
) -> dict[str, str]:
    constants: dict[str, str] = {}
    for module_input in module_inputs:
        tree = ast.parse(source_cache[module_input.name])
        for name, value in _collect_global_string_constants(tree).items():
            constants.setdefault(name, value)
    return constants


def _slice_global_string_container_constants(
    module_inputs: tuple[AotSliceInput, ...],
    source_cache: dict[str, str],
) -> dict[str, IrTuple]:
    constants: dict[str, IrTuple] = {}
    for module_input in module_inputs:
        tree = ast.parse(source_cache[module_input.name])
        for name, value in _collect_global_string_container_constants(tree).items():
            constants.setdefault(name, value)
    return constants


def _add_missing_records(
    missing_records: set[str],
    records_by_name: dict[str, IrRecord],
    class_modules: dict[str, str],
    inputs_by_name: dict[str, AotSliceInput],
    source_cache: dict[str, str],
    class_types: dict[str, AotClassInfo],
    aliases: dict[str, AotType] | None = None,
    global_annotations: dict[str, str] | None = None,
    global_string_constants: dict[str, str] | None = None,
    global_string_container_constants: dict[str, IrTuple] | None = None,
) -> None:
    for record_name in sorted(missing_records):
        if record_name in records_by_name:
            continue
        module_name = class_modules.get(record_name)
        if module_name is None:
            continue
        module_input = inputs_by_name[module_name]
        records_module = lower_source_to_ir(
            source_cache[module_name],
            filename=str(module_input.path),
            include_records={record_name},
            include_functions=frozenset(),
            extra_classes=class_types,
            extra_aliases=aliases,
            extra_global_annotations=global_annotations,
            extra_global_string_constants=global_string_constants,
            extra_global_string_container_constants=global_string_container_constants,
        )
        for record in records_module.records:
            records_by_name.setdefault(record.name, record)


def _module_rename_map(
    module_name: str,
    source: str,
    module_names: frozenset[str] | set[str] | None = None,
) -> dict[str, str]:
    tree = ast.parse(source)
    rename_map = {name: f"{module_name}.{name}" for name in _local_function_names_from_tree(tree)}
    rename_map.update(
        _imported_project_function_names(
            module_name,
            tree,
            frozenset(module_names or ()),
        )
    )
    rename_map.update(_assigned_project_function_aliases(tree, rename_map))
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
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        imported_module = _resolved_import_module(module_name, node)
        if imported_module is None or not imported_module.startswith("xcc."):
            continue
        package_module = f"{imported_module}.__init__"
        for alias in node.names:
            if alias.name == "*":
                continue
            local_name = alias.asname or alias.name
            submodule = f"{imported_module}.{alias.name}"
            if submodule in module_names:
                names[local_name] = submodule
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
        if qualified_name is None or not qualified_name.startswith("xcc."):
            continue
        aliases[target.id] = qualified_name
        known_names[target.id] = qualified_name
    return aliases


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
    aliased = dict(function_types)
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
        return IrAssign(statement.target, _rename_expr_call(statement.value, rename_map))
    if isinstance(statement, IrSetItem):
        return IrSetItem(
            _rename_expr_call(statement.target, rename_map),
            _rename_expr_call(statement.index, rename_map),
            _rename_expr_call(statement.value, rename_map),
        )
    if isinstance(statement, IrReturn):
        return IrReturn(_rename_expr_call(statement.value, rename_map))
    if isinstance(statement, IrIf):
        return IrIf(
            _rename_expr_call(statement.condition, rename_map),
            _rename_branch_calls(statement.then_branch, rename_map),
            (
                _rename_branch_calls(statement.else_branch, rename_map)
                if statement.else_branch is not None
                else None
            ),
        )
    if isinstance(statement, IrForEach):
        return IrForEach(
            statement.target,
            _rename_expr_call(statement.iterable, rename_map),
            _rename_branch_calls(statement.body, rename_map),
        )
    if isinstance(statement, IrWhile):
        return IrWhile(
            _rename_expr_call(statement.condition, rename_map),
            _rename_branch_calls(statement.body, rename_map),
        )
    if isinstance(statement, (IrBreak, IrContinue)):
        return statement
    if isinstance(statement, IrPrint):
        return IrPrint(_rename_expr_call(statement.value, rename_map))
    if isinstance(statement, IrRaise):
        return IrRaise(statement.exception, _rename_expr_call(statement.message, rename_map))
    assert_never(statement)


def _rename_branch_calls(branch: IrBranch, rename_map: dict[str, str]) -> IrBranch:
    return IrBranch(_rename_statement_calls(branch.statements, rename_map))


def _rename_expr_call(expr: IrExpr, rename_map: dict[str, str]) -> IrExpr:
    if isinstance(
        expr,
        IrConstInt
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
        return IrTupleSlice(_rename_expr_call(expr.value, rename_map), expr.start, expr.stop)
    if isinstance(expr, IrStringConcat):
        return IrStringConcat(tuple(_rename_expr_call(part, rename_map) for part in expr.parts))
    if isinstance(expr, IrStringJoin):
        return IrStringJoin(
            _rename_expr_call(expr.separator, rename_map),
            _rename_expr_call(expr.values, rename_map),
        )
    assert_never(expr)


def _rename_call_target(target: str, rename_map: dict[str, str]) -> str:
    protocol_target = _PROTOCOL_METHOD_TARGETS.get(target)
    if protocol_target is not None:
        return protocol_target
    renamed = rename_map.get(target)
    if renamed is not None:
        return _PROTOCOL_METHOD_TARGETS.get(renamed, renamed)
    for local_name, target_name in rename_map.items():
        prefix = f"{local_name}."
        if target.startswith(prefix):
            renamed_target = f"{target_name}.{target[len(prefix) :]}"
            return _PROTOCOL_METHOD_TARGETS.get(renamed_target, renamed_target)
    return target


def _function_record_names(function: IrFunction) -> tuple[str, ...]:
    names: set[str] = set()
    for param in function.params:
        names.update(_type_record_names(param.type))
    names.update(_type_record_names(function.return_type))
    for statement in function.body:
        names.update(_statement_record_names(statement))
    return tuple(sorted(names))


def _statement_record_names(statement: IrStmt) -> tuple[str, ...]:
    if isinstance(statement, IrAssign):
        return _expr_record_names(statement.value)
    if isinstance(statement, IrSetItem):
        names = set(_expr_record_names(statement.target))
        names.update(_expr_record_names(statement.index))
        names.update(_expr_record_names(statement.value))
        return tuple(sorted(names))
    if isinstance(statement, IrReturn):
        return _expr_record_names(statement.value)
    if isinstance(statement, IrIf):
        names = set(_expr_record_names(statement.condition))
        names.update(_branch_record_names(statement.then_branch))
        if statement.else_branch is not None:
            names.update(_branch_record_names(statement.else_branch))
        return tuple(sorted(names))
    if isinstance(statement, IrForEach):
        names = set(_expr_record_names(statement.iterable))
        names.update(_branch_record_names(statement.body))
        return tuple(sorted(names))
    if isinstance(statement, IrWhile):
        names = set(_expr_record_names(statement.condition))
        names.update(_branch_record_names(statement.body))
        return tuple(sorted(names))
    if isinstance(statement, (IrBreak, IrContinue)):
        return ()
    if isinstance(statement, IrPrint):
        return _expr_record_names(statement.value)
    if isinstance(statement, IrRaise):
        return _expr_record_names(statement.message)
    assert_never(statement)


def _branch_record_names(branch: IrBranch) -> tuple[str, ...]:
    names: set[str] = set()
    for statement in branch.statements:
        names.update(_statement_record_names(statement))
    return tuple(sorted(names))


def _expr_record_names(expr: IrExpr) -> tuple[str, ...]:
    names = set(_type_record_names(expr.type))
    if isinstance(
        expr,
        IrConstInt
        | IrConstString
        | IrConstFloat
        | IrConstBool
        | IrConstNone
        | IrEnumMember
        | IrName,
    ):
        return tuple(sorted(names))
    if isinstance(expr, IrBinary):
        names.update(_expr_record_names(expr.left))
        names.update(_expr_record_names(expr.right))
        return tuple(sorted(names))
    if isinstance(expr, IrGetField):
        names.update(_expr_record_names(expr.value))
        return tuple(sorted(names))
    if isinstance(expr, IrConstructRecord):
        names.add(expr.record)
        names.update(_expr_tuple_record_names(expr.args))
        return tuple(sorted(names))
    if isinstance(expr, IrCall):
        names.update(_expr_tuple_record_names(expr.args))
        return tuple(sorted(names))
    if isinstance(expr, IrTuple):
        names.update(_expr_tuple_record_names(expr.elements))
        return tuple(sorted(names))
    if isinstance(expr, IrTupleSlice):
        names.update(_expr_record_names(expr.value))
        return tuple(sorted(names))
    if isinstance(expr, IrStringConcat):
        names.update(_expr_tuple_record_names(expr.parts))
        return tuple(sorted(names))
    if isinstance(expr, IrStringJoin):
        names.update(_expr_record_names(expr.separator))
        names.update(_expr_record_names(expr.values))
        return tuple(sorted(names))
    assert_never(expr)


def _expr_tuple_record_names(expressions: tuple[IrExpr, ...]) -> tuple[str, ...]:
    names: set[str] = set()
    for expression in expressions:
        names.update(_expr_record_names(expression))
    return tuple(sorted(names))


def _type_record_names(type_info: IrRecordType | IrTupleType | object) -> tuple[str, ...]:
    if isinstance(type_info, IrRecordType):
        if type_info.name in _INTERNAL_RECORD_TYPES:
            return ()
        return (type_info.name,)
    if isinstance(type_info, IrTupleType):
        names: set[str] = set()
        for element in type_info.elements:
            names.update(_type_record_names(element))
        return tuple(sorted(names))
    return ()


def _function_call_targets(function: IrFunction) -> tuple[str, ...]:
    targets: list[str] = []
    for statement in function.body:
        targets.extend(_statement_call_targets(statement))
    return tuple(targets)


def _native_leaf_dependencies(function_name: str) -> tuple[str, ...]:
    return _NATIVE_EMITTED_LEAF_DEPENDENCIES.get(function_name, ())


def _statement_call_targets(statement: IrStmt) -> tuple[str, ...]:
    if isinstance(statement, IrAssign):
        return _expr_call_targets(statement.value)
    if isinstance(statement, IrSetItem):
        return (
            _expr_call_targets(statement.target)
            + _expr_call_targets(statement.index)
            + _expr_call_targets(statement.value)
        )
    if isinstance(statement, IrReturn):
        return _expr_call_targets(statement.value)
    if isinstance(statement, IrIf):
        targets = list(_expr_call_targets(statement.condition))
        targets.extend(_branch_call_targets(statement.then_branch))
        if statement.else_branch is not None:
            targets.extend(_branch_call_targets(statement.else_branch))
        return tuple(targets)
    if isinstance(statement, IrForEach):
        return _expr_call_targets(statement.iterable) + _branch_call_targets(statement.body)
    if isinstance(statement, IrWhile):
        return _expr_call_targets(statement.condition) + _branch_call_targets(statement.body)
    if isinstance(statement, (IrBreak, IrContinue)):
        return ()
    if isinstance(statement, IrPrint):
        return _expr_call_targets(statement.value)
    if isinstance(statement, IrRaise):
        return _expr_call_targets(statement.message)
    assert_never(statement)


def _branch_call_targets(branch: IrBranch) -> tuple[str, ...]:
    targets: list[str] = []
    for statement in branch.statements:
        targets.extend(_statement_call_targets(statement))
    return tuple(targets)


def _expr_call_targets(expr: IrExpr) -> tuple[str, ...]:
    if isinstance(
        expr,
        IrConstInt
        | IrConstString
        | IrConstFloat
        | IrConstBool
        | IrConstNone
        | IrEnumMember
        | IrName,
    ):
        return ()
    if isinstance(expr, IrBinary):
        return _expr_call_targets(expr.left) + _expr_call_targets(expr.right)
    if isinstance(expr, IrGetField):
        return _expr_call_targets(expr.value)
    if isinstance(expr, IrConstructRecord):
        return _expr_tuple_call_targets(expr.args)
    if isinstance(expr, IrCall):
        return (expr.target,) + _expr_tuple_call_targets(expr.args)
    if isinstance(expr, IrTuple):
        return _expr_tuple_call_targets(expr.elements)
    if isinstance(expr, IrTupleSlice):
        return _expr_call_targets(expr.value)
    if isinstance(expr, IrStringConcat):
        return _expr_tuple_call_targets(expr.parts)
    if isinstance(expr, IrStringJoin):
        return _expr_call_targets(expr.separator) + _expr_call_targets(expr.values)
    assert_never(expr)


def _expr_tuple_call_targets(expressions: tuple[IrExpr, ...]) -> tuple[str, ...]:
    targets: list[str] = []
    for expression in expressions:
        targets.extend(_expr_call_targets(expression))
    return tuple(targets)


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
            IrConstInt(0, int64),
            IrConstNone(),
            declarator_ops,
            IrConstNone(),
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
