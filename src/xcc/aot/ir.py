from dataclasses import dataclass, field
from typing import Literal, cast


@dataclass(frozen=True)
class IrIntType:
    bits: int
    signed: bool


@dataclass(frozen=True)
class IrStringType:
    pass


@dataclass(frozen=True)
class IrBytesType:
    pass


@dataclass(frozen=True)
class IrFloatType:
    pass


@dataclass(frozen=True)
class IrRecordType:
    name: str


@dataclass(frozen=True)
class IrBoolType:
    pass


@dataclass(frozen=True)
class IrNoneType:
    pass


@dataclass(frozen=True)
class IrTupleType:
    elements: tuple["IrType", ...]


@dataclass(frozen=True)
class IrDictType:
    key: "IrType"
    value: "IrType"


IrType = (
    IrIntType
    | IrStringType
    | IrBytesType
    | IrFloatType
    | IrRecordType
    | IrBoolType
    | IrNoneType
    | IrTupleType
    | IrDictType
)


@dataclass(frozen=True)
class IrSourceSpan:
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None


@dataclass(frozen=True)
class IrParam:
    name: str
    type: IrType


@dataclass(frozen=True)
class IrField:
    name: str
    type: IrType


@dataclass(frozen=True)
class IrRecord:
    name: str
    fields: tuple[IrField, ...]
    bases: tuple[str, ...] = ()


@dataclass(frozen=True)
class IrConstInt:
    value: int
    type: IrIntType


@dataclass(frozen=True)
class IrConstString:
    value: str

    @property
    def type(self) -> IrStringType:
        return IrStringType()


@dataclass(frozen=True)
class IrConstBytes:
    value: bytes

    @property
    def type(self) -> IrBytesType:
        return IrBytesType()


@dataclass(frozen=True)
class IrConstFloat:
    value: float

    @property
    def type(self) -> IrFloatType:
        return IrFloatType()


@dataclass(frozen=True)
class IrConstBool:
    value: bool

    @property
    def type(self) -> IrBoolType:
        return IrBoolType()


@dataclass(frozen=True)
class IrConstNone:
    @property
    def type(self) -> IrNoneType:
        return IrNoneType()


@dataclass(frozen=True)
class IrEnumMember:
    enum: str
    member: str

    @property
    def type(self) -> IrRecordType:
        return IrRecordType("Enum")


@dataclass(frozen=True)
class IrName:
    name: str
    type: IrType


@dataclass(frozen=True)
class IrBinary:
    op: Literal["+", "-", "*", "//", "%", "<<", ">>", "|", "&", "^"]
    left: "IrExpr"
    right: "IrExpr"
    type: IrType


@dataclass(frozen=True)
class IrGetField:
    value: "IrExpr"
    field: str
    type: IrType


@dataclass(frozen=True)
class IrConstructRecord:
    record: str
    args: tuple["IrExpr", ...]
    type: IrRecordType


@dataclass(frozen=True)
class IrCall:
    target: str
    args: tuple["IrExpr", ...]
    type: IrType


@dataclass(frozen=True)
class IrTuple:
    elements: tuple["IrExpr", ...]
    type: IrTupleType | IrDictType


@dataclass(frozen=True)
class IrTupleSlice:
    value: "IrExpr"
    start: "IrExpr | None"
    stop: "IrExpr | None"

    @property
    def type(self) -> IrTupleType:
        return cast(IrTupleType, self.value.type)


@dataclass(frozen=True)
class IrStringConcat:
    parts: tuple["IrExpr", ...]

    @property
    def type(self) -> IrStringType:
        return IrStringType()


@dataclass(frozen=True)
class IrStringJoin:
    separator: "IrExpr"
    values: "IrExpr"

    @property
    def type(self) -> IrStringType:
        return IrStringType()


IrExpr = (
    IrConstInt
    | IrConstString
    | IrConstBytes
    | IrConstFloat
    | IrConstBool
    | IrConstNone
    | IrEnumMember
    | IrName
    | IrBinary
    | IrGetField
    | IrConstructRecord
    | IrCall
    | IrTuple
    | IrTupleSlice
    | IrStringConcat
    | IrStringJoin
)


@dataclass(frozen=True)
class IrAssign:
    target: str
    value: IrExpr
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)
    chain: bool = field(default=False, repr=False)


@dataclass(frozen=True)
class IrSetItem:
    target: IrExpr
    index: IrExpr
    value: IrExpr
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


@dataclass(frozen=True)
class IrReturn:
    value: IrExpr
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


@dataclass(frozen=True)
class IrBranch:
    statements: tuple["IrStmt", ...]


@dataclass(frozen=True)
class IrIf:
    condition: IrExpr
    then_branch: IrBranch
    else_branch: IrBranch | None = None
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


@dataclass(frozen=True)
class IrForEach:
    target: str
    iterable: IrExpr
    body: IrBranch
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


@dataclass(frozen=True)
class IrWhile:
    condition: IrExpr
    body: IrBranch
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


@dataclass(frozen=True)
class IrBreak:
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


@dataclass(frozen=True)
class IrContinue:
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


@dataclass(frozen=True)
class IrPrint:
    value: IrExpr
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


@dataclass(frozen=True)
class IrRaise:
    exception: str
    message: IrExpr
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)
    payload: IrExpr | None = None


@dataclass(frozen=True)
class IrReraise:
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


@dataclass(frozen=True)
class IrExceptHandler:
    exceptions: tuple[str, ...]
    target: str | None
    body: IrBranch


@dataclass(frozen=True)
class IrTry:
    body: IrBranch
    handlers: tuple[IrExceptHandler, ...] = ()
    orelse: IrBranch = IrBranch(())
    finalbody: IrBranch = IrBranch(())
    span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


IrStmt = (
    IrAssign
    | IrSetItem
    | IrReturn
    | IrIf
    | IrForEach
    | IrWhile
    | IrBreak
    | IrContinue
    | IrPrint
    | IrRaise
    | IrReraise
    | IrTry
)


@dataclass(frozen=True)
class IrFunction:
    name: str
    params: tuple[IrParam, ...]
    return_type: IrType
    body: tuple[IrStmt, ...]
    source_filename: str = field(default="", compare=False)
    source_span: IrSourceSpan = field(default=IrSourceSpan(), compare=False)


@dataclass(frozen=True)
class IrModule:
    filename: str
    records: tuple[IrRecord, ...]
    functions: tuple[IrFunction, ...]
    entry: str | None = None


def qualify_ir_entry(module: IrModule, qualified_name: str) -> IrModule:
    if module.entry is None:
        raise ValueError("cannot qualify an IR module without an entry")
    functions: list[IrFunction] = []
    found = False
    for function in module.functions:
        if function.name == module.entry:
            functions.append(
                IrFunction(
                    qualified_name,
                    function.params,
                    function.return_type,
                    function.body,
                    function.source_filename,
                    function.source_span,
                )
            )
            found = True
        else:
            functions.append(function)
    if not found:
        raise ValueError(f"missing IR entry: {module.entry}")
    return IrModule(
        module.filename,
        module.records,
        tuple(functions),
        entry=qualified_name,
    )


def validate_ir_module(module: IrModule) -> None:
    """Reject symbol-table inconsistencies before native LLVM emission."""
    record_names: set[str] = set()
    for record in module.records:
        if record.name in record_names:
            raise ValueError(f"duplicate IR record: {record.name}")
        record_names.add(record.name)
    function_names: set[str] = set()
    for function in module.functions:
        if function.name in function_names:
            raise ValueError(f"duplicate IR function: {function.name}")
        function_names.add(function.name)
    if module.entry is not None and module.entry not in function_names:
        raise ValueError(f"missing IR entry: {module.entry}")
