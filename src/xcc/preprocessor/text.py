import re
from datetime import datetime
from pathlib import Path

from .common import PreprocessorError
from .macros import _Macro, _render_macro_tokens

_DIRECTIVE_RE = re.compile(r"^\s*#\s*(?P<name>[A-Za-z_]\w*)(?P<body>.*)$")
_ASM_PREFIX_RE = re.compile(r"^\s*(?:__asm__|__asm|asm)\b")
_ASM_LABEL_RE = re.compile(r"(?<!\w)(?:__asm__|__asm|asm)\s*\([^;\n]*\)")


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
    return match.group("name"), match.group("body")


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


def _expand_object_like_macros(line: str, macros: dict[str, str]) -> str:
    if not macros:
        return line
    names = sorted(macros.keys(), key=str.__len__, reverse=True)
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in names) + r")\b")
    return pattern.sub(lambda match: macros[match.group(0)], line)


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
        # Check for asm statements first (line starts with asm keyword).
        # Label stripping happens afterward so that declarations with
        # __asm("name") attributes keep their trailing semicolon.
        if _ASM_PREFIX_RE.match(line):
            stripped_lines.append(_blank_line(line))
            in_asm_statement = ";" not in line
            continue
        stripped = _ASM_LABEL_RE.sub("", line)
        stripped_lines.append(stripped)
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
                code=code,
            )
