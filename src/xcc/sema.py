from dataclasses import dataclass

from xcc.ast import (
    AssignExpr,
    BinaryExpr,
    CallExpr,
    CompoundStmt,
    DeclStmt,
    Expr,
    ExprStmt,
    FunctionDef,
    Identifier,
    IntLiteral,
    NullStmt,
    Param,
    ReturnStmt,
    Stmt,
    TranslationUnit,
    TypeSpec,
    UnaryExpr,
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


class TypeMap:
    def __init__(self) -> None:
        self._map: dict[int, Type] = {}

    def set(self, node: Expr, type_: Type) -> None:
        self._map[id(node)] = type_

    def get(self, node: Expr) -> Type | None:
        return self._map.get(id(node))


@dataclass(frozen=True)
class SemaUnit:
    functions: dict[str, FunctionSymbol]
    type_map: TypeMap


class Scope:
    def __init__(self) -> None:
        self._symbols: dict[str, VarSymbol] = {}

    def define(self, symbol: VarSymbol) -> None:
        if symbol.name in self._symbols:
            raise SemaError(f"Duplicate declaration: {symbol.name}")
        self._symbols[symbol.name] = symbol

    def lookup(self, name: str) -> VarSymbol | None:
        return self._symbols.get(name)

    @property
    def symbols(self) -> dict[str, VarSymbol]:
        return self._symbols


class Analyzer:
    def __init__(self) -> None:
        self._functions: dict[str, FunctionSymbol] = {}
        self._type_map = TypeMap()
        self._function_return_types: dict[str, Type] = {}

    def analyze(self, unit: TranslationUnit) -> SemaUnit:
        for func in unit.functions:
            if func.name in self._function_return_types:
                raise SemaError(f"Duplicate function definition: {func.name}")
            self._function_return_types[func.name] = self._resolve_type(func.return_type)
        for func in unit.functions:
            self._analyze_function(func)
        return SemaUnit(self._functions, self._type_map)

    def _analyze_function(self, func: FunctionDef) -> None:
        return_type = self._function_return_types[func.name]
        scope = Scope()
        self._define_params(func.params, scope)
        self._analyze_compound(func.body, scope, return_type)
        self._functions[func.name] = FunctionSymbol(func.name, return_type, scope.symbols)

    def _define_params(self, params: list[Param], scope: Scope) -> None:
        for param in params:
            if param.type_spec.name == "void":
                raise SemaError("Invalid parameter type: void")
            param_type = self._resolve_type(param.type_spec)
            scope.define(VarSymbol(param.name, param_type))

    def _resolve_type(self, type_spec: TypeSpec) -> Type:
        if type_spec.name == "int":
            return INT
        return VOID

    def _analyze_compound(
        self, stmt: CompoundStmt, scope: Scope, return_type: Type
    ) -> None:
        for item in stmt.statements:
            self._analyze_stmt(item, scope, return_type)

    def _analyze_stmt(self, stmt: Stmt, scope: Scope, return_type: Type) -> None:
        if isinstance(stmt, DeclStmt):
            if stmt.type_spec.name == "void":
                raise SemaError("Invalid object type: void")
            var_type = self._resolve_type(stmt.type_spec)
            scope.define(VarSymbol(stmt.name, var_type))
            if stmt.init is not None:
                self._analyze_expr(stmt.init, scope)
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
            self._analyze_expr(stmt.value, scope)
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
            if symbol is None:
                raise SemaError(f"Undeclared identifier: {expr.name}")
            self._type_map.set(expr, symbol.type_)
            return symbol.type_
        if isinstance(expr, UnaryExpr):
            self._analyze_expr(expr.operand, scope)
            self._type_map.set(expr, INT)
            return INT
        if isinstance(expr, BinaryExpr):
            self._analyze_expr(expr.left, scope)
            self._analyze_expr(expr.right, scope)
            self._type_map.set(expr, INT)
            return INT
        if isinstance(expr, AssignExpr):
            if not isinstance(expr.target, Identifier):
                raise SemaError("Assignment target is not assignable")
            self._analyze_expr(expr.target, scope)
            self._analyze_expr(expr.value, scope)
            self._type_map.set(expr, INT)
            return INT
        if isinstance(expr, CallExpr):
            if not isinstance(expr.callee, Identifier):
                raise SemaError("Call target is not a function")
            if expr.callee.name not in self._function_return_types:
                raise SemaError(f"Undeclared function: {expr.callee.name}")
            for arg in expr.args:
                self._analyze_expr(arg, scope)
            return_type = self._function_return_types[expr.callee.name]
            self._type_map.set(expr, return_type)
            return return_type
        raise SemaError("Unsupported expression")


def analyze(unit: TranslationUnit) -> SemaUnit:
    return Analyzer().analyze(unit)
