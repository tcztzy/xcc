import cProfile
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc import cc_driver, main
from xcc.codegen import generate_llvm_ir
from xcc.frontend import compile_source
from xcc.llvm_tools import (
    find_llc,
    is_llvm_llc,
    llc_candidates,
    llvm_config_bindir,
)
from xcc.parser import ParserError


class CliTests(unittest.TestCase):
    LLVM_LLC_HELP = "OVERVIEW: llvm system compiler\nUSAGE: llc [options] <input bitcode>\n"

    def _run_main(self, argv: list[str], *, stdin_text: str = "") -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv, stdin=io.StringIO(stdin_text))
        return code, stdout.getvalue(), stderr.getvalue()

    def _fake_llvm_llc_run(self, llc_path: str):
        def fake_run(cmd, **kwargs):
            if tuple(cmd) == (llc_path, "--help"):
                return subprocess.CompletedProcess(cmd, 0, stdout=self.LLVM_LLC_HELP, stderr="")
            if cmd[0] == llc_path and "-filetype=obj" in cmd:
                Path(cmd[-1]).write_bytes(b"obj")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        return fake_run

    def _llc_compile_cmds(self, run, llc_path: str) -> list[list[str]]:
        return [
            call.args[0]
            for call in run.call_args_list
            if call.args[0][0] == llc_path and "-filetype=obj" in call.args[0]
        ]

    def test_aot_smoke_compiler_writes_llvm_and_invokes_llc_under_cpython(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess:
            commands.append(tuple(command))
            if command[0] == "/opt/homebrew/opt/llvm/bin/llc" and "-filetype=obj" in command:
                Path(command[-1]).write_bytes(b"object")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "smoke.c"
            output = root / "smoke.o"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            with patch("subprocess.run", fake_run):
                code = cc_driver._aot_compile_smoke_source_to_object(
                    5,
                    ("xcc", "-c", str(source), "-o", str(output)),
                )

            self.assertEqual(code, 0)
            self.assertEqual(
                [
                    command
                    for command in commands
                    if command[0] == "/opt/homebrew/opt/llvm/bin/llc" and "-filetype=obj" in command
                ],
                [
                    (
                        "/opt/homebrew/opt/llvm/bin/llc",
                        "-O0",
                        "-filetype=obj",
                        str(output) + ".ll",
                        "-o",
                        str(output),
                    )
                ],
            )
            self.assertEqual(output.read_bytes(), b"object")

            llvm_ir = (root / "smoke.o.ll").read_text(encoding="utf-8")
            self.assertIn(f'source_filename = "{source}"', llvm_ir)
            self.assertIn("define i32 @main()", llvm_ir)
            self.assertIn("ret i32 0", llvm_ir)

    def test_native_aot_debug_c_compile_emits_metadata_and_stack_options(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess:
            commands.append(tuple(command))
            if command[0] == "/opt/homebrew/opt/llvm/bin/llc":
                Path(command[-1]).write_bytes(b"object")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "debug.c"
            output = root / "debug.o"
            source.write_text(
                "int answer(void) {\n  return 42;\n}\n",
                encoding="utf-8",
            )

            with patch("subprocess.run", fake_run):
                code = cc_driver._aot_compile_smoke_source_to_object(
                    6,
                    ("xcc", "-g", "-c", str(source), "-o", str(output)),
                )

            llvm_ir = (root / "debug.o.ll").read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        llc_command = next(
            command for command in commands if command[0] == "/opt/homebrew/opt/llvm/bin/llc"
        )
        for option in (
            "-O0",
            "--frame-pointer=all",
            "--emit-dwarf-unwind=always",
            "--dwarf-version=4",
        ):
            self.assertIn(option, llc_command)
        self.assertIn("!DICompileUnit(language: DW_LANG_C11", llvm_ir)
        self.assertRegex(llvm_ir, r'DISubprogram\(name: "answer".*line: 1')
        self.assertRegex(llvm_ir, r"DILocation\(line: 2, column: [1-9]")

    def test_native_aot_debug_link_runs_dsymutil_and_propagates_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "debug.c"
            output = root / "debug"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")
            with (
                patch("xcc.cc_driver._aot_compile_source_path_to_object", return_value=True),
                patch("xcc.cc_driver._aot_exec_argv", side_effect=(0, 7)) as execute,
            ):
                code = cc_driver._aot_compile_smoke_source_to_object(
                    5,
                    ("xcc", "-g", str(source), "-o", str(output)),
                )

        self.assertEqual(code, 7)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(execute.call_args_list[-1].args[0], ("/usr/bin/dsymutil", str(output)))

    def test_native_aot_timing_json_has_stable_success_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "timed.c"
            output = root / "timed.o"
            timing = root / "timing.json"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            with patch("xcc.cc_driver._aot_exec_argv", return_value=0):
                code = cc_driver._aot_compile_smoke_source_to_object(
                    6,
                    (
                        "xcc",
                        "-c",
                        str(source),
                        "-o",
                        str(output),
                        f"--timing-json={timing}",
                    ),
                )

            payload = json.loads(timing.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["schema"], "xcc.compile-timing.v1")
        self.assertEqual((payload["clock"], payload["unit"]), ("monotonic", "nanoseconds"))
        self.assertTrue(payload["success"])
        self.assertIsNone(payload["failed_stage"])
        self.assertGreaterEqual(payload["total_ns"], 0)
        self.assertEqual(
            tuple(payload["phases"]),
            ("preprocessing", "parser", "sema", "codegen", "llc"),
        )
        for phase in payload["phases"].values():
            self.assertGreaterEqual(phase["duration_ns"], 0)
            self.assertEqual(phase["status"], "ok")

    def test_native_aot_timing_json_records_parser_and_llc_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parser_source = root / "parser-error.c"
            parser_timing = root / "parser-error.json"
            parser_source.write_text("int main(\n", encoding="utf-8")
            parser_output = io.StringIO()
            with redirect_stdout(parser_output):
                parser_code = cc_driver._aot_compile_smoke_source_to_object(
                    4,
                    ("xcc", "-c", str(parser_source), f"--timing-json={parser_timing}"),
                )
            parser_payload = json.loads(parser_timing.read_text(encoding="utf-8"))

            llc_source = root / "llc-error.c"
            llc_timing = root / "llc-error.json"
            llc_source.write_text("int value;\n", encoding="utf-8")
            with patch("xcc.cc_driver._aot_exec_argv", return_value=9):
                llc_code = cc_driver._aot_compile_smoke_source_to_object(
                    4,
                    ("xcc", "-c", str(llc_source), f"--timing-json={llc_timing}"),
                )
            llc_payload = json.loads(llc_timing.read_text(encoding="utf-8"))

        self.assertEqual(parser_code, 1)
        self.assertIn("Declaration type is missing", parser_output.getvalue())
        self.assertFalse(parser_payload["success"])
        self.assertEqual(parser_payload["failed_stage"], "parser")
        self.assertEqual(parser_payload["phases"]["parser"]["status"], "error")
        self.assertEqual(parser_payload["phases"]["sema"]["status"], "not_run")
        self.assertEqual(llc_code, 1)
        self.assertEqual(llc_payload["failed_stage"], "llc")
        self.assertEqual(llc_payload["phases"]["llc"]["status"], "error")

    def test_native_aot_timing_is_zero_intrusion_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "plain.c"
            output = root / "plain.o"
            source.write_text("int value;\n", encoding="utf-8")
            with (
                patch(
                    "xcc.cc_driver._aot_monotonic_ns",
                    side_effect=AssertionError("driver clock reached"),
                ),
                patch(
                    "xcc.frontend._aot_monotonic_ns",
                    side_effect=AssertionError("frontend clock reached"),
                ),
                patch("xcc.cc_driver._aot_exec_argv", return_value=0),
            ):
                result = cc_driver._aot_compile_source_path_to_object(
                    str(source),
                    str(output),
                    (),
                    (),
                    (),
                    "c11",
                )

        self.assertTrue(result)

    def test_hosted_python_cprofile_observes_frontend_semantic_phases(self) -> None:
        profiler = cProfile.Profile()
        llvm_ir = profiler.runcall(
            lambda: generate_llvm_ir(
                compile_source("int answer(void){return 42;}\n", filename="profiled.c")
            )
        )
        function_names = {
            getattr(entry.code, "co_name", "") for entry in profiler.getstats()
        }

        self.assertIn("define i32 @answer()", llvm_ir)
        for function_name in (
            "compile_source",
            "preprocess_source",
            "parse",
            "analyze",
            "generate_llvm_ir",
        ):
            self.assertIn(function_name, function_names)

    def test_native_aot_timing_output_failure_fails_the_compile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "timed.c"
            output = root / "timed.o"
            timing = root / "missing" / "timing.json"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            with (
                patch("xcc.cc_driver._aot_exec_argv", return_value=0),
                patch(
                    "xcc.cc_driver._aot_write_text_file",
                    side_effect=(True, False),
                ) as write_text,
            ):
                code = cc_driver._aot_compile_smoke_source_to_object(
                    6,
                    (
                        "xcc",
                        "-c",
                        str(source),
                        "-o",
                        str(output),
                        f"--timing-json={timing}",
                    ),
                )

        self.assertEqual(code, 1)
        self.assertEqual(write_text.call_count, 2)
        self.assertEqual(write_text.call_args_list[-1].args[0], str(timing))

    def test_aot_smoke_compiler_accepts_build_flags_under_cpython(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "smoke.c"
            output = root / "smoke.o"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            with patch("xcc.cc_driver._aot_exec_argv", return_value=0) as exec_argv:
                code = cc_driver._aot_compile_smoke_source_to_object(
                    8,
                    (
                        "xcc",
                        "-c",
                        "-O3",
                        "-Wall",
                        "-Wno-unused-variable",
                        str(source),
                        "-o",
                        str(output),
                    ),
                )

            self.assertEqual(code, 0)
            exec_argv.assert_called_once()
            self.assertTrue((root / "smoke.o.ll").exists())

    def test_aot_smoke_compiler_delegates_existing_link_inputs_verbatim(self) -> None:
        argv = (
            "xcc",
            "first.o",
            "second.o",
            "libsupport.a",
            "-L/opt/support/lib",
            "-lsupport",
            "-framework",
            "CoreFoundation",
            "-o",
            "program",
        )
        with patch("xcc.cc_driver._aot_exec_argv", return_value=0) as exec_argv:
            code = cc_driver._aot_compile_smoke_source_to_object(len(argv), argv)

        self.assertEqual(code, 0)
        exec_argv.assert_called_once_with(("cc", *argv[1:]))

    def test_aot_smoke_compiler_preserves_framework_flags_when_linking_source(self) -> None:
        argv = (
            "xcc",
            "probe.c",
            "-L/opt/support/lib",
            "-ldl",
            "-framework",
            "CoreFoundation",
            "-o",
            "probe",
        )
        with (
            patch(
                "xcc.cc_driver._aot_compile_source_path_to_object",
                return_value=True,
            ) as compile_source,
            patch("xcc.cc_driver._aot_exec_argv", return_value=0) as exec_argv,
        ):
            code = cc_driver._aot_compile_smoke_source_to_object(len(argv), argv)

        self.assertEqual(code, 0)
        compile_source.assert_called_once()
        exec_argv.assert_called_once_with(
            (
                "cc",
                "probe.o",
                "-o",
                "probe",
                "-L/opt/support/lib",
                "-ldl",
                "-framework",
                "CoreFoundation",
            )
        )

    def test_aot_source_to_llvm_uses_frontend_backend_under_cpython(self) -> None:
        llvm_ir = cc_driver._aot_compile_source_to_llvm_ir(
            "smoke.c",
            "int main(void){return 1;}\n",
            (),
            (),
            (),
            "c11",
        )
        self.assertIn('source_filename = "smoke.c"', llvm_ir)
        self.assertIn("ret i32 1", llvm_ir)

    def test_aot_smoke_source_to_llvm_uses_frontend_backend_under_cpython(self) -> None:
        llvm_ir = cc_driver._aot_compile_source_to_llvm_ir(
            "smoke.c",
            "int main(void){return 0;}\n",
            (),
            (),
            (),
            "c11",
        )
        self.assertIn('source_filename = "smoke.c"', llvm_ir)
        self.assertIn("define i32 @main()", llvm_ir)
        self.assertIn("ret i32 0", llvm_ir)

    def test_aot_source_to_llvm_preserves_parser_error(self) -> None:
        with self.assertRaises(ParserError):
            cc_driver._aot_compile_source_to_llvm_ir(
                "bad.c",
                "int main( {",
                (),
                (),
                (),
                "c11",
            )

    def test_aot_smoke_compiler_rejects_failed_llvm_write_under_cpython(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "smoke.c"
            output = root / "smoke.o"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            with (
                patch("xcc.cc_driver._aot_write_text_file", return_value=False) as write_text,
                patch("xcc.cc_driver._aot_exec_argv") as exec_argv,
            ):
                code = cc_driver._aot_compile_smoke_source_to_object(
                    5,
                    ("xcc", "-c", str(source), "-o", str(output)),
                )

            self.assertEqual(code, 1)
            write_text.assert_called_once()
            write_args = write_text.call_args.args
            self.assertEqual(write_args[0], str(output) + ".ll")
            self.assertIn("define i32 @main()", write_args[1])
            self.assertIn("ret i32 0", write_args[1])
            exec_argv.assert_not_called()

    def test_aot_smoke_compiler_rejects_invalid_inputs_under_cpython(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "smoke.c"
            output = root / "smoke.o"
            source.write_text("int main(void){\n", encoding="utf-8")

            output_text = io.StringIO()
            with (
                redirect_stdout(output_text),
                patch("xcc.cc_driver._aot_exec_argv") as exec_argv,
            ):
                bad_args = cc_driver._aot_compile_smoke_source_to_object(
                    4,
                    ("xcc", "-c", str(source), "-o"),
                )
                bad_flags = cc_driver._aot_compile_smoke_source_to_object(
                    5,
                    ("xcc", "--compile", str(source), "-o", str(output)),
                )
                bad_source = cc_driver._aot_compile_smoke_source_to_object(
                    5,
                    ("xcc", "-c", str(source), "-o", str(output)),
                )

            self.assertEqual(bad_args, 1)
            self.assertEqual(bad_flags, 1)
            self.assertEqual(bad_source, 1)
            self.assertIn("Expression is missing before end of input", output_text.getvalue())
            exec_argv.assert_not_called()
            self.assertFalse((root / "smoke.o.ll").exists())

    def test_aot_smoke_compiler_rejects_unknown_frontend_flag_under_cpython(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "smoke.c"
            output = root / "smoke.o"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            with patch("xcc.cc_driver._aot_exec_argv") as exec_argv:
                code = cc_driver._aot_compile_smoke_source_to_object(
                    5,
                    ("xcc", "--compile", str(source), "-o", str(output)),
                )

            self.assertEqual(code, 1)
            exec_argv.assert_not_called()
            self.assertFalse((root / "smoke.o.ll").exists())

    def test_main_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            code, stdout, stderr = self._run_main(["--frontend", str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_dump_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            code, stdout, stderr = self._run_main([str(path), "--dump-tokens"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("1:1\tKEYWORD\tint", stdout)
        self.assertIn("1:22\tEOF", stdout)

    def test_main_dump_preprocessor_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            code, stdout, stderr = self._run_main([str(path), "--dump-pp-tokens"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("1:1\tIDENT\tint", stdout)
        self.assertIn("1:22\tEOF", stdout)

    def test_main_dump_include_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text("int x;\n", encoding="utf-8")
            source = '#include "inc.h"\nint main(void){return x;}\n'
            path = root / "ok.c"
            path.write_text(source, encoding="utf-8")
            code, stdout, stderr = self._run_main([str(path), "--dump-include-trace"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("ok.c:1: #include", stdout)

    def test_main_dump_macro_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("#define A 1\nint main(void){return A;}\n", encoding="utf-8")
            code, stdout, stderr = self._run_main([str(path), "--dump-macro-table"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("A=1", stdout)

    def test_main_dump_ast_and_sema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            code, stdout, stderr = self._run_main([str(path), "--dump-ast", "--dump-sema"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("TranslationUnit(", stdout)
        self.assertIn("FunctionSymbol(", stdout)

    def test_main_reads_stdin(self) -> None:
        code, stdout, stderr = self._run_main(["-"], stdin_text="int main(){return 0;}")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, "xcc: ok: <stdin>\n")

    def test_main_help(self) -> None:
        code, stdout, stderr = self._run_main(["--help"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("usage:", stdout)
        self.assertIn("--target=llvm", stdout)
        self.assertIn("--target=x86_64-linux-gnu", stdout)
        self.assertIn("--target=evm", stdout)
        self.assertIn("--evm-initcode", stdout)
        self.assertNotIn("--backend", stdout)

    def test_main_missing_input(self) -> None:
        code, stdout, stderr = self._run_main([])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("usage:", stderr)

    def test_main_unknown_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main([str(path), "--unknown"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("unsupported option(s) for target llvm: --unknown", stderr)
        run.assert_not_called()

    def test_main_unknown_option_without_c_input_delegates_to_driver(self) -> None:
        with patch("xcc.cc_driver.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess((), 1)
            code, stdout, stderr = self._run_main(["-", "--unknown"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once_with(("clang", "-", "--unknown"), check=False)

    def test_driver_default_target_on_x86_64_linux_is_native(self) -> None:
        with (
            patch("xcc.cc_driver.sys.platform", "linux"),
            patch("xcc.cc_driver.platform.machine", return_value="x86_64"),
        ):
            config = cc_driver._parse_driver_config(["-c", "ok.c"])
        self.assertEqual(config.target, "x86_64-linux-gnu")
        self.assertEqual(config.frontend_options.host_machine, "x86_64")
        self.assertEqual(config.frontend_options.target_os, "linux")

    def test_driver_default_target_on_darwin_arm64_tracks_native_layout(self) -> None:
        with (
            patch("xcc.cc_driver.sys.platform", "darwin"),
            patch("xcc.cc_driver.platform.machine", return_value="arm64"),
        ):
            config = cc_driver._parse_driver_config(["-c", "ok.c"])

        self.assertEqual(config.target, "llvm")
        self.assertEqual(config.frontend_options.host_machine, "arm64")
        self.assertEqual(config.frontend_options.target_os, "darwin")

    def test_main_version_reports_x86_64_linux_default_target(self) -> None:
        with (
            patch("xcc.cc_driver.sys.platform", "linux"),
            patch("xcc.cc_driver.platform.machine", return_value="x86_64"),
        ):
            code, stdout, stderr = self._run_main(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("Target: x86_64-linux-gnu", stderr)

    def test_main_x86_64_linux_target_without_c_input_delegates_to_cc(self) -> None:
        with patch("xcc.cc_driver.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess((), 0)
            code, stdout, stderr = self._run_main(["--target=x86_64-linux-gnu", "-v"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once_with(("cc", "-v"), check=False)

    def test_looks_like_cc_driver_handles_joined_options_and_value_options(self) -> None:
        self.assertTrue(cc_driver.looks_like_cc_driver(["-oout"]))
        self.assertTrue(cc_driver.looks_like_cc_driver(["-xc"]))
        self.assertFalse(cc_driver.looks_like_cc_driver(["-D", "NAME=1"]))

    def test_main_rejects_missing_driver_value_and_unsupported_std(self) -> None:
        for argv, message in (
            (["-c", "ok.c", "-o"], "Missing value for -o"),
            (["-c", "ok.c", "-std=c99"], "Unsupported language standard: c99"),
        ):
            with self.subTest(argv=argv):
                code, stdout, stderr = self._run_main(argv)
                self.assertEqual(code, 1)
                self.assertEqual(stdout, "")
                self.assertIn(message, stderr)

    def test_llvm_config_and_llc_probe_ignore_failed_tools(self) -> None:
        with patch("xcc.llvm_tools.subprocess.run", side_effect=OSError):
            self.assertIsNone(llvm_config_bindir("/missing/llvm-config"))
            self.assertFalse(is_llvm_llc("/missing/llc"))

        with patch("xcc.llvm_tools.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ("/bad/llvm-config", "--bindir"),
                1,
                stdout="",
                stderr="failed",
            )
            self.assertIsNone(llvm_config_bindir("/bad/llvm-config"))

    def test_llc_candidates_ignore_empty_llvm_config_and_missing_path_llc(self) -> None:
        def fake_run(cmd, **kwargs):
            self.assertEqual(tuple(cmd), ("/empty/llvm-config", "--bindir"))
            return subprocess.CompletedProcess(cmd, 0, stdout=" \n", stderr="")

        def fake_which(name: str) -> str | None:
            self.assertEqual(name, "llc")
            return None

        with (
            patch.dict("os.environ", {"LLVM_CONFIG": "/empty/llvm-config"}, clear=True),
            patch("xcc.llvm_tools.shutil.which", side_effect=fake_which),
            patch("xcc.llvm_tools.subprocess.run", side_effect=fake_run),
        ):
            self.assertEqual(llc_candidates(), ())

    def test_parse_driver_config_tracks_split_joined_and_passthrough_args(self) -> None:
        config = cc_driver._parse_driver_config(
            [
                "--target",
                "llvm",
                "-x",
                "none",
                "-xc",
                "-xnone",
                "-std",
                "c11",
                "-std=gnu11",
                "-fhosted",
                "-ffreestanding",
                "-oout",
                "-Iinc",
                "-D",
                "SPLIT=1",
                "-DNAME=1",
                "-UOLD",
                "-L/usr/lib",
                "-lfoo",
                "-framework",
                "CoreFoundation",
                "--",
                "forced.c",
                "forced.o",
            ]
        )

        self.assertEqual(config.target, "llvm")
        self.assertEqual(config.action, "link")
        self.assertEqual(config.c_inputs, ("forced.c",))
        self.assertEqual(config.non_c_inputs, ("forced.o",))
        self.assertFalse(config.frontend_options.hosted)
        self.assertEqual(config.frontend_options.std, "gnu11")
        self.assertEqual(config.output, "out")
        self.assertIn("inc", config.frontend_options.include_dirs)
        self.assertIn("SPLIT=1", config.frontend_options.defines)
        self.assertIn("NAME=1", config.frontend_options.defines)
        self.assertIn("OLD", config.frontend_options.undefs)
        self.assertIn("--", config.clang_argv)
        self.assertIn("-framework", config.clang_argv)
        passthrough_config = cc_driver._parse_driver_config(["--", "-Wl,--as-needed", "extra.o"])
        self.assertEqual(passthrough_config.non_c_inputs, ("extra.o",))
        self.assertIn("-Wl,--as-needed", passthrough_config.clang_argv)

    def test_compile_frontend_inputs_rejects_duplicate_stdin(self) -> None:
        config = cc_driver._parse_driver_config(["-x", "c", "-", "-"])
        with self.assertRaisesRegex(ValueError, "stdin can only be compiled once"):
            cc_driver._compile_frontend_inputs(
                config,
                stdin=io.StringIO("int f(void){return 0;}"),
            )

    def test_main_driver_mode_reports_frontend_input_errors(self) -> None:
        duplicate_code, duplicate_stdout, duplicate_stderr = self._run_main(
            ["-x", "c", "-", "-"],
            stdin_text="int f(void){return 0;}",
        )
        missing_code, missing_stdout, missing_stderr = self._run_main(["/definitely/not/here.c"])

        self.assertEqual(duplicate_code, 1)
        self.assertEqual(duplicate_stdout, "")
        self.assertIn("driver error: stdin can only be compiled once", duplicate_stderr)
        self.assertEqual(missing_code, 1)
        self.assertEqual(missing_stdout, "")
        self.assertIn("I/O error", missing_stderr)

    def test_main_x86_64_linux_target_preprocessor_delegate_uses_cc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(void){return 0;}\n", encoding="utf-8")
            with patch("xcc.cc_driver.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess((), 0)
                code, stdout, stderr = self._run_main(
                    ["--target=x86_64-linux-gnu", "-E", str(path)]
                )
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once_with(("cc", "-E", str(path)), check=False)

    def test_main_default_target_passes_o0_to_llc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            llc_path = str(root / "llvm-llc")
            src = root / "ok.c"
            obj = root / "ok.o"
            src.write_text("int f(void){return 0;}", encoding="utf-8")

            with (
                patch.dict("os.environ", {"XCC_LLC": llc_path}, clear=False),
                patch(
                    "xcc.cc_driver.subprocess.run",
                    side_effect=self._fake_llvm_llc_run(llc_path),
                ) as run,
            ):
                code, stdout, stderr = self._run_main(["-nostdinc", "-c", str(src), "-o", str(obj)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertIn(((llc_path, "--help"),), [call.args for call in run.call_args_list])
        llc_cmd = self._llc_compile_cmds(run, llc_path)[0]
        self.assertIn("-O0", llc_cmd)
        self.assertLess(llc_cmd.index("-O0"), llc_cmd.index("-filetype=obj"))

    def test_debug_driver_flags_control_metadata_frame_and_unwind_options(self) -> None:
        debug = cc_driver._parse_driver_config(["-g", "-c", "sample.c", "-o", "sample.o"])
        self.assertTrue(debug.debug_info)
        self.assertTrue(debug.frame_pointer)
        self.assertTrue(debug.unwind_tables)
        command = cc_driver._llvm_object_argv(
            debug,
            "/tool/llc",
            Path("sample.ll"),
            Path("sample.o"),
        )
        for option in (
            "-O0",
            "--frame-pointer=all",
            "--emit-dwarf-unwind=always",
            "--dwarf-version=4",
        ):
            self.assertIn(option, command)

        disabled = cc_driver._parse_driver_config(["-g", "-g0", "-c", "sample.c"])
        self.assertFalse(disabled.debug_info)
        self.assertFalse(disabled.frame_pointer)
        self.assertFalse(disabled.unwind_tables)
        frame_only = cc_driver._parse_driver_config(["-fno-omit-frame-pointer", "-c", "sample.c"])
        self.assertFalse(frame_only.debug_info)
        self.assertTrue(frame_only.frame_pointer)
        self.assertFalse(frame_only.unwind_tables)

    def test_main_debug_compile_requests_debug_ir_and_native_stack_options(self) -> None:
        generated_options: list[dict[str, object]] = []

        def fake_generate(result, **kwargs):
            generated_options.append(kwargs)
            return "define i32 @main() { ret i32 0 }\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            llc_path = str(root / "llvm-llc")
            source = root / "sample.c"
            output = root / "sample.o"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")
            with (
                patch.dict("os.environ", {"XCC_LLC": llc_path}, clear=False),
                patch("xcc.codegen.generate_llvm_ir", side_effect=fake_generate),
                patch(
                    "xcc.cc_driver.subprocess.run",
                    side_effect=self._fake_llvm_llc_run(llc_path),
                ) as run,
            ):
                code, stdout, stderr = self._run_main(
                    ["-g", "-nostdinc", "-c", str(source), "-o", str(output)]
                )

        self.assertEqual((code, stdout, stderr), (0, "", ""))
        self.assertEqual(
            generated_options,
            [{"debug": True, "target_triple": "arm64-apple-macosx11.0.0"}],
        )
        llc_command = self._llc_compile_cmds(run, llc_path)[0]
        for option in (
            "--frame-pointer=all",
            "--emit-dwarf-unwind=always",
            "--dwarf-version=4",
        ):
            self.assertIn(option, llc_command)

    @unittest.skipUnless(sys.platform == "darwin", "dSYM generation is macOS-specific")
    def test_main_debug_link_runs_dsymutil_before_temporary_object_cleanup(self) -> None:
        commands: list[tuple[str, ...]] = []
        object_exists_at_dsymutil: list[bool] = []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            llc_path = str(root / "llvm-llc")
            source = root / "sample.c"
            output = root / "sample"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            def fake_run(command, **kwargs):
                command = tuple(command)
                commands.append(command)
                if command == (llc_path, "--help"):
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=self.LLVM_LLC_HELP,
                        stderr="",
                    )
                if command[0] == llc_path:
                    Path(command[-1]).write_bytes(b"object")
                elif command[0] == "/usr/bin/dsymutil":
                    object_paths = [
                        Path(candidate[-1])
                        for candidate in commands
                        if candidate and candidate[0] == llc_path and "-filetype=obj" in candidate
                    ]
                    object_exists_at_dsymutil.append(all(path.is_file() for path in object_paths))
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with (
                patch.dict("os.environ", {"XCC_LLC": llc_path}, clear=False),
                patch("xcc.cc_driver.shutil.which", return_value="/usr/bin/dsymutil"),
                patch("xcc.cc_driver.subprocess.run", side_effect=fake_run),
            ):
                code, stdout, stderr = self._run_main(
                    ["-g", "-nostdinc", str(source), "-o", str(output)]
                )

        self.assertEqual((code, stdout, stderr), (0, "", ""))
        self.assertEqual(object_exists_at_dsymutil, [True])
        self.assertIn(("/usr/bin/dsymutil", str(output)), commands)

    def test_main_explicit_llvm_target_passes_o0_to_llc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            llc_path = str(root / "llvm-llc")
            src = root / "ok.c"
            obj = root / "ok.o"
            src.write_text("int f(void){return 0;}", encoding="utf-8")

            with (
                patch.dict("os.environ", {"XCC_LLC": llc_path}, clear=False),
                patch(
                    "xcc.cc_driver.subprocess.run",
                    side_effect=self._fake_llvm_llc_run(llc_path),
                ) as run,
            ):
                code, stdout, stderr = self._run_main(
                    ["--target=llvm", "-nostdinc", "-c", str(src), "-o", str(obj)]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertIn(((llc_path, "--help"),), [call.args for call in run.call_args_list])
        llc_cmd = self._llc_compile_cmds(run, llc_path)[0]
        self.assertIn("-O0", llc_cmd)
        self.assertLess(llc_cmd.index("-O0"), llc_cmd.index("-filetype=obj"))

    def test_find_llc_rejects_non_llvm_explicit_xcc_llc(self) -> None:
        with (
            patch.dict("os.environ", {"XCC_LLC": "/toolchain/bin/llc"}, clear=True),
            patch("xcc.llvm_tools.shutil.which") as which,
            patch("xcc.llvm_tools.subprocess.run") as run,
        ):
            run.return_value = subprocess.CompletedProcess((), 0, stdout="not llvm", stderr="")
            with self.assertRaisesRegex(ValueError, "not LLVM llc"):
                find_llc()

        which.assert_not_called()
        run.assert_called_once_with(
            ("/toolchain/bin/llc", "--help"),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_find_llc_accepts_path_candidate_with_llvm_help_stdout(self) -> None:
        def fake_run(cmd, **kwargs):
            self.assertEqual(tuple(cmd), ("/toolchain/bin/llc", "--help"))
            return subprocess.CompletedProcess(cmd, 0, stdout=self.LLVM_LLC_HELP, stderr="")

        def fake_which(name: str) -> str | None:
            return "/toolchain/bin/llc" if name == "llc" else None

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("xcc.llvm_tools.shutil.which", side_effect=fake_which),
            patch("xcc.llvm_tools.subprocess.run", side_effect=fake_run),
        ):
            self.assertEqual(find_llc(), "/toolchain/bin/llc")

    def test_find_llc_rejects_same_name_tool_with_wrong_help_stdout(self) -> None:
        def fake_run(cmd, **kwargs):
            if tuple(cmd) == ("/bad/llvm-config", "--bindir"):
                return subprocess.CompletedProcess(cmd, 0, stdout="/bad/bin\n", stderr="")
            if tuple(cmd) == ("/bad/bin/llc", "--help"):
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="USAGE: llc but not LLVM\n",
                    stderr=self.LLVM_LLC_HELP,
                )
            if tuple(cmd) == ("/good/bin/llc", "--help"):
                return subprocess.CompletedProcess(cmd, 0, stdout=self.LLVM_LLC_HELP, stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        def fake_which(name: str) -> str | None:
            return "/good/bin/llc" if name == "llc" else None

        with (
            patch.dict(
                "os.environ",
                {"LLVM_CONFIG": "/bad/llvm-config"},
                clear=True,
            ),
            patch("xcc.llvm_tools.shutil.which", side_effect=fake_which),
            patch("xcc.llvm_tools.subprocess.run", side_effect=fake_run),
        ):
            self.assertEqual(find_llc(), "/good/bin/llc")

    def test_main_llvm_target_rejects_when_no_verified_llc_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            obj = root / "ok.o"
            src.write_text("int f(void){return 0;}", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                if tuple(cmd) == ("/not-llvm/llc", "--help"):
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout="not the llvm system compiler\n",
                        stderr=self.LLVM_LLC_HELP,
                    )
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

            def fake_which(name: str) -> str | None:
                return "/not-llvm/llc" if name == "llc" else None

            with (
                patch.dict("os.environ", {}, clear=True),
                patch("xcc.llvm_tools.shutil.which", side_effect=fake_which),
                patch("xcc.llvm_tools.subprocess.run", side_effect=fake_run),
            ):
                code, stdout, stderr = self._run_main(
                    ["--target=llvm", "-nostdinc", "-c", str(src), "-o", str(obj)]
                )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("unable to find LLVM llc", stderr)

    def test_main_default_target_assembly_is_llvm_ir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            ll = root / "ok.ll"
            src.write_text("int f(void){return 0;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(["-nostdinc", "-S", str(src)])

            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            self.assertIn("define i32 @f()", ll.read_text(encoding="utf-8"))
            run.assert_not_called()

    def test_main_aarch64_target_assembly_is_native_asm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            asm_path = root / "ok.s"
            src.write_text("int f(void){return 7;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    ["--target=aarch64-apple-darwin", "-nostdinc", "-S", str(src)]
                )

            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            asm = asm_path.read_text(encoding="utf-8")
            self.assertIn(".globl _f\n_f:", asm)
            self.assertIn("    mov w0, #7", asm)
            self.assertNotIn("define i32", asm)
            run.assert_not_called()

    def test_main_aarch64_target_assembly_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "ok.c"
            src.write_text("int f(void){return 3;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    ["--target=aarch64-apple-darwin", "-nostdinc", "-S", str(src), "-o", "-"]
                )

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertIn(".globl _f\n_f:", stdout)
            self.assertIn("    mov w0, #3", stdout)
            run.assert_not_called()

    def test_main_std_c11_reaches_frontend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "bad.c"
            src.write_text("int f(void){int x; return _Alignof(x);}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    ["--target=aarch64-apple-darwin", "-nostdinc", "-std=c11", "-S", str(src)]
                )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Invalid alignof operand", stderr)
        run.assert_not_called()

    def test_main_multi_source_assembly_with_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.c"
            second = root / "b.c"
            output = root / "out.s"
            first.write_text("int a(void){return 1;}", encoding="utf-8")
            second.write_text("int b(void){return 2;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    [
                        "--target=aarch64-apple-darwin",
                        "-nostdinc",
                        "-S",
                        str(first),
                        str(second),
                        "-o",
                        str(output),
                    ]
                )
                output_exists = output.exists()

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("cannot specify -o when generating multiple output files", stderr)
        self.assertFalse(output_exists)
        run.assert_not_called()

    def test_main_multi_source_assembly_uses_per_input_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a.c"
            second = root / "b.c"
            first.write_text("int a(void){return 1;}", encoding="utf-8")
            second.write_text("int b(void){return 2;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    ["--target=aarch64-apple-darwin", "-nostdinc", "-S", str(first), str(second)]
                )
                first_asm = first.with_suffix(".s").read_text(encoding="utf-8")
                second_asm = second.with_suffix(".s").read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertIn(".globl _a\n_a:", first_asm)
        self.assertIn(".globl _b\n_b:", second_asm)
        run.assert_not_called()

    def test_main_x86_64_linux_target_assembly_is_native_asm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            asm_path = root / "ok.s"
            src.write_text("int f(void){return 7;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    ["--target=x86_64-linux-gnu", "-nostdinc", "-S", str(src)]
                )

            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            asm = asm_path.read_text(encoding="utf-8")
            self.assertIn(".globl f\nf:", asm)
            self.assertIn("    mov eax, 7", asm)
            self.assertNotIn("define i32", asm)
            run.assert_not_called()

    def test_main_evm_target_assembly_is_evm_opcodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            asm_path = root / "ok.evmasm"
            src.write_text("unsigned int get(void){return 7;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(["--target=evm", "-nostdinc", "-S", str(src)])

            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            asm = asm_path.read_text(encoding="utf-8")
            self.assertIn("PUSH4 0x6d4ce63c", asm)
            self.assertIn("RETURN", asm)
            self.assertNotIn("define i32", asm)
            run.assert_not_called()

    def test_main_evm_target_compile_writes_hex_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            bytecode_path = root / "ok.bin"
            src.write_text("unsigned int get(void){return 7;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(["--target=evm", "-nostdinc", "-c", str(src)])

            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            bytecode = bytecode_path.read_text(encoding="utf-8").strip()
            self.assertRegex(bytecode, r"^[0-9a-f]+$")
            self.assertIn("636d4ce63c", bytecode)
            run.assert_not_called()

    def test_main_evm_target_compile_can_write_deployment_initcode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            initcode_path = root / "ok.init.bin"
            runtime_path = root / "ok.bin"
            src.write_text(
                "typedef __evm_uint256 uint256;\n"
                "uint256 counter = 7;\n"
                "uint256 get(void){return counter;}\n",
                encoding="utf-8",
            )

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    ["--target=evm", "-nostdinc", "--evm-initcode", "-c", str(src)]
                )

            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            initcode = initcode_path.read_text(encoding="utf-8").strip()
            self.assertRegex(initcode, r"^[0-9a-f]+$")
            self.assertIn("636d4ce63c", initcode)
            self.assertFalse(runtime_path.exists())
            run.assert_not_called()

    def test_main_evm_initcode_option_requires_evm_compile_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "ok.c"
            src.write_text("unsigned int get(void){return 7;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                non_evm_code, non_evm_stdout, non_evm_stderr = self._run_main(
                    ["--target=llvm", "-nostdinc", "--evm-initcode", "-c", str(src)]
                )
                assembly_code, assembly_stdout, assembly_stderr = self._run_main(
                    ["--target=evm", "-nostdinc", "--evm-initcode", "-S", str(src)]
                )

        self.assertEqual(non_evm_code, 1)
        self.assertEqual(non_evm_stdout, "")
        self.assertIn("--evm-initcode requires --target=evm -c", non_evm_stderr)
        self.assertEqual(assembly_code, 1)
        self.assertEqual(assembly_stdout, "")
        self.assertIn("--evm-initcode requires --target=evm -c", assembly_stderr)
        run.assert_not_called()

    def test_main_evm_target_rejects_link_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "ok.c"
            src.write_text("unsigned int get(void){return 7;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(["--target=evm", "-nostdinc", str(src)])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("EVM target does not support link action", stderr)
        run.assert_not_called()

    def test_main_x86_64_linux_target_strips_macro_expanded_gnu_asm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "cpuid.c"
            asm_path = root / "cpuid.s"
            src.write_text(
                '#define CPUID() __asm__ __volatile__("cpuid")\n'
                "int f(void){\n"
                "  CPUID();\n"
                "  return 7;\n"
                "}\n",
                encoding="utf-8",
            )

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    [
                        "--target=x86_64-linux-gnu",
                        "-nostdinc",
                        "-S",
                        str(src),
                        "-o",
                        str(asm_path),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            self.assertIn(".globl f\nf:", asm_path.read_text(encoding="utf-8"))
            run.assert_not_called()

    def test_main_x86_64_linux_target_accepts_aliasing_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            asm_path = root / "ok.s"
            src.write_text("int f(void){return 7;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    [
                        "--target=x86_64-linux-gnu",
                        "-nostdinc",
                        "-fno-strict-aliasing",
                        "-S",
                        str(src),
                        "-o",
                        str(asm_path),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            self.assertIn(".globl f\nf:", asm_path.read_text(encoding="utf-8"))
            run.assert_not_called()

    def test_main_x86_64_linux_target_accepts_pic_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            asm_path = root / "ok.s"
            src.write_text("int f(void){return 7;}", encoding="utf-8")

            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    [
                        "--target=x86_64-linux-gnu",
                        "-nostdinc",
                        "-fPIC",
                        "-S",
                        str(src),
                        "-o",
                        str(asm_path),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            self.assertIn(".globl f\nf:", asm_path.read_text(encoding="utf-8"))
            run.assert_not_called()

    def test_main_x86_64_linux_target_compile_assembles_generated_asm_with_cc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            obj = root / "ok.o"
            src.write_text("int f(void){return 5;}", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                self.assertNotEqual(Path(cmd[0]).name, "llc")
                self.assertNotEqual(cmd[0], "clang")
                Path(cmd[cmd.index("-o") + 1]).write_bytes(b"obj")
                return subprocess.CompletedProcess(cmd, 0)

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main(
                    [
                        "--target=x86_64-linux-gnu",
                        "-nostdinc",
                        "-c",
                        str(src),
                        "-o",
                        str(obj),
                    ]
                )
                obj_bytes = obj.read_bytes()
                assemble_cmd = run.call_args.args[0]

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertEqual(obj_bytes, b"obj")
        self.assertEqual(assemble_cmd[0], "cc")
        self.assertIn("-c", assemble_cmd)

    def test_main_x86_64_linux_target_reports_assembler_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "ok.c"
            src.write_text("int f(void){return 5;}", encoding="utf-8")
            with patch("xcc.cc_driver.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    ("cc",),
                    2,
                    stdout="",
                    stderr="assembler failed",
                )
                code, stdout, stderr = self._run_main(
                    ["--target=x86_64-linux-gnu", "-nostdinc", "-c", str(src)]
                )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("assembler failed", stderr)

    def test_main_x86_64_linux_target_reports_link_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "ok.c"
            src.write_text("int main(void){return 0;}", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                if "-c" in cmd:
                    Path(cmd[cmd.index("-o") + 1]).write_bytes(b"obj")
                    return subprocess.CompletedProcess(cmd, 0)
                return subprocess.CompletedProcess(cmd, 7)

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run):
                code, stdout, stderr = self._run_main(
                    ["--target=x86_64-linux-gnu", "-nostdinc", str(src)]
                )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("link failed with exit code 7", stderr)

    def test_main_x86_64_linux_target_link_preserves_latomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            exe = root / "a.out"
            src.write_text("int main(void){return 0;}", encoding="utf-8")
            link_cmds = []

            def fake_run(cmd, **kwargs):
                if "-c" in cmd:
                    Path(cmd[cmd.index("-o") + 1]).write_bytes(b"obj")
                else:
                    link_cmds.append(cmd)
                return subprocess.CompletedProcess(cmd, 0)

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run):
                code, stdout, stderr = self._run_main(
                    [
                        "--target=x86_64-linux-gnu",
                        "-nostdinc",
                        str(src),
                        "-latomic",
                        "-o",
                        str(exe),
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertEqual(len(link_cmds), 1)
        self.assertIn("-latomic", link_cmds[0])

    def test_main_x86_64_linux_target_object_only_link_preserves_latomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obj = root / "ok.o"
            exe = root / "a.out"
            obj.write_bytes(b"obj")
            with patch("xcc.cc_driver.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess((), 0)
                code, stdout, stderr = self._run_main(
                    [
                        "--target=x86_64-linux-gnu",
                        str(obj),
                        "-latomic",
                        "-l",
                        "atomic",
                        "-o",
                        str(exe),
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        run.assert_called_once_with(
            ("cc", str(obj), "-latomic", "-l", "atomic", "-o", str(exe)),
            check=False,
        )

    def test_main_aarch64_target_compile_assembles_generated_asm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            obj = root / "ok.o"
            src.write_text("int f(void){return 5;}", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                self.assertNotEqual(Path(cmd[0]).name, "llc")
                Path(cmd[cmd.index("-o") + 1]).write_bytes(b"obj")
                return subprocess.CompletedProcess(cmd, 0)

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main(
                    [
                        "--target=aarch64-apple-darwin",
                        "-nostdinc",
                        "-c",
                        str(src),
                        "-o",
                        str(obj),
                    ]
                )
                obj_bytes = obj.read_bytes()
                assemble_cmd = run.call_args.args[0]

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertEqual(obj_bytes, b"obj")
        self.assertEqual(assemble_cmd[:3], ["clang", "-target", "aarch64-apple-darwin"])
        self.assertIn("-c", assemble_cmd)

    def test_main_aarch64_target_link_injects_target_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            exe = root / "a.out"
            src.write_text("int main(void){return 0;}", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                if "-c" in cmd:
                    Path(cmd[cmd.index("-o") + 1]).write_bytes(b"obj")
                return subprocess.CompletedProcess(cmd, 0)

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main(
                    [
                        "--target=aarch64-apple-darwin",
                        "-nostdinc",
                        str(src),
                        "-o",
                        str(exe),
                    ]
                )
                link_cmd = run.call_args_list[-1].args[0]

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertEqual(link_cmd[:3], ["clang", "-target", "aarch64-apple-darwin"])
        self.assertEqual(link_cmd[-2:], ["-o", str(exe)])

    def test_main_aarch64_target_rejects_function_body_gnu_asm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asm.c"
            path.write_text(
                'int main(void){\n  __asm__ __volatile__("movq %rcx, %rax");\n  return 0;\n}',
                encoding="utf-8",
            )
            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(
                    ["--target=aarch64-apple-darwin", "-nostdinc", str(path)]
                )
            self.assertNotEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertIn("GNU asm statement is not supported for this target", stderr)
            run.assert_not_called()

    def test_main_unsupported_target_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(["--target=wasm32", str(path)])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Unsupported target: wasm32", stderr)
        run.assert_not_called()

    def test_main_llvm_target_link_preserves_linker_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            llc_path = str(root / "llvm-llc")
            src = root / "ok.c"
            exe = root / "ok"
            src.write_text("int f(void){return 0;}", encoding="utf-8")

            with (
                patch.dict("os.environ", {"XCC_LLC": llc_path}, clear=False),
                patch(
                    "xcc.cc_driver.subprocess.run",
                    side_effect=self._fake_llvm_llc_run(llc_path),
                ) as run,
            ):
                code, stdout, stderr = self._run_main(
                    [
                        "-nostdinc",
                        str(src),
                        "-L/tmp/example",
                        "-lmissing",
                        "-framework",
                        "CoreFoundation",
                        "-o",
                        str(exe),
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        link_cmd = next(call.args[0] for call in run.call_args_list if call.args[0][0] == "clang")
        self.assertEqual(link_cmd[0], "clang")
        self.assertNotIn(str(src), link_cmd)
        self.assertIn("-L/tmp/example", link_cmd)
        self.assertIn("-lmissing", link_cmd)
        self.assertIn("-framework", link_cmd)
        self.assertIn("CoreFoundation", link_cmd)
        self.assertIn(str(exe), link_cmd)

    def test_main_llvm_target_link_drops_forced_source_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            llc_path = str(root / "llvm-llc")
            exe = root / "ok"
            with (
                patch.dict("os.environ", {"XCC_LLC": llc_path}, clear=False),
                patch(
                    "xcc.cc_driver.subprocess.run",
                    side_effect=self._fake_llvm_llc_run(llc_path),
                ) as run,
            ):
                code, stdout, stderr = self._run_main(
                    ["-nostdinc", "-x", "c", "-", "-o", str(exe)],
                    stdin_text="int main(void){return 0;}",
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        link_cmd = next(call.args[0] for call in run.call_args_list if call.args[0][0] == "clang")
        self.assertNotIn("-x", link_cmd)
        self.assertNotIn("c", link_cmd)
        self.assertNotIn("-", link_cmd)

    def test_main_frontend_unknown_option_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(["--frontend", str(path), "--unknown"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("frontend mode error: unknown options", stderr)
        run.assert_not_called()

    def test_main_io_error(self) -> None:
        code, stdout, stderr = self._run_main(["--frontend", "/definitely/not/here.c"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("I/O error", stderr)

    def test_main_frontend_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.c"
            path.write_text("int main(){return;}", encoding="utf-8")
            code, stdout, stderr = self._run_main(["--frontend", str(path)])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("sema: Non-void function must return a value", stderr)

    def test_main_frontend_error_json_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.c"
            path.write_text("#if 1 +\nint main(void){return 0;}\n", encoding="utf-8")
            code, stdout, stderr = self._run_main([str(path), "--diag-format", "json"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn('"stage":"pp"', stderr)
        self.assertIn('"code":"XCC-PP-0103"', stderr)

    def test_main_define_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(void){return ZERO;}", encoding="utf-8")
            code, stdout, stderr = self._run_main(["--frontend", str(path), "-D", "ZERO=0"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_iquote_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quote_dir = root / "quote"
            quote_dir.mkdir()
            (quote_dir / "inc.h").write_text("#define VALUE 7\n", encoding="utf-8")
            path = root / "ok.c"
            path.write_text('#include "inc.h"\nint main(void){return VALUE;}\n', encoding="utf-8")
            code, stdout, stderr = self._run_main(
                ["--frontend", str(path), "-iquote", str(quote_dir)]
            )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_cpath_environment_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cpath_dir = root / "cpath"
            cpath_dir.mkdir()
            (cpath_dir / "inc.h").write_text("#define VALUE 23\n", encoding="utf-8")
            path = root / "ok.c"
            path.write_text("#include <inc.h>\nint main(void){return VALUE;}\n", encoding="utf-8")
            with patch.dict("os.environ", {"CPATH": str(cpath_dir)}, clear=False):
                code, stdout, stderr = self._run_main(["--frontend", str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_cpath_empty_entry_uses_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text("#define VALUE 37\n", encoding="utf-8")
            path = root / "ok.c"
            path.write_text("#include <inc.h>\nint main(void){return VALUE;}\n", encoding="utf-8")
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict("os.environ", {"CPATH": f"{os.pathsep}"}, clear=False):
                    code, stdout, stderr = self._run_main(["--frontend", str(path)])
            finally:
                os.chdir(previous_cwd)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_idirafter_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            after_dir = root / "after"
            after_dir.mkdir()
            (after_dir / "inc.h").write_text("#define VALUE 9\n", encoding="utf-8")
            path = root / "ok.c"
            path.write_text("#include <inc.h>\nint main(void){return VALUE;}\n", encoding="utf-8")
            code, stdout, stderr = self._run_main(
                ["--frontend", str(path), "-idirafter", str(after_dir)]
            )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_nostdinc_disables_environment_include_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cpath_dir = root / "cpath"
            cpath_dir.mkdir()
            (cpath_dir / "inc.h").write_text("#define VALUE 31\n", encoding="utf-8")
            path = root / "ok.c"
            path.write_text("#include <inc.h>\nint main(void){return VALUE;}\n", encoding="utf-8")
            with patch.dict("os.environ", {"CPATH": str(cpath_dir)}, clear=False):
                code, stdout, stderr = self._run_main(["--frontend", str(path), "-nostdinc"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Include not found", stderr)

    def test_main_forced_include_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_dir = root / "inc"
            include_dir.mkdir()
            (include_dir / "forced.h").write_text("#define VALUE 13\n", encoding="utf-8")
            path = root / "ok.c"
            path.write_text("int main(void){return VALUE;}\n", encoding="utf-8")
            code, stdout, stderr = self._run_main(
                ["--frontend", str(path), "-I", str(include_dir), "-include", "forced.h"]
            )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_imacros_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_dir = root / "inc"
            include_dir.mkdir()
            (include_dir / "defs.h").write_text("#define VALUE 17\n", encoding="utf-8")
            path = root / "ok.c"
            path.write_text("int main(void){return VALUE;}\n", encoding="utf-8")
            code, stdout, stderr = self._run_main(
                ["--frontend", str(path), "-I", str(include_dir), "-imacros", "defs.h"]
            )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_ffreestanding_sets_stdc_hosted_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text(
                "#if __STDC_HOSTED__ != 0\n#error hosted\n#endif\nint main(void){return 0;}\n",
                encoding="utf-8",
            )
            code, stdout, stderr = self._run_main(["--frontend", str(path), "-ffreestanding"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_undef_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.c"
            path.write_text("int main(void){return ZERO;}", encoding="utf-8")
            code, stdout, stderr = self._run_main(
                ["--frontend", str(path), "-D", "ZERO=0", "-U", "ZERO"]
            )
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Undeclared identifier: ZERO", stderr)


if __name__ == "__main__":
    unittest.main()
