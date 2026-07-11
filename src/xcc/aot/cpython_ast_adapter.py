import ast as cpython_ast

from xcc.aot import py_ast


def parse_cpython_source(source: str, *, filename: str) -> py_ast.Module:
    tree = cpython_ast.parse(source, filename=filename, feature_version=(3, 11))
    converted = _convert_node(tree)
    if not isinstance(converted, py_ast.Module):
        raise TypeError("CPython parser did not produce a module")
    return converted


def parse_cpython_expression(source: str, *, filename: str) -> py_ast.Expression:
    tree = cpython_ast.parse(
        source,
        filename=filename,
        mode="eval",
        feature_version=(3, 11),
    )
    converted = _convert_node(tree)
    if not isinstance(converted, py_ast.Expression):
        raise TypeError("CPython parser did not produce an expression")
    return converted


def _convert_node(node: cpython_ast.AST) -> py_ast.AST:
    converted_fields: list[tuple[str, object]] = []
    children: list[py_ast.AST] = []
    for name in node._fields:
        value = _convert_value(getattr(node, name))
        converted_fields.append((name, value))
        _append_children(children, value)
    node_type = getattr(py_ast, type(node).__name__, None)
    span = py_ast.SourceSpan(
        getattr(node, "lineno", None),
        getattr(node, "col_offset", None),
        getattr(node, "end_lineno", None),
        getattr(node, "end_col_offset", None),
    )
    try:
        text = cpython_ast.unparse(node)
    except (AttributeError, ValueError):
        text = ""
    if node_type is None:
        converted = py_ast.UnsupportedNode(
            type(node).__name__,
            tuple(value for _, value in converted_fields),
            span=span,
            text=text,
            children=tuple(children),
        )
    else:
        kwargs = dict(converted_fields)
        if node_type in {py_ast.FunctionDef, py_ast.AsyncFunctionDef, py_ast.ClassDef}:
            kwargs.setdefault("type_params", ())
        converted = node_type(
            **kwargs,
            span=span,
            text=text,
            children=tuple(children),
        )
    return converted


def _convert_value(value: object) -> object:
    if isinstance(value, cpython_ast.AST):
        return _convert_node(value)
    if isinstance(value, list):
        return tuple(_convert_value(item) for item in value)
    return value


def _append_children(children: list[py_ast.AST], value: object) -> None:
    if isinstance(value, py_ast.AST):
        children.append(value)
    elif isinstance(value, tuple):
        for item in value:
            if isinstance(item, py_ast.AST):
                children.append(item)
