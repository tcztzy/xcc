from dataclasses import dataclass, field
from typing import Literal

StorageClass = Literal["auto", "register", "static", "extern", "typedef"]


class Expr:
    pass


class Stmt:
    pass


@dataclass(frozen=True)
class ArrayDecl:
    length: "Expr | int | None"
    qualifiers: tuple[str, ...] = ()
    has_static_bound: bool = False


FunctionDeclarator = tuple[tuple["TypeSpec", ...] | None, bool]
EnumMember = tuple[str, "Expr | None"]
DeclaratorValue = int | ArrayDecl | FunctionDeclarator
DeclaratorOp = tuple[str, DeclaratorValue]
GenericAssociation = tuple["TypeSpec | None", "Expr"]
Designator = tuple[str, "Expr | str"]


def _ops_from_legacy(
    pointer_depth: int,
    array_lengths: tuple[int, ...],
) -> tuple[DeclaratorOp, ...]:
    ops: list[DeclaratorOp] = [("arr", length) for length in array_lengths]
    ops.extend(("ptr", 0) for _ in range(pointer_depth))
    return tuple(ops)


@dataclass(frozen=True)
class TranslationUnit:
    functions: list["FunctionDef"]
    declarations: list["Stmt"] = field(default_factory=list)
    externals: list["FunctionDef | Stmt"] = field(default_factory=list)


@dataclass(frozen=True)
class RecordMemberDecl:
    type_spec: "TypeSpec"
    name: str | None
    alignment: int | None = None
    bit_width_expr: "Expr | None" = None


@dataclass(frozen=True)
class TypeSpec:
    name: str
    pointer_depth: int = 0
    array_lengths: tuple[int, ...] = ()
    declarator_ops: tuple[DeclaratorOp, ...] = ()
    qualifiers: tuple[str, ...] = ()
    is_atomic: bool = False
    atomic_target: "TypeSpec | None" = field(default=None, compare=False)
    enum_tag: str | None = None
    enum_members: tuple[EnumMember, ...] = ()
    record_tag: str | None = None
    record_members: tuple[RecordMemberDecl, ...] = ()
    source_line: int | None = field(default=None, compare=False)
    source_column: int | None = field(default=None, compare=False)
    typeof_expr: "Expr | None" = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.declarator_ops:
            pointer_depth = sum(1 for kind, _ in self.declarator_ops if kind == "ptr")
            array_lengths = tuple(
                int(length)
                for kind, length in self.declarator_ops
                if kind == "arr" and isinstance(length, int)
            )
            object.__setattr__(self, "pointer_depth", pointer_depth)
            object.__setattr__(self, "array_lengths", array_lengths)
        else:
            object.__setattr__(
                self,
                "declarator_ops",
                _ops_from_legacy(self.pointer_depth, self.array_lengths),
            )
        if self.record_members:
            normalized_members: list[RecordMemberDecl] = []
            for member in self.record_members:
                if isinstance(member, RecordMemberDecl):
                    normalized_members.append(member)
                    continue
                if isinstance(member, tuple) and len(member) == 2:
                    normalized_members.append(RecordMemberDecl(member[0], member[1]))
                    continue
                if isinstance(member, tuple) and len(member) == 3:
                    normalized_members.append(RecordMemberDecl(member[0], member[1], member[2]))
                    continue
                if isinstance(member, tuple) and len(member) == 4:
                    normalized_members.append(
                        RecordMemberDecl(member[0], member[1], member[2], member[3])
                    )
                    continue
                raise TypeError("Invalid record member declaration")
            object.__setattr__(self, "record_members", tuple(normalized_members))


@dataclass(frozen=True)
class Param:
    type_spec: TypeSpec
    name: str | None


@dataclass(frozen=True)
class FunctionDef:
    return_type: TypeSpec
    name: str
    params: list[Param]
    body: "CompoundStmt | None"
    storage_class: Literal["static", "extern"] | None = None
    is_thread_local: bool = False
    is_inline: bool = False
    is_noreturn: bool = False
    has_prototype: bool = True
    is_variadic: bool = False
    is_overloadable: bool = False


@dataclass(frozen=True)
class CompoundStmt(Stmt):
    statements: list[Stmt]


@dataclass(frozen=True)
class IfStmt(Stmt):
    condition: Expr
    then_body: Stmt
    else_body: Stmt | None


@dataclass(frozen=True)
class WhileStmt(Stmt):
    condition: Expr
    body: Stmt


@dataclass(frozen=True)
class DoWhileStmt(Stmt):
    body: Stmt
    condition: Expr


@dataclass(frozen=True)
class ForStmt(Stmt):
    init: Stmt | Expr | None
    condition: Expr | None
    post: Expr | None
    body: Stmt


@dataclass(frozen=True)
class SwitchStmt(Stmt):
    condition: Expr
    body: Stmt


@dataclass(frozen=True)
class CaseStmt(Stmt):
    value: Expr
    body: Stmt


@dataclass(frozen=True)
class DefaultStmt(Stmt):
    body: Stmt


@dataclass(frozen=True)
class LabelStmt(Stmt):
    name: str
    body: Stmt


@dataclass(frozen=True)
class GotoStmt(Stmt):
    label: str


@dataclass(frozen=True)
class IndirectGotoStmt(Stmt):
    target: "Expr"


@dataclass(frozen=True)
class BreakStmt(Stmt):
    pass


@dataclass(frozen=True)
class ContinueStmt(Stmt):
    pass


@dataclass(frozen=True)
class ReturnStmt(Stmt):
    value: Expr | None


@dataclass(frozen=True)
class StaticAssertDecl(Stmt):
    condition: Expr
    message: "StringLiteral"


@dataclass(frozen=True)
class ExprStmt(Stmt):
    expr: Expr


@dataclass(frozen=True)
class BinaryExpr(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class ConditionalExpr(Expr):
    condition: Expr
    then_expr: Expr
    else_expr: Expr


@dataclass(frozen=True)
class CommaExpr(Expr):
    left: Expr
    right: Expr


@dataclass(frozen=True)
class AssignExpr(Expr):
    op: str
    target: Expr
    value: Expr


@dataclass(frozen=True)
class UnaryExpr(Expr):
    op: str
    operand: Expr


@dataclass(frozen=True)
class UpdateExpr(Expr):
    op: str
    operand: Expr
    is_postfix: bool


@dataclass(frozen=True)
class CallExpr(Expr):
    callee: Expr
    args: list[Expr]


@dataclass(frozen=True)
class SubscriptExpr(Expr):
    base: Expr
    index: Expr


@dataclass(frozen=True)
class MemberExpr(Expr):
    base: Expr
    member: str
    through_pointer: bool


@dataclass(frozen=True)
class SizeofExpr(Expr):
    expr: Expr | None
    type_spec: TypeSpec | None


@dataclass(frozen=True)
class AlignofExpr(Expr):
    expr: Expr | None
    type_spec: TypeSpec | None


@dataclass(frozen=True)
class CastExpr(Expr):
    type_spec: TypeSpec
    expr: Expr


@dataclass(frozen=True)
class CompoundLiteralExpr(Expr):
    type_spec: TypeSpec
    initializer: "InitList"


@dataclass(frozen=True)
class StatementExpr(Expr):
    body: CompoundStmt


@dataclass(frozen=True)
class GenericExpr(Expr):
    control: Expr
    associations: tuple[GenericAssociation, ...]
    association_source_locations: tuple[tuple[int | None, int | None], ...] = field(
        default_factory=tuple,
        compare=False,
    )


@dataclass(frozen=True)
class IntLiteral(Expr):
    value: str


@dataclass(frozen=True)
class FloatLiteral(Expr):
    value: str


@dataclass(frozen=True)
class CharLiteral(Expr):
    value: str


@dataclass(frozen=True)
class StringLiteral(Expr):
    value: str


@dataclass(frozen=True)
class Identifier(Expr):
    name: str


@dataclass(frozen=True)
class LabelAddressExpr(Expr):
    label: str


@dataclass(frozen=True)
class BuiltinOffsetofExpr(Expr):
    type_spec: TypeSpec
    member: str


@dataclass(frozen=True)
class NullStmt(Stmt):
    pass


@dataclass(frozen=True)
class DeclGroupStmt(Stmt):
    declarations: list["DeclStmt | TypedefDecl"]


@dataclass(frozen=True)
class DeclStmt(Stmt):
    type_spec: TypeSpec
    name: str | None
    init: "Expr | InitList | None"
    alignment: int | None = None
    storage_class: StorageClass | None = None
    is_thread_local: bool = False


@dataclass(frozen=True)
class TypedefDecl(Stmt):
    type_spec: TypeSpec
    name: str


@dataclass(frozen=True)
class InitItem:
    designators: tuple[Designator, ...]
    initializer: "Expr | InitList"


@dataclass(frozen=True)
class InitList:
    items: tuple[InitItem, ...]
