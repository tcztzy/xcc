"""A small, standard-library-only LLVM object model for XCC's native emitter.

Types, globals, functions, blocks, instructions, and references remain Python
objects until final rendering. Text parts carry LLVM punctuation and attributes;
semantic ``@global`` and ``%local`` references must use their symbol objects.
"""

from dataclasses import dataclass, field
from typing import Literal

LlvmSymbolKind = Literal["function", "global"]
LlvmLocalKind = Literal["parameter", "value", "block"]


@dataclass(frozen=True)
class LlvmType:
    text: str

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class LlvmParameter:
    type: LlvmType
    name: str | None = None

    def render(self) -> str:
        if self.name is None:
            return self.type.text
        return f"{self.type.text} %{self.name}"


@dataclass(frozen=True)
class LlvmFunctionType:
    return_type: LlvmType
    parameters: tuple[LlvmParameter, ...]
    variadic: bool = False

    def render_parameters(self) -> str:
        rendered = [parameter.render() for parameter in self.parameters]
        if self.variadic:
            rendered.append("...")
        return ", ".join(rendered)


@dataclass
class LlvmSymbol:
    name: str
    kind: LlvmSymbolKind
    imported: bool = False

    def render(self) -> str:
        return f"@{self.name}"


@dataclass
class LlvmLocal:
    name: str
    kind: LlvmLocalKind | None = None

    def render(self) -> str:
        return f"%{self.name}"


LlvmPart = str | LlvmSymbol | LlvmLocal


def _validate_parts(parts: tuple[LlvmPart, ...]) -> None:
    for part in parts:
        if isinstance(part, str) and ("@" in part or "%" in part):
            raise ValueError(f"LLVM references must use LlvmSymbol or LlvmLocal objects: {part!r}")


def _render_parts(parts: tuple[LlvmPart, ...]) -> str:
    rendered: list[str] = []
    for part in parts:
        if isinstance(part, str):
            rendered.append(part)
        # Keep these branches separate: native AOT dispatch must see a concrete
        # receiver type instead of synthesizing a union-method symbol.
        elif isinstance(part, LlvmSymbol):  # noqa: SIM114
            rendered.append(part.render())
        elif isinstance(part, LlvmLocal):
            rendered.append(part.render())
        else:
            raise TypeError(f"unsupported LLVM part: {part}")
    return "".join(rendered)


@dataclass
class LlvmInstruction:
    result: LlvmLocal | None
    opcode: str
    parts: tuple[LlvmPart, ...]
    continuations: list[tuple[LlvmPart, ...]] = field(default_factory=list)

    def render(self) -> str:
        result = "" if self.result is None else f"{self.result.render()} = "
        lines = [f"  {result}{self.opcode}{_render_parts(self.parts)}"]
        lines.extend(f"  {_render_parts(parts)}" for parts in self.continuations)
        return "\n".join(lines)

    def references(self, symbol: LlvmSymbol) -> bool:
        if any(part is symbol for part in self.parts):
            return True
        return any(part is symbol for line in self.continuations for part in line)

    def call_target(self) -> LlvmSymbol | None:
        if self.opcode != "call":
            return None
        for part in self.parts:
            if isinstance(part, LlvmSymbol) and part.kind == "function":
                return part
        return None

    def replace_call_target(self, source: LlvmSymbol, target: LlvmSymbol) -> bool:
        if self.opcode != "call":
            return False
        rewritten = list(self.parts)
        for index, part in enumerate(rewritten):
            if isinstance(part, LlvmSymbol) and part.kind == "function":
                if part is not source:
                    return False
                rewritten[index] = target
                self.parts = tuple(rewritten)
                return True
        return False


@dataclass
class LlvmBlock:
    function: "LlvmFunction"
    label: LlvmLocal
    instructions: list[LlvmInstruction] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.label.name

    def emit(self, result: str | None, opcode: str, *parts: LlvmPart) -> LlvmInstruction:
        _validate_parts(parts)
        local = None if result is None else self.function.define_local(result, "value")
        instruction = LlvmInstruction(local, opcode, tuple(parts))
        self.instructions.append(instruction)
        return instruction

    def continue_(self, *parts: LlvmPart) -> None:
        if not self.instructions:
            raise ValueError(f"block %{self.name} has no instruction to continue")
        _validate_parts(parts)
        self.instructions[-1].continuations.append(tuple(parts))

    def render(self) -> str:
        lines = [f"{self.name}:"]
        lines.extend(instruction.render() for instruction in self.instructions)
        return "\n".join(lines)


@dataclass
class LlvmFunction:
    symbol: LlvmSymbol
    type: LlvmFunctionType
    linkage: str = ""
    declaration: bool = False
    blocks: list[LlvmBlock] = field(default_factory=list)
    _locals: dict[str, LlvmLocal] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for parameter in self.type.parameters:
            if parameter.name is not None:
                self.define_local(parameter.name, "parameter")

    def local(self, name: str) -> LlvmLocal:
        existing = self._locals.get(name)
        if existing is not None:
            return existing
        local = LlvmLocal(name)
        self._locals[name] = local
        return local

    def define_local(self, name: str, kind: LlvmLocalKind) -> LlvmLocal:
        local = self.local(name)
        if local.kind is not None:
            raise ValueError(f"duplicate local %{name} in function {self.symbol.render()}")
        local.kind = kind
        return local

    def append_block(self, name: str) -> LlvmBlock:
        if self.declaration:
            raise ValueError(f"cannot add a block to declaration {self.symbol.render()}")
        block = LlvmBlock(self, self.define_local(name, "block"))
        self.blocks.append(block)
        return block

    def validate(self) -> None:
        if self.declaration:
            if self.blocks:
                raise ValueError(f"declaration {self.symbol.render()} has a body")
            return
        if not self.blocks:
            raise ValueError(f"definition {self.symbol.render()} has no blocks")
        unresolved = sorted(name for name, local in self._locals.items() if local.kind is None)
        if unresolved:
            rendered = ", ".join(f"%{name}" for name in unresolved)
            raise ValueError(f"unresolved locals in function {self.symbol.render()}: {rendered}")
        registered = {id(local) for local in self._locals.values()}
        for block in self.blocks:
            if id(block.label) not in registered:
                raise ValueError(
                    f"foreign LLVM local in {self.symbol.render()}: {block.label.render()}"
                )
            for instruction in block.instructions:
                if instruction.result is not None and id(instruction.result) not in registered:
                    raise ValueError(
                        f"foreign LLVM local in {self.symbol.render()}: "
                        f"{instruction.result.render()}"
                    )
                parts = list(instruction.parts)
                for continuation in instruction.continuations:
                    parts.extend(continuation)
                for part in parts:
                    if isinstance(part, LlvmLocal) and id(part) not in registered:
                        raise ValueError(
                            f"foreign LLVM local in {self.symbol.render()}: {part.render()}"
                        )

    def render(self) -> str:
        parameters = self.type.render_parameters()
        if self.declaration:
            return f"declare {self.type.return_type.text} {self.symbol.render()}({parameters})"
        linkage = f"{self.linkage} " if self.linkage else ""
        header = (
            f"define {linkage}{self.type.return_type.text} {self.symbol.render()}({parameters}) {{"
        )
        body = "\n".join(block.render() for block in self.blocks)
        return f"{header}\n{body}\n}}"


@dataclass
class LlvmGlobal:
    symbol: LlvmSymbol
    definition_parts: tuple[LlvmPart, ...]

    @property
    def definition(self) -> str:
        return _render_parts(self.definition_parts)

    def render(self) -> str:
        return f"{self.symbol.render()} = {_render_parts(self.definition_parts)}"


@dataclass(frozen=True)
class LlvmSymbolUse:
    function: str
    block: str
    instruction: int
    opcode: str


class LlvmModule:
    def __init__(self) -> None:
        self._symbols: dict[str, LlvmSymbol] = {}
        self.globals: list[LlvmGlobal] = []
        self.declarations: list[LlvmFunction] = []
        self.functions: list[LlvmFunction] = []

    def _register_symbol(
        self,
        name: str,
        kind: LlvmSymbolKind,
        imported: bool = False,
    ) -> LlvmSymbol:
        if name in self._symbols:
            raise ValueError(f"duplicate LLVM symbol: @{name}")
        symbol = LlvmSymbol(name, kind, imported)
        self._symbols[name] = symbol
        return symbol

    def import_function(self, name: str) -> LlvmSymbol:
        return self._register_symbol(name, "function", imported=True)

    def add_global(self, name: str, *definition: LlvmPart) -> LlvmGlobal:
        if not definition:
            raise ValueError(f"LLVM global has no definition: @{name}")
        for part in definition:
            if isinstance(part, str) and "@" in part:
                raise ValueError(
                    "LLVM global references must use symbol objects instead of raw text"
                )
        value = LlvmGlobal(self._register_symbol(name, "global"), tuple(definition))
        self.globals.append(value)
        return value

    def declare_function(
        self,
        name: str,
        return_type: LlvmType,
        parameters: tuple[LlvmParameter, ...],
        variadic: bool = False,
    ) -> LlvmFunction:
        function = LlvmFunction(
            self._register_symbol(name, "function"),
            LlvmFunctionType(return_type, parameters, variadic),
            declaration=True,
        )
        self.declarations.append(function)
        return function

    def define_function(
        self,
        name: str,
        return_type: LlvmType,
        parameters: tuple[LlvmParameter, ...],
        linkage: str = "",
    ) -> LlvmFunction:
        function = LlvmFunction(
            self._register_symbol(name, "function"),
            LlvmFunctionType(return_type, parameters),
            linkage=linkage,
        )
        self.functions.append(function)
        return function

    def symbol(self, name: str) -> LlvmSymbol:
        try:
            return self._symbols[name]
        except KeyError:
            raise ValueError(f"unresolved LLVM symbol: @{name}") from None

    def function(self, name: str) -> LlvmFunction:
        symbol = self.symbol(name)
        if symbol.kind != "function":
            raise ValueError(f"LLVM symbol is not a function: @{name}")
        for function in self.declarations:
            if function.symbol is symbol:
                return function
        for function in self.functions:
            if function.symbol is symbol:
                return function
        raise ValueError(f"imported LLVM function has no body: @{name}")

    def global_value(self, name: str) -> LlvmGlobal:
        symbol = self.symbol(name)
        if symbol.kind != "global":
            raise ValueError(f"LLVM symbol is not a global: @{name}")
        for value in self.globals:
            if value.symbol is symbol:
                return value
        raise ValueError(f"LLVM global has no definition: @{name}")

    def rename_symbol(self, symbol: LlvmSymbol, name: str) -> None:
        if self._symbols.get(symbol.name) is not symbol:
            raise ValueError(f"symbol does not belong to this module: {symbol.render()}")
        if name in self._symbols:
            raise ValueError(f"duplicate LLVM symbol: @{name}")
        self._symbols.pop(symbol.name)
        symbol.name = name
        self._symbols[name] = symbol

    def redirect_calls(self, source: LlvmSymbol, target: LlvmSymbol) -> int:
        if source.kind != "function" or target.kind != "function":
            raise ValueError("call redirection requires function symbols")
        if self._symbols.get(source.name) is not source:
            raise ValueError(f"source symbol does not belong to module: {source.render()}")
        if self._symbols.get(target.name) is not target:
            raise ValueError(f"target symbol does not belong to module: {target.render()}")
        replacements = 0
        for function in self.functions:
            for block in function.blocks:
                for instruction in block.instructions:
                    if instruction.replace_call_target(source, target):
                        replacements += 1
        return replacements

    def symbol_uses(self, symbol: LlvmSymbol) -> tuple[LlvmSymbolUse, ...]:
        if self._symbols.get(symbol.name) is not symbol:
            raise ValueError(f"symbol does not belong to this module: {symbol.render()}")
        uses: list[LlvmSymbolUse] = []
        for function in self.functions:
            for block in function.blocks:
                for index, instruction in enumerate(block.instructions):
                    if instruction.references(symbol):
                        uses.append(
                            LlvmSymbolUse(
                                function.symbol.name,
                                block.name,
                                index,
                                instruction.opcode,
                            )
                        )
        return tuple(uses)

    def validate(self) -> None:
        registered = {id(symbol) for symbol in self._symbols.values()}
        for value in self.globals:
            for part in value.definition_parts:
                if isinstance(part, LlvmSymbol) and id(part) not in registered:
                    raise ValueError(
                        f"foreign LLVM symbol in {value.symbol.render()}: {part.render()}"
                    )
        for declaration in self.declarations:
            declaration.validate()
        for function in self.functions:
            function.validate()
            for block in function.blocks:
                for instruction in block.instructions:
                    _validate_parts(instruction.parts)
                    parts = list(instruction.parts)
                    for continuation in instruction.continuations:
                        _validate_parts(continuation)
                        parts.extend(continuation)
                    for part in parts:
                        if isinstance(part, LlvmSymbol) and id(part) not in registered:
                            raise ValueError(
                                f"foreign LLVM symbol in {function.symbol.render()}: "
                                f"{part.render()}"
                            )

    def render(self) -> str:
        self.validate()
        groups: list[str] = []
        if self.globals:
            groups.append("\n".join(value.render() for value in self.globals))
        if self.declarations:
            groups.append("\n".join(function.render() for function in self.declarations))
        if self.functions:
            groups.append("\n\n".join(function.render() for function in self.functions))
        return "\n\n".join(groups)
