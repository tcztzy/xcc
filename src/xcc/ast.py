from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

StorageClass = Literal["auto", "register", "static", "extern", "typedef"]


class Expr:
    pass


class Stmt:
    pass


@dataclass(frozen=True)
class SourceLocation:
    line: int
    column: int


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


@dataclass(frozen=True)
class DesignatorRange:
    low: "Expr"
    high: "Expr"


Designator = tuple[str, "Expr | str | DesignatorRange"]


@dataclass(frozen=True)
class TranslationUnit:
    functions: list["FunctionDef"]
    declarations: list["Stmt"] = field(default_factory=list)
    externals: list["FunctionDef | Stmt"] = field(default_factory=list)
    source_map: dict[int, SourceLocation] = field(default_factory=dict, compare=False)
    source_locations: list[SourceLocation] = field(default_factory=list, compare=False)


@dataclass(frozen=True)
class RecordMemberDecl:
    type_spec: "TypeSpec"
    name: str | None
    alignment: int | None = None
    bit_width_expr: "Expr | None" = None


@dataclass(frozen=True)
class TypeSpec:
    name: str
    declarator_ops: tuple[DeclaratorOp, ...] = ()
    qualifiers: tuple[str, ...] = ()
    is_atomic: bool = False
    atomic_target: "TypeSpec | None" = field(default=None, compare=False)
    enum_tag: str | None = None
    enum_members: tuple[EnumMember, ...] = ()
    record_tag: str | None = None
    record_members: tuple[RecordMemberDecl, ...] = ()
    has_record_body: bool = False
    source_line: int | None = field(default=None, compare=False)
    source_column: int | None = field(default=None, compare=False)
    typeof_expr: "Expr | None" = field(default=None, compare=False)


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
class BuiltinTypesCompatExpr(Expr):
    type1: TypeSpec
    type2: TypeSpec


@dataclass(frozen=True)
class BuiltinVaArgExpr(Expr):
    ap: Expr
    type_spec: TypeSpec


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
    is_transparent_union: bool = False


@dataclass(frozen=True)
class InitItem:
    designators: tuple[Designator, ...]
    initializer: "Expr | InitList"


@dataclass(frozen=True)
class InitList:
    items: tuple[InitItem, ...]


def walk_ast_children(node: object, walk: Callable[[object], None]) -> None:
    if isinstance(node, (list, tuple)):
        for item in node:
            walk(item)
    elif isinstance(node, ArrayDecl):
        walk(node.length)
    elif isinstance(node, DesignatorRange):
        walk(node.low)
        walk(node.high)
    elif isinstance(node, RecordMemberDecl):
        walk(node.type_spec)
        if node.bit_width_expr is not None:
            walk(node.bit_width_expr)
    elif isinstance(node, TypeSpec):
        for member in node.record_members:
            walk(member)
        for _kind, declarator_value in node.declarator_ops:
            walk(declarator_value)
        for _name, enum_value in node.enum_members:
            if enum_value is not None:
                walk(enum_value)
        if node.atomic_target is not None:
            walk(node.atomic_target)
        if node.typeof_expr is not None:
            walk(node.typeof_expr)
    elif isinstance(node, InitItem):
        for _kind, designator_value in node.designators:
            walk(designator_value)
        walk(node.initializer)
    elif isinstance(node, InitList):
        for item in node.items:
            walk(item)
    elif isinstance(node, FunctionDef):
        walk(node.return_type)
        for param in node.params:
            walk(param.type_spec)
        if node.body is not None:
            walk(node.body)
    elif isinstance(node, CompoundStmt):
        for statement in node.statements:
            walk(statement)
    elif isinstance(node, IfStmt):
        walk(node.condition)
        walk(node.then_body)
        if node.else_body is not None:
            walk(node.else_body)
    elif isinstance(node, WhileStmt):
        walk(node.condition)
        walk(node.body)
    elif isinstance(node, DoWhileStmt):
        walk(node.body)
        walk(node.condition)
    elif isinstance(node, ForStmt):
        walk(node.init)
        walk(node.condition)
        walk(node.post)
        walk(node.body)
    elif isinstance(node, SwitchStmt):
        walk(node.condition)
        walk(node.body)
    elif isinstance(node, CaseStmt):
        walk(node.value)
        walk(node.body)
    elif isinstance(node, (DefaultStmt, LabelStmt)):
        walk(node.body)
    elif isinstance(node, IndirectGotoStmt):
        walk(node.target)
    elif isinstance(node, ReturnStmt):
        walk(node.value)
    elif isinstance(node, StaticAssertDecl):
        walk(node.condition)
        walk(node.message)
    elif isinstance(node, ExprStmt):
        walk(node.expr)
    elif isinstance(node, DeclGroupStmt):
        for declaration in node.declarations:
            walk(declaration)
    elif isinstance(node, DeclStmt):
        walk(node.type_spec)
        walk(node.init)
    elif isinstance(node, TypedefDecl):
        walk(node.type_spec)
    elif isinstance(node, BinaryExpr):
        walk(node.left)
        walk(node.right)
    elif isinstance(node, ConditionalExpr):
        walk(node.condition)
        walk(node.then_expr)
        walk(node.else_expr)
    elif isinstance(node, CommaExpr):
        walk(node.left)
        walk(node.right)
    elif isinstance(node, AssignExpr):
        walk(node.target)
        walk(node.value)
    elif isinstance(node, (UnaryExpr, UpdateExpr)):
        walk(node.operand)
    elif isinstance(node, CallExpr):
        walk(node.callee)
        for arg in node.args:
            walk(arg)
    elif isinstance(node, SubscriptExpr):
        walk(node.base)
        walk(node.index)
    elif isinstance(node, MemberExpr):
        walk(node.base)
    elif isinstance(node, (SizeofExpr, AlignofExpr)):
        walk(node.expr)
        walk(node.type_spec)
    elif isinstance(node, CastExpr):
        walk(node.type_spec)
        walk(node.expr)
    elif isinstance(node, CompoundLiteralExpr):
        walk(node.type_spec)
        walk(node.initializer)
    elif isinstance(node, StatementExpr):
        walk(node.body)
    elif isinstance(node, GenericExpr):
        walk(node.control)
        for assoc_type, assoc_expr in node.associations:
            walk(assoc_type)
            walk(assoc_expr)
    elif isinstance(node, BuiltinOffsetofExpr):
        walk(node.type_spec)
    elif isinstance(node, BuiltinTypesCompatExpr):
        walk(node.type1)
        walk(node.type2)
    elif isinstance(node, BuiltinVaArgExpr):
        walk(node.ap)
        walk(node.type_spec)
