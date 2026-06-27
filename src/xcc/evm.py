"""Minimal legacy EVM bytecode backend.

This target emits Ethereum legacy runtime bytecode directly. It is deliberately
small: exported C functions become ABI-dispatched contract entry points, and
unsupported C constructs fail with deterministic diagnostics.
"""

from dataclasses import dataclass

from xcc.ast import (
    AlignofExpr,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    BuiltinOffsetofExpr,
    BuiltinTypesCompatExpr,
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
    DesignatorRange,
    DoWhileStmt,
    Expr,
    ExprStmt,
    ForStmt,
    FunctionDef,
    GenericExpr,
    GotoStmt,
    Identifier,
    IfStmt,
    IndirectGotoStmt,
    InitList,
    IntLiteral,
    LabelAddressExpr,
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
    integer_promotion,
    is_integer_type,
    is_signed_integer_type,
    unqualified_type,
    usual_arithmetic_conversion,
)
from xcc.types import INT, Type, TypeOp

_EVM_UNSUPPORTED = "XCC-EVM-0001"
_WORD_BYTES = 32
_LOCAL_BASE = 0x80
_DYNAMIC_MEMORY_BASE = 0x400
_SCRATCH_LENGTH = 0x00
_SCRATCH_FREE_PTR = 0x20
_SCRATCH_INDEX = 0x40
_SCRATCH_DYNAMIC_OFFSET = 0x60
_RETURN_ARRAY_SOURCE = 0x100000
_RETURN_ARRAY_LENGTH = 0x100020
_RETURN_ARRAY_INDEX = 0x100040
_INTEGER_TYPE_BITS = {
    "_Bool": 1,
    "bool": 1,
    "char": 8,
    "signed char": 8,
    "unsigned char": 8,
    "short": 16,
    "unsigned short": 16,
    "int": 32,
    "unsigned int": 32,
    "long": 64,
    "unsigned long": 64,
    "long long": 64,
    "unsigned long long": 64,
    "__int128_t": 128,
    "__uint128_t": 128,
    "__evm_address": 160,
    "__evm_uint256": 256,
}


def evm_backend_error(filename: str, message: str) -> CodegenError:
    return CodegenError(Diagnostic("codegen", filename, message, code=_EVM_UNSUPPORTED))


_ROTATION = (
    1,
    3,
    6,
    10,
    15,
    21,
    28,
    36,
    45,
    55,
    2,
    14,
    27,
    41,
    56,
    8,
    25,
    43,
    62,
    18,
    39,
    61,
    20,
    44,
)
_PI_LANES = (
    10,
    7,
    11,
    17,
    18,
    3,
    5,
    16,
    8,
    21,
    24,
    4,
    15,
    23,
    19,
    13,
    12,
    2,
    20,
    14,
    22,
    9,
    6,
    1,
)
_ROUND_CONSTANTS = (
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
)
_MASK64 = (1 << 64) - 1
_StorageInitValue = int | str


def _rol64(value: int, amount: int) -> int:
    return ((value << amount) | (value >> (64 - amount))) & _MASK64


def _keccak_f1600(state: list[int]) -> None:
    for rc in _ROUND_CONSTANTS:
        c = [
            state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
            for x in range(5)
        ]
        d = [c[(x - 1) % 5] ^ _rol64(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(0, 25, 5):
                state[x + y] ^= d[x]

        current = state[1]
        for index, lane in enumerate(_PI_LANES):
            state[lane], current = _rol64(current, _ROTATION[index]), state[lane]

        for y in range(0, 25, 5):
            row = state[y : y + 5]
            for x in range(5):
                state[y + x] ^= (~row[(x + 1) % 5]) & row[(x + 2) % 5]
                state[y + x] &= _MASK64

        state[0] ^= rc


def keccak256(data: bytes) -> bytes:
    rate = 136
    state = [0] * 25
    offset = 0
    while offset + rate <= len(data):
        block = data[offset : offset + rate]
        for index in range(rate // 8):
            lane = int.from_bytes(block[index * 8 : index * 8 + 8], "little")
            state[index] ^= lane
        _keccak_f1600(state)
        offset += rate

    tail = bytearray(data[offset:])
    tail.append(0x01)
    tail.extend(b"\x00" * (rate - len(tail)))
    tail[-1] ^= 0x80
    for index in range(rate // 8):
        lane = int.from_bytes(tail[index * 8 : index * 8 + 8], "little")
        state[index] ^= lane
    _keccak_f1600(state)

    output = bytearray()
    while len(output) < 32:
        for lane in state[: rate // 8]:  # pragma: no branch - digest breaks before exhaustion.
            output.extend(lane.to_bytes(8, "little"))
            if len(output) >= 32:
                break
        if len(output) < 32:
            _keccak_f1600(state)  # pragma: no cover - 32-byte digest fits first squeeze.
    return bytes(output[:32])


def evm_selector(signature: str) -> int:
    return int.from_bytes(keccak256(signature.encode("ascii"))[:4], "big")


@dataclass(frozen=True)
class _Instruction:
    name: str
    operand: int | bytes | str | None = None
    push_size: int | None = None


@dataclass(frozen=True)
class _Label:
    name: str


_OPCODES = {
    "STOP": 0x00,
    "ADD": 0x01,
    "MUL": 0x02,
    "SUB": 0x03,
    "DIV": 0x04,
    "SDIV": 0x05,
    "MOD": 0x06,
    "SMOD": 0x07,
    "ADDMOD": 0x08,
    "MULMOD": 0x09,
    "EXP": 0x0A,
    "SIGNEXTEND": 0x0B,
    "LT": 0x10,
    "GT": 0x11,
    "SLT": 0x12,
    "SGT": 0x13,
    "EQ": 0x14,
    "ISZERO": 0x15,
    "AND": 0x16,
    "OR": 0x17,
    "XOR": 0x18,
    "NOT": 0x19,
    "BYTE": 0x1A,
    "SHL": 0x1B,
    "SHR": 0x1C,
    "SAR": 0x1D,
    "SHA3": 0x20,
    "ADDRESS": 0x30,
    "BALANCE": 0x31,
    "ORIGIN": 0x32,
    "CALLER": 0x33,
    "CALLVALUE": 0x34,
    "GASPRICE": 0x3A,
    "CALLDATACOPY": 0x37,
    "CODESIZE": 0x38,
    "EXTCODESIZE": 0x3B,
    "EXTCODECOPY": 0x3C,
    "RETURNDATASIZE": 0x3D,
    "RETURNDATACOPY": 0x3E,
    "EXTCODEHASH": 0x3F,
    "BLOCKHASH": 0x40,
    "COINBASE": 0x41,
    "TIMESTAMP": 0x42,
    "NUMBER": 0x43,
    "PREVRANDAO": 0x44,
    "GASLIMIT": 0x45,
    "CHAINID": 0x46,
    "SELFBALANCE": 0x47,
    "BASEFEE": 0x48,
    "BLOBHASH": 0x49,
    "BLOBBASEFEE": 0x4A,
    "POP": 0x50,
    "MLOAD": 0x51,
    "MSTORE": 0x52,
    "MSTORE8": 0x53,
    "SLOAD": 0x54,
    "SSTORE": 0x55,
    "JUMP": 0x56,
    "JUMPI": 0x57,
    "PC": 0x58,
    "MSIZE": 0x59,
    "GAS": 0x5A,
    "JUMPDEST": 0x5B,
    "TLOAD": 0x5C,
    "TSTORE": 0x5D,
    "MCOPY": 0x5E,
    "PUSH0": 0x5F,
    "CALLDATALOAD": 0x35,
    "CALLDATASIZE": 0x36,
    "CODECOPY": 0x39,
    "CREATE": 0xF0,
    "CALL": 0xF1,
    "CALLCODE": 0xF2,
    "RETURN": 0xF3,
    "DELEGATECALL": 0xF4,
    "CREATE2": 0xF5,
    "STATICCALL": 0xFA,
    "REVERT": 0xFD,
    "INVALID": 0xFE,
    "SELFDESTRUCT": 0xFF,
}
for _index in range(5):
    _OPCODES[f"LOG{_index}"] = 0xA0 + _index
for _index in range(1, 17):
    _OPCODES[f"DUP{_index}"] = 0x7F + _index
    _OPCODES[f"SWAP{_index}"] = 0x8F + _index


class _Assembler:
    def __init__(self) -> None:
        self._items: list[_Instruction | _Label] = []

    def label(self, name: str) -> None:
        self._items.append(_Label(name))
        self.op("JUMPDEST")

    def op(self, name: str) -> None:
        self._items.append(_Instruction(name))

    def push(self, value: int, *, size: int | None = None) -> None:
        if value < 0:
            value &= (1 << 256) - 1
        if size is None:
            size = 0 if value == 0 else (value.bit_length() + 7) // 8
        self._items.append(_Instruction("PUSH", value, size))

    def push_label(self, label: str) -> None:
        self._items.append(_Instruction("PUSH", label, 2))

    def to_bytes(self) -> bytes:
        labels = self._label_offsets()
        out = bytearray()
        for item in self._items:
            if isinstance(item, _Label):
                continue
            if item.name == "PUSH":
                assert item.push_size is not None
                value = labels[item.operand] if isinstance(item.operand, str) else item.operand
                assert isinstance(value, int)
                if item.push_size == 0:
                    out.append(_OPCODES["PUSH0"])
                    continue
                out.append(0x5F + item.push_size)
                out.extend(value.to_bytes(item.push_size, "big"))
                continue
            out.append(_OPCODES[item.name])
        return bytes(out)

    def to_asm(self) -> str:
        labels = self._label_offsets()
        lines: list[str] = []
        for item in self._items:
            if isinstance(item, _Label):
                lines.append(f"{item.name}:")
                continue
            if item.name == "PUSH":
                assert item.push_size is not None
                value = labels[item.operand] if isinstance(item.operand, str) else item.operand
                assert isinstance(value, int)
                if item.push_size == 0:
                    lines.append("    PUSH0")
                    continue
                lines.append(f"    PUSH{item.push_size} 0x{value:0{item.push_size * 2}x}")
                continue
            lines.append(f"    {item.name}")
        return "\n".join(lines) + "\n"

    def _label_offsets(self) -> dict[str, int]:
        offset = 0
        labels: dict[str, int] = {}
        for item in self._items:
            if isinstance(item, _Label):
                labels[item.name] = offset
                continue
            if item.name == "PUSH":
                assert item.push_size is not None
                offset += 1 + item.push_size
            else:
                offset += 1
        return labels

    def label_offsets(self) -> dict[str, int]:
        return self._label_offsets()


@dataclass(frozen=True)
class _Local:
    offset: int
    type_: Type
    slots: int


@dataclass(frozen=True)
class _StorageGlobal:
    slot: int
    type_: Type
    slots: int
    initializers: tuple[_StorageInitValue, ...] = ()


@dataclass(frozen=True)
class _LValue:
    space: str
    type_: Type
    bit_width: int | None = None


@dataclass(frozen=True)
class _RecordMemberAccess:
    type_: Type
    slot_offset: int
    bit_width: int | None = None


@dataclass(frozen=True)
class _IndirectCallLayout:
    target_offset: int
    arg_offsets: tuple[int, ...]


@dataclass
class _FrameLayoutState:
    next_offset: int


@dataclass(frozen=True)
class _FunctionLayout:
    return_pc_offset: int
    return_value_offset: int
    locals: dict[str, _Local]
    compound_literals: dict[int, _Local]
    string_literals: dict[int, _Local]
    indirect_calls: dict[int, _IndirectCallLayout]
    frame_end: int


class _EvmGen:
    def __init__(self, result: FrontendResult, *, allow_storage_initializers: bool = False) -> None:
        self._result = result
        self._unit = result.unit
        self._sema = result.sema
        self._type_map = result.sema.type_map
        self._asm = _Assembler()
        self._locals: dict[str, _Local] = {}
        self._storage_globals: dict[str, _StorageGlobal] = {}
        self._static_locals: dict[str, dict[str, _StorageGlobal]] = {}
        self._function_layouts: dict[str, _FunctionLayout] = {}
        self._functions_by_name: dict[str, FunctionDef] = {}
        self._current_layout: _FunctionLayout | None = None
        self._func_sym: FunctionSymbol | None = None
        self._next_local_offset = 0x40
        self._return_label = ""
        self._return_mode = "abi"
        self._label_counter = 0
        self._break_stack: list[str] = []
        self._continue_stack: list[str] = []
        self._switch_stack: list[tuple[dict[int, str], str | None]] = []
        self._allow_storage_initializers = allow_storage_initializers
        self._dynamic_memory_base = _DYNAMIC_MEMORY_BASE

    def generate_asm(self) -> str:
        self._emit_contract()
        return self._asm.to_asm()

    def generate_bytecode(self) -> str:
        self._emit_contract()
        return self._asm.to_bytes().hex()

    def generate_initcode(self) -> str:
        runtime = bytes.fromhex(self.generate_bytecode())
        runtime_labels = self._asm.label_offsets()
        stores = tuple(
            (
                storage.slot + index,
                self._resolve_storage_initializer_value(value, runtime_labels),
            )
            for storage in self._storage_objects()
            for index, value in enumerate(storage.initializers)
        )
        return self._build_initcode(runtime, stores).hex()

    def _emit_contract(self) -> None:
        functions = [function for function in self._unit.functions if function.body is not None]
        self._functions_by_name = {function.name: function for function in functions}
        self._collect_storage_globals()
        exported = [function for function in functions if function.storage_class != "static"]
        if not exported:
            raise evm_backend_error(self._result.filename, "EVM target needs one exported function")
        for function in functions:
            self._validate_function(function)
        self._plan_function_layouts(functions)

        fallback_label = self._new_label("fallback")
        self._asm.op("CALLDATASIZE")
        self._asm.push(4)
        self._asm.op("LT")
        self._asm.push_label(fallback_label)
        self._asm.op("JUMPI")
        self._asm.push(0)
        self._asm.op("CALLDATALOAD")
        self._asm.push(224)
        self._asm.op("SHR")
        for function in exported:
            self._asm.op("DUP1")
            self._asm.push(evm_selector(self._abi_signature(function)), size=4)
            self._asm.op("EQ")
            self._asm.push_label(self._function_label(function))
            self._asm.op("JUMPI")
        self._asm.op("POP")
        self._emit_revert(fallback_label)
        for function in exported:
            self._emit_abi_function(function)
        for function in functions:
            self._emit_internal_function(function)

    def _collect_storage_globals(self) -> None:
        if self._sema.file_scope is None:
            return

        def next_storage_slot() -> int:
            return sum(storage.slots for storage in self._storage_objects())

        def collect(stmt: Stmt) -> None:
            if isinstance(stmt, DeclGroupStmt):
                for declaration in stmt.declarations:
                    collect(declaration)
                return
            if (
                not isinstance(stmt, DeclStmt)
                or stmt.name is None
                or stmt.storage_class in {"typedef", "extern"}
            ):
                return
            assert self._sema.file_scope is not None
            symbol = self._sema.file_scope.lookup(stmt.name)
            if not isinstance(symbol, VarSymbol) or symbol.is_extern:
                return
            slots = self._storage_slots_for_type(symbol.type_)
            initializers: tuple[_StorageInitValue, ...] = ()
            if stmt.init is not None:
                if not self._allow_storage_initializers:
                    raise evm_backend_error(
                        self._result.filename,
                        "EVM target does not support initialized storage globals",
                    )
                initializers = self._eval_storage_initializers(symbol.type_, stmt.init)
            if stmt.name not in self._storage_globals:
                self._storage_globals[stmt.name] = _StorageGlobal(
                    next_storage_slot(),
                    symbol.type_,
                    slots,
                    initializers,
                )

        for declaration in self._unit.declarations:
            collect(declaration)

        def collect_static_expr(expr: Expr, function_name: str, symbol: FunctionSymbol) -> None:
            if isinstance(expr, StatementExpr):
                collect_static_stmt(expr.body, function_name, symbol)
                return
            if isinstance(expr, BinaryExpr):
                collect_static_expr(expr.left, function_name, symbol)
                collect_static_expr(expr.right, function_name, symbol)
                return
            if isinstance(expr, AssignExpr):
                collect_static_expr(expr.target, function_name, symbol)
                collect_static_expr(expr.value, function_name, symbol)
                return
            if isinstance(expr, ConditionalExpr):
                collect_static_expr(expr.condition, function_name, symbol)
                collect_static_expr(expr.then_expr, function_name, symbol)
                collect_static_expr(expr.else_expr, function_name, symbol)
                return
            if isinstance(expr, CommaExpr):
                collect_static_expr(expr.left, function_name, symbol)
                collect_static_expr(expr.right, function_name, symbol)
                return
            if isinstance(expr, UnaryExpr | UpdateExpr):
                collect_static_expr(expr.operand, function_name, symbol)
                return
            if isinstance(expr, CastExpr):
                collect_static_expr(expr.expr, function_name, symbol)
                return
            if isinstance(expr, CallExpr):
                collect_static_expr(expr.callee, function_name, symbol)
                for arg in expr.args:
                    collect_static_expr(arg, function_name, symbol)
                return
            if isinstance(expr, SubscriptExpr):
                collect_static_expr(expr.base, function_name, symbol)
                collect_static_expr(expr.index, function_name, symbol)
                return
            if isinstance(expr, MemberExpr):
                collect_static_expr(expr.base, function_name, symbol)
                return
            if isinstance(expr, GenericExpr):
                collect_static_expr(self._select_generic_expr(expr), function_name, symbol)

        def collect_static_init(
            init: Expr | InitList,
            function_name: str,
            symbol: FunctionSymbol,
        ) -> None:
            if isinstance(init, InitList):
                for item in init.items:
                    collect_static_init(item.initializer, function_name, symbol)
                return
            collect_static_expr(init, function_name, symbol)

        def collect_static_stmt(stmt: Stmt, function_name: str, symbol: FunctionSymbol) -> None:
            if isinstance(stmt, CompoundStmt):
                for inner in stmt.statements:
                    collect_static_stmt(inner, function_name, symbol)
                return
            if isinstance(stmt, DeclGroupStmt):
                for declaration in stmt.declarations:
                    collect_static_stmt(declaration, function_name, symbol)
                return
            if isinstance(stmt, DeclStmt):
                if stmt.name is not None and stmt.storage_class == "static":
                    static_locals = self._static_locals.setdefault(function_name, {})
                    if stmt.name not in static_locals:
                        type_ = self._lookup_local_type(stmt, symbol)
                        slots = self._storage_slots_for_type(type_)
                        initializers: tuple[_StorageInitValue, ...] = ()
                        if stmt.init is not None:
                            if not self._allow_storage_initializers:
                                raise evm_backend_error(
                                    self._result.filename,
                                    "EVM target does not support initialized storage globals",
                                )
                            initializers = self._eval_storage_initializers(type_, stmt.init)
                        static_locals[stmt.name] = _StorageGlobal(
                            next_storage_slot(),
                            type_,
                            slots,
                            initializers,
                        )
                    return
                if stmt.init is not None:
                    collect_static_init(stmt.init, function_name, symbol)
                return
            if isinstance(stmt, ExprStmt):
                collect_static_expr(stmt.expr, function_name, symbol)
                return
            if isinstance(stmt, ReturnStmt):
                if stmt.value is not None:
                    collect_static_expr(stmt.value, function_name, symbol)
                return
            if isinstance(stmt, IndirectGotoStmt):
                collect_static_expr(stmt.target, function_name, symbol)
                return
            if isinstance(stmt, IfStmt):
                collect_static_expr(stmt.condition, function_name, symbol)
                collect_static_stmt(stmt.then_body, function_name, symbol)
                if stmt.else_body is not None:
                    collect_static_stmt(stmt.else_body, function_name, symbol)
                return
            if isinstance(stmt, SwitchStmt):
                collect_static_expr(stmt.condition, function_name, symbol)
                collect_static_stmt(stmt.body, function_name, symbol)
                return
            if isinstance(stmt, CaseStmt | DefaultStmt):
                collect_static_stmt(stmt.body, function_name, symbol)
                return
            if isinstance(stmt, WhileStmt | DoWhileStmt):
                collect_static_expr(stmt.condition, function_name, symbol)
                collect_static_stmt(stmt.body, function_name, symbol)
                return
            if isinstance(stmt, ForStmt):
                if isinstance(stmt.init, Stmt):
                    collect_static_stmt(stmt.init, function_name, symbol)
                elif stmt.init is not None:
                    collect_static_expr(stmt.init, function_name, symbol)
                if stmt.condition is not None:
                    collect_static_expr(stmt.condition, function_name, symbol)
                collect_static_stmt(stmt.body, function_name, symbol)
                if stmt.post is not None:
                    collect_static_expr(stmt.post, function_name, symbol)

        for function in self._unit.functions:
            symbol = self._sema.functions.get(function.name)
            if function.body is not None and symbol is not None:
                collect_static_stmt(function.body, function.name, symbol)

    def _storage_objects(self) -> tuple[_StorageGlobal, ...]:
        objects = list(self._storage_globals.values())
        for function_statics in self._static_locals.values():
            objects.extend(function_statics.values())
        return tuple(objects)

    def _lookup_static_local(self, name: str) -> _StorageGlobal | None:
        if self._func_sym is None:
            return None
        return self._static_locals.get(self._func_sym.name, {}).get(name)

    def _lookup_enum_constant(self, name: str) -> int | None:
        if self._func_sym is not None:
            symbol = self._func_sym.locals.get(name)
            if isinstance(symbol, EnumConstSymbol):
                return symbol.value
        if self._sema.file_scope is not None:
            symbol = self._sema.file_scope.lookup(name)
            if isinstance(symbol, EnumConstSymbol):
                return symbol.value
        return None

    def _validate_function(self, function: FunctionDef) -> None:
        symbol = self._sema.functions.get(function.name)
        if symbol is None:
            raise evm_backend_error(
                self._result.filename,
                f"missing function symbol: {function.name}",
            )
        if function.is_variadic:
            raise evm_backend_error(
                self._result.filename,
                "EVM target does not support variadic functions",
            )
        is_exported = function.storage_class != "static"
        for param in function.params:
            if param.name is None:
                raise evm_backend_error(
                    self._result.filename,
                    "EVM target requires named parameters",
                )
            param_type = symbol.locals[param.name].type_
            if is_exported:
                self._require_evm_abi_param_type(param_type)
            else:
                self._require_evm_internal_param_type(param_type)
        if is_exported:
            self._require_evm_abi_return_type(symbol.return_type)
        else:
            self._require_return_type(symbol.return_type)

    def _plan_function_layouts(self, functions: list[FunctionDef]) -> None:
        layout_state = _FrameLayoutState(_LOCAL_BASE)
        layouts: dict[str, _FunctionLayout] = {}
        for function in functions:
            symbol = self._sema.functions[function.name]
            locals_: dict[str, _Local] = {}
            compound_literals: dict[int, _Local] = {}
            string_literals: dict[int, _Local] = {}
            indirect_calls: dict[int, _IndirectCallLayout] = {}
            return_pc_offset = layout_state.next_offset
            layout_state.next_offset += _WORD_BYTES
            return_value_offset = layout_state.next_offset
            if not self._is_void_type(symbol.return_type):
                layout_state.next_offset += (
                    self._memory_slots_for_type(symbol.return_type) * _WORD_BYTES
                )

            def alloc(name: str, type_: Type, locals_ref: dict[str, _Local] = locals_) -> None:
                if name in locals_ref:
                    return
                slots = self._memory_slots_for_type(type_)
                locals_ref[name] = _Local(layout_state.next_offset, type_, slots)
                layout_state.next_offset += slots * _WORD_BYTES

            def alloc_compound(
                expr: CompoundLiteralExpr,
                compound_literals_ref: dict[int, _Local] = compound_literals,
            ) -> None:
                expr_id = id(expr)
                if expr_id in compound_literals_ref:
                    return
                type_ = self._type_map.get(expr)
                if type_ is None:
                    type_ = self._resolve_type_spec(expr.type_spec)
                slots = self._memory_slots_for_type(type_)
                compound_literals_ref[expr_id] = _Local(layout_state.next_offset, type_, slots)
                layout_state.next_offset += slots * _WORD_BYTES

            def alloc_string(
                expr: StringLiteral,
                string_literals_ref: dict[int, _Local] = string_literals,
            ) -> None:
                expr_id = id(expr)
                if expr_id in string_literals_ref:
                    return
                type_ = self._type_map.get(expr)
                if type_ is None:
                    raise evm_backend_error(
                        self._result.filename,
                        "EVM target cannot resolve string literal type",
                    )
                slots = self._memory_slots_for_type(type_)
                string_literals_ref[expr_id] = _Local(layout_state.next_offset, type_, slots)
                layout_state.next_offset += slots * _WORD_BYTES

            def alloc_indirect_call(
                expr: CallExpr,
                symbol_ref: FunctionSymbol = symbol,
                indirect_calls_ref: dict[int, _IndirectCallLayout] = indirect_calls,
            ) -> None:
                expr_id = id(expr)
                if expr_id in indirect_calls_ref:
                    return
                signature = self._callable_signature_for_expr(expr.callee, symbol_ref)
                if signature is None:
                    return
                return_type, function_params = signature
                self._require_return_type(return_type)
                params, is_variadic = function_params
                if params is None or is_variadic:
                    raise evm_backend_error(
                        self._result.filename,
                        "EVM function pointer calls need a fixed prototype",
                    )
                target_offset = layout_state.next_offset
                layout_state.next_offset += _WORD_BYTES
                arg_offsets: list[int] = []
                for param_type in params:
                    if self._is_word_value_type(param_type):
                        arg_offsets.append(layout_state.next_offset)
                        layout_state.next_offset += _WORD_BYTES
                        continue
                    if self._is_record_type(param_type):
                        arg_offsets.append(layout_state.next_offset)
                        layout_state.next_offset += (
                            self._memory_slots_for_type(param_type) * _WORD_BYTES
                        )
                        continue
                    else:
                        raise evm_backend_error(
                            self._result.filename,
                            f"unsupported EVM function pointer parameter type: {param_type}",
                        )
                indirect_calls_ref[expr_id] = _IndirectCallLayout(
                    target_offset,
                    tuple(arg_offsets),
                )

            for param in function.params:
                assert param.name is not None
                alloc(param.name, symbol.locals[param.name].type_)

            def walk_initializer(init: Expr | InitList) -> None:
                if isinstance(init, InitList):
                    for item in init.items:
                        walk_initializer(item.initializer)
                    return
                walk_expr(init)

            def walk_expr(expr: Expr) -> None:
                if isinstance(expr, StringLiteral):
                    alloc_string(expr)
                    return
                if isinstance(expr, CompoundLiteralExpr):
                    alloc_compound(expr)
                    walk_initializer(expr.initializer)
                    return
                if isinstance(expr, StatementExpr):
                    walk(expr.body)
                    return
                if isinstance(expr, BinaryExpr):
                    walk_expr(expr.left)
                    walk_expr(expr.right)
                    return
                if isinstance(expr, AssignExpr):
                    walk_expr(expr.target)
                    walk_expr(expr.value)
                    return
                if isinstance(expr, ConditionalExpr):
                    walk_expr(expr.condition)
                    walk_expr(expr.then_expr)
                    walk_expr(expr.else_expr)
                    return
                if isinstance(expr, CommaExpr):
                    walk_expr(expr.left)
                    walk_expr(expr.right)
                    return
                if isinstance(expr, UnaryExpr | UpdateExpr):
                    walk_expr(expr.operand)
                    return
                if isinstance(expr, CastExpr):
                    walk_expr(expr.expr)
                    return
                if isinstance(expr, CallExpr):
                    alloc_indirect_call(expr)
                    walk_expr(expr.callee)
                    for arg in expr.args:
                        walk_expr(arg)
                    return
                if isinstance(expr, SubscriptExpr):
                    walk_expr(expr.base)
                    walk_expr(expr.index)
                    return
                if isinstance(expr, MemberExpr):
                    walk_expr(expr.base)
                    return
                if isinstance(expr, GenericExpr):
                    walk_expr(self._select_generic_expr(expr))

            def walk(
                stmt: Stmt,
                symbol_ref: FunctionSymbol = symbol,
            ) -> None:
                if isinstance(stmt, CompoundStmt):
                    for inner in stmt.statements:
                        walk(inner)
                    return
                if isinstance(stmt, DeclGroupStmt):
                    for declaration in stmt.declarations:
                        walk(declaration)
                    return
                if isinstance(stmt, DeclStmt):
                    if stmt.storage_class == "static":
                        return
                    if self._is_function_declaration(stmt):
                        return
                    if stmt.name is not None and stmt.storage_class not in {"typedef", "extern"}:
                        alloc(stmt.name, self._lookup_local_type(stmt, symbol_ref))
                    if stmt.init is not None:
                        walk_initializer(stmt.init)
                    return
                if isinstance(stmt, ExprStmt):
                    walk_expr(stmt.expr)
                    return
                if isinstance(stmt, ReturnStmt):
                    if stmt.value is not None:
                        walk_expr(stmt.value)
                    return
                if isinstance(stmt, IndirectGotoStmt):
                    walk_expr(stmt.target)
                    return
                if isinstance(stmt, IfStmt):
                    walk_expr(stmt.condition)
                    walk(stmt.then_body)
                    if stmt.else_body is not None:
                        walk(stmt.else_body)
                    return
                if isinstance(stmt, SwitchStmt):
                    walk_expr(stmt.condition)
                    walk(stmt.body)
                    return
                if isinstance(stmt, CaseStmt | DefaultStmt):
                    walk(stmt.body)
                    return
                if isinstance(stmt, WhileStmt | DoWhileStmt):
                    walk_expr(stmt.condition)
                    walk(stmt.body)
                    return
                if isinstance(stmt, ForStmt):
                    if isinstance(stmt.init, Stmt):
                        walk(stmt.init)
                    elif stmt.init is not None:
                        walk_expr(stmt.init)
                    if stmt.condition is not None:
                        walk_expr(stmt.condition)
                    walk(stmt.body)
                    if stmt.post is not None:
                        walk_expr(stmt.post)

            assert function.body is not None
            walk(function.body)
            layouts[function.name] = _FunctionLayout(
                return_pc_offset,
                return_value_offset,
                locals_,
                compound_literals,
                string_literals,
                indirect_calls,
                layout_state.next_offset,
            )
        self._function_layouts = layouts
        self._dynamic_memory_base = max(_DYNAMIC_MEMORY_BASE, layout_state.next_offset)

    def _function_label(self, function: FunctionDef) -> str:
        return f"func_{function.name}"

    def _internal_function_label(self, function: FunctionDef) -> str:
        return f"internal_{function.name}"

    def _user_label(self, name: str) -> str:
        if self._func_sym is None:
            raise evm_backend_error(self._result.filename, "EVM label outside function")
        return f"user_{self._return_mode}_{self._func_sym.name}_{name}"

    def _callable_signature_for_expr(
        self,
        expr: Expr,
        symbol: FunctionSymbol | None = None,
    ) -> tuple[Type, tuple[tuple[Type, ...] | None, bool]] | None:
        type_ = self._type_map.get(expr)
        if type_ is None and isinstance(expr, Identifier):
            if symbol is not None:
                local_symbol = symbol.locals.get(expr.name)
                if isinstance(local_symbol, VarSymbol):
                    type_ = local_symbol.type_
            if type_ is None and self._sema.file_scope is not None:
                file_symbol = self._sema.file_scope.lookup(expr.name)
                if isinstance(file_symbol, VarSymbol):
                    type_ = file_symbol.type_
        if type_ is None:
            return None
        return type_.callable_signature()

    def _function_callable_signature(
        self,
        function: FunctionDef,
    ) -> tuple[Type, tuple[tuple[Type, ...] | None, bool]]:
        symbol = self._sema.functions[function.name]
        params: list[Type] = []
        for param in function.params:
            assert param.name is not None
            params.append(symbol.locals[param.name].type_)
        return symbol.return_type, (tuple(params), function.is_variadic)

    def _function_pointer_targets(
        self,
        signature: tuple[Type, tuple[tuple[Type, ...] | None, bool]],
    ) -> tuple[FunctionDef, ...]:
        return_type, function_params = signature
        params, is_variadic = function_params
        if params is None or is_variadic:
            return ()
        targets: list[FunctionDef] = []
        for function in self._functions_by_name.values():
            target_return, target_params = self._function_callable_signature(function)
            if target_return == return_type and target_params == function_params:
                targets.append(function)
        return tuple(targets)

    def _abi_signature(self, function: FunctionDef) -> str:
        symbol = self._sema.functions[function.name]
        parts = []
        for param in function.params:
            assert param.name is not None
            parts.append(self._abi_type(symbol.locals[param.name].type_))
        return f"{function.name}({','.join(parts)})"

    def _abi_type(self, type_: Type) -> str:
        pointee = type_.pointee()
        if pointee is not None:
            if not self._is_word_value_type(pointee):
                raise evm_backend_error(
                    self._result.filename,
                    f"unsupported EVM ABI array element type: {pointee}",
                )
            return f"{self._abi_type(pointee)}[]"
        if type_.declarator_ops:
            raise evm_backend_error(self._result.filename, "EVM ABI only supports scalar integers")
        mapping = {
            "_Bool": "bool",
            "bool": "bool",
            "char": "int8",
            "signed char": "int8",
            "unsigned char": "uint8",
            "short": "int16",
            "unsigned short": "uint16",
            "int": "int32",
            "unsigned int": "uint32",
            "long": "int64",
            "unsigned long": "uint64",
            "long long": "int64",
            "unsigned long long": "uint64",
            "__evm_uint256": "uint256",
            "__evm_address": "address",
        }
        result = mapping.get(type_.name)
        if result is None:
            raise evm_backend_error(self._result.filename, f"unsupported EVM ABI type: {type_}")
        return result

    def _require_return_type(self, type_: Type) -> None:
        if self._is_void_type(type_):
            return
        if self._is_word_value_type(type_):
            return
        if self._is_record_type(type_):
            return
        self._require_evm_integer(type_)

    def _require_evm_abi_return_type(self, type_: Type) -> None:
        if self._is_void_type(type_):
            return
        if type_.pointee() is not None:
            raise evm_backend_error(
                self._result.filename,
                "EVM ABI does not support pointer return types",
            )
        self._require_evm_integer(type_)

    def _require_evm_abi_param_type(self, type_: Type) -> None:
        if type_.pointee() is not None:
            pointee = type_.pointee()
            assert pointee is not None
            if self._is_word_value_type(pointee):
                return
        self._require_evm_integer(type_)

    def _require_evm_internal_param_type(self, type_: Type) -> None:
        if self._is_word_value_type(type_):
            return
        if self._is_record_type(type_):
            return
        raise evm_backend_error(self._result.filename, f"unsupported EVM parameter type: {type_}")

    def _require_evm_integer(self, type_: Type) -> None:
        if type_.declarator_ops or not is_integer_type(type_):
            raise evm_backend_error(self._result.filename, f"unsupported EVM scalar type: {type_}")

    def _is_word_value_type(self, type_: Type) -> bool:
        return type_.pointee() is not None or (not type_.declarator_ops and is_integer_type(type_))

    @staticmethod
    def _is_function_pointer_type(type_: Type) -> bool:
        pointee = type_.pointee()
        return pointee is not None and pointee.callable_signature() is not None

    def _is_record_type(self, type_: Type) -> bool:
        return not type_.declarator_ops and type_.name in self._sema.record_definitions

    def _memory_slots_for_type(self, type_: Type) -> int:
        if self._is_word_value_type(type_):
            return 1
        if type_.is_array():
            length = type_.declarator_ops[0][1]
            if not isinstance(length, int) or length <= 0:
                raise evm_backend_error(
                    self._result.filename,
                    f"EVM target needs a complete array type: {type_}",
                )
            element_type = type_.element_type()
            assert element_type is not None
            return length * self._memory_slots_for_type(element_type)
        if self._is_record_type(type_):
            return self._record_slots_for_type(type_)
        raise evm_backend_error(self._result.filename, f"unsupported EVM object type: {type_}")

    def _storage_slots_for_type(self, type_: Type) -> int:
        return self._memory_slots_for_type(type_)

    def _record_slots_for_type(self, type_: Type) -> int:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            raise evm_backend_error(self._result.filename, f"unknown EVM record type: {type_}")
        if type_.name.startswith("union "):
            return max(
                (self._record_member_slots(member) for member in members),
                default=1,
            )
        total = 0
        for member in members:
            if (
                member.name is None
                and not self._is_anonymous_record_member(member)
                and not self._is_unnamed_bit_field(member)
            ):
                raise evm_backend_error(
                    self._result.filename,
                    "EVM target does not support anonymous storage members",
                )
            total += self._record_member_slots(member)
        return max(total, 1)

    def _record_member_slots(self, member: RecordMemberInfo) -> int:
        if member.bit_width == 0:
            return 0
        return self._storage_slots_for_type(member.type_)

    def _is_anonymous_record_member(self, member: RecordMemberInfo) -> bool:
        return (
            member.name is None
            and member.bit_width is None
            and not member.type_.declarator_ops
            and self._is_record_type(member.type_)
        )

    def _is_unnamed_bit_field(self, member: RecordMemberInfo) -> bool:
        return member.name is None and member.bit_width is not None

    def _next_record_initializer_member_index(
        self,
        members: tuple[RecordMemberInfo, ...],
        start: int,
    ) -> int:
        index = start
        while index < len(members) and self._is_unnamed_bit_field(members[index]):
            index += 1
        return index

    def _record_member_offset(self, type_: Type, member_name: str) -> tuple[Type, int]:
        access = self._record_member_access(type_, member_name)
        return access.type_, access.slot_offset

    def _record_member_access(self, type_: Type, member_name: str) -> _RecordMemberAccess:
        result = self._find_record_member_access(type_, member_name)
        if result is not None:
            return result
        raise evm_backend_error(
            self._result.filename,
            f"unknown EVM record member: {member_name}",
        )

    def _find_record_member_access(
        self,
        type_: Type,
        member_name: str,
    ) -> _RecordMemberAccess | None:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            raise evm_backend_error(self._result.filename, f"unknown EVM record type: {type_}")
        offset = 0
        is_union = type_.name.startswith("union ")
        for member in members:
            member_slots = self._record_member_slots(member)
            member_offset = 0 if is_union else offset
            if member.name == member_name:
                return _RecordMemberAccess(member.type_, member_offset, member.bit_width)
            if self._is_anonymous_record_member(member):
                nested = self._find_record_member_access(member.type_, member_name)
                if nested is not None:
                    return _RecordMemberAccess(
                        nested.type_,
                        member_offset + nested.slot_offset,
                        nested.bit_width,
                    )
            if not is_union:
                offset += member_slots
        return None

    def _record_member_index(self, type_: Type, member_name: str) -> int:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            raise evm_backend_error(self._result.filename, f"unknown EVM record type: {type_}")
        for index, member in enumerate(members):
            if member.name == member_name:
                return index
            if self._is_anonymous_record_member(member) and (
                self._find_record_member_access(member.type_, member_name) is not None
            ):
                return index
        raise evm_backend_error(
            self._result.filename,
            f"unknown EVM record member: {member_name}",
        )

    def _record_member_slot_offset_by_index(self, type_: Type, member_index: int) -> int:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            raise evm_backend_error(self._result.filename, f"unknown EVM record type: {type_}")
        if member_index < 0 or member_index >= len(members):
            raise evm_backend_error(self._result.filename, "unknown EVM record member index")
        if type_.name.startswith("union "):
            return 0
        offset = 0
        for index, member in enumerate(members):
            if index == member_index:
                return offset
            offset += self._record_member_slots(member)
        raise evm_backend_error(  # pragma: no cover - in-range tuple indexes return above.
            self._result.filename,
            "unknown EVM record member index",
        )

    def _prepare_function_context(self, function: FunctionDef, return_mode: str) -> None:
        layout = self._function_layouts[function.name]
        self._locals = {}
        self._current_layout = layout
        self._func_sym = self._sema.functions[function.name]
        self._next_local_offset = layout.frame_end
        self._return_label = self._new_label(f"{function.name}_return")
        self._return_mode = return_mode

    def _finish_function_context(self) -> None:
        self._locals = {}
        self._current_layout = None
        self._func_sym = None
        self._return_mode = "abi"

    def _emit_abi_function(self, function: FunctionDef) -> None:
        self._asm.label(self._function_label(function))
        self._prepare_function_context(function, "abi")
        assert self._func_sym is not None
        symbol = self._func_sym
        self._emit_require_calldata_size(4 + len(function.params) * _WORD_BYTES)
        if any(
            symbol.locals[param.name].type_.pointee() is not None
            for param in function.params
            if param.name is not None
        ):
            self._asm.push(self._dynamic_memory_base)
            self._store_mem_word(_SCRATCH_FREE_PTR)
        for index, param in enumerate(function.params):
            assert param.name is not None
            local = self._alloc_local(param.name, symbol.locals[param.name].type_)
            if local.type_.pointee() is not None:
                self._emit_dynamic_array_param(index, len(function.params) * _WORD_BYTES, local)
            else:
                self._asm.push(4 + index * _WORD_BYTES)
                self._asm.op("CALLDATALOAD")
                self._emit_integer_conversion_to_type(local.type_)
                self._store_local(local)
        assert function.body is not None
        self._emit_stmt(function.body)
        if symbol.return_type.name == "void" and not symbol.return_type.declarator_ops:
            self._asm.op("STOP")
        else:
            self._asm.push(0)
            self._asm.push(0)
            self._asm.op("MSTORE")
            self._emit_return_word()
        self._asm.label(self._return_label)
        self._asm.op("STOP")
        self._finish_function_context()

    def _emit_require_calldata_size(self, minimum_size: int) -> None:
        self._asm.op("CALLDATASIZE")
        self._asm.push(minimum_size)
        self._asm.op("LT")
        self._emit_revert_if_true("abi_short_calldata")

    def _emit_require_calldata_size_from_stack(self) -> None:
        self._asm.op("CALLDATASIZE")
        self._asm.op("SWAP1")
        self._asm.op("LT")
        self._emit_revert_if_true("abi_short_calldata")

    def _emit_revert_if_true(self, label_prefix: str) -> None:
        ok_label = self._new_label(f"{label_prefix}_ok")
        revert_label = self._new_label(label_prefix)
        self._asm.push_label(revert_label)
        self._asm.op("JUMPI")
        self._asm.push_label(ok_label)
        self._asm.op("JUMP")
        self._emit_revert(revert_label)
        self._asm.label(ok_label)

    def _emit_internal_function(self, function: FunctionDef) -> None:
        self._asm.label(self._internal_function_label(function))
        self._prepare_function_context(function, "internal")
        assert self._func_sym is not None
        symbol = self._func_sym
        for param in function.params:
            assert param.name is not None
            self._alloc_local(param.name, symbol.locals[param.name].type_)
        assert function.body is not None
        self._emit_stmt(function.body)
        self._emit_internal_default_return(symbol.return_type)
        self._finish_function_context()

    def _emit_internal_default_return(self, return_type: Type) -> None:
        if not self._is_void_type(return_type):
            if self._is_record_type(return_type):
                if self._current_layout is None:
                    raise evm_backend_error(
                        self._result.filename,
                        "missing EVM internal return layout",
                    )
                for slot_index in range(self._memory_slots_for_type(return_type)):
                    self._asm.push(0)
                    self._store_mem_word(
                        self._current_layout.return_value_offset + slot_index * _WORD_BYTES,
                    )
                self._jump_to_internal_return_pc()
                return
            self._asm.push(0)
            self._emit_integer_conversion_to_type(return_type)
            self._store_internal_return_value()
        self._jump_to_internal_return_pc()

    def _alloc_local(self, name: str, type_: Type) -> _Local:
        if self._current_layout is not None:
            local = self._current_layout.locals.get(name)
            if local is not None:
                self._locals[name] = local
                return local
        slots = self._memory_slots_for_type(type_)
        local = _Local(self._next_local_offset, type_, slots)
        self._next_local_offset += slots * _WORD_BYTES
        self._locals[name] = local
        return local

    def _emit_dynamic_array_param(self, index: int, head_size: int, local: _Local) -> None:
        element_type = local.type_.pointee()
        if element_type is None:
            raise evm_backend_error(
                self._result.filename,
                f"EVM dynamic ABI parameter needs a pointer local: {local.type_}",
            )
        data_label = self._new_label("abi_copy")
        end_label = self._new_label("abi_copy_end")

        self._asm.push(4 + index * _WORD_BYTES)
        self._asm.op("CALLDATALOAD")
        self._asm.op("DUP1")
        self._asm.push(head_size)
        self._asm.op("LT")
        self._emit_revert_if_true("abi_bad_dynamic_offset")
        self._asm.op("DUP1")
        self._asm.push(_WORD_BYTES)
        self._asm.op("MOD")
        self._asm.op("ISZERO")
        self._asm.op("ISZERO")
        self._emit_revert_if_true("abi_bad_dynamic_offset")
        self._asm.push(4)
        self._asm.op("ADD")
        self._store_mem_word(_SCRATCH_DYNAMIC_OFFSET)

        self._load_mem_word(_SCRATCH_DYNAMIC_OFFSET)
        self._asm.push(_WORD_BYTES)
        self._asm.op("ADD")
        self._emit_require_calldata_size_from_stack()

        self._load_mem_word(_SCRATCH_DYNAMIC_OFFSET)
        self._asm.op("CALLDATALOAD")
        self._store_mem_word(_SCRATCH_LENGTH)

        self._load_mem_word(_SCRATCH_DYNAMIC_OFFSET)
        self._asm.push(_WORD_BYTES)
        self._asm.op("ADD")
        self._load_mem_word(_SCRATCH_LENGTH)
        self._asm.push(_WORD_BYTES)
        self._asm.op("MUL")
        self._asm.op("ADD")
        self._emit_require_calldata_size_from_stack()

        self._load_mem_word(_SCRATCH_FREE_PTR)
        self._store_local(local)

        self._asm.push(0)
        self._store_mem_word(_SCRATCH_INDEX)
        self._asm.label(data_label)
        self._load_mem_word(_SCRATCH_INDEX)
        self._load_mem_word(_SCRATCH_LENGTH)
        self._asm.op("LT")
        self._asm.op("ISZERO")
        self._asm.push_label(end_label)
        self._asm.op("JUMPI")

        self._load_mem_word(_SCRATCH_DYNAMIC_OFFSET)
        self._asm.push(_WORD_BYTES)
        self._asm.op("ADD")
        self._load_mem_word(_SCRATCH_INDEX)
        self._asm.push(_WORD_BYTES)
        self._asm.op("MUL")
        self._asm.op("ADD")
        self._asm.op("CALLDATALOAD")
        self._emit_integer_conversion_to_type(element_type)
        self._load_local(local)
        self._load_mem_word(_SCRATCH_INDEX)
        self._asm.push(_WORD_BYTES)
        self._asm.op("MUL")
        self._asm.op("ADD")
        self._asm.op("MSTORE")

        self._load_mem_word(_SCRATCH_INDEX)
        self._asm.push(1)
        self._asm.op("ADD")
        self._store_mem_word(_SCRATCH_INDEX)
        self._asm.push_label(data_label)
        self._asm.op("JUMP")
        self._asm.label(end_label)

        self._load_local(local)
        self._load_mem_word(_SCRATCH_LENGTH)
        self._asm.push(_WORD_BYTES)
        self._asm.op("MUL")
        self._asm.op("ADD")
        self._store_mem_word(_SCRATCH_FREE_PTR)

    def _emit_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, CompoundStmt):
            for inner in stmt.statements:
                self._emit_stmt(inner)
            return
        if isinstance(stmt, DeclGroupStmt):
            for declaration in stmt.declarations:
                self._emit_stmt(declaration)
            return
        if isinstance(stmt, NullStmt | StaticAssertDecl | TypedefDecl):
            return
        if isinstance(stmt, DeclStmt):
            self._emit_decl(stmt)
            return
        if isinstance(stmt, LabelStmt):
            self._asm.label(self._user_label(stmt.name))
            self._emit_stmt(stmt.body)
            return
        if isinstance(stmt, GotoStmt):
            self._asm.push_label(self._user_label(stmt.label))
            self._asm.op("JUMP")
            return
        if isinstance(stmt, IndirectGotoStmt):
            self._emit_expr(stmt.target)
            self._asm.op("JUMP")
            return
        if isinstance(stmt, ExprStmt):
            self._emit_expr(stmt.expr)
            if not self._expr_is_void(stmt.expr):
                self._asm.op("POP")
            return
        if isinstance(stmt, ReturnStmt):
            self._emit_return(stmt)
            return
        if isinstance(stmt, IfStmt):
            self._emit_if(stmt)
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
        if isinstance(stmt, WhileStmt):
            self._emit_while(stmt)
            return
        if isinstance(stmt, DoWhileStmt):
            self._emit_do_while(stmt)
            return
        if isinstance(stmt, ForStmt):
            self._emit_for(stmt)
            return
        if isinstance(stmt, BreakStmt):
            if not self._break_stack:
                raise evm_backend_error(self._result.filename, "break not within loop or switch")
            self._asm.push_label(self._break_stack[-1])
            self._asm.op("JUMP")
            return
        if isinstance(stmt, ContinueStmt):
            if not self._continue_stack:
                raise evm_backend_error(self._result.filename, "continue not within loop")
            self._asm.push_label(self._continue_stack[-1])
            self._asm.op("JUMP")
            return
        raise evm_backend_error(
            self._result.filename,
            f"unsupported EVM statement: {type(stmt).__name__}",
        )

    def _emit_decl(self, stmt: DeclStmt) -> None:
        if (
            stmt.name is None
            or stmt.storage_class in {"typedef", "extern"}
            or self._is_function_declaration(stmt)
        ):
            return
        if stmt.storage_class == "static":
            return
        declared_type = self._lookup_local_type(stmt)
        local = self._alloc_local(stmt.name, declared_type)
        if stmt.init is None:
            if self._is_word_value_type(declared_type):
                self._asm.push(0)
                self._store_local(local)
            return
        elif isinstance(stmt.init, StringLiteral) and declared_type.is_array():
            self._emit_string_literal_to_local(local, stmt.init)
            return
        elif isinstance(stmt.init, InitList):
            self._emit_local_init_list(local, stmt.init)
            return
        else:
            if not self._is_word_value_type(declared_type):
                if self._is_record_type(declared_type):
                    self._emit_aggregate_copy_to_memory(
                        local.offset,
                        declared_type,
                        stmt.init,
                        "EVM aggregate initializer type mismatch",
                    )
                    return
                raise evm_backend_error(
                    self._result.filename,
                    f"EVM scalar initializer cannot initialize {declared_type}",
                )
            self._emit_expr(stmt.init)
            self._emit_integer_conversion_to_type(declared_type)
            self._store_local(local)

    def _emit_local_init_list(self, local: _Local, init: InitList) -> None:
        self._emit_init_list_to_memory(local.offset, local.type_, init)

    def _emit_init_list_to_memory(self, offset: int, type_: Type, init: InitList) -> None:
        self._zero_memory_object(offset, type_)
        if type_.is_array():
            self._emit_array_init_list_to_memory(offset, type_, init)
            return
        if self._is_record_type(type_):
            self._emit_record_init_list_to_memory(offset, type_, init)
            return
        if self._is_word_value_type(type_):
            if len(init.items) != 1:
                raise evm_backend_error(
                    self._result.filename,
                    "EVM scalar initializer list requires one element",
                )
            self._emit_initializer_to_memory(offset, type_, init.items[0].initializer)
            return
        raise evm_backend_error(
            self._result.filename,
            f"unsupported EVM initializer list target: {type_}",
        )

    def _emit_array_init_list_to_memory(self, offset: int, type_: Type, init: InitList) -> None:
        element_type = type_.element_type()
        assert element_type is not None
        length = type_.declarator_ops[0][1]
        if not isinstance(length, int) or length <= 0:
            raise evm_backend_error(
                self._result.filename,
                f"EVM initializer list needs a complete array type: {type_}",
            )
        if len(init.items) > length:
            positional_count = sum(1 for item in init.items if not item.designators)
            if positional_count > length:
                raise evm_backend_error(self._result.filename, "EVM array initializer too long")
        stride = self._memory_stride_bytes(element_type)
        next_index = 0
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                for target_offset, target_type, target_bit_width in self._memory_designator_targets(
                    offset,
                    type_,
                    item.designators,
                ):
                    self._emit_initializer_to_memory(
                        target_offset,
                        target_type,
                        item.initializer,
                        target_bit_width,
                    )
                next_index = self._next_array_initializer_index(kind, value, length)
                continue
            if next_index >= length:
                raise evm_backend_error(self._result.filename, "EVM array initializer too long")
            self._emit_initializer_to_memory(
                offset + next_index * stride,
                element_type,
                item.initializer,
            )
            next_index += 1

    def _emit_record_init_list_to_memory(self, offset: int, type_: Type, init: InitList) -> None:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            raise evm_backend_error(self._result.filename, f"unknown EVM record type: {type_}")
        next_member = 0
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind != "member" or not isinstance(value, str):
                    raise evm_backend_error(
                        self._result.filename,
                        "EVM record initializer designator must use member",
                    )
                member_index = self._record_member_index(type_, value)
                for target_offset, target_type, target_bit_width in self._memory_designator_targets(
                    offset,
                    type_,
                    item.designators,
                ):
                    self._emit_initializer_to_memory(
                        target_offset,
                        target_type,
                        item.initializer,
                        target_bit_width,
                    )
                next_member = member_index + 1
                continue
            next_member = self._next_record_initializer_member_index(members, next_member)
            if next_member >= len(members):
                raise evm_backend_error(self._result.filename, "EVM record initializer too long")
            member = members[next_member]
            if (
                member.name is None
                and not self._is_anonymous_record_member(member)
                and not self._is_unnamed_bit_field(member)
            ):
                raise evm_backend_error(
                    self._result.filename,
                    "EVM target does not support anonymous storage members",
                )
            member_slot_offset = self._record_member_slot_offset_by_index(type_, next_member)
            self._emit_initializer_to_memory(
                offset + member_slot_offset * _WORD_BYTES,
                member.type_,
                item.initializer,
                member.bit_width,
            )
            next_member += 1

    def _emit_initializer_to_memory(
        self,
        offset: int,
        type_: Type,
        init: Expr | InitList,
        bit_width: int | None = None,
    ) -> None:
        if isinstance(init, InitList):
            self._emit_init_list_to_memory(offset, type_, init)
            return
        if not self._is_word_value_type(type_):
            raise evm_backend_error(
                self._result.filename,
                f"EVM aggregate initializer for {type_} needs braces",
            )
        self._emit_expr(init)
        self._emit_integer_conversion_to_type(type_)
        if bit_width is not None:
            self._emit_bit_field_truncation(bit_width)
        self._asm.push(offset)
        self._asm.op("MSTORE")

    def _zero_memory_object(self, offset: int, type_: Type) -> None:
        for slot_index in range(self._memory_slots_for_type(type_)):
            self._asm.push(0)
            self._asm.push(offset + slot_index * _WORD_BYTES)
            self._asm.op("MSTORE")

    def _memory_designator_targets(
        self,
        offset: int,
        type_: Type,
        designators: tuple[tuple[str, Expr | str | DesignatorRange], ...],
    ) -> tuple[tuple[int, Type, int | None], ...]:
        if not designators:
            return ((offset, type_, None),)
        kind, value = designators[0]
        rest = designators[1:]
        if kind == "index":
            if not type_.is_array() or not isinstance(value, Expr):
                raise evm_backend_error(
                    self._result.filename,
                    "EVM array initializer designator must use index",
                )
            element_type = type_.element_type()
            assert element_type is not None
            index = self._eval_initializer_designator_index(value)
            self._check_array_initializer_index(type_, index)
            stride = self._memory_stride_bytes(element_type)
            return self._memory_designator_targets(offset + index * stride, element_type, rest)
        if kind == "range":
            if not type_.is_array() or not isinstance(value, DesignatorRange):
                raise evm_backend_error(
                    self._result.filename,
                    "EVM array initializer designator must use index",
                )
            element_type = type_.element_type()
            assert element_type is not None
            low, high = self._eval_initializer_designator_range(type_, value)
            stride = self._memory_stride_bytes(element_type)
            targets: list[tuple[int, Type, int | None]] = []
            for index in range(low, high + 1):
                targets.extend(
                    self._memory_designator_targets(
                        offset + index * stride,
                        element_type,
                        rest,
                    )
                )
            return tuple(targets)
        if kind == "member" and isinstance(value, str):
            member_access = self._record_member_access(type_, value)
            if member_access.bit_width is not None and rest:
                raise evm_backend_error(
                    self._result.filename,
                    "EVM bit-field initializer designator cannot have subdesignators",
                )
            target_offset = offset + member_access.slot_offset * _WORD_BYTES
            if not rest:
                return ((target_offset, member_access.type_, member_access.bit_width),)
            return self._memory_designator_targets(
                target_offset,
                member_access.type_,
                rest,
            )
        raise evm_backend_error(
            self._result.filename,
            "EVM initializer designator does not match aggregate type",
        )

    def _storage_designator_targets(
        self,
        slot_offset: int,
        type_: Type,
        designators: tuple[tuple[str, Expr | str | DesignatorRange], ...],
    ) -> tuple[tuple[int, Type, int | None], ...]:
        if not designators:
            return ((slot_offset, type_, None),)
        kind, value = designators[0]
        rest = designators[1:]
        if kind == "index":
            if not type_.is_array() or not isinstance(value, Expr):
                raise evm_backend_error(
                    self._result.filename,
                    "EVM storage array initializer designator must use index",
                )
            element_type = type_.element_type()
            assert element_type is not None
            index = self._eval_initializer_designator_index(value)
            self._check_array_initializer_index(type_, index)
            stride = self._storage_slots_for_type(element_type)
            return self._storage_designator_targets(
                slot_offset + index * stride,
                element_type,
                rest,
            )
        if kind == "range":
            if not type_.is_array() or not isinstance(value, DesignatorRange):
                raise evm_backend_error(
                    self._result.filename,
                    "EVM storage array initializer designator must use index",
                )
            element_type = type_.element_type()
            assert element_type is not None
            low, high = self._eval_initializer_designator_range(type_, value)
            stride = self._storage_slots_for_type(element_type)
            targets: list[tuple[int, Type, int | None]] = []
            for index in range(low, high + 1):
                targets.extend(
                    self._storage_designator_targets(
                        slot_offset + index * stride,
                        element_type,
                        rest,
                    )
                )
            return tuple(targets)
        if kind == "member" and isinstance(value, str):
            member_access = self._record_member_access(type_, value)
            if member_access.bit_width is not None and rest:
                raise evm_backend_error(
                    self._result.filename,
                    "EVM storage bit-field initializer designator cannot have subdesignators",
                )
            target_offset = slot_offset + member_access.slot_offset
            if not rest:
                return ((target_offset, member_access.type_, member_access.bit_width),)
            return self._storage_designator_targets(
                target_offset,
                member_access.type_,
                rest,
            )
        raise evm_backend_error(
            self._result.filename,
            "EVM storage initializer designator does not match aggregate type",
        )

    def _eval_initializer_designator_index(self, expr: Expr) -> int:
        value = self._eval_const_expr(expr)
        if value is None:
            raise evm_backend_error(
                self._result.filename,
                "EVM initializer designator index must be constant",
            )
        return value

    def _eval_initializer_designator_range(
        self,
        type_: Type,
        designator: DesignatorRange,
    ) -> tuple[int, int]:
        low = self._eval_initializer_designator_index(designator.low)
        high = self._eval_initializer_designator_index(designator.high)
        if low > high:
            raise evm_backend_error(self._result.filename, "EVM initializer range is empty")
        self._check_array_initializer_index(type_, low)
        self._check_array_initializer_index(type_, high)
        return low, high

    def _check_array_initializer_index(self, type_: Type, index: int) -> None:
        length = type_.declarator_ops[0][1] if type_.declarator_ops else None
        if not isinstance(length, int) or length <= 0:
            raise evm_backend_error(
                self._result.filename,
                f"EVM initializer needs a complete array type: {type_}",
            )
        if index < 0 or index >= length:
            raise evm_backend_error(
                self._result.filename,
                "EVM initializer index out of range",
            )

    def _next_array_initializer_index(
        self,
        kind: str,
        value: Expr | str | DesignatorRange,
        length: int,
    ) -> int:
        if kind == "index" and isinstance(value, Expr):
            index = self._eval_initializer_designator_index(value)
            if index < 0 or index >= length:
                raise evm_backend_error(
                    self._result.filename,
                    "EVM initializer index out of range",
                )
            return index + 1
        if kind == "range" and isinstance(value, DesignatorRange):
            high = self._eval_initializer_designator_index(value.high)
            if high < 0 or high >= length:
                raise evm_backend_error(
                    self._result.filename,
                    "EVM initializer index out of range",
                )
            return high + 1
        raise evm_backend_error(
            self._result.filename,
            "EVM array initializer designator must use index",
        )

    def _emit_string_literal_to_local(self, local: _Local, expr: StringLiteral) -> None:
        if not local.type_.is_array():
            raise evm_backend_error(
                self._result.filename,
                f"EVM string literal cannot initialize {local.type_}",
            )
        element_type = local.type_.element_type()
        if element_type is None or not self._is_char_object_type(element_type):
            raise evm_backend_error(
                self._result.filename,
                f"EVM string literal needs a char array target: {local.type_}",
            )
        length = local.type_.declarator_ops[0][1]
        if not isinstance(length, int) or length <= 0:
            raise evm_backend_error(
                self._result.filename,
                f"EVM string literal needs a complete array target: {local.type_}",
            )
        units = self._string_literal_units(expr)
        if len(units) > length:
            raise evm_backend_error(
                self._result.filename,
                "EVM string literal initializer too long",
            )
        for index in range(length):
            self._asm.push(units[index] if index < len(units) else 0)
            self._emit_integer_conversion_to_type(element_type)
            self._asm.push(local.offset + index * self._memory_stride_bytes(element_type))
            self._asm.op("MSTORE")

    def _emit_return(self, stmt: ReturnStmt) -> None:
        if self._return_mode == "internal":
            if stmt.value is not None:
                if self._func_sym is not None and self._is_record_type(self._func_sym.return_type):
                    if self._current_layout is None:
                        raise evm_backend_error(
                            self._result.filename,
                            "missing EVM internal return layout",
                        )
                    self._emit_aggregate_copy_to_memory(
                        self._current_layout.return_value_offset,
                        self._func_sym.return_type,
                        stmt.value,
                        "EVM aggregate return type mismatch",
                    )
                    self._jump_to_internal_return_pc()
                    return
                self._emit_expr(stmt.value)
                if self._func_sym is not None:
                    self._emit_integer_conversion_to_type(self._func_sym.return_type)
                self._store_internal_return_value()
            self._jump_to_internal_return_pc()
            return
        if stmt.value is None:
            self._asm.op("STOP")
            return
        self._emit_expr(stmt.value)
        if self._func_sym is not None:
            self._emit_integer_conversion_to_type(self._func_sym.return_type)
        self._asm.push(0)
        self._asm.op("MSTORE")
        self._emit_return_word()

    def _emit_return_word(self) -> None:
        self._asm.push(32)
        self._asm.push(0)
        self._asm.op("RETURN")

    def _store_internal_return_value(self) -> None:
        if self._current_layout is None:
            raise evm_backend_error(self._result.filename, "missing EVM internal return layout")
        self._store_mem_word(self._current_layout.return_value_offset)

    def _jump_to_internal_return_pc(self) -> None:
        if self._current_layout is None:
            raise evm_backend_error(self._result.filename, "missing EVM internal return layout")
        self._load_mem_word(self._current_layout.return_pc_offset)
        self._asm.op("JUMP")

    def _emit_if(self, stmt: IfStmt) -> None:
        else_label = self._new_label("if_else")
        end_label = self._new_label("if_end")
        self._emit_expr(stmt.condition)
        self._asm.op("ISZERO")
        self._asm.push_label(else_label if stmt.else_body is not None else end_label)
        self._asm.op("JUMPI")
        self._emit_stmt(stmt.then_body)
        self._asm.push_label(end_label)
        self._asm.op("JUMP")
        if stmt.else_body is not None:
            self._asm.label(else_label)
            self._emit_stmt(stmt.else_body)
        self._asm.label(end_label)

    def _emit_switch(self, stmt: SwitchStmt) -> None:
        cases, default_stmt = self._collect_switch_cases(stmt.body)
        labels = {
            self._eval_case_value(case.value): self._new_label("switch_case") for case in cases
        }
        default_label = self._new_label("switch_default") if default_stmt is not None else None
        end_label = self._new_label("switch_end")

        self._emit_expr(stmt.condition)
        self._store_mem_word(_SCRATCH_INDEX)
        for value, label in labels.items():
            self._load_mem_word(_SCRATCH_INDEX)
            self._asm.push(value)
            self._asm.op("EQ")
            self._asm.push_label(label)
            self._asm.op("JUMPI")
        self._asm.push_label(default_label or end_label)
        self._asm.op("JUMP")

        self._switch_stack.append((labels, default_label))
        self._break_stack.append(end_label)
        self._emit_stmt(stmt.body)
        self._break_stack.pop()
        self._switch_stack.pop()
        self._asm.label(end_label)

    def _collect_switch_cases(self, stmt: Stmt) -> tuple[list[CaseStmt], DefaultStmt | None]:
        cases: list[CaseStmt] = []
        default_stmt_ref: list[DefaultStmt | None] = [None]

        def collect(node: Stmt) -> None:
            if isinstance(node, SwitchStmt):
                return
            if isinstance(node, CaseStmt):
                cases.append(node)
                collect(node.body)
                return
            if isinstance(node, DefaultStmt):
                default_stmt_ref[0] = node
                collect(node.body)
                return
            if isinstance(node, CompoundStmt):
                for child in node.statements:
                    collect(child)

        collect(stmt)
        return cases, default_stmt_ref[0]

    def _emit_case(self, stmt: CaseStmt) -> None:
        if not self._switch_stack:
            raise evm_backend_error(self._result.filename, "case not within switch")
        labels, _ = self._switch_stack[-1]
        self._asm.label(labels[self._eval_case_value(stmt.value)])
        self._emit_stmt(stmt.body)

    def _emit_default(self, stmt: DefaultStmt) -> None:
        if not self._switch_stack:
            raise evm_backend_error(self._result.filename, "default not within switch")
        _, default_label = self._switch_stack[-1]
        if default_label is None:
            raise evm_backend_error(self._result.filename, "default label missing")
        self._asm.label(default_label)
        self._emit_stmt(stmt.body)

    def _emit_while(self, stmt: WhileStmt) -> None:
        test_label = self._new_label("while_test")
        end_label = self._new_label("while_end")
        self._asm.label(test_label)
        self._emit_expr(stmt.condition)
        self._asm.op("ISZERO")
        self._asm.push_label(end_label)
        self._asm.op("JUMPI")
        self._break_stack.append(end_label)
        self._continue_stack.append(test_label)
        self._emit_stmt(stmt.body)
        self._continue_stack.pop()
        self._break_stack.pop()
        self._asm.push_label(test_label)
        self._asm.op("JUMP")
        self._asm.label(end_label)

    def _emit_do_while(self, stmt: DoWhileStmt) -> None:
        body_label = self._new_label("do_body")
        test_label = self._new_label("do_test")
        end_label = self._new_label("do_end")
        self._asm.label(body_label)
        self._break_stack.append(end_label)
        self._continue_stack.append(test_label)
        self._emit_stmt(stmt.body)
        self._continue_stack.pop()
        self._break_stack.pop()
        self._asm.label(test_label)
        self._emit_expr(stmt.condition)
        self._asm.op("ISZERO")
        self._asm.push_label(end_label)
        self._asm.op("JUMPI")
        self._asm.push_label(body_label)
        self._asm.op("JUMP")
        self._asm.label(end_label)

    def _emit_for(self, stmt: ForStmt) -> None:
        test_label = self._new_label("for_test")
        post_label = self._new_label("for_post")
        end_label = self._new_label("for_end")
        if isinstance(stmt.init, Stmt):
            self._emit_stmt(stmt.init)
        elif stmt.init is not None:
            self._emit_expr(stmt.init)
            if not self._expr_is_void(stmt.init):
                self._asm.op("POP")
        self._asm.label(test_label)
        if stmt.condition is not None:
            self._emit_expr(stmt.condition)
            self._asm.op("ISZERO")
            self._asm.push_label(end_label)
            self._asm.op("JUMPI")
        self._break_stack.append(end_label)
        self._continue_stack.append(post_label)
        self._emit_stmt(stmt.body)
        self._continue_stack.pop()
        self._break_stack.pop()
        self._asm.label(post_label)
        if stmt.post is not None:
            self._emit_expr(stmt.post)
            if not self._expr_is_void(stmt.post):
                self._asm.op("POP")
        self._asm.push_label(test_label)
        self._asm.op("JUMP")
        self._asm.label(end_label)

    def _emit_expr(self, expr: Expr) -> None:
        if isinstance(expr, IntLiteral):
            self._asm.push(self._parse_int(expr.value))
            return
        if isinstance(expr, CharLiteral):
            self._asm.push(self._char_value(expr.value))
            return
        if isinstance(expr, LabelAddressExpr):
            self._asm.push_label(self._user_label(expr.label))
            return
        if isinstance(expr, StringLiteral):
            self._emit_string_literal(expr)
            return
        if isinstance(expr, SizeofExpr):
            self._asm.push(self._sizeof_expr(expr))
            return
        if isinstance(expr, AlignofExpr):
            self._asm.push(self._alignof_expr(expr))
            return
        if isinstance(expr, BuiltinOffsetofExpr):
            self._asm.push(self._offsetof_value(expr))
            return
        if isinstance(expr, BuiltinTypesCompatExpr):
            self._asm.push(self._types_compatible_value(expr))
            return
        if isinstance(expr, GenericExpr):
            self._emit_generic_expr(expr)
            return
        if isinstance(expr, StatementExpr):
            self._emit_statement_expr(expr)
            return
        if isinstance(expr, CompoundLiteralExpr):
            self._emit_compound_literal(expr)
            return
        if isinstance(expr, ConditionalExpr):
            self._emit_conditional_expr(expr)
            return
        if isinstance(expr, CommaExpr):
            self._emit_comma_expr(expr)
            return
        if isinstance(expr, Identifier):
            local = self._locals.get(expr.name)
            if local is not None:
                if local.type_.is_array() or self._is_record_type(local.type_):
                    self._asm.push(local.offset)
                    return
                self._load_local(local)
                return
            enum_value = self._lookup_enum_constant(expr.name)
            if enum_value is not None:
                self._asm.push(enum_value)
                return
            static_local = self._lookup_static_local(expr.name)
            if static_local is not None:
                if not self._is_word_value_type(static_local.type_):
                    raise evm_backend_error(
                        self._result.filename,
                        f"EVM aggregate static object needs member access: {expr.name}",
                    )
                self._load_storage_global(static_local)
                return
            storage = self._storage_globals.get(expr.name)
            if storage is not None:
                if not self._is_word_value_type(storage.type_):
                    raise evm_backend_error(
                        self._result.filename,
                        f"EVM aggregate storage object needs member access: {expr.name}",
                    )
                self._load_storage_global(storage)
                return
            function = self._functions_by_name.get(expr.name)
            if function is not None:
                self._asm.push_label(self._internal_function_label(function))
                return
            raise evm_backend_error(
                self._result.filename,
                f"unknown EVM identifier: {expr.name}",
            )
        if isinstance(expr, BinaryExpr):
            self._emit_binary(expr)
            return
        if isinstance(expr, AssignExpr):
            self._emit_assign(expr)
            return
        if isinstance(expr, UnaryExpr):
            self._emit_unary(expr)
            return
        if isinstance(expr, UpdateExpr):
            self._emit_update(expr)
            return
        if isinstance(expr, SubscriptExpr | MemberExpr):
            self._emit_lvalue_load(expr)
            return
        if isinstance(expr, CastExpr):
            self._emit_cast(expr)
            return
        if isinstance(expr, CallExpr):
            self._emit_call(expr)
            return
        raise evm_backend_error(
            self._result.filename,
            f"unsupported EVM expression: {type(expr).__name__}",
        )

    def _emit_binary(self, expr: BinaryExpr) -> None:
        if expr.op in {"&&", "||"}:
            self._emit_logical_binary(expr)
            return
        if self._emit_pointer_binary(expr):
            return
        self._emit_expr(expr.left)
        self._emit_expr(expr.right)
        op = expr.op
        if op == "+":
            self._asm.op("ADD")
        elif op == "-":
            self._asm.op("SUB")
        elif op == "*":
            self._asm.op("MUL")
        elif op == "/":
            self._asm.op("SDIV" if self._binary_uses_signed_opcode(expr) else "DIV")
        elif op == "%":
            self._asm.op("SMOD" if self._binary_uses_signed_opcode(expr) else "MOD")
        elif op == "==":
            self._asm.op("EQ")
        elif op == "!=":
            self._asm.op("EQ")
            self._asm.op("ISZERO")
        elif op == "<":
            self._asm.op("SLT" if self._binary_uses_signed_opcode(expr) else "LT")
        elif op == ">":
            self._asm.op("SGT" if self._binary_uses_signed_opcode(expr) else "GT")
        elif op == "<=":
            self._asm.op("SGT" if self._binary_uses_signed_opcode(expr) else "GT")
            self._asm.op("ISZERO")
        elif op == ">=":
            self._asm.op("SLT" if self._binary_uses_signed_opcode(expr) else "LT")
            self._asm.op("ISZERO")
        elif op == "&":
            self._asm.op("AND")
        elif op == "|":
            self._asm.op("OR")
        elif op == "^":
            self._asm.op("XOR")
        elif op == "<<":
            self._asm.op("SHL")
        elif op == ">>":
            self._asm.op("SAR" if self._shift_uses_signed_opcode(expr) else "SHR")
        else:
            raise evm_backend_error(self._result.filename, f"unsupported EVM binary operator: {op}")
        if op in {"+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>"}:
            self._emit_integer_conversion_to_expr_type(expr)

    def _binary_uses_signed_opcode(self, expr: BinaryExpr) -> bool:
        left_type = self._decay_array_type(self._type_map.get(expr.left))
        right_type = self._decay_array_type(self._type_map.get(expr.right))
        if left_type is None or right_type is None:
            return False
        common_type = usual_arithmetic_conversion(left_type, right_type)
        return common_type is not None and is_signed_integer_type(common_type)

    def _shift_uses_signed_opcode(self, expr: BinaryExpr) -> bool:
        left_type = self._decay_array_type(self._type_map.get(expr.left))
        if left_type is None or not is_integer_type(left_type):
            return False
        return is_signed_integer_type(integer_promotion(left_type))

    def _emit_logical_binary(self, expr: BinaryExpr) -> None:
        end_label = self._new_label("logical_end")
        if expr.op == "&&":
            false_label = self._new_label("logical_false")
            self._emit_expr(expr.left)
            self._asm.op("ISZERO")
            self._asm.push_label(false_label)
            self._asm.op("JUMPI")
            self._emit_expr(expr.right)
            self._normalize_stack_bool()
            self._asm.push_label(end_label)
            self._asm.op("JUMP")
            self._asm.label(false_label)
            self._asm.push(0)
            self._asm.label(end_label)
            return

        true_label = self._new_label("logical_true")
        self._emit_expr(expr.left)
        self._normalize_stack_bool()
        self._asm.push_label(true_label)
        self._asm.op("JUMPI")
        self._emit_expr(expr.right)
        self._normalize_stack_bool()
        self._asm.push_label(end_label)
        self._asm.op("JUMP")
        self._asm.label(true_label)
        self._asm.push(1)
        self._asm.label(end_label)

    def _normalize_stack_bool(self) -> None:
        self._asm.op("ISZERO")
        self._asm.op("ISZERO")

    def _emit_conditional_expr(self, expr: ConditionalExpr) -> None:
        else_label = self._new_label("cond_else")
        end_label = self._new_label("cond_end")
        self._emit_expr(expr.condition)
        self._asm.op("ISZERO")
        self._asm.push_label(else_label)
        self._asm.op("JUMPI")
        self._emit_expr(expr.then_expr)
        self._emit_integer_conversion_to_expr_type(expr)
        self._asm.push_label(end_label)
        self._asm.op("JUMP")
        self._asm.label(else_label)
        self._emit_expr(expr.else_expr)
        self._emit_integer_conversion_to_expr_type(expr)
        self._asm.label(end_label)

    def _emit_comma_expr(self, expr: CommaExpr) -> None:
        self._emit_expr(expr.left)
        if not self._expr_is_void(expr.left):
            self._asm.op("POP")
        self._emit_expr(expr.right)

    def _emit_generic_expr(self, expr: GenericExpr) -> None:
        selected_expr = self._select_generic_expr(expr)
        self._emit_expr(selected_expr)
        self._emit_integer_conversion_to_expr_type(expr)

    def _emit_statement_expr(self, expr: StatementExpr) -> None:
        statements = expr.body.statements
        if not statements:
            return
        for statement in statements[:-1]:
            self._emit_stmt(statement)
        last = statements[-1]
        if isinstance(last, ExprStmt):
            self._emit_expr(last.expr)
            if not self._expr_is_void(last.expr):
                self._emit_integer_conversion_to_expr_type(expr)
            return
        self._emit_stmt(last)

    def _emit_compound_literal(self, expr: CompoundLiteralExpr) -> None:
        local = self._compound_literal_local(expr)
        self._emit_compound_literal_init(local, expr.initializer)
        if local.type_.is_array() or self._is_record_type(local.type_):
            self._asm.push(local.offset)
            return
        if not self._is_word_value_type(local.type_):
            raise evm_backend_error(
                self._result.filename,
                f"EVM cannot load compound literal type: {local.type_}",
            )
        self._load_local(local)

    def _emit_compound_literal_init(self, local: _Local, init: InitList) -> None:
        self._emit_init_list_to_memory(local.offset, local.type_, init)

    def _emit_string_literal(self, expr: StringLiteral) -> None:
        local = self._string_literal_local(expr)
        self._emit_string_literal_to_local(local, expr)
        self._asm.push(local.offset)

    def _emit_pointer_binary(self, expr: BinaryExpr) -> bool:
        if expr.op not in {"+", "-"}:
            return False
        left_type = self._decay_array_type(self._type_map.get(expr.left))
        right_type = self._decay_array_type(self._type_map.get(expr.right))
        left_pointee = None if left_type is None else left_type.pointee()
        right_pointee = None if right_type is None else right_type.pointee()
        if expr.op == "-" and left_pointee is not None and right_pointee is not None:
            stride = self._memory_stride_bytes(left_pointee)
            if stride != self._memory_stride_bytes(right_pointee):
                raise evm_backend_error(
                    self._result.filename,
                    "EVM pointer subtraction needs matching element storage size",
                )
            self._emit_expr(expr.left)
            self._emit_expr(expr.right)
            self._asm.op("SUB")
            self._asm.push(stride)
            self._asm.op("SDIV")
            self._emit_integer_conversion_to_expr_type(expr)
            return True
        if left_pointee is not None and right_pointee is None:
            assert left_type is not None
            self._emit_expr(expr.left)
            self._emit_scaled_integer_expr(expr.right, self._pointer_stride_bytes(left_type))
            self._asm.op("ADD" if expr.op == "+" else "SUB")
            return True
        if expr.op == "+" and right_pointee is not None and left_pointee is None:
            assert right_type is not None
            self._emit_scaled_integer_expr(expr.left, self._pointer_stride_bytes(right_type))
            self._emit_expr(expr.right)
            self._asm.op("ADD")
            return True
        return False

    def _emit_assign(self, expr: AssignExpr) -> None:
        target = self._emit_lvalue_address(expr.target)
        if not self._is_word_value_type(target.type_):
            if expr.op != "=":
                raise evm_backend_error(
                    self._result.filename,
                    f"unsupported EVM aggregate assignment: {expr.op}",
                )
            self._emit_aggregate_assignment(target, expr.value)
            return
        if expr.op == "=":
            self._emit_expr(expr.value)
        elif expr.op in {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}:
            self._asm.op("DUP1")
            self._load_addressed(target)
            if expr.op in {"+=", "-="} and target.type_.pointee() is not None:
                self._emit_scaled_integer_expr(expr.value, self._pointer_stride_bytes(target.type_))
            else:
                self._emit_expr(expr.value)
            self._emit_assignment_operator(expr.op, target.type_)
        else:
            raise evm_backend_error(self._result.filename, f"unsupported EVM assignment: {expr.op}")
        self._emit_integer_conversion_to_type(target.type_)
        self._store_addressed(target)

    def _emit_aggregate_assignment(self, target: _LValue, value: Expr) -> None:
        source = self._emit_lvalue_address(value)
        if self._memory_slots_for_type(source.type_) != self._memory_slots_for_type(target.type_):
            raise evm_backend_error(
                self._result.filename,
                f"EVM aggregate assignment type mismatch: {source.type_} to {target.type_}",
            )
        self._store_mem_word(_SCRATCH_DYNAMIC_OFFSET)
        self._store_mem_word(_SCRATCH_INDEX)
        self._copy_aggregate_slots(target, source)
        self._load_mem_word(_SCRATCH_INDEX)

    def _emit_aggregate_copy_to_memory(
        self,
        target_offset: int,
        target_type: Type,
        value: Expr,
        mismatch_message: str,
    ) -> None:
        source = self._emit_lvalue_address(value)
        if self._memory_slots_for_type(source.type_) != self._memory_slots_for_type(target_type):
            raise evm_backend_error(
                self._result.filename,
                f"{mismatch_message}: {source.type_} to {target_type}",
            )
        self._store_mem_word(_SCRATCH_DYNAMIC_OFFSET)
        self._asm.push(target_offset)
        self._store_mem_word(_SCRATCH_INDEX)
        self._copy_aggregate_slots(_LValue("memory", target_type), source)

    def _emit_aggregate_memory_copy(
        self,
        target_offset: int,
        target_type: Type,
        source_offset: int,
        source_type: Type,
        mismatch_message: str,
    ) -> None:
        if self._memory_slots_for_type(source_type) != self._memory_slots_for_type(target_type):
            raise evm_backend_error(
                self._result.filename,
                f"{mismatch_message}: {source_type} to {target_type}",
            )
        self._asm.push(source_offset)
        self._store_mem_word(_SCRATCH_DYNAMIC_OFFSET)
        self._asm.push(target_offset)
        self._store_mem_word(_SCRATCH_INDEX)
        self._copy_aggregate_slots(_LValue("memory", target_type), _LValue("memory", source_type))

    def _copy_aggregate_slots(self, target: _LValue, source: _LValue) -> None:
        for slot_index in range(self._memory_slots_for_type(target.type_)):
            self._emit_slot_address(source.space, _SCRATCH_DYNAMIC_OFFSET, slot_index)
            self._asm.op("MLOAD" if source.space == "memory" else "SLOAD")
            self._emit_slot_address(target.space, _SCRATCH_INDEX, slot_index)
            self._asm.op("MSTORE" if target.space == "memory" else "SSTORE")

    def _emit_slot_address(self, space: str, base_offset: int, slot_index: int) -> None:
        self._load_mem_word(base_offset)
        unit = _WORD_BYTES if space == "memory" else 1
        offset = slot_index * unit
        if offset:
            self._asm.push(offset)
            self._asm.op("ADD")

    def _emit_assignment_operator(self, op: str, target_type: Type) -> None:
        if op == "+=":
            self._asm.op("ADD")
        elif op == "-=":
            self._asm.op("SUB")
        elif op == "*=":
            self._asm.op("MUL")
        elif op == "/=":
            self._asm.op("SDIV" if is_signed_integer_type(target_type) else "DIV")
        elif op == "%=":
            self._asm.op("SMOD" if is_signed_integer_type(target_type) else "MOD")
        elif op == "&=":
            self._asm.op("AND")
        elif op == "|=":
            self._asm.op("OR")
        elif op == "^=":
            self._asm.op("XOR")
        elif op == "<<=":
            self._asm.op("SHL")
        elif op == ">>=":
            self._asm.op("SAR" if is_signed_integer_type(target_type) else "SHR")
        else:
            raise evm_backend_error(self._result.filename, f"unsupported EVM assignment: {op}")

    def _emit_unary(self, expr: UnaryExpr) -> None:
        if expr.op == "+":
            self._emit_expr(expr.operand)
            self._emit_integer_conversion_to_expr_type(expr)
            return
        if expr.op == "-":
            self._asm.push(0)
            self._emit_expr(expr.operand)
            self._asm.op("SUB")
            self._emit_integer_conversion_to_expr_type(expr)
            return
        if expr.op == "!":
            self._emit_expr(expr.operand)
            self._asm.op("ISZERO")
            return
        if expr.op == "~":
            self._emit_expr(expr.operand)
            self._asm.op("NOT")
            self._emit_integer_conversion_to_expr_type(expr)
            return
        if expr.op == "&":
            if isinstance(expr.operand, Identifier):
                function = self._functions_by_name.get(expr.operand.name)
                if function is not None:
                    self._asm.push_label(self._internal_function_label(function))
                    return
            lvalue = self._emit_lvalue_address(expr.operand)
            if lvalue.space != "memory":
                raise evm_backend_error(
                    self._result.filename,
                    "EVM target only supports addresses of memory objects",
                )
            return
        if expr.op == "*":
            self._emit_lvalue_load(expr)
            return
        raise evm_backend_error(self._result.filename, f"unsupported EVM unary operator: {expr.op}")

    def _emit_update(self, expr: UpdateExpr) -> None:
        target = self._emit_lvalue_address(expr.operand)
        self._asm.op("DUP1")
        self._load_addressed(target)
        stride = (
            self._pointer_stride_bytes(target.type_) if target.type_.pointee() is not None else 1
        )
        if expr.is_postfix:
            self._asm.op("DUP1")
        self._asm.push(stride)
        if expr.op == "++":
            self._asm.op("ADD")
        elif expr.op == "--":
            self._asm.op("SUB")
        else:
            raise evm_backend_error(self._result.filename, f"unsupported EVM update: {expr.op}")
        self._emit_integer_conversion_to_type(target.type_)
        if target.bit_width is not None:
            self._emit_bit_field_truncation(target.bit_width)
        if expr.is_postfix:
            self._asm.op("SWAP1")
            self._asm.op("SWAP2")
            self._store_addressed_without_result(target)
            return
        self._store_addressed(target)

    def _emit_cast(self, expr: CastExpr) -> None:
        target_type = self._type_map.get(expr)
        source_type = self._type_map.get(expr.expr)
        self._emit_expr(expr.expr)
        if target_type is None:
            return
        if self._is_void_type(target_type):
            if source_type is None or not self._is_void_type(source_type):
                self._asm.op("POP")
            return
        self._emit_integer_conversion_to_type(target_type)

    def _emit_integer_conversion_to_expr_type(self, expr: Expr) -> None:
        target_type = self._type_map.get(expr)
        if target_type is not None:
            self._emit_integer_conversion_to_type(target_type)

    def _emit_integer_conversion_to_type(self, type_: Type) -> None:
        type_ = unqualified_type(type_)
        if not is_integer_type(type_):
            return
        bits = self._integer_type_bits(type_)
        if bits is None or bits >= 256:
            return
        if self._is_bool_type(type_):
            self._normalize_stack_bool()
            return
        if is_signed_integer_type(type_):
            self._asm.push((bits // 8) - 1)
            self._asm.op("SIGNEXTEND")
            return
        self._asm.push((1 << bits) - 1)
        self._asm.op("AND")

    def _emit_call(self, expr: CallExpr) -> None:
        if self._callable_signature_for_expr(expr.callee) is not None and not (
            isinstance(expr.callee, Identifier)
            and expr.callee.name in self._functions_by_name
            and expr.callee.name not in self._locals
        ):
            self._emit_indirect_function_call(expr)
            return
        if not isinstance(expr.callee, Identifier):
            raise evm_backend_error(
                self._result.filename,
                "EVM target does not support function pointers",
            )
        name = expr.callee.name
        modular_opcode = self._evm_modular_arithmetic_opcode(name)
        if modular_opcode is not None:
            if len(expr.args) != 3:
                raise evm_backend_error(
                    self._result.filename,
                    f"{name} expects three arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op(modular_opcode)
            return
        if name == "__builtin_evm_exp":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_exp expects two arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("EXP")
            return
        if name == "__builtin_evm_byte":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_byte expects two arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("BYTE")
            return
        if name == "__builtin_evm_signextend":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_signextend expects two arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("SIGNEXTEND")
            return
        if name == "__builtin_evm_sload":
            if len(expr.args) != 1:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_sload expects one argument",
                )
            self._emit_expr(expr.args[0])
            self._asm.op("SLOAD")
            return
        if name == "__builtin_evm_sstore":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_sstore expects two arguments",
                )
            self._emit_expr(expr.args[1])
            self._emit_expr(expr.args[0])
            self._asm.op("SSTORE")
            return
        if name == "__builtin_evm_tload":
            if len(expr.args) != 1:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_tload expects one argument",
                )
            self._emit_expr(expr.args[0])
            self._asm.op("TLOAD")
            return
        if name == "__builtin_evm_tstore":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_tstore expects two arguments",
                )
            self._emit_expr(expr.args[1])
            self._emit_expr(expr.args[0])
            self._asm.op("TSTORE")
            return
        if name == "__builtin_evm_caller":
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_caller expects no arguments",
                )
            self._asm.op("CALLER")
            return
        if name == "__builtin_evm_callvalue":
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_callvalue expects no arguments",
                )
            self._asm.op("CALLVALUE")
            return
        environment_opcode = self._evm_environment_opcode(name)
        if environment_opcode is not None:
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    f"{name} expects no arguments",
                )
            self._asm.op(environment_opcode)
            return
        query_opcode = self._evm_unary_query_opcode(name)
        if query_opcode is not None:
            if len(expr.args) != 1:
                raise evm_backend_error(
                    self._result.filename,
                    f"{name} expects one argument",
                )
            self._emit_expr(expr.args[0])
            self._asm.op(query_opcode)
            return
        if name == "__builtin_evm_blobhash":
            if len(expr.args) != 1:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_blobhash expects one argument",
                )
            self._emit_expr(expr.args[0])
            self._asm.op("BLOBHASH")
            return
        if name == "__builtin_evm_calldatasize":
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_calldatasize expects no arguments",
                )
            self._asm.op("CALLDATASIZE")
            return
        if name == "__builtin_evm_calldataload":
            if len(expr.args) != 1:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_calldataload expects one argument",
                )
            self._emit_expr(expr.args[0])
            self._asm.op("CALLDATALOAD")
            return
        if name == "__builtin_evm_calldatacopy":
            if len(expr.args) != 3:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_calldatacopy expects three arguments",
                )
            self._emit_expr(expr.args[2])
            self._emit_expr(expr.args[1])
            self._emit_expr(expr.args[0])
            self._asm.op("CALLDATACOPY")
            return
        if name == "__builtin_evm_codesize":
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_codesize expects no arguments",
                )
            self._asm.op("CODESIZE")
            return
        if name == "__builtin_evm_codecopy":
            if len(expr.args) != 3:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_codecopy expects three arguments",
                )
            self._emit_expr(expr.args[2])
            self._emit_expr(expr.args[1])
            self._emit_expr(expr.args[0])
            self._asm.op("CODECOPY")
            return
        if name == "__builtin_evm_mload":
            if len(expr.args) != 1:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_mload expects one argument",
                )
            self._emit_expr(expr.args[0])
            self._asm.op("MLOAD")
            return
        if name == "__builtin_evm_mstore":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_mstore expects two arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("MSTORE")
            return
        if name == "__builtin_evm_mcopy":
            if len(expr.args) != 3:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_mcopy expects three arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("MCOPY")
            return
        if name == "__builtin_evm_mstore8":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_mstore8 expects two arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("MSTORE8")
            return
        if name == "__builtin_evm_msize":
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_msize expects no arguments",
                )
            self._asm.op("MSIZE")
            return
        if name == "__builtin_evm_pc":
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_pc expects no arguments",
                )
            self._asm.op("PC")
            return
        if name == "__builtin_evm_extcodecopy":
            if len(expr.args) != 4:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_extcodecopy expects four arguments",
                )
            self._emit_expr(expr.args[3])
            self._emit_expr(expr.args[2])
            self._emit_expr(expr.args[1])
            self._emit_expr(expr.args[0])
            self._asm.op("EXTCODECOPY")
            return
        if name == "__builtin_evm_returndatasize":
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_returndatasize expects no arguments",
                )
            self._asm.op("RETURNDATASIZE")
            return
        if name == "__builtin_evm_returndatacopy":
            if len(expr.args) != 3:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_returndatacopy expects three arguments",
                )
            self._emit_expr(expr.args[2])
            self._emit_expr(expr.args[1])
            self._emit_expr(expr.args[0])
            self._asm.op("RETURNDATACOPY")
            return
        if name == "__builtin_evm_create":
            if len(expr.args) != 3:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_create expects three arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("CREATE")
            return
        if name == "__builtin_evm_create2":
            if len(expr.args) != 4:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_create2 expects four arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("CREATE2")
            return
        if name == "__builtin_evm_call":
            if len(expr.args) != 7:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_call expects seven arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("CALL")
            return
        if name == "__builtin_evm_callcode":
            if len(expr.args) != 7:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_callcode expects seven arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("CALLCODE")
            return
        if name == "__builtin_evm_staticcall":
            if len(expr.args) != 6:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_staticcall expects six arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("STATICCALL")
            return
        if name == "__builtin_evm_delegatecall":
            if len(expr.args) != 6:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_delegatecall expects six arguments",
                )
            for arg in reversed(expr.args):
                self._emit_expr(arg)
            self._asm.op("DELEGATECALL")
            return
        if name == "__builtin_evm_revert":
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_revert expects no arguments",
                )
            self._asm.push(0)
            self._asm.push(0)
            self._asm.op("REVERT")
            return
        if name == "__builtin_evm_revert_data":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_revert_data expects two arguments",
                )
            self._emit_expr(expr.args[1])
            self._emit_expr(expr.args[0])
            self._asm.op("REVERT")
            return
        if name == "__builtin_evm_return":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_return expects two arguments",
                )
            self._emit_expr(expr.args[1])
            self._emit_expr(expr.args[0])
            self._asm.op("RETURN")
            return
        if name == "__builtin_evm_stop":
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_stop expects no arguments",
                )
            self._asm.op("STOP")
            return
        if name == "__builtin_evm_invalid":
            if expr.args:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_invalid expects no arguments",
                )
            self._asm.op("INVALID")
            return
        if name == "__builtin_evm_selfdestruct":
            if len(expr.args) != 1:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_selfdestruct expects one argument",
                )
            self._emit_expr(expr.args[0])
            self._asm.op("SELFDESTRUCT")
            return
        if name == "__builtin_evm_keccak256":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_keccak256 expects two arguments",
                )
            self._emit_expr(expr.args[1])
            self._emit_expr(expr.args[0])
            self._asm.op("SHA3")
            return
        log_topic_count = self._evm_log_topic_count(name)
        if log_topic_count is not None:
            expected_arg_count = log_topic_count + 1
            if len(expr.args) != expected_arg_count:
                raise evm_backend_error(
                    self._result.filename,
                    f"{name} expects {expected_arg_count} arguments",
                )
            self._emit_expr(expr.args[-1])
            self._asm.push(0)
            self._asm.op("MSTORE")
            for topic in reversed(expr.args[:-1]):
                self._emit_expr(topic)
            self._asm.push(32)
            self._asm.push(0)
            self._asm.op(f"LOG{log_topic_count}")
            return
        log_data_topic_count = self._evm_log_data_topic_count(name)
        if log_data_topic_count is not None:
            expected_arg_count = log_data_topic_count + 2
            if len(expr.args) != expected_arg_count:
                raise evm_backend_error(
                    self._result.filename,
                    f"{name} expects {expected_arg_count} arguments",
                )
            for topic in reversed(expr.args[:log_data_topic_count]):
                self._emit_expr(topic)
            self._emit_expr(expr.args[-1])
            self._emit_expr(expr.args[-2])
            self._asm.op(f"LOG{log_data_topic_count}")
            return
        if name == "__builtin_evm_return_array":
            if len(expr.args) != 2:
                raise evm_backend_error(
                    self._result.filename,
                    "__builtin_evm_return_array expects two arguments",
                )
            self._emit_return_array(expr.args[0], expr.args[1])
            return
        function = self._functions_by_name.get(name)
        if function is not None:
            self._emit_direct_function_call(function, expr)
            return
        raise evm_backend_error(self._result.filename, f"unsupported EVM call: {name}")

    def _emit_indirect_function_call(self, expr: CallExpr) -> None:
        if self._current_layout is None:
            raise evm_backend_error(self._result.filename, "missing EVM function layout")
        call_layout = self._current_layout.indirect_calls.get(id(expr))
        if call_layout is None:
            raise evm_backend_error(
                self._result.filename,
                "missing EVM function pointer call layout",
            )
        signature = self._callable_signature_for_expr(expr.callee)
        if signature is None:
            raise evm_backend_error(
                self._result.filename,
                "EVM target does not support function pointers",
            )
        return_type, function_params = signature
        params, is_variadic = function_params
        if params is None or is_variadic:
            raise evm_backend_error(
                self._result.filename,
                "EVM function pointer calls need a fixed prototype",
            )
        if len(expr.args) != len(params) or len(call_layout.arg_offsets) != len(params):
            raise evm_backend_error(
                self._result.filename,
                "EVM function pointer argument count mismatch",
            )
        targets = self._function_pointer_targets(signature)
        if not targets:
            raise evm_backend_error(
                self._result.filename,
                "EVM function pointer call has no local target with matching prototype",
            )

        self._emit_expr(expr.callee)
        self._store_mem_word(call_layout.target_offset)
        for arg, param_type, arg_offset in zip(
            expr.args,
            params,
            call_layout.arg_offsets,
            strict=True,
        ):
            if self._is_word_value_type(param_type):
                self._emit_expr(arg)
                self._emit_integer_conversion_to_type(param_type)
                self._store_mem_word(arg_offset)
                continue
            if self._is_record_type(param_type):
                self._emit_aggregate_copy_to_memory(
                    arg_offset,
                    param_type,
                    arg,
                    "EVM aggregate function pointer argument type mismatch",
                )
                continue
            raise evm_backend_error(
                self._result.filename,
                f"unsupported EVM function pointer argument type: {param_type}",
            )

        end_label = self._new_label("fnptr_end")
        dispatch_labels: list[tuple[FunctionDef, str]] = []
        for function in targets:
            dispatch_label = self._new_label(f"fnptr_{function.name}")
            dispatch_labels.append((function, dispatch_label))
            self._load_mem_word(call_layout.target_offset)
            self._asm.push_label(self._internal_function_label(function))
            self._asm.op("EQ")
            self._asm.push_label(dispatch_label)
            self._asm.op("JUMPI")

        self._emit_revert(self._new_label("fnptr_bad_target"))
        for function, dispatch_label in dispatch_labels:
            function_layout = self._function_layouts[function.name]
            self._asm.label(dispatch_label)
            for param, param_type, arg_offset in zip(
                function.params,
                params,
                call_layout.arg_offsets,
                strict=True,
            ):
                assert param.name is not None
                local = function_layout.locals[param.name]
                if self._is_word_value_type(param_type):
                    self._load_mem_word(arg_offset)
                    self._store_local(local)
                    continue
                if self._is_record_type(param_type):
                    self._emit_aggregate_memory_copy(
                        local.offset,
                        local.type_,
                        arg_offset,
                        param_type,
                        "EVM aggregate function pointer dispatch type mismatch",
                    )
                    continue
                raise evm_backend_error(  # pragma: no cover - argument validation rejects earlier.
                    self._result.filename,
                    f"unsupported EVM function pointer dispatch type: {param_type}",
                )
            if self._is_void_type(return_type):
                self._asm.push_label(end_label)
                self._store_mem_word(function_layout.return_pc_offset)
                self._asm.push_label(self._internal_function_label(function))
                self._asm.op("JUMP")
                continue
            return_label = self._new_label(f"fnptr_{function.name}_return")
            self._asm.push_label(return_label)
            self._store_mem_word(function_layout.return_pc_offset)
            self._asm.push_label(self._internal_function_label(function))
            self._asm.op("JUMP")
            self._asm.label(return_label)
            if self._is_record_type(return_type):
                self._asm.push(function_layout.return_value_offset)
            else:
                self._load_mem_word(function_layout.return_value_offset)
            self._asm.push_label(end_label)
            self._asm.op("JUMP")
        self._asm.label(end_label)

    @staticmethod
    def _evm_modular_arithmetic_opcode(name: str) -> str | None:
        opcodes = {
            "__builtin_evm_addmod": "ADDMOD",
            "__builtin_evm_mulmod": "MULMOD",
        }
        return opcodes.get(name)

    @staticmethod
    def _evm_log_topic_count(name: str) -> int | None:
        prefix = "__builtin_evm_log"
        if not name.startswith(prefix):
            return None
        suffix = name[len(prefix) :]
        if suffix not in {"0", "1", "2", "3", "4"}:
            return None
        return int(suffix)

    @staticmethod
    def _evm_log_data_topic_count(name: str) -> int | None:
        prefix = "__builtin_evm_log"
        suffix = "_data"
        if not name.startswith(prefix) or not name.endswith(suffix):
            return None
        count = name[len(prefix) : -len(suffix)]
        if count not in {"0", "1", "2", "3", "4"}:
            return None
        return int(count)

    @staticmethod
    def _evm_environment_opcode(name: str) -> str | None:
        opcodes = {
            "__builtin_evm_address": "ADDRESS",
            "__builtin_evm_origin": "ORIGIN",
            "__builtin_evm_gasprice": "GASPRICE",
            "__builtin_evm_coinbase": "COINBASE",
            "__builtin_evm_timestamp": "TIMESTAMP",
            "__builtin_evm_number": "NUMBER",
            "__builtin_evm_prevrandao": "PREVRANDAO",
            "__builtin_evm_gaslimit": "GASLIMIT",
            "__builtin_evm_chainid": "CHAINID",
            "__builtin_evm_selfbalance": "SELFBALANCE",
            "__builtin_evm_basefee": "BASEFEE",
            "__builtin_evm_blobbasefee": "BLOBBASEFEE",
            "__builtin_evm_gas": "GAS",
        }
        return opcodes.get(name)

    @staticmethod
    def _evm_unary_query_opcode(name: str) -> str | None:
        opcodes = {
            "__builtin_evm_balance": "BALANCE",
            "__builtin_evm_blockhash": "BLOCKHASH",
            "__builtin_evm_extcodesize": "EXTCODESIZE",
            "__builtin_evm_extcodehash": "EXTCODEHASH",
        }
        return opcodes.get(name)

    def _emit_direct_function_call(self, function: FunctionDef, expr: CallExpr) -> None:
        symbol = self._sema.functions.get(function.name)
        layout = self._function_layouts.get(function.name)
        if symbol is None or layout is None:
            raise evm_backend_error(
                self._result.filename,
                f"missing EVM function layout: {function.name}",
            )
        if len(expr.args) != len(function.params):
            raise evm_backend_error(
                self._result.filename,
                f"EVM call argument count mismatch for {function.name}",
            )
        for arg, param in zip(expr.args, function.params, strict=True):
            assert param.name is not None
            local = layout.locals[param.name]
            self._emit_direct_call_argument(arg, local)

        return_label = self._new_label(f"{function.name}_call_return")
        self._asm.push_label(return_label)
        self._store_mem_word(layout.return_pc_offset)
        self._asm.push_label(self._internal_function_label(function))
        self._asm.op("JUMP")
        self._asm.label(return_label)
        if self._is_record_type(symbol.return_type):
            self._asm.push(layout.return_value_offset)
        elif not self._is_void_type(symbol.return_type):
            self._load_mem_word(layout.return_value_offset)

    def _emit_direct_call_argument(self, arg: Expr, local: _Local) -> None:
        if self._is_word_value_type(local.type_):
            self._emit_expr(arg)
            self._emit_integer_conversion_to_type(local.type_)
            self._store_local(local)
            return
        if self._is_record_type(local.type_):
            self._emit_aggregate_copy_to_memory(
                local.offset,
                local.type_,
                arg,
                "EVM aggregate argument type mismatch",
            )
            return
        raise evm_backend_error(
            self._result.filename,
            f"unsupported EVM call argument type: {local.type_}",
        )

    def _emit_return_array(self, pointer_expr: Expr, length_expr: Expr) -> None:
        copy_label = self._new_label("return_array_copy")
        end_label = self._new_label("return_array_end")

        self._emit_expr(pointer_expr)
        self._store_mem_word(_RETURN_ARRAY_SOURCE)
        self._emit_expr(length_expr)
        self._store_mem_word(_RETURN_ARRAY_LENGTH)
        self._asm.push(0)
        self._store_mem_word(_RETURN_ARRAY_INDEX)

        self._asm.label(copy_label)
        self._load_mem_word(_RETURN_ARRAY_INDEX)
        self._load_mem_word(_RETURN_ARRAY_LENGTH)
        self._asm.op("LT")
        self._asm.op("ISZERO")
        self._asm.push_label(end_label)
        self._asm.op("JUMPI")

        self._load_mem_word(_RETURN_ARRAY_SOURCE)
        self._load_mem_word(_RETURN_ARRAY_INDEX)
        self._asm.push(_WORD_BYTES)
        self._asm.op("MUL")
        self._asm.op("ADD")
        self._asm.op("MLOAD")
        self._asm.push(64)
        self._load_mem_word(_RETURN_ARRAY_INDEX)
        self._asm.push(_WORD_BYTES)
        self._asm.op("MUL")
        self._asm.op("ADD")
        self._asm.op("MSTORE")

        self._load_mem_word(_RETURN_ARRAY_INDEX)
        self._asm.push(1)
        self._asm.op("ADD")
        self._store_mem_word(_RETURN_ARRAY_INDEX)
        self._asm.push_label(copy_label)
        self._asm.op("JUMP")

        self._asm.label(end_label)
        self._asm.push(_WORD_BYTES)
        self._asm.push(0)
        self._asm.op("MSTORE")
        self._load_mem_word(_RETURN_ARRAY_LENGTH)
        self._asm.push(_WORD_BYTES)
        self._asm.op("MUL")
        self._asm.push(64)
        self._asm.op("ADD")
        self._load_mem_word(_RETURN_ARRAY_LENGTH)
        self._asm.push(_WORD_BYTES)
        self._asm.op("MSTORE")
        self._asm.push(0)
        self._asm.op("RETURN")

    def _store_local(self, local: _Local) -> None:
        self._asm.push(local.offset)
        self._asm.op("MSTORE")

    def _load_local(self, local: _Local) -> None:
        self._asm.push(local.offset)
        self._asm.op("MLOAD")

    def _store_mem_word(self, offset: int) -> None:
        self._asm.push(offset)
        self._asm.op("MSTORE")

    def _load_mem_word(self, offset: int) -> None:
        self._asm.push(offset)
        self._asm.op("MLOAD")

    def _store_storage_global(self, storage: _StorageGlobal) -> None:
        self._asm.push(storage.slot)
        self._asm.op("SSTORE")

    def _load_storage_global(self, storage: _StorageGlobal) -> None:
        self._asm.push(storage.slot)
        self._asm.op("SLOAD")

    def _emit_lvalue_load(self, expr: Expr) -> None:
        lvalue = self._emit_lvalue_address(expr)
        if not self._is_word_value_type(lvalue.type_):
            return
        self._load_addressed(lvalue)

    def _emit_lvalue_address(self, expr: Expr) -> _LValue:
        if isinstance(expr, CompoundLiteralExpr):
            compound_local = self._compound_literal_local(expr)
            self._emit_compound_literal_init(compound_local, expr.initializer)
            self._asm.push(compound_local.offset)
            return _LValue("memory", compound_local.type_)
        if isinstance(expr, CallExpr):
            type_ = self._type_map.get(expr)
            if type_ is not None and self._is_record_type(type_):
                self._emit_call(expr)
                return _LValue("memory", type_)
        if isinstance(expr, Identifier):
            identifier_local = self._locals.get(expr.name)
            if identifier_local is not None:
                self._asm.push(identifier_local.offset)
                return _LValue("memory", identifier_local.type_)
            static_local = self._lookup_static_local(expr.name)
            if static_local is not None:
                self._asm.push(static_local.slot)
                return _LValue("storage", static_local.type_)
            storage = self._storage_globals.get(expr.name)
            if storage is not None:
                self._asm.push(storage.slot)
                return _LValue("storage", storage.type_)
            raise evm_backend_error(
                self._result.filename,
                f"unknown EVM lvalue: {expr.name}",
            )
        if isinstance(expr, UnaryExpr) and expr.op == "*":
            operand_type = self._decay_array_type(self._type_map.get(expr.operand))
            pointee = None if operand_type is None else operand_type.pointee()
            if pointee is None:
                raise evm_backend_error(self._result.filename, "EVM dereference needs a pointer")
            self._emit_expr(expr.operand)
            return _LValue("memory", pointee)
        if isinstance(expr, SubscriptExpr):
            return self._emit_subscript_lvalue_address(expr)
        if isinstance(expr, MemberExpr):
            return self._emit_member_lvalue_address(expr)
        raise evm_backend_error(
            self._result.filename,
            f"unsupported EVM lvalue: {type(expr).__name__}",
        )

    def _compound_literal_local(self, expr: CompoundLiteralExpr) -> _Local:
        if self._current_layout is None:
            raise evm_backend_error(self._result.filename, "missing EVM function layout")
        local = self._current_layout.compound_literals.get(id(expr))
        if local is None:
            raise evm_backend_error(self._result.filename, "missing EVM compound literal storage")
        return local

    def _string_literal_local(self, expr: StringLiteral) -> _Local:
        if self._current_layout is None:
            raise evm_backend_error(self._result.filename, "missing EVM function layout")
        local = self._current_layout.string_literals.get(id(expr))
        if local is None:
            raise evm_backend_error(self._result.filename, "missing EVM string literal storage")
        return local

    def _emit_subscript_lvalue_address(self, expr: SubscriptExpr) -> _LValue:
        base_type = self._type_map.get(expr.base)
        if base_type is not None and (base_type.is_array() or self._is_record_type(base_type)):
            base_lvalue = self._emit_lvalue_address(expr.base)
            element_type = base_lvalue.type_.element_type()
            if element_type is None:
                raise evm_backend_error(
                    self._result.filename,
                    f"EVM subscript base is not an array: {base_lvalue.type_}",
                )
            self._emit_expr(expr.index)
            stride = (
                self._storage_slots_for_type(element_type)
                if base_lvalue.space == "storage"
                else self._memory_stride_bytes(element_type)
            )
            self._scale_top(stride)
            self._asm.op("ADD")
            return _LValue(base_lvalue.space, element_type)

        pointer_type = self._decay_array_type(base_type)
        pointee = None if pointer_type is None else pointer_type.pointee()
        if pointee is None:
            raise evm_backend_error(self._result.filename, "EVM subscript needs a pointer")
        self._emit_expr(expr.base)
        self._emit_scaled_integer_expr(expr.index, self._memory_stride_bytes(pointee))
        self._asm.op("ADD")
        return _LValue("memory", pointee)

    def _emit_member_lvalue_address(self, expr: MemberExpr) -> _LValue:
        if expr.through_pointer:
            pointer_type = self._decay_array_type(self._type_map.get(expr.base))
            base_type = None if pointer_type is None else pointer_type.pointee()
            if base_type is None:
                raise evm_backend_error(self._result.filename, "EVM member pointer needs a record")
            self._emit_expr(expr.base)
            base_lvalue = _LValue("memory", base_type)
        else:
            base_lvalue = self._emit_lvalue_address(expr.base)
            base_type = base_lvalue.type_
        member_access = self._record_member_access(base_type, expr.member)
        if member_access.slot_offset:
            scale = _WORD_BYTES if base_lvalue.space == "memory" else 1
            self._asm.push(member_access.slot_offset * scale)
            self._asm.op("ADD")
        return _LValue(base_lvalue.space, member_access.type_, member_access.bit_width)

    def _load_addressed(self, lvalue: _LValue) -> None:
        if not self._is_word_value_type(lvalue.type_):
            raise evm_backend_error(
                self._result.filename,
                f"EVM cannot load aggregate value directly: {lvalue.type_}",
            )
        self._asm.op("MLOAD" if lvalue.space == "memory" else "SLOAD")
        if lvalue.bit_width is not None:
            self._emit_bit_field_load_conversion(lvalue)

    def _store_addressed(self, lvalue: _LValue) -> None:
        if not self._is_word_value_type(lvalue.type_):
            raise evm_backend_error(
                self._result.filename,
                f"EVM cannot store aggregate value directly: {lvalue.type_}",
            )
        if lvalue.bit_width is not None:
            self._emit_bit_field_truncation(lvalue.bit_width)
        self._asm.op("DUP1")
        self._asm.op("SWAP2")
        self._asm.op("MSTORE" if lvalue.space == "memory" else "SSTORE")

    def _store_addressed_without_result(self, lvalue: _LValue) -> None:
        if not self._is_word_value_type(lvalue.type_):
            raise evm_backend_error(
                self._result.filename,
                f"EVM cannot store aggregate value directly: {lvalue.type_}",
            )
        self._asm.op("MSTORE" if lvalue.space == "memory" else "SSTORE")

    def _emit_bit_field_load_conversion(self, lvalue: _LValue) -> None:
        assert lvalue.bit_width is not None
        self._emit_bit_field_truncation(lvalue.bit_width)
        if is_signed_integer_type(lvalue.type_) and lvalue.bit_width < 256:
            shift = 256 - lvalue.bit_width
            self._asm.push(shift)
            self._asm.op("SHL")
            self._asm.push(shift)
            self._asm.op("SAR")

    def _emit_bit_field_truncation(self, bit_width: int) -> None:
        if bit_width <= 0:
            self._asm.push(0)
            self._asm.op("AND")
            return
        if bit_width >= 256:
            return
        self._asm.push((1 << bit_width) - 1)
        self._asm.op("AND")

    def _decay_array_type(self, type_: Type | None) -> Type | None:
        if type_ is None:
            return None
        element_type = type_.element_type()
        if element_type is not None:
            return element_type.pointer_to()
        return type_

    def _pointer_stride_bytes(self, type_: Type) -> int:
        pointee = type_.pointee()
        if pointee is None:
            return 1
        return self._memory_stride_bytes(pointee)

    def _memory_stride_bytes(self, type_: Type) -> int:
        return self._memory_slots_for_type(type_) * _WORD_BYTES

    def _sizeof_expr(self, expr: SizeofExpr) -> int:
        return self._sizeof_type(self._sizeof_operand_type(expr))

    def _alignof_expr(self, expr: AlignofExpr) -> int:
        return self._alignof_type(self._sizeof_operand_type(expr))

    def _offsetof_value(self, expr: BuiltinOffsetofExpr) -> int:
        root_type = self._resolve_type_spec(expr.type_spec)
        return self._offsetof_member_path(root_type, expr.member.split("."))

    def _offsetof_member_path(self, root_type: Type, parts: list[str]) -> int:
        if not parts:
            return 0
        member_type, member_slot_offset = self._record_member_offset(root_type, parts[0])
        return member_slot_offset * _WORD_BYTES + self._offsetof_member_path(member_type, parts[1:])

    def _types_compatible_value(self, expr: BuiltinTypesCompatExpr) -> int:
        type1 = unqualified_type(self._resolve_type_spec(expr.type1))
        type2 = unqualified_type(self._resolve_type_spec(expr.type2))
        return int(type1 == type2)

    def _select_generic_expr(self, expr: GenericExpr) -> Expr:
        control_type = self._decay_array_type(self._type_map.get(expr.control))
        if control_type is None:
            raise evm_backend_error(
                self._result.filename,
                "EVM target cannot resolve _Generic control type",
            )
        selected_expr: Expr | None = None
        default_expr: Expr | None = None
        for assoc_type_spec, assoc_expr in expr.associations:
            if assoc_type_spec is None:
                default_expr = assoc_expr
                continue
            if self._resolve_type_spec(assoc_type_spec) == control_type:
                selected_expr = assoc_expr
        if selected_expr is not None:
            return selected_expr
        if default_expr is not None:
            return default_expr
        raise evm_backend_error(
            self._result.filename,
            "EVM target cannot select _Generic association",
        )

    def _sizeof_operand_type(self, expr: SizeofExpr | AlignofExpr) -> Type:
        if expr.type_spec is not None:
            return self._resolve_type_spec(expr.type_spec)
        assert expr.expr is not None
        type_ = self._type_map.get(expr.expr)
        if type_ is None:
            raise evm_backend_error(
                self._result.filename,
                "EVM target cannot resolve sizeof operand type",
            )
        return type_

    def _sizeof_type(self, type_: Type) -> int:
        pointee = type_.pointee()
        if pointee is not None:
            return _WORD_BYTES
        if type_.declarator_ops:
            kind, value = type_.declarator_ops[0]
            if kind == "fn":
                raise evm_backend_error(
                    self._result.filename,
                    f"EVM target cannot size function type: {type_}",
                )
            if kind != "arr" or not isinstance(value, int) or value <= 0:
                raise evm_backend_error(
                    self._result.filename,
                    f"EVM target needs a complete sized type: {type_}",
                )
            element_type = type_.element_type()
            if element_type is None:
                raise evm_backend_error(  # pragma: no cover - Type array ops always have elements.
                    self._result.filename,
                    f"EVM target cannot size array type: {type_}",
                )
            return value * self._sizeof_type(element_type)
        if is_integer_type(type_) or self._is_record_type(type_):
            return self._memory_slots_for_type(type_) * _WORD_BYTES
        raise evm_backend_error(self._result.filename, f"EVM target cannot size type: {type_}")

    def _alignof_type(self, type_: Type) -> int:
        pointee = type_.pointee()
        if pointee is not None:
            return _WORD_BYTES
        if type_.declarator_ops:
            kind, _ = type_.declarator_ops[0]
            if kind == "fn":
                raise evm_backend_error(
                    self._result.filename,
                    f"EVM target cannot align function type: {type_}",
                )
            element_type = type_.element_type()
            if element_type is None:
                raise evm_backend_error(
                    self._result.filename,
                    f"EVM target cannot align array type: {type_}",
                )
            return self._alignof_type(element_type)
        if is_integer_type(type_) or self._is_record_type(type_):
            return _WORD_BYTES
        raise evm_backend_error(self._result.filename, f"EVM target cannot align type: {type_}")

    def _emit_scaled_integer_expr(self, expr: Expr, scale: int) -> None:
        self._emit_expr(expr)
        self._scale_top(scale)

    def _scale_top(self, scale: int) -> None:
        if scale == 1:
            return
        self._asm.push(scale)
        self._asm.op("MUL")

    def _lookup_local_type(
        self,
        stmt: DeclStmt,
        symbol: FunctionSymbol | None = None,
    ) -> Type:
        assert stmt.name is not None
        local_symbol = self._func_sym if symbol is None else symbol
        if local_symbol is not None:
            candidate = local_symbol.locals.get(stmt.name)
            if isinstance(candidate, VarSymbol):
                return candidate.type_
        return self._resolve_type_spec(stmt.type_spec)

    @staticmethod
    def _is_function_declaration(stmt: DeclStmt) -> bool:
        return bool(stmt.type_spec.declarator_ops) and stmt.type_spec.declarator_ops[0][0] == "fn"

    def _resolve_type_spec(self, type_spec: TypeSpec) -> Type:
        typedef = None
        if self._sema.file_scope is not None:
            typedef = self._sema.file_scope.lookup_typedef(type_spec.name)
        if typedef is not None:
            base = typedef
        elif type_spec.has_record_body or type_spec.record_tag is not None:
            base = Type(
                self._record_name_for_type_spec(type_spec),
                qualifiers=type_spec.qualifiers,
            )
        elif type_spec.name == "enum":
            base = INT
        elif type_spec.name == "bool":
            base = Type("_Bool", qualifiers=type_spec.qualifiers)
        else:
            base = Type(type_spec.name, qualifiers=type_spec.qualifiers)
        ops: list[TypeOp] = []
        for kind, value in type_spec.declarator_ops:
            if kind == "ptr":
                ops.append(("ptr", 0))
            elif kind == "arr":
                ops.append(("arr", value if isinstance(value, int) else -1))
            else:
                raise evm_backend_error(
                    self._result.filename,
                    "EVM target does not support local function declarators",
                )
        ops.extend(base.declarator_ops)
        return Type(base.name, declarator_ops=tuple(ops), qualifiers=base.qualifiers)

    def _record_name_for_type_spec(self, type_spec: TypeSpec) -> str:
        if type_spec.record_tag is not None:
            candidate = f"{type_spec.name} {type_spec.record_tag}"
            if candidate in self._sema.record_definitions or not type_spec.has_record_body:
                return candidate
            scoped_prefix = f"{candidate} <scope:"
            for record_name in self._sema.record_definitions:
                if record_name.startswith(scoped_prefix) and self._record_members_match_type_spec(
                    record_name,
                    type_spec,
                ):
                    return record_name
            return candidate
        if type_spec.has_record_body:
            for record_name in self._sema.record_definitions:
                if not record_name.startswith(type_spec.name):
                    continue
                if self._record_members_match_type_spec(record_name, type_spec):
                    return record_name
        return type_spec.name

    def _record_members_match_type_spec(self, record_name: str, type_spec: TypeSpec) -> bool:
        members = self._sema.record_definitions.get(record_name)
        if members is None or len(members) != len(type_spec.record_members):
            return False
        for resolved, declared in zip(members, type_spec.record_members, strict=True):
            if resolved.name != declared.name:
                return False
            if resolved.type_ != self._resolve_type_spec(declared.type_spec):
                return False
        return True

    def _expr_is_void(self, expr: Expr) -> bool:
        type_ = self._type_map.get(expr)
        return type_ is not None and self._is_void_type(type_)

    @staticmethod
    def _is_void_type(type_: Type) -> bool:
        type_ = unqualified_type(type_)
        return type_.name == "void" and not type_.declarator_ops

    @staticmethod
    def _is_bool_type(type_: Type) -> bool:
        type_ = unqualified_type(type_)
        return type_.name in {"_Bool", "bool"} and not type_.declarator_ops

    @staticmethod
    def _is_char_object_type(type_: Type) -> bool:
        type_ = unqualified_type(type_)
        return type_.name in {"char", "signed char", "unsigned char"} and not type_.declarator_ops

    @staticmethod
    def _integer_type_bits(type_: Type) -> int | None:
        type_ = unqualified_type(type_)
        if type_.declarator_ops:
            return None
        return _INTEGER_TYPE_BITS.get(type_.name)

    def _emit_revert(self, label: str) -> None:
        self._asm.label(label)
        self._asm.push(0)
        self._asm.push(0)
        self._asm.op("REVERT")

    def _eval_storage_initializers(
        self,
        type_: Type,
        init: Expr | InitList,
    ) -> tuple[_StorageInitValue, ...]:
        if isinstance(init, StringLiteral):
            return self._eval_storage_string_literal(type_, init)
        if isinstance(init, InitList):
            return self._eval_storage_init_list(type_, init)
        if not self._is_word_value_type(type_):
            raise evm_backend_error(
                self._result.filename,
                f"EVM aggregate storage initializer for {type_} needs braces",
            )
        value = self._eval_storage_word_initializer(type_, init)
        if value is None:
            raise evm_backend_error(
                self._result.filename,
                "EVM initcode requires constant storage initializers",
            )
        if isinstance(value, str):
            return (value,)
        return (self._normalize_integer_constant(value, type_),)

    def _eval_storage_word_initializer(
        self,
        type_: Type,
        init: Expr,
    ) -> _StorageInitValue | None:
        if isinstance(init, ConditionalExpr):
            branch = self._select_const_conditional_branch(init)
            if branch is None:
                return None
            return self._eval_storage_word_initializer(type_, branch)
        function_label = self._eval_storage_function_label(type_, init)
        if function_label is not None:
            return function_label
        return self._eval_const_expr(init)

    def _eval_storage_function_label(self, type_: Type, init: Expr) -> str | None:
        if type_.callable_signature() is None:
            return None
        if isinstance(init, ConditionalExpr):
            branch = self._select_const_conditional_branch(init)
            if branch is None:
                return None
            return self._eval_storage_function_label(type_, branch)
        if isinstance(init, Identifier):
            function = self._functions_by_name.get(init.name)
            if function is not None:
                return self._internal_function_label(function)
            return None
        if isinstance(init, UnaryExpr) and init.op == "&" and isinstance(init.operand, Identifier):
            function = self._functions_by_name.get(init.operand.name)
            if function is not None:
                return self._internal_function_label(function)
        if isinstance(init, CastExpr):
            return self._eval_storage_function_label(type_, init.expr)
        return None

    def _select_const_conditional_branch(self, expr: ConditionalExpr) -> Expr | None:
        condition = self._eval_const_expr(expr.condition)
        if condition is None:
            return None
        return expr.then_expr if condition else expr.else_expr

    def _eval_storage_string_literal(self, type_: Type, init: StringLiteral) -> tuple[int, ...]:
        if not type_.is_array():
            raise evm_backend_error(
                self._result.filename,
                f"EVM string literal cannot initialize storage {type_}",
            )
        element_type = type_.element_type()
        if element_type is None or not self._is_char_object_type(element_type):
            raise evm_backend_error(
                self._result.filename,
                f"EVM string literal storage initializer needs a char array target: {type_}",
            )
        length = type_.declarator_ops[0][1]
        if not isinstance(length, int) or length <= 0:
            raise evm_backend_error(
                self._result.filename,
                f"EVM string literal storage initializer needs a complete array target: {type_}",
            )
        units = self._string_literal_units(init)
        if len(units) > length:
            raise evm_backend_error(
                self._result.filename,
                "EVM string literal storage initializer too long",
            )
        values = [
            self._normalize_integer_constant(
                units[index] if index < len(units) else 0,
                element_type,
            )
            for index in range(length)
        ]
        return tuple(values)

    def _eval_storage_init_list(
        self,
        type_: Type,
        init: InitList,
    ) -> tuple[_StorageInitValue, ...]:
        if type_.is_array():
            return self._eval_storage_array_init_list(type_, init)
        if self._is_record_type(type_):
            return self._eval_storage_record_init_list(type_, init)
        if self._is_word_value_type(type_):
            if len(init.items) != 1:
                raise evm_backend_error(
                    self._result.filename,
                    "EVM scalar storage initializer list requires one element",
                )
            return self._eval_storage_initializers(type_, init.items[0].initializer)
        raise evm_backend_error(
            self._result.filename,
            f"unsupported EVM storage initializer target: {type_}",
        )

    def _eval_storage_array_init_list(
        self,
        type_: Type,
        init: InitList,
    ) -> tuple[_StorageInitValue, ...]:
        element_type = type_.element_type()
        assert element_type is not None
        length = type_.declarator_ops[0][1]
        if not isinstance(length, int) or length <= 0:
            raise evm_backend_error(
                self._result.filename,
                f"EVM storage initializer needs a complete array type: {type_}",
            )
        values: list[_StorageInitValue] = [0] * self._storage_slots_for_type(type_)
        element_slots = self._storage_slots_for_type(element_type)
        next_index = 0
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                for (
                    target_offset,
                    target_type,
                    target_bit_width,
                ) in self._storage_designator_targets(0, type_, item.designators):
                    self._write_storage_initializer_values(
                        values,
                        target_offset,
                        target_type,
                        item.initializer,
                        target_bit_width,
                    )
                next_index = self._next_array_initializer_index(kind, value, length)
                continue
            if next_index >= length:
                raise evm_backend_error(
                    self._result.filename,
                    "EVM storage array initializer too long",
                )
            self._write_storage_initializer_values(
                values,
                next_index * element_slots,
                element_type,
                item.initializer,
            )
            next_index += 1
        return tuple(values)

    def _eval_storage_record_init_list(
        self,
        type_: Type,
        init: InitList,
    ) -> tuple[_StorageInitValue, ...]:
        members = self._sema.record_definitions.get(type_.name)
        if members is None:
            raise evm_backend_error(self._result.filename, f"unknown EVM record type: {type_}")
        values: list[_StorageInitValue] = [0] * self._storage_slots_for_type(type_)
        next_member = 0
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind != "member" or not isinstance(value, str):
                    raise evm_backend_error(
                        self._result.filename,
                        "EVM storage record initializer designator must use member",
                    )
                member_index = self._record_member_index(type_, value)
                for (
                    target_offset,
                    target_type,
                    target_bit_width,
                ) in self._storage_designator_targets(0, type_, item.designators):
                    self._write_storage_initializer_values(
                        values,
                        target_offset,
                        target_type,
                        item.initializer,
                        target_bit_width,
                    )
                next_member = member_index + 1
                continue
            next_member = self._next_record_initializer_member_index(members, next_member)
            if next_member >= len(members):
                raise evm_backend_error(
                    self._result.filename,
                    "EVM storage record initializer too long",
                )
            member = members[next_member]
            if (
                member.name is None
                and not self._is_anonymous_record_member(member)
                and not self._is_unnamed_bit_field(member)
            ):
                raise evm_backend_error(  # pragma: no cover - slot sizing rejects this first.
                    self._result.filename,
                    "EVM target does not support anonymous storage members",
                )
            member_slot_offset = self._record_member_slot_offset_by_index(type_, next_member)
            self._write_storage_initializer_values(
                values,
                member_slot_offset,
                member.type_,
                item.initializer,
                member.bit_width,
            )
            next_member += 1
        return tuple(values)

    def _write_storage_initializer_values(
        self,
        values: list[_StorageInitValue],
        slot_offset: int,
        type_: Type,
        init: Expr | InitList,
        bit_width: int | None = None,
    ) -> None:
        piece = self._eval_storage_initializers(type_, init)
        if bit_width is not None:
            if len(piece) != 1 or not isinstance(piece[0], int):
                raise evm_backend_error(
                    self._result.filename,
                    "EVM bit-field storage initializer must be an integer word",
                )
            piece = (self._truncate_bit_field_constant(piece[0], bit_width),)
        end = slot_offset + len(piece)
        if slot_offset < 0 or end > len(values):
            raise evm_backend_error(
                self._result.filename,
                "EVM storage initializer writes outside aggregate",
            )
        values[slot_offset:end] = piece

    def _eval_case_value(self, expr: Expr) -> int:
        value = self._eval_const_expr(expr)
        if value is None:
            raise evm_backend_error(self._result.filename, "EVM target cannot evaluate case value")
        return value

    def _eval_const_expr(self, expr: Expr) -> int | None:
        if isinstance(expr, IntLiteral):
            return self._parse_int(expr.value)
        if isinstance(expr, CharLiteral):
            return self._char_value(expr.value)
        if isinstance(expr, Identifier):
            return self._lookup_enum_constant(expr.name)
        if isinstance(expr, UnaryExpr):
            value = self._eval_const_expr(expr.operand)
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
        if isinstance(expr, BinaryExpr):
            left = self._eval_const_expr(expr.left)
            right = self._eval_const_expr(expr.right)
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
            if expr.op == "&":
                return left & right
            if expr.op == "|":
                return left | right
            if expr.op == "^":
                return left ^ right
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
        if isinstance(expr, ConditionalExpr):
            branch = self._select_const_conditional_branch(expr)
            if branch is None:
                return None
            return self._eval_const_expr(branch)
        if isinstance(expr, CastExpr):
            value = self._eval_const_expr(expr.expr)
            target_type = self._type_map.get(expr)
            if value is None or target_type is None:
                return value
            return self._normalize_integer_constant(value, target_type)
        if isinstance(expr, SizeofExpr):
            return self._sizeof_expr(expr)
        if isinstance(expr, AlignofExpr):
            return self._alignof_expr(expr)
        if isinstance(expr, BuiltinOffsetofExpr):
            return self._offsetof_value(expr)
        if isinstance(expr, BuiltinTypesCompatExpr):
            return self._types_compatible_value(expr)
        if isinstance(expr, GenericExpr):
            return self._eval_const_expr(self._select_generic_expr(expr))
        return None

    def _normalize_integer_constant(self, value: int, type_: Type) -> int:
        type_ = unqualified_type(type_)
        if not is_integer_type(type_):
            return value & ((1 << 256) - 1)
        bits = self._integer_type_bits(type_)
        if bits is None:
            return value & ((1 << 256) - 1)  # pragma: no cover - canonical ints have widths.
        if self._is_bool_type(type_):
            return int(value != 0)
        if bits >= 256:
            return value & ((1 << 256) - 1)
        mask = (1 << bits) - 1
        value &= mask
        if is_signed_integer_type(type_) and value & (1 << (bits - 1)):
            value -= 1 << bits
        return value & ((1 << 256) - 1)

    def _truncate_bit_field_constant(self, value: int, bit_width: int) -> int:
        if bit_width <= 0:
            return 0
        if bit_width >= 256:
            return value & ((1 << 256) - 1)
        return value & ((1 << bit_width) - 1)

    def _resolve_storage_initializer_value(
        self,
        value: _StorageInitValue,
        runtime_labels: dict[str, int],
    ) -> int:
        if isinstance(value, int):
            return value
        resolved = runtime_labels.get(value)
        if resolved is None:
            raise evm_backend_error(
                self._result.filename,
                f"unknown EVM storage initializer label: {value}",
            )
        return resolved

    def _build_initcode(self, runtime: bytes, stores: tuple[tuple[int, int], ...]) -> bytes:
        if len(runtime) > 0xFFFF:
            raise evm_backend_error(self._result.filename, "EVM runtime is too large for initcode")
        out = bytearray()
        for slot, value in stores:
            self._append_push(out, value)
            self._append_push(out, slot)
            out.append(_OPCODES["SSTORE"])
        copy_stub_size = 15
        runtime_offset = len(out) + copy_stub_size
        if runtime_offset > 0xFFFF:
            raise evm_backend_error(self._result.filename, "EVM initcode prefix is too large")
        self._append_push(out, len(runtime), size=2)
        self._append_push(out, runtime_offset, size=2)
        self._append_push(out, 0)
        out.append(_OPCODES["CODECOPY"])
        self._append_push(out, len(runtime), size=2)
        self._append_push(out, 0)
        out.append(_OPCODES["RETURN"])
        out.extend(runtime)
        return bytes(out)

    def _append_push(self, out: bytearray, value: int, *, size: int | None = None) -> None:
        if value < 0:
            value &= (1 << 256) - 1
        if size is None:
            size = max(1, (value.bit_length() + 7) // 8)
        if size < 1 or size > 32:
            raise evm_backend_error(self._result.filename, "EVM PUSH operand is out of range")
        out.append(0x5F + size)
        out.extend(value.to_bytes(size, "big"))

    def _new_label(self, prefix: str) -> str:
        self._label_counter += 1
        return f"{prefix}_{self._label_counter}"

    @staticmethod
    def _parse_int(raw: str) -> int:
        text = raw.replace("_", "").lower()
        while text and text[-1] in "ul":
            text = text[:-1]
        if text.startswith(("0x", "+0x")):
            return int(text, 16)
        if text.startswith(("0b", "+0b")):
            return int(text, 2)
        if text.startswith("0") and text not in {"0", "+0"}:
            sign = -1 if text.startswith("-") else 1
            body = text[1:] if sign > 0 else text[2:]
            return sign * int(body or "0", 8)
        return int(text or "0", 10)

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

    def _string_literal_units(self, expr: StringLiteral) -> list[int]:
        body = string_literal_body(expr.value)
        if body is None:
            raise evm_backend_error(
                self._result.filename,
                "EVM target cannot decode string literal",
            )
        units = decode_escaped_units(body)
        units.append(0)
        return units


def generate_evm_asm(result: FrontendResult) -> str:
    return _EvmGen(result).generate_asm()


def generate_evm_bytecode(result: FrontendResult) -> str:
    return _EvmGen(result).generate_bytecode()


def generate_evm_initcode(result: FrontendResult) -> str:
    return _EvmGen(result, allow_storage_initializers=True).generate_initcode()
