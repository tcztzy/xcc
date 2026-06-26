import ast
from dataclasses import dataclass

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.module import AotModule

_DYNAMIC_CALLS = {
    "__import__",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "hasattr",
    "locals",
    "setattr",
}
_REJECTED_STDLIB_SHIM_CALLS = {"re.fullmatch", "re.match", "re.search"}

_UNSUPPORTED_NODES = (
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.AsyncWith,
    ast.Await,
    ast.Delete,
    ast.Global,
    ast.Lambda,
    ast.Match,
    ast.Nonlocal,
    ast.Yield,
    ast.YieldFrom,
)


@dataclass(frozen=True)
class AotModuleSummary:
    filename: str
    imports: tuple[str, ...]
    classes: tuple[str, ...]
    functions: tuple[str, ...]


def check_subset(module: AotModule) -> AotModuleSummary:
    checker = _SubsetChecker(module.filename)
    checker.visit(module.tree)
    checker.raise_if_errors()
    return AotModuleSummary(
        module.filename,
        tuple(checker.imports),
        tuple(checker.classes),
        tuple(checker.functions),
    )


class _SubsetChecker(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.imports: list[str] = []
        self.classes: list[str] = []
        self.functions: list[str] = []
        self._diagnostics: list[AotDiagnostic] = []

    def raise_if_errors(self) -> None:
        if self._diagnostics:
            raise AotError(tuple(self._diagnostics))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record_import(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is not None:
            self._record_import(node.module)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_decorators(node.decorator_list)
        self.classes.append(node.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_decorators(node.decorator_list)
        self.functions.append(node.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name in _DYNAMIC_CALLS:
            self._add_error(
                "XCC-AOT-SUBSET-0003",
                f"Unsupported dynamic call: {name}",
                node,
            )
        elif name in _REJECTED_STDLIB_SHIM_CALLS:
            self._add_error(
                "XCC-AOT-SUBSET-0004",
                f"Unsupported runtime stdlib shim call: {name}",
                node,
            )
        self.generic_visit(node)

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, _UNSUPPORTED_NODES):
            self._add_error(
                "XCC-AOT-SUBSET-0001",
                f"Unsupported Python syntax: {type(node).__name__}",
                node,
            )
            return
        super().generic_visit(node)

    def _record_import(self, module: str) -> None:
        root = module.split(".", 1)[0]
        if root not in self.imports:
            self.imports.append(root)

    def _check_decorators(self, decorators: list[ast.expr]) -> None:
        for decorator in decorators:
            if _is_allowed_decorator(decorator):
                continue
            self._add_error(
                "XCC-AOT-SUBSET-0002",
                f"Unsupported decorator: {ast.unparse(decorator)}",
                decorator,
            )

    def _add_error(self, code: str, message: str, node: ast.AST) -> None:
        self._diagnostics.append(
            AotDiagnostic(
                code,
                message,
                filename=self.filename,
                line=getattr(node, "lineno", None),
                column=getattr(node, "col_offset", None),
            )
        )


def _is_allowed_decorator(decorator: ast.expr) -> bool:
    if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
        return True
    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
        if decorator.func.id != "dataclass":
            return False
        for keyword in decorator.keywords:
            if keyword.arg != "frozen":
                return False
            if not isinstance(keyword.value, ast.Constant):
                return False
            if keyword.value.value is not True:
                return False
        return True
    return False


def _call_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        receiver = _call_name(expr.value)
        if receiver is None:
            return expr.attr
        return f"{receiver}.{expr.attr}"
    return None
