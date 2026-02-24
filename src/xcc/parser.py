from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Literal, cast

from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CallExpr,
    CaseStmt,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundLiteralExpr,
    CompoundStmt,
    ConditionalExpr,
    ContinueStmt,
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
    DoWhileStmt,
    Expr,
    ExprStmt,
    FloatLiteral,
    ForStmt,
    FunctionDef,
    GenericExpr,
    GotoStmt,
    Identifier,
    IfStmt,
    IndirectGotoStmt,
    InitItem,
    InitList,
    IntLiteral,
    LabelAddressExpr,
    LabelStmt,
    MemberExpr,
    NullStmt,
    Param,
    RecordMemberDecl,
    ReturnStmt,
    SizeofExpr,
    StatementExpr,
    StaticAssertDecl,
    Stmt,
    StorageClass,
    StringLiteral,
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
DeclaratorOp = tuple[str, int | ArrayDecl | FunctionDeclarator]
POINTER_OP: DeclaratorOp = ("ptr", 0)
ASSIGNMENT_OPERATORS = ("=", "+=", "-=", "*=", "/=", "%=", "<<=", ">>=", "&=", "^=", "|=")
INTEGER_TYPE_KEYWORDS = {"int", "char", "short", "long", "signed", "unsigned"}
FLOATING_TYPE_KEYWORDS = {"float", "double"}
SIMPLE_TYPE_SPEC_KEYWORDS = INTEGER_TYPE_KEYWORDS | FLOATING_TYPE_KEYWORDS | {"void"}
PAREN_TYPE_NAME_KEYWORDS = SIMPLE_TYPE_SPEC_KEYWORDS | {
    "_Atomic",
    "_Bool",
    "_Complex",
    "enum",
    "struct",
    "union",
}
TYPE_QUALIFIER_KEYWORDS = {"const", "volatile", "restrict"}
STORAGE_CLASS_KEYWORDS = {"auto", "register", "static", "extern", "typedef"}
EXTERNAL_STATEMENT_KEYWORDS = {
    "break",
    "case",
    "continue",
    "default",
    "do",
    "for",
    "goto",
    "if",
    "return",
    "switch",
    "while",
}


_INTEGER_LITERAL_SUFFIXES = {"", "u", "l", "ul", "lu", "ll", "ull", "llu"}
_POINTER_SIZE = 8
_BASE_TYPE_SIZES = {
    "_Bool": 1,
    "char": 1,
    "unsigned char": 1,
    "short": 2,
    "unsigned short": 2,
    "int": 4,
    "unsigned int": 4,
    "long": 8,
    "unsigned long": 8,
    "long long": 8,
    "unsigned long long": 8,
    "float": 4,
    "double": 8,
    "long double": 16,
    "enum": 4,
}
_EXTENSION_MARKER = "__extension__"
StdMode = Literal["c11", "gnu11"]


def _parse_int_literal_value(lexeme: str) -> int | None:
    suffix_start = len(lexeme)
    while suffix_start > 0 and lexeme[suffix_start - 1] in "uUlL":
        suffix_start -= 1
    body = lexeme[:suffix_start]
    suffix = lexeme[suffix_start:].lower()
    if suffix not in _INTEGER_LITERAL_SUFFIXES:
        return None
    if body.startswith(("0x", "0X")):
        digits = body[2:]
        return None if not digits else int(digits, 16)
    if body.startswith("0") and len(body) > 1:
        if any(ch not in "01234567" for ch in body):
            return None
        return int(body, 8)
    if not body.isdigit():
        return None
    return int(body)


def _array_size_literal_error(lexeme: str) -> str | None:
    suffix_start = len(lexeme)
    while suffix_start > 0 and lexeme[suffix_start - 1] in "uUlL":
        suffix_start -= 1
    body = lexeme[:suffix_start]
    suffix = lexeme[suffix_start:].lower()
    if suffix not in _INTEGER_LITERAL_SUFFIXES:
        return "Array size literal has unsupported integer suffix"
    if body.startswith(("0x", "0X")):
        digits = body[2:]
        if not digits:
            return "Array size hexadecimal literal requires at least one digit"
        return None
    if body.startswith("0") and len(body) > 1:
        if any(ch not in "01234567" for ch in body):
            return "Array size octal literal contains non-octal digits"
        return None
    if not body.isdigit():
        return "Array size literal must contain decimal digits"
    return None


def _array_size_non_ice_error(
    expr: Expr,
    eval_expr: Callable[[Expr], int | None],
) -> str:
    if isinstance(expr, Identifier):
        return f"Array size identifier '{expr.name}' is not an integer constant expression"
    if isinstance(expr, UnaryExpr):
        return f"Array size unary operator '{expr.op}' is not an integer constant expression"
    if isinstance(expr, BinaryExpr):
        return f"Array size binary operator '{expr.op}' is not an integer constant expression"
    if isinstance(expr, CallExpr):
        return "Array size call expression is not an integer constant expression"
    if isinstance(expr, GenericExpr):
        return "Array size generic selection is not an integer constant expression"
    if isinstance(expr, CommaExpr):
        return "Array size comma expression is not an integer constant expression"
    if isinstance(expr, AssignExpr):
        return "Array size assignment expression is not an integer constant expression"
    if isinstance(expr, UpdateExpr):
        return "Array size update expression is not an integer constant expression"
    if isinstance(expr, SubscriptExpr):
        return "Array size subscript expression is not an integer constant expression"
    if isinstance(expr, MemberExpr):
        return "Array size member access expression is not an integer constant expression"
    if isinstance(expr, CompoundLiteralExpr):
        return "Array size compound literal is not an integer constant expression"
    if isinstance(expr, IntLiteral):
        return "Array size integer literal is not an integer constant expression"
    if isinstance(expr, FloatLiteral):
        return "Array size floating literal is not an integer constant expression"
    if isinstance(expr, CharLiteral):
        return "Array size character literal is not an integer constant expression"
    if isinstance(expr, StringLiteral):
        return "Array size string literal is not an integer constant expression"
    if isinstance(expr, StatementExpr):
        return "Array size statement expression is not an integer constant expression"
    if isinstance(expr, LabelAddressExpr):
        return "Array size label address expression is not an integer constant expression"
    if isinstance(expr, CastExpr):
        if eval_expr(expr.expr) is None:
            return _array_size_non_ice_error(expr.expr, eval_expr)
        return "Array size cast expression is not an integer constant expression"
    if isinstance(expr, SizeofExpr):
        return "Array size sizeof expression is not an integer constant expression"
    if isinstance(expr, AlignofExpr):
        return "Array size alignof expression is not an integer constant expression"
    if isinstance(expr, ConditionalExpr):
        if eval_expr(expr.condition) is None:
            return "Array size conditional condition is not an integer constant expression"
        branch = expr.then_expr if eval_expr(expr.condition) != 0 else expr.else_expr
        if eval_expr(branch) is None:
            return _array_size_non_ice_error(branch, eval_expr)
        return "Array size conditional expression is not an integer constant expression"
    return f"Array size expression '{type(expr).__name__}' is not an integer constant expression"


@dataclass(frozen=True)
class ParserError(ValueError):
    message: str
    token: Token

    def __str__(self) -> str:
        return f"{self.message} at {self.token.line}:{self.token.column}"


@dataclass(frozen=True)
class DeclSpecInfo:
    is_typedef: bool = False
    storage_class: StorageClass | None = None
    storage_class_token: Token | None = None
    alignment: int | None = None
    alignment_token: Token | None = None
    is_thread_local: bool = False
    is_inline: bool = False
    is_noreturn: bool = False


class Parser:
    def __init__(self, tokens: list[Token], *, std: StdMode = "c11") -> None:
        self._tokens = tokens
        self._index = 0
        self._std = std
        self._typedef_scopes: list[dict[str, TypeSpec]] = [{}]
        self._typedef_qualified_scopes: list[dict[str, bool]] = [{}]
        self._ordinary_name_scopes: list[set[str]] = [set()]
        self._ordinary_type_scopes: list[dict[str, TypeSpec]] = [{}]

    def _push_scope(
        self,
        names: set[str] | None = None,
        types: dict[str, TypeSpec] | None = None,
    ) -> None:
        self._typedef_scopes.append({})
        self._typedef_qualified_scopes.append({})
        if names is None:
            self._ordinary_name_scopes.append(set())
        else:
            self._ordinary_name_scopes.append(set(names))
        self._ordinary_type_scopes.append({} if types is None else dict(types))

    def _pop_scope(self) -> None:
        self._typedef_scopes.pop()
        self._typedef_qualified_scopes.pop()
        self._ordinary_name_scopes.pop()
        self._ordinary_type_scopes.pop()

    def _define_typedef(
        self,
        name: str,
        type_spec: TypeSpec,
        *,
        is_top_level_qualified: bool = False,
    ) -> None:
        self._typedef_scopes[-1][name] = type_spec
        self._typedef_qualified_scopes[-1][name] = is_top_level_qualified

    def _define_ordinary_name(self, name: str) -> None:
        self._ordinary_name_scopes[-1].add(name)

    def _define_ordinary_type(self, name: str, type_spec: TypeSpec) -> None:
        self._define_ordinary_name(name)
        self._ordinary_type_scopes[-1][name] = type_spec

    def _lookup_ordinary_type(self, name: str) -> TypeSpec | None:
        for types, ordinary_names in zip(
            reversed(self._ordinary_type_scopes),
            reversed(self._ordinary_name_scopes),
            strict=True,
        ):
            if name in ordinary_names:
                return types.get(name)
        return None

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

    def _is_top_level_qualified_typedef(self, name: str) -> bool:
        for typedefs, typedef_qualified, ordinary_names in zip(
            reversed(self._typedef_scopes),
            reversed(self._typedef_qualified_scopes),
            reversed(self._ordinary_name_scopes),
            strict=True,
        ):
            if name in ordinary_names:
                return False
            if name in typedefs:
                return bool(typedef_qualified.get(name, False))
        return False

    def _is_typedef_name(self, name: str) -> bool:
        return self._lookup_typedef(name) is not None

    def parse(self) -> TranslationUnit:
        functions: list[FunctionDef] = []
        declarations: list[Stmt] = []
        externals: list[FunctionDef | Stmt] = []
        while not self._match(TokenKind.EOF):
            self._skip_extension_markers()
            if self._match(TokenKind.EOF):
                break
            if self._check_keyword("_Static_assert"):
                declaration = self._parse_static_assert_decl()
                declarations.append(declaration)
                externals.append(declaration)
                continue
            if self._looks_like_function():
                function = self._parse_function()
                functions.append(function)
                externals.append(function)
                continue
            if self._is_external_statement_start():
                token = self._current()
                assert isinstance(token.lexeme, str)
                raise ParserError(f"{token.lexeme} statement outside of a function", token)
            declaration = self._parse_decl_stmt()
            declarations.append(declaration)
            externals.append(declaration)
        self._expect(TokenKind.EOF)
        return TranslationUnit(functions, declarations, externals)

    def _is_external_statement_start(self) -> bool:
        token = self._current()
        return token.kind == TokenKind.KEYWORD and token.lexeme in EXTERNAL_STATEMENT_KEYWORDS

    def _expected_identifier_error(self, token: Token | None = None) -> ParserError:
        culprit = self._current() if token is None else token
        if culprit.kind == TokenKind.EOF:
            return ParserError("Expected identifier before end of input", culprit)
        lexeme = culprit.lexeme
        if lexeme is None:
            return ParserError("Expected identifier", culprit)
        return ParserError(f"Expected identifier before '{lexeme}'", culprit)

    def _looks_like_function(self) -> bool:
        saved_index = self._index
        try:
            decl_specs = self._consume_decl_specifiers()
            if decl_specs.is_typedef:
                return False
            self._parse_type_spec()
            self._skip_gnu_attributes()
            if self._current().kind != TokenKind.IDENT:
                return False
            self._advance()
            self._skip_gnu_attributes()
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
        decl_specs = self._consume_decl_specifiers()
        self._reject_invalid_alignment_context(
            decl_specs.alignment,
            decl_specs.alignment_token,
            context="function declaration",
            allow=False,
        )
        return_type = self._parse_type_spec()
        is_overloadable = self._consume_overloadable_gnu_attributes()
        name = self._expect(TokenKind.IDENT).lexeme
        function_name = str(name)
        if self._consume_overloadable_gnu_attributes():
            is_overloadable = True
        self._expect_punct("(")
        params, has_prototype, is_variadic = self._parse_params()
        self._expect_punct(")")
        param_types = tuple(param.type_spec for param in params) if has_prototype else None
        function_type = self._build_declarator_type(
            return_type,
            (
                (
                    "fn",
                    (param_types, is_variadic),
                ),
            ),
        )
        self._define_ordinary_type(function_name, function_type)
        if self._check_punct(";"):
            self._advance()
            return FunctionDef(
                return_type,
                function_name,
                params,
                None,
                storage_class=cast(Literal["static", "extern"] | None, decl_specs.storage_class),
                is_thread_local=decl_specs.is_thread_local,
                is_inline=decl_specs.is_inline,
                is_noreturn=decl_specs.is_noreturn,
                has_prototype=has_prototype,
                is_variadic=is_variadic,
                is_overloadable=is_overloadable,
            )
        if any(param.name is None for param in params):
            raise ParserError("Expected parameter name", self._current())
        parameter_names = {param.name for param in params if param.name is not None}
        parameter_types = {
            param.name: param.type_spec for param in params if param.name is not None
        }
        body = self._parse_compound_stmt(
            initial_names=parameter_names,
            initial_types=parameter_types,
        )
        return FunctionDef(
            return_type,
            function_name,
            params,
            body,
            storage_class=cast(Literal["static", "extern"] | None, decl_specs.storage_class),
            is_thread_local=decl_specs.is_thread_local,
            is_inline=decl_specs.is_inline,
            is_noreturn=decl_specs.is_noreturn,
            has_prototype=has_prototype,
            is_variadic=is_variadic,
            is_overloadable=is_overloadable,
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
            comma = self._advance()
            if self._check_punct(")"):
                raise ParserError("Expected parameter after ','", comma)
            if self._check_punct("..."):
                self._advance()
                is_variadic = True
                if not self._check_punct(")"):
                    raise ParserError("Expected ')' after ... in parameter list", self._current())
                break
            params.append(self._parse_param())
        return params, True, is_variadic

    def _parse_param(self) -> Param:
        decl_specs = self._consume_decl_specifiers()
        if decl_specs.storage_class not in {None, "register"}:
            storage_class = decl_specs.storage_class or "<unknown>"
            raise ParserError(
                f"Invalid storage class for parameter: '{storage_class}'",
                decl_specs.storage_class_token or self._current(),
            )
        if decl_specs.is_thread_local or decl_specs.is_inline or decl_specs.is_noreturn:
            raise ParserError(
                self._invalid_decl_specifier_message("parameter", decl_specs),
                self._current(),
            )
        self._reject_invalid_alignment_context(
            decl_specs.alignment,
            decl_specs.alignment_token,
            context="parameter",
            allow=False,
        )
        base_type = self._parse_type_spec()
        name, declarator_ops = self._parse_declarator(
            allow_abstract=True,
            allow_vla=True,
            allow_parameter_arrays=True,
        )
        declarator_type = self._build_declarator_type(base_type, declarator_ops)
        if self._is_invalid_void_parameter_type(declarator_type):
            raise ParserError("Invalid parameter type", self._previous())
        return Param(declarator_type, name)

    def _parse_type_spec(
        self,
        *,
        parse_pointer_depth: bool = True,
        context: str = "declaration",
    ) -> TypeSpec:
        qualifiers = self._consume_type_qualifiers()
        if self._check_keyword("_Atomic"):
            atomic_token = self._advance()
            if self._check_punct("("):
                (
                    atomic_base,
                    is_qualified_atomic_target,
                ) = self._parse_parenthesized_atomic_type_name()
                invalid_reason = self._classify_invalid_atomic_type(
                    atomic_base,
                    is_qualified_atomic_target=is_qualified_atomic_target,
                )
                if invalid_reason is not None:
                    raise ParserError(
                        self._format_invalid_atomic_type_message(invalid_reason),
                        atomic_token,
                    )
                atomic_type = self._mark_atomic_type_spec(atomic_base)
                if parse_pointer_depth:
                    pointer_depth = self._parse_pointer_depth()
                    if pointer_depth:
                        atomic_type = self._build_declarator_type(
                            atomic_type,
                            (POINTER_OP,) * pointer_depth,
                        )
                return self._apply_type_qualifiers(atomic_type, qualifiers)
            if self._current().kind not in {TokenKind.KEYWORD, TokenKind.IDENT}:
                raise ParserError("Expected type name after _Atomic", atomic_token)
            atomic_base = self._parse_type_spec(parse_pointer_depth=False, context=context)
            invalid_reason = self._classify_invalid_atomic_type(
                atomic_base,
                include_atomic=False,
            )
            if invalid_reason is not None:
                raise ParserError(
                    self._format_invalid_atomic_type_message(invalid_reason),
                    atomic_token,
                )
            atomic_type = self._mark_atomic_type_spec(atomic_base)
            if parse_pointer_depth:
                pointer_depth = self._parse_pointer_depth()
                if pointer_depth:
                    atomic_type = self._build_declarator_type(
                        atomic_type,
                        (POINTER_OP,) * pointer_depth,
                    )
            return self._apply_type_qualifiers(atomic_type, qualifiers)
        token = self._current()
        if token.kind == TokenKind.IDENT:
            assert isinstance(token.lexeme, str)
            type_spec = self._lookup_typedef(token.lexeme)
            if type_spec is None:
                raise ParserError(self._unsupported_type_message(context, token), token)
            self._advance()
            return self._apply_type_qualifiers(type_spec, qualifiers)
        token = self._current()
        if token.kind != TokenKind.KEYWORD:
            raise ParserError(self._unsupported_type_message(context, token), token)
        self._advance()
        if token.lexeme == "_Complex":
            if self._check_keyword("float") or self._check_keyword("double"):
                complex_base = self._advance()
                assert isinstance(complex_base.lexeme, str)
                pointer_depth = self._parse_pointer_depth() if parse_pointer_depth else 0
                return TypeSpec(str(complex_base.lexeme), pointer_depth, qualifiers=qualifiers)
            if (
                self._check_keyword("long")
                and self._peek().kind == TokenKind.KEYWORD
                and self._peek().lexeme == "double"
            ):
                self._advance()
                self._advance()
                pointer_depth = self._parse_pointer_depth() if parse_pointer_depth else 0
                return TypeSpec("long double", pointer_depth, qualifiers=qualifiers)
            raise ParserError(self._unsupported_type_message(context, token), token)
        if token.lexeme in FLOATING_TYPE_KEYWORDS:
            assert isinstance(token.lexeme, str)
            type_name = str(token.lexeme)
            self._consume_optional_complex_specifier()
            pointer_depth = self._parse_pointer_depth() if parse_pointer_depth else 0
            return TypeSpec(type_name, pointer_depth, qualifiers=qualifiers)
        if token.lexeme == "_Bool":
            pointer_depth = self._parse_pointer_depth() if parse_pointer_depth else 0
            return TypeSpec("_Bool", pointer_depth, qualifiers=qualifiers)
        if token.lexeme in SIMPLE_TYPE_SPEC_KEYWORDS:
            assert isinstance(token.lexeme, str)
            if token.lexeme == "void":
                pointer_depth = self._parse_pointer_depth() if parse_pointer_depth else 0
                return TypeSpec("void", pointer_depth, qualifiers=qualifiers)
            type_name = self._parse_integer_type_spec(token.lexeme, token, context=context)
            if type_name == "long" and self._check_keyword("double"):
                self._advance()
                type_name = "long double"
            self._consume_optional_complex_specifier()
            pointer_depth = self._parse_pointer_depth() if parse_pointer_depth else 0
            return TypeSpec(type_name, pointer_depth, qualifiers=qualifiers)
        if token.lexeme == "enum":
            enum_tag, enum_members = self._parse_enum_spec(token)
            pointer_depth = self._parse_pointer_depth() if parse_pointer_depth else 0
            return TypeSpec(
                "enum",
                pointer_depth,
                qualifiers=qualifiers,
                enum_tag=enum_tag,
                enum_members=enum_members,
            )
        if token.lexeme in {"struct", "union"}:
            record_tag, record_members = self._parse_record_spec(token, str(token.lexeme))
            pointer_depth = self._parse_pointer_depth() if parse_pointer_depth else 0
            return TypeSpec(
                str(token.lexeme),
                pointer_depth,
                qualifiers=qualifiers,
                record_tag=record_tag,
                record_members=record_members,
            )
        raise ParserError(self._unsupported_type_message(context, token), token)

    def _unsupported_type_message(self, context: str, token: Token) -> str:
        token_text = str(token.lexeme)
        if token.kind == TokenKind.IDENT:
            if context == "type-name":
                return f"Unknown type name: '{token_text}'"
            return f"Unknown declaration type name: '{token_text}'"
        if token.kind == TokenKind.KEYWORD:
            if context == "type-name":
                return f"Unsupported type name: '{token_text}'"
            return f"Unsupported declaration type: '{token_text}'"
        token_kind = self._unsupported_type_token_kind(token.kind)
        if context == "type-name":
            if token.kind == TokenKind.PUNCTUATOR:
                return self._unsupported_type_name_punctuator_message(token_text)
            return self._unsupported_type_name_token_message(token_text, token_kind)
        if token.kind == TokenKind.PUNCTUATOR:
            return self._unsupported_declaration_type_punctuator_message(token_text)
        return f"Unsupported declaration type token ({token_kind}): '{token_text}'"

    def _unsupported_type_name_token_message(self, token_text: str, token_kind: str) -> str:
        if token_kind == "end of input":
            return "Type name is missing before end of input"
        return f"Type name cannot start with {token_kind}: '{token_text}'"

    def _unsupported_type_name_punctuator_message(self, punctuator: str) -> str:
        messages = {
            "(": "Type name cannot start with '(': expected a type specifier",
            ")": "Type name is missing before ')'",
            "+": "Type name cannot start with '+': expected a type specifier",
            "++": "Type name cannot start with '++': expected a type specifier",
            "-": "Type name cannot start with '-': expected a type specifier",
            "--": "Type name cannot start with '--': expected a type specifier",
            "<": "Type name cannot start with '<': expected a type specifier",
            "<=": "Type name cannot start with '<=': expected a type specifier",
            "<<": "Type name cannot start with '<<': expected a type specifier",
            ">": "Type name cannot start with '>': expected a type specifier",
            ">=": "Type name cannot start with '>=': expected a type specifier",
            ">>": "Type name cannot start with '>>': expected a type specifier",
            "!": "Type name cannot start with '!': expected a type specifier",
            "~": "Type name cannot start with '~': expected a type specifier",
            "&": "Type name cannot start with '&': expected a type specifier",
            "&&": "Type name cannot start with '&&': expected a type specifier",
            "|": "Type name cannot start with '|': expected a type specifier",
            "||": "Type name cannot start with '||': expected a type specifier",
            "^": "Type name cannot start with '^': expected a type specifier",
            "*": "Type name cannot start with '*': expected a type specifier",
            "/": "Type name cannot start with '/': expected a type specifier",
            "%": "Type name cannot start with '%': expected a type specifier",
            "%:": "Type name cannot start with '%:': expected a type specifier",
            "%:%:": "Type name cannot start with '%:%:': expected a type specifier",
            ".": "Type name cannot start with '.': expected a type specifier",
            "->": "Type name cannot start with '->': expected a type specifier",
            "...": "Type name cannot start with '...': expected a type specifier",
            "[": "Type name cannot start with '[': expected a type specifier",
            "<:": "Type name cannot start with '<:': expected a type specifier",
            "{": "Type name is missing before '{'",
            "<%": "Type name is missing before '<%'",
            "]": "Type name is missing before ']'",
            ":>": "Type name is missing before ':>'",
            ",": "Type name is missing before ','",
            ":": "Type name is missing before ':'",
            ";": "Type name is missing before ';'",
            "?": "Type name is missing before '?'",
            "#": "Type name cannot start with '#': expected a type specifier",
            "##": "Type name cannot start with '##': expected a type specifier",
            "=": "Type name cannot start with '=': expected a type specifier",
            "==": "Type name cannot start with '==': expected a type specifier",
            "!=": "Type name cannot start with '!=': expected a type specifier",
            "+=": "Type name cannot start with '+=': expected a type specifier",
            "-=": "Type name cannot start with '-=': expected a type specifier",
            "*=": "Type name cannot start with '*=': expected a type specifier",
            "/=": "Type name cannot start with '/=': expected a type specifier",
            "%=": "Type name cannot start with '%=': expected a type specifier",
            "&=": "Type name cannot start with '&=': expected a type specifier",
            "|=": "Type name cannot start with '|=': expected a type specifier",
            "^=": "Type name cannot start with '^=': expected a type specifier",
            "<<=": "Type name cannot start with '<<=': expected a type specifier",
            ">>=": "Type name cannot start with '>>=': expected a type specifier",
            "}": "Type name is missing before '}'",
            "%>": "Type name is missing before '%>'",
        }
        return messages.get(punctuator, f"Unsupported type name punctuator: '{punctuator}'")

    def _unsupported_declaration_type_punctuator_message(self, punctuator: str) -> str:
        messages = {
            "(": "Declaration type cannot start with '(': expected a type specifier",
            ")": "Declaration type is missing before ')'",
            "+": "Declaration type is missing before '+': expected a type specifier",
            "++": "Declaration type is missing before '++': expected a type specifier",
            "-": "Declaration type is missing before '-': expected a type specifier",
            "--": "Declaration type is missing before '--': expected a type specifier",
            "<": "Declaration type is missing before '<': expected a type specifier",
            "<=": "Declaration type is missing before '<=': expected a type specifier",
            "<<": "Declaration type is missing before '<<': expected a type specifier",
            ">": "Declaration type is missing before '>': expected a type specifier",
            ">=": "Declaration type is missing before '>=': expected a type specifier",
            ">>": "Declaration type is missing before '>>': expected a type specifier",
            "!": "Declaration type is missing before '!': expected a type specifier",
            "~": "Declaration type is missing before '~': expected a type specifier",
            "&": "Declaration type is missing before '&': expected a type specifier",
            "&&": "Declaration type is missing before '&&': expected a type specifier",
            "|": "Declaration type is missing before '|': expected a type specifier",
            "||": "Declaration type is missing before '||': expected a type specifier",
            "^": "Declaration type is missing before '^': expected a type specifier",
            "/": "Declaration type is missing before '/': expected a type specifier",
            "%": "Declaration type is missing before '%': expected a type specifier",
            "%:": "Declaration type is missing before '%:': expected a type specifier",
            "%:%:": "Declaration type is missing before '%:%:': expected a type specifier",
            "[": "Declaration type cannot start with '[': expected a type specifier",
            "<:": "Declaration type cannot start with '<:': expected a type specifier",
            "*": "Declaration type is missing before '*': pointer declarator requires a base type",
            ".": "Declaration type is missing before '.': expected a type specifier",
            "->": "Declaration type is missing before '->': expected a type specifier",
            "...": "Declaration type is missing before '...': expected a type specifier",
            ",": "Declaration type is missing before ','",
            ":": "Declaration type is missing before ':'",
            ";": "Declaration type is missing before ';'",
            "?": "Declaration type is missing before '?'",
            "#": "Declaration type is missing before '#': expected a type specifier",
            "##": "Declaration type is missing before '##': expected a type specifier",
            "=": "Declaration type is missing before '=': expected a type specifier",
            "==": "Declaration type is missing before '==': expected a type specifier",
            "!=": "Declaration type is missing before '!=': expected a type specifier",
            "+=": "Declaration type is missing before '+=': expected a type specifier",
            "-=": "Declaration type is missing before '-=': expected a type specifier",
            "*=": "Declaration type is missing before '*=': expected a type specifier",
            "/=": "Declaration type is missing before '/=': expected a type specifier",
            "%=": "Declaration type is missing before '%=': expected a type specifier",
            "&=": "Declaration type is missing before '&=': expected a type specifier",
            "|=": "Declaration type is missing before '|=': expected a type specifier",
            "^=": "Declaration type is missing before '^=': expected a type specifier",
            "<<=": "Declaration type is missing before '<<=': expected a type specifier",
            ">>=": "Declaration type is missing before '>>=': expected a type specifier",
            "]": "Declaration type is missing before ']'",
            ":>": "Declaration type is missing before ':>'",
            "{": "Declaration type is missing before '{'",
            "<%": "Declaration type is missing before '<%'",
            "}": "Declaration type is missing before '}'",
            "%>": "Declaration type is missing before '%>'",
        }
        return messages.get(punctuator, f"Unsupported declaration type punctuator: '{punctuator}'")

    def _unsupported_type_token_kind(self, kind: TokenKind) -> str:
        if kind == TokenKind.INT_CONST:
            return "integer constant"
        if kind == TokenKind.FLOAT_CONST:
            return "floating constant"
        if kind == TokenKind.CHAR_CONST:
            return "character constant"
        if kind == TokenKind.STRING_LITERAL:
            return "string literal"
        if kind == TokenKind.PUNCTUATOR:
            return "punctuator"
        if kind == TokenKind.HEADER_NAME:
            return "header name"
        if kind == TokenKind.PP_NUMBER:
            return "preprocessor number"
        if kind == TokenKind.EOF:
            return "end of input"
        return "token"

    def _consume_type_qualifiers(self, *, allow_atomic: bool = False) -> tuple[str, ...]:
        qualifiers = TYPE_QUALIFIER_KEYWORDS | ({"_Atomic"} if allow_atomic else set())
        seen: list[str] = []
        while self._current().kind == TokenKind.KEYWORD and self._current().lexeme in qualifiers:
            token = self._advance()
            lexeme = str(token.lexeme)
            if lexeme in seen:
                raise ParserError(f"Duplicate type qualifier: '{lexeme}'", token)
            seen.append(lexeme)
        return tuple(seen)

    def _apply_type_qualifiers(
        self,
        type_spec: TypeSpec,
        qualifiers: tuple[str, ...],
    ) -> TypeSpec:
        if not qualifiers:
            return type_spec
        merged = tuple(dict.fromkeys((*type_spec.qualifiers, *qualifiers)))
        return TypeSpec(
            type_spec.name,
            declarator_ops=type_spec.declarator_ops,
            qualifiers=merged,
            is_atomic=type_spec.is_atomic,
            atomic_target=type_spec.atomic_target,
            enum_tag=type_spec.enum_tag,
            enum_members=type_spec.enum_members,
            record_tag=type_spec.record_tag,
            record_members=type_spec.record_members,
        )

    def _consume_optional_complex_specifier(self) -> None:
        if self._check_keyword("_Complex"):
            self._advance()

    def _parse_integer_type_spec(
        self,
        first_keyword: str,
        first_token: Token,
        *,
        context: str = "declaration",
    ) -> str:
        signedness: str | None = None
        base: str | None = None

        def invalid_order(keyword: str, *, current_base: str | None) -> str:
            prior = current_base if current_base is not None else "<none>"
            return f"Invalid integer type keyword order: '{keyword}' after '{prior}'"

        def consume(keyword: str, token: Token) -> None:
            nonlocal signedness, base
            if keyword in {"signed", "unsigned"}:
                if signedness is not None:
                    raise ParserError(
                        f"Duplicate integer signedness specifier: '{keyword}'",
                        token,
                    )
                signedness = keyword
                return
            if keyword == "char":
                if base is not None:
                    raise ParserError(invalid_order(keyword, current_base=base), token)
                base = keyword
                return
            if keyword == "short":
                if base in {None, "int"}:
                    base = keyword
                    return
                raise ParserError(invalid_order(keyword, current_base=base), token)
            if keyword == "long":
                if base in {None, "int"}:
                    base = keyword
                    return
                if base == "long":
                    base = "long long"
                    return
                raise ParserError(invalid_order(keyword, current_base=base), token)
            assert keyword == "int"
            if base is None:
                base = keyword
                return
            if base in {"short", "long", "long long"}:
                return
            raise ParserError(invalid_order(keyword, current_base=base), token)

        consume(first_keyword, first_token)
        while self._current().kind == TokenKind.KEYWORD:
            token = self._current()
            assert isinstance(token.lexeme, str)
            if token.lexeme not in INTEGER_TYPE_KEYWORDS:
                break
            self._advance()
            consume(token.lexeme, token)

        if base is None:
            base = "int"
        if base == "char":
            return "unsigned char" if signedness == "unsigned" else "char"
        if base == "short":
            return "unsigned short" if signedness == "unsigned" else "short"
        if base == "long":
            return "unsigned long" if signedness == "unsigned" else "long"
        if base == "long long":
            return "unsigned long long" if signedness == "unsigned" else "long long"
        return "unsigned int" if signedness == "unsigned" else "int"

    def _parse_pointer_depth(self) -> int:
        self._skip_type_qualifiers()
        pointer_depth = 0
        while self._check_punct("*"):
            self._advance()
            self._skip_type_qualifiers(allow_atomic=True)
            pointer_depth += 1
        return pointer_depth

    def _parse_enum_spec(
        self,
        token: Token,
    ) -> tuple[str | None, tuple[tuple[str, Expr | None], ...]]:
        enum_tag: str | None = None
        if self._current().kind == TokenKind.IDENT:
            ident = self._advance()
            assert isinstance(ident.lexeme, str)
            enum_tag = ident.lexeme
        enum_members: tuple[tuple[str, Expr | None], ...] = ()
        if self._check_punct("{"):
            enum_members = self._parse_enum_members()
        if enum_tag is None and not enum_members:
            raise ParserError("Expected enum tag or definition", token)
        return enum_tag, enum_members

    def _parse_enum_members(self) -> tuple[tuple[str, Expr | None], ...]:
        self._expect_punct("{")
        if self._check_punct("}"):
            raise ParserError("Expected enumerator", self._current())
        members: list[tuple[str, Expr | None]] = []
        while True:
            members.append(self._parse_enum_member())
            if not self._check_punct(","):
                break
            self._advance()
            if self._check_punct("}"):
                break
        self._expect_punct("}")
        return tuple(members)

    def _parse_enum_member(self) -> tuple[str, Expr | None]:
        token = self._expect(TokenKind.IDENT)
        assert isinstance(token.lexeme, str)
        if not self._check_punct("="):
            return token.lexeme, None
        self._advance()
        return token.lexeme, self._parse_conditional()

    def _parse_record_spec(
        self,
        token: Token,
        kind: str,
    ) -> tuple[str | None, tuple[RecordMemberDecl, ...]]:
        record_tag: str | None = None
        if self._current().kind == TokenKind.IDENT:
            ident = self._advance()
            assert isinstance(ident.lexeme, str)
            record_tag = ident.lexeme
        record_members: tuple[RecordMemberDecl, ...] = ()
        if self._check_punct("{"):
            record_members = self._parse_record_members()
        if record_tag is None and not record_members:
            raise ParserError(f"Expected {kind} tag or definition", token)
        return record_tag, record_members

    def _parse_record_members(self) -> tuple[RecordMemberDecl, ...]:
        self._expect_punct("{")
        if self._check_punct("}"):
            raise ParserError("Expected member declaration", self._current())
        members: list[RecordMemberDecl] = []
        while not self._check_punct("}"):
            members.extend(self._parse_record_member_declaration())
        self._expect_punct("}")
        return tuple(members)

    def _parse_record_member_declaration(self) -> list[RecordMemberDecl]:
        decl_specs = self._consume_decl_specifiers()
        if decl_specs.is_typedef or decl_specs.storage_class not in {None, "typedef"}:
            raise ParserError("Expected type specifier", self._current())
        if decl_specs.is_thread_local or decl_specs.is_inline or decl_specs.is_noreturn:
            raise ParserError(
                self._invalid_decl_specifier_message("record member", decl_specs),
                self._current(),
            )
        base_type = self._parse_type_spec()
        if self._check_punct(";"):
            if decl_specs.alignment is not None:
                raise ParserError(
                    self._invalid_alignment_specifier_message("record member declaration"),
                    decl_specs.alignment_token or self._current(),
                )
            raise self._expected_identifier_error()
        members: list[RecordMemberDecl] = []
        while True:
            name, declarator_ops = self._parse_declarator(allow_abstract=True)
            bit_width_expr: Expr | None = None
            if self._check_punct(":"):
                self._advance()
                bit_width_expr = self._parse_conditional()
            if name is None and bit_width_expr is None:
                raise self._expected_identifier_error()
            member_type = self._build_declarator_type(base_type, declarator_ops)
            if decl_specs.alignment is not None and self._is_function_object_type(member_type):
                raise ParserError(
                    self._invalid_alignment_specifier_message("record member declaration"),
                    decl_specs.alignment_token or self._current(),
                )
            if self._is_invalid_void_object_type(member_type):
                raise ParserError("Invalid member type", self._current())
            members.append(
                RecordMemberDecl(
                    member_type,
                    name,
                    decl_specs.alignment,
                    bit_width_expr=bit_width_expr,
                )
            )
            if not self._check_punct(","):
                break
            self._advance()
        self._expect_punct(";")
        return members

    def _parse_compound_stmt(
        self,
        initial_names: set[str] | None = None,
        initial_types: dict[str, TypeSpec] | None = None,
    ) -> CompoundStmt:
        self._expect_punct("{")
        self._push_scope(initial_names, initial_types)
        try:
            statements: list[Stmt] = []
            while not self._check_punct("}"):
                statements.append(self._parse_statement())
            self._expect_punct("}")
            return CompoundStmt(statements)
        finally:
            self._pop_scope()

    def _parse_statement(self) -> Stmt:
        self._skip_extension_markers()
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
        if self._check_keyword("_Static_assert"):
            return self._parse_static_assert_decl()
        if self._is_declaration_start():
            return self._parse_decl_stmt()
        expr = self._parse_expression()
        self._expect_punct(";")
        return ExprStmt(expr)

    def _is_declaration_start(self) -> bool:
        if self._check_keyword(_EXTENSION_MARKER):
            saved_index = self._index
            self._skip_extension_markers()
            is_decl = self._is_declaration_start()
            self._index = saved_index
            return is_decl
        if (
            self._check_keyword("int")
            or self._check_keyword("char")
            or self._check_keyword("void")
            or self._check_keyword("float")
            or self._check_keyword("double")
            or self._check_keyword("short")
            or self._check_keyword("long")
            or self._check_keyword("signed")
            or self._check_keyword("unsigned")
            or self._check_keyword("_Bool")
            or self._check_keyword("_Atomic")
            or self._check_keyword("_Complex")
            or self._check_keyword("enum")
            or self._check_keyword("struct")
            or self._check_keyword("union")
            or self._check_keyword("const")
            or self._check_keyword("volatile")
            or self._check_keyword("restrict")
            or self._check_keyword("typedef")
            or self._check_keyword("auto")
            or self._check_keyword("register")
            or self._check_keyword("static")
            or self._check_keyword("extern")
            or self._check_keyword("inline")
            or self._check_keyword("_Noreturn")
            or self._check_keyword("_Thread_local")
            or self._check_keyword("_Alignas")
            or self._check_keyword("_Static_assert")
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

    def _parse_goto_stmt(self) -> Stmt:
        self._advance()
        if self._check_punct("*"):
            if self._std == "c11":
                raise ParserError("Indirect goto is a GNU extension", self._current())
            self._advance()
            target = self._parse_expression()
            self._expect_punct(";")
            return IndirectGotoStmt(target)
        label = self._expect(TokenKind.IDENT)
        assert isinstance(label.lexeme, str)
        self._expect_punct(";")
        return GotoStmt(label.lexeme)

    def _is_label_start(self) -> bool:
        token = self._current()
        return token.kind == TokenKind.IDENT and self._peek_punct(":")

    def _parse_decl_stmt(self) -> Stmt:
        self._skip_extension_markers()
        if self._check_keyword("_Static_assert"):
            return self._parse_static_assert_decl()
        decl_specs = self._consume_decl_specifiers()
        is_typedef = decl_specs.is_typedef
        if is_typedef and decl_specs.alignment is not None:
            raise ParserError(
                self._invalid_alignment_specifier_message("typedef declaration"),
                decl_specs.alignment_token or self._current(),
            )
        if is_typedef and (
            decl_specs.is_thread_local or decl_specs.is_inline or decl_specs.is_noreturn
        ):
            raise ParserError(
                self._invalid_decl_specifier_message("typedef", decl_specs),
                self._current(),
            )
        base_is_qualified_typedef = False
        current = self._current()
        if current.kind == TokenKind.IDENT and isinstance(current.lexeme, str):
            base_is_qualified_typedef = self._is_top_level_qualified_typedef(current.lexeme)
        base_has_leading_qualifier = (
            self._current().kind == TokenKind.KEYWORD
            and self._current().lexeme in TYPE_QUALIFIER_KEYWORDS
        )
        base_type = self._parse_type_spec(parse_pointer_depth=not is_typedef)
        if self._check_punct(";"):
            self._reject_invalid_alignment_context(
                decl_specs.alignment,
                decl_specs.alignment_token,
                context="tag-only declaration",
                allow=False,
            )
            if is_typedef or not self._is_tag_or_definition_decl(base_type):
                raise self._expected_identifier_error()
            self._expect_punct(";")
            self._define_enum_member_names(base_type)
            return DeclStmt(
                base_type,
                None,
                None,
                decl_specs.alignment,
                storage_class=decl_specs.storage_class,
                is_thread_local=decl_specs.is_thread_local,
            )
        declarations: list[DeclStmt | TypedefDecl] = []
        while True:
            declarator_has_prefix_qualifier = False
            top_pointer_is_qualified = False
            if is_typedef:
                (
                    name,
                    declarator_ops,
                    declarator_has_prefix_qualifier,
                    top_pointer_is_qualified,
                ) = self._parse_atomic_type_name_declarator(
                    allow_abstract=False,
                    allow_gnu_attributes=base_type.is_atomic,
                )
            else:
                self._skip_gnu_attributes()
                name, declarator_ops = self._parse_declarator(
                    allow_abstract=False,
                    allow_vla=True,
                )
            if name is None:
                raise self._expected_identifier_error()
            decl_type = self._build_declarator_type(base_type, declarator_ops)
            if is_typedef:
                if self._check_punct("="):
                    raise ParserError("Typedef cannot have initializer", self._current())
                is_top_level_qualified = self._is_top_level_qualified_type_name(
                    base_has_leading_qualifier=base_has_leading_qualifier,
                    base_is_qualified_typedef=base_is_qualified_typedef,
                    declarator_has_prefix_qualifier=declarator_has_prefix_qualifier,
                    declarator_ops=declarator_ops,
                    top_pointer_is_qualified=top_pointer_is_qualified,
                )
                self._define_typedef(name, decl_type, is_top_level_qualified=is_top_level_qualified)
                declarations.append(TypedefDecl(decl_type, name))
            else:
                if self._is_invalid_void_object_type(decl_type):
                    raise ParserError("Invalid object type", self._current())
                self._define_ordinary_type(name, decl_type)
                init: Expr | InitList | None = None
                if self._check_punct("="):
                    self._advance()
                    init = self._parse_initializer()
                declarations.append(
                    DeclStmt(
                        decl_type,
                        name,
                        init,
                        decl_specs.alignment,
                        storage_class=decl_specs.storage_class,
                        is_thread_local=decl_specs.is_thread_local,
                    )
                )
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

    def _is_function_object_type(self, type_spec: TypeSpec) -> bool:
        return bool(type_spec.declarator_ops) and type_spec.declarator_ops[0][0] == "fn"

    def _define_enum_member_names(self, type_spec: TypeSpec) -> None:
        for member_name, _ in type_spec.enum_members:
            self._define_ordinary_name(member_name)

    def _parse_static_assert_decl(self) -> StaticAssertDecl:
        if not self._check_keyword("_Static_assert"):
            raise ParserError("Expected _Static_assert", self._current())
        self._advance()
        self._expect_punct("(")
        condition = self._parse_conditional()
        self._expect_punct(",")
        if self._current().kind != TokenKind.STRING_LITERAL:
            raise ParserError("Expected static assertion message", self._current())
        message = self._parse_string_literal()
        self._expect_punct(")")
        self._expect_punct(";")
        return StaticAssertDecl(condition, message)

    def _parse_return_stmt(self) -> ReturnStmt:
        self._advance()
        if self._check_punct(";"):
            self._expect_punct(";")
            return ReturnStmt(None)
        value = self._parse_expression()
        self._expect_punct(";")
        return ReturnStmt(value)

    def _parse_initializer(self) -> Expr | InitList:
        if self._check_punct("{"):
            return self._parse_initializer_list()
        return self._parse_assignment()

    def _parse_initializer_list(self) -> InitList:
        self._expect_punct("{")
        if self._check_punct("}"):
            raise ParserError("Expected initializer", self._current())
        items: list[InitItem] = []
        while True:
            designators = self._parse_designator_list()
            if designators:
                self._expect_punct("=")
            initializer = self._parse_initializer()
            items.append(InitItem(designators, initializer))
            if not self._check_punct(","):
                break
            self._advance()
            if self._check_punct("}"):
                break
        self._expect_punct("}")
        return InitList(tuple(items))

    def _parse_designator_list(self) -> tuple[tuple[str, Expr | str], ...]:
        designators: list[tuple[str, Expr | str]] = []
        while True:
            if self._check_punct("."):
                self._advance()
                token = self._expect(TokenKind.IDENT)
                assert isinstance(token.lexeme, str)
                designators.append(("member", token.lexeme))
                continue
            if self._check_punct("["):
                self._advance()
                index_expr = self._parse_conditional()
                self._expect_punct("]")
                designators.append(("index", index_expr))
                continue
            break
        return tuple(designators)

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
        if self._check_keyword(_EXTENSION_MARKER):
            self._advance()
            return self._parse_unary()
        if self._check_keyword("sizeof"):
            return self._parse_sizeof_expr()
        if self._check_keyword("_Alignof"):
            return self._parse_alignof_expr()
        if self._is_parenthesized_type_name_start() and not self._looks_like_compound_literal():
            return self._parse_cast_expr()
        if self._check_punct("++") or self._check_punct("--"):
            op = str(self._advance().lexeme)
            operand = self._parse_unary()
            return UpdateExpr(op, operand, False)
        if self._check_punct("&&"):
            if self._std == "c11":
                raise ParserError("Label address is a GNU extension", self._current())
            self._advance()
            label = self._expect(TokenKind.IDENT)
            assert isinstance(label.lexeme, str)
            return LabelAddressExpr(label.lexeme)
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

    def _parse_alignof_expr(self) -> AlignofExpr:
        token = self._advance()
        if self._is_parenthesized_type_name_start():
            type_spec = self._parse_parenthesized_type_name()
            return AlignofExpr(None, type_spec)
        if self._std == "c11":
            raise ParserError("Invalid alignof operand", token)
        operand = self._parse_unary()
        return AlignofExpr(operand, None)

    def _parse_cast_expr(self) -> CastExpr:
        type_spec = self._parse_parenthesized_type_name()
        operand = self._parse_unary()
        return CastExpr(type_spec, operand)

    def _parse_parenthesized_type_name(self) -> TypeSpec:
        self._expect_punct("(")
        base_type = self._parse_type_spec(context="type-name")
        name, declarator_ops = self._parse_declarator(allow_abstract=True, allow_vla=True)
        if name is not None:
            raise ParserError(
                f"Type name cannot declare identifier '{name}'",
                self._current(),
            )
        self._expect_punct(")")
        return self._build_declarator_type(base_type, declarator_ops)

    def _parse_parenthesized_atomic_type_name(self) -> tuple[TypeSpec, bool]:
        self._expect_punct("(")
        base_is_qualified_typedef = False
        current = self._current()
        if current.kind == TokenKind.IDENT and isinstance(current.lexeme, str):
            base_is_qualified_typedef = self._is_top_level_qualified_typedef(current.lexeme)
        base_has_leading_qualifier = (
            self._current().kind == TokenKind.KEYWORD
            and self._current().lexeme in TYPE_QUALIFIER_KEYWORDS
        )
        base_type = self._parse_type_spec(parse_pointer_depth=False, context="type-name")
        name, declarator_ops, declarator_has_prefix_qualifier, top_pointer_is_qualified = (
            self._parse_atomic_type_name_declarator(allow_gnu_attributes=True)
        )
        if name is not None:
            raise ParserError(
                f"Type name cannot declare identifier '{name}'",
                self._current(),
            )
        self._expect_punct(")")
        type_spec = self._build_declarator_type(base_type, declarator_ops)
        is_qualified = self._is_top_level_qualified_type_name(
            base_has_leading_qualifier=base_has_leading_qualifier,
            base_is_qualified_typedef=base_is_qualified_typedef,
            declarator_has_prefix_qualifier=declarator_has_prefix_qualifier,
            declarator_ops=declarator_ops,
            top_pointer_is_qualified=top_pointer_is_qualified,
        )
        return type_spec, is_qualified

    def _parse_atomic_type_name_declarator(
        self,
        *,
        allow_abstract: bool = True,
        allow_gnu_attributes: bool = False,
    ) -> tuple[str | None, tuple[DeclaratorOp, ...], bool, bool]:
        declarator_has_prefix_qualifier = self._skip_type_qualifiers(allow_atomic=True)
        if allow_gnu_attributes:
            self._skip_gnu_attributes()
        pointer_qualifiers: list[bool] = []
        while self._check_punct("*"):
            self._advance()
            pointer_qualifiers.append(self._skip_type_qualifiers(allow_atomic=True))
            if allow_gnu_attributes:
                self._skip_gnu_attributes()
        (
            name,
            direct_ops,
            direct_top_pointer_is_qualified,
        ) = self._parse_atomic_type_name_direct_declarator(
            allow_abstract=allow_abstract,
            allow_gnu_attributes=allow_gnu_attributes,
        )
        declarator_ops = direct_ops + (POINTER_OP,) * len(pointer_qualifiers)
        top_pointer_is_qualified = direct_top_pointer_is_qualified
        if not direct_ops and pointer_qualifiers:
            top_pointer_is_qualified = pointer_qualifiers[-1]
        return (
            name,
            declarator_ops,
            declarator_has_prefix_qualifier,
            top_pointer_is_qualified,
        )

    def _parse_atomic_type_name_direct_declarator(
        self,
        *,
        allow_abstract: bool = True,
        allow_gnu_attributes: bool = False,
    ) -> tuple[str | None, tuple[DeclaratorOp, ...], bool]:
        name: str | None
        declarator_ops: tuple[DeclaratorOp, ...]
        top_pointer_is_qualified = False
        if allow_gnu_attributes:
            self._skip_gnu_attributes()
        if self._current().kind == TokenKind.IDENT:
            token = self._advance()
            assert isinstance(token.lexeme, str)
            name = token.lexeme
            declarator_ops = ()
        elif self._check_punct("("):
            self._advance()
            (
                name,
                declarator_ops,
                _,
                top_pointer_is_qualified,
            ) = self._parse_atomic_type_name_declarator(
                allow_abstract=True,
                allow_gnu_attributes=allow_gnu_attributes,
            )
            self._expect_punct(")")
        elif allow_abstract:
            name = None
            declarator_ops = ()
        else:
            raise self._expected_identifier_error()
        while True:
            if allow_gnu_attributes and self._skip_gnu_attributes():
                continue
            if self._check_punct("["):
                self._advance()
                size_token = self._current()
                size_expr = self._parse_assignment()
                size = self._parse_array_size_expr(size_expr, size_token)
                self._expect_punct("]")
                declarator_ops = declarator_ops + (("arr", size),)
                continue
            if self._check_punct("("):
                self._advance()
                function_declarator = self._parse_function_suffix_params()
                self._expect_punct(")")
                declarator_ops = declarator_ops + (("fn", function_declarator),)
                continue
            break
        if not declarator_ops or declarator_ops[0][0] != "ptr":
            top_pointer_is_qualified = False
        return name, declarator_ops, top_pointer_is_qualified

    def _is_top_level_qualified_type_name(
        self,
        *,
        base_has_leading_qualifier: bool,
        base_is_qualified_typedef: bool,
        declarator_has_prefix_qualifier: bool,
        declarator_ops: tuple[DeclaratorOp, ...],
        top_pointer_is_qualified: bool,
    ) -> bool:
        if declarator_ops:
            if declarator_ops[0][0] == "ptr":
                return top_pointer_is_qualified
            return False
        return (
            base_has_leading_qualifier
            or base_is_qualified_typedef
            or declarator_has_prefix_qualifier
        )

    def _is_parenthesized_type_name_start(self) -> bool:
        if not self._check_punct("("):
            return False
        index = self._index + 1
        token = self._tokens[min(index, len(self._tokens) - 1)]
        while token.kind == TokenKind.KEYWORD and token.lexeme in TYPE_QUALIFIER_KEYWORDS:
            index += 1
            token = self._tokens[min(index, len(self._tokens) - 1)]
        if token.kind == TokenKind.KEYWORD:
            return str(token.lexeme) in PAREN_TYPE_NAME_KEYWORDS
        if token.kind == TokenKind.IDENT and isinstance(token.lexeme, str):
            return self._is_typedef_name(token.lexeme)
        return False

    def _parse_postfix(self) -> Expr:
        if self._is_parenthesized_type_name_start() and self._looks_like_compound_literal():
            expr = self._parse_compound_literal_expr()
        else:
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

    def _looks_like_compound_literal(self) -> bool:
        if not self._is_parenthesized_type_name_start():
            return False
        saved_index = self._index
        try:
            self._parse_parenthesized_type_name()
            return self._check_punct("{")
        except ParserError:
            return False
        finally:
            self._index = saved_index

    def _parse_compound_literal_expr(self) -> CompoundLiteralExpr:
        type_spec = self._parse_parenthesized_type_name()
        if not self._check_punct("{"):
            raise ParserError("Expected '{'", self._current())
        initializer = self._parse_initializer_list()
        return CompoundLiteralExpr(type_spec, initializer)

    def _build_declarator_type(
        self,
        base_type: TypeSpec,
        declarator_ops: tuple[DeclaratorOp, ...],
    ) -> TypeSpec:
        combined_ops = declarator_ops + base_type.declarator_ops
        return TypeSpec(
            base_type.name,
            declarator_ops=combined_ops,
            qualifiers=base_type.qualifiers,
            is_atomic=base_type.is_atomic,
            atomic_target=base_type.atomic_target,
            enum_tag=base_type.enum_tag,
            enum_members=base_type.enum_members,
            record_tag=base_type.record_tag,
            record_members=base_type.record_members,
        )

    def _mark_atomic_type_spec(self, type_spec: TypeSpec) -> TypeSpec:
        if type_spec.is_atomic:
            return type_spec
        return TypeSpec(
            type_spec.name,
            declarator_ops=type_spec.declarator_ops,
            qualifiers=type_spec.qualifiers,
            is_atomic=True,
            atomic_target=type_spec,
            enum_tag=type_spec.enum_tag,
            enum_members=type_spec.enum_members,
            record_tag=type_spec.record_tag,
            record_members=type_spec.record_members,
        )

    def _format_invalid_atomic_type_message(
        self,
        reason: str,
    ) -> str:
        return f"Invalid atomic type: {reason}"

    def _classify_invalid_atomic_type(
        self,
        type_spec: TypeSpec,
        *,
        is_qualified_atomic_target: bool = False,
        include_atomic: bool = True,
    ) -> str | None:
        if is_qualified_atomic_target:
            return "qualified"
        if include_atomic and type_spec.is_atomic:
            return "atomic"
        if bool(type_spec.declarator_ops) and type_spec.declarator_ops[0][0] == "arr":
            return "array"
        if bool(type_spec.declarator_ops) and type_spec.declarator_ops[0][0] == "fn":
            return "function"
        return None

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
        *,
        allow_vla: bool = False,
        allow_parameter_arrays: bool = False,
    ) -> tuple[str | None, tuple[DeclaratorOp, ...]]:
        self._skip_type_qualifiers()
        pointer_count = 0
        while self._check_punct("*"):
            self._advance()
            self._skip_type_qualifiers()
            pointer_count += 1
        name, ops = self._parse_direct_declarator(
            allow_abstract,
            allow_vla=allow_vla,
            allow_parameter_arrays=allow_parameter_arrays,
        )
        if pointer_count:
            ops = ops + (POINTER_OP,) * pointer_count
        return name, ops

    def _parse_direct_declarator(
        self,
        allow_abstract: bool,
        *,
        allow_vla: bool = False,
        allow_parameter_arrays: bool = False,
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
            name, ops = self._parse_declarator(
                allow_abstract=True,
                allow_vla=allow_vla,
                allow_parameter_arrays=allow_parameter_arrays,
            )
            self._expect_punct(")")
        elif allow_abstract:
            name = None
            ops = ()
        else:
            raise self._expected_identifier_error()
        while True:
            if self._check_punct("["):
                self._advance()
                array_decl = self._parse_array_declarator(
                    allow_vla=allow_vla,
                    allow_parameter_arrays=allow_parameter_arrays,
                )
                ops = ops + (("arr", array_decl),)
                continue
            if self._check_punct("("):
                self._advance()
                function_declarator = self._parse_function_suffix_params()
                self._expect_punct(")")
                ops = ops + (("fn", function_declarator),)
                continue
            break
        return name, ops

    def _parse_array_declarator(
        self,
        *,
        allow_vla: bool,
        allow_parameter_arrays: bool,
    ) -> int | ArrayDecl:
        qualifiers: list[str] = []
        seen_qualifiers: set[str] = set()
        has_static_bound = False
        while allow_parameter_arrays and self._current().kind == TokenKind.KEYWORD:
            lexeme = str(self._current().lexeme)
            if lexeme in TYPE_QUALIFIER_KEYWORDS:
                if lexeme in seen_qualifiers:
                    raise ParserError(f"Duplicate type qualifier: '{lexeme}'", self._current())
                qualifiers.append(lexeme)
                seen_qualifiers.add(lexeme)
                self._advance()
                continue
            if lexeme == "static":
                if has_static_bound:
                    raise ParserError("Duplicate array bound specifier: 'static'", self._current())
                has_static_bound = True
                self._advance()
                continue
            break
        size_expr: Expr | None = None
        size_token = self._current()
        if not self._check_punct("]"):
            size_expr = self._parse_assignment()
        self._expect_punct("]")
        if size_expr is None:
            if has_static_bound:
                raise ParserError("Array parameter with 'static' requires a size", size_token)
            if allow_parameter_arrays:
                return ArrayDecl(None, tuple(qualifiers), False)
            if allow_vla:
                return ArrayDecl(None)
            raise ParserError("Array size is required in this context", size_token)
        if isinstance(size_expr, IntLiteral):
            if not isinstance(size_expr.value, str):
                raise ParserError("Array size literal token is malformed", size_token)
            message = _array_size_literal_error(size_expr.value)
            if message is not None:
                raise ParserError(message, size_token)
        size = self._eval_array_size_expr(size_expr)
        if size is not None and size <= 0:
            raise ParserError("Array size must be positive", size_token)
        if allow_parameter_arrays and (qualifiers or has_static_bound):
            return ArrayDecl(size_expr, tuple(qualifiers), has_static_bound)
        if size is not None:
            return size
        if allow_vla:
            return ArrayDecl(size_expr, tuple(qualifiers), has_static_bound)
        raise ParserError(
            _array_size_non_ice_error(size_expr, self._eval_array_size_expr),
            size_token,
        )

    def _parse_array_size(self, token: Token) -> int:
        lexeme = token.lexeme
        if not isinstance(lexeme, str):
            raise ParserError("Array size literal token is malformed", token)
        message = _array_size_literal_error(lexeme)
        if message is not None:
            raise ParserError(message, token)
        size = _parse_int_literal_value(lexeme)
        assert size is not None
        if size <= 0:
            raise ParserError("Array size must be positive", token)
        return size

    def _parse_array_size_expr(self, expr: Expr, token: Token) -> int:
        size = self._eval_array_size_expr(expr)
        if size is None:
            raise ParserError(_array_size_non_ice_error(expr, self._eval_array_size_expr), token)
        if size <= 0:
            raise ParserError("Array size must be positive", token)
        return size

    def _parse_array_size_expr_or_vla(self, expr: Expr, token: Token) -> int:
        size = self._eval_array_size_expr(expr)
        if size is None:
            return -1
        if size <= 0:
            raise ParserError("Array size must be positive", token)
        return size

    def _eval_array_size_expr(self, expr: Expr) -> int | None:
        if isinstance(expr, IntLiteral):
            assert isinstance(expr.value, str)
            return _parse_int_literal_value(expr.value)
        if isinstance(expr, GenericExpr):
            return self._eval_array_size_generic_expr(expr)
        if isinstance(expr, CastExpr):
            return self._eval_array_size_expr(expr.expr)
        if isinstance(expr, SizeofExpr):
            if expr.type_spec is not None:
                return self._sizeof_type_spec(expr.type_spec)
            return None
        if isinstance(expr, AlignofExpr):
            if expr.type_spec is not None:
                return self._alignof_type_spec(expr.type_spec)
            return None
        if isinstance(expr, UnaryExpr) and expr.op in {"+", "-"}:
            operand = self._eval_array_size_expr(expr.operand)
            if operand is None:
                return None
            return operand if expr.op == "+" else -operand
        if isinstance(expr, BinaryExpr):
            left = self._eval_array_size_expr(expr.left)
            right = self._eval_array_size_expr(expr.right)
            if left is None or right is None:
                return None
            if expr.op == "+":
                return left + right
            if expr.op == "-":
                return left - right
            if expr.op == "<<":
                return None if right < 0 else left << right
            if expr.op == "==":
                return int(left == right)
            if expr.op == "!=":
                return int(left != right)
        if isinstance(expr, ConditionalExpr):
            condition = self._eval_array_size_expr(expr.condition)
            if condition is None:
                return None
            branch = expr.then_expr if condition != 0 else expr.else_expr
            return self._eval_array_size_expr(branch)
        return None

    def _eval_array_size_generic_expr(self, expr: GenericExpr) -> int | None:
        control_type = self._array_size_generic_control_type(expr.control)
        default_expr: Expr | None = None
        selected_expr: Expr | None = None
        for assoc_type, assoc_expr in expr.associations:
            if assoc_type is None:
                default_expr = assoc_expr
                continue
            if control_type is not None and self._is_generic_control_type_compatible(
                control_type,
                assoc_type,
            ):
                selected_expr = assoc_expr
                break
        if selected_expr is None:
            selected_expr = default_expr
        if selected_expr is None:
            return None
        return self._eval_array_size_expr(selected_expr)

    def _array_size_generic_control_type(self, control: Expr) -> TypeSpec | None:
        if isinstance(control, IntLiteral):
            return self._int_literal_type_spec(control.value)
        if isinstance(control, StringLiteral):
            return TypeSpec("char", declarator_ops=(POINTER_OP,))
        if isinstance(control, Identifier):
            type_spec = self._lookup_ordinary_type(control.name)
            if type_spec is None:
                return None
            return self._decay_type_spec(type_spec)
        return None

    def _int_literal_type_spec(self, literal: str) -> TypeSpec:
        lowered = literal.lower()
        if lowered.endswith("ull") or lowered.endswith("llu"):
            return TypeSpec("unsigned long long")
        if lowered.endswith("ll"):
            return TypeSpec("long long")
        if lowered.endswith("ul") or lowered.endswith("lu") or lowered.endswith("u"):
            return TypeSpec("unsigned int")
        if lowered.endswith("l"):
            return TypeSpec("long")
        return TypeSpec("int")

    def _decay_type_spec(self, type_spec: TypeSpec) -> TypeSpec:
        if not type_spec.declarator_ops:
            return type_spec
        kind, _ = type_spec.declarator_ops[0]
        if kind == "arr":
            return TypeSpec(
                type_spec.name,
                declarator_ops=(POINTER_OP, *type_spec.declarator_ops[1:]),
            )
        if kind == "fn":
            return TypeSpec(type_spec.name, declarator_ops=(POINTER_OP, *type_spec.declarator_ops))
        return type_spec

    def _is_generic_control_type_compatible(
        self,
        control_type: TypeSpec,
        assoc_type: TypeSpec,
    ) -> bool:
        return self._unqualified_type_spec(
            self._decay_type_spec(control_type)
        ) == self._unqualified_type_spec(self._decay_type_spec(assoc_type))

    def _unqualified_type_spec(self, type_spec: TypeSpec) -> TypeSpec:
        if not type_spec.qualifiers:
            return type_spec
        return TypeSpec(
            type_spec.name,
            declarator_ops=type_spec.declarator_ops,
            is_atomic=type_spec.is_atomic,
            atomic_target=type_spec.atomic_target,
            enum_tag=type_spec.enum_tag,
            enum_members=type_spec.enum_members,
            record_tag=type_spec.record_tag,
            record_members=type_spec.record_members,
        )

    def _sizeof_type_spec(self, type_spec: TypeSpec) -> int | None:
        def eval_ops(index: int) -> int | None:
            if index >= len(type_spec.declarator_ops):
                return _BASE_TYPE_SIZES.get(type_spec.name)
            kind, value = type_spec.declarator_ops[index]
            if kind == "arr":
                if not isinstance(value, int):
                    if not isinstance(value, ArrayDecl):
                        return None
                    if value.length is None:
                        return None
                    if isinstance(value.length, int):
                        value = value.length
                    else:
                        evaluated = self._eval_array_size_expr(value.length)
                        if evaluated is None:
                            return None
                        value = evaluated
                if value <= 0:
                    return None
                item_size = eval_ops(index + 1)
                return None if item_size is None else item_size * value
            if kind == "ptr":
                return _POINTER_SIZE
            return None

        return eval_ops(0)

    def _alignof_type_spec(self, type_spec: TypeSpec) -> int | None:
        if not type_spec.declarator_ops:
            return _BASE_TYPE_SIZES.get(type_spec.name)
        kind, _ = type_spec.declarator_ops[0]
        if kind == "ptr":
            return _POINTER_SIZE
        if kind == "arr":
            return self._alignof_type_spec(
                TypeSpec(
                    type_spec.name,
                    declarator_ops=type_spec.declarator_ops[1:],
                    is_atomic=type_spec.is_atomic,
                    atomic_target=type_spec.atomic_target,
                    enum_tag=type_spec.enum_tag,
                    enum_members=type_spec.enum_members,
                    record_tag=type_spec.record_tag,
                    record_members=type_spec.record_members,
                )
            )
        return None

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
            comma = self._advance()
            if self._check_punct(")"):
                raise ParserError("Expected parameter after ','", comma)
            if self._check_punct("..."):
                self._advance()
                is_variadic = True
                if not self._check_punct(")"):
                    raise ParserError("Expected ')' after ... in parameter list", self._current())
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
        if token.kind == TokenKind.FLOAT_CONST:
            self._advance()
            assert isinstance(token.lexeme, str)
            return FloatLiteral(token.lexeme)
        if token.kind == TokenKind.INT_CONST:
            self._advance()
            assert isinstance(token.lexeme, str)
            return IntLiteral(token.lexeme)
        if token.kind == TokenKind.CHAR_CONST:
            self._advance()
            assert isinstance(token.lexeme, str)
            return CharLiteral(token.lexeme)
        if self._check_keyword("_Generic"):
            return self._parse_generic_expr()
        if token.kind == TokenKind.STRING_LITERAL:
            return self._parse_string_literal()
        if token.kind == TokenKind.IDENT:
            self._advance()
            assert isinstance(token.lexeme, str)
            return Identifier(token.lexeme)
        if self._check_punct("("):
            if self._peek_punct("{"):
                if self._std == "c11":
                    raise ParserError("Statement expression is a GNU extension", self._current())
                return self._parse_statement_expr()
            self._advance()
            expr = self._parse_expression()
            self._expect_punct(")")
            return expr
        invalid_expression_starts = {
            "...",
            ")",
            "]",
            "}",
            ",",
            ":",
            "?",
            ";",
            "{",
            "##",
            "%:",
            "%:%:",
            "<:",
            ":>",
            "<%",
            "%>",
        }
        if token.kind == TokenKind.PUNCTUATOR and token.lexeme in invalid_expression_starts:
            raise ParserError(
                f"Expression cannot start with '{token.lexeme}': expected an operand",
                token,
            )
        if token.kind == TokenKind.KEYWORD:
            raise ParserError(
                f"Expression cannot start with keyword '{token.lexeme}': expected an operand",
                token,
            )
        if token.kind == TokenKind.EOF:
            raise ParserError("Expression is missing before end of input", token)
        if token.kind == TokenKind.PP_NUMBER:
            raise ParserError(
                f"Expression cannot start with preprocessing number: '{token.lexeme}'",
                token,
            )
        if token.kind == TokenKind.HEADER_NAME:
            raise ParserError(
                f"Expression cannot start with header name: '{token.lexeme}'",
                token,
            )
        kind_name = token.kind.name if isinstance(token.kind, Enum) else repr(token.kind)
        lexeme_hint = f" (lexeme {token.lexeme!r})" if token.lexeme is not None else ""
        raise ParserError(
            f"Expression cannot start with unsupported token kind '{kind_name}'{lexeme_hint}",
            token,
        )

    def _parse_type_name(self) -> TypeSpec:
        base_type = self._parse_type_spec(context="type-name")
        name, declarator_ops = self._parse_declarator(allow_abstract=True, allow_vla=True)
        if name is not None:
            raise ParserError(
                f"Type name cannot declare identifier '{name}'",
                self._current(),
            )
        return self._build_declarator_type(base_type, declarator_ops)

    def _parse_generic_expr(self) -> GenericExpr:
        self._advance()
        self._expect_punct("(")
        control = self._parse_assignment()
        self._expect_punct(",")
        associations: list[tuple[TypeSpec | None, Expr]] = []
        first_default_index: int | None = None
        first_default_token: Token | None = None
        association_index = 0
        parsed_type_positions: dict[TypeSpec, tuple[int, Token]] = {}
        while True:
            association_index += 1
            assoc_type: TypeSpec | None
            if self._check_keyword("default"):
                if first_default_index is not None:
                    assert first_default_token is not None
                    raise ParserError(
                        "Duplicate default generic association at position "
                        f"{association_index}: previous default was at position "
                        f"{first_default_index} (line {first_default_token.line}, "
                        f"column {first_default_token.column}); only one default "
                        "association is allowed",
                        self._current(),
                    )
                first_default_index = association_index
                first_default_token = self._current()
                self._advance()
                assoc_type = None
            else:
                association_type_token = self._current()
                assoc_type = self._parse_type_name()
                if assoc_type in parsed_type_positions:
                    previous_index, previous_token = parsed_type_positions[assoc_type]
                    raise ParserError(
                        "Duplicate generic type association at position "
                        f"{association_index}: previous identical type association "
                        f"was at position {previous_index} (line {previous_token.line}, "
                        f"column {previous_token.column})",
                        association_type_token,
                    )
                parsed_type_positions[assoc_type] = (association_index, association_type_token)
            self._expect_punct(":")
            associations.append((assoc_type, self._parse_assignment()))
            if not self._check_punct(","):
                break
            self._advance()
        self._expect_punct(")")
        return GenericExpr(control, tuple(associations))

    def _parse_statement_expr(self) -> StatementExpr:
        self._expect_punct("(")
        body = self._parse_compound_stmt()
        self._expect_punct(")")
        return StatementExpr(body)

    def _parse_string_literal(self) -> StringLiteral:
        token = self._expect(TokenKind.STRING_LITERAL)
        assert isinstance(token.lexeme, str)
        prefix, body = self._split_string_literal(token.lexeme, token)
        while self._current().kind == TokenKind.STRING_LITERAL:
            token = self._advance()
            assert isinstance(token.lexeme, str)
            next_prefix, next_body = self._split_string_literal(token.lexeme, token)
            prefix = self._merge_string_prefix(prefix, next_prefix, token)
            body += next_body
        return StringLiteral(f'{prefix}"{body}"')

    def _split_string_literal(self, lexeme: str, token: Token) -> tuple[str, str]:
        if lexeme.startswith('"') and lexeme.endswith('"'):
            return "", lexeme[1:-1]
        if lexeme.startswith('u8"') and lexeme.endswith('"'):
            return "u8", lexeme[3:-1]
        if (
            len(lexeme) >= 3
            and lexeme[0] in {"u", "U", "L"}
            and lexeme[1] == '"'
            and lexeme.endswith('"')
        ):
            return lexeme[0], lexeme[2:-1]
        raise ParserError("Invalid string literal", token)

    def _merge_string_prefix(self, prefix: str, next_prefix: str, token: Token) -> str:
        if prefix == next_prefix or not next_prefix:
            return prefix
        if not prefix:
            return next_prefix
        raise ParserError("Incompatible string literal prefixes", token)

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

    def _skip_extension_markers(self) -> None:
        while self._check_keyword(_EXTENSION_MARKER):
            self._advance()

    def _invalid_decl_specifier_message(self, context: str, decl_specs: DeclSpecInfo) -> str:
        if decl_specs.is_thread_local:
            return f"Invalid declaration specifier for {context}: '_Thread_local'"
        if decl_specs.is_inline:
            return f"Invalid declaration specifier for {context}: 'inline'"
        if decl_specs.is_noreturn:
            return f"Invalid declaration specifier for {context}: '_Noreturn'"
        return f"Invalid declaration specifier for {context}"

    def _invalid_alignment_specifier_message(self, context: str) -> str:
        return f"Invalid alignment specifier for {context}"

    def _consume_overloadable_gnu_attributes(self) -> bool:
        _, has_overloadable = self._consume_gnu_attributes()
        return has_overloadable

    def _skip_gnu_attributes(self) -> bool:
        found, _ = self._consume_gnu_attributes()
        return found

    def _consume_gnu_attributes(self) -> tuple[bool, bool]:
        found = False
        has_overloadable = False
        while self._is_gnu_attribute_start():
            start = self._advance()
            self._expect_punct("(")
            self._expect_punct("(")
            depth = 2
            while depth > 0:
                token = self._current()
                if token.kind == TokenKind.EOF:
                    raise ParserError("Expected ')'", start)
                if token.kind == TokenKind.IDENT and token.lexeme == "overloadable":
                    has_overloadable = True
                if token.kind == TokenKind.PUNCTUATOR:
                    if token.lexeme == "(":
                        depth += 1
                    elif token.lexeme == ")":
                        depth -= 1
                self._advance()
            found = True
        return found, has_overloadable

    def _is_gnu_attribute_start(self) -> bool:
        token = self._current()
        if token.kind != TokenKind.IDENT or token.lexeme != "__attribute__":
            return False
        first = self._peek(1)
        second = self._peek(2)
        return (
            first.kind == TokenKind.PUNCTUATOR
            and first.lexeme == "("
            and second.kind == TokenKind.PUNCTUATOR
            and second.lexeme == "("
        )

    def _skip_type_qualifiers(self, *, allow_atomic: bool = False) -> bool:
        qualifiers = TYPE_QUALIFIER_KEYWORDS | ({"_Atomic"} if allow_atomic else set())
        found = False
        while self._current().kind == TokenKind.KEYWORD and self._current().lexeme in qualifiers:
            found = True
            self._advance()
        return found

    def _consume_decl_specifiers(self) -> DeclSpecInfo:
        storage_class: str | None = None
        storage_class_token: Token | None = None
        alignment: int | None = None
        alignment_token: Token | None = None
        is_thread_local = False
        is_inline = False
        is_noreturn = False
        while self._current().kind == TokenKind.KEYWORD:
            lexeme = str(self._current().lexeme)
            if lexeme in STORAGE_CLASS_KEYWORDS:
                if storage_class is not None:
                    raise ParserError(
                        f"Duplicate storage class specifier: '{lexeme}'", self._current()
                    )
                storage_class = cast(StorageClass, lexeme)
                storage_class_token = self._current()
                self._advance()
                continue
            if lexeme == "_Thread_local":
                if is_thread_local:
                    raise ParserError(
                        "Duplicate thread-local specifier: '_Thread_local'", self._current()
                    )
                is_thread_local = True
                self._advance()
                continue
            if lexeme == "inline":
                if is_inline:
                    raise ParserError("Duplicate function specifier: 'inline'", self._current())
                is_inline = True
                self._advance()
                continue
            if lexeme == "_Noreturn":
                if is_noreturn:
                    raise ParserError("Duplicate function specifier: '_Noreturn'", self._current())
                is_noreturn = True
                self._advance()
                continue
            if lexeme == "_Alignas":
                if alignment_token is None:
                    alignment_token = self._current()
                current_alignment = self._consume_alignas_specifier()
                if alignment is None or current_alignment > alignment:
                    alignment = current_alignment
                continue
            break
        return DeclSpecInfo(
            is_typedef=storage_class == "typedef",
            storage_class=storage_class,
            storage_class_token=storage_class_token,
            alignment=alignment,
            alignment_token=alignment_token,
            is_thread_local=is_thread_local,
            is_inline=is_inline,
            is_noreturn=is_noreturn,
        )

    def _reject_invalid_alignment_context(
        self,
        alignment: int | None,
        alignment_token: Token | None,
        *,
        context: str,
        allow: bool,
    ) -> None:
        if alignment is None or allow:
            return
        raise ParserError(
            self._invalid_alignment_specifier_message(context),
            alignment_token or self._current(),
        )

    def _consume_alignas_specifier(self) -> int:
        token = self._current()
        self._advance()
        self._expect_punct("(")
        if self._try_parse_type_name():
            base_type = self._parse_type_spec()
            name, declarator_ops = self._parse_declarator(allow_abstract=True)
            assert name is None
            type_spec = self._build_declarator_type(base_type, declarator_ops)
            self._expect_punct(")")
            alignment = self._alignof_type_spec(type_spec)
            if alignment is None:
                raise ParserError("_Alignas type operand must denote an object type", token)
            return alignment
        expr = self._parse_conditional()
        alignment = self._eval_array_size_expr(expr)
        if alignment is None:
            raise ParserError(
                "_Alignas expression operand must be an integer constant expression", token
            )
        if alignment <= 0:
            raise ParserError("_Alignas expression operand must be positive", token)
        if (alignment & (alignment - 1)) != 0:
            raise ParserError(
                "_Alignas expression operand must evaluate to a power of two", token
            )
        self._expect_punct(")")
        return alignment

    def _try_parse_type_name(self) -> bool:
        saved_index = self._index
        try:
            base_type = self._parse_type_spec()
            name, declarator_ops = self._parse_declarator(allow_abstract=True)
            if name is not None:
                self._index = saved_index
                return False
            self._build_declarator_type(base_type, declarator_ops)
            self._index = saved_index
            return True
        except ParserError:
            self._index = saved_index
            return False

    def _is_assignment_operator(self) -> bool:
        token = self._current()
        return token.kind == TokenKind.PUNCTUATOR and token.lexeme in ASSIGNMENT_OPERATORS

    def _peek_punct(self, value: str) -> bool:
        token = self._peek()
        return token.kind == TokenKind.PUNCTUATOR and token.lexeme == value

    def _peek(self, offset: int = 1) -> Token:
        index = min(self._index + offset, len(self._tokens) - 1)
        return self._tokens[index]

    def _match(self, kind: TokenKind) -> bool:
        return self._current().kind == kind


def parse(tokens: list[Token], *, std: StdMode = "c11") -> TranslationUnit:
    return Parser(tokens, std=std).parse()
