import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from xcc.ast import TranslationUnit
from xcc.lexer import LexerError, Token, lex
from xcc.parser import ParserError, parse
from xcc.sema import SemaError, SemaUnit, analyze


def _trim_location_suffix(message: str, line: int, column: int) -> str:
    return message.removesuffix(f" at {line}:{column}")


@dataclass(frozen=True)
class Diagnostic:
    stage: str
    filename: str
    message: str
    line: int | None = None
    column: int | None = None

    def __str__(self) -> str:
        if self.line is None or self.column is None:
            return f"{self.filename}: {self.stage}: {self.message}"
        return f"{self.filename}:{self.line}:{self.column}: {self.stage}: {self.message}"


class FrontendError(ValueError):
    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(str(diagnostic))
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class FrontendResult:
    filename: str
    source: str
    tokens: list[Token]
    unit: TranslationUnit
    sema: SemaUnit


def read_source(path: str, *, stdin: TextIO | None = None) -> tuple[str, str]:
    if path == "-":
        stream = sys.stdin if stdin is None else stdin
        return "<stdin>", stream.read()
    resolved = Path(path)
    return str(resolved), resolved.read_text(encoding="utf-8")


def compile_source(source: str, *, filename: str = "<input>") -> FrontendResult:
    try:
        tokens = lex(source)
    except LexerError as error:
        message = _trim_location_suffix(str(error), error.line, error.column)
        diagnostic = Diagnostic("lex", filename, message, error.line, error.column)
        raise FrontendError(diagnostic) from error
    try:
        unit = parse(tokens)
    except ParserError as error:
        token = error.token
        diagnostic = Diagnostic("parse", filename, error.message, token.line, token.column)
        raise FrontendError(diagnostic) from error
    try:
        sema = analyze(unit)
    except SemaError as error:
        raise FrontendError(Diagnostic("sema", filename, str(error))) from error
    return FrontendResult(filename, source, tokens, unit, sema)


def compile_path(path: str | Path) -> FrontendResult:
    filename, source = read_source(str(path))
    return compile_source(source, filename=filename)


def format_token(token: Token) -> str:
    if token.lexeme is None:
        return f"{token.line}:{token.column}\t{token.kind.name}"
    return f"{token.line}:{token.column}\t{token.kind.name}\t{token.lexeme}"


def format_tokens(tokens: list[Token]) -> list[str]:
    return [format_token(token) for token in tokens]
