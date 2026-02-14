import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from tests import _bootstrap  # noqa: F401
from xcc.frontend import FrontendError, compile_source

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/external/clang/manifest.json"
ALLOWED_EXPECTATIONS = {"ok", "pp", "lex", "parse", "sema"}
REQUIRED_CASE_KEYS = {"id", "upstream", "fixture", "expect", "sha256"}
OPTIONAL_CASE_KEYS = {"message_contains", "line", "column"}


def _load_cases() -> list[dict[str, Any]]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise AssertionError("clang manifest must contain a list under cases")
    cases: list[dict[str, Any]] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise AssertionError("each clang manifest case must be an object")
        case = dict(raw_case)
        cases.append(case)
    return cases


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ClangSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._cases = _load_cases()

    def test_clang_fixtures_match_manifest_checksums(self) -> None:
        for case in self._cases:
            with self.subTest(case=case.get("id", "<missing-id>")):
                fixture = ROOT / case["fixture"]
                self.assertTrue(fixture.is_file(), f"missing fixture: {fixture}")
                self.assertEqual(_sha256(fixture.read_bytes()), case["sha256"])

    def test_clang_manifest_case_schema(self) -> None:
        case_ids: set[str] = set()
        for case in self._cases:
            case_id = case.get("id", "<missing-id>")
            with self.subTest(case=case_id):
                keys = set(case)
                self.assertTrue(REQUIRED_CASE_KEYS.issubset(keys))
                self.assertTrue(keys.issubset(REQUIRED_CASE_KEYS | OPTIONAL_CASE_KEYS))
                self.assertIsInstance(case["id"], str)
                self.assertNotEqual(case["id"], "")
                self.assertNotIn(case["id"], case_ids)
                case_ids.add(case["id"])
                self.assertIsInstance(case["upstream"], str)
                self.assertIsInstance(case["fixture"], str)
                self.assertIsInstance(case["expect"], str)
                self.assertIsInstance(case["sha256"], str)
                if "message_contains" in case:
                    self.assertIsInstance(case["message_contains"], str)
                if "line" in case:
                    self.assertIsInstance(case["line"], int)
                if "column" in case:
                    self.assertIsInstance(case["column"], int)

    def test_clang_fixtures_match_expected_frontend_stage(self) -> None:
        for case in self._cases:
            case_id = case.get("id", "<missing-id>")
            expectation = case["expect"]
            fixture = ROOT / case["fixture"]
            source = fixture.read_text(encoding="utf-8")
            with self.subTest(case=case_id, expect=expectation):
                self.assertIn(expectation, ALLOWED_EXPECTATIONS)
                if expectation == "ok":
                    compile_source(source, filename=str(fixture))
                    continue
                with self.assertRaises(FrontendError) as ctx:
                    compile_source(source, filename=str(fixture))
                diagnostic = ctx.exception.diagnostic
                self.assertEqual(diagnostic.stage, expectation)
                message_contains = case.get("message_contains")
                if isinstance(message_contains, str):
                    self.assertIn(message_contains, diagnostic.message)
                line = case.get("line")
                if isinstance(line, int):
                    self.assertEqual(diagnostic.line, line)
                column = case.get("column")
                if isinstance(column, int):
                    self.assertEqual(diagnostic.column, column)


if __name__ == "__main__":
    unittest.main()
