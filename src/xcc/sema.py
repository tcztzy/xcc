from dataclasses import dataclass

from xcc.ast import (
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CallExpr,
    CaseStmt,
    CompoundStmt,
    ContinueStmt,
    DeclStmt,
    DefaultStmt,
    Expr,
    ExprStmt,
    ForStmt,
    FunctionDef,
    Identifier,
    IfStmt,
    IntLiteral,
    NullStmt,
    Param,
    ReturnStmt,
    Stmt,
    SubscriptExpr,
    SwitchStmt,
    TranslationUnit,
    TypeSpec,
    UnaryExpr,
    WhileStmt,
)
from xcc.types import INT, VOID, Type


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
class FunctionSymbol:
    name: str
    return_type: Type
    locals: dict[str, VarSymbol]


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
        self._symbols: dict[str, VarSymbol] = {}
        self._parent = parent

    def define(self, symbol: VarSymbol) -> None:
        if symbol.name in self._symbols:
            raise SemaError(f"Duplicate declaration: {symbol.name}")
        self._symbols[symbol.name] = symbol

    def lookup(self, name: str) -> VarSymbol | None:
        symbol = self._symbols.get(name)
        if symbol is not None:
            return symbol
        if self._parent is None:
            return None
        return self._parent.lookup(name)

    @property
    def symbols(self) -> dict[str, VarSymbol]:
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
        self._loop_depth = 0
        self._switch_stack: list[SwitchContext] = []

    def analyze(self, unit: TranslationUnit) -> SemaUnit:
        for func in unit.functions:
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
        for func in unit.functions:
            if func.body is None:
                continue
            self._analyze_function(func)
        return SemaUnit(self._functions, self._type_map)

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
        scope = Scope()
        self._define_params(func.params, scope)
        self._analyze_compound(func.body, scope, return_type)
        self._functions[func.name] = FunctionSymbol(func.name, return_type, scope.symbols)

    def _define_params(self, params: list[Param], scope: Scope) -> None:
        for param in params:
            if param.name is None:
                raise SemaError("Missing parameter name")
            param_type = self._resolve_param_type(param.type_spec)
            scope.define(VarSymbol(param.name, param_type))

    def _signature_from(self, func: FunctionDef) -> FunctionSignature:
        if not func.has_prototype:
            if func.is_variadic:
                raise SemaError("Variadic function requires a prototype")
            return FunctionSignature(self._resolve_type(func.return_type), None, False)
        params: list[Type] = []
        for param in func.params:
            if self._is_invalid_void_parameter_type(param.type_spec):
                raise SemaError("Invalid parameter type: void")
            params.append(self._resolve_param_type(param.type_spec))
        return FunctionSignature(
            self._resolve_type(func.return_type),
            tuple(params),
            func.is_variadic,
        )

    def _resolve_type(self, type_spec: TypeSpec) -> Type:
        if type_spec.name == "int" and not type_spec.declarator_ops:
            return INT
        if type_spec.name == "void" and not type_spec.declarator_ops:
            return VOID
        resolved_ops: list[tuple[str, int | tuple[tuple[Type, ...] | None, bool]]] = []
        for kind, value in type_spec.declarator_ops:
            if kind != "fn":
                assert isinstance(value, int)
                resolved_ops.append((kind, value))
                continue
            resolved_params = self._resolve_function_param_types(value)
            resolved_ops.append((kind, resolved_params))
        return Type(type_spec.name, declarator_ops=tuple(resolved_ops))

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
            params.append(self._resolve_param_type(param_spec))
        return tuple(params), is_variadic

    def _resolve_param_type(self, type_spec: TypeSpec) -> Type:
        resolved = self._resolve_type(type_spec)
        return resolved.decay_parameter_type()

    def _is_invalid_void_object_type(self, type_spec: TypeSpec) -> bool:
        if type_spec.name != "void":
            return False
        return not any(kind == "ptr" for kind, _ in type_spec.declarator_ops)

    def _is_invalid_void_parameter_type(self, type_spec: TypeSpec) -> bool:
        if type_spec.name != "void":
            return False
        return not type_spec.declarator_ops

    def _analyze_compound(self, stmt: CompoundStmt, scope: Scope, return_type: Type) -> None:
        for item in stmt.statements:
            self._analyze_stmt(item, scope, return_type)

    def _analyze_stmt(self, stmt: Stmt, scope: Scope, return_type: Type) -> None:
        if isinstance(stmt, DeclStmt):
            if self._is_invalid_void_object_type(stmt.type_spec):
                raise SemaError("Invalid object type: void")
            var_type = self._resolve_type(stmt.type_spec)
            scope.define(VarSymbol(stmt.name, var_type))
            if stmt.init is not None:
                init_type = self._decay_array_value(self._analyze_expr(stmt.init, scope))
                if init_type != var_type:
                    raise SemaError("Initializer type mismatch")
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
            if value_type != return_type:
                raise SemaError("Return type mismatch")
            return
        if isinstance(stmt, ForStmt):
            inner_scope = Scope(scope)
            if isinstance(stmt.init, DeclStmt):
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
            if not isinstance(stmt.value, IntLiteral):
                raise SemaError("case value is not integer constant")
            context = self._switch_stack[-1]
            if stmt.value.value in context.case_values:
                raise SemaError("Duplicate case value")
            context.case_values.add(stmt.value.value)
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
            if index_type != INT:
                raise SemaError("Array subscript is not an integer")
            element_type = base_type.element_type()
            if element_type is None:
                element_type = base_type.pointee()
            if element_type is None:
                raise SemaError("Subscripted value is not an array or pointer")
            self._type_map.set(expr, element_type)
            return element_type
        if isinstance(expr, UnaryExpr):
            operand_type = self._analyze_expr(expr.operand, scope)
            if expr.op in {"+", "-", "!", "~"}:
                self._type_map.set(expr, INT)
                return INT
            if expr.op == "&":
                if not self._is_assignable(expr.operand):
                    raise SemaError("Address-of operand is not assignable")
                result = operand_type.pointer_to()
                self._type_map.set(expr, result)
                return result
            if expr.op == "*":
                value_operand_type = self._decay_array_value(operand_type)
                pointee = value_operand_type.pointee()
                if pointee is None:
                    raise SemaError("Cannot dereference non-pointer")
                self._type_map.set(expr, pointee)
                return pointee
            raise SemaError("Unsupported expression")
        if isinstance(expr, BinaryExpr):
            self._analyze_expr(expr.left, scope)
            self._analyze_expr(expr.right, scope)
            self._type_map.set(expr, INT)
            return INT
        if isinstance(expr, AssignExpr):
            if not self._is_assignable(expr.target):
                raise SemaError("Assignment target is not assignable")
            target_type = self._analyze_expr(expr.target, scope)
            value_type = self._decay_array_value(self._analyze_expr(expr.value, scope))
            if target_type.is_array():
                raise SemaError("Assignment target is not assignable")
            if target_type != value_type:
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
            if value_arg_type != parameter_types[index]:
                suffix = f": {function_name}" if function_name is not None else ""
                raise SemaError(f"Argument type mismatch{suffix}")

    def _is_assignable(self, expr: Expr) -> bool:
        return (
            isinstance(expr, Identifier)
            or (isinstance(expr, UnaryExpr) and expr.op == "*")
            or isinstance(expr, SubscriptExpr)
        )

    def _decay_array_value(self, type_: Type) -> Type:
        return type_.decay_parameter_type()


def analyze(unit: TranslationUnit) -> SemaUnit:
    return Analyzer().analyze(unit)
