import unittest

from tests import _bootstrap  # noqa: F401
from xcc.aot import AotDiagnostic, AotError, check_subset, parse_source


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


if __name__ == "__main__":
    unittest.main()
