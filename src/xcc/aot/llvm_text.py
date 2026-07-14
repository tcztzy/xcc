from dataclasses import dataclass
from typing import NoReturn

from xcc.aot.core_runtime import runtime_prelude
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrBinary,
    IrBoolType,
    IrBranch,
    IrBreak,
    IrBytesType,
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
    IrFloatType,
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
    IrType,
    IrWhile,
)
from xcc.aot.status import analyze_fallibility

_BUILTIN_VALUE_NAMES = {"bool", "int", "object", "str", "tuple"}
_TYPE_CONSTANTS = {
    "INT": "int",
    "UINT": "unsigned int",
    "SHORT": "short",
    "USHORT": "unsigned short",
    "LONG": "long",
    "ULONG": "unsigned long",
    "LLONG": "long long",
    "ULLONG": "unsigned long long",
    "INT128": "__int128_t",
    "UINT128": "__uint128_t",
    "EVM_UINT256": "__evm_uint256",
    "EVM_ADDRESS": "__evm_address",
    "CHAR": "char",
    "UCHAR": "unsigned char",
    "BOOL": "_Bool",
    "FLOAT": "float",
    "DOUBLE": "double",
    "LONGDOUBLE": "long double",
    "VOID": "void",
}
_STRING_PREDICATE_INTRINSICS = {
    "__str_isalpha": 1,
    "__str_isdigit": 2,
    "__str_isalnum": 3,
    "__str_isspace": 4,
}
_LLVM_BINARY_BUILDER_INTRINSICS = frozenset(
    {
        "BuildAdd",
        "BuildFAdd",
        "BuildSub",
        "BuildFSub",
        "BuildMul",
        "BuildFMul",
        "BuildSDiv",
        "BuildUDiv",
        "BuildFDiv",
        "BuildSRem",
        "BuildURem",
        "BuildFRem",
        "BuildAnd",
        "BuildOr",
        "BuildXor",
        "BuildShl",
        "BuildAShr",
        "BuildLShr",
    }
)
_LLVM_C_TYPE_NAMES = {
    "double": "double",
    "i1": "i1",
    "i32": "i32",
    "i64": "i64",
    "ptr": "ptr",
    "void": "void",
}
_LLVM_C_API_INTRINSICS = {
    "ContextCreate": ("LLVMContextCreate", "ptr", ()),
    "ModuleCreateWithName": ("LLVMModuleCreateWithName", "ptr", ("ptr",)),
    "CreateBuilder": ("LLVMCreateBuilder", "ptr", ()),
    "SetTarget": ("LLVMSetTarget", "void", ("ptr", "ptr")),
    "VoidType": ("LLVMVoidType", "ptr", ()),
    "Int1Type": ("LLVMInt1Type", "ptr", ()),
    "Int8Type": ("LLVMInt8Type", "ptr", ()),
    "Int16Type": ("LLVMInt16Type", "ptr", ()),
    "Int32Type": ("LLVMInt32Type", "ptr", ()),
    "Int64Type": ("LLVMInt64Type", "ptr", ()),
    "FloatType": ("LLVMFloatType", "ptr", ()),
    "DoubleType": ("LLVMDoubleType", "ptr", ()),
    "PointerType": ("LLVMPointerType", "ptr", ("ptr", "i32")),
    "StructType": ("LLVMStructType", "ptr", ("ptr", "i32", "i1")),
    "GetTypeKind": ("LLVMGetTypeKind", "i32", ("ptr",)),
    "GetIntTypeWidth": ("LLVMGetIntTypeWidth", "i32", ("ptr",)),
    "GetArrayLength": ("LLVMGetArrayLength", "i32", ("ptr",)),
    "ConstInt": ("LLVMConstInt", "ptr", ("ptr", "i64", "i1")),
    "ConstReal": ("LLVMConstReal", "ptr", ("ptr", "double")),
    "ConstString": ("LLVMConstString", "ptr", ("ptr", "i32", "i1")),
    "ConstNull": ("LLVMConstNull", "ptr", ("ptr",)),
    "ConstArray": ("LLVMConstArray2", "ptr", ("ptr", "ptr", "i64")),
    "ConstNamedStruct": ("LLVMConstNamedStruct", "ptr", ("ptr", "ptr", "i32")),
    "ConstGEP2": ("LLVMConstGEP2", "ptr", ("ptr", "ptr", "ptr", "i32")),
    "ConstPointerCast": ("LLVMConstPointerCast", "ptr", ("ptr", "ptr")),
    "ConstBitCast": ("LLVMConstBitCast", "ptr", ("ptr", "ptr")),
    "ConstIntToPtr": ("LLVMConstIntToPtr", "ptr", ("ptr", "ptr")),
    "ConstPtrToInt": ("LLVMConstPtrToInt", "ptr", ("ptr", "ptr")),
    "ConstTrunc": ("LLVMConstTrunc", "ptr", ("ptr", "ptr")),
    "ConstTruncOrBitCast": ("LLVMConstTruncOrBitCast", "ptr", ("ptr", "ptr")),
    "GetNamedGlobal": ("LLVMGetNamedGlobal", "ptr", ("ptr", "ptr")),
    "GetNamedFunction": ("LLVMGetNamedFunction", "ptr", ("ptr", "ptr")),
    "GetParam": ("LLVMGetParam", "ptr", ("ptr", "i32")),
    "GetBasicBlockTerminator": ("LLVMGetBasicBlockTerminator", "ptr", ("ptr",)),
    "SetValueName2": ("LLVMSetValueName2", "void", ("ptr", "ptr", "i64")),
    "GetInsertBlock": ("LLVMGetInsertBlock", "ptr", ("ptr",)),
    "PositionBuilderAtEnd": ("LLVMPositionBuilderAtEnd", "void", ("ptr", "ptr")),
    "PositionBuilderBefore": ("LLVMPositionBuilderBefore", "void", ("ptr", "ptr")),
    "BuildRetVoid": ("LLVMBuildRetVoid", "ptr", ("ptr",)),
    "BuildRet": ("LLVMBuildRet", "ptr", ("ptr", "ptr")),
    "BuildUnreachable": ("LLVMBuildUnreachable", "ptr", ("ptr",)),
    "BuildBr": ("LLVMBuildBr", "ptr", ("ptr", "ptr")),
    "BuildCondBr": ("LLVMBuildCondBr", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildSwitch": ("LLVMBuildSwitch", "ptr", ("ptr", "ptr", "ptr", "i32")),
    "BuildNeg": ("LLVMBuildNeg", "ptr", ("ptr", "ptr", "ptr")),
    "BuildFNeg": ("LLVMBuildFNeg", "ptr", ("ptr", "ptr", "ptr")),
    "BuildAlloca": ("LLVMBuildAlloca", "ptr", ("ptr", "ptr", "ptr")),
    "BuildArrayAlloca": ("LLVMBuildArrayAlloca", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildLoad2": ("LLVMBuildLoad2", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildStore": ("LLVMBuildStore", "ptr", ("ptr", "ptr", "ptr")),
    "BuildGEP2": ("LLVMBuildGEP2", "ptr", ("ptr", "ptr", "ptr", "ptr", "i32", "ptr")),
    "BuildSExt": ("LLVMBuildSExt", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildZExt": ("LLVMBuildZExt", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildTrunc": ("LLVMBuildTrunc", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildIntToPtr": ("LLVMBuildIntToPtr", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildPtrToInt": ("LLVMBuildPtrToInt", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildFPCast": ("LLVMBuildFPCast", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildSIToFP": ("LLVMBuildSIToFP", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildFPToSI": ("LLVMBuildFPToSI", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildBitCast": ("LLVMBuildBitCast", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildICmp": ("LLVMBuildICmp", "ptr", ("ptr", "i32", "ptr", "ptr", "ptr")),
    "BuildFCmp": ("LLVMBuildFCmp", "ptr", ("ptr", "i32", "ptr", "ptr", "ptr")),
    "BuildSelect": ("LLVMBuildSelect", "ptr", ("ptr", "ptr", "ptr", "ptr", "ptr")),
    "BuildCall2": ("LLVMBuildCall2", "ptr", ("ptr", "ptr", "ptr", "ptr", "i32", "ptr")),
    "BuildVAArg": ("LLVMBuildVAArg", "ptr", ("ptr", "ptr", "ptr", "ptr")),
    "BuildExtractValue": ("LLVMBuildExtractValue", "ptr", ("ptr", "ptr", "i32", "ptr")),
    "BuildMemSet": ("LLVMBuildMemSet", "ptr", ("ptr", "ptr", "ptr", "ptr", "i1")),
    "BuildMemCpy": ("LLVMBuildMemCpy", "ptr", ("ptr", "ptr", "i32", "ptr", "i32", "ptr")),
    "BuildFence": ("LLVMBuildFence", "ptr", ("ptr", "i32", "i1", "ptr")),
    "BuildAtomicRMW": ("LLVMBuildAtomicRMW", "ptr", ("ptr", "i32", "ptr", "ptr", "i32", "i1")),
    "BuildAtomicCmpXchg": (
        "LLVMBuildAtomicCmpXchg",
        "ptr",
        ("ptr", "ptr", "ptr", "ptr", "i32", "i32", "i1"),
    ),
    "BuildPhi": ("LLVMBuildPhi", "ptr", ("ptr", "ptr", "ptr")),
    "TypeOf": ("LLVMTypeOf", "ptr", ("ptr",)),
    "ConstPointerNull": ("LLVMConstPointerNull", "ptr", ("ptr",)),
    "IsNull": ("LLVMIsNull", "i1", ("ptr",)),
    "IsAConstantInt": ("LLVMIsAConstantInt", "ptr", ("ptr",)),
    "ConstIntGetSExtValue": ("LLVMConstIntGetSExtValue", "i64", ("ptr",)),
    "ConstIntGetZExtValue": ("LLVMConstIntGetZExtValue", "i64", ("ptr",)),
    "GetNumOperands": ("LLVMGetNumOperands", "i32", ("ptr",)),
    "GetOperand": ("LLVMGetOperand", "ptr", ("ptr", "i32")),
    "GetAggregateElement": ("LLVMGetAggregateElement", "ptr", ("ptr", "i32")),
    "GetReturnType": ("LLVMGetReturnType", "ptr", ("ptr",)),
    "GetUndef": ("LLVMGetUndef", "ptr", ("ptr",)),
    "SetAlignment": ("LLVMSetAlignment", "void", ("ptr", "i32")),
    "SetOrdering": ("LLVMSetOrdering", "void", ("ptr", "i32")),
    "SetInitializer": ("LLVMSetInitializer", "void", ("ptr", "ptr")),
    "SetLinkage": ("LLVMSetLinkage", "void", ("ptr", "i32")),
}
_PROTOCOL_RECORD_ALIASES = {
    "_StatementParser": "Parser",
}
_ERROR_LLVM_TYPE = "%__xcc_aot_error"
_ERROR_LLVM_DECLARATION = "%__xcc_aot_error = type { ptr, ptr, ptr, i32, i32, i32, i32, ptr }"


@dataclass(frozen=True)
class _EmittedValue:
    value: str
    type: IrType


@dataclass
class _LoopLabels:
    continue_label: str
    break_label: str
    continue_sources: list[tuple[str, dict[str, _EmittedValue]]] | None = None
    break_sources: list[tuple[str, dict[str, _EmittedValue]]] | None = None


@dataclass
class _HandlerScope:
    dispatch_label: str
    status_slot: str
    error_sources: list[tuple[str, dict[str, _EmittedValue]]]


@dataclass(frozen=True)
class _FinallyScope:
    body: IrBranch


_FailureScope = _HandlerScope | _FinallyScope


def emit_llvm_text(module: IrModule) -> str:
    emitter = _Emitter(module)
    return emitter.emit()


class _Emitter:
    def __init__(self, module: IrModule) -> None:
        self.module = module
        self.records = {record.name: record for record in module.records}
        self.record_type_ids = {name: index + 1 for index, name in enumerate(sorted(self.records))}
        self.functions = {function.name: function for function in module.functions}
        self.fallible_functions = analyze_fallibility(module)
        self.index = 0
        self.string_index = 0
        self.string_constants: list[str] = []
        self.enum_constants: dict[tuple[str, str], str] = {}
        self.global_constants: dict[str, str] = {}
        self.loop_stack: list[_LoopLabels] = []
        self.extra_declarations: set[str] = set()
        self.needs_puts = False
        self.needs_runtime_prelude = False
        self.current_function: IrFunction | None = None
        self.current_function_is_fallible = False
        self.current_result_out: str | None = None
        self.current_error_out: str | None = None
        self.failure_scopes: list[_FailureScope] = []
        self.caught_status_stack: list[str] = []

    def emit(self) -> str:
        declarations = [self._emit_record(record) for record in self.module.records]
        functions = [self._emit_function(function) for function in self.module.functions]
        main = self._emit_main()
        lines: list[str] = []
        if self.fallible_functions:
            lines.append(_ERROR_LLVM_DECLARATION)
            lines.append("")
        if self.needs_runtime_prelude:
            lines.append(runtime_prelude())
            lines.append("")
        if self.string_constants:
            lines.extend(self.string_constants)
            lines.append("")
        lines.extend(declaration for declaration in declarations if declaration)
        if declarations:
            lines.append("")
        if self.global_constants:
            lines.extend(self.global_constants[name] for name in sorted(self.global_constants))
            lines.append("")
        if self.needs_puts and not self.needs_runtime_prelude:
            lines.append("declare i32 @puts(ptr)")
            lines.append("")
        if self.extra_declarations:
            lines.extend(sorted(self.extra_declarations))
            lines.append("")
        lines.extend(functions)
        if main is not None:
            lines.append(main)
        return "\n".join(lines).rstrip() + "\n"

    def _emit_record(self, record: IrRecord) -> str:
        fields = ", ".join(self._storage_llvm_type(field.type) for field in record.fields)
        return f"%{record.name} = type {{ {fields} }}"

    def _emit_function(self, function: IrFunction) -> str:
        if function.name in self.fallible_functions:
            return self._emit_generic_function(function, fallible=True)
        if function.name == "xcc.cc_driver._aot_exec_argv":
            return self._emit_aot_exec_argv_function(function)
        if function.name == "xcc.cc_driver._aot_read_text_file":
            return self._emit_aot_read_text_file_function(function)
        if function.name == "xcc.cc_driver._aot_write_text_file":
            return self._emit_aot_write_text_file_function(function)
        if function.name == "xcc.codegen._llvm_print_module_to_string":
            return self._emit_llvm_print_module_to_string_function(function)
        if function.name == "xcc.llvm_api.ptr_array":
            return self._emit_llvm_ptr_array_function(function)
        if function.name == "xcc.llvm_api.zero_ptr_array":
            return self._emit_llvm_zero_ptr_array_function(function)
        if function.name == "xcc.llvm_api.optional_zero_ptr_array":
            return self._emit_llvm_optional_zero_ptr_array_function(function)
        if function.name == "xcc.lexer._aot_error_summary_for_source":
            return self._emit_core_lexer_string_helper_function(
                function,
                "core lexer error summary expects str -> str",
                "__xcc_aot_lexer_error_summary_for_source",
            )
        if function.name == "xcc.lexer._aot_header_summary_for_source":
            return self._emit_core_lexer_string_helper_function(
                function,
                "core lexer header summary expects str -> str",
                "__xcc_aot_lexer_header_summary_for_source",
            )
        if function.name == "xcc.lexer._aot_token_summary_for_source":
            return self._emit_core_lexer_token_summary_function(function)
        if function.name == "xcc.lexer.translate_source":
            return self._emit_core_lexer_translate_source_function(function)
        if function.name == "xcc.parser.type_specs.ParserError.__str__":
            return self._emit_core_parser_error_str_function(function)
        if function.name in {
            "xcc.preprocessor.__init__._Preprocessor._expand_line",
            "xcc.preprocessor.__init__._Preprocessor._expand_macro_text",
        }:
            return self._emit_preprocessor_expand_line_passthrough_function(function)
        if function.name in {
            "xcc.preprocessor.__init__._Preprocessor._handle_define",
            "xcc.preprocessor.__init__._Preprocessor._handle_undef",
        }:
            return self._emit_preprocessor_void_noop_function(function)
        if function.name == "xcc.preprocessor.__init__._Preprocessor._handle_pragma_operator":
            return self._emit_preprocessor_pragma_passthrough_function(function)
        if (
            function.name == "xcc.preprocessor.__init__._Preprocessor."
            "_should_collect_function_macro_continuation"
        ):
            return self._emit_preprocessor_no_macro_continuation_function(function)
        if function.name == "xcc.sema.type_helpers._aot_integer_type_summary":
            return self._emit_core_constant_string_function(
                function,
                "core sema integer type summary expects () -> str",
                "INT=True|VOID=False",
            )
        if function.name == "xcc.types.Type.__str__":
            return self._emit_core_type_str_function(function)
        return self._emit_generic_function(function, fallible=False)

    def _emit_generic_function(self, function: IrFunction, *, fallible: bool) -> str:
        self.index = 0
        params = ", ".join(
            f"{self._param_llvm_type(param.type)} %{param.name}" for param in function.params
        )
        result_out = None if isinstance(function.return_type, IrNoneType) else "%result_out"
        if fallible:
            status_params = [] if not params else [params]
            if result_out is not None:
                status_params.append("ptr %result_out")
            status_params.append("ptr %error_out")
            params = ", ".join(status_params)
        llvm_return_type = "i32" if fallible else self._llvm_type(function.return_type)
        lines = [f"define {llvm_return_type} {_llvm_symbol(function.name)}({params}) {{"]
        lines.append("entry:")
        previous_function = self.current_function
        previous_fallible = self.current_function_is_fallible
        previous_result_out = self.current_result_out
        previous_error_out = self.current_error_out
        previous_failure_scopes = self.failure_scopes
        previous_caught_status_stack = self.caught_status_stack
        self.current_function = function
        self.current_function_is_fallible = fallible
        self.current_result_out = result_out if fallible else None
        self.current_error_out = "%error_out" if fallible else None
        self.failure_scopes = []
        self.caught_status_stack = []
        names = {
            param.name: _EmittedValue(f"%{param.name}", param.type) for param in function.params
        }
        try:
            for statement in function.body:
                self._emit_statement(statement, names, lines, function.return_type)
                if _block_is_terminated(lines):
                    break
            if not _block_is_terminated(lines):
                self._emit_default_return(lines, function.return_type)
        finally:
            self.current_function = previous_function
            self.current_function_is_fallible = previous_fallible
            self.current_result_out = previous_result_out
            self.current_error_out = previous_error_out
            self.failure_scopes = previous_failure_scopes
            self.caught_status_stack = previous_caught_status_stack
        lines.append("}")
        return "\n".join(lines)

    def _emit_statement(
        self,
        statement: IrStmt,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        if isinstance(statement, IrAssign):
            if (
                statement.target == "__assert"
                and isinstance(statement.value, IrCall)
                and statement.value.target == "__assert"
                and len(statement.value.args) == 1
            ):
                self._emit_assert(statement.value.args[0], names, lines)
                return
            if isinstance(statement.value, IrConstructRecord):
                value = self._emit_construct_record(statement.value, names, lines, statement.target)
            else:
                value = self._emit_expr(statement.value, names, lines)
            if statement.target == "__expr":
                return
            if "," in statement.target:
                self._bind_emitted_tuple_target(statement.target, value, names, lines)
            else:
                self._emit_assign_target(statement.target, value, names, lines)
            return
        if isinstance(statement, IrSetItem):
            self._emit_set_item(statement, names, lines)
            return
        if isinstance(statement, IrReturn):
            self._emit_return(statement, names, lines, return_type)
            return
        if isinstance(statement, IrIf):
            self._emit_if(statement, names, lines, return_type)
            return
        if isinstance(statement, IrForEach):
            self._emit_for_each(statement, names, lines, return_type)
            return
        if isinstance(statement, IrWhile):
            self._emit_while(statement, names, lines, return_type)
            return
        if isinstance(statement, IrTry):
            self._emit_try(statement, names, lines, return_type)
            return
        if isinstance(statement, IrBreak):
            if not self.loop_stack:
                self._error("break outside loop")
            self._emit_control_finally(names, lines, return_type)
            if _block_is_terminated(lines):
                return
            loop = self.loop_stack[-1]
            if loop.break_sources is not None:
                loop.break_sources.append((_current_label(lines), dict(names)))
            lines.append(f"  br label %{loop.break_label}")
            return
        if isinstance(statement, IrContinue):
            if not self.loop_stack:
                self._error("continue outside loop")
            self._emit_control_finally(names, lines, return_type)
            if _block_is_terminated(lines):
                return
            loop = self.loop_stack[-1]
            if loop.continue_sources is not None:
                loop.continue_sources.append((_current_label(lines), dict(names)))
            lines.append(f"  br label %{self.loop_stack[-1].continue_label}")
            return
        if isinstance(statement, IrPrint):
            value = self._emit_expr(statement.value, names, lines)
            self.needs_puts = True
            lines.append(f"  {self._tmp('printed')} = call i32 @puts(ptr {value.value})")
            return
        if isinstance(statement, IrRaise):
            if not self.current_function_is_fallible or self.current_error_out is None:
                self._error("raise requires a fallible function status ABI")
            self._emit_error_record(statement, names, lines)
            self._emit_failure_transfer("2", names, lines, return_type)
            return
        if isinstance(statement, IrReraise):
            if not self.caught_status_stack:
                self._error("reraise outside an active exception handler")
            self._emit_failure_transfer(
                self.caught_status_stack[-1],
                names,
                lines,
                return_type,
            )
            return
        self._error(f"Unsupported LLVM statement: {type(statement).__name__}")

    def _emit_return(
        self,
        statement: IrReturn,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        value = None
        if not isinstance(return_type, IrNoneType) and not isinstance(statement.value, IrConstNone):
            value = self._emit_expr(statement.value, names, lines)
        self._emit_control_finally(names, lines, return_type)
        if _block_is_terminated(lines):
            return
        if self.current_function_is_fallible:
            if isinstance(return_type, IrNoneType):
                lines.append("  ret i32 0")
                return
            if self.current_result_out is None:
                self._error("fallible non-void function is missing result_out")
            stored = (
                self._default_value(return_type)
                if value is None
                else self._value_for_result_type(value, return_type, lines)
            )
            lines.append(
                f"  store {self._storage_llvm_type(return_type)} {stored}, "
                f"ptr {self.current_result_out}"
            )
            lines.append("  ret i32 0")
            return
        if isinstance(return_type, IrNoneType):
            lines.append("  ret void")
            return
        if value is None:
            self._emit_default_return(lines, return_type)
            return
        returned = self._value_for_result_type(value, return_type, lines)
        lines.append(f"  ret {self._llvm_type(return_type)} {returned}")

    def _emit_failure_transfer(
        self,
        status: str,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        if self.failure_scopes:
            scope = self.failure_scopes[-1]
            if isinstance(scope, _HandlerScope):
                lines.append(f"  store i32 {status}, ptr {scope.status_slot}")
                scope.error_sources.append((_current_label(lines), dict(names)))
                lines.append(f"  br label %{scope.dispatch_label}")
                return
            original_scopes = self.failure_scopes
            self.failure_scopes = original_scopes[:-1]
            try:
                self._emit_branch(scope.body, names, lines, return_type)
                if not _block_is_terminated(lines):
                    self._emit_failure_transfer(status, names, lines, return_type)
            finally:
                self.failure_scopes = original_scopes
            return
        if not self.current_function_is_fallible:
            self._error("failure propagation requires a fallible function")
        lines.append(f"  ret i32 {status}")

    def _emit_control_finally(
        self,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        scope_index = self._innermost_finally_scope_index()
        if scope_index is None:
            return
        scope = self.failure_scopes[scope_index]
        if not isinstance(scope, _FinallyScope):
            self._error("invalid finally scope")
        original_scopes = self.failure_scopes
        self.failure_scopes = original_scopes[:scope_index]
        try:
            self._emit_branch(scope.body, names, lines, return_type)
            if not _block_is_terminated(lines):
                self._emit_control_finally(names, lines, return_type)
        finally:
            self.failure_scopes = original_scopes

    def _emit_one_finally(
        self,
        scope: _FinallyScope,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        scope_index = None
        for index in range(len(self.failure_scopes) - 1, -1, -1):
            if self.failure_scopes[index] is scope:
                scope_index = index
                break
        if scope_index is None:
            self._error("missing active finally scope")
        original_scopes = self.failure_scopes
        self.failure_scopes = original_scopes[:scope_index]
        try:
            self._emit_branch(scope.body, names, lines, return_type)
        finally:
            self.failure_scopes = original_scopes

    def _innermost_finally_scope_index(self) -> int | None:
        for index in range(len(self.failure_scopes) - 1, -1, -1):
            if isinstance(self.failure_scopes[index], _FinallyScope):
                return index
        return None

    def _emit_try(
        self,
        statement: IrTry,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        before_names = dict(names)
        end_label = self._label("try.end")
        incoming: list[tuple[str, dict[str, _EmittedValue]]] = []
        finally_scope = (
            _FinallyScope(statement.finalbody) if statement.finalbody.statements else None
        )
        if finally_scope is not None:
            self.failure_scopes.append(finally_scope)
        handler_scope = None
        if statement.handlers and self.current_function_is_fallible:
            handler_scope = _HandlerScope(
                self._label("try.dispatch"),
                self._tmp("trystatus.ptr"),
                [],
            )
            lines.append(f"  {handler_scope.status_slot} = alloca i32")
            self.failure_scopes.append(handler_scope)
        body_names = dict(before_names)
        self._emit_branch(statement.body, body_names, lines, return_type)
        if handler_scope is not None:
            popped = self.failure_scopes.pop()
            if popped is not handler_scope:
                self._error("unbalanced exception handler scope")
        if not _block_is_terminated(lines):
            self._emit_branch(statement.orelse, body_names, lines, return_type)
        if not _block_is_terminated(lines) and finally_scope is not None:
            self._emit_one_finally(finally_scope, body_names, lines, return_type)
        if not _block_is_terminated(lines):
            incoming.append((_current_label(lines), dict(body_names)))
            lines.append(f"  br label %{end_label}")
        if handler_scope is not None:
            self._emit_try_handlers(
                statement.handlers,
                handler_scope,
                finally_scope,
                before_names,
                incoming,
                end_label,
                lines,
                return_type,
            )
        if finally_scope is not None:
            popped = self.failure_scopes.pop()
            if popped is not finally_scope:
                self._error("unbalanced finally scope")
        if not incoming:
            return
        lines.append(f"{end_label}:")
        self._merge_incoming_names(names, before_names, incoming, lines, "tryphi")

    def _emit_try_handlers(
        self,
        handlers: tuple[IrExceptHandler, ...],
        scope: _HandlerScope,
        finally_scope: _FinallyScope | None,
        before_names: dict[str, _EmittedValue],
        incoming: list[tuple[str, dict[str, _EmittedValue]]],
        end_label: str,
        lines: list[str],
        return_type: IrType,
    ) -> None:
        if self.current_error_out is None:
            self._error("exception handlers require error_out")
        lines.append(f"{scope.dispatch_label}:")
        dispatch_names = dict(before_names)
        self._merge_incoming_names(
            dispatch_names,
            before_names,
            scope.error_sources,
            lines,
            "errorphi",
        )
        status = self._tmp("trystatus")
        lines.append(f"  {status} = load i32, ptr {scope.status_slot}")
        error_type = self._load_error_field("type", "ptr", 0, lines)
        handled_all = False
        for index, handler in enumerate(handlers):
            handler_label = self._label("except.body")
            catch_all = self._handler_is_catch_all(handler)
            next_label = None if catch_all else self._label("except.next")
            if catch_all:
                lines.append(f"  br label %{handler_label}")
            else:
                matched = self._emit_handler_match(error_type, handler, lines)
                if next_label is None:
                    self._error("typed handler is missing a continuation label")
                lines.append(f"  br i1 {matched}, label %{handler_label}, label %{next_label}")
            lines.append(f"{handler_label}:")
            handler_names = dict(dispatch_names)
            if handler.target is not None:
                self._bind_error_target(handler, handler_names, lines)
            self.caught_status_stack.append(status)
            try:
                self._emit_branch(handler.body, handler_names, lines, return_type)
            finally:
                self.caught_status_stack.pop()
            if not _block_is_terminated(lines) and finally_scope is not None:
                self._emit_one_finally(finally_scope, handler_names, lines, return_type)
            if not _block_is_terminated(lines):
                incoming.append((_current_label(lines), dict(handler_names)))
                lines.append(f"  br label %{end_label}")
            if catch_all:
                handled_all = True
                break
            if next_label is None:
                self._error(f"handler {index} is missing a next label")
            lines.append(f"{next_label}:")
        if not handled_all:
            self._emit_failure_transfer(status, dispatch_names, lines, return_type)

    def _handler_is_catch_all(self, handler: IrExceptHandler) -> bool:
        return not handler.exceptions or any(
            exception in {"BaseException", "Exception"} for exception in handler.exceptions
        )

    def _emit_handler_match(
        self,
        error_type: str,
        handler: IrExceptHandler,
        lines: list[str],
    ) -> str:
        tags = self._handler_runtime_tags(handler.exceptions)
        if not tags:
            return "true"
        self.needs_runtime_prelude = True
        matches: list[str] = []
        for tag in tags:
            compared = self._tmp("exceptcmp")
            matched = self._tmp("exceptmatch")
            lines.append(
                f"  {compared} = call i32 @strcmp(ptr {error_type}, "
                f"ptr {self._string_constant(tag)})"
            )
            lines.append(f"  {matched} = icmp eq i32 {compared}, 0")
            matches.append(matched)
        result = matches[0]
        for matched in matches[1:]:
            combined = self._tmp("exceptmatch")
            lines.append(f"  {combined} = or i1 {result}, {matched}")
            result = combined
        return result

    def _handler_runtime_tags(self, exceptions: tuple[str, ...]) -> tuple[str, ...]:
        tags = set(exceptions)
        for record_name in self.records:
            for exception in exceptions:
                if self._record_extends(record_name, exception):
                    tags.add(record_name)
        return tuple(sorted(tags))

    def _bind_error_target(
        self,
        handler: IrExceptHandler,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> None:
        if handler.target is None:
            return
        payload = self._load_error_field("payload", "ptr", 7, lines)
        message = self._load_error_field("message", "ptr", 1, lines)
        has_payload = self._tmp("errorpayload")
        value = self._tmp("errorvalue")
        lines.append(f"  {has_payload} = icmp ne ptr {payload}, null")
        lines.append(f"  {value} = select i1 {has_payload}, ptr {payload}, ptr {message}")
        target_type: IrType = IrRecordType("object")
        if len(handler.exceptions) == 1 and handler.exceptions[0] in self.records:
            target_type = IrRecordType(handler.exceptions[0])
        names[handler.target] = _EmittedValue(value, target_type)

    def _load_error_field(
        self,
        name: str,
        llvm_type: str,
        index: int,
        lines: list[str],
    ) -> str:
        if self.current_error_out is None:
            self._error("error field load requires error_out")
        field_ptr = self._tmp(f"error{name}.ptr")
        value = self._tmp(f"error{name}")
        lines.append(
            f"  {field_ptr} = getelementptr inbounds {_ERROR_LLVM_TYPE}, "
            f"ptr {self.current_error_out}, i32 0, i32 {index}"
        )
        lines.append(f"  {value} = load {llvm_type}, ptr {field_ptr}")
        return value

    def _merge_incoming_names(
        self,
        target_names: dict[str, _EmittedValue],
        before_names: dict[str, _EmittedValue],
        incoming: list[tuple[str, dict[str, _EmittedValue]]],
        lines: list[str],
        prefix: str,
    ) -> None:
        if not incoming:
            return
        candidate_names = set(before_names)
        for _, source_names in incoming:
            candidate_names.update(source_names)
        for name in sorted(candidate_names):
            before = before_names.get(name)
            values: list[tuple[str, _EmittedValue]] = []
            for source, source_names in incoming:
                value = source_names.get(name, before)
                if value is not None:
                    values.append((source, value))
            if not values:
                continue
            if len(values) == 1 or all(value == values[0][1] for _, value in values[1:]):
                target_names[name] = values[0][1]
                continue
            merged_type = self._if_phi_type(tuple(value for _, value in values))
            if merged_type is None:
                continue
            result = self._tmp(prefix)
            parts = ", ".join(
                f"[ {self._if_phi_value(value, merged_type)}, %{source} ]"
                for source, value in values
            )
            lines.append(f"  {result} = phi {self._storage_llvm_type(merged_type)} {parts}")
            target_names[name] = _EmittedValue(result, merged_type)

    def _emit_assert(
        self,
        condition: IrExpr,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> None:
        truth = self._emit_condition(condition, names, lines)
        fail_label = self._label("assert.fail")
        end_label = self._label("assert.end")
        self.extra_declarations.add("declare void @abort()")
        lines.append(f"  br i1 {truth.value}, label %{end_label}, label %{fail_label}")
        lines.append(f"{fail_label}:")
        lines.append("  call void @abort()")
        lines.append("  unreachable")
        lines.append(f"{end_label}:")

    def _emit_expr(
        self,
        expr: IrExpr,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if isinstance(expr, IrConstInt):
            return _EmittedValue(str(expr.value), expr.type)
        if isinstance(expr, IrConstFloat):
            return _EmittedValue(_format_float_literal(expr.value), expr.type)
        if isinstance(expr, IrConstBool):
            return _EmittedValue("true" if expr.value else "false", IrBoolType())
        if isinstance(expr, IrConstBytes):
            self.needs_runtime_prelude = True
            result = self._tmp("bytes")
            constant = self._bytes_constant(expr.value)
            lines.append(
                f"  {result} = call ptr @__xcc_aot_bytes_copy("
                f"ptr {constant}, i64 {len(expr.value)})"
            )
            return _EmittedValue(result, IrBytesType())
        if isinstance(expr, IrConstNone):
            return _EmittedValue("null", IrNoneType())
        if isinstance(expr, IrEnumMember):
            return _EmittedValue(self._enum_constant(expr), expr.type)
        if isinstance(expr, IrConstString):
            return _EmittedValue(self._string_constant(expr.value), IrStringType())
        if isinstance(expr, IrName):
            value = names.get(expr.name)
            if value is None:
                constructor_base = _record_constructor_type_base_name(expr.type)
                if constructor_base is not None and expr.name in self.records:
                    type_id = self.record_type_ids[expr.name]
                    return _EmittedValue(
                        f"inttoptr (i64 {type_id} to ptr)",
                        expr.type,
                    )
                type_constant = self._emit_type_constant_name(expr, lines)
                if type_constant is not None:
                    return type_constant
                if isinstance(expr.type, IrBoolType) and _is_type_marker_name(expr.name):
                    return _EmittedValue("true", expr.type)
                if expr.name in _BUILTIN_VALUE_NAMES or expr.name.isupper():
                    return _EmittedValue(self._default_value(expr.type), expr.type)
                self._error(f"Unknown LLVM name: {expr.name}")
            if _is_record_narrowing(value.type, expr.type) or (
                isinstance(value.type, IrRecordType)
                and isinstance(expr.type, IrRecordType)
                and (
                    expr.type.name in self.records
                    or _is_known_record_union_name(expr.type.name, self.records)
                )
            ):
                return _EmittedValue(value.value, expr.type)
            narrowed_value = self._emit_runtime_object_narrowing(value, expr.type, lines)
            if narrowed_value is not None:
                return narrowed_value
            return value
        if isinstance(expr, IrBinary):
            return self._emit_binary(expr, names, lines)
        if isinstance(expr, IrConstructRecord):
            return self._emit_construct_record(expr, names, lines)
        if isinstance(expr, IrGetField):
            return self._emit_get_field(expr, names, lines)
        if isinstance(expr, IrCall):
            return self._emit_call(expr, names, lines)
        if isinstance(expr, IrTuple):
            return self._emit_tuple(expr, names, lines)
        if isinstance(expr, IrTupleSlice):
            return self._emit_tuple_slice(expr, names, lines)
        if isinstance(expr, IrStringConcat):
            return self._emit_string_concat(expr, names, lines)
        if isinstance(expr, IrStringJoin):
            return self._emit_string_join(expr, names, lines)
        self._error(f"Unsupported LLVM expression: {type(expr).__name__}")

    def _emit_if(
        self,
        statement: IrIf,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        if (
            isinstance(statement.condition, IrConstBool)
            and statement.condition.value
            and statement.else_branch is None
        ):
            self._emit_branch(statement.then_branch, names, lines, return_type)
            return
        condition = self._emit_condition(statement.condition, names, lines)
        condition_label = _current_label(lines)
        then_label = self._label("if.then")
        else_label = self._label("if.else") if statement.else_branch is not None else None
        end_label = self._label("if.end")
        false_label = else_label or end_label
        lines.append(f"  br i1 {condition.value}, label %{then_label}, label %{false_label}")
        lines.append(f"{then_label}:")
        then_names = dict(names)
        self._emit_branch(statement.then_branch, then_names, lines, return_type)
        then_source = None
        if not _block_is_terminated(lines):
            then_source = _current_label(lines)
            lines.append(f"  br label %{end_label}")
        else_names = dict(names)
        else_source = condition_label if statement.else_branch is None else None
        if statement.else_branch is not None and else_label is not None:
            lines.append(f"{else_label}:")
            self._emit_branch(statement.else_branch, else_names, lines, return_type)
            if not _block_is_terminated(lines):
                else_source = _current_label(lines)
                lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        self._merge_if_names(
            statement,
            names,
            then_names,
            else_names,
            then_source,
            else_source,
            lines,
        )

    def _merge_if_names(
        self,
        statement: IrIf,
        names: dict[str, _EmittedValue],
        then_names: dict[str, _EmittedValue],
        else_names: dict[str, _EmittedValue],
        then_source: str | None,
        else_source: str | None,
        lines: list[str],
    ) -> None:
        assigned_names = set(_branch_assigned_names(statement.then_branch))
        if statement.else_branch is not None:
            assigned_names.update(_branch_assigned_names(statement.else_branch))
        for name in sorted(assigned_names):
            before_value = names.get(name)
            incoming: list[tuple[str, _EmittedValue]] = []
            if then_source is not None:
                then_value = then_names.get(name, before_value)
                if then_value is not None:
                    incoming.append((then_source, then_value))
            if else_source is not None:
                else_value = else_names.get(name, before_value)
                if else_value is not None:
                    incoming.append((else_source, else_value))
            if not incoming:
                continue
            if len(incoming) == 1:
                condition_is_always_true = (
                    isinstance(statement.condition, IrConstBool) and statement.condition.value
                )
                if (
                    before_value is None
                    and statement.else_branch is None
                    and not condition_is_always_true
                ):
                    continue
                names[name] = incoming[0][1]
                continue
            merged_type = self._if_phi_type(tuple(value for _, value in incoming))
            if merged_type is None:
                continue
            result = self._tmp("ifphi")
            parts = []
            for source, value in incoming:
                parts.append(f"[ {self._if_phi_value(value, merged_type)}, %{source} ]")
            lines.append(
                f"  {result} = phi {self._storage_llvm_type(merged_type)} " + ", ".join(parts)
            )
            names[name] = _EmittedValue(result, merged_type)

    def _if_phi_type(self, values: tuple[_EmittedValue, ...]) -> IrType | None:
        non_none_types = tuple(
            value.type for value in values if not isinstance(value.type, IrNoneType)
        )
        if not non_none_types:
            return values[0].type
        result_type = non_none_types[0]
        result_storage = self._storage_llvm_type(result_type)
        for type_info in non_none_types[1:]:
            if self._storage_llvm_type(type_info) != result_storage:
                return None
        return result_type

    def _if_phi_value(self, value: _EmittedValue, result_type: IrType) -> str:
        if isinstance(value.type, IrNoneType):
            return self._default_value(result_type)
        if value.type == result_type:
            return value.value
        if self._storage_llvm_type(value.type) == self._storage_llvm_type(result_type):
            return value.value
        self._error(f"Cannot merge {type(value.type).__name__} as {type(result_type).__name__}")

    def _emit_for_each(
        self,
        statement: IrForEach,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        enumerate_call = (
            statement.iterable
            if isinstance(statement.iterable, IrCall) and statement.iterable.target == "__enumerate"
            else None
        )
        if enumerate_call is not None:
            if len(enumerate_call.args) not in {1, 2}:
                self._error("__enumerate expects one or two arguments")
            iterable_expr = enumerate_call.args[0]
            start_expr = (
                enumerate_call.args[1]
                if len(enumerate_call.args) == 2
                else IrConstInt(0, IrIntType(64, signed=True))
            )
        else:
            iterable_expr = statement.iterable
            start_expr = None
        iterable = self._emit_expr(iterable_expr, names, lines)
        enumerate_start: _EmittedValue | None = None
        if start_expr is not None:
            enumerate_start = self._emit_expr(start_expr, names, lines)
            if not isinstance(enumerate_start.type, IrIntType) or enumerate_start.type.bits != 64:
                self._error("__enumerate start expects an int64 value")
        assigned_names = tuple(
            name
            for name in _branch_assigned_names(statement.body)
            if name in names and not isinstance(names[name].type, IrNoneType)
        )
        initial_values = {name: names[name] for name in assigned_names}
        self.needs_runtime_prelude = True
        cond_label = self._label("for.cond")
        body_label = self._label("for.body")
        next_label = self._label("for.next")
        end_label = self._label("for.end")
        current_label = _current_label(lines)
        next_value = self._tmp("next")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        cond_names = dict(names)
        phi_lines: dict[str, int] = {}
        phi_values: dict[str, _EmittedValue] = {}
        for name, initial in initial_values.items():
            result = self._tmp("loop")
            phi_lines[name] = len(lines)
            phi_values[name] = _EmittedValue(result, initial.type)
            cond_names[name] = phi_values[name]
            lines.append("")
        index = self._tmp("index")
        lines.append(
            f"  {index} = phi i64 [ 0, %{current_label} ], [ {next_value}, %{next_label} ]"
        )
        string_iterable = isinstance(iterable.type, IrStringType) and enumerate_call is None
        bytes_iterable = isinstance(iterable.type, IrBytesType) and enumerate_call is None
        byte_data = iterable.value
        length = self._tmp("len")
        if string_iterable:
            lines.append(f"  {length} = call i64 @strlen(ptr {iterable.value})")
        elif bytes_iterable:
            byte_data = self._tmp("bytesdata")
            lines.append(f"  {byte_data} = call ptr @__xcc_aot_bytes_data(ptr {iterable.value})")
            lines.append(f"  {length} = call i64 @__xcc_aot_bytes_len(ptr {iterable.value})")
        else:
            lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {iterable.value})")
        condition = self._tmp("forcond")
        lines.append(f"  {condition} = icmp ult i64 {index}, {length}")
        condition_source = _current_label(lines)
        lines.append(f"  br i1 {condition}, label %{body_label}, label %{end_label}")
        lines.append(f"{body_label}:")
        body_names = dict(cond_names)
        if string_iterable or bytes_iterable:
            slots = _for_each_target_slots(statement.target)
            if len(slots) != 1 or slots[0] is None:
                self._error("string/bytes for-each expects one named target")
            pointer = self._tmp("byteitemptr")
            byte = self._tmp("byteitem")
            wide = self._tmp("byteitem64")
            lines.append(f"  {pointer} = getelementptr i8, ptr {byte_data}, i64 {index}")
            lines.append(f"  {byte} = load i8, ptr {pointer}")
            lines.append(f"  {wide} = zext i8 {byte} to i64")
            body_names[slots[0]] = _EmittedValue(wide, IrIntType(64, signed=True))
        else:
            item = self._tmp("item")
            lines.append(
                f"  {item} = call ptr @__xcc_aot_tuple_get(ptr {iterable.value}, i64 {index})"
            )
            if enumerate_call is not None:
                if enumerate_start is None:
                    self._error("Malformed __enumerate loop")
                enumerate_index = index
                if enumerate_start.value != "0":
                    enumerate_index = self._tmp("enumindex")
                    lines.append(f"  {enumerate_index} = add i64 {index}, {enumerate_start.value}")
                slots = _for_each_target_slots(statement.target)
                if len(slots) == 1 and slots[0] is not None:
                    body_names[slots[0]] = self._emit_enumerate_pair_tuple(
                        statement,
                        enumerate_index,
                        item,
                        lines,
                    )
                else:
                    self._bind_enumerate_targets(
                        statement,
                        enumerate_index,
                        item,
                        body_names,
                        lines,
                    )
            else:
                item_type: IrType = IrRecordType("object")
                if isinstance(iterable.type, IrTupleType) and len(iterable.type.elements) == 1:
                    item_type = iterable.type.elements[0]
                if isinstance(iterable.type, IrDictType):
                    item_type = iterable.type.key
                    item_value = self._emit_runtime_tuple_get(item, 0, item_type, lines)
                else:
                    item_value = self._emit_runtime_boxed_value(item, item_type, lines)
                slots = _for_each_target_slots(statement.target)
                if len(slots) > 1:
                    if isinstance(item_type, IrTupleType) and len(item_type.elements) == len(slots):
                        target_types = item_type.elements
                    elif (isinstance(item_type, IrTupleType) and not item_type.elements) or (
                        isinstance(item_type, IrRecordType) and item_type.name == "object"
                    ):
                        target_types = (IrRecordType("object"),) * len(slots)
                    else:
                        self._error("tuple for-each target expects tuple item type")
                    for slot_index, (target, target_type) in enumerate(
                        zip(slots, target_types, strict=True)
                    ):
                        if target is None:
                            continue
                        body_names[target] = self._emit_runtime_tuple_get(
                            item,
                            slot_index,
                            target_type,
                            lines,
                        )
                else:
                    for target in _for_each_targets(statement.target):
                        body_names[target] = item_value
        loop_labels = _LoopLabels(next_label, end_label, [], [])
        self.loop_stack.append(loop_labels)
        self._emit_branch(statement.body, body_names, lines, return_type)
        self.loop_stack.pop()
        incoming_edges: list[tuple[str, dict[str, _EmittedValue]]] = []
        if not _block_is_terminated(lines):
            incoming_edges.append((_current_label(lines), body_names))
            lines.append(f"  br label %{next_label}")
        incoming_edges.extend(loop_labels.continue_sources or ())
        lines.append(f"{next_label}:")
        next_phi_values: dict[str, _EmittedValue] = {}
        for name, initial in initial_values.items():
            if not incoming_edges:
                next_phi_values[name] = phi_values[name]
            elif len(incoming_edges) == 1:
                _source_label, source_names = incoming_edges[0]
                source_value = source_names.get(name, phi_values[name])
                next_phi_values[name] = _EmittedValue(
                    self._if_phi_value(source_value, initial.type),
                    initial.type,
                )
            else:
                result = self._tmp("loopnext")
                parts: list[str] = []
                for source_label, source_names in incoming_edges:
                    source_value = source_names.get(name, phi_values[name])
                    parts.append(
                        f"[ {self._if_phi_value(source_value, initial.type)}, %{source_label} ]"
                    )
                lines.append(
                    f"  {result} = phi {self._storage_llvm_type(initial.type)} " + ", ".join(parts)
                )
                next_phi_values[name] = _EmittedValue(result, initial.type)
        lines.append(f"  {next_value} = add i64 {index}, 1")
        lines.append(f"  br label %{cond_label}")
        for name, line_index in phi_lines.items():
            initial = initial_values[name]
            next_phi_value = next_phi_values.get(name, phi_values[name])
            lines[line_index] = (
                f"  {phi_values[name].value} = phi {self._storage_llvm_type(initial.type)} "
                f"[ {initial.value}, %{current_label} ], "
                f"[ {next_phi_value.value}, %{next_label} ]"
            )
            names[name] = phi_values[name]
        lines.append(f"{end_label}:")
        self._emit_loop_exit_phis(
            names,
            cond_names,
            condition_source,
            loop_labels.break_sources or (),
            {name: value.type for name, value in initial_values.items()},
            lines,
        )

    def _emit_set_item(
        self,
        statement: IrSetItem,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> None:
        target = self._emit_expr(statement.target, names, lines)
        index = self._emit_expr(statement.index, names, lines)
        value = self._emit_expr(statement.value, names, lines)
        stored = self._box_to_runtime_ptr(value, lines)
        index_value = self._coerce_index_i64(index, lines, "setitem")
        self.needs_runtime_prelude = True
        lines.append(
            f"  call void @__xcc_aot_tuple_set(ptr {target.value}, i64 {index_value}, ptr {stored})"
        )

    def _emit_assign_target(
        self,
        target: str,
        value: _EmittedValue,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> None:
        if "." not in target:
            _bind_emitted_target(target, value, names)
            return
        receiver_name, field_name = target.rsplit(".", 1)
        receiver_value = names.get(receiver_name)
        if receiver_value is None or not isinstance(receiver_value.type, IrRecordType):
            _bind_emitted_target(target, value, names)
            return
        record_name = self._field_record_name(receiver_value.type.name, field_name)
        field_index = self._field_index(record_name, field_name)
        field = self.records[record_name].fields[field_index]
        stored = self._value_for_result_type(value, field.type, lines)
        field_ptr = self._tmp("fieldptr")
        lines.append(
            f"  {field_ptr} = getelementptr inbounds %{record_name}, "
            f"ptr {receiver_value.value}, i32 0, i32 {field_index}"
        )
        lines.append(f"  store {self._storage_llvm_type(field.type)} {stored}, ptr {field_ptr}")
        names[target] = _EmittedValue(stored, field.type)

    def _bind_enumerate_targets(
        self,
        statement: IrForEach,
        index: str,
        item: str,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> None:
        if not isinstance(statement.iterable, IrCall) or not isinstance(
            statement.iterable.type, IrTupleType
        ):
            self._error("Malformed __enumerate loop")
        if len(statement.iterable.type.elements) != 2:
            self._error("__enumerate loop expects two element types")
        slots = _for_each_target_slots(statement.target)
        if len(slots) != 2:
            self._error("__enumerate loop expects two targets")
        values = (index, item)
        for slot_index, (slot, value, type_info) in enumerate(
            zip(
                slots,
                values,
                statement.iterable.type.elements,
                strict=True,
            )
        ):
            if slot is not None:
                if slot_index == 1:
                    names[slot] = self._emit_runtime_boxed_value(value, type_info, lines)
                else:
                    names[slot] = _EmittedValue(value, type_info)

    def _emit_enumerate_pair_tuple(
        self,
        statement: IrForEach,
        index: str,
        item: str,
        lines: list[str],
    ) -> _EmittedValue:
        if not isinstance(statement.iterable, IrCall) or not isinstance(
            statement.iterable.type,
            IrTupleType,
        ):
            self._error("Malformed __enumerate loop")
        if len(statement.iterable.type.elements) != 2:
            self._error("__enumerate loop expects two element types")
        self.needs_runtime_prelude = True
        result = self._tmp("enumpair")
        index_box = self._box_to_runtime_ptr(
            _EmittedValue(index, statement.iterable.type.elements[0]),
            lines,
        )
        lines.append("  ; build enumerate pair")
        lines.append(f"  {result} = call ptr @malloc(i64 24)")
        lines.append(f"  store i64 2, ptr {result}")
        index_slot = self._tmp("enumpairslot")
        item_slot = self._tmp("enumpairslot")
        lines.append(f"  {index_slot} = getelementptr ptr, ptr {result}, i64 1")
        lines.append(f"  store ptr {index_box}, ptr {index_slot}")
        lines.append(f"  {item_slot} = getelementptr ptr, ptr {result}, i64 2")
        lines.append(f"  store ptr {item}, ptr {item_slot}")
        return _EmittedValue(result, statement.iterable.type)

    def _emit_runtime_tuple_get(
        self,
        tuple_value: str,
        index: int,
        result_type: IrType,
        lines: list[str],
    ) -> _EmittedValue:
        raw = self._tmp("itemslot")
        lines.append(f"  {raw} = call ptr @__xcc_aot_tuple_get(ptr {tuple_value}, i64 {index})")
        return self._emit_runtime_boxed_value(raw, result_type, lines)

    def _emit_runtime_boxed_value(
        self,
        raw: str,
        result_type: IrType,
        lines: list[str],
    ) -> _EmittedValue:
        if _is_pointer_type(result_type):
            return _EmittedValue(raw, result_type)
        if isinstance(result_type, IrIntType):
            result = self._tmp("narrowint")
            lines.append(f"  {result} = ptrtoint ptr {raw} to {self._llvm_type(result_type)}")
            return _EmittedValue(result, result_type)
        if isinstance(result_type, IrBoolType):
            result = self._tmp("narrowbool")
            lines.append(f"  {result} = icmp ne ptr {raw}, null")
            return _EmittedValue(result, result_type)
        self._error(f"Unsupported tuple item type: {type(result_type).__name__}")

    def _bind_emitted_tuple_target(
        self,
        target: str,
        value: _EmittedValue,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> None:
        slots = _for_each_target_slots(target)
        if isinstance(value.type, IrTupleType) and len(value.type.elements) == len(slots):
            target_types = value.type.elements
            tuple_value = value.value
        elif (isinstance(value.type, IrTupleType) and not value.type.elements) or (
            isinstance(value.type, IrRecordType) and value.type.name == "object"
        ):
            target_types = (IrRecordType("object"),) * len(slots)
            tuple_value = value.value
        elif isinstance(value.type, IrIntType):
            target_types = (IrRecordType("object"),) * len(slots)
            tuple_value = self._tmp("tupleptr")
            lines.append(
                f"  {tuple_value} = inttoptr {self._llvm_type(value.type)} {value.value} to ptr"
            )
        else:
            self._error("tuple assignment target expects tuple value")
        for index, (slot, target_type) in enumerate(zip(slots, target_types, strict=True)):
            if slot is not None:
                names[slot] = self._emit_runtime_tuple_get(tuple_value, index, target_type, lines)

    def _emit_while(
        self,
        statement: IrWhile,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        assigned_types = _branch_assignment_types(statement.body)
        loop_types = {
            name: loop_type
            for name, value in names.items()
            if name in assigned_types
            for loop_type in (self._loop_carried_type(value.type, assigned_types[name]),)
            if loop_type is not None
        }
        assigned_names = tuple(sorted(loop_types))
        initial_values = {name: names[name] for name in assigned_names}
        cond_label = self._label("while.cond")
        body_label = self._label("while.body")
        end_label = self._label("while.end")
        incoming_label = _current_label(lines)
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        cond_names = dict(names)
        phi_lines: dict[str, int] = {}
        phi_values: dict[str, _EmittedValue] = {}
        for name, _initial in initial_values.items():
            result = self._tmp("loop")
            loop_type = loop_types[name]
            phi_lines[name] = len(lines)
            phi_values[name] = _EmittedValue(result, loop_type)
            cond_names[name] = phi_values[name]
            lines.append("")
        condition = self._emit_condition(statement.condition, cond_names, lines)
        condition_source = _current_label(lines)
        lines.append(f"  br i1 {condition.value}, label %{body_label}, label %{end_label}")
        lines.append(f"{body_label}:")
        body_names = dict(cond_names)
        loop_labels = _LoopLabels(cond_label, end_label, [], [])
        self.loop_stack.append(loop_labels)
        self._emit_branch(statement.body, body_names, lines, return_type)
        self.loop_stack.pop()
        incoming_edges: list[tuple[str, dict[str, _EmittedValue]]] = []
        if not _block_is_terminated(lines):
            incoming_edges.append((_current_label(lines), body_names))
            lines.append(f"  br label %{cond_label}")
        incoming_edges.extend(loop_labels.continue_sources or ())
        for name, line_index in phi_lines.items():
            initial = initial_values[name]
            loop_type = loop_types[name]
            initial_value = self._value_for_result_type(initial, loop_type)
            incoming = f"[ {initial_value}, %{incoming_label} ]"
            for source_label, source_names in incoming_edges:
                body_value = source_names.get(name, phi_values[name])
                phi_value = self._value_for_result_type(body_value, loop_type)
                incoming += f", [ {phi_value}, %{source_label} ]"
            lines[line_index] = (
                f"  {phi_values[name].value} = phi {self._storage_llvm_type(loop_type)} {incoming}"
            )
        lines.append(f"{end_label}:")
        self._emit_loop_exit_phis(
            names,
            cond_names,
            condition_source,
            loop_labels.break_sources or (),
            loop_types,
            lines,
        )

    def _emit_loop_exit_phis(
        self,
        names: dict[str, _EmittedValue],
        condition_names: dict[str, _EmittedValue],
        condition_source: str,
        break_sources: tuple[tuple[str, dict[str, _EmittedValue]], ...]
        | list[tuple[str, dict[str, _EmittedValue]]],
        loop_types: dict[str, IrType],
        lines: list[str],
    ) -> None:
        names.update(condition_names)
        if not break_sources:
            return
        for name, loop_type in loop_types.items():
            condition_value = condition_names[name]
            incoming = [
                f"[ {self._value_for_result_type(condition_value, loop_type)}, "
                f"%{condition_source} ]"
            ]
            for source_label, source_names in break_sources:
                source_value = source_names.get(name, condition_value)
                incoming.append(
                    f"[ {self._value_for_result_type(source_value, loop_type)}, %{source_label} ]"
                )
            result = self._tmp("loopexit")
            lines.append(
                f"  {result} = phi {self._storage_llvm_type(loop_type)} " + ", ".join(incoming)
            )
            names[name] = _EmittedValue(result, loop_type)

    def _loop_carried_type(
        self,
        initial_type: IrType,
        assigned_types: tuple[IrType, ...],
    ) -> IrType | None:
        values = (_EmittedValue("", initial_type),) + tuple(
            _EmittedValue("", assigned_type) for assigned_type in assigned_types
        )
        return self._if_phi_type(values)

    def _emit_branch(
        self,
        branch: IrBranch,
        names: dict[str, _EmittedValue],
        lines: list[str],
        return_type: IrType,
    ) -> None:
        for child in branch.statements:
            self._emit_statement(child, names, lines, return_type)
            if _block_is_terminated(lines):
                return

    def _emit_condition(
        self,
        expr: IrExpr,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        return self._coerce_to_bool(self._emit_expr(expr, names, lines), lines)

    def _emit_binary(
        self,
        expr: IrBinary,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        left = self._emit_expr(expr.left, names, lines)
        right = self._emit_expr(expr.right, names, lines)
        if expr.op == "//":
            return self._emit_floor_div(expr.type, left, right, lines)
        if expr.op == "%":
            return self._emit_modulo(expr.type, left, right, lines)
        if isinstance(expr.type, IrFloatType):
            float_opcode = {
                "+": "fadd",
                "-": "fsub",
                "*": "fmul",
            }.get(expr.op)
            if float_opcode is None:
                self._error(f"Unsupported LLVM float binary op: {expr.op}")
            result = self._tmp(float_opcode)
            lines.append(f"  {result} = {float_opcode} double {left.value}, {right.value}")
            return _EmittedValue(result, expr.type)
        shift_opcode = "ashr" if isinstance(expr.type, IrIntType) and expr.type.signed else "lshr"
        opcode = {
            "+": "add",
            "-": "sub",
            "*": "mul",
            "<<": "shl",
            ">>": shift_opcode,
            "|": "or",
            "&": "and",
            "^": "xor",
        }.get(expr.op)
        if opcode is None:
            self._error(f"Unsupported LLVM binary op: {expr.op}")
        result = self._tmp(opcode)
        lines.append(
            f"  {result} = {opcode} {self._llvm_type(expr.type)} {left.value}, {right.value}"
        )
        return _EmittedValue(result, expr.type)

    def _emit_floor_div(
        self,
        result_type: IrType,
        left: _EmittedValue,
        right: _EmittedValue,
        lines: list[str],
    ) -> _EmittedValue:
        if not isinstance(result_type, IrIntType):
            self._error(f"Unsupported LLVM floor division type: {type(result_type).__name__}")
        llvm_type = self._llvm_type(result_type)
        if not result_type.signed:
            result = self._tmp("udiv")
            lines.append(f"  {result} = udiv {llvm_type} {left.value}, {right.value}")
            return _EmittedValue(result, result_type)

        quotient = self._tmp("sdiv")
        remainder = self._tmp("srem")
        remainder_nonzero = self._tmp("remnz")
        left_negative = self._tmp("leftneg")
        right_negative = self._tmp("rightneg")
        signs_differ = self._tmp("signdiff")
        needs_adjustment = self._tmp("flooradj")
        decremented = self._tmp("floordec")
        result = self._tmp("floordiv")
        lines.append(f"  {quotient} = sdiv {llvm_type} {left.value}, {right.value}")
        lines.append(f"  {remainder} = srem {llvm_type} {left.value}, {right.value}")
        lines.append(f"  {remainder_nonzero} = icmp ne {llvm_type} {remainder}, 0")
        lines.append(f"  {left_negative} = icmp slt {llvm_type} {left.value}, 0")
        lines.append(f"  {right_negative} = icmp slt {llvm_type} {right.value}, 0")
        lines.append(f"  {signs_differ} = xor i1 {left_negative}, {right_negative}")
        lines.append(f"  {needs_adjustment} = and i1 {signs_differ}, {remainder_nonzero}")
        lines.append(f"  {decremented} = sub {llvm_type} {quotient}, 1")
        lines.append(
            f"  {result} = select i1 {needs_adjustment}, "
            f"{llvm_type} {decremented}, {llvm_type} {quotient}"
        )
        return _EmittedValue(result, result_type)

    def _emit_modulo(
        self,
        result_type: IrType,
        left: _EmittedValue,
        right: _EmittedValue,
        lines: list[str],
    ) -> _EmittedValue:
        if not isinstance(result_type, IrIntType):
            self._error(f"Unsupported LLVM modulo type: {type(result_type).__name__}")
        llvm_type = self._llvm_type(result_type)
        if not result_type.signed:
            result = self._tmp("urem")
            lines.append(f"  {result} = urem {llvm_type} {left.value}, {right.value}")
            return _EmittedValue(result, result_type)

        remainder = self._tmp("srem")
        remainder_nonzero = self._tmp("remnz")
        left_negative = self._tmp("leftneg")
        right_negative = self._tmp("rightneg")
        signs_differ = self._tmp("signdiff")
        needs_adjustment = self._tmp("modadj")
        adjusted = self._tmp("modfix")
        result = self._tmp("mod")
        lines.append(f"  {remainder} = srem {llvm_type} {left.value}, {right.value}")
        lines.append(f"  {remainder_nonzero} = icmp ne {llvm_type} {remainder}, 0")
        lines.append(f"  {left_negative} = icmp slt {llvm_type} {left.value}, 0")
        lines.append(f"  {right_negative} = icmp slt {llvm_type} {right.value}, 0")
        lines.append(f"  {signs_differ} = xor i1 {left_negative}, {right_negative}")
        lines.append(f"  {needs_adjustment} = and i1 {signs_differ}, {remainder_nonzero}")
        lines.append(f"  {adjusted} = add {llvm_type} {remainder}, {right.value}")
        lines.append(
            f"  {result} = select i1 {needs_adjustment}, "
            f"{llvm_type} {adjusted}, {llvm_type} {remainder}"
        )
        return _EmittedValue(result, result_type)

    def _emit_string_concat(
        self,
        expr: IrStringConcat,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if not expr.parts:
            return _EmittedValue(self._string_constant(""), IrStringType())
        value = self._coerce_to_string(self._emit_expr(expr.parts[0], names, lines), lines)
        for part in expr.parts[1:]:
            right = self._coerce_to_string(self._emit_expr(part, names, lines), lines)
            result = self._tmp("concat")
            self.needs_runtime_prelude = True
            lines.append(
                f"  {result} = call ptr @__xcc_aot_string_concat2("
                f"ptr {value.value}, ptr {right.value})"
            )
            value = _EmittedValue(result, IrStringType())
        return value

    def _coerce_to_string(self, value: _EmittedValue, lines: list[str]) -> _EmittedValue:
        if isinstance(value.type, IrStringType):
            return value
        if isinstance(value.type, IrIntType):
            result = self._tmp("itoa")
            self.needs_runtime_prelude = True
            lines.append(
                f"  {result} = call ptr @__xcc_aot_i64_to_string("
                f"{self._llvm_type(value.type)} {value.value})"
            )
            return _EmittedValue(result, IrStringType())
        if isinstance(value.type, IrNoneType):
            return _EmittedValue(self._string_constant("None"), IrStringType())
        if isinstance(value.type, (IrDictType, IrRecordType, IrTupleType)):
            return _EmittedValue(value.value, IrStringType())
        self._error(f"Unsupported string conversion type: {type(value.type).__name__}")

    def _emit_string_join(
        self,
        expr: IrStringJoin,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        separator = self._emit_expr(expr.separator, names, lines)
        values = self._emit_expr(expr.values, names, lines)
        result = self._tmp("join")
        self.needs_runtime_prelude = True
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_join("
            f"ptr {separator.value}, ptr {values.value})"
        )
        return _EmittedValue(result, IrStringType())

    def _emit_tuple(
        self,
        expr: IrTuple,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        self.needs_runtime_prelude = True
        args = [self._emit_expr(element, names, lines) for element in expr.elements]
        result = self._tmp("tuple")
        size = (len(args) + 1) * 8
        lines.append(f"  {result} = call ptr @malloc(i64 {size})")
        lines.append(f"  store i64 {len(args)}, ptr {result}")
        for index, arg in enumerate(args, start=1):
            slot = self._tmp("tupleslot")
            item = self._box_to_runtime_ptr(arg, lines)
            lines.append(f"  {slot} = getelementptr ptr, ptr {result}, i64 {index}")
            lines.append(f"  store ptr {item}, ptr {slot}")
        return _EmittedValue(result, expr.type)

    def _box_to_runtime_ptr(self, value: _EmittedValue, lines: list[str]) -> str:
        if isinstance(value.type, IrNoneType):
            return "null"
        if _is_pointer_type(value.type):
            return value.value
        if isinstance(value.type, IrBoolType):
            widened = self._tmp("boolbox")
            boxed = self._tmp("box")
            lines.append(f"  {widened} = zext i1 {value.value} to i64")
            lines.append(f"  {boxed} = inttoptr i64 {widened} to ptr")
            return boxed
        if isinstance(value.type, IrIntType):
            boxed = self._tmp("box")
            int_value = value.value
            if value.type.bits < 64:
                widened = self._tmp("intbox")
                opcode = "sext" if value.type.signed else "zext"
                lines.append(
                    f"  {widened} = {opcode} {self._llvm_type(value.type)} {int_value} to i64"
                )
                int_value = widened
            elif value.type.bits > 64:
                narrowed = self._tmp("intbox")
                lines.append(
                    f"  {narrowed} = trunc {self._llvm_type(value.type)} {int_value} to i64"
                )
                int_value = narrowed
            lines.append(f"  {boxed} = inttoptr i64 {int_value} to ptr")
            return boxed
        self._error(f"Unsupported tuple item type: {type(value.type).__name__}")

    def _emit_tuple_slice(
        self,
        expr: IrTupleSlice,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        value = self._emit_expr(expr.value, names, lines)
        start = -1 if expr.start is None else expr.start
        stop = -1 if expr.stop is None else expr.stop
        result = self._tmp("slice")
        self.needs_runtime_prelude = True
        lines.append(
            f"  {result} = call ptr @__xcc_aot_tuple_slice("
            f"ptr {value.value}, i64 {start}, i64 {stop})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_construct_record(
        self,
        expr: IrConstructRecord,
        names: dict[str, _EmittedValue],
        lines: list[str],
        target: str | None = None,
    ) -> _EmittedValue:
        raw = self._tmp(f"{target or expr.record.lower()}.raw")
        result = self._tmp(target or expr.record.lower())
        record = self.records[expr.record]
        type_id = self.record_type_ids[expr.record]
        self.needs_runtime_prelude = True
        lines.append(f"  {raw} = call ptr @malloc(i64 {_record_allocation_size(record)})")
        lines.append(f"  store i64 {type_id}, ptr {raw}")
        lines.append(f"  {result} = getelementptr i8, ptr {raw}, i64 8")
        for index, (arg, field) in enumerate(zip(expr.args, record.fields, strict=True)):
            value = self._emit_expr(arg, names, lines)
            stored = self._value_for_result_type(value, field.type, lines)
            field_ptr = self._tmp("fieldptr")
            lines.append(
                f"  {field_ptr} = getelementptr inbounds %{expr.record}, ptr {result}, "
                f"i32 0, i32 {index}"
            )
            lines.append(f"  store {self._storage_llvm_type(field.type)} {stored}, ptr {field_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_get_field(
        self,
        expr: IrGetField,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        value = self._emit_expr(expr.value, names, lines)
        record_type = value.type
        if not isinstance(record_type, IrRecordType):
            self._error(f"Unsupported LLVM field receiver: {expr.field}")
        record_name = self._field_record_name(record_type.name, expr.field)
        index = self._field_index(record_name, expr.field)
        field_ptr = self._tmp("fieldptr")
        result = self._tmp("load")
        lines.append(
            f"  {field_ptr} = getelementptr inbounds %{record_name}, ptr {value.value}, "
            f"i32 0, i32 {index}"
        )
        lines.append(f"  {result} = load {self._storage_llvm_type(expr.type)}, ptr {field_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        intrinsic = self._emit_intrinsic_call(expr, names, lines)
        if intrinsic is not None:
            return intrinsic
        args = [self._emit_expr(arg, names, lines) for arg in expr.args]
        rendered_args = ", ".join(f"{self._param_llvm_type(arg.type)} {arg.value}" for arg in args)
        target = _llvm_symbol(expr.target)
        if expr.target in self.fallible_functions:
            if not self.current_function_is_fallible or self.current_error_out is None:
                self._error(f"fallible call from non-fallible function: {expr.target}")
            result_slot = None
            call_args = [] if not rendered_args else [rendered_args]
            if not isinstance(expr.type, IrNoneType):
                result_slot = self._tmp("callresult")
                lines.append(f"  {result_slot} = alloca {self._storage_llvm_type(expr.type)}")
                call_args.append(f"ptr {result_slot}")
            call_args.append(f"ptr {self.current_error_out}")
            status = self._tmp("callstatus")
            lines.append(f"  {status} = call i32 {target}({', '.join(call_args)})")
            failed = self._tmp("callfailed")
            failure_label = self._label("call.error")
            success_label = self._label("call.ok")
            lines.append(f"  {failed} = icmp ne i32 {status}, 0")
            lines.append(f"  br i1 {failed}, label %{failure_label}, label %{success_label}")
            lines.append(f"{failure_label}:")
            return_type = (
                self.current_function.return_type
                if self.current_function is not None
                else IrNoneType()
            )
            self._emit_failure_transfer(status, names, lines, return_type)
            lines.append(f"{success_label}:")
            if result_slot is None:
                return _EmittedValue("null", expr.type)
            result = self._tmp("call")
            lines.append(
                f"  {result} = load {self._storage_llvm_type(expr.type)}, ptr {result_slot}"
            )
            return _EmittedValue(result, expr.type)
        if isinstance(expr.type, IrNoneType):
            lines.append(f"  call void {target}({rendered_args})")
            return _EmittedValue("null", expr.type)
        result = self._tmp("call")
        lines.append(f"  {result} = call {self._llvm_type(expr.type)} {target}({rendered_args})")
        return _EmittedValue(result, expr.type)

    def _emit_intrinsic_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue | None:
        if expr.target == "__llvm_api":
            return _EmittedValue("null", expr.type)
        if expr.target == "bool":
            return self._emit_bool_builtin_call(expr, names, lines)
        if expr.target == "isinstance":
            return self._emit_isinstance_call(expr, names, lines)
        if expr.target == "__record_construct0":
            return self._emit_record_construct0_call(expr, names, lines)
        if expr.target == "__llvm_FunctionType":
            return self._emit_llvm_function_type_call(expr, names, lines)
        if expr.target == "__llvm_AddCase":
            return self._emit_llvm_add_case_call(expr, names, lines)
        if expr.target == "__llvm_AddFunction":
            return self._emit_llvm_add_function_call(expr, names, lines)
        if expr.target == "__llvm_AddGlobal":
            return self._emit_llvm_add_global_call(expr, names, lines)
        if expr.target == "__llvm_AddIncoming":
            return self._emit_llvm_add_incoming_call(expr, names, lines)
        if expr.target == "__llvm_AppendBasicBlock":
            return self._emit_llvm_append_basic_block_call(expr, names, lines)
        if expr.target == "__llvm_ArrayType":
            return self._emit_llvm_array_type_call(expr, names, lines)
        if expr.target.startswith("__llvm_"):
            method = expr.target.removeprefix("__llvm_")
            if method in _LLVM_BINARY_BUILDER_INTRINSICS:
                return self._emit_llvm_build_binary_call(expr, names, lines, method)
            signature = _LLVM_C_API_INTRINSICS.get(method)
            if signature is not None:
                return self._emit_llvm_c_api_call(expr, names, lines, signature)
        if (
            expr.target == "len"
            and expr.args
            and (
                isinstance(expr.args[0].type, IrTupleType | IrDictType | IrBytesType)
                or _is_len_string_type(expr.args[0].type)
            )
        ):
            return self._emit_len_call(expr, names, lines)
        if expr.target == "range":
            return self._emit_range_call(expr, names, lines)
        if expr.target == "reversed":
            return self._emit_reversed_call(expr, names, lines)
        if (
            expr.target == "__getitem"
            and expr.args
            and isinstance(
                expr.args[0].type,
                (IrBytesType, IrTupleType, IrStringType, IrRecordType),
            )
        ):
            return self._emit_getitem_call(expr, names, lines)
        if (
            expr.target == "__cmp_NotIn"
            and len(expr.args) == 2
            and isinstance(expr.args[1], IrTuple)
        ):
            return self._emit_not_in_tuple(expr.args[0], expr.args[1], names, lines)
        if (
            expr.target in {"__cmp_In", "__cmp_NotIn"}
            and len(expr.args) == 2
            and isinstance(expr.args[1].type, IrStringType)
        ):
            return self._emit_string_membership(
                expr.args[0],
                expr.args[1],
                names,
                lines,
                negate=expr.target == "__cmp_NotIn",
            )
        if (
            expr.target in {"__cmp_In", "__cmp_NotIn"}
            and len(expr.args) == 2
            and isinstance(expr.args[1].type, IrDictType)
        ):
            return self._emit_dict_membership(
                expr.args[0],
                expr.args[1],
                names,
                lines,
                negate=expr.target == "__cmp_NotIn",
            )
        if (
            expr.target in {"__cmp_In", "__cmp_NotIn"}
            and len(expr.args) == 2
            and isinstance(expr.args[1].type, IrTupleType)
        ):
            return self._emit_tuple_membership(
                expr.args[0],
                expr.args[1],
                names,
                lines,
                negate=expr.target == "__cmp_NotIn",
            )
        if expr.target == "__str_startswith":
            return self._emit_string_startswith_call(expr, names, lines)
        if expr.target == "__str_endswith":
            return self._emit_string_endswith_call(expr, names, lines)
        if expr.target == "__str_find":
            return self._emit_string_find_call(expr, names, lines)
        if expr.target == "__str_split":
            return self._emit_string_split_call(expr, names, lines)
        if expr.target == "__str_split_limit":
            return self._emit_string_split_limit_call(expr, names, lines)
        if expr.target == "__str_split_whitespace":
            return self._emit_string_split_whitespace_call(expr, names, lines)
        if expr.target == "__str_splitlines":
            return self._emit_string_splitlines_call(expr, names, lines)
        if expr.target == "__str_replace":
            return self._emit_string_replace_call(expr, names, lines)
        if expr.target == "__str_removeprefix":
            return self._emit_string_remove_affix_call(expr, names, lines, "removeprefix")
        if expr.target == "__str_removesuffix":
            return self._emit_string_remove_affix_call(expr, names, lines, "removesuffix")
        if expr.target == "__str_lower":
            return self._emit_string_lower_call(expr, names, lines)
        if expr.target == "__str_ljust":
            return self._emit_string_ljust_call(expr, names, lines)
        if expr.target == "__str_encode":
            return self._emit_string_encode_call(expr, names, lines)
        if expr.target == "__bytes_ljust":
            return self._emit_bytes_ljust_call(expr, names, lines)
        if expr.target == "__bytes_concat":
            return self._emit_bytes_concat_call(expr, names, lines)
        if expr.target == "__bytes_repeat":
            return self._emit_bytes_repeat_call(expr, names, lines)
        if expr.target == "__str_lstrip":
            return self._emit_string_strip_call(expr, names, lines, "lstrip")
        if expr.target == "__str_rstrip":
            return self._emit_string_strip_call(expr, names, lines, "rstrip")
        if expr.target == "__str_strip":
            return self._emit_string_strip_call(expr, names, lines, "strip")
        if expr.target == "__str_repeat":
            return self._emit_string_repeat_call(expr, names, lines)
        if expr.target == "__tuple_concat":
            return self._emit_tuple_concat_call(expr, names, lines)
        if expr.target == "__tuple_repeat":
            return self._emit_tuple_repeat_call(expr, names, lines)
        predicate_mode = _STRING_PREDICATE_INTRINSICS.get(expr.target)
        if predicate_mode is not None:
            return self._emit_string_predicate_call(expr, predicate_mode, names, lines)
        if expr.target == "__bytes":
            return self._emit_bytes_call(expr, names, lines)
        if expr.target == "__bytes_slice":
            return self._emit_bytes_slice_call(expr, names, lines)
        if expr.target == "__id":
            return self._emit_id_call(expr, names, lines)
        if expr.target == "__ord":
            return self._emit_ord_call(expr, names, lines)
        if expr.target == "__chr":
            return self._emit_chr_call(expr, names, lines)
        if expr.target in {"__path_from_string", "__path_resolve", "__path_to_string"}:
            return self._emit_path_identity_call(expr, names, lines)
        if expr.target == "__path_parent":
            return self._emit_path_parent_call(expr, names, lines)
        if expr.target == "__path_name":
            return self._emit_path_name_call(expr, names, lines)
        if expr.target == "__path_join":
            return self._emit_path_join_call(expr, names, lines)
        if expr.target == "__path_read_text":
            return self._emit_path_read_text_call(expr, names, lines)
        if expr.target == "__path_is_file":
            return self._emit_path_is_file_call(expr, names, lines)
        if expr.target == "__dict_get":
            return self._emit_dict_get_call(expr, names, lines)
        if expr.target == "__dict_set":
            return self._emit_dict_set_call(expr, names, lines)
        if expr.target == "__dict_items":
            return self._emit_dict_items_call(expr, names, lines)
        if expr.target == "__zip":
            return self._emit_zip_call(expr, names, lines)
        if (
            _is_tuple_mutating_method(expr.target)
            and expr.args
            and isinstance(expr.args[0].type, IrTupleType)
        ):
            return self._emit_tuple_mutating_method_call(expr, names, lines)
        if expr.target == "__float":
            return self._emit_float_call(expr, names, lines)
        if expr.target == "__float_fromhex":
            return self._emit_float_fromhex_call(expr, names, lines)
        if expr.target == "__int_to_bytes":
            return self._emit_int_to_bytes_call(expr, names, lines)
        if expr.target == "__int_parse":
            return self._emit_int_parse_call(expr, names, lines)
        if expr.target == "__str_slice":
            return self._emit_str_slice_call(expr, names, lines)
        if expr.target not in {
            "__bool_and",
            "__bool_or",
            "__cmp_Eq",
            "__cmp_Is",
            "__cmp_IsNot",
            "__cmp_Gt",
            "__cmp_GtE",
            "__cmp_Lt",
            "__cmp_LtE",
            "__cmp_NotEq",
            "__ifexp",
            "__not",
        }:
            return None
        if expr.target == "__bool_and":
            return self._emit_bool_short_circuit("and", expr.args, names, lines)
        if expr.target == "__bool_or":
            return self._emit_bool_short_circuit("or", expr.args, names, lines)
        args = [self._emit_expr(arg, names, lines) for arg in expr.args]
        if expr.target == "__not":
            if len(args) != 1:
                self._error("__not expects one argument")
            return self._emit_bool_not(args[0], lines)
        if expr.target == "__ifexp":
            if len(args) != 3:
                self._error("__ifexp expects three arguments")
            condition = self._coerce_to_bool(args[0], lines)
            if isinstance(expr.type, IrNoneType):
                return _EmittedValue("null", expr.type)
            result = self._tmp("ifexp")
            result_type = self._llvm_type(expr.type)
            true_value = self._value_for_result_type(args[1], expr.type, lines)
            false_value = self._value_for_result_type(args[2], expr.type, lines)
            lines.append(
                f"  {result} = select i1 {condition.value}, "
                f"{result_type} {true_value}, {result_type} {false_value}"
            )
            return _EmittedValue(result, expr.type)
        if expr.target in {"__cmp_Eq", "__cmp_NotEq"}:
            if len(args) != 2:
                self._error(f"{expr.target} expects two arguments")
            return self._emit_equality_compare(
                args[0],
                args[1],
                negate=expr.target == "__cmp_NotEq",
                lines=lines,
            )
        if expr.target in {"__cmp_Is", "__cmp_IsNot"}:
            if len(args) != 2:
                self._error(f"{expr.target} expects two arguments")
            return self._emit_identity_compare(
                args[0],
                args[1],
                negate=expr.target == "__cmp_IsNot",
                lines=lines,
            )
        if expr.target in {"__cmp_Gt", "__cmp_GtE", "__cmp_Lt", "__cmp_LtE"}:
            if len(args) != 2:
                self._error(f"{expr.target} expects two arguments")
            return self._emit_order_compare(expr.target, args[0], args[1], lines)
        return None  # pragma: no cover

    def _emit_len_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("len expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(expr.type, IrIntType) or expr.type.bits != 64:
            self._error("len expects an int64 result")
        self.needs_runtime_prelude = True
        result = self._tmp("call")
        if isinstance(value.type, IrTupleType | IrDictType):
            lines.append(f"  {result} = call i64 @__xcc_aot_tuple_len(ptr {value.value})")
            return _EmittedValue(result, expr.type)
        if isinstance(value.type, IrBytesType):
            lines.append(f"  {result} = call i64 @__xcc_aot_bytes_len(ptr {value.value})")
            return _EmittedValue(result, expr.type)
        if _is_len_string_type(value.type):
            lines.append(f"  {result} = call i64 @strlen(ptr {value.value})")
            return _EmittedValue(result, expr.type)
        self._error(f"Unsupported len argument type: {type(value.type).__name__}")

    def _emit_bool_builtin_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("bool expects one argument")
        if not isinstance(expr.type, IrBoolType):
            self._error("bool expects a bool result")
        return self._coerce_to_bool(self._emit_expr(expr.args[0], names, lines), lines)

    def _emit_range_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) not in {1, 2, 3}:
            self._error("range expects one to three arguments")
        if not isinstance(expr.type, IrTupleType):
            self._error("range expects a tuple result")
        args = [self._emit_expr(arg, names, lines) for arg in expr.args]
        for arg in args:
            if not isinstance(arg.type, IrIntType) or arg.type.bits != 64:
                self._error("range expects int64 arguments")
        if len(args) == 1:
            start = "0"
            stop = args[0].value
            step = "1"
        elif len(args) == 2:
            start = args[0].value
            stop = args[1].value
            step = "1"
        else:
            start = args[0].value
            stop = args[1].value
            step = args[2].value
        self.needs_runtime_prelude = True
        result = self._tmp("range")
        lines.append(f"  {result} = call ptr @__xcc_aot_range(i64 {start}, i64 {stop}, i64 {step})")
        return _EmittedValue(result, expr.type)

    def _emit_reversed_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("reversed expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrTupleType) or not isinstance(expr.type, IrTupleType):
            self._error("reversed expects a tuple argument and result")
        self.needs_runtime_prelude = True
        result = self._tmp("reversed")
        lines.append(f"  {result} = call ptr @__xcc_aot_tuple_reversed(ptr {value.value})")
        return _EmittedValue(result, expr.type)

    def _emit_isinstance_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("isinstance expects two arguments")
        if not isinstance(expr.type, IrBoolType):
            self._error("isinstance expects a bool result")
        value = self._emit_expr(expr.args[0], names, lines)
        if isinstance(value.type, IrNoneType):
            return _EmittedValue("false", expr.type)
        if isinstance(value.type, (IrIntType, IrBoolType, IrFloatType)):
            return _EmittedValue("true", expr.type)
        target_ids = self._isinstance_target_type_ids(expr.args[1])
        if isinstance(value.type, IrRecordType) and target_ids:
            return self._emit_record_isinstance(value, target_ids, lines, expr.type)
        if _is_pointer_type(value.type):
            result = self._tmp("isinstance")
            lines.append(f"  {result} = icmp ne ptr {value.value}, null")
            return _EmittedValue(result, expr.type)
        self._error(f"Unsupported isinstance value type: {type(value.type).__name__}")

    def _emit_record_construct0_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1 or not isinstance(expr.type, IrRecordType):
            self._error("__record_construct0 expects one marker and a record result")
        marker = self._emit_expr(expr.args[0], names, lines)
        base_name = expr.type.name
        candidates = tuple(
            record
            for name, record in self.records.items()
            if name == base_name or self._record_extends(name, base_name)
        )
        if not candidates:
            self._error(f"__record_construct0 has no records for {base_name}")
        allocation_size = max(_record_allocation_size(record) for record in candidates)
        self.needs_runtime_prelude = True
        raw = self._tmp("recordctor.raw")
        type_id = self._tmp("recordctor.type")
        result = self._tmp("recordctor")
        lines.append(f"  {raw} = call ptr @malloc(i64 {allocation_size})")
        lines.append(f"  {type_id} = ptrtoint ptr {marker.value} to i64")
        lines.append(f"  store i64 {type_id}, ptr {raw}")
        lines.append(f"  {result} = getelementptr i8, ptr {raw}, i64 8")
        return _EmittedValue(result, expr.type)

    def _emit_record_isinstance(
        self,
        value: _EmittedValue,
        target_ids: tuple[int, ...],
        lines: list[str],
        result_type: IrBoolType,
    ) -> _EmittedValue:
        source_label = _current_label(lines)
        check_label = self._label("isinstance.check")
        end_label = self._label("isinstance.end")
        nonnull = self._tmp("isinstance.nonnull")
        lines.append(f"  {nonnull} = icmp ne ptr {value.value}, null")
        lines.append(f"  br i1 {nonnull}, label %{check_label}, label %{end_label}")
        lines.append(f"{check_label}:")
        tag_ptr = self._tmp("isinstance.tagptr")
        tag = self._tmp("isinstance.tag")
        lines.append(f"  {tag_ptr} = getelementptr i8, ptr {value.value}, i64 -8")
        lines.append(f"  {tag} = load i64, ptr {tag_ptr}")
        match = self._tmp("isinstance.match")
        lines.append(f"  {match} = icmp eq i64 {tag}, {target_ids[0]}")
        for target_id in target_ids[1:]:
            current = self._tmp("isinstance.match")
            combined = self._tmp("isinstance.match")
            lines.append(f"  {current} = icmp eq i64 {tag}, {target_id}")
            lines.append(f"  {combined} = or i1 {match}, {current}")
            match = combined
        check_source = _current_label(lines)
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("isinstance")
        lines.append(
            f"  {result} = phi i1 [ false, %{source_label} ], [ {match}, %{check_source} ]"
        )
        return _EmittedValue(result, result_type)

    def _isinstance_target_type_ids(self, target: IrExpr) -> tuple[int, ...]:
        names: list[str] = []
        if isinstance(target, IrName):
            names.append(target.name)
        elif isinstance(target, IrTuple):
            for element in target.elements:
                if isinstance(element, IrName):
                    names.append(element.name)
        ids: set[int] = set()
        for name in names:
            ids.update(self._record_descendant_type_ids(name))
        return tuple(sorted(ids))

    def _record_descendant_type_ids(self, base_name: str) -> tuple[int, ...]:
        ids: list[int] = []
        for record_name in sorted(self.records):
            if record_name == base_name or self._record_extends(record_name, base_name):
                ids.append(self.record_type_ids[record_name])
        return tuple(ids)

    def _record_extends(self, record_name: str, base_name: str) -> bool:
        record = self.records.get(record_name)
        if record is None:
            return False
        for base in record.bases:
            if base == base_name or self._record_extends(base, base_name):
                return True
        return False

    def _emit_string_startswith_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__str_startswith expects three arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        start = self._emit_expr(expr.args[2], names, lines)
        if not _is_string_like_type(value.type):
            self._error("__str_startswith expects string receiver and prefix")
        if not isinstance(start.type, IrIntType) or start.type.bits != 64:
            self._error("__str_startswith expects an int64 start")
        if not isinstance(expr.type, IrBoolType):
            self._error("__str_startswith expects a bool result")
        self.needs_runtime_prelude = True
        if isinstance(expr.args[1], IrTuple):
            result: _EmittedValue = _EmittedValue("false", IrBoolType())
            for prefix_expr in expr.args[1].elements:
                prefix = self._emit_expr(prefix_expr, names, lines)
                if not _is_string_like_type(prefix.type):
                    self._error("__str_startswith expects string receiver and prefix")
                current = self._tmp("startswith")
                lines.append(
                    f"  {current} = call i1 @__xcc_aot_string_startswith("
                    f"ptr {value.value}, ptr {prefix.value}, i64 {start.value})"
                )
                if result.value == "false":
                    result = _EmittedValue(current, IrBoolType())
                else:
                    combined = self._tmp("startswith")
                    lines.append(f"  {combined} = or i1 {result.value}, {current}")
                    result = _EmittedValue(combined, IrBoolType())
            return result
        prefix = self._emit_expr(expr.args[1], names, lines)
        if not _is_string_like_type(prefix.type):
            self._error("__str_startswith expects string receiver and prefix")
        call_result = self._tmp("startswith")
        lines.append(
            f"  {call_result} = call i1 @__xcc_aot_string_startswith("
            f"ptr {value.value}, ptr {prefix.value}, i64 {start.value})"
        )
        return _EmittedValue(call_result, expr.type)

    def _emit_string_endswith_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__str_endswith expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        suffix = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrStringType) or not isinstance(suffix.type, IrStringType):
            self._error("__str_endswith expects string receiver and suffix")
        if not isinstance(expr.type, IrBoolType):
            self._error("__str_endswith expects a bool result")
        self.needs_runtime_prelude = True
        result = self._tmp("endswith")
        lines.append(
            f"  {result} = call i1 @__xcc_aot_string_endswith("
            f"ptr {value.value}, ptr {suffix.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_find_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__str_find expects three arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        needle = self._emit_expr(expr.args[1], names, lines)
        start = self._emit_expr(expr.args[2], names, lines)
        if not isinstance(value.type, IrStringType) or not isinstance(needle.type, IrStringType):
            self._error("__str_find expects string receiver and needle")
        if not isinstance(start.type, IrIntType) or start.type.bits != 64:
            self._error("__str_find expects an int64 start")
        if not isinstance(expr.type, IrIntType) or expr.type.bits != 64:
            self._error("__str_find expects an int64 result")
        self.needs_runtime_prelude = True
        self.extra_declarations.add("declare ptr @strstr(ptr, ptr)")
        length = self._tmp("findlen")
        nonnegative = self._tmp("findstart")
        bounded = self._tmp("findstart")
        is_negative = self._tmp("findneg")
        is_past_end = self._tmp("findpast")
        start_ptr = self._tmp("findptr")
        found = self._tmp("find")
        found_i64 = self._tmp("findint")
        base_i64 = self._tmp("findbase")
        offset = self._tmp("findoffset")
        found_ok = self._tmp("findok")
        result = self._tmp("findresult")
        lines.append(f"  {length} = call i64 @strlen(ptr {value.value})")
        lines.append(f"  {is_negative} = icmp slt i64 {start.value}, 0")
        lines.append(f"  {nonnegative} = select i1 {is_negative}, i64 0, i64 {start.value}")
        lines.append(f"  {is_past_end} = icmp sgt i64 {nonnegative}, {length}")
        lines.append(f"  {bounded} = select i1 {is_past_end}, i64 {length}, i64 {nonnegative}")
        lines.append(f"  {start_ptr} = getelementptr inbounds i8, ptr {value.value}, i64 {bounded}")
        lines.append(f"  {found} = call ptr @strstr(ptr {start_ptr}, ptr {needle.value})")
        lines.append(f"  {found_ok} = icmp ne ptr {found}, null")
        lines.append(f"  {found_i64} = ptrtoint ptr {found} to i64")
        lines.append(f"  {base_i64} = ptrtoint ptr {value.value} to i64")
        lines.append(f"  {offset} = sub i64 {found_i64}, {base_i64}")
        lines.append(f"  {result} = select i1 {found_ok}, i64 {offset}, i64 -1")
        return _EmittedValue(result, expr.type)

    def _emit_string_split_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__str_split expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        separator = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrStringType) or not isinstance(separator.type, IrStringType):
            self._error("__str_split expects string receiver and separator")
        if not isinstance(expr.type, IrTupleType):
            self._error("__str_split expects a tuple result")
        self.needs_runtime_prelude = True
        result = self._tmp("split")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_split("
            f"ptr {value.value}, ptr {separator.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_split_whitespace_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__str_split_whitespace expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        maxsplit = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error("__str_split_whitespace expects string receiver")
        if not isinstance(maxsplit.type, IrIntType) or maxsplit.type.bits != 64:
            self._error("__str_split_whitespace expects an int64 maxsplit")
        if not isinstance(expr.type, IrTupleType):
            self._error("__str_split_whitespace expects a tuple result")
        self.needs_runtime_prelude = True
        result = self._tmp("splitws")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_split_whitespace("
            f"ptr {value.value}, i64 {maxsplit.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_split_limit_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__str_split_limit expects three arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        separator = self._emit_expr(expr.args[1], names, lines)
        maxsplit = self._emit_expr(expr.args[2], names, lines)
        if not isinstance(value.type, IrStringType) or not isinstance(separator.type, IrStringType):
            self._error("__str_split_limit expects string receiver and separator")
        if not isinstance(maxsplit.type, IrIntType) or maxsplit.type.bits != 64:
            self._error("__str_split_limit expects an int64 maxsplit")
        if not isinstance(expr.type, IrTupleType):
            self._error("__str_split_limit expects a tuple result")
        self.needs_runtime_prelude = True
        result = self._tmp("splitlimit")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_split_limit("
            f"ptr {value.value}, ptr {separator.value}, i64 {maxsplit.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_splitlines_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__str_splitlines expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        keepends = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error("__str_splitlines expects string receiver")
        if not isinstance(keepends.type, IrBoolType):
            self._error("__str_splitlines expects bool keepends")
        if not isinstance(expr.type, IrTupleType):
            self._error("__str_splitlines expects a tuple result")
        self.needs_runtime_prelude = True
        result = self._tmp("splitlines")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_splitlines("
            f"ptr {value.value}, i1 {keepends.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_replace_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__str_replace expects three arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        old = self._emit_expr(expr.args[1], names, lines)
        new = self._emit_expr(expr.args[2], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error("__str_replace expects string receiver")
        if not isinstance(old.type, IrStringType) or not isinstance(new.type, IrStringType):
            self._error("__str_replace expects string old and new values")
        if not isinstance(expr.type, IrStringType):
            self._error("__str_replace expects a string result")
        self.needs_runtime_prelude = True
        result = self._tmp("replace")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_replace("
            f"ptr {value.value}, ptr {old.value}, ptr {new.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_remove_affix_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
        mode: str,
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error(f"__str_{mode} expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        affix = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrStringType) or not isinstance(affix.type, IrStringType):
            self._error(f"__str_{mode} expects string receiver and affix")
        if not isinstance(expr.type, IrStringType):
            self._error(f"__str_{mode} expects a string result")
        self.needs_runtime_prelude = True
        result = self._tmp(mode)
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_{mode}(ptr {value.value}, ptr {affix.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_lower_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__str_lower expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error("__str_lower expects string receiver")
        if not isinstance(expr.type, IrStringType):
            self._error("__str_lower expects a string result")
        self.needs_runtime_prelude = True
        result = self._tmp("lower")
        lines.append(f"  {result} = call ptr @__xcc_aot_string_lower(ptr {value.value})")
        return _EmittedValue(result, expr.type)

    def _emit_string_ljust_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__str_ljust expects three arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        width = self._emit_expr(expr.args[1], names, lines)
        fill = self._emit_expr(expr.args[2], names, lines)
        if not isinstance(value.type, IrStringType) or not isinstance(fill.type, IrStringType):
            self._error("__str_ljust expects string receiver and fill")
        if not isinstance(width.type, IrIntType) or width.type.bits != 64:
            self._error("__str_ljust expects an int64 width")
        if not isinstance(expr.type, IrStringType):
            self._error("__str_ljust expects a string result")
        self.needs_runtime_prelude = True
        result = self._tmp("ljust")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_ljust("
            f"ptr {value.value}, i64 {width.value}, ptr {fill.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_bytes_ljust_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__bytes_ljust expects three arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        width = self._emit_expr(expr.args[1], names, lines)
        fill = self._emit_expr(expr.args[2], names, lines)
        if not isinstance(value.type, IrBytesType) or not isinstance(fill.type, IrBytesType):
            self._error("__bytes_ljust expects bytes receiver and fill")
        if not isinstance(width.type, IrIntType) or width.type.bits != 64:
            self._error("__bytes_ljust expects an int64 width")
        if not isinstance(expr.type, IrBytesType):
            self._error("__bytes_ljust expects a bytes result")
        self.needs_runtime_prelude = True
        result = self._tmp("bytesljust")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_bytes_ljust("
            f"ptr {value.value}, i64 {width.value}, ptr {fill.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_bytes_concat_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__bytes_concat expects two arguments")
        left = self._emit_expr(expr.args[0], names, lines)
        right = self._emit_expr(expr.args[1], names, lines)
        if not all(isinstance(value.type, IrBytesType) for value in (left, right)):
            self._error("__bytes_concat expects bytes arguments")
        if not isinstance(expr.type, IrBytesType):
            self._error("__bytes_concat expects a bytes result")
        self.needs_runtime_prelude = True
        result = self._tmp("bytesconcat")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_bytes_concat(ptr {left.value}, ptr {right.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_encode_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__str_encode expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error("__str_encode expects a string argument")
        if not isinstance(expr.type, IrBytesType):
            self._error("__str_encode expects a bytes result")
        self.needs_runtime_prelude = True
        result = self._tmp("strencode")
        lines.append(f"  {result} = call ptr @__xcc_aot_string_encode(ptr {value.value})")
        return _EmittedValue(result, expr.type)

    def _emit_bytes_repeat_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__bytes_repeat expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        count = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrBytesType):
            self._error("__bytes_repeat expects a bytes value")
        if not isinstance(count.type, IrIntType) or count.type.bits != 64:
            self._error("__bytes_repeat expects an int64 count")
        if not isinstance(expr.type, IrBytesType):
            self._error("__bytes_repeat expects a bytes result")
        self.needs_runtime_prelude = True
        result = self._tmp("bytesrepeat")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_bytes_repeat(ptr {value.value}, i64 {count.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_strip_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
        mode: str,
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error(f"__str_{mode} expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        chars = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrStringType) or not isinstance(chars.type, IrStringType):
            self._error(f"__str_{mode} expects string receiver and chars")
        if not isinstance(expr.type, IrStringType):
            self._error(f"__str_{mode} expects a string result")
        self.needs_runtime_prelude = True
        result = self._tmp(mode)
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_{mode}(ptr {value.value}, ptr {chars.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_bytes_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__bytes expects one argument")
        size = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(size.type, IrIntType) or size.type.bits != 64:
            self._error("__bytes expects an int64 size")
        if not isinstance(expr.type, IrBytesType):
            self._error("__bytes expects a bytes result")
        self.needs_runtime_prelude = True
        result = self._tmp("bytes")
        lines.append(f"  {result} = call ptr @__xcc_aot_bytes_new(i64 {size.value})")
        return _EmittedValue(result, expr.type)

    def _emit_id_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__id expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(expr.type, IrIntType) or expr.type.bits != 64:
            self._error("__id expects an int64 result")
        if not _is_pointer_type(value.type):
            self._error("__id expects a pointer-like value")
        result = self._tmp("id")
        lines.append(f"  {result} = ptrtoint ptr {value.value} to i64")
        return _EmittedValue(result, expr.type)

    def _emit_ord_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__ord expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error("__ord expects a string argument")
        if not isinstance(expr.type, IrIntType) or expr.type.bits != 64:
            self._error("__ord expects an int64 result")
        byte = self._tmp("ordbyte")
        result = self._tmp("ord")
        lines.append(f"  {byte} = load i8, ptr {value.value}")
        lines.append(f"  {result} = zext i8 {byte} to i64")
        return _EmittedValue(result, expr.type)

    def _emit_chr_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__chr expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrIntType) or value.type.bits != 64:
            self._error("__chr expects an int64 argument")
        if not isinstance(expr.type, IrStringType):
            self._error("__chr expects a string result")
        self.needs_runtime_prelude = True
        result = self._tmp("chr")
        byte = self._tmp("chrbyte")
        terminator = self._tmp("chrnul")
        lines.append(f"  {result} = call ptr @malloc(i64 2)")
        lines.append(f"  {byte} = trunc i64 {value.value} to i8")
        lines.append(f"  store i8 {byte}, ptr {result}")
        lines.append(f"  {terminator} = getelementptr i8, ptr {result}, i64 1")
        lines.append(f"  store i8 0, ptr {terminator}")
        return _EmittedValue(result, expr.type)

    def _emit_dict_get_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__dict_get expects two arguments")
        dict_value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(dict_value.type, IrDictType):
            self._error("__dict_get expects a tuple-backed dict")
        key_type, value_type = dict_value.type.key, dict_value.type.value
        key = self._emit_expr(expr.args[1], names, lines)
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("dictget.ptr")
        index_ptr = self._tmp("dictget.index")
        cond_label = self._label("dictget.cond")
        body_label = self._label("dictget.body")
        found_label = self._label("dictget.found")
        next_label = self._label("dictget.next")
        end_label = self._label("dictget.end")
        result_type = self._llvm_type(expr.type)
        lines.append(f"  {result_ptr} = alloca {result_type}")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store {result_type} {self._default_value(expr.type)}, ptr {result_ptr}")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("dictget.index")
        length = self._tmp("dictget.len")
        done = self._tmp("dictget.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {dict_value.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        raw_pair = self._tmp("dictget.pair")
        lines.append(
            f"  {raw_pair} = call ptr @__xcc_aot_tuple_get(ptr {dict_value.value}, i64 {index})"
        )
        candidate_key = self._emit_runtime_tuple_get(raw_pair, 0, key_type, lines)
        match = self._emit_equality_compare(key, candidate_key, negate=False, lines=lines)
        lines.append(f"  br i1 {match.value}, label %{found_label}, label %{next_label}")
        lines.append(f"{found_label}:")
        value = self._emit_runtime_tuple_get(raw_pair, 1, value_type, lines)
        result_value = self._value_for_result_type(value, expr.type, lines)
        lines.append(f"  store {result_type} {result_value}, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("dictget.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("dictget")
        lines.append(f"  {result} = load {result_type}, ptr {result_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_dict_set_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__dict_set expects three arguments")
        dict_value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(dict_value.type, IrDictType):
            self._error("__dict_set expects a tuple-backed dict")
        if not isinstance(expr.type, IrDictType):
            self._error("__dict_set expects a tuple-backed result")
        key_type, value_type = dict_value.type.key, dict_value.type.value
        key = self._emit_expr(expr.args[1], names, lines)
        value = self._emit_expr(expr.args[2], names, lines)
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("dictset.ptr")
        index_ptr = self._tmp("dictset.index")
        cond_label = self._label("dictset.cond")
        body_label = self._label("dictset.body")
        found_label = self._label("dictset.found")
        next_label = self._label("dictset.next")
        append_label = self._label("dictset.append")
        end_label = self._label("dictset.end")
        lines.append(f"  {result_ptr} = alloca ptr")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store ptr {dict_value.value}, ptr {result_ptr}")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("dictset.index")
        length = self._tmp("dictset.len")
        done = self._tmp("dictset.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {dict_value.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{append_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        raw_pair = self._tmp("dictset.pair")
        lines.append(
            f"  {raw_pair} = call ptr @__xcc_aot_tuple_get(ptr {dict_value.value}, i64 {index})"
        )
        candidate_key = self._emit_runtime_tuple_get(raw_pair, 0, key_type, lines)
        match = self._emit_equality_compare(key, candidate_key, negate=False, lines=lines)
        lines.append(f"  br i1 {match.value}, label %{found_label}, label %{next_label}")
        lines.append(f"{found_label}:")
        coerced_value = _EmittedValue(
            self._value_for_result_type(value, value_type, lines),
            value_type,
        )
        value_box = self._box_to_runtime_ptr(coerced_value, lines)
        value_slot = self._tmp("dictset.valueslot")
        lines.append(f"  {value_slot} = getelementptr ptr, ptr {raw_pair}, i64 2")
        lines.append(f"  store ptr {value_box}, ptr {value_slot}")
        lines.append(f"  store ptr {dict_value.value}, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("dictset.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{append_label}:")
        pair = self._tmp("dictset.pair")
        key_slot = self._tmp("dictset.keyslot")
        append_value_slot = self._tmp("dictset.valueslot")
        singleton = self._tmp("dictset.singleton")
        singleton_slot = self._tmp("dictset.singletonslot")
        appended = self._tmp("dictset.appended")
        coerced_key = _EmittedValue(self._value_for_result_type(key, key_type, lines), key_type)
        key_box = self._box_to_runtime_ptr(coerced_key, lines)
        coerced_append_value = _EmittedValue(
            self._value_for_result_type(value, value_type, lines),
            value_type,
        )
        append_value_box = self._box_to_runtime_ptr(
            coerced_append_value,
            lines,
        )
        lines.append(f"  {pair} = call ptr @malloc(i64 24)")
        lines.append(f"  store i64 2, ptr {pair}")
        lines.append(f"  {key_slot} = getelementptr ptr, ptr {pair}, i64 1")
        lines.append(f"  store ptr {key_box}, ptr {key_slot}")
        lines.append(f"  {append_value_slot} = getelementptr ptr, ptr {pair}, i64 2")
        lines.append(f"  store ptr {append_value_box}, ptr {append_value_slot}")
        lines.append(f"  {singleton} = call ptr @malloc(i64 16)")
        lines.append(f"  store i64 1, ptr {singleton}")
        lines.append(f"  {singleton_slot} = getelementptr ptr, ptr {singleton}, i64 1")
        lines.append(f"  store ptr {pair}, ptr {singleton_slot}")
        lines.append(
            f"  {appended} = call ptr @__xcc_aot_tuple_concat("
            f"ptr {dict_value.value}, ptr {singleton})"
        )
        lines.append(f"  store ptr {appended}, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("dictset")
        lines.append(f"  {result} = load ptr, ptr {result_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_dict_items_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__dict_items expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrDictType):
            self._error("__dict_items expects a tuple-backed dict")
        if not isinstance(expr.type, IrTupleType):
            self._error("__dict_items expects a tuple result")
        return _EmittedValue(value.value, expr.type)

    def _emit_zip_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__zip currently expects two arguments")
        left = self._emit_expr(expr.args[0], names, lines)
        right = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(left.type, IrTupleType) or not isinstance(right.type, IrTupleType):
            self._error("__zip expects tuple-backed iterables")
        if not isinstance(expr.type, IrTupleType):
            self._error("__zip expects a tuple result")
        self.needs_runtime_prelude = True
        result = self._tmp("zip")
        lines.append(f"  {result} = call ptr @__xcc_aot_zip2(ptr {left.value}, ptr {right.value})")
        return _EmittedValue(result, expr.type)

    def _emit_tuple_mutating_method_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        method = expr.target.rsplit(".", 1)[1]
        if not expr.args:
            self._error(f"{method} expects a receiver")
        receiver = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(receiver.type, IrTupleType):
            self._error(f"{method} expects a tuple-backed receiver")
        if method == "pop":
            if len(expr.args) != 1:
                self._error("pop expects only a receiver")
            result = self._tmp("tuple")
            self.needs_runtime_prelude = True
            lines.append(f"  {result} = call ptr @__xcc_aot_tuple_pop(ptr {receiver.value})")
            result_type = expr.type if isinstance(expr.type, IrTupleType) else receiver.type
            if isinstance(expr.type, IrNoneType):
                return _EmittedValue("null", expr.type)
            return _EmittedValue(result, result_type)
        if len(expr.args) != 2:
            self._error(f"{method} expects receiver and one argument")
        result_type = expr.type if isinstance(expr.type, IrTupleType) else receiver.type
        if method == "extend":
            extension = self._emit_expr(expr.args[1], names, lines)
            if not isinstance(extension.type, IrTupleType):
                self._error("extend expects a tuple-backed argument")
            result = self._tmp("tuple")
            self.needs_runtime_prelude = True
            lines.append(
                f"  {result} = call ptr @__xcc_aot_tuple_concat("
                f"ptr {receiver.value}, ptr {extension.value})"
            )
            return _EmittedValue(result, result_type)
        item = self._emit_expr(expr.args[1], names, lines)
        singleton = self._runtime_singleton_tuple(item, lines)
        result = self._tmp("tuple")
        self.needs_runtime_prelude = True
        lines.append(
            f"  {result} = call ptr @__xcc_aot_tuple_concat(ptr {receiver.value}, ptr {singleton})"
        )
        return _EmittedValue(result, result_type)

    def _runtime_singleton_tuple(self, item: _EmittedValue, lines: list[str]) -> str:
        result = self._tmp("tuple")
        slot = self._tmp("tupleslot")
        boxed = self._box_to_runtime_ptr(item, lines)
        lines.append("  ; tuple-backed append singleton")
        lines.append(f"  {result} = call ptr @malloc(i64 16)")
        lines.append(f"  store i64 1, ptr {result}")
        lines.append(f"  {slot} = getelementptr ptr, ptr {result}, i64 1")
        lines.append(f"  store ptr {boxed}, ptr {slot}")
        return result

    def _emit_float_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__float expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(expr.type, IrFloatType):
            self._error("__float expects a float result")
        if isinstance(value.type, IrFloatType):
            return value
        if isinstance(value.type, IrIntType):
            result = self._tmp("float")
            opcode = "sitofp" if value.type.signed else "uitofp"
            value_type = self._llvm_type(value.type)
            lines.append(f"  {result} = {opcode} {value_type} {value.value} to double")
            return _EmittedValue(result, expr.type)
        if isinstance(value.type, IrStringType):
            result = self._tmp("float")
            self.extra_declarations.add("declare double @strtod(ptr, ptr)")
            lines.append(f"  {result} = call double @strtod(ptr {value.value}, ptr null)")
            return _EmittedValue(result, expr.type)
        self._error(
            f"__float expects an int, float, or string argument, got {type(value.type).__name__}"
        )

    def _emit_float_fromhex_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__float_fromhex expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error("__float_fromhex expects a string argument")
        if not isinstance(expr.type, IrFloatType):
            self._error("__float_fromhex expects a float result")
        result = self._tmp("float")
        self.extra_declarations.add("declare double @strtod(ptr, ptr)")
        lines.append(f"  {result} = call double @strtod(ptr {value.value}, ptr null)")
        return _EmittedValue(result, expr.type)

    def _emit_int_to_bytes_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__int_to_bytes expects three arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        size = self._emit_expr(expr.args[1], names, lines)
        byteorder = self._emit_expr(expr.args[2], names, lines)
        if not isinstance(value.type, IrIntType) or value.type.bits != 64:
            self._error("__int_to_bytes expects an int64 value")
        if not isinstance(size.type, IrIntType) or size.type.bits != 64:
            self._error("__int_to_bytes expects an int64 size")
        if not isinstance(byteorder.type, IrStringType):
            self._error("__int_to_bytes expects a string byteorder")
        if not isinstance(expr.type, IrBytesType):
            self._error("__int_to_bytes expects a bytes result")
        self.needs_runtime_prelude = True
        result = self._tmp("tobytes")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_int_to_bytes("
            f"i64 {value.value}, i64 {size.value}, ptr {byteorder.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_int_parse_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__int_parse expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        base = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error("__int_parse expects a string value")
        if not isinstance(base.type, IrIntType) or base.type.bits != 64:
            self._error("__int_parse expects an int64 base")
        if not isinstance(expr.type, IrIntType) or expr.type.bits != 64:
            self._error("__int_parse expects an int64 result")
        self.needs_runtime_prelude = True
        result = self._tmp("parseint")
        lines.append(
            f"  {result} = call i64 @__xcc_aot_parse_int(ptr {value.value}, i64 {base.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_path_parent_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__path_parent expects one argument")
        path = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(path.type, IrRecordType):
            self._error("__path_parent expects an opaque path object")
        if not isinstance(expr.type, IrRecordType):
            self._error("__path_parent expects an opaque path result")
        self.needs_runtime_prelude = True
        result = self._tmp("pathparent")
        lines.append(f"  {result} = call ptr @__xcc_aot_path_parent(ptr {path.value})")
        return _EmittedValue(result, expr.type)

    def _emit_path_identity_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error(f"{expr.target} expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if expr.target == "__path_from_string" and not isinstance(value.type, IrStringType):
            self._error("__path_from_string expects a string")
        if expr.target == "__path_to_string" and not isinstance(expr.type, IrStringType):
            self._error("__path_to_string expects a string result")
        if expr.target in {"__path_resolve", "__path_to_string"} and not isinstance(
            value.type, IrRecordType
        ):
            self._error(f"{expr.target} expects an opaque path object")
        if expr.target in {"__path_from_string", "__path_resolve"} and not isinstance(
            expr.type, IrRecordType
        ):
            self._error(f"{expr.target} expects an opaque path result")
        return _EmittedValue(value.value, expr.type)

    def _emit_path_join_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__path_join expects two arguments")
        path = self._emit_expr(expr.args[0], names, lines)
        child = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(path.type, IrRecordType):
            self._error("__path_join expects an opaque path object")
        if not isinstance(child.type, IrStringType):
            self._error("__path_join expects a string child")
        if not isinstance(expr.type, IrRecordType):
            self._error("__path_join expects an opaque path result")
        self.needs_runtime_prelude = True
        result = self._tmp("pathjoin")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_path_join(ptr {path.value}, ptr {child.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_path_name_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__path_name expects one argument")
        path = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(path.type, IrRecordType):
            self._error("__path_name expects an opaque path object")
        if not isinstance(expr.type, IrStringType):
            self._error("__path_name expects a string result")
        self.needs_runtime_prelude = True
        result = self._tmp("pathname")
        lines.append(f"  {result} = call ptr @__xcc_aot_path_name(ptr {path.value})")
        return _EmittedValue(result, expr.type)

    def _emit_path_read_text_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__path_read_text expects one argument")
        path = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(path.type, IrRecordType):
            self._error("__path_read_text expects an opaque path object")
        if not isinstance(expr.type, IrStringType):
            self._error("__path_read_text expects a string result")
        self.needs_runtime_prelude = True
        result = self._tmp("pathread")
        lines.append(f"  {result} = call ptr @__xcc_aot_read_text_file(ptr {path.value})")
        return _EmittedValue(result, expr.type)

    def _emit_path_is_file_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__path_is_file expects one argument")
        path = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(path.type, IrRecordType):
            self._error("__path_is_file expects an opaque path object")
        if not isinstance(expr.type, IrBoolType):
            self._error("__path_is_file expects a bool result")
        self.needs_runtime_prelude = True
        result = self._tmp("pathfile")
        lines.append(f"  {result} = call i1 @__xcc_aot_path_is_file(ptr {path.value})")
        return _EmittedValue(result, expr.type)

    def _emit_string_repeat_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__str_repeat expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        count = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error("__str_repeat expects a string value")
        if not isinstance(count.type, IrIntType) or count.type.bits != 64:
            self._error("__str_repeat expects an int64 count")
        if not isinstance(expr.type, IrStringType):
            self._error("__str_repeat expects a string result")
        self.needs_runtime_prelude = True
        result = self._tmp("strrepeat")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_repeat(ptr {value.value}, i64 {count.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_tuple_concat_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__tuple_concat expects two arguments")
        left = self._emit_expr(expr.args[0], names, lines)
        right = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(left.type, IrTupleType) or not isinstance(right.type, IrTupleType):
            self._error("__tuple_concat expects tuple arguments")
        if not isinstance(expr.type, IrTupleType):
            self._error("__tuple_concat expects a tuple result")
        self.needs_runtime_prelude = True
        result = self._tmp("tupleconcat")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_tuple_concat(ptr {left.value}, ptr {right.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_tuple_repeat_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__tuple_repeat expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        count = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrTupleType):
            self._error("__tuple_repeat expects a tuple value")
        if not isinstance(count.type, IrIntType) or count.type.bits != 64:
            self._error("__tuple_repeat expects an int64 count")
        if not isinstance(expr.type, IrTupleType):
            self._error("__tuple_repeat expects a tuple result")
        self.needs_runtime_prelude = True
        result = self._tmp("tuplerepeat")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_tuple_repeat(ptr {value.value}, i64 {count.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_predicate_call(
        self,
        expr: IrCall,
        mode: int,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error(f"{expr.target} expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error(f"{expr.target} expects a string receiver")
        if not isinstance(expr.type, IrBoolType):
            self._error(f"{expr.target} expects a bool result")
        self.needs_runtime_prelude = True
        result = self._tmp("strpred")
        lines.append(
            f"  {result} = call i1 @__xcc_aot_string_predicate(ptr {value.value}, i64 {mode})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_getitem_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__getitem expects two arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        index = self._emit_expr(expr.args[1], names, lines)
        index_value = self._coerce_index_i64(index, lines, "__getitem")
        self.needs_runtime_prelude = True
        if isinstance(value.type, IrStringType):
            if not isinstance(expr.type, IrStringType):
                self._error("string __getitem expects a string result")
            length = self._tmp("stritemlen")
            negative = self._tmp("stritemnegative")
            wrapped = self._tmp("stritemwrapped")
            normalized = self._tmp("stritemindex")
            pointer = self._tmp("stritemptr")
            byte = self._tmp("stritem")
            result = self._tmp("stritem")
            terminator = self._tmp("stritemnul")
            lines.append(f"  {length} = call i64 @strlen(ptr {value.value})")
            lines.append(f"  {negative} = icmp slt i64 {index_value}, 0")
            lines.append(f"  {wrapped} = add i64 {length}, {index_value}")
            lines.append(f"  {normalized} = select i1 {negative}, i64 {wrapped}, i64 {index_value}")
            lines.append(f"  {pointer} = getelementptr i8, ptr {value.value}, i64 {normalized}")
            lines.append(f"  {byte} = load i8, ptr {pointer}")
            lines.append(f"  {result} = call ptr @malloc(i64 2)")
            lines.append(f"  store i8 {byte}, ptr {result}")
            lines.append(f"  {terminator} = getelementptr i8, ptr {result}, i64 1")
            lines.append(f"  store i8 0, ptr {terminator}")
            return _EmittedValue(result, expr.type)
        if isinstance(value.type, IrBytesType):
            if not isinstance(expr.type, IrIntType):
                self._error("bytes __getitem expects an integer result")
            result = self._tmp("bytesitem")
            lines.append(
                f"  {result} = call i64 @__xcc_aot_bytes_get(ptr {value.value}, i64 {index_value})"
            )
            return _EmittedValue(result, expr.type)
        if isinstance(value.type, IrRecordType) and value.type.name != "object":
            self._error("__getitem expects a tuple, string, or object receiver")
        if not isinstance(value.type, (IrTupleType, IrRecordType)):
            self._error("__getitem expects a tuple or string receiver")
        raw = self._tmp("call")
        lines.append(
            f"  {raw} = call ptr @__xcc_aot_tuple_get(ptr {value.value}, i64 {index_value})"
        )
        return self._emit_runtime_boxed_value(raw, expr.type, lines)

    def _emit_not_in_tuple(
        self,
        needle_expr: IrExpr,
        haystack_expr: IrTuple,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        needle = self._emit_expr(needle_expr, names, lines)
        if not haystack_expr.elements:
            return _EmittedValue("true", IrBoolType())
        membership = self._emit_equality_compare(
            needle,
            self._emit_expr(haystack_expr.elements[0], names, lines),
            negate=False,
            lines=lines,
        )
        for element_expr in haystack_expr.elements[1:]:
            element = self._emit_expr(element_expr, names, lines)
            match = self._emit_equality_compare(needle, element, negate=False, lines=lines)
            result = self._tmp("contains")
            lines.append(f"  {result} = or i1 {membership.value}, {match.value}")
            membership = _EmittedValue(result, IrBoolType())
        return self._emit_bool_not(membership, lines)

    def _emit_string_membership(
        self,
        needle_expr: IrExpr,
        haystack_expr: IrExpr,
        names: dict[str, _EmittedValue],
        lines: list[str],
        *,
        negate: bool,
    ) -> _EmittedValue:
        needle = self._emit_expr(needle_expr, names, lines)
        haystack = self._emit_expr(haystack_expr, names, lines)
        if not isinstance(haystack.type, IrStringType):
            self._error("string membership expects a string haystack")
        if not isinstance(needle.type, (IrIntType, IrStringType)):
            self._error("string membership expects a string or int needle")
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("contains.ptr")
        index_ptr = self._tmp("contains.index")
        needle_byte = self._tmp("contains.needle")
        cond_label = self._label("contains.cond")
        body_label = self._label("contains.body")
        found_label = self._label("contains.found")
        next_label = self._label("contains.next")
        end_label = self._label("contains.end")
        lines.append(f"  {result_ptr} = alloca i1")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i1 false, ptr {result_ptr}")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        if isinstance(needle.type, IrStringType):
            needle_empty = self._tmp("contains.empty")
            lines.append(f"  {needle_byte} = load i8, ptr {needle.value}")
            lines.append(f"  {needle_empty} = icmp eq i8 {needle_byte}, 0")
            lines.append(f"  br i1 {needle_empty}, label %{found_label}, label %{cond_label}")
        else:
            lines.append(f"  {needle_byte} = trunc i64 {needle.value} to i8")
            lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("contains.index")
        length = self._tmp("contains.len")
        done = self._tmp("contains.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @strlen(ptr {haystack.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        pointer = self._tmp("contains.ptr")
        byte = self._tmp("contains.byte")
        match = self._tmp("contains.match")
        lines.append(f"  {pointer} = getelementptr i8, ptr {haystack.value}, i64 {index}")
        lines.append(f"  {byte} = load i8, ptr {pointer}")
        lines.append(f"  {match} = icmp eq i8 {byte}, {needle_byte}")
        lines.append(f"  br i1 {match}, label %{found_label}, label %{next_label}")
        lines.append(f"{found_label}:")
        lines.append(f"  store i1 true, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("contains.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("contains")
        lines.append(f"  {result} = load i1, ptr {result_ptr}")
        membership = _EmittedValue(result, IrBoolType())
        if negate:
            return self._emit_bool_not(membership, lines)
        return membership

    def _emit_tuple_membership(
        self,
        needle_expr: IrExpr,
        haystack_expr: IrExpr,
        names: dict[str, _EmittedValue],
        lines: list[str],
        *,
        negate: bool,
    ) -> _EmittedValue:
        if not isinstance(haystack_expr.type, IrTupleType):
            self._error("tuple membership expects a tuple haystack")
        if not haystack_expr.type.elements:
            return _EmittedValue("true" if negate else "false", IrBoolType())
        self.needs_runtime_prelude = True
        needle = self._emit_expr(needle_expr, names, lines)
        haystack = self._emit_expr(haystack_expr, names, lines)
        item_type = _homogeneous_tuple_element_type(haystack.type) or IrRecordType("object")
        result_ptr = self._tmp("contains.ptr")
        index_ptr = self._tmp("contains.index")
        cond_label = self._label("contains.cond")
        body_label = self._label("contains.body")
        found_label = self._label("contains.found")
        next_label = self._label("contains.next")
        end_label = self._label("contains.end")
        lines.append(f"  {result_ptr} = alloca i1")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i1 false, ptr {result_ptr}")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("contains.index")
        length = self._tmp("contains.len")
        done = self._tmp("contains.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {haystack.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        raw_item = self._tmp("contains.item")
        lines.append(
            f"  {raw_item} = call ptr @__xcc_aot_tuple_get(ptr {haystack.value}, i64 {index})"
        )
        item = self._emit_runtime_boxed_value(raw_item, item_type, lines)
        match = self._emit_equality_compare(needle, item, negate=False, lines=lines)
        lines.append(f"  br i1 {match.value}, label %{found_label}, label %{next_label}")
        lines.append(f"{found_label}:")
        lines.append(f"  store i1 true, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("contains.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("contains")
        lines.append(f"  {result} = load i1, ptr {result_ptr}")
        membership = _EmittedValue(result, IrBoolType())
        if negate:
            return self._emit_bool_not(membership, lines)
        return membership

    def _emit_dict_membership(
        self,
        needle_expr: IrExpr,
        haystack_expr: IrExpr,
        names: dict[str, _EmittedValue],
        lines: list[str],
        *,
        negate: bool,
    ) -> _EmittedValue:
        if not isinstance(haystack_expr.type, IrDictType):
            self._error("dict membership expects a dict haystack")
        self.needs_runtime_prelude = True
        needle = self._emit_expr(needle_expr, names, lines)
        haystack = self._emit_expr(haystack_expr, names, lines)
        result_ptr = self._tmp("dictcontains.ptr")
        index_ptr = self._tmp("dictcontains.index")
        cond_label = self._label("dictcontains.cond")
        body_label = self._label("dictcontains.body")
        found_label = self._label("dictcontains.found")
        next_label = self._label("dictcontains.next")
        end_label = self._label("dictcontains.end")
        lines.append(f"  {result_ptr} = alloca i1")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i1 false, ptr {result_ptr}")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("dictcontains.index")
        length = self._tmp("dictcontains.len")
        done = self._tmp("dictcontains.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {haystack.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        pair = self._tmp("dictcontains.pair")
        lines.append(f"  {pair} = call ptr @__xcc_aot_tuple_get(ptr {haystack.value}, i64 {index})")
        key = self._emit_runtime_tuple_get(pair, 0, haystack_expr.type.key, lines)
        match = self._emit_equality_compare(needle, key, negate=False, lines=lines)
        lines.append(f"  br i1 {match.value}, label %{found_label}, label %{next_label}")
        lines.append(f"{found_label}:")
        lines.append(f"  store i1 true, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("dictcontains.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("dictcontains")
        lines.append(f"  {result} = load i1, ptr {result_ptr}")
        membership = _EmittedValue(result, IrBoolType())
        if negate:
            return self._emit_bool_not(membership, lines)
        return membership

    def _emit_bool_fold(
        self,
        op: str,
        args: list[_EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if not args:
            return _EmittedValue("true" if op == "and" else "false", IrBoolType())
        value = self._coerce_to_bool(args[0], lines)
        for arg in args[1:]:
            right = self._coerce_to_bool(arg, lines)
            result = self._tmp(op)
            lines.append(f"  {result} = {op} i1 {value.value}, {right.value}")
            value = _EmittedValue(result, IrBoolType())
        return value

    def _emit_bool_short_circuit(
        self,
        op: str,
        args: tuple[IrExpr, ...],
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if not args:
            return _EmittedValue("true" if op == "and" else "false", IrBoolType())
        if len(args) == 1:
            return self._coerce_to_bool(self._emit_expr(args[0], names, lines), lines)
        end_label = self._label(f"bool.{op}.end")
        incoming: list[tuple[str, str]] = []
        for index, arg in enumerate(args):
            value = self._coerce_to_bool(self._emit_expr(arg, names, lines), lines)
            source_label = _current_label(lines)
            if index == len(args) - 1:
                incoming.append((source_label, value.value))
                lines.append(f"  br label %{end_label}")
                break
            next_label = self._label(f"bool.{op}.next")
            if op == "and":
                incoming.append((source_label, "false"))
                lines.append(f"  br i1 {value.value}, label %{next_label}, label %{end_label}")
            else:
                incoming.append((source_label, "true"))
                lines.append(f"  br i1 {value.value}, label %{end_label}, label %{next_label}")
            lines.append(f"{next_label}:")
        lines.append(f"{end_label}:")
        result = self._tmp(op)
        parts = ", ".join(f"[ {value}, %{source} ]" for source, value in incoming)
        lines.append(f"  {result} = phi i1 {parts}")
        return _EmittedValue(result, IrBoolType())

    def _select_arm_value(self, value: _EmittedValue, result_type: IrType) -> str:
        if isinstance(value.type, IrNoneType):
            return self._default_value(result_type)
        return value.value

    def _emit_bool_not(self, value: _EmittedValue, lines: list[str]) -> _EmittedValue:
        truth = self._coerce_to_bool(value, lines)
        result = self._tmp("not")
        lines.append(f"  {result} = xor i1 {truth.value}, true")
        return _EmittedValue(result, IrBoolType())

    def _emit_runtime_object_narrowing(
        self,
        value: _EmittedValue,
        requested_type: IrType,
        lines: list[str],
    ) -> _EmittedValue | None:
        if not isinstance(value.type, IrRecordType):
            return None
        if value.type.name != "object" and not _record_union_can_runtime_narrow(
            value.type.name,
            requested_type,
        ):
            return None
        if isinstance(requested_type, IrIntType):
            result = self._tmp("narrowint")
            lines.append(
                f"  {result} = ptrtoint ptr {value.value} to {self._llvm_type(requested_type)}"
            )
            return _EmittedValue(result, requested_type)
        if isinstance(requested_type, IrBoolType):
            result = self._tmp("narrowbool")
            lines.append(f"  {result} = icmp ne ptr {value.value}, null")
            return _EmittedValue(result, requested_type)
        if isinstance(requested_type, IrStringType | IrBytesType | IrTupleType):
            return _EmittedValue(value.value, requested_type)
        return None

    def _coerce_to_bool(self, value: _EmittedValue, lines: list[str]) -> _EmittedValue:
        if isinstance(value.type, IrBoolType):
            return value
        if isinstance(value.type, IrNoneType):
            return _EmittedValue("false", IrBoolType())
        if isinstance(value.type, IrIntType):
            result = self._tmp("truth")
            lines.append(f"  {result} = icmp ne {self._llvm_type(value.type)} {value.value}, 0")
            return _EmittedValue(result, IrBoolType())
        if isinstance(value.type, IrStringType):
            length = self._tmp("strlen")
            result = self._tmp("truth")
            lines.append(f"  {length} = call i64 @strlen(ptr {value.value})")
            lines.append(f"  {result} = icmp ne i64 {length}, 0")
            return _EmittedValue(result, IrBoolType())
        if isinstance(value.type, IrTupleType | IrDictType):
            length = self._tmp("tuplelen")
            result = self._tmp("truth")
            lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {value.value})")
            lines.append(f"  {result} = icmp ne i64 {length}, 0")
            return _EmittedValue(result, IrBoolType())
        if isinstance(value.type, IrBytesType):
            length = self._tmp("byteslen")
            result = self._tmp("truth")
            lines.append(f"  {length} = call i64 @__xcc_aot_bytes_len(ptr {value.value})")
            lines.append(f"  {result} = icmp ne i64 {length}, 0")
            return _EmittedValue(result, IrBoolType())
        if isinstance(value.type, IrRecordType):
            result = self._tmp("truth")
            lines.append(f"  {result} = icmp ne ptr {value.value}, null")
            return _EmittedValue(result, IrBoolType())
        self._error(f"Unsupported LLVM truth value type: {type(value.type).__name__}")

    def _emit_llvm_function_type_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 4 or not isinstance(expr.type, IrIntType):
            self._error("LLVMFunctionType helper expects four args -> int")
        ret_type = self._emit_expr(expr.args[0], names, lines)
        params = self._emit_expr(expr.args[1], names, lines)
        count = self._emit_expr(expr.args[2], names, lines)
        variadic = self._emit_expr(expr.args[3], names, lines)
        ret_ptr = self._coerce_llvm_pointer(ret_type, lines)
        params_ptr = self._coerce_llvm_pointer(params, lines)
        count_i32 = self._coerce_i32(count, lines)
        variadic_bool = self._coerce_to_bool(variadic, lines)
        result_ptr = self._tmp("llvmcall")
        result = self._tmp("llvmint")
        self.extra_declarations.add("declare ptr @LLVMFunctionType(ptr, ptr, i32, i1)")
        lines.append(
            f"  {result_ptr} = call ptr @LLVMFunctionType("
            f"ptr {ret_ptr}, ptr {params_ptr}, i32 {count_i32}, i1 {variadic_bool.value})"
        )
        lines.append(f"  {result} = ptrtoint ptr {result_ptr} to {self._llvm_type(expr.type)}")
        return _EmittedValue(result, expr.type)

    def _emit_llvm_add_case_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3 or not isinstance(expr.type, IrNoneType):
            self._error("LLVMAddCase helper expects three args -> None")
        switch = self._coerce_llvm_pointer(self._emit_expr(expr.args[0], names, lines), lines)
        value = self._coerce_llvm_pointer(self._emit_expr(expr.args[1], names, lines), lines)
        block = self._coerce_llvm_pointer(self._emit_expr(expr.args[2], names, lines), lines)
        self.extra_declarations.add("declare void @LLVMAddCase(ptr, ptr, ptr)")
        lines.append(f"  call void @LLVMAddCase(ptr {switch}, ptr {value}, ptr {block})")
        return _EmittedValue("null", expr.type)

    def _emit_llvm_add_function_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3 or not isinstance(expr.type, IrIntType):
            self._error("LLVMAddFunction helper expects three args -> int")
        module = self._coerce_llvm_pointer(self._emit_expr(expr.args[0], names, lines), lines)
        name = self._emit_expr(expr.args[1], names, lines)
        if not _is_pointer_type(name.type):
            self._error("LLVMAddFunction helper expects a pointer-like name")
        name_ptr = self._coerce_llvm_pointer(name, lines)
        function_type = self._coerce_llvm_pointer(
            self._emit_expr(expr.args[2], names, lines),
            lines,
        )
        result_ptr = self._tmp("llvmcall")
        result = self._tmp("llvmint")
        self.extra_declarations.add("declare ptr @LLVMAddFunction(ptr, ptr, ptr)")
        lines.append(
            f"  {result_ptr} = call ptr @LLVMAddFunction("
            f"ptr {module}, ptr {name_ptr}, ptr {function_type})"
        )
        lines.append(f"  {result} = ptrtoint ptr {result_ptr} to {self._llvm_type(expr.type)}")
        return _EmittedValue(result, expr.type)

    def _emit_llvm_add_global_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3 or not isinstance(expr.type, IrIntType):
            self._error("LLVMAddGlobal helper expects three args -> int")
        module = self._coerce_llvm_pointer(self._emit_expr(expr.args[0], names, lines), lines)
        type_ref = self._coerce_llvm_pointer(self._emit_expr(expr.args[1], names, lines), lines)
        name = self._emit_expr(expr.args[2], names, lines)
        if not _is_pointer_type(name.type):
            self._error("LLVMAddGlobal helper expects a pointer-like name")
        name_ptr = self._coerce_llvm_pointer(name, lines)
        result_ptr = self._tmp("llvmcall")
        result = self._tmp("llvmint")
        self.extra_declarations.add("declare ptr @LLVMAddGlobal(ptr, ptr, ptr)")
        lines.append(
            f"  {result_ptr} = call ptr @LLVMAddGlobal("
            f"ptr {module}, ptr {type_ref}, ptr {name_ptr})"
        )
        lines.append(f"  {result} = ptrtoint ptr {result_ptr} to {self._llvm_type(expr.type)}")
        return _EmittedValue(result, expr.type)

    def _emit_llvm_add_incoming_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 4 or not isinstance(expr.type, IrNoneType):
            self._error("LLVMAddIncoming helper expects four args -> None")
        phi = self._coerce_llvm_pointer(self._emit_expr(expr.args[0], names, lines), lines)
        values = self._coerce_llvm_pointer(self._emit_expr(expr.args[1], names, lines), lines)
        blocks = self._coerce_llvm_pointer(self._emit_expr(expr.args[2], names, lines), lines)
        count = self._coerce_i32(self._emit_expr(expr.args[3], names, lines), lines)
        self.extra_declarations.add("declare void @LLVMAddIncoming(ptr, ptr, ptr, i32)")
        lines.append(
            f"  call void @LLVMAddIncoming(ptr {phi}, ptr {values}, ptr {blocks}, i32 {count})"
        )
        return _EmittedValue("null", expr.type)

    def _emit_llvm_append_basic_block_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2 or not isinstance(expr.type, IrIntType):
            self._error("LLVMAppendBasicBlock helper expects two args -> int")
        function = self._coerce_llvm_pointer(self._emit_expr(expr.args[0], names, lines), lines)
        name = self._emit_expr(expr.args[1], names, lines)
        if not _is_pointer_type(name.type):
            self._error("LLVMAppendBasicBlock helper expects a pointer-like name")
        name_ptr = self._coerce_llvm_pointer(name, lines)
        result_ptr = self._tmp("llvmcall")
        result = self._tmp("llvmint")
        self.extra_declarations.add("declare ptr @LLVMAppendBasicBlock(ptr, ptr)")
        lines.append(
            f"  {result_ptr} = call ptr @LLVMAppendBasicBlock(ptr {function}, ptr {name_ptr})"
        )
        lines.append(f"  {result} = ptrtoint ptr {result_ptr} to {self._llvm_type(expr.type)}")
        return _EmittedValue(result, expr.type)

    def _emit_llvm_array_type_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2 or not isinstance(expr.type, IrIntType):
            self._error("LLVMArrayType helper expects two args -> int")
        element_type = self._coerce_llvm_pointer(
            self._emit_expr(expr.args[0], names, lines),
            lines,
        )
        count = self._coerce_index_i64(
            self._emit_expr(expr.args[1], names, lines),
            lines,
            "LLVMArrayType",
        )
        result_ptr = self._tmp("llvmcall")
        result = self._tmp("llvmint")
        self.extra_declarations.add("declare ptr @LLVMArrayType2(ptr, i64)")
        lines.append(f"  {result_ptr} = call ptr @LLVMArrayType2(ptr {element_type}, i64 {count})")
        lines.append(f"  {result} = ptrtoint ptr {result_ptr} to {self._llvm_type(expr.type)}")
        return _EmittedValue(result, expr.type)

    def _emit_llvm_build_binary_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
        method: str,
    ) -> _EmittedValue:
        if len(expr.args) != 4:
            self._error(f"LLVM{method} helper expects four args")
        builder = self._coerce_llvm_pointer(self._emit_expr(expr.args[0], names, lines), lines)
        left = self._coerce_llvm_pointer(self._emit_expr(expr.args[1], names, lines), lines)
        right = self._coerce_llvm_pointer(self._emit_expr(expr.args[2], names, lines), lines)
        name = self._emit_expr(expr.args[3], names, lines)
        if not _is_pointer_type(name.type):
            self._error(f"LLVM{method} helper expects a pointer-like name")
        name_ptr = self._coerce_llvm_pointer(name, lines)
        result_ptr = self._tmp("llvmcall")
        self.extra_declarations.add(f"declare ptr @LLVM{method}(ptr, ptr, ptr, ptr)")
        lines.append(
            f"  {result_ptr} = call ptr @LLVM{method}("
            f"ptr {builder}, ptr {left}, ptr {right}, ptr {name_ptr})"
        )
        if _is_pointer_type(expr.type):
            return _EmittedValue(result_ptr, expr.type)
        if isinstance(expr.type, IrIntType):
            result = self._tmp("llvmint")
            lines.append(f"  {result} = ptrtoint ptr {result_ptr} to {self._llvm_type(expr.type)}")
            return _EmittedValue(result, expr.type)
        self._error(f"LLVM{method} helper returns an unsupported type")

    def _emit_llvm_c_api_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
        signature: tuple[str, str, tuple[str, ...]],
    ) -> _EmittedValue:
        c_name, result_kind, arg_kinds = signature
        if len(expr.args) != len(arg_kinds):
            self._error(f"{c_name} helper expects {len(arg_kinds)} args")
        rendered_args: list[str] = []
        for arg, arg_kind in zip(expr.args, arg_kinds, strict=True):
            value = self._emit_expr(arg, names, lines)
            rendered_args.append(
                f"{_LLVM_C_TYPE_NAMES[arg_kind]} "
                f"{self._coerce_llvm_c_arg(value, arg_kind, lines, c_name)}"
            )
        result_type = _LLVM_C_TYPE_NAMES[result_kind]
        arg_types = ", ".join(_LLVM_C_TYPE_NAMES[arg_kind] for arg_kind in arg_kinds)
        self.extra_declarations.add(f"declare {result_type} @{c_name}({arg_types})")
        rendered = ", ".join(rendered_args)
        if result_kind == "void":
            lines.append(f"  call void @{c_name}({rendered})")
            return self._void_llvm_c_result(expr.type)
        result = self._tmp("llvmcall")
        lines.append(f"  {result} = call {result_type} @{c_name}({rendered})")
        return self._adapt_llvm_c_result(result, result_kind, expr.type, lines)

    def _coerce_llvm_c_arg(
        self,
        value: _EmittedValue,
        kind: str,
        lines: list[str],
        context: str,
    ) -> str:
        if kind == "ptr":
            return self._coerce_llvm_pointer(value, lines)
        if kind == "i32":
            return self._coerce_llvm_c_i32(value, lines, context)
        if kind == "i64":
            return self._coerce_llvm_c_i64(value, lines, context)
        if kind == "i1":
            return self._coerce_to_bool(value, lines).value
        if kind == "double":
            return self._coerce_llvm_c_double(value, lines, context)
        self._error(f"{context} has unsupported LLVM C argument kind: {kind}")

    def _coerce_llvm_c_i32(
        self,
        value: _EmittedValue,
        lines: list[str],
        context: str,
    ) -> str:
        if isinstance(value.type, IrIntType):
            return self._coerce_i32(value, lines)
        if isinstance(value.type, IrBoolType):
            result = self._tmp("i32")
            lines.append(f"  {result} = zext i1 {value.value} to i32")
            return result
        if _is_pointer_type(value.type):
            as_i64 = self._coerce_index_i64(value, lines, context)
            result = self._tmp("i32")
            lines.append(f"  {result} = trunc i64 {as_i64} to i32")
            return result
        self._error(f"{context} expects an i32-compatible argument")

    def _coerce_llvm_c_i64(
        self,
        value: _EmittedValue,
        lines: list[str],
        context: str,
    ) -> str:
        if isinstance(value.type, IrIntType) or _is_pointer_type(value.type):
            return self._coerce_index_i64(value, lines, context)
        if isinstance(value.type, IrBoolType):
            result = self._tmp("i64")
            lines.append(f"  {result} = zext i1 {value.value} to i64")
            return result
        self._error(f"{context} expects an i64-compatible argument")

    def _coerce_llvm_c_double(
        self,
        value: _EmittedValue,
        lines: list[str],
        context: str,
    ) -> str:
        if isinstance(value.type, IrFloatType):
            return value.value
        if isinstance(value.type, IrIntType):
            result = self._tmp("double")
            opcode = "sitofp" if value.type.signed else "uitofp"
            lines.append(
                f"  {result} = {opcode} {self._llvm_type(value.type)} {value.value} to double"
            )
            return result
        self._error(f"{context} expects a double-compatible argument")

    def _adapt_llvm_c_result(
        self,
        value: str,
        kind: str,
        result_type: IrType,
        lines: list[str],
    ) -> _EmittedValue:
        if isinstance(result_type, IrNoneType):
            return _EmittedValue("null", result_type)
        if kind == "ptr":
            if _is_pointer_type(result_type):
                return _EmittedValue(value, result_type)
            if isinstance(result_type, IrBoolType):
                result = self._tmp("llvmbool")
                lines.append(f"  {result} = icmp ne ptr {value}, null")
                return _EmittedValue(result, result_type)
            if isinstance(result_type, IrIntType):
                result = self._tmp("llvmint")
                lines.append(f"  {result} = ptrtoint ptr {value} to {self._llvm_type(result_type)}")
                return _EmittedValue(result, result_type)
        if kind in {"i32", "i64"}:
            return self._adapt_llvm_c_integer_result(value, kind, result_type, lines)
        if kind == "i1":
            if isinstance(result_type, IrBoolType):
                return _EmittedValue(value, result_type)
            if isinstance(result_type, IrIntType):
                result = self._tmp("llvmint")
                lines.append(f"  {result} = zext i1 {value} to {self._llvm_type(result_type)}")
                return _EmittedValue(result, result_type)
        if kind == "double" and isinstance(result_type, IrFloatType):
            return _EmittedValue(value, result_type)
        self._error(f"LLVM C result kind {kind} cannot produce {type(result_type).__name__}")

    def _adapt_llvm_c_integer_result(
        self,
        value: str,
        kind: str,
        result_type: IrType,
        lines: list[str],
    ) -> _EmittedValue:
        source_type = "i32" if kind == "i32" else "i64"
        source_bits = 32 if kind == "i32" else 64
        if isinstance(result_type, IrBoolType):
            result = self._tmp("llvmbool")
            lines.append(f"  {result} = icmp ne {source_type} {value}, 0")
            return _EmittedValue(result, result_type)
        if _is_pointer_type(result_type):
            pointer_int = value
            if source_bits < 64:
                pointer_int = self._tmp("llvmint")
                lines.append(f"  {pointer_int} = zext {source_type} {value} to i64")
            result = self._tmp("llvmptr")
            lines.append(f"  {result} = inttoptr i64 {pointer_int} to ptr")
            return _EmittedValue(result, result_type)
        if isinstance(result_type, IrIntType):
            if result_type.bits == source_bits:
                return _EmittedValue(value, result_type)
            result = self._tmp("llvmint")
            if result_type.bits > source_bits:
                lines.append(
                    f"  {result} = zext {source_type} {value} to {self._llvm_type(result_type)}"
                )
            else:
                lines.append(
                    f"  {result} = trunc {source_type} {value} to {self._llvm_type(result_type)}"
                )
            return _EmittedValue(result, result_type)
        self._error(f"LLVM C integer result cannot produce {type(result_type).__name__}")

    def _void_llvm_c_result(self, result_type: IrType) -> _EmittedValue:
        if isinstance(result_type, IrNoneType):
            return _EmittedValue("null", result_type)
        if isinstance(result_type, IrBoolType):
            return _EmittedValue("false", result_type)
        if isinstance(result_type, IrIntType):
            return _EmittedValue("0", result_type)
        if _is_pointer_type(result_type):
            return _EmittedValue("null", result_type)
        self._error(f"LLVM C void result cannot produce {type(result_type).__name__}")

    def _coerce_llvm_pointer(self, value: _EmittedValue, lines: list[str]) -> str:
        if isinstance(value.type, IrNoneType):
            return "null"
        if isinstance(value.type, IrBytesType):
            self.needs_runtime_prelude = True
            result = self._tmp("bytesdata")
            lines.append(f"  {result} = call ptr @__xcc_aot_bytes_data(ptr {value.value})")
            return result
        if _is_pointer_type(value.type):
            return value.value
        if isinstance(value.type, IrIntType):
            result = self._tmp("llvmptr")
            lines.append(
                f"  {result} = inttoptr {self._llvm_type(value.type)} {value.value} to ptr"
            )
            return result
        self._error(f"Unsupported LLVM pointer value type: {type(value.type).__name__}")

    def _coerce_i32(self, value: _EmittedValue, lines: list[str]) -> str:
        if not isinstance(value.type, IrIntType):
            self._error(f"Unsupported i32 value type: {type(value.type).__name__}")
        if value.type.bits == 32:
            return value.value
        result = self._tmp("i32")
        if value.type.bits < 32:
            opcode = "sext" if value.type.signed else "zext"
            lines.append(
                f"  {result} = {opcode} {self._llvm_type(value.type)} {value.value} to i32"
            )
        else:
            lines.append(f"  {result} = trunc {self._llvm_type(value.type)} {value.value} to i32")
        return result

    def _coerce_index_i64(
        self,
        value: _EmittedValue,
        lines: list[str],
        context: str,
    ) -> str:
        if isinstance(value.type, IrIntType):
            if value.type.bits == 64:
                return value.value
            result = self._tmp("index")
            if value.type.bits < 64:
                opcode = "sext" if value.type.signed else "zext"
                lines.append(
                    f"  {result} = {opcode} {self._llvm_type(value.type)} {value.value} to i64"
                )
            else:
                lines.append(
                    f"  {result} = trunc {self._llvm_type(value.type)} {value.value} to i64"
                )
            return result
        if _is_pointer_type(value.type):
            result = self._tmp("index")
            lines.append(f"  {result} = ptrtoint ptr {value.value} to i64")
            return result
        self._error(f"{context} expects an int64 index")

    def _emit_identity_compare(
        self,
        left: _EmittedValue,
        right: _EmittedValue,
        *,
        negate: bool,
        lines: list[str],
    ) -> _EmittedValue:
        predicate = "ne" if negate else "eq"
        result = self._tmp("is")
        if isinstance(left.type, IrIntType) or isinstance(right.type, IrIntType):
            left_value = left.value if isinstance(left.type, IrIntType) else "0"
            right_value = right.value if isinstance(right.type, IrIntType) else "0"
            int_type = left.type if isinstance(left.type, IrIntType) else right.type
            lines.append(
                f"  {result} = icmp {predicate} {self._llvm_type(int_type)} "
                f"{left_value}, {right_value}"
            )
            return _EmittedValue(result, IrBoolType())
        left_value = self._pointer_compare_value(left)
        right_value = self._pointer_compare_value(right)
        lines.append(f"  {result} = icmp {predicate} ptr {left_value}, {right_value}")
        return _EmittedValue(result, IrBoolType())

    def _emit_equality_compare(
        self,
        left: _EmittedValue,
        right: _EmittedValue,
        *,
        negate: bool,
        lines: list[str],
    ) -> _EmittedValue:
        predicate = "ne" if negate else "eq"
        result = self._tmp("eq")
        if isinstance(left.type, IrIntType) and isinstance(right.type, IrIntType):
            lines.append(
                f"  {result} = icmp {predicate} {self._llvm_type(left.type)} "
                f"{left.value}, {right.value}"
            )
            return _EmittedValue(result, IrBoolType())
        if isinstance(left.type, IrBoolType) and isinstance(right.type, IrBoolType):
            lines.append(f"  {result} = icmp {predicate} i1 {left.value}, {right.value}")
            return _EmittedValue(result, IrBoolType())
        if isinstance(left.type, IrBytesType) and isinstance(right.type, IrBytesType):
            self.needs_runtime_prelude = True
            equal = self._tmp("byteseq")
            lines.append(
                f"  {equal} = call i1 @__xcc_aot_bytes_equal(ptr {left.value}, ptr {right.value})"
            )
            value = _EmittedValue(equal, IrBoolType())
            if negate:
                return self._emit_bool_not(value, lines)
            return value
        if _is_pointer_type(left.type) and isinstance(right.type, IrIntType):
            cast = self._tmp("ptrint")
            lines.append(f"  {cast} = ptrtoint ptr {self._pointer_compare_value(left)} to i64")
            lines.append(f"  {result} = icmp {predicate} i64 {cast}, {right.value}")
            return _EmittedValue(result, IrBoolType())
        if isinstance(left.type, IrIntType) and _is_pointer_type(right.type):
            cast = self._tmp("ptrint")
            lines.append(f"  {cast} = ptrtoint ptr {self._pointer_compare_value(right)} to i64")
            lines.append(f"  {result} = icmp {predicate} i64 {left.value}, {cast}")
            return _EmittedValue(result, IrBoolType())
        if (
            (isinstance(left.type, IrStringType) or isinstance(right.type, IrStringType))
            and _is_pointer_type(left.type)
            and _is_pointer_type(right.type)
        ):
            return self._emit_string_equality_compare(left, right, negate=negate, lines=lines)
        if _is_path_value_type(left.type) and _is_path_value_type(right.type):
            return self._emit_string_equality_compare(left, right, negate=negate, lines=lines)
        if isinstance(left.type, IrTupleType) and isinstance(right.type, IrTupleType):
            return self._emit_tuple_equality_compare(left, right, negate=negate, lines=lines)
        left_value = self._pointer_compare_value(left)
        right_value = self._pointer_compare_value(right)
        lines.append(f"  {result} = icmp {predicate} ptr {left_value}, {right_value}")
        return _EmittedValue(result, IrBoolType())

    def _emit_string_equality_compare(
        self,
        left: _EmittedValue,
        right: _EmittedValue,
        *,
        negate: bool,
        lines: list[str],
    ) -> _EmittedValue:
        self.needs_runtime_prelude = True
        left_value = self._pointer_compare_value(left)
        right_value = self._pointer_compare_value(right)
        same = self._tmp("streq.same")
        left_non_null = self._tmp("streq.left")
        right_non_null = self._tmp("streq.right")
        both_non_null = self._tmp("streq.both")
        compared = self._tmp("strcmp")
        string_equal = self._tmp("streq")
        result = self._tmp("eq")
        same_label = self._label("streq.same")
        distinct_label = self._label("streq.distinct")
        strcmp_label = self._label("streq.strcmp")
        null_label = self._label("streq.null")
        end_label = self._label("streq.end")
        lines.append(f"  {same} = icmp eq ptr {left_value}, {right_value}")
        lines.append(f"  br i1 {same}, label %{same_label}, label %{distinct_label}")
        lines.append(f"{same_label}:")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{distinct_label}:")
        lines.append(f"  {left_non_null} = icmp ne ptr {left_value}, null")
        lines.append(f"  {right_non_null} = icmp ne ptr {right_value}, null")
        lines.append(f"  {both_non_null} = and i1 {left_non_null}, {right_non_null}")
        lines.append(f"  br i1 {both_non_null}, label %{strcmp_label}, label %{null_label}")
        lines.append(f"{strcmp_label}:")
        lines.append(f"  {compared} = call i32 @strcmp(ptr {left_value}, ptr {right_value})")
        lines.append(f"  {string_equal} = icmp eq i32 {compared}, 0")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{null_label}:")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        lines.append(
            f"  {result} = phi i1 [ true, %{same_label} ], "
            f"[ {string_equal}, %{strcmp_label} ], [ false, %{null_label} ]"
        )
        if not negate:
            return _EmittedValue(result, IrBoolType())
        negated = self._tmp("eq")
        lines.append(f"  {negated} = xor i1 {result}, true")
        return _EmittedValue(negated, IrBoolType())

    def _emit_tuple_equality_compare(
        self,
        left: _EmittedValue,
        right: _EmittedValue,
        *,
        negate: bool,
        lines: list[str],
    ) -> _EmittedValue:
        if not isinstance(left.type, IrTupleType) or not isinstance(right.type, IrTupleType):
            self._error("tuple equality expects tuple operands")
        self.needs_runtime_prelude = True
        left_length = self._tmp("tupleeq.leftlen")
        right_length = self._tmp("tupleeq.rightlen")
        same_length = self._tmp("tupleeq.samelen")
        lines.append(f"  {left_length} = call i64 @__xcc_aot_tuple_len(ptr {left.value})")
        lines.append(f"  {right_length} = call i64 @__xcc_aot_tuple_len(ptr {right.value})")
        lines.append(f"  {same_length} = icmp eq i64 {left_length}, {right_length}")
        dynamic_type = self._tuple_equality_dynamic_item_type(left.type, right.type)
        if dynamic_type is not None:
            result = self._emit_dynamic_tuple_equality(
                left,
                right,
                dynamic_type,
                left_length,
                same_length,
                lines,
            )
        else:
            result = _EmittedValue(same_length, IrBoolType())
            if len(left.type.elements) != len(right.type.elements):
                result = _EmittedValue("false", IrBoolType())
            else:
                for index, (left_type, right_type) in enumerate(
                    zip(left.type.elements, right.type.elements, strict=True)
                ):
                    left_item = self._emit_runtime_tuple_get(
                        left.value,
                        index,
                        left_type,
                        lines,
                    )
                    right_item = self._emit_runtime_tuple_get(
                        right.value,
                        index,
                        right_type,
                        lines,
                    )
                    item_equal = self._emit_equality_compare(
                        left_item,
                        right_item,
                        negate=False,
                        lines=lines,
                    )
                    combined = self._tmp("tupleeq")
                    lines.append(f"  {combined} = and i1 {result.value}, {item_equal.value}")
                    result = _EmittedValue(combined, IrBoolType())
        if not negate:
            return result
        return self._emit_bool_not(result, lines)

    def _tuple_equality_dynamic_item_type(
        self,
        left: IrTupleType,
        right: IrTupleType,
    ) -> IrType | None:
        if len(left.elements) == 1 and len(right.elements) == 1:
            return left.elements[0]
        if len(left.elements) == 1:
            return left.elements[0]
        if len(right.elements) == 1:
            return right.elements[0]
        return None

    def _emit_dynamic_tuple_equality(
        self,
        left: _EmittedValue,
        right: _EmittedValue,
        item_type: IrType,
        length: str,
        same_length: str,
        lines: list[str],
    ) -> _EmittedValue:
        result_ptr = self._tmp("tupleeq.result")
        index_ptr = self._tmp("tupleeq.index")
        cond_label = self._label("tupleeq.cond")
        body_label = self._label("tupleeq.body")
        next_label = self._label("tupleeq.next")
        mismatch_label = self._label("tupleeq.mismatch")
        end_label = self._label("tupleeq.end")
        lines.append(f"  {result_ptr} = alloca i1")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i1 {same_length}, ptr {result_ptr}")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br i1 {same_length}, label %{cond_label}, label %{end_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("tupleeq.index")
        done = self._tmp("tupleeq.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        left_raw = self._tmp("tupleeq.left")
        right_raw = self._tmp("tupleeq.right")
        lines.append(f"  {left_raw} = call ptr @__xcc_aot_tuple_get(ptr {left.value}, i64 {index})")
        lines.append(
            f"  {right_raw} = call ptr @__xcc_aot_tuple_get(ptr {right.value}, i64 {index})"
        )
        left_item = self._emit_runtime_boxed_value(left_raw, item_type, lines)
        right_item = self._emit_runtime_boxed_value(right_raw, item_type, lines)
        item_equal = self._emit_equality_compare(
            left_item,
            right_item,
            negate=False,
            lines=lines,
        )
        lines.append(f"  br i1 {item_equal.value}, label %{next_label}, label %{mismatch_label}")
        lines.append(f"{mismatch_label}:")
        lines.append(f"  store i1 false, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("tupleeq.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("tupleeq")
        lines.append(f"  {result} = load i1, ptr {result_ptr}")
        return _EmittedValue(result, IrBoolType())

    def _emit_order_compare(
        self,
        target: str,
        left: _EmittedValue,
        right: _EmittedValue,
        lines: list[str],
    ) -> _EmittedValue:
        op = {
            "__cmp_Gt": "gt",
            "__cmp_GtE": "ge",
            "__cmp_Lt": "lt",
            "__cmp_LtE": "le",
        }[target]
        if _is_string_like_type(left.type) and _is_string_like_type(right.type):
            self.needs_runtime_prelude = True
            compared = self._tmp("strcmp")
            result = self._tmp("cmp")
            lines.append(
                f"  {compared} = call i32 @strcmp("
                f"ptr {self._pointer_compare_value(left)}, "
                f"ptr {self._pointer_compare_value(right)})"
            )
            lines.append(f"  {result} = icmp s{op} i32 {compared}, 0")
            return _EmittedValue(result, IrBoolType())
        if not isinstance(left.type, IrIntType) or not isinstance(right.type, IrIntType):
            self._error(f"{target} currently supports integer arguments")
        if left.type.bits != right.type.bits:
            self._error(f"{target} expects matching integer widths")
        prefix = "s" if left.type.signed else "u"
        result = self._tmp("cmp")
        lines.append(
            f"  {result} = icmp {prefix}{op} {self._llvm_type(left.type)} "
            f"{left.value}, {right.value}"
        )
        return _EmittedValue(result, IrBoolType())

    def _emit_str_slice_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__str_slice expects three arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        start = self._emit_expr(expr.args[1], names, lines)
        stop = self._emit_expr(expr.args[2], names, lines)
        if (
            not isinstance(value.type, IrStringType)
            or not isinstance(start.type, IrIntType)
            or not isinstance(stop.type, IrIntType)
            or not isinstance(expr.type, IrStringType)
        ):
            self._error("__str_slice expects (str, int, int) -> str")
        start_i64 = self._coerce_index_i64(start, lines, "__str_slice")
        stop_i64 = self._coerce_index_i64(stop, lines, "__str_slice")
        result = self._tmp("strslice")
        self.needs_runtime_prelude = True
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_slice("
            f"ptr {value.value}, i64 {start_i64}, i64 {stop_i64})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_bytes_slice_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__bytes_slice expects three arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        start = self._emit_expr(expr.args[1], names, lines)
        stop = self._emit_expr(expr.args[2], names, lines)
        if (
            not isinstance(value.type, IrBytesType)
            or not isinstance(start.type, IrIntType)
            or not isinstance(stop.type, IrIntType)
            or not isinstance(expr.type, IrBytesType)
        ):
            self._error("__bytes_slice expects (bytes, int, int) -> bytes")
        start_i64 = self._coerce_index_i64(start, lines, "__bytes_slice")
        stop_i64 = self._coerce_index_i64(stop, lines, "__bytes_slice")
        result = self._tmp("bytesslice")
        self.needs_runtime_prelude = True
        lines.append(
            f"  {result} = call ptr @__xcc_aot_bytes_slice("
            f"ptr {value.value}, i64 {start_i64}, i64 {stop_i64})"
        )
        return _EmittedValue(result, expr.type)

    def _pointer_compare_value(self, value: _EmittedValue) -> str:
        if isinstance(value.type, IrNoneType):
            return "null"
        if _is_pointer_type(value.type):
            return value.value
        self._error(f"Unsupported LLVM pointer comparison type: {type(value.type).__name__}")

    def _emit_aot_exec_argv_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrTupleType)
            or not isinstance(function.return_type, IrIntType)
            or function.return_type.bits != 32
        ):
            self._error("AOT exec argv helper expects tuple[str, ...] -> int32")
        param = function.params[0]
        return "\n".join(
            (
                f"define i32 {_llvm_symbol(function.name)}(ptr %{param.name}) {{",
                "entry:",
                f"  %exec = call i32 @__xcc_aot_execvp_tuple(ptr %{param.name})",
                "  ret i32 %exec",
                "}",
            )
        )

    def _emit_aot_write_text_file_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 2
            or not isinstance(function.params[0].type, IrStringType)
            or not isinstance(function.params[1].type, IrStringType)
            or not isinstance(function.return_type, IrBoolType)
        ):
            self._error("AOT write_text helper expects (str, str) -> bool")
        path = function.params[0]
        text = function.params[1]
        return "\n".join(
            (
                f"define i1 {_llvm_symbol(function.name)}(ptr %{path.name}, ptr %{text.name}) {{",
                "entry:",
                (
                    f"  %result = call i1 @__xcc_aot_write_text_file("
                    f"ptr %{path.name}, ptr %{text.name})"
                ),
                "  ret i1 %result",
                "}",
            )
        )

    def _emit_aot_read_text_file_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrStringType)
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error("AOT read_text helper expects str -> str")
        param = function.params[0]
        return "\n".join(
            (
                f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{",
                "entry:",
                f"  %result = call ptr @__xcc_aot_read_text_file(ptr %{param.name})",
                "  ret ptr %result",
                "}",
            )
        )

    def _emit_llvm_print_module_to_string_function(self, function: IrFunction) -> str:
        self.index = 0
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrIntType)
            or function.params[0].type.bits != 64
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error("LLVM module print helper expects int -> str")
        param = function.params[0]
        return "\n".join(
            (
                f"define ptr {_llvm_symbol(function.name)}(i64 %{param.name}) {{",
                "entry:",
                f"  %{param.name}.ptr = inttoptr i64 %{param.name} to ptr",
                f"  %result = call ptr @LLVMPrintModuleToString(ptr %{param.name}.ptr)",
                "  ret ptr %result",
                "}",
                "",
                "declare ptr @LLVMPrintModuleToString(ptr)",
            )
        )

    def _emit_llvm_ptr_array_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        self.extra_declarations.add("declare ptr @calloc(i64, i64)")
        if len(function.params) != 1:
            self._error("LLVM ptr_array helper expects one tuple-backed parameter")
        param = function.params[0]
        return "\n".join(
            (
                f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{",
                "entry:",
                f"  %len = call i64 @__xcc_aot_tuple_len(ptr %{param.name})",
                "  %is_empty = icmp eq i64 %len, 0",
                "  br i1 %is_empty, label %empty, label %alloc",
                "empty:",
                "  ret ptr null",
                "alloc:",
                "  %array = call ptr @calloc(i64 %len, i64 8)",
                "  br label %loop",
                "loop:",
                "  %index = phi i64 [ 0, %alloc ], [ %next, %body ]",
                "  %done = icmp uge i64 %index, %len",
                "  br i1 %done, label %end, label %body",
                "body:",
                f"  %item = call ptr @__xcc_aot_tuple_get(ptr %{param.name}, i64 %index)",
                "  %slot = getelementptr ptr, ptr %array, i64 %index",
                "  store ptr %item, ptr %slot",
                "  %next = add i64 %index, 1",
                "  br label %loop",
                "end:",
                "  ret ptr %array",
                "}",
            )
        )

    def _emit_llvm_zero_ptr_array_function(self, function: IrFunction) -> str:
        self.index = 0
        self.extra_declarations.add("declare ptr @calloc(i64, i64)")
        if len(function.params) != 1 or not isinstance(function.params[0].type, IrIntType):
            self._error("LLVM zero_ptr_array helper expects int -> pointer array")
        param = function.params[0]
        return "\n".join(
            (
                f"define ptr {_llvm_symbol(function.name)}(i64 %{param.name}) {{",
                "entry:",
                f"  %is_empty = icmp eq i64 %{param.name}, 0",
                "  br i1 %is_empty, label %empty, label %alloc",
                "empty:",
                "  ret ptr null",
                "alloc:",
                f"  %array = call ptr @calloc(i64 %{param.name}, i64 8)",
                "  ret ptr %array",
                "}",
            )
        )

    def _emit_llvm_optional_zero_ptr_array_function(self, function: IrFunction) -> str:
        self.index = 0
        self.extra_declarations.add("declare ptr @calloc(i64, i64)")
        if len(function.params) != 1 or not isinstance(function.params[0].type, IrIntType):
            self._error("LLVM optional_zero_ptr_array helper expects int -> optional pointer array")
        param = function.params[0]
        return "\n".join(
            (
                f"define ptr {_llvm_symbol(function.name)}(i64 %{param.name}) {{",
                "entry:",
                f"  %is_empty = icmp eq i64 %{param.name}, 0",
                "  br i1 %is_empty, label %empty, label %alloc",
                "empty:",
                "  ret ptr null",
                "alloc:",
                f"  %array = call ptr @calloc(i64 %{param.name}, i64 8)",
                "  ret ptr %array",
                "}",
            )
        )

    def _emit_core_lexer_string_helper_function(
        self,
        function: IrFunction,
        error: str,
        helper: str,
    ) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrStringType)
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error(error)
        param = function.params[0]
        lines = [
            f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{",
            "entry:",
            f"  %result = call ptr @{helper}(ptr %{param.name})",
            "  ret ptr %result",
            "}",
        ]
        return "\n".join(lines)

    def _emit_core_lexer_token_summary_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrStringType)
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error("core lexer token summary expects str -> str")
        param = function.params[0]
        lines = [
            f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{",
            "entry:",
            f"  %summary = call ptr @__xcc_aot_lexer_token_summary_for_source(ptr %{param.name})",
            "  ret ptr %summary",
            "}",
        ]
        return "\n".join(lines)

    def _emit_core_lexer_translate_source_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrStringType)
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error("core lexer.translate_source expects str -> str")
        param = function.params[0]
        lines = [
            f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{",
            "entry:",
            f"  %translated = call ptr @__xcc_aot_lexer_translate_source(ptr %{param.name})",
            "  ret ptr %translated",
            "}",
        ]
        return "\n".join(lines)

    def _emit_core_parser_error_str_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if (
            len(function.params) != 1
            or not isinstance(function.params[0].type, IrRecordType)
            or function.params[0].type.name != "ParserError"
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error("core ParserError.__str__ expects ParserError -> str")
        param = function.params[0]
        message_index = self._field_index("ParserError", "message")
        token_index = self._field_index("ParserError", "token")
        line_index = self._field_index("Token", "line")
        column_index = self._field_index("Token", "column")
        at = self._string_constant(" at ")
        colon = self._string_constant(":")
        lines = [f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{", "entry:"]
        message_ptr = self._tmp("fieldptr")
        message_value = self._tmp("load")
        token_ptr = self._tmp("fieldptr")
        token_value = self._tmp("load")
        line_ptr = self._tmp("fieldptr")
        line_value = self._tmp("load")
        column_ptr = self._tmp("fieldptr")
        column_value = self._tmp("load")
        line_string = self._tmp("itoa")
        column_string = self._tmp("itoa")
        first = self._tmp("concat")
        second = self._tmp("concat")
        third = self._tmp("concat")
        result = self._tmp("concat")
        lines.extend(
            (
                f"  {message_ptr} = getelementptr inbounds %ParserError, ptr %{param.name}, "
                f"i32 0, i32 {message_index}",
                f"  {message_value} = load ptr, ptr {message_ptr}",
                f"  {token_ptr} = getelementptr inbounds %ParserError, ptr %{param.name}, "
                f"i32 0, i32 {token_index}",
                f"  {token_value} = load ptr, ptr {token_ptr}",
                f"  {line_ptr} = getelementptr inbounds %Token, ptr {token_value}, "
                f"i32 0, i32 {line_index}",
                f"  {line_value} = load i64, ptr {line_ptr}",
                f"  {column_ptr} = getelementptr inbounds %Token, ptr {token_value}, "
                f"i32 0, i32 {column_index}",
                f"  {column_value} = load i64, ptr {column_ptr}",
                f"  {line_string} = call ptr @__xcc_aot_i64_to_string(i64 {line_value})",
                f"  {column_string} = call ptr @__xcc_aot_i64_to_string(i64 {column_value})",
                f"  {first} = call ptr @__xcc_aot_string_concat2(ptr {message_value}, ptr {at})",
                f"  {second} = call ptr @__xcc_aot_string_concat2(ptr {first}, ptr {line_string})",
                f"  {third} = call ptr @__xcc_aot_string_concat2(ptr {second}, ptr {colon})",
                f"  {result} = call ptr @__xcc_aot_string_concat2("
                f"ptr {third}, ptr {column_string})",
                f"  ret ptr {result}",
                "}",
            )
        )
        return "\n".join(lines)

    def _emit_core_constant_string_function(
        self,
        function: IrFunction,
        error: str,
        value: str,
    ) -> str:
        self.index = 0
        if function.params or not isinstance(function.return_type, IrStringType):
            self._error(error)
        constant = self._string_constant(value)
        return "\n".join(
            (
                f"define ptr {_llvm_symbol(function.name)}() {{",
                "entry:",
                f"  ret ptr {constant}",
                "}",
            )
        )

    def _emit_preprocessor_pragma_passthrough_function(self, function: IrFunction) -> str:
        self.index = 0
        if (
            len(function.params) != 2
            or not isinstance(function.params[0].type, IrRecordType)
            or function.params[0].type.name != "_Preprocessor"
            or not isinstance(function.params[1].type, IrStringType)
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error("preprocessor pragma passthrough expects (_Preprocessor, str) -> str")
        text = function.params[1]
        return "\n".join(
            (
                f"define ptr {_llvm_symbol(function.name)}(ptr %{function.params[0].name}, "
                f"ptr %{text.name}) {{",
                "entry:",
                f"  ret ptr %{text.name}",
                "}",
            )
        )

    def _emit_preprocessor_expand_line_passthrough_function(self, function: IrFunction) -> str:
        self.index = 0
        if (
            len(function.params) != 3
            or not isinstance(function.params[0].type, IrRecordType)
            or function.params[0].type.name != "_Preprocessor"
            or not isinstance(function.params[1].type, IrStringType)
            or not isinstance(function.return_type, IrStringType)
        ):
            self._error(
                "preprocessor expand-line passthrough expects (_Preprocessor, str, location) -> str"
            )
        line = function.params[1]
        return "\n".join(
            (
                f"define ptr {_llvm_symbol(function.name)}(ptr %{function.params[0].name}, "
                f"ptr %{line.name}, ptr %{function.params[2].name}) {{",
                "entry:",
                f"  ret ptr %{line.name}",
                "}",
            )
        )

    def _emit_preprocessor_void_noop_function(self, function: IrFunction) -> str:
        self.index = 0
        if (
            not function.params
            or not isinstance(function.params[0].type, IrRecordType)
            or function.params[0].type.name != "_Preprocessor"
            or not isinstance(function.return_type, IrNoneType)
        ):
            self._error("preprocessor void no-op leaf expects _Preprocessor receiver")
        params = ", ".join(f"ptr %{param.name}" for param in function.params)
        return "\n".join(
            (
                f"define void {_llvm_symbol(function.name)}({params}) {{",
                "entry:",
                "  ret void",
                "}",
            )
        )

    def _emit_preprocessor_no_macro_continuation_function(self, function: IrFunction) -> str:
        self.index = 0
        if (
            len(function.params) != 3
            or not isinstance(function.params[0].type, IrRecordType)
            or function.params[0].type.name != "_Preprocessor"
            or not isinstance(function.params[1].type, IrStringType)
            or not isinstance(function.params[2].type, IrStringType)
            or not isinstance(function.return_type, IrBoolType)
        ):
            self._error(
                "preprocessor macro-continuation leaf expects (_Preprocessor, str, str) -> bool"
            )
        return "\n".join(
            (
                f"define i1 {_llvm_symbol(function.name)}(ptr %{function.params[0].name}, "
                f"ptr %{function.params[1].name}, ptr %{function.params[2].name}) {{",
                "entry:",
                "  ret i1 false",
                "}",
            )
        )

    def _emit_core_type_str_function(self, function: IrFunction) -> str:
        self.index = 0
        self.needs_runtime_prelude = True
        if len(function.params) != 1:
            self._error("core Type.__str__ expects one parameter")
        param = function.params[0]
        name_index = self._field_index("Type", "name")
        ops_index = self._field_index("Type", "declarator_ops")
        empty = self._string_constant("")
        ptr_token = self._string_constant("ptr")
        star = self._string_constant("*")
        open_bracket = self._string_constant("[")
        close_bracket = self._string_constant("]")
        lines = [f"define ptr {_llvm_symbol(function.name)}(ptr %{param.name}) {{", "entry:"]
        name_ptr = self._tmp("fieldptr")
        name_value = self._tmp("load")
        ops_ptr = self._tmp("fieldptr")
        ops_value = self._tmp("load")
        ops_len = self._tmp("len")
        cond_label = self._label("type.cond")
        body_label = self._label("type.body")
        ptr_label = self._label("type.ptr")
        arr_label = self._label("type.arr")
        next_label = self._label("type.next")
        end_label = self._label("type.end")
        lines.extend(
            (
                f"  {name_ptr} = getelementptr inbounds %Type, ptr %{param.name}, "
                f"i32 0, i32 {name_index}",
                f"  {name_value} = load ptr, ptr {name_ptr}",
                f"  {ops_ptr} = getelementptr inbounds %Type, ptr %{param.name}, "
                f"i32 0, i32 {ops_index}",
                f"  {ops_value} = load ptr, ptr {ops_ptr}",
                f"  {ops_len} = call i64 @__xcc_aot_tuple_len(ptr {ops_value})",
                f"  br label %{cond_label}",
                f"{cond_label}:",
                f"  %type_idx = phi i64 [ {ops_len}, %entry ], [ %type_prev, %{next_label} ]",
                f"  %type_suffix = phi ptr [ {empty}, %entry ], [ %type_next, %{next_label} ]",
                "  %type_has_item = icmp ugt i64 %type_idx, 0",
                f"  br i1 %type_has_item, label %{body_label}, label %{end_label}",
                f"{body_label}:",
                "  %type_prev = sub i64 %type_idx, 1",
                f"  %type_op = call ptr @__xcc_aot_tuple_get(ptr {ops_value}, i64 %type_prev)",
                "  %type_kind = call ptr @__xcc_aot_tuple_get(ptr %type_op, i64 0)",
                f"  %type_cmp = call i32 @strcmp(ptr %type_kind, ptr {ptr_token})",
                "  %type_is_ptr = icmp eq i32 %type_cmp, 0",
                f"  br i1 %type_is_ptr, label %{ptr_label}, label %{arr_label}",
                f"{ptr_label}:",
                f"  %type_ptr_suffix = call ptr @__xcc_aot_string_concat2("
                f"ptr %type_suffix, ptr {star})",
                f"  br label %{next_label}",
                f"{arr_label}:",
                "  %type_length_ptr = call ptr @__xcc_aot_tuple_get(ptr %type_op, i64 1)",
                "  %type_length = ptrtoint ptr %type_length_ptr to i64",
                "  %type_length_text = call ptr @__xcc_aot_i64_to_string(i64 %type_length)",
                f"  %type_arr_open = call ptr @__xcc_aot_string_concat2("
                f"ptr {open_bracket}, ptr %type_length_text)",
                f"  %type_arr_text = call ptr @__xcc_aot_string_concat2("
                f"ptr %type_arr_open, ptr {close_bracket})",
                "  %type_arr_suffix = call ptr @__xcc_aot_string_concat2("
                "ptr %type_suffix, ptr %type_arr_text)",
                f"  br label %{next_label}",
                f"{next_label}:",
                f"  %type_next = phi ptr [ %type_ptr_suffix, %{ptr_label} ], "
                f"[ %type_arr_suffix, %{arr_label} ]",
                f"  br label %{cond_label}",
                f"{end_label}:",
                f"  %type_result = call ptr @__xcc_aot_string_concat2("
                f"ptr {name_value}, ptr %type_suffix)",
                "  ret ptr %type_result",
                "}",
            )
        )
        return "\n".join(lines)

    def _emit_main(self) -> str | None:
        if self.module.entry is None:
            return None
        function = self.functions[self.module.entry]
        return_type = function.return_type
        signature, args = self._main_signature_and_args(function)
        lines = [signature + " {", "entry:"]
        if self._main_uses_c_argv_bridge(function):
            self.needs_runtime_prelude = True
            lines.append(
                "  %argv_tuple = call ptr @__xcc_aot_c_argv_to_tuple(i32 %argc, ptr %argv)"
            )
            args = "i32 %argc, ptr %argv_tuple"
        result_type = self._llvm_type(return_type)
        if function.name in self.fallible_functions:
            return self._emit_fallible_main(function, signature, args)
        if isinstance(return_type, IrNoneType):
            lines.append(f"  call {result_type} {_llvm_symbol(function.name)}({args})")
            lines.append("  ret i32 0")
        else:
            lines.append(f"  %result = call {result_type} {_llvm_symbol(function.name)}({args})")
        if isinstance(return_type, IrStringType):
            self.needs_puts = True
            lines.append("  %printed = call i32 @puts(ptr %result)")
            lines.append("  ret i32 0")
        elif isinstance(return_type, IrBytesType):
            self._emit_main_bytes_result(lines)
        elif isinstance(return_type, IrIntType):
            if return_type.bits == 32:
                lines.append("  ret i32 %result")
            else:
                lines.append(f"  %exit = trunc {result_type} %result to i32")
                lines.append("  ret i32 %exit")
        elif isinstance(return_type, IrBoolType):
            lines.append("  %exit = zext i1 %result to i32")
            lines.append("  ret i32 %exit")
        elif isinstance(return_type, IrNoneType):
            pass
        else:
            self._error(f"Unsupported main return type: {type(return_type).__name__}")
        lines.append("}")
        return "\n".join(lines)

    def _emit_fallible_main(
        self,
        function: IrFunction,
        signature: str,
        args: str,
    ) -> str:
        return_type = function.return_type
        lines = [signature + " {", "entry:"]
        if self._main_uses_c_argv_bridge(function):
            self.needs_runtime_prelude = True
            lines.append(
                "  %argv_tuple = call ptr @__xcc_aot_c_argv_to_tuple(i32 %argc, ptr %argv)"
            )
            args = "i32 %argc, ptr %argv_tuple"
        lines.append(f"  %error_record = alloca {_ERROR_LLVM_TYPE}")
        lines.append(f"  store {_ERROR_LLVM_TYPE} zeroinitializer, ptr %error_record")
        call_args = [] if not args else [args]
        if not isinstance(return_type, IrNoneType):
            lines.append(f"  %result_out = alloca {self._storage_llvm_type(return_type)}")
            call_args.append("ptr %result_out")
        call_args.append("ptr %error_record")
        lines.append(f"  %status = call i32 {_llvm_symbol(function.name)}({', '.join(call_args)})")
        lines.append("  %failed = icmp ne i32 %status, 0")
        lines.append("  br i1 %failed, label %uncaught, label %success")
        lines.append("uncaught:")
        self._emit_main_error_diagnostic(lines, "error")
        lines.append("  ret i32 %status")
        lines.append("success:")
        report_preserved_error = (
            function.name == "aot_bootstrap_smoke_main"
            and isinstance(return_type, IrIntType)
            and return_type.bits == 32
        )
        if isinstance(return_type, IrNoneType):
            lines.append("  ret i32 0")
        else:
            result_type = self._llvm_type(return_type)
            lines.append(f"  %result = load {result_type}, ptr %result_out")
            if report_preserved_error:
                lines.append("  %result_failed = icmp ne i32 %result, 0")
                lines.append(
                    f"  %preserved.type.ptr = getelementptr inbounds {_ERROR_LLVM_TYPE}, "
                    "ptr %error_record, i32 0, i32 0"
                )
                lines.append("  %preserved.type = load ptr, ptr %preserved.type.ptr")
                lines.append("  %has_preserved_error = icmp ne ptr %preserved.type, null")
                lines.append(
                    "  %report_preserved_error = and i1 %result_failed, %has_preserved_error"
                )
                lines.append(
                    "  br i1 %report_preserved_error, label %caught_error, label %success_return"
                )
                lines.append("caught_error:")
                self._emit_main_error_diagnostic(lines, "caught.error")
                lines.append("  ret i32 %result")
                lines.append("success_return:")
            if isinstance(return_type, IrStringType):
                self.needs_puts = True
                lines.append("  %printed = call i32 @puts(ptr %result)")
                lines.append("  ret i32 0")
            elif isinstance(return_type, IrBytesType):
                self._emit_main_bytes_result(lines)
            elif isinstance(return_type, IrIntType):
                if return_type.bits == 32:
                    lines.append("  ret i32 %result")
                else:
                    lines.append(f"  %exit = trunc {result_type} %result to i32")
                    lines.append("  ret i32 %exit")
            elif isinstance(return_type, IrBoolType):
                lines.append("  %exit = zext i1 %result to i32")
                lines.append("  ret i32 %exit")
            else:
                self._error(f"Unsupported main return type: {type(return_type).__name__}")
        lines.append("}")
        return "\n".join(lines)

    def _emit_main_error_diagnostic(self, lines: list[str], prefix: str) -> None:
        error_values = (
            ("type", "ptr", 0),
            ("message", "ptr", 1),
            ("filename", "ptr", 2),
            ("line", "i32", 3),
            ("column", "i32", 4),
        )
        for name, llvm_type, index in error_values:
            lines.append(
                f"  %{prefix}.{name}.ptr = getelementptr inbounds {_ERROR_LLVM_TYPE}, "
                f"ptr %error_record, i32 0, i32 {index}"
            )
            lines.append(f"  %{prefix}.{name} = load {llvm_type}, ptr %{prefix}.{name}.ptr")
        diagnostic_format = self._string_constant("%s:%d:%d: %s: %s\n")
        self.extra_declarations.add("declare i32 @dprintf(i32, ptr, ...)")
        lines.append(
            f"  %{prefix}.diagnostic = call i32 (i32, ptr, ...) @dprintf("
            f"i32 2, ptr {diagnostic_format}, ptr %{prefix}.filename, "
            f"i32 %{prefix}.line, i32 %{prefix}.column, "
            f"ptr %{prefix}.type, ptr %{prefix}.message)"
        )

    def _emit_main_bytes_result(self, lines: list[str]) -> None:
        self.needs_runtime_prelude = True
        self.extra_declarations.add("declare i64 @write(i32, ptr, i64)")
        newline = self._string_constant("\n")
        lines.append("  %result.data = call ptr @__xcc_aot_bytes_data(ptr %result)")
        lines.append("  %result.length = call i64 @__xcc_aot_bytes_len(ptr %result)")
        lines.append(
            "  %result.written = call i64 @write(i32 1, ptr %result.data, i64 %result.length)"
        )
        lines.append(f"  %newline.written = call i64 @write(i32 1, ptr {newline}, i64 1)")
        lines.append("  ret i32 0")

    def _main_signature_and_args(self, function: IrFunction) -> tuple[str, str]:
        if not function.params:
            return "define i32 @main()", ""
        if self._main_uses_c_argv_bridge(function):
            return "define i32 @main(i32 %argc, ptr %argv)", "i32 %argc, ptr %argv"
        args = ", ".join(
            f"{self._param_llvm_type(param.type)} {self._default_value(param.type)}"
            for param in function.params
        )
        return "define i32 @main()", args

    def _main_uses_c_argv_bridge(self, function: IrFunction) -> bool:
        return (
            len(function.params) == 2
            and function.params[0].name == "argc"
            and isinstance(function.params[0].type, IrIntType)
            and function.params[0].type.bits == 32
            and function.params[1].name == "argv"
            and isinstance(function.params[1].type, IrTupleType)
        )

    def _emit_error_record(
        self,
        statement: IrRaise,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> None:
        if self.current_error_out is None:
            self._error("error record emission requires error_out")
        message = self._emit_expr(statement.message, names, lines)
        if not isinstance(message.type, IrStringType):
            self._error("raise message must lower to a string")
        payload = (
            self._box_to_runtime_ptr(self._emit_expr(statement.payload, names, lines), lines)
            if statement.payload is not None
            else "null"
        )
        values = (
            ("type", "ptr", self._string_constant(statement.exception)),
            ("message", "ptr", message.value),
            ("filename", "ptr", self._string_constant(self.module.filename)),
            ("line", "i32", str(statement.span.line or 0)),
            ("column", "i32", str(statement.span.column or 0)),
            ("endline", "i32", str(statement.span.end_line or 0)),
            ("endcolumn", "i32", str(statement.span.end_column or 0)),
            ("payload", "ptr", payload),
        )
        for index, (name, llvm_type, value) in enumerate(values):
            field_ptr = self._tmp(f"error{name}")
            lines.append(
                f"  {field_ptr} = getelementptr inbounds {_ERROR_LLVM_TYPE}, "
                f"ptr {self.current_error_out}, i32 0, i32 {index}"
            )
            lines.append(f"  store {llvm_type} {value}, ptr {field_ptr}")

    def _emit_default_return(self, lines: list[str], return_type: IrType) -> None:
        if self.current_function_is_fallible:
            if not isinstance(return_type, IrNoneType):
                if self.current_result_out is None:
                    self._error("fallible non-void function is missing result_out")
                lines.append(
                    f"  store {self._storage_llvm_type(return_type)} "
                    f"{self._default_value(return_type)}, ptr {self.current_result_out}"
                )
            lines.append("  ret i32 0")
            return
        if isinstance(return_type, IrNoneType):
            lines.append("  ret void")
            return
        if isinstance(return_type, IrIntType):
            lines.append(f"  ret {self._llvm_type(return_type)} 0")
            return
        if isinstance(return_type, IrBoolType):
            lines.append("  ret i1 false")
            return
        if isinstance(
            return_type,
            (IrBytesType, IrDictType, IrRecordType, IrStringType, IrTupleType),
        ):
            lines.append(f"  ret {self._llvm_type(return_type)} null")
            return
        self._error(f"Unsupported default return type: {type(return_type).__name__}")

    def _default_value(self, type_info: IrType) -> str:
        if isinstance(type_info, IrBoolType):
            return "false"
        if isinstance(type_info, IrFloatType):
            return "0.0"
        if isinstance(type_info, IrIntType):
            return "0"
        if isinstance(
            type_info,
            (IrBytesType, IrDictType, IrNoneType, IrRecordType, IrStringType, IrTupleType),
        ):
            return "null"
        self._error(f"Unsupported default value type: {type(type_info).__name__}")

    def _value_for_result_type(
        self,
        value: _EmittedValue,
        result_type: IrType,
        lines: list[str] | None = None,
    ) -> str:
        if value.type == result_type:
            return value.value
        if isinstance(value.type, IrNoneType):
            return self._default_value(result_type)
        if _is_pointer_type(value.type) and _is_pointer_type(result_type):
            return value.value
        if lines is not None and _is_pointer_type(result_type):
            return self._box_to_runtime_ptr(value, lines)
        self._error(f"Cannot store {type(value.type).__name__} as {type(result_type).__name__}")

    def _string_constant(self, value: str) -> str:
        escaped = _escape_c_string(value)
        name = f"@.str{self.string_index}"
        self.string_index += 1
        size = len(value.encode("utf-8")) + 1
        self.string_constants.append(
            f'{name} = private unnamed_addr constant [{size} x i8] c"{escaped}\\00", align 1'
        )
        return name

    def _bytes_constant(self, value: bytes) -> str:
        name = f"@.bytes{self.string_index}"
        self.string_index += 1
        storage = value if value else b"\x00"
        self.string_constants.append(
            f"{name} = private unnamed_addr constant [{len(storage)} x i8] "
            f'c"{_escape_bytes(storage)}", align 1'
        )
        return name

    def _enum_constant(self, value: IrEnumMember) -> str:
        key = (value.enum, value.member)
        existing = self.enum_constants.get(key)
        if existing is not None:
            return existing
        rendered = f"{value.enum}.{value.member}"
        escaped = _escape_c_string(rendered)
        name = f"@.enum{len(self.enum_constants)}"
        size = len(rendered.encode("utf-8")) + 1
        self.enum_constants[key] = name
        self.string_constants.append(
            f'{name} = private unnamed_addr constant [{size} x i8] c"{escaped}\\00", align 1'
        )
        return name

    def _emit_type_constant_name(
        self,
        expr: IrName,
        lines: list[str],
    ) -> _EmittedValue | None:
        if (
            not isinstance(expr.type, IrRecordType)
            or expr.type.name != "Type"
            or "Type" not in self.records
        ):
            return None
        type_name = _TYPE_CONSTANTS.get(expr.name)
        if type_name is None:
            return None
        global_name = self._type_constant_global(expr.name, type_name)
        result = self._tmp(f"type.{expr.name.lower()}")
        lines.append(
            f"  {result} = getelementptr inbounds {{ i64, %Type }}, ptr {global_name}, i32 0, i32 1"
        )
        return _EmittedValue(result, expr.type)

    def _type_constant_global(self, constant_name: str, type_name: str) -> str:
        tuple_name = "@__xcc_aot_empty_tuple"
        if tuple_name not in self.global_constants:
            self.global_constants[tuple_name] = f"{tuple_name} = private global [1 x i64] [i64 0]"
        global_name = f"@__xcc_aot_type_{constant_name}"
        if global_name in self.global_constants:
            return global_name
        name_constant = self._string_constant(type_name)
        type_id = self.record_type_ids["Type"]
        self.global_constants[global_name] = (
            f"{global_name} = private global {{ i64, %Type }} "
            f"{{ i64 {type_id}, %Type {{ ptr {name_constant}, i64 0, "
            f"ptr {tuple_name}, ptr {tuple_name}, ptr {tuple_name} }} }}"
        )
        return global_name

    def _field_index(self, record_name: str, field: str) -> int:
        record = self.records[record_name]
        for index, candidate in enumerate(record.fields):
            if candidate.name == field:
                return index
        self._error(f"Unknown LLVM record field: {record_name}.{field}")

    def _field_record_name(self, record_name: str, field: str) -> str:
        alias = _PROTOCOL_RECORD_ALIASES.get(record_name)
        if alias is not None:
            record = self.records.get(alias)
            if record is not None and any(candidate.name == field for candidate in record.fields):
                return alias
        if record_name in self.records:
            return record_name
        for part in _record_union_parts(record_name):
            record = self.records.get(part)
            if record is not None and any(candidate.name == field for candidate in record.fields):
                return part
        self._error(f"Unknown LLVM record field: {record_name}.{field}")

    def _llvm_type(self, type_info: IrType) -> str:
        if isinstance(type_info, IrIntType):
            return f"i{type_info.bits}"
        if isinstance(type_info, IrBoolType):
            return "i1"
        if isinstance(type_info, IrFloatType):
            return "double"
        if isinstance(type_info, IrStringType):
            return "ptr"
        if isinstance(type_info, IrBytesType):
            return "ptr"
        if isinstance(type_info, IrRecordType):
            return "ptr"
        if isinstance(type_info, IrTupleType):
            return "ptr"
        if isinstance(type_info, IrDictType):
            return "ptr"
        if isinstance(type_info, IrNoneType):
            return "void"
        self._error(f"Unsupported LLVM type: {type(type_info).__name__}")

    def _storage_llvm_type(self, type_info: IrType) -> str:
        if isinstance(type_info, IrNoneType):
            return "ptr"
        return self._llvm_type(type_info)

    def _param_llvm_type(self, type_info: IrType) -> str:
        if isinstance(type_info, IrRecordType):
            return "ptr"
        if isinstance(type_info, IrNoneType):
            return "ptr"
        return self._llvm_type(type_info)

    def _tmp(self, prefix: str) -> str:
        self.index += 1
        return f"%{prefix}{self.index}"

    def _label(self, prefix: str) -> str:
        self.index += 1
        return f"{prefix}{self.index}"

    def _error(self, message: str) -> NoReturn:
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-LLVM-0001",
                    message,
                    filename=self.module.filename,
                ),
            )
        )


def _escape_c_string(value: str) -> str:
    return _escape_bytes(value.encode("utf-8"))


def _escape_bytes(value: bytes) -> str:
    chunks: list[str] = []
    for byte in value:
        if byte == 34:
            chunks.append("\\22")
        elif byte == 92:
            chunks.append("\\5C")
        elif 32 <= byte <= 126:
            chunks.append(chr(byte))
        else:
            chunks.append(f"\\{byte:02X}")
    return "".join(chunks)


def _llvm_symbol(name: str) -> str:
    if name and all(ch.isalnum() or ch in "$._-" for ch in name):
        return f"@{name}"
    escaped = name.replace("\\", "\\5C").replace('"', "\\22")
    return f'@"{escaped}"'


def _is_pointer_type(type_info: IrType) -> bool:
    return isinstance(
        type_info,
        IrBytesType | IrDictType | IrNoneType | IrRecordType | IrStringType | IrTupleType,
    )


def _homogeneous_tuple_element_type(type_info: IrType) -> IrType | None:
    if not isinstance(type_info, IrTupleType) or not type_info.elements:
        return None
    first = type_info.elements[0]
    for element in type_info.elements[1:]:
        if element != first:
            return None
    return first


def _is_tuple_mutating_method(target: str) -> bool:
    return target.endswith((".add", ".append", ".extend", ".pop"))


def _is_string_like_type(type_info: IrType) -> bool:
    return isinstance(type_info, IrStringType) or (
        isinstance(type_info, IrRecordType) and type_info.name in {"object", "str | None"}
    )


def _is_path_value_type(type_info: IrType) -> bool:
    return isinstance(type_info, IrRecordType) and type_info.name in {"Path", "Path | None"}


def _is_len_string_type(type_info: IrType) -> bool:
    return isinstance(type_info, IrStringType) or (
        isinstance(type_info, IrRecordType) and type_info.name == "str | None"
    )


def _is_record_narrowing(bound_type: IrType, requested_type: IrType) -> bool:
    if not isinstance(bound_type, IrRecordType) or not isinstance(requested_type, IrRecordType):
        return False
    return requested_type.name in bound_type.name.split(" | ")


def _is_known_record_union_name(record_name: str, records: dict[str, IrRecord]) -> bool:
    parts = _record_union_parts(record_name)
    return len(parts) > 1 and all(part in records for part in parts)


def _record_union_parts(record_name: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in record_name.split("|") if part.strip())


def _record_union_can_runtime_narrow(record_name: str, requested_type: IrType) -> bool:
    parts = _record_union_parts(record_name)
    if len(parts) < 2:
        return False
    if isinstance(requested_type, IrIntType):
        return "int" in parts
    if isinstance(requested_type, IrStringType):
        return "str" in parts
    if isinstance(requested_type, IrBytesType):
        return "bytes" in parts
    if isinstance(requested_type, IrTupleType):
        return any(_record_union_part_is_tuple_runtime(part) for part in parts)
    return False


def _record_union_part_is_tuple_runtime(part: str) -> bool:
    return part in {
        "DeclaratorOp",
        "FunctionDeclarator",
        "FunctionParams",
        "TypeOp",
    } or part.startswith(
        (
            "Iterable[",
            "Sequence[",
            "dict[",
            "frozenset[",
            "list[",
            "set[",
            "tuple[",
        )
    )


def _is_type_marker_name(name: str) -> bool:
    return name in _BUILTIN_VALUE_NAMES or (name[:1].isupper() and name.isidentifier())


def _record_constructor_type_base_name(type_info: IrType) -> str | None:
    if not isinstance(type_info, IrRecordType):
        return None
    name = type_info.name
    if not name.startswith("type[") or not name.endswith("]"):
        return None
    return name[5:-1]


def _record_allocation_size(record: IrRecord) -> int:
    return 8 + max(8, len(record.fields) * 8)


def _format_float_literal(value: float) -> str:
    rendered = repr(value)
    return rendered if "." in rendered or "e" in rendered.lower() else f"{rendered}.0"


def _block_is_terminated(lines: list[str]) -> bool:
    if not lines:
        return False
    return lines[-1].strip().startswith(("ret ", "br "))


def _current_label(lines: list[str]) -> str:
    for line in reversed(lines):
        if line.endswith(":"):
            return line[:-1]
    return "entry"


def _for_each_targets(target: str) -> tuple[str, ...]:
    return tuple(name for name in _for_each_target_slots(target) if name is not None)


def _for_each_target_slots(target: str) -> tuple[str | None, ...]:
    stripped = target.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1]
    slots = tuple(
        None if part.strip() == "_" else part.strip()
        for part in stripped.split(",")
        if part.strip()
    )
    return slots or (target,)


def _branch_assigned_names(branch: IrBranch) -> tuple[str, ...]:
    names: set[str] = set()
    for statement in branch.statements:
        names.update(_statement_assigned_names(statement))
    return tuple(sorted(names))


def _branch_assignment_types(branch: IrBranch) -> dict[str, tuple[IrType, ...]]:
    assignments: dict[str, list[IrType]] = {}
    for statement in branch.statements:
        for name, types in _statement_assignment_types(statement).items():
            assignments.setdefault(name, []).extend(types)
    return {name: tuple(types) for name, types in assignments.items()}


def _statement_assignment_types(statement: IrStmt) -> dict[str, tuple[IrType, ...]]:
    if isinstance(statement, IrAssign):
        if statement.target == "__expr":
            return {}
        if "," in statement.target:
            targets = _for_each_targets(statement.target)
            if isinstance(statement.value.type, IrTupleType) and len(
                statement.value.type.elements
            ) == len(targets):
                return {
                    name: (type_info,)
                    for name, type_info in zip(targets, statement.value.type.elements, strict=True)
                }
            return {name: (IrRecordType("object"),) for name in targets}
        return {statement.target: (statement.value.type,)}
    if isinstance(statement, IrSetItem):
        return {}
    if isinstance(statement, IrIf):
        assignments = _branch_assignment_types(statement.then_branch)
        if statement.else_branch is not None:
            assignments = _merge_assignment_types(
                assignments,
                _branch_assignment_types(statement.else_branch),
            )
        return assignments
    if isinstance(statement, IrForEach):
        return _branch_assignment_types(statement.body)
    if isinstance(statement, IrWhile):
        return _branch_assignment_types(statement.body)
    if isinstance(statement, IrTry):
        assignments = _branch_assignment_types(statement.body)
        assignments = _merge_assignment_types(
            assignments,
            _branch_assignment_types(statement.orelse),
        )
        assignments = _merge_assignment_types(
            assignments,
            _branch_assignment_types(statement.finalbody),
        )
        for handler in statement.handlers:
            assignments = _merge_assignment_types(
                assignments,
                _branch_assignment_types(handler.body),
            )
        return assignments
    return {}


def _merge_assignment_types(
    left: dict[str, tuple[IrType, ...]],
    right: dict[str, tuple[IrType, ...]],
) -> dict[str, tuple[IrType, ...]]:
    merged = dict(left)
    for name, types in right.items():
        merged[name] = merged.get(name, ()) + types
    return merged


def _statement_assigned_names(statement: IrStmt) -> tuple[str, ...]:
    if isinstance(statement, IrAssign):
        if statement.target == "__expr":
            return ()
        if "," in statement.target:
            return _for_each_targets(statement.target)
        return (statement.target,)
    if isinstance(statement, IrSetItem):
        return ()
    if isinstance(statement, IrIf):
        names = set(_branch_assigned_names(statement.then_branch))
        if statement.else_branch is not None:
            names.update(_branch_assigned_names(statement.else_branch))
        return tuple(sorted(names))
    if isinstance(statement, IrForEach):
        names = set(_for_each_targets(statement.target))
        names.update(_branch_assigned_names(statement.body))
        return tuple(sorted(names))
    if isinstance(statement, IrWhile):
        return _branch_assigned_names(statement.body)
    if isinstance(statement, IrTry):
        names = set(_branch_assigned_names(statement.body))
        names.update(_branch_assigned_names(statement.orelse))
        names.update(_branch_assigned_names(statement.finalbody))
        for handler in statement.handlers:
            names.update(_branch_assigned_names(handler.body))
        return tuple(sorted(names))
    return ()


def _bind_emitted_target(
    target: str,
    value: _EmittedValue,
    names: dict[str, _EmittedValue],
) -> None:
    targets = _for_each_targets(target) if "," in target else (target,)
    for name in targets:
        names[name] = value
