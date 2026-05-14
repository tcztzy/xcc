import io
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.frontend import (
    Diagnostic,
    FrontendError,
    _map_diagnostic_location,
    compile_path,
    compile_source,
    format_token,
    read_source,
)
from xcc.lexer import TokenKind
from xcc.options import FrontendOptions


class FrontendTests(unittest.TestCase):
    def test_compile_source_success(self) -> None:
        result = compile_source("int main(){return 0;}", filename="sample.c")
        self.assertEqual(result.filename, "sample.c")
        self.assertEqual(result.preprocessed_source, "int main(){return 0;}")
        self.assertEqual(result.pp_tokens[-1].kind, TokenKind.EOF)
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
        source = "#define SUM(a, b) \\\n  ((a) + (b))\nint main(void){return 0;}\n"
        result = compile_source(source, filename="pp.c")
        self.assertEqual(result.unit.functions[0].name, "main")

    def test_compile_source_expands_object_like_preprocessor_define(self) -> None:
        source = (
            "#define SOME_ADDR (unsigned long long)0\nint *p = 0;\nvoid f(void){p = SOME_ADDR;}\n"
        )
        result = compile_source(source, filename="pp.c")
        self.assertEqual(result.unit.functions[0].name, "f")

    def test_compile_source_expands_command_line_define(self) -> None:
        result = compile_source(
            "int main(void){return ZERO;}\n",
            filename="pp.c",
            options=FrontendOptions(defines=("ZERO=0",)),
        )
        self.assertEqual(result.unit.functions[0].name, "main")

    def test_compile_source_cli_undef_removes_macro(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source(
                "int main(void){return ZERO;}\n",
                filename="pp.c",
                options=FrontendOptions(defines=("ZERO=0",), undefs=("ZERO",)),
            )
        self.assertEqual(ctx.exception.diagnostic.stage, "sema")
        self.assertEqual(ctx.exception.diagnostic.code, "XCC-SEMA-0001")

    def test_compile_source_function_like_preprocessor_define_expands(self) -> None:
        source = "#define ID(x) x\nint main(void){return ID(1);}\n"
        result = compile_source(source, filename="pp.c")
        self.assertEqual(result.unit.functions[0].name, "main")

    def test_compile_source_tolerates_empty_define_directive(self) -> None:
        source = "#define\nint main(void){return 0;}\n"
        result = compile_source(source, filename="pp.c")
        self.assertEqual(result.unit.functions[0].name, "main")

    def test_compile_source_tolerates_invalid_define_identifier(self) -> None:
        source = "#define 1ZERO 0\nint main(void){return 0;}\n"
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
        result = compile_source(source, filename="asm.c", options=FrontendOptions(std="gnu11"))
        self.assertEqual(result.unit.functions[0].name, "foo")
        self.assertEqual(result.unit.functions[1].name, "f")

    def test_compile_source_accepts_tag_only_record_definition_with_trailing_attributes(
        self,
    ) -> None:
        result = compile_source(
            'struct Tagged { int value; } __attribute__((btf_decl_tag("tag1")));\n',
            filename="attrs.c",
            options=FrontendOptions(std="gnu11"),
        )
        declaration = result.unit.declarations[0]
        self.assertEqual(declaration.type_spec.record_tag, "Tagged")
        self.assertIsNone(declaration.name)

    def test_compile_source_rejects_gnu_asm_in_c11(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source(
                'asm("INST r1, 0");\n', filename="asm.c", options=FrontendOptions(std="c11")
            )
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "pp")
        self.assertEqual(diagnostic.code, "XCC-PP-0105")
        self.assertEqual(diagnostic.message, "GNU asm extension is not allowed in c11")

    def test_compile_source_accepts_statement_expression_in_c11(self) -> None:
        result = compile_source(
            "int main(void){return ({1;});}",
            filename="ok.c",
            options=FrontendOptions(std="c11"),
        )
        self.assertIsNotNone(result.unit)

    def test_compile_source_accepts_computed_goto_in_c11(self) -> None:
        result = compile_source(
            "int main(void){void *target=0; goto *target;}",
            filename="ok.c",
            options=FrontendOptions(std="c11"),
        )
        self.assertIsNotNone(result.unit)

    def test_compile_source_lex_error(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source("@", filename="bad.c")
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "lex")
        self.assertEqual(diagnostic.code, "XCC-LEX-0001")
        self.assertEqual((diagnostic.line, diagnostic.column), (1, 1))
        self.assertEqual(str(ctx.exception), "bad.c:1:1: lex: Unexpected character")

    def test_compile_source_parse_error(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source("int main( {return 0;}", filename="bad.c")
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "parse")
        self.assertEqual(diagnostic.code, "XCC-PARSE-0001")
        self.assertEqual((diagnostic.line, diagnostic.column), (1, 11))

    def test_compile_source_sema_error(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source("int main(){return;}", filename="bad.c")
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "sema")
        self.assertEqual(diagnostic.code, "XCC-SEMA-0001")
        self.assertEqual((diagnostic.line, diagnostic.column), (None, None))
        self.assertEqual(str(ctx.exception), "bad.c: sema: Non-void function must return a value")

    def test_compile_source_alignof_expression_rejected_in_c11(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source(
                "int main(void){int x; return _Alignof(x);}",
                filename="bad.c",
                options=FrontendOptions(std="c11"),
            )
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "parse")
        self.assertEqual(diagnostic.code, "XCC-PARSE-0001")
        self.assertEqual(diagnostic.message, "Invalid alignof operand")

    def test_compile_source_alignof_expression_allowed_in_gnu11(self) -> None:
        result = compile_source(
            "int main(void){int x; return _Alignof(x);}",
            filename="ok.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertEqual(result.unit.functions[0].name, "main")

    def test_compile_source_accepts_builtin_expect_in_default_mode(self) -> None:
        result = compile_source(
            "int f(int x) { if (__builtin_expect(x == 0, 0)) return -1; return x; }",
            filename="ok.c",
        )
        self.assertEqual(result.unit.functions[0].name, "f")

    def test_compile_source_accepts_builtin_unreachable_in_default_mode(self) -> None:
        result = compile_source(
            "int f(int x) { switch(x) { case 0: return 0; default: __builtin_unreachable(); } }",
            filename="ok.c",
        )
        self.assertEqual(result.unit.functions[0].name, "f")

    def test_compile_source_accepts_builtin_float_compare_in_default_mode(self) -> None:
        result = compile_source(
            "int f(double x, long double y) { return __builtin_isgreater(x, y); }",
            filename="ok.c",
        )
        self.assertEqual(result.unit.functions[0].name, "f")

    def test_compile_source_preprocessor_error(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source("#if 1 +\nint main(void){return 0;}\n", filename="bad.c")
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "pp")
        self.assertEqual(diagnostic.code, "XCC-PP-0103")
        self.assertEqual((diagnostic.line, diagnostic.column), (1, 1))

    def test_compile_source_preprocessor_error_without_location(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source(
                "int main(void){return 0;}\n",
                filename="bad.c",
                options=FrontendOptions(defines=("1BAD=0",)),
            )
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "pp")
        self.assertEqual(diagnostic.code, "XCC-PP-0201")
        self.assertEqual((diagnostic.line, diagnostic.column), (None, None))

    def test_compile_source_lex_error_uses_line_mapping(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source('#line 42 "mapped.c"\n@\n', filename="bad.c")
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "lex")
        self.assertEqual(
            (diagnostic.filename, diagnostic.line, diagnostic.column), ("mapped.c", 42, 1)
        )

    def test_compile_source_parse_error_uses_line_mapping(self) -> None:
        with self.assertRaises(FrontendError) as ctx:
            compile_source('#line 42 "mapped.c"\nint main( {return 0;}\n', filename="bad.c")
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic.stage, "parse")
        self.assertEqual((diagnostic.filename, diagnostic.line), ("mapped.c", 42))

    def test_compile_source_exposes_include_trace_and_macro_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text("int x;\n", encoding="utf-8")
            source = '#define A 1\n#include "inc.h"\nint main(void){return x;}\n'
            result = compile_source(source, filename=str(root / "main.c"))
        self.assertEqual(len(result.include_trace), 1)
        self.assertIn("main.c:2: #include", result.include_trace[0])
        self.assertIn("A=1", result.macro_table)

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
        diagnostic = Diagnostic("pp", "bad.c", "oops", code="XCC-PP-0001")
        self.assertEqual(diagnostic.code, "XCC-PP-0001")

    def test_map_diagnostic_location_fallback_paths(self) -> None:
        self.assertEqual(
            _map_diagnostic_location((("mapped.c", 1),), None, None),
            (None, None, None),
        )
        self.assertEqual(
            _map_diagnostic_location((("mapped.c", 1),), 2, 3),
            (None, 2, 3),
        )

    def test_format_token(self) -> None:
        result = compile_source("int main(){return 0;}")
        self.assertEqual(format_token(result.tokens[0]), "1:1\tKEYWORD\tint")
        self.assertEqual(format_token(result.tokens[-1]), "1:22\tEOF")

    def test_printf_format_int_mismatch(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%zu", (double)42); }'
        with self.assertRaises(FrontendError) as ctx:
            compile_source(source)
        self.assertEqual(ctx.exception.diagnostic.stage, "sema")
        self.assertIn("format specifies type", ctx.exception.diagnostic.message)
        self.assertIn("double", ctx.exception.diagnostic.message)

    def test_printf_format_int_valid(self) -> None:
        source = (
            "int printf(const char *, ...);"
            "typedef unsigned long size_t;"
            "void f(void) { printf(\"%zu\", (size_t)0); }"
        )
        compile_source(source)

    def test_printf_format_float_mismatch(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%f", (int)42); }'
        with self.assertRaises(FrontendError) as ctx:
            compile_source(source)
        self.assertEqual(ctx.exception.diagnostic.stage, "sema")
        self.assertIn("floating-point", ctx.exception.diagnostic.message)

    def test_printf_format_float_valid(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%f", 3.14); }'
        compile_source(source)

    def test_printf_format_char_valid(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%c", 65); }'
        compile_source(source)

    def test_printf_format_char_mismatch(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%c", 3.14); }'
        with self.assertRaises(FrontendError) as ctx:
            compile_source(source)
        self.assertIn("integer", ctx.exception.diagnostic.message)

    def test_printf_format_string_valid(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%s", "hello"); }'
        compile_source(source)

    def test_printf_format_string_mismatch(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%s", 42); }'
        with self.assertRaises(FrontendError) as ctx:
            compile_source(source)
        self.assertIn("pointer to char", ctx.exception.diagnostic.message)

    def test_printf_format_pointer_valid(self) -> None:
        source = 'int printf(const char *, ...); void f(int *p) { printf("%p", (void*)0); }'
        compile_source(source)

    def test_printf_format_pointer_mismatch(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%p", 42); }'
        with self.assertRaises(FrontendError) as ctx:
            compile_source(source)
        self.assertIn("pointer", ctx.exception.diagnostic.message)

    def test_printf_format_writeback_valid(self) -> None:
        source = 'int printf(const char *, ...); void f(int *p) { printf("%n", p); }'
        compile_source(source)

    def test_printf_format_writeback_mismatch(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%n", 42); }'
        with self.assertRaises(FrontendError) as ctx:
            compile_source(source)
        self.assertIn("pointer to integer", ctx.exception.diagnostic.message)

    def test_printf_format_all_specs_valid(self) -> None:
        source = (
            "int printf(const char *, ...);"
            "typedef unsigned long size_t;"
            "void f(int *p, double d, char *s) {"
            "  printf(\"%d %i %u %o %x %f %e %g %a %c %s %p %n %zu %jd %ju %td\","
            "         1, 2, 3U, 4, 5, d, d, d, d, 'x', s, (void*)0, p, (size_t)0,"
            "         1L, 2UL, 3L);"
            "}"
        )
        compile_source(source)

    def test_printf_non_literal_format_skips_check(self) -> None:
        source = 'int printf(const char *, ...); void f(const char *fmt) { printf(fmt, 42); }'
        compile_source(source)

    def test_printf_percent_escape(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%% no args"); }'
        compile_source(source)

    def test_printf_format_with_flags_width_precision_length(self) -> None:
        source = (
            "int printf(const char *, ...);"
            "void f(int i, double d) {"
            "  printf(\"%-5d %+d % d %#x %04d %5d %.5f %hd %ld %lld %Lf\","
            "         i, i, i, i, i, i, d, (short)i, 1L, 2LL, (long double)d);"
            "}"
        )
        compile_source(source)

    def test_printf_format_trailing_percent(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("trailing %"); }'
        compile_source(source)

    def test_printf_format_precision_star(self) -> None:
        source = 'int printf(const char *, ...); void f(int w, int p, double d) { printf("%*.*f", w, p, d); }'
        compile_source(source)

    def test_printf_format_ll_length(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%lld", 1LL); }'
        compile_source(source)

    def test_printf_format_L_length(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%Lf", 1.0L); }'
        compile_source(source)

    def test_printf_format_string_wrong_pointee(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%s", (int*)0); }'
        with self.assertRaises(FrontendError) as ctx:
            compile_source(source)
        self.assertIn("pointer to char", ctx.exception.diagnostic.message)

    def test_printf_format_more_specs_than_args(self) -> None:
        source = 'int printf(const char *, ...); void f(void) { printf("%d %d", 1); }'
        compile_source(source)

    def test_printf_every_parser_feature(self) -> None:
        source = (
            "int printf(const char *, ...);"
            "void f(int i, char *s, double d) {"
            "  printf(\"%% %-5d %+d % d %#x %04d %5d %.5f %hd %ld %lld %Lf %hhx %hhd %c %s %p %n\","
            "         i, i, i, i, i, i, d, (short)i, 1L, 2LL, (long double)d, (char)i, (char)i, 'x', s, (void*)0, &i);"
            "}"
        )
        compile_source(source)


if __name__ == "__main__":
    unittest.main()
