import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from xcc.ast import TranslationUnit
from xcc.data_layout import data_layout_for_target
from xcc.diag import Diagnostic, FrontendError
from xcc.lexer import LexerError, Token, lex, lex_pp
from xcc.options import FrontendOptions, normalize_options
from xcc.parser import ParserError, parse
from xcc.preprocessor import PreprocessorError, PreprocessResult, preprocess_source
from xcc.sema import SemaError, SemaUnit, analyze

_LEX_ERROR_CODE = "XCC-LEX-0001"
_PARSE_ERROR_CODE = "XCC-PARSE-0001"
_SEMA_ERROR_CODE = "XCC-SEMA-0001"


def _trim_location_suffix(
    message: str,
    line: int | None,
    column: int | None,
    *,
    filename: str | None = None,
) -> str:
    if line is None or column is None:
        return message
    trimmed = message.removesuffix(f" at {line}:{column}")
    if filename is not None:
        trimmed = trimmed.removesuffix(f" at {filename}:{line}:{column}")
    return trimmed


@dataclass(frozen=True)
class FrontendResult:
    filename: str
    source: str
    preprocessed_source: str
    tokens: list[Token]
    unit: TranslationUnit
    sema: SemaUnit
    include_trace: tuple[str, ...]
    macro_table: tuple[str, ...]
    line_map: tuple[tuple[str, int], ...] = ()
    _pp_tokens: list[Token] | None = None

    @property
    def pp_tokens(self) -> list[Token]:
        tokens = self._pp_tokens
        if tokens is None:
            tokens = lex_pp(self.preprocessed_source)
            object.__setattr__(self, "_pp_tokens", tokens)
        return tokens


@dataclass
class AotFrontendTimings:
    preprocessing_ns: int = 0
    parser_ns: int = 0
    sema_ns: int = 0


def _aot_monotonic_ns() -> int:
    return time.monotonic_ns()


def _map_diagnostic_location(
    pp_line_map: tuple[tuple[str, int], ...],
    line: int | None,
    column: int | None,
) -> tuple[str | None, int | None, int | None]:
    if line is None or column is None:
        return None, line, column
    if 1 <= line <= len(pp_line_map):
        mapped_filename, mapped_line = pp_line_map[line - 1]
        return mapped_filename, mapped_line, column
    return None, line, column


def read_source(path: str, *, stdin: TextIO | None = None) -> tuple[str, str]:
    if path == "-":
        stream = sys.stdin if stdin is None else stdin
        return "<stdin>", stream.read()
    resolved = Path(path)
    return str(resolved), resolved.read_text(encoding="utf-8", errors="surrogateescape")


def _aot_compile_source_unchecked(
    source: str,
    filename: str,
    options: FrontendOptions,
    timings: AotFrontendTimings | None = None,
) -> FrontendResult:
    normalized_options: FrontendOptions = normalize_options(options)
    data_layout = data_layout_for_target(
        normalized_options.target_os,
        normalized_options.host_machine,
    )
    preprocessing_start = _aot_monotonic_ns() if timings is not None else 0
    try:
        pp_result: PreprocessResult = preprocess_source(
            source,
            filename=filename,
            options=normalized_options,
        )
    finally:
        if timings is not None:
            timings.preprocessing_ns = _aot_monotonic_ns() - preprocessing_start
    parser_start = _aot_monotonic_ns() if timings is not None else 0
    try:
        tokens: list[Token] = lex(pp_result.source)
        unit: TranslationUnit = parse(
            tokens,
            std=normalized_options.std,
            data_layout=data_layout,
        )
    finally:
        if timings is not None:
            timings.parser_ns = _aot_monotonic_ns() - parser_start
    sema_start = _aot_monotonic_ns() if timings is not None else 0
    try:
        sema: SemaUnit = analyze(
            unit,
            std=normalized_options.std,
            excess_init_ok=pp_result.embed_used,
            pack_changes=pp_result.pack_changes,
            data_layout=data_layout,
        )
    finally:
        if timings is not None:
            timings.sema_ns = _aot_monotonic_ns() - sema_start
    return FrontendResult(
        filename,
        source,
        pp_result.source,
        tokens,
        unit,
        sema,
        pp_result.include_trace,
        pp_result.macro_table,
        pp_result.line_map,
    )


def compile_source(
    source: str,
    *,
    filename: str = "<input>",
    options: FrontendOptions | None = None,
) -> FrontendResult:
    normalized_options = normalize_options(options)
    data_layout = data_layout_for_target(
        normalized_options.target_os,
        normalized_options.host_machine,
    )
    try:
        pp_result = preprocess_source(source, filename=filename, options=normalized_options)
    except PreprocessorError as error:
        message = _trim_location_suffix(
            str(error),
            error.line,
            error.column,
            filename=error.filename,
        )
        diagnostic = Diagnostic(
            "pp",
            filename if error.filename is None else error.filename,
            message,
            error.line,
            error.column,
            code=error.code,
        )
        raise FrontendError(diagnostic) from error
    try:
        tokens = lex(pp_result.source)
    except LexerError as error:
        mapped_filename, mapped_line, mapped_column = _map_diagnostic_location(
            pp_result.line_map,
            error.line,
            error.column,
        )
        message = _trim_location_suffix(str(error), error.line, error.column)
        diagnostic = Diagnostic(
            "lex",
            filename if mapped_filename is None else mapped_filename,
            message,
            mapped_line,
            mapped_column,
            code=_LEX_ERROR_CODE,
        )
        raise FrontendError(diagnostic) from error
    try:
        unit = parse(tokens, std=normalized_options.std, data_layout=data_layout)
    except ParserError as error:
        token = error.token
        mapped_filename, mapped_line, mapped_column = _map_diagnostic_location(
            pp_result.line_map,
            token.line,
            token.column,
        )
        diagnostic = Diagnostic(
            "parse",
            filename if mapped_filename is None else mapped_filename,
            error.message,
            mapped_line,
            mapped_column,
            code=_PARSE_ERROR_CODE,
        )
        raise FrontendError(diagnostic) from error
    try:
        sema = analyze(
            unit,
            std=normalized_options.std,
            excess_init_ok=pp_result.embed_used,
            pack_changes=pp_result.pack_changes,
            data_layout=data_layout,
        )
    except SemaError as error:
        mapped_filename, mapped_line, mapped_column = _map_diagnostic_location(
            pp_result.line_map,
            error.line,
            error.column,
        )
        raise FrontendError(
            Diagnostic(
                "sema",
                filename if mapped_filename is None else mapped_filename,
                str(error),
                mapped_line,
                mapped_column,
                code=_SEMA_ERROR_CODE,
            )
        ) from error
    return FrontendResult(
        filename,
        source,
        pp_result.source,
        tokens,
        unit,
        sema,
        pp_result.include_trace,
        pp_result.macro_table,
        pp_result.line_map,
    )


def compile_path(path: str | Path, *, options: FrontendOptions | None = None) -> FrontendResult:
    filename, source = read_source(str(path))
    return compile_source(source, filename=filename, options=options)


def format_token(token: Token) -> str:
    if token.lexeme is None:
        return f"{token.line}:{token.column}\t{token.kind.name}"
    return f"{token.line}:{token.column}\t{token.kind.name}\t{token.lexeme}"


def format_tokens(tokens: list[Token]) -> list[str]:
    return [format_token(token) for token in tokens]
