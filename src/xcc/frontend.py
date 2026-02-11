import re
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


def _blank_line(line: str) -> str:
    return "\n" if line.endswith("\n") else ""


_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_DEFINE_RE = re.compile(r"^\s*#\s*define\b")


def _parse_object_like_define(line: str) -> tuple[str, str] | None:
    if _DEFINE_RE.match(line) is None:
        return None
    define_body = line.rstrip("\n")
    define_body = define_body[define_body.find("define") + len("define") :].lstrip()
    if not define_body:
        return None
    name_match = _IDENT_RE.match(define_body)
    if name_match is None:
        return None
    name = name_match.group(0)
    replacement = define_body[name_match.end() :]
    if replacement.startswith("("):
        return None
    return name, replacement.strip()


def _expand_object_like_macros(line: str, macros: dict[str, str]) -> str:
    if not macros:
        return line
    names: list[str] = list(macros)
    names.sort(key=len, reverse=True)
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in names) + r")\b")
    return pattern.sub(lambda match: macros[match.group(0)], line)


def _strip_preprocessor_directives(source: str) -> str:
    lines = source.splitlines(keepends=True)
    if not lines:
        return source
    stripped_lines: list[str] = []
    macros: dict[str, str] = {}
    in_directive_continuation = False
    for line in lines:
        if in_directive_continuation:
            stripped_lines.append(_blank_line(line))
            in_directive_continuation = line.rstrip().endswith("\\")
            continue
        if line.lstrip().startswith("#"):
            define = _parse_object_like_define(line)
            if define is not None:
                macros[define[0]] = define[1]
            stripped_lines.append(_blank_line(line))
            in_directive_continuation = line.rstrip().endswith("\\")
            continue
        stripped_lines.append(_expand_object_like_macros(line, macros))
    return "".join(stripped_lines)


_ASM_PREFIX_RE = re.compile(r"^\s*(?:__asm__|__asm|asm)\b")
_ASM_LABEL_RE = re.compile(r"(?<!\w)(?:__asm__|__asm|asm)\s*\([^;\n]*\)")


def _strip_gnu_asm_extensions(source: str) -> str:
    lines = source.splitlines(keepends=True)
    if not lines:
        return source
    stripped_lines: list[str] = []
    in_asm_statement = False
    for line in lines:
        if in_asm_statement:
            stripped_lines.append(_blank_line(line))
            if ";" in line:
                in_asm_statement = False
            continue
        if _ASM_PREFIX_RE.match(line):
            stripped_lines.append(_blank_line(line))
            in_asm_statement = ";" not in line
            continue
        stripped_lines.append(_ASM_LABEL_RE.sub("", line))
    return "".join(stripped_lines)


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
    normalized_source = _strip_gnu_asm_extensions(_strip_preprocessor_directives(source))
    try:
        tokens = lex(normalized_source)
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
