import re
from datetime import datetime
from pathlib import Path

from . import PreprocessorError
from .macros import _Macro, _render_macro_tokens

_DIRECTIVE_RE = re.compile(r"^\s*#\s*(?P<name>[A-Za-z_]\w*)(?P<body>.*)$", re.DOTALL)
_ASM_PREFIX_RE = re.compile(r"^\s*(?:__asm__|__asm|asm)\b")
_ASM_STMT_RE = re.compile(r"^\s*asm\b")
_ASM_KEYWORD_RE = re.compile(r"(?<!\w)(?:__asm__|__asm|asm)\b")
_ASM_QUALIFIERS = frozenset({"volatile", "__volatile__", "inline", "__inline__"})
_AARCH64_SP_ASM_RE = re.compile(
    r'^\(\s*"mov\s+%0\s*,\s*sp"\s*:\s*"=r"\s*\(\s*([A-Za-z_]\w*)\s*\)\s*\)$'
)
_CONTROL_STATEMENT_PREFIXES = frozenset({"if", "for", "switch", "while"})
_ENUM_DECL_RE = re.compile(
    r"(?<!\w)__(?:enum|enum_class)_decl\s*\(\s*([A-Za-z_]\w*)\s*,[^,]*,\s*\{"
)
_ENUM_DECL_CLOSE_RE = re.compile(r"^\s*\}\s*\)\s*;\s*$")


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
    cycle_start = include_stack.index(include_path)
    cycle_chain = (*include_stack[cycle_start:], include_path)
    return " -> ".join(cycle_chain)


def _format_include_search_roots(search_roots: tuple[Path, ...]) -> str:
    if not search_roots:
        return "<none>"
    return ", ".join(str(root) for root in search_roots)


def _parse_directive(line: str) -> tuple[str, str] | None:
    if not line.lstrip().startswith("#"):
        return None
    match = _DIRECTIVE_RE.match(line)
    if match is None:
        return None
    body = match.group("body")
    if body.endswith("\n"):
        body = body[:-1]
    return match.group("name"), body


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


def _strip_gnu_asm_extensions(source: str) -> str:
    lines = source.splitlines(keepends=True)
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
        if _ASM_STMT_RE.match(line):
            stripped_lines.append(";\n" if line.endswith("\n") else ";")
            in_asm_statement = ";" not in line
            continue
        # __asm__ or __asm labels/attributes/statements (strip just the asm part).
        stripped = _strip_inline_asm_segments(line)
        # Translate __enum_decl(name, type, { -> enum name {
        m = _ENUM_DECL_RE.search(stripped)
        if m:
            stripped = _ENUM_DECL_RE.sub(f"enum {m.group(1)} {{", stripped)
            in_enum_decl = True
        # Translate } ); (closing of __enum_decl) -> };
        if in_enum_decl:
            closed = _ENUM_DECL_CLOSE_RE.sub(r"};", stripped)
            if closed != stripped:
                stripped = closed
                in_enum_decl = False
        # If __asm appeared on its own line with just a ';' left, keep
        # the ';' as a null statement (it was the end of a multi-line
        # declaration like size_t wcsftime(...) __asm("_wcsftime");).
        stripped_lines.append(stripped)
    return "".join(stripped_lines)


def _strip_inline_asm_segments(line: str) -> str:
    result: list[str] = []
    index = 0
    while True:
        match = _ASM_KEYWORD_RE.search(line, index)
        if match is None:
            result.append(line[index:])
            return "".join(result)
        result.append(line[index : match.start()])
        open_index = _asm_operand_open_index(line, match.end())
        if open_index is None:
            index = match.end()
            continue
        close_index = _find_matching_paren(line, open_index)
        if close_index is None:
            index = match.end()
            continue
        after = close_index + 1
        statement_end = _asm_statement_end(line, after)
        if statement_end is not None and _asm_statement_context(line[: match.start()]):
            asm_text = line[open_index : close_index + 1]
            rewrite = _rewrite_aarch64_stack_pointer_asm(asm_text)
            result.append(rewrite if rewrite is not None else ";")
            index = statement_end
            continue
        index = after


def _rewrite_aarch64_stack_pointer_asm(asm_text: str) -> str | None:
    match = _AARCH64_SP_ASM_RE.match(asm_text)
    if match is None:
        return None
    target = match.group(1)
    return f"{target} = (unsigned long)&{target};"


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
    for line_number, line in enumerate(source.splitlines(), start=1):
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
        match = _ASM_KEYWORD_RE.search(line, index)
        if match is None:
            return False
        prefix = line[: match.start()]
        open_index = _asm_operand_open_index(line, match.end())
        if open_index is None:
            index = match.end()
            continue
        close_index = _find_matching_paren(line, open_index)
        if close_index is None:
            if _asm_statement_context(prefix):
                return True
            index = match.end()
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
    return _ASM_PREFIX_RE.match(line) is not None


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
    for line_number, line in enumerate(source.splitlines(), start=1):
        if not _ASM_PREFIX_RE.match(line):
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
