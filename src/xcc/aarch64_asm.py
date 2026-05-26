"""Direct Darwin AArch64 assembly backend.

This backend is intentionally small: it emits native assembly for scalar
integer leaf functions and rejects unsupported C constructs with deterministic
codegen diagnostics instead of falling back to LLVM.
"""

from collections.abc import Callable
from dataclasses import dataclass

from xcc.ast import (
    AssignExpr,
    BinaryExpr,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundStmt,
    DeclGroupStmt,
    DeclStmt,
    Expr,
    ExprStmt,
    FunctionDef,
    Identifier,
    InitList,
    IntLiteral,
    ReturnStmt,
    Stmt,
    TypedefDecl,
    UnaryExpr,
)
from xcc.diag import CodegenError, Diagnostic
from xcc.frontend import FrontendResult
from xcc.sema.constants import char_literal_body, decode_escaped_units
from xcc.sema.symbols import EnumConstSymbol, FunctionSymbol, VarSymbol
from xcc.sema.type_helpers import is_integer_type, unqualified_type, usual_arithmetic_conversion
from xcc.types import INT, VOID, Type

_AARCH64_UNSUPPORTED = "XCC-A64-0001"


def aarch64_backend_error(filename: str, message: str) -> CodegenError:
    return CodegenError(Diagnostic("codegen", filename, message, code=_AARCH64_UNSUPPORTED))


@dataclass(frozen=True)
class _ScalarInfo:
    size: int
    align: int
    signed: bool

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


class _AArch64AsmGen:
    def __init__(self, result: FrontendResult):
        self._result = result
        self._unit = result.unit
        self._sema = result.sema
        self._type_map = result.sema.type_map
        self._lines: list[str] = []
        self._func: FunctionDef | None = None
        self._func_sym: FunctionSymbol | None = None
        self._slots: dict[str, _Slot] = {}
        self._frame_size = 0
        self._return_label = ""

    def generate(self) -> str:
        self._lines = [".section __TEXT,__text,regular,pure_instructions"]
        for function in self._unit.functions:
            if function.body is None:
                continue
            self._emit_function(function)
        self._lines.append(".subsections_via_symbols")
        return "\n".join(self._lines) + "\n"

    def _emit_function(self, function: FunctionDef) -> None:
        body = function.body
        assert body is not None
        self._func = function
        self._func_sym = self._sema.functions.get(function.name)
        if self._func_sym is None:
            raise self._error(f"Missing semantic function symbol: {function.name}")
        if function.is_variadic:
            raise self._error("AArch64 target does not support variadic functions yet")
        if len(function.params) > 8:
            raise self._error("AArch64 target does not support more than 8 parameters yet")
        if self._func_sym.return_type != VOID:
            self._scalar_info(self._func_sym.return_type)
        self._prepare_frame(function, body)

        label = self._symbol_name(function.name)
        self._return_label = f"L_{function.name}_return"
        self._lines.append(".p2align 2")
        if function.storage_class != "static":
            self._lines.append(f".globl {label}")
        self._lines.append(f"{label}:")
        if self._frame_size:
            self._emit(f"sub sp, sp, #{self._frame_size}")
        self._spill_parameters(function)
        self._emit_stmt(body)
        self._lines.append(f"{self._return_label}:")
        if self._frame_size:
            self._emit(f"add sp, sp, #{self._frame_size}")
        self._emit("ret")

    def _prepare_frame(self, function: FunctionDef, body: CompoundStmt) -> None:
        self._slots = {}
        offset = 0

        def add_slot(name: str, type_: Type, alignment: int | None = None) -> None:
            nonlocal offset
            info = self._scalar_info(type_)
            align = alignment or info.align
            offset = self._align_to(offset, align)
            self._slots[name] = _Slot(offset, type_, info)
            offset += info.size

        assert self._func_sym is not None
        for param in function.params:
            if param.name is None:
                continue
            symbol = self._func_sym.locals.get(param.name)
            if not isinstance(symbol, VarSymbol):
                raise self._error(f"Missing parameter symbol: {param.name}")
            add_slot(param.name, symbol.type_, symbol.alignment)
        self._collect_local_slots(body, add_slot)
        self._frame_size = self._align_to(offset, 16)

    def _collect_local_slots(
        self,
        stmt: Stmt,
        add_slot: Callable[[str, Type, int | None], None],
    ) -> None:
        if isinstance(stmt, CompoundStmt):
            for child in stmt.statements:
                self._collect_local_slots(child, add_slot)
            return
        if isinstance(stmt, DeclStmt):
            if stmt.name is None or stmt.storage_class == "typedef":
                return
            if stmt.storage_class in {"static", "extern"}:
                raise self._error("AArch64 target does not support static or extern locals yet")
            assert self._func_sym is not None
            symbol = self._func_sym.locals.get(stmt.name)
            if not isinstance(symbol, VarSymbol):
                raise self._error(f"Missing local symbol: {stmt.name}")
            add_slot(stmt.name, symbol.type_, stmt.alignment or symbol.alignment)
            return
        if isinstance(stmt, DeclGroupStmt):
            for declaration in stmt.declarations:
                self._collect_local_slots(declaration, add_slot)

    def _spill_parameters(self, function: FunctionDef) -> None:
        for index, param in enumerate(function.params):
            if param.name is None:
                continue
            slot = self._require_slot(param.name)
            self._emit_store(slot, index)

    def _emit_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, CompoundStmt):
            for child in stmt.statements:
                self._emit_stmt(child)
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
        if isinstance(stmt, TypedefDecl):
            return
        raise self._error(f"AArch64 target does not support {type(stmt).__name__} yet")

    def _emit_return(self, stmt: ReturnStmt) -> None:
        assert self._func_sym is not None
        if self._func_sym.return_type == VOID:
            if stmt.value is not None:
                raise self._error("Void function cannot return a value")
            self._emit(f"b {self._return_label}")
            return
        if stmt.value is None:
            raise self._error("Non-void function must return a value")
        value = self._emit_expr(stmt.value, 0)
        return_info = self._scalar_info(self._func_sym.return_type)
        self._coerce_value(value, self._func_sym.return_type, return_info, 0)
        self._emit(f"b {self._return_label}")

    def _emit_decl(self, stmt: DeclStmt) -> None:
        if stmt.name is None or stmt.storage_class == "typedef":
            return
        if isinstance(stmt.init, InitList):
            raise self._error("AArch64 target does not support aggregate initializers yet")
        if stmt.init is None:
            return
        slot = self._require_slot(stmt.name)
        value = self._emit_expr(stmt.init, 0)
        self._coerce_value(value, slot.type_, slot.info, 0)
        self._emit_store(slot, 0)

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
        if isinstance(expr, Identifier):
            return self._emit_identifier(expr, target)
        if isinstance(expr, UnaryExpr):
            return self._emit_unary(expr, target)
        if isinstance(expr, BinaryExpr):
            return self._emit_binary(expr, target)
        if isinstance(expr, AssignExpr):
            return self._emit_assign(expr, target)
        if isinstance(expr, CastExpr):
            return self._emit_cast(expr, target)
        if isinstance(expr, CommaExpr):
            self._emit_expr(expr.left, target)
            return self._emit_expr(expr.right, target)
        raise self._error(f"AArch64 target does not support {type(expr).__name__} yet")

    def _emit_identifier(self, expr: Identifier, target: int) -> _Value:
        assert self._func_sym is not None
        symbol = self._func_sym.locals.get(expr.name)
        if isinstance(symbol, EnumConstSymbol):
            info = self._scalar_info(symbol.type_)
            self._emit_load_immediate(self._reg(target, info), symbol.value, info.bits)
            return _Value(symbol.type_, info, target)
        if isinstance(symbol, VarSymbol):
            slot = self._require_slot(expr.name)
            self._emit_load(slot, target)
            return _Value(slot.type_, slot.info, target)
        if self._sema.file_scope is not None:
            file_symbol = self._sema.file_scope.lookup(expr.name)
            if isinstance(file_symbol, EnumConstSymbol):
                info = self._scalar_info(file_symbol.type_)
                self._emit_load_immediate(self._reg(target, info), file_symbol.value, info.bits)
                return _Value(file_symbol.type_, info, target)
        raise self._error(f"AArch64 target does not support global identifier: {expr.name}")

    def _emit_unary(self, expr: UnaryExpr, target: int) -> _Value:
        if expr.op == "+":
            return self._emit_expr(expr.operand, target)
        value = self._emit_expr(expr.operand, target)
        if expr.op == "-":
            self._emit(f"neg {self._reg(target, value.info)}, {self._reg(target, value.info)}")
            return value
        if expr.op == "~":
            self._emit(f"mvn {self._reg(target, value.info)}, {self._reg(target, value.info)}")
            return value
        if expr.op == "!":
            result_type = self._expr_type(expr)
            result_info = self._scalar_info(result_type)
            self._emit(f"cmp {self._reg(target, value.info)}, #0")
            self._emit(f"cset {self._reg(target, result_info)}, eq")
            return _Value(result_type, result_info, target)
        raise self._error(f"AArch64 target does not support unary operator {expr.op}")

    def _emit_binary(self, expr: BinaryExpr, target: int) -> _Value:
        if expr.op in {"&&", "||"}:
            raise self._error(
                f"AArch64 target does not support short-circuit operator {expr.op} yet"
            )
        if expr.op in {"<<", ">>"}:
            return self._emit_shift(expr, target)

        left = self._emit_expr(expr.left, 9)
        right = self._emit_expr(expr.right, 10)
        common_type = usual_arithmetic_conversion(left.type_, right.type_)
        if common_type is None:
            raise self._error(f"AArch64 target does not support binary operator {expr.op}")
        common_info = self._scalar_info(common_type)
        self._coerce_value(left, common_type, common_info, 9)
        self._coerce_value(right, common_type, common_info, 10)

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

    def _emit_shift(self, expr: BinaryExpr, target: int) -> _Value:
        left = self._emit_expr(expr.left, 9)
        right = self._emit_expr(expr.right, 10)
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
        if expr.op != "=":
            raise self._error(f"AArch64 target does not support assignment operator {expr.op}")
        if not isinstance(expr.target, Identifier):
            raise self._error("AArch64 target only supports assignment to local identifiers")
        slot = self._require_slot(expr.target.name)
        value = self._emit_expr(expr.value, target)
        self._coerce_value(value, slot.type_, slot.info, target)
        self._emit_store(slot, target)
        return _Value(slot.type_, slot.info, target)

    def _emit_cast(self, expr: CastExpr, target: int) -> _Value:
        value = self._emit_expr(expr.expr, target)
        target_type = self._expr_type(expr)
        target_info = self._scalar_info(target_type)
        self._coerce_value(value, target_type, target_info, target)
        return _Value(target_type, target_info, target)

    def _emit_load(self, slot: _Slot, target: int) -> None:
        offset = self._slot_addr(slot)
        reg = self._reg(target, slot.info)
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
        if slot.info.size == 1:
            self._emit(f"strb w{source}, {offset}")
            return
        if slot.info.size == 2:
            self._emit(f"strh w{source}, {offset}")
            return
        self._emit(f"str {self._reg(source, slot.info)}, {offset}")

    def _coerce_value(
        self,
        value: _Value,
        target_type: Type,
        target_info: _ScalarInfo,
        reg: int,
    ) -> None:
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

    def _expr_type(self, expr: Expr) -> Type:
        type_ = self._type_map.get(expr)
        return INT if type_ is None else type_

    def _scalar_info(self, type_: Type) -> _ScalarInfo:
        if type_.declarator_ops:
            if type_.declarator_ops[0][0] == "ptr":
                return _ScalarInfo(8, 8, False)
            raise self._error(f"AArch64 target does not support scalar type {type_}")
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
        }
        info = by_name.get(type_.name)
        if info is None:
            raise self._error(f"AArch64 target does not support scalar type {type_}")
        return info

    @staticmethod
    def _types_assignable(type_: Type) -> bool:
        return bool(
            type_.declarator_ops and type_.declarator_ops[0][0] == "ptr"
        ) or is_integer_type(unqualified_type(type_))

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
    def _reg(number: int, info: _ScalarInfo) -> str:
        return f"x{number}" if info.size == 8 else f"w{number}"

    @staticmethod
    def _slot_addr(slot: _Slot) -> str:
        return f"[sp, #{slot.offset}]"

    @staticmethod
    def _lsl_suffix(shift: int) -> str:
        return "" if shift == 0 else f", lsl #{shift}"

    @staticmethod
    def _align_to(value: int, alignment: int) -> int:
        return (value + alignment - 1) // alignment * alignment

    @staticmethod
    def _symbol_name(name: str) -> str:
        return f"_{name}"

    def _require_slot(self, name: str) -> _Slot:
        slot = self._slots.get(name)
        if slot is None:
            raise self._error(f"Unknown local variable: {name}")
        return slot

    def _emit(self, text: str) -> None:
        self._lines.append(f"    {text}")

    def _error(self, message: str) -> CodegenError:
        return aarch64_backend_error(self._result.filename, message)


def generate_aarch64_asm(result: FrontendResult) -> str:
    return _AArch64AsmGen(result).generate()
