from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceSpan:
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None


@dataclass(frozen=True, kw_only=True)
class AST:
    span: SourceSpan = field(default=SourceSpan(), compare=False)
    text: str = field(default="", compare=False)
    children: tuple["AST", ...] = field(default=(), compare=False)

    @property
    def lineno(self) -> int:
        if self.span.line is None:
            raise AttributeError("synthetic node has no line")
        return self.span.line

    @property
    def col_offset(self) -> int:
        if self.span.column is None:
            raise AttributeError("synthetic node has no column")
        return self.span.column

    @property
    def end_lineno(self) -> int:
        if self.span.end_line is None:
            raise AttributeError("synthetic node has no end line")
        return self.span.end_line

    @property
    def end_col_offset(self) -> int:
        if self.span.end_column is None:
            raise AttributeError("synthetic node has no end column")
        return self.span.end_column


class stmt(AST):
    pass


class expr(AST):
    pass


class expr_context(AST):
    pass


class operator(AST):
    pass


class unaryop(AST):
    pass


class boolop(AST):
    pass


class cmpop(AST):
    pass


class excepthandler(AST):
    pass


@dataclass(frozen=True)
class Load(expr_context):
    pass


@dataclass(frozen=True)
class Store(expr_context):
    pass


@dataclass(frozen=True)
class Del(expr_context):
    pass


@dataclass(frozen=True)
class Add(operator):
    pass


@dataclass(frozen=True)
class Sub(operator):
    pass


@dataclass(frozen=True)
class Mult(operator):
    pass


@dataclass(frozen=True)
class Div(operator):
    pass


@dataclass(frozen=True)
class FloorDiv(operator):
    pass


@dataclass(frozen=True)
class Mod(operator):
    pass


@dataclass(frozen=True)
class LShift(operator):
    pass


@dataclass(frozen=True)
class RShift(operator):
    pass


@dataclass(frozen=True)
class BitOr(operator):
    pass


@dataclass(frozen=True)
class BitXor(operator):
    pass


@dataclass(frozen=True)
class BitAnd(operator):
    pass


@dataclass(frozen=True)
class MatMult(operator):
    pass


@dataclass(frozen=True)
class Invert(unaryop):
    pass


@dataclass(frozen=True)
class Not(unaryop):
    pass


@dataclass(frozen=True)
class UAdd(unaryop):
    pass


@dataclass(frozen=True)
class USub(unaryop):
    pass


@dataclass(frozen=True)
class And(boolop):
    pass


@dataclass(frozen=True)
class Or(boolop):
    pass


@dataclass(frozen=True)
class Eq(cmpop):
    pass


@dataclass(frozen=True)
class NotEq(cmpop):
    pass


@dataclass(frozen=True)
class Lt(cmpop):
    pass


@dataclass(frozen=True)
class LtE(cmpop):
    pass


@dataclass(frozen=True)
class Gt(cmpop):
    pass


@dataclass(frozen=True)
class GtE(cmpop):
    pass


@dataclass(frozen=True)
class Is(cmpop):
    pass


@dataclass(frozen=True)
class IsNot(cmpop):
    pass


@dataclass(frozen=True)
class In(cmpop):
    pass


@dataclass(frozen=True)
class NotIn(cmpop):
    pass


@dataclass(frozen=True)
class alias(AST):
    name: str
    asname: str | None


@dataclass(frozen=True)
class arg(AST):
    arg: str
    annotation: expr | None
    type_comment: str | None


@dataclass(frozen=True)
class keyword(AST):
    arg: str | None
    value: expr


@dataclass(frozen=True)
class arguments(AST):
    posonlyargs: tuple[arg, ...]
    args: tuple[arg, ...]
    vararg: arg | None
    kwonlyargs: tuple[arg, ...]
    kw_defaults: tuple[expr | None, ...]
    kwarg: arg | None
    defaults: tuple[expr, ...]


@dataclass(frozen=True)
class comprehension(AST):
    target: expr
    iter: expr
    ifs: tuple[expr, ...]
    is_async: int


@dataclass(frozen=True)
class withitem(AST):
    context_expr: expr
    optional_vars: expr | None


@dataclass(frozen=True)
class Module(AST):
    body: tuple[stmt, ...] = ()
    type_ignores: tuple[AST, ...] = ()


@dataclass(frozen=True)
class Expression(AST):
    body: expr


@dataclass(frozen=True)
class FunctionDef(stmt):
    name: str
    args: arguments
    body: tuple[stmt, ...]
    decorator_list: tuple[expr, ...]
    returns: expr | None
    type_comment: str | None
    type_params: tuple[AST, ...] = ()


@dataclass(frozen=True)
class AsyncFunctionDef(stmt):
    name: str
    args: arguments
    body: tuple[stmt, ...]
    decorator_list: tuple[expr, ...]
    returns: expr | None
    type_comment: str | None
    type_params: tuple[AST, ...] = ()


@dataclass(frozen=True)
class ClassDef(stmt):
    name: str
    bases: tuple[expr, ...]
    keywords: tuple[keyword, ...]
    body: tuple[stmt, ...]
    decorator_list: tuple[expr, ...]
    type_params: tuple[AST, ...] = ()


@dataclass(frozen=True)
class Return(stmt):
    value: expr | None


@dataclass(frozen=True)
class Delete(stmt):
    targets: tuple[expr, ...]


@dataclass(frozen=True)
class Assign(stmt):
    targets: tuple[expr, ...]
    value: expr
    type_comment: str | None


@dataclass(frozen=True)
class AnnAssign(stmt):
    target: expr
    annotation: expr
    value: expr | None
    simple: int


@dataclass(frozen=True)
class AugAssign(stmt):
    target: expr
    op: operator
    value: expr


@dataclass(frozen=True)
class For(stmt):
    target: expr
    iter: expr
    body: tuple[stmt, ...]
    orelse: tuple[stmt, ...]
    type_comment: str | None


@dataclass(frozen=True)
class AsyncFor(stmt):
    target: expr
    iter: expr
    body: tuple[stmt, ...]
    orelse: tuple[stmt, ...]
    type_comment: str | None


@dataclass(frozen=True)
class While(stmt):
    test: expr
    body: tuple[stmt, ...]
    orelse: tuple[stmt, ...]


@dataclass(frozen=True)
class If(stmt):
    test: expr
    body: tuple[stmt, ...]
    orelse: tuple[stmt, ...]


@dataclass(frozen=True)
class With(stmt):
    items: tuple[withitem, ...]
    body: tuple[stmt, ...]
    type_comment: str | None


@dataclass(frozen=True)
class AsyncWith(stmt):
    items: tuple[withitem, ...]
    body: tuple[stmt, ...]
    type_comment: str | None


@dataclass(frozen=True)
class Match(stmt):
    subject: expr
    cases: tuple[AST, ...]


@dataclass(frozen=True)
class Raise(stmt):
    exc: expr | None
    cause: expr | None


@dataclass(frozen=True)
class Try(stmt):
    body: tuple[stmt, ...]
    handlers: tuple["ExceptHandler", ...]
    orelse: tuple[stmt, ...]
    finalbody: tuple[stmt, ...]


@dataclass(frozen=True)
class Assert(stmt):
    test: expr
    msg: expr | None


@dataclass(frozen=True)
class Import(stmt):
    names: tuple[alias, ...]


@dataclass(frozen=True)
class ImportFrom(stmt):
    module: str | None
    names: tuple[alias, ...]
    level: int


@dataclass(frozen=True)
class Global(stmt):
    names: tuple[str, ...]


@dataclass(frozen=True)
class Nonlocal(stmt):
    names: tuple[str, ...]


@dataclass(frozen=True)
class Expr(stmt):
    value: expr


@dataclass(frozen=True)
class Pass(stmt):
    pass


@dataclass(frozen=True)
class Break(stmt):
    pass


@dataclass(frozen=True)
class Continue(stmt):
    pass


@dataclass(frozen=True)
class BoolOp(expr):
    op: boolop
    values: tuple[expr, ...]


@dataclass(frozen=True)
class NamedExpr(expr):
    target: expr
    value: expr


@dataclass(frozen=True)
class BinOp(expr):
    left: expr
    op: operator
    right: expr


@dataclass(frozen=True)
class UnaryOp(expr):
    op: unaryop
    operand: expr


@dataclass(frozen=True)
class Lambda(expr):
    args: arguments
    body: expr


@dataclass(frozen=True)
class IfExp(expr):
    test: expr
    body: expr
    orelse: expr


@dataclass(frozen=True)
class Dict(expr):
    keys: tuple[expr | None, ...]
    values: tuple[expr, ...]


@dataclass(frozen=True)
class Set(expr):
    elts: tuple[expr, ...]


@dataclass(frozen=True)
class ListComp(expr):
    elt: expr
    generators: tuple[comprehension, ...]


@dataclass(frozen=True)
class SetComp(expr):
    elt: expr
    generators: tuple[comprehension, ...]


@dataclass(frozen=True)
class DictComp(expr):
    key: expr
    value: expr
    generators: tuple[comprehension, ...]


@dataclass(frozen=True)
class GeneratorExp(expr):
    elt: expr
    generators: tuple[comprehension, ...]


@dataclass(frozen=True)
class Await(expr):
    value: expr


@dataclass(frozen=True)
class Yield(expr):
    value: expr | None


@dataclass(frozen=True)
class YieldFrom(expr):
    value: expr


@dataclass(frozen=True)
class Compare(expr):
    left: expr
    ops: tuple[cmpop, ...]
    comparators: tuple[expr, ...]


@dataclass(frozen=True)
class Call(expr):
    func: expr
    args: tuple[expr, ...]
    keywords: tuple[keyword, ...]


@dataclass(frozen=True)
class FormattedValue(expr):
    value: expr
    conversion: int
    format_spec: expr | None


@dataclass(frozen=True)
class JoinedStr(expr):
    values: tuple[expr, ...]


@dataclass(frozen=True)
class Constant(expr):
    value: object
    kind: str | None = None


@dataclass(frozen=True)
class Attribute(expr):
    value: expr
    attr: str
    ctx: expr_context


@dataclass(frozen=True)
class Subscript(expr):
    value: expr
    slice: expr
    ctx: expr_context


@dataclass(frozen=True)
class Starred(expr):
    value: expr
    ctx: expr_context


@dataclass(frozen=True)
class Name(expr):
    id: str
    ctx: expr_context


@dataclass(frozen=True)
class List(expr):
    elts: tuple[expr, ...]
    ctx: expr_context


@dataclass(frozen=True)
class Tuple(expr):
    elts: tuple[expr, ...]
    ctx: expr_context


@dataclass(frozen=True)
class Slice(expr):
    lower: expr | None
    upper: expr | None
    step: expr | None


@dataclass(frozen=True)
class ExceptHandler(excepthandler):
    type: expr | None
    name: str | None
    body: tuple[stmt, ...]


@dataclass(frozen=True)
class UnsupportedNode(AST):
    kind: str
    values: tuple[object, ...]


def walk(node: AST) -> tuple[AST, ...]:
    pending = [node]
    result: list[AST] = []
    while pending:
        current = pending.pop(0)
        result.append(current)
        pending[0:0] = current.children
    return tuple(result)


def unparse(node: AST) -> str:
    if isinstance(node, Name):
        return node.id
    if isinstance(node, Constant):
        if node.value is Ellipsis:
            return "..."
        return repr(node.value)
    if isinstance(node, Attribute):
        return f"{unparse(node.value)}.{node.attr}"
    if isinstance(node, Subscript):
        return f"{unparse(node.value)}[{_unparse_subscript_slice(node.slice)}]"
    if isinstance(node, Tuple):
        body = ", ".join(unparse(element) for element in node.elts)
        if len(node.elts) == 1:
            body += ","
        return f"({body})"
    if isinstance(node, List):
        return f"[{', '.join(unparse(element) for element in node.elts)}]"
    if isinstance(node, Set):
        if not node.elts:
            return "set()"
        return f"{{{', '.join(unparse(element) for element in node.elts)}}}"
    if isinstance(node, Dict):
        items: list[str] = []
        for key, value in zip(node.keys, node.values, strict=False):
            if key is None:
                items.append(f"**{unparse(value)}")
            else:
                items.append(f"{unparse(key)}: {unparse(value)}")
        return f"{{{', '.join(items)}}}"
    if isinstance(node, BinOp):
        operator_text = _binary_text(node.op)
        if operator_text:
            return f"{unparse(node.left)} {operator_text} {unparse(node.right)}"
    if isinstance(node, BoolOp):
        operator_text = _bool_text(node.op)
        if operator_text:
            return f" {operator_text} ".join(unparse(value) for value in node.values)
    if isinstance(node, UnaryOp):
        prefix = _unary_text(node.op)
        if prefix:
            return f"{prefix}{unparse(node.operand)}"
    if isinstance(node, Compare):
        result = unparse(node.left)
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            result += f" {_compare_text(op)} {unparse(comparator)}"
        return result
    if isinstance(node, Call):
        args = [unparse(argument) for argument in node.args]
        for item in node.keywords:
            prefix = "**" if item.arg is None else f"{item.arg}="
            args.append(f"{prefix}{unparse(item.value)}")
        return f"{unparse(node.func)}({', '.join(args)})"
    if isinstance(node, IfExp):
        return f"{unparse(node.body)} if {unparse(node.test)} else {unparse(node.orelse)}"
    if isinstance(node, Starred):
        return f"*{unparse(node.value)}"
    if isinstance(node, Slice):
        lower = "" if node.lower is None else unparse(node.lower)
        upper = "" if node.upper is None else unparse(node.upper)
        if node.step is None:
            return f"{lower}:{upper}"
        return f"{lower}:{upper}:{unparse(node.step)}"
    if isinstance(node, NamedExpr):
        return f"({unparse(node.target)} := {unparse(node.value)})"
    return type(node).__name__


def _binary_text(op: operator) -> str:
    if isinstance(op, Add):
        return "+"
    if isinstance(op, Sub):
        return "-"
    if isinstance(op, Mult):
        return "*"
    if isinstance(op, Div):
        return "/"
    if isinstance(op, FloorDiv):
        return "//"
    if isinstance(op, Mod):
        return "%"
    if isinstance(op, LShift):
        return "<<"
    if isinstance(op, RShift):
        return ">>"
    if isinstance(op, BitOr):
        return "|"
    if isinstance(op, BitXor):
        return "^"
    if isinstance(op, BitAnd):
        return "&"
    if isinstance(op, MatMult):
        return "@"
    return ""


def _bool_text(op: boolop) -> str:
    if isinstance(op, And):
        return "and"
    if isinstance(op, Or):
        return "or"
    return ""


def _compare_text(op: cmpop) -> str:
    if isinstance(op, Eq):
        return "=="
    if isinstance(op, NotEq):
        return "!="
    if isinstance(op, Lt):
        return "<"
    if isinstance(op, LtE):
        return "<="
    if isinstance(op, Gt):
        return ">"
    if isinstance(op, GtE):
        return ">="
    if isinstance(op, Is):
        return "is"
    if isinstance(op, IsNot):
        return "is not"
    if isinstance(op, In):
        return "in"
    if isinstance(op, NotIn):
        return "not in"
    return type(op).__name__


def _unary_text(op: unaryop) -> str:
    if isinstance(op, Not):
        return "not "
    if isinstance(op, UAdd):
        return "+"
    if isinstance(op, USub):
        return "-"
    if isinstance(op, Invert):
        return "~"
    return ""


def _unparse_subscript_slice(node: expr) -> str:
    if isinstance(node, Tuple):
        return ", ".join(unparse(element) for element in node.elts)
    return unparse(node)
