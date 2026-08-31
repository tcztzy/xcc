from dataclasses import dataclass, field

from xcc.ast import Expr
from xcc.data_layout import GENERIC_LP64_DATA_LAYOUT, TargetDataLayout
from xcc.types import INT, Type

from .layout import RecordLayout


@dataclass
class SemaError(ValueError):
    message: str
    line: int | None = None
    column: int | None = None

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
        self._nodes: list[Expr] = []

    def set(self, node: Expr, type_: Type) -> None:
        self._nodes.append(node)
        self._map[id(node)] = type_

    def get(self, node: Expr) -> Type | None:
        return self._map.get(id(node))

    def require(self, node: Expr) -> Type:
        type_ = self.get(node)
        if type_ is None:
            raise KeyError("missing type map entry")
        return type_


@dataclass(frozen=True)
class SemaUnit:
    functions: dict[str, FunctionSymbol]
    type_map: TypeMap
    record_definitions: dict[str, tuple[RecordMemberInfo, ...]]
    file_scope: "Scope | None" = None
    function_signatures: dict[str, FunctionSignature] = field(default_factory=dict)
    transparent_union_types: set[str] = field(default_factory=set)
    data_layout: TargetDataLayout = GENERIC_LP64_DATA_LAYOUT
    record_type_names: dict[int, str] = field(default_factory=dict)
    record_packs: dict[str, int | None] = field(default_factory=dict)
    record_layouts: dict[str, RecordLayout] = field(default_factory=dict)


class Scope:
    def __init__(self, parent: "Scope | None" = None) -> None:
        self._symbols: dict[str, VarSymbol | EnumConstSymbol] = {}
        self._enum_values: dict[str, int] = {}
        self._typedefs: dict[str, Type] = {}
        self._record_tags: dict[str, str] = {}
        self._parent = parent

    def child(self) -> "Scope":
        scope = Scope()
        scope._parent = self
        return scope

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
                bound_a = val_a
                bound_b = val_b
                if bound_a > 0 and bound_b > 0 and bound_a != bound_b:
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
        if isinstance(symbol, EnumConstSymbol):
            self._enum_values[symbol.name] = symbol.value

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
        key = kind + " " + tag
        existing = self._record_tags.get(key)
        if existing is not None:
            return existing
        self._record_tags[key] = record_name
        return record_name

    def lookup_record_tag_current(self, kind: str, tag: str) -> str | None:
        return self._record_tags.get(kind + " " + tag)

    def lookup_record_tag(self, kind: str, tag: str) -> str | None:
        scope: Scope | None = self
        while scope is not None:
            record_name = scope.lookup_record_tag_current(kind, tag)
            if record_name is not None:
                return record_name
            scope = scope._parent
        return None

    def lookup(self, name: str) -> VarSymbol | EnumConstSymbol | None:
        scope: Scope | None = self
        while scope is not None:
            symbol = scope._symbols.get(name)
            if symbol is not None:
                return symbol
            scope = scope._parent
        return None

    def lookup_enum_value(self, name: str) -> int | None:
        scope: Scope | None = self
        while scope is not None:
            symbol = scope._symbols.get(name)
            if symbol is not None:
                if name in scope._enum_values:
                    return scope._enum_values[name]
                return None
            scope = scope._parent
        return None

    def lookup_typedef(self, name: str) -> Type | None:
        scope: Scope | None = self
        while scope is not None:
            typedef_type = scope._typedefs.get(name)
            if typedef_type is not None:
                return typedef_type
            scope = scope._parent
        return None

    @property
    def symbols(self) -> dict[str, VarSymbol | EnumConstSymbol]:
        return self._symbols


class SwitchContext:
    def __init__(self) -> None:
        self.case_values: set[str] = set()
        self.has_default = False
