import re
from dataclasses import dataclass

from xcc.lexer import LexerError, TokenKind, lex_pp

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")


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


def _parse_cli_define_head(head: str) -> tuple[str, tuple[str, ...], bool] | None:
    stripped = head.strip()
    if "(" not in stripped:
        return None
    open_index = stripped.find("(")
    close_index = stripped.rfind(")")
    if close_index <= open_index:
        return None
    if stripped[close_index + 1 :].strip():
        return None

    name = stripped[:open_index].strip()
    if _IDENT_RE.fullmatch(name) is None:
        return None

    parsed = _parse_macro_parameters(stripped[open_index + 1 : close_index])
    if parsed is None:
        return None
    params, variadic = parsed
    return name, tuple(params), variadic


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
