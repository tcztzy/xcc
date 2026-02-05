from __future__ import annotations

from dataclasses import dataclass


class Expr:
    pass


class Stmt:
    pass


@dataclass(frozen=True)
class TranslationUnit:
    functions: list[FunctionDef]


@dataclass(frozen=True)
class TypeSpec:
    name: str


@dataclass(frozen=True)
class FunctionDef:
    return_type: TypeSpec
    name: str
    body: CompoundStmt


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
class IntLiteral(Expr):
    value: str


@dataclass(frozen=True)
class Identifier(Expr):
    name: str
