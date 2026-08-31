import contextlib
import io
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import xcc.aot.cli as native_cli_module
from xcc.aot.cli import main as native_main
from xcc.aot.hosted_cli import hosted_main, normalize_llvm
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.lower import lower_source_to_ir
from xcc.aot.native import _native_llc_options, compile_llvm_executable

ROOT = Path(__file__).resolve().parents[1]


def _run(entry, argv: tuple[str, ...]):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        status = entry(len(argv), argv)
    return status, stdout.getvalue(), stderr.getvalue()


class AotCliTests(unittest.TestCase):
    def test_native_command_and_option_boundaries(self) -> None:
        cases = (
            (("xcc-aot",), 2, "usage:"),
            (("xcc-aot", "--help"), 0, "usage:"),
            (("xcc-aot", "unknown"), 2, "unknown command"),
            (("xcc-aot", "build", "--help"), 0, "usage:"),
            (("xcc-aot", "build", "--parser"), 2, "rejects parser"),
            (
                ("xcc-aot", "build", "--parser=subset", "--debug", "--debug"),
                2,
                "duplicate option",
            ),
            (
                ("xcc-aot", "build", "--parser=subset", "--source-root"),
                2,
                "missing value",
            ),
            (
                ("xcc-aot", "build", "--parser=subset", "--unknown=value"),
                2,
                "unknown option",
            ),
            (
                ("xcc-aot", "build", "--parser=subset", "--source-root="),
                2,
                "empty value",
            ),
        )
        for argv, expected_status, message in cases:
            with self.subTest(argv=argv):
                status, stdout, stderr = _run(native_main, argv)
                self.assertEqual((status, stderr), (expected_status, ""))
                self.assertIn(message, stdout)

    def test_native_option_values_reach_build_boundary(self) -> None:
        argv = (
            "xcc-aot",
            "build",
            "--source-root",
            "/source",
            "--entry=pkg.cli:main",
            "--output=/output",
            "--parser=subset",
            "--emit-llvm=/output.ll",
            "--emit-normalized-ir=/output.norm.ll",
            "--source-manifest=/sources.json",
            "--tool-log=/tools.log",
            "--llc=/tools/llc",
            "--assembler=/tools/as",
            "--linker=/tools/cc",
            "--debug",
            "--profile",
            "--no-cache",
        )
        with patch("xcc.aot.cli._run_native_build", return_value=23) as build:
            status, stdout, stderr = _run(native_main, argv)

        self.assertEqual((status, stdout, stderr), (23, "", ""))
        build.assert_called_once_with(
            "/source",
            "pkg.cli:main",
            "/output",
            "/output.ll",
            "/output.norm.ll",
            "/sources.json",
            "/tools.log",
            "/tools/llc",
            "/tools/as",
            "/tools/cc",
            True,
            True,
            True,
        )

    def test_native_build_reports_artifact_and_tool_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "cli.py").write_text(
                "def main(argc: int, argv: tuple[str, ...]) -> int:\n    return 0\n",
                encoding="utf-8",
            )
            output = str(Path(tmp) / "out")

            def invoke(
                *,
                entry: str = "pkg.cli:main",
                normalized: str = "",
                manifest: str = "",
                tool_log: str = "",
                assembler: str = "",
                debug: bool = False,
                profile: bool = False,
            ) -> tuple[int, str]:
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    status = native_cli_module._run_native_build(
                        str(root),
                        entry,
                        output,
                        output + ".ll",
                        normalized,
                        manifest,
                        tool_log,
                        "/tools/llc",
                        assembler,
                        "/tools/cc",
                        True,
                        debug,
                        profile,
                    )
                return status, stdout.getvalue()

            status, stdout = invoke(entry="invalid")
            self.assertEqual(status, 2)
            self.assertIn("invalid entry", stdout)

            with patch("xcc.aot.cli._write_native_reachability", return_value=False):
                status, stdout = invoke()
            self.assertEqual(status, 1)
            self.assertIn("cannot write native reachability", stdout)

            with (
                patch("xcc.aot.cli._write_native_reachability", return_value=True),
                patch("xcc.aot.cli._write_text", return_value=False),
            ):
                status, stdout = invoke()
            self.assertEqual(status, 1)
            self.assertIn("cannot write LLVM", stdout)

            with (
                patch("xcc.aot.cli._write_native_reachability", return_value=True),
                patch("xcc.aot.cli._write_text", side_effect=(True, False)),
            ):
                status, stdout = invoke(normalized=output + ".norm.ll")
            self.assertEqual(status, 1)
            self.assertIn("cannot write normalized LLVM", stdout)

            with (
                patch("xcc.aot.cli._write_native_reachability", return_value=True),
                patch("xcc.aot.cli._write_text", side_effect=(True, False)),
            ):
                status, stdout = invoke(manifest=output + ".json")
            self.assertEqual(status, 1)
            self.assertIn("cannot write source manifest", stdout)

            common_patches = (
                patch("xcc.aot.cli._write_native_reachability", return_value=True),
                patch("xcc.aot.cli._write_text", return_value=True),
            )
            with (
                common_patches[0],
                common_patches[1],
                patch("xcc.aot.cli._run_tool", return_value=1),
            ):
                status, stdout = invoke(assembler="/tools/as", debug=True)
            self.assertEqual(status, 1)
            self.assertIn("llc failed", stdout)

            with (
                patch("xcc.aot.cli._write_native_reachability", return_value=True),
                patch("xcc.aot.cli._write_text", return_value=True),
                patch("xcc.aot.cli._run_tool", side_effect=(0, 1)),
            ):
                status, stdout = invoke(assembler="/tools/as", profile=True)
            self.assertEqual(status, 1)
            self.assertIn("assembler failed", stdout)

            with (
                patch("xcc.aot.cli._write_native_reachability", return_value=True),
                patch("xcc.aot.cli._write_text", return_value=True),
                patch("xcc.aot.cli._run_tool", return_value=1),
            ):
                status, stdout = invoke()
            self.assertEqual(status, 1)
            self.assertIn("llc failed", stdout)

            with (
                patch("xcc.aot.cli._write_native_reachability", return_value=True),
                patch("xcc.aot.cli._write_text", return_value=True),
                patch("xcc.aot.cli._run_tool", side_effect=(0, 1)),
            ):
                status, stdout = invoke()
            self.assertEqual(status, 1)
            self.assertIn("linker failed", stdout)

            with (
                patch("xcc.aot.cli._write_native_reachability", return_value=True),
                patch("xcc.aot.cli._write_text", side_effect=(True, False)),
                patch("xcc.aot.cli._run_tool", return_value=0),
            ):
                status, stdout = invoke(tool_log=output + ".tools")
            self.assertEqual(status, 1)
            self.assertIn("cannot write tool log", stdout)

            with (
                patch("xcc.aot.cli._write_native_reachability", return_value=True),
                patch("xcc.aot.cli._write_text", return_value=True) as write_text,
                patch("xcc.aot.cli._run_tool", return_value=0),
            ):
                status, stdout = invoke(
                    tool_log=output + ".tools",
                    assembler="/tools/as",
                    debug=True,
                )
            self.assertEqual((status, stdout), (0, ""))
            self.assertIn("format=xcc-aot-tool-log-v1", write_text.call_args_list[-1].args[1])

    def test_native_normalizer_and_tool_subprocess_boundaries(self) -> None:
        source_root = "/tmp/source"
        llvm_text = (
            f'; ModuleID = "{source_root}/module.py"  \n'
            f'source_filename = "{source_root}/module.py"\n'
            f'!DIFile(filename: "module.py", directory: "{source_root}")\n'
            "define i32 @main() { ret i32 0 }  \n"
        )
        normalized = native_cli_module._normalize_llvm(llvm_text, source_root)
        self.assertNotIn(source_root, normalized)
        self.assertFalse(native_cli_module._llvm_is_already_normalized("line\r\n", source_root))
        with patch("xcc.aot.cli.subprocess.call", return_value=17) as call:
            self.assertEqual(native_cli_module._run_tool(("tool", "arg")), 17)
        call.assert_called_once_with(("tool", "arg"))

    def test_aot_module_entrypoint_delegates_to_cli(self) -> None:
        stdout = io.StringIO()
        with (
            patch.object(sys, "argv", ["xcc-aot", "--help"]),
            contextlib.redirect_stdout(stdout),
            self.assertRaises(SystemExit) as context,
        ):
            runpy.run_module("xcc.aot.__main__", run_name="__main__")

        self.assertEqual(context.exception.code, 0)
        self.assertIn("usage:", stdout.getvalue())

    @unittest.skipUnless(
        Path("/opt/homebrew/opt/llvm/bin/llc").is_file() and Path("/usr/bin/dwarfdump").is_file(),
        "LLVM llc and dwarfdump are required",
    )
    def test_real_debug_object_has_dwarf_lines_and_runtime_unwind(self) -> None:
        source = (
            "def helper(value: int) -> int:\n"
            "    adjusted = value + 1\n"
            "    return adjusted\n"
            "def answer() -> int:\n"
            "    return helper(2)\n"
        )
        module = lower_source_to_ir(
            source,
            filename="/tmp/xcc-native-debug/compiler.py",
            entry="answer",
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "debug-compiler"
            compile_llvm_executable(
                emit_llvm_text(module, debug=True),
                output,
                filename="compiler.py",
                llc="/opt/homebrew/opt/llvm/bin/llc",
                debug=True,
            )
            dwarf = subprocess.run(
                ("/usr/bin/dwarfdump", "--debug-info", "--debug-line", str(output) + ".o"),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            unwind = subprocess.run(
                (
                    "/opt/homebrew/opt/llvm/bin/llvm-dwarfdump",
                    "--eh-frame",
                    str(output) + ".o",
                ),
                check=True,
                capture_output=True,
                text=True,
            ).stdout

        self.assertIn("DW_TAG_compile_unit", dwarf)
        self.assertIn("DW_TAG_subprogram", dwarf)
        self.assertIn("compiler.py", dwarf)
        self.assertRegex(dwarf, r"0x[0-9a-f]+\s+2\s+5\s+1")
        self.assertIn(".eh_frame contents:", unwind)
        self.assertIn("FDE", unwind)

    @unittest.skipUnless(
        all(
            Path(f"/opt/homebrew/opt/llvm/bin/{tool}").is_file()
            for tool in ("llc", "llvm-dwarfdump", "llvm-objdump", "llvm-readelf")
        ),
        "LLVM cross-target inspection tools are required",
    )
    def test_linux_elf_debug_object_is_perf_and_frame_pointer_compatible(self) -> None:
        source = (
            "def helper(value: int) -> int:\n"
            "    adjusted = value + 1\n"
            "    return adjusted\n"
            "def answer() -> int:\n"
            "    return helper(2)\n"
        )
        module = lower_source_to_ir(
            source,
            filename="/build/xcc/compiler.py",
            entry="answer",
        )
        llvm_bin = Path("/opt/homebrew/opt/llvm/bin")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            llvm_path = base / "compiler.ll"
            object_path = base / "compiler.o"
            llvm_path.write_text(emit_llvm_text(module, debug=True), encoding="utf-8")
            subprocess.run(
                (
                    str(llvm_bin / "llc"),
                    "-mtriple=x86_64-unknown-linux-gnu",
                    "-filetype=obj",
                    "--frame-pointer=all",
                    "--emit-dwarf-unwind=always",
                    "--dwarf-version=4",
                    str(llvm_path),
                    "-o",
                    str(object_path),
                ),
                check=True,
                capture_output=True,
                text=True,
            )
            sections = subprocess.run(
                (str(llvm_bin / "llvm-readelf"), "--sections", str(object_path)),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            unwind = subprocess.run(
                (str(llvm_bin / "llvm-dwarfdump"), "--eh-frame", str(object_path)),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            disassembly = subprocess.run(
                (str(llvm_bin / "llvm-objdump"), "--disassemble", str(object_path)),
                check=True,
                capture_output=True,
                text=True,
            ).stdout

        for section in (".debug_info", ".debug_line", ".eh_frame"):
            self.assertIn(section, sections)
        self.assertIn("FDE", unwind)
        self.assertRegex(disassembly, r"pushq?\s+%rbp")
        self.assertRegex(disassembly, r"movq?\s+%rsp,\s*%rbp")

    def test_debug_and_profile_native_options_preserve_default_commands(self) -> None:
        self.assertEqual(_native_llc_options(debug=False, profile=False), ())
        debug = _native_llc_options(debug=True, profile=False)
        profile = _native_llc_options(debug=False, profile=True)
        for option in ("--frame-pointer=all", "--emit-dwarf-unwind=always"):
            self.assertIn(option, debug)
            self.assertIn(option, profile)
        self.assertNotIn("-O0", debug)
        self.assertNotIn("-O0", profile)
        self.assertNotIn("--force-dwarf-frame-section", debug)

    def test_hosted_debug_build_emits_metadata_and_passes_native_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "cli.py").write_text(
                "def main(argc: int, argv: tuple[str, ...]) -> int:\n    return 0\n",
                encoding="utf-8",
            )
            output = base / "xcc-aot"
            llvm_path = base / "xcc-aot.ll"
            argv = (
                "xcc-aot",
                "build",
                f"--source-root={root}",
                "--entry=pkg.cli:main",
                f"--output={output}",
                "--parser=subset",
                "--debug",
                f"--emit-llvm={llvm_path}",
            )
            with patch("xcc.aot.hosted_cli.compile_llvm_executable") as compile_executable:
                status, stdout, stderr = _run(hosted_main, argv)

            llvm_text = llvm_path.read_text(encoding="utf-8")

        self.assertEqual((status, stdout, stderr), (0, "", ""))
        self.assertIn("!DIFile", llvm_text)
        self.assertTrue(compile_executable.call_args.kwargs["debug"])
        self.assertFalse(compile_executable.call_args.kwargs["profile"])

    def test_v440_native_normalizer_recognizes_allocation_free_input(self) -> None:
        predicate = getattr(native_cli_module, "_llvm_is_already_normalized", None)
        self.assertTrue(callable(predicate))
        assert callable(predicate)
        self.assertTrue(predicate("define i32 @main() {\n  ret i32 0\n}\n", "src/xcc"))
        self.assertFalse(predicate("define i32 @main() { \n}\n", "src/xcc"))
        self.assertFalse(predicate('source_filename = "src/xcc/main.py"\n', "src/xcc"))
        self.assertFalse(predicate("define i32 @main() {\n}\n\nextra", "src/xcc"))

    def test_native_cli_source_lowers_to_valid_llvm(self) -> None:
        path = ROOT / "src/xcc/aot/cli.py"
        module = lower_source_to_ir(
            path.read_text(encoding="utf-8"),
            filename=str(path),
            entry="main",
            include_functions={"main"},
        )

        llvm_text = emit_llvm_text(module)

        self.assertIn("define i32 @main", llvm_text)

    def test_hosted_and_native_help_version_and_parser_boundaries(self) -> None:
        status, stdout, stderr = _run(hosted_main, ("xcc-aot", "--version"))
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("hosted", stdout)
        status, stdout, stderr = _run(native_main, ("xcc-aot", "--version"))
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("native-contract", stdout)
        for argv in (
            ("xcc-aot", "build", "--parser=cpython"),
            ("xcc-aot", "build", "--parser", "cpython"),
            ("xcc-aot", "build", "--help", "--parser=cpython"),
            ("xcc-aot", "build", "--parser=cpython", "--help"),
        ):
            with self.subTest(argv=argv):
                status, stdout, stderr = _run(native_main, argv)
                self.assertEqual((status, stderr), (2, ""))
                self.assertIn("rejects --parser=cpython", stdout)
        status, stdout, stderr = _run(
            native_main,
            ("xcc-aot", "build", "--parser=other"),
        )
        self.assertEqual((status, stderr), (2, ""))
        self.assertIn("rejects parser: other", stdout)

    def test_hosted_usage_rejects_missing_duplicate_and_unknown_options(self) -> None:
        for argv, message in (
            (("xcc-aot", "build"), "missing required option"),
            (
                (
                    "xcc-aot",
                    "build",
                    "--source-root=xcc",
                    "--source-root=xcc",
                ),
                "duplicate option",
            ),
            (("xcc-aot", "build", "--unknown"), "unknown option"),
        ):
            with self.subTest(argv=argv):
                status, _stdout, stderr = _run(hosted_main, argv)
                self.assertEqual(status, 2)
                self.assertIn(message, stderr)

    def test_native_usage_rejects_missing_duplicate_and_unknown_options(self) -> None:
        for argv, message in (
            (("xcc-aot", "build"), "missing required option"),
            (
                (
                    "xcc-aot",
                    "build",
                    "--source-root=xcc",
                    "--source-root=xcc",
                    "--parser=subset",
                ),
                "duplicate option",
            ),
            (("xcc-aot", "build", "--unknown"), "unknown option"),
        ):
            with self.subTest(argv=argv):
                status, stdout, _stderr = _run(native_main, argv)
                self.assertEqual(status, 2)
                self.assertIn(message, stdout)

    def test_native_build_lowers_full_subset_source_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "helper.py").write_text(
                "int32 = int\ndef result() -> int32:\n    return 7\n",
                encoding="utf-8",
            )
            (root / "cli.py").write_text(
                "from pkg.helper import result\n"
                "int32 = int\n"
                "def main(argc: int32, argv: tuple[str, ...]) -> int32:\n"
                "    return result()\n",
                encoding="utf-8",
            )
            output = base / "out" / "xcc-aot"
            llvm_path = base / "artifacts" / "cli.ll"
            manifest_path = base / "artifacts" / "sources.json"
            output.parent.mkdir()
            llvm_path.parent.mkdir()
            argv = (
                "xcc-aot",
                "build",
                f"--source-root={root}",
                "--entry=pkg.cli:main",
                f"--output={output}",
                "--parser=subset",
                "--no-cache",
                f"--emit-llvm={llvm_path}",
                f"--source-manifest={manifest_path}",
            )
            with patch("xcc.aot.cli._run_tool", return_value=0):
                status, stdout, stderr = _run(native_main, argv)

            llvm_text = llvm_path.read_text(encoding="utf-8")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual((status, stdout, stderr), (0, "", ""))
        self.assertIn("define i32 @pkg.cli.main", llvm_text)
        self.assertIn("define i32 @pkg.helper.result", llvm_text)
        self.assertEqual(
            [unit["module"] for unit in manifest["units"]],
            ["pkg", "pkg.helper", "pkg.cli"],
        )
        self.assertEqual(
            manifest["cache"],
            {
                "directory": None,
                "read_enabled": False,
                "requested_no_cache": True,
                "write_enabled": False,
            },
        )

    def test_native_build_resolves_function_local_static_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "helper.py").write_text(
                "def result() -> int:\n    return 7\n",
                encoding="utf-8",
            )
            (root / "cli.py").write_text(
                "def main(argc: int, argv: tuple[str, ...]) -> int:\n"
                "    from pkg.helper import result\n"
                "    return result()\n",
                encoding="utf-8",
            )
            output = base / "out" / "xcc-aot"
            llvm_path = base / "artifacts" / "cli.ll"
            output.parent.mkdir()
            llvm_path.parent.mkdir()
            argv = (
                "xcc-aot",
                "build",
                f"--source-root={root}",
                "--entry=pkg.cli:main",
                f"--output={output}",
                "--parser=subset",
                "--no-cache",
                f"--emit-llvm={llvm_path}",
            )
            with patch("xcc.aot.cli._run_tool", return_value=0):
                status, stdout, stderr = _run(native_main, argv)

            llvm_text = llvm_path.read_text(encoding="utf-8")

        self.assertEqual((status, stdout, stderr), (0, "", ""))
        self.assertIn("define i64 @pkg.helper.result", llvm_text)
        self.assertIn("call i64 @pkg.helper.result()", llvm_text)

    def test_hosted_build_emits_contract_artifacts_and_invokes_native_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "cli.py").write_text(
                "int32 = int\n"
                "def main(argc: int32, argv: tuple[str, ...]) -> int32:\n"
                "    return 0\n",
                encoding="utf-8",
            )
            output = base / "out" / "xcc-aot"
            llvm_path = base / "artifacts" / "cli.ll"
            normalized_path = base / "artifacts" / "cli.norm.ll"
            manifest_path = base / "artifacts" / "sources.json"
            tool_log = base / "artifacts" / "tools.log"
            argv = (
                "xcc-aot",
                "build",
                f"--source-root={root}",
                "--entry=pkg.cli:main",
                f"--output={output}",
                "--parser=cpython",
                "--no-cache",
                f"--emit-llvm={llvm_path}",
                f"--emit-normalized-ir={normalized_path}",
                f"--source-manifest={manifest_path}",
                f"--tool-log={tool_log}",
                "--llc=/configured/llc",
                "--assembler=/configured/as",
                "--linker=/configured/cc",
            )
            with patch("xcc.aot.hosted_cli.compile_llvm_executable") as compile_executable:
                status, stdout, stderr = _run(hosted_main, argv)

            self.assertEqual((status, stdout, stderr), (0, "", ""))
            llvm_text = llvm_path.read_text(encoding="utf-8")
            self.assertIn("define i32 @main", llvm_text)
            self.assertIn("@pkg.cli.main", llvm_text)
            self.assertNotIn(str(root.resolve()), normalized_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["entry"], "pkg.cli")
            self.assertEqual(
                manifest["cache"],
                {
                    "directory": None,
                    "read_enabled": False,
                    "requested_no_cache": True,
                    "write_enabled": False,
                },
            )
            self.assertFalse((root / ".aot-cache").exists())
            compile_executable.assert_called_once()
            self.assertEqual(compile_executable.call_args.kwargs["llc"], "/configured/llc")
            self.assertEqual(
                compile_executable.call_args.kwargs["assembler"],
                "/configured/as",
            )
            self.assertEqual(
                compile_executable.call_args.kwargs["linker"],
                "/configured/cc",
            )
            self.assertEqual(compile_executable.call_args.kwargs["tool_log"], tool_log)

    def test_hosted_parser_oracle_command_emits_canonical_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("ROOT = 1\n", encoding="utf-8")
            (root / "entry.py").write_text(
                "def main() -> int:\n    return 0\n",
                encoding="utf-8",
            )
            status, stdout, stderr = _run(
                hosted_main,
                (
                    "xcc-aot",
                    "parser-oracle",
                    f"--source-root={root}",
                    "--entry=pkg.entry:main",
                ),
            )

        self.assertEqual((status, stderr), (0, ""))
        payload = json.loads(stdout)
        self.assertEqual(payload["entry"], "pkg.entry")
        self.assertEqual(payload["failures"], [])
        self.assertEqual(payload["version"], 1)

    def test_hosted_subset_build_never_calls_cpython_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "cli.py").write_text(
                "int32 = int\n"
                "def result() -> int32:\n"
                "    return 0\n"
                "def main(argc: int32, argv: tuple[str, ...]) -> int32:\n"
                "    return result()\n",
                encoding="utf-8",
            )
            output = base / "out" / "xcc-aot"
            normalized_path = base / "artifacts" / "subset.ir"
            manifest_path = base / "artifacts" / "sources.json"
            argv = (
                "xcc-aot",
                "build",
                f"--source-root={root}",
                "--entry=pkg.cli:main",
                f"--output={output}",
                "--parser=subset",
                "--no-cache",
                f"--emit-normalized-ir={normalized_path}",
                f"--source-manifest={manifest_path}",
            )
            with (
                patch(
                    "xcc.aot.cpython_ast_adapter.parse_cpython_source",
                    side_effect=AssertionError("hosted adapter reached"),
                ),
                patch("xcc.aot.hosted_cli.compile_llvm_executable") as compile_executable,
            ):
                status, stdout, stderr = _run(hosted_main, argv)

            reachability = normalized_path.with_suffix(".reachability")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            reachability_text = reachability.read_text(encoding="utf-8")

        self.assertEqual((status, stdout, stderr), (0, "", ""))
        self.assertEqual(manifest["parser"], "subset")
        self.assertIn("parser=subset", reachability_text)
        self.assertIn("native_call_graph=true", reachability_text)
        self.assertIn("root=pkg.cli.main", reachability_text)
        self.assertIn(
            "edge=function:pkg.cli.main->function:pkg.cli.result;reason=call",
            reachability_text,
        )
        self.assertNotIn("cpython_ast_adapter", reachability_text)
        compile_executable.assert_called_once()

    def test_normalized_llvm_only_rewrites_root_and_trailing_space(self) -> None:
        self.assertEqual(
            normalize_llvm(
                'source_filename = "/tmp/root/a.py"  \n'
                '@value = private constant [16 x i8] c"/tmp/root/data\\00"\n',
                "/tmp/root",
            ),
            'source_filename = "$SOURCE_ROOT/a.py"\n'
            '@value = private constant [16 x i8] c"/tmp/root/data\\00"\n',
        )

    def test_configured_assembler_and_linker_commands_are_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bin" / "tool"
            tool_log = Path(tmp) / "artifacts" / "tools.log"
            with (
                patch("xcc.aot.native.find_llc", return_value="/tool/llc"),
                patch("xcc.aot.native._run_tool") as run_tool,
            ):
                compile_llvm_executable(
                    "define i32 @main() { ret i32 0 }\n",
                    output,
                    filename="tool.py",
                    llc="/tool/llc",
                    assembler="/tool/as",
                    linker="/tool/ld",
                    tool_log=tool_log,
                )

            tool_log_text = tool_log.read_text(encoding="utf-8")

        commands = [call.args[0] for call in run_tool.call_args_list]
        self.assertEqual(commands[0][0:2], ("/tool/llc", "-filetype=asm"))
        self.assertEqual(commands[1][0], "/tool/as")
        self.assertEqual(commands[2][0], "/tool/ld")
        self.assertEqual(
            tool_log_text,
            "format=xcc-aot-tool-log-v1\n"
            f"command=/tool/llc\t-filetype=asm\t{output}.ll\t-o\t{output}.s\n"
            f"command=/tool/as\t{output}.s\t-o\t{output}.o\n"
            f"command=/tool/ld\t{output}.o\t-o\t{output}\n",
        )


if __name__ == "__main__":
    unittest.main()
