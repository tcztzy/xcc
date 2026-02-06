from dataclasses import dataclass


@dataclass(frozen=True)
class Type:
    name: str
    pointer_depth: int = 0

    def __str__(self) -> str:
        return f"{self.name}{'*' * self.pointer_depth}"

    def pointer_to(self) -> "Type":
        return Type(self.name, self.pointer_depth + 1)

    def pointee(self) -> "Type | None":
        if self.pointer_depth == 0:
            return None
        return Type(self.name, self.pointer_depth - 1)


INT = Type("int")
VOID = Type("void")
