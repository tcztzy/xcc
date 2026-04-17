import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from scripts import clang_frontier


class ClangFrontierTests(unittest.TestCase):
    def test_extract_actual_stage_from_skip_reason(self) -> None:
        self.assertEqual(
            clang_frontier.extract_actual_stage("baseline skip: expected ok, got sema"),
            "sema",
        )
        self.assertIsNone(clang_frontier.extract_actual_stage("manual skip"))

    def test_classify_case_prefers_type_family_for_sema_mismatches(self) -> None:
        case = {
            "id": "clang-sema-int-conv",
            "upstream": "clang/test/Sema/int-conv.c",
            "expect": "ok",
            "skip_reason": "baseline skip: expected ok, got sema (incompatible integer conversion)",
        }
        bucket = clang_frontier.classify_case(case)
        self.assertEqual(bucket.layer, "P0")
        self.assertEqual(bucket.family, "types-and-conversions")
        self.assertEqual(bucket.subsystem, "sema")

    def test_classify_case_prefers_preprocessor_bucket(self) -> None:
        case = {
            "id": "clang-pp-macro",
            "upstream": "clang/test/Preprocessor/macro.c",
            "expect": "ok",
            "skip_reason": "baseline skip: expected ok, got pp (macro expansion mismatch)",
        }
        bucket = clang_frontier.classify_case(case)
        self.assertEqual(bucket.layer, "P2")
        self.assertEqual(bucket.subsystem, "preprocessor")

    def test_build_frontier_groups_cases(self) -> None:
        payload = {
            "cases": [
                {
                    "id": "clang-sema-int-conv",
                    "upstream": "clang/test/Sema/int-conv.c",
                    "expect": "ok",
                    "skip_reason": "baseline skip: expected ok, got sema (incompatible integer conversion)",
                },
                {
                    "id": "clang-sema-int-promote",
                    "upstream": "clang/test/Sema/int-promote.c",
                    "expect": "ok",
                    "skip_reason": "baseline skip: expected ok, got sema (integer promotion mismatch)",
                },
                {
                    "id": "clang-pp-macro",
                    "upstream": "clang/test/Preprocessor/macro.c",
                    "expect": "ok",
                    "skip_reason": "baseline skip: expected ok, got pp (macro expansion mismatch)",
                },
            ]
        }
        frontier = clang_frontier.build_frontier(payload)
        self.assertEqual(frontier[0]["slice_id"], "clang-p0-types-and-conversions-sema")
        self.assertEqual(frontier[0]["count"], 2)
        self.assertEqual(frontier[1]["slice_id"], "clang-p2-macro-and-include-edges-preprocessor")

    def test_load_manifest_and_filter_only_skipped_cases(self) -> None:
        payload = {
            "cases": [
                {"id": "skip", "upstream": "clang/test/Sema/a.c", "expect": "ok", "skip_reason": "baseline skip: expected ok, got sema"},
                {"id": "pass", "upstream": "clang/test/Sema/b.c", "expect": "ok"},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(__import__("json").dumps(payload), encoding="utf-8")
            filtered = clang_frontier.load_skipped_cases(manifest)
        self.assertEqual([case["id"] for case in filtered], ["skip"])
