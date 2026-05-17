import os
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from tests import _bootstrap  # noqa: F401
from xcc.clang_suite import (
    ALLOWED_EXPECTATIONS,
    SKIP_REASON_KEY,
    case_id_from_upstream_path,
)
from xcc.frontend import FrontendError, compile_source
from xcc.options import FrontendOptions
from xcc.preprocessor import preprocess_source

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/external/clang/manifest.json"
REQUIRED_CASE_KEYS = {"id", "upstream", "fixture", "expect", "sha256"}
OPTIONAL_CASE_KEYS = {"message_contains", "line", "column", SKIP_REASON_KEY}
REQUIRED_UPSTREAM_KEYS = {
    "repository",
    "release_tag",
    "archive_url",
    "archive_name",
    "archive_sha256",
    "license",
    "strip_components",
}


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


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_file_scope_embed_test(source: str) -> bool:
    """Check if source has #embed at file scope (outside any function/declaration).

    These tests produce bare integer constants at file scope after
    preprocessing, which can't be parsed. They need preprocess-only mode.
    """
    import re
    # Remove comments and preprocessor lines to find bare #embed at top level
    lines = source.splitlines()
    in_function = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if stripped.startswith("#embed"):
            if not in_function:
                return True
        if "{" in stripped:
            in_function = True
        if "}" in stripped:
            in_function = False
    return False


def _is_external_case(case: dict[str, Any]) -> bool:
    return case["upstream"].startswith("clang/test/")


def _external_fixtures_ready(cases: list[dict[str, Any]]) -> bool:
    for case in cases:
        if not _is_external_case(case):
            continue
        fixture = ROOT / case["fixture"]
        if not fixture.is_file():
            return False
        if _sha256(fixture.read_bytes()) != case["sha256"]:
            return False
    return True


def _assert_external_fixtures_ready(cases: list[dict[str, Any]]) -> None:
    if _external_fixtures_ready(cases):
        return
    raise AssertionError(
        "external clang fixtures are missing or stale; run "
        "`uv run python scripts/sync_clang_fixtures.py` first"
    )


@unittest.skipUnless(
    os.environ.get("XCC_RUN_CLANG_SUITE") == "1",
    "clang suite is disabled outside tox -e clang_suite",
)
class ClangSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._manifest = _load_manifest()
        cls._cases = _load_cases()
        _assert_external_fixtures_ready(cls._cases)

    def test_clang_fixtures_match_manifest_checksums(self) -> None:
        for case in self._cases:
            with self.subTest(case=case.get("id", "<missing-id>")):
                fixture = ROOT / case["fixture"]
                self.assertTrue(fixture.is_file(), f"missing fixture: {fixture}")
                self.assertEqual(_sha256(fixture.read_bytes()), case["sha256"])

    def test_clang_manifest_case_schema(self) -> None:
        upstream = self._manifest.get("upstream")
        self.assertIsInstance(upstream, dict)
        upstream_keys = set(upstream or {})
        self.assertTrue(REQUIRED_UPSTREAM_KEYS.issubset(upstream_keys))
        self.assertEqual(
            sorted(upstream_keys),
            sorted(REQUIRED_UPSTREAM_KEYS),
        )
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
                if _is_external_case(case):
                    self.assertTrue(case["fixture"].startswith("tests/external/clang/generated/"))
                    self.assertEqual(case["id"], case_id_from_upstream_path(case["upstream"]))
                else:
                    self.assertTrue(case["upstream"].startswith("xcc/local/"))
                    self.assertTrue(case["fixture"].startswith("tests/external/clang/fixtures/"))
                if "message_contains" in case:
                    self.assertIsInstance(case["message_contains"], str)
                if "line" in case:
                    self.assertIsInstance(case["line"], int)
                if "column" in case:
                    self.assertIsInstance(case["column"], int)
                if SKIP_REASON_KEY in case:
                    self.assertIsInstance(case[SKIP_REASON_KEY], str)
                    self.assertNotEqual(case[SKIP_REASON_KEY], "")

    def _compile_options(self, fixture: Path | None = None) -> FrontendOptions:
        embed_dirs: tuple[str, ...] = ()
        if fixture is not None:
            inputs_dir = fixture.parent / "Inputs"
            if inputs_dir.is_dir():
                embed_dirs = (str(inputs_dir),)
        return FrontendOptions(
            embed_dirs=embed_dirs,
        )

    def _assert_case_matches_expectation(self, case: dict[str, Any]) -> None:
        expectation = case["expect"]
        fixture = ROOT / case["fixture"]
        source = fixture.read_text(encoding="utf-8")
        self.assertIn(expectation, ALLOWED_EXPECTATIONS)
        opts = self._compile_options(fixture)
        # Tests where #embed is used at file scope (not inside a function
        # or declaration) need preprocess-only evaluation, since the
        # expansion produces bare integer constants.
        if _is_file_scope_embed_test(source):
            if expectation == "ok":
                try:
                    preprocess_source(source, filename=str(fixture), options=opts)
                except Exception as exc:
                    raise AssertionError(
                        f"Preprocess-only test raised: {exc}"
                    ) from exc
                return
            with self.assertRaises(Exception) as ctx:
                preprocess_source(source, filename=str(fixture), options=opts)
            return
        if expectation == "ok":
            compile_source(source, filename=str(fixture), options=opts)
            return
        with self.assertRaises(FrontendError) as ctx:
            compile_source(source, filename=str(fixture), options=opts)
        diagnostic = ctx.exception.diagnostic
        if expectation != "error":
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

    def test_clang_fixtures_match_expected_frontend_stage(self) -> None:
        for case in self._cases:
            case_id = case.get("id", "<missing-id>")
            expectation = case["expect"]
            skip_reason = case.get(SKIP_REASON_KEY)
            with self.subTest(case=case_id, expect=expectation):
                if isinstance(skip_reason, str):
                    self.skipTest(skip_reason)
                self._assert_case_matches_expectation(case)


if __name__ == "__main__":
    unittest.main()
