from dataclasses import dataclass

TypeOp = tuple[str, int]
POINTER_OP: TypeOp = ("ptr", 0)


def _ops_from_legacy(pointer_depth: int, array_lengths: tuple[int, ...]) -> tuple[TypeOp, ...]:
    ops: list[TypeOp] = [("arr", length) for length in array_lengths]
    ops.extend(POINTER_OP for _ in range(pointer_depth))
    return tuple(ops)


@dataclass(frozen=True)
class Type:
    name: str
    pointer_depth: int = 0
    array_lengths: tuple[int, ...] = ()
    declarator_ops: tuple[TypeOp, ...] = ()

    def __post_init__(self) -> None:
        if self.declarator_ops:
            pointer_depth = sum(1 for kind, _ in self.declarator_ops if kind == "ptr")
            array_lengths = tuple(length for kind, length in self.declarator_ops if kind == "arr")
            object.__setattr__(self, "pointer_depth", pointer_depth)
            object.__setattr__(self, "array_lengths", array_lengths)
            return
        object.__setattr__(
            self,
            "declarator_ops",
            _ops_from_legacy(self.pointer_depth, self.array_lengths),
        )

    def __str__(self) -> str:
        suffix = []
        for kind, value in reversed(self.declarator_ops):
            if kind == "ptr":
                suffix.append("*")
            else:
                suffix.append(f"[{value}]")
        return f"{self.name}{''.join(suffix)}"

    def pointer_to(self) -> "Type":
        return Type(self.name, declarator_ops=(POINTER_OP,) + self.declarator_ops)

    def pointee(self) -> "Type | None":
        if not self.declarator_ops or self.declarator_ops[0][0] != "ptr":
            return None
        return Type(self.name, declarator_ops=self.declarator_ops[1:])

    def array_of(self, length: int) -> "Type":
        return Type(self.name, declarator_ops=(("arr", length),) + self.declarator_ops)

    def element_type(self) -> "Type | None":
        if not self.declarator_ops or self.declarator_ops[0][0] != "arr":
            return None
        return Type(self.name, declarator_ops=self.declarator_ops[1:])

    def decay_parameter_array(self) -> "Type":
        if not self.declarator_ops or self.declarator_ops[0][0] != "arr":
            return self
        return Type(self.name, declarator_ops=(POINTER_OP,) + self.declarator_ops[1:])

    def is_array(self) -> bool:
        return bool(self.declarator_ops) and self.declarator_ops[0][0] == "arr"


INT = Type("int")
VOID = Type("void")
