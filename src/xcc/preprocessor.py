import ast
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from xcc.lexer import LexerError, TokenKind, lex_pp
from xcc.options import FrontendOptions, normalize_options

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_INCLUDE_RE = re.compile(r"^(?:\"(?P<quote>[^\"\n]+)\"|<(?P<angle>[^>\n]+)>)$")
_DIRECTIVE_RE = re.compile(r"^\s*#\s*(?P<name>[A-Za-z_]\w*)(?P<body>.*)$")
_DEFINED_PAREN_RE = re.compile(r"\bdefined\s*\(\s*([A-Za-z_]\w*)\s*\)")
_DEFINED_BARE_RE = re.compile(r"\bdefined\s+([A-Za-z_]\w*)")
_PP_INT_RE = re.compile(
    r"^(?:0[xX][0-9A-Fa-f]+|[0-9]+)(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?$"
)
_EXPR_TOKEN_RE = re.compile(
    r"0[xX][0-9A-Fa-f]+(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?"
    r"|[0-9]+(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?"
    r"|[A-Za-z_]\w*"
    r"|\|\||&&|==|!=|<=|>=|<<|>>|[()!~+\-*/%<>&^|]"
)

_PP_UNKNOWN_DIRECTIVE = "XCC-PP-0101"
_PP_INCLUDE_NOT_FOUND = "XCC-PP-0102"
_PP_INVALID_IF_EXPR = "XCC-PP-0103"
_PP_INVALID_DIRECTIVE = "XCC-PP-0104"
_PP_GNU_EXTENSION = "XCC-PP-0105"
_PP_INVALID_MACRO = "XCC-PP-0201"
_PP_INCLUDE_READ_ERROR = "XCC-PP-0301"
_PP_INCLUDE_CYCLE = "XCC-PP-0302"
_PREDEFINED_MACROS = (
    "__STDC__=1",
    "__STDC_HOSTED__=1",
    "__STDC_VERSION__=201112L",
    "__STDC_UTF_16__=1",
    "__STDC_UTF_32__=1",
    "__INT_WIDTH__=32",
    "__LONG_WIDTH__=64",
    "__LONG_LONG_WIDTH__=64",
    "__INTMAX_MAX__=9223372036854775807LL",
    "__LONG_LONG_MAX__=9223372036854775807LL",
    "__UINTMAX_MAX__=18446744073709551615ULL",
    "__LP64__=1",
    "__SIZEOF_POINTER__=8",
    "__SIZEOF_LONG__=8",
    "__SIZE_TYPE__=unsigned long",
    "__PTRDIFF_TYPE__=long",
    "__FILE__=0",
    "__LINE__=0",
)
_PREDEFINED_DYNAMIC_MACROS = frozenset({"__FILE__", "__LINE__"})
_PREDEFINED_STATIC_MACROS = frozenset({"__DATE__", "__TIME__"})
_PREDEFINED_MACRO_NAMES = frozenset(item.split("=", 1)[0] for item in _PREDEFINED_MACROS) | frozenset(
    _PREDEFINED_DYNAMIC_MACROS | _PREDEFINED_STATIC_MACROS
)


@dataclass(frozen=True)
class PreprocessResult:
    source: str
    line_map: tuple[tuple[str, int], ...]
    include_trace: tuple[str, ...]
    macro_table: tuple[str, ...]


@dataclass(frozen=True)
class _ProcessedText:
    source: str
    line_map: tuple[tuple[str, int], ...]


class PreprocessorError(ValueError):
    def __init__(
        self,
        message: str,
        line: int | None = None,
        column: int | None = None,
        *,
        filename: str | None = None,
        code: str = _PP_INVALID_MACRO,
    ) -> None:
        if line is None or column is None:
            super().__init__(message)
        else:
            location = f"{filename}:{line}:{column}" if filename is not None else f"{line}:{column}"
            super().__init__(f"{message} at {location}")
        self.line = line
        self.column = column
        self.filename = filename
        self.code = code


@dataclass(frozen=True)
class _SourceLocation:
    filename: str
    line: int


def _location_tuple(location: _SourceLocation) -> tuple[str, int]:
    return location.filename, location.line


class _LineMapBuilder:
    def __init__(self) -> None:
        self._entries: list[tuple[str, int]] = []

    def append_line(self, text: str, location: _SourceLocation) -> None:
        if text:
            self._entries.append(_location_tuple(location))

    def extend(self, mappings: tuple[tuple[str, int], ...]) -> None:
        self._entries.extend(mappings)

    def build(self) -> tuple[tuple[str, int], ...]:
        return tuple(self._entries)


class _OutputBuilder:
    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._line_map = _LineMapBuilder()

    def append(self, text: str, location: _SourceLocation) -> None:
        self._chunks.append(text)
        self._line_map.append_line(text, location)

    def extend_processed(self, processed: _ProcessedText) -> None:
        self._chunks.append(processed.source)
        self._line_map.extend(processed.line_map)

    def build(self) -> _ProcessedText:
        return _ProcessedText("".join(self._chunks), self._line_map.build())


class _LogicalCursor:
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.line = 1

    def current(self) -> _SourceLocation:
        return _SourceLocation(self.filename, self.line)

    def advance(self, count: int = 1) -> None:
        self.line += count

    def rebase(self, line: int, filename: str | None) -> None:
        self.line = line
        if filename is not None:
            self.filename = filename


class _DirectiveCursor:
    def __init__(self, cursor: _LogicalCursor, count: int) -> None:
        self._locations = tuple(
            _SourceLocation(cursor.filename, cursor.line + index) for index in range(count)
        )

    def line_location(self, index: int) -> _SourceLocation:
        return self._locations[index]

    def first_location(self) -> _SourceLocation:
        return self._locations[0]

    def all_locations(self) -> tuple[_SourceLocation, ...]:
        return self._locations


def _macro_table_line(macro: "_Macro") -> str:
    if macro.parameters is None:
        signature = macro.name
    else:
        params = list(macro.parameters)
        if macro.is_variadic:
            params.append("...")
        signature = f"{macro.name}({','.join(params)})"
    body = _render_macro_tokens(list(macro.replacement))
    return f"{signature}={body}"


def _format_include_trace(
    source: str,
    line: int,
    include_name: str,
    include_path: str,
    is_angled: bool,
) -> str:
    delim_open, delim_close = ("<", ">") if is_angled else ('"', '"')
    return f"{source}:{line}: #include {delim_open}{include_name}{delim_close} -> {include_path}"


def _format_include_reference(include_name: str, is_angled: bool) -> str:
    if is_angled:
        return f"<{include_name}>"
    return f'"{include_name}"'


@dataclass
class _ConditionalFrame:
    parent_active: bool
    active: bool
    branch_taken: bool
    saw_else: bool = False


@dataclass(frozen=True)
class _MacroToken:
    kind: TokenKind
    text: str


@dataclass(frozen=True)
class _Macro:
    name: str
    replacement: tuple[_MacroToken, ...]
    parameters: tuple[str, ...] | None = None
    is_variadic: bool = False


_EMPTY_MACRO_TOKEN = _MacroToken(TokenKind.PUNCTUATOR, "")
_COMMA_MACRO_TOKEN = _MacroToken(TokenKind.PUNCTUATOR, ",")


def preprocess_source(
    source: str,
    *,
    filename: str = "<input>",
    options: FrontendOptions | None = None,
) -> PreprocessResult:
    normalized_options = normalize_options(options)
    processor = _Preprocessor(normalized_options)
    processed = processor.process(source, filename=filename)
    if normalized_options.std == "gnu11":
        stripped = _strip_gnu_asm_extensions(processed.source)
    else:
        _reject_gnu_asm_extensions(processed.source, processed.line_map)
        stripped = processed.source
    return PreprocessResult(
        stripped,
        processed.line_map,
        tuple(processor.include_trace),
        tuple(_macro_table_line(macro) for _, macro in sorted(processor.macro_table.items())),
    )


class _Preprocessor:
    def __init__(self, options: FrontendOptions) -> None:
        self._options = options
        translation_start = datetime.now()
        self._date_literal = _quote_string_literal(_format_date_macro(translation_start))
        self._time_literal = _quote_string_literal(translation_start.strftime("%H:%M:%S"))
        self._macros: dict[str, _Macro] = {}
        for define in _PREDEFINED_MACROS:
            macro = self._parse_cli_define(define)
            self._macros[macro.name] = macro
        self._macros["__DATE__"] = _Macro(
            "__DATE__",
            (_MacroToken(TokenKind.STRING_LITERAL, self._date_literal),),
        )
        self._macros["__TIME__"] = _Macro(
            "__TIME__",
            (_MacroToken(TokenKind.STRING_LITERAL, self._time_literal),),
        )
        self.include_trace: list[str] = []
        self._pragma_once_files: set[str] = set()
        for define in options.defines:
            macro = self._parse_cli_define(define)
            self._macros[macro.name] = macro
        for name in options.undefs:
            if _IDENT_RE.fullmatch(name) is None:
                raise PreprocessorError(f"Invalid macro name in -U: {name}")
            self._macros.pop(name, None)
        self.macro_table = self._macros

    def process(self, source: str, *, filename: str) -> _ProcessedText:
        base_dir = self._source_dir(filename)
        return self._process_text(
            source,
            filename=filename,
            source_id=filename,
            base_dir=base_dir,
            include_stack=(filename,),
        )

    def _source_dir(self, filename: str) -> Path | None:
        if filename in {"<input>", "<stdin>"}:
            return None
        return Path(filename).resolve().parent

    def _process_text(
        self,
        source: str,
        *,
        filename: str,
        source_id: str,
        base_dir: Path | None,
        include_stack: tuple[str, ...],
    ) -> _ProcessedText:
        lines = source.splitlines(keepends=True)
        if not lines:
            return _ProcessedText(source, ())
        out = _OutputBuilder()
        logical_cursor = _LogicalCursor(filename)
        stack: list[_ConditionalFrame] = []
        line_index = 0
        while line_index < len(lines):
            line = lines[line_index]
            parsed = _parse_directive(line)
            if parsed is None:
                location = logical_cursor.current()
                if _is_active(stack):
                    out.append(self._expand_line(line, location), location)
                else:
                    out.append(_blank_line(line), location)
                logical_cursor.advance()
                line_index += 1
                continue
            directive_lines = [line]
            while directive_lines[-1].rstrip().endswith("\\") and line_index + 1 < len(lines):
                line_index += 1
                directive_lines.append(lines[line_index])
            directive_cursor = _DirectiveCursor(logical_cursor, len(directive_lines))
            directive_text = "".join(directive_lines)
            parsed = _parse_directive(directive_text)
            if parsed is None:
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            name, body = parsed
            conditional_result = self._handle_conditional(
                name,
                body,
                directive_cursor.first_location(),
                stack,
                base_dir=base_dir,
            )
            if conditional_result is not None:
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if not _is_active(stack):
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if name == "define":
                self._handle_define(body)
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if name == "undef":
                self._handle_undef(body, directive_cursor.first_location())
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if name in {"include", "include_next"}:
                if name == "include_next" and self._options.std == "c11":
                    raise PreprocessorError(
                        "Unknown preprocessor directive: #include_next",
                        directive_cursor.first_location().line,
                        1,
                        filename=directive_cursor.first_location().filename,
                        code=_PP_UNKNOWN_DIRECTIVE,
                    )
                include_processed = self._handle_include(
                    body,
                    directive_cursor.first_location(),
                    base_dir=base_dir,
                    include_stack=include_stack,
                    include_next=name == "include_next",
                )
                out.extend_processed(include_processed)
                for directive_index, chunk in enumerate(directive_lines[1:], start=1):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if name == "error":
                message = body.strip() or "#error"
                raise PreprocessorError(
                    message,
                    directive_cursor.first_location().line,
                    1,
                    filename=directive_cursor.first_location().filename,
                    code=_PP_INVALID_DIRECTIVE,
                )
            if name == "line":
                line_value, filename_value = self._parse_line_directive(
                    body, directive_cursor.first_location()
                )
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.rebase(line_value, filename_value)
                line_index += 1
                continue
            if name == "pragma":
                if body.strip() == "once":
                    self._pragma_once_files.add(source_id)
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if self._options.std == "c11":
                raise PreprocessorError(
                    f"Unknown preprocessor directive: #{name}",
                    directive_cursor.first_location().line,
                    1,
                    filename=directive_cursor.first_location().filename,
                    code=_PP_UNKNOWN_DIRECTIVE,
                )
            for directive_index, chunk in enumerate(directive_lines):
                out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
            logical_cursor.advance(len(directive_lines))
            line_index += 1
            continue
        if stack:
            location = logical_cursor.current()
            raise PreprocessorError(
                "Unterminated conditional directive",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )
        return out.build()

    def _handle_conditional(
        self,
        name: str,
        body: str,
        location: _SourceLocation,
        stack: list[_ConditionalFrame],
        *,
        base_dir: Path | None,
    ) -> str | None:
        if name not in {"if", "ifdef", "ifndef", "elif", "else", "endif"}:
            return None
        if name == "if":
            parent_active = _is_active(stack)
            condition = parent_active and self._eval_condition(body, location, base_dir=base_dir)
            stack.append(_ConditionalFrame(parent_active, condition, condition))
            return ""
        if name == "ifdef":
            parent_active = _is_active(stack)
            macro_name = self._require_macro_name(body, location)
            condition = parent_active and macro_name in self._macros
            stack.append(_ConditionalFrame(parent_active, condition, condition))
            return ""
        if name == "ifndef":
            parent_active = _is_active(stack)
            macro_name = self._require_macro_name(body, location)
            condition = parent_active and macro_name not in self._macros
            stack.append(_ConditionalFrame(parent_active, condition, condition))
            return ""
        if not stack:
            raise PreprocessorError(
                f"Unexpected #{name}",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )
        frame = stack[-1]
        if name == "elif":
            if frame.saw_else:
                raise PreprocessorError(
                    "#elif after #else",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_DIRECTIVE,
                )
            if not frame.parent_active or frame.branch_taken:
                frame.active = False
                return ""
            condition = self._eval_condition(body, location, base_dir=base_dir)
            frame.active = condition
            frame.branch_taken = frame.branch_taken or condition
            return ""
        if name == "else":
            if frame.saw_else:
                raise PreprocessorError(
                    "Duplicate #else",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_DIRECTIVE,
                )
            frame.saw_else = True
            frame.active = frame.parent_active and not frame.branch_taken
            frame.branch_taken = True
            return ""
        stack.pop()
        return ""

    def _handle_define(self, body: str) -> None:
        macro = self._parse_define(body)
        if macro is None:
            return
        self._macros[macro.name] = macro

    def _parse_define(self, body: str) -> _Macro | None:
        define_body = body.lstrip()
        if not define_body:
            return None
        name_match = _IDENT_RE.match(define_body)
        if name_match is None:
            return None
        name = name_match.group(0)
        tail = define_body[name_match.end() :]
        if tail.startswith("("):
            return self._parse_function_like_define(name, tail)
        replacement = tail.strip()
        return _Macro(name, tuple(_tokenize_macro_replacement(replacement)))

    def _parse_function_like_define(self, name: str, tail: str) -> _Macro | None:
        close_index = tail.find(")")
        if close_index < 0:
            return None
        params_text = tail[1:close_index].strip()
        replacement = tail[close_index + 1 :].strip()
        parsed = _parse_macro_parameters(params_text)
        if parsed is None:
            return None
        parameters, is_variadic = parsed
        return _Macro(
            name,
            tuple(_tokenize_macro_replacement(replacement)),
            parameters=tuple(parameters),
            is_variadic=is_variadic,
        )

    def _expand_line(self, line: str, location: _SourceLocation) -> str:
        if not self._macros:
            return line
        trailing_newline = "\n" if line.endswith("\n") else ""
        text = line[:-1] if trailing_newline else line
        if self._macros.keys() <= _PREDEFINED_MACRO_NAMES and not self._line_needs_macro_expansion(
            text
        ):
            return line
        expanded = self._expand_macro_text(text, location)
        return expanded + trailing_newline

    def _line_needs_macro_expansion(self, text: str) -> bool:
        tokens = _tokenize_macro_text(text)
        if tokens is None:
            return False
        return any(token.kind == TokenKind.IDENT and token.text in self._macros for token in tokens)

    def _expand_macro_text(self, text: str, location: _SourceLocation) -> str:
        tokens = _tokenize_macro_text(text)
        if tokens is None:
            return text
        expanded = _expand_macro_tokens(tokens, self._macros, self._options.std, location)
        return _render_macro_tokens(expanded)

    def _handle_undef(self, body: str, location: _SourceLocation) -> None:
        macro_name = self._require_macro_name(body, location)
        self._macros.pop(macro_name, None)

    def _handle_include(
        self,
        body: str,
        location: _SourceLocation,
        *,
        base_dir: Path | None,
        include_stack: tuple[str, ...],
        include_next: bool = False,
    ) -> _ProcessedText:
        include_name, is_angled = self._parse_include_target(body, location)
        include_path = self._resolve_include(
            include_name,
            is_angled=is_angled,
            base_dir=base_dir,
            include_next_from=base_dir if include_next else None,
        )
        if include_path is None:
            raise PreprocessorError(
                f"Include not found: {_format_include_reference(include_name, is_angled)}",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_NOT_FOUND,
            )
        include_path_text = str(include_path)
        if include_path_text in self._pragma_once_files:
            return _ProcessedText("", ())
        self.include_trace.append(
            _format_include_trace(
                include_stack[-1],
                location.line,
                include_name,
                include_path_text,
                is_angled,
            )
        )
        if include_path_text in include_stack:
            raise PreprocessorError(
                "Circular include detected",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_CYCLE,
            )
        try:
            include_source = include_path.read_text(encoding="utf-8")
        except OSError as error:
            raise PreprocessorError(
                f"Unable to read include: {include_name}: {error}",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_READ_ERROR,
            ) from error
        return self._process_text(
            include_source,
            filename=include_path_text,
            source_id=include_path_text,
            base_dir=include_path.parent,
            include_stack=(*include_stack, include_path_text),
        )

    def _parse_include_target(self, body: str, location: _SourceLocation) -> tuple[str, bool]:
        return self._parse_header_name_operand(body.strip(), location)

    def _parse_header_name_operand(
        self,
        operand: str,
        location: _SourceLocation,
    ) -> tuple[str, bool]:
        direct = _INCLUDE_RE.match(operand)
        if direct is not None:
            quoted_name = direct.group("quote")
            angle_name = direct.group("angle")
            include_name = quoted_name if quoted_name is not None else angle_name
            assert include_name is not None
            return include_name, angle_name is not None

        expanded = self._expand_macro_text(operand, location).strip()
        tokens = _tokenize_macro_text(expanded)
        if tokens is None:
            raise PreprocessorError(
                "Invalid #include directive",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )

        if len(tokens) == 1 and tokens[0].kind == TokenKind.STRING_LITERAL:
            literal = tokens[0].text
            return literal[1:-1], False

        if (
            len(tokens) >= 3
            and tokens[0].kind == TokenKind.PUNCTUATOR
            and tokens[-1].kind == TokenKind.PUNCTUATOR
            and tokens[0].text == "<"
            and tokens[-1].text == ">"
        ):
            return "".join(token.text for token in tokens[1:-1]), True

        raise PreprocessorError(
            "Invalid #include directive",
            location.line,
            1,
            filename=location.filename,
            code=_PP_INVALID_DIRECTIVE,
        )

    def _resolve_include(
        self,
        include_name: str,
        *,
        is_angled: bool,
        base_dir: Path | None,
        include_next_from: Path | None = None,
    ) -> Path | None:
        search_roots: list[Path] = []
        if not is_angled and base_dir is not None:
            search_roots.append(base_dir)
        search_roots.extend(Path(path) for path in self._options.include_dirs)
        search_roots.extend(Path(path) for path in self._options.system_include_dirs)

        start_index = 0
        if include_next_from is not None:
            include_next_from_resolved = include_next_from.resolve()
            for index, root in enumerate(search_roots):
                if root.resolve() == include_next_from_resolved:
                    start_index = index + 1
                    break

        for root in search_roots[start_index:]:
            candidate = root / include_name
            if candidate.is_file():
                return candidate.resolve()
        return None

    def _parse_cli_define(self, define: str) -> _Macro:
        if "=" in define:
            name, replacement = define.split("=", 1)
        else:
            name, replacement = define, "1"
        if _IDENT_RE.fullmatch(name) is None:
            raise PreprocessorError(f"Invalid macro definition: {define}", code=_PP_INVALID_MACRO)
        return _Macro(name, tuple(_tokenize_macro_replacement(replacement.strip())))

    def _require_macro_name(self, body: str, location: _SourceLocation) -> str:
        macro_name = body.strip()
        if _IDENT_RE.fullmatch(macro_name) is None:
            raise PreprocessorError(
                "Expected macro name",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )
        return macro_name

    def _eval_condition(
        self,
        body: str,
        location: _SourceLocation,
        *,
        base_dir: Path | None,
    ) -> bool:
        def replace_defined(match: re.Match[str]) -> str:
            macro_name = match.group(1)
            return "1" if macro_name in self._macros else "0"

        condition = _strip_condition_comments(body)
        expanded = _DEFINED_PAREN_RE.sub(replace_defined, condition)
        expanded = _DEFINED_BARE_RE.sub(replace_defined, expanded)
        try:
            expanded = self._replace_has_include_operators(
                expanded,
                location,
                base_dir=base_dir,
            )
            expanded = self._expand_macro_text(expanded, location)
            py_expr = _translate_expr_to_python(expanded)
            return bool(_safe_eval_pp_expr(py_expr))
        except PreprocessorError:
            raise
        except ValueError as error:
            raise PreprocessorError(
                "Invalid #if expression",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_IF_EXPR,
            ) from error

    def _replace_has_include_operators(
        self,
        expr: str,
        location: _SourceLocation,
        *,
        base_dir: Path | None,
    ) -> str:
        # Handle __has_include(<...>) and __has_include("...") before expression tokenization.
        marker = "__has_include"
        chunks: list[str] = []
        index = 0
        while True:
            found = expr.find(marker, index)
            if found < 0:
                chunks.append(expr[index:])
                return "".join(chunks)
            prev = expr[found - 1] if found > 0 else ""
            next_pos = found + len(marker)
            next_char = expr[next_pos] if next_pos < len(expr) else ""
            if (prev and (prev.isalnum() or prev == "_")) or (
                next_char and (next_char.isalnum() or next_char == "_")
            ):
                chunks.append(expr[index : found + len(marker)])
                index = found + len(marker)
                continue
            chunks.append(expr[index:found])
            cursor = next_pos
            while cursor < len(expr) and expr[cursor].isspace():
                cursor += 1
            if cursor >= len(expr) or expr[cursor] != "(":
                raise PreprocessorError(
                    "Invalid __has_include expression",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            close_paren = self._find_matching_has_include_close(expr, cursor)
            if close_paren < 0:
                raise PreprocessorError(
                    "Invalid __has_include expression",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            operand = expr[cursor + 1 : close_paren].strip()
            if not operand:
                raise PreprocessorError(
                    "Invalid __has_include expression",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            try:
                include_name, is_angled = self._parse_header_name_operand(operand, location)
            except PreprocessorError as error:
                raise PreprocessorError(
                    "Invalid __has_include expression",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                ) from error
            cursor = close_paren + 1
            present = self._resolve_include(include_name, is_angled=is_angled, base_dir=base_dir)
            chunks.append("1" if present is not None else "0")
            index = cursor

    def _find_matching_has_include_close(self, expr: str, open_paren: int) -> int:
        depth = 0
        index = open_paren
        while index < len(expr):
            char = expr[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
            index += 1
        return -1

    def _parse_line_directive(
        self,
        body: str,
        location: _SourceLocation,
    ) -> tuple[int, str | None]:
        expanded = self._expand_macro_text(body, location).strip()
        match = re.match(r'^(\d+)(?:\s+("(?:[^"\n]|\\.)*"))?\s*$', expanded)
        if match is None:
            raise PreprocessorError(
                "Invalid #line directive",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )

        line = int(match.group(1))
        if line <= 0:
            raise PreprocessorError(
                "Invalid #line directive",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )

        filename_literal = match.group(2)
        if filename_literal is None:
            return line, None
        try:
            mapped_filename = cast(str, ast.literal_eval(filename_literal))
        except (SyntaxError, ValueError) as error:
            raise PreprocessorError(
                "Invalid #line directive",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            ) from error
        return line, mapped_filename


def _parse_macro_parameters(text: str) -> tuple[list[str], bool] | None:
    if not text:
        return [], False
    items = [item.strip() for item in text.split(",")]
    params: list[str] = []
    is_variadic = False
    for index, item in enumerate(items):
        if item == "...":
            if index != len(items) - 1:
                return None
            is_variadic = True
            break
        if _IDENT_RE.fullmatch(item) is None or item in params:
            return None
        params.append(item)
    return params, is_variadic


def _tokenize_macro_replacement(text: str) -> list[_MacroToken]:
    if not text:
        return []
    tokens = _tokenize_macro_text(text)
    if tokens is None:
        return [_MacroToken(TokenKind.IDENT, text)]
    return tokens


def _tokenize_macro_text(text: str) -> list[_MacroToken] | None:
    if not text:
        return []
    try:
        tokens = lex_pp(text)
    except LexerError:
        return None
    out: list[_MacroToken] = []
    for token in tokens:
        if token.kind == TokenKind.EOF:
            continue
        lexeme = token.lexeme
        assert lexeme is not None
        out.append(_MacroToken(token.kind, lexeme))
    return out


def _render_macro_tokens(tokens: list[_MacroToken]) -> str:
    return " ".join(token.text for token in tokens if token.text)


def _expand_macro_tokens(
    tokens: list[_MacroToken],
    macros: dict[str, _Macro],
    std: str,
    location: _SourceLocation,
    disabled: frozenset[str] = frozenset(),
) -> list[_MacroToken]:
    expanded: list[_MacroToken] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind != TokenKind.IDENT:
            expanded.append(token)
            index += 1
            continue
        if token.text in _PREDEFINED_DYNAMIC_MACROS and token.text in macros:
            if token.text == "__LINE__":
                expanded.append(_MacroToken(TokenKind.INT_CONST, str(location.line)))
            else:
                expanded.append(
                    _MacroToken(TokenKind.STRING_LITERAL, _quote_string_literal(location.filename))
                )
            index += 1
            continue
        macro = macros.get(token.text)
        if macro is None or macro.name in disabled:
            expanded.append(token)
            index += 1
            continue
        next_disabled = frozenset((*disabled, macro.name))
        if macro.parameters is None:
            replacement = _expand_macro_tokens(
                list(macro.replacement),
                macros,
                std,
                location,
                disabled=next_disabled,
            )
            expanded.extend(replacement)
            index += 1
            continue
        parsed = _parse_macro_invocation(tokens, index + 1, location)
        if parsed is None:
            expanded.append(token)
            index += 1
            continue
        args, next_index = parsed
        replacement = _expand_function_like_macro(
            macro,
            args,
            macros,
            std=std,
            location=location,
            disabled=next_disabled,
        )
        replacement = _expand_macro_tokens(
            replacement,
            macros,
            std,
            location,
            disabled=next_disabled,
        )
        expanded.extend(replacement)
        index = next_index
    return expanded


def _parse_macro_invocation(
    tokens: list[_MacroToken],
    index: int,
    location: _SourceLocation,
) -> tuple[list[list[_MacroToken]], int] | None:
    if index >= len(tokens) or tokens[index].text != "(":
        return None
    if index + 1 < len(tokens) and tokens[index + 1].text == ")":
        return [], index + 2
    args: list[list[_MacroToken]] = []
    current: list[_MacroToken] = []
    depth = 1
    index += 1
    while index < len(tokens):
        token = tokens[index]
        if token.text == "(":
            depth += 1
            current.append(token)
        elif token.text == ")":
            depth -= 1
            if depth == 0:
                args.append(current)
                return args, index + 1
            current.append(token)
        elif token.text == "," and depth == 1:
            args.append(current)
            current = []
        else:
            current.append(token)
        index += 1
    raise PreprocessorError(
        "Unterminated macro invocation",
        location.line,
        1,
        filename=location.filename,
        code=_PP_INVALID_MACRO,
    )


def _expand_function_like_macro(
    macro: _Macro,
    args: list[list[_MacroToken]],
    macros: dict[str, _Macro],
    *,
    std: str,
    location: _SourceLocation,
    disabled: frozenset[str],
) -> list[_MacroToken]:
    assert macro.parameters is not None
    expected = len(macro.parameters)
    if macro.is_variadic:
        if len(args) < expected:
            raise PreprocessorError(
                "Insufficient macro arguments",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_MACRO,
            )
    elif len(args) != expected:
        raise PreprocessorError(
            "Macro argument count mismatch",
            location.line,
            1,
            filename=location.filename,
            code=_PP_INVALID_MACRO,
        )
    raw_named_args = {name: args[index] for index, name in enumerate(macro.parameters)}
    expanded_named_args = {
        name: _expand_macro_tokens(arg, macros, std, location, disabled=disabled)
        for name, arg in raw_named_args.items()
    }
    raw_var_args: list[_MacroToken] = []
    expanded_var_args: list[_MacroToken] = []
    if macro.is_variadic:
        variadic_args = args[expected:]
        raw_var_args = _join_macro_arguments(variadic_args)
        expanded_var_args = _join_macro_arguments(
            [
                _expand_macro_tokens(arg, macros, std, location, disabled=disabled)
                for arg in variadic_args
            ]
        )
    pieces: list[_MacroToken] = []
    replacement = list(macro.replacement)
    index = 0
    while index < len(replacement):
        token = replacement[index]
        token_text = token.text
        if token_text == "#" and index + 1 < len(replacement):
            target = replacement[index + 1].text
            target_tokens = _lookup_macro_argument(
                target,
                raw_named_args,
                expanded_named_args,
                raw_var_args,
                expanded_var_args,
                macro.is_variadic,
                want_raw=True,
            )
            if target_tokens is not None:
                pieces.append(
                    _MacroToken(TokenKind.STRING_LITERAL, _stringize_tokens(target_tokens))
                )
                index += 2
                continue
        is_paste_context = (
            index > 0
            and replacement[index - 1].text == "##"
            or index + 1 < len(replacement)
            and replacement[index + 1].text == "##"
        )
        target_tokens = _lookup_macro_argument(
            token_text,
            raw_named_args,
            expanded_named_args,
            raw_var_args,
            expanded_var_args,
            macro.is_variadic,
            want_raw=is_paste_context,
        )
        if target_tokens is not None:
            if target_tokens:
                pieces.extend(target_tokens)
            elif is_paste_context:
                pieces.append(_EMPTY_MACRO_TOKEN)
            index += 1
            continue
        pieces.append(token)
        index += 1
    return _apply_token_paste(pieces, std=std, location=location)


def _lookup_macro_argument(
    name: str,
    raw_named_args: dict[str, list[_MacroToken]],
    expanded_named_args: dict[str, list[_MacroToken]],
    raw_var_args: list[_MacroToken],
    expanded_var_args: list[_MacroToken],
    is_variadic: bool,
    *,
    want_raw: bool,
) -> list[_MacroToken] | None:
    if name in raw_named_args:
        return raw_named_args[name] if want_raw else expanded_named_args[name]
    if is_variadic and name == "__VA_ARGS__":
        return raw_var_args if want_raw else expanded_var_args
    return None


def _join_macro_arguments(args: list[list[_MacroToken]]) -> list[_MacroToken]:
    if not args:
        return []
    out: list[_MacroToken] = []
    for index, arg in enumerate(args):
        if index > 0:
            out.append(_COMMA_MACRO_TOKEN)
        out.extend(arg)
    return out


def _stringize_tokens(tokens: list[_MacroToken]) -> str:
    text = " ".join(token.text for token in tokens if token.text)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _apply_token_paste(
    tokens: list[_MacroToken], *, std: str, location: _SourceLocation
) -> list[_MacroToken]:
    out = list(tokens)
    index = 0
    while index < len(out):
        if out[index].text != "##":
            index += 1
            continue
        if index == 0 or index + 1 >= len(out):
            raise PreprocessorError(
                "Invalid token paste",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_MACRO,
            )
        left = out[index - 1]
        right = out[index + 1]
        pasted = _paste_token_pair(left, right, std=std, location=location)
        out[index - 1 : index + 2] = pasted
        index -= 1
    return [token for token in out if token.text]


def _paste_token_pair(
    left: _MacroToken,
    right: _MacroToken,
    *,
    std: str,
    location: _SourceLocation | None = None,
    line_no: int | None = None,
) -> list[_MacroToken]:
    actual_location = location
    if actual_location is None:
        actual_location = _SourceLocation("<input>", 1 if line_no is None else line_no)
    left_text = left.text
    right_text = right.text
    if not left_text and not right_text:
        return []
    if not left_text:
        return [right]
    if not right_text:
        if std == "gnu11" and left_text == ",":
            return []
        return [left]
    pasted = _tokenize_macro_text(left_text + right_text)
    if pasted is None or len(pasted) != 1:
        raise PreprocessorError(
            "Invalid token paste result",
            actual_location.line,
            1,
            filename=actual_location.filename,
            code=_PP_INVALID_MACRO,
        )
    return pasted


def _translate_expr_to_python(expr: str) -> str:
    tokens = _tokenize_expr(expr)
    tokens = _collapse_function_invocations(tokens)
    mapped: list[str] = []
    for token in tokens:
        value = _parse_pp_integer_literal(token)
        if value is not None:
            if _is_unsigned_pp_integer(token):
                mapped.append(f"u64({value})")
            else:
                mapped.append(str(value))
            continue
        if _IDENT_RE.fullmatch(token):
            mapped.append("0")
            continue
        if token == "&&":
            mapped.append("and")
            continue
        if token == "||":
            mapped.append("or")
            continue
        if token == "!":
            mapped.append("not")
            continue
        if token == "/":
            mapped.append("//")
            continue
        mapped.append(token)
    return " ".join(mapped)


def _collapse_function_invocations(tokens: list[str]) -> list[str]:
    collapsed: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _IDENT_RE.fullmatch(token) and index + 1 < len(tokens) and tokens[index + 1] == "(":
            depth = 0
            index += 1
            while index < len(tokens):
                next_token = tokens[index]
                if next_token == "(":
                    depth += 1
                elif next_token == ")":
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
            if depth != 0:
                raise ValueError("Invalid token")
            collapsed.append("0")
            continue
        collapsed.append(token)
        index += 1
    return collapsed


def _parse_pp_integer_literal(token: str) -> int | None:
    if _PP_INT_RE.fullmatch(token) is None:
        return None
    index = len(token)
    while index > 0 and token[index - 1] in "uUlL":
        index -= 1
    digits = token[:index]
    if digits.startswith(("0x", "0X")):
        return int(digits, 16)
    if digits.startswith("0") and len(digits) > 1:
        if any(ch not in "01234567" for ch in digits):
            return None
        return int(digits, 8)
    return int(digits, 10)


def _is_unsigned_pp_integer(token: str) -> bool:
    if _PP_INT_RE.fullmatch(token) is None:
        return False
    return any(ch in "uU" for ch in token)


def _strip_condition_comments(expr: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", " ", expr)
    if "//" in without_block:
        return without_block.split("//", 1)[0]
    return without_block


def _tokenize_expr(expr: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(expr):
        if expr[index].isspace():
            index += 1
            continue
        match = _EXPR_TOKEN_RE.match(expr, index)
        if match is None:
            raise ValueError("Invalid token")
        tokens.append(match.group(0))
        index = match.end()
    return tokens


def _safe_eval_int_expr(expr: str) -> int:
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError as error:
        raise ValueError("Invalid expression") from error
    return _eval_node(node)


_UINT64_MASK = (1 << 64) - 1


@dataclass(frozen=True)
class _PPValue:
    value: int
    is_unsigned: bool = False

    def as_unsigned(self) -> int:
        return self.value & _UINT64_MASK

    def normalize(self) -> "_PPValue":
        if not self.is_unsigned:
            return self
        return _PPValue(self.value & _UINT64_MASK, True)


def _safe_eval_pp_expr(expr: str) -> int:
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError as error:
        raise ValueError("Invalid expression") from error
    try:
        return _eval_pp_node(node).value
    except ZeroDivisionError as error:
        raise ValueError("Invalid expression") from error


def _eval_pp_node(node: ast.AST) -> _PPValue:
    if isinstance(node, ast.Expression):
        return _eval_pp_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return _PPValue(int(node.value))
        if isinstance(node.value, int):
            return _PPValue(node.value)
        raise ValueError(f"Unsupported preprocessor literal type: {type(node.value).__name__}")
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "u64"
            and len(node.args) == 1
            and not node.keywords
        ):
            value = _eval_pp_node(node.args[0])
            return _PPValue(value.as_unsigned(), True)
        raise ValueError("Unsupported preprocessor call expression")
    if isinstance(node, ast.UnaryOp):
        operand = _eval_pp_node(node.operand)
        if isinstance(node.op, ast.Not):
            return _PPValue(0 if operand.value else 1)
        if isinstance(node.op, ast.UAdd):
            return operand.normalize()
        if isinstance(node.op, ast.USub):
            value = -operand.value
            result = _PPValue(value, operand.is_unsigned)
            return result.normalize()
        if isinstance(node.op, ast.Invert):
            value = ~operand.value
            result = _PPValue(value, operand.is_unsigned)
            return result.normalize()
        raise ValueError(f"Unsupported preprocessor unary operator: {type(node.op).__name__}")
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if _eval_pp_node(value).value == 0:
                    return _PPValue(0)
            return _PPValue(1)
        if isinstance(node.op, ast.Or):
            for value in node.values:
                if _eval_pp_node(value).value != 0:
                    return _PPValue(1)
            return _PPValue(0)
        raise ValueError(f"Unsupported preprocessor boolean operator: {type(node.op).__name__}")
    if isinstance(node, ast.BinOp):
        left = _eval_pp_node(node.left)
        right = _eval_pp_node(node.right)
        is_unsigned = left.is_unsigned or right.is_unsigned
        left_value = left.as_unsigned() if is_unsigned else left.value
        right_value = right.as_unsigned() if is_unsigned else right.value
        if isinstance(node.op, ast.Add):
            value = left_value + right_value
        elif isinstance(node.op, ast.Sub):
            value = left_value - right_value
        elif isinstance(node.op, ast.Mult):
            value = left_value * right_value
        elif isinstance(node.op, ast.FloorDiv):
            value = left_value // right_value
        elif isinstance(node.op, ast.Mod):
            value = left_value % right_value
        elif isinstance(node.op, ast.LShift):
            value = left_value << right_value
        elif isinstance(node.op, ast.RShift):
            value = left_value >> right_value
        elif isinstance(node.op, ast.BitOr):
            value = left_value | right_value
        elif isinstance(node.op, ast.BitAnd):
            value = left_value & right_value
        elif isinstance(node.op, ast.BitXor):
            value = left_value ^ right_value
        else:
            raise ValueError(f"Unsupported preprocessor binary operator: {type(node.op).__name__}")
        result = _PPValue(value, is_unsigned)
        return result.normalize()
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise ValueError(
                "Unsupported preprocessor comparison shape: "
                f"expected 1 operator, got {len(node.ops)}"
            )
        if len(node.comparators) != 1:
            raise ValueError(
                "Unsupported preprocessor comparison shape: "
                f"expected 1 comparator, got {len(node.comparators)}"
            )
        left = _eval_pp_node(node.left)
        right = _eval_pp_node(node.comparators[0])
        is_unsigned = left.is_unsigned or right.is_unsigned
        left_value = left.as_unsigned() if is_unsigned else left.value
        right_value = right.as_unsigned() if is_unsigned else right.value
        op = node.ops[0]
        if isinstance(op, ast.Eq):
            return _PPValue(int(left_value == right_value))
        if isinstance(op, ast.NotEq):
            return _PPValue(int(left_value != right_value))
        if isinstance(op, ast.Lt):
            return _PPValue(int(left_value < right_value))
        if isinstance(op, ast.LtE):
            return _PPValue(int(left_value <= right_value))
        if isinstance(op, ast.Gt):
            return _PPValue(int(left_value > right_value))
        if isinstance(op, ast.GtE):
            return _PPValue(int(left_value >= right_value))
        raise ValueError(f"Unsupported preprocessor comparison operator: {type(op).__name__}")
    raise ValueError(f"Unsupported preprocessor expression node: {type(node).__name__}")


def _eval_node(node: ast.AST) -> int:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return int(node.value)
        if isinstance(node.value, int):
            return node.value
        raise ValueError(
            f"Unsupported integer-expression literal type: {type(node.value).__name__}"
        )
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand)
        if isinstance(node.op, ast.Not):
            return 0 if value else 1
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.Invert):
            return ~value
        raise ValueError(f"Unsupported integer-expression unary operator: {type(node.op).__name__}")
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if _eval_node(value) == 0:
                    return 0
            return 1
        if isinstance(node.op, ast.Or):
            for value in node.values:
                if _eval_node(value) != 0:
                    return 1
            return 0
        raise ValueError(
            f"Unsupported integer-expression boolean operator: {type(node.op).__name__}"
        )
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.LShift):
            return left << right
        if isinstance(node.op, ast.RShift):
            return left >> right
        if isinstance(node.op, ast.BitOr):
            return left | right
        if isinstance(node.op, ast.BitAnd):
            return left & right
        if isinstance(node.op, ast.BitXor):
            return left ^ right
        raise ValueError(
            f"Unsupported integer-expression binary operator: {type(node.op).__name__}"
        )
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise ValueError(
                "Unsupported integer-expression comparison shape: "
                f"expected 1 operator, got {len(node.ops)}"
            )
        if len(node.comparators) != 1:
            raise ValueError(
                "Unsupported integer-expression comparison shape: "
                f"expected 1 comparator, got {len(node.comparators)}"
            )
        left = _eval_node(node.left)
        right = _eval_node(node.comparators[0])
        op = node.ops[0]
        if isinstance(op, ast.Eq):
            return int(left == right)
        if isinstance(op, ast.NotEq):
            return int(left != right)
        if isinstance(op, ast.Lt):
            return int(left < right)
        if isinstance(op, ast.LtE):
            return int(left <= right)
        if isinstance(op, ast.Gt):
            return int(left > right)
        if isinstance(op, ast.GtE):
            return int(left >= right)
        raise ValueError(f"Unsupported integer-expression comparison operator: {type(op).__name__}")
    raise ValueError(f"Unsupported integer-expression node: {type(node).__name__}")


def _parse_directive(line: str) -> tuple[str, str] | None:
    if not line.lstrip().startswith("#"):
        return None
    match = _DIRECTIVE_RE.match(line)
    if match is None:
        return None
    return match.group("name"), match.group("body")


def _blank_line(line: str) -> str:
    return "\n" if line.endswith("\n") else ""


def _is_active(stack: list[_ConditionalFrame]) -> bool:
    return all(frame.active for frame in stack)


def _expand_object_like_macros(line: str, macros: dict[str, str]) -> str:
    if not macros:
        return line
    names = cast(list[str], sorted(macros, key=len, reverse=True))
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in names) + r")\b")
    return pattern.sub(lambda match: macros[match.group(0)], line)


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


def _quote_string_literal(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _format_date_macro(now: datetime) -> str:
    month = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )[now.month - 1]
    return f"{month} {now.day:2d} {now.year:04d}"


def _reject_gnu_asm_extensions(
    source: str,
    line_map: tuple[tuple[str, int], ...],
) -> None:
    for line_number, line in enumerate(source.splitlines(), start=1):
        if _ASM_PREFIX_RE.match(line) or _ASM_LABEL_RE.search(line):
            mapped_filename, mapped_line = (
                line_map[line_number - 1]
                if 1 <= line_number <= len(line_map)
                else ("<input>", line_number)
            )
            raise PreprocessorError(
                "GNU asm extension is not allowed in c11",
                mapped_line,
                1,
                filename=mapped_filename,
                code=_PP_GNU_EXTENSION,
            )
