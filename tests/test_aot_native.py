import os
import pickle
import subprocess
import sys
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
            if command[0] == sys.executable:
                Path(command[2]).write_bytes(pickle.dumps(42))
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
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
            command = tuple(str(part) for part in cmd)
            if command[0] == sys.executable:
                Path(command[2]).write_bytes(pickle.dumps(42))
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
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

    def test_native_smoke_reports_python_oracle_failure(self) -> None:
        for stdout, stderr, expected in (
            ("", "oracle stderr", "oracle stderr"),
            ("oracle stdout", "", "oracle stdout"),
            ("", "", "CPython oracle failed"),
        ):
            with self.subTest(expected=expected):

                def fake_run(cmd, **kwargs):
                    return subprocess.CompletedProcess(cmd, 1, stdout=stdout, stderr=stderr)

                with (
                    patch("xcc.aot.native.subprocess.run", side_effect=fake_run),
                    self.assertRaises(AotError) as ctx,
                ):
                    run_native_smoke(
                        "def answer() -> int:\n    return 42\n",
                        entry="answer",
                        llc="/tool/llc",
                    )
                self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-NATIVE-0001")
                self.assertEqual(ctx.exception.diagnostics[0].message, expected)

    def test_native_smoke_rejects_non_callable_python_entry(self) -> None:
        with self.assertRaises(TypeError) as ctx:
            run_native_smoke("answer = 42\n", entry="answer", llc="/tool/llc")
        self.assertEqual(str(ctx.exception), "answer is not callable")

    def test_native_smoke_rejects_invalid_python_entry_name(self) -> None:
        with self.assertRaises(TypeError) as ctx:
            run_native_smoke(
                "def answer() -> int:\n    return 42\n",
                entry="answer.bad",
                llc="/tool/llc",
            )
        self.assertEqual(str(ctx.exception), "answer.bad is not callable")


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

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_string_join_native_smoke_matches_cpython_stdout(self) -> None:
        result = run_native_smoke(
            "def message() -> str:\n"
            "    empty = '|'.join(())\n"
            "    single = '|'.join(('one',))\n"
            "    many = '|'.join(('a', '', 'b'))\n"
            "    return empty + '/' + single + '/' + many\n",
            entry="message",
            llc=_real_llc(),
        )
        self.assertEqual(result.python_result, "/one/a||b")
        self.assertEqual(result.native_stdout, "/one/a||b\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_string_padding_native_smoke_matches_cpython_stdout(self) -> None:
        result = run_native_smoke(
            "def message() -> str:\n"
            "    padded = 'ab'.ljust(4, '.')\n"
            "    return padded.rstrip('.')\n",
            entry="message",
            llc=_real_llc(),
        )
        self.assertEqual(result.python_result, "ab")
        self.assertEqual(result.native_stdout, "ab\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_none_initialized_loop_local_native_smoke_matches_cpython_stdout(self) -> None:
        result = run_native_smoke(
            "def message() -> str:\n"
            "    expanded = None\n"
            "    while expanded is None:\n"
            "        expanded = 'done'\n"
            "    return expanded\n",
            entry="message",
            llc=_real_llc(),
        )
        self.assertEqual(result.python_result, "done")
        self.assertEqual(result.native_stdout, "done\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_tuple_negative_index_native_smoke_matches_cpython_stdout(self) -> None:
        result = run_native_smoke(
            "def message() -> str:\n"
            "    values = ('first', 'last')\n"
            "    return values[-1]\n",
            entry="message",
            llc=_real_llc(),
        )
        self.assertEqual(result.python_result, "last")
        self.assertEqual(result.native_stdout, "last\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_string_slice_native_smoke_matches_cpython_stdout(self) -> None:
        result = run_native_smoke(
            "def message() -> str:\n"
            "    text = 'abcdef'\n"
            "    start = 1\n"
            "    stop = 4\n"
            "    return text[start:stop]\n",
            entry="message",
            llc=_real_llc(),
        )
        self.assertEqual(result.python_result, "bcd")
        self.assertEqual(result.native_stdout, "bcd\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_optional_string_equality_native_smoke_matches_cpython_stdout(self) -> None:
        result = run_native_smoke(
            "def message() -> str:\n"
            "    storage_class: str | None = None\n"
            "    if storage_class == 'typedef':\n"
            "        return 'bad'\n"
            "    return 'ok'\n",
            entry="message",
            llc=_real_llc(),
        )
        self.assertEqual(result.python_result, "ok")
        self.assertEqual(result.native_stdout, "ok\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_int_to_bytes_native_smoke_matches_single_byte_stdout(self) -> None:
        result = run_native_smoke(
            "def message() -> bytes:\n"
            "    return (65).to_bytes(1, 'little')\n",
            entry="message",
            llc=_real_llc(),
        )
        self.assertEqual(result.python_result, b"A")
        self.assertEqual(result.native_stdout, "A\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_real_id_native_smoke_returns_truthy_pointer_identity(self) -> None:
        result = run_native_smoke(
            "def check() -> bool:\n"
            "    return id('x') != 0\n",
            entry="check",
            llc=_real_llc(),
        )
        self.assertIs(result.python_result, True)
        self.assertEqual(result.native_returncode, 1)


if __name__ == "__main__":
    unittest.main()
