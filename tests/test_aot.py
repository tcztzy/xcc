import unittest

from tests import _bootstrap  # noqa: F401
from xcc.aot import AotDiagnostic, AotError


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


if __name__ == "__main__":
    unittest.main()
