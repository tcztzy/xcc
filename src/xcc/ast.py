from dataclasses import dataclass


class Expr:
    pass


class Stmt:
    pass


@dataclass(frozen=True)
class TranslationUnit:
    functions: list["FunctionDef"]


@dataclass(frozen=True)
class TypeSpec:
    name: str


@dataclass(frozen=True)
class Param:
    type_spec: TypeSpec
    name: str


@dataclass(frozen=True)
class FunctionDef:
    return_type: TypeSpec
    name: str
    params: list[Param]
    body: "CompoundStmt"


@dataclass(frozen=True)
class CompoundStmt:
    statements: list[Stmt]


@dataclass(frozen=True)
class ReturnStmt(Stmt):
    value: Expr | None


@dataclass(frozen=True)
class ExprStmt(Stmt):
    expr: Expr


@dataclass(frozen=True)
class BinaryExpr(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class AssignExpr(Expr):
    op: str
    target: Expr
    value: Expr


@dataclass(frozen=True)
class UnaryExpr(Expr):
    op: str
    operand: Expr


@dataclass(frozen=True)
class CallExpr(Expr):
    callee: Expr
    args: list[Expr]


@dataclass(frozen=True)
class IntLiteral(Expr):
    value: str


@dataclass(frozen=True)
class Identifier(Expr):
    name: str


@dataclass(frozen=True)
class NullStmt(Stmt):
    pass


@dataclass(frozen=True)
class DeclStmt(Stmt):
    type_spec: TypeSpec
    name: str
    init: Expr | None
