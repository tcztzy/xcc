"""Direct ELF x86_64 SysV assembly backend.

This backend emits GNU assembler input in Intel syntax. It is deliberately
small at first, but it follows the same no-LLVM contract as the Darwin
AArch64 backend: unsupported C constructs fail with deterministic diagnostics
instead of falling back to LLVM IR.
"""

import struct
from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass

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
    IndirectGotoStmt,
    InitItem,
    InitList,
    IntLiteral,
    LabelStmt,
    MemberExpr,
    NullStmt,
    ReturnStmt,
    SizeofExpr,
    StatementExpr,
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
    is_integer_type,
    unqualified_type,
    usual_arithmetic_conversion,
)
from xcc.types import DOUBLE, INT, VOID, Type

_X86_64_UNSUPPORTED = "XCC-X64-0001"


def x86_64_backend_error(filename: str, message: str) -> CodegenError:
    return CodegenError(Diagnostic("codegen", filename, message, code=_X86_64_UNSUPPORTED))


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
    reg: str


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
class _CallArg:
    expr: Expr
    type_: Type
    info: _ScalarInfo
    location: str
    index: int
    offset: int = 0
    aggregate_type: Type | None = None


@dataclass(frozen=True)
class _AggregateChunk:
    offset: int
    info: _ScalarInfo


@dataclass(frozen=True)
class _MemberAccess:
    offset: int
    type_: Type
    bit_offset: int | None = None
    bit_width: int | None = None


class _X86_64AsmGen:
    _INT_ARG_REGS = ("rdi", "rsi", "rdx", "rcx", "r8", "r9")
    _FP_ARG_REGS = ("xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7")

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
        self._aggregate_call_slots: dict[int, _Slot] = {}
        self._sret_slot: _Slot | None = None
        self._va_reg_save_slot: _Slot | None = None
        self._scope_stack: list[dict[str, _Slot]] = []
        self._frame_size = 0
        self._return_label = ""
        self._label_counter = 0
        self._string_literals: dict[bytes, str] = {}
        self._string_literal_alignments: dict[bytes, int] = {}
        self._float_literals: dict[tuple[int, int], str] = {}
        self._compound_literals: list[tuple[str, Type, InitList]] = []
        self._globals: dict[str, _Global] = {}
        self._static_locals: dict[tuple[str, str], _StaticLocal] = {}
        self._record_type_spec_names: dict[int, str] = {}
        self._data_static_function: str | None = None
        self._break_stack: list[str] = []
        self._continue_stack: list[str] = []
        self._switch_stack: list[tuple[dict[int, str], str | None, str]] = []
        self._stack_depth = 0

    def generate(self) -> str:
        self._lines = [".intel_syntax noprefix", ".text"]
        self._collect_globals()
        self._collect_static_locals()
        for function in self._unit.functions:
            if function.body is None or function.is_inline:
                continue
            self._emit_function(function)
        for function in self._used_inline_functions():
            self._emit_function(function, force_local=True)
        self._emit_global_data()
        if self._string_literals or self._float_literals:
            self._lines.append(".section .rodata")
            for value, label in self._string_literals.items():
                align = self._string_literal_alignments.get(value, 0)
                if align:
                    self._lines.append(f".p2align {align}")
                self._lines.append(f"{label}:")
                self._emit_bytes(value)
            for (bits, size), label in self._float_literals.items():
                self._lines.append(f".p2align {3 if size == 8 else 2}")
                self._lines.append(f"{label}:")
                if size == 8:
                    self._lines.append(f"    .quad 0x{bits:016x}")
                else:
                    self._lines.append(f"    .long 0x{bits:08x}")
        self._lines.append('.section .note.GNU-stack,"",@progbits')
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
                type_ = self._complete_local_array_bound_type(stmt, type_)
                label = f".L.{function.name}.{stmt.name}"
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
            if isinstance(stmt, (WhileStmt, DoWhileStmt, SwitchStmt, LabelStmt)):
                collect(function, stmt.body)
                return
            if isinstance(stmt, ForStmt):
                if isinstance(stmt.init, Stmt):
                    collect(function, stmt.init)
                collect(function, stmt.body)
                return
            if isinstance(stmt, (CaseStmt, DefaultStmt)):
                collect(function, stmt.body)

        for function in self._unit.functions:
            if function.body is not None:
                collect(function, function.body)

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

    def _emit_function(self, function: FunctionDef, force_local: bool = False) -> None:
        body = function.body
        assert body is not None
        self._func = function
        self._func_sym = self._sema.functions.get(function.name)
        if self._func_sym is None:
            raise self._error(f"Missing semantic function symbol: {function.name}")
        if not self._is_void_type(self._func_sym.return_type):
            if self._is_aggregate_type(self._func_sym.return_type):
                if not self._aggregate_return_uses_memory(self._func_sym.return_type):
                    self._small_aggregate_return_chunks(self._func_sym.return_type)
            else:
                self._scalar_info(self._func_sym.return_type)
        self._record_type_spec_names = self._index_local_record_type_specs(body)
        self._prepare_frame(function, body)
        label = self._symbol_name(function.name)
        self._return_label = f".L.{function.name}.return"
        self._lines.append(".p2align 4")
        if function.storage_class != "static" and not force_local:
            self._lines.append(f".globl {label}")
        self._lines.append(f"{label}:")
        self._emit("push rbp")
        self._emit("mov rbp, rsp")
        if self._frame_size:
            self._emit(f"sub rsp, {self._frame_size}")
        self._stack_depth = 0
        self._spill_parameters(function)
        self._scope_stack = [dict(self._param_slots)]
        try:
            self._emit_stmt(body)
        finally:
            self._scope_stack = []
            self._record_type_spec_names = {}
        self._lines.append(f"{self._return_label}:")
        self._emit("leave")
        self._emit("ret")

    def _index_local_record_type_specs(self, body: CompoundStmt) -> dict[int, str]:
        resolved: dict[int, str] = {}
        tag_scopes: list[dict[tuple[str, str], str]] = [{}]

        def note_type_spec(type_spec: TypeSpec) -> None:
            if not (type_spec.has_record_body or type_spec.record_tag is not None):
                return
            if type_spec.has_record_body:
                name = self._record_name_for_type_spec(type_spec)
                resolved[id(type_spec)] = name
                if type_spec.record_tag is not None:
                    tag_scopes[-1][(type_spec.name, type_spec.record_tag)] = name
                return
            if type_spec.record_tag is None:  # pragma: no cover - guarded above
                return
            key = (type_spec.name, type_spec.record_tag)
            for scope in reversed(tag_scopes):
                resolved_name = scope.get(key)
                if resolved_name is not None:
                    resolved[id(type_spec)] = resolved_name
                    return

        def walk(node: object) -> None:
            if isinstance(node, (str, int, float, bytes, type(None))):
                return
            if isinstance(node, TypeSpec):
                note_type_spec(node)
                for member in node.record_members:
                    walk(member.type_spec)
                for _kind, value in node.declarator_ops:
                    walk(value)
                if node.atomic_target is not None:
                    walk(node.atomic_target)
                if node.typeof_expr is not None:
                    walk(node.typeof_expr)
                return
            if isinstance(node, CompoundStmt):
                tag_scopes.append({})
                try:
                    for child in node.statements:
                        walk(child)
                finally:
                    tag_scopes.pop()
                return
            if isinstance(node, DeclGroupStmt):
                for declaration in node.declarations:
                    walk(declaration)
                return
            if isinstance(node, DeclStmt):
                walk(node.type_spec)
                walk(node.init)
                return
            if isinstance(node, TypedefDecl):
                walk(node.type_spec)
                return
            if isinstance(node, (list, tuple)):
                for item in node:
                    walk(item)
                return
            if is_dataclass(node):
                for field in fields(node):
                    walk(getattr(node, field.name))

        walk(body)
        return resolved

    def _prepare_frame(self, function: FunctionDef, body: CompoundStmt) -> None:
        self._param_slots = {}
        self._decl_slots = {}
        self._compound_literal_slots = {}
        self._aggregate_call_slots = {}
        self._sret_slot = None
        self._va_reg_save_slot = None
        offset = 0

        def add_slot(type_: Type, alignment: int | None = None) -> _Slot:
            nonlocal offset
            info = self._slot_info(type_)
            align = alignment or info.align
            offset = self._align_to(offset, align)
            offset += info.size
            return _Slot(offset, type_, info)

        def add_raw_slot(size: int, alignment: int = 8) -> _Slot:
            nonlocal offset
            offset = self._align_to(offset, alignment)
            offset += size
            return _Slot(offset, VOID, _ScalarInfo(size, alignment, False))

        def add_param_slot(type_: Type, alignment: int | None = None) -> _Slot:
            if self._is_va_list_type(type_):
                nonlocal offset
                align = alignment or 8
                offset = self._align_to(offset, align)
                offset += 8
                return _Slot(offset, type_, _ScalarInfo(8, align, False))
            return add_slot(type_, alignment)

        assert self._func_sym is not None
        if self._is_aggregate_type(
            self._func_sym.return_type
        ) and self._aggregate_return_uses_memory(self._func_sym.return_type):
            self._sret_slot = add_slot(VOID.pointer_to())
        if function.is_variadic:
            self._va_reg_save_slot = add_raw_slot(176, 16)
        for param in function.params:
            if param.name is None:
                continue
            symbol = self._func_sym.locals.get(param.name)
            if not isinstance(symbol, VarSymbol):
                raise self._error(f"Missing parameter symbol: {param.name}")
            self._param_slots[param.name] = add_param_slot(symbol.type_, symbol.alignment)

        def add_decl_slot(stmt: DeclStmt, type_: Type, alignment: int | None = None) -> None:
            self._decl_slots[id(stmt)] = add_slot(type_, alignment)

        self._collect_local_slots(body, add_decl_slot)

        def add_compound_literal_slot(expr: CompoundLiteralExpr, type_: Type) -> None:
            self._compound_literal_slots[id(expr)] = add_slot(type_)

        self._collect_compound_literal_slots(body, add_compound_literal_slot)

        def add_aggregate_call_slot(expr: CallExpr, type_: Type) -> None:
            self._aggregate_call_slots[id(expr)] = add_slot(type_)

        self._collect_aggregate_call_slots(body, add_aggregate_call_slot)
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
            self._collect_statement_expr_local_slots(stmt.condition, add_slot)
            self._collect_local_slots(stmt.then_body, add_slot)
            if stmt.else_body is not None:
                self._collect_local_slots(stmt.else_body, add_slot)
            return
        if isinstance(stmt, WhileStmt):
            self._collect_statement_expr_local_slots(stmt.condition, add_slot)
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, DoWhileStmt):
            self._collect_local_slots(stmt.body, add_slot)
            self._collect_statement_expr_local_slots(stmt.condition, add_slot)
            return
        if isinstance(stmt, SwitchStmt):
            self._collect_statement_expr_local_slots(stmt.condition, add_slot)
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, LabelStmt):
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, ForStmt):
            if isinstance(stmt.init, Stmt):
                self._collect_local_slots(stmt.init, add_slot)
            elif isinstance(stmt.init, Expr):
                self._collect_statement_expr_local_slots(stmt.init, add_slot)
            if stmt.condition is not None:
                self._collect_statement_expr_local_slots(stmt.condition, add_slot)
            if stmt.post is not None:
                self._collect_statement_expr_local_slots(stmt.post, add_slot)
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, CaseStmt):
            self._collect_statement_expr_local_slots(stmt.value, add_slot)
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, DefaultStmt):
            self._collect_local_slots(stmt.body, add_slot)
            return
        if isinstance(stmt, DeclGroupStmt):
            for declaration in stmt.declarations:
                self._collect_local_slots(declaration, add_slot)
            return
        if isinstance(stmt, ExprStmt):
            self._collect_statement_expr_local_slots(stmt.expr, add_slot)
            return
        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._collect_statement_expr_local_slots(stmt.value, add_slot)
            return
        if isinstance(stmt, StaticAssertDecl):
            self._collect_statement_expr_local_slots(stmt.condition, add_slot)
            return
        if isinstance(stmt, IndirectGotoStmt):
            self._collect_statement_expr_local_slots(stmt.target, add_slot)
            return
        if not isinstance(stmt, DeclStmt):
            return
        if stmt.name is None or stmt.storage_class in {"typedef", "static", "extern"}:
            return
        self._collect_statement_expr_local_slots(stmt.init, add_slot)
        type_ = self._local_decl_type(stmt)
        if self._is_function_type(type_):
            return
        type_ = self._complete_local_array_bound_type(stmt, type_)
        if isinstance(stmt.init, InitList):
            type_ = self._complete_array_initializer_type(type_, stmt.init)
        if isinstance(stmt.init, StringLiteral):
            type_ = self._complete_array_string_initializer_type(type_, stmt.init)
        add_slot(stmt, type_, stmt.alignment)

    def _collect_statement_expr_local_slots(
        self,
        node: object,
        add_slot: Callable[[DeclStmt, Type, int | None], None],
    ) -> None:
        def walk(value: object) -> None:
            if isinstance(value, StatementExpr):
                self._collect_local_slots(value.body, add_slot)
                return
            if isinstance(value, (str, int, float, bytes, type(None), TypeSpec)):
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)
                return
            if is_dataclass(value):
                for field in fields(value):
                    walk(getattr(value, field.name))

        walk(node)

    def _collect_compound_literal_slots(
        self,
        node: object,
        add_slot: Callable[[CompoundLiteralExpr, Type], None],
    ) -> None:
        def walk(value: object) -> None:
            if isinstance(value, CompoundLiteralExpr):
                type_ = self._compound_literal_type(value)
                add_slot(value, type_)
                walk(value.initializer)
                return
            if isinstance(value, (str, int, float, bytes, type(None), TypeSpec)):
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)
                return
            if is_dataclass(value):
                for field in fields(value):
                    walk(getattr(value, field.name))

        walk(node)

    def _collect_aggregate_call_slots(
        self,
        node: object,
        add_slot: Callable[[CallExpr, Type], None],
    ) -> None:
        def walk(value: object) -> None:
            if isinstance(value, CallExpr):
                type_ = self._expr_type(value)
                if self._is_aggregate_type(type_):
                    add_slot(value, type_)
                walk(value.callee)
                for arg in value.args:
                    walk(arg)
                return
            if isinstance(value, CompoundLiteralExpr):
                walk(value.initializer)
                return
            if isinstance(value, (str, int, float, bytes, type(None), TypeSpec)):
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)
                return
            if is_dataclass(value):
                for field in fields(value):
                    walk(getattr(value, field.name))

        walk(node)

    def _spill_parameters(self, function: FunctionDef) -> None:
        if function.is_variadic:
            self._spill_variadic_registers()
        int_arg_reg = 1 if self._sret_slot is not None else 0
        fp_arg_reg = 0
        stack_arg_offset = 16
        if self._sret_slot is not None:
            self._emit_store_to_address(
                self._sret_slot.info, "rdi", self._slot_addr(self._sret_slot)
            )
        for param in function.params:
            if param.name is None:
                continue
            slot = self._require_slot(param.name)
            if self._is_aggregate_type(slot.type_):
                chunks = self._aggregate_chunks(slot.type_)
                use_registers = self._aggregate_uses_registers(
                    slot.type_, chunks, int_arg_reg, fp_arg_reg
                )
                for chunk in chunks:
                    destination = self._slot_addr(slot, chunk.offset)
                    if use_registers:
                        if chunk.info.is_float:
                            self._emit_float_store(
                                chunk.info, self._FP_ARG_REGS[fp_arg_reg], destination
                            )
                            fp_arg_reg += 1
                        else:
                            self._emit_store_to_address(
                                chunk.info, self._INT_ARG_REGS[int_arg_reg], destination
                            )
                            int_arg_reg += 1
                        continue
                    if chunk.info.is_float:
                        self._emit_float_load(chunk.info, "xmm0", f"[rbp + {stack_arg_offset}]")
                        self._emit_float_store(chunk.info, "xmm0", destination)
                    else:
                        self._emit(f"mov rax, QWORD PTR [rbp + {stack_arg_offset}]")
                        self._emit_store_to_address(chunk.info, "rax", destination)
                    stack_arg_offset += 8
                continue
            if slot.info.is_float:
                if fp_arg_reg >= len(self._FP_ARG_REGS):
                    self._emit_float_load(slot.info, "xmm0", f"[rbp + {stack_arg_offset}]")
                    self._emit_float_store(slot.info, "xmm0", self._slot_addr(slot))
                    stack_arg_offset += 8
                else:
                    self._emit_float_store(
                        slot.info, self._FP_ARG_REGS[fp_arg_reg], self._slot_addr(slot)
                    )
                    fp_arg_reg += 1
                continue
            if int_arg_reg < len(self._INT_ARG_REGS):
                source = self._sized_reg(self._INT_ARG_REGS[int_arg_reg], slot.info)
                self._emit(f"mov {self._mem(slot.info, self._slot_addr(slot))}, {source}")
            else:
                self._emit(f"mov rax, QWORD PTR [rbp + {stack_arg_offset}]")
                self._emit_store_to_address(slot.info, "rax", self._slot_addr(slot))
                stack_arg_offset += 8
            int_arg_reg += 1

    def _spill_variadic_registers(self) -> None:
        if self._va_reg_save_slot is None:
            raise self._error("x86_64 target missing variadic register save slot")
        for index, reg in enumerate(self._INT_ARG_REGS):
            self._emit(f"mov QWORD PTR {self._slot_addr(self._va_reg_save_slot, index * 8)}, {reg}")
        for index, reg in enumerate(self._FP_ARG_REGS):
            addr = self._slot_addr(self._va_reg_save_slot, 48 + index * 16)
            self._emit(f"movaps XMMWORD PTR {addr}, {reg}")

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
            self._emit_expr(stmt.expr)
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
            if not self._break_stack:
                raise self._error("break outside loop or switch")
            self._emit(f"jmp {self._break_stack[-1]}")
            return
        if isinstance(stmt, ContinueStmt):
            if not self._continue_stack:
                raise self._error("continue outside loop")
            self._emit(f"jmp {self._continue_stack[-1]}")
            return
        if isinstance(stmt, LabelStmt):
            self._lines.append(f"{self._user_label(stmt.name)}:")
            self._emit_stmt(stmt.body)
            return
        if isinstance(stmt, GotoStmt):
            self._emit(f"jmp {self._user_label(stmt.label)}")
            return
        if isinstance(stmt, (StaticAssertDecl, TypedefDecl, NullStmt)):
            return
        raise self._error(f"x86_64 target does not support {type(stmt).__name__} yet")

    def _emit_if(self, stmt: IfStmt) -> None:
        else_label = self._new_label("if_else")
        end_label = self._new_label("if_end")
        self._emit_branch_if_zero(stmt.condition, else_label)
        self._emit_stmt(stmt.then_body)
        self._emit(f"jmp {end_label}")
        self._lines.append(f"{else_label}:")
        if stmt.else_body is not None:
            self._emit_stmt(stmt.else_body)
        self._lines.append(f"{end_label}:")

    def _emit_while(self, stmt: WhileStmt) -> None:
        cond_label = self._new_label("while_cond")
        end_label = self._new_label("while_end")
        self._lines.append(f"{cond_label}:")
        self._emit_branch_if_zero(stmt.condition, end_label)
        self._break_stack.append(end_label)
        self._continue_stack.append(cond_label)
        try:
            self._emit_stmt(stmt.body)
        finally:
            self._continue_stack.pop()
            self._break_stack.pop()
        self._emit(f"jmp {cond_label}")
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
        cond_label = self._new_label("for_cond")
        post_label = self._new_label("for_post")
        end_label = self._new_label("for_end")
        try:
            self._scope_stack.append({})
            if isinstance(stmt.init, Stmt):
                self._emit_stmt(stmt.init)
            elif stmt.init is not None:
                self._emit_expr(stmt.init)
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
                self._emit_expr(stmt.post)
            self._emit(f"jmp {cond_label}")
            self._lines.append(f"{end_label}:")
        finally:
            self._scope_stack.pop()

    def _emit_switch(self, stmt: SwitchStmt) -> None:
        cases, default_stmt = self._collect_switch_cases(stmt.body)
        labels = {
            self._eval_case_value(case.value): self._new_label("switch_case") for case in cases
        }
        default_label = self._new_label("switch_default") if default_stmt is not None else None
        end_label = self._new_label("switch_end")
        self._emit_expr(stmt.condition)
        for value, label in labels.items():
            self._emit_cmp_rax_immediate(value)
            self._emit(f"je {label}")
        self._emit(f"jmp {default_label or end_label}")
        self._switch_stack.append((labels, default_label, end_label))
        self._break_stack.append(end_label)
        try:
            self._emit_stmt(stmt.body)
        finally:
            self._break_stack.pop()
            self._switch_stack.pop()
        self._lines.append(f"{end_label}:")

    def _collect_switch_cases(self, stmt: Stmt) -> tuple[list[CaseStmt], DefaultStmt | None]:
        cases: list[CaseStmt] = []
        default_stmt: DefaultStmt | None = None

        def collect(node: Stmt) -> None:
            nonlocal default_stmt
            if isinstance(node, SwitchStmt):
                return
            if isinstance(node, CaseStmt):
                cases.append(node)
                collect(node.body)
                return
            if isinstance(node, DefaultStmt):
                default_stmt = node
                collect(node.body)
                return
            if isinstance(node, CompoundStmt):
                for child in node.statements:
                    collect(child)

        collect(stmt)
        return cases, default_stmt

    def _emit_case(self, stmt: CaseStmt) -> None:
        if not self._switch_stack:
            raise self._error("case outside switch")
        labels, _, _ = self._switch_stack[-1]
        value = self._eval_case_value(stmt.value)
        self._lines.append(f"{labels[value]}:")
        self._emit_stmt(stmt.body)

    def _emit_default(self, stmt: DefaultStmt) -> None:
        if not self._switch_stack:
            raise self._error("default outside switch")
        _, default_label, _ = self._switch_stack[-1]
        if default_label is None:
            raise self._error("default label missing")
        self._lines.append(f"{default_label}:")
        self._emit_stmt(stmt.body)

    def _emit_return(self, stmt: ReturnStmt) -> None:
        assert self._func_sym is not None
        return_type = self._func_sym.return_type
        if stmt.value is not None:
            if self._is_aggregate_type(return_type):
                self._emit_aggregate_return(stmt.value, return_type)
            else:
                value = self._emit_expr(stmt.value)
                if not self._is_void_type(return_type):
                    info = self._scalar_info(return_type)
                    self._coerce_value(value, return_type, info)
        self._emit(f"jmp {self._return_label}")

    def _emit_aggregate_return(self, expr: Expr, return_type: Type) -> None:
        if self._aggregate_return_uses_memory(return_type):
            self._emit_indirect_aggregate_return(expr, return_type)
            return
        self._small_aggregate_return_chunks(return_type)
        if isinstance(expr, CallExpr):
            value_type = self._expr_type(expr)
            if value_type == return_type:
                self._emit_call(expr, "rax")
                return
        if isinstance(expr, (CompoundLiteralExpr, ConditionalExpr)) or self._is_zero_initializer(
            expr
        ):
            self._emit_small_aggregate_return_from_expr(expr, return_type)
            return
        self._emit_address(expr, "rcx")
        self._emit_aggregate_return_from_address(return_type, "rcx")

    def _emit_small_aggregate_return_from_expr(self, expr: Expr, return_type: Type) -> None:
        size = self._type_size(return_type)
        if size is None:
            raise self._error("x86_64 target cannot size aggregate return")
        scratch_size = self._align_to(size, 16)
        self._emit(f"sub rsp, {scratch_size}")
        self._emit("mov rcx, rsp")
        self._emit_aggregate_expr_to_address(return_type, expr, "rcx")
        self._emit_aggregate_return_from_address(return_type, "rcx")
        self._emit(f"add rsp, {scratch_size}")

    def _emit_indirect_aggregate_return(self, expr: Expr, return_type: Type) -> None:
        if self._sret_slot is None:
            raise self._error("x86_64 target missing indirect aggregate return slot")
        size = self._type_size(return_type)
        if size is None:
            raise self._error("x86_64 target cannot size indirect aggregate return")
        self._emit_load_from_address(self._sret_slot.info, "rcx", self._slot_addr(self._sret_slot))
        if isinstance(expr, CallExpr) and self._expr_type(expr) == return_type:
            self._emit_call(expr, "rax", aggregate_return_address="rcx")
            return
        if isinstance(expr, (CompoundLiteralExpr, ConditionalExpr)) or self._is_zero_initializer(
            expr
        ):
            self._emit_aggregate_expr_to_address(return_type, expr, "rcx")
        else:
            self._emit("push rcx")
            self._emit_address(expr, "rdx")
            self._emit("pop rcx")
            self._emit_copy_memory("rcx", "rdx", size)
        self._emit_load_from_address(self._sret_slot.info, "rax", self._slot_addr(self._sret_slot))

    def _emit_aggregate_return_from_address(self, return_type: Type, address_reg: str) -> None:
        int_return_regs = ("rax", "rdx")
        fp_return_regs = ("xmm0", "xmm1")
        int_index = 0
        fp_index = 0
        for chunk in self._small_aggregate_return_chunks(return_type):
            address = self._address_operand(address_reg, chunk.offset)
            if chunk.info.is_float:
                if fp_index >= len(fp_return_regs):
                    raise self._error("x86_64 target cannot return aggregate FP chunk")
                self._emit_float_load(chunk.info, fp_return_regs[fp_index], address)
                fp_index += 1
                continue
            if int_index >= len(int_return_regs):
                raise self._error("x86_64 target cannot return aggregate integer chunk")
            self._emit_load_from_address(chunk.info, int_return_regs[int_index], address)
            int_index += 1

    def _emit_aggregate_return_to_address(self, return_type: Type, address_reg: str) -> None:
        int_return_regs = ("rax", "rdx")
        fp_return_regs = ("xmm0", "xmm1")
        int_index = 0
        fp_index = 0
        for chunk in self._small_aggregate_return_chunks(return_type):
            address = self._address_operand(address_reg, chunk.offset)
            if chunk.info.is_float:
                if fp_index >= len(fp_return_regs):
                    raise self._error("x86_64 target cannot store aggregate FP return chunk")
                self._emit_float_store(chunk.info, fp_return_regs[fp_index], address)
                fp_index += 1
                continue
            if int_index >= len(int_return_regs):
                raise self._error("x86_64 target cannot store aggregate integer return chunk")
            self._emit_store_to_address(chunk.info, int_return_regs[int_index], address)
            int_index += 1

    def _emit_aggregate_expr_to_address(
        self, target_type: Type, expr: Expr, address_reg: str
    ) -> None:
        if self._is_zero_initializer(expr):
            size = self._type_size(target_type)
            if size is None:
                raise self._error("x86_64 target cannot size zero aggregate initializer")
            self._emit_zero_memory(address_reg, size)
            return
        if isinstance(expr, ConditionalExpr):
            false_label = self._new_label("aggregate_cond_false")
            end_label = self._new_label("aggregate_cond_end")
            self._emit(f"push {address_reg}")
            self._emit_branch_if_zero(expr.condition, false_label)
            self._emit(f"pop {address_reg}")
            self._emit_aggregate_expr_to_address(target_type, expr.then_expr, address_reg)
            self._emit(f"jmp {end_label}")
            self._lines.append(f"{false_label}:")
            self._emit(f"pop {address_reg}")
            self._emit_aggregate_expr_to_address(target_type, expr.else_expr, address_reg)
            self._lines.append(f"{end_label}:")
            return
        if isinstance(expr, CompoundLiteralExpr):
            self._emit_record_compound_initializer_to_address(
                target_type, expr.initializer, address_reg
            )
            return
        if isinstance(expr, CallExpr):
            if self._aggregate_return_uses_memory(target_type):
                self._emit_call(expr, "rax", aggregate_return_address=address_reg)
                return
            self._emit(f"push {address_reg}")
            self._emit("sub rsp, 8")
            self._emit_call(expr, "rax")
            self._emit("add rsp, 8")
            self._emit(f"pop {address_reg}")
            self._emit_aggregate_return_to_address(target_type, address_reg)
            return
        target_size = self._type_size(target_type)
        value_type = self._expr_type(expr)
        value_size = self._type_size(value_type)
        if target_size is None or value_size is None or value_size != target_size:
            raise self._error("x86_64 target cannot initialize aggregate value")
        self._emit(f"push {address_reg}")
        self._emit_address(expr, "rdx")
        self._emit(f"pop {address_reg}")
        self._emit_copy_memory(address_reg, "rdx", target_size)

    def _emit_compound_literal_to_address(
        self, type_: Type, init: InitList, address_reg: str
    ) -> None:
        if type_.is_array():
            self._emit_array_initializer_to_address(type_, init, address_reg)
            return
        if self._is_record_type(type_):
            self._emit_record_compound_initializer_to_address(type_, init, address_reg)
            return
        if len(init.items) != 1 or init.items[0].designators:
            raise self._error("x86_64 target requires scalar compound initializer")
        item = init.items[0].initializer
        if not isinstance(item, Expr):
            raise self._error("x86_64 target requires scalar compound initializer expression")
        info = self._scalar_info(type_)
        self._emit(f"push {address_reg}")
        value_target = self._float_target("rax") if info.is_float else "rax"
        value = self._emit_expr(item, value_target)
        self._coerce_value(value, type_, info)
        source = self._coerced_reg(value, info)
        self._emit(f"pop {address_reg}")
        self._emit_store_to_address(info, source, self._address_operand(address_reg))

    def _emit_array_initializer_to_address(
        self, type_: Type, init: InitList, address_reg: str
    ) -> None:
        type_ = self._complete_array_initializer_type(type_, init)
        element_type = type_.element_type()
        if element_type is None:
            raise self._error("x86_64 target cannot initialize non-array as array")
        element_info = self._slot_info(element_type)
        length = type_.declarator_ops[0][1]
        if not isinstance(length, int) or length < 0:
            raise self._error("x86_64 target requires known compound array length")
        size = self._type_size(type_)
        if size is None:
            raise self._error("x86_64 target cannot size compound array literal")
        self._emit_zero_memory(address_reg, size)
        items = self._array_initializer_items_by_index(init)
        for index, item in items.items():
            if index >= length:
                continue
            offset = index * element_info.size
            if self._is_aggregate_type(element_type):
                self._emit(f"push {address_reg}")
                self._emit_address_offset("rcx", address_reg, offset)
                if isinstance(item.initializer, InitList):
                    self._emit_compound_literal_to_address(element_type, item.initializer, "rcx")
                elif isinstance(item.initializer, Expr):
                    self._emit_aggregate_expr_to_address(element_type, item.initializer, "rcx")
                else:
                    raise self._error("x86_64 target requires aggregate array initializer")
                self._emit(f"pop {address_reg}")
                continue
            if not isinstance(item.initializer, Expr):
                raise self._error("x86_64 target requires scalar array initializer")
            self._emit(f"push {address_reg}")
            value_target = self._float_target("rax") if element_info.is_float else "rax"
            value = self._emit_expr(item.initializer, value_target)
            self._coerce_value(value, element_type, element_info)
            source = self._coerced_reg(value, element_info)
            self._emit(f"pop {address_reg}")
            self._emit_store_to_address(
                element_info, source, self._address_operand(address_reg, offset)
            )

    def _emit_decl(self, stmt: DeclStmt) -> None:
        if stmt.storage_class == "typedef" or stmt.name is None:
            return
        if stmt.storage_class == "extern":
            return
        if self._is_function_type(self._local_decl_type(stmt)):
            return
        if stmt.storage_class == "static":
            if stmt.name not in self._scope_stack[-1]:
                static_local = self._static_local(stmt.name)
                if static_local is None:
                    raise self._error(f"Unknown static local: {stmt.name}")
                self._scope_stack[-1][stmt.name] = _Slot(
                    0,
                    static_local.type_,
                    self._slot_info(static_local.type_),
                )
            return
        slot = self._require_decl_slot(stmt)
        self._scope_stack[-1][stmt.name] = slot
        if stmt.init is None:
            return
        if isinstance(stmt.init, InitList):
            if slot.type_.is_array():
                self._emit_local_array_initializer(slot, stmt.init)
                return
            if self._is_record_type(slot.type_):
                self._emit(f"lea rcx, {self._slot_addr(slot)}")
                self._emit_record_compound_initializer_to_address(slot.type_, stmt.init, "rcx")
                return
            raise self._error("x86_64 target does not support aggregate local initializer yet")
        if isinstance(stmt.init, StringLiteral) and slot.type_.is_array():
            self._emit_local_char_array_string_initializer(slot, stmt.init)
            return
        if self._is_aggregate_type(slot.type_):
            if slot.type_.is_array():
                raise self._error("x86_64 target cannot initialize array from expression")
            self._emit(f"lea rcx, {self._slot_addr(slot)}")
            self._emit_aggregate_expr_to_address(slot.type_, stmt.init, "rcx")
            return
        value = self._emit_expr(stmt.init)
        self._store_value_to_slot(slot, value)

    def _emit_expr(self, expr: Expr, target: str = "rax") -> _Value:
        target = self._expr_target(expr, target)
        if isinstance(expr, IntLiteral):
            value = self._parse_int_value(expr.value)
            type_ = self._expr_type(expr)
            info = self._scalar_info(type_)
            self._emit_load_immediate(target, value, info)
            return _Value(type_, info, target)
        if isinstance(expr, CharLiteral):
            value = self._char_value(expr.value)
            type_ = self._expr_type(expr)
            info = self._scalar_info(type_)
            self._emit_load_immediate(target, value, info)
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
            self._emit_expr(expr.left)
            return self._emit_expr(expr.right, target)
        if isinstance(expr, StatementExpr):
            return self._emit_statement_expr(expr, target)
        if isinstance(expr, ConditionalExpr):
            return self._emit_conditional(expr, target)
        raise self._error(f"x86_64 target does not support {type(expr).__name__} yet")

    def _emit_statement_expr(self, expr: StatementExpr, target: str) -> _Value:
        self._scope_stack.append({})
        try:
            statements = expr.body.statements
            if not statements:
                return _Value(VOID, _ScalarInfo(4, 4, False), "rax")
            for statement in statements[:-1]:
                self._emit_stmt(statement)
            last = statements[-1]
            if isinstance(last, ExprStmt):
                return self._emit_expr(last.expr, target)
            self._emit_stmt(last)
            return _Value(VOID, _ScalarInfo(4, 4, False), "rax")
        finally:
            self._scope_stack.pop()

    def _emit_compound_literal(self, expr: CompoundLiteralExpr, target: str) -> _Value:
        slot = self._compound_literal_slots.get(id(expr))
        if slot is None:
            raise self._error("x86_64 target missing compound literal storage")
        self._emit(f"lea rcx, {self._slot_addr(slot)}")
        self._emit_compound_literal_to_address(slot.type_, expr.initializer, "rcx")
        if self._is_aggregate_type(slot.type_) or slot.type_.is_array():
            if target != "rcx":
                self._emit(f"mov {target}, rcx")
            return _Value(slot.type_, _ScalarInfo(8, 8, False), target)
        info = self._scalar_info(slot.type_)
        load_target = self._float_target(target) if info.is_float else target
        self._emit_load_from_address(info, load_target, self._slot_addr(slot))
        return _Value(slot.type_, info, load_target)

    def _expr_target(self, expr: Expr, target: str) -> str:
        type_ = self._expr_type(expr)
        if self._is_void_type(type_):
            return target
        if type_.is_array() or self._is_aggregate_type(type_):
            return self._gpr_target(target)
        info = self._scalar_info(type_)
        if info.is_float:
            return self._float_target(target)
        return self._gpr_target(target)

    def _emit_identifier(self, expr: Identifier, target: str) -> _Value:
        if expr.name == "__func__" and self._func is not None:
            return self._emit_func_name_literal(expr, target)
        enum_symbol = self._lookup_enum_const(expr.name)
        if enum_symbol is not None:
            info = self._scalar_info(enum_symbol.type_)
            self._emit_load_immediate(target, enum_symbol.value, info)
            return _Value(enum_symbol.type_, info, target)
        slot = self._lookup_slot(expr.name)
        if slot is not None:
            static_local = self._static_local_slot_marker(expr.name, slot)
            if static_local is not None:
                if self._is_aggregate_type(static_local.type_) or static_local.type_.is_array():
                    self._emit(f"lea {target}, [rip + {static_local.label}]")
                    return _Value(static_local.type_.pointer_to(), _ScalarInfo(8, 8, False), target)
                info = self._slot_info(static_local.type_)
                load_target = self._float_target(target) if info.is_float else target
                self._emit_load_from_address(info, load_target, f"[rip + {static_local.label}]")
                return _Value(static_local.type_, info, load_target)
            if self._is_va_list_type(slot.type_):
                if self._param_slots.get(expr.name) is slot:
                    self._emit_load_from_address(
                        _ScalarInfo(8, 8, False), target, self._slot_addr(slot)
                    )
                    return _Value(VOID.pointer_to(), _ScalarInfo(8, 8, False), target)
                self._emit(f"lea {target}, {self._slot_addr(slot)}")
                return _Value(VOID.pointer_to(), _ScalarInfo(8, 8, False), target)
            if self._is_aggregate_type(slot.type_) or slot.type_.is_array():
                self._emit(f"lea {target}, {self._slot_addr(slot)}")
                return _Value(slot.type_.pointer_to(), _ScalarInfo(8, 8, False), target)
            load_target = self._float_target(target) if slot.info.is_float else target
            self._emit_load_from_address(slot.info, load_target, self._slot_addr(slot))
            return _Value(slot.type_, slot.info, load_target)
        static_local = self._static_local(expr.name)
        if static_local is not None:
            if self._is_aggregate_type(static_local.type_) or static_local.type_.is_array():
                self._emit(f"lea {target}, [rip + {static_local.label}]")
                return _Value(static_local.type_.pointer_to(), _ScalarInfo(8, 8, False), target)
            info = self._slot_info(static_local.type_)
            load_target = self._float_target(target) if info.is_float else target
            self._emit_load_from_address(info, load_target, f"[rip + {static_local.label}]")
            return _Value(static_local.type_, info, load_target)
        global_ = self._globals.get(expr.name)
        if global_ is not None:
            if self._is_aggregate_type(global_.type_) or global_.type_.is_array():
                self._emit_global_address(global_, target)
                return _Value(global_.type_.pointer_to(), _ScalarInfo(8, 8, False), target)
            info = self._slot_info(global_.type_)
            address_target = self._gpr_target(target)
            self._emit_global_address(global_, address_target)
            load_target = self._float_target(target) if info.is_float else target
            self._emit_load_from_address(info, load_target, f"[{address_target}]")
            return _Value(global_.type_, info, load_target)
        if expr.name in self._sema.function_signatures:
            self._emit_function_address(expr.name, target)
            return _Value(
                self._function_designator_value_type(self._expr_type(expr)),
                _ScalarInfo(8, 8, False),
                target,
            )
        if self._sema.file_scope is not None:
            symbol = self._sema.file_scope.lookup(expr.name)
            if isinstance(symbol, VarSymbol):
                if self._is_aggregate_type(symbol.type_) or symbol.type_.is_array():
                    self._emit_external_data_address(expr.name, target)
                    return _Value(symbol.type_.pointer_to(), _ScalarInfo(8, 8, False), target)
                info = self._slot_info(symbol.type_)
                address_target = self._gpr_target(target)
                self._emit_external_data_address(expr.name, address_target)
                load_target = self._float_target(target) if info.is_float else target
                self._emit_load_from_address(info, load_target, f"[{address_target}]")
                return _Value(symbol.type_, info, load_target)
        raise self._error(f"Unknown identifier: {expr.name}")

    def _emit_func_name_literal(self, expr: Identifier, target: str) -> _Value:
        assert self._func is not None
        label = self._string_literal_label(StringLiteral(f'"{self._func.name}"'))
        self._emit(f"lea {target}, [rip + {label}]")
        return _Value(self._expr_type(expr), _ScalarInfo(8, 8, False), target)

    def _emit_call(
        self, expr: CallExpr, target: str, aggregate_return_address: str | None = None
    ) -> _Value:
        callee_name = expr.callee.name if isinstance(expr.callee, Identifier) else None
        if callee_name == "__builtin_va_start":
            return self._emit_va_start(expr)
        if callee_name == "__builtin_va_end":
            return self._emit_va_end(expr)
        if callee_name == "__builtin_va_copy":
            return self._emit_va_copy(expr)
        if callee_name is not None:
            builtin_value = self._emit_common_builtin(callee_name, expr, target)
            if builtin_value is not None:
                return builtin_value
        if callee_name is not None and callee_name.startswith("__atomic_"):
            atomic_value = self._emit_atomic_builtin(callee_name, expr, target)
            if atomic_value is not None:
                return atomic_value
        if callee_name in {
            "__builtin_isfinite",
            "__builtin_isinf",
            "__builtin_isinf_sign",
            "__builtin_isnan",
            "__builtin_isnormal",
            "__builtin_signbit",
        }:
            return self._emit_float_class_builtin(callee_name, expr, target)
        direct_name = (
            expr.callee.name
            if (
                isinstance(expr.callee, Identifier)
                and expr.callee.name in self._sema.function_signatures
                and self._lookup_slot(expr.callee.name) is None
            )
            else None
        )
        if direct_name is not None:
            direct_name = {
                "__builtin_bzero": "bzero",
                "__builtin___bzero": "bzero",
                "__builtin_memcpy": "memcpy",
                "__builtin_memmove": "memmove",
                "__builtin_memset": "memset",
            }.get(direct_name, direct_name)
        result_type = self._expr_type(expr)
        aggregate_result = self._is_aggregate_type(result_type)
        memory_result = aggregate_result and self._aggregate_return_uses_memory(result_type)
        if memory_result and aggregate_return_address is None:
            slot = self._aggregate_call_slots.get(id(expr))
            if slot is None:
                raise self._error("x86_64 target needs address for indirect aggregate return")
            self._emit(f"lea rcx, {self._slot_addr(slot)}")
            aggregate_return_address = "rcx"
        if aggregate_result and not memory_result:
            self._small_aggregate_return_chunks(result_type)
        call_args = self._classify_call_args(expr.args, int_arg_reg=1 if memory_result else 0)
        values_on_stack = 0
        stack_arg_count = sum(1 for arg in call_args if arg.location == "stack")
        if memory_result and aggregate_return_address is not None:
            self._push_stack(aggregate_return_address)
            values_on_stack += 1
        pad_stack = (self._stack_depth + stack_arg_count) % 2 == 1
        if pad_stack:
            self._push_stack("0")
            values_on_stack += 1
        pushed_call_results: set[int] = set()
        pushed_conditional_aggregates: set[int] = set()
        pushed_compound_literals: set[int] = set()
        reversed_args = list(reversed(call_args))
        for arg in reversed_args:
            if arg.aggregate_type is not None and isinstance(arg.expr, CallExpr):
                expr_id = id(arg.expr)
                if expr_id in pushed_call_results:
                    continue
                chunks = [candidate for candidate in reversed_args if candidate.expr is arg.expr]
                self._push_aggregate_call_result_arg(arg.expr, chunks)
                values_on_stack += len(chunks)
                pushed_call_results.add(expr_id)
                continue
            if arg.aggregate_type is not None and isinstance(arg.expr, ConditionalExpr):
                expr_id = id(arg.expr)
                if expr_id in pushed_conditional_aggregates:
                    continue
                chunks = [candidate for candidate in reversed_args if candidate.expr is arg.expr]
                self._push_aggregate_conditional_arg(arg.expr, chunks)
                values_on_stack += len(chunks)
                pushed_conditional_aggregates.add(expr_id)
                continue
            if arg.aggregate_type is not None and isinstance(arg.expr, CompoundLiteralExpr):
                expr_id = id(arg.expr)
                if expr_id in pushed_compound_literals:
                    continue
                chunks = [candidate for candidate in reversed_args if candidate.expr is arg.expr]
                self._push_aggregate_expr_arg_chunks(arg.expr, chunks)
                values_on_stack += len(chunks)
                pushed_compound_literals.add(expr_id)
                continue
            self._push_call_arg(arg)
            values_on_stack += 1
        for arg in call_args:
            if arg.location == "stack":
                continue
            if arg.info.is_float:
                self._pop_float_arg(arg.info, self._FP_ARG_REGS[arg.index])
            else:
                self._pop_stack(self._INT_ARG_REGS[arg.index])
            values_on_stack -= 1
        if memory_result:
            sret_offset = (values_on_stack - 1) * 8
            self._emit(f"mov rdi, QWORD PTR {self._address_operand('rsp', sret_offset)}")
        if direct_name is None:
            self._emit_expr(expr.callee, "r11")
            self._emit(f"mov eax, {self._used_fp_arg_regs(call_args)}")
            self._emit("call r11")
        else:
            self._emit(f"mov eax, {self._used_fp_arg_regs(call_args)}")
            self._emit(f"call {self._symbol_name(direct_name)}")
        cleanup = values_on_stack * 8
        if cleanup:
            self._emit(f"add rsp, {cleanup}")
            self._stack_depth -= values_on_stack
        if aggregate_result:
            return _Value(result_type, self._slot_info(result_type), "rax")
        if self._is_void_type(result_type):
            return _Value(result_type, _ScalarInfo(4, 4, False), "rax")
        info = self._scalar_info(result_type)
        if info.is_float:
            target = self._float_target(target)
            if target != "xmm0":
                self._emit_float_move(info, target, "xmm0")
            return _Value(result_type, info, target)
        if target != "rax":
            self._emit(f"mov {self._sized_reg(target, info)}, {self._sized_reg('rax', info)}")
        return _Value(result_type, info, target)

    def _emit_va_start(self, expr: CallExpr) -> _Value:
        if len(expr.args) != 2:
            raise self._error("x86_64 target requires two arguments for va_start")
        last_arg = expr.args[1]
        if not isinstance(last_arg, Identifier):
            raise self._error("x86_64 target requires named va_start anchor")
        gp_offset, fp_offset, overflow_offset = self._variadic_start_state(last_arg.name)
        if self._va_reg_save_slot is None:
            raise self._error("x86_64 target missing variadic register save area")
        self._emit_address(expr.args[0], "rcx")
        self._emit(f"mov DWORD PTR [rcx], {gp_offset}")
        self._emit(f"mov DWORD PTR [rcx + 4], {fp_offset}")
        self._emit(f"lea r10, [rbp + {overflow_offset}]")
        self._emit("mov QWORD PTR [rcx + 8], r10")
        self._emit(f"lea r10, {self._slot_addr(self._va_reg_save_slot)}")
        self._emit("mov QWORD PTR [rcx + 16], r10")
        return _Value(VOID, _ScalarInfo(4, 4, False), "rax")

    def _emit_va_end(self, expr: CallExpr) -> _Value:
        if len(expr.args) != 1:
            raise self._error("x86_64 target requires one argument for va_end")
        return _Value(VOID, _ScalarInfo(4, 4, False), "rax")

    def _emit_va_copy(self, expr: CallExpr) -> _Value:
        if len(expr.args) != 2:
            raise self._error("x86_64 target requires two arguments for va_copy")
        self._emit_va_list_storage_address(expr.args[0], "rcx")
        self._emit("push rcx")
        self._emit_va_list_storage_address(expr.args[1], "rdx")
        self._emit("mov r10, QWORD PTR [rdx]")
        self._emit("mov r11, QWORD PTR [rdx + 8]")
        self._emit("mov rax, QWORD PTR [rdx + 16]")
        self._emit("pop rcx")
        self._emit("mov QWORD PTR [rcx], r10")
        self._emit("mov QWORD PTR [rcx + 8], r11")
        self._emit("mov QWORD PTR [rcx + 16], rax")
        return _Value(VOID, _ScalarInfo(4, 4, False), "rax")

    def _emit_common_builtin(self, callee_name: str, expr: CallExpr, target: str) -> _Value | None:
        if callee_name == "__builtin_unreachable":
            self._emit("ud2")
            return _Value(VOID, _ScalarInfo(4, 4, False), "rax")
        if callee_name == "__builtin_expect" and expr.args:
            value = self._emit_expr(expr.args[0], target)
            result_type = self._expr_type(expr)
            result_info = self._scalar_info(result_type)
            self._coerce_value(value, result_type, result_info)
            return _Value(result_type, result_info, self._coerced_reg(value, result_info))
        if callee_name == "__builtin_assume_aligned" and expr.args:
            return self._emit_expr(expr.args[0], target)
        if callee_name in {"__builtin_alloca", "__builtin_alloca_with_align"}:
            return self._emit_alloca_builtin(callee_name, expr, target)
        if callee_name in {"__builtin_frame_address", "__builtin_return_address"}:
            return self._emit_address_builtin(callee_name, expr, target)
        if callee_name in {
            "__builtin_bswap16",
            "__builtin_bswap32",
            "__builtin_bswap64",
            "__builtin_clz",
            "__builtin_clzl",
            "__builtin_clzll",
            "__builtin_ctz",
            "__builtin_ctzl",
            "__builtin_ctzll",
            "__builtin_popcount",
            "__builtin_popcountl",
            "__builtin_popcountll",
        }:
            return self._emit_integer_bit_builtin(callee_name, expr, target)
        if callee_name in {
            "__builtin_inff",
            "__builtin_inf",
            "__builtin_infl",
            "__builtin_huge_valf",
            "__builtin_huge_val",
            "__builtin_huge_vall",
            "__builtin_nanf",
            "__builtin_nan",
            "__builtin_nanl",
        }:
            float_value = float("nan") if "nan" in callee_name else float("inf")
            return self._emit_float_constant_builtin(expr, target, float_value)
        return None

    def _emit_alloca_builtin(self, callee_name: str, expr: CallExpr, target: str) -> _Value:
        if not expr.args:
            raise self._error(f"x86_64 target requires size argument for {callee_name}")
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        target = self._gpr_target(target)
        value = self._emit_expr(expr.args[0], "rax")
        if value.info.is_float:
            raise self._error(f"x86_64 target requires integer size for {callee_name}")
        if value.reg != "rax":
            self._emit(
                f"mov {self._sized_reg('rax', value.info)}, "
                f"{self._sized_reg(value.reg, value.info)}"
            )
        self._emit("add rax, 15")
        self._emit("and rax, -16")
        self._emit("sub rsp, rax")
        if target != "rsp":
            self._emit(f"mov {target}, rsp")
        return _Value(result_type, result_info, target)

    def _emit_address_builtin(self, callee_name: str, expr: CallExpr, target: str) -> _Value:
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        target = self._gpr_target(target)
        level = self._eval_int_constant(expr.args[0]) if expr.args else 0
        if level not in {0, None}:
            self._emit_load_immediate(target, 0, result_info)
        elif callee_name == "__builtin_frame_address":
            self._emit(f"mov {target}, rbp")
        else:
            self._emit(f"mov {target}, QWORD PTR [rbp + 8]")
        return _Value(result_type, result_info, target)

    def _emit_integer_bit_builtin(self, callee_name: str, expr: CallExpr, target: str) -> _Value:
        if not expr.args:
            raise self._error(f"x86_64 target requires argument for {callee_name}")
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        target = self._gpr_target(target)
        value = self._emit_expr(expr.args[0], "rax")
        source_info = value.info
        if value.info.is_float:
            raise self._error(f"x86_64 target requires integer argument for {callee_name}")
        if value.reg != "rax":
            self._emit(
                f"mov {self._sized_reg('rax', source_info)}, "
                f"{self._sized_reg(value.reg, source_info)}"
            )
        op_info = _ScalarInfo(8, 8, False) if source_info.size == 8 else _ScalarInfo(4, 4, False)
        if callee_name == "__builtin_bswap16":
            self._emit("rol ax, 8")
            self._emit("movzx eax, ax")
        elif callee_name == "__builtin_bswap32":
            self._emit("bswap eax")
        elif callee_name == "__builtin_bswap64":
            self._emit("bswap rax")
        elif callee_name.startswith("__builtin_ctz"):
            self._emit(f"bsf {self._sized_reg('rax', op_info)}, {self._sized_reg('rax', op_info)}")
        elif callee_name.startswith("__builtin_clz"):
            bits = 64 if op_info.size == 8 else 32
            self._emit(f"bsr {self._sized_reg('rax', op_info)}, {self._sized_reg('rax', op_info)}")
            self._emit(f"xor eax, {bits - 1}")
        elif callee_name.startswith("__builtin_popcount"):
            self._emit_popcount_loop(op_info)
        if target != "rax":
            self._emit(f"mov {self._sized_reg(target, result_info)}, eax")
        return _Value(result_type, result_info, target)

    def _emit_popcount_loop(self, info: _ScalarInfo) -> None:
        loop_label = self._new_label("popcount_loop")
        done_label = self._new_label("popcount_done")
        source = self._sized_reg("rax", info)
        scratch = self._sized_reg("r11", info)
        self._emit("xor r10d, r10d")
        self._lines.append(f"{loop_label}:")
        self._emit(f"test {source}, {source}")
        self._emit(f"je {done_label}")
        self._emit(f"mov {scratch}, {source}")
        self._emit(f"and {scratch}, 1")
        self._emit("add r10d, r11d")
        self._emit(f"shr {source}, 1")
        self._emit(f"jmp {loop_label}")
        self._lines.append(f"{done_label}:")
        self._emit("mov eax, r10d")

    def _emit_float_constant_builtin(self, expr: CallExpr, target: str, value: float) -> _Value:
        result_type = self._expr_type(expr)
        info = self._scalar_info(result_type)
        if info.size not in {4, 8}:
            info = _ScalarInfo(8, 8, True, is_float=True)
        target = self._float_target(target)
        bits = self._float_to_bits(value, info.size)
        label = self._float_literals.get((bits, info.size))
        if label is None:
            label = f".LCF{len(self._float_literals)}"
            self._float_literals[(bits, info.size)] = label
        self._emit_float_load(info, target, f"[rip + {label}]")
        return _Value(result_type, info, target)

    def _emit_atomic_builtin(self, callee_name: str, expr: CallExpr, target: str) -> _Value | None:
        if callee_name == "__atomic_thread_fence":
            self._emit("mfence")
            return _Value(VOID, _ScalarInfo(4, 4, False), "rax")
        if callee_name == "__atomic_load_n":
            pointee, info = self._emit_atomic_pointer_arg(expr, 0, "rcx")
            load_target = self._float_target(target) if info.is_float else self._gpr_target(target)
            self._emit_load_from_address(info, load_target, "[rcx]")
            return _Value(pointee, info, load_target)
        if callee_name == "__atomic_store_n":
            pointee, info = self._emit_atomic_pointer_arg(expr, 0, "rcx")
            self._emit("push rcx")
            value_target = self._float_target("rax") if info.is_float else "rax"
            value = self._emit_expr(expr.args[1], value_target)
            self._coerce_value(value, pointee, info)
            source = self._coerced_reg(value, info)
            self._emit("pop rcx")
            self._emit_store_to_address(info, source, "[rcx]")
            return _Value(VOID, _ScalarInfo(4, 4, False), "rax")
        if callee_name == "__atomic_load":
            pointee, info = self._emit_atomic_pointer_arg(expr, 0, "rcx")
            self._emit("push rcx")
            self._emit_expr(expr.args[1], "rdx")
            self._emit("pop rcx")
            temp = self._float_target("rax") if info.is_float else "rax"
            self._emit_load_from_address(info, temp, "[rcx]")
            self._emit_store_to_address(info, temp, "[rdx]")
            return _Value(VOID, _ScalarInfo(4, 4, False), "rax")
        if callee_name == "__atomic_store":
            pointee, info = self._emit_atomic_pointer_arg(expr, 0, "rcx")
            self._emit("push rcx")
            self._emit_expr(expr.args[1], "rdx")
            self._emit("pop rcx")
            temp = self._float_target("rax") if info.is_float else "rax"
            self._emit_load_from_address(info, temp, "[rdx]")
            self._emit_store_to_address(info, temp, "[rcx]")
            return _Value(VOID, _ScalarInfo(4, 4, False), "rax")
        if callee_name in {"__atomic_exchange_n", "__atomic_fetch_add", "__atomic_fetch_sub"}:
            pointee, info = self._emit_atomic_pointer_arg(expr, 0, "rcx")
            self._emit("push rcx")
            value = self._emit_expr(expr.args[1], "rax")
            self._coerce_value(value, pointee, info)
            if self._coerced_reg(value, info) != "rax":
                self._emit(
                    f"mov {self._sized_reg('rax', info)}, "
                    f"{self._sized_reg(self._coerced_reg(value, info), info)}"
                )
            if callee_name == "__atomic_fetch_sub":
                self._emit(f"neg {self._sized_reg('rax', info)}")
            self._emit("pop rcx")
            if callee_name == "__atomic_exchange_n":
                self._emit(f"xchg {self._mem(info, '[rcx]')}, {self._sized_reg('rax', info)}")
            else:
                self._emit(f"lock xadd {self._mem(info, '[rcx]')}, {self._sized_reg('rax', info)}")
            return _Value(pointee, info, "rax")
        if callee_name in {"__atomic_fetch_and", "__atomic_fetch_or", "__atomic_fetch_xor"}:
            op = {
                "__atomic_fetch_and": "and",
                "__atomic_fetch_or": "or",
                "__atomic_fetch_xor": "xor",
            }[callee_name]
            pointee, info = self._emit_atomic_pointer_arg(expr, 0, "rcx")
            self._emit("push rcx")
            value = self._emit_expr(expr.args[1], "r10")
            self._coerce_value(value, pointee, info)
            if self._coerced_reg(value, info) != "r10":
                self._emit(
                    f"mov {self._sized_reg('r10', info)}, "
                    f"{self._sized_reg(self._coerced_reg(value, info), info)}"
                )
            self._emit("pop rcx")
            retry = self._new_label("atomic_fetch_retry")
            self._emit_load_from_address(info, "rax", "[rcx]")
            self._lines.append(f"{retry}:")
            self._emit(f"mov {self._sized_reg('r11', info)}, {self._sized_reg('rax', info)}")
            self._emit(f"{op} {self._sized_reg('r11', info)}, {self._sized_reg('r10', info)}")
            self._emit(f"lock cmpxchg {self._mem(info, '[rcx]')}, {self._sized_reg('r11', info)}")
            self._emit(f"jne {retry}")
            return _Value(pointee, info, "rax")
        if callee_name == "__atomic_compare_exchange_n":
            pointee, info = self._emit_atomic_pointer_arg(expr, 0, "rcx")
            self._emit("push rcx")
            self._emit_expr(expr.args[1], "rdx")
            self._emit("push rdx")
            desired = self._emit_expr(expr.args[2], "r11")
            self._coerce_value(desired, pointee, info)
            if self._coerced_reg(desired, info) != "r11":
                self._emit(
                    f"mov {self._sized_reg('r11', info)}, "
                    f"{self._sized_reg(self._coerced_reg(desired, info), info)}"
                )
            self._emit("pop rdx")
            self._emit("pop rcx")
            self._emit_load_from_address(info, "rax", "[rdx]")
            self._emit(f"lock cmpxchg {self._mem(info, '[rcx]')}, {self._sized_reg('r11', info)}")
            self._emit("sete r10b")
            self._emit("movzx r10d, r10b")
            done = self._new_label("atomic_cmpxchg_done")
            self._emit("test r10d, r10d")
            self._emit(f"jne {done}")
            self._emit_store_to_address(info, "rax", "[rdx]")
            self._lines.append(f"{done}:")
            if target != "rax":
                self._emit(f"mov {self._sized_reg(target, _ScalarInfo(4, 4, False))}, r10d")
                return _Value(INT, _ScalarInfo(4, 4, False), target)
            self._emit("mov eax, r10d")
            return _Value(INT, _ScalarInfo(4, 4, False), "rax")
        return None

    def _emit_atomic_pointer_arg(
        self, expr: CallExpr, index: int, target: str
    ) -> tuple[Type, _ScalarInfo]:
        if len(expr.args) <= index:
            raise self._error("x86_64 target requires atomic pointer argument")
        value = self._emit_expr(expr.args[index], target)
        pointee = value.type_.pointee()
        if pointee is None:
            raise self._error("x86_64 target requires pointer atomic argument")
        info = self._scalar_info(pointee)
        if value.reg != target:
            self._emit(f"mov {target}, {value.reg}")
        return pointee, info

    def _emit_va_arg(self, expr: BuiltinVaArgExpr, target: str) -> _Value:
        result_type = self._expr_type(expr)
        if self._is_aggregate_type(result_type):
            raise self._error("x86_64 target does not support aggregate va_arg yet")
        info = self._scalar_info(result_type)
        self._emit_va_list_storage_address(expr.ap, "rcx")
        offset_field = 4 if info.is_float else 0
        offset_step = 16 if info.is_float else 8
        register_limit = 160 if info.is_float else 40
        overflow_label = self._new_label("va_arg_overflow")
        done_label = self._new_label("va_arg_done")
        self._emit(f"mov eax, DWORD PTR [rcx + {offset_field}]")
        self._emit(f"cmp eax, {register_limit}")
        self._emit(f"ja {overflow_label}")
        self._emit("mov r11, QWORD PTR [rcx + 16]")
        self._emit("add r11, rax")
        result_reg = self._float_target(target) if info.is_float else self._gpr_target(target)
        self._emit_load_from_address(info, result_reg, "[r11]")
        self._emit(f"add DWORD PTR [rcx + {offset_field}], {offset_step}")
        self._emit(f"jmp {done_label}")
        self._lines.append(f"{overflow_label}:")
        self._emit("mov r11, QWORD PTR [rcx + 8]")
        self._emit_load_from_address(info, result_reg, "[r11]")
        self._emit("add r11, 8")
        self._emit("mov QWORD PTR [rcx + 8], r11")
        self._lines.append(f"{done_label}:")
        return _Value(result_type, info, result_reg)

    def _emit_va_list_storage_address(self, expr: Expr, target: str) -> Type:
        if isinstance(expr, Identifier):
            slot = self._lookup_slot(expr.name)
            if (
                slot is not None
                and self._is_va_list_type(slot.type_)
                and self._param_slots.get(expr.name) is slot
            ):
                self._emit_load_from_address(
                    _ScalarInfo(8, 8, False), target, self._slot_addr(slot)
                )
                return VOID.pointer_to()
        return self._emit_address(expr, target)

    def _variadic_start_state(self, last_param_name: str) -> tuple[int, int, int]:
        if self._func is None:
            raise self._error("va_start outside function")
        int_arg_reg = 1 if self._sret_slot is not None else 0
        fp_arg_reg = 0
        stack_arg_offset = 16
        for param in self._func.params:
            if param.name is None:
                continue
            slot = self._require_slot(param.name)
            if self._is_aggregate_type(slot.type_):
                chunks = self._aggregate_chunks(slot.type_)
                if self._aggregate_uses_registers(slot.type_, chunks, int_arg_reg, fp_arg_reg):
                    int_arg_reg += sum(1 for chunk in chunks if not chunk.info.is_float)
                    fp_arg_reg += sum(1 for chunk in chunks if chunk.info.is_float)
                else:
                    stack_arg_offset += 8 * len(chunks)
            elif slot.info.is_float:
                if fp_arg_reg < len(self._FP_ARG_REGS):
                    fp_arg_reg += 1
                else:
                    stack_arg_offset += 8
            else:
                if int_arg_reg < len(self._INT_ARG_REGS):
                    int_arg_reg += 1
                else:
                    stack_arg_offset += 8
            if param.name == last_param_name:
                return int_arg_reg * 8, 48 + fp_arg_reg * 16, stack_arg_offset
        raise self._error(f"x86_64 target cannot find va_start anchor {last_param_name}")

    def _classify_call_args(
        self, args: list[Expr], int_arg_reg: int = 0, fp_arg_reg: int = 0
    ) -> list[_CallArg]:
        stack_arg = 0
        result: list[_CallArg] = []
        for arg in args:
            arg_type = self._expr_type(arg).decay_parameter_type()
            if self._is_va_list_type(arg_type):
                arg_type = VOID.pointer_to()
            if self._is_aggregate_type(arg_type):
                chunks = self._aggregate_chunks(arg_type)
                if self._aggregate_uses_registers(arg_type, chunks, int_arg_reg, fp_arg_reg):
                    for chunk in chunks:
                        if chunk.info.is_float:
                            result.append(
                                _CallArg(
                                    arg,
                                    arg_type,
                                    chunk.info,
                                    "fp_reg",
                                    fp_arg_reg,
                                    chunk.offset,
                                    arg_type,
                                )
                            )
                            fp_arg_reg += 1
                        else:
                            result.append(
                                _CallArg(
                                    arg,
                                    arg_type,
                                    chunk.info,
                                    "int_reg",
                                    int_arg_reg,
                                    chunk.offset,
                                    arg_type,
                                )
                            )
                            int_arg_reg += 1
                else:
                    for chunk in chunks:
                        result.append(
                            _CallArg(
                                arg,
                                arg_type,
                                chunk.info,
                                "stack",
                                stack_arg,
                                chunk.offset,
                                arg_type,
                            )
                        )
                        stack_arg += 1
                continue
            info = self._scalar_info(arg_type)
            if info.is_float:
                if fp_arg_reg < len(self._FP_ARG_REGS):
                    result.append(_CallArg(arg, arg_type, info, "fp_reg", fp_arg_reg))
                    fp_arg_reg += 1
                else:
                    result.append(_CallArg(arg, arg_type, info, "stack", stack_arg))
                    stack_arg += 1
                continue
            if int_arg_reg < len(self._INT_ARG_REGS):
                result.append(_CallArg(arg, arg_type, info, "int_reg", int_arg_reg))
                int_arg_reg += 1
            else:
                result.append(_CallArg(arg, arg_type, info, "stack", stack_arg))
                stack_arg += 1
        return result

    def _push_call_arg(self, arg: _CallArg) -> None:
        if arg.aggregate_type is None:
            value = self._emit_expr(arg.expr, "xmm0" if arg.info.is_float else "rax")
            self._coerce_value(value, arg.type_, arg.info)
            self._push_call_value(_Value(arg.type_, arg.info, self._coerced_reg(value, arg.info)))
            return
        self._emit_address(arg.expr, "rax")
        address = "[rax]" if arg.offset == 0 else f"[rax + {arg.offset}]"
        if arg.info.is_float:
            self._emit_float_load(arg.info, "xmm0", address)
            self._push_call_value(_Value(arg.type_, arg.info, "xmm0"))
            return
        self._emit_load_from_address(arg.info, "rax", address)
        self._push_call_value(_Value(arg.type_, arg.info, "rax"))

    def _push_aggregate_call_result_arg(self, expr: CallExpr, chunks: list[_CallArg]) -> None:
        result_type = self._expr_type(expr)
        if self._aggregate_return_uses_memory(result_type):
            raise self._error("x86_64 target cannot pass indirect aggregate call result yet")
        self._emit_call(expr, "rax")
        return_regs = self._aggregate_return_registers(result_type)
        for arg in chunks:
            reg = return_regs.get(arg.offset)
            if reg is None:
                raise self._error("x86_64 target cannot find aggregate return chunk")
            if arg.info.is_float:
                self._push_call_value(_Value(arg.type_, arg.info, reg))
            elif arg.info.size == 8:
                self._push_stack(reg)
            else:
                if reg != "rax":
                    source = self._sized_reg(reg, arg.info)
                    self._emit(f"mov {self._sized_reg('rax', arg.info)}, {source}")
                self._push_call_value(_Value(arg.type_, arg.info, "rax"))

    def _push_aggregate_conditional_arg(
        self, expr: ConditionalExpr, chunks: list[_CallArg]
    ) -> None:
        false_label = self._new_label("aggregate_arg_cond_false")
        end_label = self._new_label("aggregate_arg_cond_end")
        base_depth = self._stack_depth
        self._emit_branch_if_zero(expr.condition, false_label)
        self._push_aggregate_expr_arg_chunks(expr.then_expr, chunks)
        then_depth = self._stack_depth
        self._emit(f"jmp {end_label}")
        self._lines.append(f"{false_label}:")
        self._stack_depth = base_depth
        self._push_aggregate_expr_arg_chunks(expr.else_expr, chunks)
        else_depth = self._stack_depth
        if then_depth != else_depth:
            raise self._error("x86_64 target conditional aggregate argument stack mismatch")
        self._stack_depth = then_depth
        self._lines.append(f"{end_label}:")

    def _push_aggregate_expr_arg_chunks(self, expr: Expr, chunks: list[_CallArg]) -> None:
        if isinstance(expr, CallExpr):
            self._push_aggregate_call_result_arg(expr, chunks)
            return
        if isinstance(expr, ConditionalExpr):
            self._push_aggregate_conditional_arg(expr, chunks)
            return
        self._emit_address(expr, "r11")
        for arg in chunks:
            address = "[r11]" if arg.offset == 0 else f"[r11 + {arg.offset}]"
            if arg.info.is_float:
                self._emit_float_load(arg.info, "xmm0", address)
                self._push_call_value(_Value(arg.type_, arg.info, "xmm0"))
                continue
            self._emit_load_from_address(arg.info, "rax", address)
            self._push_call_value(_Value(arg.type_, arg.info, "rax"))

    def _push_call_value(self, value: _Value) -> None:
        if value.info.is_float:
            self._emit("sub rsp, 8")
            self._stack_depth += 1
            self._emit_float_store(value.info, value.reg, "[rsp]")
            return
        self._emit_integer_to_64(value)
        self._push_stack("rax")

    def _pop_float_arg(self, info: _ScalarInfo, target: str) -> None:
        self._emit_float_load(info, target, "[rsp]")
        self._emit("add rsp, 8")
        self._stack_depth -= 1

    @staticmethod
    def _used_fp_arg_regs(args: list[_CallArg]) -> int:
        used = [arg.index for arg in args if arg.location == "fp_reg"]
        return max(used) + 1 if used else 0

    def _emit_unary(self, expr: UnaryExpr, target: str) -> _Value:
        if expr.op == "&":
            type_ = self._expr_type(expr)
            self._emit_address(expr.operand, target)
            return _Value(type_, _ScalarInfo(8, 8, False), target)
        if expr.op == "*":
            address_target = self._gpr_target(target)
            pointer_value = self._emit_expr(expr.operand, address_target)
            pointee = pointer_value.type_.pointee()
            if pointee is None:
                pointee = pointer_value.type_.element_type()
            if pointee is None:
                raise self._error(f"Cannot dereference non-pointer {pointer_value.type_}")
            if (
                self._is_aggregate_type(pointee)
                or pointee.is_array()
                or self._is_function_type(pointee)
            ):
                return _Value(pointee, self._slot_info(pointee), address_target)
            info = self._scalar_info(pointee)
            load_target = self._float_target(target) if info.is_float else address_target
            self._emit_load_from_address(info, load_target, f"[{address_target}]")
            return _Value(pointee, info, load_target)
        if expr.op == "+":
            return self._emit_expr(expr.operand, target)
        if expr.op == "-":
            operand_info = self._scalar_info(self._expr_type(expr.operand))
            result_target = self._float_target(target) if operand_info.is_float else target
            value = self._emit_expr(expr.operand, result_target)
            if value.info.is_float:
                self._emit_float_neg(value.info, value.reg)
            else:
                self._emit(f"neg {self._sized_reg(result_target, value.info)}")
            return value
        if expr.op == "~":
            value = self._emit_expr(expr.operand, target)
            self._emit(f"not {self._sized_reg(target, value.info)}")
            return value
        if expr.op == "!":
            value = self._emit_expr(expr.operand)
            if value.info.is_float:
                self._emit_float_zero_compare(value.info, value.reg)
                self._emit("sete al")
                self._emit("setnp r10b")
                self._emit("and al, r10b")
            else:
                self._emit("cmp rax, 0")
                self._emit("sete al")
            self._emit("movzx eax, al")
            return _Value(INT, self._scalar_info(INT), target)
        raise self._error(f"x86_64 target does not support unary {expr.op}")

    def _emit_update(self, expr: UpdateExpr, target: str) -> _Value:
        type_ = self._expr_type(expr.operand)
        info = self._scalar_info(type_)
        address_reg = self._update_address_register(target)
        old_reg = self._postfix_old_value_register(target, address_reg)
        if isinstance(expr.operand, MemberExpr):
            access = self._record_member_access(expr.operand)
            if access.bit_width is not None:
                self._emit_member_access_address(expr.operand, address_reg, access)
                self._emit_bitfield_load(access, info, target, f"[{address_reg}]")
                if expr.is_postfix:
                    self._emit(
                        f"mov {self._sized_reg(old_reg, info)}, {self._sized_reg(target, info)}"
                    )
                delta = 1
                if self._is_pointer_type(type_):
                    delta = self._pointer_step_size(type_)
                op = "add" if expr.op == "++" else "sub"
                self._emit(f"{op} {self._sized_reg(target, info)}, {delta}")
                self._emit_bitfield_store(access, info, target, f"[{address_reg}]")
                if expr.is_postfix:
                    self._emit(
                        f"mov {self._sized_reg(target, info)}, {self._sized_reg(old_reg, info)}"
                    )
                return _Value(type_, info, target)
        self._emit_address(expr.operand, address_reg)
        self._emit_load_from_address(info, target, f"[{address_reg}]")
        if expr.is_postfix:
            self._emit(f"mov {self._sized_reg(old_reg, info)}, {self._sized_reg(target, info)}")
        delta = 1
        if self._is_pointer_type(type_):
            delta = self._pointer_step_size(type_)
        op = "add" if expr.op == "++" else "sub"
        self._emit(f"{op} {self._sized_reg(target, info)}, {delta}")
        self._emit_store_to_address(info, target, f"[{address_reg}]")
        if expr.is_postfix:
            self._emit(f"mov {self._sized_reg(target, info)}, {self._sized_reg(old_reg, info)}")
        return _Value(type_, info, target)

    def _emit_binary(self, expr: BinaryExpr, target: str) -> _Value:
        if expr.op in {"&&", "||"}:
            return self._emit_short_circuit(expr, target)
        if self._is_pointer_binary(
            expr.op, self._expr_type(expr.left), self._expr_type(expr.right)
        ):
            return self._emit_pointer_binary(expr, target)
        result_type = self._expr_type(expr)
        info = self._scalar_info(result_type)
        common_type = usual_arithmetic_conversion(
            self._expr_type(expr.left), self._expr_type(expr.right)
        )
        if common_type is None:
            left_type = self._expr_type(expr.left)
            right_type = self._expr_type(expr.right)
            raise self._error(
                f"x86_64 target cannot convert operands for {expr.op}: {left_type} and {right_type}"
            )
        common_info = self._scalar_info(common_type)
        if common_info.is_float:
            return self._emit_float_binary(expr, target)
        target = self._gpr_target(target)
        left = self._emit_expr(expr.left, target)
        self._coerce_value(left, common_type, common_info)
        self._emit("push rax")
        right = self._emit_expr(expr.right, target)
        self._coerce_value(right, common_type, common_info)
        self._emit(
            f"mov {self._sized_reg('r10', common_info)}, {self._sized_reg(target, common_info)}"
        )
        self._emit("pop rax")
        if expr.op in {"+", "-", "*", "&", "|", "^"}:
            opcode = {
                "+": "add",
                "-": "sub",
                "*": "imul",
                "&": "and",
                "|": "or",
                "^": "xor",
            }[expr.op]
            left_reg = self._sized_reg("rax", common_info)
            right_reg = self._sized_reg("r10", common_info)
            self._emit(f"{opcode} {left_reg}, {right_reg}")
        elif expr.op in {"/", "%"}:
            if common_info.signed:
                self._emit("cqo" if common_info.size == 8 else "cdq")
                self._emit(f"idiv {self._sized_reg('r10', common_info)}")
            else:
                self._emit("xor edx, edx")
                self._emit(f"div {self._sized_reg('r10', common_info)}")
            if expr.op == "%":
                dst_reg = self._sized_reg("rax", common_info)
                rem_reg = self._sized_reg("rdx", common_info)
                self._emit(f"mov {dst_reg}, {rem_reg}")
        elif expr.op in {"<<", ">>"}:
            self._emit("mov rcx, r10")
            instruction = (
                "sar"
                if expr.op == ">>" and common_info.signed
                else "shr"
                if expr.op == ">>"
                else "sal"
            )
            self._emit(f"{instruction} {self._sized_reg('rax', common_info)}, cl")
        elif expr.op in {"==", "!=", "<", "<=", ">", ">="}:
            self._emit(
                f"cmp {self._sized_reg('rax', common_info)}, {self._sized_reg('r10', common_info)}"
            )
            condition = self._comparison_condition(expr.op, common_info.signed)
            self._emit(f"set{condition} al")
            self._emit("movzx eax, al")
            return _Value(result_type, info, target)
        else:
            raise self._error(f"x86_64 target does not support binary {expr.op}")
        self._coerce_register(common_info, info, "rax")
        if target != "rax":
            self._emit(f"mov {self._sized_reg(target, info)}, {self._sized_reg('rax', info)}")
        return _Value(result_type, info, target)

    def _emit_short_circuit(self, expr: BinaryExpr, target: str) -> _Value:
        done_label = self._new_label("logic_done")
        selected_label = self._new_label("logic_selected")
        if expr.op == "&&":
            self._emit_branch_if_zero(expr.left, selected_label)
            self._emit_branch_if_zero(expr.right, selected_label)
            self._emit("mov eax, 1")
            self._emit(f"jmp {done_label}")
            self._lines.append(f"{selected_label}:")
            self._emit("xor eax, eax")
        else:
            self._emit_branch_if_nonzero(expr.left, selected_label)
            self._emit_branch_if_nonzero(expr.right, selected_label)
            self._emit("xor eax, eax")
            self._emit(f"jmp {done_label}")
            self._lines.append(f"{selected_label}:")
            self._emit("mov eax, 1")
        self._lines.append(f"{done_label}:")
        if target != "rax":
            self._emit(f"mov {target}, rax")
        return _Value(self._expr_type(expr), self._scalar_info(self._expr_type(expr)), target)

    def _emit_pointer_binary(self, expr: BinaryExpr, target: str) -> _Value:
        target = self._gpr_target(target)
        left_type = self._expr_type(expr.left)
        right_type = self._expr_type(expr.right)
        result_type = self._expr_type(expr)
        if (
            expr.op in {"+", "-"}
            and self._is_pointer_like_type(left_type)
            and is_integer_type(right_type)
        ):
            self._emit_expr(expr.left, target)
            self._emit("push rax")
            index = self._emit_expr(expr.right, target)
            self._emit_integer_to_64(index)
            step = self._pointer_step_size(left_type)
            if step != 1:
                self._emit(f"imul rax, {step}")
            self._emit("mov r10, rax")
            self._emit("pop rax")
            self._emit(("sub" if expr.op == "-" else "add") + " rax, r10")
            return _Value(result_type, self._scalar_info(result_type), target)
        if expr.op == "+" and is_integer_type(left_type) and self._is_pointer_like_type(right_type):
            swapped = BinaryExpr("+", expr.right, expr.left)
            self._type_map.set(swapped, result_type)
            return self._emit_pointer_binary(swapped, target)
        if (
            expr.op == "-"
            and self._is_pointer_like_type(left_type)
            and self._is_pointer_like_type(right_type)
        ):
            self._emit_expr(expr.left, target)
            self._emit("push rax")
            self._emit_expr(expr.right, target)
            self._emit("mov r10, rax")
            self._emit("pop rax")
            self._emit("sub rax, r10")
            step = self._pointer_step_size(left_type)
            if step != 1:
                self._emit("cqo")
                self._emit(f"mov r10, {step}")
                self._emit("idiv r10")
            return _Value(result_type, self._scalar_info(result_type), target)
        if expr.op in {"==", "!=", "<", "<=", ">", ">="}:
            self._emit_expr(expr.left, target)
            self._emit("push rax")
            self._emit_expr(expr.right, target)
            self._emit("mov r10, rax")
            self._emit("pop rax")
            self._emit("cmp rax, r10")
            self._emit(f"set{self._comparison_condition(expr.op, False)} al")
            self._emit("movzx eax, al")
            return _Value(result_type, self._scalar_info(result_type), target)
        raise self._error(f"x86_64 target does not support pointer binary {expr.op}")

    def _emit_assign(self, expr: AssignExpr, target: str) -> _Value:
        if expr.op != "=":
            return self._emit_compound_assign(expr, target)
        target_type = self._expr_type(expr.target)
        if self._is_aggregate_type(target_type):
            target_size = self._type_size(target_type)
            if target_size is None:
                raise self._error("x86_64 target cannot size aggregate assignment target")
            self._emit_address(expr.target, "rcx")
            self._emit_aggregate_expr_to_address(target_type, expr.value, "rcx")
            return _Value(target_type, self._slot_info(target_type), "rcx")
        info = self._scalar_info(target_type)
        value = self._emit_expr(expr.value, self._float_target(target) if info.is_float else target)
        self._coerce_value(value, target_type, info)
        if info.is_float:
            self._emit_address(expr.target, "rcx")
            source = self._coerced_reg(value, info)
            self._emit_store_to_address(info, source, "[rcx]")
            return _Value(target_type, info, source)
        if isinstance(expr.target, MemberExpr):
            access = self._record_member_access(expr.target)
            if access.bit_width is not None:
                source = self._coerced_reg(value, info)
                if source != "rax":
                    self._emit(
                        f"mov {self._sized_reg('rax', info)}, {self._sized_reg(source, info)}"
                    )
                self._emit("push rax")
                self._emit_member_access_address(expr.target, "rcx", access)
                self._emit("pop rax")
                self._emit_bitfield_store(access, info, "rax", "[rcx]")
                return _Value(target_type, info, "rax")
        self._emit("push rax")
        self._emit_address(expr.target, "rcx")
        self._emit("pop rax")
        self._emit_store_to_address(info, "rax", "[rcx]")
        return _Value(target_type, info, target)

    def _emit_compound_assign(self, expr: AssignExpr, target: str) -> _Value:
        op = expr.op.removesuffix("=")
        target_type = self._expr_type(expr.target)
        info = self._scalar_info(target_type)
        if self._is_pointer_type(target_type) and op in {"+", "-"}:
            return self._emit_pointer_compound_assign(expr, op, target_type, info, target)
        if info.is_float:
            return self._emit_float_compound_assign(expr, op, target_type, info, target)
        if isinstance(expr.target, MemberExpr):
            access = self._record_member_access(expr.target)
            if access.bit_width is not None:
                self._emit_member_access_address(expr.target, "rcx", access)
                self._emit("push rcx")
                self._emit_bitfield_load(access, info, target, "[rcx]")
                self._emit("push rax")
                value = self._emit_expr(expr.value, target)
                self._coerce_value(value, target_type, info)
                self._emit(f"mov {self._sized_reg('r10', info)}, {self._sized_reg(target, info)}")
                self._emit("pop rax")
                self._emit_integer_compound_op(op, info)
                self._emit("pop rcx")
                self._emit_bitfield_store(access, info, "rax", "[rcx]")
                return _Value(target_type, info, target)
        self._emit_address(expr.target, "rcx")
        self._emit("push rcx")
        self._emit_load_from_address(info, target, "[rcx]")
        self._emit("push rax")
        value = self._emit_expr(expr.value, target)
        self._coerce_value(value, target_type, info)
        self._emit(f"mov {self._sized_reg('r10', info)}, {self._sized_reg(target, info)}")
        self._emit("pop rax")
        self._emit_integer_compound_op(op, info)
        self._emit("pop rcx")
        self._emit_store_to_address(info, "rax", "[rcx]")
        return _Value(target_type, info, target)

    def _emit_pointer_compound_assign(
        self,
        expr: AssignExpr,
        op: str,
        target_type: Type,
        info: _ScalarInfo,
        target: str,
    ) -> _Value:
        target = self._gpr_target(target)
        self._emit_address(expr.target, "rcx")
        self._emit("push rcx")
        self._emit_load_from_address(info, "rax", "[rcx]")
        self._emit("push rax")
        value = self._emit_expr(expr.value, "rax")
        if not is_integer_type(unqualified_type(value.type_)):
            raise self._error("x86_64 target requires integer pointer offset")
        self._emit_integer_to_64(value)
        step = self._pointer_step_size(target_type)
        if step != 1:
            self._emit(f"imul rax, {step}")
        self._emit("mov r10, rax")
        self._emit("pop rax")
        instruction = "add" if op == "+" else "sub"
        self._emit(f"{instruction} rax, r10")
        self._emit("pop rcx")
        self._emit_store_to_address(info, "rax", "[rcx]")
        if target != "rax":
            self._emit(f"mov {target}, rax")
        return _Value(target_type, info, target)

    def _emit_integer_compound_op(self, op: str, info: _ScalarInfo) -> None:
        if op in {"+", "-", "*", "&", "|", "^"}:
            opcode = {"+": "add", "-": "sub", "*": "imul", "&": "and", "|": "or", "^": "xor"}[op]
            self._emit(f"{opcode} {self._sized_reg('rax', info)}, {self._sized_reg('r10', info)}")
        elif op in {"/", "%"}:
            if info.signed:
                self._emit("cqo" if info.size == 8 else "cdq")
                self._emit(f"idiv {self._sized_reg('r10', info)}")
            else:
                self._emit("xor edx, edx")
                self._emit(f"div {self._sized_reg('r10', info)}")
            if op == "%":
                self._emit(f"mov {self._sized_reg('rax', info)}, {self._sized_reg('rdx', info)}")
        elif op in {"<<", ">>"}:
            self._emit("mov rcx, r10")
            instruction = "sar" if op == ">>" and info.signed else "shr" if op == ">>" else "sal"
            self._emit(f"{instruction} {self._sized_reg('rax', info)}, cl")
        else:
            raise self._error(f"x86_64 target does not support compound assignment {op}=")

    def _emit_float_compound_assign(
        self,
        expr: AssignExpr,
        op: str,
        target_type: Type,
        info: _ScalarInfo,
        target: str,
    ) -> _Value:
        if op not in {"+", "-", "*", "/"}:
            raise self._error(
                f"x86_64 target does not support floating compound assignment {expr.op}"
            )
        self._emit_address(expr.target, "rcx")
        self._emit("push rcx")
        self._emit_float_load(info, "xmm0", "[rcx]")
        self._emit("sub rsp, 8")
        self._emit_float_store(info, "xmm0", "[rsp]")
        value = self._emit_expr(expr.value, "xmm0")
        self._coerce_value(value, target_type, info)
        self._emit_float_move(info, "xmm1", self._coerced_reg(value, info))
        self._emit_float_load(info, "xmm0", "[rsp]")
        self._emit("add rsp, 8")
        suffix = "ss" if info.size == 4 else "sd"
        opcode = {"+": "add", "-": "sub", "*": "mul", "/": "div"}[op]
        self._emit(f"{opcode}{suffix} xmm0, xmm1")
        self._emit("pop rcx")
        self._emit_float_store(info, "xmm0", "[rcx]")
        result_target = self._float_target(target)
        if result_target != "xmm0":
            self._emit_float_move(info, result_target, "xmm0")
        return _Value(target_type, info, result_target)

    def _emit_cast(self, expr: CastExpr, target: str) -> _Value:
        target_type = self._expr_type(expr)
        if self._is_void_type(target_type):
            self._emit_expr(expr.expr, target)
            return _Value(target_type, _ScalarInfo(4, 4, False), target)
        source_type = self._expr_type(expr.expr)
        source_value: _Value | None = None
        if source_type.is_array():
            element_type = source_type.element_type()
            if element_type is None:
                raise self._error(f"x86_64 target cannot decay array type {source_type}")
            source_type = element_type.pointer_to()
            value = self._emit_expr(expr.expr, self._gpr_target(target))
            source_value = _Value(source_type, self._scalar_info(source_type), value.reg)
            if self._is_pointer_type(target_type):
                return _Value(target_type, self._scalar_info(target_type), value.reg)
        info = self._scalar_info(target_type)
        source_info = self._scalar_info(source_type)
        value = source_value or self._emit_expr(
            expr.expr, self._float_target(target) if source_info.is_float else "rax"
        )
        self._coerce_value(value, target_type, info)
        if info.is_float:
            return _Value(target_type, info, self._float_target(target))
        result_reg = self._gpr_target(target)
        source_reg = "rax" if value.info.is_float else value.reg
        if source_reg != result_reg:
            self._emit(
                f"mov {self._sized_reg(result_reg, info)}, {self._sized_reg(source_reg, info)}"
            )
        return _Value(target_type, info, result_reg)

    def _emit_conditional(self, expr: ConditionalExpr, target: str) -> _Value:
        false_label = self._new_label("cond_false")
        end_label = self._new_label("cond_end")
        type_ = self._expr_type(expr)
        info = self._slot_info(type_)
        result_reg = self._float_target(target) if info.is_float else target
        self._emit_branch_if_zero(expr.condition, false_label)
        then_value = self._emit_expr(expr.then_expr, result_reg)
        if not (self._is_aggregate_type(type_) or type_.is_array()):
            self._coerce_value(then_value, type_, info)
        self._emit(f"jmp {end_label}")
        self._lines.append(f"{false_label}:")
        else_value = self._emit_expr(expr.else_expr, result_reg)
        if not (self._is_aggregate_type(type_) or type_.is_array()):
            self._coerce_value(else_value, type_, info)
        self._lines.append(f"{end_label}:")
        return _Value(type_, info, result_reg)

    def _emit_subscript(self, expr: SubscriptExpr, target: str) -> _Value:
        element_type = self._subscript_element_type(self._expr_type(expr.base))
        if element_type is None:
            raise self._error("Subscript requires array or pointer base")
        address_target = self._gpr_target(target)
        self._emit_address(expr, address_target)
        if self._is_aggregate_type(element_type) or element_type.is_array():
            return _Value(element_type, self._slot_info(element_type), address_target)
        info = self._scalar_info(element_type)
        load_target = self._float_target(target) if info.is_float else address_target
        self._emit_load_from_address(info, load_target, f"[{address_target}]")
        return _Value(element_type, info, load_target)

    def _emit_member(self, expr: MemberExpr, target: str) -> _Value:
        access = self._record_member_access(expr)
        address_target = self._gpr_target(target)
        self._emit_member_access_address(expr, address_target, access)
        if access.bit_width is not None:
            info = self._scalar_info(access.type_)
            self._emit_bitfield_load(access, info, address_target, f"[{address_target}]")
            return _Value(access.type_, info, address_target)
        if access.type_.is_array():
            return _Value(access.type_.pointer_to(), _ScalarInfo(8, 8, False), address_target)
        if self._is_aggregate_type(access.type_):
            return _Value(access.type_, self._slot_info(access.type_), address_target)
        info = self._scalar_info(access.type_)
        load_target = self._float_target(target) if info.is_float else address_target
        self._emit_load_from_address(info, load_target, f"[{address_target}]")
        return _Value(access.type_, info, load_target)

    def _emit_branch_if_zero(self, expr: Expr, label: str) -> None:
        value = self._emit_expr(expr)
        if value.info.is_float:
            not_zero_label = self._new_label("float_not_zero")
            self._emit_float_zero_compare(value.info, value.reg)
            self._emit(f"jp {not_zero_label}")
            self._emit(f"je {label}")
            self._lines.append(f"{not_zero_label}:")
            return
        self._emit("cmp rax, 0")
        self._emit(f"je {label}")

    def _emit_branch_if_nonzero(self, expr: Expr, label: str) -> None:
        value = self._emit_expr(expr)
        if value.info.is_float:
            self._emit_float_zero_compare(value.info, value.reg)
            self._emit(f"jp {label}")
            self._emit(f"jne {label}")
            return
        self._emit("cmp rax, 0")
        self._emit(f"jne {label}")

    def _emit_address(self, expr: Expr, target: str) -> Type:
        if isinstance(expr, Identifier):
            slot = self._lookup_slot(expr.name)
            if slot is not None:
                static_local = self._static_local_slot_marker(expr.name, slot)
                if static_local is not None:
                    self._emit(f"lea {target}, [rip + {static_local.label}]")
                    return static_local.type_
                self._emit(f"lea {target}, {self._slot_addr(slot)}")
                return slot.type_
            static_local = self._static_local(expr.name)
            if static_local is not None:
                self._emit(f"lea {target}, [rip + {static_local.label}]")
                return static_local.type_
            global_ = self._globals.get(expr.name)
            if global_ is not None:
                self._emit_global_address(global_, target)
                return global_.type_
            if expr.name in self._sema.function_signatures:
                self._emit_function_address(expr.name, target)
                return self._expr_type(expr)
            if self._sema.file_scope is not None:
                symbol = self._sema.file_scope.lookup(expr.name)
                if isinstance(symbol, VarSymbol):
                    self._emit_external_data_address(expr.name, target)
                    return symbol.type_
            raise self._error(f"Unknown identifier address: {expr.name}")
        if isinstance(expr, StringLiteral):
            label = self._string_literal_label(expr)
            self._emit(f"lea {target}, [rip + {label}]")
            return self._expr_type(expr)
        if isinstance(expr, CompoundLiteralExpr):
            slot = self._compound_literal_slots.get(id(expr))
            if slot is None:
                raise self._error("x86_64 target missing compound literal storage")
            self._emit(f"lea rcx, {self._slot_addr(slot)}")
            self._emit_compound_literal_to_address(slot.type_, expr.initializer, "rcx")
            if target != "rcx":
                self._emit(f"mov {target}, rcx")
            return slot.type_
        if isinstance(expr, CallExpr):
            slot = self._aggregate_call_slots.get(id(expr))
            if slot is None:
                raise self._error("x86_64 target cannot form address of scalar call result")
            if self._aggregate_return_uses_memory(slot.type_):
                self._emit(f"lea rcx, {self._slot_addr(slot)}")
                self._emit_call(expr, "rax", aggregate_return_address="rcx")
            else:
                self._emit_call(expr, "rax")
                self._emit(f"lea rcx, {self._slot_addr(slot)}")
                self._emit_aggregate_return_to_address(slot.type_, "rcx")
            self._emit(f"lea {target}, {self._slot_addr(slot)}")
            return slot.type_
        if isinstance(expr, UnaryExpr) and expr.op == "*":
            value = self._emit_expr(expr.operand, target)
            pointee = value.type_.pointee()
            if pointee is None:
                raise self._error("Cannot dereference non-pointer")
            return pointee
        if isinstance(expr, SubscriptExpr):
            base_type = self._emit_subscript_base_address(expr.base, target)
            element_type = self._subscript_element_type(base_type)
            if element_type is None:
                raise self._error("Subscript requires array or pointer base")
            self._emit("push rax" if target == "rax" else f"push {target}")
            index_value = self._emit_expr(expr.index)
            self._emit_integer_to_64(index_value)
            step = self._type_size(element_type)
            if step is None:
                raise self._error(f"x86_64 target cannot size subscript element {element_type}")
            if step != 1:
                self._emit(f"imul rax, {step}")
            self._emit("mov r10, rax")
            self._emit("pop rax" if target == "rax" else f"pop {target}")
            self._emit(f"add {target}, r10")
            return element_type
        if isinstance(expr, CommaExpr):
            self._emit_expr(expr.left)
            return self._emit_address(expr.right, target)
        if isinstance(expr, MemberExpr):
            access = self._emit_member_access_address(expr, target)
            if access.bit_width is not None:
                raise self._error("x86_64 target cannot take address of bit-field member")
            return access.type_
        raise self._error(f"x86_64 target cannot form address of {type(expr).__name__}")

    def _emit_member_access_address(
        self, expr: MemberExpr, target: str, access: _MemberAccess | None = None
    ) -> _MemberAccess:
        if access is None:
            access = self._record_member_access(expr)
        self._emit_member_storage_address(expr, target)
        if access.offset:
            self._emit(f"add {target}, {access.offset}")
        return access

    def _emit_subscript_base_address(self, expr: Expr, target: str) -> Type:
        type_ = self._expr_type(expr)
        if type_.is_array():
            self._emit_address(expr, target)
            return type_
        value = self._emit_expr(expr, target)
        return value.type_

    def _emit_member_storage_address(self, expr: MemberExpr, target: str) -> None:
        if expr.through_pointer:
            value = self._emit_expr(expr.base, target)
            if not self._is_pointer_type(value.type_):
                raise self._error("Arrow base is not pointer")
            return
        self._emit_address(expr.base, target)

    def _emit_string_literal(self, expr: StringLiteral, target: str) -> _Value:
        label = self._string_literal_label(expr)
        type_ = self._expr_type(expr)
        self._emit(f"lea {target}, [rip + {label}]")
        return _Value(type_, _ScalarInfo(8, 8, False), target)

    def _emit_float_literal(self, expr: FloatLiteral, target: str) -> _Value:
        type_ = self._expr_type(expr)
        info = self._scalar_info(type_)
        if info.size not in {4, 8}:
            info = _ScalarInfo(8, 8, True, is_float=True)
        target = self._float_target(target)
        bits = self._float_bits(expr.value, info.size)
        label = self._float_literals.get((bits, info.size))
        if label is None:
            label = f".LCF{len(self._float_literals)}"
            self._float_literals[(bits, info.size)] = label
        self._emit_float_load(info, target, f"[rip + {label}]")
        return _Value(type_, info, target)

    def _emit_sizeof(self, expr: SizeofExpr, target: str) -> _Value:
        type_ = self._sizeof_operand_type(expr)
        size = self._type_size(type_)
        if size is None:
            raise self._error(f"x86_64 target cannot size {type_}")
        result_type = self._expr_type(expr)
        info = self._scalar_info(result_type)
        self._emit_load_immediate(target, size, info)
        return _Value(result_type, info, target)

    def _emit_alignof(self, expr: AlignofExpr, target: str) -> _Value:
        type_ = self._sizeof_operand_type(expr)
        align = self._type_align(type_)
        if align is None:
            raise self._error(f"x86_64 target cannot align {type_}")
        result_type = self._expr_type(expr)
        info = self._scalar_info(result_type)
        self._emit_load_immediate(target, align, info)
        return _Value(result_type, info, target)

    def _emit_offsetof(self, expr: BuiltinOffsetofExpr, target: str) -> _Value:
        value = self._offsetof_value(expr)
        if value is None:
            raise self._error("x86_64 target cannot evaluate __builtin_offsetof")
        result_type = self._expr_type(expr)
        info = self._scalar_info(result_type)
        self._emit_load_immediate(target, value, info)
        return _Value(result_type, info, target)

    def _emit_local_array_initializer(self, slot: _Slot, init: InitList) -> None:
        element_type = slot.type_.element_type()
        if element_type is None:
            raise self._error("array initializer needs array destination")
        element_info = self._slot_info(element_type)
        length = slot.type_.declarator_ops[0][1]
        if not isinstance(length, int) or length < 0:
            raise self._error("x86_64 target requires known local array length")
        for index in range(slot.info.size):
            self._emit(
                f"mov {self._mem(_ScalarInfo(1, 1, False), self._slot_addr(slot, index))}, 0"
            )
        items = self._array_initializer_items_by_index(init)
        for index, item in items.items():
            if index >= length:
                continue
            address = self._slot_addr(slot, index * element_info.size)
            if self._is_aggregate_type(element_type):
                self._emit(f"lea rcx, {address}")
                if isinstance(item.initializer, InitList):
                    if not self._is_record_type(element_type):
                        raise self._error("x86_64 target only supports record array initializers")
                    self._emit_record_compound_initializer_to_address(
                        element_type, item.initializer, "rcx"
                    )
                    continue
                if isinstance(item.initializer, Expr):
                    self._emit_aggregate_expr_to_address(element_type, item.initializer, "rcx")
                    continue
                raise self._error("x86_64 target requires aggregate array initializer")
            if not isinstance(item.initializer, Expr):
                raise self._error("x86_64 target only supports scalar array initializers")
            value_target = self._float_target("rax") if element_info.is_float else "rax"
            value = self._emit_expr(item.initializer, value_target)
            self._coerce_value(value, element_type, element_info)
            source = self._coerced_reg(value, element_info)
            self._emit_store_to_address(element_info, source, address)

    def _emit_local_char_array_string_initializer(self, slot: _Slot, init: StringLiteral) -> None:
        data = self._string_literal_bytes(init)
        length_value = slot.type_.declarator_ops[0][1]
        if not isinstance(length_value, int) or length_value < 0:
            raise self._error("x86_64 target requires known char array length")
        data = data[:length_value] + b"\x00" * max(0, length_value - len(data))
        for index, byte in enumerate(data):
            self._emit(f"mov BYTE PTR {self._slot_addr(slot, index)}, {byte}")

    def _emit_float_binary(self, expr: BinaryExpr, target: str) -> _Value:
        common_type = usual_arithmetic_conversion(
            self._expr_type(expr.left), self._expr_type(expr.right)
        )
        if common_type is None:
            raise self._error(f"x86_64 target cannot convert floating operands for {expr.op}")
        common_info = self._scalar_info(common_type)
        if not common_info.is_float:
            raise self._error(f"x86_64 target expected floating operands for {expr.op}")
        left_info = self._scalar_info(self._expr_type(expr.left))
        right_info = self._scalar_info(self._expr_type(expr.right))
        left = self._emit_expr(expr.left, "xmm0" if left_info.is_float else "rax")
        self._coerce_value(left, common_type, common_info)
        self._emit("sub rsp, 8")
        self._emit_float_store(common_info, "xmm0", "[rsp]")
        right = self._emit_expr(expr.right, "xmm0" if right_info.is_float else "rax")
        self._coerce_value(right, common_type, common_info)
        self._emit_float_move(common_info, "xmm1", "xmm0")
        self._emit_float_load(common_info, "xmm0", "[rsp]")
        self._emit("add rsp, 8")
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        op_suffix = "ss" if common_info.size == 4 else "sd"
        if expr.op in {"+", "-", "*", "/"}:
            opcode = {
                "+": "add",
                "-": "sub",
                "*": "mul",
                "/": "div",
            }[expr.op]
            result_target = self._float_target(target)
            self._emit(f"{opcode}{op_suffix} xmm0, xmm1")
            if result_target != "xmm0":
                self._emit_float_move(common_info, result_target, "xmm0")
            return _Value(result_type, result_info, result_target)
        if expr.op in {"==", "!=", "<", "<=", ">", ">="}:
            self._emit(f"ucomi{op_suffix} xmm0, xmm1")
            condition = {
                "==": "e",
                "!=": "ne",
                "<": "b",
                "<=": "be",
                ">": "a",
                ">=": "ae",
            }[expr.op]
            self._emit(f"set{condition} al")
            if expr.op == "==":
                self._emit("setnp r10b")
                self._emit("and al, r10b")
            elif expr.op == "!=":
                self._emit("setp r10b")
                self._emit("or al, r10b")
            self._emit("movzx eax, al")
            if target != "rax":
                self._emit(f"mov {self._sized_reg(target, result_info)}, eax")
            return _Value(result_type, result_info, target)
        raise self._error(f"x86_64 target does not support floating binary {expr.op} yet")

    def _emit_float_load(self, info: _ScalarInfo, target: str, address: str) -> None:
        self._emit(f"{'movss' if info.size == 4 else 'movsd'} {target}, {address}")

    def _emit_float_store(self, info: _ScalarInfo, source: str, address: str) -> None:
        self._emit(f"{'movss' if info.size == 4 else 'movsd'} {address}, {source}")

    def _emit_float_move(self, info: _ScalarInfo, target: str, source: str) -> None:
        self._emit(f"{'movss' if info.size == 4 else 'movsd'} {target}, {source}")

    def _emit_float_neg(self, info: _ScalarInfo, target: str) -> None:
        mask = "0x80000000" if info.size == 4 else "0x8000000000000000"
        self._emit(f"mov r10, {mask}")
        self._emit("movq xmm15, r10")
        self._emit(f"{'xorps' if info.size == 4 else 'xorpd'} {target}, xmm15")

    def _emit_float_zero_compare(self, info: _ScalarInfo, reg: str) -> None:
        self._emit("pxor xmm15, xmm15")
        self._emit(f"{'ucomiss' if info.size == 4 else 'ucomisd'} {reg}, xmm15")

    def _emit_float_class_builtin(self, callee_name: str, expr: CallExpr, target: str) -> _Value:
        result_type = self._expr_type(expr)
        result_info = self._scalar_info(result_type)
        if not expr.args:
            self._emit_load_immediate(target, 0, result_info)
            return _Value(result_type, result_info, target)
        value = self._emit_expr(expr.args[0], self._float_target(target))
        float_type = value.type_ if value.info.is_float and value.info.size in {4, 8} else DOUBLE
        if value.info.is_float and value.info.size in {4, 8}:
            float_info = value.info
        else:
            float_info = self._scalar_info(float_type)
        self._coerce_value(value, float_type, float_info)
        if callee_name == "__builtin_isnan":
            compare = "ucomiss" if float_info.size == 4 else "ucomisd"
            self._emit(f"{compare} xmm0, xmm0")
            self._emit("setp al")
            self._emit("movzx eax, al")
            if target != "rax":
                self._emit(f"mov {self._sized_reg(target, result_info)}, eax")
            return _Value(result_type, result_info, target)
        if callee_name == "__builtin_signbit":
            if float_info.size == 4:
                self._emit("movd r11d, xmm0")
                self._emit("shr r11d, 31")
            else:
                self._emit("movq r11, xmm0")
                self._emit("shr r11, 63")
            self._emit("mov eax, r11d")
            if target != "rax":
                self._emit(f"mov {self._sized_reg(target, result_info)}, eax")
            return _Value(result_type, result_info, target)
        if float_info.size == 4:
            self._emit("movd r11d, xmm0")
            self._emit("mov r10d, r11d")
            self._emit("and r10d, 0x7fffffff")
            self._emit("cmp r10d, 0x7f800000")
        else:
            self._emit("movq r11, xmm0")
            self._emit("mov r10, r11")
            self._emit("mov rax, 0x7fffffffffffffff")
            self._emit("and r10, rax")
            self._emit("mov rax, 0x7ff0000000000000")
            self._emit("cmp r10, rax")
        if callee_name == "__builtin_isnormal":
            if float_info.size == 4:
                self._emit("cmp r10d, 0x007fffff")
                self._emit("seta al")
                self._emit("cmp r10d, 0x7f800000")
            else:
                self._emit("mov rax, 0x000fffffffffffff")
                self._emit("cmp r10, rax")
                self._emit("seta al")
                self._emit("mov rax, 0x7ff0000000000000")
                self._emit("cmp r10, rax")
            self._emit("setb r11b")
            self._emit("and al, r11b")
            self._emit("movzx eax, al")
        elif callee_name == "__builtin_isfinite":
            self._emit("setb al")
            self._emit("movzx eax, al")
        elif callee_name == "__builtin_isinf":
            self._emit("sete al")
            self._emit("movzx eax, al")
        else:
            zero_label = self._new_label("isinf_sign.zero")
            done_label = self._new_label("isinf_sign.done")
            self._emit(f"jne {zero_label}")
            self._emit("mov eax, 1")
            sign_test = "test r11, r11" if float_info.size == 8 else "test r11d, r11d"
            self._emit(sign_test)
            self._emit(f"jns {done_label}")
            self._emit("neg eax")
            self._emit(f"jmp {done_label}")
            self._lines.append(f"{zero_label}:")
            self._emit("xor eax, eax")
            self._lines.append(f"{done_label}:")
        if target != "rax":
            self._emit(f"mov {self._sized_reg(target, result_info)}, eax")
        return _Value(result_type, result_info, target)

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
                self._lines.append(".data")
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
                self._lines.append(".data")
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
                self._lines.append(".data")
                emitted_section = True
            align = self._type_align(type_) or 1
            self._lines.append(f".p2align {max(0, align.bit_length() - 1)}")
            self._lines.append(f"{label}:")
            self._emit_global_initializer(type_, init)

    def _emit_global_initializer(self, type_: Type, init: Expr | InitList | None) -> None:
        if isinstance(init, StringLiteral) and type_.is_array():
            self._emit_global_char_array_string_initializer(type_, init)
            return
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
            raise self._error("x86_64 target does not support aggregate global initializer yet")
        if isinstance(init, CompoundLiteralExpr) and not self._is_pointer_type(type_):
            compound_type = self._complete_array_initializer_type(
                self._type_map.get(init) or self._resolve_type_spec(init.type_spec),
                init.initializer,
            )
            self._emit_global_initializer(compound_type, init.initializer)
            return
        if isinstance(init, Expr):
            self._emit_global_scalar_initializer(type_, init)
            return
        self._emit_global_zero(type_)

    def _emit_global_array_initializer(self, type_: Type, init: InitList) -> None:
        completed_type = self._complete_array_initializer_type(type_, init)
        element_type = completed_type.element_type()
        if element_type is None:
            raise self._error("x86_64 target cannot initialize non-array as array")
        length = completed_type.declarator_ops[0][1]
        if not isinstance(length, int) or length < 0:
            raise self._error("x86_64 target requires known global array initializer length")
        items_by_index = self._array_initializer_items_by_index(init)
        for index in range(length):
            item = items_by_index.get(index)
            if item is None:
                self._emit_global_zero(element_type)
            else:
                self._emit_global_initializer(element_type, item.initializer)

    def _emit_global_record_initializer(self, type_: Type, init: InitList) -> None:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            raise self._error(f"x86_64 target cannot initialize record {type_}")
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
                raise self._error(f"x86_64 target cannot size record {type_}")
            if size > member_size:
                self._lines.append(f"    .zero {size - member_size}")
            return
        items_by_index = self._record_initializer_items_by_index(members, init)
        offset = 0
        active_bit_base = 0
        active_bit_size = 0
        active_bit_used = 0
        active_bit_type: Type | None = None
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
            if active_bit_base > offset:  # pragma: no cover - bitfield base tracks offset
                self._lines.append(f"    .zero {active_bit_base - offset}")
            self._emit_global_int_constant(self._scalar_info(active_bit_type), active_bit_value)
            offset = active_bit_base + active_bit_size
            active_bit_type = None
            active_bit_used = 0
            active_bit_value = 0

        for index, member in enumerate(members):
            member_align = self._member_align(member)
            member_size = self._type_size(member.type_)
            is_flexible_tail = (
                self._is_flexible_array_member(member.type_) and index == len(members) - 1
            )
            if member_size is None and is_flexible_tail:
                member_size = 0
            if member_align is None or member_size is None:
                raise self._error(f"x86_64 target cannot size record member {member.name}")
            if member.bit_width is not None:
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
                        raise self._error("x86_64 target requires scalar bit-field initializer")
                    bitfield_value = self._eval_int_constant(bitfield_item.initializer)
                    if bitfield_value is None:
                        raise self._error("x86_64 target requires constant bit-field initializer")
                    active_bit_value |= (
                        bitfield_value & ((1 << member.bit_width) - 1)
                    ) << active_bit_used
                active_bit_used += member.bit_width
                continue
            flush_bitfield_unit()
            access_offset = self._align_to(offset, member_align)
            if access_offset > offset:
                self._lines.append(f"    .zero {access_offset - offset}")
            member_item = items_by_index.get(index)
            if is_flexible_tail:
                if member_item is not None and not (
                    isinstance(member_item.initializer, Expr)
                    and self._is_zero_initializer(member_item.initializer)
                ):
                    self._emit_global_initializer(member.type_, member_item.initializer)
                offset = access_offset
                continue
            if member_item is None:
                if member_size:
                    self._emit_global_zero(member.type_)
            else:
                if (
                    isinstance(member_item.initializer, Expr)
                    and self._is_aggregate_type(member.type_)
                    and self._is_zero_initializer(member_item.initializer)
                ):
                    self._emit_global_zero(member.type_)
                else:
                    self._emit_global_initializer(member.type_, member_item.initializer)
            offset = access_offset + member_size
        flush_bitfield_unit()
        size = self._type_size(type_)
        if size is None:
            raise self._error(f"x86_64 target cannot size type {type_}")
        if size > offset:
            self._lines.append(f"    .zero {size - offset}")

    def _emit_record_compound_initializer_to_address(
        self, type_: Type, init: InitList, address_reg: str
    ) -> None:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            raise self._error(f"x86_64 target cannot initialize record {type_}")
        size = self._type_size(type_)
        if size is None:
            raise self._error(f"x86_64 target cannot size record {type_}")
        self._emit_zero_memory(address_reg, size)
        items_by_index = self._record_initializer_items_by_index(members, init)
        for member_index, item in items_by_index.items():
            access = self._record_member_access_by_index(type_, member_index)
            if access is None:
                raise self._error("x86_64 target cannot find record initializer member")
            if isinstance(item.initializer, InitList):
                self._emit(f"push {address_reg}")
                self._emit_address_offset("r10", address_reg, access.offset)
                self._emit_compound_literal_to_address(access.type_, item.initializer, "r10")
                self._emit(f"pop {address_reg}")
                continue
            if access.bit_width is not None:
                if not isinstance(item.initializer, Expr):
                    raise self._error("x86_64 target requires scalar bit-field initializer")
                info = self._scalar_info(access.type_)
                self._emit(f"push {address_reg}")
                value = self._emit_expr(item.initializer)
                self._coerce_value(value, access.type_, info)
                self._emit(f"pop {address_reg}")
                self._emit_address_offset("r11", address_reg, access.offset)
                self._emit_bitfield_store(access, info, self._coerced_reg(value, info), "[r11]")
                continue
            if self._is_aggregate_type(access.type_):
                if not isinstance(item.initializer, Expr):
                    raise self._error("x86_64 target requires aggregate initializer list")
                if self._is_zero_initializer(item.initializer):
                    continue
                member_size = self._type_size(access.type_)
                if member_size is None:
                    raise self._error("x86_64 target cannot size aggregate initializer member")
                self._emit(f"push {address_reg}")
                self._emit_address(item.initializer, "rdx")
                self._emit(f"pop {address_reg}")
                self._emit_address_offset("r11", address_reg, access.offset)
                self._emit_copy_memory("r11", "rdx", member_size)
                continue
            if not isinstance(item.initializer, Expr):
                raise self._error("x86_64 target requires scalar initializer")
            info = self._scalar_info(access.type_)
            self._emit(f"push {address_reg}")
            value_target = self._float_target("rax") if info.is_float else "rax"
            value = self._emit_expr(item.initializer, value_target)
            self._coerce_value(value, access.type_, info)
            source = self._coerced_reg(value, info)
            if not info.is_float and source != "rax":
                self._emit(f"mov {self._sized_reg('rax', info)}, {self._sized_reg(source, info)}")
                source = "rax"
            self._emit(f"pop {address_reg}")
            self._emit_address_offset("r11", address_reg, access.offset)
            self._emit_store_to_address(info, source, "[r11]")

    def _record_member_access_by_index(
        self, type_: Type, member_index: int
    ) -> _MemberAccess | None:
        members = self._sema.record_definitions.get(type_.name)
        if members is None or member_index >= len(members):
            return None
        member = members[member_index]
        if type_.name.startswith("union "):
            bit_offset = 0 if member.bit_width is not None else None
            return _MemberAccess(0, member.type_, bit_offset=bit_offset, bit_width=member.bit_width)
        offset = 0
        active_bit_base = 0
        active_bit_used = 0
        active_bit_type: Type | None = None
        for index, current in enumerate(members):
            member_size = self._type_size(current.type_)
            member_align = self._member_align(current)
            if (
                member_size is None
                and self._is_flexible_array_member(current.type_)
                and index == len(members) - 1
            ):
                member_size = 0
            if member_size is None or member_align is None:
                return None
            if current.bit_width is not None:
                if current.bit_width == 0:
                    active_bit_type = None
                    active_bit_used = 0
                    offset = self._align_to(offset, member_align)
                    continue
                if (
                    active_bit_type != current.type_
                    or active_bit_used + current.bit_width > member_size * 8
                ):
                    offset = self._align_to(offset, member_align)
                    active_bit_base = offset
                    active_bit_used = 0
                    active_bit_type = current.type_
                    offset += member_size
                if index == member_index:
                    return _MemberAccess(
                        active_bit_base,
                        current.type_,
                        active_bit_used,
                        current.bit_width,
                    )
                active_bit_used += current.bit_width
                continue
            active_bit_type = None
            active_bit_used = 0
            offset = self._align_to(offset, member_align)
            if index == member_index:
                return _MemberAccess(offset, current.type_)
            offset += member_size
        return None

    def _array_initializer_items_by_index(self, init: InitList) -> dict[int, InitItem]:
        items_by_index: dict[int, InitItem] = {}
        positional_index = 0
        for item in init.items:
            if not item.designators:
                item_index = positional_index
            else:
                if len(item.designators) != 1:
                    raise self._error("x86_64 target does not support nested array designators yet")
                kind, value = item.designators[0]
                if kind != "index" or not isinstance(value, Expr):
                    raise self._error("x86_64 target does not support global array designator")
                const_index = self._eval_int_constant(value)
                if const_index is None:
                    raise self._error("x86_64 target requires constant array designator")
                item_index = const_index
            items_by_index[item_index] = item
            positional_index = item_index + 1
        return items_by_index

    def _record_initializer_items_by_index(
        self, members: tuple[RecordMemberInfo, ...], init: InitList
    ) -> dict[int, InitItem]:
        items_by_index: dict[int, InitItem] = {}
        nested_items_by_index: dict[int, list[InitItem]] = {}
        positional_index = 0
        for item in init.items:
            member_name = self._record_init_first_member_designator_name(item)
            if member_name is None:
                member_index = self._record_initializer_next_positional_index(
                    members, positional_index
                )
                if member_index >= len(members):
                    raise self._error("x86_64 target found too many record initializers")
                items_by_index[member_index] = item
                nested_items_by_index.pop(member_index, None)
            else:
                member_index, is_direct = self._record_initializer_member_index(
                    members, member_name
                )
                if member_index < 0:
                    raise self._error(f"x86_64 target cannot find member {member_name}")
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
    def _record_initializer_next_positional_index(
        members: tuple[RecordMemberInfo, ...], positional_index: int
    ) -> int:
        while positional_index < len(members):
            member = members[positional_index]
            if member.name is not None or member.bit_width is None:
                return positional_index
            positional_index += 1
        return positional_index

    @staticmethod
    def _record_init_first_member_designator_name(item: InitItem) -> str | None:
        if not item.designators:
            return None
        kind, value = item.designators[0]
        if kind == "member" and isinstance(value, str):
            return value
        return None

    def _record_initializer_member_index(
        self, members: tuple[RecordMemberInfo, ...], member_name: str
    ) -> tuple[int, bool]:
        for index, member in enumerate(members):
            if member.name == member_name:
                return index, True
        for index, member in enumerate(members):
            if member.name is not None:
                continue
            if self._record_member_access_match(member.type_, member_name) is not None:
                return index, False
        return -1, False

    def _emit_global_char_array_string_initializer(self, type_: Type, init: StringLiteral) -> None:
        length_value = type_.declarator_ops[0][1]
        if not isinstance(length_value, int) or length_value < 0:
            raise self._error("x86_64 target requires known string array length")
        data = self._string_literal_bytes(init)
        data = data[:length_value] + b"\x00" * max(0, length_value - len(data))
        self._emit_bytes(data)

    def _emit_global_scalar_initializer(self, type_: Type, init: Expr) -> None:
        info = self._scalar_info(type_)
        if self._is_pointer_type(type_) or self._is_function_type(type_):
            if isinstance(init, CompoundLiteralExpr):
                compound_type = self._complete_array_initializer_type(
                    self._type_map.get(init) or self._resolve_type_spec(init.type_spec),
                    init.initializer,
                )
                label = self._add_global_compound_literal(compound_type, init.initializer)
                self._lines.append(f"    .quad {label}")
                return
            address = self._global_pointer_initializer_address(init)
            if address is not None:
                label, offset = address
                suffix = "" if offset == 0 else f" + {offset}" if offset > 0 else f" - {-offset}"
                self._lines.append(f"    .quad {label}{suffix}")
                return
        if info.is_float:
            value = self._eval_float_constant(init)
            if value is None:
                raise self._error("x86_64 target requires constant floating initializer")
            bits = self._float_to_bits(value, info.size)
            if info.size == 8:
                self._lines.append(f"    .quad 0x{bits:016x}")
            elif info.size == 4:
                self._lines.append(f"    .long 0x{bits:08x}")
            else:
                bits = self._float_to_bits(value, 8)
                self._lines.append(f"    .quad 0x{bits:016x}")
                self._lines.append("    .zero 8")
            return
        value = self._eval_int_constant(init)
        if value is None:
            raise self._error("x86_64 target requires constant scalar initializer")
        self._emit_global_int_constant(info, value)

    def _global_pointer_initializer_address(self, init: Expr) -> tuple[str, int] | None:
        if isinstance(init, StringLiteral):
            return self._string_literal_label(init), 0
        if isinstance(init, CastExpr):
            return self._global_pointer_initializer_address(init.expr)
        if isinstance(init, ConditionalExpr):
            condition = self._eval_int_constant(init.condition)
            if condition is None:
                return None
            return self._global_pointer_initializer_address(
                init.then_expr if condition else init.else_expr
            )
        if isinstance(init, BinaryExpr):
            return self._global_pointer_binary_initializer_address(init)
        init_type = self._type_map.get(init)
        if init_type is not None and init_type.is_array():
            return self._global_lvalue_initializer_symbol(init)
        if isinstance(init, UnaryExpr) and init.op == "&":
            return self._global_lvalue_initializer_symbol(init.operand)
        if isinstance(init, Identifier):
            if init.name in self._sema.function_signatures:
                return self._symbol_name(init.name), 0
            return self._global_lvalue_initializer_symbol(init)
        if self._is_null_pointer_initializer(init):
            return None
        return None

    def _global_pointer_binary_initializer_address(
        self, init: BinaryExpr
    ) -> tuple[str, int] | None:
        if init.op not in {"+", "-"}:
            return None
        left = self._global_pointer_offset_initializer_address(init.left, init.right, init.op)
        if left is not None:
            return left
        if init.op == "+":
            return self._global_pointer_offset_initializer_address(init.right, init.left, init.op)
        return None

    def _global_pointer_offset_initializer_address(
        self, base_expr: Expr, offset_expr: Expr, op: str
    ) -> tuple[str, int] | None:
        base = self._global_pointer_initializer_address(base_expr)
        index = self._eval_int_constant(offset_expr)
        if base is None or index is None:
            return None
        base_type = self._type_map.get(base_expr)
        if base_type is None:
            return None
        if base_type.is_array():
            element_type = base_type.element_type()
        elif self._is_pointer_type(base_type):
            element_type = base_type.pointee()
        else:
            element_type = None
        if element_type is None:
            return None
        element_size = self._type_size(element_type)
        if element_size is None:
            return None
        delta = index * element_size
        if op == "-":
            delta = -delta
        return base[0], base[1] + delta

    def _global_lvalue_initializer_symbol(self, expr: Expr) -> tuple[str, int] | None:
        if isinstance(expr, UnaryExpr) and expr.op == "&":
            return self._global_lvalue_initializer_symbol(expr.operand)
        if isinstance(expr, Identifier):
            static_local = self._static_local_initializer(expr.name)
            if static_local is not None:
                return static_local.label, 0
            if expr.name in self._sema.function_signatures:
                return self._symbol_name(expr.name), 0
            global_ = self._globals.get(expr.name)
            if global_ is not None:
                return global_.label, 0
            if self._sema.file_scope is not None:
                symbol = self._sema.file_scope.lookup(expr.name)
                if isinstance(symbol, VarSymbol):
                    return self._symbol_name(expr.name), 0
        if isinstance(expr, CompoundLiteralExpr):
            compound_type = self._complete_array_initializer_type(
                self._type_map.get(expr) or self._resolve_type_spec(expr.type_spec),
                expr.initializer,
            )
            label = self._add_global_compound_literal(compound_type, expr.initializer)
            return label, 0
        if isinstance(expr, MemberExpr):
            base = self._global_lvalue_initializer_symbol(expr.base)
            if base is None:
                return None
            access = self._record_member_access(expr)
            return base[0], base[1] + access.offset
        if isinstance(expr, SubscriptExpr):
            base_type = self._expr_type(expr.base)
            if not base_type.is_array():
                return None
            element_type = base_type.element_type()
            if element_type is None:
                return None
            element_size = self._type_size(element_type)
            index = self._eval_int_constant(expr.index)
            if element_size is None or index is None:
                return None
            base = self._global_lvalue_initializer_symbol(expr.base)
            if base is None:
                return None
            return base[0], base[1] + index * element_size
        return None

    def _add_global_compound_literal(self, type_: Type, init: InitList) -> str:
        label = f".Lcompound{len(self._compound_literals)}"
        self._compound_literals.append((label, type_, init))
        return label

    def _emit_global_zero(self, type_: Type) -> None:
        size = self._type_size(type_)
        if size is None:
            raise self._error(f"x86_64 target cannot size type {type_}")
        self._lines.append(f"    .zero {size}")

    def _emit_global_int_constant(self, info: _ScalarInfo, value: int) -> None:
        mask = (1 << info.bits) - 1
        value &= mask
        if info.size == 1:
            self._lines.append(f"    .byte {value}")
        elif info.size == 2:
            self._lines.append(f"    .short {value}")
        elif info.size == 4:
            self._lines.append(f"    .long {value}")
        elif info.size == 8:
            self._lines.append(f"    .quad {value}")
        else:
            raise self._error(f"x86_64 target cannot emit {info.size}-byte integer")

    def _emit_bytes(self, data: bytes) -> None:
        if not data:
            return
        for offset in range(0, len(data), 16):
            chunk = data[offset : offset + 16]
            self._lines.append("    .byte " + ", ".join(str(byte) for byte in chunk))

    def _sizeof_operand_type(self, expr: SizeofExpr | AlignofExpr) -> Type:
        if expr.type_spec is not None:
            return self._resolve_type_spec(expr.type_spec)
        if expr.expr is None:
            raise self._error("sizeof/_Alignof missing operand")
        if isinstance(expr.expr, Identifier):
            slot = self._lookup_slot(expr.expr.name)
            if slot is not None:
                return self._codegen_type(slot.type_)
        type_ = self._type_map.get(expr.expr)
        if type_ is not None:
            return self._codegen_type(type_)
        if isinstance(expr.expr, Identifier) and self._func_sym is not None:
            symbol = self._func_sym.locals.get(expr.expr.name)
            if isinstance(symbol, VarSymbol):
                return self._codegen_type(symbol.type_)
        if isinstance(expr.expr, Identifier) and self._sema.file_scope is not None:
            symbol = self._sema.file_scope.lookup(expr.expr.name)
            if isinstance(symbol, VarSymbol):
                return self._codegen_type(symbol.type_)
        if isinstance(expr.expr, MemberExpr):
            base_raw = self._type_map.get(expr.expr.base)
            if base_raw is not None:
                base_type = self._codegen_type(base_raw)
                if expr.expr.through_pointer:
                    base_type = base_type.pointee() or base_type
                access = self._record_member_access_match(base_type, expr.expr.member)
                if access is not None:
                    return access.type_
            chain = [(expr.expr.member, expr.expr.through_pointer)]
            current = expr.expr.base
            while isinstance(current, MemberExpr):
                chain.append((current.member, current.through_pointer))
                current = current.base
            if isinstance(current, Identifier):
                base_raw = self._type_map.get(current)
                if base_raw is None and self._func_sym is not None:
                    symbol = self._func_sym.locals.get(current.name)
                    if isinstance(symbol, VarSymbol):
                        base_raw = symbol.type_
                if base_raw is not None:
                    base_type = self._codegen_type(base_raw)
                    for member_name, through_pointer in reversed(chain):
                        if through_pointer:
                            base_type = base_type.pointee() or base_type
                        access = self._record_member_access_match(base_type, member_name)
                        if access is None:
                            break
                        base_type = access.type_
                    else:
                        return base_type
        raise self._error("x86_64 target cannot resolve sizeof operand type")

    def _offsetof_value(self, expr: BuiltinOffsetofExpr) -> int | None:
        root_type = self._resolve_type_spec(expr.type_spec)
        return self._offsetof_member_path(root_type, expr.member.split("."))

    def _offsetof_member_path(self, root_type: Type, parts: list[str]) -> int | None:
        offset = 0
        current = root_type
        for part in parts:
            access = self._record_member_access_match(current, part)
            if access is None:
                return None
            offset += access.offset
            current = access.type_
        return offset

    def _record_member_access(self, expr: MemberExpr) -> _MemberAccess:
        base_type = self._expr_type(expr.base)
        if expr.through_pointer:
            pointee = base_type.pointee()
            if pointee is None:
                raise self._error("Arrow base is not pointer")
            base_type = pointee
        access = self._record_member_access_match(base_type, expr.member)
        if access is None:
            raise self._error(f"x86_64 target cannot find member {expr.member}")
        return access

    def _record_member_access_match(
        self, base_type: Type, member_name: str
    ) -> _MemberAccess | None:
        members = self._sema.record_definitions.get(base_type.name)
        if members is None:
            return None
        if base_type.name.startswith("union "):
            for member in members:
                if member.name == member_name:
                    bit_offset = 0 if member.bit_width is not None else None
                    return _MemberAccess(
                        0,
                        member.type_,
                        bit_offset=bit_offset,
                        bit_width=member.bit_width,
                    )
                if self._is_anonymous_record_member(member.name, member.type_, member.bit_width):
                    found = self._record_member_access_match(member.type_, member_name)
                    if found is not None:
                        return found
            return None
        offset = 0
        active_bit_base = 0
        active_bit_used = 0
        active_bit_type: Type | None = None
        for index, member in enumerate(members):
            member_size = self._type_size(member.type_)
            member_align = self._member_align(member)
            if (
                member_size is None
                and self._is_flexible_array_member(member.type_)
                and index == len(members) - 1
            ):
                member_size = 0
            if member_size is None or member_align is None:
                return None
            if member.bit_width is not None:
                if member.bit_width == 0:
                    active_bit_type = None
                    active_bit_used = 0
                    offset = self._align_to(offset, member_align)
                    continue
                if (
                    active_bit_type != member.type_
                    or active_bit_used + member.bit_width > member_size * 8
                ):
                    offset = self._align_to(offset, member_align)
                    active_bit_base = offset
                    active_bit_used = 0
                    active_bit_type = member.type_
                    offset += member_size
                if member.name == member_name:
                    return _MemberAccess(
                        active_bit_base,
                        member.type_,
                        active_bit_used,
                        member.bit_width,
                    )
                active_bit_used += member.bit_width
                continue
            active_bit_type = None
            active_bit_used = 0
            offset = self._align_to(offset, member_align)
            if member.name == member_name:
                return _MemberAccess(offset, member.type_)
            if self._is_anonymous_record_member(member.name, member.type_, member.bit_width):
                found = self._record_member_access_match(member.type_, member_name)
                if found is not None:
                    return _MemberAccess(
                        offset + found.offset,
                        found.type_,
                        found.bit_offset,
                        found.bit_width,
                    )
            offset += member_size
        return None

    @staticmethod
    def _is_anonymous_record_member(name: str | None, type_: Type, bit_width: int | None) -> bool:
        return (
            name is None
            and bit_width is None
            and not type_.declarator_ops
            and type_.name.startswith(("struct ", "union "))
        )

    def _local_decl_type(self, stmt: DeclStmt) -> Type:
        assert self._func_sym is not None
        resolved = self._resolve_type_spec(stmt.type_spec)
        if resolved.is_array():
            return resolved
        symbol = self._func_sym.locals.get(stmt.name or "")
        if not isinstance(symbol, VarSymbol):
            return resolved
        semantic = self._codegen_type(symbol.type_)
        resolved = self._codegen_type(resolved)
        if not self._local_symbol_type_matches_decl_shape(semantic, resolved):
            return resolved
        return semantic

    def _local_symbol_type_matches_decl_shape(self, symbol_type: Type, decl_type: Type) -> bool:
        symbol_ops = tuple(kind for kind, _value in symbol_type.declarator_ops)
        decl_ops = tuple(kind for kind, _value in decl_type.declarator_ops)
        if symbol_ops != decl_ops:
            return False
        symbol_size = self._type_size(symbol_type)
        decl_size = self._type_size(decl_type)
        return not (symbol_size is not None and decl_size is not None and symbol_size != decl_size)

    def _complete_local_array_bound_type(self, stmt: DeclStmt, type_: Type) -> Type:
        if not type_.is_array() or type_.declarator_ops[0][1] != -1:
            return type_
        resolved = self._resolve_type_spec(stmt.type_spec)
        if resolved.is_array() and resolved.declarator_ops[0][1] != -1:
            return resolved
        if isinstance(stmt.init, StringLiteral):
            return self._complete_array_string_initializer_type(type_, stmt.init)
        if isinstance(stmt.init, InitList):
            return self._complete_array_initializer_type(type_, stmt.init)
        return type_

    @staticmethod
    def _complete_array_initializer_type(type_: Type, init: InitList) -> Type:
        if not type_.is_array():
            return type_
        length = type_.declarator_ops[0][1]
        if isinstance(length, int) and length >= 0:
            return type_
        largest = -1
        positional = 0
        for item in init.items:
            item_index = positional
            if item.designators:
                kind, value = item.designators[0]
                if kind == "index" and isinstance(value, IntLiteral):
                    item_index = int(value.value, 0)
            largest = max(largest, item_index)
            positional = item_index + 1
        return Type(
            type_.name,
            declarator_ops=(("arr", largest + 1),) + type_.declarator_ops[1:],
            qualifiers=type_.qualifiers,
        )

    def _complete_array_string_initializer_type(self, type_: Type, init: StringLiteral) -> Type:
        if not type_.is_array():
            return type_
        length = type_.declarator_ops[0][1]
        if isinstance(length, int) and length >= 0:
            return type_
        return Type(
            type_.name,
            declarator_ops=(("arr", len(self._string_literal_units(init)) + 1),)
            + type_.declarator_ops[1:],
            qualifiers=type_.qualifiers,
        )

    def _expr_type(self, expr: Expr) -> Type:
        return self._codegen_type(self._type_map.require(expr))

    def _compound_literal_type(self, expr: CompoundLiteralExpr) -> Type:
        type_ = self._type_map.get(expr) or self._resolve_type_spec(expr.type_spec)
        return self._complete_array_initializer_type(self._codegen_type(type_), expr.initializer)

    @staticmethod
    def _codegen_type(type_: Type) -> Type:
        if not type_.declarator_ops and type_.name == "enum":
            return INT
        return type_

    def _resolve_type_spec(self, type_spec: TypeSpec) -> Type:
        if type_spec.typeof_expr is not None:
            base = self._expr_type(type_spec.typeof_expr)
        elif type_spec.has_record_body or type_spec.record_tag is not None:
            base = Type(self._record_name_for_type_spec(type_spec))
        else:
            base = Type(type_spec.name)
        ops: list[tuple[str, int | tuple[tuple[Type, ...] | None, bool]]] = []
        for kind, value in type_spec.declarator_ops:
            if kind == "ptr":
                ops.append(("ptr", 0))
            elif kind == "arr":
                length = value.length if isinstance(value, ArrayDecl) else value
                if isinstance(length, Expr):
                    resolved_length = self._eval_int_constant(length)
                    ops.append(("arr", -1 if resolved_length is None else resolved_length))
                elif isinstance(length, int):
                    ops.append(("arr", length))
                else:
                    ops.append(("arr", -1))
            elif kind == "fn":
                ops.append(("fn", (None, False)))
        return Type(
            base.name,
            declarator_ops=tuple(ops) + base.declarator_ops,
            qualifiers=type_spec.qualifiers,
        )

    def _record_name_for_type_spec(self, type_spec: TypeSpec) -> str:
        local_name = self._record_type_spec_names.get(id(type_spec))
        if local_name is not None:
            return local_name
        prefix = type_spec.name
        if type_spec.record_tag is not None:
            candidate = f"{prefix} {type_spec.record_tag}"
            if candidate in self._sema.record_definitions:
                return candidate
            if type_spec.has_record_body:
                scoped_prefix = f"{candidate} <scope:"
                for name in self._sema.record_definitions:
                    if name.startswith(scoped_prefix) and self._record_members_match_type_spec(
                        name, type_spec
                    ):
                        return name
            else:
                return candidate
        if type_spec.has_record_body:
            for name in self._sema.record_definitions:
                if not name.startswith(prefix):
                    continue
                if self._record_members_match_type_spec(name, type_spec):
                    return name
        return prefix

    def _record_members_match_type_spec(self, record_name: str, type_spec: TypeSpec) -> bool:
        members = self._sema.record_definitions.get(record_name)
        if members is None or len(members) != len(type_spec.record_members):
            return False
        for resolved, declared in zip(members, type_spec.record_members, strict=True):
            if resolved.name != declared.name:
                return False
            declared_type = self._resolve_type_spec(declared.type_spec)
            if not self._record_member_types_match(resolved.type_, declared_type):
                return False
        return True

    @staticmethod
    def _record_member_types_match(resolved: Type, declared: Type) -> bool:
        resolved = _X86_64AsmGen._codegen_type(resolved)
        declared = _X86_64AsmGen._codegen_type(declared)
        if resolved.name != declared.name or resolved.qualifiers != declared.qualifiers:
            return False
        if len(resolved.declarator_ops) != len(declared.declarator_ops):
            return False
        for (resolved_kind, resolved_value), (declared_kind, declared_value) in zip(
            resolved.declarator_ops, declared.declarator_ops, strict=True
        ):
            if resolved_kind != declared_kind:
                return False
            if resolved_kind == "arr" and resolved_value != declared_value:
                return False
            if resolved_kind == "fn":
                continue
        return True

    def _aggregate_chunks(self, type_: Type) -> list[_AggregateChunk]:
        size = self._type_size(type_)
        if size is None:
            raise self._error(f"x86_64 target cannot size aggregate argument {type_}")
        if size <= 0:
            return []
        fp_chunks = (
            self._aggregate_fp_chunk_infos(type_, size)
            if size <= 16 and not type_.is_array()
            else {}
        )
        chunks: list[_AggregateChunk] = []
        for offset in range(0, size, 8):
            chunk_size = min(8, size - offset)
            info = fp_chunks.get(offset)
            if info is None:
                if chunk_size < 1 or chunk_size > 8:  # pragma: no cover - range/min invariant
                    raise self._error(
                        f"x86_64 target cannot pass {chunk_size}-byte aggregate chunk"
                    )
                info = _ScalarInfo(chunk_size, 1, False)
            chunks.append(_AggregateChunk(offset, info))
        return chunks

    def _aggregate_uses_registers(
        self,
        type_: Type,
        chunks: list[_AggregateChunk],
        int_arg_reg: int,
        fp_arg_reg: int,
    ) -> bool:
        size = self._type_size(type_)
        if size is None or size > 16:
            return False
        needed_int = sum(1 for chunk in chunks if not chunk.info.is_float)
        needed_fp = sum(1 for chunk in chunks if chunk.info.is_float)
        return int_arg_reg + needed_int <= len(
            self._INT_ARG_REGS
        ) and fp_arg_reg + needed_fp <= len(self._FP_ARG_REGS)

    def _aggregate_return_uses_memory(self, type_: Type) -> bool:
        size = self._type_size(type_)
        if size is None:
            raise self._error("x86_64 target cannot size aggregate return")
        return size > 16

    def _small_aggregate_return_chunks(self, type_: Type) -> list[_AggregateChunk]:
        size = self._type_size(type_)
        if size is None:
            raise self._error("x86_64 target cannot size aggregate return")
        if size > 16:
            raise self._error("x86_64 target does not support indirect aggregate returns yet")
        chunks = self._aggregate_chunks(type_)
        int_chunks = sum(1 for chunk in chunks if not chunk.info.is_float)
        fp_chunks = sum(1 for chunk in chunks if chunk.info.is_float)
        if int_chunks > 2 or fp_chunks > 2:
            raise self._error("x86_64 target cannot classify aggregate return")
        return chunks

    def _aggregate_return_registers(self, type_: Type) -> dict[int, str]:
        int_return_regs = ("rax", "rdx")
        fp_return_regs = ("xmm0", "xmm1")
        int_index = 0
        fp_index = 0
        result: dict[int, str] = {}
        for chunk in self._small_aggregate_return_chunks(type_):
            if chunk.info.is_float:
                if fp_index >= len(fp_return_regs):
                    raise self._error("x86_64 target cannot find aggregate FP return register")
                result[chunk.offset] = fp_return_regs[fp_index]
                fp_index += 1
                continue
            if int_index >= len(int_return_regs):
                raise self._error("x86_64 target cannot find aggregate integer return register")
            result[chunk.offset] = int_return_regs[int_index]
            int_index += 1
        return result

    def _aggregate_fp_chunk_infos(self, type_: Type, size: int) -> dict[int, _ScalarInfo]:
        fp_chunks: dict[int, _ScalarInfo] = {}
        int_chunks: set[int] = set()
        for offset, member_type, bit_width in self._record_member_offsets(type_):
            member_size = self._type_size(member_type)
            if member_size is None or member_size == 0:
                continue
            start_chunk = offset // 8 * 8
            end_chunk = (offset + member_size - 1) // 8 * 8
            touched = range(start_chunk, min(end_chunk, size - 1) + 1, 8)
            fp_info = self._standalone_fp_member_info(member_type)
            if (
                bit_width is None
                and fp_info is not None
                and start_chunk == end_chunk
                and offset % 8 == 0
                and start_chunk not in int_chunks
                and start_chunk not in fp_chunks
            ):
                fp_chunks[start_chunk] = fp_info
                continue
            for chunk_offset in touched:
                int_chunks.add(chunk_offset)
                fp_chunks.pop(chunk_offset, None)
        return fp_chunks

    def _record_member_offsets(self, type_: Type) -> list[tuple[int, Type, int | None]]:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            return []
        if type_.name.startswith("union "):
            return [(0, member.type_, member.bit_width) for member in members]
        result: list[tuple[int, Type, int | None]] = []
        offset = 0
        active_bit_size = 0
        active_bit_used = 0
        active_bit_type: Type | None = None
        for index, member in enumerate(members):
            member_size = self._type_size(member.type_)
            member_align = self._member_align(member)
            if (
                member_size is None
                and self._is_flexible_array_member(member.type_)
                and index == len(members) - 1
            ):
                member_size = 0
            if member_size is None or member_align is None:
                return []
            if member.bit_width is not None:
                if member.bit_width == 0:
                    active_bit_type = None
                    active_bit_used = 0
                    offset = self._align_to(offset, member_align)
                    continue
                if (
                    active_bit_type != member.type_
                    or active_bit_used + member.bit_width > member_size * 8
                ):
                    offset = self._align_to(offset, member_align)
                    active_bit_size = member_size
                    active_bit_used = 0
                    active_bit_type = member.type_
                    offset += active_bit_size
                result.append((offset - active_bit_size, member.type_, member.bit_width))
                active_bit_used += member.bit_width
                continue
            active_bit_type = None
            active_bit_used = 0
            offset = self._align_to(offset, member_align)
            result.append((offset, member.type_, None))
            offset += member_size
        return result

    def _standalone_fp_member_info(self, type_: Type) -> _ScalarInfo | None:
        type_ = unqualified_type(type_)
        if type_.declarator_ops or type_.name not in {"float", "double"}:
            return None
        return self._scalar_info(type_)

    def _is_va_list_type(self, type_: Type) -> bool:
        type_ = unqualified_type(type_)
        return not type_.declarator_ops and type_.name == "__builtin_va_list"

    def _type_size(self, type_: Type) -> int | None:
        if self._is_va_list_type(type_):
            return 24
        if type_.declarator_ops:
            kind, value = type_.declarator_ops[0]
            if kind == "ptr":
                return 8
            if kind == "fn":
                return None
            if not isinstance(value, int) or value < 0:
                return None
            element = type_.element_type()
            if element is None:
                return None
            element_size = self._type_size(element)
            return None if element_size is None else element_size * value
        base_sizes = {
            "_Bool": 1,
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
            "__int128": 16,
            "__uint128": 16,
            "unsigned __int128": 16,
            "__int128_t": 16,
            "__uint128_t": 16,
            "enum": 4,
            "float": 4,
            "double": 8,
            "long double": 16,
        }
        base = base_sizes.get(type_.name)
        if base is not None:
            return base
        return self._record_size(type_)

    def _type_align(self, type_: Type) -> int | None:
        if self._is_va_list_type(type_):
            return 8
        if type_.declarator_ops:
            kind, _ = type_.declarator_ops[0]
            if kind == "ptr":
                return 8
            if kind == "fn":
                return None
            element = type_.element_type()
            return None if element is None else self._type_align(element)
        base_align = {
            "_Bool": 1,
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
            "__int128": 16,
            "__uint128": 16,
            "unsigned __int128": 16,
            "__int128_t": 16,
            "__uint128_t": 16,
            "enum": 4,
            "float": 4,
            "double": 8,
            "long double": 16,
        }
        base = base_align.get(type_.name)
        if base is not None:
            return base
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            return None
        largest = 1
        for member in members:
            align = self._member_align(member)
            if align is None:
                return None
            largest = max(largest, align)
        return largest

    def _member_align(self, member: RecordMemberInfo) -> int | None:
        align = self._type_align(member.type_)
        if align is None:
            return None
        if member.alignment is not None and member.alignment > align:
            return member.alignment
        return align

    def _record_size(self, type_: Type) -> int | None:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            return None
        if type_.name.startswith("union "):
            largest = 0
            for member in members:
                size = self._type_size(member.type_)
                if size is None:
                    return None
                largest = max(largest, size)
            union_align = self._type_align(type_) or 1
            return self._align_to(largest, union_align)
        offset = 0
        active_bit_size = 0
        active_bit_used = 0
        active_bit_type: Type | None = None
        max_align = 1
        for index, member in enumerate(members):
            size = self._type_size(member.type_)
            member_align = self._member_align(member)
            if (
                size is None
                and self._is_flexible_array_member(member.type_)
                and index == len(members) - 1
            ):
                size = 0
            if size is None or member_align is None:
                return None
            max_align = max(max_align, member_align)
            if member.bit_width is not None:
                if member.bit_width == 0:
                    active_bit_type = None
                    active_bit_used = 0
                    offset = self._align_to(offset, member_align)
                    continue
                if active_bit_type != member.type_ or active_bit_used + member.bit_width > size * 8:
                    offset = self._align_to(offset, member_align)
                    active_bit_size = size
                    active_bit_used = 0
                    active_bit_type = member.type_
                    offset += active_bit_size
                active_bit_used += member.bit_width
                continue
            active_bit_type = None
            active_bit_used = 0
            offset = self._align_to(offset, member_align)
            offset += size
        return self._align_to(offset, max_align)

    def _scalar_info(self, type_: Type) -> _ScalarInfo:
        type_ = unqualified_type(type_)
        if type_.declarator_ops:
            if type_.declarator_ops[0][0] == "ptr":
                return _ScalarInfo(8, 8, False)
            if type_.declarator_ops[0][0] == "fn":
                return _ScalarInfo(8, 8, False)
            raise self._error(f"x86_64 target cannot scalarize array type {type_}")
        if type_.name in {"float", "double", "long double"}:
            size = self._type_size(type_)
            align = self._type_align(type_)
            if size is None or align is None:
                raise self._error(f"x86_64 target cannot size floating type {type_}")
            return _ScalarInfo(size, align, True, is_float=True)
        if self._is_va_list_type(type_):
            return _ScalarInfo(24, 8, False)
        size = self._type_size(type_)
        align = self._type_align(type_)
        if size is None or align is None:
            union_info = self._scalar_union_info(type_)
            if union_info is not None:
                return union_info
            raise self._error(f"x86_64 target cannot size scalar type {type_}")
        signed = not type_.name.startswith("unsigned") and type_.name not in {"_Bool"}
        return _ScalarInfo(size, align, signed)

    def _slot_info(self, type_: Type) -> _ScalarInfo:
        if self._is_aggregate_type(type_) or type_.is_array():
            size = self._type_size(type_)
            align = self._type_align(type_)
            if size is None or align is None:
                raise self._error(f"x86_64 target cannot size aggregate type {type_}")
            return _ScalarInfo(size, align, False)
        return self._scalar_info(type_)

    def _scalar_union_info(self, type_: Type) -> _ScalarInfo | None:
        if not type_.name.startswith("union "):
            return None
        size = self._record_size(type_)
        align = self._type_align(type_)
        if size in {1, 2, 4, 8} and align is not None:
            return _ScalarInfo(size, align, False)
        return None

    def _coerce_value(self, value: _Value, target_type: Type, target_info: _ScalarInfo) -> None:
        if self._is_void_type(target_type):
            return
        if target_type.name == "_Bool":
            if value.type_.name != "_Bool":
                self._coerce_scalar_to_bool(value)
            return
        if value.info.is_float or target_info.is_float:
            if value.info.is_float and target_info.is_float and value.info.size == target_info.size:
                return
            if value.info.is_float and target_info.is_float:
                opcode = "cvtss2sd" if target_info.size == 8 else "cvtsd2ss"
                self._emit(f"{opcode} {self._float_target(value.reg)}, {value.reg}")
                return
            if target_info.is_float:
                if value.info.size == 8 and not value.info.signed:
                    self._emit_uint64_to_float(value, target_info)
                    return
                self._coerce_register(value.info, _ScalarInfo(8, 8, value.info.signed), value.reg)
                opcode = "cvtsi2ss" if target_info.size == 4 else "cvtsi2sd"
                self._emit(f"{opcode} xmm0, {self._sized_reg(value.reg, _ScalarInfo(8, 8, True))}")
                return
            opcode = "cvttss2si" if value.info.size == 4 else "cvttsd2si"
            self._emit(f"{opcode} rax, {value.reg}")
            self._coerce_register(_ScalarInfo(8, 8, True), target_info, "rax")
            return
        self._coerce_register(value.info, target_info, value.reg)

    def _coerce_scalar_to_bool(self, value: _Value) -> None:
        if value.info.is_float:
            self._emit_float_zero_compare(value.info, value.reg)
            self._emit("setne al")
            self._emit("setp r10b")
            self._emit("or al, r10b")
            self._emit("movzx eax, al")
            return
        reg = value.reg
        if value.info.size in {1, 2}:
            source = self._sized_reg(reg, value.info)
            dest = self._sized_reg(reg, _ScalarInfo(4, 4, False))
            self._emit(f"movzx {dest}, {source}")
            compare = dest
        else:
            compare = self._sized_reg(reg, value.info)
        self._emit(f"cmp {compare}, 0")
        self._emit(f"setne {self._sized_reg(reg, _ScalarInfo(1, 1, False))}")
        self._emit(
            f"movzx {self._sized_reg(reg, _ScalarInfo(4, 4, False))}, "
            f"{self._sized_reg(reg, _ScalarInfo(1, 1, False))}"
        )

    def _emit_uint64_to_float(self, value: _Value, target_info: _ScalarInfo) -> None:
        opcode = "cvtsi2ss" if target_info.size == 4 else "cvtsi2sd"
        add_opcode = "addss" if target_info.size == 4 else "addsd"
        slow_label = self._new_label("uint64_float_slow")
        done_label = self._new_label("uint64_float_done")
        source = self._sized_reg(value.reg, _ScalarInfo(8, 8, False))
        self._emit(f"test {source}, {source}")
        self._emit(f"js {slow_label}")
        self._emit(f"{opcode} xmm0, {source}")
        self._emit(f"jmp {done_label}")
        self._lines.append(f"{slow_label}:")
        self._emit(f"mov r10, {source}")
        self._emit("mov r11, r10")
        self._emit("and r10, 1")
        self._emit("shr r11, 1")
        self._emit("or r11, r10")
        self._emit(f"{opcode} xmm0, r11")
        self._emit(f"{add_opcode} xmm0, xmm0")
        self._lines.append(f"{done_label}:")

    def _coerced_reg(self, value: _Value, target_info: _ScalarInfo) -> str:
        if target_info.is_float:
            if value.info.is_float and value.info.size == target_info.size:
                return value.reg
            return self._float_target(value.reg)
        if value.info.is_float:
            return "rax"
        return value.reg

    def _coerce_register(
        self, source_info: _ScalarInfo, target_info: _ScalarInfo, reg: str
    ) -> None:
        if source_info.size == target_info.size:
            return
        if target_info.size == 1:
            self._emit(f"and {self._sized_reg(reg, _ScalarInfo(4, 4, False))}, 255")
            return
        if target_info.size == 2:
            dest = self._sized_reg(reg, _ScalarInfo(4, 4, False))
            source = self._sized_reg(reg, _ScalarInfo(2, 2, False))
            self._emit(f"movzx {dest}, {source}")
            return
        if source_info.size < target_info.size:
            source = self._sized_reg(reg, source_info)
            dest = self._sized_reg(reg, target_info)
            if source_info.size == 4 and target_info.size == 8:
                if source_info.signed:
                    self._emit(f"movsxd {dest}, {source}")
                return
            op = "movsx" if source_info.signed else "movzx"
            self._emit(f"{op} {dest}, {source}")

    def _store_value_to_slot(self, slot: _Slot, value: _Value) -> None:
        self._coerce_value(value, slot.type_, slot.info)
        source = self._coerced_reg(value, slot.info)
        if slot.info.is_float:
            self._emit_float_store(slot.info, source, self._slot_addr(slot))
        else:
            self._emit_store_to_address(slot.info, source, self._slot_addr(slot))

    def _emit_copy_memory(self, dst_reg: str, src_reg: str, size: int) -> None:
        offset = 0
        while size - offset >= 8:
            self._emit(f"mov r10, QWORD PTR {self._address_operand(src_reg, offset)}")
            self._emit(f"mov QWORD PTR {self._address_operand(dst_reg, offset)}, r10")
            offset += 8
        if size - offset >= 4:
            self._emit(f"mov r10d, DWORD PTR {self._address_operand(src_reg, offset)}")
            self._emit(f"mov DWORD PTR {self._address_operand(dst_reg, offset)}, r10d")
            offset += 4
        if size - offset >= 2:
            self._emit(f"mov r10w, WORD PTR {self._address_operand(src_reg, offset)}")
            self._emit(f"mov WORD PTR {self._address_operand(dst_reg, offset)}, r10w")
            offset += 2
        if size - offset:
            self._emit(f"mov r10b, BYTE PTR {self._address_operand(src_reg, offset)}")
            self._emit(f"mov BYTE PTR {self._address_operand(dst_reg, offset)}, r10b")

    def _emit_zero_memory(self, dst_reg: str, size: int) -> None:
        offset = 0
        while size - offset >= 8:
            self._emit(f"mov QWORD PTR {self._address_operand(dst_reg, offset)}, 0")
            offset += 8
        if size - offset >= 4:
            self._emit(f"mov DWORD PTR {self._address_operand(dst_reg, offset)}, 0")
            offset += 4
        if size - offset >= 2:
            self._emit(f"mov WORD PTR {self._address_operand(dst_reg, offset)}, 0")
            offset += 2
        if size - offset:
            self._emit(f"mov BYTE PTR {self._address_operand(dst_reg, offset)}, 0")

    def _emit_address_offset(self, target: str, base: str, offset: int) -> None:
        if offset:
            self._emit(f"lea {target}, {self._address_operand(base, offset)}")
        elif target != base:
            self._emit(f"mov {target}, {base}")

    def _emit_load_from_address(self, info: _ScalarInfo, target: str, address: str) -> None:
        if info.is_float:
            self._emit_float_load(info, target, address)
            return
        if info.size not in {1, 2, 4, 8}:
            self._emit_load_bytes_from_address(info.size, target, address)
            return
        dest = self._sized_reg(
            target, _ScalarInfo(max(info.size, 4), max(info.size, 4), info.signed)
        )
        if info.size == 8:
            self._emit(f"mov {dest}, QWORD PTR {address}")
            return
        if info.size == 4:
            self._emit(f"mov {dest}, DWORD PTR {address}")
            return
        source = self._mem(info, address)
        op = "movsx" if info.signed else "movzx"
        self._emit(f"{op} {dest}, {source}")

    def _emit_store_to_address(self, info: _ScalarInfo, source: str, address: str) -> None:
        if info.is_float:
            self._emit_float_store(info, source, address)
            return
        if info.size not in {1, 2, 4, 8}:
            self._emit_store_bytes_to_address(info.size, source, address)
            return
        self._emit(f"mov {self._mem(info, address)}, {self._sized_reg(source, info)}")

    def _emit_load_bytes_from_address(self, size: int, target: str, address: str) -> None:
        self._emit(f"lea r10, {address}")
        self._emit(f"mov {target}, 0")
        for offset in range(size):
            self._emit(f"movzx r11d, BYTE PTR {self._address_operand('r10', offset)}")
            if offset:
                self._emit(f"shl r11, {offset * 8}")
            self._emit(f"or {target}, r11")

    def _emit_store_bytes_to_address(self, size: int, source: str, address: str) -> None:
        self._emit(f"lea r10, {address}")
        self._emit(f"mov r11, {source}")
        for offset in range(size):
            self._emit(f"mov BYTE PTR {self._address_operand('r10', offset)}, r11b")
            if offset != size - 1:
                self._emit("shr r11, 8")

    def _emit_bitfield_load(
        self,
        access: _MemberAccess,
        result_info: _ScalarInfo,
        target: str,
        address: str,
    ) -> None:
        assert access.bit_offset is not None and access.bit_width is not None
        storage_info = self._scalar_info(access.type_)
        op_info = self._bitfield_op_info(storage_info)
        self._emit_load_from_address(storage_info, target, address)
        reg = self._sized_reg(target, op_info)
        if access.bit_offset:
            self._emit(f"shr {reg}, {access.bit_offset}")
        if result_info.signed:
            shift = op_info.bits - access.bit_width
            if shift:
                self._emit(f"sal {reg}, {shift}")
                self._emit(f"sar {reg}, {shift}")
            return
        self._emit_and_immediate(target, op_info, (1 << access.bit_width) - 1)

    def _emit_bitfield_store(
        self,
        access: _MemberAccess,
        result_info: _ScalarInfo,
        source: str,
        address: str,
    ) -> None:
        assert access.bit_offset is not None and access.bit_width is not None
        storage_info = self._scalar_info(access.type_)
        op_info = self._bitfield_op_info(storage_info)
        value_mask = (1 << access.bit_width) - 1
        field_mask = value_mask << access.bit_offset
        full_mask = (1 << op_info.bits) - 1

        self._emit(
            f"mov {self._sized_reg('r10', op_info)}, "
            f"{self._sized_reg(source, self._bitfield_op_info(result_info))}"
        )
        self._emit_and_immediate("r10", op_info, value_mask)
        if access.bit_offset:
            self._emit(f"sal {self._sized_reg('r10', op_info)}, {access.bit_offset}")
        self._emit_load_from_address(storage_info, "r11", address)
        self._emit_and_immediate("r11", op_info, full_mask ^ field_mask)
        self._emit(f"or {self._sized_reg('r11', op_info)}, {self._sized_reg('r10', op_info)}")
        self._emit_store_to_address(storage_info, "r11", address)

    @staticmethod
    def _bitfield_op_info(info: _ScalarInfo) -> _ScalarInfo:
        size = 8 if info.size == 8 else 4
        return _ScalarInfo(size, size, info.signed)

    def _emit_and_immediate(self, reg: str, info: _ScalarInfo, value: int) -> None:
        sized_reg = self._sized_reg(reg, info)
        if value == (1 << info.bits) - 1:
            return
        if value <= 0x7FFFFFFF:
            self._emit(f"and {sized_reg}, {value}")
            return
        scratch = "rdx" if reg != "rdx" else "r11"
        self._emit("push rdx" if scratch == "rdx" else "push r11")
        self._emit(f"mov {self._sized_reg(scratch, info)}, {value}")
        self._emit(f"and {sized_reg}, {self._sized_reg(scratch, info)}")
        self._emit("pop rdx" if scratch == "rdx" else "pop r11")

    def _emit_load_immediate(self, target: str, value: int, info: _ScalarInfo) -> None:
        if info.is_float:
            raise self._error("floating immediates should use literal loads")
        self._emit(f"mov {self._sized_reg(target, info)}, {value}")

    def _emit_integer_to_64(self, value: _Value) -> None:
        if value.info.size == 8:
            return
        if value.info.size == 4:
            if value.info.signed:
                self._emit(f"movsxd rax, {self._sized_reg(value.reg, value.info)}")
            return
        if value.info.size not in {1, 2}:
            if value.reg != "rax":
                self._emit(f"mov rax, {value.reg}")
            return
        if value.info.signed:
            self._emit(f"movsx rax, {self._sized_reg(value.reg, value.info)}")
        else:
            self._emit(f"movzx rax, {self._sized_reg(value.reg, value.info)}")

    def _eval_case_value(self, expr: Expr) -> int:
        value = self._eval_int_constant(expr)
        if value is None:
            raise self._error("x86_64 target cannot evaluate switch case value")
        return value

    def _eval_int_constant(self, expr: Expr) -> int | None:
        if isinstance(expr, IntLiteral):
            return self._parse_int_value(expr.value)
        if isinstance(expr, CharLiteral):
            return self._char_value(expr.value)
        if isinstance(expr, Identifier):
            symbol = self._lookup_enum_const(expr.name)
            if symbol is not None:
                return symbol.value
        if isinstance(expr, UnaryExpr):
            value = self._eval_int_constant(expr.operand)
            if value is None:
                return None
            if expr.op == "-":
                return -value
            if expr.op == "+":
                return value
            if expr.op == "~":
                return ~value
            if expr.op == "!":
                return int(not value)
        if isinstance(expr, BinaryExpr):
            left = self._eval_int_constant(expr.left)
            right = self._eval_int_constant(expr.right)
            if left is None or right is None:
                return None
            if expr.op == "+":
                return left + right
            if expr.op == "-":
                return left - right
            if expr.op == "*":
                return left * right
            if expr.op == "/" and right:
                return int(left / right)
            if expr.op == "%" and right:
                return left % right
            if expr.op == "<<":
                return left << right
            if expr.op == ">>":
                return left >> right
            if expr.op == "&":
                return left & right
            if expr.op == "|":
                return left | right
            if expr.op == "^":
                return left ^ right
            if expr.op == "&&":
                return int(bool(left) and bool(right))
            if expr.op == "||":
                return int(bool(left) or bool(right))
            if expr.op == "==":
                return int(left == right)
            if expr.op == "!=":
                return int(left != right)
            if expr.op == "<":
                return int(left < right)
            if expr.op == "<=":
                return int(left <= right)
            if expr.op == ">":
                return int(left > right)
            if expr.op == ">=":
                return int(left >= right)
        if isinstance(expr, CastExpr):
            target_type = self._resolve_type_spec(expr.type_spec)
            float_value = self._eval_float_constant(expr.expr)
            if float_value is not None and is_integer_type(target_type):
                return int(float_value)
            return self._eval_int_constant(expr.expr)
        if isinstance(expr, CommaExpr):
            return self._eval_int_constant(expr.right)
        if isinstance(expr, SizeofExpr):
            type_ = self._sizeof_operand_type(expr)
            return self._type_size(type_)
        if isinstance(expr, AlignofExpr):
            type_ = self._sizeof_operand_type(expr)
            return self._type_align(type_)
        if isinstance(expr, BuiltinOffsetofExpr):
            return self._offsetof_value(expr)
        if isinstance(expr, ConditionalExpr):
            condition = self._eval_int_constant(expr.condition)
            if condition is None:
                return None
            return self._eval_int_constant(expr.then_expr if condition else expr.else_expr)
        return None

    def _lookup_enum_const(self, name: str) -> EnumConstSymbol | None:
        if self._func_sym is not None:
            symbol = self._func_sym.locals.get(name)
            if isinstance(symbol, EnumConstSymbol):
                return symbol
        if self._sema.file_scope is not None:
            symbol = self._sema.file_scope.lookup(name)
            if isinstance(symbol, EnumConstSymbol):
                return symbol
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

    def _eval_call_float_constant(self, expr: CallExpr) -> float | None:
        if isinstance(expr.callee, Identifier):
            if expr.callee.name in {
                "__builtin_inff",
                "__builtin_inf",
                "__builtin_infl",
                "__builtin_huge_valf",
                "__builtin_huge_val",
                "__builtin_huge_vall",
            }:
                return float("inf")
            if expr.callee.name in {
                "__builtin_nanf",
                "__builtin_nan",
                "__builtin_nanl",
            }:
                return float("nan")
            if (
                expr.callee.name
                in {
                    "__builtin_fabsf",
                    "__builtin_fabs",
                    "__builtin_fabsl",
                }
                and len(expr.args) == 1
            ):
                value = self._eval_float_constant(expr.args[0])
                return None if value is None else abs(value)
        return None

    @staticmethod
    def _parse_int_value(lexeme: str) -> int:
        stripped = lexeme
        while stripped and stripped[-1] in "uUlL":
            stripped = stripped[:-1]
        if stripped.startswith(("0x", "0X")):
            return int(stripped, 16)
        if stripped.startswith(("0b", "0B")):
            return int(stripped, 2)
        if len(stripped) > 1 and stripped.startswith("0"):
            return int(stripped, 8)
        return int(stripped or "0", 10)

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
        return _X86_64AsmGen._float_to_bits(float(lexeme.rstrip("fFlL")), size)

    @staticmethod
    def _float_to_bits(value: float, size: int) -> int:
        if size == 4:
            return struct.unpack("<I", struct.pack("<f", value))[0]
        return struct.unpack("<Q", struct.pack("<d", value))[0]

    def _string_literal_units(self, expr: StringLiteral) -> list[int]:
        body = string_literal_body(expr.value)
        if body is None:
            raise self._error(f"x86_64 target does not support string literal {expr.value}")
        return decode_escaped_units(body)

    def _string_literal_bytes(self, expr: StringLiteral) -> bytes:
        units = self._string_literal_units(expr)
        element_size = self._string_literal_unit_width(expr)
        if element_size == 1:
            if any(unit < 0 or unit > 0xFF for unit in units):
                raise self._error("x86_64 target found non-byte string literal unit")
            return bytes(units) + b"\x00"
        limit = (1 << (element_size * 8)) - 1
        if any(unit < 0 or unit > limit for unit in units):
            raise self._error("x86_64 target found out-of-range string literal unit")
        data = bytearray()
        for unit in units:
            data.extend(unit.to_bytes(element_size, "little"))
        data.extend(b"\x00" * element_size)
        return bytes(data)

    def _string_literal_label(self, expr: StringLiteral) -> str:
        data = self._string_literal_bytes(expr)
        label = self._string_literals.get(data)
        if label is None:
            label = f".LC{len(self._string_literals)}"
            self._string_literals[data] = label
        self._string_literal_alignments[data] = max(
            self._string_literal_alignments.get(data, 0),
            self._string_literal_alignment(expr),
        )
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

    def _string_literal_alignment(self, expr: StringLiteral) -> int:
        width = self._string_literal_unit_width(expr)
        if width <= 1:
            return 0
        return width.bit_length() - 1

    @staticmethod
    def _subscript_element_type(type_: Type) -> Type | None:
        if not type_.declarator_ops:
            return None
        if type_.declarator_ops[0][0] == "arr":
            return type_.element_type()
        if type_.declarator_ops[0][0] == "ptr":
            return type_.pointee()
        return None

    @staticmethod
    def _is_record_type(type_: Type) -> bool:
        return not type_.declarator_ops and type_.name.startswith(("struct ", "union "))

    @classmethod
    def _is_aggregate_type(cls, type_: Type) -> bool:
        return cls._is_record_type(type_) or type_.is_array()

    @staticmethod
    def _is_function_type(type_: Type) -> bool:
        return bool(type_.declarator_ops and type_.declarator_ops[0][0] == "fn")

    @staticmethod
    def _is_void_type(type_: Type) -> bool:
        return unqualified_type(type_) == VOID

    @staticmethod
    def _is_pointer_type(type_: Type) -> bool:
        return bool(type_.declarator_ops and type_.declarator_ops[0][0] == "ptr")

    @staticmethod
    def _is_pointer_like_type(type_: Type) -> bool:
        return bool(type_.declarator_ops and type_.declarator_ops[0][0] in {"arr", "ptr"})

    @staticmethod
    def _is_flexible_array_member(type_: Type) -> bool:
        return bool(
            type_.declarator_ops
            and type_.declarator_ops[0][0] == "arr"
            and type_.declarator_ops[0][1] == -1
        )

    @staticmethod
    def _is_pointer_binary(op: str, left_type: Type, right_type: Type) -> bool:
        if op in {"==", "!=", "<", "<=", ">", ">="}:
            return _X86_64AsmGen._is_pointer_like_type(
                left_type
            ) or _X86_64AsmGen._is_pointer_like_type(right_type)
        if op == "+":
            return (
                _X86_64AsmGen._is_pointer_like_type(left_type) and is_integer_type(right_type)
            ) or (is_integer_type(left_type) and _X86_64AsmGen._is_pointer_like_type(right_type))
        if op == "-":
            return _X86_64AsmGen._is_pointer_like_type(left_type)
        return False

    def _pointer_step_size(self, pointer_type: Type) -> int:
        pointee = pointer_type.pointee()
        if pointee is None:
            pointee = pointer_type.element_type()
        if pointee is None:
            return 1
        size = self._type_size(pointee)
        if size is None:
            return 1
        return size

    @staticmethod
    def _function_designator_value_type(type_: Type) -> Type:
        if type_.declarator_ops and type_.declarator_ops[0][0] == "fn":
            return type_.pointer_to()
        return type_

    def _is_null_pointer_initializer(self, expr: Expr) -> bool:
        return self._eval_int_constant(expr) == 0

    def _is_zero_initializer(self, expr: Expr) -> bool:
        return self._eval_int_constant(expr) == 0

    @staticmethod
    def _comparison_condition(op: str, signed: bool) -> str:
        if op == "==":
            return "e"
        if op == "!=":
            return "ne"
        if op == "<":
            return "l" if signed else "b"
        if op == "<=":
            return "le" if signed else "be"
        if op == ">":
            return "g" if signed else "a"
        if op == ">=":
            return "ge" if signed else "ae"
        raise AssertionError(op)

    @staticmethod
    def _sized_reg(reg: str, info: _ScalarInfo) -> str:
        table = {
            "rax": ("al", "ax", "eax", "rax"),
            "rbx": ("bl", "bx", "ebx", "rbx"),
            "rcx": ("cl", "cx", "ecx", "rcx"),
            "rdx": ("dl", "dx", "edx", "rdx"),
            "rsi": ("sil", "si", "esi", "rsi"),
            "rdi": ("dil", "di", "edi", "rdi"),
            "r8": ("r8b", "r8w", "r8d", "r8"),
            "r9": ("r9b", "r9w", "r9d", "r9"),
            "r10": ("r10b", "r10w", "r10d", "r10"),
            "r11": ("r11b", "r11w", "r11d", "r11"),
        }
        regs = table[reg]
        if info.size == 1:
            return regs[0]
        if info.size == 2:
            return regs[1]
        if info.size == 4:
            return regs[2]
        return regs[3]

    @staticmethod
    def _float_target(target: str) -> str:
        return target if target.startswith("xmm") else "xmm0"

    @staticmethod
    def _gpr_target(target: str) -> str:
        return "rax" if target.startswith("xmm") else target

    def _update_address_register(self, target: str) -> str:
        return "r8" if self._gpr_target(target) == "rcx" else "rcx"

    def _postfix_old_value_register(self, target: str, address_reg: str) -> str:
        result_reg = self._gpr_target(target)
        for reg in ("rdx", "r9"):
            if reg != result_reg and reg != address_reg:
                return reg
        return "r9"

    @staticmethod
    def _mem(info: _ScalarInfo, address: str) -> str:
        prefix = {1: "BYTE", 2: "WORD", 4: "DWORD", 8: "QWORD", 16: "XMMWORD"}[info.size]
        return f"{prefix} PTR {address}"

    @staticmethod
    def _address_operand(reg: str, offset: int = 0) -> str:
        if offset == 0:
            return f"[{reg}]"
        if offset > 0:
            return f"[{reg} + {offset}]"
        return f"[{reg} - {-offset}]"

    def _slot_addr(self, slot: _Slot, extra: int = 0) -> str:
        offset = slot.offset - extra
        if extra:
            return f"[rbp - {offset}]"
        return f"[rbp - {slot.offset}]"

    @staticmethod
    def _align_to(value: int, alignment: int) -> int:
        return (value + alignment - 1) // alignment * alignment

    @staticmethod
    def _symbol_name(name: str) -> str:
        return name

    def _emit_external_data_address(self, name: str, target: str) -> None:
        self._emit(f"mov {target}, QWORD PTR [rip + {self._symbol_name(name)}@GOTPCREL]")

    def _emit_function_address(self, name: str, target: str) -> None:
        if self._is_local_function(name):
            self._emit(f"lea {target}, [rip + {self._symbol_name(name)}]")
        else:
            self._emit(f"mov {target}, QWORD PTR [rip + {self._symbol_name(name)}@GOTPCREL]")

    def _emit_cmp_rax_immediate(self, value: int) -> None:
        if -(1 << 31) <= value <= (1 << 31) - 1:
            self._emit(f"cmp rax, {value}")
            return
        self._emit(f"mov r10, {value & ((1 << 64) - 1)}")
        self._emit("cmp rax, r10")

    def _emit_global_address(self, global_: _Global, target: str) -> None:
        if global_.is_static:
            self._emit(f"lea {target}, [rip + {global_.label}]")
        else:
            self._emit(f"mov {target}, QWORD PTR [rip + {global_.label}@GOTPCREL]")

    def _is_local_function(self, name: str) -> bool:
        for function in self._unit.functions:
            if function.name == name and function.body is not None:
                return function.storage_class == "static" or function.is_inline
        return False

    @staticmethod
    def _global_symbol_name(name: str, is_static: bool) -> str:
        return f".L.{name}" if is_static else name

    def _user_label(self, name: str) -> str:
        assert self._func is not None
        return f".L.{self._func.name}.{name}"

    def _new_label(self, prefix: str) -> str:
        assert self._func is not None
        self._label_counter += 1
        return f".L.{self._func.name}.{prefix}.{self._label_counter}"

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

    def _static_local_slot_marker(self, name: str, slot: _Slot) -> _StaticLocal | None:
        if slot.offset != 0:
            return None
        static_local = self._static_local(name)
        if static_local is None or static_local.type_ != slot.type_:
            return None
        return static_local

    def _static_local_initializer(self, name: str) -> _StaticLocal | None:
        if self._data_static_function is None:
            return None
        return self._static_locals.get((self._data_static_function, name))

    def _push_stack(self, operand: str) -> None:
        self._emit(f"push {operand}")
        self._stack_depth += 1

    def _pop_stack(self, operand: str) -> None:
        self._emit(f"pop {operand}")
        self._stack_depth -= 1

    def _emit(self, text: str) -> None:
        self._lines.append(f"    {text}")

    def _error(self, message: str) -> CodegenError:
        return x86_64_backend_error(self._result.filename, message)


def generate_x86_64_asm(result: FrontendResult) -> str:
    return _X86_64AsmGen(result).generate()
