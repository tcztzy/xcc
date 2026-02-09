from dataclasses import dataclass

from xcc.ast import (
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CallExpr,
    CaseStmt,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundStmt,
    ConditionalExpr,
    ContinueStmt,
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
    DoWhileStmt,
    Expr,
    ExprStmt,
    ForStmt,
    FunctionDef,
    GotoStmt,
    Identifier,
    IfStmt,
    IntLiteral,
    LabelStmt,
    MemberExpr,
    NullStmt,
    Param,
    ReturnStmt,
    SizeofExpr,
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
from xcc.types import CHAR, INT, VOID, Type

_HEX_DIGITS = "0123456789abcdefABCDEF"
_OCTAL_DIGITS = "01234567"
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


@dataclass(frozen=True)
class SemaError(ValueError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class VarSymbol:
    name: str
    type_: Type


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
    def __init__(self) -> None:
        self._functions: dict[str, FunctionSymbol] = {}
        self._type_map = TypeMap()
        self._function_signatures: dict[str, FunctionSignature] = {}
        self._defined_functions: set[str] = set()
        self._record_definitions: dict[str, tuple[tuple[str, Type], ...]] = {}
        self._seen_record_definitions: set[int] = set()
        self._file_scope = Scope()
        self._loop_depth = 0
        self._switch_stack: list[SwitchContext] = []
        self._function_labels: set[str] = set()
        self._pending_goto_labels: list[str] = []

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
        if self._file_scope.lookup(func.name) is not None:
            raise SemaError(f"Conflicting declaration: {func.name}")
        if self._file_scope.lookup_typedef(func.name) is not None:
            raise SemaError(f"Conflicting declaration: {func.name}")
        signature = self._signature_from(func)
        existing = self._function_signatures.get(func.name)
        if existing is None:
            self._function_signatures[func.name] = signature
        else:
            merged_signature = self._merge_signature(existing, signature, func.name)
            self._function_signatures[func.name] = merged_signature
        if func.body is not None:
            if func.name in self._defined_functions:
                raise SemaError(f"Duplicate function definition: {func.name}")
            self._defined_functions.add(func.name)

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
        self._define_params(func.params, scope)
        self._analyze_compound(func.body, scope, return_type)
        for label in self._pending_goto_labels:
            if label not in self._function_labels:
                raise SemaError(f"Undefined label: {label}")
        self._functions[func.name] = FunctionSymbol(func.name, return_type, scope.symbols)

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
            self._define_enum_members(declaration.type_spec, self._file_scope)
            typedef_type = self._resolve_type(declaration.type_spec)
            self._file_scope.define_typedef(declaration.name, typedef_type)
            return
        if isinstance(declaration, DeclStmt):
            self._register_type_spec(declaration.type_spec)
            self._define_enum_members(declaration.type_spec, self._file_scope)
            if declaration.name is None:
                return
            if declaration.name in self._function_signatures:
                raise SemaError(f"Conflicting declaration: {declaration.name}")
            if self._is_invalid_void_object_type(declaration.type_spec):
                raise SemaError("Invalid object type: void")
            if self._is_invalid_incomplete_record_object_type(declaration.type_spec):
                raise SemaError("Invalid object type: incomplete")
            var_type = self._resolve_type(declaration.type_spec)
            self._file_scope.define(VarSymbol(declaration.name, var_type))
            if declaration.init is not None:
                init_type = self._decay_array_value(
                    self._analyze_expr(declaration.init, self._file_scope)
                )
                if not self._is_initializer_compatible(
                    var_type,
                    declaration.init,
                    init_type,
                ):
                    raise SemaError("Initializer type mismatch")
            return
        raise SemaError("Unsupported file-scope declaration")

    def _signature_from(self, func: FunctionDef) -> FunctionSignature:
        if not func.has_prototype:
            if func.is_variadic:
                raise SemaError("Variadic function requires a prototype")
            if self._is_invalid_incomplete_record_object_type(func.return_type):
                raise SemaError("Invalid return type: incomplete")
            return FunctionSignature(self._resolve_type(func.return_type), None, False)
        params: list[Type] = []
        for param in func.params:
            if self._is_invalid_void_parameter_type(param.type_spec):
                raise SemaError("Invalid parameter type: void")
            if self._is_invalid_incomplete_record_object_type(param.type_spec):
                raise SemaError("Invalid parameter type: incomplete")
            params.append(self._resolve_param_type(param.type_spec))
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

    def _register_type_spec(self, type_spec: TypeSpec) -> None:
        if type_spec.name not in {"struct", "union"} or not type_spec.record_members:
            return
        spec_id = id(type_spec)
        if spec_id in self._seen_record_definitions:
            return
        self._seen_record_definitions.add(spec_id)
        seen_members: set[str] = set()
        member_types: list[tuple[str, Type]] = []
        for member_spec, member_name in type_spec.record_members:
            if member_name in seen_members:
                raise SemaError(f"Duplicate declaration: {member_name}")
            seen_members.add(member_name)
            if self._is_invalid_void_object_type(member_spec):
                raise SemaError("Invalid member type")
            if self._is_function_object_type(member_spec):
                raise SemaError("Invalid member type")
            if self._is_invalid_incomplete_record_object_type(member_spec):
                raise SemaError("Invalid member type")
            member_types.append((member_name, self._resolve_type(member_spec)))
        key = self._record_type_name(type_spec)
        if key in self._record_definitions:
            raise SemaError(f"Duplicate definition: {key}")
        self._record_definitions[key] = tuple(member_types)

    def _resolve_type(self, type_spec: TypeSpec) -> Type:
        self._register_type_spec(type_spec)
        if type_spec.name == "int" and not type_spec.declarator_ops:
            return INT
        if type_spec.name == "char" and not type_spec.declarator_ops:
            return CHAR
        if type_spec.name == "void" and not type_spec.declarator_ops:
            return VOID
        if type_spec.name == "enum" and not type_spec.declarator_ops:
            return INT
        if type_spec.name in {"struct", "union"} and not type_spec.declarator_ops:
            return Type(self._record_type_name(type_spec))
        resolved_ops: list[tuple[str, int | tuple[tuple[Type, ...] | None, bool]]] = []
        for kind, value in type_spec.declarator_ops:
            if kind != "fn":
                assert isinstance(value, int)
                resolved_ops.append((kind, value))
                continue
            resolved_params = self._resolve_function_param_types(value)
            resolved_ops.append((kind, resolved_params))
        if type_spec.name == "enum":
            base_name = "int"
        elif type_spec.name in {"struct", "union"}:
            base_name = self._record_type_name(type_spec)
        else:
            base_name = type_spec.name
        return Type(base_name, declarator_ops=tuple(resolved_ops))

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
        members = self._record_definitions.get(record_type.name)
        if members is None:
            raise SemaError("Member access on incomplete type")
        for declared_name, declared_type in members:
            if declared_name == member_name:
                return declared_type
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
            self._is_invalid_void_object_type(type_spec)
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

    def _is_integer_type(self, type_: Type) -> bool:
        return type_ in (INT, CHAR)

    def _is_assignment_compatible(self, target_type: Type, value_type: Type) -> bool:
        return target_type == value_type or (
            self._is_integer_type(target_type) and self._is_integer_type(value_type)
        )

    def _is_initializer_compatible(
        self,
        target_type: Type,
        init_expr: Expr,
        init_type: Type,
    ) -> bool:
        return self._is_char_array_string_initializer(target_type, init_expr) or (
            self._is_assignment_compatible(target_type, init_type)
        )

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
        return self._is_integer_type(type_) or (
            bool(type_.declarator_ops) and type_.declarator_ops[0][0] == "ptr"
        )

    def _analyze_additive_types(self, left_type: Type, right_type: Type, op: str) -> Type | None:
        if self._is_integer_type(left_type) and self._is_integer_type(right_type):
            return INT
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
        if left_ptr is not None and right_ptr is not None and left_type == right_type:
            return INT
        return None

    def _is_pointer_relational_compatible(self, left_type: Type, right_type: Type) -> bool:
        left_pointee = left_type.pointee()
        right_pointee = right_type.pointee()
        if left_pointee is None or right_pointee is None or left_type != right_type:
            return False
        if left_pointee == VOID:
            return False
        return not (left_pointee.declarator_ops and left_pointee.declarator_ops[0][0] == "fn")

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
        if then_pointee is not None and else_pointee is not None:
            return then_type if then_type == else_type else None
        if then_pointee is not None and self._eval_int_constant_expr(else_expr, scope) == 0:
            return then_type
        if else_pointee is not None and self._eval_int_constant_expr(then_expr, scope) == 0:
            return else_type
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

    def _analyze_compound(self, stmt: CompoundStmt, scope: Scope, return_type: Type) -> None:
        for item in stmt.statements:
            self._analyze_stmt(item, scope, return_type)

    def _analyze_stmt(self, stmt: Stmt, scope: Scope, return_type: Type) -> None:
        if isinstance(stmt, DeclGroupStmt):
            for grouped_decl in stmt.declarations:
                self._analyze_stmt(grouped_decl, scope, return_type)
            return
        if isinstance(stmt, DeclStmt):
            self._register_type_spec(stmt.type_spec)
            self._define_enum_members(stmt.type_spec, scope)
            if stmt.name is None:
                return
            if self._is_invalid_void_object_type(stmt.type_spec):
                raise SemaError("Invalid object type: void")
            if self._is_invalid_incomplete_record_object_type(stmt.type_spec):
                raise SemaError("Invalid object type: incomplete")
            var_type = self._resolve_type(stmt.type_spec)
            scope.define(VarSymbol(stmt.name, var_type))
            if stmt.init is not None:
                init_type = self._decay_array_value(self._analyze_expr(stmt.init, scope))
                if not self._is_initializer_compatible(
                    var_type,
                    stmt.init,
                    init_type,
                ):
                    raise SemaError("Initializer type mismatch")
            return
        if isinstance(stmt, TypedefDecl):
            self._register_type_spec(stmt.type_spec)
            self._define_enum_members(stmt.type_spec, scope)
            typedef_type = self._resolve_type(stmt.type_spec)
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
            if not self._is_assignment_compatible(return_type, value_type):
                raise SemaError("Return type mismatch")
            return
        if isinstance(stmt, ForStmt):
            inner_scope = Scope(scope)
            if isinstance(stmt.init, Stmt):
                self._analyze_stmt(stmt.init, inner_scope, return_type)
            elif isinstance(stmt.init, Expr):
                self._analyze_expr(stmt.init, inner_scope)
            if stmt.condition is not None:
                condition_type = self._analyze_expr(stmt.condition, inner_scope)
                if condition_type is VOID:
                    raise SemaError("Condition must be non-void")
            if stmt.post is not None:
                self._analyze_expr(stmt.post, inner_scope)
            self._loop_depth += 1
            try:
                self._analyze_stmt(stmt.body, inner_scope, return_type)
            finally:
                self._loop_depth -= 1
            return
        if isinstance(stmt, SwitchStmt):
            condition_type = self._analyze_expr(stmt.condition, scope)
            if condition_type is VOID:
                raise SemaError("Condition must be non-void")
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
        if isinstance(stmt, CompoundStmt):
            inner_scope = Scope(scope)
            self._analyze_compound(stmt, inner_scope, return_type)
            return
        if isinstance(stmt, IfStmt):
            condition_type = self._analyze_expr(stmt.condition, scope)
            if condition_type is VOID:
                raise SemaError("Condition must be non-void")
            self._analyze_stmt(stmt.then_body, scope, return_type)
            if stmt.else_body is not None:
                self._analyze_stmt(stmt.else_body, scope, return_type)
            return
        if isinstance(stmt, WhileStmt):
            condition_type = self._analyze_expr(stmt.condition, scope)
            if condition_type is VOID:
                raise SemaError("Condition must be non-void")
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
                condition_type = self._analyze_expr(stmt.condition, scope)
                if condition_type is VOID:
                    raise SemaError("Condition must be non-void")
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
        raise SemaError("Unsupported statement")

    def _analyze_expr(self, expr: Expr, scope: Scope) -> Type:
        if isinstance(expr, IntLiteral):
            self._type_map.set(expr, INT)
            return INT
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
            function_type = signature.return_type.function_of(
                signature.params,
                is_variadic=signature.is_variadic,
            )
            self._type_map.set(expr, function_type)
            return function_type
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
        if isinstance(expr, CastExpr):
            self._register_type_spec(expr.type_spec)
            target_type = self._resolve_type(expr.type_spec)
            if self._is_invalid_cast_target(expr.type_spec, target_type):
                raise SemaError("Invalid cast")
            operand_type = self._decay_array_value(self._analyze_expr(expr.expr, scope))
            if self._is_invalid_cast_operand(operand_type, target_type):
                raise SemaError("Invalid cast")
            self._type_map.set(expr, target_type)
            return target_type
        if isinstance(expr, UnaryExpr):
            operand_type = self._analyze_expr(expr.operand, scope)
            value_operand_type = self._decay_array_value(operand_type)
            if expr.op in {"+", "-", "~"}:
                if not self._is_integer_type(value_operand_type):
                    raise SemaError("Unary operator requires integer operand")
                self._type_map.set(expr, INT)
                return INT
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
            raise SemaError("Unsupported expression")
        if isinstance(expr, UpdateExpr):
            if isinstance(expr.operand, Identifier):
                target_symbol = scope.lookup(expr.operand.name)
                if isinstance(target_symbol, EnumConstSymbol):
                    raise SemaError("Assignment target is not assignable")
            if not self._is_assignable(expr.operand):
                raise SemaError("Assignment target is not assignable")
            operand_type = self._analyze_expr(expr.operand, scope)
            if operand_type.is_array():
                raise SemaError("Assignment target is not assignable")
            value_operand_type = self._decay_array_value(operand_type)
            if (
                not self._is_integer_type(value_operand_type)
                and value_operand_type.pointee() is None
            ):
                raise SemaError("Assignment type mismatch")
            self._type_map.set(expr, operand_type)
            return operand_type
        if isinstance(expr, BinaryExpr):
            left_type = self._decay_array_value(self._analyze_expr(expr.left, scope))
            right_type = self._decay_array_value(self._analyze_expr(expr.right, scope))
            if expr.op in {"+", "-"}:
                result_type = self._analyze_additive_types(left_type, right_type, expr.op)
                if result_type is None:
                    raise SemaError(
                        "Additive operator requires integer and compatible pointer operands"
                    )
                self._type_map.set(expr, result_type)
                return result_type
            integer_ops = {"*", "/", "%", "<<", ">>", "&", "^", "|"}
            if expr.op in integer_ops:
                if not self._is_integer_type(left_type) or not self._is_integer_type(right_type):
                    raise SemaError("Binary operator requires integer operands")
            elif expr.op in {"<", "<=", ">", ">="}:
                if (
                    not self._is_integer_type(left_type) or not self._is_integer_type(right_type)
                ) and not self._is_pointer_relational_compatible(left_type, right_type):
                    raise SemaError(
                        "Relational operator requires integer or compatible object pointer operands"
                    )
            elif expr.op in {"==", "!="}:
                if not self._is_scalar_type(left_type) or not self._is_scalar_type(right_type):
                    raise SemaError("Equality operator requires scalar operands")
                if not (self._is_integer_type(left_type) and self._is_integer_type(right_type)):
                    if left_type.pointee() is not None and right_type.pointee() is not None:
                        if left_type != right_type:
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
                if not self._is_scalar_type(left_type) or not self._is_scalar_type(right_type):
                    raise SemaError("Logical operator requires scalar operands")
            else:
                raise SemaError("Unsupported expression")
            self._type_map.set(expr, INT)
            return INT
        if isinstance(expr, ConditionalExpr):
            condition_type = self._analyze_expr(expr.condition, scope)
            if condition_type is VOID:
                raise SemaError("Condition must be non-void")
            then_type = self._decay_array_value(self._analyze_expr(expr.then_expr, scope))
            else_type = self._decay_array_value(self._analyze_expr(expr.else_expr, scope))
            if then_type == else_type:
                result_type = then_type
            elif self._is_integer_type(then_type) and self._is_integer_type(else_type):
                result_type = INT
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
            self._type_map.set(expr, result_type)
            return result_type
        if isinstance(expr, CommaExpr):
            self._analyze_expr(expr.left, scope)
            right_type = self._analyze_expr(expr.right, scope)
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
            value_type = self._decay_array_value(self._analyze_expr(expr.value, scope))
            if target_type.is_array():
                raise SemaError("Assignment target is not assignable")
            if expr.op == "=":
                if not self._is_assignment_compatible(target_type, value_type):
                    raise SemaError("Assignment type mismatch")
                self._type_map.set(expr, target_type)
                return target_type
            if expr.op in {"+=", "-="}:
                if (
                    not self._is_integer_type(target_type) or not self._is_integer_type(value_type)
                ) and (target_type.pointee() is None or not self._is_integer_type(value_type)):
                    raise SemaError("Assignment type mismatch")
                self._type_map.set(expr, target_type)
                return target_type
            if not self._is_integer_type(target_type) or not self._is_integer_type(value_type):
                raise SemaError("Assignment type mismatch")
            self._type_map.set(expr, target_type)
            return target_type
        if isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                signature = self._function_signatures.get(expr.callee.name)
                if signature is not None:
                    for arg in expr.args:
                        self._analyze_expr(arg, scope)
                    self._check_call_arguments(
                        expr.args,
                        signature.params,
                        signature.is_variadic,
                        expr.callee.name,
                    )
                    self._type_map.set(expr, signature.return_type)
                    return signature.return_type
                symbol = scope.lookup(expr.callee.name)
                if symbol is None:
                    raise SemaError(f"Undeclared function: {expr.callee.name}")
                callee_type = symbol.type_
            else:
                callee_type = self._analyze_expr(expr.callee, scope)
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
            )
            self._type_map.set(expr, return_type)
            return return_type
        raise SemaError("Unsupported expression")

    def _eval_int_constant_expr(self, expr: Expr, scope: Scope) -> int | None:
        if isinstance(expr, IntLiteral):
            if not expr.value.isdigit():
                return None
            return int(expr.value)
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
    ) -> None:
        if parameter_types is None:
            return
        if (not is_variadic and len(args) != len(parameter_types)) or (
            is_variadic and len(args) < len(parameter_types)
        ):
            suffix = f": {function_name}" if function_name is not None else ""
            raise SemaError(f"Argument count mismatch{suffix}")
        for index, arg in enumerate(args[: len(parameter_types)]):
            arg_type = self._type_map.require(arg)
            value_arg_type = self._decay_array_value(arg_type)
            if not self._is_assignment_compatible(parameter_types[index], value_arg_type):
                suffix = f": {function_name}" if function_name is not None else ""
                raise SemaError(f"Argument type mismatch{suffix}")

    def _is_assignable(self, expr: Expr) -> bool:
        return isinstance(expr, (Identifier, SubscriptExpr, MemberExpr)) or (
            isinstance(expr, UnaryExpr) and expr.op == "*"
        )

    def _decay_array_value(self, type_: Type) -> Type:
        return type_.decay_parameter_type()


def analyze(unit: TranslationUnit) -> SemaUnit:
    return Analyzer().analyze(unit)
