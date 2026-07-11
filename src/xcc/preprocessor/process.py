from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from xcc.options import FrontendOptions

from . import (
    PreprocessorError,
    _DirectiveCursor,
    _LogicalCursor,
    _OutputBuilder,
    _ProcessedText,
    _SourceLocation,
)
from .conditionals import _ConditionalFrame, _is_active
from .pragmas import _validate_pragma
from .text import _blank_line, _parse_directive, _scan_block_comment_state

_PP_UNKNOWN_DIRECTIVE = "XCC-PP-0101"
_PP_INVALID_DIRECTIVE = "XCC-PP-0104"
_PP_UNTERMINATED_MACRO = "XCC-PP-0202"


class _ProcessTextPreprocessor(Protocol):
    _options: FrontendOptions
    _pragma_once_files: set[str]

    def _expand_line(self, line: str, location: _SourceLocation) -> str: ...

    def _should_collect_function_macro_continuation(
        self,
        text: str,
        next_line: str,
    ) -> bool: ...

    def _handle_conditional(
        self,
        name: str,
        body: str,
        location: _SourceLocation,
        stack: list[_ConditionalFrame],
        *,
        base_dir: Path | None,
    ) -> str | None: ...

    def _handle_conditional_for_process(
        self,
        name: str,
        body: str,
        location: _SourceLocation,
        stack: list[_ConditionalFrame],
        *,
        base_dir: Path | None,
    ) -> tuple[str | None, list[_ConditionalFrame]]: ...

    def _handle_define(self, body: str) -> None: ...

    def _handle_undef(self, body: str, location: _SourceLocation) -> None: ...

    def _handle_include(
        self,
        body: str,
        location: _SourceLocation,
        *,
        base_dir: Path | None,
        include_stack: tuple[str, ...],
        include_next: bool = False,
        is_import: bool = False,
    ) -> _ProcessedText: ...

    def _parse_line_directive(
        self,
        body: str,
        location: _SourceLocation,
    ) -> tuple[int, str | None]: ...

    def _handle_embed(
        self,
        body: str,
        location: _SourceLocation,
        *,
        base_dir: Path | None,
    ) -> _ProcessedText: ...

    def _handle_pack_pragma(
        self,
        body: str,
        location: _SourceLocation | None = None,
    ) -> None: ...


def _strip_block_comments(text: str) -> str:
    """Strip /* block comments */ and // line comments from text.

    Returns text with comment content replaced by spaces so that
    column offsets are preserved for diagnostics.  If a block comment
    is still open at end-of-text the original text is returned
    unchanged --- the closing ``*/`` is in a subsequent line that
    hasn't been collected yet.

    String literals and character constants are tracked so that
    ``//`` and ``/*`` inside them are not treated as comment starts.
    """
    result: list[str] = []
    in_block = False
    in_string: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string is not None:
            if ch == "\\" and i + 1 < len(text):
                result.append(ch)
                result.append(text[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            result.append(ch)
            i += 1
            continue
        if in_block:
            if ch == "*" and i + 1 < len(text) and text[i + 1] == "/":
                in_block = False
                result.append("  ")
                i += 2
                continue
            result.append(" " if ch != "\n" else ch)
            i += 1
            continue
        if ch in {'"', "'"}:
            in_string = ch
            result.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "/":
                while i < len(text) and text[i] != "\n":
                    result.append(" ")
                    i += 1
                if i < len(text):
                    result.append(text[i])
                    i += 1
                continue
            if nxt == "*":
                in_block = True
                result.append("  ")
                i += 2
                continue
        result.append(ch)
        i += 1
    if in_block:
        return text
    return "".join(result)


def _has_unclosed_block_comment(text: str) -> bool:
    in_block = False
    for line in text.splitlines(keepends=True):
        in_block = _scan_block_comment_state(line, in_block)
    return in_block


def process_text(
    preprocessor: _ProcessTextPreprocessor,
    source: str,
    *,
    filename: str,
    source_id: str,
    base_dir: Path | None,
    include_stack: tuple[str, ...],
    parse_directive: Callable[[str], tuple[str, str] | None] = _parse_directive,
) -> _ProcessedText:
    self = preprocessor
    lines = source.splitlines(keepends=True)
    if not lines:
        return _ProcessedText(source, ())
    out = _OutputBuilder()
    logical_cursor = _LogicalCursor(filename, include_level=max(len(include_stack) - 1, 0))
    stack: list[_ConditionalFrame] = []
    in_block_comment = False
    comment_from_directive = False
    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        parsed = None if in_block_comment else parse_directive(line)
        if parsed is None:
            location = logical_cursor.current()
            if _is_active(stack) and not in_block_comment:
                all_lines = [line]
                text_parts = [line]
                inner_stack: list[_ConditionalFrame] = []
                expanded = None
                while expanded is None:
                    # Phase 2: splice backslash-newline continuations before
                    # each macro expansion attempt, so that string literals
                    # spanning physical lines are joined correctly.
                    while line_index + len(all_lines) < len(lines):
                        joined_check = "".join(text_parts)
                        if not joined_check.rstrip().endswith("\\"):
                            break
                        next_line = lines[line_index + len(all_lines)]
                        # Delete the backslash-newline: remove \ from the
                        # current last part and merge with the next line.
                        # The output will show both lines concatenated,
                        # and continuation lines are blanked separately.
                        text_parts[-1] = text_parts[-1].rstrip()[:-1] + next_line
                        all_lines.append(next_line)
                    joined = "".join(text_parts)
                    if len(all_lines) > 1:
                        if _has_unclosed_block_comment(joined):
                            next_idx = line_index + len(all_lines)
                            if next_idx >= len(lines):
                                raise PreprocessorError(
                                    "Unterminated macro invocation",
                                    location.line,
                                    1,
                                    filename=location.filename,
                                    code=_PP_UNTERMINATED_MACRO,
                                )
                            next_line = lines[next_idx]
                            text_parts.append(next_line)
                            all_lines.append(next_line)
                            continue
                        joined = _strip_block_comments(joined)
                    next_idx = line_index + len(all_lines)
                    if next_idx < len(lines) and self._should_collect_function_macro_continuation(
                        joined,
                        lines[next_idx],
                    ):
                        next_line = lines[next_idx]
                        text_parts.append(next_line)
                        all_lines.append(next_line)
                        continue
                    try:
                        expanded = self._expand_line(joined, location)
                    except PreprocessorError as exc:
                        if exc.code != _PP_UNTERMINATED_MACRO:
                            raise
                        next_idx = line_index + len(all_lines)
                        if next_idx >= len(lines):
                            raise
                        next_line = lines[next_idx]
                        # Collect \ continuation lines for directives inside
                        # macro bodies, matching the top-level directive handling.
                        inner_lines = [next_line]
                        while inner_lines[-1].rstrip().endswith("\\") and next_idx + len(
                            inner_lines
                        ) < len(lines):
                            inner_lines.append(lines[next_idx + len(inner_lines)])
                        inner_text = "".join(inner_lines).replace("\\\n", "")
                        inner_parsed = parse_directive(inner_text)
                        if inner_parsed is not None:
                            inner_name, inner_body = inner_parsed
                            inner_loc = _SourceLocation(
                                logical_cursor.filename,
                                logical_cursor.line + len(all_lines),
                                logical_cursor.include_level,
                            )
                            result, inner_stack = self._handle_conditional_for_process(
                                inner_name,
                                inner_body,
                                inner_loc,
                                inner_stack,
                                base_dir=base_dir,
                            )
                            if result is None:
                                if _is_active(inner_stack):
                                    raise
                                for il in inner_lines:
                                    all_lines.append(il)
                                continue
                            for il in inner_lines:
                                all_lines.append(il)
                        elif _is_active(inner_stack):
                            text_parts.append(next_line)
                            all_lines.append(next_line)
                        else:
                            all_lines.append(next_line)
                out.append(expanded, location)
                for i in range(1, len(all_lines)):
                    in_block_comment, comment_from_directive = _update_comment_state(
                        in_block_comment, comment_from_directive, line=all_lines[i - 1]
                    )
                    logical_cursor.advance()
                    line_index += 1
                    out.append(_blank_line(all_lines[i]), logical_cursor.current())
                logical_cursor.advance()
                in_block_comment, comment_from_directive = _update_comment_state(
                    in_block_comment, comment_from_directive, line=all_lines[-1]
                )
                line_index += 1
                continue
            if _is_active(stack) and not (in_block_comment and comment_from_directive):
                out.append(line, location)
            else:
                out.append(_blank_line(line), location)
            logical_cursor.advance()
            in_block_comment, comment_from_directive = _update_comment_state(
                in_block_comment, comment_from_directive, line=line
            )
            line_index += 1
            continue
        directive_lines = [line]
        while _directive_lines_continue(directive_lines) and line_index + 1 < len(lines):
            line_index += 1
            directive_lines.append(lines[line_index])
        directive_cursor = _DirectiveCursor(logical_cursor, len(directive_lines))
        directive_text = "".join(directive_lines).replace("\\\n", "")
        parsed = parse_directive(directive_text)
        if parsed is None:
            for directive_index, chunk in enumerate(directive_lines):
                out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
            logical_cursor.advance(len(directive_lines))
            line_index += 1
            continue
        name, body = parsed
        conditional_result, stack = self._handle_conditional_for_process(
            name,
            body,
            directive_cursor.first_location(),
            stack,
            base_dir=base_dir,
        )
        if conditional_result is not None:
            _blank_directive_lines(out, directive_cursor, directive_lines)
            logical_cursor.advance(len(directive_lines))
            in_block_comment, comment_from_directive = _update_comment_state(
                in_block_comment, comment_from_directive, directive_lines=directive_lines
            )
            line_index += 1
            continue
        if not _is_active(stack):
            _blank_directive_lines(out, directive_cursor, directive_lines)
            logical_cursor.advance(len(directive_lines))
            in_block_comment, comment_from_directive = _update_comment_state(
                in_block_comment, comment_from_directive, directive_lines=directive_lines
            )
            line_index += 1
            continue
        if name == "define":
            self._handle_define(body)
            _blank_directive_lines(out, directive_cursor, directive_lines)
            logical_cursor.advance(len(directive_lines))
            in_block_comment, comment_from_directive = _update_comment_state(
                in_block_comment, comment_from_directive, directive_lines=directive_lines
            )
            line_index += 1
            continue
        if name == "undef":
            self._handle_undef(body, directive_cursor.first_location())
            _blank_directive_lines(out, directive_cursor, directive_lines)
            logical_cursor.advance(len(directive_lines))
            in_block_comment, comment_from_directive = _update_comment_state(
                in_block_comment, comment_from_directive, directive_lines=directive_lines
            )
            line_index += 1
            continue
        if name in {"include", "include_next", "import"}:
            include_processed = self._handle_include(
                body,
                directive_cursor.first_location(),
                base_dir=base_dir,
                include_stack=include_stack,
                include_next=name == "include_next",
                is_import=name == "import",
            )
            if include_processed is not None:
                out.extend_processed(include_processed)
            for directive_index, chunk in enumerate(directive_lines[1:], start=1):
                out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
            logical_cursor.advance(len(directive_lines))
            in_block_comment, comment_from_directive = _update_comment_state(
                in_block_comment, comment_from_directive, directive_lines=directive_lines
            )
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
        if name == "warning":
            _blank_directive_lines(out, directive_cursor, directive_lines)
            logical_cursor.advance(len(directive_lines))
            in_block_comment, comment_from_directive = _update_comment_state(
                in_block_comment, comment_from_directive, directive_lines=directive_lines
            )
            line_index += 1
            continue
        if name == "line":
            line_value, filename_value = self._parse_line_directive(
                body, directive_cursor.first_location()
            )
            _blank_directive_lines(out, directive_cursor, directive_lines)
            logical_cursor.rebase(line_value, filename_value)
            in_block_comment, comment_from_directive = _update_comment_state(
                in_block_comment, comment_from_directive, directive_lines=directive_lines
            )
            line_index += 1
            continue
        if name == "embed":
            embed_processed = self._handle_embed(
                body,
                directive_cursor.first_location(),
                base_dir=base_dir,
            )
            if embed_processed is not None:
                out.extend_processed(embed_processed)
            for directive_index, chunk in enumerate(directive_lines[1:], start=1):
                out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
            logical_cursor.advance(len(directive_lines))
            in_block_comment, comment_from_directive = _update_comment_state(
                in_block_comment, comment_from_directive, directive_lines=directive_lines
            )
            line_index += 1
            continue
        if name == "pragma":
            stripped_body = body.strip()
            if stripped_body == "once":
                self._pragma_once_files.add(source_id)
            elif stripped_body.startswith("pack("):
                self._handle_pack_pragma(
                    stripped_body,
                    directive_cursor.first_location(),
                )
            else:
                _validate_pragma(stripped_body, directive_cursor.first_location())
            _blank_directive_lines(out, directive_cursor, directive_lines)
            logical_cursor.advance(len(directive_lines))
            in_block_comment, comment_from_directive = _update_comment_state(
                in_block_comment, comment_from_directive, directive_lines=directive_lines
            )
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
        _blank_directive_lines(out, directive_cursor, directive_lines)
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


def _blank_directive_lines(
    out: _OutputBuilder,
    directive_cursor: _DirectiveCursor,
    directive_lines: list[str],
) -> None:
    for directive_index, chunk in enumerate(directive_lines):
        out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))


def _directive_lines_continue(directive_lines: list[str]) -> bool:
    if directive_lines[-1].rstrip().endswith("\\"):
        return True
    in_block_comment = False
    for chunk in directive_lines:
        in_block_comment = _scan_block_comment_state(chunk, in_block_comment)
    return in_block_comment


def _scan_directive_comments(
    directive_lines: list[str],
    in_block_comment: bool,
) -> tuple[bool, bool]:
    prev = in_block_comment
    for chunk in directive_lines:
        in_block_comment = _scan_block_comment_state(chunk, in_block_comment)
    return in_block_comment, (not prev and in_block_comment)


def _update_comment_state(
    in_block_comment: bool,
    comment_from_directive: bool,
    *,
    directive_lines: list[str] | None = None,
    line: str | None = None,
) -> tuple[bool, bool]:
    """Update in_block_comment and comment_from_directive after scanning a line.

    When a directive opens a block comment, comment_from_directive is set so
    subsequent non-directive lines (the comment tail) are blanked.  When the
    comment closes, comment_from_directive is cleared.
    """
    if directive_lines is not None:
        new_state, opened = _scan_directive_comments(directive_lines, in_block_comment)
        # in_block_comment is always False at directive entry (line 43),
        # so opened == new_state — either True (comment opened) or False.
        if opened:
            return new_state, True
        return new_state, False
    assert line is not None
    new_state = _scan_block_comment_state(line, in_block_comment)
    if not new_state:
        return new_state, False
    return new_state, comment_from_directive
