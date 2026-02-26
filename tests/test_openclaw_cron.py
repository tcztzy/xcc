import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc import openclaw_cron


class OpenClawCronSmokeTests(unittest.TestCase):
    def test_select_smoke_check_uses_cpython_configure_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cpython_dir = root / "cpython"
            cpython_dir.mkdir()
            (cpython_dir / "configure").write_text("#!/bin/sh\n", encoding="utf-8")
            check = openclaw_cron.select_smoke_check(root)
        self.assertEqual(check.name, "cpython-configure")
        self.assertEqual(check.cwd, cpython_dir.resolve())
        self.assertEqual(check.command, ("./configure",))
        self.assertEqual(check.extra_env, (("CC", "xcc"),))

    def test_select_smoke_check_uses_explicit_cpython_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit = root / "custom-cpython"
            explicit.mkdir()
            (explicit / "configure").write_text("#!/bin/sh\n", encoding="utf-8")
            check = openclaw_cron.select_smoke_check(root, explicit)
        self.assertEqual(check.name, "cpython-configure")
        self.assertEqual(check.cwd, explicit.resolve())

    def test_select_smoke_check_falls_back_to_unittest_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            check = openclaw_cron.select_smoke_check(root)
        self.assertEqual(check.name, "xcc-tests")
        self.assertEqual(check.cwd, root)
        self.assertEqual(check.command[:3], (sys.executable, "-m", "unittest"))
        self.assertEqual(check.extra_env, ())

    def test_run_smoke_check_timeout_captures_partial_output(self) -> None:
        check = openclaw_cron.SmokeCheck(
            name="cpython-configure",
            cwd=Path.cwd(),
            command=("./configure",),
            extra_env=(("CC", "xcc"),),
        )
        timeout_error = TimeoutExpired(
            cmd=["./configure"], timeout=1, output="configure stdout", stderr="configure stderr"
        )
        with patch("xcc.openclaw_cron.subprocess.run", side_effect=timeout_error):
            result = openclaw_cron.run_smoke_check(check, timeout_seconds=1)
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.returncode)
        self.assertEqual(result.stdout, "configure stdout")
        self.assertEqual(result.stderr, "configure stderr")
        self.assertEqual(openclaw_cron.result_exit_code(result), openclaw_cron.EXIT_TIMEOUT)

    def test_run_smoke_check_success_and_nonzero_exit_codes(self) -> None:
        check = openclaw_cron.SmokeCheck(
            name="xcc-tests",
            cwd=Path.cwd(),
            command=(sys.executable, "-c", "print('smoke-ok')"),
        )
        result = openclaw_cron.run_smoke_check(check, timeout_seconds=5)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.returncode, 0)
        self.assertIn("smoke-ok", result.stdout)
        self.assertEqual(openclaw_cron.result_exit_code(result), openclaw_cron.EXIT_OK)
        failed = openclaw_cron.SmokeResult(
            check=check,
            returncode=9,
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
            timed_out=False,
        )
        self.assertEqual(openclaw_cron.result_exit_code(failed), openclaw_cron.EXIT_FAIL)

    def test_coerce_output_handles_none_and_bytes(self) -> None:
        self.assertEqual(openclaw_cron._coerce_output(None), "")
        self.assertEqual(openclaw_cron._coerce_output(b"ok"), "ok")
        self.assertEqual(openclaw_cron._coerce_output("text"), "text")

    def test_format_report_includes_status_and_log_tails(self) -> None:
        check = openclaw_cron.SmokeCheck(
            name="xcc-tests",
            cwd=Path("/tmp/xcc"),
            command=(sys.executable, "-m", "unittest", "discover", "-v"),
        )
        result = openclaw_cron.SmokeResult(
            check=check,
            returncode=0,
            stdout="line-1\nline-2\n",
            stderr="",
            elapsed_seconds=0.25,
            timed_out=False,
        )
        report = openclaw_cron.format_report(result, max_log_lines=1)
        self.assertIn("openclaw-smoke: ok (xcc-tests)", report)
        self.assertIn("stdout:\nline-2", report)
        self.assertIn("stderr:\n<empty>", report)

    def test_format_report_includes_timeout_reason_and_env(self) -> None:
        check = openclaw_cron.SmokeCheck(
            name="cpython-configure",
            cwd=Path("/tmp/cpython"),
            command=("./configure",),
            extra_env=(("CC", "xcc"),),
        )
        result = openclaw_cron.SmokeResult(
            check=check,
            returncode=None,
            stdout="",
            stderr="timed out",
            elapsed_seconds=1.0,
            timed_out=True,
        )
        report = openclaw_cron.format_report(result)
        self.assertIn("reason=timeout", report)
        self.assertIn("env=CC=xcc", report)

    def test_main_prints_report_and_propagates_failure_code(self) -> None:
        check = openclaw_cron.SmokeCheck(
            name="xcc-tests",
            cwd=Path("/tmp/xcc"),
            command=(sys.executable, "-m", "unittest", "discover", "-v"),
        )
        result = openclaw_cron.SmokeResult(
            check=check,
            returncode=1,
            stdout="",
            stderr="test failure",
            elapsed_seconds=0.5,
            timed_out=False,
        )
        with patch("xcc.openclaw_cron.select_smoke_check", return_value=check):
            with patch("xcc.openclaw_cron.run_smoke_check", return_value=result):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = openclaw_cron.main(["--repo-root", str(Path.cwd())])
        self.assertEqual(code, openclaw_cron.EXIT_FAIL)
        self.assertIn("openclaw-smoke: fail", output.getvalue())


if __name__ == "__main__":
    unittest.main()
