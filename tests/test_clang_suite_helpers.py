import unittest

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
        punctuated_case_id = case_id_from_upstream_path(
            "clang/test/Sema/mixed.../warn+null!.c"
        )
        self.assertTrue(punctuated_case_id.startswith("clang-sema-mixed-warn-null-c-"))
        self.assertNotIn("--", punctuated_case_id)

    def test_infer_expectation_from_source_prefers_expected_no_diagnostics(self) -> None:
        source = "// expected-no-diagnostics\n// expected-error {{ignored by baseline classifier}}\n"
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
