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
    def _run_main(self, argv: list[str], *, stdin_text: str = "") -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv, stdin=io.StringIO(stdin_text))
        return code, stdout.getvalue(), stderr.getvalue()

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
            src = root / "ok.c"
            obj = root / "ok.o"
            src.write_text("int f(void){return 0;}", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                if cmd[0] == "/opt/homebrew/opt/llvm/bin/llc":
                    Path(cmd[-1]).write_bytes(b"obj")
                return subprocess.CompletedProcess(cmd, 0)

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main(
                    ["-nostdinc", "-c", str(src), "-o", str(obj)]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        llc_cmd = run.call_args_list[0].args[0]
        self.assertIn("-O0", llc_cmd)
        self.assertLess(llc_cmd.index("-O0"), llc_cmd.index("-filetype=obj"))

    def test_main_explicit_llvm_target_passes_o0_to_llc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            obj = root / "ok.o"
            src.write_text("int f(void){return 0;}", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                if cmd[0] == "/opt/homebrew/opt/llvm/bin/llc":
                    Path(cmd[-1]).write_bytes(b"obj")
                return subprocess.CompletedProcess(cmd, 0)

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main(
                    ["--target=llvm", "-nostdinc", "-c", str(src), "-o", str(obj)]
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        llc_cmd = run.call_args_list[0].args[0]
        self.assertIn("-O0", llc_cmd)
        self.assertLess(llc_cmd.index("-O0"), llc_cmd.index("-filetype=obj"))

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

    def test_main_x86_64_linux_target_strips_macro_expanded_gnu_asm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "cpuid.c"
            asm_path = root / "cpuid.s"
            src.write_text(
                "#define CPUID() __asm__ __volatile__(\"cpuid\")\n"
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
                self.assertNotEqual(cmd[0], "/opt/homebrew/opt/llvm/bin/llc")
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
                self.assertNotEqual(cmd[0], "/opt/homebrew/opt/llvm/bin/llc")
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

    def test_main_llvm_target_link_preserves_linker_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "ok.c"
            exe = root / "ok"
            src.write_text("int f(void){return 0;}", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                if cmd[0] == "/opt/homebrew/opt/llvm/bin/llc":
                    Path(cmd[-1]).write_bytes(b"obj")
                return subprocess.CompletedProcess(cmd, 0)

            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
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
        link_cmd = run.call_args_list[1].args[0]
        self.assertEqual(link_cmd[0], "clang")
        self.assertNotIn(str(src), link_cmd)
        self.assertIn("-L/tmp/example", link_cmd)
        self.assertIn("-lmissing", link_cmd)
        self.assertIn("-framework", link_cmd)
        self.assertIn("CoreFoundation", link_cmd)
        self.assertIn(str(exe), link_cmd)

    def test_main_llvm_target_link_drops_forced_source_language(self) -> None:
        def fake_run(cmd, **kwargs):
            if cmd[0] == "/opt/homebrew/opt/llvm/bin/llc":
                Path(cmd[-1]).write_bytes(b"obj")
            return subprocess.CompletedProcess(cmd, 0)

        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "ok"
            with patch("xcc.cc_driver.subprocess.run", side_effect=fake_run) as run:
                code, stdout, stderr = self._run_main(
                    ["-nostdinc", "-x", "c", "-", "-o", str(exe)],
                    stdin_text="int main(void){return 0;}",
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        link_cmd = run.call_args_list[1].args[0]
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
