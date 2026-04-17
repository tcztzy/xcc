from xcc.lexer import Token, TokenKind


def unsupported_type_message(context: str, token: Token) -> str:
    token_text = str(token.lexeme)
    if token.kind == TokenKind.IDENT:
        if context == "type-name":
            return f"Unknown type name: '{token_text}'"
        return f"Unknown declaration type name: '{token_text}'"
    if token.kind == TokenKind.KEYWORD:
        if context == "type-name":
            return f"Unsupported type name: '{token_text}'"
        return f"Unsupported declaration type: '{token_text}'"
    token_kind = unsupported_type_token_kind(token.kind)
    if context == "type-name":
        if token.kind == TokenKind.PUNCTUATOR:
            return unsupported_type_name_punctuator_message(token_text)
        return unsupported_type_name_token_message(token_text, token_kind)
    if token.kind == TokenKind.PUNCTUATOR:
        return unsupported_declaration_type_punctuator_message(token_text)
    return unsupported_declaration_type_token_message(token_text, token_kind)


def unsupported_type_name_token_message(token_text: str, token_kind: str) -> str:
    if token_kind == "end of input":
        return "Type name is missing before end of input"
    return f"Type name cannot start with {token_kind}: '{token_text}'"


def unsupported_declaration_type_token_message(token_text: str, token_kind: str) -> str:
    if token_kind == "end of input":
        return "Declaration type is missing before end of input"
    return f"Declaration type cannot start with {token_kind}: '{token_text}'"


_UNSUPPORTED_TYPE_NAME_PUNCTUATOR_MESSAGES = {
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


def unsupported_type_name_punctuator_message(punctuator: str) -> str:
    return _UNSUPPORTED_TYPE_NAME_PUNCTUATOR_MESSAGES.get(
        punctuator,
        f"Unsupported type name punctuator: '{punctuator}'",
    )


_UNSUPPORTED_DECLARATION_TYPE_PUNCTUATOR_MESSAGES = {
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


def unsupported_declaration_type_punctuator_message(punctuator: str) -> str:
    return _UNSUPPORTED_DECLARATION_TYPE_PUNCTUATOR_MESSAGES.get(
        punctuator,
        f"Unsupported declaration type punctuator: '{punctuator}'",
    )


def unsupported_type_token_kind(kind: TokenKind) -> str:
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
