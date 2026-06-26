import ast
from dataclasses import dataclass

_BUILTIN_TYPES = {"bool", "int", "None", "str"}
_WIDTH_ALIASES = {
    "int8": (8, True),
    "int16": (16, True),
    "int32": (32, True),
    "int64": (64, True),
    "uint8": (8, False),
    "uint16": (16, False),
    "uint32": (32, False),
    "uint64": (64, False),
    "usize": (64, False),
}


@dataclass(frozen=True)
class AotType:
    name: str
    bits: int | None = None
    signed: bool | None = None


@dataclass(frozen=True)
class AotClassInfo:
    name: str
    fields: dict[str, AotType]


@dataclass(frozen=True)
class AotFunctionInfo:
    name: str
    parameters: tuple[tuple[str, str], ...]
    return_type: AotType


@dataclass(frozen=True)
class AotTypeAnalysis:
    filename: str
    width_aliases: dict[str, AotType]
    classes: dict[str, AotClassInfo]
    functions: dict[str, AotFunctionInfo]


def width_alias_type(name: str) -> AotType | None:
    entry = _WIDTH_ALIASES.get(name)
    if entry is None:
        return None
    bits, signed = entry
    return AotType(name, bits=bits, signed=signed)


def annotation_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    return ast.unparse(node)


def is_builtin_type_name(name: str) -> bool:
    return name in _BUILTIN_TYPES
