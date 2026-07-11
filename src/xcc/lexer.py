from dataclasses import dataclass
from enum import Enum, auto
from typing import NoReturn, cast

TRIGRAPHS = {
    "=": "#",
    "/": "\\",
    "'": "^",
    "(": "[",
    ")": "]",
    "!": "|",
    "<": "{",
    ">": "}",
    "-": "~",
}

KEYWORDS = {
    "auto",
    "break",
    "case",
    "char",
    "const",
    "continue",
    "default",
    "do",
    "double",
    "else",
    "enum",
    "extern",
    "float",
    "for",
    "goto",
    "if",
    "inline",
    "int",
    "long",
    "register",
    "restrict",
    "__restrict",
    "__restrict__",
    "return",
    "short",
    "signed",
    "sizeof",
    "static",
    "struct",
    "switch",
    "typedef",
    "union",
    "unsigned",
    "void",
    "volatile",
    "while",
    "_Alignas",
    "_Alignof",
    "__alignof__",
    "_Atomic",
    "_Bool",
    "_Complex",
    "_Generic",
    "_Imaginary",
    "_Noreturn",
    "_Static_assert",
    "_Thread_local",
    "typeof",
    "typeof_unqual",
    "__typeof__",
    "__typeof",
    "__typeof_unqual__",
    "__typeof_unqual",
    "__extension__",
}

PUNCTUATORS: tuple[str, ...] = (
    "...",
    ">>=",
    "<<=",
    "->",
    "++",
    "--",
    "&&",
    "||",
    "<=",
    ">=",
    "==",
    "!=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<",
    ">>",
    "##",
    "<:",
    ":>",
    "<%",
    "%>",
    "%:",
    "%:%:",
    "[",
    "]",
    "(",
    ")",
    "{",
    "}",
    ".",
    "&",
    "*",
    "+",
    "-",
    "~",
    "!",
    "/",
    "%",
    "<",
    ">",
    "^",
    "|",
    "?",
    ":",
    ";",
    "=",
    ",",
    "#",
)

PUNCTUATORS_SORTED: tuple[str, ...] = cast(
    tuple[str, ...], tuple(sorted(PUNCTUATORS, key=len, reverse=True))
)

SIMPLE_ESCAPES = {
    "'",
    '"',
    "?",
    "\\",
    "a",
    "b",
    "f",
    "n",
    "r",
    "t",
    "v",
}


class TokenKind(Enum):
    KEYWORD = auto()
    IDENT = auto()
    INT_CONST = auto()
    FLOAT_CONST = auto()
    CHAR_CONST = auto()
    STRING_LITERAL = auto()
    PUNCTUATOR = auto()
    HEADER_NAME = auto()
    PP_NUMBER = auto()
    EOF = auto()


@dataclass(frozen=True)
class Token:
    kind: Enum
    lexeme: str | None
    line: int
    column: int


class LexerError(ValueError):
    def __init__(self, message: str, line: int, column: int) -> None:
        super().__init__(f"{message} at {line}:{column}")
        self.line = line
        self.column = column


def translate_source(source: str) -> str:
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    source = _replace_trigraphs(source)
    return _splice_lines(source)


def _replace_trigraphs(source: str) -> str:
    out: list[str] = []
    i = 0
    length = len(source)
    while i < length:
        if (
            source[i] == "?"
            and i + 2 < length
            and source[i + 1] == "?"
            and source[i + 2] in TRIGRAPHS
        ):
            out.append(TRIGRAPHS[source[i + 2]])
            i += 3
            continue
        out.append(source[i])
        i += 1
    return "".join(out)


def _splice_lines(source: str) -> str:
    out: list[str] = []
    i = 0
    length = len(source)
    while i < length:
        if source[i] == "\\" and i + 1 < length and source[i + 1] == "\n":
            i += 2
            continue
        out.append(source[i])
        i += 1
    return "".join(out)


def lex(source: str) -> list[Token]:
    return Lexer(source).tokenize()


def lex_pp(source: str, *, header_names: bool = False) -> list[Token]:
    return Lexer(source, mode="preprocessor", header_names=header_names).tokenize()


def summarize_tokens(tokens: list[Token]) -> str:
    parts: list[str] = []
    for token in tokens:
        parts.append(f"{token.kind.name}:{token.lexeme}:{token.line}:{token.column}")
    return "|".join(parts)


def _aot_token_summary_for_source(source: str) -> str:
    return summarize_tokens(lex(source))


def _aot_header_summary_for_source(source: str) -> str:
    return summarize_tokens(lex_pp(source, header_names=True))


def _aot_error_summary_for_source(source: str) -> str:
    try:
        lex(source)
    except LexerError as exc:
        return str(exc)
    return ""


class Lexer:
    def __init__(
        self, source: str, *, mode: str = "translation", header_names: bool = False
    ) -> None:
        if mode not in {"translation", "preprocessor"}:
            raise ValueError("Unknown lexer mode")
        self._source = translate_source(source)
        self._length = len(self._source)
        self._index = 0
        self._line = 1
        self._column = 1
        self._mode = mode
        self._header_names = header_names

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while True:
            self._skip_whitespace_and_comments()
            if self._eof():
                tokens.append(Token(TokenKind.EOF, None, self._line, self._column))
                return tokens
            start_line = self._line
            start_column = self._column
            if self._mode == "preprocessor" and self._header_names:
                header_name = self._maybe_read_header_name()
                if header_name is not None:
                    tokens.append(
                        Token(TokenKind.HEADER_NAME, header_name, start_line, start_column)
                    )
                    continue
            literal = self._maybe_read_literal()
            if literal is not None:
                kind, lexeme = literal
                tokens.append(Token(kind, lexeme, start_line, start_column))
                continue
            if self._is_number_start():
                lexeme = self._read_pp_number()
                if self._mode == "preprocessor":
                    kind = TokenKind.PP_NUMBER
                else:
                    kind = self._classify_number(lexeme, start_line, start_column)
                tokens.append(Token(kind, lexeme, start_line, start_column))
                continue
            if self._is_identifier_start():
                lexeme = self._read_identifier()
                if self._mode == "translation" and lexeme in KEYWORDS:
                    kind = TokenKind.KEYWORD
                else:
                    kind = TokenKind.IDENT
                tokens.append(Token(kind, lexeme, start_line, start_column))
                continue
            punct = self._read_punctuator(start_line, start_column)
            tokens.append(Token(TokenKind.PUNCTUATOR, punct, start_line, start_column))

    def _peek(self, offset: int = 0) -> str:
        index = self._index + offset
        if index >= self._length:
            return ""
        return self._source[index]

    def _advance(self) -> str:
        if self._index >= self._length:
            return ""
        ch = self._source[self._index]
        self._index += 1
        if ch == "\n":
            self._line += 1
            self._column = 1
        else:
            self._column += 1
        return ch

    def _eof(self) -> bool:
        return self._index >= self._length

    def _skip_whitespace_and_comments(self) -> None:
        while not self._eof():
            ch = self._peek()
            if ch in " \t\v\f\n":
                self._advance()
                continue
            if ch == "/" and self._peek(1) == "/":
                self._advance()
                self._advance()
                while not self._eof() and self._peek() != "\n":
                    self._advance()
                continue
            if ch == "/" and self._peek(1) == "*":
                self._advance()
                self._advance()
                while not self._eof() and not (self._peek() == "*" and self._peek(1) == "/"):
                    self._advance()
                if self._eof():
                    self._error("Unterminated block comment")
                self._advance()
                self._advance()
                continue
            break

    def _is_identifier_start(self) -> bool:
        ch = self._peek()
        if ch == "_" or ch.isalpha():
            return True
        return ch == "\\" and self._peek(1) in {"u", "U"}

    def _is_identifier_part(self) -> bool:
        ch = self._peek()
        if ch == "_" or ch.isalpha() or ch.isdigit():
            return True
        return ch == "\\" and self._peek(1) in {"u", "U"}

    def _read_identifier(self) -> str:
        start = self._index
        if not self._is_identifier_start():
            self._error("Expected identifier")
        self._read_identifier_char(initial=True)
        while not self._eof() and self._is_identifier_part():
            self._read_identifier_char(initial=False)
        return self._source[start : self._index]

    def _read_identifier_char(self, *, initial: bool) -> None:
        ch = self._peek()
        if ch == "\\" and self._peek(1) in {"u", "U"}:
            self._read_ucn()
            return
        if ch == "_" or ch.isalpha() or (not initial and ch.isdigit()):
            self._advance()
            return
        self._error("Invalid identifier character")

    def _read_ucn(self) -> str:
        start = self._index
        if self._advance() != "\\":
            self._error("Expected universal character name")
        kind = self._advance()
        if kind not in {"u", "U"}:
            self._error("Invalid universal character name")
        self._read_ucn_digits(kind)
        return self._source[start : self._index]

    def _maybe_read_literal(self) -> tuple[TokenKind, str] | None:
        start = self._index
        ch = self._peek()
        if ch in {'"', "'"}:
            if ch == '"':
                return TokenKind.STRING_LITERAL, self._read_string_literal(start)
            return TokenKind.CHAR_CONST, self._read_char_constant(start)
        if ch == "u" and self._peek(1) == "8" and self._peek(2) == '"':
            self._advance()
            self._advance()
            return TokenKind.STRING_LITERAL, self._read_string_literal(start)
        if ch in {"u", "U", "L"} and self._peek(1) in {'"', "'"}:
            self._advance()
            if self._peek() == '"':
                return TokenKind.STRING_LITERAL, self._read_string_literal(start)
            return TokenKind.CHAR_CONST, self._read_char_constant(start)
        return None

    def _read_string_literal(self, start: int) -> str:
        if self._peek() != '"':
            self._error("Expected string literal")
        self._advance()
        while not self._eof():
            ch = self._advance()
            if ch == '"':
                return self._source[start : self._index]
            if ch == "\n" or ch == "":
                self._error("Unterminated string literal")
            if ch == "\\":
                self._read_escape_sequence()
        self._error("Unterminated string literal")

    def _read_char_constant(self, start: int) -> str:
        if self._peek() != "'":
            self._error("Expected character constant")
        self._advance()
        if self._peek() == "'":
            self._error("Empty character constant")
        while not self._eof():
            ch = self._advance()
            if ch == "'":
                return self._source[start : self._index]
            if ch == "\n" or ch == "":
                self._error("Unterminated character constant")
            if ch == "\\":
                self._read_escape_sequence()
        self._error("Unterminated character constant")

    def _read_escape_sequence(self) -> None:
        ch = self._peek()
        if ch in SIMPLE_ESCAPES:
            self._advance()
            return
        if ch == "x":
            self._advance()
            if not _is_hex_digit(self._peek()):
                self._error("Invalid hexadecimal escape")
            while _is_hex_digit(self._peek()):
                self._advance()
            return
        if ch in {"u", "U"}:
            self._read_ucn_escape()
            return
        if _is_octal_digit(ch):
            self._advance()
            if _is_octal_digit(self._peek()):
                self._advance()
                if _is_octal_digit(self._peek()):
                    self._advance()
            return
        self._error("Invalid escape sequence")

    def _read_ucn_escape(self) -> None:
        kind = self._advance()
        if kind not in {"u", "U"}:
            self._error("Invalid universal character name")
        self._read_ucn_digits(kind)

    def _read_ucn_digits(self, kind: str) -> None:
        count = 4 if kind == "u" else 8
        digits = []
        for _ in range(count):
            ch = self._peek()
            if ch == "" or not _is_hex_digit(ch):
                self._error("Invalid universal character name")
            digits.append(self._advance())
        codepoint = int("".join(digits), 16)
        if codepoint > 0x10FFFF:
            self._error("Invalid universal character name")
        if codepoint < 0x00A0 and codepoint not in {0x0024, 0x0040, 0x0060}:
            self._error("Invalid universal character name")
        if 0xD800 <= codepoint <= 0xDFFF:
            self._error("Invalid universal character name")

    def _is_number_start(self) -> bool:
        ch = self._peek()
        if ch.isdigit():
            return True
        return ch == "." and self._peek(1).isdigit()

    def _read_pp_number(self) -> str:
        start = self._index
        if self._peek() == ".":
            self._advance()
        else:
            self._advance()
        while not self._eof():
            ch = self._peek()
            next_ch = self._peek(1)
            if ch in {"e", "E", "p", "P"} and next_ch in {"+", "-"}:
                self._advance()
                self._advance()
                continue
            if ch.isdigit() or ch == "." or ch == "_" or ch.isalpha():
                self._advance()
                continue
            if ch == "\\" and next_ch in {"u", "U"}:
                self._read_ucn()
                continue
            break
        return self._source[start : self._index]

    def _classify_number(self, lexeme: str, line: int, column: int) -> TokenKind:
        if _is_hex_float_literal(lexeme) or _is_decimal_float_literal(lexeme):
            return TokenKind.FLOAT_CONST
        if _is_integer_literal(lexeme):
            return TokenKind.INT_CONST
        return TokenKind.PP_NUMBER

    def _read_punctuator(self, line: int, column: int) -> str:
        for punct in PUNCTUATORS_SORTED:
            if self._source.startswith(punct, self._index):
                self._index += len(punct)
                self._column += len(punct)
                return punct
        self._error("Unexpected character", line=line, column=column)

    def _maybe_read_header_name(self) -> str | None:
        ch = self._peek()
        if ch not in {"<", '"'}:
            return None
        start = self._index
        end_char = ">" if ch == "<" else '"'
        self._advance()
        while not self._eof():
            if self._peek() == "\n":
                self._error("Unterminated header name")
            if self._peek() == end_char:
                self._advance()
                return self._source[start : self._index]
            if self._peek() in {"'", "\\"}:
                self._error("Invalid header name")
            if self._peek() == "/" and self._peek(1) in {"/", "*"}:
                self._error("Invalid header name")
            self._advance()
        self._error("Unterminated header name")

    def _error(
        self, message: str, *, line: int | None = None, column: int | None = None
    ) -> NoReturn:
        raise LexerError(message, line or self._line, column or self._column)


def _is_hex_digit(ch: str) -> bool:
    return ch.isdigit() or ("a" <= ch <= "f") or ("A" <= ch <= "F")


def _is_octal_digit(ch: str) -> bool:
    return "0" <= ch <= "7"


def _is_float_suffix(ch: str) -> bool:
    return ch in {"f", "F", "l", "L"}


def _is_sign(ch: str) -> bool:
    return ch == "+" or ch == "-"


def _is_x_marker(ch: str) -> bool:
    return ch == "x" or ch == "X"


def _is_p_marker(ch: str) -> bool:
    return ch == "p" or ch == "P"


def _is_e_marker(ch: str) -> bool:
    return ch == "e" or ch == "E"


def _is_u_suffix(ch: str) -> bool:
    return ch == "u" or ch == "U"


def _is_l_suffix(ch: str) -> bool:
    return ch == "l" or ch == "L"


def _has_long_long_suffix(text: str, index: int) -> bool:
    return index + 1 < len(text) and (
        (text[index] == "l" and text[index + 1] == "l")
        or (text[index] == "L" and text[index + 1] == "L")
    )


def _is_integer_suffix(text: str, index: int) -> bool:
    length = len(text)
    if index == length:
        return True
    if index > length:
        return False
    ch = text[index]
    if _is_u_suffix(ch):
        index += 1
        if index == length:
            return True
        if _has_long_long_suffix(text, index):
            return index + 2 == length
        if _is_l_suffix(text[index]):
            return index + 1 == length
        return False
    if _has_long_long_suffix(text, index):
        index += 2
        if index == length:
            return True
        return _is_u_suffix(text[index]) and index + 1 == length
    if _is_l_suffix(ch):
        index += 1
        if index == length:
            return True
        return _is_u_suffix(text[index]) and index + 1 == length
    return False


def _is_integer_literal(text: str) -> bool:
    length = len(text)
    if length == 0:
        return False
    if text[0] == "0":
        if length > 1 and _is_x_marker(text[1]):
            index = 2
            digits = 0
            while index < length and _is_hex_digit(text[index]):
                index += 1
                digits += 1
            return digits > 0 and _is_integer_suffix(text, index)
        index = 1
        while index < length and _is_octal_digit(text[index]):
            index += 1
        return _is_integer_suffix(text, index)
    if "1" <= text[0] <= "9":
        index = 1
        while index < length and text[index].isdigit():
            index += 1
        return _is_integer_suffix(text, index)
    return False


def _is_decimal_float_literal(text: str) -> bool:
    end = len(text)
    if end == 0:
        return False
    if _is_float_suffix(text[end - 1]):
        end -= 1
    if end == 0:
        return False
    index = 0
    whole_digits = 0
    while index < end and text[index].isdigit():
        index += 1
        whole_digits += 1
    saw_dot = False
    fraction_digits = 0
    if index < end and text[index] == ".":
        saw_dot = True
        index += 1
        while index < end and text[index].isdigit():
            index += 1
            fraction_digits += 1
    if index < end and _is_e_marker(text[index]):
        if whole_digits == 0 and not saw_dot:
            return False
        index += 1
        if index < end and _is_sign(text[index]):
            index += 1
        exponent_digits = 0
        while index < end and text[index].isdigit():
            index += 1
            exponent_digits += 1
        return exponent_digits > 0 and index == end
    if saw_dot:
        return whole_digits + fraction_digits > 0 and index == end
    return False


def _is_hex_float_literal(text: str) -> bool:
    end = len(text)
    if end == 0:
        return False
    if _is_float_suffix(text[end - 1]):
        end -= 1
    if end < 4:
        return False
    if text[0] != "0" or not _is_x_marker(text[1]):
        return False
    index = 2
    whole_digits = 0
    while index < end and _is_hex_digit(text[index]):
        index += 1
        whole_digits += 1
    fraction_digits = 0
    if index < end and text[index] == ".":
        index += 1
        while index < end and _is_hex_digit(text[index]):
            index += 1
            fraction_digits += 1
    if whole_digits + fraction_digits == 0:
        return False
    if index >= end or not _is_p_marker(text[index]):
        return False
    index += 1
    if index < end and _is_sign(text[index]):
        index += 1
    exponent_digits = 0
    while index < end and text[index].isdigit():
        index += 1
        exponent_digits += 1
    return exponent_digits > 0 and index == end
