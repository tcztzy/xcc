import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import AotError, collect_slice_inputs

ROOT = Path(__file__).resolve().parents[1]
CORE_SLICE = (
    ROOT / "src/xcc/types.py",
    ROOT / "src/xcc/diag.py",
    ROOT / "src/xcc/options.py",
)


class AotMilestone3SliceTests(unittest.TestCase):
    def test_collects_core_slice_in_deterministic_order(self) -> None:
        modules = collect_slice_inputs(CORE_SLICE)
        self.assertEqual(
            [module.name for module in modules],
            ["xcc.diag", "xcc.options", "xcc.types"],
        )
        self.assertEqual(
            [module.path.name for module in modules],
            ["diag.py", "options.py", "types.py"],
        )

    def test_rejects_module_outside_src_xcc(self) -> None:
        with self.assertRaises(AotError) as ctx:
            collect_slice_inputs((ROOT / "tests/test_aot.py",))
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SLICE-0001")


if __name__ == "__main__":
    unittest.main()
