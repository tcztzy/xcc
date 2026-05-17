import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc import cc_driver
from xcc.diag import CodegenError, Diagnostic, FrontendError
from xcc.frontend import FrontendResult
from xcc.options import FrontendOptions
from xcc.sema import SemaUnit, TypeMap
from xcc.ast import TranslationUnit


def _frontend_result(filename: str = "<test>") -> FrontendResult:
    return FrontendResult(
        filename=filename,
        source="",
        preprocessed_source="",
        pp_tokens=[],
        tokens=[],
        unit=TranslationUnit(functions=[], declarations=[], externals=[]),
        sema=SemaUnit({}, TypeMap()),
        include_trace=(),
        macro_table=(),
    )


class CcDriverHelperTests(unittest.TestCase):
    def test_parse_helpers_validate_values(self) -> None:
        self.assertEqual(cc_driver._take_value(["x"], 0, "-o"), ("x", 1))
        self.assertEqual(cc_driver._take_joined_or_value([], 0, "-Iinc", "-I"), ("inc", 0))
        self.assertEqual(cc_driver._take_joined_or_value(["out"], 0, "-o", "-o"), ("out", 1))
        self.assertIsNone(cc_driver._take_joined_or_value([], 0, "-Wall", "-I"))
        self.assertTrue(cc_driver.looks_like_cc_driver(["-omain.o", "ok.c"]))
        self.assertTrue(cc_driver.looks_like_cc_driver(["-xc", "-"]))
        self.assertEqual(cc_driver._parse_std("c11"), "c11")
        self.assertEqual(cc_driver._parse_backend("clang"), "clang")
        with self.assertRaisesRegex(ValueError, "Missing value for -o"):
            cc_driver._take_value([], 0, "-o")
        with self.assertRaisesRegex(ValueError, "Unsupported language standard"):
            cc_driver._parse_std("c99")
        with self.assertRaisesRegex(ValueError, "Unsupported backend"):
            cc_driver._parse_backend("llvm")

    def test_parse_driver_config_covers_argument_forms(self) -> None:
        config = cc_driver._parse_driver_config(
            [
                "--backend",
                "xcc",
                "--no-backend-fallback",
                "-x",
                "none",
                "-std=gnu11",
                "-ffreestanding",
                "-nostdinc",
                "-Iinc",
                "-iquote",
                "quote",
                "-isystemsys",
                "-idirafter",
                "after",
                "-includeforce.h",
                "-imacros",
                "macros.h",
                "-DNAME=1",
                "-U",
                "OLD",
                "-oout.o",
                "note.txt",
                "--",
                "raw.c",
                "raw.txt",
            ]
        )
        self.assertEqual(config.backend, "xcc")
        self.assertTrue(config.no_backend_fallback)
        self.assertEqual(config.frontend_options.std, "gnu11")
        self.assertFalse(config.frontend_options.hosted)
        self.assertTrue(config.frontend_options.no_standard_includes)
        self.assertEqual(config.frontend_options.include_dirs, ("inc",))
        self.assertEqual(config.frontend_options.quote_include_dirs, ("quote",))
        self.assertEqual(config.frontend_options.system_include_dirs, ("sys",))
        self.assertEqual(config.frontend_options.after_include_dirs, ("after",))
        self.assertEqual(config.frontend_options.forced_includes, ("force.h",))
        self.assertEqual(config.frontend_options.macro_includes, ("macros.h",))
        self.assertEqual(config.frontend_options.defines, ("NAME=1",))
        self.assertEqual(config.frontend_options.undefs, ("OLD",))
        self.assertEqual(config.output, "out.o")
        self.assertEqual(config.c_inputs, ("raw.c",))
        self.assertEqual(config.non_c_inputs, ("note.txt", "raw.txt"))
        self.assertIn("--", config.clang_argv)

        config = cc_driver._parse_driver_config(["--", "note.txt", "next.txt"])
        self.assertEqual(config.non_c_inputs, ("note.txt", "next.txt"))

        config = cc_driver._parse_driver_config(["--", "-dash"])
        self.assertEqual(config.clang_argv, ("--", "-dash"))
        self.assertEqual(config.c_inputs, ())
        self.assertEqual(config.non_c_inputs, ())

        config = cc_driver._parse_driver_config(["-xc", "-", "-S", "--version", "-fhosted"])
        self.assertEqual(config.action, "delegate")
        self.assertEqual(config.c_inputs, ("-",))
        self.assertTrue(config.frontend_options.hosted)

        config = cc_driver._parse_driver_config(
            ["-E", "-S", "-c", "-x", "none", "-std", "c11", "note.c"]
        )
        self.assertEqual(config.action, "delegate")
        # Frontend always uses gnu11 for system-header compatibility;
        # -std=c11 is preserved in clang_argv for the backend.
        self.assertEqual(config.frontend_options.std, "gnu11")

        config = cc_driver._parse_driver_config(["-xnone", "note.txt"])
        self.assertEqual(config.non_c_inputs, ("note.txt",))

    def test_run_clang_and_default_output_helpers(self) -> None:
        with patch(
            "xcc.cc_driver.subprocess.run", return_value=subprocess.CompletedProcess(("clang",), 7)
        ):
            self.assertEqual(cc_driver._run_clang(["-v"]), 7)
        with patch("xcc.cc_driver.subprocess.run", side_effect=OSError("missing")):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(cc_driver._run_clang(["-v"]), 1)
        self.assertIn("failed to execute clang", stderr.getvalue())
        self.assertEqual(cc_driver._default_output("main.c", "link"), "a.out")
        self.assertEqual(cc_driver._default_output("-", "assembly"), "out.s")
        self.assertEqual(cc_driver._default_output("-", "compile"), "out.o")
        self.assertTrue(cc_driver._default_output("main.c", "assembly").endswith("main.s"))
        self.assertTrue(cc_driver._default_output("main.c", "compile").endswith("main.o"))

    def test_compile_frontend_inputs_and_shape_errors(self) -> None:
        config = cc_driver.DriverConfig(
            frontend_options=FrontendOptions(),
            clang_argv=(),
            c_inputs=("-", "-"),
            non_c_inputs=(),
            backend="auto",
            no_backend_fallback=False,
            action="link",
            output=None,
            native_unsupported_flags=(),
        )
        with patch("xcc.cc_driver.read_source", return_value=("<stdin>", "int x;\n")):
            with patch("xcc.cc_driver.compile_source", return_value=_frontend_result()):
                with self.assertRaisesRegex(ValueError, "stdin can only be compiled once"):
                    cc_driver._compile_frontend_inputs(config, stdin=io.StringIO("int x;\n"))

        config = cc_driver.DriverConfig(
            frontend_options=FrontendOptions(),
            clang_argv=(),
            c_inputs=("main.c",),
            non_c_inputs=(),
            backend="auto",
            no_backend_fallback=False,
            action="link",
            output=None,
            native_unsupported_flags=(),
        )
        with patch(
            "xcc.cc_driver.compile_path", return_value=_frontend_result("main.c")
        ) as compile_path:
            results = cc_driver._compile_frontend_inputs(config, stdin=None)
        self.assertEqual([result.filename for result in results], ["main.c"])
        compile_path.assert_called_once()

        result = _frontend_result("main.c")
        self.assertIsNotNone(
            cc_driver._native_shape_error(
                cc_driver.DriverConfig(
                    FrontendOptions(),
                    (),
                    ("main.c",),
                    (),
                    "auto",
                    False,
                    "delegate",
                    None,
                    (),
                ),
                result,
            )
        )
        self.assertIsNotNone(
            cc_driver._native_shape_error(
                cc_driver.DriverConfig(
                    FrontendOptions(),
                    (),
                    ("a.c", "b.c"),
                    (),
                    "auto",
                    False,
                    "link",
                    None,
                    (),
                ),
                result,
            )
        )
        self.assertIsNotNone(
            cc_driver._native_shape_error(
                cc_driver.DriverConfig(
                    FrontendOptions(),
                    (),
                    ("main.c",),
                    ("data.o",),
                    "auto",
                    False,
                    "link",
                    None,
                    (),
                ),
                result,
            )
        )
        self.assertIsNotNone(
            cc_driver._native_shape_error(
                cc_driver.DriverConfig(
                    FrontendOptions(),
                    (),
                    ("main.c",),
                    (),
                    "auto",
                    False,
                    "link",
                    None,
                    ("-Wall",),
                ),
                result,
            )
        )
        self.assertIsNone(
            cc_driver._native_shape_error(
                cc_driver.DriverConfig(
                    FrontendOptions(),
                    (),
                    ("main.c",),
                    (),
                    "auto",
                    False,
                    "link",
                    None,
                    (),
                ),
                result,
            )
        )

    def test_run_native_backend_helper_covers_file_and_error_paths(self) -> None:
        config = cc_driver.DriverConfig(
            frontend_options=FrontendOptions(),
            clang_argv=(),
            c_inputs=("main.c",),
            non_c_inputs=(),
            backend="auto",
            no_backend_fallback=False,
            action="assembly",
            output=None,
            native_unsupported_flags=(),
        )
        result = _frontend_result("main.c")
        with tempfile.TemporaryDirectory() as tmp:
            asm_path = Path(tmp) / "out.s"
            config = cc_driver.DriverConfig(
                config.frontend_options,
                config.clang_argv,
                config.c_inputs,
                config.non_c_inputs,
                config.backend,
                config.no_backend_fallback,
                config.action,
                str(asm_path),
                config.native_unsupported_flags,
            )
            with patch("xcc.cc_driver.generate_native_assembly", return_value=".text\n"):
                self.assertEqual(cc_driver._run_native_backend(config, result), 0)
            self.assertEqual(asm_path.read_text(encoding="utf-8"), ".text\n")

        config = cc_driver.DriverConfig(
            FrontendOptions(),
            (),
            ("main.c",),
            (),
            "auto",
            False,
            "compile",
            "main.o",
            (),
        )
        with patch("xcc.cc_driver.generate_native_assembly", return_value=".text\n"):
            with patch("xcc.cc_driver.subprocess.run", side_effect=OSError("missing")):
                with self.assertRaisesRegex(CodegenError, "Failed to execute clang"):
                    cc_driver._run_native_backend(config, result)
        with patch("xcc.cc_driver.generate_native_assembly", return_value=".text\n"):
            with patch(
                "xcc.cc_driver.subprocess.run",
                return_value=subprocess.CompletedProcess(("clang",), 2),
            ):
                with self.assertRaisesRegex(CodegenError, "exit code 2"):
                    cc_driver._run_native_backend(config, result)

    def test_main_reports_frontend_and_codegen_errors(self) -> None:
        frontend_error = FrontendError(
            Diagnostic("sema", "main.c", "bad return", line=1, column=1, code="XCC-SEMA-0001")
        )
        with patch("xcc.cc_driver._parse_driver_config", side_effect=ValueError("bad flag")):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(cc_driver.main(["main.c"]), 1)
        self.assertIn("driver error", stderr.getvalue())

        config = cc_driver.DriverConfig(
            FrontendOptions(),
            ("-v",),
            ("main.c",),
            (),
            "auto",
            False,
            "link",
            None,
            (),
        )
        with patch("xcc.cc_driver._parse_driver_config", return_value=config):
            with patch("xcc.cc_driver._compile_frontend_inputs", side_effect=frontend_error):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    self.assertEqual(cc_driver.main(["main.c"]), 1)
        self.assertIn("sema:", stderr.getvalue())
        self.assertNotIn("driver error", stderr.getvalue())

        with patch("xcc.cc_driver.compile_path", side_effect=frontend_error):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(cc_driver.main(["main.c"]), 1)
        self.assertIn("sema:", stderr.getvalue())
        self.assertNotIn("driver error", stderr.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            bad_c = Path(tmp) / "bad.c"
            bad_c.write_text("int main(void) { return ; }\n", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(cc_driver.main([str(bad_c)]), 1)
        self.assertIn(str(bad_c), stderr.getvalue())

        stdin_config = cc_driver.DriverConfig(
            FrontendOptions(),
            (),
            ("-", "-"),
            (),
            "auto",
            False,
            "link",
            None,
            (),
        )
        with patch("xcc.cc_driver._parse_driver_config", return_value=stdin_config):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(cc_driver.main(["-", "-"], stdin=io.StringIO("int x;\n")), 1)
        self.assertIn("driver error", stderr.getvalue())
        self.assertIn("stdin can only be compiled once", stderr.getvalue())

        codegen_error = CodegenError(
            Diagnostic("codegen", "main.c", "tool failed", code="XCC-CG-0002")
        )
        with patch("xcc.cc_driver._parse_driver_config", return_value=config):
            with patch(
                "xcc.cc_driver._compile_frontend_inputs", return_value=[_frontend_result("main.c")]
            ):
                with patch("xcc.cc_driver._run_native_backend", side_effect=codegen_error):
                    stderr = io.StringIO()
                    with redirect_stderr(stderr):
                        self.assertEqual(cc_driver.main(["main.c"]), 1)
        self.assertIn("tool failed", stderr.getvalue())
