from dataclasses import dataclass

from xcc.ast import (
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CallExpr,
    CaseStmt,
    CastExpr,
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
    SubscriptExpr,
    SwitchStmt,
    TranslationUnit,
    TypedefDecl,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
    WhileStmt,
)
from xcc.lexer import Token, TokenKind

FunctionDeclarator = tuple[tuple[TypeSpec, ...] | None, bool]
DeclaratorOp = tuple[str, int | FunctionDeclarator]
POINTER_OP: DeclaratorOp = ("ptr", 0)
ASSIGNMENT_OPERATORS = ("=", "+=", "-=", "*=", "/=", "%=", "<<=", ">>=", "&=", "^=", "|=")


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
        self._typedef_scopes: list[dict[str, TypeSpec]] = [{}]
        self._ordinary_name_scopes: list[set[str]] = [set()]

    def _push_scope(self, names: set[str] | None = None) -> None:
        self._typedef_scopes.append({})
        if names is None:
            self._ordinary_name_scopes.append(set())
        else:
            self._ordinary_name_scopes.append(set(names))

    def _pop_scope(self) -> None:
        self._typedef_scopes.pop()
        self._ordinary_name_scopes.pop()

    def _define_typedef(self, name: str, type_spec: TypeSpec) -> None:
        self._typedef_scopes[-1][name] = type_spec

    def _define_ordinary_name(self, name: str) -> None:
        self._ordinary_name_scopes[-1].add(name)

    def _lookup_typedef(self, name: str) -> TypeSpec | None:
        for typedefs, ordinary_names in zip(
            reversed(self._typedef_scopes),
            reversed(self._ordinary_name_scopes),
            strict=True,
        ):
            if name in ordinary_names:
                return None
            type_spec = typedefs.get(name)
            if type_spec is not None:
                return type_spec
        return None

    def _is_typedef_name(self, name: str) -> bool:
        return self._lookup_typedef(name) is not None

    def parse(self) -> TranslationUnit:
        functions: list[FunctionDef] = []
        declarations: list[Stmt] = []
        externals: list[FunctionDef | Stmt] = []
        while not self._match(TokenKind.EOF):
            if self._looks_like_function():
                function = self._parse_function()
                functions.append(function)
                externals.append(function)
                continue
            declaration = self._parse_decl_stmt()
            declarations.append(declaration)
            externals.append(declaration)
        self._expect(TokenKind.EOF)
        return TranslationUnit(functions, declarations, externals)

    def _looks_like_function(self) -> bool:
        saved_index = self._index
        try:
            self._parse_type_spec()
            if self._current().kind != TokenKind.IDENT:
                return False
            self._advance()
            if not self._check_punct("("):
                return False
            self._advance()
            self._parse_params()
            self._expect_punct(")")
            return self._check_punct("{") or self._check_punct(";")
        except ParserError:
            return False
        finally:
            self._index = saved_index

    def _parse_function(self) -> FunctionDef:
        return_type = self._parse_type_spec()
        name = self._expect(TokenKind.IDENT).lexeme
        function_name = str(name)
        self._define_ordinary_name(function_name)
        self._expect_punct("(")
        params, has_prototype, is_variadic = self._parse_params()
        self._expect_punct(")")
        if self._check_punct(";"):
            self._advance()
            return FunctionDef(
                return_type,
                function_name,
                params,
                None,
                has_prototype=has_prototype,
                is_variadic=is_variadic,
            )
        if any(param.name is None for param in params):
            raise ParserError("Expected parameter name", self._current())
        parameter_names = {param.name for param in params if param.name is not None}
        body = self._parse_compound_stmt(initial_names=parameter_names)
        return FunctionDef(
            return_type,
            function_name,
            params,
            body,
            has_prototype=has_prototype,
            is_variadic=is_variadic,
        )

    def _parse_params(self) -> tuple[list[Param], bool, bool]:
        if self._check_punct(")"):
            return [], False, False
        if self._check_keyword("void") and self._peek_punct(")"):
            self._advance()
            return [], True, False
        if self._check_punct("..."):
            raise ParserError("Expected parameter before ...", self._current())
        params = [self._parse_param()]
        is_variadic = False
        while self._check_punct(","):
            self._advance()
            if self._check_punct("..."):
                self._advance()
                is_variadic = True
                break
            params.append(self._parse_param())
        return params, True, is_variadic

    def _parse_param(self) -> Param:
        base_type = self._parse_type_spec()
        name, declarator_ops = self._parse_declarator(allow_abstract=True)
        declarator_type = self._build_declarator_type(base_type, declarator_ops)
        if self._is_invalid_void_parameter_type(declarator_type):
            raise ParserError("Invalid parameter type", self._previous())
        return Param(declarator_type, name)

    def _parse_type_spec(self) -> TypeSpec:
        token = self._current()
        if token.kind == TokenKind.IDENT:
            assert isinstance(token.lexeme, str)
            type_spec = self._lookup_typedef(token.lexeme)
            if type_spec is None:
                raise ParserError("Unsupported type", token)
            self._advance()
            return type_spec
        token = self._expect(TokenKind.KEYWORD)
        if token.lexeme in {"int", "void"}:
            pointer_depth = self._parse_pointer_depth()
            return TypeSpec(str(token.lexeme), pointer_depth)
        if token.lexeme == "enum":
            enum_tag, enum_members = self._parse_enum_spec(token)
            pointer_depth = self._parse_pointer_depth()
            return TypeSpec(
                "enum",
                pointer_depth,
                enum_tag=enum_tag,
                enum_members=enum_members,
            )
        if token.lexeme in {"struct", "union"}:
            record_tag, record_members = self._parse_record_spec(token, str(token.lexeme))
            pointer_depth = self._parse_pointer_depth()
            return TypeSpec(
                str(token.lexeme),
                pointer_depth,
                record_tag=record_tag,
                record_members=record_members,
            )
        raise ParserError("Unsupported type", token)

    def _parse_pointer_depth(self) -> int:
        pointer_depth = 0
        while self._check_punct("*"):
            self._advance()
            pointer_depth += 1
        return pointer_depth

    def _parse_enum_spec(self, token: Token) -> tuple[str | None, tuple[tuple[str, int], ...]]:
        enum_tag: str | None = None
        if self._current().kind == TokenKind.IDENT:
            ident = self._advance()
            assert isinstance(ident.lexeme, str)
            enum_tag = ident.lexeme
        enum_members: tuple[tuple[str, int], ...] = ()
        if self._check_punct("{"):
            enum_members = self._parse_enum_members()
        if enum_tag is None and not enum_members:
            raise ParserError("Expected enum tag or definition", token)
        return enum_tag, enum_members

    def _parse_enum_members(self) -> tuple[tuple[str, int], ...]:
        self._expect_punct("{")
        if self._check_punct("}"):
            raise ParserError("Expected enumerator", self._current())
        members: list[tuple[str, int]] = []
        next_value = 0
        while True:
            name, value = self._parse_enum_member(next_value)
            members.append((name, value))
            next_value = value + 1
            if not self._check_punct(","):
                break
            self._advance()
            if self._check_punct("}"):
                break
        self._expect_punct("}")
        return tuple(members)

    def _parse_enum_member(self, default_value: int) -> tuple[str, int]:
        token = self._expect(TokenKind.IDENT)
        assert isinstance(token.lexeme, str)
        value = default_value
        if self._check_punct("="):
            self._advance()
            value = self._parse_enum_value()
        return token.lexeme, value

    def _parse_enum_value(self) -> int:
        sign = 1
        if self._check_punct("+"):
            self._advance()
        elif self._check_punct("-"):
            self._advance()
            sign = -1
        token = self._expect(TokenKind.INT_CONST)
        assert isinstance(token.lexeme, str)
        if not token.lexeme.isdigit():
            raise ParserError("Unsupported enum value", token)
        return sign * int(token.lexeme)

    def _parse_record_spec(
        self,
        token: Token,
        kind: str,
    ) -> tuple[str | None, tuple[tuple[TypeSpec, str], ...]]:
        record_tag: str | None = None
        if self._current().kind == TokenKind.IDENT:
            ident = self._advance()
            assert isinstance(ident.lexeme, str)
            record_tag = ident.lexeme
        record_members: tuple[tuple[TypeSpec, str], ...] = ()
        if self._check_punct("{"):
            record_members = self._parse_record_members()
        if record_tag is None and not record_members:
            raise ParserError(f"Expected {kind} tag or definition", token)
        return record_tag, record_members

    def _parse_record_members(self) -> tuple[tuple[TypeSpec, str], ...]:
        self._expect_punct("{")
        if self._check_punct("}"):
            raise ParserError("Expected member declaration", self._current())
        members: list[tuple[TypeSpec, str]] = []
        while not self._check_punct("}"):
            members.extend(self._parse_record_member_declaration())
        self._expect_punct("}")
        return tuple(members)

    def _parse_record_member_declaration(self) -> list[tuple[TypeSpec, str]]:
        base_type = self._parse_type_spec()
        members: list[tuple[TypeSpec, str]] = []
        while True:
            name, declarator_ops = self._parse_declarator(allow_abstract=False)
            if name is None:
                raise ParserError("Expected identifier", self._current())
            member_type = self._build_declarator_type(base_type, declarator_ops)
            if self._is_invalid_void_object_type(member_type):
                raise ParserError("Invalid member type", self._current())
            members.append((member_type, name))
            if not self._check_punct(","):
                break
            self._advance()
        self._expect_punct(";")
        return members

    def _parse_compound_stmt(self, initial_names: set[str] | None = None) -> CompoundStmt:
        self._expect_punct("{")
        self._push_scope(initial_names)
        try:
            statements: list[Stmt] = []
            while not self._check_punct("}"):
                statements.append(self._parse_statement())
            self._expect_punct("}")
            return CompoundStmt(statements)
        finally:
            self._pop_scope()

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
        if self._check_keyword("do"):
            return self._parse_do_while_stmt()
        if self._check_keyword("for"):
            return self._parse_for_stmt()
        if self._check_keyword("switch"):
            return self._parse_switch_stmt()
        if self._check_keyword("case"):
            return self._parse_case_stmt()
        if self._check_keyword("default"):
            return self._parse_default_stmt()
        if self._is_label_start():
            return self._parse_label_stmt()
        if self._check_keyword("goto"):
            return self._parse_goto_stmt()
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
        if self._is_declaration_start():
            return self._parse_decl_stmt()
        expr = self._parse_expression()
        self._expect_punct(";")
        return ExprStmt(expr)

    def _is_declaration_start(self) -> bool:
        if (
            self._check_keyword("int")
            or self._check_keyword("void")
            or self._check_keyword("enum")
            or self._check_keyword("struct")
            or self._check_keyword("union")
            or self._check_keyword("typedef")
        ):
            return True
        token = self._current()
        if token.kind != TokenKind.IDENT or not isinstance(token.lexeme, str):
            return False
        return self._is_typedef_name(token.lexeme)

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

    def _parse_do_while_stmt(self) -> DoWhileStmt:
        self._advance()
        body = self._parse_statement()
        if not self._check_keyword("while"):
            raise ParserError("Expected while", self._current())
        self._advance()
        self._expect_punct("(")
        condition = self._parse_expression()
        self._expect_punct(")")
        self._expect_punct(";")
        return DoWhileStmt(body, condition)

    def _parse_for_stmt(self) -> ForStmt:
        self._advance()
        self._expect_punct("(")
        self._push_scope()
        try:
            init: Stmt | Expr | None
            if self._check_punct(";"):
                self._advance()
                init = None
            elif self._is_declaration_start():
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
        finally:
            self._pop_scope()

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

    def _parse_label_stmt(self) -> LabelStmt:
        token = self._expect(TokenKind.IDENT)
        assert isinstance(token.lexeme, str)
        self._expect_punct(":")
        body = self._parse_statement()
        return LabelStmt(token.lexeme, body)

    def _parse_goto_stmt(self) -> GotoStmt:
        self._advance()
        label = self._expect(TokenKind.IDENT)
        assert isinstance(label.lexeme, str)
        self._expect_punct(";")
        return GotoStmt(label.lexeme)

    def _is_label_start(self) -> bool:
        token = self._current()
        return token.kind == TokenKind.IDENT and self._peek_punct(":")

    def _parse_decl_stmt(self) -> Stmt:
        is_typedef = False
        if self._check_keyword("typedef"):
            self._advance()
            is_typedef = True
        base_type = self._parse_type_spec()
        if self._check_punct(";"):
            if is_typedef or not self._is_tag_or_definition_decl(base_type):
                raise ParserError("Expected identifier", self._current())
            self._expect_punct(";")
            self._define_enum_member_names(base_type)
            return DeclStmt(base_type, None, None)
        declarations: list[DeclStmt | TypedefDecl] = []
        while True:
            name, declarator_ops = self._parse_declarator(allow_abstract=False)
            if name is None:
                raise ParserError("Expected identifier", self._current())
            decl_type = self._build_declarator_type(base_type, declarator_ops)
            if is_typedef:
                if self._check_punct("="):
                    raise ParserError("Typedef cannot have initializer", self._current())
                self._define_typedef(name, decl_type)
                declarations.append(TypedefDecl(decl_type, name))
            else:
                if self._is_invalid_void_object_type(decl_type):
                    raise ParserError("Invalid object type", self._current())
                self._define_ordinary_name(name)
                init: Expr | None = None
                if self._check_punct("="):
                    self._advance()
                    init = self._parse_assignment()
                declarations.append(DeclStmt(decl_type, name, init))
            if not self._check_punct(","):
                break
            self._advance()
        self._expect_punct(";")
        self._define_enum_member_names(base_type)
        if len(declarations) == 1:
            return declarations[0]
        return DeclGroupStmt(declarations)

    def _is_tag_or_definition_decl(self, type_spec: TypeSpec) -> bool:
        if type_spec.name == "enum":
            return type_spec.enum_tag is not None or bool(type_spec.enum_members)
        if type_spec.name in {"struct", "union"}:
            return type_spec.record_tag is not None or bool(type_spec.record_members)
        return False

    def _define_enum_member_names(self, type_spec: TypeSpec) -> None:
        for member_name, _ in type_spec.enum_members:
            self._define_ordinary_name(member_name)

    def _parse_return_stmt(self) -> ReturnStmt:
        self._advance()
        if self._check_punct(";"):
            self._expect_punct(";")
            return ReturnStmt(None)
        value = self._parse_expression()
        self._expect_punct(";")
        return ReturnStmt(value)

    def _parse_expression(self) -> Expr:
        expr = self._parse_assignment()
        while self._check_punct(","):
            self._advance()
            right = self._parse_assignment()
            expr = CommaExpr(expr, right)
        return expr

    def _parse_assignment(self) -> Expr:
        expr = self._parse_conditional()
        if self._is_assignment_operator():
            op = str(self._advance().lexeme)
            value = self._parse_assignment()
            return AssignExpr(op, expr, value)
        return expr

    def _parse_conditional(self) -> Expr:
        expr = self._parse_logical_or()
        if not self._check_punct("?"):
            return expr
        self._advance()
        then_expr = self._parse_expression()
        self._expect_punct(":")
        else_expr = self._parse_conditional()
        return ConditionalExpr(expr, then_expr, else_expr)

    def _parse_logical_or(self) -> Expr:
        expr = self._parse_logical_and()
        while self._check_punct("||"):
            op = self._advance().lexeme
            right = self._parse_logical_and()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_logical_and(self) -> Expr:
        expr = self._parse_bitwise_or()
        while self._check_punct("&&"):
            op = self._advance().lexeme
            right = self._parse_bitwise_or()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_bitwise_or(self) -> Expr:
        expr = self._parse_bitwise_xor()
        while self._check_punct("|"):
            op = self._advance().lexeme
            right = self._parse_bitwise_xor()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_bitwise_xor(self) -> Expr:
        expr = self._parse_bitwise_and()
        while self._check_punct("^"):
            op = self._advance().lexeme
            right = self._parse_bitwise_and()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_bitwise_and(self) -> Expr:
        expr = self._parse_equality()
        while self._check_punct("&"):
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
        expr = self._parse_shift()
        while (
            self._check_punct("<")
            or self._check_punct("<=")
            or self._check_punct(">")
            or self._check_punct(">=")
        ):
            op = self._advance().lexeme
            right = self._parse_shift()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_shift(self) -> Expr:
        expr = self._parse_additive()
        while self._check_punct("<<") or self._check_punct(">>"):
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
        while self._check_punct("*") or self._check_punct("/") or self._check_punct("%"):
            op = self._advance().lexeme
            right = self._parse_unary()
            expr = BinaryExpr(str(op), expr, right)
        return expr

    def _parse_unary(self) -> Expr:
        if self._check_keyword("sizeof"):
            return self._parse_sizeof_expr()
        if self._is_parenthesized_type_name_start():
            return self._parse_cast_expr()
        if self._check_punct("++") or self._check_punct("--"):
            op = str(self._advance().lexeme)
            operand = self._parse_unary()
            return UpdateExpr(op, operand, False)
        if (
            self._check_punct("+")
            or self._check_punct("-")
            or self._check_punct("!")
            or self._check_punct("~")
            or self._check_punct("&")
            or self._check_punct("*")
        ):
            op = self._advance().lexeme
            operand = self._parse_unary()
            return UnaryExpr(str(op), operand)
        return self._parse_postfix()

    def _parse_sizeof_expr(self) -> SizeofExpr:
        self._advance()
        if self._is_parenthesized_type_name_start():
            type_spec = self._parse_parenthesized_type_name()
            return SizeofExpr(None, type_spec)
        operand = self._parse_unary()
        return SizeofExpr(operand, None)

    def _parse_cast_expr(self) -> CastExpr:
        type_spec = self._parse_parenthesized_type_name()
        operand = self._parse_unary()
        return CastExpr(type_spec, operand)

    def _parse_parenthesized_type_name(self) -> TypeSpec:
        self._expect_punct("(")
        base_type = self._parse_type_spec()
        name, declarator_ops = self._parse_declarator(allow_abstract=True)
        if name is not None:
            raise ParserError("Expected type name", self._current())
        self._expect_punct(")")
        return self._build_declarator_type(base_type, declarator_ops)

    def _is_parenthesized_type_name_start(self) -> bool:
        if not self._check_punct("("):
            return False
        token = self._peek()
        if token.kind == TokenKind.KEYWORD:
            return str(token.lexeme) in {"int", "void", "enum", "struct", "union"}
        if token.kind == TokenKind.IDENT and isinstance(token.lexeme, str):
            return self._is_typedef_name(token.lexeme)
        return False

    def _parse_postfix(self) -> Expr:
        expr = self._parse_primary()
        while True:
            if self._check_punct("("):
                self._advance()
                args = self._parse_arguments()
                self._expect_punct(")")
                expr = CallExpr(expr, args)
                continue
            if self._check_punct("["):
                self._advance()
                index = self._parse_expression()
                self._expect_punct("]")
                expr = SubscriptExpr(expr, index)
                continue
            if self._check_punct("."):
                self._advance()
                member_token = self._expect(TokenKind.IDENT)
                assert isinstance(member_token.lexeme, str)
                expr = MemberExpr(expr, member_token.lexeme, False)
                continue
            if self._check_punct("->"):
                self._advance()
                member_token = self._expect(TokenKind.IDENT)
                assert isinstance(member_token.lexeme, str)
                expr = MemberExpr(expr, member_token.lexeme, True)
                continue
            if self._check_punct("++") or self._check_punct("--"):
                op = str(self._advance().lexeme)
                expr = UpdateExpr(op, expr, True)
                continue
            break
        return expr

    def _build_declarator_type(
        self,
        base_type: TypeSpec,
        declarator_ops: tuple[DeclaratorOp, ...],
    ) -> TypeSpec:
        combined_ops = declarator_ops + base_type.declarator_ops
        return TypeSpec(
            base_type.name,
            declarator_ops=combined_ops,
            enum_tag=base_type.enum_tag,
            enum_members=base_type.enum_members,
            record_tag=base_type.record_tag,
            record_members=base_type.record_members,
        )

    def _is_invalid_void_object_type(self, type_spec: TypeSpec) -> bool:
        if type_spec.name != "void":
            return False
        return not any(kind == "ptr" for kind, _ in type_spec.declarator_ops)

    def _is_invalid_void_parameter_type(self, type_spec: TypeSpec) -> bool:
        if type_spec.name != "void":
            return False
        return not type_spec.declarator_ops

    def _parse_declarator(
        self,
        allow_abstract: bool,
    ) -> tuple[str | None, tuple[DeclaratorOp, ...]]:
        pointer_count = 0
        while self._check_punct("*"):
            self._advance()
            pointer_count += 1
        name, ops = self._parse_direct_declarator(allow_abstract)
        if pointer_count:
            ops = ops + (POINTER_OP,) * pointer_count
        return name, ops

    def _parse_direct_declarator(
        self,
        allow_abstract: bool,
    ) -> tuple[str | None, tuple[DeclaratorOp, ...]]:
        name: str | None
        ops: tuple[DeclaratorOp, ...]
        if self._current().kind == TokenKind.IDENT:
            token = self._advance()
            assert isinstance(token.lexeme, str)
            name = token.lexeme
            ops = ()
        elif self._check_punct("("):
            self._advance()
            name, ops = self._parse_declarator(allow_abstract=True)
            self._expect_punct(")")
        elif allow_abstract:
            name = None
            ops = ()
        else:
            raise ParserError("Expected identifier", self._current())
        while True:
            if self._check_punct("["):
                self._advance()
                size_token = self._expect(TokenKind.INT_CONST)
                size = self._parse_array_size(size_token)
                self._expect_punct("]")
                ops = ops + (("arr", size),)
                continue
            if self._check_punct("("):
                self._advance()
                function_declarator = self._parse_function_suffix_params()
                self._expect_punct(")")
                ops = ops + (("fn", function_declarator),)
                continue
            break
        return name, ops

    def _parse_array_size(self, token: Token) -> int:
        lexeme = token.lexeme
        if not isinstance(lexeme, str) or not lexeme.isdigit():
            raise ParserError("Unsupported array size", token)
        size = int(lexeme)
        if size <= 0:
            raise ParserError("Array size must be positive", token)
        return size

    def _parse_function_suffix_params(self) -> FunctionDeclarator:
        if self._check_punct(")"):
            return None, False
        if self._check_keyword("void") and self._peek_punct(")"):
            self._advance()
            return (), False
        if self._check_punct("..."):
            raise ParserError("Expected parameter before ...", self._current())
        params = [self._parse_param().type_spec]
        is_variadic = False
        while self._check_punct(","):
            self._advance()
            if self._check_punct("..."):
                self._advance()
                is_variadic = True
                break
            params.append(self._parse_param().type_spec)
        return tuple(params), is_variadic

    def _parse_arguments(self) -> list[Expr]:
        if self._check_punct(")"):
            return []
        args = [self._parse_assignment()]
        while self._check_punct(","):
            self._advance()
            args.append(self._parse_assignment())
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

    def _is_assignment_operator(self) -> bool:
        token = self._current()
        return token.kind == TokenKind.PUNCTUATOR and token.lexeme in ASSIGNMENT_OPERATORS

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
