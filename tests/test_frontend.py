import io
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.frontend import (
    Diagnostic,
    FrontendError,
    compile_path,
    compile_source,
    format_token,
    read_source,
)
from xcc.lexer import TokenKind


class FrontendTests(unittest.TestCase):
    def test_compile_source_success(self) -> None:
        result = compile_source("int main(){return 0;}", filename="sample.c")
        self.assertEqual(result.filename, "sample.c")
        self.assertEqual(result.tokens[-1].kind, TokenKind.EOF)
        self.assertEqual(result.unit.functions[0].name, "main")
        self.assertIn("main", result.sema.functions)

    def test_compile_source_empty_translation_unit(self) -> None:
        result = compile_source("", filename="empty.c")
        self.assertEqual(result.filename, "empty.c")
        self.assertEqual(len(result.tokens), 1)
        self.assertEqual(result.tokens[0].kind, TokenKind.EOF)
        self.assertEqual(result.unit.functions, [])

    def test_compile_source_ignores_preprocessor_directives(self) -> None:
        source = "#define ZERO 0\nint main(void){\n#if ZERO\nreturn 1;\n#endif\nreturn 0;\n}\n"
        result = compile_source(source, filename="pp.c")
        self.assertEqual(result.unit.functions[0].name, "main")

    def test_compile_source_ignores_multiline_preprocessor_directive(self) -> None:
        source = (
            "#define SUM(a, b) \\\n"
            "  ((a) + (b))\n"
            "int main(void){return 0;}\n"
        )
        result = compile_source(source, filename="pp.c")
        self.assertEqual(result.unit.functions[0].name, "main")

    def test_compile_source_ignores_gnu_asm_statements_and_labels(self) -> None:
        source = (
            'asm("INST r1, 0");\n'
            'void foo(void) __asm("__foo_func");\n'
            'int foo1 asm("bar1") = 0;\n'
            "void f(void) {\n"
            "  long long x = 0, y = 1;\n"
            "  asm volatile(\n"
            '    "INST %0, %1"\n'
            '    : "=r"(x)\n'
            '    : "r"(y)\n'
            "  );\n"
            '  asm ("");\n'
            "}\n"
        )
        result = compile_source(source, filename="asm.c")
        self.assertEqual(result.unit.functions[0].name, "foo")
        self.assertEqual(result.unit.functions[1].name, "f")

    def test_compile_source_lex_error(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source("@", filename="bad.c")
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "lex")
        self.assertEqual((diagnostic.line, diagnostic.column), (1, 1))
        self.assertEqual(str(ctx.exception), "bad.c:1:1: lex: Unexpected character")

    def test_compile_source_parse_error(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source("int main( {return 0;}", filename="bad.c")
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "parse")
        self.assertEqual((diagnostic.line, diagnostic.column), (1, 11))

    def test_compile_source_sema_error(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source("int main(){return;}", filename="bad.c")
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "sema")
        self.assertEqual((diagnostic.line, diagnostic.column), (None, None))
        self.assertEqual(str(ctx.exception), "bad.c: sema: Non-void function must return a value")

    def test_compile_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            result = compile_path(path)
        self.assertEqual(result.filename, str(path))
        self.assertEqual(result.unit.functions[0].name, "main")

    def test_read_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.c"
            path.write_text("int main(){return 0;}", encoding="utf-8")
            filename, source = read_source(str(path))
            self.assertEqual(filename, str(path))
            self.assertEqual(source, "int main(){return 0;}")

        filename, source = read_source("-", stdin=io.StringIO("int main(){return 0;}"))
        self.assertEqual(filename, "<stdin>")
        self.assertEqual(source, "int main(){return 0;}")

    def test_diagnostic_format(self) -> None:
        self.assertEqual(
            str(Diagnostic("lex", "bad.c", "oops", 2, 3)),
            "bad.c:2:3: lex: oops",
        )
        self.assertEqual(
            str(Diagnostic("sema", "bad.c", "oops")),
            "bad.c: sema: oops",
        )

    def test_format_token(self) -> None:
        result = compile_source("int main(){return 0;}")
        self.assertEqual(format_token(result.tokens[0]), "1:1\tKEYWORD\tint")
        self.assertEqual(format_token(result.tokens[-1]), "1:22\tEOF")


if __name__ == "__main__":
    unittest.main()
