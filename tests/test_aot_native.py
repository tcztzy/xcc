import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc.aot import AotError, NativeSmokeResult, run_native_smoke


class AotNativeHarnessTests(unittest.TestCase):
    def test_native_smoke_writes_llvm_runs_llc_links_and_executes(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_run(cmd, **kwargs):
            command = tuple(str(part) for part in cmd)
            calls.append(command)
            if command[0] == "/tool/llc":
                Path(command[-1]).write_bytes(b"object")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if command[0] == "cc":
                Path(command[-1]).write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 42, stdout="", stderr="")

        with patch("xcc.aot.native.subprocess.run", side_effect=fake_run):
            result = run_native_smoke(
                "int64 = int\ndef answer() -> int64:\n    return 42\n",
                entry="answer",
                llc="/tool/llc",
                cc="cc",
            )

        self.assertIsInstance(result, NativeSmokeResult)
        self.assertEqual(result.python_result, 42)
        self.assertEqual(result.native_returncode, 42)
        self.assertTrue(any(command[0] == "/tool/llc" for command in calls))
        self.assertTrue(any(command[0] == "cc" for command in calls))

    def test_native_smoke_reports_tool_failure(self) -> None:
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="failed")

        with (
            patch("xcc.aot.native.subprocess.run", side_effect=fake_run),
            self.assertRaises(AotError) as ctx,
        ):
            run_native_smoke(
                "int64 = int\ndef answer() -> int64:\n    return 42\n",
                entry="answer",
                llc="/tool/llc",
                cc="cc",
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-NATIVE-0001")


def _real_llc() -> str | None:
    path = os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    return path if Path(path).exists() else None


class AotNativeRealSmokeTests(unittest.TestCase):
    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_scalar_native_smoke_matches_cpython_exit_code(self) -> None:
        result = run_native_smoke(
            "int64 = int\ndef answer() -> int64:\n    return 42\n",
            entry="answer",
            llc=_real_llc(),
        )
        self.assertEqual(result.python_result, 42)
        self.assertEqual(result.native_returncode, 42)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_string_native_smoke_matches_cpython_stdout(self) -> None:
        result = run_native_smoke(
            'def message() -> str:\n    return "ok"\n',
            entry="message",
            llc=_real_llc(),
        )
        self.assertEqual(result.python_result, "ok")
        self.assertEqual(result.native_stdout, "ok\n")
        self.assertEqual(result.native_returncode, 0)


if __name__ == "__main__":
    unittest.main()
