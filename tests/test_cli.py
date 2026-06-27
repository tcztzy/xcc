import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc import cc_driver, main


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
                commands,
                [
                    (
                        "/opt/homebrew/opt/llvm/bin/llc",
                        "-filetype=obj",
                        str(output) + ".ll",
                        "-o",
                        str(output),
                    )
                ],
            )
            self.assertEqual(
                (root / "smoke.o.ll").read_text(encoding="utf-8"),
                "define i32 @main() {\nentry:\n  ret i32 0\n}\n",
            )
            self.assertEqual(output.read_bytes(), b"object")

    def test_aot_smoke_compiler_rejects_failed_llvm_write_under_cpython(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "smoke.c"
            output = root / "smoke.o"
            source.write_text("int main(void){return 0;}\n", encoding="utf-8")

            with (
                patch("xcc.cc_driver._aot_write_text_file", return_value=False) as write_text,
                patch("subprocess.run") as run,
            ):
                code = cc_driver._aot_compile_smoke_source_to_object(
                    5,
                    ("xcc", "-c", str(source), "-o", str(output)),
                )

            self.assertEqual(code, 1)
            write_text.assert_called_once_with(
                str(output) + ".ll",
                "define i32 @main() {\nentry:\n  ret i32 0\n}\n",
            )
            run.assert_not_called()

    def test_aot_smoke_compiler_rejects_non_smoke_inputs_under_cpython(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "smoke.c"
            output = root / "smoke.o"
            source.write_text("int main(void){return 1;}\n", encoding="utf-8")

            with patch("subprocess.run") as run:
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
            run.assert_not_called()
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

    def test_driver_value_helpers_reject_missing_values_and_bad_std(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing value for -o"):
            cc_driver._take_value((), 0, "-o")
        self.assertEqual(cc_driver._parse_std("gnu17"), "gnu11")
        self.assertEqual(cc_driver._parse_std("iso9899:2011"), "c11")
        with self.assertRaisesRegex(ValueError, "Unsupported language standard"):
            cc_driver._parse_std("kandr")

    def test_llvm_config_and_llc_probe_ignore_failed_tools(self) -> None:
        with patch("xcc.cc_driver.subprocess.run", side_effect=OSError):
            self.assertIsNone(cc_driver._llvm_config_bindir("/missing/llvm-config"))
            self.assertFalse(cc_driver._is_llvm_llc("/missing/llc"))

        with patch("xcc.cc_driver.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                ("/bad/llvm-config", "--bindir"),
                1,
                stdout="",
                stderr="failed",
            )
            self.assertIsNone(cc_driver._llvm_config_bindir("/bad/llvm-config"))

    def test_llc_candidates_ignore_empty_llvm_config_and_missing_path_llc(self) -> None:
        def fake_run(cmd, **kwargs):
            self.assertEqual(tuple(cmd), ("/empty/llvm-config", "--bindir"))
            return subprocess.CompletedProcess(cmd, 0, stdout=" \n", stderr="")

        def fake_which(name: str) -> str | None:
            self.assertEqual(name, "llc")
            return None

        with (
            patch.dict("os.environ", {"LLVM_CONFIG": "/empty/llvm-config"}, clear=True),
            patch("xcc.cc_driver.shutil.which", side_effect=fake_which),
            patch("xcc.cc_driver.subprocess.run", side_effect=fake_run),
        ):
            self.assertEqual(cc_driver._llc_candidates(), ())

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
                "c99",
                "-std=gnu17",
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

    def test_driver_misc_error_and_output_helpers(self) -> None:
        version_config = cc_driver._parse_driver_config(["-V"])
        self.assertEqual(version_config.clang_argv, ("-V",))
        self.assertEqual(
            cc_driver._unique_tool_candidates(["", "/tool/llc", "/tool/llc", "/other/llc"]),
            ("/tool/llc", "/other/llc"),
        )
        self.assertEqual(cc_driver._default_output("input.c", "link", "llvm"), "a.out")
        self.assertEqual(
            cc_driver._default_output("input.c", "compile", "evm", evm_initcode=True),
            "input.init.bin",
        )
        self.assertEqual(cc_driver._default_output("input.c", "compile", "llvm"), "input.o")

        config = cc_driver._parse_driver_config(["-xc", "input.c"])
        self.assertEqual(
            cc_driver._link_argv_with_objects(config, ["input.o"]),
            ["clang", "input.o"],
        )
        delegate_config = cc_driver._parse_driver_config(["-E", "-S", "-c", "input.c"])
        self.assertEqual(delegate_config.action, "delegate")

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("xcc.cc_driver.subprocess.run", side_effect=OSError("no tool")),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            self.assertEqual(cc_driver._run_tool("missing-cc", ["-v"]), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("failed to execute missing-cc", stderr.getvalue())

    def test_main_removed_no_backend_fallback_option_is_rejected(self) -> None:
        code, stdout, stderr = self._run_main(["--no-backend-fallback", "ok.c"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("--no-backend-fallback has been removed", stderr)

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
        self.assertNotIn(((llc_path, "--help"),), [call.args for call in run.call_args_list])
        llc_cmd = self._llc_compile_cmds(run, llc_path)[0]
        self.assertIn("-O0", llc_cmd)
        self.assertLess(llc_cmd.index("-O0"), llc_cmd.index("-filetype=obj"))

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
        self.assertNotIn(((llc_path, "--help"),), [call.args for call in run.call_args_list])
        llc_cmd = self._llc_compile_cmds(run, llc_path)[0]
        self.assertIn("-O0", llc_cmd)
        self.assertLess(llc_cmd.index("-O0"), llc_cmd.index("-filetype=obj"))

    def test_find_llc_trusts_explicit_xcc_llc_without_probe(self) -> None:
        with (
            patch.dict("os.environ", {"XCC_LLC": "/toolchain/bin/llc"}, clear=True),
            patch("xcc.cc_driver.shutil.which") as which,
            patch("xcc.cc_driver.subprocess.run") as run,
        ):
            self.assertEqual(cc_driver._find_llc(), "/toolchain/bin/llc")

        which.assert_not_called()
        run.assert_not_called()

    def test_find_llc_accepts_path_candidate_with_llvm_help_stdout(self) -> None:
        def fake_run(cmd, **kwargs):
            self.assertEqual(tuple(cmd), ("/toolchain/bin/llc", "--help"))
            return subprocess.CompletedProcess(cmd, 0, stdout=self.LLVM_LLC_HELP, stderr="")

        def fake_which(name: str) -> str | None:
            return "/toolchain/bin/llc" if name == "llc" else None

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("xcc.cc_driver.shutil.which", side_effect=fake_which),
            patch("xcc.cc_driver.subprocess.run", side_effect=fake_run),
        ):
            self.assertEqual(cc_driver._find_llc(), "/toolchain/bin/llc")

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
            patch("xcc.cc_driver.shutil.which", side_effect=fake_which),
            patch("xcc.cc_driver.subprocess.run", side_effect=fake_run),
        ):
            self.assertEqual(cc_driver._find_llc(), "/good/bin/llc")

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
                patch("xcc.cc_driver.shutil.which", side_effect=fake_which),
                patch("xcc.cc_driver.subprocess.run", side_effect=fake_run),
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

    def test_main_x86_64_linux_target_link_drops_latomic(self) -> None:
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
        self.assertNotIn("-latomic", link_cmds[0])

    def test_main_x86_64_linux_target_object_only_link_drops_latomic(self) -> None:
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
        run.assert_called_once_with(("cc", str(obj), "-o", str(exe)), check=False)

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

    def test_main_backend_option_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            with patch("xcc.cc_driver.subprocess.run") as run:
                code, stdout, stderr = self._run_main(["--backend=xcc", str(path)])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("--backend has been removed", stderr)
        run.assert_not_called()

    def test_main_unhandled_internal_target_asserts(self) -> None:
        config = cc_driver.DriverConfig(
            frontend_options=cc_driver.FrontendOptions(),
            clang_argv=(),
            c_inputs=("ok.c",),
            non_c_inputs=(),
            target="not-a-target",
            action="compile",
            output=None,
            native_unsupported_flags=(),
            evm_initcode=False,
        )

        with (
            patch("xcc.cc_driver._parse_driver_config", return_value=config),
            patch("xcc.cc_driver._compile_frontend_inputs", return_value=[]),
            self.assertRaisesRegex(AssertionError, "unhandled target: not-a-target"),
        ):
            self._run_main(["ok.c"])

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
