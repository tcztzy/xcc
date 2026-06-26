from dataclasses import dataclass
from typing import Literal


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


IrType = IrIntType | IrStringType | IrRecordType


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


IrExpr = IrConstInt | IrConstString | IrName | IrBinary | IrGetField | IrConstructRecord | IrCall


@dataclass(frozen=True)
class IrAssign:
    target: str
    value: IrExpr


@dataclass(frozen=True)
class IrReturn:
    value: IrExpr


IrStmt = IrAssign | IrReturn


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
