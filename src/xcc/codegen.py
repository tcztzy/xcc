"""LLVM IR code generator using libLLVM-C.

Zero runtime dependencies. Uses the system libLLVM.dylib through
xcc.llvm_api.

Consumes FrontendResult (AST + TypeMap + SemaUnit), produces
LLVM IR text. Driver pipes through llc for .o files.
"""

from dataclasses import dataclass

from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    BuiltinOffsetofExpr,
    BuiltinVaArgExpr,
    CallExpr,
    CaseStmt,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundLiteralExpr,
    CompoundStmt,
    ConditionalExpr,
    ContinueStmt,
    DeclaratorOp,
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
    DesignatorRange,
    DoWhileStmt,
    Expr,
    ExprStmt,
    FloatLiteral,
    ForStmt,
    FunctionDef,
    GotoStmt,
    Identifier,
    IfStmt,
    InitItem,
    InitList,
    IntLiteral,
    LabelStmt,
    MemberExpr,
    NullStmt,
    ReturnStmt,
    SizeofExpr,
    SourceLocation,
    StatementExpr,
    StaticAssertDecl,
    Stmt,
    StringLiteral,
    SubscriptExpr,
    SwitchStmt,
    TranslationUnit,
    TypedefDecl,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
    WhileStmt,
)
from xcc.diag import CodegenError, Diagnostic
from xcc.frontend import FrontendResult
from xcc.llvm_api import (
    ATOMIC_ORDER_SEQ_CST,
    ATOMIC_RMW_ADD,
    ATOMIC_RMW_AND,
    ATOMIC_RMW_NAND,
    ATOMIC_RMW_OR,
    ATOMIC_RMW_SUB,
    ATOMIC_RMW_XCHG,
    ATOMIC_RMW_XOR,
    LLVM_DWARF_EMISSION_FULL,
    LLVM_DWARF_SOURCE_LANGUAGE_C11,
    LLVM_EXTERNAL_LINKAGE,
    LLVM_INTERNAL_LINKAGE,
    LLVM_MODULE_FLAG_BEHAVIOR_WARNING,
    LLVMTypeKind,
    llvm,
    ptr_array,
)
from xcc.sema.constants import (
    char_literal_value,
    decode_escaped_units,
    narrow_string_bytes,
    string_literal_body,
)
from xcc.sema.layout import RecordMemberLayout
from xcc.sema.symbols import (
    EnumConstSymbol,
    FunctionSymbol,
    RecordMemberInfo,
    SemaUnit,
    TypeMap,
    VarSymbol,
)
from xcc.sema.type_helpers import (
    is_integer_type,
    is_signed_integer_type,
    usual_arithmetic_conversion,
)
from xcc.types import INT, FunctionParams, Type, TypeOp

_CG_UNSUPPORTED = "XCC-CG-0005"


def llvm_backend_error(filename: str, message: str) -> CodegenError:
    return CodegenError(Diagnostic("codegen", filename, message, code=_CG_UNSUPPORTED))


# ── code generator ──────────────────────────────────────────


def _base_size(name: str) -> int:
    return {"__builtin_va_list": 8, "void": 0}[name]


def _merge_qualifiers(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    merged: tuple[str, ...] = ()
    for qualifier in left:
        if qualifier not in merged:
            merged = merged + (qualifier,)
    for qualifier in right:
        if qualifier not in merged:
            merged = merged + (qualifier,)
    return merged


@dataclass
class _LoopCtx:
    continue_block: int  # _LLVMBasicBlockRef
    break_block: int  # _LLVMBasicBlockRef


@dataclass(frozen=True)
class _LValue:
    address: int
    type_: Type
    bit_offset: int | None = None
    bit_width: int | None = None
    storage_size: int | None = None


class _LLVMGen:
    _result: FrontendResult
    _unit: TranslationUnit
    _type_map: TypeMap
    _sema: SemaUnit
    _ctx: int
    _mod: int
    _builder: int
    _target_triple: str
    _str_constants: dict[str, int]
    _compound_literal_globals: dict[int, int]
    _func_types: dict[str, int]
    _func_param_types: dict[str, list[Type]]
    _struct_types: dict[str, int]
    _struct_layouts: dict[int, tuple[tuple[int, int | None], ...]]
    _struct_physical_layouts: dict[int, tuple[tuple[int, int, int, int | None], ...]]
    _struct_member_fields: dict[str, tuple[int, ...]]
    _static_local_counter: int
    _static_local_globals: dict[int, int]
    _static_local_global_values: set[int]
    _func: int
    _func_sym: FunctionSymbol | None
    _sret_ptr: int
    _locals: list[dict[str, int]]
    _label_blocks: dict[str, int]
    _loop_stack: list[_LoopCtx]
    _break_stack: list[int]
    _switch_info: list[tuple[int, int, int | None, bool, int]]
    _entry_block: int
    _debug: bool
    _debug_builder: int
    _debug_files: dict[str, int]
    _debug_subroutine_type: int
    _debug_scope: int
    _debug_scope_filename: str
    _debug_file_scopes: dict[str, int]
    _debug_source_location_index: int
    _debug_function_location: SourceLocation | None

    def __init__(
        self,
        result: FrontendResult,
        *,
        debug: bool = False,
        target_triple: str = "arm64-apple-macosx11.0.0",
    ) -> None:
        self._result = result
        self._unit = result.unit
        self._type_map = result.sema.type_map
        self._sema = result.sema

        c = llvm()
        self._ctx = c.ContextCreate()
        self._mod = c.ModuleCreateWithName(result.filename.encode("utf-8"))
        c.SetTarget(self._mod, target_triple.encode("utf-8"))
        self._builder = c.CreateBuilder()
        self._target_triple = target_triple
        self._str_constants: dict[str, int] = {}  # literal → _LLVMValueRef
        self._compound_literal_globals: dict[int, int] = {}
        self._func_types: dict[str, int] = {}  # func name → _LLVMTypeRef
        self._func_param_types: dict[str, list[Type]] = {}

        # Struct types: record_name → _LLVMTypeRef
        self._struct_types: dict[str, int] = {}
        self._struct_layouts = {}
        self._struct_physical_layouts = {}
        self._struct_member_fields = {}
        self._static_local_counter = 0
        self._static_local_globals: dict[int, int] = {}
        self._static_local_global_values: set[int] = set()

        # Function state
        self._func: int = 0  # _LLVMValueRef
        self._func_sym: FunctionSymbol | None = None
        self._sret_ptr = 0
        self._locals: list[dict[str, int]] = []
        self._label_blocks: dict[str, int] = {}
        self._loop_stack: list[_LoopCtx] = []
        self._break_stack: list[int] = []
        # (switch_inst, end_block, default_block, default_handled, cond_type)
        self._switch_info: list[tuple[int, int, int | None, bool, int]] = []
        self._entry_block: int = 0
        self._debug = debug
        self._debug_builder = 0
        self._debug_files: dict[str, int] = {}
        self._debug_subroutine_type = 0
        self._debug_scope = 0
        self._debug_scope_filename = ""
        self._debug_file_scopes: dict[str, int] = {}
        self._debug_source_location_index = 0
        self._debug_function_location: SourceLocation | None = None
        if self._debug:
            self._initialize_debug_info()

    # ── helpers ──────────────────────────────────────────────

    def _debug_file(self, filename: str) -> int:
        cached = self._debug_files.get(filename)
        if cached is not None:
            return cached
        normalized = filename.replace("\\", "/")
        if "/" in normalized:
            directory, basename = normalized.rsplit("/", 1)
            if directory == "":
                directory = "/"
        else:
            directory = ""
            basename = normalized
        c = llvm()
        basename_bytes = basename.encode("utf-8")
        directory_bytes = directory.encode("utf-8")
        file_metadata = c.DIBuilderCreateFile(
            self._debug_builder,
            basename_bytes,
            len(basename_bytes),
            directory_bytes,
            len(directory_bytes),
        )
        self._debug_files[filename] = file_metadata
        return file_metadata

    def _initialize_debug_info(self) -> None:
        c = llvm()
        self._debug_builder = c.CreateDIBuilder(self._mod)
        file_metadata = self._debug_file(self._result.filename)
        producer = b"xcc 0.2"
        c.DIBuilderCreateCompileUnit(
            self._debug_builder,
            LLVM_DWARF_SOURCE_LANGUAGE_C11,
            file_metadata,
            producer,
            len(producer),
            False,
            b"",
            0,
            0,
            b"",
            0,
            LLVM_DWARF_EMISSION_FULL,
            0,
            False,
            True,
            b"",
            0,
            b"",
            0,
        )
        self._debug_subroutine_type = c.DIBuilderCreateSubroutineType(
            self._debug_builder,
            file_metadata,
            None,
            0,
            0,
        )
        dwarf_version = c.ValueAsMetadata(c.ConstInt(c.Int32Type(), 4, False))
        debug_version = c.ValueAsMetadata(c.ConstInt(c.Int32Type(), 3, False))
        c.AddModuleFlag(
            self._mod,
            LLVM_MODULE_FLAG_BEHAVIOR_WARNING,
            b"Dwarf Version",
            len(b"Dwarf Version"),
            dwarf_version,
        )
        c.AddModuleFlag(
            self._mod,
            LLVM_MODULE_FLAG_BEHAVIOR_WARNING,
            b"Debug Info Version",
            len(b"Debug Info Version"),
            debug_version,
        )

    def _next_source_location(self) -> SourceLocation | None:
        index = self._debug_source_location_index
        if index >= len(self._unit.source_locations):
            return None
        self._debug_source_location_index += 1
        return self._unit.source_locations[index]

    def _mapped_source_location(
        self,
        location: SourceLocation | None,
    ) -> tuple[str, int, int]:
        if location is None:
            return self._result.filename, 1, 1
        filename = self._result.filename
        line = location.line
        if 1 <= line <= len(self._result.line_map):
            filename, line = self._result.line_map[line - 1]
        return filename, max(line, 1), max(location.column, 1)

    def _begin_function_debug(self, func: FunctionDef, function: int) -> None:
        if not self._debug:
            return
        self._debug_function_location = self._next_source_location()
        filename, line, _column = self._mapped_source_location(self._debug_function_location)
        file_metadata = self._debug_file(filename)
        name = func.name.encode("utf-8")
        c = llvm()
        subprogram = c.DIBuilderCreateFunction(
            self._debug_builder,
            file_metadata,
            name,
            len(name),
            name,
            len(name),
            file_metadata,
            line,
            self._debug_subroutine_type,
            self._function_definition_is_internal(func),
            True,
            line,
            0,
            False,
        )
        c.SetSubprogram(function, subprogram)
        self._debug_scope = subprogram
        self._debug_scope_filename = filename
        self._debug_file_scopes = {filename: subprogram}

    def _set_source_debug_location(self, source_location: SourceLocation | None) -> None:
        if not self._debug or not self._debug_scope:
            return
        filename, line, column = self._mapped_source_location(source_location)
        scope = self._debug_file_scopes.get(filename)
        if scope is None:
            scope = llvm().DIBuilderCreateLexicalBlockFile(
                self._debug_builder,
                self._debug_scope,
                self._debug_file(filename),
                0,
            )
            self._debug_file_scopes[filename] = scope
        location = llvm().DIBuilderCreateDebugLocation(
            self._ctx,
            line,
            column,
            scope,
            None,
        )
        llvm().SetCurrentDebugLocation2(self._builder, location)

    def _type_to_llvm(self, t: Type) -> int:
        """Map XCC Type to LLVMTypeRef."""
        c = llvm()
        base_name = t.name
        ops = t.declarator_ops

        result: int | None = None
        op_index = len(ops)
        while op_index:
            op_index -= 1
            kind, value = ops[op_index]
            if kind == "ptr":
                result = c.PointerType(c.Int8Type(), 0)
            elif kind == "arr":
                if result is None:
                    result = self._base_type(base_name)
                if isinstance(value, int):
                    result = c.ArrayType(result, max(value, 0))
                else:
                    result = c.ArrayType(result, 0)
            elif kind == "fn":
                if result is None:
                    result = self._base_type(base_name)
                params: tuple[Type, ...] = ()
                is_var = False
                if isinstance(value, tuple):
                    params = value[0] if value[0] else ()
                    is_var = value[1]
                # Filter out void params
                real_params: list[Type] = []
                for pt in params:
                    if pt.name != "void" or pt.declarator_ops:
                        real_params.append(pt)
                n = len(real_params)
                if n == 0:
                    param_arr = None
                else:
                    param_types: list[int] = []
                    for pt in real_params:
                        param_types.append(self._abi_param_llvm_type(pt))
                    param_arr = ptr_array(param_types)
                result = c.FunctionType(result, param_arr, n, is_var)
        if result is None:
            result = self._base_type(base_name)
        # C11 6.3.2.1p4: function designator → pointer-to-function.
        if c.GetTypeKind(result) == LLVMTypeKind.FUNCTION:
            result = c.PointerType(c.Int8Type(), 0)
        return result

    def _abi_param_llvm_type(self, type_: Type) -> int:
        if self._large_record_is_indirect(type_):
            return llvm().PointerType(llvm().Int8Type(), 0)
        return self._small_record_param_llvm_type(type_) or self._type_to_llvm(type_)

    def _small_record_param_llvm_type(self, type_: Type) -> int:
        if (
            not self._target_triple.startswith(("arm64-apple-", "aarch64-apple-"))
            or not self._is_record_type(type_)
            or self._aarch64_hfa(type_) is not None
        ):
            return 0
        size = self._type_size(type_)
        c = llvm()
        if size <= 8:
            return c.Int64Type()
        if size <= 16:
            return c.ArrayType(c.Int64Type(), 2)
        return 0

    def _small_record_return_llvm_type(self, type_: Type) -> int:
        if (
            not self._target_triple.startswith(("arm64-apple-", "aarch64-apple-"))
            or not self._is_record_type(type_)
            or self._aarch64_hfa(type_) is not None
        ):
            return 0
        size = self._type_size(type_)
        if 1 <= size <= 8:
            return llvm().IntType(size * 8)
        if 9 <= size <= 16:
            return llvm().ArrayType(llvm().Int64Type(), 2)
        return 0

    def _large_record_is_indirect(self, type_: Type) -> bool:
        return (
            self._target_triple.startswith(("arm64-apple-", "aarch64-apple-"))
            and self._is_record_type(type_)
            and self._type_size(type_) > 16
            and self._aarch64_hfa(type_) is None
        )

    def _aarch64_hfa(self, type_: Type) -> tuple[str, int] | None:
        if type_.declarator_ops:
            kind, length = type_.declarator_ops[0]
            if kind != "arr" or not isinstance(length, int) or length < 1:
                return None
            element = Type(
                type_.name,
                declarator_ops=type_.declarator_ops[1:],
                qualifiers=type_.qualifiers,
            )
            hfa = self._aarch64_hfa(element)
            if hfa is None or hfa[1] * length > 4:
                return None
            return hfa[0], hfa[1] * length
        base = type_.name
        if base == "long double" and self._sema.data_layout.long_double_mantissa_bits == 53:
            base = "double"
        if base in {"float", "double"}:
            return base, 1
        if not base.startswith(("struct ", "union ")):
            return None
        members = self._sema.record_definitions.get(base)
        if not members:
            return None
        hfa_base = ""
        count = 0
        is_union = base.startswith("union ")
        for member in members:
            if member.bit_width is not None:
                return None
            hfa = self._aarch64_hfa(member.type_)
            if hfa is None or (hfa_base and hfa[0] != hfa_base):
                return None
            hfa_base = hfa[0]
            count = max(count, hfa[1]) if is_union else count + hfa[1]
            if count > 4:
                return None
        return hfa_base, count

    def _copy_indirect_record_arg(self, value: int, type_: Type) -> int:
        c = llvm()
        copy = self._build_entry_alloca(
            self._type_to_llvm(type_),
            "arg.copy",
            self._type_align(type_) if self._type_has_nonstandard_record_layout(type_) else 0,
        )
        c.BuildStore(self._builder, value, copy)
        return copy

    def _coerce_small_record_arg(self, value: int, type_: Type) -> int:
        return self._coerce_record(value, self._small_record_param_llvm_type(type_))

    def _coerce_record(self, value: int, abi_type: int) -> int:
        c = llvm()
        slot = self._build_entry_alloca(abi_type, "arg.coerce", 0)
        c.BuildStore(self._builder, c.ConstNull(abi_type), slot)
        c.BuildStore(self._builder, value, slot)
        return c.BuildLoad2(self._builder, abi_type, slot, b"arg.coerced")

    def _record_from_abi(self, value: int, type_: Type) -> int:
        c = llvm()
        slot = self._build_entry_alloca(c.TypeOf(value), "return.coerce", 0)
        c.BuildStore(self._builder, value, slot)
        return c.BuildLoad2(
            self._builder,
            self._type_to_llvm(type_),
            slot,
            b"return.coerced",
        )

    def _abi_function_type(
        self,
        return_type: Type,
        param_types: list[Type],
        is_variadic: bool,
    ) -> int:
        c = llvm()
        params = [self._abi_param_llvm_type(type_) for type_ in param_types]
        if self._large_record_is_indirect(return_type):
            params = [c.PointerType(c.Int8Type(), 0)] + params
            result = c.VoidType()
        else:
            result = self._small_record_return_llvm_type(return_type) or self._type_to_llvm(
                return_type
            )
        return c.FunctionType(
            result,
            None if not params else ptr_array(params),
            len(params),
            is_variadic,
        )

    def _sret_attribute(self, return_type: Type) -> int:
        c = llvm()
        kind = c.GetEnumAttributeKindForName(b"sret", 4)
        return c.CreateTypeAttribute(self._ctx, kind, self._type_to_llvm(return_type))

    def _mark_sret_function(self, function: int, return_type: Type) -> None:
        llvm().AddAttributeAtIndex(function, 1, self._sret_attribute(return_type))

    def _mark_sret_call(self, call: int, return_type: Type) -> None:
        llvm().AddCallSiteAttribute(call, 1, self._sret_attribute(return_type))

    def _sret_result(self, return_type: Type) -> int:
        result = self._build_entry_alloca(
            self._type_to_llvm(return_type),
            "call.result",
            self._type_align(return_type)
            if self._type_has_nonstandard_record_layout(return_type)
            else 0,
        )
        return result

    def _base_type(self, name: str) -> int:
        c = llvm()
        if name.startswith(("struct ", "union ")):
            return self._struct_type(name)
        if name == "__builtin_va_list":
            return c.PointerType(c.Int8Type(), 0)
        if name in ("int", "unsigned int"):
            return c.Int32Type()
        if name in ("long", "unsigned long", "long long", "unsigned long long"):
            return c.Int64Type()
        if name in ("char", "unsigned char", "signed char"):
            return c.Int8Type()
        if name in ("_Bool", "bool"):
            return c.Int1Type()
        if name in ("short", "unsigned short"):
            return c.Int16Type()
        if name == "float":
            return c.FloatType()
        if name == "double":
            return c.DoubleType()
        if name == "long double":
            mantissa_bits = self._sema.data_layout.long_double_mantissa_bits
            if mantissa_bits == 53:
                return c.DoubleType()
            if mantissa_bits == 64:
                return c.X86FP80Type()
            return c.FP128Type()
        if name == "void":
            return c.VoidType()
        return c.Int32Type()

    @staticmethod
    def _is_unsigned_integer_c_type(type_: Type | None) -> bool:
        if type_ is None:
            return False
        return is_integer_type(type_) and not is_signed_integer_type(type_)

    @staticmethod
    def _common_integer_c_type(left: Type | None, right: Type | None) -> Type | None:
        if left is None or right is None:
            return None
        if not is_integer_type(left) or not is_integer_type(right):
            return None
        return usual_arithmetic_conversion(left, right)

    def _cast_integer_value(
        self,
        value: int,
        target_type: int,
        source_type: Type | None,
        name: bytes,
    ) -> int:
        c = llvm()
        source_type_ref = c.TypeOf(value)
        if source_type_ref == target_type:
            return value
        source_width = c.GetIntTypeWidth(source_type_ref)
        target_width = c.GetIntTypeWidth(target_type)
        if target_width == 1:
            return self._to_bool(value)
        if source_width > target_width:
            return c.BuildTrunc(self._builder, value, target_type, name)
        if source_width < target_width:
            if self._is_unsigned_integer_c_type(source_type):
                return c.BuildZExt(self._builder, value, target_type, name)
            return c.BuildSExt(self._builder, value, target_type, name)
        return value  # pragma: no cover - LLVM integer types are uniqued by width.

    def _gep_index_value(
        self,
        value: int,
        source_type: Type | None,
        name: bytes,
    ) -> int:
        c = llvm()
        value_type = c.TypeOf(value)
        if c.GetTypeKind(value_type) != LLVMTypeKind.INTEGER:
            return value
        return self._cast_integer_value(value, c.Int64Type(), source_type, name)

    @staticmethod
    def _is_float_kind(kind: int) -> bool:
        return kind in (
            LLVMTypeKind.FLOAT,
            LLVMTypeKind.DOUBLE,
            LLVMTypeKind.HALF,
            LLVMTypeKind.BFLOAT,
            LLVMTypeKind.X86_FP80,
            LLVMTypeKind.FP128,
            LLVMTypeKind.PPC_FP128,
        )

    @staticmethod
    def _float_rank(kind: int) -> int:
        if kind in (LLVMTypeKind.HALF, LLVMTypeKind.BFLOAT):
            return 1
        if kind == LLVMTypeKind.FLOAT:
            return 2
        if kind == LLVMTypeKind.DOUBLE:
            return 3
        if kind == LLVMTypeKind.X86_FP80:
            return 4
        if kind in (LLVMTypeKind.FP128, LLVMTypeKind.PPC_FP128):
            return 5
        return 0

    def _struct_type(self, record_name: str) -> int:
        c = llvm()
        if record_name in self._struct_types:
            return self._struct_types[record_name]
        members = self._sema.record_definitions.get(record_name)
        if not members:
            st = c.StructType(None, 0, False)
            self._struct_types[record_name] = st
            return st
        if record_name.startswith("union "):
            storage_member = self._union_storage_member(members)
            storage_type = self._record_member_llvm_type(storage_member)
            storage_size = self._type_size(storage_member.type_)
            union_size = self._union_size(record_name)
            field_types: list[int] = [storage_type]
            padding = union_size - storage_size
            if padding > 0:
                field_types.append(c.ArrayType(c.Int8Type(), padding))
            member_types = ptr_array(field_types)
            st = c.StructType(
                member_types,
                len(field_types),
                self._sema.record_packs.get(record_name) is not None,
            )
            self._struct_types[record_name] = st
            return st
        st = self._build_struct_type(record_name, members, {})
        self._struct_types[record_name] = st
        return st

    def _build_struct_type(
        self,
        record_name: str,
        members: tuple[RecordMemberInfo, ...],
        overrides: dict[int, Type],
    ) -> int:
        if not overrides and any(member.bit_width is not None for member in members):
            return self._build_bitfield_struct_type(record_name, members)
        c = llvm()
        pack = self._sema.record_packs.get(record_name)
        if pack is None and not any(
            member.alignment is not None
            or self._type_has_nonstandard_record_layout(overrides.get(index, member.type_))
            for index, member in enumerate(members)
        ):
            ordinary_field_types = [
                self._record_field_llvm_type(overrides.get(index, member.type_))
                for index, member in enumerate(members)
            ]
            result = c.StructType(ptr_array(ordinary_field_types), len(ordinary_field_types), False)
            if not overrides:
                self._struct_member_fields[record_name] = tuple(range(len(members)))
            return result
        offset = 0
        field_types: list[int] = []
        field_layout: list[tuple[int, int | None]] = []
        member_fields: list[int] = []
        for index, member in enumerate(members):
            member_type = overrides.get(index, member.type_)
            aligned = self._align_to(
                offset,
                self._record_member_align(record_name, member, member_type),
            )
            if aligned > offset:
                padding_type = c.ArrayType(c.Int8Type(), aligned - offset)
                field_types.append(padding_type)
                field_layout.append((padding_type, None))
            member_fields.append(len(field_types))
            member_type_ref = self._record_field_llvm_type(member_type)
            field_types.append(member_type_ref)
            field_layout.append((member_type_ref, index))
            offset = aligned + self._type_size(member_type)
        size = self._record_size_with_overrides(record_name, members, overrides)
        if size > offset:
            padding_type = c.ArrayType(c.Int8Type(), size - offset)
            field_types.append(padding_type)
            field_layout.append((padding_type, None))
        member_types = ptr_array(field_types)
        result = c.StructType(member_types, len(field_types), pack is not None)
        self._struct_layouts[result] = tuple(field_layout)
        if not overrides:
            self._struct_member_fields[record_name] = tuple(member_fields)
        return result

    def _build_bitfield_struct_type(
        self,
        record_name: str,
        members: tuple[RecordMemberInfo, ...],
    ) -> int:
        c = llvm()
        layout = self._sema.record_layouts[record_name]
        entities: list[tuple[int, int, int, int | None, tuple[int, int] | None]] = []
        storage_fields: set[tuple[int, int]] = set()
        for index, (member, member_layout) in enumerate(zip(members, layout.members, strict=True)):
            if member.bit_width is not None:
                if member.bit_width == 0:
                    continue
                assert member_layout.storage_size is not None
                key = (member_layout.offset, member_layout.storage_size)
                if key not in storage_fields:
                    storage_fields.add(key)
                    entities.append(
                        (
                            member_layout.offset,
                            member_layout.storage_size,
                            c.ArrayType(c.Int8Type(), member_layout.storage_size),
                            None,
                            key,
                        )
                    )
                continue
            member_size = self._type_size(member.type_)
            entities.append(
                (
                    member_layout.offset,
                    member_size,
                    self._record_member_llvm_type(member),
                    index,
                    None,
                )
            )
        field_types: list[int] = []
        physical: list[tuple[int, int, int, int | None]] = []
        entity_fields: dict[tuple[int, int] | int, int] = {}
        offset = 0
        for entity_offset, size, field_type, member_index, storage_key in entities:
            if entity_offset > offset:
                padding = c.ArrayType(c.Int8Type(), entity_offset - offset)
                field_types.append(padding)
                physical.append((padding, offset, entity_offset - offset, None))
            field_index = len(field_types)
            field_types.append(field_type)
            physical.append((field_type, entity_offset, size, member_index))
            if storage_key is None:
                assert member_index is not None
                entity_fields[member_index] = field_index
            else:
                entity_fields[storage_key] = field_index
            offset = max(offset, entity_offset + size)
        if layout.size > offset:
            padding = c.ArrayType(c.Int8Type(), layout.size - offset)
            field_types.append(padding)
            physical.append((padding, offset, layout.size - offset, None))
        result = c.StructType(ptr_array(field_types), len(field_types), True)
        self._struct_physical_layouts[result] = tuple(physical)
        member_fields = []
        for index, (member, member_layout) in enumerate(zip(members, layout.members, strict=True)):
            if member.bit_width == 0:
                member_fields.append(-1)
            elif member.bit_width is None:
                member_fields.append(entity_fields[index])
            else:
                assert member_layout.storage_size is not None
                member_fields.append(
                    entity_fields[(member_layout.offset, member_layout.storage_size)]
                )
        self._struct_member_fields[record_name] = tuple(member_fields)
        return result

    def _type_has_nonstandard_record_layout(self, type_: Type) -> bool:
        if type_.declarator_ops:
            if type_.declarator_ops[0][0] != "arr":
                return False
            return self._type_has_nonstandard_record_layout(
                Type(type_.name, declarator_ops=type_.declarator_ops[1:])
            )
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            return False
        if self._sema.record_packs.get(type_.name) is not None:
            return True
        return any(
            member.alignment is not None
            or member.bit_width is not None
            or self._type_has_nonstandard_record_layout(member.type_)
            for member in members
        )

    def _llvm_field_index(self, record_name: str, member_index: int) -> int:
        self._struct_type(record_name)
        return self._struct_member_fields[record_name][member_index]

    def _record_member_llvm_type(self, member: RecordMemberInfo) -> int:
        return self._record_field_llvm_type(member.type_)

    def _record_field_llvm_type(self, type_: Type) -> int:
        c = llvm()
        mt = self._type_to_llvm(type_)
        # In opaque-pointer mode, function-pointer members must be ptr
        # not ptr (void (...)).  Force all pointer-typed members to
        # opaque ptr(i8) to avoid typed-pointer IR in struct layouts.
        if c.GetTypeKind(mt) == LLVMTypeKind.POINTER:
            return c.PointerType(c.Int8Type(), 0)
        return mt

    def _field_index(self, record_name: str, member_name: str) -> int:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            raise llvm_backend_error(self._result.filename, f"Unknown record: {record_name}")
        for i, m in enumerate(members):
            if m.name == member_name:
                return i
        raise llvm_backend_error(
            self._result.filename,
            f"Record '{record_name}' has no member '{member_name}'",
        )

    def _member_path(
        self,
        record_name: str,
        member_name: str,
    ) -> list[tuple[str, int, RecordMemberInfo]] | None:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return None
        for i, member in enumerate(members):
            if member.name == member_name:
                return [(record_name, i, member)]
            if (
                member.name is None
                and member.bit_width is None
                and not member.type_.declarator_ops
                and member.type_.name.startswith(("struct ", "union "))
            ):
                nested = self._member_path(member.type_.name, member_name)
                if nested is not None:
                    path: list[tuple[str, int, RecordMemberInfo]] = [(record_name, i, member)]
                    path.extend(nested)
                    return path
        return None

    def _type_size(self, t: Type) -> int:
        if not t.declarator_ops:
            if t.name.startswith(("struct ", "union ")):
                return self._sema.record_layouts[t.name].size
            scalar_size = self._sema.data_layout.scalar_size(t.name)
            return _base_size(t.name) if scalar_size is None else scalar_size
        for kind, value in t.declarator_ops:
            if kind == "ptr":
                return self._sema.data_layout.pointer_size
            if kind == "arr":
                assert isinstance(value, int)
                elem_type = Type(t.name, declarator_ops=t.declarator_ops[1:])
                return max(value, 0) * self._type_size(elem_type)
        scalar_size = self._sema.data_layout.scalar_size(t.name)
        return _base_size(t.name) if scalar_size is None else scalar_size

    def _type_align(self, t: Type) -> int:
        if not t.declarator_ops:
            if t.name.startswith(("struct ", "union ")):
                return self._sema.record_layouts[t.name].alignment
            scalar_align = self._sema.data_layout.scalar_alignment(t.name)
            return min(_base_size(t.name), 8) if scalar_align is None else scalar_align
        kind, _ = t.declarator_ops[0]
        if kind == "ptr":
            return self._sema.data_layout.pointer_alignment
        if kind == "arr":
            elem_type = Type(t.name, declarator_ops=t.declarator_ops[1:])
            return self._type_align(elem_type)
        return 1

    def _member_align(
        self,
        member: RecordMemberInfo,
        member_type: Type | None = None,
    ) -> int:
        member_align = self._type_align(member.type_ if member_type is None else member_type)
        if member.alignment is not None and member.alignment > member_align:
            return member.alignment
        return member_align

    def _record_member_align(
        self,
        record_name: str,
        member: RecordMemberInfo,
        member_type: Type | None = None,
    ) -> int:
        alignment = self._member_align(member, member_type)
        pack = self._sema.record_packs.get(record_name)
        return alignment if pack is None else min(alignment, pack)

    @staticmethod
    def _align_to(value: int, alignment: int) -> int:
        return ((value + alignment - 1) // alignment) * alignment

    def _record_size(self, record_name: str) -> int:
        return self._sema.record_layouts[record_name].size

    def _record_size_with_overrides(
        self,
        record_name: str,
        members: tuple[RecordMemberInfo, ...],
        overrides: dict[int, Type],
    ) -> int:
        offset = 0
        max_align = 1
        for index, member in enumerate(members):
            member_type = overrides.get(index, member.type_)
            member_align = self._record_member_align(record_name, member, member_type)
            max_align = max(max_align, member_align)
            offset = self._align_to(offset, member_align)
            offset += self._type_size(member_type)
        return self._align_to(offset, max_align)

    def _union_size(self, record_name: str) -> int:
        return self._sema.record_layouts[record_name].size

    def _union_storage_member(self, members: tuple[RecordMemberInfo, ...]) -> RecordMemberInfo:
        best = members[0]
        best_type = best.type_
        best_size = self._type_size(best_type)
        best_is_record = (
            1
            if not best_type.declarator_ops and best_type.name.startswith(("struct ", "union "))
            else 0
        )
        best_align = self._member_align(best)
        for member in members[1:]:
            type_ = member.type_
            member_size = self._type_size(type_)
            member_is_record = (
                1
                if not type_.declarator_ops and type_.name.startswith(("struct ", "union "))
                else 0
            )
            member_align = self._member_align(member)
            better = member_size > best_size
            if member_size == best_size and member_is_record > best_is_record:
                better = True
            if (
                member_size == best_size
                and member_is_record == best_is_record
                and member_align > best_align
            ):
                better = True
            if better:
                best = member
                best_size = member_size
                best_is_record = member_is_record
                best_align = member_align
        return best

    # ── module ───────────────────────────────────────────────

    def generate(self) -> str:
        self._emit_globals()
        self._emit_functions()
        if self._debug:
            llvm().DIBuilderFinalize(self._debug_builder)
        llvm_text = _llvm_print_module_to_string(self._mod)
        if self._debug:
            llvm().DisposeDIBuilder(self._debug_builder)
            return _enable_unwind_tables(llvm_text)
        return llvm_text

    def _emit_globals(self) -> None:
        llvm()
        externals: list[FunctionDef | Stmt] = self._unit.externals
        if not externals:
            externals = []
            externals.extend(self._unit.declarations)
            externals.extend(self._unit.functions)
        for ext in externals:
            if isinstance(ext, FunctionDef):
                continue
            if isinstance(ext, DeclGroupStmt):
                for decl in ext.declarations:
                    if isinstance(decl, DeclStmt):
                        self._emit_global_var(decl)
            elif isinstance(ext, DeclStmt):
                self._emit_global_var(ext)

    def _emit_global_var(self, decl: DeclStmt) -> None:
        c = llvm()
        name = decl.name
        if name is None:
            return
        t = self._resolve_type(decl.type_spec)
        if self._is_function_designator_type(t):
            return
        if self._sema.file_scope is not None:
            symbol = self._sema.file_scope.lookup(name)
            if isinstance(symbol, VarSymbol):
                t = symbol.type_
        if t.is_array():
            array_length = t.declarator_ops[0][1]
            unspecified = (isinstance(array_length, int) and array_length <= 0) or (
                isinstance(array_length, ArrayDecl) and array_length.length is None
            )
            if unspecified and isinstance(decl.init, InitList):
                inferred = self._infer_array_init_length(decl.init, t)
                new_ops = (("arr", inferred),) + t.declarator_ops[1:]
                t = Type(t.name, declarator_ops=new_ops, qualifiers=t.qualifiers)
            if unspecified and isinstance(decl.init, StringLiteral):
                string_inferred = self._string_array_initializer_length(decl.init, t)
                if string_inferred is not None:
                    new_ops = (("arr", string_inferred),) + t.declarator_ops[1:]
                    t = Type(t.name, declarator_ops=new_ops, qualifiers=t.qualifiers)
        flexible_members: dict[int, Type] | None = None
        lt = self._type_to_llvm(t)
        if isinstance(decl.init, InitList):
            flexible_members = self._flexible_array_member_overrides(t, decl.init)
            if flexible_members:
                lt = self._struct_type_with_member_overrides(t.name, flexible_members)
        gv = c.GetNamedGlobal(self._mod, name.encode())
        if not gv:
            gv = c.AddGlobal(self._mod, lt, name.encode())
        if decl.is_thread_local:
            c.SetThreadLocal(gv, True)
        if self._type_has_nonstandard_record_layout(t):
            c.SetAlignment(gv, self._type_align(t))
        if decl.storage_class == "static":
            c.SetLinkage(gv, LLVM_INTERNAL_LINKAGE)
        if decl.storage_class == "extern":
            return
        if decl.init:
            if flexible_members and isinstance(decl.init, InitList):
                init_value = self._eval_record_init(
                    decl.init,
                    t,
                    member_type_overrides=flexible_members,
                    record_lt=lt,
                )
            else:
                init_value = self._eval_init(decl.init, t)
            if init_value:
                c.SetInitializer(gv, init_value)
                return
        c.SetInitializer(gv, c.ConstNull(lt))

    def _emit_functions(self) -> None:
        for func in self._unit.functions:
            self._declare_func(func)
        for func in self._unit.functions:
            if func.body is not None:
                self._define_func(func)

    def _function_definition_is_internal(self, func: FunctionDef) -> bool:
        return func.storage_class == "static" or (func.body is not None and func.is_inline)

    def _function_param_types(self, func: FunctionDef) -> list[Type]:
        signature = self._sema.function_signatures.get(func.name)
        if signature is not None:
            params = signature.params
            if params is None:
                return []
            result: list[Type] = []
            for param_type in params:
                result.append(param_type)
            return result
        param_types: list[Type] = []
        for param in func.params:
            param_type = self._resolve_type(param.type_spec)
            if param_type.name == "void" and not param_type.declarator_ops:
                continue
            param_types.append(param_type.decay_parameter_type())
        return param_types

    def _declare_func(self, func: FunctionDef) -> None:
        c = llvm()
        func_sym = self._sema.functions.get(func.name)
        signature = self._sema.function_signatures.get(func.name)
        if func_sym is not None:
            return_type = func_sym.return_type
        elif signature is not None:
            return_type = signature.return_type
        else:
            return_type = self._resolve_type(func.return_type)
        c_param_types = self._function_param_types(func)
        is_variadic = signature.is_variadic if signature is not None else func.is_variadic
        fn_t = self._abi_function_type(return_type, c_param_types, is_variadic)
        self._func_types[func.name] = fn_t  # save for later calls
        self._func_param_types[func.name] = c_param_types
        fn = c.GetNamedFunction(self._mod, func.name.encode())
        if not fn:
            fn = c.AddFunction(self._mod, func.name.encode(), fn_t)
        if self._large_record_is_indirect(return_type):
            self._mark_sret_function(fn, return_type)
        if self._function_definition_is_internal(func):
            c.SetLinkage(fn, LLVM_INTERNAL_LINKAGE)
        if func.body is None:
            c.SetLinkage(
                fn,
                LLVM_INTERNAL_LINKAGE if func.storage_class == "static" else LLVM_EXTERNAL_LINKAGE,
            )

    def _define_func(self, func: FunctionDef) -> None:
        c = llvm()
        func_sym = self._sema.functions.get(func.name)
        if func_sym is None:
            return
        self._func_sym = func_sym
        self._locals = [{}]
        self._label_blocks = {}
        self._loop_stack = []
        self._break_stack = []
        self._switch_info = []

        return_type = func_sym.return_type
        c_param_types = self._function_param_types(func)
        fn_t = self._abi_function_type(return_type, c_param_types, func.is_variadic)
        ret_t = c.GetReturnType(fn_t)
        # Reuse existing declaration if present
        fn = c.GetNamedFunction(self._mod, func.name.encode())
        if not fn:
            fn = c.AddFunction(self._mod, func.name.encode(), fn_t)
        if self._large_record_is_indirect(return_type):
            self._mark_sret_function(fn, return_type)
        if self._function_definition_is_internal(func):
            c.SetLinkage(fn, LLVM_INTERNAL_LINKAGE)
        self._func = fn
        self._begin_function_debug(func, fn)

        entry = c.AppendBasicBlock(fn, b"entry")
        self._entry_block = entry
        c.PositionBuilderAtEnd(self._builder, entry)
        self._set_source_debug_location(self._debug_function_location)

        # Alloca + store params
        self._sret_ptr = c.GetParam(fn, 0) if self._large_record_is_indirect(return_type) else 0
        param_index = 1 if self._sret_ptr else 0
        for param in func.params:
            assert param.name
            pt = self._resolve_type(param.type_spec)
            if pt.name == "void" and not pt.declarator_ops:
                continue
            symbol = func_sym.locals.get(param.name)
            if isinstance(symbol, VarSymbol):  # noqa: SIM108
                pt = symbol.type_
            else:
                pt = pt.decay_parameter_type()
            lt = self._type_to_llvm(pt)
            pv = c.GetParam(fn, param_index)
            param_index += 1
            if self._large_record_is_indirect(pt):
                self._set_current_local(param.name, pv)
                continue
            alloca = c.BuildAlloca(
                self._builder,
                self._small_record_param_llvm_type(pt) or lt,
                f"{param.name}.addr".encode(),
            )
            if self._type_has_nonstandard_record_layout(pt):
                c.SetAlignment(alloca, self._type_align(pt))
            c.BuildStore(self._builder, pv, alloca)
            self._set_current_local(param.name, alloca)

        assert func.body is not None
        self._emit_stmt(func.body)

        if self._bb_needs_term():
            if self._sret_ptr or (
                func_sym.return_type.name == "void" and not func_sym.return_type.declarator_ops
            ):
                c.BuildRetVoid(self._builder)
            elif c.GetTypeKind(ret_t) == LLVMTypeKind.POINTER:
                c.BuildRet(self._builder, c.ConstNull(ret_t))
            elif self._is_float_kind(c.GetTypeKind(ret_t)):
                c.BuildRet(self._builder, c.ConstReal(ret_t, 0.0))
            elif c.GetTypeKind(ret_t) != LLVMTypeKind.INTEGER:
                c.BuildRet(self._builder, c.ConstNull(ret_t))
            else:
                c.BuildRet(self._builder, c.ConstInt(ret_t, 0, False))
        if self._debug:
            c.SetCurrentDebugLocation2(self._builder, None)
            self._debug_scope = 0
            self._debug_scope_filename = ""
            self._debug_file_scopes = {}
            self._debug_function_location = None

    def _build_call_args(self, expr: CallExpr) -> tuple[list[int], list[int], list[Type | None]]:
        """Evaluate call args, return (values, LLVM types, C types)."""
        vals = []
        types = []
        c_types = []
        for arg in expr.args:
            v = self._emit_expr(arg)
            vals.append(v)
            types.append(llvm().TypeOf(v))
            c_types.append(self._type_map.get(arg))
        return vals, types, c_types

    def _coerce_call_args(
        self,
        vals: list[int],
        callee_name: str,
        arg_c_types: list[Type | None] | None = None,
    ) -> list[int]:
        """Coerce argument values to match function parameter types."""
        c_param_types = self._func_param_types.get(callee_name)
        if not c_param_types:
            return vals
        c = llvm()
        result = []
        for i, v in enumerate(vals):
            if i < len(c_param_types):
                c_param_type = c_param_types[i]
                if self._large_record_is_indirect(c_param_type):
                    result.append(self._copy_indirect_record_arg(v, c_param_type))
                    continue
                if self._small_record_param_llvm_type(c_param_type):
                    result.append(self._coerce_small_record_arg(v, c_param_type))
                    continue
                pt = self._type_to_llvm(c_param_type)
                vt = c.TypeOf(v)
                pk = c.GetTypeKind(pt)
                vk = c.GetTypeKind(vt)
                # Array decay for args
                if vk == LLVMTypeKind.ARRAY:
                    v = self._build_cast(v, c.PointerType(c.Int8Type(), 0))
                    vt = c.TypeOf(v)
                    vk = c.GetTypeKind(vt)
                if pk == LLVMTypeKind.INTEGER and vk == LLVMTypeKind.INTEGER:
                    source_type = None if arg_c_types is None else arg_c_types[i]
                    v = self._cast_integer_value(v, pt, source_type, b"arg.ext")
                elif self._is_float_kind(pk) and self._is_float_kind(vk) and pt != vt:
                    v = c.BuildFPCast(self._builder, v, pt, b"arg.cast")
                elif pk == LLVMTypeKind.POINTER and vk == LLVMTypeKind.INTEGER:
                    v = c.BuildIntToPtr(self._builder, v, pt, b"arg.cast")
                elif pk == LLVMTypeKind.INTEGER and vk == LLVMTypeKind.POINTER:
                    v = c.BuildPtrToInt(self._builder, v, pt, b"arg.cast")
            result.append(v)
        return result

    # ── statement emission ───────────────────────────────────

    def _bb_needs_term(self, bb: int = 0) -> bool:
        """True if the given (or current) basic block has no terminator."""
        c = llvm()
        if not bb:
            bb = c.GetInsertBlock(self._builder)
            if not bb:
                return False
        term = c.GetBasicBlockTerminator(bb)
        return term is None or term == 0

    def _emit_stmt(self, stmt: Stmt) -> None:
        previous_debug_location = 0
        if self._debug:
            previous_debug_location = llvm().GetCurrentDebugLocation2(self._builder)
            self._set_source_debug_location(self._next_source_location())
        if isinstance(stmt, CompoundStmt):
            self._locals.append({})
            for s in stmt.statements:
                self._emit_stmt(s)
            self._locals.pop()
        elif isinstance(stmt, ReturnStmt):
            self._emit_return(stmt)
        elif isinstance(stmt, ExprStmt):
            self._emit_expr(stmt.expr)
        elif isinstance(stmt, NullStmt):
            pass
        elif isinstance(stmt, IfStmt):
            self._emit_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._emit_while(stmt)
        elif isinstance(stmt, DoWhileStmt):
            self._emit_do_while(stmt)
        elif isinstance(stmt, ForStmt):
            self._emit_for(stmt)
        elif isinstance(stmt, BreakStmt):
            self._emit_break()
        elif isinstance(stmt, ContinueStmt):
            self._emit_continue()
        elif isinstance(stmt, DeclStmt):
            self._ensure_decl_alloca(stmt)
            self._emit_decl_init(stmt)
        elif isinstance(stmt, DeclGroupStmt):
            for d in stmt.declarations:
                if isinstance(d, DeclStmt):
                    self._ensure_decl_alloca(d)
                    self._emit_decl_init(d)
        elif isinstance(stmt, SwitchStmt):
            self._emit_switch(stmt)
        elif isinstance(stmt, CaseStmt):
            self._emit_case(stmt)
        elif isinstance(stmt, DefaultStmt):
            self._emit_default(stmt)
        elif isinstance(stmt, LabelStmt):
            self._emit_label(stmt)
        elif isinstance(stmt, GotoStmt):
            self._emit_goto(stmt)
        elif isinstance(stmt, (TypedefDecl, StaticAssertDecl)):
            pass
        if self._debug:
            llvm().SetCurrentDebugLocation2(self._builder, previous_debug_location)

    def _emit_return(self, stmt: ReturnStmt) -> None:
        c = llvm()
        if stmt.value is None:
            c.BuildRetVoid(self._builder)
        elif self._sret_ptr:
            c.BuildStore(self._builder, self._emit_expr(stmt.value), self._sret_ptr)
            c.BuildRetVoid(self._builder)
        elif self._func_sym is not None and self._small_record_return_llvm_type(
            self._func_sym.return_type
        ):
            return_type = self._func_sym.return_type
            c.BuildRet(
                self._builder,
                self._coerce_record(
                    self._emit_expr(stmt.value),
                    self._small_record_return_llvm_type(return_type),
                ),
            )
        elif (
            self._func_sym is not None
            and self._func_sym.return_type.name == "void"
            and not self._func_sym.return_type.declarator_ops
        ):
            self._emit_expr(stmt.value)
            c.BuildRetVoid(self._builder)
        else:
            v = self._emit_expr(stmt.value)
            declared_return_type: Type = INT
            if self._func_sym is not None:
                declared_return_type = self._func_sym.return_type
            ret_lt = self._type_to_llvm(declared_return_type)
            if c.TypeOf(v) != ret_lt:
                v = self._build_cast(v, ret_lt, self._type_map.get(stmt.value))
            c.BuildRet(self._builder, v)

    def _emit_decl_init(self, stmt: DeclStmt) -> None:
        if stmt.storage_class == "static":
            return
        if stmt.name is None or stmt.init is None:
            return
        addr = self._lookup_local(stmt.name)
        if addr is None:
            return
        if isinstance(stmt.init, InitList):
            target_type = self._decl_type(stmt)
            if self._emit_init_list_to_addr(addr, target_type, stmt.init):
                return
            return
        c = llvm()
        target_type = self._decl_type(stmt)
        if isinstance(stmt.init, StringLiteral) and self._is_string_array_initializer(
            stmt.init,
            target_type,
        ):
            val = self._string_array_initializer(stmt.init, target_type)
            c.BuildStore(self._builder, val, addr)
            return
        if self._is_aggregate_type(target_type):
            self._emit_initializer_to_addr(addr, target_type, (), stmt.init)
            return
        val = self._emit_expr(stmt.init)
        target_lt = self._type_to_llvm(target_type)
        if c.TypeOf(val) != target_lt:
            val = self._build_cast(val, target_lt, self._type_map.get(stmt.init))
        c.BuildStore(self._builder, val, addr)

    def _emit_init_list_to_addr(self, addr: int, target_type: Type, init: InitList) -> bool:
        c = llvm()
        target_lt = self._type_to_llvm(target_type)
        c.BuildStore(self._builder, c.ConstNull(target_lt), addr)
        if target_type.is_array():
            return self._emit_array_init_list_to_addr(addr, target_type, init)
        if self._is_record_type(target_type):
            return self._emit_record_init_list_to_addr(addr, target_type, init)
        if len(init.items) == 1 and not init.items[0].designators:
            initializer = init.items[0].initializer
            if isinstance(initializer, InitList):
                return self._emit_init_list_to_addr(addr, target_type, initializer)
            val = self._emit_expr(initializer)
            if c.TypeOf(val) != target_lt:
                val = self._build_cast(val, target_lt, self._type_map.get(initializer))
            c.BuildStore(self._builder, val, addr)
            return True
        return False

    def _emit_array_init_list_to_addr(self, addr: int, target_type: Type, init: InitList) -> bool:
        elem_type = target_type.element_type()
        if elem_type is None:
            return False
        length_value = target_type.declarator_ops[0][1]
        if not isinstance(length_value, int):
            return False
        length = max(length_value, 0)
        next_index = 0
        item_index = 0
        while item_index < len(init.items):
            item = init.items[item_index]
            if item.designators:
                kind, value = item.designators[0]
                if kind != "index" or not isinstance(value, Expr):
                    return False
                index = self._eval_int_constant_value(value)
                if index is None:
                    return False
                if 0 <= index < length:
                    elem_ptr = self._array_element_ptr(addr, target_type, index)
                    self._emit_initializer_to_addr(
                        elem_ptr,
                        elem_type,
                        item.designators[1:],
                        item.initializer,
                    )
                next_index = index + 1
                item_index += 1
                continue
            if next_index >= length:
                item_index += 1
                continue
            elem_ptr = self._array_element_ptr(addr, target_type, next_index)
            if self._is_single_aggregate_initializer(elem_type, item.initializer):
                self._emit_initializer_to_addr(elem_ptr, elem_type, (), item.initializer)
                next_index += 1
                item_index += 1
                continue
            consumed = self._emit_unbraced_aggregate_items_to_addr(
                elem_ptr,
                elem_type,
                init.items,
                item_index,
            )
            if consumed == 0:
                self._emit_initializer_to_addr(elem_ptr, elem_type, (), item.initializer)
                consumed = 1
            next_index += 1
            item_index += consumed
        return True

    def _emit_record_init_list_to_addr(self, addr: int, target_type: Type, init: InitList) -> bool:
        members = self._sema.record_definitions.get(target_type.name)
        if members is None:
            return False
        next_member = 0
        initialized_union = False
        is_union = target_type.name.startswith("union ")
        item_index = 0
        while item_index < len(init.items):
            item = init.items[item_index]
            if item.designators:
                kind, value = item.designators[0]
                if kind != "member" or not isinstance(value, str):
                    return False
                path = self._member_path(target_type.name, value)
                if path is None:
                    return False
                self._emit_initializer_to_lvalue(
                    self._record_path_lvalue(addr, path),
                    item.designators[1:],
                    item.initializer,
                )
                if is_union:
                    initialized_union = True
                else:
                    next_member = path[0][1] + 1
                item_index += 1
                continue
            if is_union:
                if initialized_union:
                    item_index += 1
                    continue
                member_index = self._next_initializable_record_member(members, 0)
                assert member_index is not None
                initialized_union = True
            else:
                member_index = self._next_initializable_record_member(members, next_member)
                if member_index is None:
                    item_index += 1
                    continue
                next_member = member_index + 1
            member = members[member_index]
            member_lvalue = self._record_path_lvalue(
                addr,
                [(target_type.name, member_index, member)],
            )
            if self._is_single_aggregate_initializer(member.type_, item.initializer):
                self._emit_initializer_to_lvalue(member_lvalue, (), item.initializer)
                item_index += 1
                continue
            consumed = self._emit_unbraced_aggregate_items_to_addr(
                member_lvalue.address,
                member.type_,
                init.items,
                item_index,
            )
            if consumed == 0:
                self._emit_initializer_to_lvalue(member_lvalue, (), item.initializer)
                consumed = 1
            item_index += consumed
        return True

    def _is_aggregate_type(self, type_: Type) -> bool:
        return type_.is_array() or self._is_record_type(type_)

    def _is_single_aggregate_initializer(
        self,
        target_type: Type,
        initializer: Expr | InitList,
    ) -> bool:
        if isinstance(initializer, InitList):
            return True
        if not self._is_aggregate_type(target_type):
            return True
        if isinstance(initializer, StringLiteral) and self._is_string_array_initializer(
            initializer,
            target_type,
        ):
            return True
        initializer_type = self._type_map.get(initializer)
        return (
            initializer_type is not None
            and initializer_type.name == target_type.name
            and initializer_type.declarator_ops == target_type.declarator_ops
        )

    def _is_whole_aggregate_value_initializer(
        self,
        target_type: Type,
        initializer: Expr,
    ) -> bool:
        if not self._is_aggregate_type(target_type):
            return True
        if isinstance(initializer, StringLiteral) and self._is_string_array_initializer(
            initializer,
            target_type,
        ):
            return True
        initializer_type = self._type_map.get(initializer)
        if (
            initializer_type is None
            or initializer_type.name != target_type.name
            or initializer_type.declarator_ops != target_type.declarator_ops
        ):
            return False
        if isinstance(
            initializer,
            (Identifier, MemberExpr, SubscriptExpr, CallExpr, CompoundLiteralExpr, StatementExpr),
        ):
            return True
        if isinstance(initializer, UnaryExpr) and initializer.op == "*":
            return True
        if isinstance(initializer, CommaExpr):
            return self._is_whole_aggregate_value_initializer(target_type, initializer.right)
        if isinstance(initializer, ConditionalExpr):
            return self._is_whole_aggregate_value_initializer(
                target_type,
                initializer.then_expr,
            ) and self._is_whole_aggregate_value_initializer(target_type, initializer.else_expr)
        return False

    def _emit_unbraced_aggregate_items_to_addr(
        self,
        addr: int,
        target_type: Type,
        items: tuple[InitItem, ...],
        start: int,
    ) -> int:
        if start >= len(items):
            return 0
        c = llvm()
        c.BuildStore(self._builder, c.ConstNull(self._type_to_llvm(target_type)), addr)
        if target_type.is_array():
            elem_type = target_type.element_type()
            length_value = target_type.declarator_ops[0][1]
            if elem_type is None or not isinstance(length_value, int):
                return 0
            index = start
            for elem_index in range(max(length_value, 0)):
                if index >= len(items) or items[index].designators:
                    break
                elem_ptr = self._array_element_ptr(addr, target_type, elem_index)
                consumed = self._emit_unbraced_initializer_item_to_addr(
                    elem_ptr,
                    elem_type,
                    items,
                    index,
                )
                if consumed == 0:
                    break
                index += consumed
            return index - start
        if self._is_record_type(target_type):
            members = self._sema.record_definitions.get(target_type.name)
            if members is None:
                return 0
            is_union = target_type.name.startswith("union ")
            index = start
            member_start = 0
            while True:
                if index >= len(items) or items[index].designators:
                    break
                member_index = self._next_initializable_record_member(members, member_start)
                if member_index is None:
                    break
                member = members[member_index]
                member_lvalue = self._record_path_lvalue(
                    addr,
                    [(target_type.name, member_index, member)],
                )
                if member_lvalue.bit_width is not None:
                    self._emit_initializer_to_lvalue(
                        member_lvalue,
                        (),
                        items[index].initializer,
                    )
                    consumed = 1
                else:
                    consumed = self._emit_unbraced_initializer_item_to_addr(
                        member_lvalue.address,
                        member.type_,
                        items,
                        index,
                    )
                if consumed == 0:
                    break
                index += consumed
                if is_union:
                    break
                member_start = member_index + 1
            return index - start
        return 0

    def _emit_unbraced_initializer_item_to_addr(
        self,
        addr: int,
        target_type: Type,
        items: tuple[InitItem, ...],
        index: int,
    ) -> int:
        item = items[index]
        if item.designators:
            return 0
        if self._is_single_aggregate_initializer(target_type, item.initializer):
            self._emit_initializer_to_addr(addr, target_type, (), item.initializer)
            return 1
        return self._emit_unbraced_aggregate_items_to_addr(addr, target_type, items, index)

    def _emit_initializer_to_addr(
        self,
        addr: int,
        target_type: Type,
        designators: tuple[tuple[str, Expr | str | DesignatorRange], ...],
        initializer: Expr | InitList,
    ) -> None:
        c = llvm()
        if designators:
            if target_type.is_array():
                kind, value = designators[0]
                if kind == "index" and isinstance(value, Expr):
                    index = self._eval_int_constant_value(value)
                    if index is not None:
                        elem_type = target_type.element_type()
                        if elem_type is not None:
                            elem_ptr = self._array_element_ptr(addr, target_type, index)
                            self._emit_initializer_to_addr(
                                elem_ptr,
                                elem_type,
                                designators[1:],
                                initializer,
                            )
                return
            if self._is_record_type(target_type):
                kind, value = designators[0]
                if kind == "member" and isinstance(value, str):
                    path = self._member_path(target_type.name, value)
                    if path is not None:
                        self._emit_initializer_to_lvalue(
                            self._record_path_lvalue(addr, path),
                            designators[1:],
                            initializer,
                        )
                return
        if isinstance(initializer, InitList):
            self._emit_init_list_to_addr(addr, target_type, initializer)
            return
        if isinstance(initializer, StringLiteral) and self._is_string_array_initializer(
            initializer,
            target_type,
        ):
            val = self._string_array_initializer(initializer, target_type)
            c.BuildStore(self._builder, val, addr)
            return
        initializer_type = self._type_map.get(initializer)
        if (
            initializer_type is not None
            and initializer_type.name == target_type.name
            and initializer_type.declarator_ops == target_type.declarator_ops
            and self._is_whole_aggregate_value_initializer(target_type, initializer)
        ):
            val = self._emit_expr(initializer)
            target_lt = self._type_to_llvm(target_type)
            if c.TypeOf(val) != target_lt:
                val = self._build_cast(val, target_lt, self._type_map.get(initializer))
            c.BuildStore(self._builder, val, addr)
            return
        if self._is_record_type(target_type):
            members = self._sema.record_definitions.get(target_type.name)
            if not members:
                return
            c.BuildStore(self._builder, c.ConstNull(self._type_to_llvm(target_type)), addr)
            first = members[0]
            self._emit_initializer_to_lvalue(
                self._record_path_lvalue(addr, [(target_type.name, 0, first)]),
                (),
                initializer,
            )
            return
        val = self._emit_expr(initializer)
        target_lt = self._type_to_llvm(target_type)
        if c.TypeOf(val) != target_lt:
            val = self._build_cast(val, target_lt, self._type_map.get(initializer))
        c.BuildStore(self._builder, val, addr)

    def _array_element_ptr(self, addr: int, array_type: Type, index: int) -> int:
        c = llvm()
        zero = c.ConstInt(c.Int32Type(), 0, False)
        idx = c.ConstInt(c.Int32Type(), index, index < 0)
        indices = ptr_array([zero, idx])
        return c.BuildGEP2(
            self._builder,
            self._type_to_llvm(array_type),
            addr,
            indices,
            2,
            b"init.ptr",
        )

    def _record_path_ptr(
        self,
        addr: int,
        path: list[tuple[str, int, RecordMemberInfo]],
    ) -> int:
        return self._record_path_lvalue(addr, path).address

    def _record_path_lvalue(
        self,
        addr: int,
        path: list[tuple[str, int, RecordMemberInfo]],
    ) -> _LValue:
        c = llvm()
        ptr = addr
        member_layout: RecordMemberLayout | None = None
        for step_record, field_idx, _member in path:
            member_layout = self._sema.record_layouts[step_record].members[field_idx]
            if member_layout.offset:
                index = c.ConstInt(c.Int64Type(), member_layout.offset, False)
                ptr = c.BuildGEP2(
                    self._builder,
                    c.Int8Type(),
                    ptr,
                    ptr_array([index]),
                    1,
                    b"init.ptr",
                )
        assert member_layout is not None
        member = path[-1][2]
        return _LValue(
            ptr,
            member.type_,
            member_layout.bit_offset,
            member_layout.bit_width,
            member_layout.storage_size,
        )

    def _emit_initializer_to_lvalue(
        self,
        lvalue: _LValue,
        designators: tuple[tuple[str, Expr | str | DesignatorRange], ...],
        initializer: Expr | InitList,
    ) -> None:
        if lvalue.bit_width is None:
            self._emit_initializer_to_addr(
                lvalue.address,
                lvalue.type_,
                designators,
                initializer,
            )
            return
        assert not designators
        if isinstance(initializer, InitList):
            initializer = initializer.items[0].initializer
        assert isinstance(initializer, Expr)
        self._store_lvalue(
            lvalue,
            self._emit_expr(initializer),
            self._type_map.get(initializer),
        )

    def _ensure_decl_alloca(self, stmt: DeclStmt) -> None:
        if stmt.name is None or not self._locals:
            return
        if stmt.storage_class == "static":
            self._ensure_static_local(stmt)
            return
        if stmt.storage_class == "extern":
            if stmt.is_thread_local:
                c = llvm()
                c.SetThreadLocal(self._global_var_ref(stmt.name, self._decl_type(stmt)), True)
            return
        if self._current_local_contains(stmt.name):
            return
        var_type = self._decl_type(stmt)
        lt = self._type_to_llvm(var_type)
        self._set_current_local(
            stmt.name,
            self._build_entry_alloca(
                lt,
                f"{stmt.name}.addr",
                self._type_align(var_type)
                if self._type_has_nonstandard_record_layout(var_type)
                else 0,
            ),
        )

    def _ensure_static_local(self, stmt: DeclStmt) -> int | None:
        if stmt.name is None or not self._locals:
            return None
        current_scope = self._current_local_scope()
        existing = self._lookup_local_in_scope(current_scope, stmt.name)
        if existing is not None:
            return existing

        key = id(stmt)
        gv = self._static_local_globals.get(key)
        if gv is None:
            c = llvm()
            var_type = self._decl_type(stmt)
            lt = self._type_to_llvm(var_type)
            func_name = self._func_sym.name if self._func_sym is not None else "file"
            global_name = f".static.{func_name}.{stmt.name}.{self._static_local_counter}"
            self._static_local_counter += 1
            gv = c.AddGlobal(self._mod, lt, global_name.encode())
            if self._type_has_nonstandard_record_layout(var_type):
                c.SetAlignment(gv, self._type_align(var_type))
            c.SetLinkage(gv, LLVM_INTERNAL_LINKAGE)
            if stmt.is_thread_local:
                c.SetThreadLocal(gv, True)
            self._static_local_globals[key] = gv
            self._static_local_global_values.add(gv)
            self._set_current_local(stmt.name, gv)

            init = self._eval_init(stmt.init, var_type) if stmt.init is not None else None
            c.SetInitializer(gv, init if init is not None else c.ConstNull(lt))
            return gv

        self._set_current_local(stmt.name, gv)
        return gv

    def _build_entry_alloca(self, llvm_type: int, name: str, alignment: int) -> int:
        c = llvm()
        current_bb = c.GetInsertBlock(self._builder)
        entry_bb = self._entry_block or current_bb
        term = c.GetBasicBlockTerminator(entry_bb)
        if term:
            c.PositionBuilderBefore(self._builder, term)
        else:
            c.PositionBuilderAtEnd(self._builder, entry_bb)
        alloca = c.BuildAlloca(self._builder, llvm_type, name.encode())
        if alignment:
            c.SetAlignment(alloca, alignment)
        if current_bb:  # pragma: no branch
            c.PositionBuilderAtEnd(self._builder, current_bb)
        return alloca

    def _decl_type(self, stmt: DeclStmt) -> Type:
        t = self._resolve_type(stmt.type_spec)
        if t.is_array():
            val = t.declarator_ops[0][1]
            unspecified = (isinstance(val, int) and val <= 0) or (
                isinstance(val, ArrayDecl) and val.length is None
            )
            if unspecified and isinstance(stmt.init, InitList):
                new_ops = (
                    ("arr", self._infer_array_init_length(stmt.init, t)),
                ) + t.declarator_ops[1:]
                return Type(t.name, declarator_ops=new_ops, qualifiers=t.qualifiers)
            if unspecified and isinstance(stmt.init, StringLiteral):
                inferred = self._string_array_initializer_length(stmt.init, t)
                if inferred is None:
                    return t
                new_ops = (("arr", inferred),) + t.declarator_ops[1:]
                return Type(t.name, declarator_ops=new_ops, qualifiers=t.qualifiers)
        return t

    # ── control flow ─────────────────────────────────────────

    def _emit_if(self, stmt: IfStmt) -> None:
        c = llvm()
        fn = self._func
        cond_val = self._emit_expr(stmt.condition)
        cond = self._to_bool(cond_val)

        then_bb = c.AppendBasicBlock(fn, b"if.then")
        else_bb = None
        if stmt.else_body is not None:
            else_bb = c.AppendBasicBlock(fn, b"if.else")
        merge_bb = c.AppendBasicBlock(fn, b"if.end")

        if else_bb is not None:
            c.BuildCondBr(self._builder, cond, then_bb, else_bb)
        else:
            c.BuildCondBr(self._builder, cond, then_bb, merge_bb)

        c.PositionBuilderAtEnd(self._builder, then_bb)
        self._emit_stmt(stmt.then_body)
        if self._bb_needs_term():
            c.BuildBr(self._builder, merge_bb)

        if else_bb is not None:
            c.PositionBuilderAtEnd(self._builder, else_bb)
            assert stmt.else_body is not None
            self._emit_stmt(stmt.else_body)
            if self._bb_needs_term():
                c.BuildBr(self._builder, merge_bb)

        c.PositionBuilderAtEnd(self._builder, merge_bb)

    def _emit_while(self, stmt: WhileStmt) -> None:
        c = llvm()
        fn = self._func
        cond_bb = c.AppendBasicBlock(fn, b"while.cond")
        body_bb = c.AppendBasicBlock(fn, b"while.body")
        end_bb = c.AppendBasicBlock(fn, b"while.end")

        c.BuildBr(self._builder, cond_bb)
        c.PositionBuilderAtEnd(self._builder, cond_bb)
        cond = self._to_bool(self._emit_expr(stmt.condition))
        c.BuildCondBr(self._builder, cond, body_bb, end_bb)

        c.PositionBuilderAtEnd(self._builder, body_bb)
        self._loop_stack.append(_LoopCtx(cond_bb, end_bb))
        self._break_stack.append(end_bb)
        try:
            self._emit_stmt(stmt.body)
        finally:
            self._break_stack.pop()
            self._loop_stack.pop()
        if self._bb_needs_term():
            c.BuildBr(self._builder, cond_bb)

        c.PositionBuilderAtEnd(self._builder, end_bb)

    def _emit_do_while(self, stmt: DoWhileStmt) -> None:
        c = llvm()
        fn = self._func
        body_bb = c.AppendBasicBlock(fn, b"do.body")
        cond_bb = c.AppendBasicBlock(fn, b"do.cond")
        end_bb = c.AppendBasicBlock(fn, b"do.end")

        c.BuildBr(self._builder, body_bb)
        c.PositionBuilderAtEnd(self._builder, body_bb)
        self._loop_stack.append(_LoopCtx(cond_bb, end_bb))
        self._break_stack.append(end_bb)
        try:
            self._emit_stmt(stmt.body)
        finally:
            self._break_stack.pop()
            self._loop_stack.pop()
        if self._bb_needs_term():
            c.BuildBr(self._builder, cond_bb)

        c.PositionBuilderAtEnd(self._builder, cond_bb)
        cond = self._to_bool(self._emit_expr(stmt.condition))
        c.BuildCondBr(self._builder, cond, body_bb, end_bb)

        c.PositionBuilderAtEnd(self._builder, end_bb)

    def _emit_for(self, stmt: ForStmt) -> None:
        c = llvm()
        fn = self._func
        self._locals.append({})
        try:
            if isinstance(stmt.init, Expr):
                self._emit_expr(stmt.init)
            elif stmt.init is not None:
                self._emit_stmt(stmt.init)

            cond_bb = c.AppendBasicBlock(fn, b"for.cond")
            body_bb = c.AppendBasicBlock(fn, b"for.body")
            step_bb = c.AppendBasicBlock(fn, b"for.step")
            end_bb = c.AppendBasicBlock(fn, b"for.end")

            c.BuildBr(self._builder, cond_bb)
            c.PositionBuilderAtEnd(self._builder, cond_bb)
            if stmt.condition:
                cond = self._to_bool(self._emit_expr(stmt.condition))
                c.BuildCondBr(self._builder, cond, body_bb, end_bb)
            else:
                c.BuildBr(self._builder, body_bb)

            c.PositionBuilderAtEnd(self._builder, body_bb)
            self._loop_stack.append(_LoopCtx(step_bb, end_bb))
            self._break_stack.append(end_bb)
            try:
                self._emit_stmt(stmt.body)
            finally:
                self._break_stack.pop()
                self._loop_stack.pop()
            if self._bb_needs_term():
                c.BuildBr(self._builder, step_bb)

            c.PositionBuilderAtEnd(self._builder, step_bb)
            if stmt.post:
                self._emit_expr(stmt.post)
            c.BuildBr(self._builder, cond_bb)

            c.PositionBuilderAtEnd(self._builder, end_bb)
        finally:
            self._locals.pop()

    def _emit_break(self) -> None:
        if not self._break_stack:
            raise llvm_backend_error(self._result.filename, "break not within loop or switch")
        llvm().BuildBr(self._builder, self._break_stack[-1])

    def _emit_continue(self) -> None:
        if not self._loop_stack:
            raise llvm_backend_error(self._result.filename, "continue not within loop")
        llvm().BuildBr(self._builder, self._loop_stack[-1].continue_block)

    def _label_block(self, name: str) -> int:
        block = self._label_blocks.get(name)
        if block is None:
            block = llvm().AppendBasicBlock(self._func, f"label.{name}".encode())
            self._label_blocks[name] = block
        return block

    def _emit_label(self, stmt: LabelStmt) -> None:
        c = llvm()
        block = self._label_block(stmt.name)
        current = c.GetInsertBlock(self._builder)
        if current and current != block and self._bb_needs_term(current):
            c.BuildBr(self._builder, block)
        c.PositionBuilderAtEnd(self._builder, block)
        self._emit_stmt(stmt.body)

    def _emit_goto(self, stmt: GotoStmt) -> None:
        c = llvm()
        block = self._label_block(stmt.label)
        if self._bb_needs_term():
            c.BuildBr(self._builder, block)
        continuation = c.AppendBasicBlock(self._func, b"goto.cont")
        c.PositionBuilderAtEnd(self._builder, continuation)

    def _emit_switch(self, stmt: SwitchStmt) -> None:
        c = llvm()
        fn = self._func
        cond = self._emit_expr(stmt.condition)
        end_bb = c.AppendBasicBlock(fn, b"switch.end")
        default_bb = c.AppendBasicBlock(fn, b"switch.default")

        cdt = c.TypeOf(cond)
        sw = c.BuildSwitch(self._builder, cond, default_bb, 0)
        self._switch_info.append((sw, end_bb, default_bb, False, cdt))
        self._break_stack.append(end_bb)

        try:
            self._emit_stmt(stmt.body)
        finally:
            self._break_stack.pop()

        if self._bb_needs_term():
            c.BuildBr(self._builder, end_bb)

        # If default block was never entered (no DefaultStmt), add terminator.
        _, _, _, default_handled, _ = self._switch_info[-1]
        if not default_handled:
            c.PositionBuilderAtEnd(self._builder, default_bb)
            if self._bb_needs_term(default_bb):
                c.BuildBr(self._builder, end_bb)
        c.PositionBuilderAtEnd(self._builder, end_bb)
        self._switch_info.pop()

    def _emit_case(self, stmt: CaseStmt) -> None:
        c = llvm()
        fn = self._func
        val = self._eval_case_val(stmt.value)
        case_bb = c.AppendBasicBlock(fn, b"switch.case")
        sw, end_bb, _, _, cond_t = self._switch_info[-1]
        c.AddCase(sw, c.ConstInt(cond_t, val, False), case_bb)
        current_bb = c.GetInsertBlock(self._builder)
        if current_bb and current_bb != case_bb and self._bb_needs_term(current_bb):
            c.BuildBr(self._builder, case_bb)
        c.PositionBuilderAtEnd(self._builder, case_bb)
        if stmt.body:
            self._emit_stmt(stmt.body)

    def _emit_default(self, stmt: DefaultStmt) -> None:
        sw, end_bb, default_bb, _, cond_t = self._switch_info[-1]
        self._switch_info[-1] = (sw, end_bb, default_bb, True, cond_t)
        c = llvm()
        current_bb = c.GetInsertBlock(self._builder)
        if current_bb and current_bb != default_bb and self._bb_needs_term(current_bb):
            c.BuildBr(self._builder, default_bb)
        c.PositionBuilderAtEnd(self._builder, default_bb)
        if stmt.body:
            self._emit_stmt(stmt.body)

    # ── expression emission ──────────────────────────────────

    def _emit_expr(self, expr: Expr) -> int:
        if isinstance(expr, IntLiteral):
            return self._int_literal(expr)
        if isinstance(expr, CharLiteral):
            return self._int_literal(expr)
        if isinstance(expr, FloatLiteral):
            return self._float_literal(expr)
        if isinstance(expr, StringLiteral):
            return self._string_literal(expr)
        if isinstance(expr, Identifier):
            return self._identifier(expr)
        if isinstance(expr, UnaryExpr):
            return self._unary(expr)
        if isinstance(expr, BinaryExpr):
            return self._binary(expr)
        if isinstance(expr, AssignExpr):
            return self._assign(expr)
        if isinstance(expr, CallExpr):
            return self._call(expr)
        if isinstance(expr, CastExpr):
            return self._cast(expr)
        if isinstance(expr, SubscriptExpr):
            return self._subscript(expr)
        if isinstance(expr, MemberExpr):
            return self._member(expr)
        if isinstance(expr, ConditionalExpr):
            return self._ternary(expr)
        if isinstance(expr, CommaExpr):
            self._emit_expr(expr.left)
            return self._emit_expr(expr.right)
        if isinstance(expr, SizeofExpr):
            return self._size_const(expr)
        if isinstance(expr, AlignofExpr):
            return self._size_const(expr)
        if isinstance(expr, UpdateExpr):
            return self._update(expr)
        if isinstance(expr, StatementExpr):
            return self._stmt_expr(expr)
        if isinstance(expr, CompoundLiteralExpr):
            return self._compound_literal(expr)
        if isinstance(expr, BuiltinOffsetofExpr):
            return self._offsetof_expr(expr)
        if isinstance(expr, BuiltinVaArgExpr):
            return self._va_arg(expr)
        raise llvm_backend_error(
            self._result.filename,
            f"Unsupported expression: {type(expr).__name__}",
        )

    # ── literals ─────────────────────────────────────────────

    @staticmethod
    def _parse_int_value(lexeme: str) -> int:
        """Parse a C integer literal lexeme, stripping any suffix."""
        end = len(lexeme)
        while end > 0:
            suffix_ch = lexeme[end - 1]
            if suffix_ch == "u" or suffix_ch == "U" or suffix_ch == "l" or suffix_ch == "L":
                end -= 1
                continue
            break
        if end == 0:
            return 0
        base = 10
        index = 0
        if end > 1 and lexeme[0] == "0":
            second_ch = lexeme[1]
            if second_ch == "x" or second_ch == "X":
                base = 16
                index = 2
            elif second_ch == "b" or second_ch == "B":
                base = 2
                index = 2
            else:
                base = 8
        if index >= end:
            raise ValueError("invalid integer literal")
        value = 0
        while index < end:
            ch = lexeme[index]
            codepoint = ord(ch)
            digit = 0
            valid_digit = True
            if 48 <= codepoint <= 57:
                digit = codepoint - 48
            elif 65 <= codepoint <= 70:
                digit = codepoint - 55
            elif 97 <= codepoint <= 102:
                digit = codepoint - 87
            else:
                valid_digit = False
            if not valid_digit or digit >= base:
                raise ValueError("invalid integer literal")
            value = value * base + digit
            index += 1
        return value

    def _int_literal(self, expr: IntLiteral | CharLiteral) -> int:
        c = llvm()
        val_type = self._type_map.get(expr)
        if val_type is None:
            val_type = INT
        lt = self._type_to_llvm(val_type)
        val = (
            char_literal_value(expr.value)
            if isinstance(expr, CharLiteral)
            else self._parse_int_value(expr.value)
        )
        return c.ConstInt(lt, val, False)

    def _float_literal(self, expr: FloatLiteral) -> int:
        c = llvm()
        val_type = self._type_map.get(expr)
        lt = self._type_to_llvm(val_type) if val_type else c.DoubleType()
        v = expr.value
        if v and v[-1] in "fFlL":
            v = v[:-1]
        f = float.fromhex(v) if v.startswith(("0x", "0X")) else float(v)
        return c.ConstReal(lt, f)

    def _string_literal(self, expr: StringLiteral) -> int:
        c = llvm()
        if expr.value in self._str_constants:
            gv = self._str_constants[expr.value]
        else:
            data = self._string_literal_bytes(expr)
            init_len = len(data)
            if init_len > 0 and data[init_len - 1] == 0:
                init_len -= 1
            lt = c.ArrayType(c.Int8Type(), init_len + 1)
            init = c.ConstString(data, init_len, False)
            gv = c.AddGlobal(self._mod, lt, b".str")
            c.SetInitializer(gv, init)
            c.SetLinkage(gv, LLVM_INTERNAL_LINKAGE)
            self._str_constants[expr.value] = gv
        zero = c.ConstInt(c.Int64Type(), 0, False)
        idx = ptr_array([zero, zero])
        return c.BuildGEP2(self._builder, c.TypeOf(gv), gv, idx, 2, b"str.ptr")

    def _string_literal_bytes(self, expr: StringLiteral) -> bytes:
        raw = expr.value
        body = string_literal_body(raw)
        assert body is not None
        prefix = raw.split('"', 1)[0]
        if prefix == "u":
            return self._encode_string_units(decode_escaped_units(body), 2)
        if prefix in {"L", "U"}:
            return self._encode_string_units(decode_escaped_units(body), 4)
        return narrow_string_bytes(body) + b"\x00"

    @staticmethod
    def _encode_string_units(units: list[int], width: int) -> bytes:
        data = b""
        for unit in units:
            data += unit.to_bytes(width, "little")
        return data + bytes(width)

    def _string_literal_prefix(self, expr: StringLiteral) -> str:
        return expr.value.split('"', 1)[0]

    def _string_literal_units(self, expr: StringLiteral) -> list[int]:
        body = string_literal_body(expr.value)
        assert body is not None
        return [*decode_escaped_units(body), 0]

    def _string_array_element_width(self, type_: Type) -> int | None:
        if not type_.is_array():
            return None
        elem_type = type_.element_type()
        if elem_type is None or elem_type.declarator_ops:
            return None
        if elem_type.name in ("char", "signed char", "unsigned char"):
            return 1
        if elem_type.name in ("short", "unsigned short"):
            return 2
        if elem_type.name in ("int", "unsigned int"):
            return 4
        return None

    def _is_string_array_initializer(self, expr: StringLiteral, target_type: Type) -> bool:
        width = self._string_array_element_width(target_type)
        prefix = self._string_literal_prefix(expr)
        if prefix == "u":
            return width == 2
        if prefix in {"L", "U"}:
            return width == 4
        return width == 1

    def _string_array_initializer_length(
        self,
        expr: StringLiteral,
        target_type: Type,
    ) -> int | None:
        if not self._is_string_array_initializer(expr, target_type):
            return None
        if self._string_array_element_width(target_type) == 1:
            return len(self._string_literal_bytes(expr))
        return len(self._string_literal_units(expr))

    def _string_array_initializer(self, expr: StringLiteral, target_type: Type) -> int:
        c = llvm()
        length = target_type.declarator_ops[0][1]
        assert isinstance(length, int)
        width = self._string_array_element_width(target_type)
        if width == 1:
            data = self._string_literal_bytes(expr)
            if len(data) < length:
                data += b"\x00" * (length - len(data))
            else:
                data = data[:length]
            return c.ConstString(data, length, True)
        elem_type = target_type.element_type()
        assert elem_type is not None
        elem_lt = self._type_to_llvm(elem_type)
        units = self._string_literal_units(expr)
        if len(units) < length:
            units += [0] * (length - len(units))
        else:
            units = units[:length]
        values: list[int] = []
        for unit in units:
            values.append(c.ConstInt(elem_lt, unit, False))
        return self._const_array(elem_lt, values)

    # ── identifier ───────────────────────────────────────────

    def _identifier(self, expr: Identifier) -> int:
        c = llvm()
        name = expr.name
        assert isinstance(name, str)

        if name == "__func__":  # noqa: SIM102 - keep AOT Optional narrowing explicit.
            if self._func_sym is not None:  # pragma: no branch
                func_name = self._func_sym.name
                return self._string_literal(StringLiteral('"' + func_name + '"'))

        addr = self._lookup_local(name)
        if addr is not None:
            val_type = self._type_map.require(expr)
            if val_type.is_array():
                return addr
            lt = self._type_to_llvm(val_type)
            return c.BuildLoad2(self._builder, lt, addr, name.encode())

        # Check function locals (globals)
        if self._func_sym is not None:  # noqa: SIM102  # pragma: no branch
            if name in self._func_sym.locals:
                sym = self._func_sym.locals[name]
                if isinstance(sym, EnumConstSymbol):
                    return c.ConstInt(c.Int32Type(), sym.value, True)
                if isinstance(sym, VarSymbol):
                    val_type = sym.type_
                    lt = self._type_to_llvm(val_type)
                    gv = self._global_var_ref(name, val_type)
                    if val_type.is_array():
                        return gv
                    return c.BuildLoad2(self._builder, lt, gv, name.encode())

        val_type = self._type_map.require(expr)
        if self._is_function_designator_type(val_type):
            return self._function_designator(name, val_type)
        if self._sema.file_scope is not None:
            file_symbol = self._sema.file_scope.lookup(name)
            if isinstance(file_symbol, EnumConstSymbol):
                return c.ConstInt(c.Int32Type(), file_symbol.value, True)
        lt = self._type_to_llvm(val_type)
        # Function type → reference the existing function declaration.
        if (
            c.GetTypeKind(lt) == LLVMTypeKind.FUNCTION
        ):  # pragma: no cover - function designators return above.
            fn = c.GetNamedFunction(self._mod, name.encode())
            if fn:
                return fn
            # Declare external function.
            fn = c.AddFunction(self._mod, name.encode(), lt)
            c.SetLinkage(fn, 0)
            return fn
        gv = c.GetNamedGlobal(self._mod, name.encode())
        if not gv:
            gv = self._global_var_ref(name, val_type)
        if val_type.is_array():
            return gv
        return c.BuildLoad2(self._builder, lt, gv, name.encode())

    @staticmethod
    def _is_function_designator_type(type_: Type) -> bool:
        ops = type_.declarator_ops
        return bool(ops) and ops[0][0] == "fn"

    def _function_designator(self, name: str, type_: Type) -> int:
        c = llvm()
        signature = type_.callable_signature()
        assert signature is not None
        return_type, params = signature
        fn = c.GetNamedFunction(self._mod, name.encode())
        parameter_types: tuple[Type, ...] | None = params[0]
        is_variadic = params[1]
        c_param_types: list[Type] = []
        for param in parameter_types or ():
            if param.name != "void" or param.declarator_ops:
                c_param_types.append(param)
        fn_t = self._abi_function_type(return_type, c_param_types, is_variadic)
        if name not in self._func_types:
            self._func_types[name] = fn_t
        if name not in self._func_param_types:
            self._func_param_types[name] = c_param_types
        if not fn:
            fn = c.AddFunction(self._mod, name.encode(), fn_t)
            c.SetLinkage(fn, LLVM_EXTERNAL_LINKAGE)
        if self._large_record_is_indirect(return_type):
            self._mark_sret_function(fn, return_type)
        return fn

    def _global_var_ref(self, name: str, type_: Type) -> int:
        c = llvm()
        gv = c.GetNamedGlobal(self._mod, name.encode())
        if gv:
            return gv
        lt = self._type_to_llvm(type_)
        gv = c.AddGlobal(self._mod, lt, name.encode())
        if self._type_has_nonstandard_record_layout(type_):
            c.SetAlignment(gv, self._type_align(type_))
        return gv

    def _pointer_arith_pointee(self, pointer_type: Type | None) -> Type | None:
        if pointer_type is None:
            return None
        if pointer_type.is_array():
            pointee = pointer_type.element_type()
            if pointee is None:  # pragma: no cover - Type.is_array() guarantees an element type.
                return None
            return pointee
        pointee = pointer_type.pointee()
        if pointee is None:
            return None
        if pointee.name == "void" and not pointee.declarator_ops:
            return None
        if self._is_function_designator_type(pointee):
            return None
        return pointee

    def _pointer_arith_element_llvm_type(self, pointer_type: Type | None) -> int:
        pointee = self._pointer_arith_pointee(pointer_type)
        if pointee is None:
            return llvm().Int8Type()
        return self._type_to_llvm(pointee)

    def _pointer_arith_element_size(self, pointer_type: Type | None) -> int:
        pointee = self._pointer_arith_pointee(pointer_type)
        if pointee is None:
            return 1
        return max(self._type_size(pointee), 1)

    def _lookup_local(self, name: str) -> int | None:
        index = len(self._locals)
        while index > 0:
            index -= 1
            scope = self._locals[index]
            local = self._lookup_local_in_scope(scope, name)
            if local is not None:
                return local
        return None

    def _lookup_local_in_scope(self, scope: dict[str, int], name: str) -> int | None:
        for local_name, value in scope.items():
            if local_name == name:
                return value
        return None

    def _current_local_scope(self) -> dict[str, int]:
        index = len(self._locals) - 1
        return self._locals[index]

    def _current_local_contains(self, name: str) -> bool:
        if not self._locals:
            return False
        scope = self._current_local_scope()
        for local_name, _value in scope.items():  # noqa: SIM110 - keep AOT-friendly loop.
            if local_name == name:
                return True
        return False

    def _set_current_local(self, name: str, value: int) -> None:
        if not self._locals:
            return
        index = len(self._locals) - 1
        scope = self._locals[index]
        scope[name] = value
        self._locals[index] = scope

    # ── unary ────────────────────────────────────────────────

    def _unary(self, expr: UnaryExpr) -> int:
        c = llvm()
        op = expr.op
        if op == "&":
            return self._addrof(expr)
        if op == "*":
            return self._deref(expr)
        operand = self._emit_expr(expr.operand)
        if op == "+":
            return operand
        if op == "-":
            ot = c.TypeOf(operand)
            ok = c.GetTypeKind(ot)
            if self._is_float_kind(ok):
                return c.BuildFNeg(self._builder, operand, b"neg")
            if ok == LLVMTypeKind.POINTER:
                # ptr - ptr → i64, or use ptrtoint for -ptr
                op_i64 = c.BuildPtrToInt(self._builder, operand, c.Int64Type(), b"cast")
                return c.BuildSub(
                    self._builder,
                    c.ConstInt(c.Int64Type(), 0, False),
                    op_i64,
                    b"neg",
                )
            zero = c.ConstInt(ot, 0, False)
            return c.BuildSub(self._builder, zero, operand, b"neg")
        if op == "~":
            ot = c.TypeOf(operand)
            all_ones = 0 - 1
            if c.GetTypeKind(ot) == LLVMTypeKind.POINTER:
                # Pointer ~: cast to i64 first, then xor.
                op_i64 = c.BuildPtrToInt(self._builder, operand, c.Int64Type(), b"cast")
                m1 = c.ConstInt(c.Int64Type(), all_ones, True)
                return c.BuildXor(self._builder, op_i64, m1, b"not")
            m1 = c.ConstInt(ot, all_ones, True)
            return c.BuildXor(self._builder, operand, m1, b"not")
        if op == "!":
            cond = self._to_bool(operand)
            return c.BuildZExt(
                self._builder,
                c.BuildXor(self._builder, cond, c.ConstInt(c.Int1Type(), 1, False), b"lnot"),
                c.Int32Type(),
                b"lnot.ext",
            )
        raise llvm_backend_error(self._result.filename, f"Unsupported unary: {op}")

    def _addrof(self, expr: UnaryExpr) -> int:
        operand = expr.operand
        if isinstance(operand, CompoundLiteralExpr):
            return self._compound_literal_addr(operand)
        if isinstance(operand, Identifier):
            name = operand.name
            assert isinstance(name, str)
            local = self._lookup_local(name)
            if local is not None:
                return local
            c = llvm()
            operand_type = self._type_map.get(operand) or self._lookup_symbol_type(name)
            if operand_type is not None:
                if self._is_function_designator_type(operand_type):
                    return self._function_designator(name, operand_type)
                return self._global_var_ref(name, operand_type)
            gv = c.GetNamedGlobal(self._mod, name.encode())
            if gv:
                return gv
            fn = c.GetNamedFunction(self._mod, name.encode())
            if fn:
                return fn
            raise llvm_backend_error(
                self._result.filename,
                f"Unknown address target: {name}",
            )
        if isinstance(operand, SubscriptExpr):
            return self._subscript_ptr(operand)
        if isinstance(operand, MemberExpr):
            return self._member_ptr(operand)
        if isinstance(operand, UnaryExpr) and operand.op == "*":
            return self._emit_expr(operand.operand)
        raise llvm_backend_error(self._result.filename, f"Unsupported &{type(operand).__name__}")

    def _deref(self, expr: UnaryExpr) -> int:
        c = llvm()
        ptr = self._emit_expr(expr.operand)
        operand_type = self._type_map.get(expr.operand)
        pointee = None if operand_type is None else operand_type.pointee()
        if pointee is not None and self._is_function_designator_type(pointee):
            return ptr
        val_type = self._type_map.require(expr)
        lt = self._type_to_llvm(val_type)
        return c.BuildLoad2(self._builder, lt, ptr, b"deref")

    # ── binary ───────────────────────────────────────────────

    def _binary(self, expr: BinaryExpr) -> int:
        c = llvm()
        op = expr.op

        if op in {"&&", "||"}:
            return self._logical(expr)

        left_c_type = self._type_map.get(expr.left)
        right_c_type = self._type_map.get(expr.right)
        left = self._emit_expr(expr.left)
        right = self._emit_expr(expr.right)
        left_is_null_pointer_constant = self._is_zero_int_literal(expr.left)
        right_is_null_pointer_constant = self._is_zero_int_literal(expr.right)

        if op in {"==", "!=", "<", ">", "<=", ">="}:
            if op == "==" or op == "!=":
                null_cmp = self._compare_pointer_null(
                    op,
                    left,
                    right,
                    left_c_type,
                    right_c_type,
                    left_is_null_pointer_constant,
                    right_is_null_pointer_constant,
                )
                if null_cmp is not None:
                    return null_cmp
            return self._compare(
                op,
                left,
                right,
                left_c_type,
                right_c_type,
                left_is_null_pointer_constant,
                right_is_null_pointer_constant,
            )

        result_type = self._type_map.require(expr)
        self._type_to_llvm(result_type)

        # Pointer arithmetic: ptr ± int → GEP
        lt = c.TypeOf(left)
        rt = c.TypeOf(right)
        # Decay array operands
        if c.GetTypeKind(lt) == LLVMTypeKind.ARRAY:
            left = self._build_cast(left, c.PointerType(c.Int8Type(), 0))
            lt = c.TypeOf(left)
        if c.GetTypeKind(rt) == LLVMTypeKind.ARRAY:
            right = self._build_cast(right, c.PointerType(c.Int8Type(), 0))
            rt = c.TypeOf(right)
        # Commute int + ptr → ptr + int
        rk_ptr = c.GetTypeKind(c.TypeOf(right))
        if (
            op in ("+", "-")
            and rk_ptr == LLVMTypeKind.POINTER
            and c.GetTypeKind(lt) != LLVMTypeKind.POINTER
        ):
            left, right = right, left
            left_c_type, right_c_type = right_c_type, left_c_type
            lt = c.TypeOf(left)
            rt = c.TypeOf(right)
        if op in ("+", "-") and c.GetTypeKind(lt) == LLVMTypeKind.POINTER:
            rk = c.GetTypeKind(rt)
            if rk == LLVMTypeKind.POINTER:
                # ptr - ptr: use ptrtoint + integer arithmetic
                li = c.BuildPtrToInt(self._builder, left, c.Int64Type(), b"cast")
                ri = c.BuildPtrToInt(self._builder, right, c.Int64Type(), b"cast")
                diff = c.BuildSub(self._builder, li, ri, b"ptr.diff")
                elem_size = self._pointer_arith_element_size(left_c_type)
                if elem_size > 1:
                    size_val = c.ConstInt(c.Int64Type(), elem_size, False)
                    diff = c.BuildSDiv(self._builder, diff, size_val, b"ptr.diff.scaled")
                return diff
            right = self._gep_index_value(right, right_c_type, b"ptr.idx")
            if op == "-":
                right = c.BuildNeg(self._builder, right, b"neg")
            idx = ptr_array([right])
            elem_lt = self._pointer_arith_element_llvm_type(left_c_type)
            return c.BuildGEP2(self._builder, elem_lt, left, idx, 1, b"ptr.arith")

        lk = c.GetTypeKind(lt)
        rk = c.GetTypeKind(rt)
        l_float = self._is_float_kind(lk)
        r_float = self._is_float_kind(rk)

        if l_float and not r_float:
            right = c.BuildSIToFP(self._builder, right, lt, b"bin.cast")
            r_float = True
            rk = c.GetTypeKind(c.TypeOf(right))
        elif r_float and not l_float:
            left = c.BuildSIToFP(self._builder, left, rt, b"bin.cast")
            l_float = True
            lk = c.GetTypeKind(c.TypeOf(left))
        elif l_float and r_float and lt != rt:
            if self._float_rank(lk) >= self._float_rank(rk):
                right = c.BuildFPCast(self._builder, right, lt, b"bin.cast")
                rt = lt
                rk = lk
            else:
                left = c.BuildFPCast(self._builder, left, rt, b"bin.cast")
                lt = rt
                lk = rk

        # For integer ops, match operand widths to avoid i32 vs i64 errors.
        both_int = lk == LLVMTypeKind.INTEGER and rk == LLVMTypeKind.INTEGER
        if not l_float and not r_float and both_int:
            target_t = self._type_to_llvm(result_type)
            if c.GetTypeKind(target_t) == LLVMTypeKind.INTEGER:
                left = self._cast_integer_value(left, target_t, left_c_type, b"bin.cast")
                right = self._cast_integer_value(right, target_t, right_c_type, b"bin.cast")
                lt = target_t
                rt = target_t

        result = 0
        if l_float or r_float:
            if op == "+":
                result = c.BuildFAdd(self._builder, left, right, b"binop")
            elif op == "-":
                result = c.BuildFSub(self._builder, left, right, b"binop")
            elif op == "*":
                result = c.BuildFMul(self._builder, left, right, b"binop")
            elif op == "/":  # pragma: no branch
                result = c.BuildFDiv(self._builder, left, right, b"binop")
        else:
            unsigned_result = self._is_unsigned_integer_c_type(result_type)
            if op == "+":
                result = c.BuildAdd(self._builder, left, right, b"binop")
            elif op == "-":
                result = c.BuildSub(self._builder, left, right, b"binop")
            elif op == "*":
                result = c.BuildMul(self._builder, left, right, b"binop")
            elif op == "/":
                if unsigned_result:
                    result = c.BuildUDiv(self._builder, left, right, b"binop")
                else:
                    result = c.BuildSDiv(self._builder, left, right, b"binop")
            elif op == "%":
                if unsigned_result:
                    result = c.BuildURem(self._builder, left, right, b"binop")
                else:
                    result = c.BuildSRem(self._builder, left, right, b"binop")
            elif op == "&":
                result = c.BuildAnd(self._builder, left, right, b"binop")
            elif op == "|":
                result = c.BuildOr(self._builder, left, right, b"binop")
            elif op == "^":
                result = c.BuildXor(self._builder, left, right, b"binop")
            elif op == "<<":
                result = c.BuildShl(self._builder, left, right, b"binop")
            elif op == ">>":
                if unsigned_result:
                    result = c.BuildLShr(self._builder, left, right, b"binop")
                else:
                    result = c.BuildAShr(self._builder, left, right, b"binop")

        if result == 0:
            raise llvm_backend_error(self._result.filename, f"Unsupported binary: {op}")
        return result

    def _compare_pointer_null(
        self,
        op: str,
        left: int,
        right: int,
        left_c_type: Type | None,
        right_c_type: Type | None,
        left_is_null_pointer_constant: bool,
        right_is_null_pointer_constant: bool,
    ) -> int | None:
        if self._is_pointer_comparison_type(left_c_type) and right_is_null_pointer_constant:
            return self._compare_pointer_truth(op, left)
        if self._is_pointer_comparison_type(right_c_type) and left_is_null_pointer_constant:
            return self._compare_pointer_truth(op, right)
        return None

    def _is_pointer_comparison_type(self, type_: Type | None) -> bool:
        if type_ is None:
            return False
        return type_.pointee() is not None or type_.is_array()

    def _compare_pointer_truth(self, op: str, value: int) -> int:
        c = llvm()
        value_type = c.TypeOf(value)
        if c.GetTypeKind(value_type) == LLVMTypeKind.ARRAY:
            value = self._build_cast(value, c.PointerType(c.Int8Type(), 0))
            value_type = c.TypeOf(value)
        null = c.ConstNull(value_type)
        if op == "==":
            cmp = c.BuildICmp(self._builder, 32, value, null, b"cmp")
        else:
            cmp = c.BuildICmp(self._builder, 33, value, null, b"cmp")
        return c.BuildZExt(self._builder, cmp, c.Int32Type(), b"cmp.ext")

    def _compare(
        self,
        op: str,
        left: int,
        right: int,
        left_c_type: Type | None,
        right_c_type: Type | None,
        left_is_null_pointer_constant: bool,
        right_is_null_pointer_constant: bool,
    ) -> int:
        c = llvm()
        lt = c.TypeOf(left)
        rt = c.TypeOf(right)
        lk = c.GetTypeKind(lt)
        rk = c.GetTypeKind(rt)
        # Decay array operands to pointer
        if lk == LLVMTypeKind.ARRAY:
            left = self._build_cast(left, c.PointerType(c.Int8Type(), 0))
            lt = c.TypeOf(left)
            lk = LLVMTypeKind.POINTER
        if rk == LLVMTypeKind.ARRAY:
            right = self._build_cast(right, c.PointerType(c.Int8Type(), 0))
            rt = c.TypeOf(right)
            rk = LLVMTypeKind.POINTER
        l_float = self._is_float_kind(lk)
        r_float = self._is_float_kind(rk)

        if l_float and not r_float:
            right = c.BuildSIToFP(self._builder, right, lt, b"cast")
            r_float = True
            rt = lt
            rk = lk
        elif r_float and not l_float:
            left = c.BuildSIToFP(self._builder, left, rt, b"cast")
            l_float = True
            lt = rt
            lk = rk
        elif l_float and r_float and lt != rt:
            if self._float_rank(lk) >= self._float_rank(rk):
                right = c.BuildFPCast(self._builder, right, lt, b"cast")
                rt = lt
                rk = lk
            else:
                left = c.BuildFPCast(self._builder, left, rt, b"cast")
                lt = rt
                lk = rk

        if l_float:
            pred = 0
            if op == "==":
                pred = 1
            elif op == "!=":
                pred = 6
            elif op == "<":
                pred = 4
            elif op == ">":
                pred = 2
            elif op == "<=":
                pred = 5
            elif op == ">=":
                pred = 3
            if pred == 0:
                raise llvm_backend_error(self._result.filename, f"Unsupported compare: {op}")
            cmp = c.BuildFCmp(self._builder, pred, left, right, b"cmp")
        else:
            unsigned_compare = False
            # Normalize pointer ↔ integer comparisons: convert
            # the integer operand to a pointer so icmp is valid.
            if lk == LLVMTypeKind.POINTER and rk == LLVMTypeKind.INTEGER:
                if right_is_null_pointer_constant:
                    right = c.ConstNull(lt)
                else:
                    right = c.BuildIntToPtr(self._builder, right, lt, b"cmp.cast")
            elif rk == LLVMTypeKind.POINTER and lk == LLVMTypeKind.INTEGER:
                if left_is_null_pointer_constant:
                    left = c.ConstNull(rt)
                else:
                    left = c.BuildIntToPtr(self._builder, left, rt, b"cmp.cast")
            elif lk == LLVMTypeKind.INTEGER and rk == LLVMTypeKind.INTEGER:
                common_type = self._common_integer_c_type(left_c_type, right_c_type)
                if common_type is not None:
                    target_t = self._type_to_llvm(common_type)
                    left = self._cast_integer_value(left, target_t, left_c_type, b"cmp.cast")
                    right = self._cast_integer_value(right, target_t, right_c_type, b"cmp.cast")
                    unsigned_compare = self._is_unsigned_integer_c_type(common_type)
                elif lt != rt:
                    # Match integer widths for icmp.
                    lw = c.GetIntTypeWidth(lt)
                    rw = c.GetIntTypeWidth(rt)
                    if lw > rw:
                        right = self._cast_integer_value(right, lt, right_c_type, b"cmp.cast")
                    elif rw > lw:  # pragma: no branch
                        left = self._cast_integer_value(left, rt, left_c_type, b"cmp.cast")
            pred = 0
            if op == "==":
                pred = 32
            elif op == "!=":
                pred = 33
            elif unsigned_compare:
                if op == "<":
                    pred = 36
                elif op == ">":
                    pred = 34
                elif op == "<=":
                    pred = 37
                elif op == ">=":  # pragma: no branch
                    pred = 35
            else:
                if op == "<":
                    pred = 40
                elif op == ">":
                    pred = 38
                elif op == "<=":
                    pred = 41
                elif op == ">=":
                    pred = 39
            if pred == 0:
                raise llvm_backend_error(self._result.filename, f"Unsupported compare: {op}")
            cmp = c.BuildICmp(self._builder, pred, left, right, b"cmp")
        return c.BuildZExt(self._builder, cmp, c.Int32Type(), b"cmp.ext")

    def _is_zero_int_literal(self, expr: Expr) -> bool:
        if isinstance(expr, IntLiteral):
            return self._parse_int_value(expr.value) == 0
        return False

    def _logical(self, expr: BinaryExpr) -> int:
        c = llvm()
        fn = self._func
        lhs = self._to_bool(self._emit_expr(expr.left))

        rhs_bb = c.AppendBasicBlock(fn, b"log.rhs")
        short_bb = c.AppendBasicBlock(fn, b"log.short")
        end_bb = c.AppendBasicBlock(fn, b"log.end")

        alloca = self._build_entry_alloca(c.Int32Type(), "log.res", 0)
        if expr.op == "&&":
            c.BuildCondBr(self._builder, lhs, rhs_bb, short_bb)
            short_val = 0
        else:
            c.BuildCondBr(self._builder, lhs, short_bb, rhs_bb)
            short_val = 1

        c.PositionBuilderAtEnd(self._builder, short_bb)
        c.BuildStore(self._builder, c.ConstInt(c.Int32Type(), short_val, False), alloca)
        c.BuildBr(self._builder, end_bb)

        c.PositionBuilderAtEnd(self._builder, rhs_bb)
        rhs = self._to_bool(self._emit_expr(expr.right))
        rhs_ext = c.BuildZExt(self._builder, rhs, c.Int32Type(), b"log.rhs.ext")
        c.BuildStore(self._builder, rhs_ext, alloca)
        c.BuildBr(self._builder, end_bb)

        c.PositionBuilderAtEnd(self._builder, end_bb)
        return c.BuildLoad2(self._builder, c.Int32Type(), alloca, b"log.res")

    # ── assign ───────────────────────────────────────────────

    def _assign(self, expr: AssignExpr) -> int:
        c = llvm()
        val = self._emit_expr(expr.value)

        target = expr.target
        lvalue = self._lvalue(target)

        if expr.op == "=":
            return self._store_lvalue(lvalue, val, self._type_map.get(expr.value))

        # Compound: load, compute, store
        target_type = lvalue.type_
        lt = self._type_to_llvm(target_type)
        old = self._load_lvalue(lvalue)

        lk = c.GetTypeKind(lt)

        # Pointer += / -= : use GEP
        if lk == LLVMTypeKind.POINTER and expr.op in ("+=", "-="):
            val = self._gep_index_value(val, self._type_map.get(expr.value), b"ptr.idx")
            if expr.op == "-=":
                val = c.BuildNeg(self._builder, val, b"neg")
            idx = ptr_array([val])
            elem_lt = self._pointer_arith_element_llvm_type(target_type)
            result = c.BuildGEP2(self._builder, elem_lt, old, idx, 1, b"ptr.arith")
            return self._store_lvalue(lvalue, result)

        # Match operand widths for mixed integer types.
        vt = c.TypeOf(val)
        vk = c.GetTypeKind(vt)
        if lk == LLVMTypeKind.INTEGER and vk == LLVMTypeKind.INTEGER and lt != vt:
            val = self._cast_integer_value(val, lt, self._type_map.get(expr.value), b"cmpd.cast")

        is_float = self._is_float_kind(lk)
        if is_float and vt != lt:
            if vk == LLVMTypeKind.INTEGER:
                val = c.BuildSIToFP(self._builder, val, lt, b"cmpd.cast")
            elif self._is_float_kind(vk):  # pragma: no branch
                val = c.BuildFPCast(self._builder, val, lt, b"cmpd.cast")

        result = 0
        if is_float:
            if expr.op == "+=":
                result = c.BuildFAdd(self._builder, old, val, b"compound")
            elif expr.op == "-=":
                result = c.BuildFSub(self._builder, old, val, b"compound")
            elif expr.op == "*=":
                result = c.BuildFMul(self._builder, old, val, b"compound")
            elif expr.op == "/=":  # pragma: no branch
                result = c.BuildFDiv(self._builder, old, val, b"compound")
        else:
            unsigned_target = self._is_unsigned_integer_c_type(target_type)
            if expr.op == "+=":
                result = c.BuildAdd(self._builder, old, val, b"compound")
            elif expr.op == "-=":
                result = c.BuildSub(self._builder, old, val, b"compound")
            elif expr.op == "*=":
                result = c.BuildMul(self._builder, old, val, b"compound")
            elif expr.op == "/=":
                if unsigned_target:
                    result = c.BuildUDiv(self._builder, old, val, b"compound")
                else:
                    result = c.BuildSDiv(self._builder, old, val, b"compound")
            elif expr.op == "%=":
                if unsigned_target:
                    result = c.BuildURem(self._builder, old, val, b"compound")
                else:
                    result = c.BuildSRem(self._builder, old, val, b"compound")
            elif expr.op == "&=":
                result = c.BuildAnd(self._builder, old, val, b"compound")
            elif expr.op == "|=":
                result = c.BuildOr(self._builder, old, val, b"compound")
            elif expr.op == "^=":
                result = c.BuildXor(self._builder, old, val, b"compound")
            elif expr.op == "<<=":
                result = c.BuildShl(self._builder, old, val, b"compound")
            elif expr.op == ">>=":
                if unsigned_target:
                    result = c.BuildLShr(self._builder, old, val, b"compound")
                else:
                    result = c.BuildAShr(self._builder, old, val, b"compound")

        if result == 0:
            raise llvm_backend_error(self._result.filename, f"Unsupported compound: {expr.op}")
        return self._store_lvalue(lvalue, result, target_type)

    def _assign_addr(self, target: Expr) -> int:
        return self._lvalue(target).address

    # ── update ───────────────────────────────────────────────

    def _update(self, expr: UpdateExpr) -> int:
        c = llvm()
        delta = 1 if expr.op == "++" else -1
        target = expr.operand
        lvalue = self._lvalue(target)
        target_type = lvalue.type_
        lt = self._type_to_llvm(target_type)
        old = self._load_lvalue(lvalue)
        if c.GetTypeKind(lt) == LLVMTypeKind.POINTER:
            # Pointer arithmetic: use i64 delta with GEP
            idx = c.ConstInt(c.Int64Type(), delta, True)
            idx_arr = ptr_array([idx])
            elem_lt = self._pointer_arith_element_llvm_type(target_type)
            new_v = c.BuildGEP2(self._builder, elem_lt, old, idx_arr, 1, b"update.gep")
        elif self._is_float_kind(c.GetTypeKind(lt)):
            delta_v = c.ConstReal(lt, float(delta))
            new_v = c.BuildFAdd(self._builder, old, delta_v, b"update.new")
        else:
            delta_v = c.ConstInt(lt, delta, True)
            new_v = c.BuildAdd(self._builder, old, delta_v, b"update.new")
        stored = self._store_lvalue(lvalue, new_v, target_type)
        return old if expr.is_postfix else stored

    # ── atomic builtins ──────────────────────────────────────

    def _atomic_pointer(self, expr: Expr) -> tuple[int, Type, int]:
        c = llvm()
        ptr = self._emit_expr(expr)
        ptr_type = self._type_map.get(expr)
        pointee = None if ptr_type is None else ptr_type.pointee()
        if pointee is None:
            pointee = INT
        lt = self._type_to_llvm(pointee)
        if c.GetTypeKind(lt) == LLVMTypeKind.VOID:
            pointee = INT
            lt = c.Int32Type()
        return ptr, pointee, lt

    def _atomic_align(self, type_: Type) -> int:
        return max(1, self._type_align(type_))

    def _atomic_load_value(self, ptr: int, type_: Type, lt: int) -> int:
        c = llvm()
        load = c.BuildLoad2(self._builder, lt, ptr, b"atomic.load")
        c.SetOrdering(load, ATOMIC_ORDER_SEQ_CST)
        c.SetAlignment(load, self._atomic_align(type_))
        return load

    def _atomic_store_value(self, ptr: int, type_: Type, lt: int, value: int) -> int:
        c = llvm()
        if c.TypeOf(value) != lt:
            value = self._build_cast(value, lt)
        store = c.BuildStore(self._builder, value, ptr)
        c.SetOrdering(store, ATOMIC_ORDER_SEQ_CST)
        c.SetAlignment(store, self._atomic_align(type_))
        return c.ConstInt(c.Int32Type(), 0, False)

    def _atomic_rmw_value(self, op: int, ptr: int, type_: Type, lt: int, value: int) -> int:
        c = llvm()
        if c.TypeOf(value) != lt:
            value = self._build_cast(value, lt)
        rmw = c.BuildAtomicRMW(self._builder, op, ptr, value, ATOMIC_ORDER_SEQ_CST, False)
        c.SetValueName2(rmw, b"atomic.rmw", len(b"atomic.rmw"))
        c.SetAlignment(rmw, self._atomic_align(type_))
        return rmw

    def _atomic_promote_result(self, value: int, type_: Type) -> int:
        c = llvm()
        value_type = c.TypeOf(value)
        if c.GetTypeKind(value_type) != LLVMTypeKind.INTEGER:
            return value
        if c.GetIntTypeWidth(value_type) >= 32:
            return value
        if type_.name.startswith("unsigned") or type_.name == "_Bool":
            return c.BuildZExt(self._builder, value, c.Int32Type(), b"atomic.promote")
        return c.BuildSExt(self._builder, value, c.Int32Type(), b"atomic.promote")

    def _atomic_rmw_new_value(self, op: int, old: int, value: int) -> int:
        c = llvm()
        if op == ATOMIC_RMW_ADD:
            return c.BuildAdd(self._builder, old, value, b"atomic.new")
        if op == ATOMIC_RMW_SUB:
            return c.BuildSub(self._builder, old, value, b"atomic.new")
        if op == ATOMIC_RMW_AND:
            return c.BuildAnd(self._builder, old, value, b"atomic.new")
        if op == ATOMIC_RMW_OR:
            return c.BuildOr(self._builder, old, value, b"atomic.new")
        if op == ATOMIC_RMW_XOR:
            return c.BuildXor(self._builder, old, value, b"atomic.new")
        if op == ATOMIC_RMW_NAND:
            and_value = c.BuildAnd(self._builder, old, value, b"atomic.and")
            all_ones = 0 - 1
            return c.BuildXor(
                self._builder,
                and_value,
                c.ConstInt(c.TypeOf(and_value), all_ones, True),
                b"atomic.new",
            )
        return value

    def _atomic_compare_exchange(
        self,
        ptr: int,
        type_: Type,
        lt: int,
        expected_ptr: int,
        desired: int,
    ) -> int:
        c = llvm()
        if c.TypeOf(desired) != lt:
            desired = self._build_cast(desired, lt)
        expected = c.BuildLoad2(self._builder, lt, expected_ptr, b"atomic.expected")
        cmpxchg = c.BuildAtomicCmpXchg(
            self._builder,
            ptr,
            expected,
            desired,
            ATOMIC_ORDER_SEQ_CST,
            ATOMIC_ORDER_SEQ_CST,
            False,
        )
        c.SetValueName2(cmpxchg, b"atomic.cmpxchg", len(b"atomic.cmpxchg"))
        c.SetAlignment(cmpxchg, self._atomic_align(type_))
        old = c.BuildExtractValue(self._builder, cmpxchg, 0, b"atomic.old")
        success = c.BuildExtractValue(self._builder, cmpxchg, 1, b"atomic.ok")
        c.BuildStore(self._builder, old, expected_ptr)
        return c.BuildZExt(self._builder, success, c.Int32Type(), b"atomic.ok.ext")

    def _atomic_builtin_call(self, callee_name: str, args: tuple[Expr, ...]) -> int | None:
        c = llvm()
        if callee_name in {
            "__atomic_thread_fence",
            "__atomic_signal_fence",
            "__c11_atomic_thread_fence",
            "__c11_atomic_signal_fence",
            "__sync_synchronize",
            "__scoped_atomic_thread_fence",
        }:
            c.BuildFence(self._builder, ATOMIC_ORDER_SEQ_CST, False, b"")
            return c.ConstInt(c.Int32Type(), 0, False)

        if callee_name in {
            "__atomic_is_lock_free",
            "__atomic_always_lock_free",
            "__c11_atomic_is_lock_free",
        }:
            return c.ConstInt(c.Int32Type(), 1, False)

        if callee_name in {"__atomic_load_n", "__c11_atomic_load", "__scoped_atomic_load"}:
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            value = self._atomic_load_value(ptr, elem_type, elem_lt)
            return self._atomic_promote_result(value, elem_type)

        if callee_name in {
            "__atomic_store_n",
            "__c11_atomic_store",
            "__c11_atomic_init",
            "__scoped_atomic_store",
        }:
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            value = self._emit_expr(args[1])
            return self._atomic_store_value(ptr, elem_type, elem_lt, value)

        if callee_name == "__atomic_load":
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            out_ptr = self._emit_expr(args[1])
            value = self._atomic_load_value(ptr, elem_type, elem_lt)
            return self._atomic_store_value(out_ptr, elem_type, elem_lt, value)

        if callee_name == "__atomic_store":
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            in_ptr = self._emit_expr(args[1])
            value = c.BuildLoad2(self._builder, elem_lt, in_ptr, b"atomic.in")
            return self._atomic_store_value(ptr, elem_type, elem_lt, value)

        fetch_op = -1
        if callee_name in {
            "__atomic_fetch_add",
            "__sync_fetch_and_add",
            "__c11_atomic_fetch_add",
            "__scoped_atomic_fetch_add",
        }:
            fetch_op = ATOMIC_RMW_ADD
        elif callee_name in {
            "__atomic_fetch_sub",
            "__sync_fetch_and_sub",
            "__c11_atomic_fetch_sub",
        }:
            fetch_op = ATOMIC_RMW_SUB
        elif callee_name in {
            "__atomic_fetch_and",
            "__sync_fetch_and_and",
            "__c11_atomic_fetch_and",
        }:
            fetch_op = ATOMIC_RMW_AND
        elif callee_name in {
            "__atomic_fetch_or",
            "__sync_fetch_and_or",
            "__c11_atomic_fetch_or",
        }:
            fetch_op = ATOMIC_RMW_OR
        elif callee_name in {
            "__atomic_fetch_xor",
            "__sync_fetch_and_xor",
            "__c11_atomic_fetch_xor",
        }:
            fetch_op = ATOMIC_RMW_XOR
        elif callee_name == "__atomic_fetch_nand":
            fetch_op = ATOMIC_RMW_NAND
        if fetch_op >= 0:
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            value = self._emit_expr(args[1])
            old = self._atomic_rmw_value(fetch_op, ptr, elem_type, elem_lt, value)
            return self._atomic_promote_result(old, elem_type)

        new_op = -1
        if callee_name in {"__atomic_add_fetch", "__sync_add_and_fetch"}:
            new_op = ATOMIC_RMW_ADD
        elif callee_name in {"__atomic_sub_fetch", "__sync_sub_and_fetch"}:
            new_op = ATOMIC_RMW_SUB
        elif callee_name in {"__atomic_and_fetch", "__sync_and_and_fetch"}:
            new_op = ATOMIC_RMW_AND
        elif callee_name in {"__atomic_or_fetch", "__sync_or_and_fetch"}:
            new_op = ATOMIC_RMW_OR
        elif callee_name in {"__atomic_xor_fetch", "__sync_xor_and_fetch"}:
            new_op = ATOMIC_RMW_XOR
        elif callee_name == "__atomic_nand_fetch":
            new_op = ATOMIC_RMW_NAND
        if new_op >= 0:
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            value = self._emit_expr(args[1])
            if c.TypeOf(value) != elem_lt:
                value = self._build_cast(value, elem_lt)
            old = self._atomic_rmw_value(new_op, ptr, elem_type, elem_lt, value)
            new_value = self._atomic_rmw_new_value(new_op, old, value)
            return self._atomic_promote_result(new_value, elem_type)

        if callee_name in {
            "__atomic_exchange_n",
            "__c11_atomic_exchange",
            "__sync_lock_test_and_set",
        }:
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            value = self._emit_expr(args[1])
            old = self._atomic_rmw_value(ATOMIC_RMW_XCHG, ptr, elem_type, elem_lt, value)
            return self._atomic_promote_result(old, elem_type)

        if callee_name == "__atomic_exchange":
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            in_ptr = self._emit_expr(args[1])
            out_ptr = self._emit_expr(args[2])
            value = c.BuildLoad2(self._builder, elem_lt, in_ptr, b"atomic.in")
            old = self._atomic_rmw_value(ATOMIC_RMW_XCHG, ptr, elem_type, elem_lt, value)
            return self._atomic_store_value(out_ptr, elem_type, elem_lt, old)

        if callee_name in {
            "__atomic_compare_exchange_n",
            "__c11_atomic_compare_exchange_strong",
            "__c11_atomic_compare_exchange_weak",
        }:
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            expected_ptr = self._emit_expr(args[1])
            desired = self._emit_expr(args[2])
            return self._atomic_compare_exchange(ptr, elem_type, elem_lt, expected_ptr, desired)

        if callee_name == "__atomic_compare_exchange":
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            expected_ptr = self._emit_expr(args[1])
            desired_ptr = self._emit_expr(args[2])
            desired = c.BuildLoad2(self._builder, elem_lt, desired_ptr, b"atomic.desired")
            return self._atomic_compare_exchange(ptr, elem_type, elem_lt, expected_ptr, desired)

        if callee_name in {"__sync_val_compare_and_swap", "__sync_bool_compare_and_swap"}:
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            expected = self._emit_expr(args[1])
            desired = self._emit_expr(args[2])
            if c.TypeOf(expected) != elem_lt:
                expected = self._build_cast(expected, elem_lt)
            if c.TypeOf(desired) != elem_lt:
                desired = self._build_cast(desired, elem_lt)
            cmpxchg = c.BuildAtomicCmpXchg(
                self._builder,
                ptr,
                expected,
                desired,
                ATOMIC_ORDER_SEQ_CST,
                ATOMIC_ORDER_SEQ_CST,
                False,
            )
            c.SetValueName2(cmpxchg, b"sync.cmpxchg", len(b"sync.cmpxchg"))
            c.SetAlignment(cmpxchg, self._atomic_align(elem_type))
            old = c.BuildExtractValue(self._builder, cmpxchg, 0, b"sync.old")
            if callee_name == "__sync_val_compare_and_swap":
                return self._atomic_promote_result(old, elem_type)
            success = c.BuildExtractValue(self._builder, cmpxchg, 1, b"sync.ok")
            return c.BuildZExt(self._builder, success, c.Int32Type(), b"sync.ok.ext")

        if callee_name == "__sync_lock_release":
            ptr, elem_type, elem_lt = self._atomic_pointer(args[0])
            return self._atomic_store_value(
                ptr,
                elem_type,
                elem_lt,
                c.ConstInt(elem_lt, 0, False),
            )

        return None

    # ── GCC/Clang builtins ──────────────────────────────────

    def _int_type_for_width(self, width: int) -> int:
        c = llvm()
        if width == 1:
            return c.Int1Type()
        if width == 8:
            return c.Int8Type()
        if width == 16:
            return c.Int16Type()
        if width == 32:
            return c.Int32Type()
        if width == 64:
            return c.Int64Type()
        return c.Int64Type()

    def _cast_int_to_width(self, value: int, width: int, *, signed: bool) -> int:
        c = llvm()
        target_t = self._int_type_for_width(width)
        value_t = c.TypeOf(value)
        value_kind = c.GetTypeKind(value_t)
        if value_t == target_t:
            return value
        if value_kind == LLVMTypeKind.POINTER:
            return c.BuildPtrToInt(self._builder, value, target_t, b"builtin.ptrint")
        if value_kind != LLVMTypeKind.INTEGER:
            return self._build_cast(value, target_t)
        value_width = c.GetIntTypeWidth(value_t)
        if value_width < width:
            if signed:
                return c.BuildSExt(self._builder, value, target_t, b"builtin.ext")
            return c.BuildZExt(self._builder, value, target_t, b"builtin.ext")
        if value_width > width:
            return c.BuildTrunc(self._builder, value, target_t, b"builtin.trunc")
        return value  # pragma: no cover - LLVM integer types are uniqued by width.

    def _result_type_ref(self, expr: CallExpr) -> int:
        return self._type_to_llvm(self._type_map.require(expr))

    def _coerce_builtin_result(self, value: int, expr: CallExpr) -> int:
        result_type = self._type_map.require(expr)
        target_t = self._type_to_llvm(result_type)
        if llvm().GetTypeKind(target_t) == LLVMTypeKind.VOID:
            return value
        if llvm().TypeOf(value) == target_t:
            return value
        return self._build_cast(value, target_t)

    def _intrinsic_call(
        self,
        name: str,
        return_type: int,
        values: list[int],
        param_types: list[int],
    ) -> int:
        c = llvm()
        n = len(values)
        params = None if n == 0 else ptr_array(param_types)
        args = None if n == 0 else ptr_array(values)
        fn_t = c.FunctionType(return_type, params, n, False)
        fn = c.GetNamedFunction(self._mod, name.encode())
        if not fn:
            fn = c.AddFunction(self._mod, name.encode(), fn_t)
        call_name = b"" if c.GetTypeKind(return_type) == LLVMTypeKind.VOID else b"call"
        return c.BuildCall2(self._builder, fn_t, fn, args, n, call_name)

    def _bit_builtin_width(self, callee_name: str) -> int:
        if callee_name.endswith("ll") or callee_name.endswith("64"):
            return 64
        if callee_name.endswith("l"):
            return 64
        if callee_name.endswith("16"):
            return 16
        return 32

    def _integer_bit_builtin(self, callee_name: str, expr: CallExpr) -> int | None:
        supported = {
            "__builtin_bswap16",
            "__builtin_bswap32",
            "__builtin_bswap64",
            "__builtin_clz",
            "__builtin_clzl",
            "__builtin_clzll",
            "__builtin_ctz",
            "__builtin_ctzl",
            "__builtin_ctzll",
            "__builtin_ffs",
            "__builtin_ffsl",
            "__builtin_ffsll",
            "__builtin_popcount",
            "__builtin_popcountl",
            "__builtin_popcountll",
        }
        if callee_name not in supported:
            return None
        c = llvm()
        width = self._bit_builtin_width(callee_name)
        arg_t = self._int_type_for_width(width)
        arg = self._cast_int_to_width(self._emit_expr(expr.args[0]), width, signed=False)

        if "bswap" in callee_name:
            value = self._intrinsic_call(f"llvm.bswap.i{width}", arg_t, [arg], [arg_t])
            return self._coerce_builtin_result(value, expr)

        if "popcount" in callee_name:
            value = self._intrinsic_call(f"llvm.ctpop.i{width}", arg_t, [arg], [arg_t])
            return self._coerce_builtin_result(value, expr)

        if "clz" in callee_name or "ctz" in callee_name:
            intrinsic = "ctlz" if "clz" in callee_name else "cttz"
            flag = c.ConstInt(c.Int1Type(), 1, False)
            value = self._intrinsic_call(
                f"llvm.{intrinsic}.i{width}",
                arg_t,
                [arg, flag],
                [arg_t, c.Int1Type()],
            )
            return self._coerce_builtin_result(value, expr)

        if "ffs" in callee_name:
            is_zero = c.BuildICmp(
                self._builder,
                32,
                arg,
                c.ConstInt(arg_t, 0, False),
                b"builtin.ffs.zero",
            )
            flag = c.ConstInt(c.Int1Type(), 0, False)
            ctz = self._intrinsic_call(
                f"llvm.cttz.i{width}",
                arg_t,
                [arg, flag],
                [arg_t, c.Int1Type()],
            )
            one_based = c.BuildAdd(
                self._builder,
                ctz,
                c.ConstInt(arg_t, 1, False),
                b"builtin.ffs.index",
            )
            value = c.BuildSelect(
                self._builder,
                is_zero,
                c.ConstInt(arg_t, 0, False),
                one_based,
                b"builtin.ffs",
            )
            return self._coerce_builtin_result(value, expr)

        return None  # pragma: no cover - supported names are exhausted above.

    def _float_intrinsic_type(self, value: int, expr: CallExpr) -> int:
        c = llvm()
        value_t = c.TypeOf(value)
        if self._is_float_kind(c.GetTypeKind(value_t)):
            return value_t
        result_t = self._result_type_ref(expr)
        if self._is_float_kind(c.GetTypeKind(result_t)):
            return result_t
        return c.DoubleType()

    def _floating_builtin(self, callee_name: str, expr: CallExpr) -> int | None:
        c = llvm()
        if callee_name in {
            "__builtin_inf",
            "__builtin_inff",
            "__builtin_infl",
            "__builtin_huge_val",
            "__builtin_huge_valf",
            "__builtin_huge_vall",
        }:
            result_t = self._result_type_ref(expr)
            return c.ConstReal(result_t, float("inf"))
        if callee_name in {"__builtin_nan", "__builtin_nanf", "__builtin_nanl"}:
            result_t = self._result_type_ref(expr)
            return c.ConstReal(result_t, float("nan"))
        if callee_name in {"__builtin_isinf", "__builtin_isnan", "__builtin_isfinite"}:
            value = self._emit_expr(expr.args[0])
            value_t = self._float_intrinsic_type(value, expr)
            if c.TypeOf(value) != value_t:
                value = self._build_cast(value, value_t)
            if callee_name == "__builtin_isnan":
                pred = c.BuildFCmp(self._builder, 8, value, value, b"builtin.isnan")
            else:
                abs_value = self._intrinsic_call(
                    "llvm.fabs.f32"
                    if c.GetTypeKind(value_t) == LLVMTypeKind.FLOAT
                    else "llvm.fabs.f64",
                    value_t,
                    [value],
                    [value_t],
                )
                inf = c.ConstReal(value_t, float("inf"))
                predicate = 1 if callee_name == "__builtin_isinf" else 6
                pred = c.BuildFCmp(self._builder, predicate, abs_value, inf, b"builtin.fpclass")
            result = c.BuildZExt(self._builder, pred, c.Int32Type(), b"builtin.fpclass.ext")
            return self._coerce_builtin_result(result, expr)
        if callee_name in {
            "__builtin_fabs",
            "__builtin_fabsf",
            "__builtin_fabsl",
            "__builtin_copysign",
            "__builtin_copysignf",
            "__builtin_copysignl",
        }:
            first = self._emit_expr(expr.args[0])
            intrinsic_t = self._float_intrinsic_type(first, expr)
            if c.TypeOf(first) != intrinsic_t:
                first = self._build_cast(first, intrinsic_t)
            values = [first]
            param_types = [intrinsic_t]
            intrinsic = "fabs"
            if "copysign" in callee_name:
                second = self._emit_expr(expr.args[1])
                if c.TypeOf(second) != intrinsic_t:
                    second = self._build_cast(second, intrinsic_t)
                values.append(second)
                param_types.append(intrinsic_t)
                intrinsic = "copysign"
            suffix = "f32" if c.GetTypeKind(intrinsic_t) == LLVMTypeKind.FLOAT else "f64"
            value = self._intrinsic_call(
                f"llvm.{intrinsic}.{suffix}",
                intrinsic_t,
                values,
                param_types,
            )
            return self._coerce_builtin_result(value, expr)
        return None

    def _gcc_builtin_call(self, callee_name: str, expr: CallExpr) -> int | None:
        c = llvm()
        if callee_name == "__builtin_assume_aligned":
            return self._coerce_builtin_result(self._emit_expr(expr.args[0]), expr)
        if callee_name in {"__builtin_alloca", "__builtin_alloca_with_align"}:
            count = self._cast_int_to_width(self._emit_expr(expr.args[0]), 64, signed=False)
            alloca = c.BuildArrayAlloca(self._builder, c.Int8Type(), count, b"builtin.alloca")
            return self._coerce_builtin_result(alloca, expr)
        if callee_name == "__builtin_flt_rounds":
            result_t = self._result_type_ref(expr)
            return c.ConstInt(result_t, 1, False)
        if callee_name in {"__builtin_frame_address", "__builtin_return_address"}:
            arg = self._cast_int_to_width(self._emit_expr(expr.args[0]), 32, signed=False)
            intrinsic = (
                "llvm.frameaddress.p0"
                if callee_name == "__builtin_frame_address"
                else "llvm.returnaddress"
            )
            value = self._intrinsic_call(
                intrinsic,
                c.PointerType(c.Int8Type(), 0),
                [arg],
                [c.Int32Type()],
            )
            return self._coerce_builtin_result(value, expr)

        integer_result = self._integer_bit_builtin(callee_name, expr)
        if integer_result is not None:
            return integer_result
        return self._floating_builtin(callee_name, expr)

    # ── call ─────────────────────────────────────────────────

    def _call(self, expr: CallExpr) -> int:
        c = llvm()
        if isinstance(expr.callee, Identifier):
            callee_name = expr.callee.name
            assert isinstance(callee_name, str)

            if callee_name == "__builtin_unreachable":
                return c.GetUndef(c.VoidType())
            if callee_name == "__builtin_expect":
                return self._emit_expr(expr.args[0])
            if callee_name == "__builtin_constant_p":
                return c.ConstInt(c.Int32Type(), 0, False)
            if callee_name in ("__builtin_bzero", "__builtin_memset"):
                # Lower to direct LLVM memset call.
                args = expr.args
                if callee_name == "__builtin_memset":
                    dst = self._emit_expr(args[0])
                    val = self._emit_expr(args[1])
                    val = self._build_cast(val, c.Int8Type(), self._type_map.get(args[1]))
                    ln = self._emit_expr(args[2])
                else:
                    dst = self._emit_expr(args[0])
                    val = c.ConstInt(c.Int8Type(), 0, False)
                    ln = self._emit_expr(args[1])
                return c.BuildMemSet(self._builder, dst, val, ln, False)
            if callee_name == "__builtin___memcpy_chk":
                args = expr.args
                return self._build_memcpy_call(args[0], args[1], args[2])
            if callee_name in {
                "__builtin_va_start",
                "__builtin_va_end",
                "__builtin_va_copy",
            }:
                return self._va_intrinsic_call(callee_name, tuple(expr.args))
            builtin_result = self._gcc_builtin_call(callee_name, expr)
            if builtin_result is not None:
                return builtin_result
            atomic_result = self._atomic_builtin_call(callee_name, tuple(expr.args))
            if atomic_result is not None:
                return atomic_result

            callee_type = self._type_map.get(expr.callee)
            if (
                callee_type is not None
                and not self._is_function_designator_type(callee_type)
                and callee_type.callable_signature() is not None
            ):
                return self._indirect_call(expr, callee_type)
            if callee_type is None:
                symbol_type = self._lookup_symbol_type(callee_name)
                if symbol_type is not None and symbol_type.callable_signature() is not None:
                    return self._indirect_call(expr, symbol_type)

            vals, types, arg_c_types = self._build_call_args(expr)
            return_type = self._type_map.get(expr) or INT
            fn = c.GetNamedFunction(self._mod, callee_name.encode())
            fn_t = self._func_types.get(callee_name)
            if fn is None or fn_t is None:
                callee_type = self._type_map.get(expr.callee)
                callable_signature = (
                    None if callee_type is None else callee_type.callable_signature()
                )
                is_variadic = False
                if callable_signature is None:
                    param_types = types
                    c_param_types: list[Type] = []
                    if self._large_record_is_indirect(return_type):
                        param_types = [c.PointerType(c.Int8Type(), 0)] + param_types
                        ret_lt = c.VoidType()
                    else:
                        ret_lt = self._small_record_return_llvm_type(
                            return_type
                        ) or self._type_to_llvm(return_type)
                    fn_t = c.FunctionType(
                        ret_lt,
                        None if not param_types else ptr_array(param_types),
                        len(param_types),
                        False,
                    )
                else:
                    _return_type, params = callable_signature
                    parameter_types: tuple[Type, ...] | None = params[0]
                    is_variadic = params[1]
                    c_param_types = []
                    for pt in parameter_types or ():
                        if pt.name != "void" or pt.declarator_ops:
                            c_param_types.append(pt)
                    fn_t = self._abi_function_type(return_type, c_param_types, is_variadic)
                fn = c.AddFunction(self._mod, callee_name.encode(), fn_t)
                if self._large_record_is_indirect(return_type):
                    self._mark_sret_function(fn, return_type)
                self._func_types[callee_name] = fn_t
                self._func_param_types[callee_name] = c_param_types
            vals = self._coerce_call_args(vals, callee_name, arg_c_types)
            sret_result = 0
            if self._large_record_is_indirect(return_type):
                sret_result = self._sret_result(return_type)
                vals = [sret_result] + vals
            args_arr = None if len(vals) == 0 else ptr_array(vals)
            # Void-returning calls must not be named in LLVM IR.
            ret_kind = c.GetTypeKind(c.GetReturnType(fn_t))
            call_name = b"" if ret_kind == LLVMTypeKind.VOID else b"call"
            if len(vals) == 0:
                result = c.BuildCall2(self._builder, fn_t, fn, None, 0, call_name)
            else:
                result = c.BuildCall2(self._builder, fn_t, fn, args_arr, len(vals), call_name)
            if sret_result:
                self._mark_sret_call(result, return_type)
                return c.BuildLoad2(
                    self._builder,
                    self._type_to_llvm(return_type),
                    sret_result,
                    b"call.result.value",
                )
            if self._small_record_return_llvm_type(return_type):
                return self._record_from_abi(result, return_type)
            # Void calls: return dummy value to avoid downstream void errors.
            if ret_kind == LLVMTypeKind.VOID:
                return c.ConstInt(c.Int32Type(), 0, False)
            return result

        return self._indirect_call(expr)

    def _indirect_call(self, expr: CallExpr, callee_type: Type | None = None) -> int:
        c = llvm()
        # Indirect call through function pointer.
        if callee_type is None:
            callee_type = self._type_map.require(expr.callee)
        elif self._type_map.get(expr.callee) is None:
            self._type_map.set(expr.callee, callee_type)
        callee_ptr = self._emit_expr(expr.callee)
        callable_signature = callee_type.callable_signature()
        if callable_signature is None:
            raise llvm_backend_error(self._result.filename, "Indirect call target is not callable")
        return_type, params = callable_signature
        parameter_types: tuple[Type, ...] | None = params[0]
        is_var = params[1]
        c_param_types: list[Type] = []
        for pt in parameter_types or ():
            if pt.name != "void" or pt.declarator_ops:
                c_param_types.append(pt)
        param_types = [self._abi_param_llvm_type(type_) for type_ in c_param_types]
        n = len(param_types)
        fn_t = self._abi_function_type(return_type, c_param_types, is_var)
        ret_lt = c.GetReturnType(fn_t)

        vals, _types, arg_c_types = self._build_call_args(expr)
        # Coerce using extracted param types.
        for i, v in enumerate(vals):
            if i < n:
                c_param_type = c_param_types[i]
                if self._large_record_is_indirect(c_param_type):
                    vals[i] = self._copy_indirect_record_arg(v, c_param_type)
                    continue
                if self._small_record_param_llvm_type(c_param_type):
                    vals[i] = self._coerce_small_record_arg(v, c_param_type)
                    continue
                param_lt = param_types[i]
                vt = c.TypeOf(v)
                pk = c.GetTypeKind(param_lt)
                vk = c.GetTypeKind(vt)
                if pk == LLVMTypeKind.INTEGER and vk == LLVMTypeKind.INTEGER:
                    vals[i] = self._cast_integer_value(
                        v,
                        param_lt,
                        arg_c_types[i],
                        b"arg.ext",
                    )
                elif self._is_float_kind(pk) and self._is_float_kind(vk) and param_lt != vt:
                    vals[i] = c.BuildFPCast(self._builder, v, param_lt, b"arg.cast")
        sret_result = 0
        if self._large_record_is_indirect(return_type):
            sret_result = self._sret_result(return_type)
            vals = [sret_result] + vals
        args_arr = None if len(vals) == 0 else ptr_array(vals)
        ret_kind = c.GetTypeKind(ret_lt)
        call_name = b"" if ret_kind == LLVMTypeKind.VOID else b"call"
        if len(vals) == 0:
            result = c.BuildCall2(self._builder, fn_t, callee_ptr, None, 0, call_name)
        else:
            result = c.BuildCall2(self._builder, fn_t, callee_ptr, args_arr, len(vals), call_name)
        if sret_result:
            self._mark_sret_call(result, return_type)
            return c.BuildLoad2(
                self._builder,
                self._type_to_llvm(return_type),
                sret_result,
                b"call.result.value",
            )
        if self._small_record_return_llvm_type(return_type):
            return self._record_from_abi(result, return_type)
        if ret_kind == LLVMTypeKind.VOID:
            return c.ConstInt(c.Int32Type(), 0, False)
        return result

    def _lookup_symbol_type(self, name: str) -> Type | None:
        if self._func_sym is not None:
            symbol = self._func_sym.locals.get(name)
            if isinstance(symbol, VarSymbol):
                return symbol.type_
        if self._sema.file_scope is not None:
            symbol = self._sema.file_scope.lookup(name)
            if isinstance(symbol, VarSymbol):
                return symbol.type_
        return None

    # ── cast ─────────────────────────────────────────────────

    def _cast(self, expr: CastExpr) -> int:
        c = llvm()
        op = self._emit_expr(expr.expr)
        if not op:
            raise llvm_backend_error(self._result.filename, "Cast operand emitted null")
        result_type = self._type_map.require(expr)
        lt = self._type_to_llvm(result_type)
        from_t = c.TypeOf(op)

        if from_t == lt:
            return op

        from_kind = c.GetTypeKind(from_t)
        to_kind = c.GetTypeKind(lt)

        # Cast from void (e.g., (int)void_call()): return undef/null.
        if from_kind == LLVMTypeKind.VOID:
            if to_kind == LLVMTypeKind.POINTER:
                return c.ConstNull(lt)
            return c.GetUndef(lt)

        if result_type.name == "__builtin_va_list":
            return c.BuildBitCast(self._builder, op, lt, b"cast")

        # Cast to void: discard the value (no-op).
        if to_kind == LLVMTypeKind.VOID:
            return op

        # Array decay: cast to pointer.
        if from_kind == LLVMTypeKind.ARRAY and to_kind == LLVMTypeKind.POINTER:
            return self._build_cast(op, lt)

        # Pointer → Integer
        if from_kind == LLVMTypeKind.POINTER and to_kind != LLVMTypeKind.POINTER:
            return c.BuildPtrToInt(self._builder, op, lt, b"cast")
        # Integer → Pointer
        if from_kind != LLVMTypeKind.POINTER and to_kind == LLVMTypeKind.POINTER:
            return c.BuildIntToPtr(self._builder, op, lt, b"cast")
        # Float ↔ non-float: use bitcast
        from_is_float = self._is_float_kind(from_kind)
        to_is_float = self._is_float_kind(to_kind)

        if from_is_float and not to_is_float:
            return c.BuildFPToSI(self._builder, op, lt, b"cast")
        if not from_is_float and to_is_float:
            return c.BuildSIToFP(self._builder, op, lt, b"cast")
        if from_is_float and to_is_float:
            return c.BuildFPCast(self._builder, op, lt, b"cast")

        if from_kind == LLVMTypeKind.INTEGER and to_kind == LLVMTypeKind.INTEGER:
            operand_type = self._type_map.get(expr.expr)
            return self._cast_integer_value(op, lt, operand_type, b"cast")
        return c.BuildSExt(self._builder, op, lt, b"cast")

    def _va_arg(self, expr: BuiltinVaArgExpr) -> int:
        c = llvm()
        ap = self._lvalue_addr(expr.ap)
        if ap is None:
            ap = self._emit_expr(expr.ap)
        result_type = self._resolve_type(expr.type_spec)
        lt = self._type_to_llvm(result_type)
        return c.BuildVAArg(self._builder, ap, lt, b"vaarg")

    def _va_intrinsic_call(self, callee_name: str, args: tuple[Expr, ...]) -> int:
        c = llvm()
        ptr_t = c.PointerType(c.Int8Type(), 0)
        if callee_name == "__builtin_va_copy":
            intrinsic_name = "llvm.va_copy.p0"
            dst = self._lvalue_addr(args[0])
            src = self._lvalue_addr(args[1])
            if dst is None:
                dst = self._emit_expr(args[0])
            if src is None:
                src = self._emit_expr(args[1])
            values = [dst, src]
            param_types = [ptr_t, ptr_t]
        else:
            intrinsic_name = (
                "llvm.va_start.p0" if callee_name == "__builtin_va_start" else "llvm.va_end.p0"
            )
            ap = self._lvalue_addr(args[0])
            if ap is None:
                ap = self._emit_expr(args[0])
            values = [ap]
            param_types = [ptr_t]
        n = len(values)
        params = ptr_array(param_types)
        vals = ptr_array(values)
        fn_t = c.FunctionType(c.VoidType(), params, n, False)
        fn = c.GetNamedFunction(self._mod, intrinsic_name.encode())
        if not fn:
            fn = c.AddFunction(self._mod, intrinsic_name.encode(), fn_t)
        c.BuildCall2(self._builder, fn_t, fn, vals, n, b"")
        return c.ConstInt(c.Int32Type(), 0, False)

    # ── subscript / member ───────────────────────────────────

    def _subscript(self, expr: SubscriptExpr) -> int:
        c = llvm()
        ptr = self._subscript_ptr(expr)
        elem_t = self._type_map.require(expr)
        lt = self._type_to_llvm(elem_t)
        return c.BuildLoad2(self._builder, lt, ptr, b"sub.load")

    def _subscript_ptr(self, expr: SubscriptExpr) -> int:
        c = llvm()
        idx = self._emit_expr(expr.index)
        idx = self._gep_index_value(idx, self._type_map.get(expr.index), b"sub.idx")
        base_t = self._type_map.require(expr.base)
        if base_t.is_array():
            base = self._array_base_pointer(expr.base)
            base_lt = self._type_to_llvm(base_t)
            zero = c.ConstInt(c.Int64Type(), 0, False)
            indices = ptr_array([zero, idx])
            return c.BuildGEP2(self._builder, base_lt, base, indices, 2, b"sub.ptr")

        base = self._emit_expr(expr.base)
        indices = ptr_array([idx])
        elem_t = self._type_map.require(expr)
        lt = self._type_to_llvm(elem_t)
        return c.BuildGEP2(self._builder, lt, base, indices, 1, b"sub.ptr")

    def _array_base_pointer(self, expr: Expr) -> int:
        c = llvm()
        if isinstance(expr, Identifier):
            name = expr.name
            assert isinstance(name, str)
            local = self._lookup_local(name)
            if local is not None:
                return local
            gv = c.GetNamedGlobal(self._mod, name.encode())
            if not gv:
                val_type = self._type_map.require(expr)
                gv = self._global_var_ref(name, val_type)
            return gv

        base = self._emit_expr(expr)
        base_kind = c.GetTypeKind(c.TypeOf(base))
        if base_kind == LLVMTypeKind.ARRAY:
            tmp = self._build_entry_alloca(c.TypeOf(base), "sub.tmp", 0)
            c.BuildStore(self._builder, base, tmp)
            return tmp
        return base

    def _member(self, expr: MemberExpr) -> int:
        lvalue = self._member_lvalue(expr)
        return lvalue.address if lvalue.type_.is_array() else self._load_lvalue(lvalue)

    def _member_ptr(self, expr: MemberExpr) -> int:
        return self._member_lvalue(expr).address

    def _member_lvalue(self, expr: MemberExpr) -> _LValue:
        c = llvm()
        base_t = self._type_map.require(expr.base)

        if expr.through_pointer:
            base = self._emit_expr(expr.base)
            pointee = base_t.pointee()
            if pointee is None:
                if not base_t.declarator_ops and base_t.name.startswith(("struct ", "union ")):
                    struct_t = base_t
                    struct_ptr = self._lvalue_addr(expr.base)
                    if struct_ptr is None:
                        lt = self._type_to_llvm(struct_t)
                        tmp = self._build_entry_alloca(lt, "mem.tmp", 0)
                        c.BuildStore(self._builder, base, tmp)
                        struct_ptr = tmp
                else:
                    raise llvm_backend_error(
                        self._result.filename, "Cannot deref non-ptr in member"
                    )
            else:
                struct_t = pointee
                struct_ptr = base
        else:
            struct_t = base_t
            struct_ptr = self._lvalue_addr(expr.base)
            if struct_ptr is None:
                struct_value = self._emit_expr(expr.base)
                lt = self._type_to_llvm(struct_t)
                tmp = self._build_entry_alloca(lt, "mem.tmp", 0)
                c.BuildStore(self._builder, struct_value, tmp)
                struct_ptr = tmp

        record_name = struct_t.name
        path = self._member_path(record_name, expr.member)
        if path is None:
            raise llvm_backend_error(
                self._result.filename,
                f"Record '{record_name}' has no member '{expr.member}'",
            )
        ptr = struct_ptr
        member_layout: RecordMemberLayout | None = None
        for step_record, field_idx, _member in path:
            member_layout = self._sema.record_layouts[step_record].members[field_idx]
            if member_layout.offset:
                index = c.ConstInt(c.Int64Type(), member_layout.offset, False)
                ptr = c.BuildGEP2(
                    self._builder,
                    c.Int8Type(),
                    ptr,
                    ptr_array([index]),
                    1,
                    b"mem.ptr",
                )
        assert member_layout is not None
        member = path[-1][2]
        return _LValue(
            ptr,
            member.type_,
            member_layout.bit_offset,
            member_layout.bit_width,
            member_layout.storage_size,
        )

    def _lvalue(self, expr: Expr) -> _LValue:
        c = llvm()
        type_ = self._type_map.require(expr)
        if isinstance(expr, Identifier):
            name = expr.name
            assert isinstance(name, str)
            address = self._lookup_local(name)
            if address is None:
                address = c.GetNamedGlobal(self._mod, name.encode())
            if not address:
                address = self._global_var_ref(name, type_)
            return _LValue(address, type_)
        if isinstance(expr, UnaryExpr) and expr.op == "*":
            return _LValue(self._emit_expr(expr.operand), type_)
        if isinstance(expr, SubscriptExpr):
            return _LValue(self._subscript_ptr(expr), type_)
        if isinstance(expr, MemberExpr):
            return self._member_lvalue(expr)
        if isinstance(expr, CompoundLiteralExpr):
            return _LValue(self._compound_literal_addr(expr), type_)
        raise llvm_backend_error(
            self._result.filename,
            f"Unsupported assign target: {type(expr).__name__}",
        )

    def _load_lvalue(self, lvalue: _LValue) -> int:
        c = llvm()
        target_type = self._type_to_llvm(lvalue.type_)
        if lvalue.bit_width is None:
            return c.BuildLoad2(self._builder, target_type, lvalue.address, b"load")
        assert lvalue.bit_offset is not None and lvalue.storage_size is not None
        storage_bits = lvalue.storage_size * 8
        storage_type = c.IntType(storage_bits)
        value = c.BuildLoad2(self._builder, storage_type, lvalue.address, b"bit.load")
        c.SetAlignment(value, 1)
        if lvalue.bit_offset:
            value = c.BuildLShr(
                self._builder,
                value,
                c.ConstInt(storage_type, lvalue.bit_offset, False),
                b"bit.shift",
            )
        if is_signed_integer_type(lvalue.type_):
            shift = storage_bits - lvalue.bit_width
            if shift:
                shift_value = c.ConstInt(storage_type, shift, False)
                value = c.BuildAShr(
                    self._builder,
                    c.BuildShl(self._builder, value, shift_value, b"bit.sign.left"),
                    shift_value,
                    b"bit.sign",
                )
        else:
            value = c.BuildAnd(
                self._builder,
                value,
                c.ConstInt(storage_type, (1 << lvalue.bit_width) - 1, False),
                b"bit.mask",
            )
        return self._cast_integer_value(value, target_type, lvalue.type_, b"bit.value")

    def _store_lvalue(
        self,
        lvalue: _LValue,
        value: int,
        source_type: Type | None = None,
    ) -> int:
        c = llvm()
        target_type = self._type_to_llvm(lvalue.type_)
        if c.TypeOf(value) != target_type:
            value = self._build_cast(value, target_type, source_type)
        if lvalue.bit_width is None:
            c.BuildStore(self._builder, value, lvalue.address)
            return value
        assert lvalue.bit_offset is not None and lvalue.storage_size is not None
        storage_bits = lvalue.storage_size * 8
        storage_type = c.IntType(storage_bits)
        value_bits = c.GetIntTypeWidth(target_type)
        if value_bits > storage_bits:
            value = c.BuildTrunc(self._builder, value, storage_type, b"bit.trunc")
        elif value_bits < storage_bits:
            value = c.BuildZExt(self._builder, value, storage_type, b"bit.extend")
        value_mask = (1 << lvalue.bit_width) - 1
        value = c.BuildAnd(
            self._builder,
            value,
            c.ConstInt(storage_type, value_mask, False),
            b"bit.value.mask",
        )
        shifted_mask = value_mask << lvalue.bit_offset
        if lvalue.bit_offset:
            value = c.BuildShl(
                self._builder,
                value,
                c.ConstInt(storage_type, lvalue.bit_offset, False),
                b"bit.value.shift",
            )
        old = c.BuildLoad2(self._builder, storage_type, lvalue.address, b"bit.old")
        c.SetAlignment(old, 1)
        cleared = c.BuildAnd(
            self._builder,
            old,
            c.ConstInt(
                storage_type,
                ((1 << storage_bits) - 1) ^ shifted_mask,
                False,
            ),
            b"bit.clear",
        )
        store = c.BuildStore(
            self._builder,
            c.BuildOr(self._builder, cleared, value, b"bit.merge"),
            lvalue.address,
        )
        c.SetAlignment(store, 1)
        return self._load_lvalue(lvalue)

    def _lvalue_addr(self, expr: Expr) -> int | None:
        c = llvm()
        if isinstance(expr, Identifier):
            name = expr.name
            assert isinstance(name, str)
            local = self._lookup_local(name)
            if local is not None:
                return local
            gv = c.GetNamedGlobal(self._mod, name.encode())
            if gv:
                return gv
            value_type = self._type_map.get(expr) or self._lookup_symbol_type(name)
            if value_type is not None and not self._is_function_designator_type(value_type):
                return self._global_var_ref(name, value_type)
        if isinstance(expr, MemberExpr):
            return self._member_lvalue(expr).address
        if isinstance(expr, SubscriptExpr):
            return self._subscript_ptr(expr)
        if isinstance(expr, CompoundLiteralExpr):
            return self._compound_literal_addr(expr)
        if isinstance(expr, UnaryExpr) and expr.op == "*":
            return self._emit_expr(expr.operand)
        return None

    def _build_cast(self, val: int, to_type: int, from_c_type: Type | None = None) -> int:
        c = llvm()
        from_type = c.TypeOf(val)
        fk = c.GetTypeKind(from_type)
        tk = c.GetTypeKind(to_type)
        if from_type == to_type:
            return val
        if tk == LLVMTypeKind.INTEGER and c.GetIntTypeWidth(to_type) == 1:
            return self._to_bool(val)
        if fk == tk and fk != LLVMTypeKind.INTEGER:
            if self._is_float_kind(fk) and self._is_float_kind(tk):
                return c.BuildFPCast(  # pragma: no cover - float types are uniqued by kind.
                    self._builder, val, to_type, b"cast"
                )
            return val  # Same non-integer kind: no cast needed
        if fk == LLVMTypeKind.ARRAY:
            # Array decay: returns pointer to first element.
            # For value-type arrays (loaded from memory/alloca), we need
            # to store to an alloca and GEP.  Zero-length arrays get a
            # null pointer (they have no valid storage).
            elem_count = c.GetArrayLength(from_type)
            if elem_count == 0:
                return c.ConstNull(to_type)
            tmp = self._build_entry_alloca(from_type, "cast.tmp", 0)
            c.BuildStore(self._builder, val, tmp)
            zero = c.ConstInt(c.Int32Type(), 0, False)
            idx = ptr_array([zero, zero])
            return c.BuildGEP2(self._builder, from_type, tmp, idx, 2, b"cast.gep")
        if fk == LLVMTypeKind.POINTER and tk == LLVMTypeKind.INTEGER:
            return c.BuildPtrToInt(self._builder, val, to_type, b"cast")
        if fk == LLVMTypeKind.INTEGER and tk == LLVMTypeKind.POINTER:
            return c.BuildIntToPtr(self._builder, val, to_type, b"cast")
        if self._is_float_kind(fk) and not self._is_float_kind(tk):
            return c.BuildFPToSI(self._builder, val, to_type, b"cast")
        if not self._is_float_kind(fk) and self._is_float_kind(tk):
            return c.BuildSIToFP(self._builder, val, to_type, b"cast")
        if self._is_float_kind(fk) and self._is_float_kind(tk):
            return c.BuildFPCast(self._builder, val, to_type, b"cast")
        if fk == LLVMTypeKind.INTEGER and tk == LLVMTypeKind.INTEGER:
            return self._cast_integer_value(val, to_type, from_c_type, b"cast")
        return c.BuildBitCast(self._builder, val, to_type, b"cast")

    # ── ternary ──────────────────────────────────────────────

    def _ternary(self, expr: ConditionalExpr) -> int:
        c = llvm()
        fn = self._func
        cond = self._to_bool(self._emit_expr(expr.condition))
        result_type = self._type_map.require(expr)
        phi_type = self._type_to_llvm(result_type)
        phi_is_void = c.GetTypeKind(phi_type) == LLVMTypeKind.VOID

        then_bb = c.AppendBasicBlock(fn, b"tern.then")
        else_bb = c.AppendBasicBlock(fn, b"tern.else")
        merge_bb = c.AppendBasicBlock(fn, b"tern.end")

        c.BuildCondBr(self._builder, cond, then_bb, else_bb)

        c.PositionBuilderAtEnd(self._builder, then_bb)
        then_val = self._emit_expr(expr.then_expr)
        if not phi_is_void and c.TypeOf(then_val) != phi_type:
            then_val = self._build_cast(then_val, phi_type)
        then_incoming_bb = c.GetInsertBlock(self._builder)
        if self._bb_needs_term(then_incoming_bb):
            c.BuildBr(self._builder, merge_bb)

        c.PositionBuilderAtEnd(self._builder, else_bb)
        else_val = self._emit_expr(expr.else_expr)
        if not phi_is_void and c.TypeOf(else_val) != phi_type:
            else_val = self._build_cast(else_val, phi_type)
        else_incoming_bb = c.GetInsertBlock(self._builder)
        if self._bb_needs_term(else_incoming_bb):
            c.BuildBr(self._builder, merge_bb)

        c.PositionBuilderAtEnd(self._builder, merge_bb)
        if phi_is_void:
            # Void-typed ternary (e.g., assert-like macros): no phi needed.
            return c.GetUndef(c.Int32Type())
        phi = c.BuildPhi(self._builder, phi_type, b"tern")
        vals = ptr_array([then_val, else_val])
        bbs = ptr_array([then_incoming_bb, else_incoming_bb])
        c.AddIncoming(phi, vals, bbs, 2)
        return phi

    # ── statement expr ───────────────────────────────────────

    def _stmt_expr(self, expr: StatementExpr) -> int:
        self._locals.append({})
        c = llvm()
        stmts = expr.body.statements
        if not stmts:
            self._locals.pop()
            return c.ConstInt(c.Int32Type(), 0, False)
        for s in stmts[:-1]:
            self._emit_stmt(s)
        last = stmts[-1]
        if isinstance(last, ExprStmt):
            result = self._emit_expr(last.expr)
        else:
            self._emit_stmt(last)
            result = c.ConstInt(c.Int32Type(), 0, False)
        self._locals.pop()
        return result

    # ── compound literal ─────────────────────────────────────

    def _compound_literal(self, expr: CompoundLiteralExpr) -> int:
        c = llvm()
        result_t = self._type_map.require(expr)
        tmp = self._compound_literal_addr(expr)
        if result_t.is_array():
            return tmp
        lt = self._type_to_llvm(result_t)
        return c.BuildLoad2(self._builder, lt, tmp, b"compound.load")

    def _compound_literal_addr(self, expr: CompoundLiteralExpr) -> int:
        c = llvm()
        result_t = self._type_map.require(expr)
        lt = self._type_to_llvm(result_t)
        tmp = self._build_entry_alloca(
            lt,
            "compound.lit",
            self._type_align(result_t) if self._type_has_nonstandard_record_layout(result_t) else 0,
        )
        if isinstance(expr.initializer, InitList):
            self._emit_init_list_to_addr(tmp, result_t, expr.initializer)
        else:
            val = self._emit_expr(expr.initializer)
            c.BuildStore(self._builder, val, tmp)
        return tmp

    # ── sizeof / alignof ─────────────────────────────────────

    def _size_const(self, expr: SizeofExpr | AlignofExpr) -> int:
        c = llvm()
        # Use the type_spec from the expression (the type being queried),
        # not the result type of the sizeof expression itself.
        if expr.type_spec is not None:
            result_t = self._resolve_type(expr.type_spec)
        else:
            assert expr.expr is not None
            result_t = self._type_map.require(expr.expr)
        value = (
            self._type_align(result_t)
            if isinstance(expr, AlignofExpr)
            else self._type_size(result_t)
        )
        return c.ConstInt(c.Int64Type(), value, False)

    def _offsetof_expr(self, expr: BuiltinOffsetofExpr) -> int:
        c = llvm()
        offset = self._offsetof_value(expr)
        return c.ConstInt(c.Int64Type(), 0 if offset is None else offset, False)

    # ── helpers ──────────────────────────────────────────────

    def _build_memcpy_call(self, dst_arg: Expr, src_arg: Expr, len_arg: Expr) -> int:
        """Lower memcpy-like intrinsic to LLVM memcpy."""
        c = llvm()
        dst = self._emit_expr(dst_arg)
        src = self._emit_expr(src_arg)
        ln = self._emit_expr(len_arg)
        return c.BuildMemCpy(self._builder, dst, 1, src, 1, ln)

    def _to_bool(self, val: int) -> int:
        c = llvm()
        t = c.TypeOf(val)
        k = c.GetTypeKind(t)
        # Array decay: arrays can't be compared directly.
        if k == LLVMTypeKind.ARRAY:
            val = self._build_cast(val, c.PointerType(c.Int8Type(), 0))
            t = c.TypeOf(val)
            k = c.GetTypeKind(t)
        name = b"tobool"
        if k == LLVMTypeKind.POINTER:
            return c.BuildICmp(self._builder, 33, val, c.ConstNull(t), name)
        if self._is_float_kind(k):
            return c.BuildFCmp(self._builder, 6, val, c.ConstReal(t, 0.0), name)
        return c.BuildICmp(self._builder, 33, val, c.ConstInt(t, 0, False), name)

    def _resolve_type(self, ts: TypeSpec) -> Type:
        resolved_ops = self._resolve_declarator_ops(ts.declarator_ops)
        if ts.name == "typeof" and ts.typeof_expr is not None:
            base_type = self._type_map.get(ts.typeof_expr)
            if base_type is None:
                raise llvm_backend_error(self._result.filename, "Unknown typeof expression type")
            for kind, value in resolved_ops:
                if kind == "ptr":
                    base_type = base_type.pointer_to()
                elif kind == "arr":
                    assert isinstance(value, int)
                    base_type = base_type.array_of(value)
                elif kind == "fn":
                    assert isinstance(value, tuple)
                    base_type = base_type.function_of(value[0], is_variadic=value[1])
            return base_type
        if ts.name in {"struct", "union"}:
            name = self._record_name_for_type_spec(ts)
        elif ts.name == "enum":
            name = "int"
        elif ts.name == "bool":
            name = "_Bool"
        elif self._sema.file_scope is not None:
            typedef_type = self._sema.file_scope.lookup_typedef(ts.name)
            if typedef_type is not None:
                qualifiers = _merge_qualifiers(typedef_type.qualifiers, ts.qualifiers)
                return Type(
                    typedef_type.name,
                    declarator_ops=resolved_ops + typedef_type.declarator_ops,
                    qualifiers=qualifiers,
                )
            name = ts.name
        else:
            name = ts.name
        return Type(name, declarator_ops=resolved_ops, qualifiers=ts.qualifiers)

    def _resolve_declarator_ops(self, ops: tuple[DeclaratorOp, ...]) -> tuple[TypeOp, ...]:
        resolved: list[TypeOp] = []
        for kind, value in ops:
            if kind == "ptr":
                resolved.append(("ptr", 0))
                continue
            if kind == "arr":
                if isinstance(value, ArrayDecl):
                    if value.length is None:
                        length = -1
                    elif isinstance(value.length, int):
                        length = value.length
                    else:
                        evaluated = self._eval_int_constant_value(value.length)
                        length = evaluated if evaluated is not None else -1
                else:
                    assert isinstance(value, int)
                    length = value
                resolved.append((kind, length))
                continue
            if kind == "fn":
                assert isinstance(value, tuple) and len(value) == 2
                param_specs, is_variadic = value
                assert param_specs is None or isinstance(param_specs, tuple)
                assert isinstance(is_variadic, bool)
                params: tuple[Type, ...] | None = None
                if param_specs is not None:
                    resolved_params: list[Type] = []
                    for param_spec in param_specs:
                        assert isinstance(param_spec, TypeSpec)
                        resolved_params.append(
                            self._resolve_type(param_spec).decay_parameter_type()
                        )
                    params = tuple(resolved_params)
                function_params: FunctionParams = (params, is_variadic)
                resolved.append((kind, function_params))
                continue
            assert isinstance(value, int)
            resolved.append((kind, value))
        return tuple(resolved)

    def _record_name_for_type_spec(self, ts: TypeSpec) -> str:
        return self._sema.record_type_names[id(ts)]

    def _eval_init(self, init: Expr | InitList, var_type: Type) -> int | None:
        c = llvm()
        lt = self._type_to_llvm(var_type)
        if isinstance(init, InitList):
            if var_type.is_array():
                return self._eval_array_init(init, var_type)
            if self._is_record_type(var_type):
                return self._eval_record_init(init, var_type)
            if len(init.items) == 1 and not init.items[0].designators:
                return self._eval_init(init.items[0].initializer, var_type)
            return None
        if isinstance(init, StringLiteral) and self._is_string_array_initializer(init, var_type):
            return self._string_array_initializer(init, var_type)
        if self._is_record_type(var_type):
            return self._eval_scalar_record_init(init, var_type)
        lt_kind = c.GetTypeKind(lt)
        if isinstance(init, IntLiteral) and lt_kind == LLVMTypeKind.INTEGER:
            return c.ConstInt(lt, self._parse_int_value(init.value), False)
        if isinstance(init, CharLiteral) and lt_kind == LLVMTypeKind.INTEGER:
            return c.ConstInt(lt, char_literal_value(init.value), False)
        if isinstance(init, FloatLiteral) and self._is_float_kind(lt_kind):
            v = init.value
            if v and v[-1] in "fFlL":
                v = v[:-1]
            return c.ConstReal(lt, float.fromhex(v) if v.startswith(("0x", "0X")) else float(v))
        value = self._eval_const_expr(init, var_type)
        if value is None:
            return None
        return self._const_cast(value, lt)

    @staticmethod
    def _is_record_type(type_: Type) -> bool:
        return not type_.declarator_ops and type_.name.startswith(("struct ", "union "))

    @staticmethod
    def _record_member_takes_initializer(member: RecordMemberInfo) -> bool:
        return member.name is not None or (
            member.bit_width is None
            and not member.type_.declarator_ops
            and member.type_.name.startswith(("struct ", "union "))
        )

    def _next_initializable_record_member(
        self,
        members: tuple[RecordMemberInfo, ...],
        start: int,
    ) -> int | None:
        for index in range(start, len(members)):
            if self._record_member_takes_initializer(members[index]):
                return index
        return None

    def _infer_array_init_length(self, init: InitList, array_type: Type | None = None) -> int:
        element_type = array_type.element_type() if array_type is not None else None
        max_index = 0
        next_index = 0
        item_index = 0
        while item_index < len(init.items):
            item = init.items[item_index]
            if item.designators:
                kind, value = item.designators[0]
                if kind == "index" and isinstance(value, Expr):
                    index = self._eval_int_constant_value(value)
                    next_index = 0 if index is None else index + 1
                elif kind == "range" and isinstance(value, DesignatorRange):
                    high = self._eval_int_constant_value(value.high)
                    next_index = 0 if high is None else high + 1
                else:
                    next_index += 1
                item_index += 1
            else:
                consumed = 1
                if element_type is not None and not self._is_single_aggregate_initializer(
                    element_type,
                    item.initializer,
                ):
                    consumed, _ = self._eval_unbraced_aggregate_initializer_items(
                        element_type,
                        init.items,
                        item_index,
                    )
                    if consumed == 0:
                        consumed = 1
                item_index += consumed
                next_index += 1
            max_index = max(max_index, next_index)
        return max_index

    def _flexible_array_member_overrides(
        self,
        record_type: Type,
        init: InitList,
    ) -> dict[int, Type] | None:
        if record_type.declarator_ops or not record_type.name.startswith("struct "):
            return None
        members = self._sema.record_definitions.get(record_type.name)
        if not members:
            return None
        last_index: int = len(members) - 1
        flexible_member = members[last_index]
        flexible_type = flexible_member.type_
        if not flexible_type.is_array():
            return None
        length_value = flexible_type.declarator_ops[0][1]
        if isinstance(length_value, int) and length_value > 0:
            return None
        member_init = self._record_member_initializer(init, record_type.name, last_index)
        if member_init is None:
            return None
        length = self._infer_flexible_array_init_length(member_init, flexible_type)
        if length <= 0:
            return None
        flexible_ops = (("arr", length),) + flexible_type.declarator_ops[1:]
        adjusted = Type(
            flexible_type.name,
            declarator_ops=flexible_ops,
            qualifiers=flexible_type.qualifiers,
        )
        result: dict[int, Type] = {}
        result[last_index] = adjusted
        return result

    def _record_member_initializer(
        self,
        init: InitList,
        record_name: str,
        target_index: int,
    ) -> Expr | InitList | None:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return None
        next_member = 0
        designated_items: list[InitItem] = []
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind != "member" or not isinstance(value, str):
                    continue
                path = self._member_path(record_name, value)
                if path is None or path[0][1] != target_index:
                    continue
                if item.designators[1:]:
                    designated_items.append(InitItem(item.designators[1:], item.initializer))
                    continue
                return item.initializer
            else:
                member_index = self._next_initializable_record_member(members, next_member)
                if member_index is None:
                    continue
                if member_index == target_index:
                    return item.initializer
                next_member = member_index + 1
        if designated_items:
            return InitList(tuple(designated_items))
        return None

    def _infer_flexible_array_init_length(
        self,
        init: Expr | InitList,
        array_type: Type,
    ) -> int:
        if isinstance(init, InitList):
            return self._infer_array_init_length(init, array_type)
        if isinstance(init, StringLiteral):
            inferred = self._string_array_initializer_length(init, array_type)
            if inferred is not None:
                return inferred
        return 1

    def _struct_type_with_member_overrides(
        self,
        record_name: str,
        member_type_overrides: dict[int, Type],
    ) -> int:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return self._type_to_llvm(Type(record_name))
        return self._build_struct_type(record_name, members, member_type_overrides)

    def _eval_array_init(self, init: InitList, array_type: Type) -> int | None:
        c = llvm()
        elem_type = array_type.element_type()
        if elem_type is None:
            return None
        length_value = array_type.declarator_ops[0][1]
        if not isinstance(length_value, int):
            return None
        length = max(length_value, 0)
        elem_lt = self._type_to_llvm(elem_type)
        elems: list[int] = []
        for _ in range(length):
            elems.append(c.ConstNull(elem_lt))
        next_index = 0
        item_index = 0
        while item_index < len(init.items):
            item = init.items[item_index]
            if item.designators:
                kind, value = item.designators[0]
                if kind == "range":
                    if not isinstance(value, DesignatorRange):
                        return None
                    low = self._eval_int_constant_value(value.low)
                    high = self._eval_int_constant_value(value.high)
                    if low is None or high is None:
                        return None
                    for index in range(low, high + 1):
                        if 0 <= index < length:
                            val = self._eval_designated_init(
                                elem_type,
                                item.designators[1:],
                                item.initializer,
                            )
                            if val is None:
                                continue
                            elems[index] = val
                    next_index = high + 1
                    item_index += 1
                    continue
                if kind != "index" or not isinstance(value, Expr):
                    return None
                designated_index = self._eval_int_constant_value(value)
                if designated_index is None:
                    return None
                if 0 <= designated_index < length:
                    val = self._eval_designated_init(
                        elem_type,
                        item.designators[1:],
                        item.initializer,
                    )
                    if val is None:
                        next_index = designated_index + 1
                        item_index += 1
                        continue
                    elems[designated_index] = val
                next_index = designated_index + 1
                item_index += 1
                continue
            if next_index >= length:
                item_index += 1
                continue
            if self._is_single_aggregate_initializer(elem_type, item.initializer):
                val = self._eval_init(item.initializer, elem_type)
                consumed = 1
            else:
                consumed, val = self._eval_unbraced_aggregate_initializer_items(
                    elem_type,
                    init.items,
                    item_index,
                )
                if consumed == 0:
                    val = self._eval_init(item.initializer, elem_type)
                    consumed = 1
            if val is None:
                next_index += 1
                item_index += consumed
                continue
            elems[next_index] = val
            next_index += 1
            item_index += consumed
        return self._const_array(elem_lt, elems)

    def _record_init_member_type(
        self,
        members: tuple[RecordMemberInfo, ...],
        overrides: dict[int, Type],
        index: int,
    ) -> Type:
        override: Type | None = overrides.get(index)
        if override is not None:
            return override
        return members[index].type_

    def _eval_record_init(
        self,
        init: InitList,
        record_type: Type,
        member_type_overrides: dict[int, Type] | None = None,
        record_lt: int | None = None,
    ) -> int | None:
        c = llvm()
        members = self._sema.record_definitions.get(record_type.name)
        if members is None:
            return None
        if not members:
            return c.ConstNull(self._type_to_llvm(record_type))
        overrides = member_type_overrides or {}

        next_member = 0
        union_member: RecordMemberInfo | None = None
        union_value: int | None = None
        initialized_union = False
        is_union = record_type.name.startswith("union ")
        fields: list[int] = []
        if not is_union:
            for i in range(len(members)):
                fields.append(
                    c.ConstNull(
                        self._type_to_llvm(self._record_init_member_type(members, overrides, i))
                    )
                )
        nested_items: dict[int, list[InitItem]] = {}
        nested_order: list[int] = []
        item_index = 0
        while item_index < len(init.items):
            item = init.items[item_index]
            if item.designators:
                kind, value = item.designators[0]
                if kind != "member" or not isinstance(value, str):
                    return None
                path = self._member_path(record_type.name, value)
                if path is None:
                    return None
                remaining_designators = item.designators[1:]
                if remaining_designators or (len(path) > 1 and path[0][2].name is None):
                    path_member_index = path[0][1]
                    if path_member_index not in nested_items:
                        nested_items[path_member_index] = []
                        nested_order.append(path_member_index)
                    nested_designators = (
                        item.designators if path[0][2].name is None else remaining_designators
                    )
                    nested_member_items: list[InitItem] = nested_items[path_member_index]
                    nested_member_items.append(InitItem(nested_designators, item.initializer))
                    nested_items[path_member_index] = nested_member_items
                    if is_union:
                        initialized_union = True
                    else:
                        next_member = path_member_index + 1
                    item_index += 1
                    continue
                if len(path) > 1:  # pragma: no cover - anonymous paths are nested above.
                    val = self._eval_record_path_init(
                        path[1:],
                        item.designators[1:],
                        item.initializer,
                    )
                elif item.designators[
                    1:
                ]:  # pragma: no cover - handled above as remaining_designators.
                    val = self._eval_init(
                        InitList((InitItem(item.designators[1:], item.initializer),)),
                        self._record_init_member_type(members, overrides, path[0][1]),
                    )
                else:
                    val = self._eval_init(
                        item.initializer,
                        self._record_init_member_type(members, overrides, path[0][1]),
                    )
                if val is None:
                    item_index += 1
                    continue
                if is_union:
                    union_member = path[0][2]
                    union_value = val
                    initialized_union = True
                else:
                    fields[path[0][1]] = val
                    next_member = path[0][1] + 1
                item_index += 1
                continue
            if is_union:
                if initialized_union:
                    item_index += 1
                    continue
                member_index = self._next_initializable_record_member(members, 0)
                assert member_index is not None
                initialized_union = True
            else:
                member_index = self._next_initializable_record_member(members, next_member)
                if member_index is None:
                    item_index += 1
                    continue
                next_member = member_index + 1
            current_member_type = self._record_init_member_type(members, overrides, member_index)
            if self._is_single_aggregate_initializer(
                current_member_type,
                item.initializer,
            ):
                val = self._eval_init(item.initializer, current_member_type)
                consumed = 1
            else:
                consumed, val = self._eval_unbraced_aggregate_initializer_items(
                    current_member_type,
                    init.items,
                    item_index,
                )
                if consumed == 0:
                    val = self._eval_init(item.initializer, current_member_type)
                    consumed = 1
            if val is None:
                item_index += consumed
                continue
            if is_union:
                union_member = members[member_index]
                union_value = val
            else:
                fields[member_index] = val
            item_index += consumed
        for member_index in nested_order:
            member = members[member_index]
            val = self._eval_init(
                InitList(tuple(nested_items[member_index])),
                self._record_init_member_type(members, overrides, member_index),
            )
            if val is None:
                continue
            if is_union:
                union_member = member
                union_value = val
            else:
                fields[member_index] = val
        if is_union:
            if union_member is None or union_value is None:
                return c.ConstNull(self._type_to_llvm(record_type))
            return self._const_union(record_type, union_member, union_value)
        return self._const_struct(record_type, fields, record_lt)

    def _eval_unbraced_aggregate_initializer_items(
        self,
        target_type: Type,
        items: tuple[InitItem, ...],
        start: int,
    ) -> tuple[int, int | None]:
        c = llvm()
        if start >= len(items):
            return 0, None
        if target_type.is_array():
            elem_type = target_type.element_type()
            if elem_type is None:  # pragma: no cover - Type.is_array() guarantees an element type.
                return 0, None
            length_value = target_type.declarator_ops[0][1]
            if not isinstance(length_value, int) or length_value < 0:
                return 0, None
            elem_lt = self._type_to_llvm(elem_type)
            elems: list[int] = []
            for _ in range(length_value):
                elems.append(c.ConstNull(elem_lt))
            item_index = start
            for elem_index in range(length_value):
                if item_index >= len(items) or items[item_index].designators:
                    break
                consumed, val = self._eval_unbraced_initializer_item(
                    elem_type,
                    items,
                    item_index,
                )
                if consumed == 0:
                    break
                if val is not None:
                    elems[elem_index] = val
                item_index += consumed
            return item_index - start, self._const_array(elem_lt, elems)
        if not self._is_record_type(target_type):
            return 0, None
        members = self._sema.record_definitions.get(target_type.name)
        if members is None:
            return 0, None
        is_union = target_type.name.startswith("union ")
        item_index = start
        union_member: RecordMemberInfo | None = None
        union_value: int | None = None
        fields: list[int] = []
        if not is_union:
            for member in members:
                fields.append(c.ConstNull(self._type_to_llvm(member.type_)))
        member_start = 0
        while True:
            if item_index >= len(items) or items[item_index].designators:
                break
            member_index = self._next_initializable_record_member(members, member_start)
            if member_index is None:
                break
            member = members[member_index]
            consumed, val = self._eval_unbraced_initializer_item(
                member.type_,
                items,
                item_index,
            )
            if consumed == 0:
                break
            if val is not None:
                if is_union:
                    union_member = member
                    union_value = val
                else:
                    fields[member_index] = val
            item_index += consumed
            if is_union:
                break
            member_start = member_index + 1
        consumed_total = item_index - start
        if is_union:
            if union_member is None or union_value is None:
                return consumed_total, c.ConstNull(self._type_to_llvm(target_type))
            return consumed_total, self._const_union(target_type, union_member, union_value)
        return consumed_total, self._const_struct(target_type, fields)

    def _eval_unbraced_initializer_item(
        self,
        target_type: Type,
        items: tuple[InitItem, ...],
        index: int,
    ) -> tuple[int, int | None]:
        item = items[index]
        if item.designators:
            return 0, None
        if self._is_single_aggregate_initializer(target_type, item.initializer):
            return 1, self._eval_init(item.initializer, target_type)
        return self._eval_unbraced_aggregate_initializer_items(target_type, items, index)

    def _eval_scalar_record_init(self, init: Expr, record_type: Type) -> int | None:
        c = llvm()
        members = self._sema.record_definitions.get(record_type.name)
        if not members:
            return c.ConstNull(self._type_to_llvm(record_type))
        member_index = self._next_initializable_record_member(members, 0)
        assert member_index is not None
        member = members[member_index]
        val = self._eval_init(init, member.type_)
        if val is None:
            return None
        if record_type.name.startswith("union "):
            return self._const_union(record_type, member, val)
        fields: list[int] = []
        for member in members:
            fields.append(c.ConstNull(self._type_to_llvm(member.type_)))
        fields[member_index] = val
        return self._const_struct(record_type, fields)

    def _eval_record_path_init(
        self,
        path: list[tuple[str, int, RecordMemberInfo]],
        designators: tuple[tuple[str, Expr | str | DesignatorRange], ...],
        initializer: Expr | InitList,
    ) -> int | None:
        c = llvm()
        first_path: tuple[str, int, RecordMemberInfo] = path[0]
        record_name: str = first_path[0]
        field_index: int = first_path[1]
        member: RecordMemberInfo = first_path[2]
        record_type = Type(record_name)
        members = self._sema.record_definitions.get(record_name)
        if members is None:
            return None
        fields: list[int] = []
        for item in members:
            fields.append(c.ConstNull(self._type_to_llvm(item.type_)))
        if len(path) > 1:
            val = self._eval_record_path_init(path[1:], designators, initializer)
        elif designators:
            val = self._eval_init(InitList((InitItem(designators, initializer),)), member.type_)
        else:
            val = self._eval_init(initializer, member.type_)
        if val is None:
            return None
        if record_name.startswith("union "):
            return self._const_union(record_type, member, val)
        fields[field_index] = val
        return self._const_struct(record_type, fields)

    def _eval_designated_init(
        self,
        target_type: Type,
        designators: tuple[tuple[str, Expr | str | DesignatorRange], ...],
        initializer: Expr | InitList,
    ) -> int | None:
        if not designators:
            return self._eval_init(initializer, target_type)
        return self._eval_init(InitList((InitItem(designators, initializer),)), target_type)

    def _const_array(self, elem_lt: int, values: list[int]) -> int:
        c = llvm()
        if not values:
            return c.ConstArray(elem_lt, None, 0)
        arr = ptr_array(values)
        return c.ConstArray(elem_lt, arr, len(values))

    def _const_aggregate_element(self, value: int, index: int, fallback_type: int) -> int:
        c = llvm()
        if index < c.GetNumOperands(value):
            return c.GetOperand(value, index)
        aggregate_element = c.GetAggregateElement(value, index)
        if aggregate_element:
            return aggregate_element
        return c.ConstNull(fallback_type)

    def _const_struct(
        self,
        record_type: Type,
        fields: list[int],
        record_lt: int | None = None,
    ) -> int:
        c = llvm()
        lt = record_lt if record_lt is not None else self._type_to_llvm(record_type)
        if not fields:
            return c.ConstNull(lt)
        if lt in self._struct_physical_layouts:
            return self._const_bitfield_struct(record_type, fields, lt)
        layout = self._struct_layouts.get(lt)
        if layout is not None:
            fields = [
                c.ConstNull(field_type) if member_index is None else fields[member_index]
                for field_type, member_index in layout
            ]
        arr = ptr_array(fields)
        return c.ConstNamedStruct(lt, arr, len(fields))

    def _const_bitfield_struct(
        self,
        record_type: Type,
        fields: list[int],
        record_lt: int,
    ) -> int:
        c = llvm()
        layout = self._sema.record_layouts[record_type.name]
        members = self._sema.record_definitions[record_type.name]
        data = bytes(layout.size)
        raw = 0
        for index, (member, member_layout) in enumerate(zip(members, layout.members, strict=True)):
            if member.bit_width is not None:
                if member.bit_width == 0:
                    continue
                value = fields[index]
                if not c.IsAConstantInt(value):
                    continue
                bit = member_layout.offset * 8
                assert member_layout.bit_offset is not None
                bit += member_layout.bit_offset
                mask = (1 << member.bit_width) - 1
                raw |= (c.ConstIntGetZExtValue(value) & mask) << bit
                continue
            member_data = self._const_value_bytes(fields[index], member.type_)
            if member_data is None:
                continue
            start = member_layout.offset
            data = data[:start] + member_data + data[start + len(member_data) :]
        bit_data = raw.to_bytes(layout.size, "little")
        merged = b""
        for index, value in enumerate(bit_data):
            merged += (data[index] | value).to_bytes(1, "little")
        return self._const_struct_from_physical_bytes(merged, record_type.name, record_lt)

    def _const_struct_from_physical_bytes(
        self,
        data: bytes,
        record_name: str,
        record_lt: int,
    ) -> int:
        c = llvm()
        members = self._sema.record_definitions[record_name]
        fields: list[int] = []
        for field_type, offset, size, member_index in self._struct_physical_layouts[record_lt]:
            chunk = data[offset : offset + size]
            if member_index is None:
                fields.append(
                    self._const_array(
                        c.Int8Type(),
                        [c.ConstInt(c.Int8Type(), byte, False) for byte in chunk],
                    )
                )
                continue
            field = self._const_from_bytes(
                chunk,
                members[member_index].type_,
                field_type,
            )
            assert field is not None
            fields.append(field)
        return c.ConstNamedStruct(record_lt, ptr_array(fields), len(fields))

    def _const_union(
        self,
        record_type: Type,
        active_member: RecordMemberInfo,
        value: int,
    ) -> int:
        c = llvm()
        members = self._sema.record_definitions.get(record_type.name)
        if not members:
            return c.ConstNull(self._type_to_llvm(record_type))
        storage_member = self._union_storage_member(members)
        storage_type = self._record_member_llvm_type(storage_member)
        if c.TypeOf(value) == storage_type:
            storage_value = value
        else:
            converted = self._coerce_union_storage_value(
                value,
                active_member,
                storage_member,
                storage_type,
            )
            if converted is None:
                return c.ConstNull(self._type_to_llvm(record_type))
            storage_value = converted
        fields = [storage_value]
        padding = self._union_size(record_type.name) - self._type_size(storage_member.type_)
        if padding > 0:
            fields.append(c.ConstNull(c.ArrayType(c.Int8Type(), padding)))
        return self._const_struct(record_type, fields)

    def _coerce_union_storage_value(
        self,
        value: int,
        active_member: RecordMemberInfo,
        storage_member: RecordMemberInfo,
        storage_type: int,
    ) -> int | None:
        c = llvm()
        value_type = c.TypeOf(value)
        if (
            c.GetTypeKind(value_type) == LLVMTypeKind.POINTER
            and c.GetTypeKind(storage_type) == LLVMTypeKind.POINTER
        ):
            return c.ConstPointerCast(value, storage_type)
        if (
            c.GetTypeKind(value_type) == LLVMTypeKind.INTEGER
            and c.GetTypeKind(storage_type) == LLVMTypeKind.INTEGER
            and c.IsAConstantInt(value)
        ):
            signed = not active_member.type_.name.startswith("unsigned ")
            raw = c.ConstIntGetSExtValue(value) if signed else c.ConstIntGetZExtValue(value)
            return c.ConstInt(storage_type, raw, raw < 0)
        data = self._const_value_bytes(value, active_member.type_)
        if data is None:
            return None
        return self._const_from_bytes(data, storage_member.type_, storage_type)

    def _const_value_bytes(self, value: int, value_type: Type) -> bytes | None:
        c = llvm()
        size = self._type_size(value_type)
        if size == 0:
            return b""
        if c.IsNull(value):
            return bytes(size)
        if value_type.declarator_ops:
            kind, length_value = value_type.declarator_ops[0]
            if kind == "arr":
                if not isinstance(
                    length_value, int
                ):  # pragma: no cover - _type_size rejects it first.
                    return None
                elem_type = value_type.element_type()
                if elem_type is None:  # pragma: no cover - array ops always have elements.
                    return None
                elem_size = self._type_size(elem_type)
                data = b""
                elem_lt = self._type_to_llvm(elem_type)
                for index in range(max(length_value, 0)):
                    elem_value = self._const_aggregate_element(value, index, elem_lt)
                    elem_data = self._const_value_bytes(elem_value, elem_type)
                    if elem_data is None:
                        return None
                    data += elem_data[:elem_size].ljust(elem_size, b"\0")
                return data
            return None
        if value_type.name.startswith("struct "):
            return self._const_struct_bytes(value, value_type.name)
        if value_type.name.startswith("union "):
            return self._const_union_bytes(value, value_type.name)
        if is_integer_type(value_type) and c.IsAConstantInt(value):
            raw: int = c.ConstIntGetZExtValue(value)
            # Native AOT integers are i64.  Avoid shifting by 64 here: LLVM
            # masks that shift count on the host CPU, producing a zero mask
            # instead of Python's arbitrary-precision ``(1 << 64) - 1``.
            mask: int = -1
            if size < 8:
                mask = (1 << (size * 8)) - 1
            masked: int = raw & mask
            return masked.to_bytes(size, "little")
        return None

    def _const_struct_bytes(self, value: int, record_name: str) -> bytes | None:
        members = self._sema.record_definitions.get(record_name)
        if members is None:
            return None
        value_type = llvm().TypeOf(value)
        physical = self._struct_physical_layouts.get(value_type)
        if physical is not None:
            physical_data = bytes(self._record_size(record_name))
            for index, (_field_type, offset, size, member_index) in enumerate(physical):
                field = self._const_aggregate_element(
                    value,
                    index,
                    physical[index][0],
                )
                if member_index is None:
                    field_data = self._const_byte_array_bytes(field, size)
                else:
                    field_data = self._const_value_bytes(field, members[member_index].type_)
                if field_data is None:
                    return None
                physical_data = (
                    physical_data[:offset] + field_data[:size] + physical_data[offset + size :]
                )
            return physical_data
        record_size = self._record_size(record_name)
        data = b""
        offset = 0
        for index, member in enumerate(members):
            member_align = self._record_member_align(record_name, member)
            aligned_offset = self._align_to(offset, member_align)
            if aligned_offset > len(data):
                data += bytes(aligned_offset - len(data))
            offset = aligned_offset
            member_size = self._type_size(member.type_)
            member_value = self._const_aggregate_element(
                value,
                self._llvm_field_index(record_name, index),
                self._record_member_llvm_type(member),
            )
            member_data = self._const_value_bytes(member_value, member.type_)
            if member_data is None:
                return None
            data += member_data[:member_size].ljust(
                member_size,
                b"\0",
            )
            offset += member_size
        if record_size > len(data):
            data += bytes(record_size - len(data))
        return data[:record_size]

    def _const_byte_array_bytes(self, value: int, size: int) -> bytes | None:
        c = llvm()
        if c.IsNull(value):
            return bytes(size)
        result = b""
        for index in range(size):
            element = self._const_aggregate_element(value, index, c.Int8Type())
            if not c.IsAConstantInt(element):
                return None
            result += c.ConstIntGetZExtValue(element).to_bytes(1, "little")
        return result

    def _const_union_bytes(self, value: int, record_name: str) -> bytes | None:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return bytes(self._union_size(record_name))
        storage_member = self._union_storage_member(members)
        storage_size = self._type_size(storage_member.type_)
        storage_value = self._const_aggregate_element(
            value,
            0,
            self._record_member_llvm_type(storage_member),
        )
        storage_data = self._const_value_bytes(storage_value, storage_member.type_)
        if storage_data is None:
            return None
        return storage_data[:storage_size].ljust(self._union_size(record_name), b"\0")

    def _const_from_bytes(
        self,
        data: bytes,
        target_type: Type,
        target_lt: int | None = None,
    ) -> int | None:
        c = llvm()
        size = self._type_size(target_type)
        chunk = data[:size].ljust(size, b"\0")
        if target_type.declarator_ops:
            kind, length_value = target_type.declarator_ops[0]
            if kind == "arr":
                if not isinstance(
                    length_value, int
                ):  # pragma: no cover - _type_size rejects it first.
                    return None
                elem_type = target_type.element_type()
                if elem_type is None:  # pragma: no cover - array ops always have elements.
                    return None
                elem_size = self._type_size(elem_type)
                elem_lt = self._type_to_llvm(elem_type)
                values: list[int] = []
                for index in range(max(length_value, 0)):
                    offset = index * elem_size
                    elem = self._const_from_bytes(
                        chunk[offset : offset + elem_size],
                        elem_type,
                        elem_lt,
                    )
                    if elem is None:
                        return None
                    values.append(elem)
                return self._const_array(elem_lt, values)
            if kind == "ptr":
                has_nonzero = False
                for byte in chunk:
                    if byte:
                        has_nonzero = True
                if has_nonzero:
                    return None
                lt = target_lt if target_lt is not None else self._type_to_llvm(target_type)
                return c.ConstPointerNull(lt)
            return None
        if target_type.name.startswith("struct "):
            return self._const_struct_from_bytes(chunk, target_type.name, target_lt)
        if target_type.name.startswith("union "):
            return self._const_union_from_bytes(chunk, target_type.name, target_lt)
        if is_integer_type(target_type):
            lt = target_lt if target_lt is not None else self._type_to_llvm(target_type)
            raw = 0
            shift = 0
            for byte in chunk:
                raw = raw | (byte << shift)
                shift += 8
            return c.ConstInt(lt, raw, False)
        return None

    def _const_struct_from_bytes(
        self,
        data: bytes,
        record_name: str,
        record_lt: int | None = None,
    ) -> int | None:
        members = self._sema.record_definitions.get(record_name)
        if members is None:
            return None
        lt = record_lt if record_lt is not None else self._type_to_llvm(Type(record_name))
        if lt in self._struct_physical_layouts:
            return self._const_struct_from_physical_bytes(data, record_name, lt)
        offset = 0
        fields: list[int] = []
        for member in members:
            member_align = self._record_member_align(record_name, member)
            offset = self._align_to(offset, member_align)
            member_size = self._type_size(member.type_)
            field = self._const_from_bytes(
                data[offset : offset + member_size],
                member.type_,
                self._record_member_llvm_type(member),
            )
            if field is None:
                return None
            fields.append(field)
            offset += member_size
        return self._const_struct(Type(record_name), fields, record_lt)

    def _const_union_from_bytes(
        self,
        data: bytes,
        record_name: str,
        record_lt: int | None = None,
    ) -> int | None:
        members = self._sema.record_definitions.get(record_name)
        if not members:
            return llvm().ConstNull(
                record_lt if record_lt is not None else self._type_to_llvm(Type(record_name))
            )
        storage_member = self._union_storage_member(members)
        storage_size = self._type_size(storage_member.type_)
        storage = self._const_from_bytes(
            data[:storage_size],
            storage_member.type_,
            self._record_member_llvm_type(storage_member),
        )
        if storage is None:
            return None
        return self._const_union(Type(record_name), storage_member, storage)
        return None

    def _eval_const_expr(self, expr: Expr, target_type: Type | None = None) -> int | None:
        c = llvm()
        target_lt = self._type_to_llvm(target_type) if target_type is not None else None
        target_kind = c.GetTypeKind(target_lt) if target_lt is not None else None
        int_value = self._eval_int_constant_value(expr)
        if target_lt is not None and int_value is not None:
            if target_kind == LLVMTypeKind.INTEGER:
                return c.ConstInt(target_lt, int_value, int_value < 0)
            if target_kind == LLVMTypeKind.POINTER:
                if int_value == 0:
                    return c.ConstPointerNull(target_lt)
                raw = c.ConstInt(c.Int64Type(), int_value, int_value < 0)
                return c.ConstIntToPtr(raw, target_lt)
            if target_kind is not None and self._is_float_kind(target_kind):
                return c.ConstReal(target_lt, float(int_value))
        if target_kind == LLVMTypeKind.POINTER:
            value_type: Type | None = self._type_map.get(expr)
            if value_type is not None:  # noqa: SIM102  # pragma: no branch
                if value_type.is_array():
                    value = self._eval_const_addr(expr)
                    if value is not None:
                        assert target_lt is not None
                        return self._const_cast(value, target_lt)
        if isinstance(expr, CompoundLiteralExpr):
            value = self._const_compound_literal_addr(expr)
            if target_lt is not None:
                return self._const_cast(value, target_lt)
            return value
        if isinstance(expr, StringLiteral):
            return self._const_string_literal_ptr(expr)
        if isinstance(expr, Identifier):
            return self._eval_const_identifier(expr)
        if isinstance(expr, UnaryExpr):
            if expr.op == "&":
                return self._eval_const_addr(expr.operand)
            if expr.op == "-" and isinstance(expr.operand, FloatLiteral):
                if target_lt is None:
                    return None
                text = expr.operand.value.rstrip("fFlL")
                float_value = float.fromhex(text) if text.startswith(("0x", "0X")) else float(text)
                negative_value = 0.0 - float_value
                return c.ConstReal(target_lt, negative_value)
        if isinstance(expr, CastExpr):
            result_type = self._resolve_type(expr.type_spec)
            result_lt = self._type_to_llvm(result_type)
            cast_int = self._eval_int_constant_value(expr)
            if cast_int is not None:
                result_kind = c.GetTypeKind(result_lt)
                if result_kind == LLVMTypeKind.INTEGER:
                    return c.ConstInt(result_lt, cast_int, cast_int < 0)
                if self._is_float_kind(result_kind):
                    return c.ConstReal(result_lt, float(cast_int))
            value = self._eval_const_expr(expr.expr)
            if value is None:
                return None
            return self._const_cast(value, result_lt)
        if isinstance(expr, SizeofExpr):
            return self._size_const(expr)
        if isinstance(expr, AlignofExpr):
            if expr.type_spec is None:
                return None
            return c.ConstInt(
                c.Int64Type(),
                self._type_align(self._resolve_type(expr.type_spec)),
                False,
            )
        if isinstance(expr, BuiltinOffsetofExpr):
            return self._offsetof_expr(expr)
        return None

    def _eval_const_identifier(self, expr: Identifier) -> int | None:
        c = llvm()
        name = expr.name
        local = self._lookup_local(name)
        if local is not None and local in self._static_local_global_values:
            return local
        if self._sema.file_scope is not None:
            symbol = self._sema.file_scope.lookup(name)
            if isinstance(symbol, EnumConstSymbol):
                return c.ConstInt(c.Int32Type(), symbol.value, symbol.value < 0)
        value_type: Type | None = self._type_map.get(expr)
        if value_type is None:
            value_type = self._lookup_symbol_type(name)
        if value_type is None:
            return None
        if self._is_function_designator_type(value_type):
            return self._function_designator(name, value_type)
        if value_type.is_array():
            return self._global_var_ref(name, value_type)
        return None

    def _eval_const_addr(self, expr: Expr) -> int | None:
        c = llvm()
        if isinstance(expr, Identifier):
            name = expr.name
            local = self._lookup_local(name)
            if local is not None and local in self._static_local_global_values:
                return local
            value_type: Type | None = self._type_map.get(expr)
            if value_type is None:
                value_type = self._lookup_symbol_type(name)
            if value_type is not None:
                if self._is_function_designator_type(value_type):
                    return self._function_designator(name, value_type)
                return self._global_var_ref(name, value_type)
            gv = c.GetNamedGlobal(self._mod, name.encode())
            if gv:
                return gv
            fn = c.GetNamedFunction(self._mod, name.encode())
            if fn:
                return fn
            return None
        if isinstance(expr, MemberExpr):
            return self._eval_const_member_ptr(expr)
        if isinstance(expr, SubscriptExpr):
            return self._eval_const_subscript_ptr(expr)
        if isinstance(expr, CompoundLiteralExpr):
            return self._const_compound_literal_addr(expr)
        if isinstance(expr, UnaryExpr) and expr.op == "*":
            return self._eval_const_expr(expr.operand)
        return None

    def _const_compound_literal_addr(self, expr: CompoundLiteralExpr) -> int:
        c = llvm()
        key = id(expr)
        gv = self._compound_literal_globals.get(key)
        if gv is not None:
            return gv
        literal_type = self._type_map.require(expr)
        if literal_type.is_array():
            length_value = literal_type.declarator_ops[0][1]
            if isinstance(length_value, int) and length_value <= 0:
                inferred = (
                    self._infer_array_init_length(expr.initializer, literal_type)
                    if isinstance(expr.initializer, InitList)
                    else 1
                )
                literal_type = Type(
                    literal_type.name,
                    declarator_ops=(("arr", inferred),) + literal_type.declarator_ops[1:],
                    qualifiers=literal_type.qualifiers,
                )
        lt = self._type_to_llvm(literal_type)
        name = f".compound.{len(self._compound_literal_globals)}".encode()
        gv = c.AddGlobal(self._mod, lt, name)
        if self._type_has_nonstandard_record_layout(literal_type):
            c.SetAlignment(gv, self._type_align(literal_type))
        c.SetLinkage(gv, LLVM_INTERNAL_LINKAGE)
        init = self._eval_init(expr.initializer, literal_type)
        c.SetInitializer(gv, init if init is not None else c.ConstNull(lt))
        self._compound_literal_globals[key] = gv
        return gv

    def _eval_const_member_ptr(self, expr: MemberExpr) -> int | None:
        c = llvm()
        base_t = self._type_map.require(expr.base)
        if expr.through_pointer:
            base = self._eval_const_expr(expr.base)
            pointee = base_t.pointee()
            if base is None or pointee is None:
                return None
            struct_t = pointee
            struct_ptr = base
        else:
            struct_t = base_t
            struct_ptr_value = self._eval_const_addr(expr.base)
            if struct_ptr_value is None:
                return None
            struct_ptr = struct_ptr_value
        path = self._member_path(struct_t.name, expr.member)
        if path is None:
            return None
        zero = c.ConstInt(c.Int32Type(), 0, False)
        ptr = struct_ptr
        for step_record, field_idx, _member in path:
            if step_record.startswith("union "):
                continue
            st = self._struct_type(step_record)
            fi = c.ConstInt(
                c.Int32Type(),
                self._llvm_field_index(step_record, field_idx),
                False,
            )
            indices = ptr_array([zero, fi])
            ptr = c.ConstGEP2(st, ptr, indices, 2)
        return ptr

    def _eval_const_subscript_ptr(self, expr: SubscriptExpr) -> int | None:
        c = llvm()
        index = self._eval_int_constant_value(expr.index)
        if index is None:
            return None
        idx = c.ConstInt(c.Int64Type(), index, index < 0)
        base_t = self._type_map.require(expr.base)
        if base_t.is_array():
            base = self._eval_const_addr(expr.base)
            if base is None:
                return None
            zero = c.ConstInt(c.Int64Type(), 0, False)
            indices = ptr_array([zero, idx])
            return c.ConstGEP2(self._type_to_llvm(base_t), base, indices, 2)
        base = self._eval_const_expr(expr.base)
        elem_t = self._type_map.require(expr)
        if base is None:
            return None
        indices = ptr_array([idx])
        return c.ConstGEP2(self._type_to_llvm(elem_t), base, indices, 1)

    def _const_string_literal_ptr(self, expr: StringLiteral) -> int:
        c = llvm()
        if expr.value in self._str_constants:
            return self._str_constants[expr.value]
        data = self._string_literal_bytes(expr)
        lt = c.ArrayType(c.Int8Type(), len(data))
        init = c.ConstString(data, len(data), True)
        gv = c.AddGlobal(self._mod, lt, b".str")
        c.SetInitializer(gv, init)
        c.SetLinkage(gv, LLVM_INTERNAL_LINKAGE)
        self._str_constants[expr.value] = gv
        return gv

    def _const_cast(self, value: int, to_type: int) -> int:
        c = llvm()
        from_type = c.TypeOf(value)
        if from_type == to_type:
            return value
        from_kind = c.GetTypeKind(from_type)
        to_kind = c.GetTypeKind(to_type)
        if to_kind == LLVMTypeKind.VOID:
            return value
        if from_kind == LLVMTypeKind.POINTER and to_kind == LLVMTypeKind.POINTER:
            return c.ConstPointerCast(
                value, to_type
            )  # pragma: no cover - opaque pointers compare equal first.
        if from_kind == LLVMTypeKind.POINTER and to_kind == LLVMTypeKind.INTEGER:
            return c.ConstPtrToInt(value, to_type)
        if from_kind == LLVMTypeKind.INTEGER and to_kind == LLVMTypeKind.POINTER:
            if c.IsAConstantInt(value) and c.ConstIntGetZExtValue(value) == 0:
                return c.ConstPointerNull(to_type)
            return c.ConstIntToPtr(value, to_type)
        if from_kind == LLVMTypeKind.INTEGER and to_kind == LLVMTypeKind.INTEGER:
            if c.IsAConstantInt(value):
                val = c.ConstIntGetSExtValue(value)
                if c.GetIntTypeWidth(to_type) == 1:
                    return c.ConstInt(to_type, 1 if val != 0 else 0, False)
                return c.ConstInt(to_type, val, val < 0)
            return c.ConstTruncOrBitCast(value, to_type)
        return c.ConstBitCast(value, to_type)

    def _eval_int_constant_value(self, expr: Expr) -> int | None:
        if isinstance(expr, ConditionalExpr):
            condition = self._eval_int_constant_value(expr.condition)
            if condition is None:
                return None
            return self._eval_int_constant_value(expr.then_expr if condition else expr.else_expr)
        if isinstance(expr, CommaExpr):
            return self._eval_int_constant_value(expr.right)
        if isinstance(expr, UnaryExpr):
            operand = self._eval_int_constant_value(expr.operand)
            if operand is None:
                return None
            if expr.op == "-":
                return -operand
            if expr.op == "+":
                return operand
            if expr.op == "!":
                return 0 if operand else 1
            if expr.op == "~":
                return ~operand
            return None
        if isinstance(expr, BinaryExpr):
            left = self._eval_int_constant_value(expr.left)
            right = self._eval_int_constant_value(expr.right)
            if left is None or right is None:
                return None
            if expr.op == "+":
                return left + right
            if expr.op == "-":
                return left - right
            if expr.op == "*":
                return left * right
            if expr.op == "/":
                return 0 if right == 0 else left // right
            if expr.op == "%":
                return 0 if right == 0 else left % right
            if expr.op == "<<":
                return left << right
            if expr.op == ">>":
                return left >> right
            if expr.op == "|":
                return left | right
            if expr.op == "&":
                return left & right
            if expr.op == "^":
                return left ^ right
            if expr.op == "&&":
                return 1 if left and right else 0
            if expr.op == "||":
                return 1 if left or right else 0
            if expr.op == "==":
                return 1 if left == right else 0
            if expr.op == "!=":
                return 1 if left != right else 0
            if expr.op == "<":
                return 1 if left < right else 0
            if expr.op == ">":
                return 1 if left > right else 0
            if expr.op == "<=":
                return 1 if left <= right else 0
            if expr.op == ">=":
                return 1 if left >= right else 0
            return None
        if isinstance(expr, CastExpr):
            return self._eval_int_constant_value(expr.expr)
        if isinstance(expr, SizeofExpr):
            result_t = (
                self._resolve_type(expr.type_spec)
                if expr.type_spec is not None
                else self._type_map.get(expr.expr)
                if expr.expr is not None
                else None
            )
            return None if result_t is None else self._type_size(result_t)
        if isinstance(expr, AlignofExpr):
            if expr.type_spec is None:
                return None
            return self._type_align(self._resolve_type(expr.type_spec))
        if isinstance(expr, BuiltinOffsetofExpr):
            return self._offsetof_value(expr)
        try:
            return self._eval_case_val(expr)
        except CodegenError:
            return None

    def _offsetof_value(self, expr: BuiltinOffsetofExpr) -> int | None:
        root_type = self._resolve_type(expr.type_spec)
        return self._offsetof_member_path(root_type, expr.member.split("."))

    def _offsetof_member_path(self, root_type: Type, parts: list[str]) -> int | None:
        if not parts:
            return 0
        if root_type.declarator_ops:
            return None
        if not root_type.name.startswith(("struct ", "union ")):
            return None
        found = self._record_member_offset_and_type(root_type.name, parts[0])
        if found is None:
            return None
        member_offset, member_type = found
        nested_offset = self._offsetof_member_path(member_type, parts[1:])
        if nested_offset is None:
            return None
        return member_offset + nested_offset

    def _record_member_offset_and_type(
        self,
        record_name: str,
        member_name: str,
    ) -> tuple[int, Type] | None:
        members = self._sema.record_definitions.get(record_name)
        if members is None:
            return None
        layout = self._sema.record_layouts[record_name]
        for member, member_layout in zip(members, layout.members, strict=True):
            found = self._record_member_offset_match(member, member_name)
            if found is not None:
                nested_offset, nested_type = found
                return member_layout.offset + nested_offset, nested_type
        return None

    def _record_member_offset_match(
        self,
        member: RecordMemberInfo,
        member_name: str,
    ) -> tuple[int, Type] | None:
        if member.name == member_name:
            if member.bit_width is not None:
                return None
            return 0, member.type_
        if (
            member.name is None
            and member.bit_width is None
            and not member.type_.declarator_ops
            and member.type_.name.startswith(("struct ", "union "))
        ):
            return self._record_member_offset_and_type(member.type_.name, member_name)
        return None

    def _eval_case_val(self, expr: Expr) -> int:
        if isinstance(expr, IntLiteral):
            return self._parse_int_value(expr.value)
        if isinstance(expr, CharLiteral):
            return char_literal_value(expr.value)
        if isinstance(expr, UnaryExpr):
            if expr.op == "-":
                return -self._eval_case_val(expr.operand)
            if expr.op == "+":
                return self._eval_case_val(expr.operand)
            if expr.op == "!":
                return int(self._eval_case_val(expr.operand) == 0)
            if expr.op == "~":
                return ~self._eval_case_val(expr.operand)
        if isinstance(expr, CommaExpr):
            return self._eval_case_val(expr.right)
        if isinstance(expr, Identifier):
            # Check function locals first, then file scope.
            if self._func_sym:
                sym = self._func_sym.locals.get(expr.name)
                if isinstance(sym, EnumConstSymbol):
                    return sym.value
            sym = None
            if self._sema.file_scope is not None:
                sym = self._sema.file_scope.lookup(expr.name)
            if isinstance(sym, EnumConstSymbol):
                return sym.value
        if isinstance(expr, BinaryExpr):
            left = self._eval_case_val(expr.left)
            right = self._eval_case_val(expr.right)
            if expr.op == "+":
                return left + right
            if expr.op == "-":
                return left - right
            if expr.op == "*":
                return left * right
            if expr.op == "/":
                return 0 if right == 0 else left // right
            if expr.op == "%":
                return 0 if right == 0 else left % right
            if expr.op == "<<":
                return left << right
            if expr.op == ">>":
                return left >> right
            if expr.op == "|":
                return left | right
            if expr.op == "&":
                return left & right
            if expr.op == "^":
                return left ^ right
            if expr.op == "==":
                return int(left == right)
            if expr.op == "!=":
                return int(left != right)
            if expr.op == "<":
                return int(left < right)
            if expr.op == ">":
                return int(left > right)
            if expr.op == "<=":
                return int(left <= right)
            if expr.op == ">=":
                return int(left >= right)
            if expr.op == "&&":
                return int(left != 0 and right != 0)
            if expr.op == "||":
                return int(left != 0 or right != 0)
            return 0
        if isinstance(expr, ConditionalExpr):
            condition = self._eval_case_val(expr.condition)
            return self._eval_case_val(expr.then_expr if condition else expr.else_expr)
        if isinstance(expr, CastExpr):
            return self._eval_case_val(expr.expr)
        raise llvm_backend_error(self._result.filename, "Expected integer constant for case")


# ── public API ───────────────────────────────────────────────


def generate_llvm_ir(
    result: FrontendResult,
    *,
    debug: bool = False,
    target_triple: str = "arm64-apple-macosx11.0.0",
) -> str:
    return _LLVMGen(result, debug=debug, target_triple=target_triple).generate()


def _llvm_print_module_to_string(module: int) -> str:
    c = llvm()
    ir = c.PrintModuleToString(module)
    return ir.decode("utf-8") if isinstance(ir, bytes) else str(ir)


def _enable_unwind_tables(llvm_text: str) -> str:
    lines: list[str] = []
    in_function_header = False
    for line in llvm_text.splitlines():
        if line.startswith("define "):
            in_function_header = True
        if in_function_header and line.endswith("{") and " uwtable" not in line:
            debug_index = line.find(" !dbg !")
            if debug_index >= 0:
                line = line[:debug_index] + " uwtable" + line[debug_index:]
            else:
                line = line[:-1].rstrip() + " uwtable {"
        if in_function_header and line.endswith("{"):
            in_function_header = False
        lines.append(line)
    return "\n".join(lines) + "\n"
