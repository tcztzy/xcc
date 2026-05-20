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
    SwitchStmt,
    TypeSpec,
    WhileStmt,
)
from xcc.lexer import TokenKind

_EXTENSION_MARKER = "__extension__"
_MS_DECLSPEC_KEYWORD = "__declspec"
TYPE_QUALIFIER_KEYWORDS = {"const", "volatile", "restrict"}
_IGNORED_IDENT_TYPE_QUALIFIERS = {"__unaligned"}


def parse_compound_stmt(
    parser: object,
    initial_names: set[str] | None = None,
    initial_types: dict[str, TypeSpec] | None = None,
) -> CompoundStmt:
    parser._expect_punct("{")  # type: ignore
    parser._push_scope(initial_names, initial_types)  # type: ignore
    try:
        statements: list[Stmt] = []
        while not parser._check_punct("}"):  # type: ignore
            statements.append(parser._parse_statement())  # type: ignore
        parser._expect_punct("}")  # type: ignore
        return CompoundStmt(statements)
    finally:
        parser._pop_scope()  # type: ignore


def parse_statement(parser: object) -> Stmt:
    parser._skip_extension_markers()  # type: ignore
    if parser._check_punct(";"):  # type: ignore
        parser._advance()  # type: ignore
        return NullStmt()
    if parser._check_punct("{"):  # type: ignore
        return parser._parse_compound_stmt()  # type: ignore
    if parser._check_keyword("if"):  # type: ignore
        return parser._parse_if_stmt()  # type: ignore
    if parser._check_keyword("while"):  # type: ignore
        return parser._parse_while_stmt()  # type: ignore
    if parser._check_keyword("do"):  # type: ignore
        return parser._parse_do_while_stmt()  # type: ignore
    if parser._check_keyword("for"):  # type: ignore
        return parser._parse_for_stmt()  # type: ignore
    if parser._check_keyword("switch"):  # type: ignore
        return parser._parse_switch_stmt()  # type: ignore
    if parser._check_keyword("case"):  # type: ignore
        return parser._parse_case_stmt()  # type: ignore
    if parser._check_keyword("default"):  # type: ignore
        return parser._parse_default_stmt()  # type: ignore
    if parser._is_label_start():  # type: ignore
        return parser._parse_label_stmt()  # type: ignore
    if parser._check_keyword("goto"):  # type: ignore
        return parser._parse_goto_stmt()  # type: ignore
    if parser._check_keyword("break"):  # type: ignore
        parser._advance()  # type: ignore
        parser._expect_punct(";")  # type: ignore
        return BreakStmt()
    if parser._check_keyword("continue"):  # type: ignore
        parser._advance()  # type: ignore
        parser._expect_punct(";")  # type: ignore
        return ContinueStmt()
    if parser._check_keyword("return"):  # type: ignore
        return parser._parse_return_stmt()  # type: ignore
    if _is_static_assert_keyword(parser):
        return parser._parse_static_assert_decl()  # type: ignore
    if parser._is_declaration_start():  # type: ignore
        return parser._parse_decl_stmt()  # type: ignore
    expr = parser._parse_expression()  # type: ignore
    parser._expect_punct(";")  # type: ignore
    return ExprStmt(expr)


def is_declaration_start(parser: object) -> bool:
    if parser._check_keyword(_EXTENSION_MARKER):  # type: ignore
        saved_index = parser._index  # type: ignore
        parser._skip_extension_markers()  # type: ignore
        is_decl = parser._is_declaration_start()  # type: ignore
        parser._index = saved_index  # type: ignore
        return is_decl
    if any(
        parser._check_keyword(keyword)  # type: ignore
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
        )
    ):
        return True
    token = parser._current()  # type: ignore
    if token.kind != TokenKind.IDENT or not isinstance(token.lexeme, str):
        return False
    if token.lexeme in {"__thread", "__inline", "__inline__", "__unaligned", "static_assert"}:
        return True
    if token.lexeme == _MS_DECLSPEC_KEYWORD and parser._peek_punct("("):  # type: ignore
        return True
    return parser._is_typedef_name(token.lexeme)  # type: ignore


def parse_if_stmt(parser: object) -> IfStmt:
    parser._advance()  # type: ignore
    parser._expect_punct("(")  # type: ignore
    condition = parser._parse_expression()  # type: ignore
    parser._expect_punct(")")  # type: ignore
    then_body = parser._parse_statement()  # type: ignore
    else_body: Stmt | None = None
    if parser._check_keyword("else"):  # type: ignore
        parser._advance()  # type: ignore
        else_body = parser._parse_statement()  # type: ignore
    return IfStmt(condition, then_body, else_body)


def parse_while_stmt(parser: object) -> WhileStmt:
    parser._advance()  # type: ignore
    parser._expect_punct("(")  # type: ignore
    condition = parser._parse_expression()  # type: ignore
    parser._expect_punct(")")  # type: ignore
    body = parser._parse_statement()  # type: ignore
    return WhileStmt(condition, body)


def parse_do_while_stmt(parser: object) -> DoWhileStmt:
    parser._advance()  # type: ignore
    body = parser._parse_statement()  # type: ignore
    if not parser._check_keyword("while"):  # type: ignore
        raise parser._make_error("Expected while", parser._current())  # type: ignore
    parser._advance()  # type: ignore
    parser._expect_punct("(")  # type: ignore
    condition = parser._parse_expression()  # type: ignore
    parser._expect_punct(")")  # type: ignore
    parser._expect_punct(";")  # type: ignore
    return DoWhileStmt(body, condition)


def parse_for_stmt(parser: object) -> ForStmt:
    parser._advance()  # type: ignore
    parser._expect_punct("(")  # type: ignore
    parser._push_scope()  # type: ignore
    try:
        init: Stmt | Expr | None
        if parser._check_punct(";"):  # type: ignore
            parser._advance()  # type: ignore
            init = None
        elif parser._is_declaration_start():  # type: ignore
            init = parser._parse_decl_stmt()  # type: ignore
        else:
            init = parser._parse_expression()  # type: ignore
            parser._expect_punct(";")  # type: ignore
        if parser._check_punct(";"):  # type: ignore
            parser._advance()  # type: ignore
            condition: Expr | None = None
        else:
            condition = parser._parse_expression()  # type: ignore
            parser._expect_punct(";")  # type: ignore
        if parser._check_punct(")"):  # type: ignore
            post: Expr | None = None
        else:
            post = parser._parse_expression()  # type: ignore
        parser._expect_punct(")")  # type: ignore
        body = parser._parse_statement()  # type: ignore
        return ForStmt(init, condition, post, body)
    finally:
        parser._pop_scope()  # type: ignore


def parse_switch_stmt(parser: object) -> SwitchStmt:
    parser._advance()  # type: ignore
    parser._expect_punct("(")  # type: ignore
    condition = parser._parse_expression()  # type: ignore
    parser._expect_punct(")")  # type: ignore
    body = parser._parse_statement()  # type: ignore
    return SwitchStmt(condition, body)


def parse_case_stmt(parser: object) -> CaseStmt:
    parser._advance()  # type: ignore
    value = parser._parse_expression()  # type: ignore
    parser._expect_punct(":")  # type: ignore
    body = parser._parse_statement()  # type: ignore
    return CaseStmt(value, body)


def parse_default_stmt(parser: object) -> DefaultStmt:
    parser._advance()  # type: ignore
    parser._expect_punct(":")  # type: ignore
    body = parser._parse_statement()  # type: ignore
    return DefaultStmt(body)


def parse_label_stmt(parser: object) -> LabelStmt:
    token = parser._expect(TokenKind.IDENT)  # type: ignore
    assert isinstance(token.lexeme, str)
    parser._expect_punct(":")  # type: ignore
    body = parser._parse_statement()  # type: ignore
    return LabelStmt(token.lexeme, body)


def parse_goto_stmt(parser: object) -> Stmt:
    parser._advance()  # type: ignore
    if parser._check_punct("*"):  # type: ignore
        parser._advance()  # type: ignore
        target = parser._parse_expression()  # type: ignore
        parser._expect_punct(";")  # type: ignore
        return IndirectGotoStmt(target)
    label = parser._expect(TokenKind.IDENT)  # type: ignore
    assert isinstance(label.lexeme, str)
    parser._expect_punct(";")  # type: ignore
    return GotoStmt(label.lexeme)


def is_label_start(parser: object) -> bool:
    token = parser._current()  # type: ignore
    return token.kind == TokenKind.IDENT and parser._peek_punct(":")  # type: ignore


def _is_static_assert_keyword(parser: object) -> bool:
    """Check for _Static_assert or C23 static_assert (contextual keyword)."""
    tok = parser._current()  # type: ignore
    if (
        tok.kind == TokenKind.IDENT
        and isinstance(tok.lexeme, str)
        and tok.lexeme == "static_assert"
    ):
        return True
    return parser._check_keyword("_Static_assert")  # type: ignore


def parse_static_assert_decl(parser: object) -> StaticAssertDecl:
    if not _is_static_assert_keyword(parser):
        raise parser._make_error("Expected _Static_assert", parser._current())  # type: ignore
    parser._advance()  # type: ignore
    parser._expect_punct("(")  # type: ignore
    condition = parser._parse_conditional()  # type: ignore
    if parser._check_punct(","):  # type: ignore
        parser._expect_punct(",")  # type: ignore
        if parser._current().kind != TokenKind.STRING_LITERAL:  # type: ignore
            raise parser._make_error(  # type: ignore
                "Expected static assertion message",
                parser._current(),  # type: ignore
            )
        message = parser._parse_string_literal()  # type: ignore
    else:
        # C23: single-argument form with no message
        from xcc.ast import StringLiteral

        message = StringLiteral('""')
    parser._expect_punct(")")  # type: ignore
    parser._expect_punct(";")  # type: ignore
    return StaticAssertDecl(condition, message)


def parse_return_stmt(parser: object) -> ReturnStmt:
    parser._advance()  # type: ignore
    if parser._check_punct(";"):  # type: ignore
        parser._expect_punct(";")  # type: ignore
        return ReturnStmt(None)
    value = parser._parse_expression()  # type: ignore
    parser._expect_punct(";")  # type: ignore
    return ReturnStmt(value)


def parse_initializer(parser: object) -> Expr | InitList:
    if parser._check_punct("{"):  # type: ignore
        return parser._parse_initializer_list()  # type: ignore
    return parser._parse_assignment()  # type: ignore


def parse_initializer_list(parser: object) -> InitList:
    parser._expect_punct("{")  # type: ignore
    if parser._check_punct("}"):  # type: ignore
        raise parser._make_error("Expected initializer", parser._current())  # type: ignore
    items: list[InitItem] = []
    while True:
        designators = parser._parse_designator_list()  # type: ignore
        if designators:
            parser._expect_punct("=")  # type: ignore
        initializer = parser._parse_initializer()  # type: ignore
        items.append(InitItem(designators, initializer))
        if not parser._check_punct(","):  # type: ignore
            break
        parser._advance()  # type: ignore
        if parser._check_punct("}"):  # type: ignore
            break
    parser._expect_punct("}")  # type: ignore
    return InitList(tuple(items))


def parse_designator_list(
    parser: object,
) -> tuple[tuple[str, Expr | str | DesignatorRange], ...]:
    designators: list[tuple[str, Expr | str | DesignatorRange]] = []
    while True:
        if parser._check_punct("."):  # type: ignore
            parser._advance()  # type: ignore
            token = parser._expect(TokenKind.IDENT)  # type: ignore
            assert isinstance(token.lexeme, str)
            designators.append(("member", token.lexeme))
            continue
        if parser._check_punct("["):  # type: ignore
            parser._advance()  # type: ignore
            index_expr = parser._parse_conditional()  # type: ignore
            if parser._check_punct("..."):  # type: ignore
                parser._advance()  # type: ignore
                high_expr = parser._parse_conditional()  # type: ignore
                parser._expect_punct("]")  # type: ignore
                designators.append(("range", DesignatorRange(index_expr, high_expr)))
            else:
                parser._expect_punct("]")  # type: ignore
                designators.append(("index", index_expr))
            continue
        break
    return tuple(designators)
