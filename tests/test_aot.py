import ast
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotDiagnostic,
    AotError,
    analyze_path,
    analyze_source,
    bind_types,
    check_subset,
    parse_source,
)
from xcc.aot.diag import node_location
from xcc.aot.binder import (
    _is_supported_annotation_node,
    _is_supported_composite_annotation,
)


class AotDiagnosticTests(unittest.TestCase):
    def test_diagnostic_with_location(self) -> None:
        diagnostic = AotDiagnostic(
            "XCC-AOT-SUBSET-0001",
            "Unsupported Python syntax: Lambda",
            filename="sample.py",
            line=3,
            column=5,
        )
        self.assertEqual(
            str(diagnostic),
            "sample.py:3:5: aot: XCC-AOT-SUBSET-0001: Unsupported Python syntax: Lambda",
        )

    def test_diagnostic_without_location(self) -> None:
        diagnostic = AotDiagnostic(
            "XCC-AOT-TYPE-0002",
            "Unsupported annotation: object",
            filename="sample.py",
        )
        self.assertEqual(
            str(diagnostic),
            "sample.py: aot: XCC-AOT-TYPE-0002: Unsupported annotation: object",
        )

    def test_error_wraps_diagnostics(self) -> None:
        first = AotDiagnostic("XCC-AOT-PARSE-0001", "invalid syntax", filename="bad.py")
        second = AotDiagnostic(
            "XCC-AOT-TYPE-0001",
            "Missing return annotation",
            filename="bad.py",
        )
        error = AotError((first, second))
        self.assertEqual(error.diagnostics, (first, second))
        self.assertEqual(str(error), "bad.py: aot: XCC-AOT-PARSE-0001: invalid syntax")

    def test_error_rejects_empty_diagnostics(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            AotError(())
        self.assertEqual(str(ctx.exception), "AotError requires at least one diagnostic")

    def test_node_location_handles_positioned_and_synthetic_nodes(self) -> None:
        function = ast.parse("def f() -> int:\n    return 1\n").body[0]
        self.assertEqual(node_location(function), (1, 0))
        self.assertEqual(node_location(ast.Pass()), (None, None))


class AotModuleParseTests(unittest.TestCase):
    def test_parse_source_records_filename_and_tree(self) -> None:
        module = parse_source("def f() -> int:\n    return 1\n", filename="sample.py")
        self.assertEqual(module.filename, "sample.py")
        self.assertEqual(module.source, "def f() -> int:\n    return 1\n")
        self.assertEqual(len(module.tree.body), 1)

    def test_parse_source_reports_syntax_error(self) -> None:
        with self.assertRaises(AotError) as ctx:
            parse_source("def bad(:\n    return 1\n", filename="bad.py")
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-PARSE-0001")
        self.assertEqual(diagnostic.filename, "bad.py")
        self.assertEqual(diagnostic.line, 1)
        self.assertIsNotNone(diagnostic.column)
        self.assertIn("invalid syntax", diagnostic.message)


class AotSubsetCheckerTests(unittest.TestCase):
    def test_accepts_dataclass_and_typed_function(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Point:\n"
            "    x: int\n"
            "    y: int\n"
            "def add(point: Point) -> int:\n"
            "    return point.x + point.y\n"
        )
        summary = check_subset(parse_source(source, filename="point.py"))
        self.assertEqual(summary.filename, "point.py")
        self.assertEqual(summary.imports, ("dataclasses",))
        self.assertEqual(summary.classes, ("Point",))
        self.assertEqual(summary.functions, ("add",))

    def test_rejects_lambda_expression(self) -> None:
        module = parse_source("value = lambda x: x\n", filename="bad.py")
        with self.assertRaises(AotError) as ctx:
            check_subset(module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-SUBSET-0001")
        self.assertEqual(diagnostic.message, "Unsupported Python syntax: Lambda")
        self.assertEqual((diagnostic.line, diagnostic.column), (1, 8))

    def test_rejects_custom_decorator(self) -> None:
        source = "def marker(fn):\n    return fn\n@marker\ndef f() -> int:\n    return 1\n"
        module = parse_source(source, filename="decorator.py")
        with self.assertRaises(AotError) as ctx:
            check_subset(module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-SUBSET-0002")
        self.assertEqual(diagnostic.message, "Unsupported decorator: marker")

    def test_rejects_dynamic_reflection_call(self) -> None:
        source = "def f(value: object) -> object:\n    return getattr(value, 'x')\n"
        module = parse_source(source, filename="bad.py")
        with self.assertRaises(AotError) as ctx:
            check_subset(module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-SUBSET-0003")
        self.assertEqual(diagnostic.message, "Unsupported dynamic call: getattr")

    def test_records_import_roots_once_and_ignores_relative_import_module(self) -> None:
        source = "import os\nimport os.path\nfrom . import local\ndef f() -> int:\n    return 1\n"
        summary = check_subset(parse_source(source, filename="imports.py"))
        self.assertEqual(summary.imports, ("os",))
        self.assertEqual(summary.functions, ("f",))

    def test_accepts_bare_dataclass_decorator_and_attribute_call(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Box:\n"
            "    value: int\n"
            "def f(value: Box) -> int:\n"
            "    value.touch()\n"
            "    return 1\n"
        )
        summary = check_subset(parse_source(source, filename="bare_dataclass.py"))
        self.assertEqual(summary.classes, ("Box",))
        self.assertEqual(summary.functions, ("f",))

    def test_rejects_decorator_call_that_is_not_dataclass(self) -> None:
        source = (
            "def marker() -> object:\n"
            "    return object()\n"
            "@marker()\n"
            "def f() -> int:\n"
            "    return 1\n"
        )
        module = parse_source(source, filename="decorator_call.py")
        with self.assertRaises(AotError) as ctx:
            check_subset(module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-SUBSET-0002")
        self.assertEqual(diagnostic.message, "Unsupported decorator: marker()")

    def test_rejects_dataclass_unsupported_keyword(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "@dataclass(slots=True)\n"
            "class Box:\n"
            "    value: int\n"
        )
        module = parse_source(source, filename="dataclass_keyword.py")
        with self.assertRaises(AotError) as ctx:
            check_subset(module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-SUBSET-0002")
        self.assertEqual(diagnostic.message, "Unsupported decorator: dataclass(slots=True)")

    def test_rejects_dataclass_non_constant_frozen(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "flag = True\n"
            "@dataclass(frozen=flag)\n"
            "class Box:\n"
            "    value: int\n"
        )
        module = parse_source(source, filename="dataclass_dynamic.py")
        with self.assertRaises(AotError) as ctx:
            check_subset(module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-SUBSET-0002")
        self.assertEqual(diagnostic.message, "Unsupported decorator: dataclass(frozen=flag)")

    def test_rejects_dataclass_false_frozen(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=False)\n"
            "class Box:\n"
            "    value: int\n"
        )
        module = parse_source(source, filename="dataclass_false.py")
        with self.assertRaises(AotError) as ctx:
            check_subset(module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-SUBSET-0002")
        self.assertEqual(diagnostic.message, "Unsupported decorator: dataclass(frozen=False)")


class AotTypeBinderTests(unittest.TestCase):
    def test_binds_width_alias_dataclass_and_function(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "int64 = int\n"
            "@dataclass(frozen=True)\n"
            "class Box:\n"
            "    value: int64\n"
            "def unwrap(box: Box) -> int64:\n"
            "    return box.value\n"
        )
        module = parse_source(source, filename="box.py")
        analysis = bind_types(check_subset(module), module)
        self.assertEqual(analysis.width_aliases["int64"].bits, 64)
        self.assertTrue(analysis.width_aliases["int64"].signed)
        self.assertEqual(analysis.classes["Box"].fields["value"].name, "int64")
        self.assertEqual(analysis.functions["unwrap"].return_type.name, "int64")
        self.assertEqual(analysis.functions["unwrap"].parameters, (("box", "Box"),))

    def test_binds_unsigned_width_alias(self) -> None:
        source = "uint32 = int\ndef f(value: uint32) -> uint32:\n    return value\n"
        module = parse_source(source, filename="u.py")
        analysis = bind_types(check_subset(module), module)
        self.assertEqual(analysis.width_aliases["uint32"].bits, 32)
        self.assertFalse(analysis.width_aliases["uint32"].signed)

    def test_rejects_missing_parameter_annotation(self) -> None:
        source = "def f(value) -> int:\n    return value\n"
        module = parse_source(source, filename="missing.py")
        with self.assertRaises(AotError) as ctx:
            bind_types(check_subset(module), module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-TYPE-0001")
        self.assertEqual(diagnostic.message, "Missing annotation for parameter: f.value")

    def test_rejects_unsupported_annotation(self) -> None:
        source = "def f(value: complex) -> complex:\n    return value\n"
        module = parse_source(source, filename="badtype.py")
        with self.assertRaises(AotError) as ctx:
            bind_types(check_subset(module), module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-TYPE-0002")
        self.assertEqual(diagnostic.message, "Unsupported annotation: complex")

    def test_rejects_conflicting_width_alias(self) -> None:
        source = "int64 = str\ndef f(value: int64) -> int64:\n    return value\n"
        module = parse_source(source, filename="alias.py")
        with self.assertRaises(AotError) as ctx:
            bind_types(check_subset(module), module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-TYPE-0003")
        self.assertEqual(diagnostic.message, "Width alias must target int: int64")

    def test_ignores_non_alias_assignments_and_non_name_targets(self) -> None:
        source = "count = int\n(int64,) = (int,)\ndef f(value: int) -> int:\n    return value\n"
        module = parse_source(source, filename="assignments.py")
        analysis = bind_types(check_subset(module), module)
        self.assertEqual(analysis.width_aliases, {})

    def test_ignores_non_field_class_body_entries(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Box:\n"
            "    'doc'\n"
            "    value: int\n"
        )
        module = parse_source(source, filename="class_body.py")
        analysis = bind_types(check_subset(module), module)
        self.assertEqual(analysis.classes["Box"].fields["value"].name, "int")

    def test_rejects_missing_return_annotation(self) -> None:
        source = "def f(value: int):\n    return value\n"
        module = parse_source(source, filename="missing_return.py")
        with self.assertRaises(AotError) as ctx:
            bind_types(check_subset(module), module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-TYPE-0001")
        self.assertEqual(diagnostic.message, "Missing return annotation for function: f")

    def test_binds_none_return_annotation(self) -> None:
        source = "def f() -> None:\n    return None\n"
        module = parse_source(source, filename="none_return.py")
        analysis = bind_types(check_subset(module), module)
        self.assertEqual(analysis.functions["f"].return_type.name, "None")

    def test_binds_bytes_annotations(self) -> None:
        source = "def f(value: bytes | None) -> bytes:\n    return value or b''\n"
        module = parse_source(source, filename="bytes_annotation.py")
        analysis = bind_types(check_subset(module), module)
        self.assertEqual(analysis.functions["f"].parameters, (("value", "bytes | None"),))
        self.assertEqual(analysis.functions["f"].return_type.name, "bytes")

    def test_binds_datetime_annotations(self) -> None:
        source = (
            "from datetime import datetime\n"
            "def f(value: datetime) -> str:\n"
            "    return str(value.year)\n"
        )
        module = parse_source(source, filename="datetime_annotation.py")
        analysis = bind_types(check_subset(module), module)
        self.assertEqual(analysis.functions["f"].parameters, (("value", "datetime"),))

    def test_rejects_subscript_annotation_with_unsupported_element(self) -> None:
        source = "def f(value: list[complex]) -> int:\n    return 1\n"
        module = parse_source(source, filename="subscript.py")
        with self.assertRaises(AotError) as ctx:
            bind_types(check_subset(module), module)
        diagnostic = ctx.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "XCC-AOT-TYPE-0002")
        self.assertEqual(diagnostic.message, "Unsupported annotation: list[complex]")

    def test_annotation_support_helper_edges(self) -> None:
        self.assertTrue(_is_supported_composite_annotation("ast.expr"))
        self.assertTrue(_is_supported_composite_annotation("'Type | None'"))
        self.assertTrue(_is_supported_composite_annotation("tuple[str, ...]"))
        self.assertTrue(_is_supported_composite_annotation("Callable[..., bool]"))
        self.assertFalse(_is_supported_composite_annotation("["))
        self.assertFalse(_is_supported_composite_annotation("list[str, int]"))
        self.assertFalse(_is_supported_composite_annotation("dict[str]"))
        self.assertFalse(_is_supported_composite_annotation("Callable[[str]]"))
        self.assertFalse(_is_supported_composite_annotation("Callable[[str], complex]"))
        self.assertFalse(_is_supported_composite_annotation("Callable[str, bool]"))
        self.assertFalse(_is_supported_composite_annotation("type[str]"))

        ellipsis_constant = ast.parse("value = ...\n").body[0].value
        unsupported_constant = ast.parse("value = 1\n").body[0].value
        unsupported_expr = ast.parse("value = 1 + 2\n").body[0].value
        self.assertTrue(_is_supported_annotation_node(ellipsis_constant))
        self.assertFalse(_is_supported_annotation_node(unsupported_constant))
        self.assertFalse(_is_supported_annotation_node(unsupported_expr))


class AotAnalysisApiTests(unittest.TestCase):
    def test_analyze_source_returns_summary_and_types(self) -> None:
        source = "int64 = int\ndef f(value: int64) -> int64:\n    return value\n"
        analysis = analyze_source(source, filename="api.py")
        self.assertEqual(analysis.module.filename, "api.py")
        self.assertEqual(analysis.summary.functions, ("f",))
        self.assertEqual(analysis.types.functions["f"].return_type.name, "int64")

    def test_analyze_source_raises_first_stage_error(self) -> None:
        with self.assertRaises(AotError) as ctx:
            analyze_source("value = lambda x: x\n", filename="bad.py")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SUBSET-0001")

    def test_analyze_path_reads_python_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api.py"
            path.write_text(
                "int64 = int\ndef f(value: int64) -> int64:\n    return value\n",
                encoding="utf-8",
            )
            analysis = analyze_path(path)
        self.assertEqual(analysis.module.filename, str(path))
        self.assertEqual(analysis.types.functions["f"].return_type.name, "int64")


if __name__ == "__main__":
    unittest.main()
