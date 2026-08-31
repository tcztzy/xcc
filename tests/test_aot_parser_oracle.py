import json
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import py_ast
from xcc.aot.cpython_ast_adapter import parse_cpython_source
from xcc.aot.parser_oracle import (
    ParserOracleReport,
    normalize_owned_ast,
    render_parser_oracle_report,
    run_parser_oracle,
)
from xcc.aot.py_parser import parse_subset_source
from xcc.aot.source_contract import HOSTED_ONLY_MODULES, source_module_name

ROOT = Path(__file__).resolve().parents[1]


class AotParserOracleTests(unittest.TestCase):
    def test_normalizer_includes_semantics_spans_and_child_edges(self) -> None:
        source = "value = [item * 2 for item in values if item > 0]\n"
        subset = parse_subset_source(source, filename="fixture.py").tree
        hosted = parse_cpython_source(source, filename="fixture.py")

        self.assertEqual(normalize_owned_ast(subset), normalize_owned_ast(hosted))
        changed = py_ast.Module(
            subset.body,
            (),
            span=py_ast.SourceSpan(1, 1, 1, 2),
            children=subset.children,
        )
        self.assertNotEqual(normalize_owned_ast(changed), normalize_owned_ast(hosted))

    def test_oracle_checks_dependency_closure_and_every_candidate_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("ROOT = 1\n", encoding="utf-8")
            (root / "entry.py").write_text(
                "from pkg import helper\n"
                "def main() -> int:\n"
                "    return helper.VALUE\n",
                encoding="utf-8",
            )
            (root / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
            (root / "unused.py").write_text("UNUSED = True\n", encoding="utf-8")

            report = run_parser_oracle(root, "pkg.entry")

        self.assertEqual(report.checked, 4)
        self.assertEqual(report.closure, ("pkg", "pkg.helper", "pkg.entry"))
        self.assertEqual(report.failures, ())

    def test_oracle_matches_every_active_repository_source(self) -> None:
        source_root = ROOT / "src/xcc"
        report = run_parser_oracle(source_root, "xcc.aot.cli")
        expected = sum(
            1
            for path in source_root.rglob("*.py")
            if source_module_name(source_root, path) not in HOSTED_ONLY_MODULES
        )

        self.assertEqual(report.checked, expected)
        self.assertEqual(report.failures, ())
        self.assertIn("xcc.aot.cli", report.closure)

    def test_report_is_canonical_json(self) -> None:
        report = ParserOracleReport(
            "/source/xcc",
            "xcc.aot.cli",
            3,
            ("xcc", "xcc.aot", "xcc.aot.cli"),
            (),
        )
        first = render_parser_oracle_report(report)
        second = render_parser_oracle_report(report)

        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))
        payload = json.loads(first)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["failures"], [])
