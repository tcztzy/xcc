import json
from dataclasses import dataclass, fields
from pathlib import Path

from xcc.aot.cpython_ast_adapter import parse_cpython_source
from xcc.aot.module import AotModule
from xcc.aot.py_parser import parse_subset_source
from xcc.aot.source_contract import (
    HOSTED_ONLY_MODULES,
    CachePolicy,
    ParserBackend,
    resolve_source_set,
    source_module_name,
)

from . import py_ast as ast
from .diag import AotError


@dataclass(frozen=True)
class ParserOracleReport:
    source_root: str
    entry: str
    checked: int
    closure: tuple[str, ...]
    failures: tuple[str, ...]


def normalize_owned_ast(node: ast.AST) -> tuple[object, ...]:
    semantic_fields: list[tuple[str, object]] = []
    for item in fields(node):
        if item.name in {"span", "text", "children"}:
            continue
        semantic_fields.append((item.name, _normalize_value(getattr(node, item.name))))
    child_edges = tuple(
        (type(child).__name__, _normalize_span(child.span)) for child in node.children
    )
    return (
        type(node).__name__,
        _normalize_span(node.span),
        tuple(semantic_fields),
        child_edges,
    )


def run_parser_oracle(source_root: Path, entry_module: str) -> ParserOracleReport:
    root = source_root.resolve()
    hosted_set = resolve_source_set(
        root,
        entry_module,
        ParserBackend("cpython", _parse_cpython_module),
        CachePolicy(True),
    )
    subset_set = resolve_source_set(
        root,
        entry_module,
        ParserBackend("subset", _parse_subset_module),
        CachePolicy(True),
    )
    hosted_closure = tuple(unit.module for unit in hosted_set.units)
    subset_closure = tuple(unit.module for unit in subset_set.units)
    failures: list[str] = []
    if hosted_closure != subset_closure:
        failures.append(f"dependency closure differs: {hosted_closure!r} != {subset_closure!r}")
    hosted_units = {unit.canonical_path: unit.parsed for unit in hosted_set.units}
    subset_units = {unit.canonical_path: unit.parsed for unit in subset_set.units}

    checked = 0
    for path in sorted(root.rglob("*.py")):
        module_name = source_module_name(root, path)
        if module_name in HOSTED_ONLY_MODULES:
            continue
        checked += 1
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        try:
            canonical_path = str(path.resolve())
            hosted_module = hosted_units.get(canonical_path)
            subset_module = subset_units.get(canonical_path)
            hosted = (
                hosted_module.tree
                if hosted_module is not None
                else parse_cpython_source(source, filename=str(path))
            )
            subset = (
                subset_module.tree
                if subset_module is not None
                else parse_subset_source(source, filename=str(path)).tree
            )
        except (AotError, SyntaxError) as error:
            failures.append(f"{relative}: {type(error).__name__}: {error}")
            continue
        if normalize_owned_ast(subset) != normalize_owned_ast(hosted):
            failures.append(f"{relative}: normalized owned AST differs")

    return ParserOracleReport(
        str(root),
        entry_module,
        checked,
        subset_closure,
        tuple(failures),
    )


def render_parser_oracle_report(report: ParserOracleReport) -> str:
    payload = {
        "checked": report.checked,
        "closure": list(report.closure),
        "entry": report.entry,
        "failures": list(report.failures),
        "source_root": report.source_root,
        "version": 1,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def _parse_cpython_module(source: str, filename: str) -> AotModule:
    return AotModule(
        filename,
        source,
        parse_cpython_source(source, filename=filename),
    )


def _parse_subset_module(source: str, filename: str) -> AotModule:
    return parse_subset_source(source, filename=filename)


def _normalize_value(value: object) -> object:
    if isinstance(value, ast.AST):
        return normalize_owned_ast(value)
    if isinstance(value, tuple):
        return tuple(_normalize_value(item) for item in value)
    if value is Ellipsis:
        return ("Ellipsis",)
    return value


def _normalize_span(span: ast.SourceSpan) -> tuple[int | None, ...]:
    return (span.line, span.column, span.end_line, span.end_column)
