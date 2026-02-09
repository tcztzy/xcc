from dataclasses import dataclass, field

FunctionDeclarator = tuple[tuple["TypeSpec", ...] | None, bool]
EnumMember = tuple[str, int]
RecordMember = tuple["TypeSpec", str]
DeclaratorValue = int | FunctionDeclarator
DeclaratorOp = tuple[str, DeclaratorValue]


def _ops_from_legacy(
    pointer_depth: int,
    array_lengths: tuple[int, ...],
) -> tuple[DeclaratorOp, ...]:
    ops: list[DeclaratorOp] = [("arr", length) for length in array_lengths]
    ops.extend(("ptr", 0) for _ in range(pointer_depth))
    return tuple(ops)


class Expr:
    pass


class Stmt:
    pass


@dataclass(frozen=True)
class TranslationUnit:
    functions: list["FunctionDef"]
    declarations: list["Stmt"] = field(default_factory=list)
    externals: list["FunctionDef | Stmt"] = field(default_factory=list)


@dataclass(frozen=True)
class TypeSpec:
    name: str
    pointer_depth: int = 0
    array_lengths: tuple[int, ...] = ()
    declarator_ops: tuple[DeclaratorOp, ...] = ()
    enum_tag: str | None = None
    enum_members: tuple[EnumMember, ...] = ()
    record_tag: str | None = None
    record_members: tuple[RecordMember, ...] = ()

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
    has_prototype: bool = True
    is_variadic: bool = False


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
class BreakStmt(Stmt):
    pass


@dataclass(frozen=True)
class ContinueStmt(Stmt):
    pass


@dataclass(frozen=True)
class ReturnStmt(Stmt):
    value: Expr | None


@dataclass(frozen=True)
class ExprStmt(Stmt):
    expr: Expr


@dataclass(frozen=True)
class BinaryExpr(Expr):
    op: str
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
class CastExpr(Expr):
    type_spec: TypeSpec
    expr: Expr


@dataclass(frozen=True)
class IntLiteral(Expr):
    value: str


@dataclass(frozen=True)
class Identifier(Expr):
    name: str


@dataclass(frozen=True)
class NullStmt(Stmt):
    pass


@dataclass(frozen=True)
class DeclStmt(Stmt):
    type_spec: TypeSpec
    name: str | None
    init: Expr | None


@dataclass(frozen=True)
class TypedefDecl(Stmt):
    type_spec: TypeSpec
    name: str
