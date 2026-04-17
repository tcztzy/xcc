import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NoReturn

from xcc.lexer import TokenKind

from .common import PreprocessorError, _SourceLocation
from .macros import _MacroToken, _tokenize_macro_text

_INCLUDE_RE = re.compile(r"^(?:\"(?P<quote>[^\"\n]+)\"|<(?P<angle>[^>\n]+)>)$")


def _env_path_list(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    if not raw:
        return ()
    parts = raw.split(os.pathsep)
    # GCC/Clang treat empty include-env entries as the current working directory.
    return tuple(part if part else "." for part in parts)


def _source_dir(filename: str) -> Path | None:
    if filename in {"<input>", "<stdin>"}:
        return None
    return Path(filename).resolve().parent


def _parse_include_target(
    body: str,
    location: _SourceLocation,
    *,
    expand_macro_text: Callable[[str, _SourceLocation], str],
    invalid_directive_code: str,
) -> tuple[str, bool]:
    return _parse_header_name_operand(
        body.strip(),
        location,
        expand_macro_text=expand_macro_text,
        invalid_directive_code=invalid_directive_code,
    )


def _parse_header_name_operand(
    operand: str,
    location: _SourceLocation,
    *,
    expand_macro_text: Callable[[str, _SourceLocation], str],
    invalid_directive_code: str,
) -> tuple[str, bool]:
    direct = _INCLUDE_RE.match(operand)
    if direct is not None:
        quoted_name = direct.group("quote")
        angle_name = direct.group("angle")
        include_name = quoted_name if quoted_name is not None else angle_name
        assert include_name is not None
        return include_name, angle_name is not None

    expanded = expand_macro_text(operand, location).strip()
    tokens = _tokenize_macro_text(expanded)
    if tokens is None:
        _raise_invalid_include(location, invalid_directive_code)
    assert tokens is not None

    if len(tokens) == 1 and tokens[0].kind == TokenKind.STRING_LITERAL:
        literal = tokens[0].text
        return literal[1:-1], False

    if _is_angle_header_token_sequence(tokens):
        return "".join(token.text for token in tokens[1:-1]), True

    _raise_invalid_include(location, invalid_directive_code)


def _is_angle_header_token_sequence(tokens: list[_MacroToken]) -> bool:
    return (
        len(tokens) >= 3
        and tokens[0].kind == TokenKind.PUNCTUATOR
        and tokens[-1].kind == TokenKind.PUNCTUATOR
        and tokens[0].text == "<"
        and tokens[-1].text == ">"
    )


def _raise_invalid_include(location: _SourceLocation, code: str) -> NoReturn:
    raise PreprocessorError(
        "Invalid #include directive",
        location.line,
        1,
        filename=location.filename,
        code=code,
    )


def _resolve_include(
    include_name: str,
    *,
    is_angled: bool,
    base_dir: Path | None,
    quote_include_dirs: Iterable[str],
    include_dirs: Iterable[str],
    cpath_include_dirs: Iterable[str],
    system_include_dirs: Iterable[str],
    host_system_include_dirs: Iterable[str],
    c_include_path_dirs: Iterable[str],
    after_include_dirs: Iterable[str],
    include_next_from: Path | None = None,
) -> tuple[Path | None, tuple[Path, ...]]:
    search_roots: list[Path] = []
    if not is_angled and base_dir is not None:
        search_roots.append(base_dir)
        search_roots.extend(Path(path) for path in quote_include_dirs)
    search_roots.extend(Path(path) for path in include_dirs)
    search_roots.extend(Path(path) for path in cpath_include_dirs)
    search_roots.extend(Path(path) for path in system_include_dirs)
    search_roots.extend(Path(path) for path in host_system_include_dirs)
    search_roots.extend(Path(path) for path in c_include_path_dirs)
    search_roots.extend(Path(path) for path in after_include_dirs)

    start_index = _include_next_start_index(search_roots, include_next_from)
    seen_roots = {include_next_from.resolve()} if include_next_from is not None else set()
    searched_roots_list: list[Path] = []
    for root in search_roots[start_index:]:
        resolved_root = root.resolve()
        if resolved_root in seen_roots:
            continue
        seen_roots.add(resolved_root)
        searched_roots_list.append(resolved_root)

    searched_roots = tuple(searched_roots_list)
    for root in searched_roots:
        candidate = root / include_name
        if candidate.is_file():
            return candidate.resolve(), searched_roots
    return None, searched_roots


def _include_next_start_index(
    search_roots: list[Path],
    include_next_from: Path | None,
) -> int:
    if include_next_from is None:
        return 0
    include_next_from_resolved = include_next_from.resolve()
    for index, root in enumerate(search_roots):
        if root.resolve() == include_next_from_resolved:
            return index + 1
    return 0
