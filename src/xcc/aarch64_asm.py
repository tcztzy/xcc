"""Direct Darwin AArch64 assembly backend.

This backend is intentionally small: it emits native assembly for scalar
integer leaf functions and rejects unsupported C constructs with deterministic
codegen diagnostics instead of falling back to LLVM.
"""

import struct
from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass
from typing import cast

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
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
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
    StaticAssertDecl,
    Stmt,
    StringLiteral,
    SubscriptExpr,
    SwitchStmt,
    TypedefDecl,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
    WhileStmt,
)
from xcc.diag import CodegenError, Diagnostic
from xcc.frontend import FrontendResult
from xcc.sema.constants import char_literal_body, decode_escaped_units, string_literal_body
from xcc.sema.symbols import EnumConstSymbol, FunctionSymbol, RecordMemberInfo, VarSymbol
from xcc.sema.type_helpers import (
    is_floating_type,
    is_integer_type,
    unqualified_type,
    usual_arithmetic_conversion,
)
from xcc.types import CHAR, DOUBLE, INT, VOID, Type

_AARCH64_UNSUPPORTED = "XCC-A64-0001"


def aarch64_backend_error(filename: str, message: str) -> CodegenError:
    return CodegenError(Diagnostic("codegen", filename, message, code=_AARCH64_UNSUPPORTED))


@dataclass(frozen=True)
class _ScalarInfo:
    size: int
    align: int
    signed: bool
    is_float: bool = False

    @property
    def bits(self) -> int:
        return self.size * 8


@dataclass(frozen=True)
class _Slot:
    offset: int
    type_: Type
    info: _ScalarInfo


@dataclass(frozen=True)
class _Value:
    type_: Type
    info: _ScalarInfo
    reg: int


@dataclass(frozen=True)
class _VariadicAggregate:
    type_: Type
    slot: _Slot


@dataclass(frozen=True)
class _Global:
    label: str
    type_: Type
    is_static: bool


@dataclass(frozen=True)
class _StaticLocal:
    label: str
    type_: Type
    init: Expr | InitList | None


@dataclass(frozen=True)
class _MemberAccess:
    offset: int
    type_: Type
    bit_offset: int | None = None
    bit_width: int | None = None


class _AArch64AsmGen:
    _BASE_SCRATCH_SIZE = 16
    _EXPR_SPILL_SIZE = 16
    _CALL_ARG_SPILL_SIZE = 128
    _CALL_ARG_INT_SPILL_SIZE = 64

    def __init__(self, result: FrontendResult):
        self._result = result
        self._unit = result.unit
        self._sema = result.sema
        self._type_map = result.sema.type_map
        self._lines: list[str] = []
        self._func: FunctionDef | None = None
        self._func_sym: FunctionSymbol | None = None
        self._param_slots: dict[str, _Slot] = {}
        self._decl_slots: dict[int, _Slot] = {}
        self._compound_literal_slots: dict[int, _Slot] = {}
        self._byval_arg_slots: dict[int, _Slot] = {}
        self._indirect_call_slots: dict[int, _Slot] = {}
        self._variadic_arg_slots: dict[int, _Slot] = {}
        self._sret_slot: _Slot | None = None
        self._scope_stack: list[dict[str, _Slot]] = []
        self._frame_size = 0
        self._scratch_size = 0
        self._outgoing_arg_size = 0
        self._outgoing_arg_offset = 0
        self._frame_record_offset = 0
        self._stack_size = 0
        self._save_frame_record = False
        self._expr_spill_reserved_depth = 0
        self._expr_spill_depth = 0
        self._call_arg_spill_depth = 0
        self._subscript_index_regs: list[int] = []
        self._return_label = ""
        self._label_counter = 0
        self._string_literals: dict[bytes, str] = {}
        self._wide_string_literals: dict[bytes, str] = {}
        self._float_literals: dict[tuple[int, int], str] = {}
        self._compound_literals: list[tuple[str, Type, InitList]] = []
        self._globals: dict[str, _Global] = {}
        self._static_locals: dict[tuple[str, str], _StaticLocal] = {}
        self._data_static_function: str | None = None
        self._break_stack: list[str] = []
        self._continue_stack: list[str] = []
        self._switch_stack: list[tuple[dict[int, str], str | None, str]] = []

    def generate(self) -> str:
        self._lines = [".section __TEXT,__text,regular,pure_instructions"]
        self._collect_globals()
        self._collect_static_locals()
        for function in self._unit.functions:
            if function.body is None:
                continue
            if function.is_inline:
                continue
            self._emit_function(function)
        for function in self._used_inline_functions():
            self._emit_function(function, force_local=True)
        self._emit_global_data()
        if self._string_literals:
            self._lines.append(".section __TEXT,__cstring,cstring_literals")
            emitted_labels: set[str] = set()
            for value, label in self._string_literals.items():
                if label in emitted_labels:
                    continue
                emitted_labels.add(label)
                self._lines.append(f"{label}:")
                self._lines.append(
                    f'    .asciz "{self._asm_string(value, strip_trailing_nul=True)}"'
                )
        if self._wide_string_literals:
            self._lines.append(".section __TEXT,__const")
            for value, label in self._wide_string_literals.items():
                self._lines.append(".p2align 2")
                self._lines.append(f"{label}:")
                for offset in range(0, len(value), 16):
                    chunk = value[offset : offset + 16]
                    bytes_ = ", ".join(f"0x{byte:02x}" for byte in chunk)
                    self._lines.append(f"    .byte {bytes_}")
        if any(size == 8 for _, size in self._float_literals):
            self._lines.append(".section __TEXT,__literal8,8byte_literals")
            for (bits, size), label in self._float_literals.items():
                if size != 8:
                    continue
                self._lines.append(f"{label}:")
                self._lines.append(f"    .quad 0x{bits:016x}")
        if any(size == 4 for _, size in self._float_literals):
            self._lines.append(".section __TEXT,__literal4,4byte_literals")
            for (bits, size), label in self._float_literals.items():
                if size != 4:
                    continue
                self._lines.append(f"{label}:")
                self._lines.append(f"    .long 0x{bits:08x}")
        self._lines.append(".subsections_via_symbols")
        return "\n".join(self._lines) + "\n"

    def _collect_globals(self) -> None:
        if self._sema.file_scope is None:
            return

        def collect(stmt: Stmt) -> None:
            if isinstance(stmt, DeclGroupStmt):
                for declaration in stmt.declarations:
                    collect(declaration)
                return
            if (
                not isinstance(stmt, DeclStmt)
                or stmt.name is None
                or stmt.storage_class == "extern"
            ):
                return
            assert self._sema.file_scope is not None
            symbol = self._sema.file_scope.lookup(stmt.name)
            if not isinstance(symbol, VarSymbol) or symbol.is_extern:
                return
            self._globals[stmt.name] = _Global(
                self._global_symbol_name(stmt.name, stmt.storage_class == "static"),
                symbol.type_,
                stmt.storage_class == "static",
            )

        for declaration in self._unit.declarations:
            collect(declaration)

    def _used_inline_functions(self) -> list[FunctionDef]:
        inline_by_name = {
            function.name: function
            for function in self._unit.functions
            if function.body is not None and function.is_inline
        }
        pending: list[str] = []
        for function in self._unit.functions:
            if function.body is not None and not function.is_inline:
                pending.extend(self._referenced_function_names(function.body))
        for declaration in self._unit.declarations:
            pending.extend(self._referenced_function_names(declaration))
        used: set[str] = set()
        ordered: list[FunctionDef] = []
        while pending:
            name = pending.pop()
            if name in used:
                continue
            inline_function = inline_by_name.get(name)
            if inline_function is None or inline_function.body is None:
                continue
            used.add(name)
            ordered.append(inline_function)
            pending.extend(self._referenced_function_names(inline_function.body))
        return ordered

    def _referenced_function_names(self, node: object) -> list[str]:
        names: list[str] = []

        def walk(value: object) -> None:
            if isinstance(value, Identifier) and value.name in self._sema.function_signatures:
                names.append(value.name)
            if isinstance(value, (str, int, float, bytes, type(None))):
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)
                return
            if is_dataclass(value):
                for field in fields(value):
                    walk(getattr(value, field.name))

        walk(node)
        return names

    def _collect_static_locals(self) -> None:
        def collect(function: FunctionDef, stmt: Stmt) -> None:
            if isinstance(stmt, CompoundStmt):
                for child in stmt.statements:
                    collect(function, child)
                return
            if isinstance(stmt, DeclGroupStmt):
                for declaration in stmt.declarations:
                    collect(function, declaration)
                return
            if isinstance(stmt, DeclStmt):
                if stmt.name is None or stmt.storage_class != "static":
                    return
                func_sym = self._sema.functions.get(function.name)
                symbol = func_sym.locals.get(stmt.name) if func_sym is not None else None
                type_ = (
                    symbol.type_
                    if isinstance(symbol, VarSymbol)
                    else self._resolve_type_spec(stmt.type_spec)
                )
                label = f"L_.{function.name}.{stmt.name}"
                self._static_locals[(function.name, stmt.name)] = _StaticLocal(
                    label,
                    type_,
                    stmt.init,
                )
                return
            if isinstance(stmt, IfStmt):
                collect(function, stmt.then_body)
                if stmt.else_body is not None:
                    collect(function, stmt.else_body)
                return
            if isinstance(stmt, WhileStmt):
                collect(function, stmt.body)
                return
            if isinstance(stmt, ForStmt):
                if isinstance(stmt.init, Stmt):
                    collect(function, stmt.init)
                collect(function, stmt.body)
                return
            if isinstance(stmt, SwitchStmt):
                collect(function, stmt.body)
                return
            if isinstance(stmt, (CaseStmt, DefaultStmt, LabelStmt)):
                collect(function, stmt.body)

        for function in self._unit.functions:
            if function.body is not None:
                collect(function, function.body)

    def _emit_global_data(self) -> None:
        emitted_section = False
        initialized_globals: set[str] = set()
        emitted_labels: set[str] = set()

        def collect_initialized(stmt: Stmt) -> None:
            if isinstance(stmt, DeclGroupStmt):
                for declaration in stmt.declarations:
                    collect_initialized(declaration)
                return
            if (
                isinstance(stmt, DeclStmt)
                and stmt.name is not None
                and stmt.storage_class != "extern"
                and stmt.init is not None
            ):
                initialized_globals.add(stmt.name)

        def emit_decl(stmt: Stmt) -> None:
            nonlocal emitted_section
            if isinstance(stmt, DeclGroupStmt):
                for declaration in stmt.declarations:
                    emit_decl(declaration)
                return
            if (
                not isinstance(stmt, DeclStmt)
                or stmt.name is None
                or stmt.storage_class == "extern"
            ):
                return
            if stmt.init is None and stmt.name in initialized_globals:
                return
            global_ = self._globals.get(stmt.name)
            if global_ is None or global_.label in emitted_labels:
                return
            emitted_labels.add(global_.label)
            if not emitted_section:
                self._lines.append(".section __DATA,__data")
                emitted_section = True
            align = self._type_align(global_.type_) or 1
            self._lines.append(f".p2align {max(0, align.bit_length() - 1)}")
            if not global_.is_static:
                self._lines.append(f".globl {global_.label}")
            self._lines.append(f"{global_.label}:")
            self._emit_global_initializer(global_.type_, stmt.init)

        for declaration in self._unit.declarations:
            collect_initialized(declaration)
        for declaration in self._unit.declarations:
            emit_decl(declaration)
        for (function_name, _), static_local in self._static_locals.items():
            if not emitted_section:
                self._lines.append(".section __DATA,__data")
                emitted_section = True
            align = self._type_align(static_local.type_) or 1
            self._lines.append(f".p2align {max(0, align.bit_length() - 1)}")
            self._lines.append(f"{static_local.label}:")
            previous_static_function = self._data_static_function
            self._data_static_function = function_name
            try:
                self._emit_global_initializer(static_local.type_, static_local.init)
            finally:
                self._data_static_function = previous_static_function
        compound_index = 0
        while compound_index < len(self._compound_literals):
            label, type_, init = self._compound_literals[compound_index]
            compound_index += 1
            if not emitted_section:
                self._lines.append(".section __DATA,__data")
                emitted_section = True
            align = self._type_align(type_) or 1
            self._lines.append(f".p2align {max(0, align.bit_length() - 1)}")
            self._lines.append(f"{label}:")
            self._emit_global_initializer(type_, init)

    def _emit_global_initializer(self, type_: Type, init: Expr | InitList | None) -> None:
        if isinstance(init, StringLiteral) and type_.is_array():
            type_ = self._complete_array_string_initializer_type(type_, init)
        if isinstance(init, InitList):
            if type_.is_array():
                self._emit_global_array_initializer(type_, init)
                return
            if self._is_record_type(type_):
                self._emit_global_record_initializer(type_, init)
                return
            if len(init.items) == 1 and not init.items[0].designators:
                self._emit_global_initializer(type_, init.items[0].initializer)
                return
            raise self._error("AArch64 target does not support aggregate global initializer yet")
        if isinstance(init, CompoundLiteralExpr) and not (
            type_.declarator_ops and type_.declarator_ops[0][0] == "ptr"
        ):
            compound_type = self._complete_array_initializer_type(
                self._type_map.get(init) or self._resolve_type_spec(init.type_spec),
                init.initializer,
            )
            self._emit_global_initializer(compound_type, init.initializer)
            return
        if isinstance(init, StringLiteral) and type_.is_array():
            self._emit_global_char_array_string_initializer(type_, init)
            return
        if isinstance(init, Expr):
            self._emit_global_scalar_initializer(type_, init)
            return
        self._emit_global_zero(type_)

    def _emit_global_array_initializer(self, type_: Type, init: InitList) -> None:
        completed_type = self._complete_array_initializer_type(type_, init)
        element_type = completed_type.element_type()
        if element_type is None:
            raise self._error("AArch64 target cannot initialize non-array as array")
        length = completed_type.declarator_ops[0][1]
        items_by_index = self._array_initializer_items_by_index(init)
        if isinstance(length, int) and length < 0 and items_by_index:
            length = max(items_by_index) + 1
        if not isinstance(length, int) or length < 0:
            raise self._error("AArch64 target requires known global array initializer length")
        for index in range(length):
            item = items_by_index.get(index)
            if item is None:
                self._emit_global_zero(element_type)
            else:
                self._emit_global_initializer(element_type, item.initializer)

    def _array_initializer_items_by_index(self, init: InitList) -> dict[int, InitItem]:
        items_by_index: dict[int, InitItem] = {}
        positional_index = 0
        for item in init.items:
            if not item.designators:
                item_index = positional_index
            else:
                if len(item.designators) != 1:
                    raise self._error(
                        "AArch64 target does not support nested array designators yet"
                    )
                kind, value = item.designators[0]
                if kind != "index" or not isinstance(value, Expr):
                    raise self._error("AArch64 target does not support global array designator")
                evaluated_index = self._eval_int_constant(value)
                if evaluated_index is None:
                    raise self._error("AArch64 target requires constant array designator")
                item_index = evaluated_index
            items_by_index[item_index] = item
            positional_index = item_index + 1
        return items_by_index

    def _emit_global_record_initializer(self, type_: Type, init: InitList) -> None:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            raise self._error(f"AArch64 target cannot initialize record {type_}")
        if type_.name.startswith("union "):
            if not init.items:
                self._emit_global_zero(type_)
                return
            items_by_index = self._record_initializer_items_by_index(members, init)
            member_index = next(reversed(items_by_index))
            member = members[member_index]
            item = items_by_index[member_index]
            self._emit_global_initializer(member.type_, item.initializer)
            size = self._type_size(type_)
            member_size = self._type_size(member.type_)
            if size is None or member_size is None:
                raise self._error(f"AArch64 target cannot size record {type_}")
            if size > member_size:
                self._lines.append(f"    .zero {size - member_size}")
            return
        items_by_index = self._record_initializer_items_by_index(members, init)
        offset = 0
        active_bit_type: Type | None = None
        active_bit_base = 0
        active_bit_size = 0
        active_bit_used = 0
        active_bit_value = 0

        def flush_bitfield_unit() -> None:
            nonlocal active_bit_base
            nonlocal active_bit_size
            nonlocal active_bit_type
            nonlocal active_bit_used
            nonlocal active_bit_value
            nonlocal offset
            if active_bit_type is None:
                return
            if active_bit_base > offset:
                self._lines.append(f"    .zero {active_bit_base - offset}")
            self._emit_global_int_constant(self._scalar_info(active_bit_type), active_bit_value)
            offset = active_bit_base + active_bit_size
            active_bit_type = None
            active_bit_used = 0
            active_bit_value = 0

        for index, member in enumerate(members):
            if member.bit_width is not None:
                member_align = self._type_align(member.type_)
                member_size = self._type_size(member.type_)
                if member_align is None or member_size is None:
                    raise self._error(f"AArch64 target cannot size bit-field member {member.name}")
                if member.bit_width == 0:
                    flush_bitfield_unit()
                    access_offset = self._align_to(offset, member_align)
                    if access_offset > offset:
                        self._lines.append(f"    .zero {access_offset - offset}")
                    offset = access_offset
                    continue
                member_bits = member_size * 8
                if (
                    active_bit_type != member.type_
                    or active_bit_used + member.bit_width > member_bits
                ):
                    flush_bitfield_unit()
                    access_offset = self._align_to(offset, member_align)
                    if access_offset > offset:
                        self._lines.append(f"    .zero {access_offset - offset}")
                    offset = access_offset
                    active_bit_base = offset
                    active_bit_size = member_size
                    active_bit_used = 0
                    active_bit_type = member.type_
                    active_bit_value = 0
                bitfield_item = items_by_index.get(index)
                if bitfield_item is not None:
                    if not isinstance(bitfield_item.initializer, Expr):
                        raise self._error("AArch64 target requires scalar bit-field initializer")
                    bitfield_value = self._eval_int_constant(bitfield_item.initializer)
                    if bitfield_value is None:
                        raise self._error("AArch64 target requires constant bit-field initializer")
                    active_bit_value |= (
                        bitfield_value & ((1 << member.bit_width) - 1)
                    ) << active_bit_used
                active_bit_used += member.bit_width
                continue
            flush_bitfield_unit()
            member_align = self._type_align(member.type_)
            if member_align is None:
                raise self._error(f"AArch64 target cannot align record member {member.name}")
            access_offset = self._align_to(offset, member_align)
            member_item = items_by_index.get(index)
            if self._is_trailing_flexible_array_member(members, index):
                if access_offset > offset:
                    self._lines.append(f"    .zero {access_offset - offset}")
                if member_item is not None:
                    if isinstance(member_item.initializer, Expr) and self._is_zero_initializer(
                        member_item.initializer
                    ):
                        offset = access_offset
                        continue
                    flex_type = self._complete_flexible_array_initializer_type(
                        member.type_, member_item.initializer
                    )
                    self._emit_global_initializer(flex_type, member_item.initializer)
                    flex_size = self._type_size(flex_type)
                    if flex_size is None:
                        raise self._error(f"AArch64 target cannot size record member {member.name}")
                    offset = access_offset + flex_size
                else:
                    offset = access_offset
                continue
            member_size = self._type_size(member.type_)
            if member_size is None:
                raise self._error(f"AArch64 target cannot size record member {member.name}")
            if access_offset > offset:
                self._lines.append(f"    .zero {access_offset - offset}")
            if member_item is None:
                self._emit_global_zero(member.type_)
            else:
                if (
                    isinstance(member_item.initializer, Expr)
                    and self._is_aggregate_type(member.type_)
                    and self._is_zero_initializer(member_item.initializer)
                ):
                    self._emit_global_zero(member.type_)
                    offset = access_offset + member_size
                    continue
                self._emit_global_initializer(member.type_, member_item.initializer)
            offset = access_offset + member_size
        flush_bitfield_unit()
        size = self._type_size(type_)
        if size is None:
            raise self._error(f"AArch64 target cannot size type {type_}")
        if size > offset:
            self._lines.append(f"    .zero {size - offset}")

    def _record_initializer_items_by_index(
        self,
        members: tuple[RecordMemberInfo, ...],
        init: InitList,
    ) -> dict[int, InitItem]:
        items_by_index: dict[int, InitItem] = {}
        nested_items_by_index: dict[int, list[InitItem]] = {}
        positional_index = 0
        for item in init.items:
            member_name = self._record_init_first_member_designator_name(item)
            if member_name is None:
                if positional_index >= len(members):
                    raise self._error("AArch64 target found too many record initializers")
                member_index = positional_index
                items_by_index[member_index] = item
                nested_items_by_index.pop(member_index, None)
            else:
                member_index, is_direct = self._record_initializer_member_index(
                    members, member_name
                )
                if member_index < 0:
                    raise self._error(f"AArch64 target cannot find member {member_name}")
                remaining_designators = item.designators[1:] if is_direct else item.designators
                if is_direct and not remaining_designators:
                    items_by_index[member_index] = item
                    nested_items_by_index.pop(member_index, None)
                else:
                    nested_items = nested_items_by_index.setdefault(member_index, [])
                    nested_items.append(InitItem(remaining_designators, item.initializer))
                    items_by_index[member_index] = InitItem((), InitList(tuple(nested_items)))
            positional_index = member_index + 1
        return items_by_index

    @staticmethod
    def _record_init_first_member_designator_name(item: InitItem) -> str | None:
        if not item.designators:
            return None
        kind, value = item.designators[0]
        if kind == "member" and isinstance(value, str):
            return value
        return None

    def _record_initializer_member_index(
        self,
        members: tuple[RecordMemberInfo, ...],
        member_name: str,
    ) -> tuple[int, bool]:
        for index, member in enumerate(members):
            if member.name == member_name:
                return index, True
        for index, member in enumerate(members):
            if member.name is not None:
                continue
            if self._record_member_access_match(member, member_name) is not None:
                return index, False
        return -1, False

    def _emit_global_zero(self, type_: Type) -> None:
        size = self._type_size(type_)
        if size is None:
            raise self._error(f"AArch64 target cannot size type {type_}")
        self._lines.append(f"    .zero {size}")

    def _emit_global_char_array_string_initializer(
        self,
        type_: Type,
        init: StringLiteral,
    ) -> None:
        element_type = type_.element_type()
        if element_type is None or unqualified_type(element_type).name not in {
            "char",
            "signed char",
            "unsigned char",
        }:
            raise self._error("AArch64 target only supports char array string init yet")
        length = type_.declarator_ops[0][1]
        if not isinstance(length, int) or length < 0:
            raise self._error("AArch64 target requires known char array length")
        data = self._string_literal_bytes(init)
        emitted = data[:length]
        self._lines.append(f'    .ascii "{self._asm_string(emitted)}"')
        if len(emitted) < length:
            self._lines.append(f"    .zero {length - len(emitted)}")

    def _emit_global_scalar_initializer(self, type_: Type, init: Expr) -> None:
        info = self._scalar_info(type_)
        if isinstance(init, CastExpr):
            self._emit_global_scalar_initializer(type_, init.expr)
            return
        if isinstance(init, CallExpr):
            int_value = self._eval_int_constant(init)
            if int_value is not None:
                self._emit_global_int_constant(info, int_value)
                return
        if type_.declarator_ops and type_.declarator_ops[0][0] == "ptr":
            if isinstance(init, CompoundLiteralExpr):
                compound_type = self._complete_array_initializer_type(
                    self._type_map.get(init) or self._resolve_type_spec(init.type_spec),
                    init.initializer,
                )
                label = self._add_global_compound_literal(compound_type, init.initializer)
                self._lines.append(f"    .quad {label}")
                return
            symbol = self._global_pointer_initializer_symbol(init)
            if symbol is not None:
                self._lines.append(f"    .quad {symbol}")
                return
            if isinstance(init, StringLiteral):
                label = self._string_literal_label(init)
                self._lines.append(f"    .quad {label}")
                return
            if self._is_null_pointer_initializer(init):
                self._lines.append("    .quad 0")
                return
        if info.is_float:
            float_value = self._eval_float_constant(init)
            if float_value is not None:
                bits = self._float_to_bits(float_value, info.size)
                directive = ".quad" if info.size == 8 else ".long"
                width = 16 if info.size == 8 else 8
                self._lines.append(f"    {directive} 0x{bits:0{width}x}")
                return
        if isinstance(init, FloatLiteral):
            bits = self._float_bits(init.value, info.size)
            directive = ".quad" if info.size == 8 else ".long"
            width = 16 if info.size == 8 else 8
            self._lines.append(f"    {directive} 0x{bits:0{width}x}")
            return
        int_value = self._eval_int_constant(init)
        if int_value is not None:
            self._emit_global_int_constant(info, int_value)
            return
        if isinstance(init, BuiltinOffsetofExpr):
            value = self._offsetof_value(init)
            if value is not None:
                self._emit_global_int_constant(info, value)
                return
        raise self._error(
            f"AArch64 target does not support global initializer {type(init).__name__}"
        )

    def _global_pointer_initializer_symbol(self, init: Expr) -> str | None:
        address = self._global_pointer_initializer_address(init)
        if address is None:
            return None
        label, offset = address
        if offset:
            return f"{label}+{offset}"
        return label

    def _global_pointer_initializer_address(self, init: Expr) -> tuple[str, int] | None:
        if isinstance(init, Identifier):
            if init.name in self._sema.function_signatures:
                return self._symbol_name(init.name), 0
            static_local = self._static_local_initializer(init.name)
            if static_local is not None:
                return static_local.label, 0
            global_ = self._globals.get(init.name)
            if global_ is not None:
                return global_.label, 0
            if self._sema.file_scope is not None:
                symbol = self._sema.file_scope.lookup(init.name)
                if isinstance(symbol, VarSymbol):
                    return self._symbol_name(init.name), 0
        if isinstance(init, UnaryExpr) and init.op == "&":
            return self._global_lvalue_initializer_symbol(init.operand)
        if isinstance(init, CastExpr):
            return self._global_pointer_initializer_address(init.expr)
        if isinstance(init, ConditionalExpr):
            condition = self._eval_int_constant(init.condition)
            if condition is None:
                return None
            selected = init.then_expr if condition else init.else_expr
            return self._global_pointer_initializer_address(selected)
        if isinstance(init, BinaryExpr):
            if init.op == "+":
                left = self._global_pointer_initializer_address(init.left)
                right = self._eval_int_constant(init.right)
                if left is not None and right is not None:
                    label, offset = left
                    return label, offset + right * self._pointer_step_size(
                        self._expr_type(init.left)
                    )
                right_address = self._global_pointer_initializer_address(init.right)
                left_value = self._eval_int_constant(init.left)
                if right_address is not None and left_value is not None:
                    label, offset = right_address
                    return label, offset + left_value * self._pointer_step_size(
                        self._expr_type(init.right)
                    )
            if init.op == "-":
                left = self._global_pointer_initializer_address(init.left)
                right = self._eval_int_constant(init.right)
                if left is not None and right is not None:
                    label, offset = left
                    return label, offset - right * self._pointer_step_size(
                        self._expr_type(init.left)
                    )
        expr_type = self._type_map.get(init)
        if expr_type is not None and expr_type.is_array():
            return self._global_lvalue_initializer_symbol(init)
        return None

    def _global_lvalue_initializer_symbol(self, expr: Expr) -> tuple[str, int] | None:
        if isinstance(expr, Identifier):
            return self._global_pointer_initializer_address(expr)
        if isinstance(expr, CompoundLiteralExpr):
            compound_type = self._complete_array_initializer_type(
                self._type_map.get(expr) or self._resolve_type_spec(expr.type_spec),
                expr.initializer,
            )
            label = self._add_global_compound_literal(compound_type, expr.initializer)
            return label, 0
        if isinstance(expr, SubscriptExpr):
            base = self._global_lvalue_initializer_symbol(expr.base)
            if base is None:
                return None
            base_type = self._expr_type(expr.base)
            element_type = base_type.element_type()
            if element_type is None:
                return None
            element_size = self._type_size(element_type)
            index = self._eval_int_constant(expr.index)
            if element_size is None or index is None:
                return None
            label, offset = base
            return label, offset + index * element_size
        if isinstance(expr, MemberExpr):
            if expr.through_pointer:
                base = self._global_pointer_initializer_address(expr.base)
                member_base_type = self._expr_type(expr.base).pointee()
            else:
                base = self._global_lvalue_initializer_symbol(expr.base)
                member_base_type = self._expr_type(expr.base)
            if base is None:
                return None
            base_label, base_offset = base
            if (
                member_base_type is None
                or member_base_type.declarator_ops
                or not member_base_type.name.startswith(("struct ", "union "))
            ):
                return None
            access = self._record_member_access(member_base_type.name, expr.member)
            if access is None or access.bit_width is not None:
                return None
            return base_label, base_offset + access.offset
        return None

    def _static_local_initializer(self, name: str) -> _StaticLocal | None:
        if self._data_static_function is None:
            return None
        return self._static_locals.get((self._data_static_function, name))

    def _emit_global_int_constant(self, info: _ScalarInfo, value: int) -> None:
        if info.is_float:
            raise self._error("AArch64 target cannot emit integer data for float type")
        directive = {1: ".byte", 2: ".short", 4: ".long", 8: ".quad"}[info.size]
        coerced = value & ((1 << info.bits) - 1)
        if info.signed and coerced >= (1 << (info.bits - 1)):
            coerced -= 1 << info.bits
        self._lines.append(f"    {directive} {coerced}")

    def _is_null_pointer_initializer(self, expr: Expr) -> bool:
        value = self._eval_int_constant(expr)
        return value == 0

    def _is_zero_initializer(self, expr: Expr) -> bool:
        return self._eval_int_constant(expr) == 0

    def _add_global_compound_literal(self, type_: Type, init: InitList) -> str:
        label = f"L_.compound{len(self._compound_literals)}"
        self._compound_literals.append((label, type_, init))
        return label

    @staticmethod
    def _complete_array_initializer_type(type_: Type, init: InitList) -> Type:
        if not type_.is_array():
            return type_
        kind, length = type_.declarator_ops[0]
        if kind == "arr" and isinstance(length, int) and length < 0:
            return Type(
                type_.name,
                declarator_ops=(("arr", len(init.items)),) + type_.declarator_ops[1:],
                qualifiers=type_.qualifiers,
            )
        return type_

    def _complete_array_string_initializer_type(self, type_: Type, init: StringLiteral) -> Type:
        if not type_.is_array():
            return type_
        element_type = type_.element_type()
        if element_type is None or unqualified_type(element_type).name not in {
            "char",
            "signed char",
            "unsigned char",
        }:
            return type_
        kind, length = type_.declarator_ops[0]
        if kind == "arr" and isinstance(length, int) and length < 0:
            return Type(
                type_.name,
                declarator_ops=(("arr", len(self._string_literal_bytes(init))),)
                + type_.declarator_ops[1:],
                qualifiers=type_.qualifiers,
            )
        return type_

    def _complete_flexible_array_initializer_type(
        self,
        type_: Type,
        init: Expr | InitList,
    ) -> Type:
        if not self._is_flexible_array_type(type_):
            return type_
        if isinstance(init, InitList):
            return self._complete_array_initializer_type(type_, init)
        if isinstance(init, StringLiteral):
            element_type = type_.element_type()
            if element_type is not None and unqualified_type(element_type).name in {
                "char",
                "signed char",
                "unsigned char",
            }:
                return Type(
                    type_.name,
                    declarator_ops=(("arr", len(self._string_literal_bytes(init))),)
                    + type_.declarator_ops[1:],
                    qualifiers=type_.qualifiers,
                )
        return type_

    @staticmethod
    def _is_flexible_array_type(type_: Type) -> bool:
        if not type_.is_array():
            return False
        length = type_.declarator_ops[0][1]
        return isinstance(length, int) and length < 0

    @classmethod
    def _is_aggregate_type(cls, type_: Type) -> bool:
        return type_.is_array() or cls._is_record_type(type_)

    @classmethod
    def _is_trailing_flexible_array_member(
        cls, members: tuple[RecordMemberInfo, ...], index: int
    ) -> bool:
        if index != len(members) - 1:
            return False
        member_type = members[index].type_
        return isinstance(member_type, Type) and cls._is_flexible_array_type(member_type)

    @staticmethod
    def _is_record_type(type_: Type) -> bool:
        return not type_.declarator_ops and (
            type_.name.startswith(("struct ", "union ")) or type_.name in {"struct", "union"}
        )

    @staticmethod
    def _is_function_type(type_: Type) -> bool:
        return bool(type_.declarator_ops and type_.declarator_ops[0][0] == "fn")

    @staticmethod
    def _is_void_type(type_: Type) -> bool:
        return unqualified_type(type_) == VOID

    def _emit_function(self, function: FunctionDef, force_local: bool = False) -> None:
        body = function.body
        assert body is not None
        self._func = function
        self._func_sym = self._sema.functions.get(function.name)
        if self._func_sym is None:
            raise self._error(f"Missing semantic function symbol: {function.name}")
        if (
            not self._is_void_type(self._func_sym.return_type)
            and not self._record_return_fields(self._func_sym.return_type)
            and not self._is_indirect_return_type(self._func_sym.return_type)
        ):
            self._scalar_info(self._func_sym.return_type)
        self._prepare_frame(function, body)
        self._save_frame_record = self._stmt_contains_call(body)
        expr_spill_depth = self._stmt_expr_spill_depth(body)
        call_arg_spill_depth = self._stmt_call_arg_spill_depth(body)
        if self._stmt_needs_scratch(body) or expr_spill_depth or call_arg_spill_depth:
            self._scratch_size = (
                self._BASE_SCRATCH_SIZE
                + expr_spill_depth * self._EXPR_SPILL_SIZE
                + call_arg_spill_depth * self._CALL_ARG_SPILL_SIZE
            )
        else:
            self._scratch_size = 0
        self._outgoing_arg_size = self._max_outgoing_arg_size(body)
        self._outgoing_arg_offset = self._frame_size + self._scratch_size
        self._frame_record_offset = self._outgoing_arg_offset + self._outgoing_arg_size
        self._stack_size = self._frame_record_offset + (16 if self._save_frame_record else 0)
        self._expr_spill_reserved_depth = expr_spill_depth
        self._expr_spill_depth = 0
        self._call_arg_spill_depth = 0

        label = self._symbol_name(function.name)
        self._return_label = f"L_{function.name}_return"
        self._lines.append(".p2align 2")
        if function.storage_class != "static" and not force_local:
            self._lines.append(f".globl {label}")
        self._lines.append(f"{label}:")
        if self._stack_size:
            self._emit_adjust_sp("sub", self._stack_size)
        if self._save_frame_record:
            if self._frame_record_offset <= 504 and self._frame_record_offset % 8 == 0:
                self._emit(f"stp x29, x30, [sp, #{self._frame_record_offset}]")
                self._emit(f"add x29, sp, #{self._frame_record_offset}")
            else:
                self._emit_add_byte_offset(11, "sp", self._frame_record_offset)
                self._emit("stp x29, x30, [x11]")
                self._emit("mov x29, x11")
        if self._sret_slot is not None:
            self._emit_store(self._sret_slot, 8)
        self._spill_parameters(function)
        self._scope_stack = [dict(self._param_slots)]
        try:
            self._emit_stmt(body)
        finally:
            self._scope_stack = []
        self._lines.append(f"{self._return_label}:")
        if self._save_frame_record:
            if self._frame_record_offset <= 504 and self._frame_record_offset % 8 == 0:
                self._emit(f"ldp x29, x30, [sp, #{self._frame_record_offset}]")
            else:
                self._emit_add_byte_offset(11, "sp", self._frame_record_offset)
                self._emit("ldp x29, x30, [x11]")
        if self._stack_size:
            self._emit_adjust_sp("add", self._stack_size)
        self._emit("ret")

    def _prepare_frame(self, function: FunctionDef, body: CompoundStmt) -> None:
        self._param_slots = {}
        self._decl_slots = {}
        self._compound_literal_slots = {}
        self._byval_arg_slots = {}
        self._indirect_call_slots = {}
        self._variadic_arg_slots = {}
        self._sret_slot = None
        offset = 0

        def add_slot(type_: Type, alignment: int | None = None) -> _Slot:
            nonlocal offset
            info = self._slot_info(type_)
            align = alignment or info.align
            offset = self._align_to(offset, align)
            slot = _Slot(offset, type_, info)
            offset += info.size
            return slot

        assert self._func_sym is not None
        if self._is_indirect_return_type(self._func_sym.return_type):
            self._sret_slot = add_slot(VOID.pointer_to())
        for param in function.params:
            if param.name is None:
                continue
            symbol = self._func_sym.locals.get(param.name)
            if not isinstance(symbol, VarSymbol):
                raise self._error(f"Missing parameter symbol: {param.name}")
            self._param_slots[param.name] = add_slot(symbol.type_, symbol.alignment)

        def add_decl_slot(stmt: DeclStmt, type_: Type, alignment: int | None = None) -> None:
            self._decl_slots[id(stmt)] = add_slot(type_, alignment)

        self._collect_local_slots(body, add_decl_slot)

        def add_compound_literal_slot(expr: CompoundLiteralExpr) -> None:
            type_ = self._complete_array_initializer_type(
                self._type_map.get(expr) or self._resolve_type_spec(expr.type_spec),
                expr.initializer,
            )
            self._compound_literal_slots[id(expr)] = add_slot(type_)

        self._collect_compound_literal_slots(body, add_compound_literal_slot)

        def add_byval_arg_slot(expr: Expr, type_: Type) -> None:
            self._byval_arg_slots[id(expr)] = add_slot(type_)

        self._collect_byval_arg_slots(body, add_byval_arg_slot)

        def add_indirect_call_slot(expr: CallExpr, type_: Type) -> None:
            self._indirect_call_slots[id(expr)] = add_slot(type_)

        self._collect_indirect_call_slots(body, add_indirect_call_slot)

        def add_variadic_arg_slot(expr: Expr, type_: Type) -> None:
            self._variadic_arg_slots[id(expr)] = add_slot(type_)

        self._collect_variadic_arg_slots(body, add_variadic_arg_slot)
        self._frame_size = self._align_to(offset, 16)

    def _collect_local_slots(
        self,
        stmt: Stmt,
        add_slot: Callable[[DeclStmt, Type, int | None], None],
    ) -> None:
        if isinstance(stmt, CompoundStmt):
            for child in stmt.statements:
                self._collect_local_slots(child, add_slot)
            return
        if isinstance(stmt, IfStmt):
            self._collect_local_slots(stmt.then_body, add_slot)
            if stmt.else_body is not None:
                self._collect_local_slots(stmt.else_body, add_slot)
            return
        if isinstance(stmt, WhileStmt):
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, DoWhileStmt):
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, ForStmt):
            if isinstance(stmt.init, Stmt):
                self._collect_local_slots(stmt.init, add_slot)
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, LabelStmt):
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, SwitchStmt):
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, (CaseStmt, DefaultStmt)):
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, DeclStmt):
            if stmt.name is None or stmt.storage_class == "typedef":
                return
            if stmt.storage_class in {"static", "extern"}:
                return
            type_ = self._local_decl_type(stmt)
            if self._is_function_type(type_):
                return
            type_ = self._complete_local_array_bound_type(stmt, type_)
            if isinstance(stmt.init, InitList):
                type_ = self._complete_array_initializer_type(type_, stmt.init)
            if isinstance(stmt.init, StringLiteral):
                type_ = self._complete_array_string_initializer_type(type_, stmt.init)
            add_slot(stmt, type_, stmt.alignment)
            return
        if isinstance(stmt, DeclGroupStmt):
            for declaration in stmt.declarations:
                self._collect_local_slots(declaration, add_slot)

    def _collect_compound_literal_slots(
        self,
        node: object,
        add_slot: Callable[[CompoundLiteralExpr], None],
    ) -> None:
        if isinstance(node, CompoundLiteralExpr):
            if id(node) not in self._compound_literal_slots:
                add_slot(node)
            self._collect_compound_literal_slots(node.initializer, add_slot)
            return
        if isinstance(node, (str, int, float, bytes, type(None))):
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                self._collect_compound_literal_slots(item, add_slot)
            return
        if is_dataclass(node):
            for field in fields(node):
                self._collect_compound_literal_slots(getattr(node, field.name), add_slot)

    def _collect_byval_arg_slots(
        self,
        node: object,
        add_slot: Callable[[Expr, Type], None],
    ) -> None:
        if isinstance(node, CallExpr):
            for index, arg in enumerate(node.args):
                param_type = self._call_param_type(node, index)
                if (
                    param_type is not None
                    and self._is_indirect_argument_type(param_type)
                    and id(arg) not in self._byval_arg_slots
                ):
                    add_slot(arg, param_type)
        if isinstance(node, (str, int, float, bytes, type(None))):
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                self._collect_byval_arg_slots(item, add_slot)
            return
        if is_dataclass(node):
            for field in fields(node):
                self._collect_byval_arg_slots(getattr(node, field.name), add_slot)

    def _collect_indirect_call_slots(
        self,
        node: object,
        add_slot: Callable[[CallExpr, Type], None],
    ) -> None:
        if isinstance(node, CallExpr):
            type_ = self._expr_type(node)
            if self._is_record_type(type_) and id(node) not in self._indirect_call_slots:
                add_slot(node, type_)
        if isinstance(node, (str, int, float, bytes, type(None))):
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                self._collect_indirect_call_slots(item, add_slot)
            return
        if is_dataclass(node):
            for field in fields(node):
                self._collect_indirect_call_slots(getattr(node, field.name), add_slot)

    def _collect_variadic_arg_slots(
        self,
        node: object,
        add_slot: Callable[[Expr, Type], None],
    ) -> None:
        if isinstance(node, CallExpr):
            fixed_count = self._call_variadic_fixed_count(node)
            if fixed_count is not None:
                for index, arg in enumerate(node.args):
                    type_ = self._expr_type(arg)
                    if (
                        index >= fixed_count
                        and self._is_record_type(type_)
                        and id(arg) not in self._variadic_arg_slots
                    ):
                        add_slot(arg, type_)
        if isinstance(node, (str, int, float, bytes, type(None))):
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                self._collect_variadic_arg_slots(item, add_slot)
            return
        if is_dataclass(node):
            for field in fields(node):
                self._collect_variadic_arg_slots(getattr(node, field.name), add_slot)

    def _spill_parameters(self, function: FunctionDef) -> None:
        int_arg_reg = 0
        fp_arg_reg = 0
        for param in function.params:
            if param.name is None:
                continue
            slot = self._require_slot(param.name)
            hfa_offsets = self._hfa_double_offsets(slot.type_)
            if hfa_offsets is not None:
                for index, offset in enumerate(hfa_offsets):
                    self._emit_add_byte_offset(11, "sp", slot.offset + offset)
                    self._emit(f"str d{fp_arg_reg + index}, [x11]")
                fp_arg_reg += len(hfa_offsets)
                continue
            record_fields = self._record_return_fields(slot.type_)
            if record_fields is not None:
                for index, (offset, _, info) in enumerate(record_fields):
                    self._emit_add_byte_offset(11, "sp", slot.offset + offset)
                    self._emit_store_to_address(info, int_arg_reg + index, 11)
                int_arg_reg += len(record_fields)
                continue
            if self._is_indirect_argument_type(slot.type_):
                source_reg = int_arg_reg
                if int_arg_reg >= 8:
                    source_reg = 12
                    self._emit_stack_load_reg(
                        "x12",
                        self._stack_size + (int_arg_reg - 8) * 8,
                    )
                size = self._type_size(slot.type_)
                if size is None:
                    raise self._error(f"AArch64 target cannot size parameter {slot.type_}")
                self._emit_add_byte_offset(11, "sp", slot.offset)
                self._emit_copy_memory(11, source_reg, size)
                int_arg_reg += 1
                continue
            if slot.info.is_float:
                self._emit_store(slot, fp_arg_reg)
                fp_arg_reg += 1
                continue
            if int_arg_reg < 8:
                self._emit_store(slot, int_arg_reg)
            else:
                self._emit_stack_load_reg("x9", self._stack_size + (int_arg_reg - 8) * 8)
                self._emit_store(slot, 9)
            int_arg_reg += 1

    def _emit_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, CompoundStmt):
            self._scope_stack.append({})
            try:
                for child in stmt.statements:
                    self._emit_stmt(child)
            finally:
                self._scope_stack.pop()
            return
        if isinstance(stmt, ReturnStmt):
            self._emit_return(stmt)
            return
        if isinstance(stmt, DeclStmt):
            self._emit_decl(stmt)
            return
        if isinstance(stmt, DeclGroupStmt):
            for declaration in stmt.declarations:
                self._emit_stmt(declaration)
            return
        if isinstance(stmt, ExprStmt):
            self._emit_expr(stmt.expr, 0)
            return
        if isinstance(stmt, IfStmt):
            self._emit_if(stmt)
            return
        if isinstance(stmt, WhileStmt):
            self._emit_while(stmt)
            return
        if isinstance(stmt, DoWhileStmt):
            self._emit_do_while(stmt)
            return
        if isinstance(stmt, ForStmt):
            self._emit_for(stmt)
            return
        if isinstance(stmt, SwitchStmt):
            self._emit_switch(stmt)
            return
        if isinstance(stmt, CaseStmt):
            self._emit_case(stmt)
            return
        if isinstance(stmt, DefaultStmt):
            self._emit_default(stmt)
            return
        if isinstance(stmt, BreakStmt):
            self._emit_break()
            return
        if isinstance(stmt, ContinueStmt):
            self._emit_continue()
            return
        if isinstance(stmt, LabelStmt):
            self._emit_label(stmt)
            return
        if isinstance(stmt, GotoStmt):
            self._emit_goto(stmt)
            return
        if isinstance(stmt, (StaticAssertDecl, TypedefDecl)):
            return
        if isinstance(stmt, NullStmt):
            return
        raise self._error(f"AArch64 target does not support {type(stmt).__name__} yet")

    def _emit_if(self, stmt: IfStmt) -> None:
        else_label = self._new_label("if_else")
        end_label = self._new_label("if_end")
        self._emit_branch_if_zero(stmt.condition, else_label)
        self._emit_stmt(stmt.then_body)
        self._emit(f"b {end_label}")
        self._lines.append(f"{else_label}:")
        if stmt.else_body is not None:
            self._emit_stmt(stmt.else_body)
        self._lines.append(f"{end_label}:")

    def _emit_switch(self, stmt: SwitchStmt) -> None:
        cases, default_stmt = self._collect_switch_cases(stmt.body)
        case_labels = {id(case): self._new_label("switch_case") for case in cases}
        default_label = self._new_label("switch_default") if default_stmt is not None else None
        end_label = self._new_label("switch_end")
        condition = self._emit_expr(stmt.condition, 8)
        for case in cases:
            value = self._eval_case_value(case.value)
            self._emit_load_immediate(self._reg(9, condition.info), value, condition.info.bits)
            self._emit(f"cmp {self._reg(8, condition.info)}, {self._reg(9, condition.info)}")
            self._emit(f"b.eq {case_labels[id(case)]}")
        self._emit(f"b {default_label or end_label}")
        self._switch_stack.append((case_labels, default_label, end_label))
        self._break_stack.append(end_label)
        try:
            self._emit_stmt(stmt.body)
        finally:
            self._break_stack.pop()
            self._switch_stack.pop()
        self._emit(f"b {end_label}")
        self._lines.append(f"{end_label}:")

    def _emit_case(self, stmt: CaseStmt) -> None:
        if not self._switch_stack:
            raise self._error("AArch64 target found case outside switch")
        case_labels, _, _ = self._switch_stack[-1]
        self._lines.append(f"{case_labels[id(stmt)]}:")
        self._emit_stmt(stmt.body)

    def _emit_default(self, stmt: DefaultStmt) -> None:
        if not self._switch_stack:
            raise self._error("AArch64 target found default outside switch")
        _, default_label, _ = self._switch_stack[-1]
        if default_label is None:
            raise self._error("AArch64 target found default without switch label")
        self._lines.append(f"{default_label}:")
        self._emit_stmt(stmt.body)

    def _emit_break(self) -> None:
        if not self._break_stack:
            raise self._error("AArch64 target found break outside loop or switch")
        self._emit(f"b {self._break_stack[-1]}")

    def _emit_continue(self) -> None:
        if not self._continue_stack:
            raise self._error("AArch64 target found continue outside loop")
        self._emit(f"b {self._continue_stack[-1]}")

    def _emit_label(self, stmt: LabelStmt) -> None:
        self._lines.append(f"{self._user_label(stmt.name)}:")
        self._emit_stmt(stmt.body)

    def _emit_goto(self, stmt: GotoStmt) -> None:
        self._emit(f"b {self._user_label(stmt.label)}")

    def _emit_while(self, stmt: WhileStmt) -> None:
        cond_label = self._new_label("while_cond")
        body_label = self._new_label("while_body")
        end_label = self._new_label("while_end")
        self._lines.append(f"{cond_label}:")
        self._emit_branch_if_zero(stmt.condition, end_label)
        self._lines.append(f"{body_label}:")
        self._break_stack.append(end_label)
        self._continue_stack.append(cond_label)
        try:
            self._emit_stmt(stmt.body)
        finally:
            self._continue_stack.pop()
            self._break_stack.pop()
        self._emit(f"b {cond_label}")
        self._lines.append(f"{end_label}:")

    def _emit_do_while(self, stmt: DoWhileStmt) -> None:
        body_label = self._new_label("do_body")
        cond_label = self._new_label("do_cond")
        end_label = self._new_label("do_end")
        self._lines.append(f"{body_label}:")
        self._break_stack.append(end_label)
        self._continue_stack.append(cond_label)
        try:
            self._emit_stmt(stmt.body)
        finally:
            self._continue_stack.pop()
            self._break_stack.pop()
        self._lines.append(f"{cond_label}:")
        self._emit_branch_if_nonzero(stmt.condition, body_label)
        self._lines.append(f"{end_label}:")

    def _emit_for(self, stmt: ForStmt) -> None:
        if isinstance(stmt.init, Stmt):
            self._emit_stmt(stmt.init)
        elif isinstance(stmt.init, Expr):
            self._emit_expr(stmt.init, 0)
        cond_label = self._new_label("for_cond")
        post_label = self._new_label("for_post")
        end_label = self._new_label("for_end")
        self._lines.append(f"{cond_label}:")
        if stmt.condition is not None:
            self._emit_branch_if_zero(stmt.condition, end_label)
        self._break_stack.append(end_label)
        self._continue_stack.append(post_label)
        try:
            self._emit_stmt(stmt.body)
        finally:
            self._continue_stack.pop()
            self._break_stack.pop()
        self._lines.append(f"{post_label}:")
        if stmt.post is not None:
            self._emit_expr(stmt.post, 0)
        self._emit(f"b {cond_label}")
        self._lines.append(f"{end_label}:")

    def _collect_switch_cases(self, stmt: Stmt) -> tuple[list[CaseStmt], DefaultStmt | None]:
        cases: list[CaseStmt] = []
        default_stmt: DefaultStmt | None = None

        def collect(child: Stmt) -> None:
            nonlocal default_stmt
            if isinstance(child, SwitchStmt):
                return
            if isinstance(child, CompoundStmt):
                for nested in child.statements:
                    collect(nested)
                return
            if isinstance(child, CaseStmt):
                cases.append(child)
                collect(child.body)
                return
            if isinstance(child, DefaultStmt):
                default_stmt = child
                collect(child.body)

        collect(stmt)
        return cases, default_stmt

    def _emit_return(self, stmt: ReturnStmt) -> None:
        assert self._func_sym is not None
        if self._is_void_type(self._func_sym.return_type):
            if stmt.value is not None:
                self._emit_expr(stmt.value, 0)
            self._emit(f"b {self._return_label}")
            return
        if stmt.value is None:
            raise self._error("Non-void function must return a value")
        record_fields = self._record_return_fields(self._func_sym.return_type)
        if record_fields is not None:
            self._emit_record_return(stmt.value, record_fields)
            self._emit(f"b {self._return_label}")
            return
        if self._is_indirect_return_type(self._func_sym.return_type):
            self._emit_indirect_record_return(stmt.value, self._func_sym.return_type)
            self._emit(f"b {self._return_label}")
            return
        value = self._emit_expr(stmt.value, 0)
        return_info = self._scalar_info(self._func_sym.return_type)
        self._coerce_value(value, self._func_sym.return_type, return_info, 0)
        self._emit(f"b {self._return_label}")

    def _emit_record_return(
        self,
        expr: Expr,
        fields: list[tuple[int, Type, _ScalarInfo]],
    ) -> None:
        if isinstance(expr, ConditionalExpr) and self._record_fields_compatible(
            self._record_return_fields(self._expr_type(expr)),
            fields,
        ):
            false_label = self._new_label("record_return_false")
            end_label = self._new_label("record_return_end")
            self._emit_branch_if_zero(expr.condition, false_label)
            self._emit_record_return(expr.then_expr, fields)
            self._emit(f"b {end_label}")
            self._lines.append(f"{false_label}:")
            self._emit_record_return(expr.else_expr, fields)
            self._lines.append(f"{end_label}:")
            return
        if isinstance(expr, CallExpr) and self._record_fields_compatible(
            self._record_return_fields(self._expr_type(expr)),
            fields,
        ):
            self._emit_expr(expr, 0)
            return
        self._emit_address(expr, 11)
        for index, (offset, _, info) in enumerate(fields):
            address_reg = 11
            if offset:
                address_reg = 12
                self._emit_add_byte_offset(address_reg, "x11", offset)
            self._emit_load_from_address(info, index, address_reg)

    def _emit_indirect_record_return(self, expr: Expr, return_type: Type) -> None:
        if self._sret_slot is None:
            raise self._error("AArch64 target missing indirect return slot")
        self._emit_load(self._sret_slot, 11)
        if isinstance(expr, ConditionalExpr):
            false_label = self._new_label("indirect_return_false")
            end_label = self._new_label("indirect_return_end")
            self._emit_branch_if_zero(expr.condition, false_label)
            self._emit_indirect_record_return(expr.then_expr, return_type)
            self._emit(f"b {end_label}")
            self._lines.append(f"{false_label}:")
            self._emit_indirect_record_return(expr.else_expr, return_type)
            self._lines.append(f"{end_label}:")
            return
        if isinstance(expr, CallExpr) and self._is_indirect_return_type(self._expr_type(expr)):
            self._emit_scratch_store_reg("x11", 8)
            self._emit_call(expr, 0, indirect_result_scratch_offset=8)
            return
        if isinstance(expr, CompoundLiteralExpr):
            self._emit_record_compound_initializer_to_address(
                return_type,
                expr.initializer,
                11,
            )
            return
        self._emit_scratch_store_reg("x11", 8)
        self._emit_address(expr, 12)
        self._emit_scratch_load_reg("x11", 8)
        size = self._type_size(return_type)
        if size is None:
            raise self._error(f"AArch64 target cannot size return type {return_type}")
        self._emit_copy_memory(11, 12, size)

    def _emit_decl(self, stmt: DeclStmt) -> None:
        if stmt.name is None or stmt.storage_class == "typedef":
            return
        if stmt.storage_class in {"static", "extern"}:
            return
        if self._is_function_type(self._local_decl_type(stmt)):
            return
        slot = self._require_decl_slot(stmt)
        self._scope_stack[-1][stmt.name] = slot
        if isinstance(stmt.init, StringLiteral) and slot.type_.is_array():
            self._emit_local_char_array_string_initializer(slot, stmt.init)
            return
        if isinstance(stmt.init, InitList):
            if slot.type_.is_array():
                self._emit_local_array_initializer(slot, stmt.init)
                return
            if self._is_record_type(slot.type_):
                self._emit_add_byte_offset(11, "sp", slot.offset)
                self._emit_record_compound_initializer_to_address(slot.type_, stmt.init, 11)
                return
            raise self._error("AArch64 target does not support local initializer list yet")
            return
        if stmt.init is None:
            return
        if not self._types_assignable(slot.type_):
            if isinstance(stmt.init, CallExpr):
                fields = self._record_return_fields(slot.type_)
                if fields is not None:
                    self._emit_expr(stmt.init, 0)
                    self._emit_add_byte_offset(11, "sp", slot.offset)
                    for index, (offset, _, info) in enumerate(fields):
                        address_reg = 11
                        if offset:
                            address_reg = 12
                            self._emit_add_byte_offset(address_reg, "x11", offset)
                        self._emit_store_to_address(info, index, address_reg)
                    return
                if self._is_indirect_return_type(slot.type_):
                    self._emit_call(stmt.init, 0, indirect_result_slot=slot)
                    return
            init_type = self._expr_type(stmt.init)
            slot_size = self._type_size(slot.type_)
            init_size = self._type_size(init_type)
            if slot_size is None or init_size is None or slot_size != init_size:
                raise self._error("AArch64 target cannot initialize aggregate local")
            self._emit_add_byte_offset(11, "sp", slot.offset)
            self._emit_aggregate_expr_to_address(slot.type_, stmt.init, 11)
            return
        value = self._emit_expr(stmt.init, 0)
        self._coerce_value(value, slot.type_, slot.info, 0)
        self._emit_store(slot, 0)

    def _emit_local_array_initializer(self, slot: _Slot, init: InitList) -> None:
        element_type = slot.type_.element_type()
        if element_type is None:
            raise self._error("AArch64 target only supports local array initializers yet")
        element_size = self._type_size(element_type)
        if element_size is None:
            raise self._error(f"AArch64 target cannot size type {element_type}")
        length = slot.type_.declarator_ops[0][1]
        if not isinstance(length, int) or length < 0:
            raise self._error("AArch64 target requires known local array initializer length")
        initialized = 0
        for index, item in enumerate(init.items):
            if item.designators:
                raise self._error("AArch64 target does not support designators in local arrays yet")
            if isinstance(item.initializer, InitList):
                if self._is_record_type(element_type):
                    self._emit_local_array_element_address(slot, index, element_size, 11)
                    self._emit_record_compound_initializer_to_address(
                        element_type,
                        item.initializer,
                        11,
                    )
                else:
                    if len(item.initializer.items) != 1 or item.initializer.items[0].designators:
                        raise self._error("AArch64 target cannot initialize array element")
                    element_info = self._scalar_info(element_type)
                    inner = item.initializer.items[0].initializer
                    assert isinstance(inner, Expr)
                    value = self._emit_expr(inner, 0)
                    self._coerce_value(value, element_type, element_info, 0)
                    self._emit_local_array_element_address(slot, index, element_size, 11)
                    self._emit_store_to_address(element_info, 0, 11)
            elif not self._types_assignable(element_type):
                self._emit_local_array_element_address(slot, index, element_size, 11)
                if self._is_zero_initializer(item.initializer):
                    self._emit_zero_memory(11, element_size)
                else:
                    self._emit_scratch_store_reg("x11", 8)
                    self._emit_address(item.initializer, 12)
                    self._emit_scratch_load_reg("x11", 8)
                    self._emit_copy_memory(11, 12, element_size)
            else:
                element_info = self._scalar_info(element_type)
                value = self._emit_expr(item.initializer, 0)
                self._coerce_value(value, element_type, element_info, 0)
                self._emit_local_array_element_address(slot, index, element_size, 11)
                self._emit_store_to_address(element_info, 0, 11)
            initialized = index + 1
        if initialized < length:
            for index in range(initialized, length):
                self._emit_local_array_element_address(slot, index, element_size, 11)
                if self._types_assignable(element_type):
                    element_info = self._scalar_info(element_type)
                    self._emit_load_immediate(self._reg(0, element_info), 0, element_info.bits)
                    self._emit_store_to_address(element_info, 0, 11)
                else:
                    self._emit_zero_memory(11, element_size)

    def _emit_local_char_array_string_initializer(
        self,
        slot: _Slot,
        init: StringLiteral,
    ) -> None:
        length = slot.type_.declarator_ops[0][1]
        if not isinstance(length, int) or length < 0:
            raise self._error("AArch64 target requires known local string initializer length")
        data = self._string_literal_bytes(init)
        for index in range(length):
            value = data[index] if index < len(data) else 0
            self._emit_add_byte_offset(11, "sp", slot.offset + index)
            self._emit_load_immediate("w0", value, 32)
            self._emit("strb w0, [x11]")

    def _emit_local_array_element_address(
        self,
        slot: _Slot,
        index: int,
        element_size: int,
        target_reg: int,
    ) -> None:
        offset = slot.offset + index * element_size
        self._emit_add_byte_offset(target_reg, "sp", offset)

    def _local_decl_type(self, stmt: DeclStmt) -> Type:
        return self._resolve_type_spec(stmt.type_spec)

    def _complete_local_array_bound_type(self, stmt: DeclStmt, type_: Type) -> Type:
        if not type_.is_array():
            return type_
        kind, length = type_.declarator_ops[0]
        if kind != "arr" or not isinstance(length, int) or length >= 0:
            return type_
        if not stmt.type_spec.declarator_ops:
            return type_
        spec_kind, spec_value = stmt.type_spec.declarator_ops[0]
        if spec_kind != "arr" or not isinstance(spec_value, ArrayDecl):
            return type_
        resolved_length: int | None
        if isinstance(spec_value.length, int):
            resolved_length = spec_value.length
        elif isinstance(spec_value.length, Expr):
            evaluated_length = self._eval_int_constant(spec_value.length)
            resolved_length = evaluated_length
        else:
            resolved_length = None
        if resolved_length is None or resolved_length < 0:
            return type_
        return Type(
            type_.name,
            declarator_ops=(("arr", resolved_length),) + type_.declarator_ops[1:],
            qualifiers=type_.qualifiers,
        )

    def _emit_expr(self, expr: Expr, target: int) -> _Value:
        if isinstance(expr, IntLiteral):
            value = self._parse_int_value(expr.value)
            type_ = self._expr_type(expr)
            info = self._scalar_info(type_)
            self._emit_load_immediate(self._reg(target, info), value, info.bits)
            return _Value(type_, info, target)
        if isinstance(expr, CharLiteral):
            value = self._char_value(expr.value)
            type_ = self._expr_type(expr)
            info = self._scalar_info(type_)
            self._emit_load_immediate(self._reg(target, info), value, info.bits)
            return _Value(type_, info, target)
        if isinstance(expr, FloatLiteral):
            return self._emit_float_literal(expr, target)
        if isinstance(expr, StringLiteral):
            return self._emit_string_literal(expr, target)
        if isinstance(expr, SizeofExpr):
            return self._emit_sizeof(expr, target)
        if isinstance(expr, AlignofExpr):
            return self._emit_alignof(expr, target)
        if isinstance(expr, BuiltinOffsetofExpr):
            return self._emit_offsetof(expr, target)
        if isinstance(expr, BuiltinVaArgExpr):
            return self._emit_va_arg(expr, target)
        if isinstance(expr, Identifier):
            return self._emit_identifier(expr, target)
        if isinstance(expr, CallExpr):
            return self._emit_call(expr, target)
        if isinstance(expr, SubscriptExpr):
            return self._emit_subscript(expr, target)
        if isinstance(expr, MemberExpr):
            return self._emit_member(expr, target)
        if isinstance(expr, UnaryExpr):
            return self._emit_unary(expr, target)
        if isinstance(expr, UpdateExpr):
            return self._emit_update(expr, target)
        if isinstance(expr, BinaryExpr):
            return self._emit_binary(expr, target)
        if isinstance(expr, AssignExpr):
            return self._emit_assign(expr, target)
        if isinstance(expr, CastExpr):
            return self._emit_cast(expr, target)
        if isinstance(expr, CompoundLiteralExpr):
            return self._emit_compound_literal(expr, target)
        if isinstance(expr, CommaExpr):
            self._emit_expr(expr.left, target)
            return self._emit_expr(expr.right, target)
        if isinstance(expr, ConditionalExpr):
            return self._emit_conditional(expr, target)
        raise self._error(f"AArch64 target does not support {type(expr).__name__} yet")

    def _call_param_type(self, expr: CallExpr, index: int) -> Type | None:
        direct_name = (
            expr.callee.name
            if (
                isinstance(expr.callee, Identifier)
                and expr.callee.name in self._sema.function_signatures
            )
            else None
        )
        if direct_name is not None:
            signature = self._sema.function_signatures.get(direct_name)
            if (
                signature is not None
                and signature.params is not None
                and index < len(signature.params)
            ):
                return signature.params[index]
            return None
        callable_signature = self._expr_type(expr.callee).callable_signature()
        if callable_signature is None:
            return None
        _, params = callable_signature
        param_types, _ = params
        if param_types is not None and index < len(param_types):
            return param_types[index]
        return None

    def _call_variadic_fixed_count(self, expr: CallExpr) -> int | None:
        direct_name = (
            expr.callee.name
            if (
                isinstance(expr.callee, Identifier)
                and expr.callee.name in self._sema.function_signatures
            )
            else None
        )
        if direct_name is not None:
            signature = self._sema.function_signatures.get(direct_name)
            if signature is not None and signature.is_variadic and signature.params is not None:
                return len(signature.params)
            return None
        callable_signature = self._expr_type(expr.callee).callable_signature()
        if callable_signature is None:
            return None
        _, params = callable_signature
        param_types, is_variadic = params
        if is_variadic and param_types is not None:
            return len(param_types)
        return None

    def _emit_call(
        self,
        expr: CallExpr,
        target: int,
        indirect_result_slot: _Slot | None = None,
        indirect_result_scratch_offset: int | None = None,
    ) -> _Value:
        direct_name = (
            expr.callee.name
            if (
                isinstance(expr.callee, Identifier)
                and expr.callee.name in self._sema.function_signatures
            )
            else None
        )
        if direct_name == "__builtin_va_start":
            return self._emit_va_start(expr, target)
        if direct_name == "__builtin_va_end":
            return _Value(VOID, _ScalarInfo(4, 4, False), target)
        if direct_name == "__builtin_va_copy":
            return self._emit_va_copy(expr, target)
        if direct_name is not None:
            builtin_value = self._emit_compiler_builtin(direct_name, expr, target)
            if builtin_value is not None:
                return builtin_value
            atomic_value = self._emit_atomic_builtin(direct_name, expr, target)
            if atomic_value is not None:
                return atomic_value
        signature = (
            self._sema.function_signatures.get(direct_name) if direct_name is not None else None
        )
        indirect_params: tuple[Type, ...] | None = None
        indirect_variadic = False
        if direct_name is None:
            callable_signature = self._expr_type(expr.callee).callable_signature()
            if callable_signature is None:
                raise self._error("AArch64 target cannot call non-function pointer")
            _, params = callable_signature
            indirect_params, indirect_variadic = params
        result_type = self._expr_type(expr)
        if (
            indirect_result_slot is None
            and indirect_result_scratch_offset is None
            and self._is_indirect_return_type(result_type)
        ):
            indirect_result_slot = self._indirect_call_slots.get(id(expr))
            if indirect_result_slot is None:
                raise self._error("AArch64 target missing indirect call result slot")
        stack_arg_count = max(0, len(expr.args) - 8)
        stack_arg_size = self._call_outgoing_stack_size(len(expr.args))
        values: list[_Value | _VariadicAggregate] = []
        variadic_fixed_count = self._call_variadic_fixed_count(expr)
        int_arg_reg = 0
        fp_arg_reg = 0
        for index, arg in enumerate(expr.args):
            saved_int_arg_regs = min(int_arg_reg, 8)
            saved_fp_arg_regs = min(fp_arg_reg, 8)
            preserve_args = saved_int_arg_regs > 0 or saved_fp_arg_regs > 0
            param_type = None
            if signature is not None and signature.params is not None:
                param_types = signature.params
                if index < len(param_types):
                    param_type = param_types[index]
            elif indirect_params is not None and index < len(indirect_params):
                param_type = indirect_params[index]
            arg_type = self._expr_type(arg)
            if (
                variadic_fixed_count is not None
                and index >= variadic_fixed_count
                and self._is_record_type(arg_type)
            ):
                arg_slot = self._variadic_arg_slots.get(id(arg))
                if arg_slot is None:
                    raise self._error("AArch64 target missing variadic aggregate argument slot")
                spill = self._spill_call_arg_registers(
                    saved_int_arg_regs,
                    saved_fp_arg_regs,
                    preserve_args,
                )
                self._emit_add_byte_offset(11, "sp", arg_slot.offset)
                self._emit_aggregate_expr_to_address(arg_type, arg, 11)
                self._restore_call_arg_registers(spill)
                values.append(_VariadicAggregate(arg_type, arg_slot))
                continue
            if param_type is not None and self._is_indirect_argument_type(param_type):
                arg_slot = self._byval_arg_slots.get(id(arg))
                if arg_slot is None:
                    raise self._error("AArch64 target missing by-value argument slot")
                size = self._type_size(param_type)
                if size is None:
                    raise self._error(f"AArch64 target cannot size argument {param_type}")
                spill = self._spill_call_arg_registers(
                    saved_int_arg_regs,
                    saved_fp_arg_regs,
                    preserve_args,
                )
                self._emit_address(arg, 11)
                self._emit_add_byte_offset(12, "sp", arg_slot.offset)
                self._emit_copy_memory(12, 11, size)
                self._restore_call_arg_registers(spill)
                arg_reg = int_arg_reg if int_arg_reg < 8 else 8
                stack_index = int_arg_reg - 8 if int_arg_reg >= 8 else None
                int_arg_reg += 1
                self._emit_add_byte_offset(arg_reg, "sp", arg_slot.offset)
                value = _Value(param_type.pointer_to(), _ScalarInfo(8, 8, False), arg_reg)
                values.append(value)
                if stack_index is not None:
                    self._emit_outgoing_stack_arg(value, arg_reg, stack_index)
                continue
            hfa_offsets = self._hfa_double_offsets(param_type) if param_type is not None else None
            if hfa_offsets is not None:
                first_reg = fp_arg_reg
                fp_arg_reg += len(hfa_offsets)
                spill = self._spill_call_arg_registers(
                    saved_int_arg_regs,
                    saved_fp_arg_regs,
                    preserve_args,
                )
                self._emit_hfa_double_argument(arg, first_reg, hfa_offsets)
                self._restore_call_arg_registers(spill)
                assert param_type is not None
                values.append(_Value(param_type, self._slot_info(param_type), first_reg))
                continue
            record_fields = (
                self._record_return_fields(param_type) if param_type is not None else None
            )
            if record_fields is not None:
                first_reg = int_arg_reg
                int_arg_reg += len(record_fields)
                spill = self._spill_call_arg_registers(
                    saved_int_arg_regs,
                    saved_fp_arg_regs,
                    preserve_args,
                )
                self._emit_record_argument(arg, first_reg, record_fields)
                self._restore_call_arg_registers(spill)
                assert param_type is not None
                values.append(_Value(param_type, self._slot_info(param_type), first_reg))
                continue
            param_info = self._scalar_info(param_type) if param_type is not None else None
            if param_info is not None and param_info.is_float:
                arg_reg = fp_arg_reg
                fp_arg_reg += 1
                stack_index = None
            else:
                arg_reg = int_arg_reg if int_arg_reg < 8 else 8
                stack_index = int_arg_reg - 8 if int_arg_reg >= 8 else None
                int_arg_reg += 1
            spill = self._spill_call_arg_registers(
                saved_int_arg_regs,
                saved_fp_arg_regs,
                preserve_args,
            )
            value = self._emit_expr(arg, arg_reg)
            if param_type is not None and param_info is not None:
                self._coerce_value(value, param_type, param_info, arg_reg)
                value = _Value(param_type, param_info, arg_reg)
            self._restore_call_arg_registers(spill)
            values.append(value)
            if stack_index is not None:
                self._emit_outgoing_stack_arg(value, arg_reg, stack_index)
        if direct_name is None:
            spill = self._spill_call_arg_registers(
                min(int_arg_reg, 8),
                min(fp_arg_reg, 8),
                int_arg_reg > 0 or fp_arg_reg > 0,
            )
            self._emit_callee_address(expr.callee, 16)
            self._restore_call_arg_registers(spill)
        if stack_arg_size:
            self._emit(f"sub sp, sp, #{stack_arg_size}")
            for stack_index in range(stack_arg_count):
                frame_offset = stack_arg_size + self._outgoing_arg_offset + stack_index * 8
                self._emit_stack_load_reg("x8", frame_offset)
                self._emit_stack_store_reg("x8", stack_index * 8)
        variadic_stack_size = 0
        if signature is not None and signature.is_variadic and signature.params is not None:
            variadic_stack_size = self._emit_darwin_variadic_stack_args(
                values, len(signature.params), stack_arg_size
            )
        elif indirect_variadic and indirect_params is not None:
            variadic_stack_size = self._emit_darwin_variadic_stack_args(
                values, len(indirect_params), stack_arg_size
            )
        if indirect_result_slot is not None:
            result_offset = indirect_result_slot.offset + stack_arg_size + variadic_stack_size
            self._emit_add_byte_offset(8, "sp", result_offset)
        if indirect_result_scratch_offset is not None:
            self._emit_scratch_load_reg(
                "x8",
                indirect_result_scratch_offset,
                stack_arg_size + variadic_stack_size,
            )
        if direct_name is None:
            self._emit("blr x16")
        else:
            self._emit(f"bl {self._symbol_name(direct_name)}")
        if variadic_stack_size:
            self._emit(f"add sp, sp, #{variadic_stack_size}")
        if stack_arg_size:
            self._emit(f"add sp, sp, #{stack_arg_size}")
        if self._is_void_type(result_type):
            return _Value(result_type, _ScalarInfo(4, 4, False), 0)
        if self._is_indirect_return_type(result_type):
            if indirect_result_slot is None and indirect_result_scratch_offset is None:
                raise self._error("AArch64 target cannot materialize indirect record call result")
            return _Value(result_type, self._slot_info(result_type), target)
        if self._record_return_fields(result_type) is not None:
            return _Value(result_type, self._slot_info(result_type), target)
        result_info = self._scalar_info(result_type)
        if target != 0:
            instruction = "fmov" if result_info.is_float else "mov"
            self._emit(
                f"{instruction} {self._reg(target, result_info)}, {self._reg(0, result_info)}"
            )
        return _Value(result_type, result_info, target)

    def _emit_callee_address(self, expr: Expr, target: int) -> _Value:
        if isinstance(expr, UnaryExpr) and expr.op == "*":
            return self._emit_expr(expr.operand, target)
        return self._emit_expr(expr, target)

    def _emit_hfa_double_argument(
        self,
        expr: Expr,
        first_reg: int,
        offsets: list[int],
    ) -> None:
        if (
            isinstance(expr, CallExpr)
            and self._hfa_double_offsets(self._expr_type(expr)) is not None
        ):
            self._emit_expr(expr, 0)
            for index in reversed(range(len(offsets))):
                if first_reg + index != index:
                    self._emit(f"fmov d{first_reg + index}, d{index}")
            return
        self._emit_address(expr, 11)
        for index, offset in enumerate(offsets):
            self._emit(f"ldr d{first_reg + index}, [x11, #{offset}]")

    def _emit_record_argument(
        self,
        expr: Expr,
        first_reg: int,
        fields: list[tuple[int, Type, _ScalarInfo]],
    ) -> None:
        if isinstance(expr, ConditionalExpr) and self._record_fields_compatible(
            self._record_return_fields(self._expr_type(expr)),
            fields,
        ):
            false_label = self._new_label("record_arg_false")
            end_label = self._new_label("record_arg_end")
            self._emit_branch_if_zero(expr.condition, false_label)
            self._emit_record_argument(expr.then_expr, first_reg, fields)
            self._emit(f"b {end_label}")
            self._lines.append(f"{false_label}:")
            self._emit_record_argument(expr.else_expr, first_reg, fields)
            self._lines.append(f"{end_label}:")
            return
        if isinstance(expr, CallExpr) and self._record_fields_compatible(
            self._record_return_fields(self._expr_type(expr)),
            fields,
        ):
            self._emit_expr(expr, 0)
            for index in reversed(range(len(fields))):
                _, _, info = fields[index]
                source_reg = index
                target_reg = first_reg + index
                if target_reg != source_reg:
                    self._emit(f"mov {self._reg(target_reg, info)}, {self._reg(source_reg, info)}")
            return
        self._emit_address(expr, 11)
        for index, (offset, _, info) in enumerate(fields):
            address_reg = 11
            if offset:
                address_reg = 12
                self._emit_add_byte_offset(address_reg, "x11", offset)
            self._emit_load_from_address(info, first_reg + index, address_reg)

    def _spill_call_arg_registers(
        self,
        int_count: int,
        fp_count: int,
        enabled: bool,
    ) -> tuple[int, int, int] | None:
        if not enabled or (int_count == 0 and fp_count == 0):
            return None
        base = (
            self._call_arg_spill_offset() + self._call_arg_spill_depth * self._CALL_ARG_SPILL_SIZE
        )
        for reg in range(int_count):
            self._emit_scratch_store_reg(f"x{reg}", base + reg * 8)
        fp_base = base + self._CALL_ARG_INT_SPILL_SIZE
        for reg in range(fp_count):
            self._emit_scratch_store_reg(f"d{reg}", fp_base + reg * 8)
        self._call_arg_spill_depth += 1
        return (base, int_count, fp_count)

    def _restore_call_arg_registers(self, spill: tuple[int, int, int] | None) -> None:
        if spill is None:
            return
        base, int_count, fp_count = spill
        self._call_arg_spill_depth -= 1
        for reg in range(int_count):
            self._emit_scratch_load_reg(f"x{reg}", base + reg * 8)
        fp_base = base + self._CALL_ARG_INT_SPILL_SIZE
        for reg in range(fp_count):
            self._emit_scratch_load_reg(f"d{reg}", fp_base + reg * 8)

    def _call_arg_spill_offset(self) -> int:
        return self._BASE_SCRATCH_SIZE + self._expr_spill_reserved_depth * self._EXPR_SPILL_SIZE

    def _emit_va_start(self, expr: CallExpr, target: int) -> _Value:
        if len(expr.args) != 2:
            raise self._error("AArch64 target requires two arguments for va_start")
        self._emit_address(expr.args[0], 11)
        self._emit_add_byte_offset(10, "sp", self._stack_size)
        self._emit("str x10, [x11]")
        return _Value(VOID, _ScalarInfo(4, 4, False), target)

    def _emit_va_copy(self, expr: CallExpr, target: int) -> _Value:
        if len(expr.args) != 2:
            raise self._error("AArch64 target requires two arguments for va_copy")
        self._emit_address(expr.args[0], 11)
        self._emit_address(expr.args[1], 12)
        self._emit("ldr x10, [x12]")
        self._emit("str x10, [x11]")
        return _Value(VOID, _ScalarInfo(4, 4, False), target)

    def _emit_va_arg(self, expr: BuiltinVaArgExpr, target: int) -> _Value:
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        self._emit_address(expr.ap, 11)
        self._emit("ldr x12, [x11]")
        self._emit_load_from_address(result_info, target, 12)
        self._emit("add x12, x12, #8")
        self._emit("str x12, [x11]")
        return _Value(result_type, result_info, target)

    def _emit_compiler_builtin(
        self,
        callee_name: str,
        expr: CallExpr,
        target: int,
    ) -> _Value | None:
        args = expr.args
        result_type = self._expr_type(expr)
        if callee_name == "assert":
            return _Value(VOID, _ScalarInfo(4, 4, False), target)
        if callee_name == "__builtin_unreachable":
            self._emit("brk #1")
            return _Value(VOID, _ScalarInfo(4, 4, False), target)
        if callee_name == "__builtin_expect":
            if len(args) > 1 and self._expr_has_side_effect(args[1]):
                self._emit_expr(args[1], 10)
            if not args:
                info = self._scalar_info(result_type)
                self._emit_load_immediate(self._reg(target, info), 0, info.bits)
                return _Value(result_type, info, target)
            value = self._emit_expr(args[0], target)
            info = self._scalar_info(result_type)
            self._coerce_value(value, result_type, info, target)
            return _Value(result_type, info, target)
        if callee_name == "__builtin_constant_p":
            info = self._scalar_info(result_type)
            self._emit_load_immediate(self._reg(target, info), 0, info.bits)
            return _Value(result_type, info, target)
        if callee_name == "__builtin_assume_aligned":
            if not args:
                info = self._scalar_info(result_type)
                self._emit_load_immediate(self._reg(target, info), 0, info.bits)
                return _Value(result_type, info, target)
            value = self._emit_expr(args[0], target)
            info = self._scalar_info(result_type)
            self._coerce_value(value, result_type, info, target)
            return _Value(result_type, info, target)
        if callee_name in {"__builtin_alloca", "__builtin_alloca_with_align"}:
            if args:
                value = self._emit_expr(args[0], 0)
                self._coerce_value(value, Type("unsigned long"), _ScalarInfo(8, 8, False), 0)
            else:
                self._emit_load_immediate("x0", 0, 64)
            self._emit("bl _malloc")
            if target != 0:
                self._emit(f"mov x{target}, x0")
            return _Value(result_type, _ScalarInfo(8, 8, False), target)
        if callee_name == "__builtin_flt_rounds":
            info = self._scalar_info(result_type)
            self._emit_load_immediate(self._reg(target, info), 1, info.bits)
            return _Value(result_type, info, target)
        if callee_name in {"__builtin_frame_address", "__builtin_return_address"}:
            info = self._scalar_info(result_type)
            source = "x29" if callee_name == "__builtin_frame_address" else "x30"
            self._emit(f"mov x{target}, {source}")
            return _Value(result_type, info, target)
        if callee_name in {
            "__builtin_inf",
            "__builtin_inff",
            "__builtin_infl",
            "__builtin_huge_val",
            "__builtin_huge_valf",
            "__builtin_huge_vall",
        }:
            return self._emit_float_constant(result_type, float("inf"), target)
        if callee_name in {"__builtin_nan", "__builtin_nanf", "__builtin_nanl"}:
            return self._emit_float_constant(result_type, float("nan"), target)
        if callee_name in {"__builtin_isinf", "__builtin_isnan", "__builtin_isfinite"}:
            return self._emit_float_class_builtin(callee_name, expr, target)
        if callee_name in {"__builtin_fabs", "__builtin_fabsf", "__builtin_fabsl"}:
            return self._emit_float_abs_builtin(expr, target)
        bit_value = self._emit_integer_bit_builtin(callee_name, expr, target)
        if bit_value is not None:
            return bit_value
        return None

    def _emit_float_constant(self, type_: Type, value: float, target: int) -> _Value:
        info = self._scalar_info(type_)
        bits = self._float_to_bits(value, info.size)
        label = self._float_literals.get((bits, info.size))
        if label is None:
            label = f"L_.float{len(self._float_literals)}"
            self._float_literals[(bits, info.size)] = label
        self._emit(f"adrp x11, {label}@PAGE")
        self._emit(f"ldr {self._reg(target, info)}, [x11, {label}@PAGEOFF]")
        return _Value(type_, info, target)

    def _emit_float_class_builtin(
        self,
        callee_name: str,
        expr: CallExpr,
        target: int,
    ) -> _Value:
        if not expr.args:
            result_type = self._expr_type(expr)
            result_info = self._scalar_info(result_type)
            self._emit_load_immediate(self._reg(target, result_info), 0, result_info.bits)
            return _Value(result_type, result_info, target)
        value = self._emit_expr(expr.args[0], target)
        float_type = value.type_ if value.info.is_float else DOUBLE
        float_info = self._scalar_info(float_type)
        if not value.info.is_float or value.info.size != float_info.size:
            self._coerce_value(value, float_type, float_info, target)
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        if callee_name == "__builtin_isnan":
            self._emit(f"fcmp {self._reg(target, float_info)}, {self._reg(target, float_info)}")
            self._emit(f"cset {self._reg(target, result_info)}, vs")
            return _Value(result_type, result_info, target)
        self._emit(f"fabs {self._reg(target, float_info)}, {self._reg(target, float_info)}")
        self._emit_float_constant(float_type, float("inf"), 10)
        self._emit(f"fcmp {self._reg(target, float_info)}, {self._reg(10, float_info)}")
        condition = "eq" if callee_name == "__builtin_isinf" else "lt"
        self._emit(f"cset {self._reg(target, result_info)}, {condition}")
        return _Value(result_type, result_info, target)

    def _emit_float_abs_builtin(self, expr: CallExpr, target: int) -> _Value:
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        if not expr.args:
            self._emit_float_constant(result_type, 0.0, target)
            return _Value(result_type, result_info, target)
        value = self._emit_expr(expr.args[0], target)
        self._coerce_value(value, result_type, result_info, target)
        self._emit(f"fabs {self._reg(target, result_info)}, {self._reg(target, result_info)}")
        return _Value(result_type, result_info, target)

    def _emit_integer_bit_builtin(
        self,
        callee_name: str,
        expr: CallExpr,
        target: int,
    ) -> _Value | None:
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
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        if not expr.args:
            self._emit_load_immediate(self._reg(target, result_info), 0, result_info.bits)
            return _Value(result_type, result_info, target)
        width = self._bit_builtin_width(callee_name)
        value = self._emit_expr(expr.args[0], target)
        op_info = _ScalarInfo(8, 8, False) if width == 64 else _ScalarInfo(4, 4, False)
        self._coerce_value(
            value, Type("unsigned long") if width == 64 else Type("unsigned int"), op_info, target
        )
        if "bswap" in callee_name:
            if width == 64:
                self._emit(f"rev x{target}, x{target}")
            else:
                self._emit(f"rev w{target}, w{target}")
                if width == 16:
                    self._emit(f"lsr w{target}, w{target}, #16")
            self._coerce_value(
                _Value(result_type, op_info, target), result_type, result_info, target
            )
            return _Value(result_type, result_info, target)
        if "clz" in callee_name:
            self._emit(f"clz {self._reg(target, op_info)}, {self._reg(target, op_info)}")
            self._coerce_value(
                _Value(result_type, op_info, target), result_type, result_info, target
            )
            return _Value(result_type, result_info, target)
        if "ctz" in callee_name:
            self._emit(f"rbit {self._reg(target, op_info)}, {self._reg(target, op_info)}")
            self._emit(f"clz {self._reg(target, op_info)}, {self._reg(target, op_info)}")
            self._coerce_value(
                _Value(result_type, op_info, target), result_type, result_info, target
            )
            return _Value(result_type, result_info, target)
        if "ffs" in callee_name:
            self._emit_ffs_builtin(target, op_info)
            self._coerce_value(
                _Value(result_type, op_info, target), result_type, result_info, target
            )
            return _Value(result_type, result_info, target)
        if "popcount" in callee_name:
            self._emit_popcount_builtin(target, op_info)
            self._coerce_value(
                _Value(result_type, op_info, target), result_type, result_info, target
            )
            return _Value(result_type, result_info, target)
        return None

    @staticmethod
    def _bit_builtin_width(callee_name: str) -> int:
        if callee_name.endswith("ll") or callee_name.endswith("64"):
            return 64
        if callee_name.endswith("l"):
            return 64
        if callee_name.endswith("16"):
            return 16
        return 32

    def _emit_ffs_builtin(self, target: int, info: _ScalarInfo) -> None:
        zero_label = self._new_label("L_ffs_zero")
        end_label = self._new_label("L_ffs_end")
        reg = self._reg(target, info)
        self._emit(f"cbz {reg}, {zero_label}")
        self._emit(f"rbit {reg}, {reg}")
        self._emit(f"clz {reg}, {reg}")
        self._emit(f"add {reg}, {reg}, #1")
        self._emit(f"b {end_label}")
        self._lines.append(f"{zero_label}:")
        self._emit_load_immediate(reg, 0, info.bits)
        self._lines.append(f"{end_label}:")

    def _emit_popcount_builtin(self, target: int, info: _ScalarInfo) -> None:
        loop_label = self._new_label("L_popcount_loop")
        end_label = self._new_label("L_popcount_end")
        work = self._available_reg({target}, (11, 12, 13))
        scratch = self._available_reg({target, work}, (11, 12, 13))
        work_reg = self._reg(work, info)
        scratch_reg = self._reg(scratch, info)
        target_reg = self._reg(target, info)
        self._emit(f"mov {work_reg}, {target_reg}")
        self._emit_load_immediate(target_reg, 0, info.bits)
        self._lines.append(f"{loop_label}:")
        self._emit(f"cbz {work_reg}, {end_label}")
        self._emit(f"sub {scratch_reg}, {work_reg}, #1")
        self._emit(f"and {work_reg}, {work_reg}, {scratch_reg}")
        self._emit(f"add {target_reg}, {target_reg}, #1")
        self._emit(f"b {loop_label}")
        self._lines.append(f"{end_label}:")

    def _atomic_pointee(self, expr: Expr) -> tuple[Type, _ScalarInfo]:
        pointer_type = self._expr_type(expr)
        pointee = pointer_type.pointee()
        if pointee is None or unqualified_type(pointee) == VOID:
            pointee = INT
        info = self._scalar_info(pointee)
        if info.is_float or info.size not in {1, 2, 4, 8}:
            raise self._error(f"AArch64 target does not support atomic type {pointee}")
        return pointee, info

    def _emit_atomic_load_from_address(
        self,
        info: _ScalarInfo,
        target: int,
        address_reg: int,
    ) -> None:
        if info.size == 1:
            self._emit(f"ldarb w{target}, [x{address_reg}]")
            if info.signed:
                self._emit(f"sxtb w{target}, w{target}")
            return
        if info.size == 2:
            self._emit(f"ldarh w{target}, [x{address_reg}]")
            if info.signed:
                self._emit(f"sxth w{target}, w{target}")
            return
        self._emit(f"ldar {self._reg(target, info)}, [x{address_reg}]")

    def _emit_atomic_store_to_address(
        self,
        info: _ScalarInfo,
        source: int,
        address_reg: int,
    ) -> None:
        if info.size == 1:
            self._emit(f"stlrb w{source}, [x{address_reg}]")
            return
        if info.size == 2:
            self._emit(f"stlrh w{source}, [x{address_reg}]")
            return
        self._emit(f"stlr {self._reg(source, info)}, [x{address_reg}]")

    def _emit_atomic_exclusive_load(
        self,
        info: _ScalarInfo,
        target: int,
        address_reg: int,
    ) -> None:
        if info.size == 1:
            self._emit(f"ldaxrb w{target}, [x{address_reg}]")
            if info.signed:
                self._emit(f"sxtb w{target}, w{target}")
            return
        if info.size == 2:
            self._emit(f"ldaxrh w{target}, [x{address_reg}]")
            if info.signed:
                self._emit(f"sxth w{target}, w{target}")
            return
        self._emit(f"ldaxr {self._reg(target, info)}, [x{address_reg}]")

    def _emit_atomic_exclusive_store(
        self,
        info: _ScalarInfo,
        status_reg: int,
        source: int,
        address_reg: int,
    ) -> None:
        if info.size == 1:
            self._emit(f"stlxrb w{status_reg}, w{source}, [x{address_reg}]")
            return
        if info.size == 2:
            self._emit(f"stlxrh w{status_reg}, w{source}, [x{address_reg}]")
            return
        self._emit(f"stlxr w{status_reg}, {self._reg(source, info)}, [x{address_reg}]")

    def _emit_atomic_compute(
        self,
        op: str,
        info: _ScalarInfo,
        target: int,
        old_reg: int,
        value_reg: int,
    ) -> None:
        target_name = self._reg(target, info)
        old_name = self._reg(old_reg, info)
        value_name = self._reg(value_reg, info)
        if op == "xchg":
            self._emit(f"mov {target_name}, {value_name}")
        elif op == "add":
            self._emit(f"add {target_name}, {old_name}, {value_name}")
        elif op == "sub":
            self._emit(f"sub {target_name}, {old_name}, {value_name}")
        elif op == "and":
            self._emit(f"and {target_name}, {old_name}, {value_name}")
        elif op == "or":
            self._emit(f"orr {target_name}, {old_name}, {value_name}")
        elif op == "xor":
            self._emit(f"eor {target_name}, {old_name}, {value_name}")
        elif op == "nand":
            self._emit(f"and {target_name}, {old_name}, {value_name}")
            self._emit(f"mvn {target_name}, {target_name}")
        else:
            raise self._error(f"AArch64 target does not support atomic op {op}")

    def _emit_atomic_rmw(
        self,
        op: str,
        type_: Type,
        info: _ScalarInfo,
        target: int,
        value_reg: int,
        *,
        return_new: bool,
    ) -> _Value:
        self._coerce_value(_Value(type_, info, value_reg), type_, info, value_reg)
        new_reg = self._available_reg({target, value_reg, 11}, (9, 10, 12, 13))
        status_reg = self._available_reg({target, value_reg, 11, new_reg}, (12, 13, 9, 10))
        loop_label = self._new_label("atomic_rmw")
        self._lines.append(f"{loop_label}:")
        self._emit_atomic_exclusive_load(info, target, 11)
        self._emit_atomic_compute(op, info, new_reg, target, value_reg)
        self._emit_atomic_exclusive_store(info, status_reg, new_reg, 11)
        self._emit(f"cbnz w{status_reg}, {loop_label}")
        if return_new and new_reg != target:
            self._emit(f"mov {self._reg(target, info)}, {self._reg(new_reg, info)}")
        return _Value(type_, info, target)

    def _emit_atomic_compare_exchange(
        self,
        type_: Type,
        info: _ScalarInfo,
        target: int,
        desired_reg: int,
    ) -> _Value:
        self._coerce_value(_Value(type_, info, desired_reg), type_, info, desired_reg)
        expected_reg = self._available_reg({target, desired_reg, 11, 12}, (9, 10, 13))
        status_reg = self._available_reg(
            {target, desired_reg, 11, 12, expected_reg},
            (13, 10, 9),
        )
        self._emit_load_from_address(info, expected_reg, 12)
        loop_label = self._new_label("atomic_cmpxchg")
        fail_label = self._new_label("atomic_cmpxchg_fail")
        done_label = self._new_label("atomic_cmpxchg_done")
        self._lines.append(f"{loop_label}:")
        self._emit_atomic_exclusive_load(info, target, 11)
        self._emit(f"cmp {self._reg(target, info)}, {self._reg(expected_reg, info)}")
        self._emit(f"b.ne {fail_label}")
        self._emit_atomic_exclusive_store(info, status_reg, desired_reg, 11)
        self._emit(f"cbnz w{status_reg}, {loop_label}")
        self._emit("mov w0, #1" if target == 0 else f"mov w{target}, #1")
        self._emit(f"b {done_label}")
        self._lines.append(f"{fail_label}:")
        self._emit("clrex")
        self._emit_store_to_address(info, target, 12)
        self._emit("mov w0, #0" if target == 0 else f"mov w{target}, #0")
        self._lines.append(f"{done_label}:")
        return _Value(INT, self._scalar_info(INT), target)

    def _emit_sync_compare_exchange(
        self,
        type_: Type,
        info: _ScalarInfo,
        target: int,
        expected_reg: int,
        desired_reg: int,
        *,
        bool_result: bool,
    ) -> _Value:
        status_reg = self._available_reg(
            {target, expected_reg, desired_reg, 11},
            (12, 13, 9, 10),
        )
        loop_label = self._new_label("sync_cmpxchg")
        fail_label = self._new_label("sync_cmpxchg_fail")
        done_label = self._new_label("sync_cmpxchg_done")
        self._lines.append(f"{loop_label}:")
        self._emit_atomic_exclusive_load(info, target, 11)
        self._emit(f"cmp {self._reg(target, info)}, {self._reg(expected_reg, info)}")
        self._emit(f"b.ne {fail_label}")
        self._emit_atomic_exclusive_store(info, status_reg, desired_reg, 11)
        self._emit(f"cbnz w{status_reg}, {loop_label}")
        if bool_result:
            self._emit(f"mov w{target}, #1")
        self._emit(f"b {done_label}")
        self._lines.append(f"{fail_label}:")
        self._emit("clrex")
        if bool_result:
            self._emit(f"mov w{target}, #0")
        self._lines.append(f"{done_label}:")
        if bool_result:
            return _Value(INT, self._scalar_info(INT), target)
        return _Value(type_, info, target)

    @staticmethod
    def _atomic_value_reg(target: int) -> int:
        return 9 if target == 10 else 10

    def _emit_atomic_builtin(
        self,
        callee_name: str,
        expr: CallExpr,
        target: int,
    ) -> _Value | None:
        args = expr.args
        if callee_name in {
            "__atomic_thread_fence",
            "__atomic_signal_fence",
            "__c11_atomic_thread_fence",
            "__c11_atomic_signal_fence",
            "__sync_synchronize",
            "__scoped_atomic_thread_fence",
        }:
            self._emit("dmb ish")
            return _Value(self._expr_type(expr), _ScalarInfo(4, 4, False), target)

        if callee_name in {
            "__atomic_is_lock_free",
            "__atomic_always_lock_free",
            "__c11_atomic_is_lock_free",
        }:
            info = self._scalar_info(self._expr_type(expr))
            self._emit_load_immediate(self._reg(target, info), 1, info.bits)
            return _Value(self._expr_type(expr), info, target)

        if callee_name in {"__atomic_load_n", "__c11_atomic_load", "__scoped_atomic_load"}:
            if len(args) < 1:
                return _Value(
                    self._expr_type(expr), self._scalar_info(self._expr_type(expr)), target
                )
            type_, info = self._atomic_pointee(args[0])
            self._emit_expr(args[0], 11)
            self._emit_atomic_load_from_address(info, target, 11)
            return _Value(type_, info, target)

        if callee_name in {
            "__atomic_store_n",
            "__c11_atomic_store",
            "__c11_atomic_init",
            "__scoped_atomic_store",
        }:
            if len(args) < 2:
                return _Value(VOID, _ScalarInfo(4, 4, False), target)
            type_, info = self._atomic_pointee(args[0])
            value_reg = self._atomic_value_reg(target)
            value = self._emit_expr(args[1], value_reg)
            self._coerce_value(value, type_, info, value_reg)
            self._emit_expr(args[0], 11)
            self._emit_atomic_store_to_address(info, value_reg, 11)
            return _Value(self._expr_type(expr), _ScalarInfo(4, 4, False), target)

        if callee_name == "__atomic_load":
            if len(args) < 2:
                return _Value(VOID, _ScalarInfo(4, 4, False), target)
            type_, info = self._atomic_pointee(args[0])
            self._emit_expr(args[1], 12)
            self._emit_expr(args[0], 11)
            self._emit_atomic_load_from_address(info, target, 11)
            self._emit_store_to_address(info, target, 12)
            return _Value(VOID, _ScalarInfo(4, 4, False), target)

        if callee_name == "__atomic_store":
            if len(args) < 2:
                return _Value(VOID, _ScalarInfo(4, 4, False), target)
            type_, info = self._atomic_pointee(args[0])
            self._emit_expr(args[1], 12)
            value_reg = self._atomic_value_reg(target)
            self._emit_load_from_address(info, value_reg, 12)
            self._emit_expr(args[0], 11)
            self._emit_atomic_store_to_address(info, value_reg, 11)
            return _Value(VOID, _ScalarInfo(4, 4, False), target)

        rmw_ops = {
            "__atomic_fetch_add": "add",
            "__atomic_fetch_sub": "sub",
            "__atomic_fetch_and": "and",
            "__atomic_fetch_or": "or",
            "__atomic_fetch_xor": "xor",
            "__atomic_fetch_nand": "nand",
            "__sync_fetch_and_add": "add",
            "__sync_fetch_and_sub": "sub",
            "__sync_fetch_and_and": "and",
            "__sync_fetch_and_or": "or",
            "__sync_fetch_and_xor": "xor",
            "__c11_atomic_fetch_add": "add",
            "__c11_atomic_fetch_sub": "sub",
            "__c11_atomic_fetch_and": "and",
            "__c11_atomic_fetch_or": "or",
            "__c11_atomic_fetch_xor": "xor",
            "__scoped_atomic_fetch_add": "add",
        }
        op = rmw_ops.get(callee_name)
        if op is not None:
            if len(args) < 2:
                return _Value(
                    self._expr_type(expr), self._scalar_info(self._expr_type(expr)), target
                )
            type_, info = self._atomic_pointee(args[0])
            value_reg = self._atomic_value_reg(target)
            value = self._emit_expr(args[1], value_reg)
            self._coerce_value(value, type_, info, value_reg)
            self._emit_expr(args[0], 11)
            return self._emit_atomic_rmw(op, type_, info, target, value_reg, return_new=False)

        new_value_ops = {
            "__atomic_add_fetch": "add",
            "__atomic_sub_fetch": "sub",
            "__atomic_and_fetch": "and",
            "__atomic_or_fetch": "or",
            "__atomic_xor_fetch": "xor",
            "__atomic_nand_fetch": "nand",
            "__sync_add_and_fetch": "add",
            "__sync_sub_and_fetch": "sub",
            "__sync_and_and_fetch": "and",
            "__sync_or_and_fetch": "or",
            "__sync_xor_and_fetch": "xor",
        }
        op = new_value_ops.get(callee_name)
        if op is not None:
            if len(args) < 2:
                return _Value(
                    self._expr_type(expr), self._scalar_info(self._expr_type(expr)), target
                )
            type_, info = self._atomic_pointee(args[0])
            value_reg = self._atomic_value_reg(target)
            value = self._emit_expr(args[1], value_reg)
            self._coerce_value(value, type_, info, value_reg)
            self._emit_expr(args[0], 11)
            return self._emit_atomic_rmw(op, type_, info, target, value_reg, return_new=True)

        if callee_name in {
            "__atomic_exchange_n",
            "__c11_atomic_exchange",
            "__sync_lock_test_and_set",
        }:
            if len(args) < 2:
                return _Value(
                    self._expr_type(expr), self._scalar_info(self._expr_type(expr)), target
                )
            type_, info = self._atomic_pointee(args[0])
            value_reg = self._atomic_value_reg(target)
            value = self._emit_expr(args[1], value_reg)
            self._coerce_value(value, type_, info, value_reg)
            self._emit_expr(args[0], 11)
            return self._emit_atomic_rmw("xchg", type_, info, target, value_reg, return_new=False)

        if callee_name == "__atomic_exchange":
            if len(args) < 3:
                return _Value(VOID, _ScalarInfo(4, 4, False), target)
            type_, info = self._atomic_pointee(args[0])
            self._emit_expr(args[1], 12)
            value_reg = self._atomic_value_reg(target)
            self._emit_load_from_address(info, value_reg, 12)
            self._emit_expr(args[0], 11)
            old = self._emit_atomic_rmw("xchg", type_, info, target, value_reg, return_new=False)
            self._emit_expr(args[2], 12)
            self._emit_store_to_address(info, old.reg, 12)
            return _Value(VOID, _ScalarInfo(4, 4, False), target)

        if callee_name in {
            "__atomic_compare_exchange_n",
            "__c11_atomic_compare_exchange_strong",
            "__c11_atomic_compare_exchange_weak",
        }:
            if len(args) < 3:
                return _Value(INT, self._scalar_info(INT), target)
            type_, info = self._atomic_pointee(args[0])
            value_reg = self._atomic_value_reg(target)
            desired = self._emit_expr(args[2], value_reg)
            self._coerce_value(desired, type_, info, value_reg)
            self._emit_expr(args[0], 11)
            self._emit_expr(args[1], 12)
            return self._emit_atomic_compare_exchange(type_, info, target, value_reg)

        if callee_name == "__atomic_compare_exchange":
            if len(args) < 3:
                return _Value(INT, self._scalar_info(INT), target)
            type_, info = self._atomic_pointee(args[0])
            self._emit_expr(args[2], 12)
            value_reg = self._atomic_value_reg(target)
            self._emit_load_from_address(info, value_reg, 12)
            self._emit_expr(args[0], 11)
            self._emit_expr(args[1], 12)
            return self._emit_atomic_compare_exchange(type_, info, target, value_reg)

        if callee_name in {"__sync_val_compare_and_swap", "__sync_bool_compare_and_swap"}:
            if len(args) < 3:
                return _Value(
                    self._expr_type(expr), self._scalar_info(self._expr_type(expr)), target
                )
            type_, info = self._atomic_pointee(args[0])
            expected_reg = self._available_reg({target, 10, 11}, (9, 12, 13))
            desired_reg = self._atomic_value_reg(target)
            if desired_reg == expected_reg:
                desired_reg = self._available_reg({target, expected_reg, 11}, (10, 9, 12, 13))
            expected = self._emit_expr(args[1], expected_reg)
            self._coerce_value(expected, type_, info, expected_reg)
            desired = self._emit_expr(args[2], desired_reg)
            self._coerce_value(desired, type_, info, desired_reg)
            self._emit_expr(args[0], 11)
            return self._emit_sync_compare_exchange(
                type_,
                info,
                target,
                expected_reg,
                desired_reg,
                bool_result=callee_name == "__sync_bool_compare_and_swap",
            )

        if callee_name == "__sync_lock_release":
            if len(args) < 1:
                return _Value(VOID, _ScalarInfo(4, 4, False), target)
            type_, info = self._atomic_pointee(args[0])
            self._emit_load_immediate(self._reg(10, info), 0, info.bits)
            self._emit_expr(args[0], 11)
            self._emit_atomic_store_to_address(info, 10, 11)
            return _Value(VOID, _ScalarInfo(4, 4, False), target)

        return None

    def _emit_outgoing_stack_arg(self, value: _Value, reg: int, stack_index: int) -> None:
        offset = self._outgoing_arg_offset + stack_index * 8
        if value.info.is_float:
            self._emit_stack_store_reg(self._reg(reg, value.info), offset)
            return
        self._emit_stack_store_reg(f"x{reg}", offset)

    def _emit_darwin_variadic_stack_args(
        self,
        values: list[_Value | _VariadicAggregate],
        fixed_count: int,
        stack_arg_size: int,
    ) -> int:
        variadic_values = values[fixed_count:]
        if not variadic_values:
            return 0
        stack_size = self._align_to(
            sum(self._darwin_variadic_arg_stack_size(value) for value in variadic_values),
            16,
        )
        self._emit(f"sub sp, sp, #{stack_size}")
        offset = 0
        frame_delta = stack_arg_size + stack_size
        for value in variadic_values:
            if isinstance(value, _VariadicAggregate):
                size = self._type_size(value.type_)
                if size is None:
                    raise self._error(f"AArch64 target cannot size variadic argument {value.type_}")
                source_offset = frame_delta + value.slot.offset
                if size > 16:
                    self._emit_add_byte_offset(11, "sp", source_offset)
                    self._emit_stack_store_reg("x11", offset)
                    offset += 8
                    continue
                self._emit_add_byte_offset(11, "sp", offset)
                self._emit_add_byte_offset(12, "sp", source_offset)
                self._emit_copy_memory(11, 12, size)
                offset += self._align_to(size, 8)
                continue
            reg = value.reg
            if value.info.size < 8:
                self._emit(f"mov w{reg}, w{reg}")
            if value.info.is_float:
                self._emit_stack_store_reg(self._reg(reg, value.info), offset)
            else:
                self._emit_stack_store_reg(f"x{reg}", offset)
            offset += 8
        return stack_size

    def _darwin_variadic_arg_stack_size(self, value: _Value | _VariadicAggregate) -> int:
        if isinstance(value, _Value):
            return 8
        size = self._type_size(value.type_)
        if size is None:
            raise self._error(f"AArch64 target cannot size variadic argument {value.type_}")
        if size > 16:
            return 8
        return self._align_to(size, 8)

    def _emit_string_literal(self, expr: StringLiteral, target: int) -> _Value:
        label = self._string_literal_label(expr)
        info = _ScalarInfo(8, 8, False)
        self._emit(f"adrp x{target}, {label}@PAGE")
        self._emit(f"add x{target}, x{target}, {label}@PAGEOFF")
        type_ = self._expr_type(expr)
        element_type = type_.element_type() or CHAR
        return _Value(element_type.pointer_to(), info, target)

    def _emit_float_literal(self, expr: FloatLiteral, target: int) -> _Value:
        type_ = self._expr_type(expr)
        info = self._scalar_info(type_)
        bits = self._float_bits(expr.value, info.size)
        label = self._float_literals.get((bits, info.size))
        if label is None:
            label = f"L_.float{len(self._float_literals)}"
            self._float_literals[(bits, info.size)] = label
        self._emit(f"adrp x11, {label}@PAGE")
        self._emit(f"ldr {self._reg(target, info)}, [x11, {label}@PAGEOFF]")
        return _Value(type_, info, target)

    def _emit_subscript(self, expr: SubscriptExpr, target: int) -> _Value:
        type_ = self._expr_type(expr)
        if type_.is_array():
            self._emit_address(expr, target)
            return _Value(type_, _ScalarInfo(8, 8, False), target)
        info = self._scalar_info(type_)
        self._emit_address(expr, 11)
        self._emit_load_from_address(info, target, 11)
        return _Value(type_, info, target)

    def _emit_member(self, expr: MemberExpr, target: int) -> _Value:
        type_ = self._expr_type(expr)
        if type_.is_array():
            self._emit_address(expr, target)
            return _Value(type_, _ScalarInfo(8, 8, False), target)
        info = self._scalar_info(type_)
        access = self._emit_member_storage_address(expr, 11)
        if access.bit_width is not None and access.bit_offset is not None:
            self._emit_bitfield_load(access, info, target, 11)
            return _Value(type_, info, target)
        self._emit_load_from_address(info, target, 11)
        return _Value(type_, info, target)

    def _emit_bitfield_load(
        self,
        access: _MemberAccess,
        result_info: _ScalarInfo,
        target: int,
        address_reg: int,
    ) -> None:
        storage_info = self._scalar_info(access.type_)
        self._emit_load_from_address(storage_info, target, address_reg)
        assert access.bit_offset is not None and access.bit_width is not None
        reg = self._reg(target, storage_info)
        if access.bit_offset:
            self._emit(f"lsr {reg}, {reg}, #{access.bit_offset}")
        if result_info.signed:
            shift = storage_info.bits - access.bit_width
            self._emit(f"lsl {reg}, {reg}, #{shift}")
            self._emit(f"asr {reg}, {reg}, #{shift}")
            return
        mask = (1 << access.bit_width) - 1
        self._emit(f"and {reg}, {reg}, #{mask}")

    def _emit_bitfield_store(
        self,
        access: _MemberAccess,
        result_info: _ScalarInfo,
        value_reg: int,
        address_reg: int,
        reserved_regs: set[int] | None = None,
    ) -> None:
        assert access.bit_offset is not None and access.bit_width is not None
        storage_info = self._scalar_info(access.type_)
        reserved = set() if reserved_regs is None else reserved_regs
        storage_reg = self._available_reg(
            {value_reg, address_reg, *reserved},
            (10, 9, 12, 13, 14, 15),
        )
        mask_reg = self._available_reg(
            {value_reg, address_reg, storage_reg, *reserved},
            (12, 13, 10, 9, 14, 15),
        )
        field_reg = self._available_reg(
            {value_reg, address_reg, storage_reg, mask_reg, *reserved},
            (13, 12, 10, 9, 14, 15),
        )

        if storage_info.size == 8 and result_info.size == 8:
            self._emit(f"mov x{field_reg}, x{value_reg}")
        else:
            self._emit(f"mov w{field_reg}, w{value_reg}")
        value_mask = (1 << access.bit_width) - 1
        self._emit_load_immediate(self._reg(mask_reg, storage_info), value_mask, storage_info.bits)
        self._emit(
            f"and {self._reg(field_reg, storage_info)}, "
            f"{self._reg(field_reg, storage_info)}, {self._reg(mask_reg, storage_info)}"
        )
        if access.bit_offset:
            self._emit(
                f"lsl {self._reg(field_reg, storage_info)}, "
                f"{self._reg(field_reg, storage_info)}, #{access.bit_offset}"
            )

        self._emit_load_from_address(storage_info, storage_reg, address_reg)
        field_mask = value_mask << access.bit_offset
        self._emit_load_immediate(self._reg(mask_reg, storage_info), field_mask, storage_info.bits)
        self._emit(
            f"bic {self._reg(storage_reg, storage_info)}, "
            f"{self._reg(storage_reg, storage_info)}, {self._reg(mask_reg, storage_info)}"
        )
        self._emit(
            f"orr {self._reg(storage_reg, storage_info)}, "
            f"{self._reg(storage_reg, storage_info)}, {self._reg(field_reg, storage_info)}"
        )
        self._emit_store_to_address(storage_info, storage_reg, address_reg)
        self._emit_bitfield_load(access, result_info, value_reg, address_reg)

    def _emit_sizeof(self, expr: SizeofExpr, target: int) -> _Value:
        type_ = self._sizeof_operand_type(expr)
        size = self._type_size(type_)
        if size is None:
            raise self._error(f"AArch64 target cannot size type {type_}")
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        self._emit_load_immediate(self._reg(target, result_info), size, result_info.bits)
        return _Value(result_type, result_info, target)

    def _emit_alignof(self, expr: AlignofExpr, target: int) -> _Value:
        type_ = self._sizeof_operand_type(expr)
        alignment = self._type_align(type_)
        if alignment is None:
            raise self._error(f"AArch64 target cannot align type {type_}")
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        self._emit_load_immediate(self._reg(target, result_info), alignment, result_info.bits)
        return _Value(result_type, result_info, target)

    def _emit_offsetof(self, expr: BuiltinOffsetofExpr, target: int) -> _Value:
        offset = self._offsetof_value(expr)
        if offset is None:
            raise self._error(f"AArch64 target cannot compute offsetof({expr.member})")
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        self._emit_load_immediate(self._reg(target, result_info), offset, result_info.bits)
        return _Value(result_type, result_info, target)

    def _sizeof_operand_type(self, expr: SizeofExpr | AlignofExpr) -> Type:
        if expr.type_spec is not None:
            return self._resolve_type_spec(expr.type_spec)
        assert expr.expr is not None
        type_ = self._type_map.get(expr.expr)
        if type_ is None:
            if isinstance(expr.expr, Identifier) and self._func_sym is not None:
                symbol = self._func_sym.locals.get(expr.expr.name)
                if isinstance(symbol, VarSymbol):
                    return symbol.type_
            if isinstance(expr.expr, Identifier) and self._sema.file_scope is not None:
                symbol = self._sema.file_scope.lookup(expr.expr.name)
                if isinstance(symbol, VarSymbol):
                    return symbol.type_
            if isinstance(expr.expr, MemberExpr):
                base_raw = self._type_map.get(expr.expr.base)
                if base_raw is not None:
                    base_type = base_raw
                    if base_type.declarator_ops and base_type.declarator_ops[0][0] == "ptr":
                        base_type = base_type.pointee() or base_type
                    if base_type is not None and not base_type.declarator_ops:
                        access = self._record_member_access(base_type.name, expr.expr.member)
                        if access is not None:
                            return access.type_
                # Walk nested MemberExpr chain to find root record type
                chain = [expr.expr.member]
                current = expr.expr.base
                while isinstance(current, MemberExpr):
                    chain.append(current.member)
                    current = current.base
                if isinstance(current, Identifier):
                    base_raw = self._type_map.get(current)
                    if base_raw is None and self._func_sym is not None:
                        symbol = self._func_sym.locals.get(current.name)
                        if isinstance(symbol, VarSymbol):
                            base_raw = symbol.type_
                    if base_raw is not None:
                        current_type: Type | None = base_raw
                        if (
                            current_type is not None
                            and current_type.declarator_ops
                            and current_type.declarator_ops[0][0] == "ptr"
                        ):
                            current_type = current_type.pointee() or current_type
                        if current_type is not None and not current_type.declarator_ops:
                            for member_name in reversed(chain):
                                access = self._record_member_access(current_type.name, member_name)
                                if access is not None:
                                    current_type = access.type_
                                else:
                                    current_type = None
                                    break
                            if current_type is not None:
                                return current_type
            raise self._error("AArch64 target cannot resolve sizeof operand type")
        return type_

    def _offsetof_value(self, expr: BuiltinOffsetofExpr) -> int | None:
        root_type = self._resolve_type_spec(expr.type_spec)
        return self._offsetof_member_path(root_type, expr.member.split("."))

    def _offsetof_member_path(self, root_type: Type, parts: list[str]) -> int | None:
        if not parts:
            return 0
        if root_type.declarator_ops:
            return None
        record_name = self._record_name_from_type(root_type)
        if record_name is not None:
            found = self._record_member_offset_and_type(record_name, parts[0])
            if found is not None:
                member_offset, member_type = found
                nested_offset = self._offsetof_member_path(member_type, parts[1:])
                if nested_offset is not None:
                    return member_offset + nested_offset
        for rec_name in self._sema.record_definitions:
            if rec_name == record_name:
                continue
            found = self._record_member_offset_and_type(rec_name, parts[0])
            if found is not None:
                member_offset, member_type = found
                nested_offset = self._offsetof_member_path(member_type, parts[1:])
                if nested_offset is not None:
                    return member_offset + nested_offset
        return None

    def _record_member_offset_and_type(
        self,
        record_name: str,
        member_name: str,
    ) -> tuple[int, Type] | None:
        access = self._record_member_access(record_name, member_name)
        if access is None or access.bit_width is not None:
            return None
        return access.offset, access.type_

    def _record_member_access(
        self,
        record_name: str,
        member_name: str,
    ) -> _MemberAccess | None:
        members = self._sema.record_definitions.get(record_name)
        if members is None:
            return None
        if record_name.startswith("union "):
            for member in members:
                found = self._record_member_access_match(member, member_name)
                if found is not None:
                    return found
            return None

        offset = 0
        active_bit_base = 0
        active_bit_size = 0
        active_bit_used = 0
        active_bit_type: Type | None = None
        for index, member in enumerate(members):
            member_align = self._type_align(member.type_)
            member_size = self._type_size(member.type_)
            is_flexible = self._is_trailing_flexible_array_member(members, index)
            if member_align is None or (member_size is None and not is_flexible):
                return None
            bit_width = member.bit_width
            if bit_width is not None:
                if member_size is None:
                    return None
                if bit_width == 0:
                    if active_bit_type is not None:
                        offset = active_bit_base + active_bit_size
                    offset = self._align_to(offset, member_align)
                    active_bit_type = None
                    active_bit_used = 0
                    continue
                member_bits = member_size * 8
                if active_bit_type != member.type_ or active_bit_used + bit_width > member_bits:
                    if active_bit_type is not None:
                        offset = active_bit_base + active_bit_size
                    offset = self._align_to(offset, member_align)
                    active_bit_base = offset
                    active_bit_size = member_size
                    active_bit_used = 0
                    active_bit_type = member.type_
                found = self._record_member_access_match(
                    member,
                    member_name,
                    bit_offset=active_bit_used,
                )
                if found is not None:
                    return _MemberAccess(
                        active_bit_base + found.offset,
                        found.type_,
                        found.bit_offset,
                        found.bit_width,
                    )
                active_bit_used += bit_width
                continue
            if active_bit_type is not None:
                offset = active_bit_base + active_bit_size
                active_bit_type = None
                active_bit_used = 0
            offset = self._align_to(offset, member_align)
            found = self._record_member_access_match(member, member_name)
            if found is not None:
                return _MemberAccess(
                    offset + found.offset,
                    found.type_,
                    found.bit_offset,
                    found.bit_width,
                )
            if member_size is None:
                return None
            offset += member_size
        return None

    def _record_member_access_match(
        self,
        member: RecordMemberInfo,
        member_name: str,
        bit_offset: int | None = None,
    ) -> _MemberAccess | None:
        bit_width = member.bit_width
        if member.name == member_name:
            return _MemberAccess(0, member.type_, bit_offset, bit_width)
        member_type = member.type_
        if (
            member.name is None
            and bit_width is None
            and not member_type.declarator_ops
            and member_type.name.startswith(("struct ", "union "))
        ):
            return self._record_member_access(member_type.name, member_name)
        return None

    def _hfa_double_offsets(self, type_: Type) -> list[int] | None:
        if type_.declarator_ops or not type_.name.startswith("struct "):
            return None
        members = self._sema.record_definitions.get(type_.name)
        if members is None or not 1 <= len(members) <= 4:
            return None
        offsets: list[int] = []
        offset = 0
        for member in members:
            if member.bit_width is not None:
                return None
            member_type = member.type_
            if unqualified_type(member_type) != DOUBLE:
                return None
            member_align = self._type_align(member_type)
            member_size = self._type_size(member_type)
            if member_align is None or member_size is None:
                return None
            offset = self._align_to(offset, member_align)
            offsets.append(offset)
            offset += member_size
        return offsets

    def _record_return_fields(self, type_: Type) -> list[tuple[int, Type, _ScalarInfo]] | None:
        if type_.declarator_ops:
            return None
        if type_.name.startswith("union "):
            size = self._type_size(type_)
            align = self._type_align(type_)
            if size not in {1, 2, 4, 8} or align is None:
                return None
            return [(0, type_, _ScalarInfo(size, align, False))]
        if not type_.name.startswith("struct "):
            return None
        hfa_offsets = self._hfa_double_offsets(type_)
        if hfa_offsets is not None:
            double_info = self._scalar_info(DOUBLE)
            return [(offset, DOUBLE, double_info) for offset in hfa_offsets]
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            return None
        size = self._type_size(type_)
        if size is None or size > 16:
            return None
        if not 1 <= len(members) <= 2:
            return self._small_record_chunk_fields(type_, size)
        fields: list[tuple[int, Type, _ScalarInfo]] = []
        for member in members:
            if member.bit_width is not None:
                return self._small_record_chunk_fields(type_, size)
            if not self._types_assignable(member.type_):
                return self._small_record_chunk_fields(type_, size)
            info = self._scalar_info(member.type_)
            if info.is_float or info.size > 8:
                return self._small_record_chunk_fields(type_, size)
            access = self._record_member_access(type_.name, member.name or "")
            if access is None or access.bit_width is not None:
                return self._small_record_chunk_fields(type_, size)
            fields.append((access.offset, member.type_, info))
        return fields

    def _small_record_chunk_fields(
        self,
        type_: Type,
        size: int,
    ) -> list[tuple[int, Type, _ScalarInfo]] | None:
        if size <= 0 or size > 16:
            return None
        fields: list[tuple[int, Type, _ScalarInfo]] = []
        offset = 0
        while offset < size:
            remaining = size - offset
            chunk_size = 8 if remaining >= 8 else remaining
            if chunk_size not in {1, 2, 4, 8}:
                return None
            chunk_type = {
                1: Type("unsigned char"),
                2: Type("unsigned short"),
                4: Type("unsigned int"),
                8: Type("unsigned long"),
            }[chunk_size]
            fields.append((offset, chunk_type, _ScalarInfo(chunk_size, chunk_size, False)))
            offset += chunk_size
        return fields

    @staticmethod
    def _record_fields_compatible(
        actual: list[tuple[int, Type, _ScalarInfo]] | None,
        expected: list[tuple[int, Type, _ScalarInfo]],
    ) -> bool:
        if actual is None or len(actual) != len(expected):
            return False
        for (actual_offset, _, actual_info), (expected_offset, _, expected_info) in zip(
            actual,
            expected,
            strict=False,
        ):
            if actual_offset != expected_offset or actual_info != expected_info:
                return False
        return True

    def _is_indirect_return_type(self, type_: Type) -> bool:
        return self._is_record_type(type_) and self._record_return_fields(type_) is None

    def _is_indirect_argument_type(self, type_: Type) -> bool:
        return self._is_record_type(type_) and self._record_return_fields(type_) is None

    def _emit_short_circuit(self, expr: BinaryExpr, target: int) -> _Value:
        true_label = self._new_label("logic_true")
        false_label = self._new_label("logic_false")
        end_label = self._new_label("logic_end")
        if expr.op == "||":
            self._emit_branch_if_nonzero(expr.left, true_label)
            self._emit_branch_if_nonzero(expr.right, true_label)
            self._emit(f"b {false_label}")
        elif expr.op == "&&":
            self._emit_branch_if_zero(expr.left, false_label)
            self._emit_branch_if_zero(expr.right, false_label)
            self._emit(f"b {true_label}")
        else:
            raise AssertionError(f"unhandled short-circuit op: {expr.op}")
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        self._lines.append(f"{true_label}:")
        self._emit_load_immediate(self._reg(target, result_info), 1, result_info.bits)
        self._emit(f"b {end_label}")
        self._lines.append(f"{false_label}:")
        self._emit_load_immediate(self._reg(target, result_info), 0, result_info.bits)
        self._lines.append(f"{end_label}:")
        return _Value(result_type, result_info, target)

    def _emit_conditional(self, expr: ConditionalExpr, target: int) -> _Value:
        else_label = self._new_label("cond_else")
        end_label = self._new_label("cond_end")
        result_type = self._expr_type(expr)
        result_info = (
            _ScalarInfo(4, 4, False)
            if self._is_void_type(result_type)
            else self._scalar_info(result_type)
        )
        self._emit_branch_if_zero(expr.condition, else_label)
        then_value = self._emit_expr(expr.then_expr, target)
        if not self._is_void_type(result_type):
            self._coerce_value(then_value, result_type, result_info, target)
        self._emit(f"b {end_label}")
        self._lines.append(f"{else_label}:")
        else_value = self._emit_expr(expr.else_expr, target)
        if not self._is_void_type(result_type):
            self._coerce_value(else_value, result_type, result_info, target)
        self._lines.append(f"{end_label}:")
        return _Value(result_type, result_info, target)

    def _emit_branch_if_zero(self, expr: Expr, label: str) -> None:
        value = self._emit_expr(expr, 0)
        self._emit_compare_zero(value.info, 0)
        self._emit(f"b.eq {label}")

    def _emit_branch_if_nonzero(self, expr: Expr, label: str) -> None:
        value = self._emit_expr(expr, 0)
        self._emit_compare_zero(value.info, 0)
        self._emit(f"b.ne {label}")

    def _emit_identifier(self, expr: Identifier, target: int) -> _Value:
        assert self._func_sym is not None
        symbol = self._func_sym.locals.get(expr.name)
        if isinstance(symbol, EnumConstSymbol):
            info = self._scalar_info(symbol.type_)
            self._emit_load_immediate(self._reg(target, info), symbol.value, info.bits)
            return _Value(symbol.type_, info, target)
        slot = self._lookup_slot(expr.name)
        if slot is not None:
            if slot.type_.is_array():
                info = _ScalarInfo(8, 8, False)
                self._emit_address(expr, target)
                return _Value(self._expr_type(expr), info, target)
            if not self._types_assignable(slot.type_):
                raise self._error(f"AArch64 target cannot load aggregate local {expr.name}")
            self._emit_load(slot, target)
            return _Value(slot.type_, slot.info, target)
        static_local = self._static_local(expr.name)
        if static_local is not None:
            if static_local.type_.is_array():
                info = _ScalarInfo(8, 8, False)
                self._emit_address(expr, target)
                return _Value(self._expr_type(expr), info, target)
            info = self._scalar_info(static_local.type_)
            self._emit_address(expr, 11)
            self._emit_load_from_address(info, target, 11)
            return _Value(static_local.type_, info, target)
        if isinstance(symbol, VarSymbol):
            if symbol.is_extern:
                if symbol.type_.is_array():
                    info = _ScalarInfo(8, 8, False)
                    self._emit_address(expr, target)
                    return _Value(symbol.type_, info, target)
                info = self._scalar_info(symbol.type_)
                label = self._symbol_name(expr.name)
                self._emit_extern_data_address(label, 11)
                self._emit_load_from_address(info, target, 11)
                return _Value(symbol.type_, info, target)
            if symbol.type_.declarator_ops and symbol.type_.declarator_ops[0][0] == "fn":
                value_type = self._function_designator_value_type(symbol.type_)
                self._emit_function_address(expr.name, target)
                return _Value(value_type, _ScalarInfo(8, 8, False), target)
            global_ = self._globals.get(expr.name)
            if global_ is not None and global_.type_.is_array():
                info = _ScalarInfo(8, 8, False)
                self._emit_address(expr, target)
                return _Value(self._expr_type(expr), info, target)
            if global_ is not None and not global_.type_.is_array():
                info = self._scalar_info(global_.type_)
                self._emit_address(expr, 11)
                self._emit_load_from_address(info, target, 11)
                return _Value(global_.type_, info, target)
            slot = self._require_slot(expr.name)
            self._emit_load(slot, target)
            return _Value(slot.type_, slot.info, target)
        if expr.name in self._sema.function_signatures:
            value_type = self._function_designator_value_type(self._expr_type(expr))
            self._emit_function_address(expr.name, target)
            return _Value(value_type, _ScalarInfo(8, 8, False), target)
        if self._sema.file_scope is not None:
            file_symbol = self._sema.file_scope.lookup(expr.name)
            if isinstance(file_symbol, EnumConstSymbol):
                info = self._scalar_info(file_symbol.type_)
                self._emit_load_immediate(self._reg(target, info), file_symbol.value, info.bits)
                return _Value(file_symbol.type_, info, target)
            if isinstance(file_symbol, VarSymbol):
                global_ = self._globals.get(expr.name)
                if global_ is not None and global_.type_.is_array():
                    info = _ScalarInfo(8, 8, False)
                    self._emit_address(expr, target)
                    return _Value(self._expr_type(expr), info, target)
                if global_ is not None and not global_.type_.is_array():
                    info = self._scalar_info(global_.type_)
                    self._emit_address(expr, 11)
                    self._emit_load_from_address(info, target, 11)
                    return _Value(global_.type_, info, target)
                if file_symbol.is_extern:
                    if file_symbol.type_.is_array():
                        info = _ScalarInfo(8, 8, False)
                        self._emit_address(expr, target)
                        return _Value(file_symbol.type_, info, target)
                    info = self._scalar_info(file_symbol.type_)
                    label = self._symbol_name(expr.name)
                    self._emit_extern_data_address(label, 11)
                    self._emit_load_from_address(info, target, 11)
                    return _Value(file_symbol.type_, info, target)
        raise self._error(f"AArch64 target does not support global identifier: {expr.name}")

    def _emit_unary(self, expr: UnaryExpr, target: int) -> _Value:
        if expr.op == "&":
            return self._emit_address_of(expr.operand, target)
        if expr.op == "*":
            type_ = self._expr_type(expr)
            value_type = self._function_designator_value_type(type_)
            if value_type != type_:
                value = self._emit_expr(expr.operand, target)
                pointee = value.type_.pointee()
                if pointee is None or self._function_designator_value_type(pointee) != value.type_:
                    raise self._error("AArch64 target cannot dereference non-function pointer")
                return _Value(value_type, _ScalarInfo(8, 8, False), target)
            info = self._scalar_info(type_)
            self._emit_address(expr, 11)
            self._emit_load_from_address(info, target, 11)
            return _Value(type_, info, target)
        if expr.op == "+":
            return self._emit_expr(expr.operand, target)
        value = self._emit_expr(expr.operand, target)
        if expr.op == "-":
            instruction = "fneg" if value.info.is_float else "neg"
            self._emit(
                f"{instruction} {self._reg(target, value.info)}, {self._reg(target, value.info)}"
            )
            return value
        if expr.op == "~":
            self._emit(f"mvn {self._reg(target, value.info)}, {self._reg(target, value.info)}")
            return value
        if expr.op == "!":
            result_type = self._expr_type(expr)
            result_info = self._scalar_info(result_type)
            self._emit_compare_zero(value.info, target)
            self._emit(f"cset {self._reg(target, result_info)}, eq")
            return _Value(result_type, result_info, target)
        raise self._error(f"AArch64 target does not support unary operator {expr.op}")

    def _emit_update(self, expr: UpdateExpr, target: int) -> _Value:
        type_ = self._expr_type(expr)
        info = self._scalar_info(type_)
        address_reg = 12 if target == 11 else 11
        step_unit = 1
        pointee = type_.pointee()
        if pointee is not None:
            pointee_size = self._type_size(pointee)
            if pointee_size is None:
                raise self._error(f"AArch64 target cannot size type {pointee}")
            step_unit = pointee_size
        step = step_unit if expr.op == "++" else -step_unit
        if isinstance(expr.operand, MemberExpr):
            access = self._emit_member_storage_address(expr.operand, address_reg)
            if access.bit_width is not None:
                self._emit_bitfield_load(access, info, target, address_reg)
                if expr.is_postfix:
                    update_reg = self._available_reg({target, address_reg}, (9, 10, 12, 13))
                    self._emit(f"mov {self._reg(update_reg, info)}, {self._reg(target, info)}")
                else:
                    update_reg = target
                self._emit_add_immediate(info, update_reg, step)
                reserved_regs = {target} if expr.is_postfix else None
                self._emit_bitfield_store(access, info, update_reg, address_reg, reserved_regs)
                return _Value(type_, info, target)
        if isinstance(expr.operand, Identifier):
            slot = self._lookup_slot(expr.operand.name)
            if slot is not None:
                self._emit_load(slot, target)
                if expr.is_postfix:
                    update_reg = self._available_reg({target}, (9, 10, 12, 13))
                    self._emit(f"mov {self._reg(update_reg, info)}, {self._reg(target, info)}")
                else:
                    update_reg = target
                self._emit_add_immediate(info, update_reg, step)
                self._emit_store(slot, update_reg)
                return _Value(type_, info, target)
        self._emit_address(expr.operand, address_reg)
        self._emit_load_from_address(info, target, address_reg)
        if expr.is_postfix:
            update_reg = self._available_reg({target, address_reg}, (9, 10, 12, 13))
            self._emit(f"mov {self._reg(update_reg, info)}, {self._reg(target, info)}")
        else:
            update_reg = target
        self._emit_add_immediate(info, update_reg, step)
        self._emit_store_to_address(info, update_reg, address_reg)
        return _Value(type_, info, target)

    def _emit_binary(self, expr: BinaryExpr, target: int) -> _Value:
        if expr.op in {"&&", "||"}:
            return self._emit_short_circuit(expr, target)
        if expr.op in {"<<", ">>"}:
            return self._emit_shift(expr, target)

        left = self._emit_expr(expr.left, 9)
        left = self._decay_array_value(left)
        left_spill = self._spill_binary_left_value(left)
        right = self._emit_expr(expr.right, 10)
        self._restore_binary_left_value(left, left_spill)
        right = self._decay_array_value(right)
        if self._is_pointer_binary(expr.op, left.type_, right.type_):
            return self._emit_pointer_binary(expr, left, right, target)
        common_type = usual_arithmetic_conversion(left.type_, right.type_)
        if common_type is None:
            raise self._error(f"AArch64 target does not support binary operator {expr.op}")
        common_info = self._scalar_info(common_type)
        self._coerce_value(left, common_type, common_info, 9)
        self._coerce_value(right, common_type, common_info, 10)

        if common_info.is_float:
            if expr.op in {"+", "-", "*", "/"}:
                result_type = self._expr_type(expr)
                result_info = self._scalar_info(result_type)
                instruction = {"+": "fadd", "-": "fsub", "*": "fmul", "/": "fdiv"}[expr.op]
                self._emit(
                    f"{instruction} {self._reg(target, result_info)}, "
                    f"{self._reg(9, common_info)}, {self._reg(10, common_info)}"
                )
                return _Value(result_type, result_info, target)
            if expr.op in {"==", "!=", "<", "<=", ">", ">="}:
                result_type = self._expr_type(expr)
                result_info = self._scalar_info(result_type)
                condition = self._comparison_condition(expr.op, signed=True)
                self._emit(f"fcmp {self._reg(9, common_info)}, {self._reg(10, common_info)}")
                self._emit(f"cset {self._reg(target, result_info)}, {condition}")
                return _Value(result_type, result_info, target)
            raise self._error(f"AArch64 target does not support binary operator {expr.op}")

        if expr.op in {"+", "-", "*", "/", "%", "|", "&", "^"}:
            result_type = self._expr_type(expr)
            result_info = self._scalar_info(result_type)
            self._emit_arithmetic(expr.op, common_info, result_info, target)
            return _Value(result_type, result_info, target)
        if expr.op in {"==", "!=", "<", "<=", ">", ">="}:
            result_type = self._expr_type(expr)
            result_info = self._scalar_info(result_type)
            condition = self._comparison_condition(expr.op, common_info.signed)
            self._emit(f"cmp {self._reg(9, common_info)}, {self._reg(10, common_info)}")
            self._emit(f"cset {self._reg(target, result_info)}, {condition}")
            return _Value(result_type, result_info, target)
        raise self._error(f"AArch64 target does not support binary operator {expr.op}")

    def _spill_binary_left_value(self, value: _Value) -> int:
        if self._expr_spill_depth >= self._expr_spill_reserved_depth:
            raise self._error("AArch64 target internal expression spill slot unavailable")
        offset = self._BASE_SCRATCH_SIZE + self._expr_spill_depth * self._EXPR_SPILL_SIZE
        self._emit_spill_value(value.info, value.reg, offset)
        self._expr_spill_depth += 1
        return offset

    def _restore_binary_left_value(self, value: _Value, offset: int) -> None:
        self._expr_spill_depth -= 1
        self._emit_reload_value(value.info, value.reg, offset)

    def _emit_spill_value(self, info: _ScalarInfo, reg: int, offset: int) -> None:
        if info.is_float:
            self._emit_scratch_store_reg(self._reg(reg, info), offset)
        elif info.size == 8:
            self._emit_scratch_store_reg(f"x{reg}", offset)
        else:
            self._emit_scratch_store_reg(f"w{reg}", offset)

    def _emit_reload_value(self, info: _ScalarInfo, reg: int, offset: int) -> None:
        if info.is_float:
            self._emit_scratch_load_reg(self._reg(reg, info), offset)
        elif info.size == 8:
            self._emit_scratch_load_reg(f"x{reg}", offset)
        else:
            self._emit_scratch_load_reg(f"w{reg}", offset)

    def _emit_pointer_binary(
        self,
        expr: BinaryExpr,
        left: _Value,
        right: _Value,
        target: int,
    ) -> _Value:
        left_is_pointer = self._is_pointer_type(left.type_)
        right_is_pointer = self._is_pointer_type(right.type_)
        if expr.op in {"==", "!=", "<", "<=", ">", ">="}:
            pointer_info = _ScalarInfo(8, 8, False)
            if not left_is_pointer:
                self._coerce_value(left, right.type_, pointer_info, 9)
            if not right_is_pointer:
                self._coerce_value(right, left.type_, pointer_info, 10)
            result_type = self._expr_type(expr)
            result_info = self._scalar_info(result_type)
            condition = self._comparison_condition(expr.op, signed=False)
            self._emit("cmp x9, x10")
            self._emit(f"cset {self._reg(target, result_info)}, {condition}")
            return _Value(result_type, result_info, target)
        if expr.op == "+":
            result_type = self._expr_type(expr)
            result_info = self._scalar_info(result_type)
            if left_is_pointer:
                self._emit_pointer_step(right, 10, left.type_)
                self._emit(f"add x{target}, x9, x10")
            else:
                self._emit_pointer_step(left, 9, right.type_)
                self._emit(f"add x{target}, x10, x9")
            return _Value(result_type, result_info, target)
        if expr.op == "-":
            result_type = self._expr_type(expr)
            result_info = self._scalar_info(result_type)
            if right_is_pointer:
                step = self._pointer_step_size(left.type_)
                self._emit("sub x11, x9, x10")
                self._emit_divide_pointer_difference(11, step)
                if result_info.size == 8:
                    self._emit(f"mov x{target}, x11")
                else:
                    self._emit(f"mov w{target}, w11")
            else:
                self._emit_pointer_step(right, 10, left.type_)
                self._emit(f"sub x{target}, x9, x10")
            return _Value(result_type, result_info, target)
        raise self._error(f"AArch64 target does not support binary operator {expr.op}")

    def _emit_pointer_step(self, value: _Value, reg: int, pointer_type: Type) -> None:
        if not is_integer_type(unqualified_type(value.type_)):
            raise self._error("AArch64 target requires integer pointer offset")
        self._emit_integer_to_x(value, reg)
        step = self._pointer_step_size(pointer_type)
        if step == 1:
            return
        shift = step.bit_length() - 1
        if 1 << shift == step:
            self._emit(f"lsl x{reg}, x{reg}, #{shift}")
            return
        self._emit_load_immediate("x12", step, 64)
        self._emit(f"mul x{reg}, x{reg}, x12")

    def _emit_divide_pointer_difference(self, reg: int, step: int) -> None:
        if step == 1:
            return
        shift = step.bit_length() - 1
        if 1 << shift == step:
            self._emit(f"asr x{reg}, x{reg}, #{shift}")
            return
        self._emit_load_immediate("x12", step, 64)
        self._emit(f"sdiv x{reg}, x{reg}, x12")

    def _emit_integer_to_x(self, value: _Value, reg: int) -> None:
        if value.info.is_float or value.info.size > 8:
            raise self._error("AArch64 target cannot use non-integer pointer offset")
        if value.info.size == 8:
            return
        if value.info.signed:
            self._emit(f"sxtw x{reg}, w{reg}")
        else:
            self._emit(f"mov w{reg}, w{reg}")

    @staticmethod
    def _decay_array_value(value: _Value) -> _Value:
        element_type = value.type_.element_type()
        if element_type is None:
            return value
        return _Value(element_type.pointer_to(), _ScalarInfo(8, 8, False), value.reg)

    def _emit_shift(self, expr: BinaryExpr, target: int) -> _Value:
        left = self._emit_expr(expr.left, 9)
        left_spill = self._spill_binary_left_value(left)
        right = self._emit_expr(expr.right, 10)
        self._restore_binary_left_value(left, left_spill)
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        self._coerce_value(left, result_type, result_info, 9)
        self._coerce_value(right, result_type, result_info, 10)
        instruction = "lsl"
        if expr.op == ">>":
            instruction = "asr" if result_info.signed else "lsr"
        self._emit(
            f"{instruction} {self._reg(target, result_info)}, "
            f"{self._reg(9, result_info)}, {self._reg(10, result_info)}"
        )
        return _Value(result_type, result_info, target)

    def _emit_arithmetic(
        self,
        op: str,
        operand_info: _ScalarInfo,
        result_info: _ScalarInfo,
        target: int,
    ) -> None:
        dst = self._reg(target, result_info)
        left = self._reg(9, operand_info)
        right = self._reg(10, operand_info)
        if op == "+":
            self._emit(f"add {dst}, {left}, {right}")
            return
        if op == "-":
            self._emit(f"sub {dst}, {left}, {right}")
            return
        if op == "*":
            self._emit(f"mul {dst}, {left}, {right}")
            return
        if op == "/":
            instruction = "sdiv" if operand_info.signed else "udiv"
            self._emit(f"{instruction} {dst}, {left}, {right}")
            return
        if op == "%":
            quotient = self._reg(11, operand_info)
            instruction = "sdiv" if operand_info.signed else "udiv"
            self._emit(f"{instruction} {quotient}, {left}, {right}")
            self._emit(f"msub {dst}, {quotient}, {right}, {left}")
            return
        if op == "<<":
            self._emit(f"lsl {dst}, {left}, {right}")
            return
        if op == ">>":
            instruction = "asr" if operand_info.signed else "lsr"
            self._emit(f"{instruction} {dst}, {left}, {right}")
            return
        if op == "|":
            self._emit(f"orr {dst}, {left}, {right}")
            return
        if op == "&":
            self._emit(f"and {dst}, {left}, {right}")
            return
        if op == "^":
            self._emit(f"eor {dst}, {left}, {right}")
            return
        raise AssertionError(f"unhandled arithmetic op: {op}")

    def _emit_assign(self, expr: AssignExpr, target: int) -> _Value:
        if expr.op in {
            "+=",
            "-=",
            "*=",
            "/=",
            "%=",
            "|=",
            "&=",
            "^=",
            "<<=",
            ">>=",
        }:
            return self._emit_compound_assign(expr, target)
        if expr.op != "=":
            raise self._error(f"AArch64 target does not support assignment operator {expr.op}")
        target_type = self._expr_type(expr.target)
        if isinstance(expr.value, CompoundLiteralExpr) and not self._types_assignable(target_type):
            self._emit_address(expr.target, 11)
            self._emit_record_compound_initializer_to_address(
                target_type,
                expr.value.initializer,
                11,
            )
            return _Value(target_type, self._slot_info(target_type), target)
        if isinstance(expr.value, CallExpr) and not self._types_assignable(target_type):
            fields = self._record_return_fields(target_type)
            if fields is None:
                if self._is_indirect_return_type(target_type):
                    self._emit_address(expr.target, 11)
                    self._emit_scratch_store_reg("x11", 8)
                    self._emit_call(expr.value, 0, indirect_result_scratch_offset=8)
                    return _Value(target_type, self._slot_info(target_type), target)
                raise self._error("AArch64 target cannot assign aggregate call result")
            self._emit_address(expr.target, 11)
            self._emit_scratch_store_reg("x11", 8)
            self._emit_expr(expr.value, 0)
            self._emit_scratch_load_reg("x11", 8)
            for index, (offset, _, info) in enumerate(fields):
                address_reg = 11
                if offset:
                    address_reg = 12
                    self._emit_add_byte_offset(address_reg, "x11", offset)
                self._emit_store_to_address(info, index, address_reg)
            return _Value(target_type, self._slot_info(target_type), target)
        if not self._types_assignable(target_type):
            value_type = self._expr_type(expr.value)
            target_size = self._type_size(target_type)
            value_size = self._type_size(value_type)
            if target_size is None or value_size is None or target_size != value_size:
                raise self._error("AArch64 target cannot assign aggregate value")
            self._emit_address(expr.target, 11)
            self._emit_scratch_store_reg("x11", 8)
            self._emit_address(expr.value, 12)
            self._emit_scratch_load_reg("x11", 8, scratch_reg=13)
            self._emit_copy_memory(11, 12, target_size)
            return _Value(target_type, self._slot_info(target_type), target)
        if isinstance(expr.target, MemberExpr):
            target_info = self._scalar_info(target_type)
            if self._expr_contains_call(expr.target):
                access = self._emit_member_storage_address(expr.target, 11)
                self._emit_scratch_store_reg("x11", 8)
                value = self._emit_expr(expr.value, target)
                self._coerce_value(value, target_type, target_info, target)
                self._emit_scratch_load_reg("x11", 8)
                if access.bit_width is not None:
                    self._emit_bitfield_store(access, target_info, target, 11)
                else:
                    self._emit_store_to_address(target_info, target, 11)
                return _Value(target_type, target_info, target)
            value = self._emit_expr(expr.value, target)
            self._coerce_value(value, target_type, target_info, target)
            access = self._emit_member_storage_address(expr.target, 11)
            if access.bit_width is not None:
                self._emit_bitfield_store(access, target_info, target, 11)
            else:
                self._emit_store_to_address(target_info, target, 11)
            return _Value(target_type, target_info, target)
        if isinstance(expr.target, (SubscriptExpr, UnaryExpr)):
            target_info = self._scalar_info(target_type)
            if self._expr_contains_call(expr.target):
                self._emit_address(expr.target, 11)
                self._emit_scratch_store_reg("x11", 8)
                value = self._emit_expr(expr.value, target)
                self._coerce_value(value, target_type, target_info, target)
                self._emit_scratch_load_reg("x11", 8)
                self._emit_store_to_address(target_info, target, 11)
                return _Value(target_type, target_info, target)
            value = self._emit_expr(expr.value, target)
            self._coerce_value(value, target_type, target_info, target)
            self._emit_address(expr.target, 11)
            self._emit_store_to_address(target_info, target, 11)
            return _Value(target_type, target_info, target)
        if not isinstance(expr.target, Identifier):
            raise self._error("AArch64 target only supports assignment to local identifiers")
        value = self._emit_expr(expr.value, target)
        slot = self._lookup_slot(expr.target.name)
        if slot is not None:
            self._coerce_value(value, slot.type_, slot.info, target)
            self._emit_store(slot, target)
            return _Value(slot.type_, slot.info, target)
        target_type = self._expr_type(expr.target)
        target_info = self._scalar_info(target_type)
        self._coerce_value(value, target_type, target_info, target)
        self._emit_address(expr.target, 11)
        self._emit_store_to_address(target_info, target, 11)
        return _Value(target_type, target_info, target)

    def _emit_record_compound_initializer_to_address(
        self,
        type_: Type,
        init: InitList,
        address_reg: int,
    ) -> None:
        if not self._is_record_type(type_):
            raise self._error("AArch64 target only supports record compound assignment yet")
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            raise self._error(f"AArch64 target cannot initialize record {type_}")
        self._emit_scratch_store_reg(f"x{address_reg}")
        size = self._type_size(type_)
        if size is None:
            raise self._error(f"AArch64 target cannot size type {type_}")
        self._emit_zero_memory(address_reg, size)
        if type_.name.startswith("union "):
            if not init.items:
                return
            item = init.items[0]
            member_name = self._record_init_designator_name(item)
            if member_name is None:
                member_name = members[0].name
            if member_name is None or isinstance(item.initializer, InitList):
                raise self._error("AArch64 target cannot initialize union compound literal")
            access = self._record_member_access(type_.name, member_name)
            if access is None:
                raise self._error(f"AArch64 target cannot initialize member {member_name}")
            value = self._emit_expr(item.initializer, 0)
            info = self._scalar_info(access.type_)
            self._coerce_value(value, access.type_, info, 0)
            self._emit_scratch_load_reg("x11")
            if access.bit_width is not None:
                self._emit_bitfield_store(access, info, 0, 11)
            else:
                self._emit_store_to_address(info, 0, 11)
            return
        positional_index = 0
        for item in init.items:
            member_name = self._record_init_designator_name(item)
            if member_name is None:
                if positional_index >= len(members):
                    raise self._error("AArch64 target found too many record initializers")
                member = members[positional_index]
                positional_index += 1
                member_name = member.name
            if member_name is None:
                if self._is_record_type(member.type_) or member.type_.is_array():
                    continue
                positional_index += 1
                continue
            access = self._record_member_access(type_.name, member_name)
            if access is None:
                raise self._error(f"AArch64 target cannot initialize member {member_name}")
            if isinstance(item.initializer, InitList):
                if self._is_record_type(access.type_):
                    self._emit_scratch_load_reg("x11")
                    self._emit_scratch_store_reg("x11", 8)
                    if access.offset:
                        self._emit_add_byte_offset(11, "x11", access.offset)
                    self._emit_record_compound_initializer_to_address(
                        access.type_,
                        item.initializer,
                        11,
                    )
                    self._emit_scratch_load_reg("x11", 8)
                    self._emit_scratch_store_reg("x11")
                    continue
                if access.type_.is_array():
                    element_type = access.type_.element_type()
                    if element_type is None:
                        raise self._error("AArch64 target cannot resolve array element type")
                    element_size = self._type_size(element_type)
                    if element_size is None:
                        raise self._error(f"AArch64 target cannot size type {element_type}")
                    for index, array_item in enumerate(item.initializer.items):
                        if isinstance(array_item.initializer, InitList):
                            if self._is_record_type(element_type):
                                self._emit_scratch_load_reg("x11")
                                self._emit_scratch_store_reg("x11", 8)
                                elem_off = access.offset + index * element_size
                                if elem_off:
                                    self._emit_add_byte_offset(11, "x11", elem_off)
                                self._emit_record_compound_initializer_to_address(
                                    element_type,
                                    array_item.initializer,
                                    11,
                                )
                                self._emit_scratch_load_reg("x11", 8)
                                self._emit_scratch_store_reg("x11")
                            else:
                                raise self._error(
                                    "AArch64 target does not support nested array init yet"
                                )
                        elif not self._types_assignable(element_type):
                            self._emit_scratch_load_reg("x11")
                            self._emit_scratch_store_reg("x11", 8)
                            elem_off = access.offset + index * element_size
                            if elem_off:
                                self._emit_add_byte_offset(11, "x11", elem_off)
                            self._emit_scratch_store_reg("x11", 16)
                            self._emit_address(array_item.initializer, 12)
                            self._emit_scratch_load_reg("x11", 16, scratch_reg=13)
                            self._emit_copy_memory(11, 12, element_size)
                            self._emit_scratch_load_reg("x11", 8)
                            self._emit_scratch_store_reg("x11")
                        else:
                            self._emit_scratch_load_reg("x11")
                            self._emit_scratch_store_reg("x11", 8)
                            elem_off = access.offset + index * element_size
                            if elem_off:
                                self._emit_add_byte_offset(11, "x11", elem_off)
                            elem_info = self._scalar_info(element_type)
                            inner = array_item.initializer
                            if not isinstance(inner, Expr):
                                raise self._error("AArch64 target cannot initialize array element")
                            value = self._emit_expr(inner, 0)
                            self._coerce_value(value, element_type, elem_info, 0)
                            self._emit_store_to_address(elem_info, 0, 11)
                            self._emit_scratch_load_reg("x11", 8)
                            self._emit_scratch_store_reg("x11")
                    continue
                if self._types_assignable(access.type_):
                    for scalar_item in item.initializer.items:
                        if isinstance(scalar_item.initializer, Expr):
                            value = self._emit_expr(scalar_item.initializer, 0)
                            info = self._scalar_info(access.type_)
                            self._coerce_value(value, access.type_, info, 0)
                            self._emit_scratch_load_reg("x11")
                            if access.offset:
                                self._emit_add_byte_offset(11, "x11", access.offset)
                            if access.bit_width is not None:
                                self._emit_bitfield_store(access, info, 0, 11)
                            else:
                                self._emit_store_to_address(info, 0, 11)
                            break
                    continue
                raise self._error("AArch64 target does not support nested record init yet")
            if self._is_aggregate_type(access.type_) and self._is_zero_initializer(
                item.initializer
            ):
                continue
            if not self._types_assignable(access.type_):
                member_size = self._type_size(access.type_)
                value_size = self._type_size(self._expr_type(item.initializer))
                if member_size is None or value_size is None or member_size != value_size:
                    raise self._error(f"AArch64 target cannot initialize member {member_name}")
                self._emit_scratch_load_reg("x11")
                if access.offset:
                    self._emit_add_byte_offset(11, "x11", access.offset)
                self._emit_scratch_store_reg("x11", 8)
                self._emit_address(item.initializer, 12)
                self._emit_scratch_load_reg("x11", 8, scratch_reg=13)
                self._emit_copy_memory(11, 12, member_size)
                continue
            value = self._emit_expr(item.initializer, 0)
            info = self._scalar_info(access.type_)
            self._coerce_value(value, access.type_, info, 0)
            self._emit_scratch_load_reg("x11")
            if access.offset:
                self._emit_add_byte_offset(11, "x11", access.offset)
            if access.bit_width is not None:
                self._emit_bitfield_store(access, info, 0, 11)
            else:
                self._emit_store_to_address(info, 0, 11)

    def _emit_aggregate_expr_to_address(
        self,
        type_: Type,
        expr: Expr,
        address_reg: int,
    ) -> None:
        size = self._type_size(type_)
        if size is None:
            raise self._error(f"AArch64 target cannot size type {type_}")
        if isinstance(expr, ConditionalExpr):
            false_label = self._new_label("aggregate_init_false")
            end_label = self._new_label("aggregate_init_end")
            self._emit_scratch_store_reg(f"x{address_reg}", 8)
            self._emit_branch_if_zero(expr.condition, false_label)
            self._emit_scratch_load_reg(f"x{address_reg}", 8)
            self._emit_aggregate_expr_to_address(type_, expr.then_expr, address_reg)
            self._emit(f"b {end_label}")
            self._lines.append(f"{false_label}:")
            self._emit_scratch_load_reg(f"x{address_reg}", 8)
            self._emit_aggregate_expr_to_address(type_, expr.else_expr, address_reg)
            self._lines.append(f"{end_label}:")
            return
        if isinstance(expr, CompoundLiteralExpr) and self._is_record_type(type_):
            self._emit_record_compound_initializer_to_address(type_, expr.initializer, address_reg)
            return
        if self._is_zero_initializer(expr):
            self._emit_zero_memory(address_reg, size)
            return
        value_size = self._type_size(self._expr_type(expr))
        if value_size is None or value_size != size:
            raise self._error("AArch64 target cannot initialize aggregate local")
        self._emit_scratch_store_reg(f"x{address_reg}", 8)
        self._emit_address(expr, 12)
        self._emit_scratch_load_reg(f"x{address_reg}", 8, scratch_reg=13)
        self._emit_copy_memory(address_reg, 12, size)

    def _emit_compound_literal_to_slot(self, expr: CompoundLiteralExpr) -> _Slot:
        slot = self._compound_literal_slots.get(id(expr))
        if slot is None:
            raise self._error("AArch64 target cannot allocate compound literal")
        if slot.type_.is_array():
            self._emit_local_array_initializer(slot, expr.initializer)
            return slot
        if self._is_record_type(slot.type_):
            self._emit_add_byte_offset(11, "sp", slot.offset)
            self._emit_record_compound_initializer_to_address(slot.type_, expr.initializer, 11)
            return slot
        if len(expr.initializer.items) != 1 or expr.initializer.items[0].designators:
            raise self._error("AArch64 target cannot initialize scalar compound literal")
        inner = expr.initializer.items[0].initializer
        assert isinstance(inner, Expr)
        value = self._emit_expr(inner, 0)
        self._coerce_value(value, slot.type_, slot.info, 0)
        self._emit_store(slot, 0)
        return slot

    def _emit_compound_literal(self, expr: CompoundLiteralExpr, target: int) -> _Value:
        slot = self._emit_compound_literal_to_slot(expr)
        if not self._types_assignable(slot.type_):
            self._emit_add_byte_offset(target, "sp", slot.offset)
            return _Value(slot.type_, _ScalarInfo(8, 8, False), target)
        self._emit_load(slot, target)
        return _Value(slot.type_, slot.info, target)

    @staticmethod
    def _record_init_designator_name(item: InitItem) -> str | None:
        if not item.designators:
            return None
        if len(item.designators) != 1:
            return None
        kind, value = item.designators[0]
        if kind == "member" and isinstance(value, str):
            return value
        return None

    def _emit_zero_memory(self, address_reg: int, size: int) -> None:
        offset = 0
        while size - offset >= 8:
            self._emit(f"str xzr, [x{address_reg}, #{offset}]")
            offset += 8
        if size - offset >= 4:
            self._emit(f"str wzr, [x{address_reg}, #{offset}]")
            offset += 4
        while offset < size:
            self._emit(f"strb wzr, [x{address_reg}, #{offset}]")
            offset += 1

    def _emit_copy_memory(self, dst_reg: int, src_reg: int, size: int) -> None:
        offset = 0
        while size - offset >= 8:
            self._emit(f"ldr x9, [x{src_reg}, #{offset}]")
            self._emit(f"str x9, [x{dst_reg}, #{offset}]")
            offset += 8
        if size - offset >= 4:
            self._emit(f"ldr w9, [x{src_reg}, #{offset}]")
            self._emit(f"str w9, [x{dst_reg}, #{offset}]")
            offset += 4
        while offset < size:
            self._emit(f"ldrb w9, [x{src_reg}, #{offset}]")
            self._emit(f"strb w9, [x{dst_reg}, #{offset}]")
            offset += 1

    def _emit_compound_assign(self, expr: AssignExpr, target: int) -> _Value:
        op = expr.op[:-1]
        if isinstance(expr.target, MemberExpr):
            access = self._emit_member_storage_address(expr.target, 11)
            if access.bit_width is not None:
                self._emit_scratch_store_reg("x11")
                value = self._emit_expr(expr.value, target)
                target_type = self._expr_type(expr.target)
                target_info = self._scalar_info(target_type)
                self._coerce_value(value, target_type, target_info, target)
                self._emit_scratch_load_reg("x11")
                self._emit_bitfield_load(access, target_info, 9, 11)
                self._emit_compound_integer_op(op, target_info, target)
                self._emit_bitfield_store(access, target_info, target, 11)
                return _Value(target_type, target_info, target)
        if isinstance(expr.target, (SubscriptExpr, MemberExpr, UnaryExpr)):
            self._emit_address(expr.target, 11)
            self._emit_scratch_store_reg("x11")
            value = self._emit_expr(expr.value, target)
            target_type = self._expr_type(expr.target)
            target_info = self._scalar_info(target_type)
            self._emit_scratch_load_reg("x11")
            self._emit_load_from_address(target_info, 9, 11)
            if self._is_pointer_type(target_type) and op in {"+", "-"}:
                self._emit_pointer_step(value, target, target_type)
                instruction = "add" if op == "+" else "sub"
                self._emit(f"{instruction} x{target}, x9, x{target}")
            else:
                self._coerce_value(value, target_type, target_info, target)
                if target_info.is_float:
                    float_instruction = {
                        "+": "fadd",
                        "-": "fsub",
                        "*": "fmul",
                        "/": "fdiv",
                    }.get(op)
                    if float_instruction is None:
                        raise self._error(
                            f"AArch64 target does not support assignment operator {expr.op}"
                        )
                    self._emit(
                        f"{float_instruction} {self._reg(target, target_info)}, "
                        f"{self._reg(9, target_info)}, {self._reg(target, target_info)}"
                    )
                else:
                    self._emit_compound_integer_op(op, target_info, target)
            self._emit_store_to_address(target_info, target, 11)
            return _Value(target_type, target_info, target)
        if not isinstance(expr.target, Identifier):
            raise self._error(
                "AArch64 target only supports compound assignment on local identifiers or lvalues"
            )
        slot = self._lookup_slot(expr.target.name)
        target_type = self._expr_type(expr.target)
        target_info = self._scalar_info(target_type)
        if slot is not None:
            self._emit_load(slot, 9)
            left = _Value(slot.type_, slot.info, 9)
            left_spill = self._spill_binary_left_value(left)
            value = self._emit_expr(expr.value, target)
            self._restore_binary_left_value(left, left_spill)
            if self._is_pointer_type(slot.type_) and op in {"+", "-"}:
                self._emit_pointer_step(value, target, slot.type_)
                instruction = "add" if op == "+" else "sub"
                self._emit(f"{instruction} x{target}, x9, x{target}")
            else:
                self._coerce_value(value, slot.type_, slot.info, target)
                if slot.info.is_float:
                    float_instruction = {
                        "+": "fadd",
                        "-": "fsub",
                        "*": "fmul",
                        "/": "fdiv",
                    }.get(op)
                    if float_instruction is None:
                        raise self._error(
                            f"AArch64 target does not support assignment operator {expr.op}"
                        )
                    self._emit(
                        f"{float_instruction} {self._reg(target, slot.info)}, "
                        f"{self._reg(9, slot.info)}, {self._reg(target, slot.info)}"
                    )
                else:
                    self._emit_compound_integer_op(op, slot.info, target)
            self._emit_store(slot, target)
            return _Value(slot.type_, slot.info, target)
        self._emit_address(expr.target, 11)
        self._emit_scratch_store_reg("x11", 8)
        value = self._emit_expr(expr.value, target)
        self._emit_scratch_load_reg("x11", 8)
        self._emit_load_from_address(target_info, 9, 11)
        if self._is_pointer_type(target_type) and op in {"+", "-"}:
            self._emit_pointer_step(value, target, target_type)
            instruction = "add" if op == "+" else "sub"
            self._emit(f"{instruction} x{target}, x9, x{target}")
        else:
            self._coerce_value(value, target_type, target_info, target)
            if target_info.is_float:
                float_instruction = {
                    "+": "fadd",
                    "-": "fsub",
                    "*": "fmul",
                    "/": "fdiv",
                }.get(op)
                if float_instruction is None:
                    raise self._error(
                        f"AArch64 target does not support assignment operator {expr.op}"
                    )
                self._emit(
                    f"{float_instruction} {self._reg(target, target_info)}, "
                    f"{self._reg(9, target_info)}, {self._reg(target, target_info)}"
                )
            else:
                self._emit_compound_integer_op(op, target_info, target)
        self._emit_store_to_address(target_info, target, 11)
        return _Value(target_type, target_info, target)

    def _emit_compound_integer_op(self, op: str, info: _ScalarInfo, target: int) -> None:
        left = self._reg(9, info)
        right = self._reg(target, info)
        dst = self._reg(target, info)
        instruction = {
            "+": "add",
            "-": "sub",
            "*": "mul",
            "|": "orr",
            "&": "and",
            "^": "eor",
        }.get(op)
        if instruction is not None:
            self._emit(f"{instruction} {dst}, {left}, {right}")
            return
        if op == "/":
            instruction = "sdiv" if info.signed else "udiv"
            self._emit(f"{instruction} {dst}, {left}, {right}")
            return
        if op == "%":
            quotient = self._reg(11, info)
            instruction = "sdiv" if info.signed else "udiv"
            self._emit(f"{instruction} {quotient}, {left}, {right}")
            self._emit(f"msub {dst}, {quotient}, {right}, {left}")
            return
        if op == "<<":
            self._emit(f"lsl {dst}, {left}, {right}")
            return
        if op == ">>":
            instruction = "asr" if info.signed else "lsr"
            self._emit(f"{instruction} {dst}, {left}, {right}")
            return
        raise self._error(f"AArch64 target does not support assignment operator {op}=")

    def _emit_add_immediate(self, info: _ScalarInfo, reg: int, value: int) -> None:
        instruction = "add" if value >= 0 else "sub"
        self._emit(f"{instruction} {self._reg(reg, info)}, {self._reg(reg, info)}, #{abs(value)}")

    def _emit_add_byte_offset(
        self,
        dst_reg: int,
        base: str,
        offset: int,
        scratch_reg: int | None = None,
    ) -> None:
        dst = f"x{dst_reg}"
        if 0 <= offset <= 4095:
            self._emit(f"add {dst}, {base}, #{offset}")
            return
        if scratch_reg is None:
            scratch_reg = 12 if dst_reg != 12 else 13
        if scratch_reg == dst_reg:
            scratch_reg = 12 if dst_reg != 12 else 13
        if base == "sp":
            self._emit(f"mov {dst}, sp")
            self._emit_load_immediate(f"x{scratch_reg}", offset, 64)
            self._emit(f"add {dst}, {dst}, x{scratch_reg}")
            return
        if base == dst:
            self._emit_load_immediate(f"x{scratch_reg}", offset, 64)
            self._emit(f"add {dst}, {dst}, x{scratch_reg}")
            return
        self._emit_load_immediate(dst, offset, 64)
        self._emit(f"add {dst}, {base}, {dst}")

    def _emit_cast(self, expr: CastExpr, target: int) -> _Value:
        target_type = self._expr_type(expr)
        if self._is_void_type(target_type):
            if self._expr_has_side_effect(expr.expr):
                self._emit_expr(expr.expr, target)
            return _Value(target_type, _ScalarInfo(4, 4, False), target)
        value = self._emit_expr(expr.expr, target)
        target_info = self._scalar_info(target_type)
        self._coerce_value(value, target_type, target_info, target)
        return _Value(target_type, target_info, target)

    def _emit_stack_load_reg(
        self,
        reg: str,
        offset: int,
        address_reg: int = 11,
        scratch_reg: int | None = None,
    ) -> None:
        if 0 <= offset <= 255:
            self._emit(f"ldr {reg}, [sp, #{offset}]")
            return
        self._emit_add_byte_offset(address_reg, "sp", offset, scratch_reg=scratch_reg)
        self._emit(f"ldr {reg}, [x{address_reg}]")

    def _emit_stack_store_reg(
        self,
        reg: str,
        offset: int,
        address_reg: int = 11,
        scratch_reg: int | None = None,
    ) -> None:
        if 0 <= offset <= 255:
            self._emit(f"str {reg}, [sp, #{offset}]")
            return
        safe_address_reg = self._stack_store_address_reg(reg, address_reg)
        self._emit_add_byte_offset(safe_address_reg, "sp", offset, scratch_reg=scratch_reg)
        self._emit(f"str {reg}, [x{safe_address_reg}]")

    def _emit_scratch_load_reg(
        self,
        reg: str,
        offset: int = 0,
        sp_adjust: int = 0,
        address_reg: int = 11,
        scratch_reg: int | None = None,
    ) -> None:
        self._emit_stack_load_reg(
            reg,
            self._scratch_offset(offset, sp_adjust),
            address_reg,
            scratch_reg,
        )

    def _emit_scratch_store_reg(
        self,
        reg: str,
        offset: int = 0,
        sp_adjust: int = 0,
        address_reg: int = 11,
        scratch_reg: int | None = None,
    ) -> None:
        self._emit_stack_store_reg(
            reg,
            self._scratch_offset(offset, sp_adjust),
            address_reg,
            scratch_reg,
        )

    def _emit_load(self, slot: _Slot, target: int) -> None:
        offset = self._slot_addr(slot)
        if slot.offset > 255:
            address_reg = 11 if target != 11 else 12
            self._emit_add_byte_offset(address_reg, "sp", slot.offset)
            self._emit_load_from_address(slot.info, target, address_reg)
            return
        reg = self._reg(target, slot.info)
        if slot.info.is_float:
            self._emit(f"ldr {reg}, {offset}")
            return
        if slot.info.size == 1:
            instruction = "ldrsb" if slot.info.signed else "ldrb"
            self._emit(f"{instruction} w{target}, {offset}")
            return
        if slot.info.size == 2:
            instruction = "ldrsh" if slot.info.signed else "ldrh"
            self._emit(f"{instruction} w{target}, {offset}")
            return
        self._emit(f"ldr {reg}, {offset}")

    def _emit_store(self, slot: _Slot, source: int) -> None:
        offset = self._slot_addr(slot)
        if slot.offset > 255:
            address_reg = 11 if source != 11 else 12
            self._emit_add_byte_offset(address_reg, "sp", slot.offset)
            self._emit_store_to_address(slot.info, source, address_reg)
            return
        if slot.info.is_float:
            self._emit(f"str {self._reg(source, slot.info)}, {offset}")
            return
        if slot.info.size == 1:
            self._emit(f"strb w{source}, {offset}")
            return
        if slot.info.size == 2:
            self._emit(f"strh w{source}, {offset}")
            return
        self._emit(f"str {self._reg(source, slot.info)}, {offset}")

    def _emit_load_from_address(self, info: _ScalarInfo, target: int, address_reg: int) -> None:
        if info.is_float:
            self._emit(f"ldr {self._reg(target, info)}, [x{address_reg}]")
            return
        if info.size == 1:
            instruction = "ldrsb" if info.signed else "ldrb"
            self._emit(f"{instruction} w{target}, [x{address_reg}]")
            return
        if info.size == 2:
            instruction = "ldrsh" if info.signed else "ldrh"
            self._emit(f"{instruction} w{target}, [x{address_reg}]")
            return
        self._emit(f"ldr {self._reg(target, info)}, [x{address_reg}]")

    def _emit_store_to_address(self, info: _ScalarInfo, source: int, address_reg: int) -> None:
        if info.is_float:
            self._emit(f"str {self._reg(source, info)}, [x{address_reg}]")
            return
        if info.size == 1:
            self._emit(f"strb w{source}, [x{address_reg}]")
            return
        if info.size == 2:
            self._emit(f"strh w{source}, [x{address_reg}]")
            return
        self._emit(f"str {self._reg(source, info)}, [x{address_reg}]")

    def _emit_address(self, expr: Expr, target_reg: int) -> Type:
        if isinstance(expr, Identifier):
            slot = self._lookup_slot(expr.name)
            if (
                slot is not None
                and slot.type_.declarator_ops
                and slot.type_.declarator_ops[0][0] == "arr"
            ):
                self._emit_add_byte_offset(target_reg, "sp", slot.offset)
                return slot.type_
            if (
                slot is not None
                and slot.type_.declarator_ops
                and slot.type_.declarator_ops[0][0] == "ptr"
            ):
                self._emit_load(slot, target_reg)
                return slot.type_
            if slot is not None and not self._types_assignable(slot.type_):
                self._emit_add_byte_offset(target_reg, "sp", slot.offset)
                return slot.type_
            if slot is not None:
                self._emit_add_byte_offset(target_reg, "sp", slot.offset)
                return slot.type_
            if expr.name in self._sema.function_signatures:
                self._emit_function_address(expr.name, target_reg)
                return self._function_designator_value_type(self._expr_type(expr))
            static_local = self._static_local(expr.name)
            if static_local is not None:
                self._emit(f"adrp x{target_reg}, {static_local.label}@PAGE")
                self._emit(f"add x{target_reg}, x{target_reg}, {static_local.label}@PAGEOFF")
                return static_local.type_
            if self._func_sym is not None:
                symbol = self._func_sym.locals.get(expr.name)
                if isinstance(symbol, VarSymbol) and symbol.is_extern:
                    label = self._symbol_name(expr.name)
                    self._emit_extern_data_address(label, target_reg)
                    return symbol.type_
            global_ = self._globals.get(expr.name)
            if global_ is not None:
                self._emit(f"adrp x{target_reg}, {global_.label}@PAGE")
                self._emit(f"add x{target_reg}, x{target_reg}, {global_.label}@PAGEOFF")
                return global_.type_
            if self._sema.file_scope is not None:
                symbol = self._sema.file_scope.lookup(expr.name)
                if isinstance(symbol, VarSymbol) and symbol.is_extern:
                    label = self._symbol_name(expr.name)
                    self._emit_extern_data_address(label, target_reg)
                    return symbol.type_
            raise self._error(f"AArch64 target cannot take address of {expr.name}")
        if isinstance(expr, StringLiteral):
            self._emit_string_literal(expr, target_reg)
            return self._expr_type(expr)
        if isinstance(expr, CastExpr):
            value = self._emit_expr(expr, target_reg)
            if value.type_.pointee() is None:
                raise self._error("AArch64 target cannot address non-pointer cast")
            return value.type_
        if isinstance(expr, CallExpr):
            result_type = self._expr_type(expr)
            if self._is_record_type(result_type):
                slot = self._indirect_call_slots.get(id(expr))
                if slot is None:
                    raise self._error("AArch64 target missing record call result slot")
                fields = self._record_return_fields(result_type)
                if fields is None:
                    self._emit_call(expr, 0, indirect_result_slot=slot)
                else:
                    self._emit_call(expr, 0)
                    self._emit_add_byte_offset(11, "sp", slot.offset)
                    for index, (offset, _, info) in enumerate(fields):
                        address_reg = 11
                        if offset:
                            address_reg = 12
                            self._emit_add_byte_offset(address_reg, "x11", offset)
                        self._emit_store_to_address(info, index, address_reg)
                self._emit_add_byte_offset(target_reg, "sp", slot.offset)
                return slot.type_
            value = self._emit_call(expr, target_reg)
            if value.type_.pointee() is None:
                raise self._error("AArch64 target cannot address non-pointer call result")
            return value.type_
        if isinstance(expr, CompoundLiteralExpr):
            slot = self._emit_compound_literal_to_slot(expr)
            self._emit_add_byte_offset(target_reg, "sp", slot.offset)
            return slot.type_
        if isinstance(expr, CommaExpr):
            self._emit_expr(expr.left, target_reg)
            return self._emit_address(expr.right, target_reg)
        if isinstance(expr, SubscriptExpr):
            index_reg = self._subscript_index_reg(target_reg)
            base_contains_call = self._expr_contains_call(expr.base)
            self._subscript_index_regs.append(index_reg)
            try:
                if base_contains_call:
                    base_type = self._emit_subscript_base_address(expr.base, target_reg)
                    self._emit_scratch_store_reg(f"x{target_reg}", 8)
                    index_value = self._emit_expr(expr.index, index_reg)
                else:
                    index_value = self._emit_expr(expr.index, index_reg)
                    base_type = self._emit_subscript_base_address(expr.base, target_reg)
                if index_value.info.size < 8:
                    if index_value.info.signed:
                        self._emit(f"sxtw x{index_reg}, w{index_reg}")
                    else:
                        self._emit(f"mov w{index_reg}, w{index_reg}")
                if base_contains_call:
                    self._emit_scratch_load_reg(f"x{target_reg}", 8)
                element_type = self._subscript_element_type(base_type)
                if element_type is None:
                    raise self._error("AArch64 target cannot subscript non-pointer type")
                element_size = self._type_size(element_type)
                if element_size is None:
                    raise self._error(f"AArch64 target cannot size type {element_type}")
                if element_size > 1:
                    shift = element_size.bit_length() - 1
                    if 1 << shift == element_size:
                        self._emit(f"add x{target_reg}, x{target_reg}, x{index_reg}, lsl #{shift}")
                    else:
                        scale_reg = self._available_reg(
                            {target_reg, index_reg, *self._subscript_index_regs},
                            (12, 13, 11, 9, 14, 15),
                        )
                        self._emit_load_immediate(f"x{scale_reg}", element_size, 64)
                        self._emit(f"mul x{index_reg}, x{index_reg}, x{scale_reg}")
                        self._emit(f"add x{target_reg}, x{target_reg}, x{index_reg}")
                else:
                    self._emit(f"add x{target_reg}, x{target_reg}, x{index_reg}")
                return element_type
            finally:
                self._subscript_index_regs.pop()
        if isinstance(expr, MemberExpr):
            access = self._emit_member_storage_address(expr, target_reg)
            if access.bit_width is not None:
                raise self._error("AArch64 target cannot take address of bit-field member")
            return access.type_
        if isinstance(expr, UnaryExpr) and expr.op == "*":
            value = self._emit_expr(expr.operand, target_reg)
            pointee = value.type_.pointee()
            if pointee is None:
                pointee = value.type_.element_type()
            if pointee is None:
                raise self._error("AArch64 target cannot dereference non-pointer type")
            return pointee
        raise self._error(f"AArch64 target cannot address {type(expr).__name__}")

    def _record_name_from_type(self, type_: Type) -> str | None:
        base = type_
        while base.declarator_ops:
            base = Type(
                base.name,
                declarator_ops=base.declarator_ops[1:],
                qualifiers=base.qualifiers,
            )
        if base.name.startswith(("struct ", "union ")):
            return base.name
        if self._sema.file_scope is not None:
            resolved = self._sema.file_scope.lookup_typedef(base.name)
            if resolved is not None:
                if resolved.name.startswith(("struct ", "union ")):
                    return resolved.name
                sub = self._record_name_from_type(resolved)
                if sub is not None:
                    return sub
        for key in self._sema.record_definitions:
            if key.endswith(" " + base.name) or key == base.name:
                return key
        if not base.name.startswith(("struct ", "union ")):
            for key in self._sema.record_definitions:
                if key.startswith("struct ") or key.startswith("union "):
                    return key
        return None

    def _emit_subscript_base_address(self, expr: Expr, target_reg: int) -> Type:
        type_ = self._expr_type(expr)
        if type_.is_array():
            return self._emit_address(expr, target_reg)
        if type_.pointee() is not None:
            value = self._emit_expr(expr, target_reg)
            return value.type_
        return self._emit_address(expr, target_reg)

    def _subscript_index_reg(self, target_reg: int) -> int:
        return self._available_reg(
            {target_reg, *self._subscript_index_regs},
            (10, 12, 13, 9, 14, 15),
        )

    def _emit_member_storage_address(
        self,
        expr: MemberExpr,
        target_reg: int,
    ) -> _MemberAccess:
        if expr.through_pointer:
            base_value = self._emit_expr(expr.base, target_reg)
            record_type = base_value.type_.pointee()
            if record_type is None:
                raise self._error("AArch64 target cannot use -> on non-pointer type")
        else:
            record_type = self._emit_address(expr.base, target_reg)
        record_name = self._record_name_from_type(record_type)
        if record_name is None and record_type.name in ("struct", "union"):
            for key in self._sema.record_definitions:
                if key.startswith(record_type.name + " "):
                    record_name = key
                    break
        if record_name is None:
            raise self._error(
                f"AArch64 target cannot access member .{expr.member} of type {record_type.name}"
            )
        access = self._record_member_access(record_name, expr.member)
        if access is None:
            for rec_name in self._sema.record_definitions:
                access = self._record_member_access(rec_name, expr.member)
                if access is not None:
                    break
        if access is None:
            raise self._error(f"AArch64 target cannot find member {expr.member} in {record_name}")
        if access.offset:
            self._emit_add_byte_offset(target_reg, f"x{target_reg}", access.offset)
        return access

    def _emit_address_of(self, expr: Expr, target: int) -> _Value:
        if isinstance(expr, Identifier):
            slot = self._lookup_slot(expr.name)
            if slot is not None:
                self._emit_add_byte_offset(target, "sp", slot.offset)
                return _Value(slot.type_.pointer_to(), _ScalarInfo(8, 8, False), target)
        self._emit_address(expr, target)
        result_type = self._expr_type(expr).pointer_to()
        return _Value(result_type, _ScalarInfo(8, 8, False), target)

    def _coerce_value(
        self,
        value: _Value,
        target_type: Type,
        target_info: _ScalarInfo,
        reg: int,
    ) -> None:
        if value.info.is_float or target_info.is_float:
            if value.info.is_float and not target_info.is_float:
                instruction = "fcvtzs" if target_info.signed else "fcvtzu"
                self._emit(
                    f"{instruction} {self._reg(reg, target_info)}, {self._reg(reg, value.info)}"
                )
                return
            if not value.info.is_float and target_info.is_float:
                instruction = "scvtf" if value.info.signed else "ucvtf"
                self._emit(
                    f"{instruction} {self._reg(reg, target_info)}, {self._reg(reg, value.info)}"
                )
                return
            if value.info.size != target_info.size:
                instruction = "fcvt"
                self._emit(
                    f"{instruction} {self._reg(reg, target_info)}, {self._reg(reg, value.info)}"
                )
            if not self._types_assignable(target_type):
                raise self._error(f"AArch64 target does not support scalar type {target_type}")
            return
        if value.info.size < target_info.size:
            if value.info.signed:
                instruction = "sxtw" if value.info.size >= 4 else "sxtb"
                if value.info.size == 2:
                    instruction = "sxth"
                self._emit(f"{instruction} {self._reg(reg, target_info)}, w{reg}")
            elif target_info.size == 8:
                self._emit(f"mov w{reg}, w{reg}")
        elif value.info.size > target_info.size:
            mask = (1 << target_info.bits) - 1
            if mask <= 65535:
                self._emit(f"and w{reg}, w{reg}, #{mask}")
        if target_info.size < 4:
            if target_info.signed:
                instruction = "sxtb" if target_info.size == 1 else "sxth"
                self._emit(f"{instruction} w{reg}, w{reg}")
            else:
                mask = (1 << target_info.bits) - 1
                self._emit(f"and w{reg}, w{reg}, #{mask}")
        if not self._types_assignable(target_type):
            raise self._error(f"AArch64 target does not support scalar type {target_type}")

    @staticmethod
    def _comparison_condition(op: str, signed: bool) -> str:
        if op == "==":
            return "eq"
        if op == "!=":
            return "ne"
        if op == "<":
            return "lt" if signed else "lo"
        if op == "<=":
            return "le" if signed else "ls"
        if op == ">":
            return "gt" if signed else "hi"
        if op == ">=":
            return "ge" if signed else "hs"
        raise AssertionError(f"unhandled comparison op: {op}")

    def _emit_compare_zero(self, info: _ScalarInfo, reg: int) -> None:
        if info.is_float:
            self._emit(f"fcmp {self._reg(reg, info)}, #0.0")
            return
        self._emit(f"cmp {self._reg(reg, info)}, #0")

    def _expr_type(self, expr: Expr) -> Type:
        type_ = self._type_map.get(expr)
        return INT if type_ is None else type_

    def _resolve_type_spec(self, type_spec: TypeSpec) -> Type:
        typedef = None
        if self._sema.file_scope is not None:
            typedef = self._sema.file_scope.lookup_typedef(type_spec.name)
        if typedef is not None:
            base = typedef
        elif type_spec.name in {"struct", "union"}:
            base = Type(
                self._record_name_for_type_spec(type_spec),
                qualifiers=type_spec.qualifiers,
            )
        elif type_spec.name == "enum":
            base = INT
        elif type_spec.name == "typeof" and type_spec.typeof_expr is not None:
            typeof_base = self._type_map.get(type_spec.typeof_expr)
            if typeof_base is None:
                raise self._error("AArch64 target cannot resolve typeof expression")
            base = typeof_base
        else:
            base = Type(type_spec.name, qualifiers=type_spec.qualifiers)
        ops: list[tuple[str, int | tuple[tuple[Type, ...] | None, bool]]] = []
        for kind, value in type_spec.declarator_ops:
            if kind == "arr":
                ops.append(("arr", value if isinstance(value, int) else -1))
            elif kind == "ptr":
                ops.append(("ptr", 0))
            elif kind == "fn":
                param_specs, is_variadic = cast(
                    "tuple[tuple[TypeSpec, ...] | None, bool]",
                    value,
                )
                assert param_specs is None or isinstance(param_specs, tuple)
                param_types = (
                    None
                    if param_specs is None
                    else tuple(self._resolve_type_spec(param) for param in param_specs)
                )
                assert isinstance(is_variadic, bool)
                ops.append(("fn", (param_types, is_variadic)))
        ops.extend(base.declarator_ops)
        return Type(base.name, declarator_ops=tuple(ops), qualifiers=base.qualifiers)

    def _record_name_for_type_spec(self, type_spec: TypeSpec) -> str:
        if type_spec.record_tag is not None:
            if self._sema.file_scope is not None:
                scoped = self._sema.file_scope.lookup_record_tag(
                    type_spec.name, type_spec.record_tag
                )
                if scoped is not None:
                    return scoped
            candidates = [
                record_name
                for record_name in self._sema.record_definitions
                if record_name == f"{type_spec.name} {type_spec.record_tag}"
                or record_name.startswith(f"{type_spec.name} {type_spec.record_tag} <scope:")
            ]
            if type_spec.record_members:
                matched = [
                    record_name
                    for record_name in candidates
                    if self._record_members_match_type_spec(record_name, type_spec)
                ]
                if len(matched) == 1:
                    return matched[0]
            elif len(candidates) == 1:
                return candidates[0]
            return f"{type_spec.name} {type_spec.record_tag}"
        if type_spec.record_members:
            for record_name, _members in self._sema.record_definitions.items():
                if not record_name.startswith(f"{type_spec.name} <anon:"):
                    continue
                if self._record_members_match_type_spec(record_name, type_spec):
                    return record_name
        return type_spec.name

    def _record_members_match_type_spec(self, record_name: str, type_spec: TypeSpec) -> bool:
        members = self._sema.record_definitions.get(record_name)
        if members is None or len(members) != len(type_spec.record_members):
            return False
        for declaration, member in zip(type_spec.record_members, members, strict=True):
            if declaration.name != member.name:
                return False
            if self._resolve_type_spec(declaration.type_spec) != member.type_:
                return False
        return True

    def _type_size(self, type_: Type) -> int | None:
        if type_.declarator_ops:
            kind, value = type_.declarator_ops[0]
            if kind == "ptr":
                return 8
            if kind == "arr":
                if isinstance(value, int) and value < 0:
                    return 0
                if not isinstance(value, int):
                    return None
                elem_size = self._type_size(
                    Type(type_.name, declarator_ops=type_.declarator_ops[1:])
                )
                return None if elem_size is None else elem_size * value
            return None
        scalar_size = {
            "_Bool": 1,
            "bool": 1,
            "char": 1,
            "signed char": 1,
            "unsigned char": 1,
            "short": 2,
            "unsigned short": 2,
            "int": 4,
            "unsigned int": 4,
            "long": 8,
            "unsigned long": 8,
            "long long": 8,
            "unsigned long long": 8,
            "__int128_t": 16,
            "__uint128_t": 16,
            "float": 4,
            "double": 8,
            "long double": 8,
        }.get(type_.name)
        if scalar_size is not None:
            return scalar_size
        return self._record_size(type_)

    def _type_align(self, type_: Type) -> int | None:
        if type_.declarator_ops:
            return (
                8
                if type_.declarator_ops[0][0] == "ptr"
                else self._type_align(Type(type_.name, declarator_ops=type_.declarator_ops[1:]))
            )
        scalar_align = {
            "_Bool": 1,
            "bool": 1,
            "char": 1,
            "signed char": 1,
            "unsigned char": 1,
            "short": 2,
            "unsigned short": 2,
            "int": 4,
            "unsigned int": 4,
            "long": 8,
            "unsigned long": 8,
            "long long": 8,
            "unsigned long long": 8,
            "__int128_t": 16,
            "__uint128_t": 16,
            "float": 4,
            "double": 8,
            "long double": 8,
        }.get(type_.name)
        if scalar_align is not None:
            return scalar_align
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            return None
        alignments = [self._type_align(member.type_) for member in members]
        valid_alignments = [alignment for alignment in alignments if alignment is not None]
        return max(valid_alignments, default=1)

    def _record_size(self, type_: Type) -> int | None:
        record_name = self._record_name_from_type(type_)
        if record_name is not None:
            type_ = Type(record_name)
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            return None
        if type_.name.startswith("union "):
            sizes = [self._type_size(member.type_) for member in members]
            valid_sizes = [size for size in sizes if size is not None]
            align = self._type_align(type_)
            if align is None:
                return None
            return self._align_to(max(valid_sizes, default=0), align)
        offset = 0
        max_align = 1
        active_bit_base = 0
        active_bit_size = 0
        active_bit_used = 0
        active_bit_type: Type | None = None
        for index, member in enumerate(members):
            member_size = self._type_size(member.type_)
            member_align = self._type_align(member.type_)
            is_flexible = self._is_trailing_flexible_array_member(members, index)
            if member_align is None or (member_size is None and not is_flexible):
                return None
            max_align = max(max_align, member_align)
            if member.bit_width is not None:
                if member_size is None:
                    return None
                if member.bit_width == 0:
                    if active_bit_type is not None:
                        offset = active_bit_base + active_bit_size
                    offset = self._align_to(offset, member_align)
                    active_bit_type = None
                    active_bit_used = 0
                    continue
                member_bits = member_size * 8
                if (
                    active_bit_type != member.type_
                    or active_bit_used + member.bit_width > member_bits
                ):
                    if active_bit_type is not None:
                        offset = active_bit_base + active_bit_size
                    offset = self._align_to(offset, member_align)
                    active_bit_base = offset
                    active_bit_size = member_size
                    active_bit_used = 0
                    active_bit_type = member.type_
                active_bit_used += member.bit_width
                continue
            if active_bit_type is not None:
                offset = active_bit_base + active_bit_size
                active_bit_type = None
                active_bit_used = 0
            offset = self._align_to(offset, member_align)
            if member_size is None:
                continue
            offset += member_size
        if active_bit_type is not None:
            offset = active_bit_base + active_bit_size
        return self._align_to(offset, max_align)

    def _scalar_info(self, type_: Type) -> _ScalarInfo:
        if type_.declarator_ops:
            if type_.declarator_ops[0][0] == "ptr":
                return _ScalarInfo(8, 8, False)
            if type_.declarator_ops[0][0] == "fn":
                return _ScalarInfo(8, 8, False)
            raise self._error(f"AArch64 target does not support scalar type {type_}")
        union_info = self._scalar_union_info(type_)
        if union_info is not None:
            return union_info
        by_name = {
            "_Bool": _ScalarInfo(1, 1, False),
            "bool": _ScalarInfo(1, 1, False),
            "char": _ScalarInfo(1, 1, True),
            "signed char": _ScalarInfo(1, 1, True),
            "unsigned char": _ScalarInfo(1, 1, False),
            "short": _ScalarInfo(2, 2, True),
            "unsigned short": _ScalarInfo(2, 2, False),
            "int": _ScalarInfo(4, 4, True),
            "unsigned int": _ScalarInfo(4, 4, False),
            "long": _ScalarInfo(8, 8, True),
            "unsigned long": _ScalarInfo(8, 8, False),
            "long long": _ScalarInfo(8, 8, True),
            "unsigned long long": _ScalarInfo(8, 8, False),
            "float": _ScalarInfo(4, 4, True, True),
            "double": _ScalarInfo(8, 8, True, True),
            "long double": _ScalarInfo(8, 8, True, True),
            "__builtin_va_list": _ScalarInfo(8, 8, False),
        }
        info = by_name.get(type_.name)
        if info is None:
            raise self._error(f"AArch64 target does not support scalar type {type_}")
        return info

    def _slot_info(self, type_: Type) -> _ScalarInfo:
        if self._types_assignable(type_):
            return self._scalar_info(type_)
        size = self._type_size(type_)
        align = self._type_align(type_)
        if size is None or align is None:
            raise self._error(f"AArch64 target cannot allocate local type {type_}")
        return _ScalarInfo(size, align, False)

    @staticmethod
    def _is_pointer_type(type_: Type) -> bool:
        return type_.pointee() is not None

    def _is_pointer_binary(self, op: str, left_type: Type, right_type: Type) -> bool:
        left_is_pointer = self._is_pointer_type(left_type)
        right_is_pointer = self._is_pointer_type(right_type)
        if op in {"==", "!="}:
            return left_is_pointer or right_is_pointer
        if op in {"<", "<=", ">", ">="}:
            return left_is_pointer and right_is_pointer
        left_is_integer = is_integer_type(unqualified_type(left_type))
        right_is_integer = is_integer_type(unqualified_type(right_type))
        if op == "+":
            return (left_is_pointer and right_is_integer) or (right_is_pointer and left_is_integer)
        if op == "-":
            return left_is_pointer and (right_is_pointer or right_is_integer)
        return False

    def _pointer_step_size(self, pointer_type: Type) -> int:
        pointee = pointer_type.pointee()
        if pointee is None and pointer_type.is_array():
            pointee = pointer_type.element_type()
        if pointee is None:
            return 1
        if unqualified_type(pointee) == VOID:
            return 1
        size = self._type_size(pointee)
        if size is None:
            raise self._error(f"AArch64 target cannot size pointer element type {pointee}")
        return size

    def _types_assignable(self, type_: Type) -> bool:
        return (
            bool(type_.declarator_ops and type_.declarator_ops[0][0] == "ptr")
            or bool(type_.declarator_ops and type_.declarator_ops[0][0] == "fn")
            or is_integer_type(unqualified_type(type_))
            or is_floating_type(unqualified_type(type_))
            or unqualified_type(type_).name == "__builtin_va_list"
            or self._scalar_union_info(type_) is not None
        )

    def _scalar_union_info(self, type_: Type) -> _ScalarInfo | None:
        if type_.declarator_ops or not type_.name.startswith("union "):
            return None
        size = self._type_size(type_)
        align = self._type_align(type_)
        if size not in {1, 2, 4, 8} or align is None:
            return None
        return _ScalarInfo(size, align, False)

    def _emit_load_immediate(self, reg: str, value: int, bits: int) -> None:
        if -65536 <= value <= 65535:
            self._emit(f"mov {reg}, #{value}")
            return
        masked = value & ((1 << bits) - 1)
        shifts = range(0, bits, 16)
        chunks = [(shift, (masked >> shift) & 0xFFFF) for shift in shifts]
        nonzero_chunks = [(shift, chunk) for shift, chunk in chunks if chunk]
        if not nonzero_chunks:
            self._emit(f"mov {reg}, #0")
            return
        first_shift, first_chunk = nonzero_chunks[0]
        self._emit(f"movz {reg}, #{first_chunk}{self._lsl_suffix(first_shift)}")
        for shift, chunk in nonzero_chunks[1:]:
            self._emit(f"movk {reg}, #{chunk}{self._lsl_suffix(shift)}")

    def _emit_adjust_sp(self, op: str, value: int) -> None:
        if 0 <= value <= 4095:
            self._emit(f"{op} sp, sp, #{value}")
            return
        self._emit_load_immediate("x16", value, 64)
        self._emit(f"{op} sp, sp, x16")

    @staticmethod
    def _parse_int_value(lexeme: str) -> int:
        s = lexeme
        while s and s[-1] in "uUlL":
            s = s[:-1]
        if s.startswith(("0x", "0X")):
            return int(s, 16)
        if s.startswith(("0b", "0B")):
            return int(s, 2)
        if len(s) > 1 and s.startswith("0"):
            return int(s, 8)
        return int(s or "0", 10)

    def _eval_int_constant(self, expr: Expr) -> int | None:
        if isinstance(expr, IntLiteral):
            return self._parse_int_value(expr.value)
        if isinstance(expr, CharLiteral):
            return self._char_value(expr.value)
        if isinstance(expr, Identifier):
            if self._func_sym is not None:
                symbol = self._func_sym.locals.get(expr.name)
                if isinstance(symbol, EnumConstSymbol):
                    return symbol.value
            if self._sema.file_scope is not None:
                file_symbol = self._sema.file_scope.lookup(expr.name)
                if isinstance(file_symbol, EnumConstSymbol):
                    return file_symbol.value
            return None
        if isinstance(expr, UnaryExpr):
            value = self._eval_int_constant(expr.operand)
            if value is None:
                return None
            if expr.op == "+":
                return value
            if expr.op == "-":
                return -value
            if expr.op == "!":
                return 0 if value else 1
            if expr.op == "~":
                return ~value
            return None
        if isinstance(expr, CastExpr):
            return self._eval_int_constant(expr.expr)
        if isinstance(expr, CommaExpr):
            return self._eval_int_constant(expr.right)
        if isinstance(expr, ConditionalExpr):
            condition = self._eval_int_constant(expr.condition)
            if condition is None:
                return None
            return self._eval_int_constant(expr.then_expr if condition else expr.else_expr)
        if isinstance(expr, SizeofExpr):
            return self._type_size(self._sizeof_operand_type(expr))
        if isinstance(expr, AlignofExpr):
            return self._type_align(self._sizeof_operand_type(expr))
        if isinstance(expr, BuiltinOffsetofExpr):
            return self._offsetof_value(expr)
        if isinstance(expr, BinaryExpr):
            return self._eval_binary_int_constant(expr)
        if isinstance(expr, CallExpr):
            return self._eval_call_int_constant(expr)
        return None

    def _eval_float_constant(self, expr: Expr) -> float | None:
        if isinstance(expr, FloatLiteral):
            return float(expr.value.rstrip("fFlL"))
        if isinstance(expr, UnaryExpr):
            value = self._eval_float_constant(expr.operand)
            if value is None:
                return None
            if expr.op == "+":
                return value
            if expr.op == "-":
                return -value
            return None
        if isinstance(expr, CastExpr):
            value = self._eval_float_constant(expr.expr)
            if value is not None:
                return value
            int_value = self._eval_int_constant(expr.expr)
            return None if int_value is None else float(int_value)
        if isinstance(expr, CommaExpr):
            return self._eval_float_constant(expr.right)
        if isinstance(expr, ConditionalExpr):
            condition = self._eval_int_constant(expr.condition)
            if condition is None:
                return None
            return self._eval_float_constant(expr.then_expr if condition else expr.else_expr)
        if isinstance(expr, BinaryExpr):
            return self._eval_binary_float_constant(expr)
        if isinstance(expr, CallExpr):
            return self._eval_call_float_constant(expr)
        int_value = self._eval_int_constant(expr)
        return None if int_value is None else float(int_value)

    def _eval_binary_float_constant(self, expr: BinaryExpr) -> float | None:
        left = self._eval_float_constant(expr.left)
        right = self._eval_float_constant(expr.right)
        if left is None or right is None:
            return None
        if expr.op == "+":
            return left + right
        if expr.op == "-":
            return left - right
        if expr.op == "*":
            return left * right
        if expr.op == "/":
            return None if right == 0.0 else left / right
        return None

    def _eval_binary_int_constant(self, expr: BinaryExpr) -> int | None:
        left = self._eval_int_constant(expr.left)
        if left is None:
            return None
        if expr.op == "&&":
            if not left:
                return 0
            right = self._eval_int_constant(expr.right)
            return None if right is None else int(bool(right))
        if expr.op == "||":
            if left:
                return 1
            right = self._eval_int_constant(expr.right)
            return None if right is None else int(bool(right))
        right = self._eval_int_constant(expr.right)
        if right is None:
            return None
        if expr.op == "+":
            return left + right
        if expr.op == "-":
            return left - right
        if expr.op == "*":
            return left * right
        if expr.op == "/":
            return None if right == 0 else left // right
        if expr.op == "%":
            return None if right == 0 else left % right
        if expr.op == "<<":
            return None if right < 0 else left << right
        if expr.op == ">>":
            return None if right < 0 else left >> right
        if expr.op == "<":
            return int(left < right)
        if expr.op == "<=":
            return int(left <= right)
        if expr.op == ">":
            return int(left > right)
        if expr.op == ">=":
            return int(left >= right)
        if expr.op == "==":
            return int(left == right)
        if expr.op == "!=":
            return int(left != right)
        if expr.op == "&":
            return left & right
        if expr.op == "^":
            return left ^ right
        if expr.op == "|":
            return left | right
        return None

    def _eval_call_int_constant(self, expr: CallExpr) -> int | None:
        if isinstance(expr.callee, Identifier):
            if expr.callee.name == "_Py_PACK_FULL_VERSION":
                if len(expr.args) != 5:
                    return None
                values = [self._eval_int_constant(arg) for arg in expr.args]
                if any(v is None for v in values):
                    return None
                v0 = cast(int, values[0])
                v1 = cast(int, values[1])
                v2 = cast(int, values[2])
                v3 = cast(int, values[3])
                v4 = cast(int, values[4])
                return (
                    ((v0 & 0xFF) << 24)
                    | ((v1 & 0xFF) << 16)
                    | ((v2 & 0xFF) << 8)
                    | ((v3 & 0xF) << 4)
                    | ((v4 & 0xF) << 0)
                )
            if expr.callee.name == "_Py_PACK_VERSION":
                if len(expr.args) != 2:
                    return None
                values = [self._eval_int_constant(arg) for arg in expr.args]
                if any(v is None for v in values):
                    return None
                v0 = cast(int, values[0])
                v1 = cast(int, values[1])
                return ((v0 & 0xFF) << 24) | ((v1 & 0xFF) << 16)
        return None

    def _eval_call_float_constant(self, expr: CallExpr) -> float | None:
        if isinstance(expr.callee, Identifier):
            if expr.callee.name in {
                "__builtin_inff",
                "__builtin_inf",
                "__builtin_infl",
            }:
                return float("inf")
            if expr.callee.name in {
                "__builtin_nanf",
                "__builtin_nan",
                "__builtin_nanl",
            }:
                return float("nan")
            if expr.callee.name in {
                "__builtin_huge_valf",
                "__builtin_huge_val",
                "__builtin_huge_vall",
            }:
                return float("inf")
            if expr.callee.name == "__builtin_fabsf" and len(expr.args) == 1:
                value = self._eval_float_constant(expr.args[0])
                return None if value is None else abs(value)
            if expr.callee.name == "__builtin_fabs" and len(expr.args) == 1:
                value = self._eval_float_constant(expr.args[0])
                return None if value is None else abs(value)
            if expr.callee.name == "__builtin_fabsl" and len(expr.args) == 1:
                value = self._eval_float_constant(expr.args[0])
                return None if value is None else abs(value)
        return None

    def _eval_case_value(self, expr: Expr) -> int:
        value = self._eval_int_constant(expr)
        if value is not None:
            return value
        raise self._error("AArch64 target cannot evaluate switch case value")

    @staticmethod
    def _char_value(lexeme: str) -> int:
        body = char_literal_body(lexeme)
        units = decode_escaped_units(body) if body is not None else [ord(ch) for ch in lexeme]
        if len(units) == 1:
            return units[0]
        value = 0
        for unit in units:
            value = (value << 8) | (unit & 0xFF)
        return value

    @staticmethod
    def _float_bits(lexeme: str, size: int) -> int:
        stripped = lexeme.rstrip("fFlL")
        return _AArch64AsmGen._float_to_bits(float(stripped), size)

    @staticmethod
    def _float_to_bits(value: float, size: int) -> int:
        if size == 4:
            return struct.unpack("<I", struct.pack("<f", value))[0]
        return struct.unpack("<Q", struct.pack("<d", value))[0]

    @staticmethod
    def _subscript_element_type(type_: Type) -> Type | None:
        if not type_.declarator_ops:
            return None
        if type_.declarator_ops[0][0] == "arr":
            return type_.element_type()
        if type_.declarator_ops[0][0] == "ptr":
            return type_.pointee()
        return None

    def _string_literal_bytes(self, expr: StringLiteral) -> bytes:
        body = string_literal_body(expr.value)
        if body is None:
            raise self._error(f"AArch64 target does not support string literal {expr.value}")
        units = decode_escaped_units(body)
        width = self._string_literal_unit_width(expr)
        limit = (1 << (width * 8)) - 1
        if any(unit < 0 or unit > limit for unit in units):
            raise self._error("AArch64 target found string literal unit out of range")
        zero = (0).to_bytes(width, "little")
        return b"".join(unit.to_bytes(width, "little") for unit in units) + zero

    def _string_literal_label(self, expr: StringLiteral) -> str:
        data = self._string_literal_bytes(expr)
        if self._string_literal_unit_width(expr) == 1:
            label = self._string_literals.get(data)
            if label is None:
                label = f"L_.cstr{len(self._string_literals)}"
                self._string_literals[data] = label
            return label
        label = self._wide_string_literals.get(data)
        if label is None:
            label = f"L_.wstr{len(self._wide_string_literals)}"
            self._wide_string_literals[data] = label
        return label

    @staticmethod
    def _string_literal_unit_width(expr: StringLiteral) -> int:
        quote = expr.value.find('"')
        prefix = expr.value[:quote] if quote >= 0 else ""
        if prefix == "u":
            return 2
        if prefix in {"L", "U"}:
            return 4
        return 1

    def _stmt_contains_call(self, stmt: Stmt) -> bool:
        if isinstance(stmt, CompoundStmt):
            return any(self._stmt_contains_call(child) for child in stmt.statements)
        if isinstance(stmt, IfStmt):
            return (
                self._expr_contains_call(stmt.condition)
                or self._stmt_contains_call(stmt.then_body)
                or (stmt.else_body is not None and self._stmt_contains_call(stmt.else_body))
            )
        if isinstance(stmt, WhileStmt):
            return self._expr_contains_call(stmt.condition) or self._stmt_contains_call(stmt.body)
        if isinstance(stmt, DoWhileStmt):
            return self._stmt_contains_call(stmt.body) or self._expr_contains_call(stmt.condition)
        if isinstance(stmt, ForStmt):
            init_has_call = (
                self._stmt_contains_call(stmt.init)
                if isinstance(stmt.init, Stmt)
                else isinstance(stmt.init, Expr) and self._expr_contains_call(stmt.init)
            )
            return (
                init_has_call
                or (stmt.condition is not None and self._expr_contains_call(stmt.condition))
                or (stmt.post is not None and self._expr_contains_call(stmt.post))
                or self._stmt_contains_call(stmt.body)
            )
        if isinstance(stmt, LabelStmt):
            return self._stmt_contains_call(stmt.body)
        if isinstance(stmt, SwitchStmt):
            return self._expr_contains_call(stmt.condition) or self._stmt_contains_call(stmt.body)
        if isinstance(stmt, (CaseStmt, DefaultStmt)):
            return self._stmt_contains_call(stmt.body)
        if isinstance(stmt, ReturnStmt):
            return stmt.value is not None and self._expr_contains_call(stmt.value)
        if isinstance(stmt, DeclStmt):
            return isinstance(stmt.init, Expr) and self._expr_contains_call(stmt.init)
        if isinstance(stmt, DeclGroupStmt):
            return any(self._stmt_contains_call(declaration) for declaration in stmt.declarations)
        if isinstance(stmt, ExprStmt):
            return self._expr_contains_call(stmt.expr)
        return False

    def _expr_contains_call(self, expr: Expr) -> bool:
        if isinstance(expr, CallExpr):
            return True
        if isinstance(expr, BinaryExpr):
            return self._expr_contains_call(expr.left) or self._expr_contains_call(expr.right)
        if isinstance(expr, ConditionalExpr):
            return (
                self._expr_contains_call(expr.condition)
                or self._expr_contains_call(expr.then_expr)
                or self._expr_contains_call(expr.else_expr)
            )
        if isinstance(expr, UnaryExpr):
            return self._expr_contains_call(expr.operand)
        if isinstance(expr, UpdateExpr):
            return self._expr_contains_call(expr.operand)
        if isinstance(expr, AssignExpr):
            return self._expr_contains_call(expr.target) or self._expr_contains_call(expr.value)
        if isinstance(expr, CastExpr):
            return self._expr_contains_call(expr.expr)
        if isinstance(expr, CommaExpr):
            return self._expr_contains_call(expr.left) or self._expr_contains_call(expr.right)
        if isinstance(expr, SubscriptExpr):
            return self._expr_contains_call(expr.base) or self._expr_contains_call(expr.index)
        if isinstance(expr, MemberExpr):
            return self._expr_contains_call(expr.base)
        if isinstance(expr, CompoundLiteralExpr):
            return self._init_contains_call(expr.initializer)
        return False

    def _init_contains_call(self, init: Expr | InitList) -> bool:
        if isinstance(init, Expr):
            return self._expr_contains_call(init)
        return any(self._init_contains_call(item.initializer) for item in init.items)

    def _stmt_needs_scratch(self, stmt: Stmt) -> bool:
        if isinstance(stmt, CompoundStmt):
            return any(self._stmt_needs_scratch(child) for child in stmt.statements)
        if isinstance(stmt, IfStmt):
            return (
                self._expr_needs_scratch(stmt.condition)
                or self._stmt_needs_scratch(stmt.then_body)
                or (stmt.else_body is not None and self._stmt_needs_scratch(stmt.else_body))
            )
        if isinstance(stmt, WhileStmt):
            return self._expr_needs_scratch(stmt.condition) or self._stmt_needs_scratch(stmt.body)
        if isinstance(stmt, DoWhileStmt):
            return self._stmt_needs_scratch(stmt.body) or self._expr_needs_scratch(stmt.condition)
        if isinstance(stmt, ForStmt):
            init_needs_scratch = (
                self._stmt_needs_scratch(stmt.init)
                if isinstance(stmt.init, Stmt)
                else isinstance(stmt.init, Expr) and self._expr_needs_scratch(stmt.init)
            )
            return (
                init_needs_scratch
                or (stmt.condition is not None and self._expr_needs_scratch(stmt.condition))
                or (stmt.post is not None and self._expr_needs_scratch(stmt.post))
                or self._stmt_needs_scratch(stmt.body)
            )
        if isinstance(stmt, LabelStmt):
            return self._stmt_needs_scratch(stmt.body)
        if isinstance(stmt, SwitchStmt):
            return self._expr_needs_scratch(stmt.condition) or self._stmt_needs_scratch(stmt.body)
        if isinstance(stmt, (CaseStmt, DefaultStmt)):
            return self._stmt_needs_scratch(stmt.body)
        if isinstance(stmt, ReturnStmt):
            if stmt.value is None:
                return False
            if (
                self._func_sym is not None
                and self._is_indirect_return_type(self._func_sym.return_type)
                and not isinstance(stmt.value, CompoundLiteralExpr)
            ):
                return True
            return self._expr_needs_scratch(stmt.value)
        if isinstance(stmt, DeclStmt):
            return (
                isinstance(stmt.init, InitList)
                or (
                    isinstance(stmt.init, Expr)
                    and not self._types_assignable(self._local_decl_type(stmt))
                )
                or isinstance(stmt.init, Expr)
                and self._expr_needs_scratch(stmt.init)
            )
        if isinstance(stmt, DeclGroupStmt):
            return any(self._stmt_needs_scratch(declaration) for declaration in stmt.declarations)
        if isinstance(stmt, ExprStmt):
            return self._expr_needs_scratch(stmt.expr)
        return False

    def _expr_needs_scratch(self, expr: Expr) -> bool:
        if isinstance(expr, AssignExpr):
            aggregate_assignment = expr.op == "=" and isinstance(
                expr.value,
                CompoundLiteralExpr,
            )
            aggregate_call_assignment = (
                expr.op == "="
                and isinstance(expr.value, CallExpr)
                and not self._types_assignable(self._expr_type(expr.target))
            )
            aggregate_value_assignment = expr.op == "=" and not self._types_assignable(
                self._expr_type(expr.target)
            )
            target_needs_scratch = isinstance(
                expr.target,
                (SubscriptExpr, MemberExpr, UnaryExpr),
            ) and self._expr_needs_scratch(expr.target)
            call_address_assignment = (
                expr.op == "="
                and isinstance(expr.target, (SubscriptExpr, MemberExpr, UnaryExpr))
                and self._expr_contains_call(expr.target)
            )
            return (
                aggregate_assignment
                or aggregate_call_assignment
                or aggregate_value_assignment
                or target_needs_scratch
                or call_address_assignment
                or expr.op
                in {
                    "+=",
                    "-=",
                    "*=",
                    "/=",
                    "%=",
                    "|=",
                    "&=",
                    "^=",
                    "<<=",
                    ">>=",
                }
                and isinstance(expr.target, (SubscriptExpr, MemberExpr, UnaryExpr))
            ) or self._expr_needs_scratch(expr.value)
        if isinstance(expr, BinaryExpr):
            return self._expr_needs_scratch(expr.left) or self._expr_needs_scratch(expr.right)
        if isinstance(expr, ConditionalExpr):
            return (
                self._expr_needs_scratch(expr.condition)
                or self._expr_needs_scratch(expr.then_expr)
                or self._expr_needs_scratch(expr.else_expr)
            )
        if isinstance(expr, UnaryExpr):
            return self._expr_needs_scratch(expr.operand)
        if isinstance(expr, UpdateExpr):
            return self._expr_needs_scratch(expr.operand)
        if isinstance(expr, CastExpr):
            return self._expr_needs_scratch(expr.expr)
        if isinstance(expr, CommaExpr):
            return self._expr_needs_scratch(expr.left) or self._expr_needs_scratch(expr.right)
        if isinstance(expr, CompoundLiteralExpr):
            return True
        if isinstance(expr, SubscriptExpr):
            return (
                self._expr_contains_call(expr.base)
                or self._expr_needs_scratch(expr.base)
                or self._expr_needs_scratch(expr.index)
            )
        if isinstance(expr, MemberExpr):
            return self._expr_needs_scratch(expr.base)
        if isinstance(expr, CallExpr):
            fixed_count = self._call_variadic_fixed_count(expr)
            has_variadic_record_arg = fixed_count is not None and any(
                index >= fixed_count and self._is_record_type(self._expr_type(arg))
                for index, arg in enumerate(expr.args)
            )
            return (
                self._is_indirect_return_type(self._expr_type(expr))
                or has_variadic_record_arg
                or any(self._expr_needs_scratch(arg) for arg in expr.args)
            )
        return False

    def _stmt_expr_spill_depth(self, stmt: Stmt) -> int:
        maximum = 0

        def walk(node: object) -> None:
            nonlocal maximum
            if isinstance(node, Expr):
                maximum = max(maximum, self._expr_spill_depth_needed(node))
                return
            if isinstance(node, InitList):
                maximum = max(maximum, self._init_expr_spill_depth(node))
                return
            if isinstance(node, (str, int, float, bytes, type(None))):
                return
            if isinstance(node, (list, tuple)):
                for item in node:
                    walk(item)
                return
            if is_dataclass(node):
                for field in fields(node):
                    walk(getattr(node, field.name))

        walk(stmt)
        return maximum

    def _init_expr_spill_depth(self, init: Expr | InitList) -> int:
        if isinstance(init, Expr):
            return self._expr_spill_depth_needed(init)
        return max(
            (self._init_expr_spill_depth(item.initializer) for item in init.items),
            default=0,
        )

    def _expr_spill_depth_needed(self, expr: Expr | None) -> int:
        if expr is None:
            return 0
        if isinstance(expr, BinaryExpr):
            left_depth = self._expr_spill_depth_needed(expr.left)
            right_depth = self._expr_spill_depth_needed(expr.right)
            if expr.op in {"&&", "||"}:
                return max(left_depth, right_depth)
            return max(left_depth, 1 + right_depth)
        if isinstance(expr, ConditionalExpr):
            return max(
                self._expr_spill_depth_needed(expr.condition),
                self._expr_spill_depth_needed(expr.then_expr),
                self._expr_spill_depth_needed(expr.else_expr),
            )
        if isinstance(expr, UnaryExpr):
            return self._expr_spill_depth_needed(expr.operand)
        if isinstance(expr, UpdateExpr):
            return self._expr_spill_depth_needed(expr.operand)
        if isinstance(expr, AssignExpr):
            if expr.op != "=":
                return max(
                    self._expr_spill_depth_needed(expr.target),
                    1 + self._expr_spill_depth_needed(expr.value),
                )
            return max(
                self._expr_spill_depth_needed(expr.target),
                self._expr_spill_depth_needed(expr.value),
            )
        if isinstance(expr, CastExpr):
            return self._expr_spill_depth_needed(expr.expr)
        if isinstance(expr, CommaExpr):
            return max(
                self._expr_spill_depth_needed(expr.left),
                self._expr_spill_depth_needed(expr.right),
            )
        if isinstance(expr, SubscriptExpr):
            return max(
                self._expr_spill_depth_needed(expr.base),
                self._expr_spill_depth_needed(expr.index),
            )
        if isinstance(expr, MemberExpr):
            return self._expr_spill_depth_needed(expr.base)
        if isinstance(expr, CallExpr):
            return max(
                [self._expr_spill_depth_needed(expr.callee)]
                + [self._expr_spill_depth_needed(arg) for arg in expr.args],
                default=0,
            )
        if isinstance(expr, CompoundLiteralExpr):
            return self._init_expr_spill_depth(expr.initializer)
        return 0

    def _stmt_call_arg_spill_depth(self, stmt: Stmt) -> int:
        if isinstance(stmt, CompoundStmt):
            return max(
                (self._stmt_call_arg_spill_depth(child) for child in stmt.statements), default=0
            )
        if isinstance(stmt, IfStmt):
            return max(
                self._expr_call_arg_spill_depth(stmt.condition),
                self._stmt_call_arg_spill_depth(stmt.then_body),
                self._stmt_call_arg_spill_depth(stmt.else_body)
                if stmt.else_body is not None
                else 0,
            )
        if isinstance(stmt, WhileStmt):
            return max(
                self._expr_call_arg_spill_depth(stmt.condition),
                self._stmt_call_arg_spill_depth(stmt.body),
            )
        if isinstance(stmt, DoWhileStmt):
            return max(
                self._stmt_call_arg_spill_depth(stmt.body),
                self._expr_call_arg_spill_depth(stmt.condition),
            )
        if isinstance(stmt, ForStmt):
            init_depth = (
                self._stmt_call_arg_spill_depth(stmt.init)
                if isinstance(stmt.init, Stmt)
                else self._expr_call_arg_spill_depth(stmt.init)
                if isinstance(stmt.init, Expr)
                else 0
            )
            return max(
                init_depth,
                self._expr_call_arg_spill_depth(stmt.condition)
                if stmt.condition is not None
                else 0,
                self._expr_call_arg_spill_depth(stmt.post) if stmt.post is not None else 0,
                self._stmt_call_arg_spill_depth(stmt.body),
            )
        if isinstance(stmt, LabelStmt):
            return self._stmt_call_arg_spill_depth(stmt.body)
        if isinstance(stmt, SwitchStmt):
            return max(
                self._expr_call_arg_spill_depth(stmt.condition),
                self._stmt_call_arg_spill_depth(stmt.body),
            )
        if isinstance(stmt, (CaseStmt, DefaultStmt)):
            return self._stmt_call_arg_spill_depth(stmt.body)
        if isinstance(stmt, ReturnStmt):
            return self._expr_call_arg_spill_depth(stmt.value) if stmt.value is not None else 0
        if isinstance(stmt, DeclStmt):
            return self._expr_call_arg_spill_depth(stmt.init) if isinstance(stmt.init, Expr) else 0
        if isinstance(stmt, DeclGroupStmt):
            return max(
                (self._stmt_call_arg_spill_depth(declaration) for declaration in stmt.declarations),
                default=0,
            )
        if isinstance(stmt, ExprStmt):
            return self._expr_call_arg_spill_depth(stmt.expr)
        return 0

    def _expr_call_arg_spill_depth(self, expr: Expr | None) -> int:
        if expr is None:
            return 0
        if isinstance(expr, CallExpr):
            maximum = 0
            for index, arg in enumerate(expr.args):
                depth = self._expr_call_arg_spill_depth(arg)
                if index > 0:
                    depth += 1
                maximum = max(maximum, depth)
            callee_depth = self._expr_call_arg_spill_depth(expr.callee)
            if expr.args:
                callee_depth += 1
            return max(maximum, callee_depth)
        if isinstance(expr, BinaryExpr):
            return max(
                self._expr_call_arg_spill_depth(expr.left),
                self._expr_call_arg_spill_depth(expr.right),
            )
        if isinstance(expr, ConditionalExpr):
            return max(
                self._expr_call_arg_spill_depth(expr.condition),
                self._expr_call_arg_spill_depth(expr.then_expr),
                self._expr_call_arg_spill_depth(expr.else_expr),
            )
        if isinstance(expr, UnaryExpr):
            return self._expr_call_arg_spill_depth(expr.operand)
        if isinstance(expr, UpdateExpr):
            return self._expr_call_arg_spill_depth(expr.operand)
        if isinstance(expr, AssignExpr):
            return max(
                self._expr_call_arg_spill_depth(expr.target),
                self._expr_call_arg_spill_depth(expr.value),
            )
        if isinstance(expr, CastExpr):
            return self._expr_call_arg_spill_depth(expr.expr)
        if isinstance(expr, CommaExpr):
            return max(
                self._expr_call_arg_spill_depth(expr.left),
                self._expr_call_arg_spill_depth(expr.right),
            )
        if isinstance(expr, SubscriptExpr):
            return max(
                self._expr_call_arg_spill_depth(expr.base),
                self._expr_call_arg_spill_depth(expr.index),
            )
        if isinstance(expr, MemberExpr):
            return self._expr_call_arg_spill_depth(expr.base)
        if isinstance(expr, CompoundLiteralExpr):
            return self._init_call_arg_spill_depth(expr.initializer)
        return 0

    def _init_call_arg_spill_depth(self, init: Expr | InitList) -> int:
        if isinstance(init, Expr):
            return self._expr_call_arg_spill_depth(init)
        return max(
            (self._init_call_arg_spill_depth(item.initializer) for item in init.items),
            default=0,
        )

    def _expr_has_side_effect(self, expr: Expr) -> bool:
        if isinstance(expr, (AssignExpr, BuiltinVaArgExpr, CallExpr, UpdateExpr)):
            return True
        if isinstance(expr, CastExpr):
            return self._expr_has_side_effect(expr.expr)
        if isinstance(expr, BinaryExpr):
            return self._expr_has_side_effect(expr.left) or self._expr_has_side_effect(expr.right)
        if isinstance(expr, ConditionalExpr):
            return (
                self._expr_has_side_effect(expr.condition)
                or self._expr_has_side_effect(expr.then_expr)
                or self._expr_has_side_effect(expr.else_expr)
            )
        if isinstance(expr, UnaryExpr):
            return self._expr_has_side_effect(expr.operand)
        if isinstance(expr, CommaExpr):
            return self._expr_has_side_effect(expr.left) or self._expr_has_side_effect(expr.right)
        if isinstance(expr, SubscriptExpr):
            return self._expr_has_side_effect(expr.base) or self._expr_has_side_effect(expr.index)
        if isinstance(expr, MemberExpr):
            return self._expr_has_side_effect(expr.base)
        return False

    def _max_outgoing_arg_size(self, stmt: Stmt) -> int:
        maximum = 0

        def walk(node: object) -> None:
            nonlocal maximum
            if isinstance(node, CallExpr):
                maximum = max(maximum, self._call_outgoing_stack_size(len(node.args)))
            if isinstance(node, (str, int, float, bytes, type(None))):
                return
            if isinstance(node, (list, tuple)):
                for item in node:
                    walk(item)
                return
            if is_dataclass(node):
                for field in fields(node):
                    walk(getattr(node, field.name))

        walk(stmt)
        return maximum

    def _call_outgoing_stack_size(self, arg_count: int) -> int:
        stack_arg_count = max(0, arg_count - 8)
        return self._align_to(stack_arg_count * 8, 16) if stack_arg_count else 0

    def _new_label(self, prefix: str) -> str:
        label = f"L_{prefix}_{self._label_counter}"
        self._label_counter += 1
        return label

    @staticmethod
    def _asm_string(data: bytes, *, strip_trailing_nul: bool = False) -> str:
        escaped: list[str] = []
        source = data[:-1] if strip_trailing_nul and data.endswith(b"\x00") else data
        for byte in source:
            if byte == 34:
                escaped.append(r"\"")
            elif byte == 92:
                escaped.append(r"\\")
            elif byte == 9:
                escaped.append(r"\t")
            elif byte == 10:
                escaped.append(r"\n")
            elif 32 <= byte <= 126:
                escaped.append(chr(byte))
            else:
                escaped.append(f"\\{byte:03o}")
        return "".join(escaped)

    @staticmethod
    def _reg(number: int, info: _ScalarInfo) -> str:
        if info.is_float:
            return f"d{number}" if info.size == 8 else f"s{number}"
        return f"x{number}" if info.size == 8 else f"w{number}"

    @staticmethod
    def _available_reg(used: set[int], candidates: tuple[int, ...]) -> int:
        for candidate in candidates:
            if candidate not in used:
                return candidate
        raise AssertionError("no scratch register available")

    @staticmethod
    def _slot_addr(slot: _Slot) -> str:
        return f"[sp, #{slot.offset}]"

    def _scratch_offset(self, offset: int = 0, sp_adjust: int = 0) -> int:
        if self._scratch_size <= offset:
            raise self._error("AArch64 target internal scratch slot unavailable")
        return self._frame_size + offset + sp_adjust

    def _scratch_addr(self, offset: int = 0, sp_adjust: int = 0) -> str:
        return f"[sp, #{self._scratch_offset(offset, sp_adjust)}]"

    @staticmethod
    def _stack_store_address_reg(reg: str, preferred: int) -> int:
        if reg.startswith(("x", "w")) and reg[1:].isdigit() and int(reg[1:]) == preferred:
            return 12 if preferred != 12 else 13
        return preferred

    @staticmethod
    def _lsl_suffix(shift: int) -> str:
        return "" if shift == 0 else f", lsl #{shift}"

    @staticmethod
    def _align_to(value: int, alignment: int) -> int:
        return (value + alignment - 1) // alignment * alignment

    @staticmethod
    def _symbol_name(name: str) -> str:
        return f"_{name}"

    def _user_label(self, name: str) -> str:
        assert self._func is not None
        return f"L_{self._func.name}_{name}"

    @staticmethod
    def _global_symbol_name(name: str, is_static: bool) -> str:
        return f"L_.{name}" if is_static else f"_{name}"

    def _require_slot(self, name: str) -> _Slot:
        slot = self._lookup_slot(name)
        if slot is None:
            raise self._error(f"Unknown local variable: {name}")
        return slot

    def _require_decl_slot(self, stmt: DeclStmt) -> _Slot:
        slot = self._decl_slots.get(id(stmt))
        if slot is None:
            raise self._error(f"Unknown local declaration: {stmt.name}")
        return slot

    def _lookup_slot(self, name: str) -> _Slot | None:
        for scope in reversed(self._scope_stack):
            slot = scope.get(name)
            if slot is not None:
                return slot
        return self._param_slots.get(name)

    def _static_local(self, name: str) -> _StaticLocal | None:
        if self._func is None:
            return None
        return self._static_locals.get((self._func.name, name))

    @staticmethod
    def _function_designator_value_type(type_: Type) -> Type:
        if type_.declarator_ops and type_.declarator_ops[0][0] == "fn":
            return type_.pointer_to()
        return type_

    def _emit_function_address(self, name: str, target_reg: int) -> None:
        label = self._symbol_name(name)
        if not self._function_has_body(name):
            self._emit(f"adrp x{target_reg}, {label}@GOTPAGE")
            self._emit(f"ldr x{target_reg}, [x{target_reg}, {label}@GOTPAGEOFF]")
            return
        self._emit(f"adrp x{target_reg}, {label}@PAGE")
        self._emit(f"add x{target_reg}, x{target_reg}, {label}@PAGEOFF")

    def _function_has_body(self, name: str) -> bool:
        return any(
            function.name == name and function.body is not None for function in self._unit.functions
        )

    def _emit_extern_data_address(self, label: str, target_reg: int) -> None:
        self._emit(f"adrp x{target_reg}, {label}@GOTPAGE")
        self._emit(f"ldr x{target_reg}, [x{target_reg}, {label}@GOTPAGEOFF]")

    def _emit(self, text: str) -> None:
        self._lines.append(f"    {text}")

    def _error(self, message: str) -> CodegenError:
        return aarch64_backend_error(self._result.filename, message)


def generate_aarch64_asm(result: FrontendResult) -> str:
    return _AArch64AsmGen(result).generate()
