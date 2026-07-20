from dataclasses import dataclass
from typing import NoReturn

from xcc.aot.core_runtime import guard_allocation_calls, runtime_prelude
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

_BUILTIN_TYPE_MARKER_NAMES = frozenset(
    {
        "bool",
        "bytes",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "object",
        "set",
        "str",
        "tuple",
        "type",
    }
)
_BUILTIN_VALUE_NAMES = {"Ellipsis", *_BUILTIN_TYPE_MARKER_NAMES}
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
    "__str_isidentifier": 5,
    "__str_isupper": 6,
}
_OBJECT_TAG_BOOL = 1
_OBJECT_TAG_INT = 2
_OBJECT_TAG_FLOAT = 3
_OBJECT_TAG_STRING = 4
_OBJECT_TAG_BYTES = 5
_OBJECT_TAG_COMPLEX = 6
_OBJECT_TAG_ELLIPSIS = 7
_OBJECT_TAG_RECORD = 8
_OBJECT_TAG_TUPLE = 9
_OBJECT_TAG_DICT = 10
_TYPE_TAG_NONE = 0
_TYPE_TAG_RECORD_BASE = 1_000_000
_NORETURN_CALL_PREFIX = "__noreturn__:"
_RECORD_INIT_PREFIX = "__record_init__:"
_EXACT_BUILTIN_TYPE_TAGS = {
    "bool": _OBJECT_TAG_BOOL,
    "bytes": _OBJECT_TAG_BYTES,
    "complex": _OBJECT_TAG_COMPLEX,
    "dict": _OBJECT_TAG_DICT,
    "float": _OBJECT_TAG_FLOAT,
    "int": _OBJECT_TAG_INT,
    "str": _OBJECT_TAG_STRING,
}
_OBJECT_BUILTIN_TAGS = {
    "bool": (_OBJECT_TAG_BOOL,),
    "bytes": (_OBJECT_TAG_BYTES,),
    "dict": (_OBJECT_TAG_DICT,),
    "float": (_OBJECT_TAG_FLOAT,),
    "frozenset": (_OBJECT_TAG_TUPLE,),
    "int": (_OBJECT_TAG_BOOL, _OBJECT_TAG_INT),
    "list": (_OBJECT_TAG_TUPLE,),
    "set": (_OBJECT_TAG_TUPLE,),
    "str": (_OBJECT_TAG_STRING,),
    "tuple": (_OBJECT_TAG_TUPLE,),
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

_TUPLE_BORROWING_CALLS = frozenset(
    {
        "__contains",
        "__getitem",
        "__len",
        "__tuple_concat",
        "__tuple_repeat",
        "len",
    }
)


def _tuple_names_in_expr(expr: IrExpr) -> set[str]:
    if isinstance(expr, IrName):
        if isinstance(expr.type, IrTupleType):
            return {expr.name}
        return set()
    if isinstance(expr, IrBinary):
        return _tuple_names_in_expr(expr.left) | _tuple_names_in_expr(expr.right)
    if isinstance(expr, IrGetField):
        return _tuple_names_in_expr(expr.value)
    if isinstance(expr, IrConstructRecord | IrCall):
        names: set[str] = set()
        for arg in expr.args:
            names.update(_tuple_names_in_expr(arg))
        return names
    if isinstance(expr, IrTuple):
        names = set()
        for element in expr.elements:
            names.update(_tuple_names_in_expr(element))
        return names
    if isinstance(expr, IrTupleSlice):
        names = _tuple_names_in_expr(expr.value)
        if expr.start is not None:
            names.update(_tuple_names_in_expr(expr.start))
        if expr.stop is not None:
            names.update(_tuple_names_in_expr(expr.stop))
        return names
    if isinstance(expr, IrStringConcat):
        names = set()
        for part in expr.parts:
            names.update(_tuple_names_in_expr(part))
        return names
    if isinstance(expr, IrStringJoin):
        return _tuple_names_in_expr(expr.separator) | _tuple_names_in_expr(expr.values)
    return set()


def _escaped_tuple_names(expr: IrExpr) -> set[str]:
    if isinstance(expr, IrBinary):
        return _escaped_tuple_names(expr.left) | _escaped_tuple_names(expr.right)
    if isinstance(expr, IrGetField):
        return _escaped_tuple_names(expr.value)
    if isinstance(expr, IrConstructRecord):
        return _tuple_names_in_expr(expr)
    if isinstance(expr, IrCall):
        escaped: set[str] = set()
        for arg in expr.args:
            escaped.update(_escaped_tuple_names(arg))
        if expr.target not in _TUPLE_BORROWING_CALLS:
            for arg in expr.args:
                escaped.update(_tuple_names_in_expr(arg))
        return escaped
    if isinstance(expr, IrTuple):
        return _tuple_names_in_expr(expr)
    if isinstance(expr, IrTupleSlice):
        escaped = _escaped_tuple_names(expr.value)
        if expr.start is not None:
            escaped.update(_escaped_tuple_names(expr.start))
        if expr.stop is not None:
            escaped.update(_escaped_tuple_names(expr.stop))
        return escaped
    if isinstance(expr, IrStringConcat):
        escaped = set()
        for part in expr.parts:
            escaped.update(_escaped_tuple_names(part))
        return escaped
    if isinstance(expr, IrStringJoin):
        return _escaped_tuple_names(expr.separator) | _escaped_tuple_names(expr.values)
    return set()


def _plain_assignment_target(target: str) -> bool:
    return "," not in target and "." not in target and "[" not in target


def _assignment_target_names(target: str) -> set[str]:
    if _plain_assignment_target(target):
        return {target}
    return {part.strip() for part in target.split(",") if part.strip()}


def _owned_tuple_rebind(statement: IrAssign, unique: set[str]) -> bool:
    if not _plain_assignment_target(statement.target) or statement.target not in unique:
        return False
    value = statement.value
    if not isinstance(value, IrCall) or value.target != "__tuple_concat":
        return False
    if len(value.args) != 2 or not isinstance(value.type, IrTupleType):
        return False
    if len(value.type.elements) != 1:
        return False
    left, right = value.args
    if not isinstance(left, IrName) or left.name != statement.target:
        return False
    return isinstance(right, IrTuple) and statement.target not in _tuple_names_in_expr(right)


def _analyze_owned_tuple_loop(
    body: IrBranch,
    incoming: set[str],
    target_names: set[str],
    owned_rebinds: set[int],
    *,
    record: bool,
) -> set[str]:
    entry = incoming - target_names
    invariant = set(entry)
    while True:
        body_out = _analyze_owned_tuple_block(body.statements, invariant, set(), record=False)
        narrowed = entry & body_out
        if narrowed == invariant:
            break
        invariant = narrowed
    body_out = _analyze_owned_tuple_block(
        body.statements,
        invariant,
        owned_rebinds,
        record=record,
    )
    return entry & body_out


def _analyze_owned_tuple_block(
    statements: tuple[IrStmt, ...],
    incoming: set[str],
    owned_rebinds: set[int],
    *,
    record: bool,
) -> set[str]:
    unique = set(incoming)
    for statement in statements:
        if isinstance(statement, IrAssign):
            if _owned_tuple_rebind(statement, unique):
                value = statement.value
                if isinstance(value, IrCall):
                    unique.difference_update(_tuple_names_in_expr(value.args[1]))
                if record:
                    owned_rebinds.add(id(statement))
                continue
            unique.difference_update(_escaped_tuple_names(statement.value))
            if isinstance(statement.value, IrName) and isinstance(
                statement.value.type,
                IrTupleType,
            ):
                unique.discard(statement.value.name)
            unique.difference_update(_assignment_target_names(statement.target))
            if (
                _plain_assignment_target(statement.target)
                and isinstance(statement.value, IrTuple)
                and isinstance(statement.value.type, IrTupleType)
            ):
                unique.add(statement.target)
            continue
        if isinstance(statement, IrIf):
            unique.difference_update(_escaped_tuple_names(statement.condition))
            then_unique = _analyze_owned_tuple_block(
                statement.then_branch.statements,
                unique,
                owned_rebinds,
                record=record,
            )
            else_unique = set(unique)
            if statement.else_branch is not None:
                else_unique = _analyze_owned_tuple_block(
                    statement.else_branch.statements,
                    unique,
                    owned_rebinds,
                    record=record,
                )
            unique = then_unique & else_unique
            continue
        if isinstance(statement, IrForEach):
            unique.difference_update(_escaped_tuple_names(statement.iterable))
            unique = _analyze_owned_tuple_loop(
                statement.body,
                unique,
                _assignment_target_names(statement.target),
                owned_rebinds,
                record=record,
            )
            continue
        if isinstance(statement, IrWhile):
            unique.difference_update(_escaped_tuple_names(statement.condition))
            unique = _analyze_owned_tuple_loop(
                statement.body,
                unique,
                set(),
                owned_rebinds,
                record=record,
            )
            continue
        if isinstance(statement, IrSetItem):
            unique.difference_update(_tuple_names_in_expr(statement.value))
            unique.difference_update(_escaped_tuple_names(statement.target))
            unique.difference_update(_escaped_tuple_names(statement.index))
            continue
        if isinstance(statement, IrReturn):
            unique.difference_update(_tuple_names_in_expr(statement.value))
            continue
        if isinstance(statement, IrTry | IrRaise | IrReraise):
            unique.clear()
            continue
        if isinstance(statement, IrPrint):
            unique.difference_update(_escaped_tuple_names(statement.value))
    return unique


def _owned_tuple_rebinds(function: IrFunction) -> set[int]:
    rebinds: set[int] = set()
    _analyze_owned_tuple_block(function.body, set(), rebinds, record=True)
    return rebinds


def _merge_phase_effects(effects: tuple[tuple[bool, bool], ...]) -> tuple[bool, bool]:
    return all(safe for safe, _ in effects), any(allocates for _, allocates in effects)


_PHASE_NO_CAPTURE_INTRINSICS = frozenset(
    {
        "__abs",
        "__all_generator",
        "__any_generator",
        "__bool_and",
        "__bool_or",
        "__bytes",
        "__bytes_from_ints",
        "__chr",
        "__complex",
        "__contains",
        "__dict_copy",
        "__dict_get",
        "__dict_items",
        "__dict_keys",
        "__dict_values",
        "__exec_argv",
        "__float",
        "__float_fromhex",
        "__getitem",
        "__id",
        "__ifexp",
        "__int_format_hex2",
        "__int_parse",
        "__int_to_bytes",
        "__len",
        "__next_generator",
        "__not",
        "__optional_box",
        "__ord",
        "__record_construct0",
        "__repr",
        "__set_comprehension",
        "__set_equal",
        "__sorted",
        "__tuple_comprehension",
        "__tuple_concat",
        "__tuple_repeat",
        "__type_marker",
        "__type_name",
        "__type_tag",
        "__union_getattr",
        "__zip",
        "bool",
        "isinstance",
        "len",
        "range",
        "reversed",
    }
)
_PHASE_SPECIAL_EMITTER_FUNCTIONS = frozenset(
    {
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
        "xcc.preprocessor.__init__._Preprocessor._handle_undef",
        "xcc.preprocessor.__init__._Preprocessor._should_collect_function_macro_continuation",
        "xcc.sema.type_helpers._aot_integer_type_summary",
        "xcc.types.Type.__str__",
    }
)


def _phase_intrinsic_is_no_capture(target: str) -> bool:
    return (
        target in _PHASE_NO_CAPTURE_INTRINSICS
        or target.startswith("__cmp_")
        or target.startswith("__bytes_")
        or target.startswith("__path_")
        or target.startswith("__str_")
    )


def _phase_expr_effect(
    expr: IrExpr,
    summaries: dict[str, tuple[bool, bool]],
) -> tuple[bool, bool]:
    if isinstance(expr, IrBinary):
        safe, allocates = _merge_phase_effects(
            (
                _phase_expr_effect(expr.left, summaries),
                _phase_expr_effect(expr.right, summaries),
            )
        )
        pointer_result = isinstance(
            expr.type,
            (IrBytesType, IrDictType, IrRecordType, IrStringType, IrTupleType),
        )
        return safe, allocates or pointer_result
    if isinstance(expr, IrGetField):
        return _phase_expr_effect(expr.value, summaries)
    if isinstance(expr, IrConstructRecord):
        safe, _ = _merge_phase_effects(
            tuple(_phase_expr_effect(arg, summaries) for arg in expr.args)
        )
        return safe, True
    if isinstance(expr, IrCall):
        args_safe, args_allocate = _merge_phase_effects(
            tuple(_phase_expr_effect(arg, summaries) for arg in expr.args)
        )
        if not args_safe:
            return False, args_allocate
        if _phase_intrinsic_is_no_capture(expr.target):
            pointer_result = isinstance(
                expr.type,
                (IrBytesType, IrDictType, IrRecordType, IrStringType, IrTupleType),
            )
            return True, args_allocate or pointer_result
        callee = summaries.get(expr.target)
        if callee is None:
            return False, args_allocate
        return callee[0], args_allocate or callee[1]
    if isinstance(expr, IrTuple):
        safe, _ = _merge_phase_effects(
            tuple(_phase_expr_effect(element, summaries) for element in expr.elements)
        )
        return safe, True
    if isinstance(expr, IrTupleSlice):
        effects = [_phase_expr_effect(expr.value, summaries)]
        if expr.start is not None:
            effects.append(_phase_expr_effect(expr.start, summaries))
        if expr.stop is not None:
            effects.append(_phase_expr_effect(expr.stop, summaries))
        safe, _ = _merge_phase_effects(tuple(effects))
        return safe, True
    if isinstance(expr, IrStringConcat):
        safe, _ = _merge_phase_effects(
            tuple(_phase_expr_effect(part, summaries) for part in expr.parts)
        )
        return safe, True
    if isinstance(expr, IrStringJoin):
        safe, _ = _merge_phase_effects(
            (
                _phase_expr_effect(expr.separator, summaries),
                _phase_expr_effect(expr.values, summaries),
            )
        )
        return safe, True
    return True, False


def _phase_local_target(target: str) -> bool:
    return all(_plain_assignment_target(part.strip()) for part in target.split(","))


def _phase_block_effect(
    statements: tuple[IrStmt, ...],
    summaries: dict[str, tuple[bool, bool]],
) -> tuple[bool, bool]:
    effects: list[tuple[bool, bool]] = []
    for statement in statements:
        if isinstance(statement, IrAssign):
            if not _phase_local_target(statement.target):
                return False, False
            effects.append(_phase_expr_effect(statement.value, summaries))
            continue
        if isinstance(statement, IrSetItem | IrRaise | IrReraise | IrTry):
            return False, False
        if isinstance(statement, IrReturn):
            effects.append(_phase_expr_effect(statement.value, summaries))
            continue
        if isinstance(statement, IrIf):
            effects.append(_phase_expr_effect(statement.condition, summaries))
            effects.append(_phase_block_effect(statement.then_branch.statements, summaries))
            if statement.else_branch is not None:
                effects.append(_phase_block_effect(statement.else_branch.statements, summaries))
            continue
        if isinstance(statement, IrForEach):
            if not _phase_local_target(statement.target):
                return False, False
            effects.append(_phase_expr_effect(statement.iterable, summaries))
            effects.append(_phase_block_effect(statement.body.statements, summaries))
            continue
        if isinstance(statement, IrWhile):
            effects.append(_phase_expr_effect(statement.condition, summaries))
            effects.append(_phase_block_effect(statement.body.statements, summaries))
            continue
        if isinstance(statement, IrPrint):
            effects.append(_phase_expr_effect(statement.value, summaries))
            continue
        if isinstance(statement, IrBreak | IrContinue):
            continue
        return False, False
    return _merge_phase_effects(tuple(effects))


def _phase_function_summaries(
    module: IrModule,
    fallible: frozenset[str],
) -> dict[str, tuple[bool, bool]]:
    summaries: dict[str, tuple[bool, bool]] = {}
    changed = True
    while changed:
        changed = False
        for function in module.functions:
            if (
                function.name in summaries
                or function.name in fallible
                or function.name in _PHASE_SPECIAL_EMITTER_FUNCTIONS
            ):
                continue
            safe, allocates = _phase_block_effect(function.body, summaries)
            if safe:
                summaries[function.name] = (True, allocates)
                changed = True
    return summaries


def _function_uses_owned_phase(
    function: IrFunction,
    summaries: dict[str, tuple[bool, bool]],
) -> bool:
    if not isinstance(
        function.return_type,
        (IrBoolType, IrFloatType, IrIntType, IrNoneType),
    ):
        return False
    summary = summaries.get(function.name)
    return summary is not None and summary[0] and summary[1]


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
        self.phase_function_summaries = _phase_function_summaries(
            module,
            self.fallible_functions,
        )
        self.index = 0
        self.string_index = 0
        self.string_constants: list[str] = []
        self.enum_constants: dict[tuple[str, str], str] = {}
        self.global_constants: dict[str, str] = {}
        self.global_tuple_constants: dict[str, str] = {}
        self.loop_stack: list[_LoopLabels] = []
        self.extra_declarations: set[str] = set()
        self.needs_puts = False
        self.needs_runtime_prelude = False
        self.current_function: IrFunction | None = None
        self.current_function_is_fallible = False
        self.current_result_out: str | None = None
        self.current_error_out: str | None = None
        self.current_owned_tuple_rebinds: set[int] = set()
        self.current_phase_mark: str | None = None
        self.failure_scopes: list[_FailureScope] = []
        self.caught_status_stack: list[str] = []
        self.record_equality_records: set[str] = set()
        self.tuple_object_equality_records: set[str] = set()
        self.needs_tagged_object_equality_helpers = False

    def emit(self) -> str:
        declarations = [self._emit_record(record) for record in self.module.records]
        functions = [
            guard_allocation_calls(self._emit_function(function))
            for function in self.module.functions
        ]
        raw_main = self._emit_main()
        main = None if raw_main is None else guard_allocation_calls(raw_main)
        record_equality_helpers = [
            guard_allocation_calls(helper) for helper in self._emit_record_equality_helpers()
        ]
        tagged_object_equality_helpers = [
            guard_allocation_calls(helper) for helper in self._emit_tagged_object_equality_helpers()
        ]
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
        lines.extend(record_equality_helpers)
        lines.extend(tagged_object_equality_helpers)
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
        param_values = {
            param.name: (f"%arg.{param.name}" if param.name == "entry" else f"%{param.name}")
            for param in function.params
        }
        params = ", ".join(
            f"{self._param_llvm_type(param.type)} {param_values[param.name]}"
            for param in function.params
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
        previous_owned_tuple_rebinds = self.current_owned_tuple_rebinds
        previous_phase_mark = self.current_phase_mark
        previous_failure_scopes = self.failure_scopes
        previous_caught_status_stack = self.caught_status_stack
        self.current_function = function
        self.current_function_is_fallible = fallible
        self.current_result_out = result_out if fallible else None
        self.current_error_out = "%error_out" if fallible else None
        self.current_owned_tuple_rebinds = _owned_tuple_rebinds(function)
        self.current_phase_mark = None
        self.failure_scopes = []
        self.caught_status_stack = []
        names = {
            param.name: _EmittedValue(param_values[param.name], param.type)
            for param in function.params
        }
        try:
            if _function_uses_owned_phase(function, self.phase_function_summaries):
                self.needs_runtime_prelude = True
                self.current_phase_mark = self._tmp("phase.mark")
                lines.append(f"  {self.current_phase_mark} = call ptr @__xcc_aot_phase_mark()")
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
            self.current_owned_tuple_rebinds = previous_owned_tuple_rebinds
            self.current_phase_mark = previous_phase_mark
            self.failure_scopes = previous_failure_scopes
            self.caught_status_stack = previous_caught_status_stack
        lines = _hoist_allocas_to_entry(lines)
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
            if id(statement) in self.current_owned_tuple_rebinds:
                value = self._emit_owned_tuple_rebind(statement, names, lines)
            elif isinstance(statement.value, IrConstructRecord):
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

    def _emit_owned_tuple_rebind(
        self,
        statement: IrAssign,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        value = statement.value
        if not isinstance(value, IrCall) or value.target != "__tuple_concat":
            self._error("Owned tuple rebind expects __tuple_concat")
        if len(value.args) != 2 or not isinstance(value.args[1], IrTuple):
            self._error("Owned tuple rebind expects a fresh tuple tail")
        current = self._emit_expr(value.args[0], names, lines)
        if not isinstance(current.type, IrTupleType):
            self._error("Owned tuple rebind expects a tuple receiver")
        items = tuple(self._emit_expr(item, names, lines) for item in value.args[1].elements)
        self.needs_runtime_prelude = True
        for item in items:
            boxed_item = self._box_to_runtime_ptr(item, lines)
            appended = self._tmp("tupleappend")
            lines.append(
                f"  {appended} = call ptr @__xcc_aot_tuple_append("
                f"ptr {current.value}, ptr {boxed_item})"
            )
            current = _EmittedValue(appended, value.type)
        return _EmittedValue(current.value, value.type)

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
                self._emit_phase_reset(lines)
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
            self._emit_phase_reset(lines)
            lines.append("  ret i32 0")
            return
        if isinstance(return_type, IrNoneType):
            self._emit_phase_reset(lines)
            lines.append("  ret void")
            return
        if value is None:
            self._emit_default_return(lines, return_type)
            return
        returned = self._value_for_result_type(value, return_type, lines)
        self._emit_phase_reset(lines)
        lines.append(f"  ret {self._llvm_type(return_type)} {returned}")

    def _emit_phase_reset(self, lines: list[str]) -> None:
        if self.current_phase_mark is None:
            return
        lines.append(f"  call void @__xcc_aot_phase_reset(ptr {self.current_phase_mark})")

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
        self._emit_phase_reset(lines)
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
                f"[ {self._if_phi_value(value, merged_type, source, lines)}, %{source} ]"
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
                if expr.name == "Ellipsis" and isinstance(expr.type, IrRecordType):
                    if _is_opaque_object_type(expr.type):
                        self.needs_runtime_prelude = True
                        return _EmittedValue("@__xcc_aot_object_ellipsis", expr.type)
                    return _EmittedValue("inttoptr (i64 -1 to ptr)", expr.type)
                type_constant = self._emit_type_constant_name(expr, lines)
                if type_constant is not None:
                    return type_constant
                if isinstance(expr.type, IrBoolType) and _is_type_marker_name(expr.name):
                    return _EmittedValue("true", expr.type)
                if expr.name in _BUILTIN_VALUE_NAMES or expr.name.isupper():
                    return _EmittedValue(self._default_value(expr.type), expr.type)
                self._error(f"Unknown LLVM name: {expr.name}")
            if (
                not _is_opaque_object_type(value.type)
                and _is_record_narrowing(value.type, expr.type)
            ) or (
                isinstance(value.type, IrRecordType)
                and isinstance(expr.type, IrRecordType)
                and not _is_opaque_object_type(value.type)
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
                fallthrough_sources = int(then_source is not None) + int(else_source is not None)
                if before_value is None and len(incoming) < fallthrough_sources:
                    continue
                names[name] = incoming[0][1]
                continue
            merged_type = self._if_phi_type(tuple(value for _, value in incoming))
            if merged_type is None:
                continue
            result = self._tmp("ifphi")
            parts = []
            for source, value in incoming:
                parts.append(
                    f"[ {self._if_phi_value(value, merged_type, source, lines)}, %{source} ]"
                )
            lines.append(
                f"  {result} = phi {self._storage_llvm_type(merged_type)} " + ", ".join(parts)
            )
            names[name] = _EmittedValue(result, merged_type)

    def _if_phi_type(self, values: tuple[_EmittedValue, ...]) -> IrType | None:
        optional_scalar = next(
            (
                value.type
                for value in values
                if _is_optional_bool_type(value.type) or _is_optional_int_type(value.type)
            ),
            None,
        )
        if optional_scalar is not None:
            for value in values:
                if isinstance(value.type, IrNoneType):
                    continue
                if _is_optional_bool_type(optional_scalar) and (
                    _is_optional_bool_type(value.type) or isinstance(value.type, IrBoolType)
                ):
                    continue
                if _is_optional_int_type(optional_scalar) and (
                    _is_optional_int_type(value.type) or isinstance(value.type, IrIntType)
                ):
                    continue
                return None
            return optional_scalar
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

    def _if_phi_value(
        self,
        value: _EmittedValue,
        result_type: IrType,
        source: str,
        lines: list[str],
    ) -> str:
        if isinstance(value.type, IrNoneType):
            return self._default_value(result_type)
        if value.type == result_type:
            return value.value
        conversion_lines: list[str] = []
        converted: str | None = None
        if _is_optional_bool_type(result_type) and isinstance(value.type, IrBoolType):
            tag = self._tmp("optional.bool.tag")
            converted = self._tmp("optional.bool")
            conversion_lines.append(f"  {tag} = select i1 {value.value}, i64 2, i64 1")
            conversion_lines.append(f"  {converted} = inttoptr i64 {tag} to ptr")
        elif _is_optional_int_type(result_type) and isinstance(value.type, IrIntType):
            converted = self._box_object_value(value, conversion_lines)
        if converted is not None:
            self._insert_if_phi_conversion(lines, source, conversion_lines)
            return converted
        if self._storage_llvm_type(value.type) == self._storage_llvm_type(result_type):
            return value.value
        self._error(f"Cannot merge {type(value.type).__name__} as {type(result_type).__name__}")

    def _insert_if_phi_conversion(
        self,
        lines: list[str],
        source: str,
        conversion_lines: list[str],
    ) -> None:
        source_line = f"{source}:"
        source_index = -1
        for index, line in enumerate(lines):
            if line == source_line:
                source_index = index
        if source_index < 0:
            self._error(f"Unknown if phi source: {source}")
        insertion_index = source_index + 1
        while insertion_index < len(lines) and not lines[insertion_index].endswith(":"):
            if lines[insertion_index].startswith("  br "):
                lines[insertion_index:insertion_index] = conversion_lines
                return
            insertion_index += 1
        self._error(f"If phi source has no branch terminator: {source}")

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
        initial_loop_values = {
            name: _EmittedValue(
                self._value_for_result_type(value, loop_types[name], lines),
                loop_types[name],
            )
            for name, value in initial_values.items()
        }
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
        for name, _initial in initial_loop_values.items():
            result = self._tmp("loop")
            phi_lines[name] = len(lines)
            phi_values[name] = _EmittedValue(result, loop_types[name])
            cond_names[name] = phi_values[name]
            lines.append("")
        index = self._tmp("index")
        lines.append(
            f"  {index} = phi i64 [ 0, %{current_label} ], [ {next_value}, %{next_label} ]"
        )
        string_iterable = isinstance(iterable.type, IrStringType)
        bytes_iterable = isinstance(iterable.type, IrBytesType)
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
            pointer = self._tmp("byteitemptr")
            byte = self._tmp("byteitem")
            lines.append(f"  {pointer} = getelementptr i8, ptr {byte_data}, i64 {index}")
            lines.append(f"  {byte} = load i8, ptr {pointer}")
            if string_iterable:
                character = self._tmp("charitem")
                lines.append(f"  {character} = call ptr @__xcc_aot_single_byte_string(i8 {byte})")
                item_value = _EmittedValue(character, IrStringType())
            else:
                wide = self._tmp("byteitem64")
                lines.append(f"  {wide} = zext i8 {byte} to i64")
                item_value = _EmittedValue(wide, IrIntType(64, signed=True))
            slots = _for_each_target_slots(statement.target)
            if enumerate_call is not None:
                if enumerate_start is None:
                    self._error("Malformed __enumerate loop")
                enumerate_index = index
                if enumerate_start.value != "0":
                    enumerate_index = self._tmp("enumindex")
                    lines.append(f"  {enumerate_index} = add i64 {index}, {enumerate_start.value}")
                pair = self._emit_enumerate_pair_tuple(
                    enumerate_call.type,
                    enumerate_index,
                    self._box_to_runtime_ptr(item_value, lines),
                    lines,
                )
                if len(slots) == 1 and slots[0] is not None:
                    body_names[slots[0]] = pair
                else:
                    self._bind_emitted_tuple_target(
                        statement.target,
                        pair,
                        body_names,
                        lines,
                    )
            else:
                if len(slots) != 1 or slots[0] is None:
                    self._error("string/bytes for-each expects one named target")
                body_names[slots[0]] = item_value
        else:
            item_type: IrType = _homogeneous_tuple_element_type(iterable.type) or IrRecordType(
                "object"
            )
            if isinstance(iterable.type, IrDictType):
                item_type = iterable.type.key
            item = self._tmp("item")
            item_getter = (
                "__xcc_aot_tuple_get_object"
                if _is_opaque_object_type(item_type)
                else "__xcc_aot_tuple_get"
            )
            lines.append(f"  {item} = call ptr @{item_getter}(ptr {iterable.value}, i64 {index})")
            if enumerate_call is not None:
                if enumerate_start is None:
                    self._error("Malformed __enumerate loop")
                enumerate_index = index
                if enumerate_start.value != "0":
                    enumerate_index = self._tmp("enumindex")
                    lines.append(f"  {enumerate_index} = add i64 {index}, {enumerate_start.value}")
                slots = _for_each_target_slots(statement.target)
                pair = self._emit_enumerate_pair_tuple(
                    enumerate_call.type,
                    enumerate_index,
                    item,
                    lines,
                )
                if len(slots) == 1 and slots[0] is not None:
                    body_names[slots[0]] = pair
                else:
                    self._bind_emitted_tuple_target(
                        statement.target,
                        pair,
                        body_names,
                        lines,
                    )
            else:
                if isinstance(iterable.type, IrDictType):
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
        for name, _initial in initial_loop_values.items():
            loop_type = loop_types[name]
            if not incoming_edges:
                next_phi_values[name] = phi_values[name]
            elif len(incoming_edges) == 1:
                source_label, source_names = incoming_edges[0]
                source_value = source_names.get(name, phi_values[name])
                next_phi_values[name] = _EmittedValue(
                    self._if_phi_value(source_value, loop_type, source_label, lines),
                    loop_type,
                )
            else:
                result = self._tmp("loopnext")
                parts: list[str] = []
                for source_label, source_names in incoming_edges:
                    source_value = source_names.get(name, phi_values[name])
                    parts.append(
                        f"[ {self._if_phi_value(source_value, loop_type, source_label, lines)}, "
                        f"%{source_label} ]"
                    )
                lines.append(
                    f"  {result} = phi {self._storage_llvm_type(loop_type)} " + ", ".join(parts)
                )
                next_phi_values[name] = _EmittedValue(result, loop_type)
        lines.append(f"  {next_value} = add i64 {index}, 1")
        lines.append(f"  br label %{cond_label}")
        for name, line_index in phi_lines.items():
            initial = initial_loop_values[name]
            loop_type = loop_types[name]
            next_phi_value = next_phi_values.get(name, phi_values[name])
            lines[line_index] = (
                f"  {phi_values[name].value} = phi {self._storage_llvm_type(loop_type)} "
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
            loop_types,
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
            existing = names.get(target)
            if existing is not None and _is_opaque_object_type(existing.type):
                stored = self._value_for_result_type(value, existing.type, lines)
                names[target] = _EmittedValue(stored, existing.type)
                return
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

    def _emit_enumerate_pair_tuple(
        self,
        enumerate_type: IrType,
        index: str,
        item: str,
        lines: list[str],
    ) -> _EmittedValue:
        if not isinstance(enumerate_type, IrTupleType) or len(enumerate_type.elements) != 2:
            self._error("__enumerate loop expects two element types")
        self.needs_runtime_prelude = True
        result = self._tmp("enumpair")
        index_box = self._box_to_runtime_ptr(
            _EmittedValue(index, enumerate_type.elements[0]),
            lines,
        )
        lines.append("  ; build enumerate pair")
        lines.append(f"  {result} = call ptr @__xcc_aot_tuple_new(i64 2)")
        lines.append(f"  call void @__xcc_aot_tuple_set(ptr {result}, i64 0, ptr {index_box})")
        lines.append(f"  call void @__xcc_aot_tuple_set(ptr {result}, i64 1, ptr {item})")
        return _EmittedValue(result, enumerate_type)

    def _emit_runtime_tuple_get(
        self,
        tuple_value: str,
        index: int,
        result_type: IrType,
        lines: list[str],
    ) -> _EmittedValue:
        raw = self._tmp("itemslot")
        getter = (
            "__xcc_aot_tuple_get_object"
            if _is_opaque_object_type(result_type)
            else "__xcc_aot_tuple_get"
        )
        lines.append(f"  {raw} = call ptr @{getter}(ptr {tuple_value}, i64 {index})")
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
        if isinstance(result_type, IrFloatType):
            result = self._tmp("narrowfloat")
            lines.append(f"  {result} = load double, ptr {raw}")
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
        elif isinstance(value.type, IrTupleType) and len(value.type.elements) == 1:
            target_types = value.type.elements * len(slots)
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
                item = self._emit_runtime_tuple_get(tuple_value, index, target_type, lines)
                if "," in slot:
                    self._bind_emitted_tuple_target(slot, item, names, lines)
                else:
                    names[slot] = item

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
                f"[ {self._if_phi_value(condition_value, loop_type, condition_source, lines)}, "
                f"%{condition_source} ]"
            ]
            for source_label, source_names in break_sources:
                source_value = source_names.get(name, condition_value)
                incoming.append(
                    f"[ {self._if_phi_value(source_value, loop_type, source_label, lines)}, "
                    f"%{source_label} ]"
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
        all_types = (initial_type,) + assigned_types
        if any(isinstance(type_info, IrNoneType) for type_info in all_types):
            if all(isinstance(type_info, IrNoneType | IrBoolType) for type_info in all_types):
                return IrRecordType("bool | None")
            if all(isinstance(type_info, IrNoneType | IrIntType) for type_info in all_types):
                return IrRecordType("int | None")
            if any(
                isinstance(type_info, IrBoolType | IrFloatType | IrIntType)
                for type_info in all_types
            ):
                return IrRecordType("object")
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
        if isinstance(expr.type, IrIntType):
            left = self._adapt_integer_width(left, expr.type, lines)
            right = self._adapt_integer_width(right, expr.type, lines)
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

    def _adapt_integer_width(
        self,
        value: _EmittedValue,
        result_type: IrIntType,
        lines: list[str],
    ) -> _EmittedValue:
        if not isinstance(value.type, IrIntType):
            self._error("Integer binary operator requires integer operands")
        if value.type.bits == result_type.bits:
            return _EmittedValue(value.value, result_type)
        result = self._tmp("intwidth")
        source_type = self._llvm_type(value.type)
        if value.type.bits > result_type.bits:
            lines.append(
                f"  {result} = trunc {source_type} {value.value} to {self._llvm_type(result_type)}"
            )
        else:
            operation = "sext" if value.type.signed else "zext"
            lines.append(
                f"  {result} = {operation} {source_type} {value.value} to "
                f"{self._llvm_type(result_type)}"
            )
        return _EmittedValue(result, result_type)

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
        lines.append(f"  {result} = call ptr @__xcc_aot_tuple_new(i64 {len(args)})")
        for index, arg in enumerate(args):
            if isinstance(expr.type, IrDictType):
                item_type: IrType = IrTupleType((expr.type.key, expr.type.value))
            elif len(expr.type.elements) == 1:
                item_type = expr.type.elements[0]
            elif len(expr.type.elements) == len(args):
                item_type = expr.type.elements[index]
            else:
                item_type = arg.type
            item = (
                self._box_object_value(arg, lines)
                if _is_opaque_object_type(item_type)
                else (
                    self._value_for_result_type(arg, item_type, lines)
                    if _is_optional_bool_type(item_type) or _is_optional_int_type(item_type)
                    else self._box_to_runtime_ptr(arg, lines)
                )
            )
            lines.append(f"  call void @__xcc_aot_tuple_set(ptr {result}, i64 {index}, ptr {item})")
        self._register_tuple_object_layout(result, expr.type, lines)
        return _EmittedValue(result, expr.type)

    def _emit_global_tuple_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if (
            len(expr.args) != 2
            or not isinstance(expr.args[0], IrConstString)
            or not isinstance(expr.args[1], IrTuple)
        ):
            self._error("__global_tuple expects a string key and tuple literal")
        key = expr.args[0].value
        slot = self.global_tuple_constants.get(key)
        if slot is None:
            slot = f"@__xcc_aot_global_tuple_{len(self.global_tuple_constants)}"
            self.global_tuple_constants[key] = slot
            self.global_constants[slot] = f"{slot} = private global ptr null"
        source_label = _current_label(lines)
        cached = self._tmp("global.tuple.cached")
        empty = self._tmp("global.tuple.empty")
        initialize_label = self._label("global.tuple.init")
        ready_label = self._label("global.tuple.ready")
        lines.append(f"  {cached} = load ptr, ptr {slot}")
        lines.append(f"  {empty} = icmp eq ptr {cached}, null")
        lines.append(f"  br i1 {empty}, label %{initialize_label}, label %{ready_label}")
        lines.append(f"{initialize_label}:")
        initialized = self._emit_tuple(expr.args[1], names, lines)
        initialized_label = _current_label(lines)
        lines.append(f"  store ptr {initialized.value}, ptr {slot}")
        lines.append(f"  br label %{ready_label}")
        lines.append(f"{ready_label}:")
        result = self._tmp("global.tuple")
        lines.append(
            f"  {result} = phi ptr [ {cached}, %{source_label} ], "
            f"[ {initialized.value}, %{initialized_label} ]"
        )
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
        if isinstance(value.type, IrFloatType):
            self.needs_runtime_prelude = True
            boxed = self._tmp("floatbox")
            lines.append(f"  {boxed} = call ptr @malloc(i64 8)")
            lines.append(f"  store double {value.value}, ptr {boxed}")
            return boxed
        self._error(f"Unsupported tuple item type: {type(value.type).__name__}")

    def _box_object_value(self, value: _EmittedValue, lines: list[str]) -> str:
        if isinstance(value.type, IrNoneType):
            return "null"
        if _is_opaque_object_type(value.type):
            return value.value
        nullable_source = ""
        nullable_nonnull_label = ""
        nullable_end_label = ""
        if _is_nullable_record_union(value.type, self.records):
            nullable_source = _current_label(lines)
            nullable_nonnull_label = self._label("object.box.nonnull")
            nullable_end_label = self._label("object.box.end")
            nonnull = self._tmp("object.box.nonnull")
            lines.append(f"  {nonnull} = icmp ne ptr {value.value}, null")
            lines.append(
                f"  br i1 {nonnull}, label %{nullable_nonnull_label}, label %{nullable_end_label}"
            )
            lines.append(f"{nullable_nonnull_label}:")
        tag: int
        if isinstance(value.type, IrBoolType):
            tag = _OBJECT_TAG_BOOL
        elif isinstance(value.type, IrIntType):
            tag = _OBJECT_TAG_INT
        elif isinstance(value.type, IrFloatType):
            tag = _OBJECT_TAG_FLOAT
        elif isinstance(value.type, IrStringType):
            tag = _OBJECT_TAG_STRING
        elif isinstance(value.type, IrBytesType):
            tag = _OBJECT_TAG_BYTES
        elif isinstance(value.type, IrDictType):
            tag = _OBJECT_TAG_DICT
        elif isinstance(value.type, IrTupleType):
            tag = _OBJECT_TAG_TUPLE
        elif isinstance(value.type, IrRecordType) and value.type.name == "complex":
            tag = _OBJECT_TAG_COMPLEX
        elif isinstance(value.type, IrRecordType):
            tag = _OBJECT_TAG_RECORD
        else:
            self._error(f"Unsupported object value type: {type(value.type).__name__}")
        self.needs_runtime_prelude = True
        if isinstance(value.type, IrTupleType):
            self._register_tuple_object_layout(value.value, value.type, lines)
        boxed = self._tmp("object")
        payload = self._tmp("object.payload")
        lines.append(f"  {boxed} = call ptr @malloc(i64 16)")
        lines.append(f"  store i64 {tag}, ptr {boxed}")
        lines.append(f"  {payload} = getelementptr i8, ptr {boxed}, i64 8")
        if isinstance(value.type, IrBoolType):
            widened = self._tmp("object.bool")
            lines.append(f"  {widened} = zext i1 {value.value} to i64")
            lines.append(f"  store i64 {widened}, ptr {payload}")
        elif isinstance(value.type, IrIntType):
            integer = value.value
            if value.type.bits < 64:
                widened = self._tmp("object.int")
                opcode = "sext" if value.type.signed else "zext"
                lines.append(
                    f"  {widened} = {opcode} {self._llvm_type(value.type)} {integer} to i64"
                )
                integer = widened
            elif value.type.bits > 64:
                narrowed = self._tmp("object.int")
                lines.append(f"  {narrowed} = trunc {self._llvm_type(value.type)} {integer} to i64")
                integer = narrowed
            lines.append(f"  store i64 {integer}, ptr {payload}")
        elif isinstance(value.type, IrFloatType):
            lines.append(f"  store double {value.value}, ptr {payload}")
        else:
            lines.append(f"  store ptr {value.value}, ptr {payload}")
        if nullable_source:
            lines.append(f"  br label %{nullable_end_label}")
            lines.append(f"{nullable_end_label}:")
            result = self._tmp("object.box")
            lines.append(
                f"  {result} = phi ptr [ null, %{nullable_source} ], "
                f"[ {boxed}, %{nullable_nonnull_label} ]"
            )
            return result
        return boxed

    def _emit_tuple_slice(
        self,
        expr: IrTupleSlice,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        value = self._emit_expr(expr.value, names, lines)
        start = "0"
        has_start = "false"
        if expr.start is not None:
            emitted_start = self._emit_expr(expr.start, names, lines)
            start = self._coerce_index_i64(emitted_start, lines, "tuple slice start")
            has_start = "true"
        stop = "0"
        has_stop = "false"
        if expr.stop is not None:
            emitted_stop = self._emit_expr(expr.stop, names, lines)
            stop = self._coerce_index_i64(emitted_stop, lines, "tuple slice stop")
            has_stop = "true"
        result = self._tmp("slice")
        self.needs_runtime_prelude = True
        lines.append(
            f"  {result} = call ptr @__xcc_aot_tuple_slice("
            f"ptr {value.value}, i64 {start}, i1 {has_start}, "
            f"i64 {stop}, i1 {has_stop})"
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
        field_type = self.records[record_name].fields[index].type
        field_ptr = self._tmp("fieldptr")
        result = self._tmp("load")
        lines.append(
            f"  {field_ptr} = getelementptr inbounds %{record_name}, ptr {value.value}, "
            f"i32 0, i32 {index}"
        )
        lines.append(f"  {result} = load {self._storage_llvm_type(field_type)}, ptr {field_ptr}")
        loaded = _EmittedValue(result, field_type)
        if field_type == expr.type:
            return loaded
        narrowed = self._emit_runtime_object_narrowing(loaded, expr.type, lines)
        if narrowed is not None:
            return narrowed
        if _is_pointer_type(field_type) and _is_pointer_type(expr.type):
            return _EmittedValue(result, expr.type)
        self._error(f"Cannot load {type(field_type).__name__} field as {type(expr.type).__name__}")

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
        function = self.functions.get(expr.target)
        if function is not None and len(function.params) == len(args):
            rendered_args = ", ".join(
                f"{self._param_llvm_type(param.type)} "
                f"{self._value_for_result_type(arg, param.type, lines)}"
                for arg, param in zip(args, function.params, strict=True)
            )
        else:
            rendered_args = ", ".join(
                f"{self._param_llvm_type(arg.type)} {arg.value}" for arg in args
            )
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
        if expr.target == "__global_tuple":
            return self._emit_global_tuple_call(expr, names, lines)
        if expr.target.startswith(_NORETURN_CALL_PREFIX):
            return self._emit_noreturn_call(expr, names, lines)
        if expr.target.startswith(_RECORD_INIT_PREFIX):
            return self._emit_record_init_call(expr, names, lines)
        if expr.target == "__super_init__":
            for arg in expr.args:
                self._emit_expr(arg, names, lines)
            return _EmittedValue("null", IrNoneType())
        if expr.target == "bool":
            return self._emit_bool_builtin_call(expr, names, lines)
        if expr.target == "__abs":
            return self._emit_abs_call(expr, names, lines)
        if expr.target == "isinstance":
            return self._emit_isinstance_call(expr, names, lines)
        if expr.target == "__type_tag":
            return self._emit_type_tag_call(expr, names, lines)
        if expr.target == "__type_name":
            return self._emit_type_name_call(expr, names, lines)
        if expr.target == "__type_marker":
            return self._emit_type_marker_call(expr)
        if expr.target == "__union_getattr":
            return self._emit_union_getattr_call(expr, names, lines)
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
        if expr.target == "__str_rfind":
            return self._emit_string_rfind_call(expr, names, lines)
        if expr.target == "__str_count":
            return self._emit_string_count_call(expr, names, lines)
        if expr.target == "__str_split":
            return self._emit_string_split_call(expr, names, lines)
        if expr.target == "__str_split_limit":
            return self._emit_string_split_limit_call(expr, names, lines)
        if expr.target == "__str_rsplit_limit":
            return self._emit_string_rsplit_limit_call(expr, names, lines)
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
        if expr.target == "__str_upper":
            return self._emit_string_upper_call(expr, names, lines)
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
        if expr.target == "__tuple_pop_item":
            return self._emit_tuple_pop_item_call(expr, names, lines)
        if expr.target == "__tuple_set_slice":
            return self._emit_tuple_set_slice_call(expr, names, lines)
        if expr.target == "__tuple_remove_item":
            return self._emit_tuple_remove_item_call(expr, names, lines)
        if expr.target == "__set_add":
            return self._emit_set_add_call(expr, names, lines)
        if expr.target in {
            "__set_difference",
            "__set_difference_update",
            "__set_intersection",
            "__set_symmetric_difference",
            "__set_update",
            "__set_union",
        }:
            return self._emit_set_binary_call(expr, names, lines)
        if expr.target == "__set_equal":
            return self._emit_set_equality_call(expr, names, lines)
        predicate_mode = _STRING_PREDICATE_INTRINSICS.get(expr.target)
        if predicate_mode is not None:
            return self._emit_string_predicate_call(expr, predicate_mode, names, lines)
        if expr.target == "__bytes":
            return self._emit_bytes_call(expr, names, lines)
        if expr.target == "__bytes_from_ints":
            return self._emit_bytes_from_ints_call(expr, names, lines)
        if expr.target == "__bytes_slice":
            return self._emit_bytes_slice_call(expr, names, lines)
        if expr.target == "__id":
            return self._emit_id_call(expr, names, lines)
        if expr.target == "__repr":
            return self._emit_repr_call(expr, names, lines)
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
        if expr.target == "__path_write_text":
            return self._emit_path_write_text_call(expr, names, lines)
        if expr.target == "__path_is_file":
            return self._emit_path_is_file_call(expr, names, lines)
        if expr.target == "__exec_argv":
            return self._emit_exec_argv_call(expr, names, lines)
        if expr.target == "__dict_get":
            return self._emit_dict_get_call(expr, names, lines)
        if expr.target == "__dict_setdefault":
            return self._emit_dict_setdefault_call(expr, names, lines)
        if expr.target == "__dict_copy":
            return self._emit_dict_copy_call(expr, names, lines)
        if expr.target == "__dict_set":
            return self._emit_dict_set_call(expr, names, lines)
        if expr.target == "__dict_items":
            return self._emit_dict_items_call(expr, names, lines)
        if expr.target == "__dict_keys":
            return self._emit_dict_keys_call(expr, names, lines)
        if expr.target == "__dict_values":
            return self._emit_dict_values_call(expr, names, lines)
        if expr.target == "__dict_update":
            return self._emit_dict_update_call(expr, names, lines)
        if expr.target == "__dict_remove":
            return self._emit_dict_remove_call(expr, names, lines)
        if expr.target == "__dict_comprehension":
            return self._emit_dict_comprehension_call(expr, names, lines)
        if expr.target in {"__set_comprehension", "__tuple_comprehension"}:
            return self._emit_sequence_comprehension_call(expr, names, lines)
        if expr.target == "__sorted":
            return self._emit_sorted_call(expr, names, lines)
        if expr.target == "__zip":
            return self._emit_zip_call(expr, names, lines)
        if expr.target in {"__all_generator", "__any_generator"}:
            return self._emit_generator_predicate_call(expr, names, lines)
        if expr.target == "__next_generator":
            return self._emit_next_generator_call(expr, names, lines)
        if expr.target == "__optional_box":
            return self._emit_optional_box_call(expr, names, lines)
        if (
            _is_tuple_mutating_method(expr.target)
            and expr.args
            and isinstance(expr.args[0].type, IrTupleType)
        ):
            return self._emit_tuple_mutating_method_call(expr, names, lines)
        if expr.target == "__float":
            return self._emit_float_call(expr, names, lines)
        if expr.target == "__complex":
            return self._emit_complex_call(expr, names, lines)
        if expr.target == "__float_fromhex":
            return self._emit_float_fromhex_call(expr, names, lines)
        if expr.target == "__int_to_bytes":
            return self._emit_int_to_bytes_call(expr, names, lines)
        if expr.target == "__int_parse":
            return self._emit_int_parse_call(expr, names, lines)
        if expr.target == "__int_format_hex2":
            return self._emit_int_format_hex2_call(expr, names, lines)
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
            "__value_or",
        }:
            return None
        if expr.target == "__bool_and":
            return self._emit_bool_short_circuit("and", expr.args, names, lines)
        if expr.target == "__bool_or":
            return self._emit_bool_short_circuit("or", expr.args, names, lines)
        if expr.target == "__ifexp":
            return self._emit_ifexp_call(expr, names, lines)
        if expr.target == "__value_or":
            return self._emit_value_or_call(expr, names, lines)
        args = [self._emit_expr(arg, names, lines) for arg in expr.args]
        if expr.target == "__not":
            if len(args) != 1:
                self._error("__not expects one argument")
            return self._emit_bool_not(args[0], lines)
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

    def _emit_abs_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1 or not isinstance(expr.type, IrIntType):
            self._error("abs expects one integer argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrIntType):
            self._error("abs expects one integer argument")
        llvm_type = self._llvm_type(expr.type)
        negative = self._tmp("absneg")
        magnitude = self._tmp("absmagnitude")
        result = self._tmp("abs")
        lines.append(f"  {negative} = icmp slt {llvm_type} {value.value}, 0")
        lines.append(f"  {magnitude} = sub {llvm_type} 0, {value.value}")
        lines.append(
            f"  {result} = select i1 {negative}, {llvm_type} {magnitude}, {llvm_type} {value.value}"
        )
        return _EmittedValue(result, expr.type)

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
        target_names = self._isinstance_target_names(expr.args[1])
        static_result = _static_builtin_isinstance_result(value.type, target_names)
        if static_result is not None:
            return _EmittedValue("true" if static_result else "false", expr.type)
        target_ids = self._isinstance_target_type_ids(expr.args[1])
        if _is_opaque_object_type(value.type):
            return self._emit_tagged_object_isinstance(
                value,
                target_names,
                target_ids,
                lines,
                expr.type,
            )
        if isinstance(value.type, IrRecordType) and target_ids:
            return self._emit_record_isinstance(value, target_ids, lines, expr.type)
        if _is_pointer_type(value.type):
            result = self._tmp("isinstance")
            lines.append(f"  {result} = icmp ne ptr {value.value}, null")
            return _EmittedValue(result, expr.type)
        self._error(f"Unsupported isinstance value type: {type(value.type).__name__}")

    def _isinstance_target_names(self, target: IrExpr) -> tuple[str, ...]:
        if isinstance(target, IrName):
            return (target.name,)
        if isinstance(target, IrTuple):
            return tuple(element.name for element in target.elements if isinstance(element, IrName))
        return ()

    def _emit_tagged_object_isinstance(
        self,
        value: _EmittedValue,
        target_names: tuple[str, ...],
        target_ids: tuple[int, ...],
        lines: list[str],
        result_type: IrBoolType,
    ) -> _EmittedValue:
        source_label = _current_label(lines)
        check_label = self._label("object.isinstance.check")
        end_label = self._label("object.isinstance.end")
        nonnull = self._tmp("object.isinstance.nonnull")
        lines.append(f"  {nonnull} = icmp ne ptr {value.value}, null")
        lines.append(f"  br i1 {nonnull}, label %{check_label}, label %{end_label}")
        lines.append(f"{check_label}:")
        tag = self._tmp("object.tag")
        lines.append(f"  {tag} = load i64, ptr {value.value}")
        builtin_tags = sorted(
            {
                object_tag
                for target_name in target_names
                for object_tag in _OBJECT_BUILTIN_TAGS.get(target_name, ())
            }
        )
        builtin_match = "false"
        for object_tag in builtin_tags:
            current = self._tmp("object.isinstance.builtin")
            lines.append(f"  {current} = icmp eq i64 {tag}, {object_tag}")
            if builtin_match == "false":
                builtin_match = current
            else:
                combined = self._tmp("object.isinstance.builtin")
                lines.append(f"  {combined} = or i1 {builtin_match}, {current}")
                builtin_match = combined
        result_source = check_label
        final_match = builtin_match
        if target_ids:
            record_label = self._label("object.isinstance.record")
            merge_label = self._label("object.isinstance.merge")
            is_record = self._tmp("object.isinstance.record")
            lines.append(f"  {is_record} = icmp eq i64 {tag}, {_OBJECT_TAG_RECORD}")
            lines.append(f"  br i1 {is_record}, label %{record_label}, label %{merge_label}")
            lines.append(f"{record_label}:")
            payload = self._tmp("object.payload")
            record_value = self._tmp("object.record")
            record_tag_pointer = self._tmp("object.record.tagptr")
            record_tag = self._tmp("object.record.tag")
            lines.append(f"  {payload} = getelementptr i8, ptr {value.value}, i64 8")
            lines.append(f"  {record_value} = load ptr, ptr {payload}")
            lines.append(f"  {record_tag_pointer} = getelementptr i8, ptr {record_value}, i64 -8")
            lines.append(f"  {record_tag} = load i64, ptr {record_tag_pointer}")
            record_match = self._tmp("object.isinstance.record")
            lines.append(f"  {record_match} = icmp eq i64 {record_tag}, {target_ids[0]}")
            for target_id in target_ids[1:]:
                current = self._tmp("object.isinstance.record")
                combined = self._tmp("object.isinstance.record")
                lines.append(f"  {current} = icmp eq i64 {record_tag}, {target_id}")
                lines.append(f"  {combined} = or i1 {record_match}, {current}")
                record_match = combined
            lines.append(f"  br label %{merge_label}")
            lines.append(f"{merge_label}:")
            merged_record = self._tmp("object.isinstance.record")
            lines.append(
                f"  {merged_record} = phi i1 [ false, %{check_label} ], "
                f"[ {record_match}, %{record_label} ]"
            )
            if builtin_match == "false":
                final_match = merged_record
            else:
                final_match = self._tmp("object.isinstance")
                lines.append(f"  {final_match} = or i1 {builtin_match}, {merged_record}")
            result_source = merge_label
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("object.isinstance")
        lines.append(
            f"  {result} = phi i1 [ false, %{source_label} ], [ {final_match}, %{result_source} ]"
        )
        return _EmittedValue(result, result_type)

    def _emit_record_construct0_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if not expr.args or not isinstance(expr.type, IrRecordType):
            self._error("__record_construct0 expects one marker and a record result")
        marker = self._emit_expr(expr.args[0], names, lines)
        base_name = expr.type.name
        base_record = self.records.get(base_name)
        if base_record is None or len(expr.args) != len(base_record.fields) + 1:
            self._error("__record_construct0 default field shape mismatch")
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
        for index, (argument, field) in enumerate(
            zip(expr.args[1:], base_record.fields, strict=True)
        ):
            value = self._emit_expr(argument, names, lines)
            stored = self._value_for_result_type(value, field.type, lines)
            field_ptr = self._tmp("recordctor.field")
            lines.append(
                f"  {field_ptr} = getelementptr inbounds %{base_name}, ptr {result}, "
                f"i32 0, i32 {index}"
            )
            lines.append(f"  store {self._storage_llvm_type(field.type)} {stored}, ptr {field_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_record_init_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if not expr.args or not isinstance(expr.args[0], IrConstructRecord):
            self._error("record initializer expects a default record instance")
        init_target = expr.target.removeprefix(_RECORD_INIT_PREFIX)
        if init_target not in self.functions:
            self._error(f"record initializer is not reachable: {init_target}")
        instance = self._emit_expr(expr.args[0], names, lines)
        instance_name = "__record_init_instance"
        init_names = dict(names)
        init_names[instance_name] = instance
        self._emit_call(
            IrCall(
                init_target,
                (IrName(instance_name, expr.args[0].type),) + expr.args[1:],
                IrNoneType(),
            ),
            init_names,
            lines,
        )
        return instance

    def _emit_noreturn_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        target = expr.target.removeprefix(_NORETURN_CALL_PREFIX)
        if target not in self.functions:
            self._error(f"NoReturn call is not reachable: {target}")
        result = self._emit_call(IrCall(target, expr.args, expr.type), names, lines)
        if not _block_is_terminated(lines):
            lines.append("  unreachable")
        return result

    def _emit_union_getattr_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) < 3 or not isinstance(expr.args[1], IrName):
            self._error("__union_getattr expects receiver, marker, and cases")
        receiver = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(receiver.type, IrRecordType):
            self._error("__union_getattr expects a record union receiver")
        marker = expr.args[1]
        cases = expr.args[2:]
        case_records: list[str] = []
        for case in cases:
            case_receiver: IrExpr | None = None
            if isinstance(case, IrGetField):
                case_receiver = case.value
            elif isinstance(case, IrCall) and case.args:
                case_receiver = case.args[0]
            if not isinstance(case_receiver, IrName) or not isinstance(
                case_receiver.type, IrRecordType
            ):
                self._error("__union_getattr case requires a concrete record receiver")
            case_records.append(case_receiver.type.name)

        case_type_ids: list[list[int]] = [[] for _case in cases]
        assigned_ids: set[int] = set()
        for index, record_name in enumerate(case_records):
            type_id = self.record_type_ids.get(record_name)
            if type_id is None:
                self._error(f"__union_getattr record is not emitted: {record_name}")
            case_type_ids[index].append(type_id)
            assigned_ids.add(type_id)
        for index, record_name in enumerate(case_records):
            for type_id in self._record_descendant_type_ids(record_name):
                if type_id in assigned_ids:
                    continue
                case_type_ids[index].append(type_id)
                assigned_ids.add(type_id)

        tag_pointer = self._tmp("unionattr.tagptr")
        tag = self._tmp("unionattr.tag")
        default_label = self._label("unionattr.default")
        end_label = self._label("unionattr.end")
        case_labels = tuple(self._label("unionattr.case") for _case in cases)
        lines.append(f"  {tag_pointer} = getelementptr i8, ptr {receiver.value}, i64 -8")
        lines.append(f"  {tag} = load i64, ptr {tag_pointer}")
        lines.append(f"  switch i64 {tag}, label %{default_label} [")
        for case_label, type_ids in zip(case_labels, case_type_ids, strict=True):
            for type_id in type_ids:
                lines.append(f"    i64 {type_id}, label %{case_label}")
        lines.append("  ]")
        lines.append(f"{default_label}:")
        lines.append(f"  br label %{end_label}")
        incoming = [(self._default_value(expr.type), default_label)]
        for case, record_name, case_label in zip(
            cases,
            case_records,
            case_labels,
            strict=True,
        ):
            lines.append(f"{case_label}:")
            case_names = dict(names)
            case_names[marker.name] = _EmittedValue(
                receiver.value,
                IrRecordType(record_name),
            )
            case_value = self._emit_expr(case, case_names, lines)
            stored_value = self._value_for_result_type(case_value, expr.type, lines)
            source_label = _current_label(lines)
            lines.append(f"  br label %{end_label}")
            incoming.append((stored_value, source_label))
        lines.append(f"{end_label}:")
        result = self._tmp("unionattr")
        rendered_incoming = ", ".join(f"[ {value}, %{label} ]" for value, label in incoming)
        lines.append(f"  {result} = phi {self._llvm_type(expr.type)} {rendered_incoming}")
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
        ids: set[int] = set()
        for name in self._isinstance_target_names(target):
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
        if not _is_string_like_type(value.type):
            self._error("__str_endswith expects string receiver and suffix")
        if not isinstance(expr.type, IrBoolType):
            self._error("__str_endswith expects a bool result")
        self.needs_runtime_prelude = True
        if isinstance(expr.args[1], IrTuple):
            tuple_result: _EmittedValue = _EmittedValue("false", IrBoolType())
            for suffix_expr in expr.args[1].elements:
                suffix = self._emit_expr(suffix_expr, names, lines)
                if not _is_string_like_type(suffix.type):
                    self._error("__str_endswith expects string receiver and suffix")
                current = self._tmp("endswith")
                lines.append(
                    f"  {current} = call i1 @__xcc_aot_string_endswith("
                    f"ptr {value.value}, ptr {suffix.value})"
                )
                if tuple_result.value == "false":
                    tuple_result = _EmittedValue(current, IrBoolType())
                else:
                    combined = self._tmp("endswith")
                    lines.append(f"  {combined} = or i1 {tuple_result.value}, {current}")
                    tuple_result = _EmittedValue(combined, IrBoolType())
            return tuple_result
        suffix = self._emit_expr(expr.args[1], names, lines)
        if not _is_string_like_type(suffix.type):
            self._error("__str_endswith expects string receiver and suffix")
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

    def _emit_string_rfind_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 4:
            self._error("__str_rfind expects four arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        needle = self._emit_expr(expr.args[1], names, lines)
        start = self._emit_expr(expr.args[2], names, lines)
        end = self._emit_expr(expr.args[3], names, lines)
        if not isinstance(value.type, IrStringType) or not isinstance(needle.type, IrStringType):
            self._error("__str_rfind expects string receiver and needle")
        if not all(
            isinstance(bound.type, IrIntType) and bound.type.bits == 64 for bound in (start, end)
        ):
            self._error("__str_rfind expects int64 bounds")
        if not isinstance(expr.type, IrIntType) or expr.type.bits != 64:
            self._error("__str_rfind expects an int64 result")
        self.needs_runtime_prelude = True
        result = self._tmp("rfind")
        lines.append(
            f"  {result} = call i64 @__xcc_aot_string_rfind("
            f"ptr {value.value}, ptr {needle.value}, i64 {start.value}, i64 {end.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_string_count_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 4:
            self._error("__str_count expects four arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        needle = self._emit_expr(expr.args[1], names, lines)
        start = self._emit_expr(expr.args[2], names, lines)
        end = self._emit_expr(expr.args[3], names, lines)
        if not isinstance(value.type, IrStringType) or not isinstance(needle.type, IrStringType):
            self._error("__str_count expects string receiver and needle")
        if not all(
            isinstance(bound.type, IrIntType) and bound.type.bits == 64 for bound in (start, end)
        ):
            self._error("__str_count expects int64 bounds")
        if not isinstance(expr.type, IrIntType) or expr.type.bits != 64:
            self._error("__str_count expects an int64 result")
        self.needs_runtime_prelude = True
        result = self._tmp("count")
        lines.append(
            f"  {result} = call i64 @__xcc_aot_string_count("
            f"ptr {value.value}, ptr {needle.value}, i64 {start.value}, i64 {end.value})"
        )
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

    def _emit_string_rsplit_limit_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__str_rsplit_limit expects three arguments")
        value = self._emit_expr(expr.args[0], names, lines)
        separator = self._emit_expr(expr.args[1], names, lines)
        maxsplit = self._emit_expr(expr.args[2], names, lines)
        if not isinstance(value.type, IrStringType) or not isinstance(separator.type, IrStringType):
            self._error("__str_rsplit_limit expects string receiver and separator")
        if not isinstance(maxsplit.type, IrIntType) or maxsplit.type.bits != 64:
            self._error("__str_rsplit_limit expects an int64 maxsplit")
        if not isinstance(expr.type, IrTupleType):
            self._error("__str_rsplit_limit expects a tuple result")
        self.needs_runtime_prelude = True
        result = self._tmp("rsplitlimit")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_string_rsplit_limit("
            f"ptr {value.value}, ptr {separator.value}, i64 {maxsplit.value})"
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

    def _emit_string_upper_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__str_upper expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrStringType):
            self._error("__str_upper expects string receiver")
        if not isinstance(expr.type, IrStringType):
            self._error("__str_upper expects a string result")
        self.needs_runtime_prelude = True
        result = self._tmp("upper")
        lines.append(f"  {result} = call ptr @__xcc_aot_string_upper(ptr {value.value})")
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

    def _emit_bytes_from_ints_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__bytes_from_ints expects one argument")
        values = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(values.type, IrTupleType) or not all(
            isinstance(element, IrIntType) for element in values.type.elements
        ):
            self._error("__bytes_from_ints expects a tuple-backed integer iterable")
        if not isinstance(expr.type, IrBytesType):
            self._error("__bytes_from_ints expects a bytes result")
        self.needs_runtime_prelude = True
        result = self._tmp("bytes")
        lines.append(f"  {result} = call ptr @__xcc_aot_bytes_from_ints(ptr {values.value})")
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

    def _emit_repr_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__repr expects one argument")
        if not isinstance(expr.type, IrStringType):
            self._error("__repr expects a string result")
        value = self._emit_expr(expr.args[0], names, lines)
        boxed = self._box_object_value(value, lines)
        self.needs_runtime_prelude = True
        result = self._tmp("repr")
        lines.append(f"  {result} = call ptr @__xcc_aot_object_repr(ptr {boxed})")
        return _EmittedValue(result, expr.type)

    def _emit_type_tag_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1 or not isinstance(expr.type, IrIntType):
            self._error("__type_tag expects one argument and an integer result")
        value = self._emit_expr(expr.args[0], names, lines)
        if _is_opaque_object_type(value.type):
            return self._emit_object_type_tag(value, expr.type, lines)
        tag = self._static_type_tag(value.type)
        return _EmittedValue(str(tag), expr.type)

    def _emit_type_name_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1 or not isinstance(expr.type, IrStringType):
            self._error("__type_name expects one argument and a string result")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrRecordType):
            self._error("__type_name expects a record value")
        base_names = tuple(
            part.rsplit(".", 1)[-1]
            for part in _record_union_parts(value.type.name)
            if part != "None"
        )
        record_names = tuple(
            record_name
            for record_name in sorted(self.records)
            if any(
                record_name == base_name or self._record_extends(record_name, base_name)
                for base_name in base_names
            )
        )
        if not record_names:
            self._error(f"__type_name record is not emitted: {value.type.name}")
        source_label = _current_label(lines)
        check_label = self._label("typename.check")
        default_label = self._label("typename.default")
        end_label = self._label("typename.end")
        case_labels = tuple(self._label("typename.case") for _name in record_names)
        nonnull = self._tmp("typename.nonnull")
        lines.append(f"  {nonnull} = icmp ne ptr {value.value}, null")
        lines.append(f"  br i1 {nonnull}, label %{check_label}, label %{end_label}")
        lines.append(f"{check_label}:")
        tag_pointer = self._tmp("typename.tagptr")
        tag = self._tmp("typename.tag")
        lines.append(f"  {tag_pointer} = getelementptr i8, ptr {value.value}, i64 -8")
        lines.append(f"  {tag} = load i64, ptr {tag_pointer}")
        lines.append(f"  switch i64 {tag}, label %{default_label} [")
        for record_name, case_label in zip(record_names, case_labels, strict=True):
            lines.append(f"    i64 {self.record_type_ids[record_name]}, label %{case_label}")
        lines.append("  ]")
        lines.append(f"{default_label}:")
        lines.append(f"  br label %{end_label}")
        incoming = [
            (self._string_constant("NoneType"), source_label),
            (self._string_constant("<unknown>"), default_label),
        ]
        for record_name, case_label in zip(record_names, case_labels, strict=True):
            lines.append(f"{case_label}:")
            lines.append(f"  br label %{end_label}")
            incoming.append((self._string_constant(record_name), case_label))
        lines.append(f"{end_label}:")
        result = self._tmp("typename")
        rendered_incoming = ", ".join(f"[ {constant}, %{label} ]" for constant, label in incoming)
        lines.append(f"  {result} = phi ptr {rendered_incoming}")
        return _EmittedValue(result, expr.type)

    def _emit_type_marker_call(self, expr: IrCall) -> _EmittedValue:
        if (
            len(expr.args) != 1
            or not isinstance(expr.args[0], IrName)
            or not isinstance(expr.type, IrIntType)
        ):
            self._error("__type_marker expects one named marker and an integer result")
        marker = expr.args[0].name
        tag = _EXACT_BUILTIN_TYPE_TAGS.get(marker)
        if tag is None:
            type_id = self.record_type_ids.get(marker)
            if type_id is None:
                self._error(f"Unsupported exact type marker: {marker}")
            tag = _TYPE_TAG_RECORD_BASE + type_id
        return _EmittedValue(str(tag), expr.type)

    def _emit_object_type_tag(
        self,
        value: _EmittedValue,
        result_type: IrIntType,
        lines: list[str],
    ) -> _EmittedValue:
        source_label = _current_label(lines)
        check_label = self._label("object.type.check")
        record_label = self._label("object.type.record")
        primitive_label = self._label("object.type.primitive")
        end_label = self._label("object.type.end")
        nonnull = self._tmp("object.type.nonnull")
        lines.append(f"  {nonnull} = icmp ne ptr {value.value}, null")
        lines.append(f"  br i1 {nonnull}, label %{check_label}, label %{end_label}")
        lines.append(f"{check_label}:")
        tag = self._tmp("object.type.tag")
        is_record = self._tmp("object.type.record")
        lines.append(f"  {tag} = load i64, ptr {value.value}")
        lines.append(f"  {is_record} = icmp eq i64 {tag}, {_OBJECT_TAG_RECORD}")
        lines.append(f"  br i1 {is_record}, label %{record_label}, label %{primitive_label}")
        lines.append(f"{record_label}:")
        payload_pointer = self._tmp("object.type.payloadptr")
        record_value = self._tmp("object.type.payload")
        record_tag_pointer = self._tmp("object.type.recordptr")
        record_id = self._tmp("object.type.recordid")
        record_tag = self._tmp("object.type.recordtag")
        lines.append(f"  {payload_pointer} = getelementptr i8, ptr {value.value}, i64 8")
        lines.append(f"  {record_value} = load ptr, ptr {payload_pointer}")
        lines.append(f"  {record_tag_pointer} = getelementptr i8, ptr {record_value}, i64 -8")
        lines.append(f"  {record_id} = load i64, ptr {record_tag_pointer}")
        lines.append(f"  {record_tag} = add i64 {record_id}, {_TYPE_TAG_RECORD_BASE}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{primitive_label}:")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("object.type")
        lines.append(
            f"  {result} = phi i64 [ {_TYPE_TAG_NONE}, %{source_label} ], "
            f"[ {record_tag}, %{record_label} ], [ {tag}, %{primitive_label} ]"
        )
        return _EmittedValue(result, result_type)

    def _static_type_tag(self, type_info: IrType) -> int:
        if isinstance(type_info, IrNoneType):
            return _TYPE_TAG_NONE
        if isinstance(type_info, IrBoolType):
            return _OBJECT_TAG_BOOL
        if isinstance(type_info, IrIntType):
            return _OBJECT_TAG_INT
        if isinstance(type_info, IrFloatType):
            return _OBJECT_TAG_FLOAT
        if isinstance(type_info, IrStringType):
            return _OBJECT_TAG_STRING
        if isinstance(type_info, IrBytesType):
            return _OBJECT_TAG_BYTES
        if isinstance(type_info, IrDictType):
            return _OBJECT_TAG_DICT
        if isinstance(type_info, IrTupleType):
            return _OBJECT_TAG_TUPLE
        if isinstance(type_info, IrRecordType) and type_info.name == "complex":
            return _OBJECT_TAG_COMPLEX
        if isinstance(type_info, IrRecordType):
            type_id = self.record_type_ids.get(type_info.name)
            if type_id is not None:
                return _TYPE_TAG_RECORD_BASE + type_id
        self._error(f"Unsupported exact type value: {type(type_info).__name__}")

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
        lines.append(f"  {byte} = trunc i64 {value.value} to i8")
        lines.append(f"  {result} = call ptr @__xcc_aot_single_byte_string(i8 {byte})")
        return _EmittedValue(result, expr.type)

    def _emit_dict_get_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) not in {2, 3}:
            self._error("__dict_get expects dict, key, and optional default")
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
        initial_value = self._default_value(expr.type)
        if len(expr.args) == 3:
            default = self._emit_expr(expr.args[2], names, lines)
            initial_value = self._value_for_result_type(default, expr.type, lines)
        lines.append(f"  {result_ptr} = alloca {result_type}")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store {result_type} {initial_value}, ptr {result_ptr}")
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

    def _emit_dict_copy_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1 or not isinstance(expr.type, IrDictType):
            self._error("__dict_copy expects one tuple-backed dict")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrDictType):
            self._error("__dict_copy expects one tuple-backed dict")
        self.needs_runtime_prelude = True
        result = self._tmp("dictcopy")
        lines.append(f"  {result} = call ptr @__xcc_aot_dict_copy(ptr {value.value})")
        return _EmittedValue(result, expr.type)

    def _emit_dict_setdefault_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__dict_setdefault expects dict, key, and default")
        dict_value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(dict_value.type, IrDictType):
            self._error("__dict_setdefault expects a tuple-backed dict")
        key_type, value_type = dict_value.type.key, dict_value.type.value
        key = self._emit_expr(expr.args[1], names, lines)
        default = self._emit_expr(expr.args[2], names, lines)
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("dictdefault.resultptr")
        index_ptr = self._tmp("dictdefault.indexptr")
        cond_label = self._label("dictdefault.cond")
        body_label = self._label("dictdefault.body")
        found_label = self._label("dictdefault.found")
        next_label = self._label("dictdefault.next")
        insert_label = self._label("dictdefault.insert")
        end_label = self._label("dictdefault.end")
        result_type = self._llvm_type(expr.type)
        default_result = self._value_for_result_type(default, expr.type, lines)
        lines.append(f"  {result_ptr} = alloca {result_type}")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("dictdefault.index")
        length = self._tmp("dictdefault.len")
        done = self._tmp("dictdefault.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {dict_value.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{insert_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        raw_pair = self._tmp("dictdefault.pair")
        lines.append(
            f"  {raw_pair} = call ptr @__xcc_aot_tuple_get(ptr {dict_value.value}, i64 {index})"
        )
        candidate_key = self._emit_runtime_tuple_get(raw_pair, 0, key_type, lines)
        match = self._emit_equality_compare(key, candidate_key, negate=False, lines=lines)
        lines.append(f"  br i1 {match.value}, label %{found_label}, label %{next_label}")
        lines.append(f"{found_label}:")
        existing = self._emit_runtime_tuple_get(raw_pair, 1, value_type, lines)
        existing_result = self._value_for_result_type(existing, expr.type, lines)
        lines.append(f"  store {result_type} {existing_result}, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("dictdefault.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{insert_label}:")
        pair = self._tmp("dictdefault.pair")
        appended = self._tmp("dictdefault.appended")
        coerced_key = _EmittedValue(
            self._value_for_result_type(key, key_type, lines),
            key_type,
        )
        coerced_default = _EmittedValue(
            self._value_for_result_type(default, value_type, lines),
            value_type,
        )
        key_box = self._box_to_runtime_ptr(coerced_key, lines)
        default_box = self._box_to_runtime_ptr(coerced_default, lines)
        lines.append(f"  {pair} = call ptr @__xcc_aot_tuple_new(i64 2)")
        lines.append(f"  call void @__xcc_aot_tuple_set(ptr {pair}, i64 0, ptr {key_box})")
        lines.append(f"  call void @__xcc_aot_tuple_set(ptr {pair}, i64 1, ptr {default_box})")
        lines.append(
            f"  {appended} = call ptr @__xcc_aot_tuple_append(ptr {dict_value.value}, ptr {pair})"
        )
        lines.append(f"  store {result_type} {default_result}, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("dictdefault")
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
        lines.append(f"  call void @__xcc_aot_tuple_set(ptr {raw_pair}, i64 1, ptr {value_box})")
        lines.append(f"  store ptr {dict_value.value}, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("dictset.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{append_label}:")
        pair = self._tmp("dictset.pair")
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
        lines.append(f"  {pair} = call ptr @__xcc_aot_tuple_new(i64 2)")
        lines.append(f"  call void @__xcc_aot_tuple_set(ptr {pair}, i64 0, ptr {key_box})")
        lines.append(f"  call void @__xcc_aot_tuple_set(ptr {pair}, i64 1, ptr {append_value_box})")
        lines.append(
            f"  {appended} = call ptr @__xcc_aot_tuple_append(ptr {dict_value.value}, ptr {pair})"
        )
        lines.append(f"  store ptr {appended}, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("dictset")
        lines.append(f"  {result} = load ptr, ptr {result_ptr}")
        return _EmittedValue(dict_value.value, expr.type)

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

    def _emit_dict_keys_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__dict_keys expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrDictType):
            self._error("__dict_keys expects a tuple-backed dict")
        if not isinstance(expr.type, IrTupleType):
            self._error("__dict_keys expects a tuple result")
        self.needs_runtime_prelude = True
        result = self._tmp("dictkeys")
        lines.append(f"  {result} = call ptr @__xcc_aot_dict_keys(ptr {value.value})")
        return _EmittedValue(result, expr.type)

    def _emit_dict_values_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__dict_values expects one argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(value.type, IrDictType):
            self._error("__dict_values expects a tuple-backed dict")
        if not isinstance(expr.type, IrTupleType):
            self._error("__dict_values expects a tuple result")
        self.needs_runtime_prelude = True
        result = self._tmp("dictvalues")
        lines.append(f"  {result} = call ptr @__xcc_aot_dict_values(ptr {value.value})")
        return _EmittedValue(result, expr.type)

    def _emit_dict_update_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2 or not isinstance(expr.type, IrDictType):
            self._error("__dict_update expects two dictionaries and a dictionary result")
        target = self._emit_expr(expr.args[0], names, lines)
        incoming = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(target.type, IrDictType) or incoming.type != target.type:
            self._error("__dict_update expects dictionaries with matching types")
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("dictupdate.resultptr")
        index_ptr = self._tmp("dictupdate.indexptr")
        cond_label = self._label("dictupdate.cond")
        body_label = self._label("dictupdate.body")
        end_label = self._label("dictupdate.end")
        lines.append(f"  {result_ptr} = alloca ptr")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store ptr {target.value}, ptr {result_ptr}")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("dictupdate.index")
        length = self._tmp("dictupdate.len")
        done = self._tmp("dictupdate.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {incoming.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        pair = self._tmp("dictupdate.pair")
        lines.append(f"  {pair} = call ptr @__xcc_aot_tuple_get(ptr {incoming.value}, i64 {index})")
        key = self._emit_runtime_tuple_get(pair, 0, target.type.key, lines)
        value = self._emit_runtime_tuple_get(pair, 1, target.type.value, lines)
        current = self._tmp("dictupdate.current")
        lines.append(f"  {current} = load ptr, ptr {result_ptr}")
        result_name = f"__dictupdate_result_{self.index}"
        key_name = f"__dictupdate_key_{self.index}"
        value_name = f"__dictupdate_value_{self.index}"
        update_names = dict(names)
        update_names[result_name] = _EmittedValue(current, target.type)
        update_names[key_name] = key
        update_names[value_name] = value
        updated = self._emit_dict_set_call(
            IrCall(
                "__dict_set",
                (
                    IrName(result_name, target.type),
                    IrName(key_name, target.type.key),
                    IrName(value_name, target.type.value),
                ),
                target.type,
            ),
            update_names,
            lines,
        )
        lines.append(f"  store ptr {updated.value}, ptr {result_ptr}")
        next_index = self._tmp("dictupdate.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("dictupdate")
        lines.append(f"  {result} = load ptr, ptr {result_ptr}")
        lines.append(f"  call void @__xcc_aot_tuple_forward(ptr {target.value}, ptr {result})")
        return _EmittedValue(target.value, target.type)

    def _emit_dict_remove_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2 or not isinstance(expr.type, IrDictType):
            self._error("__dict_remove expects a dictionary, key, and dictionary result")
        target = self._emit_expr(expr.args[0], names, lines)
        key = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(target.type, IrDictType):
            self._error("__dict_remove expects a dictionary receiver")
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("dictremove.resultptr")
        index_ptr = self._tmp("dictremove.indexptr")
        empty = self._tmp("dictremove.empty")
        cond_label = self._label("dictremove.cond")
        body_label = self._label("dictremove.body")
        append_label = self._label("dictremove.append")
        next_label = self._label("dictremove.next")
        end_label = self._label("dictremove.end")
        lines.append(f"  {result_ptr} = alloca ptr")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  {empty} = call ptr @__xcc_aot_tuple_new(i64 0)")
        lines.append(f"  store ptr {empty}, ptr {result_ptr}")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("dictremove.index")
        length = self._tmp("dictremove.len")
        done = self._tmp("dictremove.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {target.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        pair = self._tmp("dictremove.pair")
        lines.append(f"  {pair} = call ptr @__xcc_aot_tuple_get(ptr {target.value}, i64 {index})")
        candidate = self._emit_runtime_tuple_get(pair, 0, target.type.key, lines)
        matches = self._emit_equality_compare(key, candidate, negate=False, lines=lines)
        lines.append(f"  br i1 {matches.value}, label %{next_label}, label %{append_label}")
        lines.append(f"{append_label}:")
        current = self._tmp("dictremove.current")
        singleton = self._tmp("dictremove.singleton")
        appended = self._tmp("dictremove.appended")
        lines.append(f"  {current} = load ptr, ptr {result_ptr}")
        lines.append(f"  {singleton} = call ptr @__xcc_aot_tuple_new(i64 1)")
        lines.append(f"  call void @__xcc_aot_tuple_set(ptr {singleton}, i64 0, ptr {pair})")
        lines.append(
            f"  {appended} = call ptr @__xcc_aot_tuple_concat(ptr {current}, ptr {singleton})"
        )
        lines.append(f"  store ptr {appended}, ptr {result_ptr}")
        lines.append(f"  br label %{next_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("dictremove.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("dictremove")
        lines.append(f"  {result} = load ptr, ptr {result_ptr}")
        lines.append(f"  call void @__xcc_aot_tuple_forward(ptr {target.value}, ptr {result})")
        return _EmittedValue(target.value, target.type)

    def _emit_dict_comprehension_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) < 5 or len(expr.args) % 2 != 1:
            self._error("__dict_comprehension expects generator pairs, key, value, and predicate")
        if not isinstance(expr.type, IrDictType):
            self._error("__dict_comprehension expects a dict result")
        generators: list[tuple[IrExpr, IrName]] = []
        arg_index = 0
        while arg_index < len(expr.args) - 3:
            marker = expr.args[arg_index + 1]
            if not isinstance(marker, IrName):
                self._error("__dict_comprehension expects named generator targets")
            generators.append((expr.args[arg_index], marker))
            arg_index += 2
        if not generators:
            self._error("__dict_comprehension expects at least one generator")
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("dictcomp.resultptr")
        empty = self._tmp("dictcomp.empty")
        lines.append(f"  {result_ptr} = alloca ptr")
        lines.append(f"  {empty} = call ptr @__xcc_aot_tuple_new(i64 0)")
        lines.append(f"  store ptr {empty}, ptr {result_ptr}")
        self._emit_dict_comprehension_level(
            expr,
            tuple(generators),
            0,
            names,
            result_ptr,
            lines,
        )
        result = self._tmp("dictcomp")
        lines.append(f"  {result} = load ptr, ptr {result_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_dict_comprehension_level(
        self,
        expr: IrCall,
        generators: tuple[tuple[IrExpr, IrName], ...],
        level: int,
        names: dict[str, _EmittedValue],
        result_ptr: str,
        lines: list[str],
    ) -> None:
        iterable_expr, marker = generators[level]
        iterable, enumerate_start, enumerate_type, level_predicate = (
            self._emit_comprehension_iterable(
                iterable_expr,
                names,
                lines,
            )
        )
        if not isinstance(iterable.type, IrTupleType | IrDictType):
            self._error("__dict_comprehension expects tuple-backed iterables")
        index_ptr = self._tmp(f"dictcomp.{level}.indexptr")
        cond_label = self._label("dictcomp.cond")
        body_label = self._label("dictcomp.body")
        next_label = self._label("dictcomp.next")
        end_label = self._label("dictcomp.end")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("dictcomp.index")
        length = self._tmp("dictcomp.len")
        done = self._tmp("dictcomp.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {iterable.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        raw = self._tmp("dictcomp.item")
        lines.append(f"  {raw} = call ptr @__xcc_aot_tuple_get(ptr {iterable.value}, i64 {index})")
        if isinstance(iterable.type, IrDictType):
            raw_key = self._tmp("dictcomp.key")
            lines.append(f"  {raw_key} = call ptr @__xcc_aot_tuple_get(ptr {raw}, i64 0)")
            raw = raw_key
        if enumerate_type is not None:
            if enumerate_start is None:
                self._error("Malformed __enumerate comprehension")
            enumerate_index = index
            if enumerate_start.value != "0":
                enumerate_index = self._tmp("dictcomp.enumindex")
                lines.append(f"  {enumerate_index} = add i64 {index}, {enumerate_start.value}")
            item = self._emit_enumerate_pair_tuple(
                enumerate_type,
                enumerate_index,
                raw,
                lines,
            )
        else:
            item = self._emit_runtime_boxed_value(raw, marker.type, lines)
        comprehension_names = dict(names)
        if "," in marker.name:
            self._bind_emitted_tuple_target(
                marker.name,
                item,
                comprehension_names,
                lines,
            )
        else:
            comprehension_names[marker.name] = item
        self._emit_comprehension_filter(
            level_predicate,
            comprehension_names,
            next_label,
            "dictcomp",
            lines,
        )
        if level + 1 < len(generators):
            self._emit_dict_comprehension_level(
                expr,
                generators,
                level + 1,
                comprehension_names,
                result_ptr,
                lines,
            )
            lines.append(f"  br label %{next_label}")
        else:
            self._emit_dict_comprehension_value(
                expr,
                comprehension_names,
                result_ptr,
                next_label,
                lines,
            )
        lines.append(f"{next_label}:")
        next_index = self._tmp("dictcomp.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")

    def _emit_dict_comprehension_value(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        result_ptr: str,
        next_label: str,
        lines: list[str],
    ) -> None:
        append_label = self._label("dictcomp.append")
        predicate = self._coerce_to_bool(
            self._emit_expr(expr.args[-1], names, lines),
            lines,
        )
        lines.append(f"  br i1 {predicate.value}, label %{append_label}, label %{next_label}")
        lines.append(f"{append_label}:")
        current = self._tmp("dictcomp.current")
        result_name = f"__dictcomp_result_{self.index}"
        lines.append(f"  {current} = load ptr, ptr {result_ptr}")
        names[result_name] = _EmittedValue(current, expr.type)
        updated = self._emit_dict_set_call(
            IrCall(
                "__dict_set",
                (
                    IrName(result_name, expr.type),
                    expr.args[-3],
                    expr.args[-2],
                ),
                expr.type,
            ),
            names,
            lines,
        )
        lines.append(f"  store ptr {updated.value}, ptr {result_ptr}")
        lines.append(f"  br label %{next_label}")

    def _emit_comprehension_iterable(
        self,
        iterable_expr: IrExpr,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> tuple[_EmittedValue, _EmittedValue | None, IrTupleType | None, IrExpr]:
        predicate: IrExpr = IrConstBool(True)
        if isinstance(iterable_expr, IrCall) and iterable_expr.target == (
            "__comprehension_iterable"
        ):
            if len(iterable_expr.args) != 2:
                self._error("Malformed filtered comprehension iterable")
            iterable_expr, predicate = iterable_expr.args
        if not isinstance(iterable_expr, IrCall) or iterable_expr.target != "__enumerate":
            return self._emit_expr(iterable_expr, names, lines), None, None, predicate
        if len(iterable_expr.args) != 2 or not isinstance(iterable_expr.type, IrTupleType):
            self._error("Malformed __enumerate comprehension")
        iterable = self._emit_expr(iterable_expr.args[0], names, lines)
        start = self._emit_expr(iterable_expr.args[1], names, lines)
        if not isinstance(start.type, IrIntType) or start.type.bits != 64:
            self._error("__enumerate comprehension start expects int64")
        return iterable, start, iterable_expr.type, predicate

    def _emit_comprehension_filter(
        self,
        predicate: IrExpr,
        names: dict[str, _EmittedValue],
        next_label: str,
        label_prefix: str,
        lines: list[str],
    ) -> None:
        if isinstance(predicate, IrConstBool) and predicate.value:
            return
        accepted_label = self._label(f"{label_prefix}.accepted")
        accepted = self._coerce_to_bool(self._emit_expr(predicate, names, lines), lines)
        lines.append(f"  br i1 {accepted.value}, label %{accepted_label}, label %{next_label}")
        lines.append(f"{accepted_label}:")

    def _emit_sequence_comprehension_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) < 4 or len(expr.args) % 2 != 0:
            self._error(f"{expr.target} expects generator pairs, element, and predicate")
        if not isinstance(expr.type, IrTupleType) or len(expr.type.elements) != 1:
            self._error(f"{expr.target} expects a homogeneous tuple result")
        generators: list[tuple[IrExpr, IrName]] = []
        arg_index = 0
        while arg_index < len(expr.args) - 2:
            marker = expr.args[arg_index + 1]
            if not isinstance(marker, IrName):
                self._error(f"{expr.target} expects named generator targets")
            generators.append((expr.args[arg_index], marker))
            arg_index += 2
        if not generators:
            self._error(f"{expr.target} expects at least one generator")
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("seqcomp.resultptr")
        empty = self._tmp("seqcomp.empty")
        lines.append(f"  {result_ptr} = alloca ptr")
        lines.append(f"  {empty} = call ptr @__xcc_aot_tuple_new(i64 0)")
        lines.append(f"  store ptr {empty}, ptr {result_ptr}")
        self._emit_sequence_comprehension_level(
            expr,
            tuple(generators),
            0,
            names,
            result_ptr,
            lines,
        )
        result = self._tmp("seqcomp")
        lines.append(f"  {result} = load ptr, ptr {result_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_sequence_comprehension_level(
        self,
        expr: IrCall,
        generators: tuple[tuple[IrExpr, IrName], ...],
        level: int,
        names: dict[str, _EmittedValue],
        result_ptr: str,
        lines: list[str],
    ) -> None:
        iterable_expr, marker = generators[level]
        iterable, enumerate_start, enumerate_type, level_predicate = (
            self._emit_comprehension_iterable(
                iterable_expr,
                names,
                lines,
            )
        )
        if not isinstance(iterable.type, IrTupleType | IrDictType):
            self._error(f"{expr.target} expects tuple-backed iterables")
        index_ptr = self._tmp(f"seqcomp.{level}.indexptr")
        cond_label = self._label("seqcomp.cond")
        body_label = self._label("seqcomp.body")
        next_label = self._label("seqcomp.next")
        end_label = self._label("seqcomp.end")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("seqcomp.index")
        length = self._tmp("seqcomp.len")
        done = self._tmp("seqcomp.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {iterable.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        raw = self._tmp("seqcomp.item")
        lines.append(f"  {raw} = call ptr @__xcc_aot_tuple_get(ptr {iterable.value}, i64 {index})")
        if isinstance(iterable.type, IrDictType):
            raw_key = self._tmp("seqcomp.key")
            lines.append(f"  {raw_key} = call ptr @__xcc_aot_tuple_get(ptr {raw}, i64 0)")
            raw = raw_key
        if enumerate_type is not None:
            if enumerate_start is None:
                self._error("Malformed __enumerate comprehension")
            enumerate_index = index
            if enumerate_start.value != "0":
                enumerate_index = self._tmp("seqcomp.enumindex")
                lines.append(f"  {enumerate_index} = add i64 {index}, {enumerate_start.value}")
            item = self._emit_enumerate_pair_tuple(
                enumerate_type,
                enumerate_index,
                raw,
                lines,
            )
        else:
            item = self._emit_runtime_boxed_value(raw, marker.type, lines)
        comprehension_names = dict(names)
        if "," in marker.name:
            self._bind_emitted_tuple_target(
                marker.name,
                item,
                comprehension_names,
                lines,
            )
        else:
            comprehension_names[marker.name] = item
        self._emit_comprehension_filter(
            level_predicate,
            comprehension_names,
            next_label,
            "seqcomp",
            lines,
        )
        if level + 1 < len(generators):
            self._emit_sequence_comprehension_level(
                expr,
                generators,
                level + 1,
                comprehension_names,
                result_ptr,
                lines,
            )
            lines.append(f"  br label %{next_label}")
        else:
            self._emit_sequence_comprehension_value(
                expr,
                comprehension_names,
                result_ptr,
                next_label,
                lines,
            )
        lines.append(f"{next_label}:")
        next_index = self._tmp("seqcomp.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")

    def _emit_sequence_comprehension_value(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        result_ptr: str,
        next_label: str,
        lines: list[str],
    ) -> None:
        value_label = self._label("seqcomp.value")
        append_label = self._label("seqcomp.append")
        predicate = self._coerce_to_bool(
            self._emit_expr(expr.args[-1], names, lines),
            lines,
        )
        lines.append(f"  br i1 {predicate.value}, label %{value_label}, label %{next_label}")
        lines.append(f"{value_label}:")
        value = self._emit_expr(expr.args[-2], names, lines)
        if expr.target == "__set_comprehension":
            current = self._tmp("seqcomp.current")
            current_name = f"__seqcomp_current_{self.index}"
            value_name = f"__seqcomp_value_{self.index}"
            lines.append(f"  {current} = load ptr, ptr {result_ptr}")
            membership_names = dict(names)
            membership_names[current_name] = _EmittedValue(current, expr.type)
            membership_names[value_name] = value
            member = self._emit_tuple_membership(
                IrName(value_name, value.type),
                IrName(current_name, expr.type),
                membership_names,
                lines,
                negate=False,
            )
            lines.append(f"  br i1 {member.value}, label %{next_label}, label %{append_label}")
        else:
            lines.append(f"  br label %{append_label}")
        lines.append(f"{append_label}:")
        current = self._tmp("seqcomp.current")
        boxed = self._box_to_runtime_ptr(value, lines)
        updated = self._tmp("seqcomp.updated")
        lines.append(f"  {current} = load ptr, ptr {result_ptr}")
        lines.append(f"  {updated} = call ptr @__xcc_aot_tuple_append(ptr {current}, ptr {boxed})")
        lines.append(f"  store ptr {updated}, ptr {result_ptr}")
        lines.append(f"  br label %{next_label}")

    def _emit_zip_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if not expr.args:
            self._error("__zip expects at least one argument")
        iterables = [self._emit_expr(arg, names, lines) for arg in expr.args]
        if any(not isinstance(iterable.type, IrTupleType) for iterable in iterables):
            self._error("__zip expects tuple-backed iterables")
        if not isinstance(expr.type, IrTupleType):
            self._error("__zip expects a tuple result")
        self.needs_runtime_prelude = True
        if len(iterables) == 2:
            result = self._tmp("zip")
            lines.append(
                f"  {result} = call ptr @__xcc_aot_zip2("
                f"ptr {iterables[0].value}, ptr {iterables[1].value})"
            )
            return _EmittedValue(result, expr.type)

        count = self._tmp("zip.count")
        lines.append(f"  {count} = call i64 @__xcc_aot_tuple_len(ptr {iterables[0].value})")
        for iterable in iterables[1:]:
            length = self._tmp("zip.len")
            shorter = self._tmp("zip.shorter")
            next_count = self._tmp("zip.count")
            lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {iterable.value})")
            lines.append(f"  {shorter} = icmp ult i64 {length}, {count}")
            lines.append(f"  {next_count} = select i1 {shorter}, i64 {length}, i64 {count}")
            count = next_count
        result = self._tmp("zip")
        index_ptr = self._tmp("zip.indexptr")
        cond_label = self._label("zip.cond")
        body_label = self._label("zip.body")
        next_label = self._label("zip.next")
        end_label = self._label("zip.end")
        lines.append(f"  {result} = call ptr @__xcc_aot_tuple_new(i64 {count})")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("zip.index")
        done = self._tmp("zip.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {done} = icmp uge i64 {index}, {count}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        pair = self._tmp("zip.item")
        lines.append(f"  {pair} = call ptr @__xcc_aot_tuple_new(i64 {len(iterables)})")
        for item_index, iterable in enumerate(iterables):
            item = self._tmp("zip.value")
            lines.append(
                f"  {item} = call ptr @__xcc_aot_tuple_get(ptr {iterable.value}, i64 {index})"
            )
            lines.append(
                f"  call void @__xcc_aot_tuple_set(ptr {pair}, i64 {item_index}, ptr {item})"
            )
        lines.append(f"  call void @__xcc_aot_tuple_set(ptr {result}, i64 {index}, ptr {pair})")
        lines.append(f"  br label %{next_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("zip.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        return _EmittedValue(result, expr.type)

    def _emit_sorted_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 4 or not isinstance(expr.args[1], IrName):
            self._error("__sorted expects iterable, item marker, key, and reverse")
        if not isinstance(expr.type, IrTupleType) or len(expr.type.elements) != 1:
            self._error("__sorted expects a homogeneous tuple result")
        iterable, _enumerate_start, _enumerate_type, level_predicate = (
            self._emit_comprehension_iterable(expr.args[0], names, lines)
        )
        if not isinstance(iterable.type, IrTupleType | IrDictType):
            self._error("__sorted expects a tuple-backed iterable or dict")
        marker = expr.args[1]
        reverse = self._coerce_to_bool(self._emit_expr(expr.args[3], names, lines), lines)
        self.needs_runtime_prelude = True
        length = self._tmp("sorted.len")
        result = self._tmp("sorted")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {iterable.value})")
        lines.append(f"  {result} = call ptr @__xcc_aot_tuple_new(i64 {length})")

        copy_index_ptr = self._tmp("sorted.copy.indexptr")
        copy_cond_label = self._label("sorted.copy.cond")
        copy_body_label = self._label("sorted.copy.body")
        copy_end_label = self._label("sorted.copy.end")
        lines.append(f"  {copy_index_ptr} = alloca i64")
        lines.append(f"  store i64 0, ptr {copy_index_ptr}")
        lines.append(f"  br label %{copy_cond_label}")
        lines.append(f"{copy_cond_label}:")
        copy_index = self._tmp("sorted.copy.index")
        copy_done = self._tmp("sorted.copy.done")
        lines.append(f"  {copy_index} = load i64, ptr {copy_index_ptr}")
        lines.append(f"  {copy_done} = icmp uge i64 {copy_index}, {length}")
        lines.append(f"  br i1 {copy_done}, label %{copy_end_label}, label %{copy_body_label}")
        lines.append(f"{copy_body_label}:")
        raw_item = self._tmp("sorted.copy.item")
        lines.append(
            f"  {raw_item} = call ptr @__xcc_aot_tuple_get(ptr {iterable.value}, i64 {copy_index})"
        )
        if isinstance(iterable.type, IrDictType):
            raw_key = self._tmp("sorted.copy.key")
            lines.append(f"  {raw_key} = call ptr @__xcc_aot_tuple_get(ptr {raw_item}, i64 0)")
            raw_item = raw_key
        lines.append(
            f"  call void @__xcc_aot_tuple_set(ptr {result}, i64 {copy_index}, ptr {raw_item})"
        )
        copy_next = self._tmp("sorted.copy.next")
        lines.append(f"  {copy_next} = add i64 {copy_index}, 1")
        lines.append(f"  store i64 {copy_next}, ptr {copy_index_ptr}")
        lines.append(f"  br label %{copy_cond_label}")
        lines.append(f"{copy_end_label}:")

        outer_ptr = self._tmp("sorted.outerptr")
        inner_ptr = self._tmp("sorted.innerptr")
        outer_cond_label = self._label("sorted.outer.cond")
        outer_body_label = self._label("sorted.outer.body")
        outer_next_label = self._label("sorted.outer.next")
        outer_end_label = self._label("sorted.outer.end")
        inner_cond_label = self._label("sorted.inner.cond")
        inner_body_label = self._label("sorted.inner.body")
        swap_label = self._label("sorted.swap")
        inner_next_label = self._label("sorted.inner.next")
        lines.append(f"  {outer_ptr} = alloca i64")
        lines.append(f"  {inner_ptr} = alloca i64")
        lines.append(f"  store i64 0, ptr {outer_ptr}")
        lines.append(f"  br label %{outer_cond_label}")
        lines.append(f"{outer_cond_label}:")
        outer = self._tmp("sorted.outer")
        outer_done = self._tmp("sorted.outer.done")
        lines.append(f"  {outer} = load i64, ptr {outer_ptr}")
        lines.append(f"  {outer_done} = icmp uge i64 {outer}, {length}")
        lines.append(f"  br i1 {outer_done}, label %{outer_end_label}, label %{outer_body_label}")
        lines.append(f"{outer_body_label}:")
        lines.append(f"  store i64 0, ptr {inner_ptr}")
        lines.append(f"  br label %{inner_cond_label}")
        lines.append(f"{inner_cond_label}:")
        inner = self._tmp("sorted.inner")
        pass_items = self._tmp("sorted.passitems")
        pass_length = self._tmp("sorted.passlen")
        inner_done = self._tmp("sorted.inner.done")
        lines.append(f"  {inner} = load i64, ptr {inner_ptr}")
        lines.append(f"  {pass_items} = sub i64 {length}, {outer}")
        lines.append(f"  {pass_length} = sub i64 {pass_items}, 1")
        lines.append(f"  {inner_done} = icmp uge i64 {inner}, {pass_length}")
        lines.append(f"  br i1 {inner_done}, label %{outer_next_label}, label %{inner_body_label}")
        lines.append(f"{inner_body_label}:")
        left_raw = self._tmp("sorted.left")
        right_raw = self._tmp("sorted.right")
        right_index = self._tmp("sorted.right.index")
        lines.append(f"  {right_index} = add i64 {inner}, 1")
        lines.append(f"  {left_raw} = call ptr @__xcc_aot_tuple_get(ptr {result}, i64 {inner})")
        lines.append(
            f"  {right_raw} = call ptr @__xcc_aot_tuple_get(ptr {result}, i64 {right_index})"
        )
        left = self._emit_runtime_boxed_value(left_raw, marker.type, lines)
        right = self._emit_runtime_boxed_value(right_raw, marker.type, lines)
        left_names = dict(names)
        right_names = dict(names)
        left_names[marker.name] = left
        right_names[marker.name] = right
        left_key = self._emit_expr(expr.args[2], left_names, lines)
        right_key = self._emit_expr(expr.args[2], right_names, lines)
        left_key_name = f"__sorted_left_key_{self.index}"
        right_key_name = f"__sorted_right_key_{self.index}"
        comparison_names = dict(names)
        comparison_names[left_key_name] = left_key
        comparison_names[right_key_name] = right_key
        left_key_expr = IrName(left_key_name, left_key.type)
        right_key_expr = IrName(right_key_name, right_key.type)
        ascending_swap = self._emit_expr(
            IrCall("__cmp_Gt", (left_key_expr, right_key_expr), IrBoolType()),
            comparison_names,
            lines,
        )
        descending_swap = self._emit_expr(
            IrCall("__cmp_Lt", (left_key_expr, right_key_expr), IrBoolType()),
            comparison_names,
            lines,
        )
        should_swap = self._tmp("sorted.shouldswap")
        lines.append(
            f"  {should_swap} = select i1 {reverse.value}, "
            f"i1 {descending_swap.value}, i1 {ascending_swap.value}"
        )
        lines.append(f"  br i1 {should_swap}, label %{swap_label}, label %{inner_next_label}")
        lines.append(f"{swap_label}:")
        lines.append(
            f"  call void @__xcc_aot_tuple_set(ptr {result}, i64 {inner}, ptr {right_raw})"
        )
        lines.append(
            f"  call void @__xcc_aot_tuple_set(ptr {result}, i64 {right_index}, ptr {left_raw})"
        )
        lines.append(f"  br label %{inner_next_label}")
        lines.append(f"{inner_next_label}:")
        inner_next = self._tmp("sorted.inner.next")
        lines.append(f"  {inner_next} = add i64 {inner}, 1")
        lines.append(f"  store i64 {inner_next}, ptr {inner_ptr}")
        lines.append(f"  br label %{inner_cond_label}")
        lines.append(f"{outer_next_label}:")
        outer_next = self._tmp("sorted.outer.next")
        lines.append(f"  {outer_next} = add i64 {outer}, 1")
        lines.append(f"  store i64 {outer_next}, ptr {outer_ptr}")
        lines.append(f"  br label %{outer_cond_label}")
        lines.append(f"{outer_end_label}:")
        return _EmittedValue(result, expr.type)

    def _emit_generator_predicate_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) > 3:
            return self._emit_nested_generator_predicate_call(expr, names, lines)
        if len(expr.args) != 3 or not isinstance(expr.args[1], IrName):
            self._error(f"{expr.target} expects iterable, target, and predicate")
        if not isinstance(expr.type, IrBoolType):
            self._error(f"{expr.target} expects a bool result")
        mode = "any" if expr.target == "__any_generator" else "all"
        iterable_expr = expr.args[0]
        level_predicate: IrExpr = IrConstBool(True)
        if isinstance(iterable_expr, IrCall) and iterable_expr.target == (
            "__comprehension_iterable"
        ):
            if len(iterable_expr.args) != 2:
                self._error("Malformed filtered generator iterable")
            iterable_expr, level_predicate = iterable_expr.args
        iterable = self._emit_expr(iterable_expr, names, lines)
        marker = expr.args[1]
        self.needs_runtime_prelude = True
        length = self._tmp(f"{mode}.len")
        byte_data = iterable.value
        if isinstance(iterable.type, IrStringType):
            lines.append(f"  {length} = call i64 @strlen(ptr {iterable.value})")
        elif isinstance(iterable.type, IrBytesType):
            byte_data = self._tmp(f"{mode}.bytesdata")
            lines.append(f"  {byte_data} = call ptr @__xcc_aot_bytes_data(ptr {iterable.value})")
            lines.append(f"  {length} = call i64 @__xcc_aot_bytes_len(ptr {iterable.value})")
        elif isinstance(iterable.type, IrTupleType | IrDictType):
            lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {iterable.value})")
        else:
            self._error(f"{expr.target} expects an iterable value")

        cond_label = self._label(f"{mode}.cond")
        body_label = self._label(f"{mode}.body")
        next_label = self._label(f"{mode}.next")
        end_label = self._label(f"{mode}.end")
        source_label = _current_label(lines)
        next_index = self._tmp(f"{mode}.next")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp(f"{mode}.index")
        lines.append(f"  {index} = phi i64 [ 0, %{source_label} ], [ {next_index}, %{next_label} ]")
        has_item = self._tmp(f"{mode}.has_item")
        lines.append(f"  {has_item} = icmp ult i64 {index}, {length}")
        lines.append(f"  br i1 {has_item}, label %{body_label}, label %{end_label}")
        exhausted_source = _current_label(lines)
        lines.append(f"{body_label}:")
        predicate_names = dict(names)
        if isinstance(iterable.type, IrStringType | IrBytesType):
            pointer = self._tmp(f"{mode}.itemptr")
            byte = self._tmp(f"{mode}.item")
            lines.append(f"  {pointer} = getelementptr i8, ptr {byte_data}, i64 {index}")
            lines.append(f"  {byte} = load i8, ptr {pointer}")
            if isinstance(iterable.type, IrStringType):
                character = self._tmp(f"{mode}.character")
                lines.append(f"  {character} = call ptr @__xcc_aot_single_byte_string(i8 {byte})")
                item = _EmittedValue(character, IrStringType())
            else:
                wide = self._tmp(f"{mode}.item64")
                lines.append(f"  {wide} = zext i8 {byte} to i64")
                item = _EmittedValue(wide, IrIntType(64, signed=True))
        else:
            raw = self._tmp(f"{mode}.item")
            lines.append(
                f"  {raw} = call ptr @__xcc_aot_tuple_get(ptr {iterable.value}, i64 {index})"
            )
            if isinstance(iterable.type, IrDictType):
                item = self._emit_runtime_tuple_get(raw, 0, marker.type, lines)
            else:
                item = self._emit_runtime_boxed_value(raw, marker.type, lines)
        if "," in marker.name:
            self._bind_emitted_tuple_target(
                marker.name,
                item,
                predicate_names,
                lines,
            )
        else:
            predicate_names[marker.name] = item
        self._emit_comprehension_filter(
            level_predicate,
            predicate_names,
            next_label,
            mode,
            lines,
        )
        predicate = self._coerce_to_bool(
            self._emit_expr(expr.args[2], predicate_names, lines),
            lines,
        )
        predicate_source = _current_label(lines)
        if mode == "any":
            lines.append(f"  br i1 {predicate.value}, label %{end_label}, label %{next_label}")
            stopped_value = "true"
            exhausted_value = "false"
        else:
            lines.append(f"  br i1 {predicate.value}, label %{next_label}, label %{end_label}")
            stopped_value = "false"
            exhausted_value = "true"
        lines.append(f"{next_label}:")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        result = self._tmp(mode)
        lines.append(
            f"  {result} = phi i1 [ {exhausted_value}, %{exhausted_source} ], "
            f"[ {stopped_value}, %{predicate_source} ]"
        )
        return _EmittedValue(result, expr.type)

    def _emit_next_generator_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 4 or not isinstance(expr.args[1], IrName):
            self._error("__next_generator expects iterable, target, element, and default")
        marker = expr.args[1]
        iterable, enumerate_start, enumerate_type, predicate = self._emit_comprehension_iterable(
            expr.args[0], names, lines
        )
        if enumerate_start is not None or enumerate_type is not None:
            self._error("__next_generator does not accept enumerate iterables")
        if not isinstance(iterable.type, IrTupleType | IrDictType):
            self._error("__next_generator expects a tuple-backed iterable")
        default = self._emit_expr(expr.args[3], names, lines)
        default_value = self._value_for_result_type(default, expr.type, lines)
        self.needs_runtime_prelude = True
        length = self._tmp("next.len")
        cond_label = self._label("next.cond")
        body_label = self._label("next.body")
        next_label = self._label("next.advance")
        end_label = self._label("next.end")
        source_label = _current_label(lines)
        next_index = self._tmp("next.index")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {iterable.value})")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("next.index")
        lines.append(f"  {index} = phi i64 [ 0, %{source_label} ], [ {next_index}, %{next_label} ]")
        has_item = self._tmp("next.has_item")
        lines.append(f"  {has_item} = icmp ult i64 {index}, {length}")
        lines.append(f"  br i1 {has_item}, label %{body_label}, label %{end_label}")
        exhausted_source = _current_label(lines)
        lines.append(f"{body_label}:")
        raw = self._tmp("next.item")
        lines.append(f"  {raw} = call ptr @__xcc_aot_tuple_get(ptr {iterable.value}, i64 {index})")
        if isinstance(iterable.type, IrDictType):
            key = self._tmp("next.key")
            lines.append(f"  {key} = call ptr @__xcc_aot_tuple_get(ptr {raw}, i64 0)")
            raw = key
        item = self._emit_runtime_boxed_value(raw, marker.type, lines)
        generator_names = dict(names)
        if "," in marker.name:
            self._bind_emitted_tuple_target(
                marker.name,
                item,
                generator_names,
                lines,
            )
        else:
            generator_names[marker.name] = item
        self._emit_comprehension_filter(
            predicate,
            generator_names,
            next_label,
            "next",
            lines,
        )
        element = self._emit_expr(expr.args[2], generator_names, lines)
        element_value = self._value_for_result_type(element, expr.type, lines)
        matched_source = _current_label(lines)
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("next")
        lines.append(
            f"  {result} = phi {self._storage_llvm_type(expr.type)} "
            f"[ {default_value}, %{exhausted_source} ], "
            f"[ {element_value}, %{matched_source} ]"
        )
        return _EmittedValue(result, expr.type)

    def _emit_nested_generator_predicate_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) < 5 or len(expr.args) % 2 == 0:
            self._error(f"{expr.target} expects generator pairs and a predicate")
        if not isinstance(expr.type, IrBoolType):
            self._error(f"{expr.target} expects a bool result")
        generators: list[tuple[IrExpr, IrName]] = []
        arg_index = 0
        while arg_index < len(expr.args) - 1:
            marker = expr.args[arg_index + 1]
            if not isinstance(marker, IrName):
                self._error(f"{expr.target} expects named generator targets")
            generators.append((expr.args[arg_index], marker))
            arg_index += 2
        mode = "any" if expr.target == "__any_generator" else "all"
        default_value = "false" if mode == "any" else "true"
        self.needs_runtime_prelude = True
        result_ptr = self._tmp(f"{mode}.resultptr")
        end_label = self._label(f"{mode}.end")
        lines.append(f"  {result_ptr} = alloca i1")
        lines.append(f"  store i1 {default_value}, ptr {result_ptr}")
        self._emit_nested_generator_predicate_level(
            expr,
            tuple(generators),
            0,
            names,
            result_ptr,
            end_label,
            lines,
        )
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        result = self._tmp(mode)
        lines.append(f"  {result} = load i1, ptr {result_ptr}")
        return _EmittedValue(result, expr.type)

    def _emit_nested_generator_predicate_level(
        self,
        expr: IrCall,
        generators: tuple[tuple[IrExpr, IrName], ...],
        level: int,
        names: dict[str, _EmittedValue],
        result_ptr: str,
        result_label: str,
        lines: list[str],
    ) -> None:
        iterable_expr, marker = generators[level]
        iterable, enumerate_start, enumerate_type, level_predicate = (
            self._emit_comprehension_iterable(
                iterable_expr,
                names,
                lines,
            )
        )
        if not isinstance(iterable.type, IrTupleType | IrDictType):
            self._error(f"{expr.target} expects tuple-backed iterables")
        mode = "any" if expr.target == "__any_generator" else "all"
        index_ptr = self._tmp(f"{mode}.{level}.indexptr")
        cond_label = self._label(f"{mode}.cond")
        body_label = self._label(f"{mode}.body")
        next_label = self._label(f"{mode}.next")
        end_label = self._label(f"{mode}.exhausted")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp(f"{mode}.index")
        length = self._tmp(f"{mode}.len")
        done = self._tmp(f"{mode}.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {iterable.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        raw = self._tmp(f"{mode}.item")
        lines.append(f"  {raw} = call ptr @__xcc_aot_tuple_get(ptr {iterable.value}, i64 {index})")
        if isinstance(iterable.type, IrDictType):
            raw_key = self._tmp(f"{mode}.key")
            lines.append(f"  {raw_key} = call ptr @__xcc_aot_tuple_get(ptr {raw}, i64 0)")
            raw = raw_key
        if enumerate_type is not None:
            if enumerate_start is None:
                self._error("Malformed __enumerate generator")
            enumerate_index = index
            if enumerate_start.value != "0":
                enumerate_index = self._tmp(f"{mode}.enumindex")
                lines.append(f"  {enumerate_index} = add i64 {index}, {enumerate_start.value}")
            item = self._emit_enumerate_pair_tuple(
                enumerate_type,
                enumerate_index,
                raw,
                lines,
            )
        else:
            item = self._emit_runtime_boxed_value(raw, marker.type, lines)
        predicate_names = dict(names)
        if "," in marker.name:
            self._bind_emitted_tuple_target(
                marker.name,
                item,
                predicate_names,
                lines,
            )
        else:
            predicate_names[marker.name] = item
        self._emit_comprehension_filter(
            level_predicate,
            predicate_names,
            next_label,
            mode,
            lines,
        )
        if level + 1 < len(generators):
            self._emit_nested_generator_predicate_level(
                expr,
                generators,
                level + 1,
                predicate_names,
                result_ptr,
                result_label,
                lines,
            )
            lines.append(f"  br label %{next_label}")
        else:
            predicate = self._coerce_to_bool(
                self._emit_expr(expr.args[-1], predicate_names, lines),
                lines,
            )
            stop_label = self._label(f"{mode}.stop")
            if mode == "any":
                lines.append(f"  br i1 {predicate.value}, label %{stop_label}, label %{next_label}")
                stopped_value = "true"
            else:
                lines.append(f"  br i1 {predicate.value}, label %{next_label}, label %{stop_label}")
                stopped_value = "false"
            lines.append(f"{stop_label}:")
            lines.append(f"  store i1 {stopped_value}, ptr {result_ptr}")
            lines.append(f"  br label %{result_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp(f"{mode}.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")

    def _emit_optional_box_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1 or not (
            _is_optional_bool_type(expr.type) or _is_optional_int_type(expr.type)
        ):
            self._error("__optional_box expects one optional scalar argument")
        value = self._emit_expr(expr.args[0], names, lines)
        if isinstance(value.type, IrNoneType):
            return _EmittedValue("null", expr.type)
        if _is_optional_bool_type(expr.type) and isinstance(value.type, IrBoolType):
            tag = self._tmp("optional.bool.tag")
            result = self._tmp("optional.bool")
            lines.append(f"  {tag} = select i1 {value.value}, i64 2, i64 1")
            lines.append(f"  {result} = inttoptr i64 {tag} to ptr")
            return _EmittedValue(result, expr.type)
        if _is_optional_int_type(expr.type) and isinstance(value.type, IrIntType):
            return _EmittedValue(self._box_object_value(value, lines), expr.type)
        self._error("__optional_box argument does not match its optional scalar type")

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
        if method == "clear":
            if len(expr.args) != 1:
                self._error("clear expects only a receiver")
            result = self._tmp("tuple")
            self.needs_runtime_prelude = True
            lines.append(f"  {result} = call ptr @__xcc_aot_tuple_clear(ptr {receiver.value})")
            result_type = expr.type if isinstance(expr.type, IrTupleType) else receiver.type
            return _EmittedValue(result, result_type)
        if method == "pop":
            if len(expr.args) != 1:
                self._error("pop expects only a receiver")
            result = self._tmp("tuple")
            self.needs_runtime_prelude = True
            lines.append(f"  {result} = call ptr @__xcc_aot_tuple_pop(ptr {receiver.value})")
            lines.append(
                f"  call void @__xcc_aot_tuple_forward(ptr {receiver.value}, ptr {result})"
            )
            result_type = expr.type if isinstance(expr.type, IrTupleType) else receiver.type
            if isinstance(expr.type, IrNoneType):
                return _EmittedValue("null", expr.type)
            return _EmittedValue(receiver.value, result_type)
        if len(expr.args) != 2:
            self._error(f"{method} expects receiver and one argument")
        result_type = expr.type if isinstance(expr.type, IrTupleType) else receiver.type
        if method == "append":
            item = self._emit_expr(expr.args[1], names, lines)
            boxed_item = self._box_to_runtime_ptr(item, lines)
            result = self._tmp("tuple")
            self.needs_runtime_prelude = True
            lines.append(
                f"  {result} = call ptr @__xcc_aot_tuple_append("
                f"ptr {receiver.value}, ptr {boxed_item})"
            )
            lines.append(
                f"  call void @__xcc_aot_tuple_forward(ptr {receiver.value}, ptr {result})"
            )
            return _EmittedValue(receiver.value, result_type)
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
            lines.append(
                f"  call void @__xcc_aot_tuple_forward(ptr {receiver.value}, ptr {result})"
            )
            return _EmittedValue(receiver.value, result_type)
        item = self._emit_expr(expr.args[1], names, lines)
        singleton = self._runtime_singleton_tuple(item, lines)
        result = self._tmp("tuple")
        self.needs_runtime_prelude = True
        lines.append(
            f"  {result} = call ptr @__xcc_aot_tuple_concat(ptr {receiver.value}, ptr {singleton})"
        )
        lines.append(f"  call void @__xcc_aot_tuple_forward(ptr {receiver.value}, ptr {result})")
        return _EmittedValue(receiver.value, result_type)

    def _emit_tuple_pop_item_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__tuple_pop_item expects a receiver and index")
        receiver = self._emit_expr(expr.args[0], names, lines)
        index = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(receiver.type, IrTupleType):
            self._error("__tuple_pop_item expects a tuple-backed receiver")
        if not isinstance(index.type, IrIntType):
            self._error("__tuple_pop_item expects an integer index")
        self.needs_runtime_prelude = True
        raw = self._tmp("tuplepopitem")
        lines.append(
            f"  {raw} = call ptr @__xcc_aot_tuple_pop_item(ptr {receiver.value}, i64 {index.value})"
        )
        return self._emit_runtime_boxed_value(raw, expr.type, lines)

    def _emit_tuple_set_slice_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 6:
            self._error("__tuple_set_slice expects a receiver, bounds, and replacement")
        receiver = self._emit_expr(expr.args[0], names, lines)
        start = self._emit_expr(expr.args[1], names, lines)
        has_start = self._emit_expr(expr.args[2], names, lines)
        stop = self._emit_expr(expr.args[3], names, lines)
        has_stop = self._emit_expr(expr.args[4], names, lines)
        replacement = self._emit_expr(expr.args[5], names, lines)
        if not isinstance(receiver.type, IrTupleType) or not isinstance(
            replacement.type,
            IrTupleType,
        ):
            self._error("__tuple_set_slice expects tuple-backed values")
        if not isinstance(start.type, IrIntType) or not isinstance(stop.type, IrIntType):
            self._error("__tuple_set_slice expects integer bounds")
        if not isinstance(has_start.type, IrBoolType) or not isinstance(
            has_stop.type,
            IrBoolType,
        ):
            self._error("__tuple_set_slice expects boolean bound-presence flags")
        int64 = IrIntType(64, signed=True)
        start = self._adapt_integer_width(start, int64, lines)
        stop = self._adapt_integer_width(stop, int64, lines)
        self.needs_runtime_prelude = True
        result = self._tmp("tuplesetlice")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_tuple_set_slice("
            f"ptr {receiver.value}, i64 {start.value}, i1 {has_start.value}, "
            f"i64 {stop.value}, i1 {has_stop.value}, "
            f"ptr {replacement.value})"
        )
        return _EmittedValue(result, expr.type)

    def _emit_tuple_remove_item_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__tuple_remove_item expects a receiver and item")
        receiver = self._emit_expr(expr.args[0], names, lines)
        needle = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(receiver.type, IrTupleType):
            self._error("__tuple_remove_item expects a tuple-backed receiver")
        item_type = _homogeneous_tuple_element_type(receiver.type) or needle.type
        self.needs_runtime_prelude = True
        index_ptr = self._tmp("tupleremove.indexptr")
        cond_label = self._label("tupleremove.cond")
        body_label = self._label("tupleremove.body")
        found_label = self._label("tupleremove.found")
        next_label = self._label("tupleremove.next")
        end_label = self._label("tupleremove.end")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("tupleremove.index")
        length = self._tmp("tupleremove.len")
        done = self._tmp("tupleremove.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {receiver.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        raw_item = self._tmp("tupleremove.item")
        lines.append(
            f"  {raw_item} = call ptr @__xcc_aot_tuple_get(ptr {receiver.value}, i64 {index})"
        )
        item = self._emit_runtime_boxed_value(raw_item, item_type, lines)
        match = self._emit_equality_compare(needle, item, negate=False, lines=lines)
        lines.append(f"  br i1 {match.value}, label %{found_label}, label %{next_label}")
        lines.append(f"{found_label}:")
        removed = self._tmp("tupleremove.removed")
        lines.append(
            f"  {removed} = call ptr @__xcc_aot_tuple_pop_item(ptr {receiver.value}, i64 {index})"
        )
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("tupleremove.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        return _EmittedValue("null", expr.type)

    def _runtime_singleton_tuple(self, item: _EmittedValue, lines: list[str]) -> str:
        result = self._tmp("tuple")
        boxed = self._box_to_runtime_ptr(item, lines)
        lines.append("  ; tuple-backed append singleton")
        lines.append(f"  {result} = call ptr @__xcc_aot_tuple_new(i64 1)")
        lines.append(f"  call void @__xcc_aot_tuple_set(ptr {result}, i64 0, ptr {boxed})")
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

    def _emit_complex_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__complex expects two arguments")
        real = self._emit_expr(expr.args[0], names, lines)
        imaginary = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(real.type, IrFloatType) or not isinstance(
            imaginary.type,
            IrFloatType,
        ):
            self._error("__complex expects float arguments")
        if not isinstance(expr.type, IrRecordType) or expr.type.name != "complex":
            self._error("__complex expects an opaque complex result")
        self.needs_runtime_prelude = True
        result = self._tmp("complex")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_complex_new("
            f"double {real.value}, double {imaginary.value})"
        )
        return _EmittedValue(result, expr.type)

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

    def _emit_int_format_hex2_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__int_format_hex2 expects a value and case flag")
        value = self._emit_expr(expr.args[0], names, lines)
        uppercase = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(value.type, IrIntType):
            self._error("__int_format_hex2 expects an integer value")
        if not isinstance(uppercase.type, IrBoolType):
            self._error("__int_format_hex2 expects a boolean case flag")
        if not isinstance(expr.type, IrStringType):
            self._error("__int_format_hex2 expects a string result")
        value = self._adapt_integer_width(
            value,
            IrIntType(64, signed=value.type.signed),
            lines,
        )
        self.needs_runtime_prelude = True
        result = self._tmp("formathex")
        lines.append(
            f"  {result} = call ptr @__xcc_aot_i64_format_hex2("
            f"i64 {value.value}, i1 {uppercase.value})"
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

    def _emit_path_write_text_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__path_write_text expects path and text arguments")
        path = self._emit_expr(expr.args[0], names, lines)
        value = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(path.type, IrRecordType) or not isinstance(value.type, IrStringType):
            self._error("__path_write_text expects path and string values")
        if not isinstance(expr.type, IrIntType) or expr.type.bits != 64:
            self._error("__path_write_text expects an int64 result")
        self.needs_runtime_prelude = True
        written = self._tmp("pathwritten")
        length = self._tmp("pathlength")
        result = self._tmp("pathwriteresult")
        lines.append(
            f"  {written} = call i1 @__xcc_aot_write_text_file(ptr {path.value}, ptr {value.value})"
        )
        lines.append(f"  {length} = call i64 @strlen(ptr {value.value})")
        lines.append(f"  {result} = select i1 {written}, i64 {length}, i64 -1")
        return _EmittedValue(result, expr.type)

    def _emit_exec_argv_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 1:
            self._error("__exec_argv expects one tuple argument")
        argv = self._emit_expr(expr.args[0], names, lines)
        if not isinstance(argv.type, IrTupleType):
            self._error("__exec_argv expects a tuple-backed argv")
        if not isinstance(expr.type, IrIntType) or expr.type.bits != 32:
            self._error("__exec_argv expects an int32 result")
        self.needs_runtime_prelude = True
        result = self._tmp("execstatus")
        lines.append(f"  {result} = call i32 @__xcc_aot_execvp_tuple(ptr {argv.value})")
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

    def _emit_set_binary_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error(f"{expr.target} expects two arguments")
        left = self._emit_expr(expr.args[0], names, lines)
        right = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(left.type, IrTupleType) or not isinstance(right.type, IrTupleType):
            self._error(f"{expr.target} expects tuple-backed sets")
        if not isinstance(expr.type, IrTupleType) or len(expr.type.elements) != 1:
            self._error(f"{expr.target} expects a homogeneous tuple result")
        item_type = expr.type.elements[0]
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("setop.resultptr")
        empty = self._tmp("setop.empty")
        lines.append(f"  {result_ptr} = alloca ptr")
        lines.append(f"  {empty} = call ptr @__xcc_aot_tuple_new(i64 0)")
        lines.append(f"  store ptr {empty}, ptr {result_ptr}")
        if expr.target in {"__set_union", "__set_update"}:
            self._emit_set_binary_phase(
                left,
                None,
                "unique",
                item_type,
                expr.type,
                result_ptr,
                names,
                lines,
            )
            self._emit_set_binary_phase(
                right,
                None,
                "unique",
                item_type,
                expr.type,
                result_ptr,
                names,
                lines,
            )
        elif expr.target == "__set_intersection":
            self._emit_set_binary_phase(
                left,
                right,
                "present",
                item_type,
                expr.type,
                result_ptr,
                names,
                lines,
            )
        elif expr.target in {"__set_difference", "__set_difference_update"}:
            self._emit_set_binary_phase(
                left,
                right,
                "absent",
                item_type,
                expr.type,
                result_ptr,
                names,
                lines,
            )
        else:
            self._emit_set_binary_phase(
                left,
                right,
                "absent",
                item_type,
                expr.type,
                result_ptr,
                names,
                lines,
            )
            self._emit_set_binary_phase(
                right,
                left,
                "absent",
                item_type,
                expr.type,
                result_ptr,
                names,
                lines,
            )
        result = self._tmp("setop")
        lines.append(f"  {result} = load ptr, ptr {result_ptr}")
        if expr.target in {"__set_difference_update", "__set_update"}:
            lines.append(f"  call void @__xcc_aot_tuple_forward(ptr {left.value}, ptr {result})")
            return _EmittedValue(left.value, expr.type)
        return _EmittedValue(result, expr.type)

    def _emit_set_add_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__set_add expects a receiver and one item")
        receiver = self._emit_expr(expr.args[0], names, lines)
        item = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(receiver.type, IrTupleType):
            self._error("__set_add expects a tuple-backed set")
        if not isinstance(expr.type, IrTupleType):
            self._error("__set_add expects a tuple-backed set result")
        item_name = f"__setadd_item_{self.index}"
        receiver_name = f"__setadd_receiver_{self.index}"
        membership_names = dict(names)
        membership_names[item_name] = item
        membership_names[receiver_name] = receiver
        member = self._emit_tuple_membership(
            IrName(item_name, item.type),
            IrName(receiver_name, receiver.type),
            membership_names,
            lines,
            negate=False,
        )
        keep_label = self._label("setadd.keep")
        append_label = self._label("setadd.append")
        end_label = self._label("setadd.end")
        lines.append(f"  br i1 {member.value}, label %{keep_label}, label %{append_label}")
        lines.append(f"{keep_label}:")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{append_label}:")
        appended = self._tmp("setadd.appended")
        lines.append(
            f"  {appended} = call ptr @__xcc_aot_tuple_append("
            f"ptr {receiver.value}, ptr {self._box_to_runtime_ptr(item, lines)})"
        )
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        return _EmittedValue(receiver.value, expr.type)

    def _emit_set_equality_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__set_equal expects two arguments")
        left = self._emit_expr(expr.args[0], names, lines)
        right = self._emit_expr(expr.args[1], names, lines)
        if not isinstance(left.type, IrTupleType) or not isinstance(right.type, IrTupleType):
            self._error("__set_equal expects tuple-backed sets")
        if not isinstance(expr.type, IrBoolType):
            self._error("__set_equal expects a bool result")
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("seteq.resultptr")
        lines.append(f"  {result_ptr} = alloca i1")
        lines.append(f"  store i1 true, ptr {result_ptr}")
        self._emit_set_equality_phase(left, right, result_ptr, names, lines)
        self._emit_set_equality_phase(right, left, result_ptr, names, lines)
        result = self._tmp("seteq")
        lines.append(f"  {result} = load i1, ptr {result_ptr}")
        return _EmittedValue(result, IrBoolType())

    def _emit_set_equality_phase(
        self,
        values: _EmittedValue,
        other: _EmittedValue,
        result_ptr: str,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> None:
        if not isinstance(values.type, IrTupleType) or not isinstance(other.type, IrTupleType):
            self._error("set equality phase expects tuple-backed sets")
        if not values.type.elements:
            return
        item_type = _homogeneous_tuple_element_type(values.type) or IrRecordType("object")
        index_ptr = self._tmp("seteq.indexptr")
        cond_label = self._label("seteq.cond")
        body_label = self._label("seteq.body")
        next_label = self._label("seteq.next")
        mismatch_label = self._label("seteq.mismatch")
        end_label = self._label("seteq.end")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("seteq.index")
        length = self._tmp("seteq.len")
        done = self._tmp("seteq.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {values.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        raw = self._tmp("seteq.item")
        lines.append(f"  {raw} = call ptr @__xcc_aot_tuple_get(ptr {values.value}, i64 {index})")
        item = self._emit_runtime_boxed_value(raw, item_type, lines)
        item_name = f"__seteq_item_{self.index}"
        other_name = f"__seteq_other_{self.index}"
        membership_names = dict(names)
        membership_names[item_name] = item
        membership_names[other_name] = other
        member = self._emit_tuple_membership(
            IrName(item_name, item_type),
            IrName(other_name, other.type),
            membership_names,
            lines,
            negate=False,
        )
        lines.append(f"  br i1 {member.value}, label %{next_label}, label %{mismatch_label}")
        lines.append(f"{mismatch_label}:")
        lines.append(f"  store i1 false, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("seteq.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")

    def _emit_set_binary_phase(
        self,
        iterable: _EmittedValue,
        other: _EmittedValue | None,
        mode: str,
        item_type: IrType,
        result_type: IrTupleType,
        result_ptr: str,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> None:
        index_ptr = self._tmp("setop.indexptr")
        cond_label = self._label("setop.cond")
        body_label = self._label("setop.body")
        append_label = self._label("setop.append")
        next_label = self._label("setop.next")
        end_label = self._label("setop.end")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("setop.index")
        length = self._tmp("setop.len")
        done = self._tmp("setop.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {length} = call i64 @__xcc_aot_tuple_len(ptr {iterable.value})")
        lines.append(f"  {done} = icmp uge i64 {index}, {length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        raw = self._tmp("setop.item")
        lines.append(f"  {raw} = call ptr @__xcc_aot_tuple_get(ptr {iterable.value}, i64 {index})")
        item = self._emit_runtime_boxed_value(raw, item_type, lines)
        current = self._tmp("setop.current")
        lines.append(f"  {current} = load ptr, ptr {result_ptr}")
        item_name = f"__setop_item_{self.index}"
        result_name = f"__setop_result_{self.index}"
        membership_names = dict(names)
        membership_names[item_name] = item
        membership_names[result_name] = _EmittedValue(current, result_type)
        unique = self._emit_tuple_membership(
            IrName(item_name, item_type),
            IrName(result_name, result_type),
            membership_names,
            lines,
            negate=True,
        )
        should_append = unique
        if other is not None:
            other_name = f"__setop_other_{self.index}"
            membership_names[other_name] = other
            matches_other = self._emit_tuple_membership(
                IrName(item_name, item_type),
                IrName(other_name, other.type),
                membership_names,
                lines,
                negate=mode == "absent",
            )
            combined = self._tmp("setop.include")
            lines.append(f"  {combined} = and i1 {unique.value}, {matches_other.value}")
            should_append = _EmittedValue(combined, IrBoolType())
        lines.append(f"  br i1 {should_append.value}, label %{append_label}, label %{next_label}")
        lines.append(f"{append_label}:")
        singleton = self._runtime_singleton_tuple(item, lines)
        updated = self._tmp("setop.updated")
        lines.append(
            f"  {updated} = call ptr @__xcc_aot_tuple_concat(ptr {current}, ptr {singleton})"
        )
        lines.append(f"  store ptr {updated}, ptr {result_ptr}")
        lines.append(f"  br label %{next_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("setop.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")

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
            negative_label = self._label("stritem.negative")
            nonnegative_label = self._label("stritem.nonnegative")
            normalized_label = self._label("stritem.normalized")
            pointer = self._tmp("stritemptr")
            byte = self._tmp("stritem")
            result = self._tmp("stritem")
            lines.append(f"  {negative} = icmp slt i64 {index_value}, 0")
            lines.append(f"  br i1 {negative}, label %{negative_label}, label %{nonnegative_label}")
            lines.append(f"{negative_label}:")
            lines.append(f"  {length} = call i64 @strlen(ptr {value.value})")
            lines.append(f"  {wrapped} = add i64 {length}, {index_value}")
            lines.append(f"  br label %{normalized_label}")
            lines.append(f"{nonnegative_label}:")
            lines.append(f"  br label %{normalized_label}")
            lines.append(f"{normalized_label}:")
            lines.append(
                f"  {normalized} = phi i64 [ {wrapped}, %{negative_label} ], "
                f"[ {index_value}, %{nonnegative_label} ]"
            )
            lines.append(f"  {pointer} = getelementptr i8, ptr {value.value}, i64 {normalized}")
            lines.append(f"  {byte} = load i8, ptr {pointer}")
            lines.append(f"  {result} = call ptr @__xcc_aot_single_byte_string(i8 {byte})")
            return _EmittedValue(result, expr.type)
        if isinstance(value.type, IrBytesType):
            if not isinstance(expr.type, IrIntType):
                self._error("bytes __getitem expects an integer result")
            wide = self._tmp("bytesitem")
            lines.append(
                f"  {wide} = call i64 @__xcc_aot_bytes_get(ptr {value.value}, i64 {index_value})"
            )
            if expr.type.bits == 64:
                return _EmittedValue(wide, expr.type)
            result = self._tmp("bytesitem.cast")
            operation = "trunc" if expr.type.bits < 64 else "zext"
            lines.append(f"  {result} = {operation} i64 {wide} to {self._llvm_type(expr.type)}")
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
        if isinstance(needle.type, IrStringType):
            self.extra_declarations.add("declare ptr @strstr(ptr, ptr)")
            found = self._tmp("contains.substring")
            result = self._tmp("contains")
            lines.append(f"  {found} = call ptr @strstr(ptr {haystack.value}, ptr {needle.value})")
            lines.append(f"  {result} = icmp ne ptr {found}, null")
            membership = _EmittedValue(result, IrBoolType())
            if negate:
                return self._emit_bool_not(membership, lines)
            return membership
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

    def _emit_ifexp_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 3:
            self._error("__ifexp expects three arguments")
        condition = self._coerce_to_bool(self._emit_expr(expr.args[0], names, lines), lines)
        true_label = self._label("ifexp.true")
        false_label = self._label("ifexp.false")
        end_label = self._label("ifexp.end")
        lines.append(f"  br i1 {condition.value}, label %{true_label}, label %{false_label}")
        lines.append(f"{true_label}:")
        true_value = self._emit_expr(expr.args[1], names, lines)
        true_result = self._value_for_result_type(true_value, expr.type, lines)
        true_source = _current_label(lines)
        lines.append(f"  br label %{end_label}")
        lines.append(f"{false_label}:")
        false_value = self._emit_expr(expr.args[2], names, lines)
        false_result = self._value_for_result_type(false_value, expr.type, lines)
        false_source = _current_label(lines)
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        if isinstance(expr.type, IrNoneType):
            return _EmittedValue("null", expr.type)
        result = self._tmp("ifexp")
        lines.append(
            f"  {result} = phi {self._llvm_type(expr.type)} "
            f"[ {true_result}, %{true_source} ], [ {false_result}, %{false_source} ]"
        )
        return _EmittedValue(result, expr.type)

    def _emit_value_or_call(
        self,
        expr: IrCall,
        names: dict[str, _EmittedValue],
        lines: list[str],
    ) -> _EmittedValue:
        if len(expr.args) != 2:
            self._error("__value_or expects two arguments")
        left = self._emit_expr(expr.args[0], names, lines)
        condition = self._coerce_to_bool(left, lines)
        true_label = self._label("value.or.true")
        false_label = self._label("value.or.false")
        end_label = self._label("value.or.end")
        lines.append(f"  br i1 {condition.value}, label %{true_label}, label %{false_label}")
        lines.append(f"{true_label}:")
        narrowed = self._emit_runtime_object_narrowing(left, expr.type, lines)
        true_value = left if narrowed is None else narrowed
        true_result = self._value_for_result_type(true_value, expr.type, lines)
        true_source = _current_label(lines)
        lines.append(f"  br label %{end_label}")
        lines.append(f"{false_label}:")
        false_value = self._emit_expr(expr.args[1], names, lines)
        false_result = self._value_for_result_type(false_value, expr.type, lines)
        false_source = _current_label(lines)
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        if isinstance(expr.type, IrNoneType):
            return _EmittedValue("null", expr.type)
        result = self._tmp("value.or")
        lines.append(
            f"  {result} = phi {self._llvm_type(expr.type)} "
            f"[ {true_result}, %{true_source} ], [ {false_result}, %{false_source} ]"
        )
        return _EmittedValue(result, expr.type)

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
        if _is_opaque_object_type(value.type):
            if _is_opaque_object_type(requested_type) or isinstance(requested_type, IrNoneType):
                return value
            payload = self._tmp("object.payload")
            lines.append(f"  {payload} = getelementptr i8, ptr {value.value}, i64 8")
            if isinstance(requested_type, IrIntType):
                integer = self._tmp("object.int")
                lines.append(f"  {integer} = load i64, ptr {payload}")
                if requested_type.bits == 64:
                    return _EmittedValue(integer, requested_type)
                result = self._tmp("object.int")
                if requested_type.bits < 64:
                    lines.append(
                        f"  {result} = trunc i64 {integer} to {self._llvm_type(requested_type)}"
                    )
                else:
                    opcode = "sext" if requested_type.signed else "zext"
                    lines.append(
                        f"  {result} = {opcode} i64 {integer} to {self._llvm_type(requested_type)}"
                    )
                return _EmittedValue(result, requested_type)
            if isinstance(requested_type, IrBoolType):
                integer = self._tmp("object.bool")
                result = self._tmp("object.bool")
                lines.append(f"  {integer} = load i64, ptr {payload}")
                lines.append(f"  {result} = icmp ne i64 {integer}, 0")
                return _EmittedValue(result, requested_type)
            if isinstance(requested_type, IrFloatType):
                result = self._tmp("object.float")
                lines.append(f"  {result} = load double, ptr {payload}")
                return _EmittedValue(result, requested_type)
            if _is_pointer_type(requested_type):
                result = self._tmp("object.pointer")
                lines.append(f"  {result} = load ptr, ptr {payload}")
                return _EmittedValue(result, requested_type)
            return None
        if value.type.name != "object" and not _record_union_can_runtime_narrow(
            value.type.name,
            requested_type,
        ):
            return None
        if isinstance(requested_type, IrIntType):
            if _is_optional_int_type(value.type):
                payload = self._tmp("optional.int.payload")
                integer = self._tmp("optional.int")
                lines.append(f"  {payload} = getelementptr i8, ptr {value.value}, i64 8")
                lines.append(f"  {integer} = load i64, ptr {payload}")
                if requested_type.bits == 64:
                    return _EmittedValue(integer, requested_type)
                result = self._tmp("optional.int.cast")
                opcode = (
                    "trunc"
                    if requested_type.bits < 64
                    else ("sext" if requested_type.signed else "zext")
                )
                lines.append(
                    f"  {result} = {opcode} i64 {integer} to {self._llvm_type(requested_type)}"
                )
                return _EmittedValue(result, requested_type)
            result = self._tmp("narrowint")
            lines.append(
                f"  {result} = ptrtoint ptr {value.value} to {self._llvm_type(requested_type)}"
            )
            return _EmittedValue(result, requested_type)
        if isinstance(requested_type, IrBoolType):
            if _is_optional_bool_type(value.type):
                tag = self._tmp("optional.bool.tag")
                result = self._tmp("narrowbool")
                lines.append(f"  {tag} = ptrtoint ptr {value.value} to i64")
                lines.append(f"  {result} = icmp eq i64 {tag}, 2")
                return _EmittedValue(result, requested_type)
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
        if _is_optional_bool_type(value.type):
            tag = self._tmp("optional.bool.tag")
            result = self._tmp("truth")
            lines.append(f"  {tag} = ptrtoint ptr {value.value} to i64")
            lines.append(f"  {result} = icmp eq i64 {tag}, 2")
            return _EmittedValue(result, IrBoolType())
        if _is_optional_int_type(value.type):
            present = self._tmp("optional.int.present")
            present_label = self._label("optional.int.present")
            end_label = self._label("optional.int.truth.end")
            payload = self._tmp("optional.int.payload")
            integer = self._tmp("optional.int")
            nonzero = self._tmp("optional.int.nonzero")
            source_label = _current_label(lines)
            lines.append(f"  {present} = icmp ne ptr {value.value}, null")
            lines.append(f"  br i1 {present}, label %{present_label}, label %{end_label}")
            lines.append(f"{present_label}:")
            lines.append(f"  {payload} = getelementptr i8, ptr {value.value}, i64 8")
            lines.append(f"  {integer} = load i64, ptr {payload}")
            lines.append(f"  {nonzero} = icmp ne i64 {integer}, 0")
            lines.append(f"  br label %{end_label}")
            lines.append(f"{end_label}:")
            result = self._tmp("truth")
            lines.append(
                f"  {result} = phi i1 [ false, %{source_label} ], [ {nonzero}, %{present_label} ]"
            )
            return _EmittedValue(result, IrBoolType())
        if isinstance(value.type, IrRecordType) and value.type.name == "complex":
            real = self._tmp("complex.real")
            imaginary_pointer = self._tmp("complex.imagptr")
            imaginary = self._tmp("complex.imag")
            real_nonzero = self._tmp("complex.real_nonzero")
            imaginary_nonzero = self._tmp("complex.imag_nonzero")
            result = self._tmp("truth")
            lines.append(f"  {real} = load double, ptr {value.value}")
            lines.append(f"  {imaginary_pointer} = getelementptr i8, ptr {value.value}, i64 8")
            lines.append(f"  {imaginary} = load double, ptr {imaginary_pointer}")
            lines.append(f"  {real_nonzero} = fcmp une double {real}, 0.0")
            lines.append(f"  {imaginary_nonzero} = fcmp une double {imaginary}, 0.0")
            lines.append(f"  {result} = or i1 {real_nonzero}, {imaginary_nonzero}")
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
        if _is_optional_int_type(value.type):
            present = self._tmp("optional.int.ptr.present")
            present_label = self._label("optional.int.ptr.present")
            absent_label = self._label("optional.int.ptr.absent")
            end_label = self._label("optional.int.ptr.end")
            payload = self._tmp("optional.int.payload")
            integer = self._tmp("optional.int")
            pointer = self._tmp("optional.int.ptr")
            result = self._tmp("optional.int.ptr")
            lines.append(f"  {present} = icmp ne ptr {value.value}, null")
            lines.append(f"  br i1 {present}, label %{present_label}, label %{absent_label}")
            lines.append(f"{present_label}:")
            lines.append(f"  {payload} = getelementptr i8, ptr {value.value}, i64 8")
            lines.append(f"  {integer} = load i64, ptr {payload}")
            lines.append(f"  {pointer} = inttoptr i64 {integer} to ptr")
            lines.append(f"  br label %{end_label}")
            lines.append(f"{absent_label}:")
            lines.append(f"  br label %{end_label}")
            lines.append(f"{end_label}:")
            lines.append(
                f"  {result} = phi ptr [ {pointer}, %{present_label} ], [ null, %{absent_label} ]"
            )
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
        if _is_opaque_object_type(value.type):
            payload = self._tmp("index.payload")
            result = self._tmp("index")
            lines.append(f"  {payload} = getelementptr i8, ptr {value.value}, i64 8")
            lines.append(f"  {result} = load i64, ptr {payload}")
            return result
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
        if _is_opaque_object_type(left.type) and isinstance(right.type, IrBoolType):
            return self._emit_tagged_object_bool_identity(left, right, negate, lines)
        if _is_opaque_object_type(right.type) and isinstance(left.type, IrBoolType):
            return self._emit_tagged_object_bool_identity(right, left, negate, lines)
        predicate = "ne" if negate else "eq"
        result = self._tmp("is")
        left_optional_tag = self._optional_bool_tag(left, lines)
        right_optional_tag = self._optional_bool_tag(right, lines)
        if left_optional_tag is not None and right_optional_tag is not None:
            lines.append(
                f"  {result} = icmp {predicate} i64 {left_optional_tag}, {right_optional_tag}"
            )
            return _EmittedValue(result, IrBoolType())
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

    def _emit_optional_int_equality_compare(
        self,
        left: _EmittedValue,
        right: _EmittedValue,
        *,
        negate: bool,
        lines: list[str],
    ) -> _EmittedValue:
        if isinstance(left.type, IrIntType):
            left, right = right, left
        if not _is_optional_int_type(left.type):
            self._error("optional integer equality expects an optional integer operand")
        source_label = _current_label(lines)
        compare_label = self._label("optional.int.eq.compare")
        end_label = self._label("optional.int.eq.end")
        left_present = self._tmp("optional.int.eq.left.present")
        lines.append(f"  {left_present} = icmp ne ptr {left.value}, null")
        if isinstance(right.type, IrIntType):
            right_value = self._adapt_integer_width(
                right,
                IrIntType(64, signed=True),
                lines,
            )
            lines.append(f"  br i1 {left_present}, label %{compare_label}, label %{end_label}")
            lines.append(f"{compare_label}:")
            left_payload = self._tmp("optional.int.eq.left.payload")
            left_integer = self._tmp("optional.int.eq.left")
            compared = self._tmp("optional.int.eq")
            predicate = "ne" if negate else "eq"
            lines.append(f"  {left_payload} = getelementptr i8, ptr {left.value}, i64 8")
            lines.append(f"  {left_integer} = load i64, ptr {left_payload}")
            lines.append(f"  {compared} = icmp {predicate} i64 {left_integer}, {right_value.value}")
            lines.append(f"  br label %{end_label}")
            lines.append(f"{end_label}:")
            result = self._tmp("optional.int.eq")
            absent_result = "true" if negate else "false"
            lines.append(
                f"  {result} = phi i1 [ {absent_result}, %{source_label} ], "
                f"[ {compared}, %{compare_label} ]"
            )
            return _EmittedValue(result, IrBoolType())
        if not _is_optional_int_type(right.type):
            self._error("optional integer equality expects int or optional int operands")
        right_present = self._tmp("optional.int.eq.right.present")
        both_present = self._tmp("optional.int.eq.both.present")
        either_present = self._tmp("optional.int.eq.either.present")
        absent_equal = self._tmp("optional.int.eq.absent")
        lines.append(f"  {right_present} = icmp ne ptr {right.value}, null")
        lines.append(f"  {both_present} = and i1 {left_present}, {right_present}")
        lines.append(f"  {either_present} = or i1 {left_present}, {right_present}")
        lines.append(f"  {absent_equal} = xor i1 {either_present}, true")
        absent_result = absent_equal
        if negate:
            absent_result = self._tmp("optional.int.eq.absent.not")
            lines.append(f"  {absent_result} = xor i1 {absent_equal}, true")
        lines.append(f"  br i1 {both_present}, label %{compare_label}, label %{end_label}")
        lines.append(f"{compare_label}:")
        left_payload = self._tmp("optional.int.eq.left.payload")
        left_integer = self._tmp("optional.int.eq.left")
        right_payload = self._tmp("optional.int.eq.right.payload")
        right_integer = self._tmp("optional.int.eq.right")
        compared = self._tmp("optional.int.eq")
        predicate = "ne" if negate else "eq"
        lines.append(f"  {left_payload} = getelementptr i8, ptr {left.value}, i64 8")
        lines.append(f"  {left_integer} = load i64, ptr {left_payload}")
        lines.append(f"  {right_payload} = getelementptr i8, ptr {right.value}, i64 8")
        lines.append(f"  {right_integer} = load i64, ptr {right_payload}")
        lines.append(f"  {compared} = icmp {predicate} i64 {left_integer}, {right_integer}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("optional.int.eq")
        lines.append(
            f"  {result} = phi i1 [ {absent_result}, %{source_label} ], "
            f"[ {compared}, %{compare_label} ]"
        )
        return _EmittedValue(result, IrBoolType())

    def _emit_tagged_object_bool_identity(
        self,
        object_value: _EmittedValue,
        bool_value: _EmittedValue,
        negate: bool,
        lines: list[str],
    ) -> _EmittedValue:
        source_label = _current_label(lines)
        check_label = self._label("object.identity.check")
        payload_label = self._label("object.identity.payload")
        end_label = self._label("object.identity.end")
        nonnull = self._tmp("object.identity.nonnull")
        lines.append(f"  {nonnull} = icmp ne ptr {object_value.value}, null")
        lines.append(f"  br i1 {nonnull}, label %{check_label}, label %{end_label}")
        lines.append(f"{check_label}:")
        tag = self._tmp("object.identity.tag")
        is_bool = self._tmp("object.identity.isbool")
        lines.append(f"  {tag} = load i64, ptr {object_value.value}")
        lines.append(f"  {is_bool} = icmp eq i64 {tag}, {_OBJECT_TAG_BOOL}")
        lines.append(f"  br i1 {is_bool}, label %{payload_label}, label %{end_label}")
        lines.append(f"{payload_label}:")
        payload_pointer = self._tmp("object.identity.payloadptr")
        payload = self._tmp("object.identity.payload")
        expected = self._tmp("object.identity.expected")
        matches = self._tmp("object.identity.matches")
        lines.append(f"  {payload_pointer} = getelementptr i8, ptr {object_value.value}, i64 8")
        lines.append(f"  {payload} = load i64, ptr {payload_pointer}")
        lines.append(f"  {expected} = zext i1 {bool_value.value} to i64")
        lines.append(f"  {matches} = icmp eq i64 {payload}, {expected}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        raw_result = self._tmp("object.identity")
        lines.append(
            f"  {raw_result} = phi i1 [ false, %{source_label} ], "
            f"[ false, %{check_label} ], [ {matches}, %{payload_label} ]"
        )
        if not negate:
            return _EmittedValue(raw_result, IrBoolType())
        result = self._tmp("object.identity.not")
        lines.append(f"  {result} = xor i1 {raw_result}, true")
        return _EmittedValue(result, IrBoolType())

    def _emit_tagged_object_equality_compare(
        self,
        left: _EmittedValue,
        right: _EmittedValue,
        *,
        negate: bool,
        lines: list[str],
    ) -> _EmittedValue:
        self.needs_runtime_prelude = True
        self.needs_tagged_object_equality_helpers = True
        source_label = _current_label(lines)
        null_label = self._label("object.eq.null")
        tag_label = self._label("object.eq.tag")
        numeric_label = self._label("object.eq.numeric")
        same_tag_label = self._label("object.eq.same_tag")
        dispatch_label = self._label("object.eq.dispatch")
        float_label = self._label("object.eq.float")
        string_label = self._label("object.eq.string")
        bytes_label = self._label("object.eq.bytes")
        ellipsis_label = self._label("object.eq.ellipsis")
        tuple_label = self._label("object.eq.tuple")
        pointer_label = self._label("object.eq.pointer")
        end_label = self._label("object.eq.end")
        same = self._tmp("object.eq.same")
        lines.append(f"  {same} = icmp eq ptr {left.value}, {right.value}")
        lines.append(f"  br i1 {same}, label %{end_label}, label %{null_label}")
        lines.append(f"{null_label}:")
        left_nonnull = self._tmp("object.eq.left.nonnull")
        right_nonnull = self._tmp("object.eq.right.nonnull")
        both_nonnull = self._tmp("object.eq.both.nonnull")
        lines.append(f"  {left_nonnull} = icmp ne ptr {left.value}, null")
        lines.append(f"  {right_nonnull} = icmp ne ptr {right.value}, null")
        lines.append(f"  {both_nonnull} = and i1 {left_nonnull}, {right_nonnull}")
        lines.append(f"  br i1 {both_nonnull}, label %{tag_label}, label %{end_label}")
        lines.append(f"{tag_label}:")
        left_tag = self._tmp("object.eq.left.tag")
        right_tag = self._tmp("object.eq.right.tag")
        left_bool = self._tmp("object.eq.left.bool")
        left_int = self._tmp("object.eq.left.int")
        left_numeric = self._tmp("object.eq.left.numeric")
        right_bool = self._tmp("object.eq.right.bool")
        right_int = self._tmp("object.eq.right.int")
        right_numeric = self._tmp("object.eq.right.numeric")
        both_numeric = self._tmp("object.eq.both.numeric")
        lines.append(f"  {left_tag} = load i64, ptr {left.value}")
        lines.append(f"  {right_tag} = load i64, ptr {right.value}")
        lines.append(f"  {left_bool} = icmp eq i64 {left_tag}, {_OBJECT_TAG_BOOL}")
        lines.append(f"  {left_int} = icmp eq i64 {left_tag}, {_OBJECT_TAG_INT}")
        lines.append(f"  {left_numeric} = or i1 {left_bool}, {left_int}")
        lines.append(f"  {right_bool} = icmp eq i64 {right_tag}, {_OBJECT_TAG_BOOL}")
        lines.append(f"  {right_int} = icmp eq i64 {right_tag}, {_OBJECT_TAG_INT}")
        lines.append(f"  {right_numeric} = or i1 {right_bool}, {right_int}")
        lines.append(f"  {both_numeric} = and i1 {left_numeric}, {right_numeric}")
        lines.append(f"  br i1 {both_numeric}, label %{numeric_label}, label %{same_tag_label}")
        lines.append(f"{numeric_label}:")
        left_numeric_ptr = self._tmp("object.eq.left.numericptr")
        right_numeric_ptr = self._tmp("object.eq.right.numericptr")
        left_numeric_value = self._tmp("object.eq.left.numericvalue")
        right_numeric_value = self._tmp("object.eq.right.numericvalue")
        numeric_equal = self._tmp("object.eq.numeric")
        lines.append(f"  {left_numeric_ptr} = getelementptr i8, ptr {left.value}, i64 8")
        lines.append(f"  {right_numeric_ptr} = getelementptr i8, ptr {right.value}, i64 8")
        lines.append(f"  {left_numeric_value} = load i64, ptr {left_numeric_ptr}")
        lines.append(f"  {right_numeric_value} = load i64, ptr {right_numeric_ptr}")
        lines.append(f"  {numeric_equal} = icmp eq i64 {left_numeric_value}, {right_numeric_value}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{same_tag_label}:")
        same_tag = self._tmp("object.eq.same_tag")
        lines.append(f"  {same_tag} = icmp eq i64 {left_tag}, {right_tag}")
        lines.append(f"  br i1 {same_tag}, label %{dispatch_label}, label %{end_label}")
        lines.append(f"{dispatch_label}:")
        lines.append(f"  switch i64 {left_tag}, label %{pointer_label} [")
        lines.append(f"    i64 {_OBJECT_TAG_FLOAT}, label %{float_label}")
        lines.append(f"    i64 {_OBJECT_TAG_STRING}, label %{string_label}")
        lines.append(f"    i64 {_OBJECT_TAG_BYTES}, label %{bytes_label}")
        lines.append(f"    i64 {_OBJECT_TAG_ELLIPSIS}, label %{ellipsis_label}")
        lines.append(f"    i64 {_OBJECT_TAG_TUPLE}, label %{tuple_label}")
        lines.append("  ]")
        lines.append(f"{float_label}:")
        left_float_ptr = self._tmp("object.eq.left.floatptr")
        right_float_ptr = self._tmp("object.eq.right.floatptr")
        left_float = self._tmp("object.eq.left.float")
        right_float = self._tmp("object.eq.right.float")
        float_equal = self._tmp("object.eq.float")
        lines.append(f"  {left_float_ptr} = getelementptr i8, ptr {left.value}, i64 8")
        lines.append(f"  {right_float_ptr} = getelementptr i8, ptr {right.value}, i64 8")
        lines.append(f"  {left_float} = load double, ptr {left_float_ptr}")
        lines.append(f"  {right_float} = load double, ptr {right_float_ptr}")
        lines.append(f"  {float_equal} = fcmp oeq double {left_float}, {right_float}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{string_label}:")
        left_string_ptr = self._tmp("object.eq.left.stringptr")
        right_string_ptr = self._tmp("object.eq.right.stringptr")
        left_string = self._tmp("object.eq.left.string")
        right_string = self._tmp("object.eq.right.string")
        string_compared = self._tmp("object.eq.strcmp")
        string_equal = self._tmp("object.eq.string")
        lines.append(f"  {left_string_ptr} = getelementptr i8, ptr {left.value}, i64 8")
        lines.append(f"  {right_string_ptr} = getelementptr i8, ptr {right.value}, i64 8")
        lines.append(f"  {left_string} = load ptr, ptr {left_string_ptr}")
        lines.append(f"  {right_string} = load ptr, ptr {right_string_ptr}")
        lines.append(
            f"  {string_compared} = call i32 @strcmp(ptr {left_string}, ptr {right_string})"
        )
        lines.append(f"  {string_equal} = icmp eq i32 {string_compared}, 0")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{bytes_label}:")
        left_bytes_ptr = self._tmp("object.eq.left.bytesptr")
        right_bytes_ptr = self._tmp("object.eq.right.bytesptr")
        left_bytes = self._tmp("object.eq.left.bytes")
        right_bytes = self._tmp("object.eq.right.bytes")
        bytes_equal = self._tmp("object.eq.bytes")
        lines.append(f"  {left_bytes_ptr} = getelementptr i8, ptr {left.value}, i64 8")
        lines.append(f"  {right_bytes_ptr} = getelementptr i8, ptr {right.value}, i64 8")
        lines.append(f"  {left_bytes} = load ptr, ptr {left_bytes_ptr}")
        lines.append(f"  {right_bytes} = load ptr, ptr {right_bytes_ptr}")
        lines.append(
            f"  {bytes_equal} = call i1 @__xcc_aot_bytes_equal(ptr {left_bytes}, ptr {right_bytes})"
        )
        lines.append(f"  br label %{end_label}")
        lines.append(f"{ellipsis_label}:")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{tuple_label}:")
        left_tuple_ptr = self._tmp("object.eq.left.tupleptr")
        right_tuple_ptr = self._tmp("object.eq.right.tupleptr")
        left_tuple = self._tmp("object.eq.left.tuple")
        right_tuple = self._tmp("object.eq.right.tuple")
        tuple_equal = self._tmp("object.eq.tuple")
        lines.append(f"  {left_tuple_ptr} = getelementptr i8, ptr {left.value}, i64 8")
        lines.append(f"  {right_tuple_ptr} = getelementptr i8, ptr {right.value}, i64 8")
        lines.append(f"  {left_tuple} = load ptr, ptr {left_tuple_ptr}")
        lines.append(f"  {right_tuple} = load ptr, ptr {right_tuple_ptr}")
        lines.append(
            f"  {tuple_equal} = call i1 @__xcc_aot_object_tuple_equal("
            f"ptr {left_tuple}, ptr {right_tuple})"
        )
        lines.append(f"  br label %{end_label}")
        lines.append(f"{pointer_label}:")
        left_pointer_ptr = self._tmp("object.eq.left.pointerptr")
        right_pointer_ptr = self._tmp("object.eq.right.pointerptr")
        left_pointer = self._tmp("object.eq.left.pointer")
        right_pointer = self._tmp("object.eq.right.pointer")
        pointer_equal = self._tmp("object.eq.pointer")
        lines.append(f"  {left_pointer_ptr} = getelementptr i8, ptr {left.value}, i64 8")
        lines.append(f"  {right_pointer_ptr} = getelementptr i8, ptr {right.value}, i64 8")
        lines.append(f"  {left_pointer} = load ptr, ptr {left_pointer_ptr}")
        lines.append(f"  {right_pointer} = load ptr, ptr {right_pointer_ptr}")
        lines.append(f"  {pointer_equal} = icmp eq ptr {left_pointer}, {right_pointer}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{end_label}:")
        equal = self._tmp("object.eq")
        lines.append(
            f"  {equal} = phi i1 [ true, %{source_label} ], "
            f"[ false, %{null_label} ], [ {numeric_equal}, %{numeric_label} ], "
            f"[ false, %{same_tag_label} ], [ {float_equal}, %{float_label} ], "
            f"[ {string_equal}, %{string_label} ], [ {bytes_equal}, %{bytes_label} ], "
            f"[ true, %{ellipsis_label} ], [ {tuple_equal}, %{tuple_label} ], "
            f"[ {pointer_equal}, %{pointer_label} ]"
        )
        value = _EmittedValue(equal, IrBoolType())
        if negate:
            return self._emit_bool_not(value, lines)
        return value

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
        left_optional_tag = self._optional_bool_tag(left, lines)
        right_optional_tag = self._optional_bool_tag(right, lines)
        if (
            (_is_optional_bool_type(left.type) or _is_optional_bool_type(right.type))
            and left_optional_tag is not None
            and right_optional_tag is not None
        ):
            lines.append(
                f"  {result} = icmp {predicate} i64 {left_optional_tag}, {right_optional_tag}"
            )
            return _EmittedValue(result, IrBoolType())
        if (
            (_is_optional_int_type(left.type) and isinstance(right.type, IrIntType))
            or (isinstance(left.type, IrIntType) and _is_optional_int_type(right.type))
            or (_is_optional_int_type(left.type) and _is_optional_int_type(right.type))
        ):
            return self._emit_optional_int_equality_compare(
                left,
                right,
                negate=negate,
                lines=lines,
            )
        if _is_opaque_object_type(left.type) and _is_opaque_object_type(right.type):
            return self._emit_tagged_object_equality_compare(
                left,
                right,
                negate=negate,
                lines=lines,
            )
        if isinstance(left.type, IrIntType) and isinstance(right.type, IrIntType):
            lines.append(
                f"  {result} = icmp {predicate} {self._llvm_type(left.type)} "
                f"{left.value}, {right.value}"
            )
            return _EmittedValue(result, IrBoolType())
        if isinstance(left.type, IrBoolType) and isinstance(right.type, IrBoolType):
            lines.append(f"  {result} = icmp {predicate} i1 {left.value}, {right.value}")
            return _EmittedValue(result, IrBoolType())
        if isinstance(left.type, IrFloatType) and isinstance(right.type, IrFloatType):
            float_predicate = "une" if negate else "oeq"
            lines.append(f"  {result} = fcmp {float_predicate} double {left.value}, {right.value}")
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
        record_names = self._record_equality_names(left.type, right.type)
        if record_names:
            self.record_equality_records.update(record_names)
            equal = self._tmp("recordeq")
            lines.append(
                f"  {equal} = call i1 @__xcc_aot_record_equal(ptr {left.value}, ptr {right.value})"
            )
            value = _EmittedValue(equal, IrBoolType())
            if negate:
                return self._emit_bool_not(value, lines)
            return value
        left_value = self._pointer_compare_value(left)
        right_value = self._pointer_compare_value(right)
        lines.append(f"  {result} = icmp {predicate} ptr {left_value}, {right_value}")
        return _EmittedValue(result, IrBoolType())

    def _record_equality_names(self, left: IrType, right: IrType) -> tuple[str, ...]:
        left_names = self._known_record_type_names(left)
        right_names = self._known_record_type_names(right)
        if not left_names or not right_names:
            return ()
        return tuple(name for name in left_names if name in right_names)

    def _known_record_type_names(self, type_info: IrType) -> tuple[str, ...]:
        if not isinstance(type_info, IrRecordType):
            return ()
        names: list[str] = []
        for part in _record_union_parts(type_info.name):
            if part == "None":
                continue
            name = part if part in self.records else part.rsplit(".", 1)[-1]
            if name not in self.records:
                return ()
            if name not in names:
                names.append(name)
        return tuple(names)

    def _emit_record_equality_helpers(self) -> list[str]:
        if self.needs_tagged_object_equality_helpers:
            self.record_equality_records.update(self.tuple_object_equality_records)
        helpers: dict[str, str] = {}
        while True:
            pending = tuple(
                name for name in sorted(self.record_equality_records) if name not in helpers
            )
            if not pending:
                break
            for name in pending:
                helpers[name] = self._emit_record_equality_helper(name)
        if not helpers and not self.needs_tagged_object_equality_helpers:
            return []
        dispatcher = self._emit_record_equality_dispatcher(tuple(sorted(helpers)))
        return [dispatcher, *(helpers[name] for name in sorted(helpers))]

    def _emit_tagged_object_equality_helpers(self) -> list[str]:
        if not self.needs_tagged_object_equality_helpers:
            return []
        object_equal = "\n".join(
            (
                "define i1 @__xcc_aot_object_equal(ptr %left, ptr %right) {",
                "entry:",
                "  %same = icmp eq ptr %left, %right",
                "  br i1 %same, label %equal, label %check_null",
                "check_null:",
                "  %left_null = icmp eq ptr %left, null",
                "  %right_null = icmp eq ptr %right, null",
                "  %either_null = or i1 %left_null, %right_null",
                "  br i1 %either_null, label %unequal, label %check_tags",
                "check_tags:",
                "  %left_tag = load i64, ptr %left",
                "  %right_tag = load i64, ptr %right",
                f"  %left_bool = icmp eq i64 %left_tag, {_OBJECT_TAG_BOOL}",
                f"  %left_int = icmp eq i64 %left_tag, {_OBJECT_TAG_INT}",
                "  %left_numeric = or i1 %left_bool, %left_int",
                f"  %right_bool = icmp eq i64 %right_tag, {_OBJECT_TAG_BOOL}",
                f"  %right_int = icmp eq i64 %right_tag, {_OBJECT_TAG_INT}",
                "  %right_numeric = or i1 %right_bool, %right_int",
                "  %both_numeric = and i1 %left_numeric, %right_numeric",
                "  br i1 %both_numeric, label %numeric, label %same_tag",
                "numeric:",
                "  %left_numeric_ptr = getelementptr i8, ptr %left, i64 8",
                "  %right_numeric_ptr = getelementptr i8, ptr %right, i64 8",
                "  %left_numeric_value = load i64, ptr %left_numeric_ptr",
                "  %right_numeric_value = load i64, ptr %right_numeric_ptr",
                "  %numeric_equal = icmp eq i64 %left_numeric_value, %right_numeric_value",
                "  ret i1 %numeric_equal",
                "same_tag:",
                "  %tags_equal = icmp eq i64 %left_tag, %right_tag",
                "  br i1 %tags_equal, label %dispatch, label %unequal",
                "dispatch:",
                "  switch i64 %left_tag, label %pointer [",
                f"    i64 {_OBJECT_TAG_FLOAT}, label %float",
                f"    i64 {_OBJECT_TAG_STRING}, label %string",
                f"    i64 {_OBJECT_TAG_BYTES}, label %bytes",
                f"    i64 {_OBJECT_TAG_ELLIPSIS}, label %equal",
                f"    i64 {_OBJECT_TAG_RECORD}, label %record",
                f"    i64 {_OBJECT_TAG_TUPLE}, label %tuple",
                "  ]",
                "float:",
                "  %left_float_ptr = getelementptr i8, ptr %left, i64 8",
                "  %right_float_ptr = getelementptr i8, ptr %right, i64 8",
                "  %left_float = load double, ptr %left_float_ptr",
                "  %right_float = load double, ptr %right_float_ptr",
                "  %float_equal = fcmp oeq double %left_float, %right_float",
                "  ret i1 %float_equal",
                "string:",
                "  %left_string_ptr = getelementptr i8, ptr %left, i64 8",
                "  %right_string_ptr = getelementptr i8, ptr %right, i64 8",
                "  %left_string = load ptr, ptr %left_string_ptr",
                "  %right_string = load ptr, ptr %right_string_ptr",
                "  %string_compared = call i32 @strcmp(ptr %left_string, ptr %right_string)",
                "  %string_equal = icmp eq i32 %string_compared, 0",
                "  ret i1 %string_equal",
                "bytes:",
                "  %left_bytes_ptr = getelementptr i8, ptr %left, i64 8",
                "  %right_bytes_ptr = getelementptr i8, ptr %right, i64 8",
                "  %left_bytes = load ptr, ptr %left_bytes_ptr",
                "  %right_bytes = load ptr, ptr %right_bytes_ptr",
                (
                    "  %bytes_equal = call i1 @__xcc_aot_bytes_equal("
                    "ptr %left_bytes, ptr %right_bytes)"
                ),
                "  ret i1 %bytes_equal",
                "record:",
                "  %left_record_ptr = getelementptr i8, ptr %left, i64 8",
                "  %right_record_ptr = getelementptr i8, ptr %right, i64 8",
                "  %left_record = load ptr, ptr %left_record_ptr",
                "  %right_record = load ptr, ptr %right_record_ptr",
                (
                    "  %record_equal = call i1 @__xcc_aot_record_equal("
                    "ptr %left_record, ptr %right_record)"
                ),
                "  ret i1 %record_equal",
                "tuple:",
                "  %left_tuple_ptr = getelementptr i8, ptr %left, i64 8",
                "  %right_tuple_ptr = getelementptr i8, ptr %right, i64 8",
                "  %left_tuple = load ptr, ptr %left_tuple_ptr",
                "  %right_tuple = load ptr, ptr %right_tuple_ptr",
                (
                    "  %tuple_equal = call i1 @__xcc_aot_object_tuple_equal("
                    "ptr %left_tuple, ptr %right_tuple)"
                ),
                "  ret i1 %tuple_equal",
                "pointer:",
                "  %left_pointer_ptr = getelementptr i8, ptr %left, i64 8",
                "  %right_pointer_ptr = getelementptr i8, ptr %right, i64 8",
                "  %left_pointer = load ptr, ptr %left_pointer_ptr",
                "  %right_pointer = load ptr, ptr %right_pointer_ptr",
                "  %pointer_equal = icmp eq ptr %left_pointer, %right_pointer",
                "  ret i1 %pointer_equal",
                "equal:",
                "  ret i1 true",
                "unequal:",
                "  ret i1 false",
                "}",
            )
        )
        tuple_equal = "\n".join(
            (
                "define i1 @__xcc_aot_object_tuple_equal(ptr %left, ptr %right) {",
                "entry:",
                "  %same = icmp eq ptr %left, %right",
                "  br i1 %same, label %equal, label %check_null",
                "check_null:",
                "  %left_null = icmp eq ptr %left, null",
                "  %right_null = icmp eq ptr %right, null",
                "  %either_null = or i1 %left_null, %right_null",
                "  br i1 %either_null, label %unequal, label %lengths",
                "lengths:",
                "  %left_length = call i64 @__xcc_aot_tuple_len(ptr %left)",
                "  %right_length = call i64 @__xcc_aot_tuple_len(ptr %right)",
                "  %same_length = icmp eq i64 %left_length, %right_length",
                "  br i1 %same_length, label %loop, label %unequal",
                "loop:",
                "  %index = phi i64 [ 0, %lengths ], [ %next_index, %next ]",
                "  %done = icmp uge i64 %index, %left_length",
                "  br i1 %done, label %equal, label %body",
                "body:",
                "  %left_item = call ptr @__xcc_aot_tuple_get_object(ptr %left, i64 %index)",
                ("  %right_item = call ptr @__xcc_aot_tuple_get_object(ptr %right, i64 %index)"),
                (
                    "  %item_equal = call i1 @__xcc_aot_object_equal("
                    "ptr %left_item, ptr %right_item)"
                ),
                "  br i1 %item_equal, label %next, label %unequal",
                "next:",
                "  %next_index = add i64 %index, 1",
                "  br label %loop",
                "equal:",
                "  ret i1 true",
                "unequal:",
                "  ret i1 false",
                "}",
            )
        )
        return [object_equal, tuple_equal]

    def _emit_record_equality_dispatcher(self, record_names: tuple[str, ...]) -> str:
        lines = [
            "define i1 @__xcc_aot_record_equal(ptr %left, ptr %right) {",
            "entry:",
            "  %same = icmp eq ptr %left, %right",
            "  br i1 %same, label %equal, label %check_null",
            "check_null:",
            "  %left_null = icmp eq ptr %left, null",
            "  %right_null = icmp eq ptr %right, null",
            "  %either_null = or i1 %left_null, %right_null",
            "  br i1 %either_null, label %unequal, label %check_tags",
            "check_tags:",
            "  %left_tag_ptr = getelementptr i8, ptr %left, i64 -8",
            "  %right_tag_ptr = getelementptr i8, ptr %right, i64 -8",
            "  %left_tag = load i64, ptr %left_tag_ptr",
            "  %right_tag = load i64, ptr %right_tag_ptr",
            "  %same_tag = icmp eq i64 %left_tag, %right_tag",
            "  br i1 %same_tag, label %dispatch, label %unequal",
            "dispatch:",
            "  switch i64 %left_tag, label %unequal [",
        ]
        for name in record_names:
            lines.append(f"    i64 {self.record_type_ids[name]}, label %record.{name}")
        lines.append("  ]")
        for name in record_names:
            lines.extend(
                (
                    f"record.{name}:",
                    f"  %equal.{name} = call i1 @__xcc_aot_record_equal.{name}("
                    "ptr %left, ptr %right)",
                    f"  ret i1 %equal.{name}",
                )
            )
        lines.extend(("equal:", "  ret i1 true", "unequal:", "  ret i1 false", "}"))
        return "\n".join(lines)

    def _emit_record_equality_helper(self, record_name: str) -> str:
        record = self.records[record_name]
        lines = [
            f"define i1 @__xcc_aot_record_equal.{record_name}(ptr %left, ptr %right) {{",
            "entry:",
        ]
        result = _EmittedValue("true", IrBoolType())
        for index, field in enumerate(record.fields):
            left = self._emit_record_equality_field(
                record_name,
                field.type,
                index,
                "%left",
                "left",
                lines,
            )
            right = self._emit_record_equality_field(
                record_name,
                field.type,
                index,
                "%right",
                "right",
                lines,
            )
            field_equal = self._emit_equality_compare(
                left,
                right,
                negate=False,
                lines=lines,
            )
            combined = self._tmp("recordeq.fields")
            lines.append(f"  {combined} = and i1 {result.value}, {field_equal.value}")
            result = _EmittedValue(combined, IrBoolType())
        lines.extend((f"  ret i1 {result.value}", "}"))
        return "\n".join(lines)

    def _emit_record_equality_field(
        self,
        record_name: str,
        field_type: IrType,
        index: int,
        record_value: str,
        side: str,
        lines: list[str],
    ) -> _EmittedValue:
        field_pointer = self._tmp(f"recordeq.{side}.fieldptr")
        field_value = self._tmp(f"recordeq.{side}.field")
        lines.append(
            f"  {field_pointer} = getelementptr inbounds %{record_name}, "
            f"ptr {record_value}, i32 0, i32 {index}"
        )
        lines.append(
            f"  {field_value} = load {self._storage_llvm_type(field_type)}, ptr {field_pointer}"
        )
        return _EmittedValue(field_value, field_type)

    def _optional_bool_tag(
        self,
        value: _EmittedValue,
        lines: list[str],
    ) -> str | None:
        if isinstance(value.type, IrNoneType):
            return "0"
        if isinstance(value.type, IrBoolType):
            widened = self._tmp("optional.bool")
            tag = self._tmp("optional.bool.tag")
            lines.append(f"  {widened} = zext i1 {value.value} to i64")
            lines.append(f"  {tag} = add i64 {widened}, 1")
            return tag
        if _is_optional_bool_type(value.type):
            tag = self._tmp("optional.bool.tag")
            lines.append(f"  {tag} = ptrtoint ptr {value.value} to i64")
            return tag
        return None

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
        if isinstance(left.type, IrTupleType) and isinstance(right.type, IrTupleType):
            return self._emit_tuple_order_compare(target, left, right, lines)
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

    def _emit_tuple_order_compare(
        self,
        target: str,
        left: _EmittedValue,
        right: _EmittedValue,
        lines: list[str],
    ) -> _EmittedValue:
        left_item_type = _homogeneous_tuple_element_type(left.type)
        right_item_type = _homogeneous_tuple_element_type(right.type)
        if left_item_type is None or right_item_type is None:
            self._error(f"{target} expects homogeneous tuple arguments")
        if left_item_type != right_item_type:
            self._error(f"{target} expects matching tuple item types")
        length_predicate = {
            "__cmp_Gt": "ugt",
            "__cmp_GtE": "uge",
            "__cmp_Lt": "ult",
            "__cmp_LtE": "ule",
        }[target]
        self.needs_runtime_prelude = True
        result_ptr = self._tmp("tuplecmp.result")
        index_ptr = self._tmp("tuplecmp.index")
        left_length = self._tmp("tuplecmp.leftlen")
        right_length = self._tmp("tuplecmp.rightlen")
        left_shorter = self._tmp("tuplecmp.leftshorter")
        common_length = self._tmp("tuplecmp.commonlen")
        prefix_result = self._tmp("tuplecmp.prefix")
        cond_label = self._label("tuplecmp.cond")
        body_label = self._label("tuplecmp.body")
        next_label = self._label("tuplecmp.next")
        mismatch_label = self._label("tuplecmp.mismatch")
        end_label = self._label("tuplecmp.end")
        lines.append(f"  {result_ptr} = alloca i1")
        lines.append(f"  {index_ptr} = alloca i64")
        lines.append(f"  {left_length} = call i64 @__xcc_aot_tuple_len(ptr {left.value})")
        lines.append(f"  {right_length} = call i64 @__xcc_aot_tuple_len(ptr {right.value})")
        lines.append(f"  {left_shorter} = icmp ult i64 {left_length}, {right_length}")
        lines.append(
            f"  {common_length} = select i1 {left_shorter}, i64 {left_length}, i64 {right_length}"
        )
        lines.append(
            f"  {prefix_result} = icmp {length_predicate} i64 {left_length}, {right_length}"
        )
        lines.append(f"  store i1 {prefix_result}, ptr {result_ptr}")
        lines.append(f"  store i64 0, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{cond_label}:")
        index = self._tmp("tuplecmp.index")
        done = self._tmp("tuplecmp.done")
        lines.append(f"  {index} = load i64, ptr {index_ptr}")
        lines.append(f"  {done} = icmp uge i64 {index}, {common_length}")
        lines.append(f"  br i1 {done}, label %{end_label}, label %{body_label}")
        lines.append(f"{body_label}:")
        left_raw = self._tmp("tuplecmp.left")
        right_raw = self._tmp("tuplecmp.right")
        lines.append(f"  {left_raw} = call ptr @__xcc_aot_tuple_get(ptr {left.value}, i64 {index})")
        lines.append(
            f"  {right_raw} = call ptr @__xcc_aot_tuple_get(ptr {right.value}, i64 {index})"
        )
        left_item = self._emit_runtime_boxed_value(left_raw, left_item_type, lines)
        right_item = self._emit_runtime_boxed_value(right_raw, right_item_type, lines)
        item_equal = self._emit_equality_compare(
            left_item,
            right_item,
            negate=False,
            lines=lines,
        )
        lines.append(f"  br i1 {item_equal.value}, label %{next_label}, label %{mismatch_label}")
        lines.append(f"{mismatch_label}:")
        item_result = self._emit_order_compare(target, left_item, right_item, lines)
        lines.append(f"  store i1 {item_result.value}, ptr {result_ptr}")
        lines.append(f"  br label %{end_label}")
        lines.append(f"{next_label}:")
        next_index = self._tmp("tuplecmp.next")
        lines.append(f"  {next_index} = add i64 {index}, 1")
        lines.append(f"  store i64 {next_index}, ptr {index_ptr}")
        lines.append(f"  br label %{cond_label}")
        lines.append(f"{end_label}:")
        result = self._tmp("tuplecmp")
        lines.append(f"  {result} = load i1, ptr {result_ptr}")
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
        self.needs_runtime_prelude = True
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
        self.needs_runtime_prelude = True
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
        self._emit_phase_reset(lines)
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
        if _is_opaque_object_type(result_type):
            if lines is None:
                self._error(f"Cannot box {type(value.type).__name__} without an instruction block")
            return self._box_object_value(value, lines)
        if isinstance(value.type, IrNoneType):
            return self._default_value(result_type)
        if (
            lines is not None
            and isinstance(value.type, IrIntType)
            and _is_optional_int_type(result_type)
        ):
            return self._box_object_value(value, lines)
        if _is_pointer_type(value.type) and _is_pointer_type(result_type):
            return value.value
        if (
            lines is not None
            and isinstance(value.type, IrBoolType)
            and _is_optional_bool_type(result_type)
        ):
            tag = self._optional_bool_tag(value, lines)
            if tag is None:
                self._error("Cannot encode bool as optional bool")
            boxed = self._tmp("optional.bool.box")
            lines.append(f"  {boxed} = inttoptr i64 {tag} to ptr")
            return boxed
        if lines is not None and _is_pointer_type(result_type):
            return self._box_to_runtime_ptr(value, lines)
        self._error(f"Cannot store {type(value.type).__name__} as {type(result_type).__name__}")

    def _tuple_object_layout_constant(self, type_info: IrTupleType) -> str | None:
        if not type_info.elements:
            return None
        tags = tuple(self._object_storage_layout_tag(element) for element in type_info.elements)
        name = "@__xcc_aot_tuple_object_layout_" + "_".join(str(tag) for tag in tags)
        if name not in self.global_constants:
            values = ", ".join(f"i64 {tag}" for tag in tags)
            self.global_constants[name] = (
                f"{name} = private unnamed_addr constant [{len(tags)} x i64] [{values}], align 8"
            )
        return name

    def _collect_tuple_object_equality_records(self, type_info: IrType) -> None:
        if isinstance(type_info, IrTupleType):
            for element in type_info.elements:
                self._collect_tuple_object_equality_records(element)
            return
        self.tuple_object_equality_records.update(self._known_record_type_names(type_info))

    def _register_tuple_object_layout(
        self,
        value: str,
        type_info: IrType,
        lines: list[str],
    ) -> None:
        if not isinstance(type_info, IrTupleType):
            return
        self._collect_tuple_object_equality_records(type_info)
        layout = self._tuple_object_layout_constant(type_info)
        if layout is None:
            return
        lines.append(
            "  call void @__xcc_aot_tuple_object_layout_register("
            f"ptr {value}, i64 {len(type_info.elements)}, ptr {layout})"
        )

    def _object_storage_layout_tag(self, type_info: IrType) -> int:
        if isinstance(type_info, IrBoolType):
            return _OBJECT_TAG_BOOL
        if isinstance(type_info, IrIntType):
            return _OBJECT_TAG_INT
        if isinstance(type_info, IrFloatType):
            return _OBJECT_TAG_FLOAT
        if isinstance(type_info, IrStringType):
            return _OBJECT_TAG_STRING
        if isinstance(type_info, IrBytesType):
            return _OBJECT_TAG_BYTES
        if isinstance(type_info, IrDictType):
            return _OBJECT_TAG_DICT
        if isinstance(type_info, IrTupleType):
            return _OBJECT_TAG_TUPLE
        if isinstance(type_info, IrRecordType):
            if type_info.name == "object" or _is_optional_int_type(type_info):
                return 0
            if type_info.name == "complex":
                return _OBJECT_TAG_COMPLEX
            if type_info.name in self.records or _is_known_record_union_name(
                type_info.name,
                self.records,
            ):
                return _OBJECT_TAG_RECORD
        return 0

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


def _is_optional_bool_type(type_info: IrType) -> bool:
    return isinstance(type_info, IrRecordType) and {
        part.strip() for part in type_info.name.split("|")
    } == {"None", "bool"}


def _is_optional_int_type(type_info: IrType) -> bool:
    return isinstance(type_info, IrRecordType) and {
        part.strip() for part in type_info.name.split("|")
    } == {"None", "int"}


def _is_opaque_object_type(type_info: IrType) -> bool:
    if not isinstance(type_info, IrRecordType):
        return False
    if type_info.name == "object":
        return True
    parts = _record_union_parts(type_info.name)
    if len(parts) < 2:
        return False
    non_none_parts = tuple(part for part in parts if part != "None")
    if len(non_none_parts) == 1 and len(non_none_parts) != len(parts):
        return False
    scalar_parts = {"bool", "bytes", "float", "int", "str"}
    has_scalar = any(part in scalar_parts for part in non_none_parts)
    has_pointer = any(part not in scalar_parts for part in non_none_parts)
    return has_scalar and has_pointer


def _is_nullable_record_union(
    type_info: IrType,
    records: dict[str, IrRecord],
) -> bool:
    if not isinstance(type_info, IrRecordType):
        return False
    parts = _record_union_parts(type_info.name)
    if "None" not in parts:
        return False
    record_parts = tuple(part for part in parts if part != "None")
    return bool(record_parts) and all(
        _record_union_part_is_known(part, records) for part in record_parts
    )


def _static_builtin_isinstance_result(
    type_info: IrType,
    target_names: tuple[str, ...],
) -> bool | None:
    if not target_names:
        return None
    targets = set(target_names)
    if "object" in targets:
        return True
    accepted_targets: set[str] | None = None
    if isinstance(type_info, IrNoneType):
        accepted_targets = set()
    elif isinstance(type_info, IrBoolType):
        accepted_targets = {"bool", "int"}
    elif isinstance(type_info, IrIntType):
        accepted_targets = {"int"}
    elif isinstance(type_info, IrFloatType):
        accepted_targets = {"float"}
    elif isinstance(type_info, IrBytesType):
        accepted_targets = {"bytes"}
    elif isinstance(type_info, IrStringType):
        accepted_targets = {"str"}
    elif isinstance(type_info, IrDictType):
        accepted_targets = {"dict"}
    if accepted_targets is None:
        return None
    return bool(accepted_targets & targets)


def _homogeneous_tuple_element_type(type_info: IrType) -> IrType | None:
    if not isinstance(type_info, IrTupleType) or not type_info.elements:
        return None
    first = type_info.elements[0]
    for element in type_info.elements[1:]:
        if element != first:
            return None
    return first


def _is_tuple_mutating_method(target: str) -> bool:
    return target.endswith((".add", ".append", ".clear", ".extend", ".pop"))


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
    return len(parts) > 1 and all(
        part == "None" or _record_union_part_is_known(part, records) for part in parts
    )


def _record_union_part_is_known(part: str, records: dict[str, IrRecord]) -> bool:
    return part in records or part.rsplit(".", 1)[-1] in records


def _record_union_parts(record_name: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in record_name.split("|") if part.strip())


def _record_union_can_runtime_narrow(record_name: str, requested_type: IrType) -> bool:
    parts = _record_union_parts(record_name)
    if len(parts) < 2:
        return False
    if isinstance(requested_type, IrBoolType):
        return "bool" in parts
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
    return lines[-1].strip().startswith(("ret ", "br ", "unreachable"))


def _hoist_allocas_to_entry(lines: list[str]) -> list[str]:
    allocas: list[str] = []
    retained: list[str] = []
    for line in lines:
        if line.startswith("  ") and " = alloca " in line:
            allocas.append(line)
        else:
            retained.append(line)
    if not allocas:
        return lines
    result: list[str] = []
    inserted = False
    for line in retained:
        result.append(line)
        if line == "entry:":
            for alloca in allocas:
                result.append(alloca)
            inserted = True
    if not inserted:
        return lines
    return result


def _current_label(lines: list[str]) -> str:
    for line in reversed(lines):
        if line.endswith(":"):
            return line[:-1]
    return "entry"


def _for_each_targets(target: str) -> tuple[str, ...]:
    names: list[str] = []
    for slot in _for_each_target_slots(target):
        if slot is None:
            continue
        if "," in slot:
            names.extend(_for_each_targets(slot))
        else:
            names.append(slot)
    return tuple(names)


def _for_each_target_slots(target: str) -> tuple[str | None, ...]:
    stripped = target.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1]
    depth = 0
    start = 0
    parts: list[str] = []
    for index, char in enumerate(stripped):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            part = stripped[start:index].strip()
            if part:
                parts.append(part)
            start = index + 1
    tail = stripped[start:].strip()
    if tail:
        parts.append(tail)
    slots = tuple(None if part == "_" else part for part in parts)
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
