from dataclasses import dataclass

from . import py_ast as ast


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
        super().__init__(str(diagnostics[0]))
        self.diagnostics = diagnostics


def node_location(node: ast.AST) -> tuple[int | None, int | None]:
    return node.span.line, node.span.column
