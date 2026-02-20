from contextlib import suppress
from dataclasses import dataclass
from typing import Literal, cast

from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
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
    Param,
    ReturnStmt,
    SizeofExpr,
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
from xcc.types import (
    BOOL,
    CHAR,
    DOUBLE,
    FLOAT,
    INT,
    LLONG,
    LONG,
    LONGDOUBLE,
    SHORT,
    UCHAR,
    UINT,
    ULLONG,
    ULONG,
    USHORT,
    VOID,
    Type,
)

_HEX_DIGITS = "0123456789abcdefABCDEF"
_OCTAL_DIGITS = "01234567"
_MAX_ARRAY_OBJECT_BYTES = (1 << 31) - 1
_POINTER_SIZE = 8
_BASE_TYPE_SIZES = {
    "_Bool": 1,
    "char": 1,
    "unsigned char": 1,
    "short": 2,
    "unsigned short": 2,
    "int": 4,
    "unsigned int": 4,
    "long": 8,
    "unsigned long": 8,
    "long long": 8,
    "unsigned long long": 8,
    "float": 4,
    "double": 8,
    "long double": 16,
}
_BASE_TYPE_ALIGNMENTS = dict(_BASE_TYPE_SIZES)
_SIMPLE_ESCAPES = {
    "'": ord("'"),
    '"': ord('"'),
    "?": ord("?"),
    "\\": ord("\\"),
    "a": 7,
    "b": 8,
    "f": 12,
    "n": 10,
    "r": 13,
    "t": 9,
    "v": 11,
}


_SIGNED_INTEGER_TYPE_LIMITS = {
    INT: (-(1 << 31), (1 << 31) - 1),
    LONG: (-(1 << 63), (1 << 63) - 1),
    LLONG: (-(1 << 63), (1 << 63) - 1),
}
_UNSIGNED_INTEGER_TYPE_LIMITS = {
    UINT: (1 << 32) - 1,
    ULONG: (1 << 64) - 1,
    ULLONG: (1 << 64) - 1,
}
_INTEGER_PROMOTION_TYPES = {
    BOOL.name: INT,
    CHAR.name: INT,
    UCHAR.name: INT,
    SHORT.name: INT,
    USHORT.name: INT,
}
_INTEGER_TYPE_RANKS = {
    BOOL.name: 1,
    CHAR.name: 2,
    UCHAR.name: 2,
    SHORT.name: 3,
    USHORT.name: 3,
    INT.name: 4,
    UINT.name: 4,
    LONG.name: 5,
    ULONG.name: 5,
    LLONG.name: 6,
    ULLONG.name: 6,
}
_SIGNED_INTEGER_NAMES = {CHAR.name, SHORT.name, INT.name, LONG.name, LLONG.name}
_UNSIGNED_COUNTERPARTS = {
    INT.name: UINT,
    LONG.name: ULONG,
    LLONG.name: ULLONG,
}
_CANONICAL_INTEGER_TYPES = {
    BOOL.name: BOOL,
    CHAR.name: CHAR,
    UCHAR.name: UCHAR,
    SHORT.name: SHORT,
    USHORT.name: USHORT,
    INT.name: INT,
    UINT.name: UINT,
    LONG.name: LONG,
    ULONG.name: ULONG,
    LLONG.name: LLONG,
    ULLONG.name: ULLONG,
}
_DECIMAL_LITERAL_CANDIDATES: dict[str, tuple[Type, ...]] = {
    "": (INT, LONG, LLONG),
    "u": (UINT, ULONG, ULLONG),
    "l": (LONG, LLONG),
    "ul": (ULONG, ULLONG),
    "lu": (ULONG, ULLONG),
    "ll": (LLONG,),
    "ull": (ULLONG,),
    "llu": (ULLONG,),
}
_NON_DECIMAL_LITERAL_CANDIDATES: dict[str, tuple[Type, ...]] = {
    "": (INT, UINT, LONG, ULONG, LLONG, ULLONG),
    "u": (UINT, ULONG, ULLONG),
    "l": (LONG, ULONG, LLONG, ULLONG),
    "ul": (ULONG, ULLONG),
    "lu": (ULONG, ULLONG),
    "ll": (LLONG, ULLONG),
    "ull": (ULLONG,),
    "llu": (ULLONG,),
}
StdMode = Literal["c11", "gnu11"]


@dataclass(frozen=True)
class SemaError(ValueError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class VarSymbol:
    name: str
    type_: Type
    alignment: int | None = None


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
        if symbol.name in self._symbols or symbol.name in self._typedefs:
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


class Analyzer:
    def __init__(self, *, std: StdMode = "c11") -> None:
        self._std = std
        self._functions: dict[str, FunctionSymbol] = {}
        self._type_map = TypeMap()
        self._function_signatures: dict[str, FunctionSignature] = {}
        self._function_overloads: dict[str, list[FunctionSignature]] = {}
        self._overloadable_functions: set[str] = set()
        self._overload_expr_names: dict[Expr, str] = {}
        self._overload_expr_ids: dict[int, str] = {}
        self._defined_functions: set[str] = set()
        self._record_definitions: dict[str, tuple[RecordMemberInfo, ...]] = {}
        self._seen_record_definitions: set[int] = set()
        self._file_scope = Scope()
        self._loop_depth = 0
        self._switch_stack: list[SwitchContext] = []
        self._function_labels: set[str] = set()
        self._pending_goto_labels: list[str] = []
        self._current_return_type: Type | None = None

    def analyze(self, unit: TranslationUnit) -> SemaUnit:
        externals = unit.externals or [*unit.declarations, *unit.functions]
        for external in externals:
            if isinstance(external, FunctionDef):
                self._register_function_external(external)
                continue
            self._analyze_file_scope_decl(external)
        for external in externals:
            if isinstance(external, FunctionDef) and external.body is not None:
                self._analyze_function(external)
        return SemaUnit(self._functions, self._type_map)

    def _register_function_external(self, func: FunctionDef) -> None:
        if func.storage_class not in {None, "static", "extern"}:
            raise SemaError("Invalid storage class for function")
        if func.is_thread_local:
            raise SemaError("Invalid declaration specifier")
        if self._file_scope.lookup(func.name) is not None:
            raise SemaError(f"Conflicting declaration: {func.name}")
        if self._file_scope.lookup_typedef(func.name) is not None:
            raise SemaError(f"Conflicting declaration: {func.name}")
        signature = self._signature_from(func)
        existing = self._function_signatures.get(func.name)
        if existing is None:
            self._function_signatures[func.name] = signature
            if func.is_overloadable:
                self._overloadable_functions.add(func.name)
                self._add_function_overload(func.name, signature)
        else:
            if not self._signatures_compatible(existing, signature):
                if not self._is_compatible_overloadable_redeclaration(func):
                    raise SemaError(f"Conflicting declaration: {func.name}")
                self._add_function_overload(func.name, signature)
            else:
                merged_signature = self._merge_signature(existing, signature, func.name)
                self._function_signatures[func.name] = merged_signature
                if func.is_overloadable:
                    self._overloadable_functions.add(func.name)
                    self._add_function_overload(func.name, merged_signature)
        if func.body is not None:
            if func.name in self._defined_functions:
                raise SemaError(f"Duplicate function definition: {func.name}")
            self._defined_functions.add(func.name)

    def _is_compatible_overloadable_redeclaration(self, func: FunctionDef) -> bool:
        return (
            func.is_overloadable
            and func.name in self._overloadable_functions
            and func.body is None
            and func.name not in self._defined_functions
        )

    def _add_function_overload(self, name: str, signature: FunctionSignature) -> None:
        overloads = self._function_overloads.setdefault(name, [])
        if signature not in overloads:
            overloads.append(signature)

    def _set_overload_expr_name(self, expr: Expr, name: str) -> None:
        with suppress(TypeError):
            self._overload_expr_names[expr] = name
            return
        self._overload_expr_ids[id(expr)] = name

    def _get_overload_expr_name(self, expr: Expr) -> str | None:
        try:
            hash(expr)
        except TypeError:
            return self._overload_expr_ids.get(id(expr))
        return self._overload_expr_names.get(expr)

    def _signature_matches_callable_type(
        self,
        signature: FunctionSignature,
        target_type: Type,
    ) -> bool:
        callable_signature = target_type.callable_signature()
        if callable_signature is None:
            return False
        return_type, params = callable_signature
        parameter_types, is_variadic = params
        return (
            signature.return_type == return_type
            and signature.params == parameter_types
            and signature.is_variadic == is_variadic
        )

    def _resolve_overload_for_cast(
        self,
        overload_name: str,
        target_type: Type,
    ) -> FunctionSignature | None:
        overloads = self._function_overloads.get(overload_name)
        if not overloads:
            return None
        matches = [
            signature
            for signature in overloads
            if self._signature_matches_callable_type(signature, target_type)
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    def _merge_signature(
        self,
        existing: FunctionSignature,
        incoming: FunctionSignature,
        name: str,
    ) -> FunctionSignature:
        if not self._signatures_compatible(existing, incoming):
            raise SemaError(f"Conflicting declaration: {name}")
        if existing.params is None and incoming.params is not None:
            return incoming
        return existing

    def _signatures_compatible(
        self,
        existing: FunctionSignature,
        incoming: FunctionSignature,
    ) -> bool:
        if existing.return_type != incoming.return_type:
            return False
        if existing.params is None or incoming.params is None:
            return True
        return existing.params == incoming.params and existing.is_variadic == incoming.is_variadic

    def _analyze_function(self, func: FunctionDef) -> None:
        return_type = self._function_signatures[func.name].return_type
        assert func.body is not None
        scope = Scope(self._file_scope)
        self._function_labels = set()
        self._pending_goto_labels = []
        previous_return_type = self._current_return_type
        self._current_return_type = return_type
        try:
            self._define_params(func.params, scope)
            self._analyze_compound(func.body, scope, return_type)
            for label in self._pending_goto_labels:
                if label not in self._function_labels:
                    raise SemaError(f"Undefined label: {label}")
            self._functions[func.name] = FunctionSymbol(func.name, return_type, scope.symbols)
        finally:
            self._current_return_type = previous_return_type

    def _define_params(self, params: list[Param], scope: Scope) -> None:
        for param in params:
            if param.name is None:
                raise SemaError("Missing parameter name")
            param_type = self._resolve_param_type(param.type_spec)
            scope.define(VarSymbol(param.name, param_type))

    def _analyze_file_scope_decl(self, declaration: Stmt) -> None:
        if isinstance(declaration, DeclGroupStmt):
            for grouped_decl in declaration.declarations:
                self._analyze_file_scope_decl(grouped_decl)
            return
        if isinstance(declaration, TypedefDecl):
            if declaration.name in self._function_signatures:
                raise SemaError(f"Conflicting declaration: {declaration.name}")
            self._register_type_spec(declaration.type_spec)
            if self._is_invalid_atomic_type_spec(declaration.type_spec):
                raise SemaError("Invalid atomic type")
            self._define_enum_members(declaration.type_spec, self._file_scope)
            typedef_type = self._resolve_type(declaration.type_spec)
            self._ensure_array_size_limit(typedef_type)
            self._file_scope.define_typedef(declaration.name, typedef_type)
            return
        if isinstance(declaration, DeclStmt):
            if declaration.storage_class in {"auto", "register"}:
                raise SemaError("Invalid storage class for file-scope declaration")
            self._register_type_spec(declaration.type_spec)
            self._define_enum_members(declaration.type_spec, self._file_scope)
            if declaration.alignment is not None and declaration.name is None:
                raise SemaError("Invalid alignment specifier")
            if declaration.name is None:
                if declaration.storage_class is not None or declaration.is_thread_local:
                    raise SemaError("Expected identifier")
                return
            if declaration.name in self._function_signatures:
                raise SemaError(f"Conflicting declaration: {declaration.name}")
            if self._is_invalid_atomic_type_spec(declaration.type_spec):
                raise SemaError("Invalid object type: atomic")
            if self._is_invalid_void_object_type(declaration.type_spec):
                raise SemaError("Invalid object type: void")
            if self._is_invalid_incomplete_record_object_type(declaration.type_spec):
                raise SemaError("Invalid object type: incomplete")
            if self._is_file_scope_vla_type_spec(declaration.type_spec):
                raise SemaError("Variable length array not allowed at file scope")
            var_type = self._resolve_type(declaration.type_spec)
            var_alignment = self._alignof_type(var_type)
            if not self._is_valid_explicit_alignment(declaration.alignment, var_alignment):
                raise SemaError("Invalid alignment specifier")
            self._ensure_array_size_limit(var_type)
            self._file_scope.define(
                VarSymbol(
                    declaration.name,
                    var_type,
                    declaration.alignment if declaration.alignment is not None else var_alignment,
                )
            )
            if declaration.init is not None:
                if declaration.storage_class == "extern":
                    raise SemaError("Extern declaration cannot have initializer")
                self._analyze_initializer(var_type, declaration.init, self._file_scope)
            return
        if isinstance(declaration, StaticAssertDecl):
            self._check_static_assert(declaration, self._file_scope)
            return
        raise SemaError(f"Unsupported file-scope declaration node: {type(declaration).__name__}")

    def _signature_from(self, func: FunctionDef) -> FunctionSignature:
        if not func.has_prototype:
            if func.is_variadic:
                raise SemaError("Variadic function requires a prototype")
            if self._is_invalid_atomic_type_spec(func.return_type):
                raise SemaError("Invalid return type: atomic")
            if self._is_invalid_incomplete_record_object_type(func.return_type):
                raise SemaError("Invalid return type: incomplete")
            return FunctionSignature(self._resolve_type(func.return_type), None, False)
        params: list[Type] = []
        for param in func.params:
            if self._is_invalid_atomic_type_spec(param.type_spec):
                raise SemaError("Invalid parameter type: atomic")
            if self._is_invalid_void_parameter_type(param.type_spec):
                raise SemaError("Invalid parameter type: void")
            if self._is_invalid_incomplete_record_object_type(param.type_spec):
                raise SemaError("Invalid parameter type: incomplete")
            params.append(self._resolve_param_type(param.type_spec))
        if self._is_invalid_atomic_type_spec(func.return_type):
            raise SemaError("Invalid return type: atomic")
        if self._is_invalid_incomplete_record_object_type(func.return_type):
            raise SemaError("Invalid return type: incomplete")
        return FunctionSignature(
            self._resolve_type(func.return_type),
            tuple(params),
            func.is_variadic,
        )

    def _record_key(self, kind: str, tag: str) -> str:
        return f"{kind} {tag}"

    def _record_type_name(self, type_spec: TypeSpec) -> str:
        if type_spec.record_tag is not None:
            return self._record_key(type_spec.name, type_spec.record_tag)
        return f"{type_spec.name} <anon:{id(type_spec)}>"

    def _normalize_record_members(
        self,
        members: tuple[RecordMemberInfo, ...] | tuple[tuple[str | None, Type], ...],
    ) -> tuple[RecordMemberInfo, ...]:
        if all(isinstance(member, RecordMemberInfo) for member in members):
            return members  # type: ignore[return-value]
        normalized: list[RecordMemberInfo] = []
        for member in members:
            if isinstance(member, RecordMemberInfo):
                normalized.append(member)
                continue
            if isinstance(member, tuple) and len(member) == 2:
                normalized.append(RecordMemberInfo(member[0], member[1]))
                continue
            if isinstance(member, tuple) and len(member) == 3:
                normalized.append(RecordMemberInfo(member[0], member[1], member[2]))
                continue
            raise TypeError("Invalid record member")
        return tuple(normalized)

    def _record_members(self, record_name: str) -> tuple[RecordMemberInfo, ...] | None:
        members = self._record_definitions.get(record_name)
        if members is None:
            return None
        normalized = self._normalize_record_members(members)
        if normalized is not members:
            self._record_definitions[record_name] = normalized
        return normalized

    def _register_type_spec(self, type_spec: TypeSpec) -> None:
        if type_spec.name not in {"struct", "union"} or not type_spec.record_members:
            return
        spec_id = id(type_spec)
        if spec_id in self._seen_record_definitions:
            return
        self._seen_record_definitions.add(spec_id)
        seen_members: set[str] = set()
        member_types: list[RecordMemberInfo] = []
        for member in type_spec.record_members:
            member_spec = member.type_spec
            member_name = member.name
            if member_name is not None and member_name in seen_members:
                raise SemaError(f"Duplicate declaration: {member_name}")
            if member_name is not None:
                seen_members.add(member_name)
            if self._is_invalid_void_object_type(member_spec):
                raise SemaError("Invalid member type")
            if self._is_invalid_atomic_type_spec(member_spec):
                raise SemaError("Invalid member type")
            if self._is_function_object_type(member_spec):
                raise SemaError("Invalid member type")
            if self._is_invalid_incomplete_record_object_type(member_spec):
                raise SemaError("Invalid member type")
            resolved_member_type = self._resolve_type(member_spec)
            bit_width: int | None = None
            if member.bit_width_expr is not None:
                if not self._is_integer_type(resolved_member_type):
                    raise SemaError("Bit-field type must be integer")
                bit_width = self._eval_int_constant_expr(member.bit_width_expr, self._file_scope)
                if bit_width is None:
                    raise SemaError("Bit-field width is not integer constant")
                if bit_width < 0:
                    raise SemaError("Bit-field width must be non-negative")
                max_width = self._sizeof_type(resolved_member_type)
                assert max_width is not None
                if bit_width > max_width * 8:
                    raise SemaError("Bit-field width exceeds type width")
                if member_name is None and bit_width != 0:
                    raise SemaError("Unnamed bit-field must have zero width")
            natural_alignment = self._alignof_type(resolved_member_type)
            if not self._is_valid_explicit_alignment(member.alignment, natural_alignment):
                raise SemaError("Invalid alignment specifier")
            member_types.append(
                RecordMemberInfo(
                    member_name,
                    resolved_member_type,
                    member.alignment,
                    bit_width,
                )
            )
        key = self._record_type_name(type_spec)
        if key in self._record_definitions:
            raise SemaError(f"Duplicate definition: {key}")
        self._record_definitions[key] = tuple(member_types)

    def _resolve_type(self, type_spec: TypeSpec) -> Type:
        self._register_type_spec(type_spec)
        is_unqualified_scalar = not type_spec.declarator_ops and not type_spec.qualifiers
        if type_spec.name == "int" and is_unqualified_scalar:
            return INT
        if type_spec.name == "char" and is_unqualified_scalar:
            return CHAR
        if type_spec.name == "unsigned char" and is_unqualified_scalar:
            return UCHAR
        if type_spec.name == "_Bool" and is_unqualified_scalar:
            return BOOL
        if type_spec.name == "short" and is_unqualified_scalar:
            return SHORT
        if type_spec.name == "unsigned short" and is_unqualified_scalar:
            return USHORT
        if type_spec.name == "long" and is_unqualified_scalar:
            return LONG
        if type_spec.name == "unsigned long" and is_unqualified_scalar:
            return ULONG
        if type_spec.name == "long long" and is_unqualified_scalar:
            return LLONG
        if type_spec.name == "unsigned long long" and is_unqualified_scalar:
            return ULLONG
        if type_spec.name == "float" and is_unqualified_scalar:
            return FLOAT
        if type_spec.name == "double" and is_unqualified_scalar:
            return DOUBLE
        if type_spec.name == "long double" and is_unqualified_scalar:
            return LONGDOUBLE
        if type_spec.name == "unsigned int" and is_unqualified_scalar:
            return UINT
        if type_spec.name == "void" and is_unqualified_scalar:
            return VOID
        if type_spec.name == "enum" and is_unqualified_scalar:
            return INT
        if type_spec.name in {"struct", "union"} and not type_spec.declarator_ops:
            return Type(self._record_type_name(type_spec), qualifiers=type_spec.qualifiers)
        resolved_ops: list[tuple[str, int | tuple[tuple[Type, ...] | None, bool]]] = []
        for kind, value in type_spec.declarator_ops:
            if kind != "fn":
                if kind == "arr":
                    resolved_ops.append(("arr", self._resolve_array_bound(value)))
                    continue
                assert isinstance(value, int)
                resolved_ops.append((kind, value))
                continue
            assert isinstance(value, tuple) and len(value) == 2
            resolved_params = self._resolve_function_param_types(
                cast(tuple[tuple[TypeSpec, ...] | None, bool], value)
            )
            resolved_ops.append((kind, resolved_params))
        if type_spec.name == "enum":
            base_name = "int"
        elif type_spec.name in {"struct", "union"}:
            base_name = self._record_type_name(type_spec)
        else:
            base_name = type_spec.name
        return Type(base_name, declarator_ops=tuple(resolved_ops), qualifiers=type_spec.qualifiers)

    def _resolve_array_bound(self, value: object) -> int:
        if isinstance(value, int):
            return value
        if not isinstance(value, ArrayDecl):
            return -1
        if value.length is None:
            return -1
        if isinstance(value.length, int):
            return value.length
        evaluated = self._eval_int_constant_expr(value.length, self._file_scope)
        if evaluated is None:
            return -1
        return evaluated

    def _resolve_function_param_types(
        self,
        declarator_value: int | tuple[tuple[TypeSpec, ...] | None, bool],
    ) -> tuple[tuple[Type, ...] | None, bool]:
        assert isinstance(declarator_value, tuple) and len(declarator_value) == 2
        param_specs, is_variadic = declarator_value
        if param_specs is None:
            if is_variadic:
                raise SemaError("Variadic function requires a prototype")
            return None, False
        params: list[Type] = []
        for param_spec in param_specs:
            if self._is_invalid_atomic_type_spec(param_spec):
                raise SemaError("Invalid parameter type: atomic")
            if self._is_invalid_void_parameter_type(param_spec):
                raise SemaError("Invalid parameter type: void")
            if self._is_invalid_incomplete_record_object_type(param_spec):
                raise SemaError("Invalid parameter type: incomplete")
            params.append(self._resolve_param_type(param_spec))
        return tuple(params), is_variadic

    def _resolve_param_type(self, type_spec: TypeSpec) -> Type:
        resolved = self._resolve_type(type_spec)
        return resolved.decay_parameter_type()

    def _define_enum_members(self, type_spec: TypeSpec, scope: Scope) -> None:
        next_value = 0
        for name, expr in type_spec.enum_members:
            value = next_value
            if expr is not None:
                value = self._eval_int_constant_expr(expr, scope)
                if value is None:
                    raise SemaError("Enumerator value is not integer constant")
            scope.define(EnumConstSymbol(name, value))
            next_value = value + 1

    def _is_function_object_type(self, type_spec: TypeSpec) -> bool:
        return bool(type_spec.declarator_ops) and type_spec.declarator_ops[0][0] == "fn"

    def _is_invalid_atomic_type_spec(self, type_spec: TypeSpec) -> bool:
        if not type_spec.is_atomic:
            return False
        target = type_spec.atomic_target if type_spec.atomic_target is not None else type_spec
        return (
            self._is_invalid_void_object_type(target)
            or self._is_invalid_incomplete_record_object_type(target)
            or self._is_function_object_type(target)
            or (bool(target.declarator_ops) and target.declarator_ops[0][0] == "arr")
        )

    def _is_invalid_incomplete_record_object_type(self, type_spec: TypeSpec) -> bool:
        if type_spec.name not in {"struct", "union"}:
            return False
        if any(kind == "ptr" for kind, _ in type_spec.declarator_ops):
            return False
        if type_spec.record_members:
            return False
        if type_spec.record_tag is None:
            return True
        key = self._record_key(type_spec.name, type_spec.record_tag)
        return key not in self._record_definitions

    def _is_record_name(self, name: str) -> bool:
        return name.startswith("struct ") or name.startswith("union ")

    def _lookup_record_member(self, record_type: Type, member_name: str) -> Type:
        members = self._record_members(record_type.name)
        if members is None:
            raise SemaError("Member access on incomplete type")
        for member in members:
            if member.name == member_name:
                return member.type_
        raise SemaError(f"No such member: {member_name}")

    def _resolve_member_type(
        self,
        base_type: Type,
        member_name: str,
        through_pointer: bool,
    ) -> Type:
        if through_pointer:
            base_value_type = self._decay_array_value(base_type)
            record_type = base_value_type.pointee()
            if (
                record_type is None
                or record_type.declarator_ops
                or not self._is_record_name(record_type.name)
            ):
                raise SemaError("Member access on non-record pointer")
            return self._lookup_record_member(record_type, member_name)
        if base_type.declarator_ops or not self._is_record_name(base_type.name):
            raise SemaError("Member access on non-record type")
        return self._lookup_record_member(base_type, member_name)

    def _is_invalid_sizeof_type_spec(self, type_spec: TypeSpec) -> bool:
        return (
            self._is_invalid_atomic_type_spec(type_spec)
            or self._is_invalid_void_object_type(type_spec)
            or self._is_invalid_incomplete_record_object_type(type_spec)
            or self._is_function_object_type(type_spec)
        )

    def _is_invalid_sizeof_type(self, type_: Type) -> bool:
        if type_ == VOID:
            return True
        if type_.declarator_ops and type_.declarator_ops[0][0] == "fn":
            return True
        if self._is_record_name(type_.name) and not any(
            kind == "ptr" for kind, _ in type_.declarator_ops
        ):
            return type_.name not in self._record_definitions
        return False

    def _is_invalid_alignof_type_spec(self, type_spec: TypeSpec) -> bool:
        return self._is_invalid_sizeof_type_spec(type_spec)

    def _is_invalid_alignof_type(self, type_: Type) -> bool:
        return self._is_invalid_sizeof_type(type_)

    def _is_invalid_generic_association_type_spec(self, type_spec: TypeSpec) -> bool:
        return self._is_invalid_sizeof_type_spec(type_spec) or self._is_variably_modified_type_spec(
            type_spec
        )

    def _is_variably_modified_type_spec(self, type_spec: TypeSpec) -> bool:
        for kind, value in type_spec.declarator_ops:
            if kind != "arr":
                continue
            if isinstance(value, int):
                if value < 0:
                    return True
                continue
            if not isinstance(value, ArrayDecl):
                return True
            if value.length is None:
                return True
            if isinstance(value.length, int):
                continue
            if self._eval_int_constant_expr(value.length, self._file_scope) is None:
                return True
        return False

    def _is_valid_explicit_alignment(
        self,
        alignment: int | None,
        natural_alignment: int | None,
    ) -> bool:
        if alignment is None:
            return True
        if alignment <= 0 or (alignment & (alignment - 1)) != 0:
            return False
        return natural_alignment is not None and alignment >= natural_alignment

    def _is_integer_type(self, type_: Type) -> bool:
        return type_.declarator_ops == () and type_.name in {
            INT.name,
            UINT.name,
            SHORT.name,
            USHORT.name,
            LONG.name,
            ULONG.name,
            LLONG.name,
            ULLONG.name,
            CHAR.name,
            UCHAR.name,
            BOOL.name,
        }

    def _is_const_qualified(self, type_: Type) -> bool:
        return "const" in type_.qualifiers

    def _is_floating_type(self, type_: Type) -> bool:
        return type_.declarator_ops == () and type_.name in {
            FLOAT.name,
            DOUBLE.name,
            LONGDOUBLE.name,
        }

    def _is_arithmetic_type(self, type_: Type) -> bool:
        return self._is_integer_type(type_) or self._is_floating_type(type_)

    def _unqualified_type(self, type_: Type) -> Type:
        if not type_.qualifiers:
            return type_
        return Type(type_.name, declarator_ops=type_.declarator_ops)

    def _integer_rank(self, type_: Type) -> int:
        return _INTEGER_TYPE_RANKS[self._unqualified_type(type_).name]

    def _is_signed_integer_type(self, type_: Type) -> bool:
        unqualified = self._unqualified_type(type_)
        return self._is_integer_type(unqualified) and unqualified.name in _SIGNED_INTEGER_NAMES

    def _integer_promotion(self, type_: Type) -> Type:
        unqualified = self._unqualified_type(type_)
        if not self._is_integer_type(unqualified):
            return unqualified
        promoted = _INTEGER_PROMOTION_TYPES.get(unqualified.name)
        if promoted is not None:
            return promoted
        return _CANONICAL_INTEGER_TYPES[unqualified.name]

    def _signed_range(self, type_: Type) -> tuple[int, int] | None:
        return _SIGNED_INTEGER_TYPE_LIMITS.get(self._unqualified_type(type_))

    def _unsigned_max(self, type_: Type) -> int | None:
        return _UNSIGNED_INTEGER_TYPE_LIMITS.get(self._unqualified_type(type_))

    def _signed_can_represent_unsigned(self, signed: Type, unsigned: Type) -> bool:
        signed_range = self._signed_range(signed)
        unsigned_max = self._unsigned_max(unsigned)
        return (
            signed_range is not None
            and unsigned_max is not None
            and signed_range[1] >= unsigned_max
        )

    def _usual_arithmetic_conversion(self, left_type: Type, right_type: Type) -> Type | None:
        left_type = self._unqualified_type(left_type)
        right_type = self._unqualified_type(right_type)
        if self._is_floating_type(left_type) or self._is_floating_type(right_type):
            if left_type.name == LONGDOUBLE.name or right_type.name == LONGDOUBLE.name:
                return LONGDOUBLE
            if left_type.name == DOUBLE.name or right_type.name == DOUBLE.name:
                return DOUBLE
            return FLOAT
        if not self._is_integer_type(left_type) or not self._is_integer_type(right_type):
            return None
        left = self._integer_promotion(left_type)
        right = self._integer_promotion(right_type)
        if left == right:
            return left
        left_signed = self._is_signed_integer_type(left)
        right_signed = self._is_signed_integer_type(right)
        if left_signed == right_signed:
            return left if self._integer_rank(left) >= self._integer_rank(right) else right
        signed_type = left if left_signed else right
        unsigned_type = right if left_signed else left
        if self._integer_rank(unsigned_type) >= self._integer_rank(signed_type):
            return unsigned_type
        if self._signed_can_represent_unsigned(signed_type, unsigned_type):
            return signed_type
        return _UNSIGNED_COUNTERPARTS[signed_type.name]

    def _is_void_pointer_type(self, type_: Type) -> bool:
        pointee = type_.pointee()
        return pointee is not None and pointee.declarator_ops == () and pointee.name == VOID.name

    def _is_compatible_pointee_type(self, left_type: Type, right_type: Type) -> bool:
        return (
            left_type.name == right_type.name
            and left_type.declarator_ops == right_type.declarator_ops
        )

    def _merged_qualifiers(self, left_type: Type, right_type: Type) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*left_type.qualifiers, *right_type.qualifiers)))

    def _qualifiers_contain(self, target_type: Type, value_type: Type) -> bool:
        return set(value_type.qualifiers).issubset(target_type.qualifiers)

    def _is_object_pointer_type(self, type_: Type) -> bool:
        pointee = type_.pointee()
        return pointee is not None and not (
            pointee.declarator_ops and pointee.declarator_ops[0][0] == "fn"
        )

    def _is_assignment_compatible(self, target_type: Type, value_type: Type) -> bool:
        if target_type == value_type:
            return True
        if self._is_arithmetic_type(target_type) and self._is_arithmetic_type(value_type):
            return True
        target_pointee = target_type.pointee()
        value_pointee = value_type.pointee()
        if target_pointee is None or value_pointee is None:
            return False
        if self._is_pointer_conversion_compatible(target_type, value_type):
            return True
        if self._is_void_pointer_type(target_type):
            return self._is_object_pointer_type(value_type) and self._qualifiers_contain(
                target_pointee,
                value_pointee,
            )
        if self._is_void_pointer_type(value_type):
            return self._is_object_pointer_type(target_type) and self._qualifiers_contain(
                target_pointee,
                value_pointee,
            )
        return False

    def _is_pointer_conversion_compatible(self, target_type: Type, value_type: Type) -> bool:
        target_pointee = target_type.pointee()
        value_pointee = value_type.pointee()
        if target_pointee is None or value_pointee is None:
            return False
        if not self._is_compatible_pointee_type(target_pointee, value_pointee):
            return False
        if not self._qualifiers_contain(target_pointee, value_pointee):
            return False
        return not self._has_nested_pointer_qualifier_mismatch(target_pointee, value_pointee)

    def _has_nested_pointer_qualifier_mismatch(self, left_type: Type, right_type: Type) -> bool:
        # Qualifier addition on nested pointers is rejected until pointer-level
        # qualifiers are modeled structurally.
        return left_type.pointee() is not None and left_type.qualifiers != right_type.qualifiers

    def _is_null_pointer_constant(self, expr: Expr, scope: Scope) -> bool:
        if self._eval_int_constant_expr(expr, scope) == 0:
            return True
        if not isinstance(expr, CastExpr):
            return False
        cast_type = self._type_map.get(expr)
        if cast_type is None:
            cast_type = self._resolve_type(expr.type_spec)
        return self._is_void_pointer_type(cast_type) and self._is_null_pointer_constant(
            expr.expr, scope
        )

    def _is_assignment_expr_compatible(
        self,
        target_type: Type,
        value_expr: Expr,
        value_type: Type,
        scope: Scope,
    ) -> bool:
        return self._is_assignment_compatible(target_type, value_type) or (
            target_type.pointee() is not None and self._is_null_pointer_constant(value_expr, scope)
        )

    def _is_initializer_compatible(
        self,
        target_type: Type,
        init_expr: Expr,
        init_type: Type,
        scope: Scope,
    ) -> bool:
        return self._is_char_array_string_initializer(target_type, init_expr) or (
            self._is_assignment_expr_compatible(target_type, init_expr, init_type, scope)
        )

    def _analyze_initializer(
        self,
        target_type: Type,
        initializer: Expr | InitList,
        scope: Scope,
    ) -> None:
        if isinstance(initializer, InitList):
            self._analyze_initializer_list(target_type, initializer, scope)
            return
        init_type = self._decay_array_value(self._analyze_expr(initializer, scope))
        if not self._is_initializer_compatible(target_type, initializer, init_type, scope):
            raise SemaError("Initializer type mismatch")

    def _analyze_initializer_list(self, target_type: Type, init: InitList, scope: Scope) -> None:
        if target_type.is_array():
            self._analyze_array_initializer_list(target_type, init, scope)
            return
        if self._is_record_name(target_type.name) and not target_type.declarator_ops:
            self._analyze_record_initializer_list(target_type, init, scope)
            return
        if len(init.items) != 1:
            raise SemaError("Initializer type mismatch")
        item = init.items[0]
        if item.designators:
            raise SemaError("Initializer type mismatch")
        self._analyze_initializer(target_type, item.initializer, scope)

    def _analyze_array_initializer_list(
        self,
        target_type: Type,
        init: InitList,
        scope: Scope,
    ) -> None:
        assert target_type.declarator_ops and target_type.declarator_ops[0][0] == "arr"
        _, length_value = target_type.declarator_ops[0]
        assert isinstance(length_value, int)
        length = length_value
        element_type = target_type.element_type()
        assert element_type is not None
        next_index = 0
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind != "index":
                    raise SemaError("Initializer type mismatch")
                assert isinstance(value, Expr)
                index = self._eval_initializer_index(value, scope)
                if index < 0 or index >= length:
                    raise SemaError("Initializer index out of range")
                self._analyze_designated_initializer(
                    element_type,
                    item.designators[1:],
                    item.initializer,
                    scope,
                )
                next_index = index + 1
                continue
            if next_index >= length:
                raise SemaError("Initializer index out of range")
            self._analyze_initializer(element_type, item.initializer, scope)
            next_index += 1

    def _analyze_record_initializer_list(
        self,
        target_type: Type,
        init: InitList,
        scope: Scope,
    ) -> None:
        all_members = self._record_members(target_type.name)
        members = (
            None if all_members is None else tuple(m for m in all_members if m.name is not None)
        )
        if members is None or not members:
            raise SemaError("Initializer type mismatch")
        is_union = target_type.name.startswith("union ")
        next_member = 0
        initialized_union = False
        for item in init.items:
            if item.designators:
                kind, value = item.designators[0]
                if kind != "member" or not isinstance(value, str):
                    raise SemaError("Initializer type mismatch")
                member_type, member_index = self._lookup_initializer_member(target_type, value)
                self._analyze_designated_initializer(
                    member_type,
                    item.designators[1:],
                    item.initializer,
                    scope,
                )
                if is_union:
                    initialized_union = True
                else:
                    next_member = member_index + 1
                continue
            if is_union:
                if initialized_union:
                    raise SemaError("Initializer type mismatch")
                self._analyze_initializer(members[0].type_, item.initializer, scope)
                initialized_union = True
                continue
            if next_member >= len(members):
                raise SemaError("Initializer type mismatch")
            self._analyze_initializer(members[next_member].type_, item.initializer, scope)
            next_member += 1

    def _analyze_designated_initializer(
        self,
        target_type: Type,
        designators: tuple[tuple[str, Expr | str], ...],
        initializer: Expr | InitList,
        scope: Scope,
    ) -> None:
        if not designators:
            self._analyze_initializer(target_type, initializer, scope)
            return
        kind, value = designators[0]
        if kind == "index":
            if not target_type.is_array():
                raise SemaError("Initializer type mismatch")
            assert isinstance(value, Expr)
            index = self._eval_initializer_index(value, scope)
            assert target_type.declarator_ops
            _, length_value = target_type.declarator_ops[0]
            assert isinstance(length_value, int)
            if index < 0 or index >= length_value:
                raise SemaError("Initializer index out of range")
            element_type = target_type.element_type()
            assert element_type is not None
            self._analyze_designated_initializer(
                element_type,
                designators[1:],
                initializer,
                scope,
            )
            return
        if kind != "member" or not isinstance(value, str):
            raise SemaError("Initializer type mismatch")
        member_type, _ = self._lookup_initializer_member(target_type, value)
        self._analyze_designated_initializer(
            member_type,
            designators[1:],
            initializer,
            scope,
        )

    def _lookup_initializer_member(self, record_type: Type, member_name: str) -> tuple[Type, int]:
        if record_type.declarator_ops or not self._is_record_name(record_type.name):
            raise SemaError("Initializer type mismatch")
        members = self._record_members(record_type.name)
        if members is None:
            raise SemaError("Initializer type mismatch")
        for index, member in enumerate(members):
            if member.name == member_name:
                return member.type_, index
        raise SemaError(f"No such member: {member_name}")

    def _eval_initializer_index(self, expr: Expr, scope: Scope) -> int:
        value = self._eval_int_constant_expr(expr, scope)
        if value is None:
            raise SemaError("Initializer index is not integer constant")
        return value

    def _check_static_assert(self, declaration: StaticAssertDecl, scope: Scope) -> None:
        self._analyze_expr(declaration.condition, scope)
        value = self._eval_int_constant_expr(declaration.condition, scope)
        if value is None:
            raise SemaError("Static assertion condition is not integer constant")
        if value == 0:
            message = self._static_assert_message(declaration.message)
            raise SemaError(f"Static assertion failed: {message}")

    def _static_assert_message(self, message: StringLiteral) -> str:
        body = self._string_literal_body(message.value)
        return message.value if body is None else body

    def _ensure_array_size_limit(self, type_: Type) -> None:
        if not type_.is_array():
            return
        size = self._sizeof_type(type_, _MAX_ARRAY_OBJECT_BYTES)
        if size is not None and size > _MAX_ARRAY_OBJECT_BYTES:
            raise SemaError("array is too large")

    def _sizeof_type(self, type_: Type, limit: int | None = None) -> int | None:
        if not type_.declarator_ops:
            return self._sizeof_object_base_type(type_, limit)
        kind, value = type_.declarator_ops[0]
        if kind == "ptr":
            return _POINTER_SIZE
        if kind == "fn":
            return None
        assert kind == "arr"
        assert isinstance(value, int)
        if value <= 0:
            return None
        element_type = Type(type_.name, declarator_ops=type_.declarator_ops[1:])
        element_size = self._sizeof_type(element_type, limit)
        if element_size is None:
            return None
        if limit is not None and element_size > limit // value:
            return limit + 1
        return element_size * value

    def _alignof_type(self, type_: Type) -> int | None:
        if not type_.declarator_ops:
            return self._alignof_object_base_type(type_)
        kind, _ = type_.declarator_ops[0]
        if kind == "ptr":
            return _POINTER_SIZE
        if kind == "fn":
            return None
        element_type = Type(type_.name, declarator_ops=type_.declarator_ops[1:])
        return self._alignof_type(element_type)

    def _sizeof_object_base_type(self, type_: Type, limit: int | None) -> int | None:
        base_size = _BASE_TYPE_SIZES.get(type_.name)
        if base_size is not None:
            return base_size
        if not self._is_record_name(type_.name):
            return None
        members = self._record_members(type_.name)
        if members is None:
            return None
        if type_.name.startswith("struct "):
            total = 0
            for member in members:
                member_limit = None if limit is None else limit - total
                member_size = self._sizeof_type(member.type_, member_limit)
                if member_size is None:
                    return None
                total += member_size
                if limit is not None and total > limit:
                    return limit + 1
            return total
        largest = 0
        for member in members:
            member_size = self._sizeof_type(member.type_, limit)
            if member_size is None:
                return None
            if member_size > largest:
                largest = member_size
            if limit is not None and largest > limit:
                return limit + 1
        return largest

    def _alignof_object_base_type(self, type_: Type) -> int | None:
        base_align = _BASE_TYPE_ALIGNMENTS.get(type_.name)
        if base_align is not None:
            return base_align
        if not self._is_record_name(type_.name):
            return None
        members = self._record_members(type_.name)
        if members is None:
            return None
        largest = 1
        for member in members:
            member_align = self._alignof_type(member.type_)
            if member_align is None:
                return None
            if member.alignment is not None and member.alignment > member_align:
                member_align = member.alignment
            if member_align > largest:
                largest = member_align
        return largest

    def _is_char_array_string_initializer(self, target_type: Type, init_expr: Expr) -> bool:
        if not target_type.is_array() or not isinstance(init_expr, StringLiteral):
            return False
        if target_type.element_type() != CHAR:
            return False
        required_length = self._string_literal_required_length(init_expr.value)
        if required_length is None:
            return False
        assert target_type.declarator_ops
        _, value = target_type.declarator_ops[0]
        assert isinstance(value, int)
        return required_length <= value

    def _string_literal_required_length(self, lexeme: str) -> int | None:
        body = self._string_literal_body(lexeme)
        return None if body is None else len(self._decode_escaped_units(body)) + 1

    def _string_literal_body(self, lexeme: str) -> str | None:
        if lexeme.startswith('"') and lexeme.endswith('"'):
            return lexeme[1:-1]
        if lexeme.startswith('u8"') and lexeme.endswith('"'):
            return lexeme[3:-1]
        return None

    def _is_scalar_type(self, type_: Type) -> bool:
        return self._is_arithmetic_type(type_) or (
            bool(type_.declarator_ops) and type_.declarator_ops[0][0] == "ptr"
        )

    def _analyze_additive_types(self, left_type: Type, right_type: Type, op: str) -> Type | None:
        arithmetic_result = self._usual_arithmetic_conversion(left_type, right_type)
        if arithmetic_result is not None:
            return arithmetic_result
        left_ptr = left_type.pointee()
        right_ptr = right_type.pointee()
        if op == "+":
            if left_ptr is not None and self._is_integer_type(right_type):
                return left_type
            if right_ptr is not None and self._is_integer_type(left_type):
                return right_type
            return None
        if left_ptr is not None and self._is_integer_type(right_type):
            return left_type
        if self._is_compatible_nonvoid_object_pointer_pair(left_type, right_type):
            return INT
        return None

    def _is_compatible_nonvoid_object_pointer_pair(self, left_type: Type, right_type: Type) -> bool:
        left_pointee = left_type.pointee()
        right_pointee = right_type.pointee()
        if left_pointee is None or right_pointee is None:
            return False
        if left_pointee.name == VOID.name or right_pointee.name == VOID.name:
            return False
        if left_pointee.declarator_ops and left_pointee.declarator_ops[0][0] == "fn":
            return False
        if right_pointee.declarator_ops and right_pointee.declarator_ops[0][0] == "fn":
            return False
        if self._has_nested_pointer_qualifier_mismatch(left_pointee, right_pointee):
            return False
        return self._is_compatible_pointee_type(left_pointee, right_pointee)

    def _is_pointer_relational_compatible(self, left_type: Type, right_type: Type) -> bool:
        return self._is_compatible_nonvoid_object_pointer_pair(left_type, right_type)

    def _is_pointer_equality_compatible(self, left_type: Type, right_type: Type) -> bool:
        return self._is_assignment_compatible(
            left_type, right_type
        ) or self._is_assignment_compatible(
            right_type,
            left_type,
        )

    def _conditional_pointer_result(
        self,
        then_expr: Expr,
        then_type: Type,
        else_expr: Expr,
        else_type: Type,
        scope: Scope,
    ) -> Type | None:
        then_pointee = then_type.pointee()
        else_pointee = else_type.pointee()
        if then_pointee is not None and self._is_null_pointer_constant(else_expr, scope):
            return then_type
        if else_pointee is not None and self._is_null_pointer_constant(then_expr, scope):
            return else_type
        if then_pointee is not None and else_pointee is not None:
            if self._is_compatible_pointee_type(
                then_pointee,
                else_pointee,
            ) and not self._has_nested_pointer_qualifier_mismatch(then_pointee, else_pointee):
                return Type(
                    then_type.name,
                    declarator_ops=then_type.declarator_ops,
                    qualifiers=self._merged_qualifiers(then_pointee, else_pointee),
                )
            if self._is_void_pointer_type(then_type) and self._is_object_pointer_type(else_type):
                return Type(
                    VOID.name,
                    declarator_ops=then_type.declarator_ops,
                    qualifiers=self._merged_qualifiers(then_pointee, else_pointee),
                )
            if self._is_void_pointer_type(else_type) and self._is_object_pointer_type(then_type):
                return Type(
                    VOID.name,
                    declarator_ops=else_type.declarator_ops,
                    qualifiers=self._merged_qualifiers(then_pointee, else_pointee),
                )
            return None
        return None

    def _is_invalid_cast_target(self, type_spec: TypeSpec, target_type: Type) -> bool:
        return (
            self._is_function_object_type(type_spec)
            or self._is_invalid_incomplete_record_object_type(type_spec)
            or (target_type != VOID and not self._is_scalar_type(target_type))
        )

    def _is_invalid_cast_operand(self, operand_type: Type, target_type: Type) -> bool:
        return target_type != VOID and (
            operand_type == VOID or not self._is_scalar_type(operand_type)
        )

    def _is_invalid_void_object_type(self, type_spec: TypeSpec) -> bool:
        return type_spec.name == "void" and not any(
            kind == "ptr" for kind, _ in type_spec.declarator_ops
        )

    def _is_invalid_void_parameter_type(self, type_spec: TypeSpec) -> bool:
        return type_spec.name == "void" and not type_spec.declarator_ops

    def _is_file_scope_vla_type_spec(self, type_spec: TypeSpec) -> bool:
        for kind, value in type_spec.declarator_ops:
            if kind != "arr":
                continue
            if isinstance(value, int):
                continue
            if not isinstance(value, ArrayDecl):
                return True
            if value.length is None:
                return True
            if isinstance(value.length, int):
                continue
            if self._eval_int_constant_expr(value.length, self._file_scope) is None:
                return True
        return False

    def _check_condition_type(self, condition_type: Type) -> None:
        if condition_type is VOID:
            raise SemaError("Condition must be non-void")
        if not self._is_scalar_type(self._decay_array_value(condition_type)):
            raise SemaError("Condition must be scalar")

    def _check_switch_condition_type(self, condition_type: Type) -> None:
        if condition_type is VOID:
            raise SemaError("Condition must be non-void")
        if not self._is_integer_type(self._decay_array_value(condition_type)):
            raise SemaError("Switch condition must be integer")

    def _analyze_compound(self, stmt: CompoundStmt, scope: Scope, return_type: Type) -> None:
        for item in stmt.statements:
            self._analyze_stmt(item, scope, return_type)

    def _analyze_stmt(self, stmt: Stmt, scope: Scope, return_type: Type) -> None:
        if isinstance(stmt, DeclGroupStmt):
            for grouped_decl in stmt.declarations:
                self._analyze_stmt(grouped_decl, scope, return_type)
            return
        if isinstance(stmt, DeclStmt):
            if stmt.storage_class == "typedef":
                raise SemaError("Invalid storage class for object declaration")
            if stmt.is_thread_local and stmt.storage_class not in {"static", "extern"}:
                raise SemaError("Invalid thread local storage class")
            self._register_type_spec(stmt.type_spec)
            self._define_enum_members(stmt.type_spec, scope)
            if stmt.alignment is not None and stmt.name is None:
                raise SemaError("Invalid alignment specifier")
            if stmt.name is None:
                if stmt.storage_class is not None or stmt.is_thread_local:
                    raise SemaError("Expected identifier")
                return
            if self._is_invalid_atomic_type_spec(stmt.type_spec):
                raise SemaError("Invalid object type: atomic")
            if self._is_invalid_void_object_type(stmt.type_spec):
                raise SemaError("Invalid object type: void")
            if self._is_invalid_incomplete_record_object_type(stmt.type_spec):
                raise SemaError("Invalid object type: incomplete")
            var_type = self._resolve_type(stmt.type_spec)
            var_alignment = self._alignof_type(var_type)
            if not self._is_valid_explicit_alignment(stmt.alignment, var_alignment):
                raise SemaError("Invalid alignment specifier")
            self._ensure_array_size_limit(var_type)
            scope.define(
                VarSymbol(
                    stmt.name,
                    var_type,
                    stmt.alignment if stmt.alignment is not None else var_alignment,
                )
            )
            if stmt.init is not None:
                if stmt.storage_class == "extern":
                    raise SemaError("Extern declaration cannot have initializer")
                self._analyze_initializer(var_type, stmt.init, scope)
            return
        if isinstance(stmt, StaticAssertDecl):
            self._check_static_assert(stmt, scope)
            return
        if isinstance(stmt, TypedefDecl):
            self._register_type_spec(stmt.type_spec)
            if self._is_invalid_atomic_type_spec(stmt.type_spec):
                raise SemaError("Invalid atomic type")
            self._define_enum_members(stmt.type_spec, scope)
            typedef_type = self._resolve_type(stmt.type_spec)
            self._ensure_array_size_limit(typedef_type)
            scope.define_typedef(stmt.name, typedef_type)
            return
        if isinstance(stmt, ExprStmt):
            self._analyze_expr(stmt.expr, scope)
            return
        if isinstance(stmt, ReturnStmt):
            if stmt.value is None:
                if return_type is not VOID:
                    raise SemaError("Non-void function must return a value")
                return
            if return_type is VOID:
                raise SemaError("Void function should not return a value")
            value_type = self._decay_array_value(self._analyze_expr(stmt.value, scope))
            if not self._is_assignment_expr_compatible(
                return_type,
                stmt.value,
                value_type,
                scope,
            ):
                raise SemaError("Return type mismatch")
            return
        if isinstance(stmt, ForStmt):
            inner_scope = Scope(scope)
            if isinstance(stmt.init, Stmt):
                self._analyze_stmt(stmt.init, inner_scope, return_type)
            elif isinstance(stmt.init, Expr):
                self._analyze_expr(stmt.init, inner_scope)
            if stmt.condition is not None:
                self._check_condition_type(self._analyze_expr(stmt.condition, inner_scope))
            if stmt.post is not None:
                self._analyze_expr(stmt.post, inner_scope)
            self._loop_depth += 1
            try:
                self._analyze_stmt(stmt.body, inner_scope, return_type)
            finally:
                self._loop_depth -= 1
            return
        if isinstance(stmt, SwitchStmt):
            self._check_switch_condition_type(self._analyze_expr(stmt.condition, scope))
            self._switch_stack.append(SwitchContext())
            try:
                self._analyze_stmt(stmt.body, scope, return_type)
            finally:
                self._switch_stack.pop()
            return
        if isinstance(stmt, CaseStmt):
            if not self._switch_stack:
                raise SemaError("case not in switch")
            case_value = self._eval_int_constant_expr(stmt.value, scope)
            if case_value is None:
                raise SemaError("case value is not integer constant")
            context = self._switch_stack[-1]
            case_key = str(case_value)
            if case_key in context.case_values:
                raise SemaError("Duplicate case value")
            context.case_values.add(case_key)
            self._analyze_stmt(stmt.body, scope, return_type)
            return
        if isinstance(stmt, DefaultStmt):
            if not self._switch_stack:
                raise SemaError("default not in switch")
            context = self._switch_stack[-1]
            if context.has_default:
                raise SemaError("Duplicate default label")
            context.has_default = True
            self._analyze_stmt(stmt.body, scope, return_type)
            return
        if isinstance(stmt, LabelStmt):
            if stmt.name in self._function_labels:
                raise SemaError(f"Duplicate label: {stmt.name}")
            self._function_labels.add(stmt.name)
            self._analyze_stmt(stmt.body, scope, return_type)
            return
        if isinstance(stmt, GotoStmt):
            self._pending_goto_labels.append(stmt.label)
            return
        if isinstance(stmt, IndirectGotoStmt):
            target_type = self._analyze_expr(stmt.target, scope)
            if target_type.pointee() is None:
                raise SemaError("Indirect goto target must be pointer")
            return
        if isinstance(stmt, CompoundStmt):
            inner_scope = Scope(scope)
            self._analyze_compound(stmt, inner_scope, return_type)
            return
        if isinstance(stmt, IfStmt):
            self._check_condition_type(self._analyze_expr(stmt.condition, scope))
            self._analyze_stmt(stmt.then_body, scope, return_type)
            if stmt.else_body is not None:
                self._analyze_stmt(stmt.else_body, scope, return_type)
            return
        if isinstance(stmt, WhileStmt):
            self._check_condition_type(self._analyze_expr(stmt.condition, scope))
            self._loop_depth += 1
            try:
                self._analyze_stmt(stmt.body, scope, return_type)
            finally:
                self._loop_depth -= 1
            return
        if isinstance(stmt, DoWhileStmt):
            self._loop_depth += 1
            try:
                self._analyze_stmt(stmt.body, scope, return_type)
                self._check_condition_type(self._analyze_expr(stmt.condition, scope))
            finally:
                self._loop_depth -= 1
            return
        if isinstance(stmt, BreakStmt):
            if self._loop_depth == 0 and not self._switch_stack:
                raise SemaError("break not in loop")
            return
        if isinstance(stmt, ContinueStmt):
            if self._loop_depth == 0:
                raise SemaError("continue not in loop")
            return
        if isinstance(stmt, NullStmt):
            return
        raise SemaError(f"Unsupported statement node: {type(stmt).__name__}")

    def _analyze_expr(self, expr: Expr, scope: Scope) -> Type:
        if isinstance(expr, FloatLiteral):
            literal_type = self._parse_float_literal_type(expr.value)
            self._type_map.set(expr, literal_type)
            return literal_type
        if isinstance(expr, IntLiteral):
            parsed = self._parse_int_literal(expr.value)
            if parsed is None:
                raise SemaError("Invalid integer literal")
            literal_type = parsed[1]
            self._type_map.set(expr, literal_type)
            return literal_type
        if isinstance(expr, CharLiteral):
            self._type_map.set(expr, INT)
            return INT
        if isinstance(expr, StringLiteral):
            string_type = CHAR.pointer_to()
            self._type_map.set(expr, string_type)
            return string_type
        if isinstance(expr, Identifier):
            symbol = scope.lookup(expr.name)
            if symbol is not None:
                self._type_map.set(expr, symbol.type_)
                return symbol.type_
            signature = self._function_signatures.get(expr.name)
            if signature is None:
                raise SemaError(f"Undeclared identifier: {expr.name}")
            overloads = self._function_overloads.get(expr.name)
            if overloads is not None and len(overloads) > 1:
                self._set_overload_expr_name(expr, expr.name)
            function_type = signature.return_type.function_of(
                signature.params,
                is_variadic=signature.is_variadic,
            )
            self._type_map.set(expr, function_type)
            return function_type
        if isinstance(expr, LabelAddressExpr):
            target_type = VOID.pointer_to()
            self._type_map.set(expr, target_type)
            return target_type
        if isinstance(expr, StatementExpr):
            if self._current_return_type is None:
                raise SemaError("Statement expression outside of a function")
            inner_scope = Scope(scope)
            result_type: Type = VOID
            result_overload: str | None = None
            for statement in expr.body.statements:
                if isinstance(statement, ExprStmt):
                    analyzed_type = self._analyze_expr(statement.expr, inner_scope)
                    result_type = self._decay_array_value(analyzed_type)
                    result_overload = self._get_overload_expr_name(statement.expr)
                    continue
                self._analyze_stmt(statement, inner_scope, self._current_return_type)
                result_type = VOID
                result_overload = None
            if result_overload is not None:
                self._set_overload_expr_name(expr, result_overload)
            self._type_map.set(expr, result_type)
            return result_type
        if isinstance(expr, SubscriptExpr):
            base_type = self._analyze_expr(expr.base, scope)
            index_type = self._analyze_expr(expr.index, scope)
            if not self._is_integer_type(index_type):
                raise SemaError("Array subscript is not an integer")
            element_type = base_type.element_type()
            if element_type is None:
                element_type = base_type.pointee()
            if element_type is None:
                raise SemaError("Subscripted value is not an array or pointer")
            self._type_map.set(expr, element_type)
            return element_type
        if isinstance(expr, MemberExpr):
            base_type = self._analyze_expr(expr.base, scope)
            member_type = self._resolve_member_type(base_type, expr.member, expr.through_pointer)
            self._type_map.set(expr, member_type)
            return member_type
        if isinstance(expr, SizeofExpr):
            if expr.type_spec is not None:
                self._register_type_spec(expr.type_spec)
                if self._is_invalid_sizeof_type_spec(expr.type_spec):
                    raise SemaError("Invalid sizeof operand")
                self._resolve_type(expr.type_spec)
            else:
                assert expr.expr is not None
                operand_type = self._analyze_expr(expr.expr, scope)
                if self._is_invalid_sizeof_type(operand_type):
                    raise SemaError("Invalid sizeof operand")
            self._type_map.set(expr, INT)
            return INT
        if isinstance(expr, AlignofExpr):
            if expr.type_spec is not None:
                self._register_type_spec(expr.type_spec)
                if self._is_invalid_alignof_type_spec(expr.type_spec):
                    raise SemaError("Invalid alignof operand")
                resolved = self._resolve_type(expr.type_spec)
                if self._alignof_type(resolved) is None:
                    raise SemaError("Invalid alignof operand")
            else:
                assert expr.expr is not None
                if self._std == "c11":
                    raise SemaError("Invalid alignof operand")
                operand_type = self._analyze_expr(expr.expr, scope)
                if self._is_invalid_alignof_type(operand_type):
                    raise SemaError("Invalid alignof operand")
                if self._alignof_type(operand_type) is None:
                    raise SemaError("Invalid alignof operand")
            self._type_map.set(expr, INT)
            return INT
        if isinstance(expr, CastExpr):
            self._register_type_spec(expr.type_spec)
            target_type = self._resolve_type(expr.type_spec)
            if self._is_invalid_cast_target(expr.type_spec, target_type):
                raise SemaError("Invalid cast")
            operand_type = self._decay_array_value(self._analyze_expr(expr.expr, scope))
            overload_name = self._get_overload_expr_name(expr.expr)
            if overload_name is not None:
                selected_signature = self._resolve_overload_for_cast(overload_name, target_type)
                if selected_signature is None:
                    raise SemaError("Invalid cast")
                operand_type = self._decay_array_value(
                    selected_signature.return_type.function_of(
                        selected_signature.params,
                        is_variadic=selected_signature.is_variadic,
                    )
                )
            if self._is_invalid_cast_operand(operand_type, target_type):
                raise SemaError("Invalid cast")
            self._type_map.set(expr, target_type)
            return target_type
        if isinstance(expr, CompoundLiteralExpr):
            self._register_type_spec(expr.type_spec)
            target_type = self._resolve_type(expr.type_spec)
            if self._is_invalid_void_object_type(expr.type_spec):
                raise SemaError("Invalid object type: void")
            if self._is_invalid_incomplete_record_object_type(expr.type_spec):
                raise SemaError("Invalid object type: incomplete")
            self._analyze_initializer(target_type, expr.initializer, scope)
            self._type_map.set(expr, target_type)
            return target_type
        if isinstance(expr, UnaryExpr):
            operand_type = self._analyze_expr(expr.operand, scope)
            value_operand_type = self._decay_array_value(operand_type)
            if expr.op in {"+", "-"}:
                if not self._is_arithmetic_type(value_operand_type):
                    message = (
                        "Unary plus operand must be arithmetic"
                        if expr.op == "+"
                        else "Unary minus operand must be arithmetic"
                    )
                    raise SemaError(message)
                result_type = (
                    self._integer_promotion(value_operand_type)
                    if self._is_integer_type(value_operand_type)
                    else value_operand_type
                )
                self._type_map.set(expr, result_type)
                return result_type
            if expr.op == "~":
                if not self._is_integer_type(value_operand_type):
                    raise SemaError("Bitwise not operand must be integer")
                result_type = self._integer_promotion(value_operand_type)
                self._type_map.set(expr, result_type)
                return result_type
            if expr.op == "!":
                if not self._is_scalar_type(value_operand_type):
                    raise SemaError("Logical not requires scalar operand")
                self._type_map.set(expr, INT)
                return INT
            if expr.op == "&":
                if not self._is_assignable(expr.operand):
                    raise SemaError("Address-of operand is not assignable")
                result = operand_type.pointer_to()
                self._type_map.set(expr, result)
                return result
            if expr.op == "*":
                pointee = value_operand_type.pointee()
                if pointee is None:
                    raise SemaError("Cannot dereference non-pointer")
                self._type_map.set(expr, pointee)
                return pointee
            raise SemaError(f"Unsupported unary operator: {expr.op}")
        if isinstance(expr, UpdateExpr):
            if expr.op not in {"++", "--"}:
                raise SemaError(f"Unsupported update operator: {expr.op}")
            if isinstance(expr.operand, Identifier):
                target_symbol = scope.lookup(expr.operand.name)
                if isinstance(target_symbol, EnumConstSymbol):
                    raise SemaError("Assignment target is not assignable")
            if not self._is_assignable(expr.operand):
                raise SemaError("Assignment target is not assignable")
            operand_type = self._analyze_expr(expr.operand, scope)
            if self._is_const_qualified(operand_type):
                raise SemaError("Assignment target is not assignable")
            if operand_type.is_array():
                raise SemaError("Assignment target is not assignable")
            value_operand_type = self._decay_array_value(operand_type)
            if (
                not self._is_integer_type(value_operand_type)
                and value_operand_type.pointee() is None
            ):
                raise SemaError("Update operand must be integer or pointer")
            self._type_map.set(expr, operand_type)
            return operand_type
        if isinstance(expr, BinaryExpr):
            left_type = self._decay_array_value(self._analyze_expr(expr.left, scope))
            right_type = self._decay_array_value(self._analyze_expr(expr.right, scope))
            if expr.op in {"+", "-"}:
                result_type = self._analyze_additive_types(left_type, right_type, expr.op)
                if result_type is None:
                    if expr.op == "+":
                        raise SemaError("Addition operands must be arithmetic or pointer/integer")
                    raise SemaError(
                        "Subtraction operands must be arithmetic, pointer/integer, "
                        "or compatible pointers"
                    )
                self._type_map.set(expr, result_type)
                return result_type
            if expr.op == "*":
                if not self._is_arithmetic_type(left_type):
                    raise SemaError("Multiplication left operand must be arithmetic")
                if not self._is_arithmetic_type(right_type):
                    raise SemaError("Multiplication right operand must be arithmetic")
                result_type = self._usual_arithmetic_conversion(left_type, right_type)
                assert result_type is not None
                self._type_map.set(expr, result_type)
                return result_type
            if expr.op == "/":
                if not self._is_arithmetic_type(left_type):
                    raise SemaError("Division left operand must be arithmetic")
                if not self._is_arithmetic_type(right_type):
                    raise SemaError("Division right operand must be arithmetic")
                result_type = self._usual_arithmetic_conversion(left_type, right_type)
                assert result_type is not None
                self._type_map.set(expr, result_type)
                return result_type
            if expr.op == "%":
                if not self._is_integer_type(left_type):
                    raise SemaError("Modulo left operand must be integer")
                if not self._is_integer_type(right_type):
                    raise SemaError("Modulo right operand must be integer")
                result_type = self._usual_arithmetic_conversion(left_type, right_type)
                assert result_type is not None and self._is_integer_type(result_type)
                self._type_map.set(expr, result_type)
                return result_type
            if expr.op in {"<<", ">>"}:
                if not self._is_integer_type(left_type):
                    raise SemaError("Shift left operand must be integer")
                if not self._is_integer_type(right_type):
                    raise SemaError("Shift right operand must be integer")
                result_type = self._integer_promotion(left_type)
                self._type_map.set(expr, result_type)
                return result_type
            if expr.op in {"&", "^", "|"}:
                if not self._is_integer_type(left_type):
                    raise SemaError("Bitwise left operand must be integer")
                if not self._is_integer_type(right_type):
                    raise SemaError("Bitwise right operand must be integer")
                result_type = self._usual_arithmetic_conversion(left_type, right_type)
                assert result_type is not None and self._is_integer_type(result_type)
                self._type_map.set(expr, result_type)
                return result_type
            if expr.op in {"<", "<=", ">", ">="}:
                if (
                    self._usual_arithmetic_conversion(left_type, right_type) is None
                ) and not self._is_pointer_relational_compatible(left_type, right_type):
                    raise SemaError(
                        "Relational operator requires integer or compatible object pointer operands"
                    )
            elif expr.op in {"==", "!="}:
                if not self._is_scalar_type(left_type):
                    raise SemaError("Equality left operand must be scalar")
                if not self._is_scalar_type(right_type):
                    raise SemaError("Equality right operand must be scalar")
                if self._usual_arithmetic_conversion(left_type, right_type) is None:
                    if left_type.pointee() is not None and right_type.pointee() is not None:
                        if not self._is_pointer_equality_compatible(left_type, right_type):
                            raise SemaError(
                                "Equality operator requires integer or compatible pointer operands"
                            )
                    elif left_type.pointee() is not None:
                        if self._eval_int_constant_expr(expr.right, scope) != 0:
                            raise SemaError(
                                "Equality operator requires integer or compatible pointer operands"
                            )
                    elif (
                        right_type.pointee() is not None
                        and self._eval_int_constant_expr(expr.left, scope) != 0
                    ):
                        raise SemaError(
                            "Equality operator requires integer or compatible pointer operands"
                        )
            elif expr.op in {"&&", "||"}:
                if not self._is_scalar_type(left_type):
                    raise SemaError("Logical left operand must be scalar")
                if not self._is_scalar_type(right_type):
                    raise SemaError("Logical right operand must be scalar")
            else:
                raise SemaError(f"Unsupported binary operator: {expr.op}")
            self._type_map.set(expr, INT)
            return INT
        if isinstance(expr, ConditionalExpr):
            self._check_condition_type(self._analyze_expr(expr.condition, scope))
            then_type = self._decay_array_value(self._analyze_expr(expr.then_expr, scope))
            else_type = self._decay_array_value(self._analyze_expr(expr.else_expr, scope))
            if then_type == else_type:
                result_type = then_type
            else:
                arithmetic_result = self._usual_arithmetic_conversion(then_type, else_type)
                if arithmetic_result is not None:
                    result_type = arithmetic_result
                else:
                    result_type = self._conditional_pointer_result(
                        expr.then_expr,
                        then_type,
                        expr.else_expr,
                        else_type,
                        scope,
                    )
                    if result_type is None:
                        raise SemaError("Conditional type mismatch")
            then_overload = self._get_overload_expr_name(expr.then_expr)
            else_overload = self._get_overload_expr_name(expr.else_expr)
            if then_overload is not None and then_overload == else_overload:
                self._set_overload_expr_name(expr, then_overload)
            elif then_overload is not None or else_overload is not None:
                condition_value = self._eval_int_constant_expr(expr.condition, scope)
                if condition_value is not None:
                    selected = then_overload if condition_value else else_overload
                    if selected is not None:
                        self._set_overload_expr_name(expr, selected)
            self._type_map.set(expr, result_type)
            return result_type
        if isinstance(expr, GenericExpr):
            control_type = self._decay_array_value(self._analyze_expr(expr.control, scope))
            selected_expr: Expr | None = None
            default_expr: Expr | None = None
            seen_types: set[Type] = set()
            for assoc_type_spec, assoc_expr in expr.associations:
                if assoc_type_spec is None:
                    if default_expr is not None:
                        raise SemaError("Duplicate default generic association")
                    default_expr = assoc_expr
                    self._analyze_expr(assoc_expr, scope)
                    continue
                self._register_type_spec(assoc_type_spec)
                if self._is_invalid_generic_association_type_spec(assoc_type_spec):
                    raise SemaError("Invalid generic association type")
                assoc_type = self._resolve_type(assoc_type_spec)
                if assoc_type in seen_types:
                    raise SemaError("Duplicate generic association type")
                seen_types.add(assoc_type)
                self._analyze_expr(assoc_expr, scope)
                if assoc_type == control_type:
                    selected_expr = assoc_expr
            if selected_expr is None:
                selected_expr = default_expr
            if selected_expr is None:
                raise SemaError("No matching generic association")
            selected_type = self._type_map.require(selected_expr)
            selected_overload = self._get_overload_expr_name(selected_expr)
            if selected_overload is not None:
                self._set_overload_expr_name(expr, selected_overload)
            self._type_map.set(expr, selected_type)
            return selected_type
        if isinstance(expr, CommaExpr):
            self._analyze_expr(expr.left, scope)
            right_type = self._analyze_expr(expr.right, scope)
            right_overload = self._get_overload_expr_name(expr.right)
            if right_overload is not None:
                self._set_overload_expr_name(expr, right_overload)
            self._type_map.set(expr, right_type)
            return right_type
        if isinstance(expr, AssignExpr):
            if isinstance(expr.target, Identifier):
                target_symbol = scope.lookup(expr.target.name)
                if isinstance(target_symbol, EnumConstSymbol):
                    raise SemaError("Assignment target is not assignable")
            if not self._is_assignable(expr.target):
                raise SemaError("Assignment target is not assignable")
            target_type = self._analyze_expr(expr.target, scope)
            if self._is_const_qualified(target_type):
                raise SemaError("Assignment target is not assignable")
            value_type = self._decay_array_value(self._analyze_expr(expr.value, scope))
            if target_type.is_array():
                raise SemaError("Assignment target is not assignable")
            if expr.op == "=":
                if not self._is_assignment_expr_compatible(
                    target_type,
                    expr.value,
                    value_type,
                    scope,
                ):
                    raise SemaError("Assignment type mismatch")
                self._type_map.set(expr, target_type)
                return target_type
            if expr.op in {"*=", "/="}:
                if not self._is_arithmetic_type(target_type) or not self._is_arithmetic_type(
                    value_type
                ):
                    raise SemaError(
                        "Compound multiplicative assignment requires arithmetic operands"
                    )
                self._type_map.set(expr, target_type)
                return target_type
            if expr.op in {"+=", "-="}:
                if self._is_arithmetic_type(target_type) and self._is_arithmetic_type(value_type):
                    self._type_map.set(expr, target_type)
                    return target_type
                if target_type.pointee() is not None and self._is_integer_type(value_type):
                    self._type_map.set(expr, target_type)
                    return target_type
                raise SemaError(
                    "Compound additive assignment requires arithmetic operands or pointer/integer"
                )
            if expr.op in {"<<=", ">>=", "%=", "&=", "^=", "|="}:
                if not self._is_integer_type(target_type) or not self._is_integer_type(value_type):
                    raise SemaError(
                        "Compound bitwise/shift/modulo assignment requires integer operands"
                    )
                self._type_map.set(expr, target_type)
                return target_type
            raise SemaError(f"Unsupported assignment operator: {expr.op}")
        if isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                signature = self._function_signatures.get(expr.callee.name)
                if signature is not None:
                    signature = self._resolve_call_signature(
                        expr.callee.name,
                        expr.args,
                        scope,
                        default=signature,
                    )
                    self._type_map.set(expr, signature.return_type)
                    return signature.return_type
                symbol = scope.lookup(expr.callee.name)
                if symbol is None:
                    raise SemaError(f"Undeclared function: {expr.callee.name}")
                callee_type = symbol.type_
            else:
                callee_type = self._analyze_expr(expr.callee, scope)
                overload_name = self._get_overload_expr_name(expr.callee)
                if overload_name is not None:
                    signature = self._resolve_call_signature(
                        overload_name,
                        expr.args,
                        scope,
                        default=self._function_signatures[overload_name],
                    )
                    self._type_map.set(expr, signature.return_type)
                    return signature.return_type
            callable_signature = self._decay_array_value(callee_type).callable_signature()
            if callable_signature is None:
                raise SemaError("Call target is not a function")
            return_type, function_params = callable_signature
            for arg in expr.args:
                self._analyze_expr(arg, scope)
            self._check_call_arguments(
                expr.args,
                function_params[0],
                function_params[1],
                None,
                scope,
            )
            self._type_map.set(expr, return_type)
            return return_type
        raise SemaError(f"Unsupported expression node: {type(expr).__name__}")

    def _resolve_call_signature(
        self,
        name: str,
        args: list[Expr],
        scope: Scope,
        *,
        default: FunctionSignature,
    ) -> FunctionSignature:
        overloads = self._function_overloads.get(name)
        if not overloads:
            for arg in args:
                self._analyze_expr(arg, scope)
            self._check_call_arguments(args, default.params, default.is_variadic, name, scope)
            return default
        analyzed_arg_types = [
            self._decay_array_value(self._analyze_expr(arg, scope)) for arg in args
        ]
        ranked: list[tuple[int, int, FunctionSignature]] = []
        for signature in overloads:
            score = self._match_overload_signature(args, analyzed_arg_types, signature, scope)
            if score is not None:
                ranked.append((score[0], score[1], signature))
        if not ranked:
            self._check_call_arguments(args, default.params, default.is_variadic, name, scope)
            return default
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if len(ranked) > 1 and ranked[0][:2] == ranked[1][:2]:
            raise SemaError(f"Ambiguous overloaded call: {name}")
        chosen = ranked[0][2]
        self._check_call_arguments(args, chosen.params, chosen.is_variadic, name, scope)
        return chosen

    def _match_overload_signature(
        self,
        args: list[Expr],
        arg_types: list[Type],
        signature: FunctionSignature,
        scope: Scope,
    ) -> tuple[int, int] | None:
        if signature.params is None:
            return 0, 0
        if signature.is_variadic:
            if len(args) < len(signature.params):
                return None
        elif len(args) != len(signature.params):
            return None
        exact_matches = 0
        fixed_params = signature.params
        for arg, arg_type, param_type in zip(args, arg_types, fixed_params, strict=False):
            if not self._is_assignment_expr_compatible(param_type, arg, arg_type, scope):
                return None
            if arg_type == param_type:
                exact_matches += 1
        return exact_matches, int(not signature.is_variadic)

    def _parse_float_literal_type(self, lexeme: str) -> Type:
        if lexeme and lexeme[-1] in "fF":
            return FLOAT
        if lexeme and lexeme[-1] in "lL":
            return LONGDOUBLE
        return DOUBLE

    def _parse_int_literal(self, lexeme: str | int) -> tuple[int, Type] | None:
        if isinstance(lexeme, int):
            return lexeme, INT
        if not isinstance(lexeme, str):
            return None
        suffix_start = len(lexeme)
        while suffix_start > 0 and lexeme[suffix_start - 1] in "uUlL":
            suffix_start -= 1
        body = lexeme[:suffix_start]
        suffix = lexeme[suffix_start:].lower()
        is_decimal = True
        if body.startswith(("0x", "0X")):
            digits = body[2:]
            if not digits:
                return None
            value = int(digits, 16)
            is_decimal = False
        elif body.startswith("0") and len(body) > 1:
            if any(ch not in "01234567" for ch in body):
                return None
            value = int(body, 8)
            is_decimal = False
        elif body.isdigit():
            value = int(body)
        else:
            return None
        candidates = (
            _DECIMAL_LITERAL_CANDIDATES if is_decimal else _NON_DECIMAL_LITERAL_CANDIDATES
        ).get(suffix)
        if candidates is None:
            return None
        for candidate_type in candidates:
            if self._fits_integer_literal_value(value, candidate_type):
                return value, candidate_type
        return None

    def _fits_integer_literal_value(self, value: int, type_: Type) -> bool:
        signed_bounds = _SIGNED_INTEGER_TYPE_LIMITS.get(type_)
        if signed_bounds is not None:
            return signed_bounds[0] <= value <= signed_bounds[1]
        unsigned_max = _UNSIGNED_INTEGER_TYPE_LIMITS.get(type_)
        return unsigned_max is not None and 0 <= value <= unsigned_max

    def _eval_int_constant_expr(self, expr: Expr, scope: Scope) -> int | None:
        if isinstance(expr, IntLiteral):
            parsed = self._parse_int_literal(expr.value)
            return None if parsed is None else parsed[0]
        if isinstance(expr, CharLiteral):
            return self._char_const_value(expr.value)
        if isinstance(expr, UnaryExpr) and expr.op in {"+", "-", "!", "~"}:
            operand_value = self._eval_int_constant_expr(expr.operand, scope)
            if operand_value is None:
                return None
            if expr.op == "+":
                return operand_value
            if expr.op == "-":
                return -operand_value
            if expr.op == "!":
                return 0 if operand_value else 1
            return ~operand_value
        if isinstance(expr, BinaryExpr):
            left_value = self._eval_int_constant_expr(expr.left, scope)
            if left_value is None:
                return None
            if expr.op == "&&":
                if not left_value:
                    return 0
                right_value = self._eval_int_constant_expr(expr.right, scope)
                if right_value is None:
                    return None
                return 1 if right_value else 0
            if expr.op == "||":
                if left_value:
                    return 1
                right_value = self._eval_int_constant_expr(expr.right, scope)
                if right_value is None:
                    return None
                return 1 if right_value else 0
            right_value = self._eval_int_constant_expr(expr.right, scope)
            if right_value is None:
                return None
            if expr.op == "+":
                return left_value + right_value
            if expr.op == "-":
                return left_value - right_value
            if expr.op == "*":
                return left_value * right_value
            if expr.op == "/":
                if right_value == 0:
                    return None
                return left_value // right_value
            if expr.op == "%":
                if right_value == 0:
                    return None
                return left_value % right_value
            if expr.op == "<<":
                if right_value < 0:
                    return None
                return left_value << right_value
            if expr.op == ">>":
                if right_value < 0:
                    return None
                return left_value >> right_value
            if expr.op == "<":
                return 1 if left_value < right_value else 0
            if expr.op == "<=":
                return 1 if left_value <= right_value else 0
            if expr.op == ">":
                return 1 if left_value > right_value else 0
            if expr.op == ">=":
                return 1 if left_value >= right_value else 0
            if expr.op == "==":
                return 1 if left_value == right_value else 0
            if expr.op == "!=":
                return 1 if left_value != right_value else 0
            if expr.op == "&":
                return left_value & right_value
            if expr.op == "^":
                return left_value ^ right_value
            if expr.op == "|":
                return left_value | right_value
            return None
        if isinstance(expr, ConditionalExpr):
            condition_value = self._eval_int_constant_expr(expr.condition, scope)
            if condition_value is None:
                return None
            branch = expr.then_expr if condition_value else expr.else_expr
            return self._eval_int_constant_expr(branch, scope)
        if isinstance(expr, CastExpr):
            if not self._is_integer_type(self._resolve_type(expr.type_spec)):
                return None
            return self._eval_int_constant_expr(expr.expr, scope)
        if isinstance(expr, SizeofExpr):
            if expr.type_spec is None:
                return None
            self._register_type_spec(expr.type_spec)
            if self._is_invalid_sizeof_type_spec(expr.type_spec):
                return None
            return self._sizeof_type(self._resolve_type(expr.type_spec))
        if isinstance(expr, AlignofExpr):
            if expr.type_spec is None:
                return None
            self._register_type_spec(expr.type_spec)
            if self._is_invalid_alignof_type_spec(expr.type_spec):
                return None
            return self._alignof_type(self._resolve_type(expr.type_spec))
        if isinstance(expr, GenericExpr):
            selected_expr: Expr | None = None
            default_expr: Expr | None = None
            control_type = self._type_map.get(expr.control)
            if control_type is None:
                control_type = self._analyze_expr(expr.control, scope)
            control_type = self._decay_array_value(control_type)
            for assoc_type_spec, assoc_expr in expr.associations:
                if assoc_type_spec is None:
                    default_expr = assoc_expr
                    continue
                self._register_type_spec(assoc_type_spec)
                if self._resolve_type(assoc_type_spec) == control_type:
                    selected_expr = assoc_expr
            if selected_expr is None:
                selected_expr = default_expr
            if selected_expr is None:
                return None
            return self._eval_int_constant_expr(selected_expr, scope)
        if isinstance(expr, Identifier):
            symbol = scope.lookup(expr.name)
            if isinstance(symbol, EnumConstSymbol):
                return symbol.value
        return None

    def _char_const_value(self, lexeme: str) -> int | None:
        body = self._char_literal_body(lexeme)
        if body is None:
            return None
        units = self._decode_escaped_units(body)
        if len(units) != 1:
            return None
        return units[0]

    def _char_literal_body(self, lexeme: str) -> str | None:
        prefixless = lexeme
        if lexeme[:1] in {"u", "U", "L"}:
            prefixless = lexeme[1:]
        if not prefixless.startswith("'") or not prefixless.endswith("'"):
            return None
        return prefixless[1:-1]

    def _decode_escaped_units(self, body: str) -> list[int]:
        units: list[int] = []
        index = 0
        while index < len(body):
            ch = body[index]
            if ch != "\\":
                units.append(ord(ch))
                index += 1
                continue
            index += 1
            esc = body[index]
            simple = _SIMPLE_ESCAPES.get(esc)
            if simple is not None:
                units.append(simple)
                index += 1
                continue
            if esc == "x":
                index += 1
                start = index
                while index < len(body) and body[index] in _HEX_DIGITS:
                    index += 1
                units.append(int(body[start:index], 16))
                continue
            if esc in _OCTAL_DIGITS:
                start = index
                index += 1
                if index < len(body) and body[index] in _OCTAL_DIGITS:
                    index += 1
                if index < len(body) and body[index] in _OCTAL_DIGITS:
                    index += 1
                units.append(int(body[start:index], 8))
                continue
            width = 4 if esc == "u" else 8
            index += 1
            units.append(int(body[index : index + width], 16))
            index += width
        return units

    def _check_call_arguments(
        self,
        args: list[Expr],
        parameter_types: tuple[Type, ...] | None,
        is_variadic: bool,
        function_name: str | None,
        scope: Scope,
    ) -> None:
        if parameter_types is None:
            return
        if (not is_variadic and len(args) != len(parameter_types)) or (
            is_variadic and len(args) < len(parameter_types)
        ):
            suffix = f": {function_name}" if function_name is not None else ""
            expected = len(parameter_types)
            got = len(args)
            if is_variadic:
                raise SemaError(
                    f"Argument count mismatch (expected at least {expected}, got {got}){suffix}"
                )
            raise SemaError(f"Argument count mismatch (expected {expected}, got {got}){suffix}")
        for index, arg in enumerate(args[: len(parameter_types)]):
            arg_type = self._type_map.require(arg)
            value_arg_type = self._decay_array_value(arg_type)
            if not self._is_assignment_expr_compatible(
                parameter_types[index],
                arg,
                value_arg_type,
                scope,
            ):
                suffix = f": {function_name}" if function_name is not None else ""
                raise SemaError(f"Argument {index + 1} type mismatch{suffix}")

    def _is_assignable(self, expr: Expr) -> bool:
        return isinstance(expr, (Identifier, SubscriptExpr, MemberExpr, CompoundLiteralExpr)) or (
            isinstance(expr, UnaryExpr) and expr.op == "*"
        )

    def _decay_array_value(self, type_: Type) -> Type:
        return type_.decay_parameter_type()


def analyze(unit: TranslationUnit, *, std: StdMode = "c11") -> SemaUnit:
    return Analyzer(std=std).analyze(unit)
