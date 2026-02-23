import ast
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc.options import FrontendOptions
from xcc.preprocessor import (
    PreprocessorError,
    _Preprocessor,
    _DirectiveCursor,
    _LineMapBuilder,
    _LogicalCursor,
    _SourceLocation,
    _blank_line,
    _eval_node,
    _eval_pp_node,
    _expand_object_like_macros,
    _is_unsigned_pp_integer,
    _parse_macro_parameters,
    _parse_pp_integer_literal,
    _parse_directive,
    _paste_token_pair,
    _safe_eval_pp_expr,
    _safe_eval_int_expr,
    _strip_gnu_asm_extensions,
    _tokenize_macro_replacement,
    _tokenize_expr,
    _translate_expr_to_python,
    preprocess_source,
)


class PreprocessorTests(unittest.TestCase):
    def test_preprocess_empty_source(self) -> None:
        result = preprocess_source("", filename="empty.c")
        self.assertEqual(result.source, "")

    def test_expand_line_without_macros_short_circuits(self) -> None:
        processor = _Preprocessor(FrontendOptions())
        processor._macros.clear()
        location = _SourceLocation("main.c", 1)
        self.assertEqual(processor._expand_line("int x;\n", location), "int x;\n")

    def test_object_like_define_expands(self) -> None:
        source = "#define ZERO 0\nint main(void){return ZERO;}\n"
        result = preprocess_source(source, filename="main.c")
        self.assertEqual(result.source, "\nint main ( void ) { return 0 ; }\n")

    def test_function_like_define_expands(self) -> None:
        source = "#define ID(x) x\nint main(void){return ID(1);}\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("return 1", result.source)

    def test_function_like_define_with_nested_parentheses(self) -> None:
        source = "#define ID(x) x\nint main(void){return ID((1 + 2));}\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("return ( 1 + 2 )", result.source)

    def test_function_like_define_without_invocation_is_not_expanded(self) -> None:
        source = "#define ID(x) x\nint x = ID;\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("int x = ID ;", result.source)

    def test_variadic_macro_expands(self) -> None:
        source = '#define LOG(fmt, ...) printf(fmt, __VA_ARGS__)\nLOG("%d", 1)\n'
        result = preprocess_source(source, filename="main.c")
        self.assertIn('printf ( "%d" , 1 )', result.source)

    def test_variadic_macro_insufficient_arguments(self) -> None:
        source = '#define LOG(fmt, ...) printf(fmt, __VA_ARGS__)\nLOG()\n'
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="main.c")

    def test_variadic_macro_with_gnu_comma_swallow(self) -> None:
        source = '#define LOG(fmt, ...) printf(fmt, ##__VA_ARGS__)\nLOG("x")\n'
        c11_result = preprocess_source(source, filename="main.c")
        self.assertIn('printf ( "x" , )', c11_result.source)
        gnu11_result = preprocess_source(
            source,
            filename="main.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertIn('printf ( "x" )', gnu11_result.source)

    def test_variadic_macro_empty_argument_without_paste(self) -> None:
        source = "#define V(...) __VA_ARGS__\nV()\n"
        result = preprocess_source(source, filename="main.c")
        self.assertEqual(result.source, "\n\n")

    def test_variadic_macro_multiple_arguments_keep_commas(self) -> None:
        source = "#define V(...) __VA_ARGS__\nV(1, 2, 3)\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("1 , 2 , 3", result.source)

    def test_macro_stringize(self) -> None:
        source = "#define STR(x) #x\nconst char *s = STR(hello world);\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn('"hello world"', result.source)

    def test_macro_token_paste(self) -> None:
        source = "#define CAT(a, b) a##b\nint hello = 1;\nint x = CAT(he, llo);\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("int x = hello", result.source)

    def test_macro_token_paste_with_empty_left_argument(self) -> None:
        source = "#define CAT(a, b) a##b\nCAT(, tail)\n"
        result = preprocess_source(source, filename="main.c")
        self.assertEqual(result.source, "\ntail\n")

    def test_macro_token_paste_with_two_empty_arguments(self) -> None:
        source = "#define CAT(a, b) a##b\nCAT(,)\n"
        result = preprocess_source(source, filename="main.c")
        self.assertEqual(result.source, "\n\n")

    def test_macro_hash_without_parameter_target(self) -> None:
        source = "#define SHOW(x) #y\nSHOW(1)\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("# y", result.source)

    def test_macro_recursion_is_suppressed(self) -> None:
        source = "#define A B\n#define B A\nint x = A;\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("int x = A", result.source)

    def test_macro_argument_count_mismatch(self) -> None:
        source = "#define ID(x) x\nID()\n"
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="main.c")

    def test_unterminated_macro_invocation(self) -> None:
        source = "#define ID(x) x\nID(\n"
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="main.c")

    def test_invalid_token_paste(self) -> None:
        source = "#define BAD(x) ##x\nBAD(1)\n"
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="main.c")

    def test_invalid_token_paste_result(self) -> None:
        source = "#define BAD(x) x##+\nBAD(1)\n"
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="main.c")

    def test_malformed_function_like_define_is_ignored(self) -> None:
        source = "#define BAD(x\nBAD(1)\n"
        result = preprocess_source(source, filename="main.c")
        self.assertEqual(result.source, "\nBAD(1)\n")

    def test_invalid_function_like_define_parameter_list_is_ignored(self) -> None:
        source = "#define BAD(x, ..., y) x\nBAD(1, 2, 3)\n"
        result = preprocess_source(source, filename="main.c")
        self.assertEqual(result.source, "\nBAD(1, 2, 3)\n")

    def test_undef_removes_macro(self) -> None:
        source = "#define ZERO 0\n#undef ZERO\nint main(void){return ZERO;}\n"
        result = preprocess_source(source, filename="main.c")
        self.assertEqual(result.source, "\n\nint main(void){return ZERO;}\n")

    def test_cli_defines_and_undefs(self) -> None:
        source = "int main(void){return ZERO;}\n"
        options = FrontendOptions(defines=("ZERO=0",), undefs=("ZERO",))
        result = preprocess_source(source, filename="main.c", options=options)
        self.assertIn("ZERO", result.source)

    def test_invalid_cli_define(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("int x;\n", options=FrontendOptions(defines=("1BAD=0",)))
        self.assertEqual(ctx.exception.code, "XCC-PP-0201")

    def test_invalid_cli_undef(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("int x;\n", options=FrontendOptions(undefs=("1BAD",)))
        self.assertEqual(ctx.exception.code, "XCC-PP-0201")

    def test_cli_define_without_value_defaults_to_one(self) -> None:
        result = preprocess_source(
            "int main(void){return ONE;}\n",
            filename="main.c",
            options=FrontendOptions(defines=("ONE",)),
        )
        self.assertIn("return 1 ;", result.source)

    def test_predefined_integer_width_macros(self) -> None:
        source = "#if __INT_WIDTH__ == 32 && __LONG_WIDTH__ > 32\nint x;\n#endif\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("int x;", result.source)

    def test_cli_undef_removes_predefined_macro(self) -> None:
        source = "#if __INT_WIDTH__\nint x;\n#endif\n#if __STDC_UTF_16__\nint y;\n#endif\n"
        result = preprocess_source(
            source,
            filename="main.c",
            options=FrontendOptions(undefs=("__INT_WIDTH__", "__STDC_UTF_16__")),
        )
        self.assertNotIn("int x;", result.source)
        self.assertNotIn("int y;", result.source)

    def test_ifdef_and_ifndef(self) -> None:
        source = (
            "#define FLAG 1\n"
            "#ifdef FLAG\n"
            "int a;\n"
            "#endif\n"
            "#ifndef FLAG\n"
            "int b;\n"
            "#endif\n"
        )
        result = preprocess_source(source, filename="if.c")
        self.assertIn("int a ;", result.source)
        self.assertNotIn("int b;", result.source)

    def test_if_elif_else(self) -> None:
        source = (
            "#if 0\n"
            "int a;\n"
            "#elif 2 > 1\n"
            "int b;\n"
            "#else\n"
            "int c;\n"
            "#endif\n"
        )
        result = preprocess_source(source, filename="if.c")
        self.assertNotIn("int a;", result.source)
        self.assertIn("int b;", result.source)
        self.assertNotIn("int c;", result.source)

    def test_nested_conditionals(self) -> None:
        source = "#if 1\n#if 0\nint a;\n#endif\n#endif\n"
        result = preprocess_source(source, filename="if.c")
        self.assertNotIn("int a;", result.source)

    def test_elif_skipped_after_taken_branch(self) -> None:
        source = "#if 1\nint a;\n#elif 1\nint b;\n#endif\n"
        result = preprocess_source(source, filename="if.c")
        self.assertIn("int a;", result.source)
        self.assertNotIn("int b;", result.source)

    def test_unexpected_endif(self) -> None:
        with self.assertRaises(PreprocessorError):
            preprocess_source("#endif\n", filename="if.c")

    def test_elif_after_else(self) -> None:
        source = "#if 0\n#elif 0\n#else\n#elif 1\n#endif\n"
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="if.c")

    def test_duplicate_else(self) -> None:
        source = "#if 0\n#else\n#else\n#endif\n"
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="if.c")

    def test_unterminated_conditional(self) -> None:
        with self.assertRaises(PreprocessorError):
            preprocess_source("#if 1\nint a;\n", filename="if.c")

    def test_invalid_macro_name_in_ifdef(self) -> None:
        with self.assertRaises(PreprocessorError):
            preprocess_source("#ifdef 1\n#endif\n", filename="if.c")

    def test_invalid_if_expression(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if 1 +\nint x;\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertEqual((ctx.exception.filename, ctx.exception.line), ("if.c", 1))

    def test_if_expression_short_circuits_boolean_operators(self) -> None:
        result = preprocess_source(
            "#if 0 && (1 / 0)\nint bad;\n#elif 1 || (1 / 0)\nint ok;\n#endif\n",
            filename="if.c",
        )
        self.assertNotIn("int bad;", result.source)
        self.assertIn("int ok;", result.source)

    def test_if_expression_with_trailing_comment(self) -> None:
        result = preprocess_source("#if 1 // keep\nint x;\n#endif\n", filename="if.c")
        self.assertIn("int x;", result.source)

    def test_if_expression_with_block_comment(self) -> None:
        result = preprocess_source("#if 1 /* keep */\nint x;\n#endif\n", filename="if.c")
        self.assertIn("int x;", result.source)

    def test_if_expression_with_has_include_quoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "present.h").write_text("int x;\n", encoding="utf-8")
            source_path = root / "main.c"
            source_path.write_text(
                "#if __has_include(\"present.h\")\nint ok;\n#endif\n",
                encoding="utf-8",
            )
            source = source_path.read_text(encoding="utf-8")
            result = preprocess_source(source, filename=str(source_path))
        self.assertIn("int ok;", result.source)

    def test_if_expression_with_has_include_angle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include = root / "include"
            include.mkdir()
            (include / "present.h").write_text("int x;\n", encoding="utf-8")
            options = FrontendOptions(include_dirs=(str(include),))
            result = preprocess_source(
                "#if __has_include(<present.h>)\nint ok;\n#endif\n",
                filename="main.c",
                options=options,
            )
        self.assertIn("int ok;", result.source)

    def test_if_expression_with_has_include_missing(self) -> None:
        result = preprocess_source(
            "#if __has_include(\"missing.h\")\nint bad;\n#endif\n",
            filename="main.c",
        )
        self.assertNotIn("int bad;", result.source)

    def test_if_expression_with_has_include_invalid_form(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if __has_include(MISSING)\nint x;\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")

    def test_unknown_directive_active_errors_in_c11(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#unknown\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0101")
        self.assertEqual((ctx.exception.filename, ctx.exception.line), ("if.c", 1))

    def test_unknown_directive_active_is_ignored_in_gnu11(self) -> None:
        result = preprocess_source(
            "#unknown\n",
            filename="if.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertEqual(result.source, "\n")

    def test_unknown_directive_in_inactive_branch(self) -> None:
        result = preprocess_source("#if 0\n#unknown\n#endif\n", filename="if.c")
        self.assertEqual(result.source, "\n\n\n")

    def test_error_directive(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#error fail\n", filename="if.c")
        self.assertIn("fail", str(ctx.exception))

    def test_error_directive_in_inactive_branch(self) -> None:
        result = preprocess_source("#if 0\n#error fail\n#endif\n", filename="if.c")
        self.assertEqual(result.source, "\n\n\n")

    def test_pragma_and_line_directives(self) -> None:
        result = preprocess_source("#pragma once\n#line 42\nint x;\n", filename="if.c")
        self.assertEqual(result.source, "\n\nint x;\n")

    def test_include_quoted_from_source_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text("int x;\n", encoding="utf-8")
            source_path = root / "main.c"
            source_path.write_text('#include "inc.h"\n', encoding="utf-8")
            source = source_path.read_text(encoding="utf-8")
            result = preprocess_source(source, filename=str(source_path))
        self.assertEqual(result.source, "int x;\n")

    def test_include_angle_from_include_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include = root / "include"
            include.mkdir()
            (include / "inc.h").write_text("int y;\n", encoding="utf-8")
            options = FrontendOptions(include_dirs=(str(include),))
            result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int y;\n")

    def test_include_from_system_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include = root / "sys"
            include.mkdir()
            (include / "inc.h").write_text("int z;\n", encoding="utf-8")
            options = FrontendOptions(system_include_dirs=(str(include),))
            result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int z;\n")

    def test_include_quoted_prefers_source_directory_over_include_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            include_dir = root / "include"
            source_dir.mkdir()
            include_dir.mkdir()
            (source_dir / "inc.h").write_text("int from_source;\n", encoding="utf-8")
            (include_dir / "inc.h").write_text("int from_include;\n", encoding="utf-8")
            main = source_dir / "main.c"
            main.write_text('#include "inc.h"\n', encoding="utf-8")
            options = FrontendOptions(include_dirs=(str(include_dir),))
            result = preprocess_source(main.read_text(encoding="utf-8"), filename=str(main), options=options)
        self.assertEqual(result.source, "int from_source;\n")

    def test_include_angle_skips_source_directory_and_uses_include_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            include_dir = root / "include"
            source_dir.mkdir()
            include_dir.mkdir()
            (source_dir / "inc.h").write_text("int from_source;\n", encoding="utf-8")
            (include_dir / "inc.h").write_text("int from_include;\n", encoding="utf-8")
            main = source_dir / "main.c"
            options = FrontendOptions(include_dirs=(str(include_dir),))
            result = preprocess_source("#include <inc.h>\n", filename=str(main), options=options)
        self.assertEqual(result.source, "int from_include;\n")

    def test_include_expansion_preserves_line_map_for_header_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include = root / "inc.h"
            main = root / "main.c"
            include.write_text("int from_header;\n", encoding="utf-8")
            result = preprocess_source('#include "inc.h"\nint from_main;\n', filename=str(main))
        self.assertEqual(result.line_map, ((str(include.resolve()), 1), (str(main), 2)))

    def test_include_not_found(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source('#include "missing.h"\n', filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual((ctx.exception.filename, ctx.exception.line), ("main.c", 1))
        self.assertEqual(ctx.exception.args[0], 'Include not found: "missing.h" at main.c:1:1')

    def test_include_not_found_for_angle_include_reports_delimiters(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#include <missing.h>\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual(ctx.exception.args[0], "Include not found: <missing.h> at main.c:1:1")

    def test_invalid_include_directive(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#include bad\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")

    def test_circular_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.h").write_text('#include "b.h"\n', encoding="utf-8")
            (root / "b.h").write_text('#include "a.h"\n', encoding="utf-8")
            source = '#include "a.h"\n'
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source(source, filename=str(root / "main.c"))
            self.assertEqual(ctx.exception.code, "XCC-PP-0302")

    def test_include_read_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_path = root / "inc.h"
            include_path.write_text("int x;\n", encoding="utf-8")
            source = '#include "inc.h"\n'
            with patch("pathlib.Path.read_text", side_effect=OSError("boom")):
                with self.assertRaises(PreprocessorError) as ctx:
                    preprocess_source(source, filename=str(root / "main.c"))
        self.assertEqual(ctx.exception.code, "XCC-PP-0301")
        self.assertEqual(ctx.exception.filename, str(root / "main.c"))

    def test_line_directive_updates_mappings(self) -> None:
        result = preprocess_source('#line 42 "mapped.c"\nint x;\n', filename="main.c")
        self.assertEqual(result.source, "\nint x;\n")
        self.assertEqual(result.line_map[-1], ("mapped.c", 42))

    def test_line_directive_invalid(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#line nope\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")

    def test_line_directive_requires_positive_line(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#line 0\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")

    def test_predefined_standard_macros(self) -> None:
        result = preprocess_source(
            "int s = __STDC__;\n"
            "int h = __STDC_HOSTED__;\n"
            "long v = __STDC_VERSION__;\n"
            "int u16 = __STDC_UTF_16__;\n"
            "int u32 = __STDC_UTF_32__;\n",
            filename="main.c",
        )
        self.assertIn("int s = 1 ;", result.source)
        self.assertIn("int h = 1 ;", result.source)
        self.assertIn("long v = 201112L ;", result.source)
        self.assertIn("int u16 = 1 ;", result.source)
        self.assertIn("int u32 = 1 ;", result.source)

    def test_predefined_file_and_line_macros(self) -> None:
        result = preprocess_source(
            'const char *f = __FILE__;\nint l = __LINE__;\n#line 42 "mapped.c"\nint m = __LINE__;\n',
            filename="main.c",
        )
        self.assertIn('const char * f = "main.c" ;', result.source)
        self.assertIn("int l = 2 ;", result.source)
        self.assertIn("int m = 42 ;", result.source)
        self.assertEqual(result.line_map[-1], ("mapped.c", 42))

    def test_predefined_date_and_time_macros_use_translation_start_time(self) -> None:
        with patch("xcc.preprocessor.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 2, 23, 22, 21, 9)
            result = preprocess_source(
                'const char *d = __DATE__;\nconst char *t = __TIME__;\n',
                filename="main.c",
            )
        self.assertIn('const char * d = "Feb 23 2026" ;', result.source)
        self.assertIn('const char * t = "22:21:09" ;', result.source)
        self.assertIn('__DATE__="Feb 23 2026"', result.macro_table)
        self.assertIn('__TIME__="22:21:09"', result.macro_table)

    def test_predefined_date_and_time_do_not_force_retokenization(self) -> None:
        result = preprocess_source("int keep;\n", filename="main.c")
        self.assertEqual(result.source, "int keep;\n")

    def test_c11_rejects_gnu_asm_extensions(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source('asm("inst");\n', filename="main.c", options=FrontendOptions(std="c11"))
        self.assertEqual(ctx.exception.code, "XCC-PP-0105")
        self.assertEqual(str(ctx.exception), "GNU asm extension is not allowed in c11 at main.c:1:1")

    def test_include_trace_and_macro_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text("int x;\n", encoding="utf-8")
            source = '#define A 1\n#include "inc.h"\n'
            result = preprocess_source(source, filename=str(root / "main.c"))
        self.assertEqual(len(result.include_trace), 1)
        self.assertIn("main.c:2: #include", result.include_trace[0])
        self.assertIn("A=1", result.macro_table)

    def test_translate_expr_to_python_and_tokenizer(self) -> None:
        self.assertEqual(_translate_expr_to_python("A && !B || 1 / 2"), "0 and not 0 or 1 // 2")
        self.assertEqual(_translate_expr_to_python("1UL + 0x10LL"), "u64(1) + 16")
        self.assertEqual(_translate_expr_to_python("__has_extension(x)"), "0")
        self.assertEqual(_tokenize_expr("0x10 + 1"), ["0x10", "+", "1"])
        with self.assertRaises(ValueError):
            _tokenize_expr("@")
        with self.assertRaises(ValueError):
            _translate_expr_to_python("f((1)")
        self.assertIsNone(_parse_pp_integer_literal("09"))
        self.assertEqual(_parse_pp_integer_literal("010"), 8)
        self.assertFalse(_is_unsigned_pp_integer("x"))

    def test_safe_eval_int_expr_operators(self) -> None:
        self.assertEqual(_safe_eval_int_expr("1 + 2 * 3"), 7)
        self.assertEqual(_safe_eval_int_expr("3 - 1"), 2)
        self.assertEqual(_safe_eval_int_expr("8 // 2"), 4)
        self.assertEqual(_safe_eval_int_expr("5 % 2"), 1)
        self.assertEqual(_safe_eval_int_expr("1 << 3"), 8)
        self.assertEqual(_safe_eval_int_expr("8 >> 2"), 2)
        self.assertEqual(_safe_eval_int_expr("1 | 2"), 3)
        self.assertEqual(_safe_eval_int_expr("3 & 1"), 1)
        self.assertEqual(_safe_eval_int_expr("3 ^ 1"), 2)
        self.assertEqual(_safe_eval_int_expr("1 and 0"), 0)
        self.assertEqual(_safe_eval_int_expr("1 or 0"), 1)
        self.assertEqual(_safe_eval_int_expr("0 and (1 // 0)"), 0)
        self.assertEqual(_safe_eval_int_expr("1 or (1 // 0)"), 1)
        self.assertEqual(_safe_eval_int_expr("not 0"), 1)
        self.assertEqual(_safe_eval_int_expr("~1"), -2)
        self.assertEqual(_safe_eval_int_expr("-1"), -1)
        self.assertEqual(_safe_eval_int_expr("+1"), 1)
        self.assertEqual(_safe_eval_int_expr("1 == 1"), 1)
        self.assertEqual(_safe_eval_int_expr("1 != 2"), 1)
        self.assertEqual(_safe_eval_int_expr("1 < 2"), 1)
        self.assertEqual(_safe_eval_int_expr("1 <= 1"), 1)
        self.assertEqual(_safe_eval_int_expr("2 > 1"), 1)
        self.assertEqual(_safe_eval_int_expr("2 >= 2"), 1)

    def test_safe_eval_int_expr_errors(self) -> None:
        with self.assertRaises(ValueError):
            _safe_eval_int_expr("(")
        with self.assertRaises(ValueError):
            _safe_eval_int_expr('"x"')
        with self.assertRaises(ValueError):
            _safe_eval_int_expr("1 < 2 < 3")
        with self.assertRaises(ValueError):
            _safe_eval_int_expr("1 ** 2")
        with self.assertRaises(ValueError):
            _safe_eval_int_expr("1 if 1 else 0")

    def test_safe_eval_pp_expr(self) -> None:
        self.assertEqual(_safe_eval_pp_expr("u64(18446744073709551615) + u64(1)"), 0)
        self.assertEqual(_safe_eval_pp_expr("u64(0) - u64(1)"), 18446744073709551615)
        self.assertEqual(_safe_eval_pp_expr("u64(1) != 0"), 1)
        self.assertEqual(_safe_eval_pp_expr("u64(1) and 0"), 0)
        self.assertEqual(_safe_eval_pp_expr("0 and (u64(1) // 0)"), 0)
        self.assertEqual(_safe_eval_pp_expr("1 or (u64(1) // 0)"), 1)
        self.assertEqual(_safe_eval_pp_expr("True"), 1)
        self.assertEqual(_safe_eval_pp_expr("+u64(1)"), 1)
        self.assertEqual(_safe_eval_pp_expr("~u64(0)"), 18446744073709551615)
        self.assertEqual(_safe_eval_pp_expr("0 or 1"), 1)
        self.assertEqual(_safe_eval_pp_expr("u64(2) * 3"), 6)
        self.assertEqual(_safe_eval_pp_expr("u64(5) % 3"), 2)
        self.assertEqual(_safe_eval_pp_expr("u64(1) << 3"), 8)
        self.assertEqual(_safe_eval_pp_expr("u64(8) >> 1"), 4)
        self.assertEqual(_safe_eval_pp_expr("u64(1) | 2"), 3)
        self.assertEqual(_safe_eval_pp_expr("u64(3) & 1"), 1)
        self.assertEqual(_safe_eval_pp_expr("u64(3) ^ 1"), 2)
        self.assertEqual(_safe_eval_pp_expr("u64(1) <= 2"), 1)
        self.assertEqual(_safe_eval_pp_expr("u64(2) >= 2"), 1)
        with self.assertRaises(ValueError):
            _safe_eval_pp_expr("u64(1, 2)")
        with self.assertRaises(ValueError):
            _safe_eval_pp_expr("1 // 0")
        with self.assertRaises(ValueError):
            _safe_eval_pp_expr('"x"')

    def test_eval_pp_node_unsupported_branches(self) -> None:
        unsupported_unary = ast.UnaryOp(op=ast.MatMult(), operand=ast.Constant(1))
        with self.assertRaises(ValueError) as ctx:
            _eval_pp_node(unsupported_unary)
        self.assertEqual(str(ctx.exception), "Unsupported preprocessor unary operator: MatMult")
        unsupported_bool = ast.BoolOp(op=ast.BitAnd(), values=[ast.Constant(1), ast.Constant(1)])
        with self.assertRaises(ValueError) as ctx:
            _eval_pp_node(unsupported_bool)
        self.assertEqual(str(ctx.exception), "Unsupported preprocessor boolean operator: BitAnd")
        unsupported_bin = ast.BinOp(left=ast.Constant(1), op=ast.Pow(), right=ast.Constant(1))
        with self.assertRaises(ValueError) as ctx:
            _eval_pp_node(unsupported_bin)
        self.assertEqual(str(ctx.exception), "Unsupported preprocessor binary operator: Pow")
        unsupported_chain = ast.Compare(
            left=ast.Constant(1),
            ops=[ast.Lt(), ast.Lt()],
            comparators=[ast.Constant(2), ast.Constant(3)],
        )
        with self.assertRaises(ValueError) as ctx:
            _eval_pp_node(unsupported_chain)
        self.assertEqual(
            str(ctx.exception),
            "Unsupported preprocessor comparison shape: expected 1 operator, got 2",
        )
        unsupported_comparator_shape = ast.Compare(
            left=ast.Constant(1),
            ops=[ast.Lt()],
            comparators=[ast.Constant(2), ast.Constant(3)],
        )
        with self.assertRaises(ValueError) as ctx:
            _eval_pp_node(unsupported_comparator_shape)
        self.assertEqual(
            str(ctx.exception),
            "Unsupported preprocessor comparison shape: expected 1 comparator, got 2",
        )
        unsupported_cmp = ast.Compare(left=ast.Constant(1), ops=[ast.Is()], comparators=[ast.Constant(1)])
        with self.assertRaises(ValueError) as ctx:
            _eval_pp_node(unsupported_cmp)
        self.assertEqual(str(ctx.exception), "Unsupported preprocessor comparison operator: Is")
        unsupported_literal = ast.Constant("x")
        with self.assertRaises(ValueError) as ctx:
            _eval_pp_node(unsupported_literal)
        self.assertEqual(str(ctx.exception), "Unsupported preprocessor literal type: str")
        unsupported_expr = ast.IfExp(
            test=ast.Constant(True),
            body=ast.Constant(1),
            orelse=ast.Constant(0),
        )
        with self.assertRaises(ValueError) as ctx:
            _eval_pp_node(unsupported_expr)
        self.assertEqual(str(ctx.exception), "Unsupported preprocessor expression node: IfExp")

    def test_eval_node_unsupported_branches(self) -> None:
        self.assertEqual(_eval_node(ast.Constant(True)), 1)
        unsupported_unary = ast.UnaryOp(op=ast.MatMult(), operand=ast.Constant(1))
        with self.assertRaises(ValueError) as ctx:
            _eval_node(unsupported_unary)
        self.assertEqual(str(ctx.exception), "Unsupported integer-expression unary operator: MatMult")
        unsupported_bool = ast.BoolOp(op=ast.BitAnd(), values=[ast.Constant(1), ast.Constant(1)])
        with self.assertRaises(ValueError) as ctx:
            _eval_node(unsupported_bool)
        self.assertEqual(str(ctx.exception), "Unsupported integer-expression boolean operator: BitAnd")
        unsupported_bin = ast.BinOp(left=ast.Constant(1), op=ast.Pow(), right=ast.Constant(1))
        with self.assertRaises(ValueError) as ctx:
            _eval_node(unsupported_bin)
        self.assertEqual(str(ctx.exception), "Unsupported integer-expression binary operator: Pow")
        unsupported_chain = ast.Compare(
            left=ast.Constant(1),
            ops=[ast.Lt(), ast.Lt()],
            comparators=[ast.Constant(2), ast.Constant(3)],
        )
        with self.assertRaises(ValueError) as ctx:
            _eval_node(unsupported_chain)
        self.assertEqual(
            str(ctx.exception),
            "Unsupported integer-expression comparison shape: expected 1 operator, got 2",
        )
        unsupported_comparator_shape = ast.Compare(
            left=ast.Constant(1),
            ops=[ast.Lt()],
            comparators=[ast.Constant(2), ast.Constant(3)],
        )
        with self.assertRaises(ValueError) as ctx:
            _eval_node(unsupported_comparator_shape)
        self.assertEqual(
            str(ctx.exception),
            "Unsupported integer-expression comparison shape: expected 1 comparator, got 2",
        )
        unsupported_cmp = ast.Compare(left=ast.Constant(1), ops=[ast.Is()], comparators=[ast.Constant(1)])
        with self.assertRaises(ValueError) as ctx:
            _eval_node(unsupported_cmp)
        self.assertEqual(str(ctx.exception), "Unsupported integer-expression comparison operator: Is")
        unsupported_literal = ast.Constant("x")
        with self.assertRaises(ValueError) as ctx:
            _eval_node(unsupported_literal)
        self.assertEqual(str(ctx.exception), "Unsupported integer-expression literal type: str")

    def test_helpers(self) -> None:
        self.assertEqual(_blank_line("abc\n"), "\n")
        self.assertEqual(_blank_line("abc"), "")
        self.assertEqual(_parse_directive("int x;\n"), None)
        self.assertEqual(_parse_directive("#define X 1\n"), ("define", " X 1"))
        self.assertEqual(_tokenize_macro_replacement(""), [])
        self.assertEqual(_expand_object_like_macros("A B", {"A": "1", "B": "2"}), "1 2")
        self.assertEqual(_expand_object_like_macros("A B", {}), "A B")
        self.assertEqual(_parse_macro_parameters(""), ([], False))
        self.assertEqual(_parse_macro_parameters("x, ..."), (["x"], True))
        self.assertIsNone(_parse_macro_parameters("x, ..., y"))
        self.assertIsNone(_parse_macro_parameters("x, x"))
        self.assertEqual(len(_tokenize_macro_replacement("@")), 1)
        with self.assertRaises(PreprocessorError):
            _paste_token_pair(
                _tokenize_macro_replacement("x")[0],
                _tokenize_macro_replacement("+")[0],
                std="c11",
                line_no=1,
            )
        line_map_builder = _LineMapBuilder()
        line_map_builder.append_line("", _SourceLocation("main.c", 1))
        line_map_builder.append_line("x\n", _SourceLocation("main.c", 2))
        self.assertEqual(line_map_builder.build(), (("main.c", 2),))
        cursor = _LogicalCursor("main.c")
        directive_cursor = _DirectiveCursor(cursor, 2)
        self.assertEqual(
            directive_cursor.all_locations(),
            (_SourceLocation("main.c", 1), _SourceLocation("main.c", 2)),
        )

    def test_multiline_include_branch_appends_blank_continuation_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text("int x;\n", encoding="utf-8")
            source = '#include "inc.h"\\\nignored\n'

            real_parse_directive = _parse_directive

            def fake_parse_directive(text: str) -> tuple[str, str] | None:
                if text.startswith('#include "inc.h"'):
                    return ("include", ' "inc.h"')
                return real_parse_directive(text)

            with patch("xcc.preprocessor._parse_directive", side_effect=fake_parse_directive):
                result = preprocess_source(source, filename=str(root / "main.c"))
        self.assertEqual(result.source, "int x;\n\n")

    def test_if_expression_macro_error_is_preserved(self) -> None:
        source = "#define F(x) x\n#if F(\nint x;\n#endif\n"
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(source, filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0201")

    def test_strip_gnu_asm_extensions(self) -> None:
        self.assertEqual(_strip_gnu_asm_extensions(""), "")
        source = (
            'asm("inst");\n'
            'int x __asm("foo") = 0;\n'
            "asm volatile(\n"
            '  "inst"\n'
            ");\n"
        )
        stripped = _strip_gnu_asm_extensions(source)
        self.assertEqual(stripped.splitlines(), ["", "int x  = 0;", "", "", ""])


if __name__ == "__main__":
    unittest.main()
