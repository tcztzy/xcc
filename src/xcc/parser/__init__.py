from typing import Literal, cast

from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    BuiltinOffsetofExpr,
    CaseStmt,
    CastExpr,
    CompoundLiteralExpr,
    CompoundStmt,
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
    DesignatorRange,
    DoWhileStmt,
    Expr,
    ForStmt,
    FunctionDef,
    GenericExpr,
    IfStmt,
    InitList,
    LabelStmt,
    Param,
    RecordMemberDecl,
    ReturnStmt,
    SizeofExpr,
    StatementExpr,
    StaticAssertDecl,
    Stmt,
    StringLiteral,
    SwitchStmt,
    TranslationUnit,
    TypedefDecl,
    TypeSpec,
    WhileStmt,
)
from xcc.lexer import Token, TokenKind
from xcc.parser.diagnostics import (
    _array_size_non_ice_error as _array_size_non_ice_error,
)
from xcc.parser.diagnostics import (
    _parse_int_literal_value as _parse_int_literal_value,
)
from xcc.parser.model import DeclSpecInfo, ParserError

from . import array_sizes as _array_sizes
from . import declarators as _declarators
from . import expressions as _expressions
from . import extensions as _extensions
from . import statements as _statements
from . import type_diagnostics as _type_diagnostics
from . import type_specs as _type_specs

FunctionDeclarator = tuple[tuple[TypeSpec, ...] | None, bool]
DeclaratorOp = tuple[str, int | ArrayDecl | FunctionDeclarator]
POINTER_OP: DeclaratorOp = ("ptr", 0)
ASSIGNMENT_OPERATORS = ("=", "+=", "-=", "*=", "/=", "%=", "<<=", ">>=", "&=", "^=", "|=")
INTEGER_TYPE_KEYWORDS = {"int", "char", "short", "long", "signed", "unsigned"}
FLOATING_TYPE_KEYWORDS = {"float", "double"}
SIMPLE_TYPE_SPEC_KEYWORDS = INTEGER_TYPE_KEYWORDS | FLOATING_TYPE_KEYWORDS | {"void"}
TYPEOF_KEYWORDS = {
    "typeof",
    "typeof_unqual",
    "__typeof__",
    "__typeof",
    "__typeof_unqual__",
    "__typeof_unqual",
}
ALIGNOF_KEYWORDS = {"_Alignof", "__alignof__"}
PAREN_TYPE_NAME_KEYWORDS = (
    SIMPLE_TYPE_SPEC_KEYWORDS
    | {
        "_Atomic",
        "_Bool",
        "_Complex",
        "enum",
        "struct",
        "union",
    }
    | TYPEOF_KEYWORDS
)
TYPE_QUALIFIER_KEYWORDS = {"const", "volatile", "restrict"}
_NULLABLE_QUALIFIERS = {"_Nullable", "_Nonnull", "_Null_unspecified"}
_IGNORED_IDENT_TYPE_QUALIFIERS = {"__unaligned"}
_GNU_EXTENSION_TYPES = {
    "_Float16",
    "__bf16",
    "__fp16",
    "_Float32",
    "_Float64",
    "_Float128",
    "_Float32x",
    "_Float64x",
    "__int128_t",
    "__uint128_t",
}
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


_EXTENSION_MARKER = _extensions._EXTENSION_MARKER
_MS_DECLSPEC_KEYWORD = _extensions._MS_DECLSPEC_KEYWORD
StdMode = Literal["c11", "gnu11"]


class Parser:
    def __init__(self, tokens: list[Token], *, std: StdMode = "c11") -> None:
        self._tokens = tokens
        self._index = 0
        self._std = std
        self._typedef_scopes: list[dict[str, TypeSpec]] = [{}]
        self._typedef_qualified_scopes: list[dict[str, bool]] = [{}]
        self._ordinary_name_scopes: list[set[str]] = [set()]
        self._ordinary_type_scopes: list[dict[str, TypeSpec]] = [{}]
        self._capture_next_fn_params: bool = False
        self._function_def_info: tuple[list[Param], bool, bool] | None = None

        # Register compiler built-in typedefs
        self._define_typedef(
            "__builtin_va_list",
            TypeSpec(name="__builtin_va_list"),
        )

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

    def _make_error(self, message: str, token: Token) -> ParserError:
        return ParserError(message, token)

    def _looks_like_function(self) -> bool:
        saved_index = self._index
        try:
            decl_specs = self._consume_decl_specifiers()
            if decl_specs.is_typedef:
                return False
            self._parse_type_spec()
            self._skip_decl_attributes()
            self._skip_calling_convention_identifiers()
            if self._current().kind != TokenKind.IDENT:
                # Complex declarator case (e.g. function returning function pointer)
                name, ops = self._parse_declarator(allow_abstract=False)
                if name is None:
                    return False
                if not ops or ops[0][0] != "fn":
                    return False
                self._skip_decl_extensions()
                return self._check_punct("{") or self._check_punct(";")
            self._advance()
            self._skip_decl_attributes()
            if not self._check_punct("("):
                return False
            self._advance()
            params, has_prototype, _ = self._parse_params()
            self._expect_punct(")")
            self._skip_decl_extensions()
            if self._check_punct("{") or self._check_punct(";"):
                return True
            # K&R: declarations follow ')' before '{'.
            if not has_prototype and params:
                # Skip K&R declarations until we find '{'.
                while not self._check_punct("{") and self._current().kind != TokenKind.EOF:
                    self._advance()
                return self._check_punct("{")
            return False
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
        base_type = self._parse_type_spec()
        is_overloadable = self._consume_overloadable_decl_attributes()

        # Detect simple vs complex declarator.
        # Simple: bare IDENT (possibly followed by GNU attributes) then '('.
        # Complex: starts with '*' or '(' (e.g. function returning function pointer).
        self._skip_decl_attributes()
        self._skip_calling_convention_identifiers()
        if self._current().kind == TokenKind.IDENT:
            # Simple case: NAME ( params )
            name_token = self._expect(TokenKind.IDENT)
            function_name = str(name_token.lexeme)
            if self._consume_overloadable_decl_attributes():
                is_overloadable = True
            self._expect_punct("(")
            params, has_prototype, is_variadic = self._parse_params()
            self._expect_punct(")")
            self._skip_decl_extensions()
            # Parse K&R-style parameter declarations between ')' and '{'.
            is_knr = not has_prototype and params
            if is_knr and not self._check_punct("{") and not self._check_punct(";"):
                params = self._parse_knr_declarations(params)
            param_types = tuple(param.type_spec for param in params) if has_prototype else None
            function_type = self._build_declarator_type(
                base_type,
                (
                    (
                        "fn",
                        (param_types, is_variadic),
                    ),
                ),
            )
            return_type = base_type
        else:
            # Complex declarator (e.g. function returning function pointer).
            self._capture_next_fn_params = True
            self._function_def_info = None
            decl_name, declarator_ops = self._parse_declarator(allow_abstract=False)
            assert decl_name is not None
            function_name = str(decl_name)
            assert self._function_def_info is not None
            params, has_prototype, is_variadic = self._function_def_info
            self._skip_decl_extensions()
            function_type = self._build_declarator_type(base_type, declarator_ops)
            # Build the return type from base + all ops except the first (fn) op.
            return_type = self._build_declarator_type(base_type, declarator_ops[1:])

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

    def _is_knr_identifier_list(self) -> bool:
        """Check if the current position starts a K&R identifier list (bare names)."""
        token = self._current()
        if token.kind != TokenKind.IDENT:
            return False
        name = str(token.lexeme)
        # If it's a known typedef, it's a typed parameter, not K&R.
        if self._lookup_typedef(name) is not None:
            return False
        # K&R identifier must be followed by ',' or ')'.
        next_tok = self._peek()
        return next_tok.kind == TokenKind.PUNCTUATOR and next_tok.lexeme in (",", ")")

    def _parse_knr_identifier_list(self) -> list[Param]:
        """Parse K&R identifier list: (a, b, c)."""
        int_type = TypeSpec("int", 0)
        names: list[str] = []
        names.append(str(self._expect(TokenKind.IDENT).lexeme))
        while self._check_punct(","):
            self._advance()
            names.append(str(self._expect(TokenKind.IDENT).lexeme))
        return [Param(int_type, name) for name in names]

    def _parse_knr_declarations(self, params: list[Param]) -> list[Param]:
        """Parse K&R parameter type declarations and update param types."""
        param_types: dict[str, TypeSpec] = {}
        # Parse declarations until we hit '{'.
        while not self._check_punct("{"):
            self._consume_decl_specifiers()
            base_type = self._parse_type_spec()
            # Parse comma-separated declarators.
            while True:
                name, declarator_ops = self._parse_declarator(allow_abstract=False)
                assert name is not None  # allow_abstract=False guarantees a name
                decl_type = self._build_declarator_type(base_type, declarator_ops)
                param_types[name] = decl_type
                if self._check_punct(","):
                    self._advance()
                else:
                    break
            self._expect_punct(";")
        int_type = TypeSpec("int", 0)
        return [Param(param_types.get(str(p.name), int_type), p.name) for p in params]

    def _parse_params(self) -> tuple[list[Param], bool, bool]:
        if self._check_punct(")"):
            return [], False, False
        if self._check_keyword("void") and self._peek_punct(")"):
            self._advance()
            return [], True, False
        if self._check_punct("..."):
            raise ParserError("Expected parameter before ...", self._current())
        # Detect K&R-style identifier list.
        if self._is_knr_identifier_list():
            params = self._parse_knr_identifier_list()
            return params, False, False
        params = [self._parse_param()]
        is_variadic = False
        while self._check_punct(","):
            self._advance()
            if self._check_punct(")"):
                raise ParserError("Expected parameter declaration after ','", self._current())
            if self._check_punct("..."):
                self._advance()
                is_variadic = True
                if not self._check_punct(")"):
                    if self._check_punct(","):
                        self._advance()
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
        return _type_specs.parse_type_spec(
            self,
            parse_pointer_depth=parse_pointer_depth,
            context=context,
        )

    def _unsupported_type_message(self, context: str, token: Token) -> str:
        return _type_diagnostics.unsupported_type_message(context, token)

    def _unsupported_type_name_token_message(self, token_text: str, token_kind: str) -> str:
        return _type_diagnostics.unsupported_type_name_token_message(token_text, token_kind)

    def _unsupported_declaration_type_token_message(self, token_text: str, token_kind: str) -> str:
        return _type_diagnostics.unsupported_declaration_type_token_message(
            token_text,
            token_kind,
        )

    def _unsupported_type_name_punctuator_message(self, punctuator: str) -> str:
        return _type_diagnostics.unsupported_type_name_punctuator_message(punctuator)

    def _unsupported_declaration_type_punctuator_message(self, punctuator: str) -> str:
        return _type_diagnostics.unsupported_declaration_type_punctuator_message(punctuator)

    def _unsupported_type_token_kind(self, kind: TokenKind) -> str:
        return _type_diagnostics.unsupported_type_token_kind(kind)

    def _consume_type_qualifiers(self, *, allow_atomic: bool = False) -> tuple[str, ...]:
        return _type_specs.consume_type_qualifiers(self, allow_atomic=allow_atomic)

    def _apply_type_qualifiers(
        self,
        type_spec: TypeSpec,
        qualifiers: tuple[str, ...],
    ) -> TypeSpec:
        return _type_specs.apply_type_qualifiers(type_spec, qualifiers)

    def _reject_optional_complex_specifier(self, context: str, *, allow: bool = False) -> None:
        _type_specs.reject_optional_complex_specifier(self, context, allow=allow)

    def _parse_integer_type_spec(
        self,
        first_keyword: str,
        first_token: Token,
        *,
        context: str = "declaration",
    ) -> str:
        return _type_specs.parse_integer_type_spec(
            self,
            first_keyword,
            first_token,
            context=context,
        )

    def _parse_pointer_depth(self) -> int:
        return _declarators.parse_pointer_depth(self)

    def _parse_enum_spec(
        self,
        token: Token,
    ) -> tuple[str | None, tuple[tuple[str, Expr | None], ...]]:
        return _type_specs.parse_enum_spec(self, token)

    def _parse_enum_members(self) -> tuple[tuple[str, Expr | None], ...]:
        return _type_specs.parse_enum_members(self)

    def _parse_enum_member(self) -> tuple[str, Expr | None]:
        return _type_specs.parse_enum_member(self)

    def _parse_record_spec(
        self,
        token: Token,
        kind: str,
    ) -> tuple[str | None, tuple[RecordMemberDecl, ...], bool]:
        return _type_specs.parse_record_spec(self, token, kind)

    def _parse_record_members(self) -> tuple[RecordMemberDecl, ...]:
        return _type_specs.parse_record_members(self)

    def _parse_record_member_declaration(self) -> list[RecordMemberDecl]:
        return _type_specs.parse_record_member_declaration(self)

    def _parse_compound_stmt(
        self,
        initial_names: set[str] | None = None,
        initial_types: dict[str, TypeSpec] | None = None,
    ) -> CompoundStmt:
        return _statements.parse_compound_stmt(self, initial_names, initial_types)

    def _parse_statement(self) -> Stmt:
        return _statements.parse_statement(self)

    def _is_declaration_start(self) -> bool:
        return _statements.is_declaration_start(self)

    def _parse_if_stmt(self) -> IfStmt:
        return _statements.parse_if_stmt(self)

    def _parse_while_stmt(self) -> WhileStmt:
        return _statements.parse_while_stmt(self)

    def _parse_do_while_stmt(self) -> DoWhileStmt:
        return _statements.parse_do_while_stmt(self)

    def _parse_for_stmt(self) -> ForStmt:
        return _statements.parse_for_stmt(self)

    def _parse_switch_stmt(self) -> SwitchStmt:
        return _statements.parse_switch_stmt(self)

    def _parse_case_stmt(self) -> CaseStmt:
        return _statements.parse_case_stmt(self)

    def _parse_default_stmt(self) -> DefaultStmt:
        return _statements.parse_default_stmt(self)

    def _parse_label_stmt(self) -> LabelStmt:
        return _statements.parse_label_stmt(self)

    def _parse_goto_stmt(self) -> Stmt:
        return _statements.parse_goto_stmt(self)

    def _is_label_start(self) -> bool:
        return _statements.is_label_start(self)

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
        ) or (
            self._current().kind == TokenKind.IDENT
            and self._current().lexeme in _IGNORED_IDENT_TYPE_QUALIFIERS
        )
        base_type = self._parse_type_spec(parse_pointer_depth=not is_typedef)
        self._skip_decl_attributes()
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
        # For non-typedef declarations, _parse_type_spec may have absorbed
        # pointer '*' tokens into base_type.declarator_ops.  These belong to
        # the first declarator only.  Compute a raw base without those ops so
        # that subsequent declarators in a comma-separated list start clean.
        if not is_typedef and base_type.declarator_ops:
            # All ops absorbed by parse_pointer_depth are trailing ptr ops.
            trailing_ptrs = 0
            for kind, _ in reversed(base_type.declarator_ops):
                if kind == "ptr":
                    trailing_ptrs += 1
                else:
                    break
            if trailing_ptrs:
                raw_declarator_ops = base_type.declarator_ops[:-trailing_ptrs]
                raw_base_type = TypeSpec(
                    base_type.name,
                    declarator_ops=raw_declarator_ops,
                    qualifiers=base_type.qualifiers,
                    is_atomic=base_type.is_atomic,
                    atomic_target=base_type.atomic_target,
                    enum_tag=base_type.enum_tag,
                    enum_members=base_type.enum_members,
                    record_tag=base_type.record_tag,
                    record_members=base_type.record_members,
                    typeof_expr=base_type.typeof_expr,
                )
            else:
                raw_base_type = base_type
        else:
            raw_base_type = base_type
        is_first_declarator = True
        while True:
            self._skip_decl_attributes()
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
                name, declarator_ops = self._parse_declarator(
                    allow_abstract=False,
                    allow_vla=True,
                )
            if name is None:
                raise self._expected_identifier_error()
            if is_first_declarator:
                decl_type = self._build_declarator_type(base_type, declarator_ops)
                is_first_declarator = False
            else:
                decl_type = self._build_declarator_type(raw_base_type, declarator_ops)
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
                    raise ParserError(
                        self._invalid_object_type_message("object declaration", "void"),
                        self._current(),
                    )
                self._define_ordinary_type(name, decl_type)
                self._skip_decl_extensions()
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
        return _type_specs.is_tag_or_definition_decl(type_spec)

    def _is_function_object_type(self, type_spec: TypeSpec) -> bool:
        return _type_specs.is_function_object_type(type_spec)

    def _define_enum_member_names(self, type_spec: TypeSpec) -> None:
        _type_specs.define_enum_member_names(self, type_spec)

    def _parse_static_assert_decl(self) -> StaticAssertDecl:
        return _statements.parse_static_assert_decl(self)

    def _parse_return_stmt(self) -> ReturnStmt:
        return _statements.parse_return_stmt(self)

    def _parse_initializer(self) -> Expr | InitList:
        return _statements.parse_initializer(self)

    def _parse_initializer_list(self) -> InitList:
        return _statements.parse_initializer_list(self)

    def _parse_designator_list(self) -> tuple[tuple[str, Expr | str | DesignatorRange], ...]:
        return _statements.parse_designator_list(self)

    def _parse_expression(self) -> Expr:
        return _expressions.parse_expression(self)

    def _parse_assignment(self) -> Expr:
        return _expressions.parse_assignment(self)

    def _parse_conditional(self) -> Expr:
        return _expressions.parse_conditional(self)

    def _parse_logical_or(self) -> Expr:
        return _expressions.parse_logical_or(self)

    def _parse_logical_and(self) -> Expr:
        return _expressions.parse_logical_and(self)

    def _parse_bitwise_or(self) -> Expr:
        return _expressions.parse_bitwise_or(self)

    def _parse_bitwise_xor(self) -> Expr:
        return _expressions.parse_bitwise_xor(self)

    def _parse_bitwise_and(self) -> Expr:
        return _expressions.parse_bitwise_and(self)

    def _parse_equality(self) -> Expr:
        return _expressions.parse_equality(self)

    def _parse_relational(self) -> Expr:
        return _expressions.parse_relational(self)

    def _parse_shift(self) -> Expr:
        return _expressions.parse_shift(self)

    def _parse_additive(self) -> Expr:
        return _expressions.parse_additive(self)

    def _parse_multiplicative(self) -> Expr:
        return _expressions.parse_multiplicative(self)

    def _parse_unary(self) -> Expr:
        return _expressions.parse_unary(self)

    def _parse_sizeof_expr(self) -> SizeofExpr:
        return _expressions.parse_sizeof_expr(self)

    def _parse_alignof_expr(self) -> AlignofExpr:
        return _expressions.parse_alignof_expr(self)

    def _parse_typeof_type_spec(self) -> TypeSpec:
        return _expressions.parse_typeof_type_spec(self)

    def _parse_cast_expr(self) -> CastExpr:
        return _expressions.parse_cast_expr(self)

    def _parse_parenthesized_type_name(self) -> TypeSpec:
        return _expressions.parse_parenthesized_type_name(self)

    def _parse_parenthesized_atomic_type_name(self) -> tuple[TypeSpec, bool]:
        return _declarators.parse_parenthesized_atomic_type_name(self)

    def _parse_atomic_type_name_declarator(
        self,
        *,
        allow_abstract: bool = True,
        allow_gnu_attributes: bool = False,
    ) -> tuple[str | None, tuple[DeclaratorOp, ...], bool, bool]:
        return _declarators.parse_atomic_type_name_declarator(
            self,
            allow_abstract=allow_abstract,
            allow_gnu_attributes=allow_gnu_attributes,
        )

    def _parse_atomic_type_name_direct_declarator(
        self,
        *,
        allow_abstract: bool = True,
        allow_gnu_attributes: bool = False,
    ) -> tuple[str | None, tuple[DeclaratorOp, ...], bool]:
        return _declarators.parse_atomic_type_name_direct_declarator(
            self,
            allow_abstract=allow_abstract,
            allow_gnu_attributes=allow_gnu_attributes,
        )

    def _is_top_level_qualified_type_name(
        self,
        *,
        base_has_leading_qualifier: bool,
        base_is_qualified_typedef: bool,
        declarator_has_prefix_qualifier: bool,
        declarator_ops: tuple[DeclaratorOp, ...],
        top_pointer_is_qualified: bool,
    ) -> bool:
        return _declarators.is_top_level_qualified_type_name(
            base_has_leading_qualifier=base_has_leading_qualifier,
            base_is_qualified_typedef=base_is_qualified_typedef,
            declarator_has_prefix_qualifier=declarator_has_prefix_qualifier,
            declarator_ops=declarator_ops,
            top_pointer_is_qualified=top_pointer_is_qualified,
        )

    def _is_parenthesized_type_name_start(self) -> bool:
        return _expressions.is_parenthesized_type_name_start(self)

    def _parse_postfix(self) -> Expr:
        return _expressions.parse_postfix(self)

    def _looks_like_compound_literal(self) -> bool:
        return _expressions.looks_like_compound_literal(self)

    def _parse_compound_literal_expr(self) -> CompoundLiteralExpr:
        return _expressions.parse_compound_literal_expr(self)

    def _build_declarator_type(
        self,
        base_type: TypeSpec,
        declarator_ops: tuple[DeclaratorOp, ...],
    ) -> TypeSpec:
        return _declarators.build_declarator_type(base_type, declarator_ops)

    def _mark_atomic_type_spec(self, type_spec: TypeSpec) -> TypeSpec:
        return _type_specs.mark_atomic_type_spec(type_spec)

    def _format_invalid_atomic_type_message(
        self,
        reason: str,
    ) -> str:
        return _type_specs.format_invalid_atomic_type_message(reason)

    def _classify_invalid_atomic_type(
        self,
        type_spec: TypeSpec,
        *,
        is_qualified_atomic_target: bool = False,
        include_atomic: bool = True,
    ) -> str | None:
        return _type_specs.classify_invalid_atomic_type(
            type_spec,
            is_qualified_atomic_target=is_qualified_atomic_target,
            include_atomic=include_atomic,
        )

    def _is_invalid_void_object_type(self, type_spec: TypeSpec) -> bool:
        return _type_specs.is_invalid_void_object_type(type_spec)

    def _is_invalid_void_parameter_type(self, type_spec: TypeSpec) -> bool:
        return _type_specs.is_invalid_void_parameter_type(type_spec)

    def _parse_declarator(
        self,
        allow_abstract: bool,
        *,
        allow_vla: bool = False,
        allow_parameter_arrays: bool = False,
        allow_flexible_array: bool = False,
    ) -> tuple[str | None, tuple[DeclaratorOp, ...]]:
        return _declarators.parse_declarator(
            self,
            allow_abstract,
            allow_vla=allow_vla,
            allow_parameter_arrays=allow_parameter_arrays,
            allow_flexible_array=allow_flexible_array,
        )

    def _parse_direct_declarator(
        self,
        allow_abstract: bool,
        *,
        allow_vla: bool = False,
        allow_parameter_arrays: bool = False,
        allow_flexible_array: bool = False,
    ) -> tuple[str | None, tuple[DeclaratorOp, ...]]:
        return _declarators.parse_direct_declarator(
            self,
            allow_abstract,
            allow_vla=allow_vla,
            allow_parameter_arrays=allow_parameter_arrays,
            allow_flexible_array=allow_flexible_array,
        )

    def _parse_array_declarator(
        self,
        *,
        allow_vla: bool,
        allow_parameter_arrays: bool,
        allow_flexible_array: bool = False,
    ) -> int | ArrayDecl:
        return _declarators.parse_array_declarator(
            self,
            allow_vla=allow_vla,
            allow_parameter_arrays=allow_parameter_arrays,
            allow_flexible_array=allow_flexible_array,
        )

    def _parse_array_size(self, token: Token) -> int:
        return _array_sizes.parse_array_size(self, token)

    def _parse_array_size_expr(self, expr: Expr, token: Token) -> int:
        return _array_sizes.parse_array_size_expr(self, expr, token)

    def _parse_array_size_expr_or_vla(self, expr: Expr, token: Token) -> int:
        return _array_sizes.parse_array_size_expr_or_vla(self, expr, token)

    def _eval_array_size_expr(self, expr: Expr) -> int | None:
        return _array_sizes.eval_array_size_expr(self, expr)

    def _eval_array_size_generic_expr(self, expr: GenericExpr) -> int | None:
        return _array_sizes.eval_array_size_generic_expr(self, expr)

    def _array_size_generic_control_type(self, control: Expr) -> TypeSpec | None:
        return _array_sizes.array_size_generic_control_type(self, control)

    def _int_literal_type_spec(self, literal: str) -> TypeSpec:
        return _array_sizes.int_literal_type_spec(literal)

    def _decay_type_spec(self, type_spec: TypeSpec) -> TypeSpec:
        return _array_sizes.decay_type_spec(type_spec)

    def _is_generic_control_type_compatible(
        self,
        control_type: TypeSpec,
        assoc_type: TypeSpec,
    ) -> bool:
        return _array_sizes.is_generic_control_type_compatible(control_type, assoc_type)

    def _unqualified_type_spec(self, type_spec: TypeSpec) -> TypeSpec:
        return _array_sizes.unqualified_type_spec(type_spec)

    def _sizeof_type_spec(self, type_spec: TypeSpec) -> int | None:
        return _array_sizes.sizeof_type_spec(self, type_spec)

    def _alignof_type_spec(self, type_spec: TypeSpec) -> int | None:
        return _array_sizes.alignof_type_spec(self, type_spec)

    def _parse_function_suffix_params(self) -> FunctionDeclarator:
        return _declarators.parse_function_suffix_params(self)

    def _parse_arguments(self) -> list[Expr]:
        return _expressions.parse_arguments(self)

    def _parse_primary(self) -> Expr:
        return _expressions.parse_primary(self)

    def _parse_type_name(self) -> TypeSpec:
        return _declarators.parse_type_name(self)

    def _parse_builtin_offsetof(self) -> BuiltinOffsetofExpr:
        return _expressions.parse_builtin_offsetof(self)

    def _parse_generic_expr(self) -> GenericExpr:
        return _expressions.parse_generic_expr(self)

    def _parse_statement_expr(self) -> StatementExpr:
        return _expressions.parse_statement_expr(self)

    def _parse_string_literal(self) -> StringLiteral:
        return _expressions.parse_string_literal(self)

    def _split_string_literal(self, lexeme: str, token: Token) -> tuple[str, str]:
        return _expressions.split_string_literal(self, lexeme, token)

    def _merge_string_prefix(self, prefix: str, next_prefix: str, token: Token) -> str:
        return _expressions.merge_string_prefix(self, prefix, next_prefix, token)

    def _current(self) -> Token:
        return self._tokens[self._index]

    def _advance(self) -> Token:
        token = self._current()
        if token.kind != TokenKind.EOF:
            self._index += 1
        return token

    def _previous(self) -> Token:
        return self._tokens[self._index - 1]

    def _format_token_span(self, start: int, end: int) -> str:
        return _expressions.format_token_span(self, start, end)

    def _type_name_uses_typedef_alias(self, start: int, end: int) -> bool:
        return _expressions.type_name_uses_typedef_alias(self, start, end)

    def _generic_association_type_key(self, type_spec: TypeSpec) -> tuple[object, ...]:
        return _expressions.generic_association_type_key(self, type_spec)

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
        _extensions._skip_extension_markers(self)

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

    def _invalid_object_type_message(self, context: str, type_label: str) -> str:
        return f"Invalid object type for {context}: {type_label}"

    def _consume_overloadable_decl_attributes(self) -> bool:
        return _extensions._consume_overloadable_decl_attributes(self)

    def _skip_decl_attributes(self) -> bool:
        return _extensions._skip_decl_attributes(self)

    def _skip_gnu_attributes(self) -> bool:
        return _extensions._skip_gnu_attributes(self, self._make_error)

    def _skip_decl_extensions(self) -> None:
        _extensions._skip_decl_extensions(self)

    def _consume_decl_attributes(self) -> tuple[bool, bool]:
        return _extensions._consume_decl_attributes(self)

    def _consume_gnu_attributes(self) -> tuple[bool, bool]:
        return _extensions._consume_gnu_attributes(self, self._make_error)

    def _is_gnu_attribute_start(self) -> bool:
        return _extensions._is_gnu_attribute_start(self)

    def _skip_ms_declspecs(self) -> bool:
        return _extensions._skip_ms_declspecs(self, self._make_error)

    def _is_ms_declspec_start(self) -> bool:
        return _extensions._is_ms_declspec_start(self)

    def _skip_calling_convention_identifiers(self) -> bool:
        return _extensions._skip_calling_convention_identifiers(self)

    def _skip_calling_convention_identifiers_before_pointer(self) -> bool:
        return _extensions._skip_calling_convention_identifiers_before_pointer(self)

    def _skip_calling_convention_identifiers_after_pointer(self) -> bool:
        return _extensions._skip_calling_convention_identifiers_after_pointer(self)

    def _skip_type_name_attributes(self, *, allow_gnu_attributes: bool) -> bool:
        return _extensions._skip_type_name_attributes(
            self,
            allow_gnu_attributes=allow_gnu_attributes,
        )

    def _skip_type_qualifiers(self, *, allow_atomic: bool = False) -> bool:
        return _type_specs.skip_type_qualifiers(self, allow_atomic=allow_atomic)

    def _skip_asm_label(self) -> bool:
        return _extensions._skip_asm_label(self, self._make_error)

    def _consume_decl_specifiers(self) -> DeclSpecInfo:
        return _type_specs.consume_decl_specifiers(self)

    def _reject_invalid_alignment_context(
        self,
        alignment: int | None,
        alignment_token: Token | None,
        *,
        context: str,
        allow: bool,
    ) -> None:
        _type_specs.reject_invalid_alignment_context(
            self,
            alignment,
            alignment_token,
            context=context,
            allow=allow,
        )

    def _consume_alignas_specifier(self) -> int:
        return _type_specs.consume_alignas_specifier(self)

    def _try_parse_type_name(self) -> bool:
        return _declarators.try_parse_type_name(self)

    def _is_assignment_operator(self) -> bool:
        return _declarators.is_assignment_operator(self._current(), ASSIGNMENT_OPERATORS)

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
