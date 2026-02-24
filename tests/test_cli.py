import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc import main


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
            code, stdout, stderr = self._run_main([str(path)])
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

    def test_main_missing_input(self) -> None:
        code, stdout, stderr = self._run_main([])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("usage:", stderr)

    def test_main_unknown_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            code, stdout, stderr = self._run_main([str(path), "--unknown"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("unrecognized arguments", stderr)

    def test_main_io_error(self) -> None:
        code, stdout, stderr = self._run_main(["/definitely/not/here.c"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("I/O error", stderr)

    def test_main_frontend_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.c"
            path.write_text("int main(){return;}", encoding="utf-8")
            code, stdout, stderr = self._run_main([str(path)])
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
            code, stdout, stderr = self._run_main([str(path), "-D", "ZERO=0"])
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
            code, stdout, stderr = self._run_main([str(path), "-iquote", str(quote_dir)])
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
            path.write_text('#include <inc.h>\nint main(void){return VALUE;}\n', encoding="utf-8")
            with patch.dict("os.environ", {"CPATH": str(cpath_dir)}, clear=False):
                code, stdout, stderr = self._run_main([str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_cpath_empty_entry_uses_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text("#define VALUE 37\n", encoding="utf-8")
            path = root / "ok.c"
            path.write_text('#include <inc.h>\nint main(void){return VALUE;}\n', encoding="utf-8")
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict("os.environ", {"CPATH": f"{os.pathsep}"}, clear=False):
                    code, stdout, stderr = self._run_main([str(path)])
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
            path.write_text('#include <inc.h>\nint main(void){return VALUE;}\n', encoding="utf-8")
            code, stdout, stderr = self._run_main([str(path), "-idirafter", str(after_dir)])
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
            path.write_text('#include <inc.h>\nint main(void){return VALUE;}\n', encoding="utf-8")
            with patch.dict("os.environ", {"CPATH": str(cpath_dir)}, clear=False):
                code, stdout, stderr = self._run_main([str(path), "-nostdinc"])
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
            code, stdout, stderr = self._run_main([str(path), "-I", str(include_dir), "-include", "forced.h"])
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
            code, stdout, stderr = self._run_main([str(path), "-I", str(include_dir), "-imacros", "defs.h"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, f"xcc: ok: {path}\n")

    def test_main_undef_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.c"
            path.write_text("int main(void){return ZERO;}", encoding="utf-8")
            code, stdout, stderr = self._run_main([str(path), "-D", "ZERO=0", "-U", "ZERO"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Undeclared identifier: ZERO", stderr)


if __name__ == "__main__":
    unittest.main()
