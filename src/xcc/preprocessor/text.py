from datetime import datetime
from pathlib import Path

from .macros import _Macro, _render_macro_tokens
from .model import PreprocessorError

_ASM_QUALIFIERS = ("volatile", "__volatile__", "inline", "__inline__")
_CONTROL_STATEMENT_PREFIXES = ("if", "for", "switch", "while")


def _macro_table_line(macro: _Macro) -> str:
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
    *,
    directive: str = "include",
) -> str:
    delim_open, delim_close = ("<", ">") if is_angled else ('"', '"')
    return (
        f"{source}:{line}: #{directive} {delim_open}{include_name}{delim_close} -> {include_path}"
    )


def _format_include_reference(include_name: str, is_angled: bool) -> str:
    if is_angled:
        return f"<{include_name}>"
    return f'"{include_name}"'


def _format_include_cycle(include_stack: tuple[str, ...], include_path: str) -> str:
    cycle_start = 0
    while cycle_start < len(include_stack) and include_stack[cycle_start] != include_path:
        cycle_start += 1
    if cycle_start == len(include_stack):
        raise ValueError("include path is not present in include stack")
    cycle_chain = (*include_stack[cycle_start:], include_path)
    return " -> ".join(cycle_chain)


def _format_include_search_roots(search_roots: tuple[Path, ...]) -> str:
    if not search_roots:
        return "<none>"
    parts: list[str] = []
    for root in search_roots:
        parts.append(str(root))
    return ", ".join(parts)


def _parse_directive(line: str) -> tuple[str, str] | None:
    index = _skip_space(line, 0)
    if index >= len(line) or line[index] != "#":
        return None
    index = _skip_space(line, index + 1)
    scanned = _scan_identifier(line, index)
    if scanned is None:
        return None
    name, index = scanned
    body = line[index:]
    if body.endswith("\n"):
        body = body[:-1]
    return name, body


def _blank_line(line: str) -> str:
    return "\n" if line.endswith("\n") else ""


def _scan_block_comment_state(line: str, in_block_comment: bool) -> bool:
    in_string: str | None = None
    index = 0
    while index < len(line):
        ch = line[index]
        if in_string is not None:
            if ch == "\\" and index + 1 < len(line):
                index += 2
                continue
            if ch == in_string:
                in_string = None
            index += 1
            continue
        if in_block_comment:
            if ch == "*" and index + 1 < len(line) and line[index + 1] == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue
        if ch in {'"', "'"}:
            in_string = ch
            index += 1
            continue
        if ch == "/" and index + 1 < len(line):
            nxt = line[index + 1]
            if nxt == "/":
                return in_block_comment
            if nxt == "*":
                in_block_comment = True
                index += 2
                continue
        index += 1
    return in_block_comment


def _is_word_char(ch: str) -> bool:
    return ch == "_" or ch.isalnum()


def _scan_identifier(text: str, index: int) -> tuple[str, int] | None:
    if index >= len(text):
        return None
    ch = text[index]
    if ch != "_" and not ch.isalpha():
        return None
    start = index
    index += 1
    while index < len(text) and _is_word_char(text[index]):
        index += 1
    return text[start:index], index


def _object_like_macro_at(line: str, index: int, names: list[str]) -> str | None:
    if index > 0 and _is_word_char(line[index - 1]):
        return None
    for name in names:
        if not name:
            continue
        end = index + len(name)
        if not line.startswith(name, index):
            continue
        if end < len(line) and _is_word_char(line[end]):
            continue
        return name
    return None


def _expand_object_like_macros(line: str, macros: dict[str, str]) -> str:
    if not macros:
        return line
    names = sorted(macros.keys(), key=str.__len__, reverse=True)
    result: list[str] = []
    index = 0
    while index < len(line):
        name = _object_like_macro_at(line, index, names)
        if name is None:
            result.append(line[index])
            index += 1
            continue
        result.append(macros[name])
        index += len(name)
    return "".join(result)


def _asm_keyword_at(line: str, index: int) -> int | None:
    for keyword in ("__asm__", "__asm", "asm"):
        end = index + len(keyword)
        if not line.startswith(keyword, index):
            continue
        if end < len(line) and _is_word_char(line[end]):
            continue
        return end
    return None


def _find_asm_keyword(line: str, index: int) -> tuple[int, int] | None:
    cursor = index
    while cursor < len(line):
        if cursor > 0 and _is_word_char(line[cursor - 1]):
            cursor += 1
            continue
        end = _asm_keyword_at(line, cursor)
        if end is not None:
            return cursor, end
        cursor += 1
    return None


def _line_starts_asm_prefix(line: str) -> bool:
    index = _skip_space(line, 0)
    return _asm_keyword_at(line, index) is not None


def _line_starts_bare_asm(line: str) -> bool:
    index = _skip_space(line, 0)
    end = index + 3
    if not line.startswith("asm", index):
        return False
    return end >= len(line) or not _is_word_char(line[end])


def _rewrite_enum_decl(line: str) -> tuple[str, bool]:
    if "__enum_" not in line:
        return line, False
    found = _find_enum_decl(line, 0)
    if found is None:
        return line, False
    start, end, name = found
    return line[:start] + f"enum {name} {{" + line[end:], True


def _find_enum_decl(line: str, index: int) -> tuple[int, int, str] | None:
    cursor = index
    while cursor < len(line):
        if cursor > 0 and _is_word_char(line[cursor - 1]):
            cursor += 1
            continue
        prefix_end = _enum_decl_prefix_end(line, cursor)
        if prefix_end is None:
            cursor += 1
            continue
        result = _finish_enum_decl(line, prefix_end)
        if result is None:
            cursor += 1
            continue
        end, name = result
        return cursor, end, name
    return None


def _enum_decl_prefix_end(line: str, index: int) -> int | None:
    enum_prefix = "__enum_decl"
    enum_class_prefix = "__enum_class_decl"
    if line.startswith(enum_class_prefix, index):
        return index + len(enum_class_prefix)
    if line.startswith(enum_prefix, index):
        return index + len(enum_prefix)
    return None


def _finish_enum_decl(line: str, index: int) -> tuple[int, str] | None:
    cursor = _skip_space(line, index)
    if cursor >= len(line) or line[cursor] != "(":
        return None
    cursor = _skip_space(line, cursor + 1)
    scanned = _scan_identifier(line, cursor)
    if scanned is None:
        return None
    name, cursor = scanned
    cursor = _skip_space(line, cursor)
    if cursor >= len(line) or line[cursor] != ",":
        return None
    cursor += 1
    while cursor < len(line) and line[cursor] != ",":
        cursor += 1
    if cursor >= len(line):
        return None
    cursor = _skip_space(line, cursor + 1)
    if cursor >= len(line) or line[cursor] != "{":
        return None
    return cursor + 1, name


def _rewrite_enum_decl_close(line: str) -> str:
    cursor = _skip_space(line, 0)
    if cursor >= len(line) or line[cursor] != "}":
        return line
    cursor = _skip_space(line, cursor + 1)
    if cursor >= len(line) or line[cursor] != ")":
        return line
    cursor = _skip_space(line, cursor + 1)
    if cursor >= len(line) or line[cursor] != ";":
        return line
    cursor = _skip_space(line, cursor + 1)
    if cursor != len(line):
        return line
    return "};"


def _split_lines(source: str) -> list[str]:
    if not source:
        return []
    lines = source.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _split_lines_keepends(source: str) -> list[str]:
    if not source:
        return []
    raw_lines = source.split("\n")
    lines: list[str] = []
    last_index = len(raw_lines) - 1
    for index, line in enumerate(raw_lines):
        if index < last_index:
            lines.append(line + "\n")
        elif line:
            lines.append(line)
    return lines


def _strip_gnu_asm_extensions(source: str) -> str:
    lines = _split_lines_keepends(source)
    if not lines:
        return source
    stripped_lines: list[str] = []
    in_asm_statement = False
    in_enum_decl = False
    for line in lines:
        if in_asm_statement:
            stripped_lines.append(_blank_line(line))
            if ";" in line:
                in_asm_statement = False
            continue
        # Bare 'asm' at line start: standalone asm statement.
        if _line_starts_bare_asm(line):
            stripped_lines.append(";\n" if line.endswith("\n") else ";")
            in_asm_statement = ";" not in line
            continue
        # __asm__ or __asm labels/attributes/statements (strip just the asm part).
        stripped = _strip_inline_asm_segments(line)
        # Translate __enum_decl(name, type, { -> enum name {
        stripped, changed_enum_decl = _rewrite_enum_decl(stripped)
        if changed_enum_decl:
            in_enum_decl = True
        # Translate } ); (closing of __enum_decl) -> };
        if in_enum_decl:
            closed = _rewrite_enum_decl_close(stripped)
            if closed != stripped:
                stripped = closed
                in_enum_decl = False
        # If __asm appeared on its own line with just a ';' left, keep
        # the ';' as a null statement (it was the end of a multi-line
        # declaration like size_t wcsftime(...) __asm("_wcsftime");).
        stripped_lines.append(stripped)
    return "".join(stripped_lines)


def _strip_inline_asm_segments(line: str) -> str:
    if "asm" not in line:
        return line
    result: list[str] = []
    index = 0
    while True:
        match = _find_asm_keyword(line, index)
        if match is None:
            result.append(line[index:])
            return "".join(result)
        match_start, match_end = match
        result.append(line[index:match_start])
        open_index = _asm_operand_open_index(line, match_end)
        if open_index is None:
            index = match_end
            continue
        close_index = _find_matching_paren(line, open_index)
        if close_index is None:
            index = match_end
            continue
        after = close_index + 1
        statement_end = _asm_statement_end(line, after)
        if statement_end is not None and _asm_statement_context(line[:match_start]):
            asm_text = line[open_index : close_index + 1]
            rewrite = _rewrite_aarch64_stack_pointer_asm(asm_text)
            result.append(rewrite if rewrite is not None else ";")
            index = statement_end
            continue
        index = after


def _rewrite_aarch64_stack_pointer_asm(asm_text: str) -> str | None:
    target = _aarch64_stack_pointer_target(asm_text)
    if target is None:
        return None
    return f"{target} = (unsigned long)&{target};"


def _aarch64_stack_pointer_target(asm_text: str) -> str | None:
    cursor = _skip_space(asm_text, 0)
    if cursor >= len(asm_text) or asm_text[cursor] != "(":
        return None
    cursor = _skip_space(asm_text, cursor + 1)
    if cursor >= len(asm_text) or asm_text[cursor] != '"':
        return None
    template_end = _match_aarch64_sp_template(asm_text, cursor + 1)
    if template_end is None:
        return None
    cursor = template_end
    cursor = _skip_space(asm_text, cursor)
    if cursor >= len(asm_text) or asm_text[cursor] != ":":
        return None
    cursor = _skip_space(asm_text, cursor + 1)
    if not asm_text.startswith('"=r"', cursor):
        return None
    cursor = _skip_space(asm_text, cursor + 4)
    if cursor >= len(asm_text) or asm_text[cursor] != "(":
        return None
    cursor = _skip_space(asm_text, cursor + 1)
    scanned = _scan_identifier(asm_text, cursor)
    if scanned is None:
        return None
    target, cursor = scanned
    cursor = _skip_space(asm_text, cursor)
    if cursor >= len(asm_text) or asm_text[cursor] != ")":
        return None
    cursor = _skip_space(asm_text, cursor + 1)
    if cursor >= len(asm_text) or asm_text[cursor] != ")":
        return None
    cursor = _skip_space(asm_text, cursor + 1)
    if cursor != len(asm_text):
        return None
    return target


def _match_aarch64_sp_template(asm_text: str, index: int) -> int | None:
    if not asm_text.startswith("mov", index):
        return None
    cursor = index + 3
    if cursor >= len(asm_text) or not asm_text[cursor].isspace():
        return None
    cursor = _skip_space(asm_text, cursor)
    if not asm_text.startswith("%0", cursor):
        return None
    cursor = _skip_space(asm_text, cursor + 2)
    if cursor >= len(asm_text) or asm_text[cursor] != ",":
        return None
    cursor = _skip_space(asm_text, cursor + 1)
    if not asm_text.startswith("sp", cursor):
        return None
    cursor += 2
    if cursor >= len(asm_text) or asm_text[cursor] != '"':
        return None
    return cursor + 1


def _asm_operand_open_index(line: str, index: int) -> int | None:
    cursor = _skip_space(line, index)
    while True:
        scanned = _scan_identifier(line, cursor)
        if scanned is None:
            break
        word, word_end = scanned
        if word not in _ASM_QUALIFIERS:
            break
        cursor = _skip_space(line, word_end)
    if cursor < len(line) and line[cursor] == "(":
        return cursor
    return None


def _find_matching_paren(line: str, open_index: int) -> int | None:
    depth = 0
    index = open_index
    in_string: str | None = None
    while index < len(line):
        ch = line[index]
        if in_string is not None:
            if ch == "\\":
                index += 2
                continue
            if ch == in_string:
                in_string = None
            index += 1
            continue
        if ch in {'"', "'"}:
            in_string = ch
            index += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _asm_statement_end(line: str, index: int) -> int | None:
    cursor = _skip_space(line, index)
    if cursor < len(line) and line[cursor] == ";":
        return cursor + 1
    return None


def _asm_statement_context(prefix: str) -> bool:
    stripped = prefix.rstrip()
    if not stripped:
        return True
    return stripped[-1] in "{;"


def _skip_space(line: str, index: int) -> int:
    while index < len(line) and line[index].isspace():
        index += 1
    return index


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


def _format_timestamp_macro(now: datetime) -> str:
    weekday = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[now.weekday()]
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
    return f"{weekday} {month} {now.day:2d} {now:%H:%M:%S} {now.year:04d}"


def _reject_gnu_asm_extensions(
    source: str,
    line_map: tuple[tuple[str, int], ...],
    *,
    code: str,
    primary_filename: str | None = None,
) -> None:
    previous_significant_line = ""
    for line_number, line in enumerate(_split_lines(source), start=1):
        if _contains_gnu_asm_statement(
            line,
            previous_significant_line=previous_significant_line,
        ):
            mapped_filename, mapped_line = (
                line_map[line_number - 1]
                if 1 <= line_number <= len(line_map)
                else ("<input>", line_number)
            )
            if primary_filename is not None and mapped_filename != primary_filename:
                previous_significant_line = line.strip()
                continue
            raise PreprocessorError(
                "GNU asm extension is not allowed in c11",
                mapped_line,
                1,
                filename=mapped_filename,
                code=code,
            )
        if line.strip():
            previous_significant_line = line.strip()


def _contains_gnu_asm_statement(line: str, *, previous_significant_line: str = "") -> bool:
    index = 0
    while True:
        match = _find_asm_keyword(line, index)
        if match is None:
            return False
        match_start, match_end = match
        prefix = line[:match_start]
        open_index = _asm_operand_open_index(line, match_end)
        if open_index is None:
            index = match_end
            continue
        close_index = _find_matching_paren(line, open_index)
        if close_index is None:
            if _asm_statement_context(prefix):
                return True
            index = match_end
            continue
        if _asm_statement_end(line, close_index + 1) is not None and _asm_statement_context(prefix):
            if _line_starts_declaration_asm_label(line) and _can_continue_declaration(
                previous_significant_line
            ):
                index = close_index + 1
                continue
            return True
        index = close_index + 1


def _line_starts_declaration_asm_label(line: str) -> bool:
    return _line_starts_asm_prefix(line)


def _can_continue_declaration(previous_line: str) -> bool:
    if not previous_line.endswith(")"):
        return False
    scanned = _scan_identifier(previous_line, 0)
    if scanned is None:
        return True
    word, _word_end = scanned
    return word not in _CONTROL_STATEMENT_PREFIXES


def _reject_gnu_asm_statements(
    source: str,
    line_map: tuple[tuple[str, int], ...],
    *,
    code: str,
    primary_filename: str,
) -> None:
    for line_number, line in enumerate(_split_lines(source), start=1):
        if not _line_starts_asm_prefix(line):
            continue
        mapped_filename, mapped_line = (
            line_map[line_number - 1]
            if 1 <= line_number <= len(line_map)
            else ("<input>", line_number)
        )
        if mapped_filename != primary_filename:
            continue
        raise PreprocessorError(
            "GNU asm statement is not supported for this target",
            mapped_line,
            1,
            filename=mapped_filename,
            code=code,
        )
