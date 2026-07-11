from dataclasses import dataclass
from pathlib import Path

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.py_ast import Module


@dataclass(frozen=True)
class AotModule:
    filename: str
    source: str
    tree: Module


def parse_source(source: str, *, filename: str = "<input>") -> AotModule:
    from xcc.aot.cpython_ast_adapter import parse_cpython_source

    try:
        tree = parse_cpython_source(source, filename=filename)
    except SyntaxError as error:
        message = error.msg or "invalid syntax"
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-PARSE-0001",
                    message,
                    filename=filename,
                    line=error.lineno,
                    column=_syntax_error_column(source, error.lineno, error.offset),
                ),
            )
        ) from error
    return AotModule(filename, source, tree)


def parse_path(path: str | Path) -> AotModule:
    resolved = Path(path)
    source = resolved.read_text(encoding="utf-8", errors="surrogateescape")
    return parse_source(source, filename=str(resolved))


def _syntax_error_column(
    source: str,
    line: int | None,
    offset: int | None,
) -> int | None:
    if offset is None:
        return None
    character_column = max(offset - 1, 0)
    if line is None:
        return character_column
    lines = source.splitlines()
    if line < 1 or line > len(lines):
        return character_column
    prefix = lines[line - 1][:character_column]
    return len(prefix.encode("utf-8", errors="surrogateescape"))
