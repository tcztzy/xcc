from dataclasses import dataclass

FunctionParams = tuple[tuple["Type", ...] | None, bool]
TypeOp = tuple[str, int | FunctionParams]
POINTER_OP: TypeOp = ("ptr", 0)


def _format_function_params(params: FunctionParams) -> str:
    parameter_types, is_variadic = params
    if parameter_types is None:
        return "()"
    if not parameter_types:
        return "(void)"
    text = ",".join(str(param) for param in parameter_types)
    if is_variadic:
        return f"({text},...)"
    return f"({text})"


@dataclass(frozen=True)
class Type:
    name: str
    declarator_ops: tuple[TypeOp, ...] = ()
    qualifiers: tuple[str, ...] = ()

    def __str__(self) -> str:
        prefix = "" if not self.qualifiers else f"{' '.join(self.qualifiers)} "
        suffix: list[str] = []
        for kind, value in reversed(self.declarator_ops):
            if kind == "ptr":
                suffix.append("*")
            elif kind == "arr":
                assert isinstance(value, int)
                suffix.append(f"[{value}]")
            else:
                assert isinstance(value, tuple) and len(value) == 2
                suffix.append(_format_function_params(value))
        return f"{prefix}{self.name}{''.join(suffix)}"

    def pointer_to(self) -> "Type":
        return Type(
            self.name,
            declarator_ops=(POINTER_OP,) + self.declarator_ops,
            qualifiers=self.qualifiers,
        )

    def pointee(self) -> "Type | None":
        ops = self.declarator_ops
        if not ops or ops[0][0] != "ptr":
            return None
        return Type(self.name, declarator_ops=ops[1:], qualifiers=self.qualifiers)

    def array_of(self, length: int) -> "Type":
        return Type(
            self.name,
            declarator_ops=(("arr", length),) + self.declarator_ops,
            qualifiers=self.qualifiers,
        )

    def element_type(self) -> "Type | None":
        ops = self.declarator_ops
        if not ops or ops[0][0] != "arr":
            return None
        return Type(self.name, declarator_ops=ops[1:], qualifiers=self.qualifiers)

    def function_of(
        self,
        params: tuple["Type", ...] | None,
        *,
        is_variadic: bool = False,
    ) -> "Type":
        return Type(
            self.name,
            declarator_ops=(("fn", (params, is_variadic)),) + self.declarator_ops,
            qualifiers=self.qualifiers,
        )

    def callable_signature(self) -> "tuple[Type, FunctionParams] | None":
        ops = self.declarator_ops
        if ops and ops[0][0] == "ptr":
            ops = ops[1:]
        if not ops or ops[0][0] != "fn":
            return None
        params = ops[0][1]
        assert isinstance(params, tuple) and len(params) == 2
        return Type(self.name, declarator_ops=ops[1:], qualifiers=self.qualifiers), params

    def decay_parameter_type(self) -> "Type":
        ops = self.declarator_ops
        if not ops:
            return self
        if ops[0][0] == "arr":
            return Type(
                self.name,
                declarator_ops=(POINTER_OP,) + ops[1:],
                qualifiers=self.qualifiers,
            )
        if ops[0][0] == "fn":
            return Type(
                self.name,
                declarator_ops=(POINTER_OP,) + ops,
                qualifiers=self.qualifiers,
            )
        return self

    def is_array(self) -> bool:
        ops = self.declarator_ops
        return bool(ops) and ops[0][0] == "arr"


INT: Type = Type("int")
UINT: Type = Type("unsigned int")
SHORT: Type = Type("short")
USHORT: Type = Type("unsigned short")
LONG: Type = Type("long")
ULONG: Type = Type("unsigned long")
LLONG: Type = Type("long long")
ULLONG: Type = Type("unsigned long long")
INT128: Type = Type("__int128_t")
UINT128: Type = Type("__uint128_t")
EVM_UINT256: Type = Type("__evm_uint256")
EVM_ADDRESS: Type = Type("__evm_address")
CHAR: Type = Type("char")
UCHAR: Type = Type("unsigned char")
BOOL: Type = Type("_Bool")
FLOAT: Type = Type("float")
DOUBLE: Type = Type("double")
LONGDOUBLE: Type = Type("long double")
VOID: Type = Type("void")
