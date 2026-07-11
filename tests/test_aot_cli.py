import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xcc.aot.cli import main as native_main
from xcc.aot.hosted_cli import hosted_main, normalize_llvm
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.lower import lower_source_to_ir
from xcc.aot.native import compile_llvm_executable

ROOT = Path(__file__).resolve().parents[1]


def _run(entry, argv: tuple[str, ...]):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        status = entry(len(argv), argv)
    return status, stdout.getvalue(), stderr.getvalue()


class AotCliTests(unittest.TestCase):
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
        status, stdout, stderr = _run(
            hosted_main,
            (
                "xcc-aot",
                "build",
                "--source-root",
                "src/xcc",
                "--entry",
                "xcc.aot.cli:main",
                "--output",
                "out",
                "--parser=subset",
            ),
        )
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("unavailable before Milestone 3", stderr)

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
            with patch("xcc.aot.native._run_tool") as run_tool:
                compile_llvm_executable(
                    "define i32 @main() { ret i32 0 }\n",
                    output,
                    filename="tool.py",
                    llc="/tool/llc",
                    assembler="/tool/as",
                    linker="/tool/ld",
                )

        commands = [call.args[0] for call in run_tool.call_args_list]
        self.assertEqual(commands[0][0:2], ("/tool/llc", "-filetype=asm"))
        self.assertEqual(commands[1][0], "/tool/as")
        self.assertEqual(commands[2][0], "/tool/ld")


if __name__ == "__main__":
    unittest.main()
