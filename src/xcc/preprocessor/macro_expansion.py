from collections.abc import Callable

from xcc.lexer import TokenKind

from .common import PreprocessorError, _SourceLocation
from .macros import (
    _EMPTY_MACRO_TOKEN,
    _join_macro_arguments,
    _lookup_macro_argument,
    _Macro,
    _MacroToken,
    _stringize_tokens,
    _tokenize_macro_text,
)

_PP_INVALID_MACRO = "XCC-PP-0201"
_PP_UNTERMINATED_MACRO = "XCC-PP-0202"


def _expand_macro_tokens(
    tokens: list[_MacroToken],
    macros: dict[str, _Macro],
    std: str,
    location: _SourceLocation,
    disabled: frozenset[str] = frozenset(),
    dynamic_macro_resolver: Callable[[str, _SourceLocation], _MacroToken] | None = None,
    dynamic_macro_names: frozenset[str] = frozenset(),
) -> list[_MacroToken]:
    expanded: list[_MacroToken] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind != TokenKind.IDENT:
            expanded.append(token)
            index += 1
            continue
        if token.text in dynamic_macro_names and token.text in macros:
            if dynamic_macro_resolver is not None:
                expanded.append(dynamic_macro_resolver(token.text, location))
            else:
                expanded.append(_MacroToken(TokenKind.INT_CONST, "0"))
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
                dynamic_macro_resolver=dynamic_macro_resolver,
                dynamic_macro_names=dynamic_macro_names,
            )
            # Re-scan: a single-identifier replacement may name another macro
            # that should be expanded together with the remaining input.
            # Example: #define MI mi_assert  +  MI(expr) → mi_assert(expr).
            if (
                len(replacement) == 1
                and replacement[0].kind == TokenKind.IDENT
                and replacement[0].text in macros
                and replacement[0].text not in next_disabled
            ):
                re_input = replacement + tokens[index + 1:]
                expanded.extend(
                    _expand_macro_tokens(
                        re_input,
                        macros,
                        std,
                        location,
                        disabled=disabled,
                        dynamic_macro_resolver=dynamic_macro_resolver,
                        dynamic_macro_names=dynamic_macro_names,
                    )
                )
                return expanded
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
            disabled=disabled,
            dynamic_macro_resolver=dynamic_macro_resolver,
            dynamic_macro_names=dynamic_macro_names,
        )
        replacement = _expand_macro_tokens(
            replacement,
            macros,
            std,
            location,
            disabled=next_disabled,
            dynamic_macro_resolver=dynamic_macro_resolver,
            dynamic_macro_names=dynamic_macro_names,
        )
        if (
            replacement
            and replacement[-1].kind == TokenKind.IDENT
            and replacement[-1].text in macros
            and replacement[-1].text not in next_disabled
        ):
            re_input = replacement + tokens[next_index:]
            expanded.extend(
                _expand_macro_tokens(
                    re_input,
                    macros,
                    std,
                    location,
                    disabled=disabled,
                    dynamic_macro_resolver=dynamic_macro_resolver,
                    dynamic_macro_names=dynamic_macro_names,
                )
            )
            return expanded
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
        code=_PP_UNTERMINATED_MACRO,
    )


def _expand_function_like_macro(
    macro: _Macro,
    args: list[list[_MacroToken]],
    macros: dict[str, _Macro],
    *,
    std: str,
    location: _SourceLocation,
    disabled: frozenset[str],
    dynamic_macro_resolver: Callable[[str, _SourceLocation], _MacroToken] | None,
    dynamic_macro_names: frozenset[str],
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
        name: _expand_macro_tokens(
            arg,
            macros,
            std,
            location,
            disabled=disabled,
            dynamic_macro_resolver=dynamic_macro_resolver,
            dynamic_macro_names=dynamic_macro_names,
        )
        for name, arg in raw_named_args.items()
    }
    raw_var_args: list[_MacroToken] = []
    expanded_var_args: list[_MacroToken] = []
    if macro.is_variadic:
        variadic_args = args[expected:]
        raw_var_args = _join_macro_arguments(variadic_args)
        expanded_var_args = _join_macro_arguments(
            [
                _expand_macro_tokens(
                    arg,
                    macros,
                    std,
                    location,
                    disabled=disabled,
                    dynamic_macro_resolver=dynamic_macro_resolver,
                    dynamic_macro_names=dynamic_macro_names,
                )
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
    if pasted and len(pasted) != 1 and std == "gnu11":
        # In GNU mode, allow paste to produce multiple tokens (e.g. , ## rest
        # for the GNU ##__VA_ARGS__ extension where , pasted with a non-empty
        # var arg produces two tokens).
        return pasted
    if not pasted or len(pasted) != 1:
        raise PreprocessorError(
            "Invalid token paste result",
            actual_location.line,
            1,
            filename=actual_location.filename,
            code=_PP_INVALID_MACRO,
        )
    return pasted
