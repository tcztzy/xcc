from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .common import PreprocessorError, _SourceLocation
from .expressions import _strip_condition_comments
from .macros import _Macro


@dataclass
class _ConditionalFrame:
    parent_active: bool
    active: bool
    branch_taken: bool
    saw_else: bool = False


def _is_active(stack: list[_ConditionalFrame]) -> bool:
    return all(frame.active for frame in stack)


def _require_empty_conditional_tail(
    directive: str,
    body: str,
    location: _SourceLocation,
    *,
    invalid_directive_code: str,
) -> None:
    if _strip_condition_comments(body).strip():
        raise PreprocessorError(
            f"Unexpected tokens after #{directive}",
            location.line,
            1,
            filename=location.filename,
            code=invalid_directive_code,
        )


def _handle_conditional(
    name: str,
    body: str,
    location: _SourceLocation,
    stack: list[_ConditionalFrame],
    *,
    base_dir: Path | None,
    std: str,
    macros: dict[str, _Macro],
    eval_condition: Callable[[str, _SourceLocation, Path | None], bool],
    require_macro_name: Callable[[str, _SourceLocation], str],
    invalid_directive_code: str,
    unknown_directive_code: str,
) -> str | None:
    if name not in {
        "if",
        "ifdef",
        "ifndef",
        "elif",
        "elifdef",
        "elifndef",
        "else",
        "endif",
    }:
        return None
    if name == "if":
        parent_active = _is_active(stack)
        condition = parent_active and eval_condition(body, location, base_dir)
        stack.append(_ConditionalFrame(parent_active, condition, condition))
        return ""
    if name == "ifdef":
        parent_active = _is_active(stack)
        macro_name = require_macro_name(body, location)
        condition = parent_active and macro_name in macros
        stack.append(_ConditionalFrame(parent_active, condition, condition))
        return ""
    if name == "ifndef":
        parent_active = _is_active(stack)
        macro_name = require_macro_name(body, location)
        condition = parent_active and macro_name not in macros
        stack.append(_ConditionalFrame(parent_active, condition, condition))
        return ""
    if not stack:
        raise PreprocessorError(
            f"Unexpected #{name}",
            location.line,
            1,
            filename=location.filename,
            code=invalid_directive_code,
        )
    frame = stack[-1]
    if name in {"elif", "elifdef", "elifndef"}:
        if name in {"elifdef", "elifndef"} and std == "c11":
            raise PreprocessorError(
                f"Unknown preprocessor directive: #{name}",
                location.line,
                1,
                filename=location.filename,
                code=unknown_directive_code,
            )
        if frame.saw_else:
            raise PreprocessorError(
                f"#{name} after #else",
                location.line,
                1,
                filename=location.filename,
                code=invalid_directive_code,
            )
        if not frame.parent_active or frame.branch_taken:
            frame.active = False
            return ""
        if name == "elif":
            condition = eval_condition(body, location, base_dir)
        else:
            macro_name = require_macro_name(body, location)
            condition = macro_name in macros if name == "elifdef" else macro_name not in macros
        frame.active = condition
        frame.branch_taken = frame.branch_taken or condition
        return ""
    if name == "else":
        _require_empty_conditional_tail(
            "else",
            body,
            location,
            invalid_directive_code=invalid_directive_code,
        )
        if frame.saw_else:
            raise PreprocessorError(
                "Duplicate #else",
                location.line,
                1,
                filename=location.filename,
                code=invalid_directive_code,
            )
        frame.saw_else = True
        frame.active = frame.parent_active and not frame.branch_taken
        frame.branch_taken = True
        return ""
    _require_empty_conditional_tail(
        "endif",
        body,
        location,
        invalid_directive_code=invalid_directive_code,
    )
    stack.pop()
    return ""
