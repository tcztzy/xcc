import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotError,
    collect_bootstrap_sources,
    lower_bootstrap_entry_smoke,
    plan_bootstrap_entry,
    summarize_bootstrap_admission,
)

ROOT = Path(__file__).resolve().parents[1]


class AotBootstrapGraphTests(unittest.TestCase):
    def test_collects_all_src_xcc_modules_in_deterministic_order(self) -> None:
        modules = collect_bootstrap_sources(ROOT)
        expected_count = len(tuple((ROOT / "src/xcc").rglob("*.py")))
        self.assertEqual(len(modules), expected_count)
        self.assertEqual(modules[0].name, "xcc.__init__")
        self.assertIn("xcc.aot.bootstrap", {module.name for module in modules})
        self.assertEqual(modules[-1].name, "xcc.x86_64_asm")

    def test_rejects_non_repository_root(self) -> None:
        with self.assertRaises(AotError) as ctx:
            collect_bootstrap_sources(ROOT / "tests")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-BOOTSTRAP-0001")

    def test_summarizes_bootstrap_admission(self) -> None:
        report = summarize_bootstrap_admission(ROOT)
        expected_count = len(tuple((ROOT / "src/xcc").rglob("*.py")))
        self.assertEqual(report.total, expected_count)
        self.assertEqual(report.failed, ())

    def test_summarizes_bootstrap_admission_failures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "src/xcc"
            source_root.mkdir(parents=True)
            (source_root / "bad.py").write_text(
                "def bad() -> int:\n"
                "    return (lambda: 1)()\n",
                encoding="utf-8",
            )

            report = summarize_bootstrap_admission(root)

        self.assertEqual(report.total, 1)
        self.assertEqual(len(report.failed), 1)
        self.assertIn("xcc.bad", report.failed[0])
        self.assertIn("XCC-AOT-SUBSET-0001", report.failed[0])


class AotBootstrapEntryTests(unittest.TestCase):
    def test_plans_cc_driver_main_as_bootstrap_entry(self) -> None:
        plan = plan_bootstrap_entry(ROOT)
        self.assertEqual(plan.entry_symbol, "xcc.cc_driver.main")
        self.assertIn("xcc.cc_driver", plan.modules)
        self.assertIn("xcc.frontend", plan.modules)
        self.assertIn("xcc.parser.__init__", plan.modules)
        self.assertIn("xcc.sema.__init__", plan.modules)

    def test_entry_plan_contains_target_backends(self) -> None:
        plan = plan_bootstrap_entry(ROOT)
        self.assertIn("xcc.x86_64_asm", plan.modules)
        self.assertIn("xcc.aarch64_asm", plan.modules)
        self.assertIn("xcc.llvm_api", plan.modules)

    def test_entry_plan_reports_missing_bootstrap_modules(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "src/xcc"
            source_root.mkdir(parents=True)
            (source_root / "__init__.py").write_text(
                "def marker() -> None:\n"
                "    return None\n",
                encoding="utf-8",
            )

            with self.assertRaises(AotError) as ctx:
                plan_bootstrap_entry(root)

        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-BOOTSTRAP-0002")
        self.assertIn("xcc.cc_driver", ctx.exception.diagnostics[0].message)


class AotBootstrapLoweringTests(unittest.TestCase):
    def test_lowers_bootstrap_entry_smoke_wrapper(self) -> None:
        module = lower_bootstrap_entry_smoke(ROOT)
        functions = {function.name: function for function in module.functions}
        self.assertIn("aot_bootstrap_smoke_main", functions)
        self.assertIn("xcc.options.FrontendOptions.__post_init__", functions)
        self.assertIn("FrontendOptions", {record.name for record in module.records})
        self.assertIn(
            "target='xcc.options.FrontendOptions.__post_init__'",
            repr(functions["aot_bootstrap_smoke_main"].body),
        )


if __name__ == "__main__":
    unittest.main()
