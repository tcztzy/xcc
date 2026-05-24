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
    has_init: bool = False
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
    generic_return: bool = False


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
    record_definitions: dict[str, tuple[RecordMemberInfo, ...]]
    file_scope: "Scope | None" = None


class Scope:
    def __init__(self, parent: "Scope | None" = None) -> None:
        self._symbols: dict[str, VarSymbol | EnumConstSymbol] = {}
        self._typedefs: dict[str, Type] = {}
        self._record_tags: dict[tuple[str, str], str] = {}
        self._parent = parent

    def _types_mergeable(self, a: "Type", b: "Type") -> bool:
        """Check two types are compatible enough to merge tentative definitions.

        C11 6.9.2: multiple tentative definitions / external definitions
        must have compatible types. We check base name and declarator
        structure, but tolerate unknown array sizes (one side may have a
        bound while the other doesn't).
        """
        if a is b or a == b:
            return True
        # Must have same base name and qualifiers.
        if a.name != b.name or a.qualifiers != b.qualifiers:
            return False
        # Walk declarator ops: same kind sequence, tolerate mismatched array sizes.
        ops_a, ops_b = a.declarator_ops, b.declarator_ops
        if len(ops_a) != len(ops_b):
            return False
        for (kind_a, val_a), (kind_b, val_b) in zip(ops_a, ops_b, strict=True):
            if kind_a != kind_b:
                return False
            if kind_a == "arr":
                assert isinstance(val_a, int) and isinstance(val_b, int)
                if val_a > 0 and val_b > 0 and val_a != val_b:
                    return False
            elif kind_a == "fn" and val_a != val_b:
                return False
            # ptr has val=0 always
        return True

    def _composite_type(self, existing: "Type", new: "Type") -> "Type":
        if not existing.is_array() or not new.is_array():
            return new
        existing_bound = existing.declarator_ops[0][1]
        new_bound = new.declarator_ops[0][1]
        if not isinstance(existing_bound, int) or not isinstance(new_bound, int):
            return new
        if existing_bound > 0 and new_bound < 0:
            return existing
        if existing_bound < 0 and new_bound > 0:
            return new
        return new

    def define(self, symbol: VarSymbol | EnumConstSymbol) -> None:
        existing = self._symbols.get(symbol.name)
        if existing is not None or symbol.name in self._typedefs:
            if (
                isinstance(existing, VarSymbol)
                and isinstance(symbol, VarSymbol)
                and existing.is_extern
                and self._types_mergeable(existing.type_, symbol.type_)
            ):
                self._symbols[symbol.name] = symbol
                return
            raise SemaError(f"Duplicate declaration: {symbol.name}")
        self._symbols[symbol.name] = symbol

    def define_file_scope(self, symbol: VarSymbol) -> None:
        """Define a file-scope symbol, merging tentative definitions per C11 6.9.2.

        Multiple tentative definitions (no initializer) are merged silently.
        A tentative followed by an initialized definition replaces the first.
        """
        existing = self._symbols.get(symbol.name)
        if existing is not None or symbol.name in self._typedefs:
            if (
                isinstance(existing, VarSymbol)
                and isinstance(symbol, VarSymbol)
                and existing.is_extern
                and self._types_mergeable(existing.type_, symbol.type_)
            ):
                self._symbols[symbol.name] = symbol
                return
            # C11 6.9.2: Merge tentative definitions.
            if (
                isinstance(existing, VarSymbol)
                and not existing.is_extern
                and not symbol.is_extern
                and self._types_mergeable(existing.type_, symbol.type_)
            ):
                symbol.type_ = self._composite_type(existing.type_, symbol.type_)
                # Keep the initialized definition.
                if symbol.has_init and not existing.has_init:
                    self._symbols[symbol.name] = symbol
                return
            raise SemaError(f"Duplicate declaration: {symbol.name}")
        self._symbols[symbol.name] = symbol

    def define_typedef(self, name: str, type_: Type) -> None:
        if name in self._symbols:
            raise SemaError(f"Duplicate declaration: {name}")
        existing = self._typedefs.get(name)
        if existing is not None:
            if existing == type_:
                return
            raise SemaError(f"Duplicate declaration: {name}")
        self._typedefs[name] = type_

    def define_record_tag(self, kind: str, tag: str, record_name: str) -> str:
        key = (kind, tag)
        existing = self._record_tags.get(key)
        if existing is not None:
            return existing
        self._record_tags[key] = record_name
        return record_name

    def lookup_record_tag_current(self, kind: str, tag: str) -> str | None:
        return self._record_tags.get((kind, tag))

    def lookup_record_tag(self, kind: str, tag: str) -> str | None:
        record_name = self.lookup_record_tag_current(kind, tag)
        if record_name is not None:
            return record_name
        if self._parent is None:
            return None
        return self._parent.lookup_record_tag(kind, tag)

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
