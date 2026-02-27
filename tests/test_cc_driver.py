import io
import os
import subprocess
import tempfile
import unittest
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc import main
from xcc.cc_driver import looks_like_cc_driver


class CcDriverTests(unittest.TestCase):
    def _run_main(self, argv: list[str], *, stdin_text: str = "") -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv, stdin=io.StringIO(stdin_text))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cc_driver_one_positional_defaults_to_driver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            def fake_run(cmd: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
                self.assertEqual(cmd, ("clang", str(source)))
                self.assertEqual(kwargs, {"check": False})
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main([str(source)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_mode_detection_skips_option_values(self) -> None:
        self.assertTrue(looks_like_cc_driver(["-I", "inc", "ok.c"]))

    def test_cc_driver_delegates_to_clang_on_frontend_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")
            obj = root / "ok.o"

            def fake_run(argv: Sequence[str]) -> int:
                self.assertEqual(tuple(argv), ("-c", str(source), "-o", str(obj)))
                return 0

            with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
                with patch("xcc.preprocessor.host_system_include_dirs", return_value=()):
                    with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                        code, stdout, stderr = self._run_main(["-c", str(source), "-o", str(obj)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_does_not_call_clang_on_frontend_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "bad.c"
            source.write_text("int main(void){return;}\n", encoding="utf-8")
            obj = root / "bad.o"
            with patch("xcc.cc_driver._run_clang") as run:
                with patch("xcc.preprocessor.host_system_include_dirs", return_value=()):
                    with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                        code, stdout, stderr = self._run_main(["-c", str(source), "-o", str(obj)])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("sema:", stderr)
        run.assert_not_called()

    def test_cc_driver_supports_stdin_with_x_c_dash(self) -> None:
        def fake_run(argv: Sequence[str]) -> int:
            self.assertEqual(tuple(argv), ("-E", "-xc", "-", "-o", "out.i"))
            return 0

        with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
            with patch("xcc.preprocessor.host_system_include_dirs", return_value=()):
                with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                    code, stdout, stderr = self._run_main(
                        ["-E", "-xc", "-", "-o", "out.i"],
                        stdin_text="int x;\n",
                    )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_validation_mode_supports_dash_x_c_separate(self) -> None:
        def fake_run(argv: Sequence[str]) -> int:
            self.assertEqual(tuple(argv), ("-E", "-x", "c", "-", "-o", "out.i"))
            return 0

        with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
            with patch("xcc.preprocessor.host_system_include_dirs", return_value=()):
                with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                    code, stdout, stderr = self._run_main(
                        ["-E", "-x", "c", "-", "-o", "out.i"],
                        stdin_text="int x;\n",
                    )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_parses_joined_include_and_std_equals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            source.write_text("int main(void){return VALUE;}\n", encoding="utf-8")
            obj = root / "ok.o"

            def fake_run(argv: Sequence[str]) -> int:
                self.assertEqual(
                    tuple(argv),
                    ("-c", str(source), "-o", str(obj), "-Iinc", "-DVALUE=0", "-std=gnu11"),
                )
                return 0

            with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
                with patch("xcc.preprocessor.host_system_include_dirs", return_value=()):
                    with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                        code, stdout, stderr = self._run_main(
                            ["-c", str(source), "-o", str(obj), "-Iinc", "-DVALUE=0", "-std=gnu11"]
                        )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_x_none_does_not_validate_stdin(self) -> None:
        def fake_run(argv: Sequence[str]) -> int:
            self.assertEqual(tuple(argv), ("-E", "-x", "none", "-"))
            return 0

        with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
            with patch("xcc.preprocessor.host_system_include_dirs", return_value=()):
                with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                    code, stdout, stderr = self._run_main(
                        ["-E", "-x", "none", "-"],
                        stdin_text="int main(void){return;}\n",
                    )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_parses_separate_std_and_misc_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            source.write_text(
                "#if __STDC_HOSTED__ != 1\n#error hosted\n#endif\nint main(void){return 0;}\n",
                encoding="utf-8",
            )
            obj = root / "ok.o"

            def fake_run(argv: Sequence[str]) -> int:
                self.assertEqual(
                    tuple(argv),
                    (
                        "-c",
                        str(source),
                        f"-o{obj}",
                        "-std",
                        "c11",
                        "-ffreestanding",
                        "-fhosted",
                        "-nostdinc",
                    ),
                )
                return 0

            with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
                with patch("xcc.preprocessor.host_system_include_dirs", return_value=()):
                    with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                        code, stdout, stderr = self._run_main(
                            [
                                "-c",
                                str(source),
                                f"-o{obj}",
                                "-std",
                                "c11",
                                "-ffreestanding",
                                "-fhosted",
                                "-nostdinc",
                            ]
                        )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_end_of_options_stops_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            def fake_run(argv: Sequence[str]) -> int:
                self.assertEqual(tuple(argv), ("-c", "--", "note", str(source)))
                return 0

            with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
                with patch("xcc.preprocessor.host_system_include_dirs", return_value=()):
                    with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                        code, stdout, stderr = self._run_main(["-c", "--", "note", str(source)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_parse_error_does_not_invoke_clang(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")
            with patch("xcc.cc_driver._run_clang") as run:
                with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                    code, stdout, stderr = self._run_main(["-c", str(source), "-std=c99"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("driver error:", stderr)
        run.assert_not_called()

    def test_cc_driver_missing_std_value_does_not_invoke_clang(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")
            with patch("xcc.cc_driver._run_clang") as run:
                with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                    code, stdout, stderr = self._run_main(["-c", str(source), "-std"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Missing value for -std", stderr)
        run.assert_not_called()

    def test_cc_driver_missing_input_reports_io_error(self) -> None:
        with patch("xcc.cc_driver._run_clang") as run:
            with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                code, stdout, stderr = self._run_main(["-c", "missing.c"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("I/O error", stderr)
        run.assert_not_called()

    def test_cc_driver_default_mode_passthrough_calls_clang_on_missing_input(self) -> None:
        def fake_run(cmd: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(cmd, ("clang", "-c", "missing.c"))
            self.assertEqual(kwargs, {"check": False})
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
            code, stdout, stderr = self._run_main(["-c", "missing.c"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_two_positionals_uses_driver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src1 = root / "a.c"
            src2 = root / "b.c"
            src1.write_text("int a(void){return 0;}\n", encoding="utf-8")
            src2.write_text("int b(void){return 0;}\n", encoding="utf-8")

            def fake_run(argv: Sequence[str]) -> int:
                self.assertEqual(tuple(argv), (str(src1), str(src2)))
                return 0

            with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
                with patch("xcc.preprocessor.host_system_include_dirs", return_value=()):
                    with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                        code, stdout, stderr = self._run_main([str(src1), str(src2)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_clang_os_error_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            def fail_run(*args: object, **kwargs: object) -> None:
                raise OSError("clang missing")

            with patch("xcc.cc_driver.subprocess.run", side_effect=fail_run):
                code, stdout, stderr = self._run_main(["-c", str(source)])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("failed to execute clang", stderr)

    def test_cc_driver_mode_detection_for_dash_o_and_dash_x(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            def fake_run(cmd: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
                self.assertEqual(cmd, ("clang", str(source), "-o", "a.out"))
                self.assertEqual(kwargs, {"check": False})
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main([str(source), "-o", "a.out"])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_mode_detection_for_joined_dash_o(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            def fake_run(cmd: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
                self.assertEqual(cmd, ("clang", str(source), "-oa.out"))
                self.assertEqual(kwargs, {"check": False})
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main([str(source), "-oa.out"])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_mode_detection_for_joined_o_and_joined_xnone(self) -> None:
        def fake_run(cmd: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(cmd, ("clang", "-xnone", "-", "-oout.i"))
            self.assertEqual(kwargs, {"check": False})
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
            code, stdout, stderr = self._run_main(
                ["-xnone", "-", "-oout.i"],
                stdin_text="int main(void){return;}\n",
            )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_validation_mode_handles_joined_xnone(self) -> None:
        def fake_run(argv: Sequence[str]) -> int:
            self.assertEqual(tuple(argv), ("-xnone", "-", "-oout.i"))
            return 0

        with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
            with patch.dict(os.environ, {"XCC_VALIDATE_FRONTEND": "1"}, clear=False):
                code, stdout, stderr = self._run_main(
                    ["-xnone", "-", "-oout.i"],
                    stdin_text="int main(void){return;}\n",
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_mode_detection_for_dash_x_c(self) -> None:
        def fake_run(cmd: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(cmd, ("clang", "-x", "c", "-", "-o", "out.i"))
            self.assertEqual(kwargs, {"check": False})
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
            code, stdout, stderr = self._run_main(
                ["-x", "c", "-", "-o", "out.i"],
                stdin_text="int x;\n",
            )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
