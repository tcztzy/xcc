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
    from xcc.aot.py_parser import parse_subset_source

    try:
        return parse_subset_source(source, filename=filename)
    except AotError as error:
        diagnostic = error.diagnostics[0]
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-PARSE-0001",
                    f"invalid syntax: {diagnostic.message}",
                    filename=filename,
                    line=diagnostic.line,
                    column=diagnostic.column,
                ),
            )
        ) from error


def parse_path(path: str | Path) -> AotModule:
    resolved = Path(path)
    source = resolved.read_text(encoding="utf-8", errors="surrogateescape")
    return parse_source(source, filename=str(resolved))
