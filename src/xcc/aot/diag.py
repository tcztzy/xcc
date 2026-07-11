from dataclasses import dataclass
from typing import cast

from xcc.aot import py_ast as ast


class _LocatedNode:
    lineno: int
    col_offset: int


@dataclass(frozen=True)
class AotDiagnostic:
    code: str
    message: str
    filename: str
    line: int | None = None
    column: int | None = None

    def __str__(self) -> str:
        if self.line is None or self.column is None:
            return f"{self.filename}: aot: {self.code}: {self.message}"
        return f"{self.filename}:{self.line}:{self.column}: aot: {self.code}: {self.message}"


class AotError(ValueError):
    def __init__(self, diagnostics: tuple[AotDiagnostic, ...]) -> None:
        if not diagnostics:
            raise ValueError("AotError requires at least one diagnostic")
        super().__init__(str(diagnostics[0]))
        self.diagnostics = diagnostics


def node_location(node: ast.AST) -> tuple[int | None, int | None]:
    located = cast(_LocatedNode, node)
    try:
        line = located.lineno
    except AttributeError:
        line = None
    try:
        column = located.col_offset
    except AttributeError:
        column = None
    return line, column
