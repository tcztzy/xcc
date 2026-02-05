from dataclasses import dataclass


@dataclass(frozen=True)
class Type:
    name: str

    def __str__(self) -> str:
        return self.name


INT = Type("int")
VOID = Type("void")
