from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from .common import (
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


def process_text(
    preprocessor: object,
    source: str,
    *,
    filename: str,
    source_id: str,
    base_dir: Path | None,
    include_stack: tuple[str, ...],
    parse_directive: Callable[[str], tuple[str, str] | None] = _parse_directive,
) -> _ProcessedText:
    self = cast(Any, preprocessor)
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
                    try:
                        expanded = self._expand_line(joined, location)
                    except PreprocessorError as exc:
                        if exc.code != _PP_UNTERMINATED_MACRO:
                            raise
                        next_idx = line_index + len(all_lines)
                        if next_idx >= len(lines):
                            raise
                        next_line = lines[next_idx]
                        inner_parsed = parse_directive(next_line)
                        if inner_parsed is not None:
                            inner_name, inner_body = inner_parsed
                            inner_loc = _SourceLocation(
                                logical_cursor.filename,
                                logical_cursor.line + len(all_lines),
                                logical_cursor.include_level,
                            )
                            result = self._handle_conditional(
                                inner_name,
                                inner_body,
                                inner_loc,
                                inner_stack,
                                base_dir=base_dir,
                            )
                            if result is None:
                                raise
                            all_lines.append(next_line)
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
        while directive_lines[-1].rstrip().endswith("\\") and line_index + 1 < len(lines):
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
        conditional_result = self._handle_conditional(
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


def _scan_directive_comments(directive_lines: list[str], in_block_comment: bool) -> tuple[bool, bool]:
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
