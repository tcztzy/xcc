import unittest

from tests import _bootstrap  # noqa: F401
from xcc.cpython_harness import (
    CPythonFailureBucket,
    CPythonTrialResult,
    bucket_location,
    blocker_code_for_result,
    normalize_trial_detail,
    summarize_trial_results,
    top_failure_bucket,
    trial_gate_verdict,
)


class CPythonHarnessTests(unittest.TestCase):
    def test_normalize_trial_detail_collapses_whitespace(self) -> None:
        self.assertEqual(
            normalize_trial_detail("Expected\t ';' \n here"),
            "Expected ';' here",
        )

    def test_blocker_code_uses_diagnostic_location_when_present(self) -> None:
        file_result = CPythonTrialResult(
            path="Programs/python.c",
            ok=False,
            stage="parse",
            detail="Expected ';'",
            diagnostic_file="/sdk/sys/_select.h",
            line=42,
            column=1,
        )
        path_result = CPythonTrialResult(
            path="Programs/python.c",
            ok=False,
            stage="parse",
            detail="Expected ';'",
        )
        self.assertTrue(blocker_code_for_result(file_result).startswith("CPY_PARSE_"))
        self.assertNotEqual(
            blocker_code_for_result(file_result),
            blocker_code_for_result(path_result),
        )

    def test_bucket_location_prefers_diagnostic_location_and_handles_missing_columns(
        self,
    ) -> None:
        bucket = CPythonFailureBucket(
            code="CPY_PARSE_DEADBEEF",
            stage="parse",
            detail="Expected ';'",
            diagnostic_file="/sdk/sys/_select.h",
            line=42,
            column=1,
            case_paths=("Programs/python.c",),
            count=1,
        )
        self.assertEqual(bucket_location(bucket), "/sdk/sys/_select.h:42:1")
        without_column = CPythonFailureBucket(
            code="CPY_PARSE_CAFEBABE",
            stage="parse",
            detail="Expected ';'",
            diagnostic_file="/sdk/sys/_select.h",
            line=42,
            column=None,
            case_paths=("Programs/python.c",),
            count=1,
        )
        self.assertEqual(bucket_location(without_column), "/sdk/sys/_select.h:42")
        without_file = CPythonFailureBucket(
            code="CPY_PARSE_FEEDFACE",
            stage="parse",
            detail="Expected ';'",
            diagnostic_file=None,
            line=None,
            column=None,
            case_paths=("Programs/python.c",),
            count=1,
        )
        self.assertEqual(bucket_location(without_file), "Programs/python.c")

    def test_summarize_trial_results_groups_failures_by_diagnostic_origin(self) -> None:
        results = (
            CPythonTrialResult(
                path="Programs/python.c",
                ok=False,
                stage="parse",
                detail="Expected ';'",
                diagnostic_file="/sdk/sys/_select.h",
                line=42,
                column=1,
            ),
            CPythonTrialResult(
                path="Parser/token.c",
                ok=False,
                stage="parse",
                detail="Expected   ';'",
                diagnostic_file="/sdk/sys/_select.h",
                line=42,
                column=1,
            ),
            CPythonTrialResult(
                path="Modules/_sha3/sha3.c",
                ok=False,
                stage="parse",
                detail="Expected ';'",
                diagnostic_file="/clang/__stddef_max_align_t.h",
                line=21,
                column=1,
            ),
            CPythonTrialResult(
                path="Modules/getaddrinfo.c",
                ok=True,
                stage="ok",
                detail="ok",
            ),
        )

        summary = summarize_trial_results(results)

        self.assertEqual(summary.total, 4)
        self.assertEqual(summary.passed, 1)
        self.assertEqual(summary.failed, 3)
        self.assertEqual(len(summary.buckets), 2)
        top_bucket = summary.buckets[0]
        self.assertEqual(top_bucket.count, 2)
        self.assertEqual(top_bucket.case_paths, ("Parser/token.c", "Programs/python.c"))
        self.assertEqual(bucket_location(top_bucket), "/sdk/sys/_select.h:42:1")
        self.assertEqual(top_failure_bucket(summary), top_bucket)

    def test_top_failure_bucket_returns_none_for_green_summary(self) -> None:
        summary = summarize_trial_results(
            (
                CPythonTrialResult(
                    path="Programs/python.c",
                    ok=True,
                    stage="ok",
                    detail="ok",
                ),
            )
        )
        self.assertIsNone(top_failure_bucket(summary))

    def test_trial_gate_verdict_handles_skip_fail_and_pass(self) -> None:
        failed_summary = summarize_trial_results(
            (
                CPythonTrialResult(
                    path="Programs/python.c",
                    ok=False,
                    stage="parse",
                    detail="Expected ';'",
                ),
            )
        )
        passed_summary = summarize_trial_results(
            (
                CPythonTrialResult(
                    path="Programs/python.c",
                    ok=True,
                    stage="ok",
                    detail="ok",
                ),
            )
        )
        self.assertEqual(trial_gate_verdict(failed_summary), "fail")
        self.assertEqual(trial_gate_verdict(passed_summary), "pass")
        self.assertEqual(trial_gate_verdict(failed_summary, enabled=False), "skip")


if __name__ == "__main__":
    unittest.main()
