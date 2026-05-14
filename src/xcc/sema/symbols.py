from dataclasses import dataclass

from xcc.ast import Expr
from xcc.types import INT, Type


@dataclass
class SemaError(ValueError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class VarSymbol:
    name: str
    type_: Type
    alignment: int | None = None
    is_extern: bool = False
    constant_value: int | None = None
    # For arrays: the InitList expression, used to evaluate const subscripts.
    _init_expr: object | None = None


@dataclass(frozen=True)
class EnumConstSymbol:
    name: str
    value: int
    type_: Type = INT


@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    return_type: Type
    locals: dict[str, VarSymbol | EnumConstSymbol]


@dataclass(frozen=True)
class FunctionSignature:
    return_type: Type
    params: tuple[Type, ...] | None
    is_variadic: bool


@dataclass(frozen=True)
class RecordMemberInfo:
    name: str | None
    type_: Type
    alignment: int | None = None
    bit_width: int | None = None


class TypeMap:
    def __init__(self) -> None:
        self._map: dict[int, Type] = {}

    def set(self, node: Expr, type_: Type) -> None:
        self._map[id(node)] = type_

    def get(self, node: Expr) -> Type | None:
        return self._map.get(id(node))

    def require(self, node: Expr) -> Type:
        return self._map[id(node)]


@dataclass(frozen=True)
class SemaUnit:
    functions: dict[str, FunctionSymbol]
    type_map: TypeMap


class Scope:
    def __init__(self, parent: "Scope | None" = None) -> None:
        self._symbols: dict[str, VarSymbol | EnumConstSymbol] = {}
        self._typedefs: dict[str, Type] = {}
        self._parent = parent

    def define(self, symbol: VarSymbol | EnumConstSymbol) -> None:
        existing = self._symbols.get(symbol.name)
        if existing is not None or symbol.name in self._typedefs:
            if (
                isinstance(existing, VarSymbol)
                and isinstance(symbol, VarSymbol)
                and existing.is_extern
                and existing.type_ == symbol.type_
            ):
                self._symbols[symbol.name] = symbol
                return
            raise SemaError(f"Duplicate declaration: {symbol.name}")
        self._symbols[symbol.name] = symbol

    def define_typedef(self, name: str, type_: Type) -> None:
        if name in self._symbols or name in self._typedefs:
            raise SemaError(f"Duplicate declaration: {name}")
        self._typedefs[name] = type_

    def lookup(self, name: str) -> VarSymbol | EnumConstSymbol | None:
        symbol = self._symbols.get(name)
        if symbol is not None:
            return symbol
        if self._parent is None:
            return None
        return self._parent.lookup(name)

    def lookup_typedef(self, name: str) -> Type | None:
        typedef_type = self._typedefs.get(name)
        if typedef_type is not None:
            return typedef_type
        if self._parent is None:
            return None
        return self._parent.lookup_typedef(name)

    @property
    def symbols(self) -> dict[str, VarSymbol | EnumConstSymbol]:
        return self._symbols


class SwitchContext:
    def __init__(self) -> None:
        self.case_values: set[str] = set()
        self.has_default = False
