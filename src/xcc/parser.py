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
    SwitchStmt,
    TranslationUnit,
    TypeSpec,
    UnaryExpr,
    WhileStmt,
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
        params = self._parse_params()
        self._expect_punct(")")
        if self._check_punct(";"):
            self._advance()
            return FunctionDef(return_type, str(name), params, None)
        if any(param.name is None for param in params):
            raise ParserError("Expected parameter name", self._current())
        body = self._parse_compound_stmt()
        return FunctionDef(return_type, str(name), params, body)

    def _parse_params(self) -> list[Param]:
        if self._check_punct(")"):
            return []
        if self._check_keyword("void") and self._peek_punct(")"):
            self._advance()
            return []
        params = [self._parse_param()]
        while self._check_punct(","):
            self._advance()
            params.append(self._parse_param())
        return params

    def _parse_param(self) -> Param:
        type_spec = self._parse_type_spec()
        if type_spec.name == "void":
            raise ParserError("Invalid parameter type", self._previous())
        name: str | None = None
        if self._current().kind == TokenKind.IDENT:
            name_token = self._advance()
            name = str(name_token.lexeme)
        return Param(type_spec, name)

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

    def _parse_statement(self) -> Stmt:
        if self._check_punct(";"):
            self._advance()
            return NullStmt()
        if self._check_punct("{"):
            return self._parse_compound_stmt()
        if self._check_keyword("if"):
            return self._parse_if_stmt()
        if self._check_keyword("while"):
            return self._parse_while_stmt()
        if self._check_keyword("for"):
            return self._parse_for_stmt()
        if self._check_keyword("switch"):
            return self._parse_switch_stmt()
        if self._check_keyword("case"):
            return self._parse_case_stmt()
        if self._check_keyword("default"):
            return self._parse_default_stmt()
        if self._check_keyword("break"):
            self._advance()
            self._expect_punct(";")
            return BreakStmt()
        if self._check_keyword("continue"):
            self._advance()
            self._expect_punct(";")
            return ContinueStmt()
        if self._check_keyword("return"):
            return self._parse_return_stmt()
        if self._check_keyword("int") or self._check_keyword("void"):
            return self._parse_decl_stmt()
        expr = self._parse_expression()
        self._expect_punct(";")
        return ExprStmt(expr)

    def _parse_if_stmt(self) -> IfStmt:
        self._advance()
        self._expect_punct("(")
        condition = self._parse_expression()
        self._expect_punct(")")
        then_body = self._parse_statement()
        else_body: Stmt | None = None
        if self._check_keyword("else"):
            self._advance()
            else_body = self._parse_statement()
        return IfStmt(condition, then_body, else_body)

    def _parse_while_stmt(self) -> WhileStmt:
        self._advance()
        self._expect_punct("(")
        condition = self._parse_expression()
        self._expect_punct(")")
        body = self._parse_statement()
        return WhileStmt(condition, body)

    def _parse_for_stmt(self) -> ForStmt:
        self._advance()
        self._expect_punct("(")
        init: Stmt | Expr | None
        if self._check_punct(";"):
            self._advance()
            init = None
        elif self._check_keyword("int") or self._check_keyword("void"):
            init = self._parse_decl_stmt()
        else:
            init = self._parse_expression()
            self._expect_punct(";")
        if self._check_punct(";"):
            self._advance()
            condition: Expr | None = None
        else:
            condition = self._parse_expression()
            self._expect_punct(";")
        if self._check_punct(")"):
            post: Expr | None = None
        else:
            post = self._parse_expression()
        self._expect_punct(")")
        body = self._parse_statement()
        return ForStmt(init, condition, post, body)

    def _parse_switch_stmt(self) -> SwitchStmt:
        self._advance()
        self._expect_punct("(")
        condition = self._parse_expression()
        self._expect_punct(")")
        body = self._parse_statement()
        return SwitchStmt(condition, body)

    def _parse_case_stmt(self) -> CaseStmt:
        self._advance()
        value = self._parse_expression()
        self._expect_punct(":")
        body = self._parse_statement()
        return CaseStmt(value, body)

    def _parse_default_stmt(self) -> DefaultStmt:
        self._advance()
        self._expect_punct(":")
        body = self._parse_statement()
        return DefaultStmt(body)

    def _parse_decl_stmt(self) -> DeclStmt:
        if self._check_keyword("void"):
            raise ParserError("Invalid object type", self._current())
        type_spec = self._parse_type_spec()
        name = self._expect(TokenKind.IDENT).lexeme
        init: Expr | None = None
        if self._check_punct("="):
            self._advance()
            init = self._parse_expression()
        self._expect_punct(";")
        return DeclStmt(type_spec, str(name), init)

    def _parse_return_stmt(self) -> ReturnStmt:
        self._advance()
        if self._check_punct(";"):
            self._expect_punct(";")
            return ReturnStmt(None)
        value = self._parse_expression()
        self._expect_punct(";")
        return ReturnStmt(value)

    def _parse_expression(self) -> Expr:
        return self._parse_assignment()

    def _parse_assignment(self) -> Expr:
        expr = self._parse_logical_or()
        if self._check_punct("="):
            op = self._advance().lexeme
            value = self._parse_assignment()
            return AssignExpr(str(op), expr, value)
        return expr

    def _parse_logical_or(self) -> Expr:
        expr = self._parse_logical_and()
        while self._check_punct("||"):
            op = self._advance().lexeme
            right = self._parse_logical_and()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_logical_and(self) -> Expr:
        expr = self._parse_equality()
        while self._check_punct("&&"):
            op = self._advance().lexeme
            right = self._parse_equality()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_equality(self) -> Expr:
        expr = self._parse_relational()
        while self._check_punct("==") or self._check_punct("!="):
            op = self._advance().lexeme
            right = self._parse_relational()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_relational(self) -> Expr:
        expr = self._parse_additive()
        while (
            self._check_punct("<")
            or self._check_punct("<=")
            or self._check_punct(">")
            or self._check_punct(">=")
        ):
            op = self._advance().lexeme
            right = self._parse_additive()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_additive(self) -> Expr:
        expr = self._parse_multiplicative()
        while self._check_punct("+") or self._check_punct("-"):
            op = self._advance().lexeme
            right = self._parse_multiplicative()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_multiplicative(self) -> Expr:
        expr = self._parse_unary()
        while self._check_punct("*") or self._check_punct("/"):
            op = self._advance().lexeme
            right = self._parse_unary()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_unary(self) -> Expr:
        if (
            self._check_punct("+")
            or self._check_punct("-")
            or self._check_punct("!")
            or self._check_punct("~")
        ):
            op = self._advance().lexeme
            operand = self._parse_unary()
            return UnaryExpr(str(op), operand)
        return self._parse_postfix()

    def _parse_postfix(self) -> Expr:
        expr = self._parse_primary()
        while self._check_punct("("):
            self._advance()
            args = self._parse_arguments()
            self._expect_punct(")")
            expr = CallExpr(expr, args)
        return expr

    def _parse_arguments(self) -> list[Expr]:
        if self._check_punct(")"):
            return []
        args = [self._parse_expression()]
        while self._check_punct(","):
            self._advance()
            args.append(self._parse_expression())
        return args

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

    def _previous(self) -> Token:
        return self._tokens[self._index - 1]

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

    def _peek_punct(self, value: str) -> bool:
        token = self._peek()
        return token.kind == TokenKind.PUNCTUATOR and token.lexeme == value

    def _peek(self) -> Token:
        index = min(self._index + 1, len(self._tokens) - 1)
        return self._tokens[index]

    def _match(self, kind: TokenKind) -> bool:
        return self._current().kind == kind


def parse(tokens: list[Token]) -> TranslationUnit:
    return Parser(tokens).parse()
