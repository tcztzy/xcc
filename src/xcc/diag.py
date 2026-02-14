from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    stage: str
    filename: str
    message: str
    line: int | None = None
    column: int | None = None
    code: str | None = None

    def __str__(self) -> str:
        if self.line is None or self.column is None:
            return f"{self.filename}: {self.stage}: {self.message}"
        return f"{self.filename}:{self.line}:{self.column}: {self.stage}: {self.message}"


class FrontendError(ValueError):
    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(str(diagnostic))
        self.diagnostic = diagnostic
