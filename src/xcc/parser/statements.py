from typing import Protocol

from xcc.ast import (
    BreakStmt,
    CaseStmt,
    CompoundStmt,
    ContinueStmt,
    DefaultStmt,
    DesignatorRange,
    DoWhileStmt,
    Expr,
    ExprStmt,
    ForStmt,
    GotoStmt,
    IfStmt,
    IndirectGotoStmt,
    InitItem,
    InitList,
    LabelStmt,
    NullStmt,
    ReturnStmt,
    StaticAssertDecl,
    Stmt,
    StringLiteral,
    SwitchStmt,
    TypeSpec,
    WhileStmt,
)
from xcc.lexer import Token, TokenKind
from xcc.parser.type_specs import ParserError

_EXTENSION_MARKER = "__extension__"
_MS_DECLSPEC_KEYWORD = "__declspec"
TYPE_QUALIFIER_KEYWORDS = {"const", "volatile", "restrict", "__restrict", "__restrict__"}
_IGNORED_IDENT_TYPE_QUALIFIERS = {"__unaligned"}


class _StatementParser(Protocol):
    _index: int

    def _advance(self) -> Token: ...

    def _check_keyword(self, value: str) -> bool: ...

    def _check_punct(self, value: str) -> bool: ...

    def _current(self) -> Token: ...

    def _expect(self, kind: TokenKind) -> Token: ...

    def _expect_punct(self, value: str) -> None: ...

    def _is_declaration_start(self) -> bool: ...

    def _is_label_start(self) -> bool: ...

    def _is_typedef_name(self, name: str) -> bool: ...

    def _make_error(self, message: str, token: Token) -> ParserError: ...

    def _parse_assignment(self) -> Expr: ...

    def _parse_case_stmt(self) -> CaseStmt: ...

    def _parse_compound_stmt(self) -> CompoundStmt: ...

    def _parse_conditional(self) -> Expr: ...

    def _parse_decl_stmt(self) -> Stmt: ...

    def _parse_default_stmt(self) -> DefaultStmt: ...

    def _parse_designator_list(
        self,
    ) -> tuple[tuple[str, Expr | str | DesignatorRange], ...]: ...

    def _parse_do_while_stmt(self) -> DoWhileStmt: ...

    def _parse_expression(self) -> Expr: ...

    def _parse_for_stmt(self) -> ForStmt: ...

    def _parse_goto_stmt(self) -> Stmt: ...

    def _parse_if_stmt(self) -> IfStmt: ...

    def _parse_initializer(self) -> Expr | InitList: ...

    def _parse_initializer_list(self) -> InitList: ...

    def _parse_label_stmt(self) -> LabelStmt: ...

    def _parse_return_stmt(self) -> ReturnStmt: ...

    def _parse_static_assert_decl(self) -> StaticAssertDecl: ...

    def _parse_statement(self) -> Stmt: ...

    def _parse_string_literal(self) -> StringLiteral: ...

    def _parse_switch_stmt(self) -> SwitchStmt: ...

    def _parse_while_stmt(self) -> WhileStmt: ...

    def _peek_punct(self, value: str) -> bool: ...

    def _pop_scope(self) -> None: ...

    def _push_scope(
        self,
        names: set[str] | None = None,
        types: dict[str, TypeSpec] | None = None,
    ) -> None: ...

    def _skip_decl_attributes(self) -> bool: ...

    def _skip_extension_markers(self) -> None: ...


def parse_compound_stmt(
    parser: _StatementParser,
    initial_names: set[str] | None = None,
    initial_types: dict[str, TypeSpec] | None = None,
) -> CompoundStmt:
    p = parser
    p._expect_punct("{")
    p._push_scope(initial_names, initial_types)
    try:
        statements: list[Stmt] = []
        while not p._check_punct("}"):
            statements.append(p._parse_statement())
        p._expect_punct("}")
        return CompoundStmt(statements)
    finally:
        p._pop_scope()


def parse_statement(parser: _StatementParser) -> Stmt:
    p = parser
    p._skip_extension_markers()
    if p._check_punct(";"):
        p._advance()
        return NullStmt()
    if p._check_punct("{"):
        return p._parse_compound_stmt()
    if p._check_keyword("if"):
        return p._parse_if_stmt()
    if p._check_keyword("while"):
        return p._parse_while_stmt()
    if p._check_keyword("do"):
        return p._parse_do_while_stmt()
    if p._check_keyword("for"):
        return p._parse_for_stmt()
    if p._check_keyword("switch"):
        return p._parse_switch_stmt()
    if p._check_keyword("case"):
        return p._parse_case_stmt()
    if p._check_keyword("default"):
        return p._parse_default_stmt()
    if p._is_label_start():
        return p._parse_label_stmt()
    if p._check_keyword("goto"):
        return p._parse_goto_stmt()
    if p._check_keyword("break"):
        p._advance()
        p._expect_punct(";")
        return BreakStmt()
    if p._check_keyword("continue"):
        p._advance()
        p._expect_punct(";")
        return ContinueStmt()
    if p._check_keyword("return"):
        return p._parse_return_stmt()
    if _is_static_assert_keyword(p):
        return p._parse_static_assert_decl()
    if p._is_declaration_start():
        return p._parse_decl_stmt()
    expr = p._parse_expression()
    p._expect_punct(";")
    return ExprStmt(expr)


def is_declaration_start(parser: _StatementParser) -> bool:
    p = parser
    if p._check_keyword(_EXTENSION_MARKER):
        saved_index = p._index
        p._skip_extension_markers()
        is_decl = p._is_declaration_start()
        p._index = saved_index
        return is_decl
    saved_index = p._index
    if p._skip_decl_attributes():
        is_decl = p._is_declaration_start()
        p._index = saved_index
        return is_decl
    p._index = saved_index
    for keyword in (
        "int",
        "char",
        "void",
        "float",
        "double",
        "short",
        "long",
        "signed",
        "unsigned",
        "_Bool",
        "_Atomic",
        "_Complex",
        "typeof",
        "typeof_unqual",
        "__typeof__",
        "__typeof",
        "__typeof_unqual__",
        "__typeof_unqual",
        "enum",
        "struct",
        "union",
        "const",
        "volatile",
        "restrict",
        "__restrict",
        "__restrict__",
        "typedef",
        "auto",
        "register",
        "static",
        "extern",
        "inline",
        "_Noreturn",
        "_Thread_local",
        "_Alignas",
        "_Static_assert",
    ):
        if p._check_keyword(keyword):
            return True
    token = p._current()
    if token.kind != TokenKind.IDENT or not isinstance(token.lexeme, str):
        return False
    if token.lexeme in {"__thread", "__inline", "__inline__", "__unaligned", "static_assert"}:
        return True
    if token.lexeme == _MS_DECLSPEC_KEYWORD and p._peek_punct("("):
        return True
    return p._is_typedef_name(token.lexeme)


def parse_if_stmt(parser: _StatementParser) -> IfStmt:
    p = parser
    p._advance()
    p._expect_punct("(")
    condition = p._parse_expression()
    p._expect_punct(")")
    then_body = p._parse_statement()
    else_body: Stmt | None = None
    if p._check_keyword("else"):
        p._advance()
        else_body = p._parse_statement()
    return IfStmt(condition, then_body, else_body)


def parse_while_stmt(parser: _StatementParser) -> WhileStmt:
    p = parser
    p._advance()
    p._expect_punct("(")
    condition = p._parse_expression()
    p._expect_punct(")")
    body = p._parse_statement()
    return WhileStmt(condition, body)


def parse_do_while_stmt(parser: _StatementParser) -> DoWhileStmt:
    p = parser
    p._advance()
    body = p._parse_statement()
    if not p._check_keyword("while"):
        raise p._make_error("Expected while", p._current())
    p._advance()
    p._expect_punct("(")
    condition = p._parse_expression()
    p._expect_punct(")")
    p._expect_punct(";")
    return DoWhileStmt(body, condition)


def parse_for_stmt(parser: _StatementParser) -> ForStmt:
    p = parser
    p._advance()
    p._expect_punct("(")
    p._push_scope()
    try:
        init: Stmt | Expr | None
        if p._check_punct(";"):
            p._advance()
            init = None
        elif p._is_declaration_start():
            init = p._parse_decl_stmt()
        else:
            init = p._parse_expression()
            p._expect_punct(";")
        if p._check_punct(";"):
            p._advance()
            condition: Expr | None = None
        else:
            condition = p._parse_expression()
            p._expect_punct(";")
        if p._check_punct(")"):
            post: Expr | None = None
        else:
            post = p._parse_expression()
        p._expect_punct(")")
        body = p._parse_statement()
        return ForStmt(init, condition, post, body)
    finally:
        p._pop_scope()


def parse_switch_stmt(parser: _StatementParser) -> SwitchStmt:
    p = parser
    p._advance()
    p._expect_punct("(")
    condition = p._parse_expression()
    p._expect_punct(")")
    body = p._parse_statement()
    return SwitchStmt(condition, body)


def parse_case_stmt(parser: _StatementParser) -> CaseStmt:
    p = parser
    p._advance()
    value = p._parse_expression()
    p._expect_punct(":")
    body = p._parse_statement()
    return CaseStmt(value, body)


def parse_default_stmt(parser: _StatementParser) -> DefaultStmt:
    p = parser
    p._advance()
    p._expect_punct(":")
    body = p._parse_statement()
    return DefaultStmt(body)


def parse_label_stmt(parser: _StatementParser) -> LabelStmt:
    p = parser
    token = p._expect(TokenKind.IDENT)
    assert isinstance(token.lexeme, str)
    p._expect_punct(":")
    body = p._parse_statement()
    return LabelStmt(token.lexeme, body)


def parse_goto_stmt(parser: _StatementParser) -> Stmt:
    p = parser
    p._advance()
    if p._check_punct("*"):
        p._advance()
        target = p._parse_expression()
        p._expect_punct(";")
        return IndirectGotoStmt(target)
    label = p._expect(TokenKind.IDENT)
    assert isinstance(label.lexeme, str)
    p._expect_punct(";")
    return GotoStmt(label.lexeme)


def is_label_start(parser: _StatementParser) -> bool:
    p = parser
    token = p._current()
    return token.kind == TokenKind.IDENT and p._peek_punct(":")


def _is_static_assert_keyword(parser: _StatementParser) -> bool:
    """Check for _Static_assert or C23 static_assert (contextual keyword)."""
    p = parser
    tok = p._current()
    if (
        tok.kind == TokenKind.IDENT
        and isinstance(tok.lexeme, str)
        and tok.lexeme == "static_assert"
    ):
        return True
    return p._check_keyword("_Static_assert")


def parse_static_assert_decl(parser: _StatementParser) -> StaticAssertDecl:
    p = parser
    if not _is_static_assert_keyword(p):
        raise p._make_error("Expected _Static_assert", p._current())
    p._advance()
    p._expect_punct("(")
    condition = p._parse_conditional()
    if p._check_punct(","):
        p._expect_punct(",")
        if p._current().kind != TokenKind.STRING_LITERAL:
            raise p._make_error(
                "Expected static assertion message",
                p._current(),
            )
        message = p._parse_string_literal()
    else:
        # C23: single-argument form with no message
        message = StringLiteral('""')
    p._expect_punct(")")
    p._expect_punct(";")
    return StaticAssertDecl(condition, message)


def parse_return_stmt(parser: _StatementParser) -> ReturnStmt:
    p = parser
    p._advance()
    if p._check_punct(";"):
        p._expect_punct(";")
        return ReturnStmt(None)
    value = p._parse_expression()
    p._expect_punct(";")
    return ReturnStmt(value)


def parse_initializer(parser: _StatementParser) -> Expr | InitList:
    p = parser
    if p._check_punct("{"):
        return p._parse_initializer_list()
    return p._parse_assignment()


def parse_initializer_list(parser: _StatementParser) -> InitList:
    p = parser
    p._expect_punct("{")
    if p._check_punct("}"):
        raise p._make_error("Expected initializer", p._current())
    items: list[InitItem] = []
    while True:
        designators = p._parse_designator_list()
        if designators:
            p._expect_punct("=")
        initializer = p._parse_initializer()
        items.append(InitItem(designators, initializer))
        if not p._check_punct(","):
            break
        p._advance()
        if p._check_punct("}"):
            break
    p._expect_punct("}")
    return InitList(tuple(items))


def parse_designator_list(
    parser: _StatementParser,
) -> tuple[tuple[str, Expr | str | DesignatorRange], ...]:
    p = parser
    designators: list[tuple[str, Expr | str | DesignatorRange]] = []
    while True:
        if p._check_punct("."):
            p._advance()
            token = p._expect(TokenKind.IDENT)
            assert isinstance(token.lexeme, str)
            designators.append(("member", token.lexeme))
            continue
        if p._check_punct("["):
            p._advance()
            index_expr = p._parse_conditional()
            if p._check_punct("..."):
                p._advance()
                high_expr = p._parse_conditional()
                p._expect_punct("]")
                designators.append(("range", DesignatorRange(index_expr, high_expr)))
            else:
                p._expect_punct("]")
                designators.append(("index", index_expr))
            continue
        break
    return tuple(designators)
