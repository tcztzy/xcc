import io
import json
import tarfile
import tempfile
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import sync_clang_fixtures
from tests import _bootstrap  # noqa: F401
from xcc.clang_suite import (
    ALLOWED_EXPECTATIONS,
    SKIP_REASON_KEY,
    baseline_skip_reason,
    case_id_from_upstream_path,
    fixture_path_from_upstream_path,
    infer_expectation_from_source,
    is_clang_test_case_path,
    matches_expectation,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/external/clang/manifest.json"
HOST_PATH_MARKERS = (
    "/Applications/Xcode",
    "/Users/",
    "/home/",
    "/private/",
    "/tmp/",
    r"C:\\",
)


class ClangSuiteHelperTests(unittest.TestCase):
    def test_allowed_expectations_and_skip_key(self) -> None:
        self.assertEqual(ALLOWED_EXPECTATIONS, {"ok", "error", "lex", "pp", "parse", "sema"})
        self.assertEqual(SKIP_REASON_KEY, "skip_reason")

    def test_is_clang_test_case_path_filters_to_c_fixtures(self) -> None:
        self.assertTrue(is_clang_test_case_path("clang/test/Sema/warn-null.c"))
        self.assertFalse(is_clang_test_case_path("clang/docs/index.rst"))
        self.assertFalse(is_clang_test_case_path("clang/test/Sema/vector-gcc-compat.cpp"))

    def test_fixture_path_and_case_id_come_from_upstream_path(self) -> None:
        upstream = "clang/test/Sema/warn-null.c"
        self.assertEqual(
            fixture_path_from_upstream_path(upstream),
            "tests/external/clang/generated/Sema/warn-null.c",
        )
        self.assertEqual(case_id_from_upstream_path(upstream), "clang-sema-warn-null-c-a3c7de133a")
        punctuated_case_id = case_id_from_upstream_path("clang/test/Sema/mixed.../warn+null!.c")
        self.assertTrue(punctuated_case_id.startswith("clang-sema-mixed-warn-null-c-"))
        self.assertNotIn("--", punctuated_case_id)

    def test_infer_expectation_from_source_prefers_expected_no_diagnostics(self) -> None:
        source = (
            "// expected-no-diagnostics\n// expected-error {{ignored by baseline classifier}}\n"
        )
        self.assertEqual(infer_expectation_from_source(source), "ok")
        self.assertEqual(
            infer_expectation_from_source("// expected-error {{bad}}\n"),
            "error",
        )
        self.assertEqual(infer_expectation_from_source("int main(void) { return 0; }\n"), "ok")

    def test_matches_expectation_handles_coarse_and_specific_cases(self) -> None:
        self.assertTrue(matches_expectation("ok", "ok"))
        self.assertFalse(matches_expectation("ok", "parse"))
        self.assertTrue(matches_expectation("error", "parse"))
        self.assertFalse(matches_expectation("error", "ok"))
        self.assertTrue(matches_expectation("parse", "parse"))
        self.assertFalse(matches_expectation("parse", "sema"))

    def test_baseline_skip_reason_includes_optional_detail(self) -> None:
        self.assertEqual(
            baseline_skip_reason("ok", "parse"),
            "baseline skip: expected ok, got parse",
        )
        self.assertEqual(
            baseline_skip_reason("error", "ok", "compiled successfully"),
            "baseline skip: expected error, got ok (compiled successfully)",
        )

    def test_baseline_skip_reason_sanitizes_host_paths(self) -> None:
        detail = (
            'Include not found: "header.h"; searched: '
            "/Users/me/work/xcc/tests/external/clang/generated/Sema, "
            "/Applications/Xcode.app/Contents/Developer/Toolchains/"
            "XcodeDefault.xctoolchain/usr/lib/clang/21/include, "
            "/Applications/Xcode.app/Contents/Developer/Platforms/"
            "MacOSX.platform/Developer/SDKs/MacOSX.sdk/usr/include, "
            "/usr/include"
        )
        reason = baseline_skip_reason("ok", "pp", detail)
        self.assertIn("tests/external/clang/generated/Sema", reason)
        self.assertIn("<clang-resource-include>", reason)
        self.assertIn("<macos-sdk-include>", reason)
        self.assertIn("<system-include>", reason)
        for marker in HOST_PATH_MARKERS:
            self.assertNotIn(marker, reason)
        self.assertNotIn("/usr/include", reason)

    def test_manifest_skip_reasons_do_not_capture_host_paths(self) -> None:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for case in payload["cases"]:
            reason = case.get(SKIP_REASON_KEY)
            if not isinstance(reason, str):
                continue
            with self.subTest(case=case["id"]):
                for marker in HOST_PATH_MARKERS:
                    self.assertNotIn(marker, reason)
                self.assertNotIn("/usr/include", reason)

    def test_sync_script_materializes_and_checks_fixture_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "llvm.tar.gz"
            data = b"int sample(void) { return 0; }\n"
            with tarfile.open(archive_path, mode="w:gz") as archive:
                member = tarfile.TarInfo("llvm-project/clang/test/Sema/sample.c")
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))

            payload = {
                "upstream": {"strip_components": 1},
                "cases": [
                    {
                        "id": "clang-sema-sample-c",
                        "upstream": "clang/test/Sema/sample.c",
                        "fixture": "tests/external/clang/generated/Sema/sample.c",
                        "expect": "ok",
                        "sha256": sync_clang_fixtures._sha256(data),
                    }
                ],
            }
            manifest_path = root / "manifest.json"
            with patch.object(sync_clang_fixtures, "ROOT", root):
                sync_clang_fixtures._materialize_external_cases(
                    payload=payload,
                    archive_path=archive_path,
                    update_sha=False,
                    clean_external=False,
                    manifest_path=manifest_path,
                )
                fixture = root / "tests/external/clang/generated/Sema/sample.c"
                self.assertEqual(fixture.read_bytes(), data)
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = sync_clang_fixtures._run_check(
                        payload=payload,
                        archive_path=archive_path,
                    )
                self.assertEqual(code, 0)
                self.assertIn("clang fixtures check passed for 1 cases", stdout.getvalue())
