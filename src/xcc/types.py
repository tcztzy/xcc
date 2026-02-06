from dataclasses import dataclass


@dataclass(frozen=True)
class Type:
    name: str
    pointer_depth: int = 0
    array_lengths: tuple[int, ...] = ()

    def __str__(self) -> str:
        suffix = "".join(f"[{length}]" for length in self.array_lengths)
        return f"{self.name}{'*' * self.pointer_depth}{suffix}"

    def pointer_to(self) -> "Type":
        return Type(self.name, self.pointer_depth + 1, self.array_lengths)

    def pointee(self) -> "Type | None":
        if self.pointer_depth == 0:
            return None
        return Type(self.name, self.pointer_depth - 1, self.array_lengths)

    def array_of(self, length: int) -> "Type":
        return Type(self.name, self.pointer_depth, self.array_lengths + (length,))

    def element_type(self) -> "Type | None":
        if not self.array_lengths:
            return None
        return Type(self.name, self.pointer_depth, self.array_lengths[1:])


INT = Type("int")
VOID = Type("void")
