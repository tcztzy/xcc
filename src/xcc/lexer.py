from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, auto
from typing import NoReturn


class TokenKind(Enum):
    KEYWORD = auto()
    IDENT = auto()
    INT = auto()
    STRING = auto()
    CHAR = auto()
    PUNCT = auto()
    EOF = auto()


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: str | int | None
    line: int
    column: int


class LexerError(ValueError):
    def __init__(self, message: str, line: int, column: int) -> None:
        super().__init__(f"{message} at {line}:{column}")
        self.line = line
        self.column = column


KEYWORDS = {
    "int",
    "void",
    "return",
}

PUNCTUATORS = (
    ">>=",
    "<<=",
    "...",
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


class Lexer:
    def __init__(self, source: str) -> None:
        self._source = source
        self._length = len(source)
        self._index = 0
        self._line = 1
        self._column = 1

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while True:
            self._skip_whitespace_and_comments()
            if self._eof():
                tokens.append(Token(TokenKind.EOF, None, self._line, self._column))
                return tokens
            ch = self._peek()
            start_line = self._line
            start_column = self._column
            if ch.isalpha() or ch == "_":
                ident = self._read_identifier()
                kind = TokenKind.KEYWORD if ident in KEYWORDS else TokenKind.IDENT
                tokens.append(Token(kind, ident, start_line, start_column))
            elif ch.isdigit():
                value = self._read_number()
                tokens.append(Token(TokenKind.INT, value, start_line, start_column))
            elif ch == '"':
                value = self._read_string()
                tokens.append(Token(TokenKind.STRING, value, start_line, start_column))
            elif ch == "'":
                value = self._read_char()
                tokens.append(Token(TokenKind.CHAR, value, start_line, start_column))
            else:
                punct = self._read_punctuator()
                tokens.append(Token(TokenKind.PUNCT, punct, start_line, start_column))

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
            if ch in " \t\r\n":
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
                while not self._eof():
                    if self._peek() == "*" and self._peek(1) == "/":
                        self._advance()
                        self._advance()
                        break
                    self._advance()
                else:
                    self._error("Unterminated block comment")
                continue
            break

    def _read_identifier(self) -> str:
        start = self._index
        while not self._eof():
            ch = self._peek()
            if ch.isalnum() or ch == "_":
                self._advance()
            else:
                break
        return self._source[start : self._index]

    def _read_number(self) -> int:
        if self._peek() == "0" and self._peek(1) in {"x", "X"}:
            self._advance()
            self._advance()
            start = self._index
            while not self._eof() and self._peek().lower() in "0123456789abcdef":
                self._advance()
            if self._index == start:
                self._error("Invalid hex literal")
            return int(self._source[start : self._index], 16)
        start = self._index
        while not self._eof() and self._peek().isdigit():
            self._advance()
        return int(self._source[start : self._index], 10)

    def _read_escape(self) -> str:
        ch = self._advance()
        if ch == "n":
            return "\n"
        if ch == "t":
            return "\t"
        if ch == "r":
            return "\r"
        if ch == "0":
            return "\0"
        if ch == "\\":
            return "\\"
        if ch == '"':
            return '"'
        if ch == "'":
            return "'"
        self._error("Unsupported escape")

    def _read_string(self) -> str:
        self._advance()
        chars: list[str] = []
        while not self._eof():
            ch = self._advance()
            if ch == '"':
                return "".join(chars)
            if ch == "\n" or ch == "":
                self._error("Unterminated string literal")
            if ch == "\\":
                chars.append(self._read_escape())
            else:
                chars.append(ch)
        self._error("Unterminated string literal")

    def _read_char(self) -> str:
        self._advance()
        if self._eof():
            self._error("Unterminated char literal")
        ch = self._advance()
        if ch == "\\":
            ch = self._read_escape()
        if self._peek() != "'":
            self._error("Unterminated char literal")
        self._advance()
        return ch

    def _read_punctuator(self) -> str:
        for punct in PUNCTUATORS:
            if self._source.startswith(punct, self._index):
                for _ in punct:
                    self._advance()
                return punct
        self._error(f"Unexpected character {self._peek()!r}")

    def _error(self, message: str) -> NoReturn:
        raise LexerError(message, self._line, self._column)


def lex(source: str) -> Iterable[Token]:
    return Lexer(source).tokenize()
