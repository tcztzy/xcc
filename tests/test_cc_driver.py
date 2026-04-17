import io
import subprocess
import tempfile
import unittest
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

    def test_looks_like_cc_driver_recognizes_backend_and_compile_flags(self) -> None:
        self.assertTrue(looks_like_cc_driver(["--backend=xcc", "ok.c"]))
        self.assertTrue(looks_like_cc_driver(["-I", "inc", "ok.c"]))
        self.assertTrue(looks_like_cc_driver(["-x", "c", "-"]))
        self.assertFalse(looks_like_cc_driver(["--frontend", "ok.c"]))

    def test_cc_driver_uses_native_backend_by_default_for_single_c_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            def fake_run(
                cmd: tuple[str, ...], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                self.assertEqual(cmd[0], "clang")
                self.assertTrue(cmd[1].endswith("input.s"))
                self.assertEqual(cmd[-2:], ("-o", "a.out"))
                self.assertEqual(kwargs, {"check": False})
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with patch("xcc.codegen.native_backend_available", return_value=True):
                with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                    code, stdout, stderr = self._run_main([str(source)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_compile_mode_assembles_native_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            obj = root / "ok.o"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            def fake_run(
                cmd: tuple[str, ...], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                self.assertEqual(cmd[0], "clang")
                self.assertEqual(cmd[1], "-c")
                self.assertTrue(cmd[2].endswith("input.s"))
                self.assertEqual(cmd[-2:], ("-o", str(obj)))
                self.assertEqual(kwargs, {"check": False})
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with patch("xcc.codegen.native_backend_available", return_value=True):
                with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                    code, stdout, stderr = self._run_main(["-c", str(source), "-o", str(obj)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_backend_clang_skips_native_codegen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            obj = root / "ok.o"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            with patch("xcc.cc_driver.generate_native_assembly") as native_codegen:
                with patch("xcc.cc_driver._run_clang", return_value=0) as run:
                    code, stdout, stderr = self._run_main(
                        ["--backend=clang", "-c", str(source), "-o", str(obj)]
                    )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        native_codegen.assert_not_called()
        run.assert_called_once_with(("-c", str(source), "-o", str(obj)))

    def test_cc_driver_backend_clang_preserves_original_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ok.c"
            obj = root / "ok.o"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            def fake_run(argv: tuple[str, ...]) -> int:
                self.assertEqual(tuple(argv), ("-c", str(source), "-o", str(obj), "-Iinc"))
                return 0

            with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main(
                    ["--backend=clang", "-c", str(source), "-o", str(obj), "-Iinc"]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once()

    def test_cc_driver_frontend_error_blocks_backend_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bad.c"
            source.write_text("int main(void){return;}\n", encoding="utf-8")
            with patch("xcc.cc_driver._run_clang") as run:
                with patch("xcc.cc_driver.subprocess.run") as native_run:
                    code, stdout, stderr = self._run_main(["-c", str(source)])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("sema:", stderr)
        run.assert_not_called()
        native_run.assert_not_called()

    def test_cc_driver_delegate_action_falls_back_with_note(self) -> None:
        def fake_run(argv: tuple[str, ...]) -> int:
            self.assertEqual(tuple(argv), ("-E", "-x", "c", "-", "-o", "out.i"))
            return 0

        with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
            code, stdout, stderr = self._run_main(
                ["-E", "-x", "c", "-", "-o", "out.i"],
                stdin_text="int x;\n",
            )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("falling back to clang backend", stderr)
        run.assert_called_once()

    def test_cc_driver_unknown_flag_falls_back_to_clang(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            def fake_run(argv: tuple[str, ...]) -> int:
                self.assertEqual(tuple(argv), (str(source), "--unknown"))
                return 1

            with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main([str(source), "--unknown"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("driver flag: --unknown", stderr)
        run.assert_called_once()

    def test_cc_driver_no_backend_fallback_surfaces_shape_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")
            with patch("xcc.cc_driver._run_clang") as run:
                code, stdout, stderr = self._run_main(
                    [str(source), "--unknown", "--no-backend-fallback"]
                )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("codegen:", stderr)
        self.assertIn("driver flag: --unknown", stderr)
        run.assert_not_called()

    def test_cc_driver_backend_xcc_rejects_unsupported_float_codegen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "float.c"
            source.write_text(
                "float f(float x){return x;} int main(void){return 0;}\n", encoding="utf-8"
            )
            with patch("xcc.codegen.native_backend_available", return_value=True):
                with patch("xcc.cc_driver._run_clang") as run:
                    code, stdout, stderr = self._run_main(["--backend=xcc", str(source)])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("codegen:", stderr)
        self.assertIn("Unsupported native codegen", stderr)
        run.assert_not_called()

    def test_cc_driver_backend_xcc_rejects_native_unsupported_constructs(self) -> None:
        cases = {
            "gnu_asm": (
                'int main(void){ asm(""); return 0; }\n',
                "GNU asm is not supported",
            ),
            "statement_expression": (
                "int main(void){ return ({ int x = 1; x; }); }\n",
                "StatementExpr",
            ),
            "computed_goto": (
                "int main(void){ void *target = &&done; goto *target; done: return 0; }\n",
                "IndirectGotoStmt",
            ),
            "struct_object": (
                "struct pair { int a; int b; }; int main(void){ struct pair p; return 0; }\n",
                "local 'p': struct",
            ),
            "variadic_function": (
                "int sum(int n, ...){ return n; } int main(void){ return 0; }\n",
                "Variadic functions are not supported",
            ),
            "vla": (
                "int main(int n){ int values[n]; return 0; }\n",
                "local 'values': declarator",
            ),
            "static_global": (
                "static int value = 1; int main(void){ return value; }\n",
                "storage for global 'value'",
            ),
        }
        for name, (source_text, expected) in cases.items():
            with self.subTest(case=name):
                with tempfile.TemporaryDirectory() as tmp:
                    source = Path(tmp) / f"{name}.c"
                    source.write_text(source_text, encoding="utf-8")
                    with patch("xcc.codegen.native_backend_available", return_value=True):
                        with patch("xcc.cc_driver._run_clang") as run:
                            code, stdout, stderr = self._run_main(["--backend=xcc", str(source)])
                self.assertEqual(code, 1)
                self.assertEqual(stdout, "")
                self.assertIn("codegen:", stderr)
                self.assertIn(expected, stderr)
                run.assert_not_called()

    def test_cc_driver_auto_falls_back_for_native_unsupported_constructs(self) -> None:
        cases = {
            "gnu_asm": 'int main(void){ asm(""); return 0; }\n',
            "statement_expression": "int main(void){ return ({ int x = 1; x; }); }\n",
            "computed_goto": "int main(void){ void *target = &&done; goto *target; done: return 0; }\n",
            "struct_object": "struct pair { int a; int b; }; int main(void){ struct pair p; return 0; }\n",
            "variadic_function": "int sum(int n, ...){ return n; } int main(void){ return 0; }\n",
            "vla": "int main(int n){ int values[n]; return 0; }\n",
            "static_global": "static int value = 1; int main(void){ return value; }\n",
        }
        for name, source_text in cases.items():
            with self.subTest(case=name):
                with tempfile.TemporaryDirectory() as tmp:
                    source = Path(tmp) / f"{name}.c"
                    source.write_text(source_text, encoding="utf-8")

                    def fake_run(argv: tuple[str, ...]) -> int:
                        self.assertEqual(tuple(argv), (str(source),))
                        return 0

                    with patch("xcc.codegen.native_backend_available", return_value=True):
                        with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
                            code, stdout, stderr = self._run_main([str(source)])
                self.assertEqual(code, 0)
                self.assertEqual(stdout, "")
                self.assertIn("falling back to clang backend", stderr)
                run.assert_called_once()

    def test_cc_driver_backend_xcc_can_dump_native_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")
            with patch("xcc.codegen.native_backend_available", return_value=True):
                code, stdout, stderr = self._run_main(
                    ["--backend=xcc", "-S", str(source), "-o", "-"]
                )

        self.assertEqual(code, 0)
        self.assertIn("_main:", stdout)
        self.assertEqual(stderr, "")

    def test_cc_driver_missing_std_value_reports_driver_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ok.c"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")
            with patch("xcc.cc_driver._run_clang") as run:
                code, stdout, stderr = self._run_main(["-c", str(source), "-std"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("driver error:", stderr)
        run.assert_not_called()

    def test_cc_driver_missing_input_reports_io_error(self) -> None:
        with patch("xcc.cc_driver._run_clang") as run:
            code, stdout, stderr = self._run_main(["-c", "missing.c"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("I/O error", stderr)
        run.assert_not_called()

    def test_cc_driver_fallback_multiple_c_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src1 = root / "a.c"
            src2 = root / "b.c"
            src1.write_text("int a(void){return 0;}\n", encoding="utf-8")
            src2.write_text("int b(void){return 0;}\n", encoding="utf-8")

            def fake_run(argv: tuple[str, ...]) -> int:
                self.assertEqual(tuple(argv), (str(src1), str(src2)))
                return 0

            with patch("xcc.cc_driver._run_clang", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main([str(src1), str(src2)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("exactly one C input", stderr)
        run.assert_called_once()

    def test_cc_driver_clang_os_error_returns_nonzero(self) -> None:
        def fail_run(*args: object, **kwargs: object) -> None:
            raise OSError("clang missing")

        with patch("xcc.cc_driver.subprocess.run", side_effect=fail_run):
            code, stdout, stderr = self._run_main(["--backend=clang", "-v"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("failed to execute clang", stderr)


if __name__ == "__main__":
    unittest.main()
