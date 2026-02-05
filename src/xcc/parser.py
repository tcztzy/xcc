from __future__ import annotations

from dataclasses import dataclass

from xcc.ast import (
    BinaryExpr,
    CompoundStmt,
    Expr,
    ExprStmt,
    FunctionDef,
    Identifier,
    IntLiteral,
    ReturnStmt,
    Stmt,
    TranslationUnit,
    TypeSpec,
)
from xcc.lexer import Token, TokenKind


@dataclass(frozen=True)
class ParserError(ValueError):
    message: str
    token: Token

    def __str__(self) -> str:
        return f"{self.message} at {self.token.line}:{self.token.column}"


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._index = 0

    def parse(self) -> TranslationUnit:
        functions: list[FunctionDef] = []
        while not self._match(TokenKind.EOF):
            functions.append(self._parse_function())
        self._expect(TokenKind.EOF)
        return TranslationUnit(functions)

    def _parse_function(self) -> FunctionDef:
        return_type = self._parse_type_spec()
        name = self._expect(TokenKind.IDENT).lexeme
        self._expect_punct("(")
        self._expect_punct(")")
        body = self._parse_compound_stmt()
        return FunctionDef(return_type, str(name), body)

    def _parse_type_spec(self) -> TypeSpec:
        token = self._expect(TokenKind.KEYWORD)
        if token.lexeme not in {"int", "void"}:
            raise ParserError("Unsupported type", token)
        return TypeSpec(str(token.lexeme))

    def _parse_compound_stmt(self) -> CompoundStmt:
        self._expect_punct("{")
        statements: list[Stmt] = []
        while not self._check_punct("}"):
            statements.append(self._parse_statement())
        self._expect_punct("}")
        return CompoundStmt(statements)

    def _parse_statement(self):
        if self._check_keyword("return"):
            return self._parse_return_stmt()
        expr = self._parse_expression()
        self._expect_punct(";")
        return ExprStmt(expr)

    def _parse_return_stmt(self) -> ReturnStmt:
        self._advance()
        if self._check_punct(";"):
            self._expect_punct(";")
            return ReturnStmt(None)
        value = self._parse_expression()
        self._expect_punct(";")
        return ReturnStmt(value)

    def _parse_expression(self) -> Expr:
        return self._parse_additive()

    def _parse_additive(self) -> Expr:
        expr = self._parse_multiplicative()
        while self._check_punct("+") or self._check_punct("-"):
            op = self._advance().lexeme
            right = self._parse_multiplicative()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_multiplicative(self) -> Expr:
        expr = self._parse_primary()
        while self._check_punct("*") or self._check_punct("/"):
            op = self._advance().lexeme
            right = self._parse_primary()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_primary(self) -> Expr:
        token = self._current()
        if token.kind == TokenKind.INT_CONST:
            self._advance()
            assert isinstance(token.lexeme, str)
            return IntLiteral(token.lexeme)
        if token.kind == TokenKind.IDENT:
            self._advance()
            assert isinstance(token.lexeme, str)
            return Identifier(token.lexeme)
        if self._check_punct("("):
            self._advance()
            expr = self._parse_expression()
            self._expect_punct(")")
            return expr
        raise ParserError("Unexpected token", token)

    def _current(self) -> Token:
        return self._tokens[self._index]

    def _advance(self) -> Token:
        token = self._current()
        if token.kind != TokenKind.EOF:
            self._index += 1
        return token

    def _expect(self, kind: TokenKind) -> Token:
        token = self._current()
        if token.kind != kind:
            raise ParserError(f"Expected {kind.name}", token)
        self._advance()
        return token

    def _expect_punct(self, value: str) -> None:
        token = self._current()
        if token.kind != TokenKind.PUNCTUATOR or token.lexeme != value:
            raise ParserError(f"Expected '{value}'", token)
        self._advance()

    def _check_punct(self, value: str) -> bool:
        token = self._current()
        return token.kind == TokenKind.PUNCTUATOR and token.lexeme == value

    def _check_keyword(self, value: str) -> bool:
        token = self._current()
        return token.kind == TokenKind.KEYWORD and token.lexeme == value

    def _match(self, kind: TokenKind) -> bool:
        return self._current().kind == kind


def parse(tokens: list[Token]) -> TranslationUnit:
    return Parser(tokens).parse()
