from collections.abc import Sequence

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

from . import py_ast as ast

_OWNED_AST_TYPE_NAMES = {
    "alias",
    "arg",
    "arguments",
    "boolop",
    "cmpop",
    "comprehension",
    "excepthandler",
    "expr",
    "expr_context",
    "keyword",
    "operator",
    "stmt",
    "unaryop",
    "withitem",
}


def bind_types(
    summary: AotModuleSummary,
    module: AotModule,
    *,
    extra_classes: dict[str, AotClassInfo] | None = None,
    extra_functions: dict[str, AotFunctionInfo] | None = None,
) -> AotTypeAnalysis:
    binder = _TypeBinder(
        summary,
        module,
        extra_classes=extra_classes,
        extra_functions=extra_functions,
    )
    return binder.bind()


def bind_function_signatures(
    summary: AotModuleSummary,
    module: AotModule,
) -> dict[str, AotFunctionInfo]:
    local_class_names = tuple(
        statement.name for statement in module.tree.body if isinstance(statement, ast.ClassDef)
    )
    binder = _TypeBinder(
        summary,
        module,
        known_local_classes=local_class_names,
    )
    binder._collect_width_aliases()
    binder._collect_type_aliases()
    binder._collect_functions()
    binder._raise_if_errors()
    return dict(binder.functions)


def bind_class_types(
    summary: AotModuleSummary,
    module: AotModule,
    *,
    extra_classes: dict[str, AotClassInfo] | None = None,
    extra_functions: dict[str, AotFunctionInfo] | None = None,
) -> dict[str, AotClassInfo]:
    binder = _TypeBinder(
        summary,
        module,
        extra_classes=extra_classes,
        extra_functions=extra_functions,
    )
    binder._collect_width_aliases()
    binder._collect_type_aliases()
    binder._collect_classes()
    binder._raise_if_errors()
    return dict(binder.classes)


class _TypeBinder:
    def __init__(
        self,
        summary: AotModuleSummary,
        module: AotModule,
        *,
        extra_classes: dict[str, AotClassInfo] | None = None,
        extra_functions: dict[str, AotFunctionInfo] | None = None,
        known_local_classes: tuple[str, ...] = (),
    ) -> None:
        self.summary = summary
        self.module = module
        self.extra_classes = extra_classes or {}
        self.extra_functions = extra_functions or {}
        self.known_local_classes = known_local_classes
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
        self._raise_if_errors()
        return AotTypeAnalysis(
            self.summary.filename,
            dict(self.width_aliases),
            dict(self.classes),
            dict(self.functions),
            dict(self.aliases),
        )

    def _raise_if_errors(self) -> None:
        if self._diagnostics:
            raise AotError(tuple(self._diagnostics))

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
            if _is_project_type_reference(name) or name.endswith("Params") or name.endswith("Op"):
                self.aliases[name] = AotType(annotation_name(statement.value))

    def _collect_classes(self) -> None:
        return_types = self._function_return_types()
        for statement in self.module.tree.body:
            if not isinstance(statement, ast.ClassDef):
                continue
            bases = tuple(annotation_name(base) for base in statement.bases)
            fields: dict[str, AotType] = {}
            field_defaults: dict[str, ast.expr] = {}
            int_constants: dict[str, int] = {}
            init_field_parameters: dict[str, str] = {}
            for child in statement.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    fields[child.target.id] = self._resolve_annotation(child.annotation, child)
                    if child.value is not None:
                        field_defaults[child.target.id] = child.value
                elif (
                    isinstance(child, ast.Assign)
                    and len(child.targets) == 1
                    and isinstance(child.targets[0], ast.Name)
                    and isinstance(child.value, ast.Constant)
                    and type(child.value.value) is int
                ):
                    int_constants[child.targets[0].id] = child.value.value
            self._collect_init_fields(
                statement,
                fields,
                return_types,
                init_field_parameters,
            )
            self.classes[statement.name] = AotClassInfo(
                statement.name,
                fields,
                bases,
                int_constants,
                init_field_parameters,
                kw_only=_class_is_kw_only_dataclass(statement),
                field_defaults=field_defaults,
            )

    def _collect_init_fields(
        self,
        class_node: ast.ClassDef,
        fields: dict[str, AotType],
        return_types: dict[str, AotType],
        init_field_parameters: dict[str, str],
    ) -> None:
        for child in class_node.body:
            if not isinstance(child, ast.FunctionDef) or child.name != "__init__":
                continue
            local_types = self._function_local_types(
                child,
                class_node.name,
                return_types,
            )
            for target, value, annotation in _init_self_assignments(child.body):
                parameter_name = _init_field_parameter(value)
                if parameter_name is not None:
                    init_field_parameters[target.attr] = parameter_name
                if target.attr in fields:
                    continue
                if annotation is not None:
                    fields[target.attr] = self._resolve_annotation(annotation, target)
                    continue
                inferred = self._infer_expr_type(value, local_types, fields, return_types)
                if inferred is not None:
                    fields[target.attr] = inferred

    def _function_return_types(self) -> dict[str, AotType]:
        return_types = {
            name: function.return_type for name, function in self.extra_functions.items()
        }
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
        return_types: dict[str, AotType],
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
        if statement.args.vararg is not None and statement.args.vararg.annotation is not None:
            annotation = annotation_name(statement.args.vararg.annotation)
            local_types[statement.args.vararg.arg] = AotType(f"tuple[{annotation}, ...]")
        for child in statement.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                local_types[child.target.id] = self._annotation_to_known_type(child.annotation)
            elif (
                isinstance(child, ast.Assign)
                and len(child.targets) == 1
                and isinstance(child.targets[0], ast.Name)
            ):
                inferred = self._infer_expr_type(
                    child.value,
                    local_types,
                    {},
                    return_types,
                )
                if inferred is not None:
                    local_types[child.targets[0].id] = inferred
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
        if isinstance(expr, ast.List) and expr.elts:
            element_types = tuple(
                self._infer_expr_type(element, local_types, fields, return_types)
                for element in expr.elts
            )
            first = element_types[0]
            if first is not None and all(element == first for element in element_types):
                return AotType(f"list[{first.name}]")
        if isinstance(expr, ast.Attribute):
            if isinstance(expr.value, ast.Name) and expr.value.id == "self":
                return fields.get(expr.attr)
            receiver_type = self._infer_expr_type(
                expr.value,
                local_types,
                fields,
                return_types,
            )
            if receiver_type is not None:
                class_info = self._known_class(receiver_type.name)
                if class_info is not None:
                    return class_info.fields.get(expr.attr)
        if isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Name):
                if expr.func.id == "len":
                    return AotType("int")
                if expr.func.id in {"bool", "int", "str"}:
                    return AotType(expr.func.id)
                if expr.func.id == "sorted" and len(expr.args) == 1:
                    iterable_type = self._infer_expr_type(
                        expr.args[0],
                        local_types,
                        fields,
                        return_types,
                    )
                    item_type = _iterable_item_type(iterable_type)
                    if item_type is not None:
                        return AotType(f"list[{item_type.name}]")
                if expr.func.id == "enumerate" and expr.args:
                    iterable_type = self._infer_expr_type(
                        expr.args[0],
                        local_types,
                        fields,
                        return_types,
                    )
                    item_type = _iterable_item_type(iterable_type)
                    if item_type is not None:
                        return AotType(f"tuple[tuple[int, {item_type.name}], ...]")
                return return_types.get(expr.func.id)
            if isinstance(expr.func, ast.Attribute) and isinstance(expr.func.value, ast.Name):
                receiver_type = local_types.get(expr.func.value.id)
                if receiver_type is not None:
                    method_type = return_types.get(f"{receiver_type.name}.{expr.func.attr}")
                    if method_type is not None:
                        return method_type
            call_name = ast.unparse(expr.func)
            return return_types.get(call_name)
        if isinstance(expr, ast.DictComp):
            comprehension_types = self._comprehension_types(
                expr.generators,
                local_types,
                fields,
                return_types,
            )
            if comprehension_types is not None:
                key_type = self._infer_expr_type(
                    expr.key,
                    comprehension_types,
                    fields,
                    return_types,
                )
                value_type = self._infer_expr_type(
                    expr.value,
                    comprehension_types,
                    fields,
                    return_types,
                )
                if key_type is not None and value_type is not None:
                    return AotType(f"dict[{key_type.name}, {value_type.name}]")
        if isinstance(expr, ast.ListComp | ast.SetComp | ast.GeneratorExp):
            comprehension_types = self._comprehension_types(
                expr.generators,
                local_types,
                fields,
                return_types,
            )
            if comprehension_types is not None:
                element_type = self._infer_expr_type(
                    expr.elt,
                    comprehension_types,
                    fields,
                    return_types,
                )
                if element_type is not None:
                    if isinstance(expr, ast.ListComp):
                        return AotType(f"list[{element_type.name}]")
                    if isinstance(expr, ast.SetComp):
                        return AotType(f"set[{element_type.name}]")
                    return AotType(f"tuple[{element_type.name}, ...]")
        if isinstance(expr, ast.Compare):
            return AotType("bool")
        if isinstance(expr, ast.BoolOp):
            operand_types = tuple(
                self._infer_expr_type(value, local_types, fields, return_types)
                for value in expr.values
            )
            return _value_bool_op_type(tuple(expr.values), operand_types)
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
            return AotType("bool")
        if isinstance(expr, ast.BinOp):
            left_type = self._infer_expr_type(expr.left, local_types, fields, return_types)
            right_type = self._infer_expr_type(expr.right, local_types, fields, return_types)
            if left_type == right_type:
                return left_type
        return None

    def _known_class(self, name: str) -> AotClassInfo | None:
        leaf = name.rsplit(".", 1)[-1]
        return self.classes.get(leaf) or self.extra_classes.get(leaf)

    def _comprehension_types(
        self,
        generators: tuple[ast.comprehension, ...],
        local_types: dict[str, AotType],
        fields: dict[str, AotType],
        return_types: dict[str, AotType],
    ) -> dict[str, AotType] | None:
        result = dict(local_types)
        for generator in generators:
            iterable_type = self._infer_expr_type(
                generator.iter,
                result,
                fields,
                return_types,
            )
            item_type = _iterable_item_type(iterable_type)
            if item_type is None or not _bind_comprehension_target(
                generator.target,
                item_type,
                result,
            ):
                return None
        return result

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
        parameter_defaults: list[ast.expr | None] = []
        vararg: tuple[str, str] | None = None
        positional_args = statement.args.posonlyargs + statement.args.args
        positional_defaults: tuple[ast.expr | None, ...] = (None,) * (
            len(positional_args) - len(statement.args.defaults)
        ) + tuple(statement.args.defaults)
        for index, (arg, default) in enumerate(
            zip(positional_args, positional_defaults, strict=True)
        ):
            annotation = arg.annotation
            if (
                owner is not None
                and index == 0
                and annotation is None
                and arg.arg in {"self", "cls"}
            ):
                parameters.append((arg.arg, owner))
                parameter_defaults.append(default)
                continue
            if annotation is None:
                self._add_error(
                    "XCC-AOT-TYPE-0001",
                    f"Missing annotation for parameter: {function_name}.{arg.arg}",
                    statement,
                )
                continue
            parameters.append((arg.arg, annotation_name(annotation)))
            parameter_defaults.append(default)
            self._resolve_annotation(annotation, arg)
        if statement.args.vararg is not None:
            annotation = statement.args.vararg.annotation
            if annotation is None:
                self._add_error(
                    "XCC-AOT-TYPE-0001",
                    "Missing annotation for parameter: "
                    f"{function_name}.{statement.args.vararg.arg}",
                    statement,
                )
            else:
                annotation_text = annotation_name(annotation)
                vararg = (statement.args.vararg.arg, annotation_text)
                self._resolve_annotation(annotation, statement.args.vararg)
        for arg, default in zip(
            statement.args.kwonlyargs,
            statement.args.kw_defaults,
            strict=True,
        ):
            if arg.annotation is None:
                self._add_error(
                    "XCC-AOT-TYPE-0001",
                    f"Missing annotation for parameter: {function_name}.{arg.arg}",
                    statement,
                )
                continue
            parameters.append((arg.arg, annotation_name(arg.annotation)))
            parameter_defaults.append(default)
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
            tuple(parameter_defaults),
            vararg,
        )

    def _resolve_annotation(self, node: ast.expr, owner: ast.AST) -> AotType:
        name = annotation_name(node)
        alias = self.width_aliases.get(name)
        if alias is not None:
            return alias
        alias = self.aliases.get(name)
        if alias is not None:
            return alias
        if name in self.classes or name in self.known_local_classes or is_builtin_type_name(name):
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


def _iterable_item_type(type_info: AotType | None) -> AotType | None:
    if type_info is None:
        return None
    name = type_info.name.strip()
    bracket = name.find("[")
    if bracket < 0 or not name.endswith("]"):
        return None
    base = name[:bracket].rsplit(".", 1)[-1]
    parts = _split_annotation_parts(name[bracket + 1 : -1], ",")
    if base == "dict" and len(parts) == 2:
        return AotType(parts[0].strip())
    if base not in {"Iterable", "Sequence", "frozenset", "list", "set", "tuple"}:
        return None
    if base == "tuple" and len(parts) > 1 and parts[-1].strip() != "...":
        first = parts[0].strip()
        if any(part.strip() != first for part in parts[1:]):
            return None
    if not parts:
        return None
    return AotType(parts[0].strip())


def _bind_comprehension_target(
    target: ast.expr,
    item_type: AotType,
    local_types: dict[str, AotType],
) -> bool:
    if isinstance(target, ast.Name):
        local_types[target.id] = item_type
        return True
    if not isinstance(target, ast.Tuple):
        return False
    name = item_type.name.strip()
    if not name.startswith("tuple[") or not name.endswith("]"):
        return False
    parts = _split_annotation_parts(name[6:-1], ",")
    if len(parts) != len(target.elts):
        return False
    for element, part in zip(target.elts, parts, strict=True):
        if not _bind_comprehension_target(element, AotType(part.strip()), local_types):
            return False
    return True


def _value_bool_op_type(
    values: tuple[ast.expr, ...],
    types: tuple[AotType | None, ...],
) -> AotType | None:
    candidates = tuple(
        normalized
        for type_info in types
        if type_info is not None
        for normalized in (_without_none_type(type_info),)
        if normalized.name != "None"
    )
    if not candidates or any(candidate != candidates[0] for candidate in candidates[1:]):
        return None
    result = candidates[0]
    for value, type_info in zip(values, types, strict=True):
        if type_info is not None and _without_none_type(type_info) == result:
            continue
        if _empty_literal_matches_type(value, result.name):
            continue
        return None
    return result


def _without_none_type(type_info: AotType) -> AotType:
    parts = _split_annotation_parts(type_info.name, "|")
    if len(parts) <= 1:
        return type_info
    non_none = tuple(part.strip() for part in parts if part.strip() != "None")
    if len(non_none) == 1:
        return AotType(non_none[0])
    return type_info


def _empty_literal_matches_type(value: ast.expr, type_name: str) -> bool:
    if isinstance(value, ast.Dict):
        return not value.keys and type_name.startswith(("dict[", "Dict["))
    if isinstance(value, ast.List):
        return not value.elts and type_name.startswith(("list[", "List["))
    if isinstance(value, ast.Set):
        return not value.elts and type_name.startswith(("set[", "Set["))
    if isinstance(value, ast.Tuple):
        return not value.elts and type_name.startswith(("tuple[", "Tuple["))
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and not value.args
        and not value.keywords
    ):
        return type_name.startswith(f"{value.func.id}[") and value.func.id in {
            "dict",
            "frozenset",
            "list",
            "set",
            "tuple",
        }
    return False


def _init_field_parameter(value: ast.expr | None) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or) and value.values:
        first = value.values[0]
        if isinstance(first, ast.Name):
            return first.id
    return None


def _init_self_assignments(
    statements: Sequence[ast.stmt],
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


def _class_is_kw_only_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = ast.unparse(decorator.func)
        if name.rsplit(".", 1)[-1] != "dataclass":
            continue
        for keyword in decorator.keywords:
            if (
                keyword.arg == "kw_only"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            ):
                return True
    return False


def _is_supported_composite_annotation(name: str) -> bool:
    return _is_supported_annotation_text(name.strip())


def _is_supported_annotation_text(text: str) -> bool:
    text = text.strip()
    while _annotation_parentheses_wrap(text):
        text = text[1:-1].strip()
    if not text:
        return False
    if text[:1] in {'"', "'"}:
        if len(text) < 2 or text[-1] != text[0]:
            return False
        return _is_supported_annotation_text(text[1:-1].strip())
    union_parts = _split_annotation_parts(text, "|")
    if len(union_parts) > 1:
        return all(_is_supported_annotation_text(part) for part in union_parts)
    bracket = text.find("[")
    if bracket < 0:
        if text == "...":
            return True
        return (
            is_builtin_type_name(text)
            or width_alias_type(text) is not None
            or text in _OWNED_AST_TYPE_NAMES
            or _is_project_type_reference(text)
            or _is_dotted_annotation_name(text)
        )
    if not text.endswith("]") or not _balanced_annotation_text(text):
        return False
    base = text[:bracket].strip()
    body = text[bracket + 1 : -1].strip()
    elements = _split_annotation_parts(body, ",")
    if base == "Literal":
        return bool(elements) and all(_is_string_literal_text(item) for item in elements)
    if base in {"Iterable", "Sequence", "list", "set", "frozenset"}:
        return len(elements) == 1 and _is_supported_annotation_text(elements[0])
    if base == "dict":
        return len(elements) == 2 and all(_is_supported_annotation_text(item) for item in elements)
    if base == "tuple":
        if body == "()":
            return True
        return bool(elements) and all(
            item == "..." or _is_supported_annotation_text(item) for item in elements
        )
    if base != "Callable" or len(elements) != 2:
        return False
    args, return_type = elements
    if args == "...":
        return _is_supported_annotation_text(return_type)
    if not args.startswith("[") or not args.endswith("]"):
        return False
    arg_body = args[1:-1].strip()
    arg_types = () if not arg_body else _split_annotation_parts(arg_body, ",")
    return all(_is_supported_annotation_text(arg) for arg in arg_types) and (
        _is_supported_annotation_text(return_type)
    )


def _split_annotation_parts(text: str, separator: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    bracket_depth = 0
    parenthesis_depth = 0
    quote = ""
    escaped = False
    for index, ch in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'"}:
            quote = ch
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
        elif ch == "(":
            parenthesis_depth += 1
        elif ch == ")":
            parenthesis_depth -= 1
        elif ch == separator and bracket_depth == 0 and parenthesis_depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return tuple(parts)


def _balanced_annotation_text(text: str) -> bool:
    bracket_depth = 0
    parenthesis_depth = 0
    quote = ""
    escaped = False
    for ch in text:
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'"}:
            quote = ch
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth -= 1
            if bracket_depth < 0:
                return False
        elif ch == "(":
            parenthesis_depth += 1
        elif ch == ")":
            parenthesis_depth -= 1
            if parenthesis_depth < 0:
                return False
    return bracket_depth == 0 and parenthesis_depth == 0 and not quote


def _annotation_parentheses_wrap(text: str) -> bool:
    if len(text) < 2 or text[0] != "(" or text[-1] != ")":
        return False
    depth = 0
    quote = ""
    escaped = False
    for index, ch in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'"}:
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and index != len(text) - 1:
                return False
            if depth < 0:
                return False
    return depth == 0 and not quote


def _is_dotted_annotation_name(text: str) -> bool:
    parts = text.split(".")
    return len(parts) > 1 and all(part.isidentifier() for part in parts)


def _is_string_literal_text(text: str) -> bool:
    if len(text) < 2 or text[0] not in {'"', "'"} or text[-1] != text[0]:
        return False
    quote = text[0]
    escaped = False
    for index, ch in enumerate(text[1:], start=1):
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == quote:
            return index == len(text) - 1
    return False


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
        return bool(elements) and all(
            isinstance(element, ast.Constant) and isinstance(element.value, str)
            for element in elements
        )
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
