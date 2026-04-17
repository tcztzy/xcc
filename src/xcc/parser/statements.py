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
    parser._expect_punct("{")  # type: ignore[attr-defined]
    parser._push_scope(initial_names, initial_types)  # type: ignore[attr-defined]
    try:
        statements: list[Stmt] = []
        while not parser._check_punct("}"):  # type: ignore[attr-defined]
            statements.append(parser._parse_statement())  # type: ignore[attr-defined]
        parser._expect_punct("}")  # type: ignore[attr-defined]
        return CompoundStmt(statements)
    finally:
        parser._pop_scope()


def parse_statement(parser: object) -> Stmt:
    parser._skip_extension_markers()  # type: ignore[attr-defined]
    if parser._check_punct(";"):  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]
        return NullStmt()
    if parser._check_punct("{"):  # type: ignore[attr-defined]
        return parser._parse_compound_stmt()  # type: ignore[attr-defined]
    if parser._check_keyword("if"):  # type: ignore[attr-defined]
        return parser._parse_if_stmt()  # type: ignore[attr-defined]
    if parser._check_keyword("while"):  # type: ignore[attr-defined]
        return parser._parse_while_stmt()  # type: ignore[attr-defined]
    if parser._check_keyword("do"):  # type: ignore[attr-defined]
        return parser._parse_do_while_stmt()  # type: ignore[attr-defined]
    if parser._check_keyword("for"):  # type: ignore[attr-defined]
        return parser._parse_for_stmt()  # type: ignore[attr-defined]
    if parser._check_keyword("switch"):  # type: ignore[attr-defined]
        return parser._parse_switch_stmt()  # type: ignore[attr-defined]
    if parser._check_keyword("case"):  # type: ignore[attr-defined]
        return parser._parse_case_stmt()  # type: ignore[attr-defined]
    if parser._check_keyword("default"):  # type: ignore[attr-defined]
        return parser._parse_default_stmt()  # type: ignore[attr-defined]
    if parser._is_label_start():  # type: ignore[attr-defined]
        return parser._parse_label_stmt()  # type: ignore[attr-defined]
    if parser._check_keyword("goto"):  # type: ignore[attr-defined]
        return parser._parse_goto_stmt()  # type: ignore[attr-defined]
    if parser._check_keyword("break"):  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]
        parser._expect_punct(";")  # type: ignore[attr-defined]
        return BreakStmt()
    if parser._check_keyword("continue"):  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]
        parser._expect_punct(";")  # type: ignore[attr-defined]
        return ContinueStmt()
    if parser._check_keyword("return"):  # type: ignore[attr-defined]
        return parser._parse_return_stmt()  # type: ignore[attr-defined]
    if parser._check_keyword("_Static_assert"):  # type: ignore[attr-defined]
        return parser._parse_static_assert_decl()  # type: ignore[attr-defined]
    if parser._is_declaration_start():  # type: ignore[attr-defined]
        return parser._parse_decl_stmt()  # type: ignore[attr-defined]
    expr = parser._parse_expression()  # type: ignore[attr-defined]
    parser._expect_punct(";")  # type: ignore[attr-defined]
    return ExprStmt(expr)


def is_declaration_start(parser: object) -> bool:
    if parser._check_keyword(_EXTENSION_MARKER):  # type: ignore[attr-defined]
        saved_index = parser._index  # type: ignore[attr-defined]
        parser._skip_extension_markers()  # type: ignore[attr-defined]
        is_decl = parser._is_declaration_start()  # type: ignore[attr-defined]
        parser._index = saved_index  # type: ignore[attr-defined]
        return is_decl
    if any(
        parser._check_keyword(keyword)  # type: ignore[attr-defined]
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
    token = parser._current()  # type: ignore[attr-defined]
    if token.kind != TokenKind.IDENT or not isinstance(token.lexeme, str):
        return False
    if token.lexeme in {"__thread", "__inline", "__inline__", "__unaligned"}:
        return True
    if token.lexeme == _MS_DECLSPEC_KEYWORD and parser._peek_punct("("):  # type: ignore[attr-defined]
        return True
    return parser._is_typedef_name(token.lexeme)  # type: ignore[attr-defined]


def parse_if_stmt(parser: object) -> IfStmt:
    parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct("(")  # type: ignore[attr-defined]
    condition = parser._parse_expression()  # type: ignore[attr-defined]
    parser._expect_punct(")")  # type: ignore[attr-defined]
    then_body = parser._parse_statement()  # type: ignore[attr-defined]
    else_body: Stmt | None = None
    if parser._check_keyword("else"):  # type: ignore[attr-defined]
        parser._advance()  # type: ignore[attr-defined]
        else_body = parser._parse_statement()  # type: ignore[attr-defined]
    return IfStmt(condition, then_body, else_body)


def parse_while_stmt(parser: object) -> WhileStmt:
    parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct("(")  # type: ignore[attr-defined]
    condition = parser._parse_expression()  # type: ignore[attr-defined]
    parser._expect_punct(")")  # type: ignore[attr-defined]
    body = parser._parse_statement()  # type: ignore[attr-defined]
    return WhileStmt(condition, body)


def parse_do_while_stmt(parser: object) -> DoWhileStmt:
    parser._advance()  # type: ignore[attr-defined]
    body = parser._parse_statement()  # type: ignore[attr-defined]
    if not parser._check_keyword("while"):  # type: ignore[attr-defined]
        raise parser._make_error("Expected while", parser._current())  # type: ignore[attr-defined]
    parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct("(")  # type: ignore[attr-defined]
    condition = parser._parse_expression()  # type: ignore[attr-defined]
    parser._expect_punct(")")  # type: ignore[attr-defined]
    parser._expect_punct(";")  # type: ignore[attr-defined]
    return DoWhileStmt(body, condition)


def parse_for_stmt(parser: object) -> ForStmt:
    parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct("(")  # type: ignore[attr-defined]
    parser._push_scope()  # type: ignore[attr-defined]
    try:
        init: Stmt | Expr | None
        if parser._check_punct(";"):  # type: ignore[attr-defined]
            parser._advance()  # type: ignore[attr-defined]
            init = None
        elif parser._is_declaration_start():  # type: ignore[attr-defined]
            init = parser._parse_decl_stmt()  # type: ignore[attr-defined]
        else:
            init = parser._parse_expression()  # type: ignore[attr-defined]
            parser._expect_punct(";")  # type: ignore[attr-defined]
        if parser._check_punct(";"):  # type: ignore[attr-defined]
            parser._advance()  # type: ignore[attr-defined]
            condition: Expr | None = None
        else:
            condition = parser._parse_expression()  # type: ignore[attr-defined]
            parser._expect_punct(";")  # type: ignore[attr-defined]
        if parser._check_punct(")"):  # type: ignore[attr-defined]
            post: Expr | None = None
        else:
            post = parser._parse_expression()  # type: ignore[attr-defined]
        parser._expect_punct(")")  # type: ignore[attr-defined]
        body = parser._parse_statement()  # type: ignore[attr-defined]
        return ForStmt(init, condition, post, body)
    finally:
        parser._pop_scope()


def parse_switch_stmt(parser: object) -> SwitchStmt:
    parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct("(")  # type: ignore[attr-defined]
    condition = parser._parse_expression()  # type: ignore[attr-defined]
    parser._expect_punct(")")  # type: ignore[attr-defined]
    body = parser._parse_statement()  # type: ignore[attr-defined]
    return SwitchStmt(condition, body)


def parse_case_stmt(parser: object) -> CaseStmt:
    parser._advance()  # type: ignore[attr-defined]
    value = parser._parse_expression()  # type: ignore[attr-defined]
    parser._expect_punct(":")  # type: ignore[attr-defined]
    body = parser._parse_statement()  # type: ignore[attr-defined]
    return CaseStmt(value, body)


def parse_default_stmt(parser: object) -> DefaultStmt:
    parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct(":")  # type: ignore[attr-defined]
    body = parser._parse_statement()  # type: ignore[attr-defined]
    return DefaultStmt(body)


def parse_label_stmt(parser: object) -> LabelStmt:
    token = parser._expect(TokenKind.IDENT)  # type: ignore[attr-defined]
    assert isinstance(token.lexeme, str)
    parser._expect_punct(":")  # type: ignore[attr-defined]
    body = parser._parse_statement()  # type: ignore[attr-defined]
    return LabelStmt(token.lexeme, body)


def parse_goto_stmt(parser: object) -> Stmt:
    parser._advance()  # type: ignore[attr-defined]
    if parser._check_punct("*"):  # type: ignore[attr-defined]
        if parser._std == "c11":  # type: ignore[attr-defined]
            raise parser._make_error(  # type: ignore[attr-defined]
                "Indirect goto is a GNU extension",
                parser._current(),  # type: ignore[attr-defined]
            )
        parser._advance()  # type: ignore[attr-defined]
        target = parser._parse_expression()  # type: ignore[attr-defined]
        parser._expect_punct(";")  # type: ignore[attr-defined]
        return IndirectGotoStmt(target)
    label = parser._expect(TokenKind.IDENT)  # type: ignore[attr-defined]
    assert isinstance(label.lexeme, str)
    parser._expect_punct(";")  # type: ignore[attr-defined]
    return GotoStmt(label.lexeme)


def is_label_start(parser: object) -> bool:
    token = parser._current()  # type: ignore[attr-defined]
    return token.kind == TokenKind.IDENT and parser._peek_punct(":")  # type: ignore[attr-defined]


def parse_static_assert_decl(parser: object) -> StaticAssertDecl:
    if not parser._check_keyword("_Static_assert"):  # type: ignore[attr-defined]
        raise parser._make_error("Expected _Static_assert", parser._current())  # type: ignore[attr-defined]
    parser._advance()  # type: ignore[attr-defined]
    parser._expect_punct("(")  # type: ignore[attr-defined]
    condition = parser._parse_conditional()  # type: ignore[attr-defined]
    parser._expect_punct(",")  # type: ignore[attr-defined]
    if parser._current().kind != TokenKind.STRING_LITERAL:  # type: ignore[attr-defined]
        raise parser._make_error(  # type: ignore[attr-defined]
            "Expected static assertion message",
            parser._current(),  # type: ignore[attr-defined]
        )
    message = parser._parse_string_literal()  # type: ignore[attr-defined]
    parser._expect_punct(")")  # type: ignore[attr-defined]
    parser._expect_punct(";")  # type: ignore[attr-defined]
    return StaticAssertDecl(condition, message)


def parse_return_stmt(parser: object) -> ReturnStmt:
    parser._advance()  # type: ignore[attr-defined]
    if parser._check_punct(";"):  # type: ignore[attr-defined]
        parser._expect_punct(";")  # type: ignore[attr-defined]
        return ReturnStmt(None)
    value = parser._parse_expression()  # type: ignore[attr-defined]
    parser._expect_punct(";")  # type: ignore[attr-defined]
    return ReturnStmt(value)


def parse_initializer(parser: object) -> Expr | InitList:
    if parser._check_punct("{"):  # type: ignore[attr-defined]
        return parser._parse_initializer_list()  # type: ignore[attr-defined]
    return parser._parse_assignment()  # type: ignore[attr-defined]


def parse_initializer_list(parser: object) -> InitList:
    parser._expect_punct("{")  # type: ignore[attr-defined]
    if parser._check_punct("}"):  # type: ignore[attr-defined]
        raise parser._make_error("Expected initializer", parser._current())  # type: ignore[attr-defined]
    items: list[InitItem] = []
    while True:
        designators = parser._parse_designator_list()  # type: ignore[attr-defined]
        if designators:
            parser._expect_punct("=")  # type: ignore[attr-defined]
        initializer = parser._parse_initializer()  # type: ignore[attr-defined]
        items.append(InitItem(designators, initializer))
        if not parser._check_punct(","):  # type: ignore[attr-defined]
            break
        parser._advance()  # type: ignore[attr-defined]
        if parser._check_punct("}"):  # type: ignore[attr-defined]
            break
    parser._expect_punct("}")  # type: ignore[attr-defined]
    return InitList(tuple(items))


def parse_designator_list(
    parser: object,
) -> tuple[tuple[str, Expr | str | DesignatorRange], ...]:
    designators: list[tuple[str, Expr | str | DesignatorRange]] = []
    while True:
        if parser._check_punct("."):  # type: ignore[attr-defined]
            parser._advance()  # type: ignore[attr-defined]
            token = parser._expect(TokenKind.IDENT)  # type: ignore[attr-defined]
            assert isinstance(token.lexeme, str)
            designators.append(("member", token.lexeme))
            continue
        if parser._check_punct("["):  # type: ignore[attr-defined]
            parser._advance()  # type: ignore[attr-defined]
            index_expr = parser._parse_conditional()  # type: ignore[attr-defined]
            if parser._check_punct("..."):  # type: ignore[attr-defined]
                parser._advance()  # type: ignore[attr-defined]
                high_expr = parser._parse_conditional()  # type: ignore[attr-defined]
                parser._expect_punct("]")  # type: ignore[attr-defined]
                designators.append(("range", DesignatorRange(index_expr, high_expr)))
            else:
                parser._expect_punct("]")  # type: ignore[attr-defined]
                designators.append(("index", index_expr))
            continue
        break
    return tuple(designators)
