from dataclasses import dataclass
from typing import Literal, cast


@dataclass(frozen=True)
class IrIntType:
    bits: int
    signed: bool


@dataclass(frozen=True)
class IrStringType:
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


IrType = IrIntType | IrStringType | IrRecordType | IrBoolType | IrNoneType | IrTupleType


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
class IrName:
    name: str
    type: IrType


@dataclass(frozen=True)
class IrBinary:
    op: Literal["+", "-", "*"]
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
    type: IrTupleType


@dataclass(frozen=True)
class IrTupleSlice:
    value: "IrExpr"
    start: int | None
    stop: int | None

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
    | IrConstBool
    | IrConstNone
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


@dataclass(frozen=True)
class IrReturn:
    value: IrExpr


@dataclass(frozen=True)
class IrBranch:
    statements: tuple["IrStmt", ...]


@dataclass(frozen=True)
class IrIf:
    condition: IrExpr
    then_branch: IrBranch
    else_branch: IrBranch | None = None


@dataclass(frozen=True)
class IrForEach:
    target: str
    iterable: IrExpr
    body: IrBranch


@dataclass(frozen=True)
class IrWhile:
    condition: IrExpr
    body: IrBranch


@dataclass(frozen=True)
class IrPrint:
    value: IrExpr


@dataclass(frozen=True)
class IrRaise:
    exception: str
    message: IrExpr


IrStmt = IrAssign | IrReturn | IrIf | IrForEach | IrWhile | IrPrint | IrRaise


@dataclass(frozen=True)
class IrFunction:
    name: str
    params: tuple[IrParam, ...]
    return_type: IrType
    body: tuple[IrStmt, ...]


@dataclass(frozen=True)
class IrModule:
    filename: str
    records: tuple[IrRecord, ...]
    functions: tuple[IrFunction, ...]
    entry: str | None = None
