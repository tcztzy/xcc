import ast

from xcc.aot.diag import AotDiagnostic, AotError, node_location
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
        self.aliases: dict[str, AotType] = {}
        self.classes: dict[str, AotClassInfo] = {}
        self.functions: dict[str, AotFunctionInfo] = {}
        self._diagnostics: list[AotDiagnostic] = []

    def bind(self) -> AotTypeAnalysis:
        self._collect_width_aliases()
        self._collect_type_aliases()
        self._collect_classes()
        self._collect_functions()
        if self._diagnostics:
            raise AotError(tuple(self._diagnostics))
        return AotTypeAnalysis(
            self.summary.filename,
            dict(self.width_aliases),
            dict(self.classes),
            dict(self.functions),
            dict(self.aliases),
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

    def _collect_type_aliases(self) -> None:
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.Assign):
                continue
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                continue
            if not _is_annotation_alias_value(statement.value):
                continue
            name = statement.targets[0].id
            if name in self.width_aliases:
                continue
            if name[:1].isupper() or name.endswith("Params") or name.endswith("Op"):
                self.aliases[name] = AotType(annotation_name(statement.value))

    def _collect_classes(self) -> None:
        return_types = self._function_return_types()
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.ClassDef):
                continue
            bases = tuple(annotation_name(base) for base in statement.bases)
            fields: dict[str, AotType] = {}
            for child in statement.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    fields[child.target.id] = self._resolve_annotation(child.annotation, child)
            self._collect_init_fields(statement, fields, return_types)
            self.classes[statement.name] = AotClassInfo(statement.name, fields, bases)

    def _collect_init_fields(
        self,
        class_node: ast.ClassDef,
        fields: dict[str, AotType],
        return_types: dict[str, AotType],
    ) -> None:
        for child in class_node.body:
            if not isinstance(child, ast.FunctionDef) or child.name != "__init__":
                continue
            local_types = self._function_local_types(child, class_node.name)
            for target, value, annotation in _init_self_assignments(child.body):
                if target.attr in fields:
                    continue
                if annotation is not None:
                    fields[target.attr] = self._resolve_annotation(annotation, target)
                    continue
                inferred = self._infer_expr_type(value, local_types, fields, return_types)
                if inferred is not None:
                    fields[target.attr] = inferred

    def _function_return_types(self) -> dict[str, AotType]:
        return_types: dict[str, AotType] = {}
        for statement in self.module.tree.body:
            if isinstance(statement, ast.FunctionDef) and statement.returns is not None:
                return_types[statement.name] = self._annotation_to_known_type(statement.returns)
            if not isinstance(statement, ast.ClassDef):
                continue
            for child in statement.body:
                if isinstance(child, ast.FunctionDef) and child.returns is not None:
                    return_types[f"{statement.name}.{child.name}"] = self._annotation_to_known_type(
                        child.returns
                    )
        return return_types

    def _function_local_types(
        self,
        statement: ast.FunctionDef,
        owner: str,
    ) -> dict[str, AotType]:
        local_types: dict[str, AotType] = {}
        positional_args = statement.args.posonlyargs + statement.args.args
        for index, arg in enumerate(positional_args):
            if index == 0 and arg.annotation is None and arg.arg == "self":
                local_types[arg.arg] = AotType(owner)
            elif arg.annotation is not None:
                local_types[arg.arg] = self._annotation_to_known_type(arg.annotation)
        for arg in statement.args.kwonlyargs:
            if arg.annotation is not None:
                local_types[arg.arg] = self._annotation_to_known_type(arg.annotation)
        return local_types

    def _annotation_to_known_type(self, node: ast.expr) -> AotType:
        name = annotation_name(node)
        alias = self.width_aliases.get(name)
        if alias is not None:
            return alias
        alias = self.aliases.get(name)
        if alias is not None:
            return alias
        return AotType(name)

    def _infer_expr_type(
        self,
        expr: ast.expr | None,
        local_types: dict[str, AotType],
        fields: dict[str, AotType],
        return_types: dict[str, AotType],
    ) -> AotType | None:
        if expr is None:
            return AotType("None")
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, bool):
                return AotType("bool")
            if expr.value is None:
                return AotType("None")
            if isinstance(expr.value, int):
                return AotType("int")
            if isinstance(expr.value, str):
                return AotType("str")
        if isinstance(expr, ast.Name):
            return local_types.get(expr.id)
        if (
            isinstance(expr, ast.Attribute)
            and isinstance(expr.value, ast.Name)
            and expr.value.id == "self"
        ):
            return fields.get(expr.attr)
        if isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Name):
                if expr.func.id == "len":
                    return AotType("int")
                if expr.func.id in {"bool", "int", "str"}:
                    return AotType(expr.func.id)
                return return_types.get(expr.func.id)
            call_name = ast.unparse(expr.func)
            return return_types.get(call_name)
        if isinstance(expr, (ast.Compare, ast.BoolOp)):
            return AotType("bool")
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
            return AotType("bool")
        if isinstance(expr, ast.BinOp):
            left_type = self._infer_expr_type(expr.left, local_types, fields, return_types)
            right_type = self._infer_expr_type(expr.right, local_types, fields, return_types)
            if left_type == right_type:
                return left_type
        return None

    def _collect_functions(self) -> None:
        for statement in self.module.tree.body:
            if isinstance(statement, ast.FunctionDef):
                self._collect_function(statement, owner=None)
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.ClassDef):
                continue
            for child in statement.body:
                if isinstance(child, ast.FunctionDef):
                    self._collect_function(child, owner=statement.name)

    def _collect_function(self, statement: ast.FunctionDef, owner: str | None) -> None:
        function_name = f"{owner}.{statement.name}" if owner is not None else statement.name
        parameters: list[tuple[str, str]] = []
        positional_args = statement.args.posonlyargs + statement.args.args
        for index, arg in enumerate(positional_args):
            annotation = arg.annotation
            if (
                owner is not None
                and index == 0
                and annotation is None
                and arg.arg in {"self", "cls"}
            ):
                parameters.append((arg.arg, owner))
                continue
            if annotation is None:
                self._add_error(
                    "XCC-AOT-TYPE-0001",
                    f"Missing annotation for parameter: {function_name}.{arg.arg}",
                    statement,
                )
                continue
            parameters.append((arg.arg, annotation_name(annotation)))
            self._resolve_annotation(annotation, arg)
        for arg in statement.args.kwonlyargs:
            if arg.annotation is None:
                self._add_error(
                    "XCC-AOT-TYPE-0001",
                    f"Missing annotation for parameter: {function_name}.{arg.arg}",
                    statement,
                )
                continue
            parameters.append((arg.arg, annotation_name(arg.annotation)))
            self._resolve_annotation(arg.annotation, arg)
        if statement.returns is None:
            self._add_error(
                "XCC-AOT-TYPE-0001",
                f"Missing return annotation for function: {function_name}",
                statement,
            )
            return_type = AotType("None")
        else:
            return_type = self._resolve_annotation(statement.returns, statement)
        self.functions[function_name] = AotFunctionInfo(
            function_name,
            tuple(parameters),
            return_type,
        )

    def _resolve_annotation(self, node: ast.expr, owner: ast.AST) -> AotType:
        name = annotation_name(node)
        alias = self.width_aliases.get(name)
        if alias is not None:
            return alias
        alias = self.aliases.get(name)
        if alias is not None:
            return alias
        if name in self.classes or is_builtin_type_name(name):
            return AotType(name)
        if _is_supported_composite_annotation(name):
            return AotType(name)
        self._add_error("XCC-AOT-TYPE-0002", f"Unsupported annotation: {name}", owner)
        return AotType(name)

    def _add_error(self, code: str, message: str, node: ast.AST) -> None:
        line, column = node_location(node)
        self._diagnostics.append(
            AotDiagnostic(
                code,
                message,
                filename=self.summary.filename,
                line=line,
                column=column,
            )
        )


def _is_annotation_alias_value(node: ast.expr) -> bool:
    return isinstance(node, (ast.Subscript, ast.BinOp, ast.Name))


def _init_self_assignments(
    statements: list[ast.stmt],
) -> tuple[tuple[ast.Attribute, ast.expr | None, ast.expr | None], ...]:
    assignments: list[tuple[ast.Attribute, ast.expr | None, ast.expr | None]] = []
    for statement in statements:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Attribute)
            and _is_self_attribute(statement.targets[0])
        ):
            assignments.append((statement.targets[0], statement.value, None))
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Attribute)
            and _is_self_attribute(statement.target)
        ):
            assignments.append((statement.target, statement.value, statement.annotation))
        elif isinstance(statement, ast.If):
            assignments.extend(_init_self_assignments(statement.body))
            assignments.extend(_init_self_assignments(statement.orelse))
    return tuple(assignments)


def _is_self_attribute(expr: ast.Attribute) -> bool:
    return isinstance(expr.value, ast.Name) and expr.value.id == "self"


def _is_supported_composite_annotation(name: str) -> bool:
    try:
        node = ast.parse(name, mode="eval").body
    except SyntaxError:
        return _is_project_type_reference(name)
    return _is_supported_annotation_node(node)


def _is_supported_annotation_node(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return (
            is_builtin_type_name(node.id)
            or width_alias_type(node.id) is not None
            or _is_project_type_reference(node.id)
        )
    if isinstance(node, ast.Attribute):
        return True
    if isinstance(node, ast.Constant):
        if node.value is None:
            return True
        if isinstance(node.value, str):
            return _is_supported_composite_annotation(node.value)
        return node.value is Ellipsis
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_supported_annotation_node(node.left) and (
            _is_supported_annotation_node(node.right)
        )
    if isinstance(node, ast.Subscript):
        return _is_supported_subscript_annotation(node)
    return False


def _is_supported_subscript_annotation(node: ast.Subscript) -> bool:
    base = ast.unparse(node.value)
    elements = _annotation_slice_elements(node.slice)
    if base == "Literal":
        return all(isinstance(element, ast.Constant) for element in elements)
    if base in {"Iterable", "Sequence", "list", "set", "frozenset"}:
        return len(elements) == 1 and _is_supported_annotation_node(elements[0])
    if base == "dict":
        return len(elements) == 2 and all(
            _is_supported_annotation_node(element) for element in elements
        )
    if base == "tuple":
        return all(
            isinstance(element, ast.Constant)
            and element.value is Ellipsis
            or _is_supported_annotation_node(element)
            for element in elements
        )
    if base == "Callable":
        return _is_supported_callable_annotation(elements)
    return False


def _is_supported_callable_annotation(elements: tuple[ast.expr, ...]) -> bool:
    if len(elements) != 2:
        return False
    args, return_type = elements
    if isinstance(args, ast.Constant) and args.value is Ellipsis:
        return _is_supported_annotation_node(return_type)
    if not isinstance(args, ast.List):
        return False
    return all(_is_supported_annotation_node(arg) for arg in args.elts) and (
        _is_supported_annotation_node(return_type)
    )


def _annotation_slice_elements(node: ast.expr) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Tuple):
        return tuple(node.elts)
    return (node,)


def _is_project_type_reference(name: str) -> bool:
    leaf = name.rsplit(".", 1)[-1].strip("\"'").lstrip("_")
    return leaf[:1].isupper()
