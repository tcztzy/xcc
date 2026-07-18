import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import aot_bootstrap_gate


class AotBootstrapBehaviorGateTests(unittest.TestCase):
    def test_v377_rejects_different_process_observations(self) -> None:
        left = subprocess.CompletedProcess(("stage2", "--version"), 0, "same\n", "")
        right = subprocess.CompletedProcess(("stage3", "--version"), 1, "same\n", "")

        with self.assertRaises(aot_bootstrap_gate.BehaviorMismatch) as ctx:
            aot_bootstrap_gate.compare_process_observations("version", left, right)

        self.assertIn("version return code", str(ctx.exception))

    def test_v377_rejects_different_behavior_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            left = root / "stage2.norm.ll"
            right = root / "stage3.norm.ll"
            left.write_text("left\n", encoding="utf-8")
            right.write_text("right\n", encoding="utf-8")

            with self.assertRaises(aot_bootstrap_gate.BehaviorMismatch) as ctx:
                aot_bootstrap_gate.compare_artifacts("normalized fixture IR", left, right)

        self.assertIn("normalized fixture IR differs", str(ctx.exception))

    def test_v377_cli_dispatches_compare_behavior(self) -> None:
        with patch.object(aot_bootstrap_gate, "compare_behavior") as compare:
            status = aot_bootstrap_gate.main(("compare-behavior", "/tmp/stage2", "/tmp/stage3"))

        self.assertEqual(status, 0)
        compare.assert_called_once_with(Path("/tmp/stage2"), Path("/tmp/stage3"))

    def test_v377_cli_rejects_invalid_arguments(self) -> None:
        self.assertEqual(aot_bootstrap_gate.main(("compare-behavior",)), 2)


if __name__ == "__main__":
    unittest.main()
