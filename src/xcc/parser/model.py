from dataclasses import dataclass

from xcc.ast import StorageClass
from xcc.lexer import Token


@dataclass(frozen=True)
class ParserError(ValueError):
    message: str
    token: Token

    def __str__(self) -> str:
        return f"{self.message} at {self.token.line}:{self.token.column}"


@dataclass(frozen=True)
class DeclSpecInfo:
    is_typedef: bool = False
    storage_class: StorageClass | None = None
    storage_class_token: Token | None = None
    alignment: int | None = None
    alignment_token: Token | None = None
    is_thread_local: bool = False
    is_inline: bool = False
    is_noreturn: bool = False
