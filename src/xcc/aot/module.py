import ast
from dataclasses import dataclass
from pathlib import Path

from xcc.aot.diag import AotDiagnostic, AotError


@dataclass(frozen=True)
class AotModule:
    filename: str
    source: str
    tree: ast.Module


def parse_source(source: str, *, filename: str = "<input>") -> AotModule:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as error:
        message = error.msg or "invalid syntax"
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-PARSE-0001",
                    message,
                    filename=filename,
                    line=error.lineno,
                    column=error.offset,
                ),
            )
        ) from error
    return AotModule(filename, source, tree)


def parse_path(path: str | Path) -> AotModule:
    resolved = Path(path)
    source = resolved.read_text(encoding="utf-8", errors="surrogateescape")
    return parse_source(source, filename=str(resolved))
