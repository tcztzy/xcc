import ast

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.module import AotModule
from xcc.aot.subset import AotModuleSummary
from xcc.aot.types import (
    AotClassInfo,
    AotFunctionInfo,
    AotType,
    AotTypeAnalysis,
    annotation_name,
    is_builtin_type_name,
    width_alias_type,
)


def bind_types(summary: AotModuleSummary, module: AotModule) -> AotTypeAnalysis:
    binder = _TypeBinder(summary, module)
    return binder.bind()


class _TypeBinder:
    def __init__(self, summary: AotModuleSummary, module: AotModule) -> None:
        self.summary = summary
        self.module = module
        self.width_aliases: dict[str, AotType] = {}
        self.classes: dict[str, AotClassInfo] = {}
        self.functions: dict[str, AotFunctionInfo] = {}
        self._diagnostics: list[AotDiagnostic] = []

    def bind(self) -> AotTypeAnalysis:
        self._collect_width_aliases()
        self._collect_classes()
        self._collect_functions()
        if self._diagnostics:
            raise AotError(tuple(self._diagnostics))
        return AotTypeAnalysis(
            self.summary.filename,
            dict(self.width_aliases),
            dict(self.classes),
            dict(self.functions),
        )

    def _collect_width_aliases(self) -> None:
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.Assign):
                continue
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                continue
            name = statement.targets[0].id
            alias = width_alias_type(name)
            if alias is None:
                continue
            if not isinstance(statement.value, ast.Name) or statement.value.id != "int":
                self._add_error(
                    "XCC-AOT-TYPE-0003",
                    f"Width alias must target int: {name}",
                    statement,
                )
                continue
            self.width_aliases[name] = alias

    def _collect_classes(self) -> None:
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.ClassDef):
                continue
            fields: dict[str, AotType] = {}
            for child in statement.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    fields[child.target.id] = self._resolve_annotation(child.annotation, child)
            self.classes[statement.name] = AotClassInfo(statement.name, fields)

    def _collect_functions(self) -> None:
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.FunctionDef):
                continue
            parameters: list[tuple[str, str]] = []
            for arg in statement.args.posonlyargs + statement.args.args:
                if arg.annotation is None:
                    self._add_error(
                        "XCC-AOT-TYPE-0001",
                        f"Missing annotation for parameter: {statement.name}.{arg.arg}",
                        statement,
                    )
                    continue
                parameters.append((arg.arg, annotation_name(arg.annotation)))
                self._resolve_annotation(arg.annotation, arg)
            if statement.returns is None:
                self._add_error(
                    "XCC-AOT-TYPE-0001",
                    f"Missing return annotation for function: {statement.name}",
                    statement,
                )
                return_type = AotType("None")
            else:
                return_type = self._resolve_annotation(statement.returns, statement)
            self.functions[statement.name] = AotFunctionInfo(
                statement.name,
                tuple(parameters),
                return_type,
            )

    def _resolve_annotation(self, node: ast.expr, owner: ast.AST) -> AotType:
        name = annotation_name(node)
        alias = self.width_aliases.get(name)
        if alias is not None:
            return alias
        if name in self.classes or is_builtin_type_name(name):
            return AotType(name)
        self._add_error("XCC-AOT-TYPE-0002", f"Unsupported annotation: {name}", owner)
        return AotType(name)

    def _add_error(self, code: str, message: str, node: ast.AST) -> None:
        self._diagnostics.append(
            AotDiagnostic(
                code,
                message,
                filename=self.summary.filename,
                line=getattr(node, "lineno", None),
                column=getattr(node, "col_offset", None),
            )
        )
