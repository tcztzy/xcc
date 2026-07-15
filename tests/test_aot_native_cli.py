import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot.hosted_cli import hosted_main


ROOT = Path(__file__).resolve().parents[1]
LLC = Path("/opt/homebrew/opt/llvm/bin/llc")


@unittest.skipUnless(LLC.is_file(), "LLVM llc is not available")
class AotNativeCliTests(unittest.TestCase):
    workspace: tempfile.TemporaryDirectory[str]
    build_root: Path
    compiler: Path
    reachability: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = tempfile.TemporaryDirectory()
        cls.build_root = Path(cls.workspace.name)
        output_root = cls.build_root / "compiler"
        output_root.mkdir()
        cls.compiler = output_root / "xcc-aot"
        llvm_path = output_root / "xcc-aot.ll"
        argv = (
            "xcc-aot",
            "build",
            f"--source-root={ROOT / 'src/xcc'}",
            "--entry=xcc.aot.cli:main",
            f"--output={cls.compiler}",
            "--parser=cpython",
            "--no-cache",
            f"--emit-llvm={llvm_path}",
        )
        status = hosted_main(len(argv), argv)
        if status != 0:
            raise AssertionError(f"Stage 0 native CLI build failed with status {status}")
        cls.reachability = cls.compiler.with_suffix(".reachability").read_text(
            encoding="utf-8"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.workspace.cleanup()

    def test_root_manifest_has_required_reason_edges_and_negative_gates(self) -> None:
        required_functions = (
            "xcc.aot.cli.main",
            "xcc.aot.cli._run_native_build",
            "xcc.aot.py_lexer.lex_python",
            "xcc.aot.py_parser.parse_subset_source",
            "xcc.aot.binder.bind_types",
            "xcc.aot.analysis.analyze_module",
            "xcc.aot.lower.lower_analysis_to_ir",
            "xcc.aot.ir.validate_ir_module",
            "xcc.aot.llvm_text.emit_llvm_text",
            "xcc.aot.cli._run_tool",
        )
        self.assertIn("native_call_graph=true", self.reachability)
        self.assertIn("root=xcc.aot.cli.main", self.reachability)
        for function in required_functions:
            with self.subTest(function=function):
                self.assertIn(f"function={function};", self.reachability)
        edge_targets = {
            line.split("->function:", 1)[1].split(";", 1)[0]
            for line in self.reachability.splitlines()
            if "->function:" in line
        }
        for function in required_functions[1:]:
            with self.subTest(reason_target=function):
                self.assertIn(function, edge_targets)
        for forbidden in (
            "ast.parse",
            "cpython_ast_adapter",
            "_aot_compile_smoke_source_to_object",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.reachability)

    def test_native_compiler_symbols_and_dynamic_libraries_exclude_python(self) -> None:
        symbols = subprocess.run(
            ("nm", str(self.compiler)),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for layer in ("py_lexer", "py_parser", "binder", "lower", "llvm_text", "cli"):
            with self.subTest(layer=layer):
                self.assertIn(f"xcc.aot.{layer}", symbols)
        otool = shutil.which("otool")
        if otool is not None:
            libraries = subprocess.run(
                (otool, "-L", str(self.compiler)),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertNotIn("Python", libraries)
            self.assertNotIn("libpython", libraries.lower())

    def test_native_compiler_builds_independent_python_source(self) -> None:
        source_root = self.build_root / "demo"
        output_root = self.build_root / "independent"
        source_root.mkdir()
        output_root.mkdir()
        (source_root / "program.py").write_text(
            "def main() -> int:\n"
            "    return 7\n",
            encoding="utf-8",
        )
        output = output_root / "program"
        llvm_path = output_root / "program.ll"
        source_manifest = output_root / "sources.json"
        completed = subprocess.run(
            (
                str(self.compiler),
                "build",
                f"--source-root={source_root}",
                "--entry=demo.program:main",
                f"--output={output}",
                "--parser=subset",
                "--no-cache",
                f"--emit-llvm={llvm_path}",
                f"--source-manifest={source_manifest}",
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(llvm_path.is_file())
        self.assertTrue(source_manifest.is_file())
        native_program = subprocess.run(
            (str(output),),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(native_program.returncode, 7, native_program.stdout + native_program.stderr)


if __name__ == "__main__":
    unittest.main()
