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

    def test_strict_mode_defines_strict_ansi_macro(self) -> None:
        result = preprocess_source("int strict = __STRICT_ANSI__;\n", filename="main.c")
        self.assertIn("int strict = 1 ;", result.source)

    def test_gnu_mode_defines_gnu_version_macros(self) -> None:
        result = preprocess_source(
            "int g = __GNUC__;\nint gm = __GNUC_MINOR__;\nint gp = __GNUC_PATCHLEVEL__;\n"
            'const char *v = __VERSION__;\n',
            filename="main.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertIn("int g = 4 ;", result.source)
        self.assertIn("int gm = 2 ;", result.source)
        self.assertIn("int gp = 1 ;", result.source)
        self.assertIn('const char * v = "xcc gnu11" ;', result.source)

    def test_gnu_mode_does_not_define_strict_ansi_macro(self) -> None:
        result = preprocess_source(
            "#if defined(__STRICT_ANSI__)\nint strict = 1;\n#endif\n",
            filename="main.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertNotIn("strict", result.source)

    def test_strict_mode_does_not_define_gnu_version_macros(self) -> None:
        result = preprocess_source(
            "#if defined(__GNUC__) || defined(__GNUC_MINOR__) || defined(__GNUC_PATCHLEVEL__)\n"
            "int g = 1;\n"
            "#endif\n",
            filename="main.c",
        )
        self.assertNotIn("int g", result.source)

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

    def test_cli_define_function_like_macro(self) -> None:
        result = preprocess_source(
            "int x = INTMAX_C(12);\n",
            filename="main.c",
            options=FrontendOptions(defines=("INTMAX_C(v)=v##LL",)),
        )
        self.assertIn("int x = 12LL ;", result.source)

    def test_predefined_integer_width_macros(self) -> None:
        source = "#if __INT_WIDTH__ == 32 && __LONG_WIDTH__ > 32\nint x;\n#endif\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("int x;", result.source)

    def test_cli_undef_removes_predefined_macro(self) -> None:
        source = (
            "#if __INT_WIDTH__\nint x;\n#endif\n"
            "#if __STDC_UTF_16__\nint y;\n#endif\n"
            "#if __STDC_MB_MIGHT_NEQ_WC__\nint mw;\n#endif\n"
            "#if __STDC_NO_THREADS__\nint t;\n#endif\n"
            "#if __SIZEOF_POINTER__\nint z;\n#endif\n"
            "#if __SIZEOF_FLOAT__\nint fsz;\n#endif\n"
            "#if __SIZEOF_DOUBLE__\nint dsz;\n#endif\n"
            "#if __SIZEOF_LONG_DOUBLE__\nint ldsz;\n#endif\n"
            "#if __FLT_RADIX__ == 2\nint fr;\n#endif\n"
            "#if __FLT_MANT_DIG__ == 24\nint fm;\n#endif\n"
            "#if __DBL_MANT_DIG__ == 53\nint dm;\n#endif\n"
            "#if __LDBL_MANT_DIG__ == 113\nint ldm;\n#endif\n"
            "#if __FLT_DIG__ == 6\nint fdig;\n#endif\n"
            "#if __DBL_DIG__ == 15\nint ddig;\n#endif\n"
            "#if __LDBL_DIG__ == 33\nint lddig;\n#endif\n"
            "#if defined(__FLT_EPSILON__)\nint feps;\n#endif\n"
            "#if defined(__DBL_EPSILON__)\nint deps;\n#endif\n"
            "#if defined(__LDBL_EPSILON__)\nint ldeps;\n#endif\n"
            "#if defined(__FLT_MIN__)\nint fmin;\n#endif\n"
            "#if defined(__DBL_MIN__)\nint dmin;\n#endif\n"
            "#if defined(__LDBL_MIN__)\nint ldmin;\n#endif\n"
            "#if defined(__FLT_MAX__)\nint fmax;\n#endif\n"
            "#if defined(__DBL_MAX__)\nint dmax;\n#endif\n"
            "#if defined(__LDBL_MAX__)\nint ldmax;\n#endif\n"
            "#if __FLT_MIN_EXP__ < 0\nint fminexp;\n#endif\n"
            "#if __DBL_MIN_EXP__ < 0\nint dminexp;\n#endif\n"
            "#if __LDBL_MIN_EXP__ < 0\nint ldminexp;\n#endif\n"
            "#if __FLT_MAX_EXP__ > 0\nint fmaxexp;\n#endif\n"
            "#if __DBL_MAX_EXP__ > 0\nint dmaxexp;\n#endif\n"
            "#if __LDBL_MAX_EXP__ > 0\nint ldmaxexp;\n#endif\n"
            "#if __SIZEOF_SIZE_T__\nint szz;\n#endif\n"
            "#if __SIZEOF_PTRDIFF_T__\nint pdz;\n#endif\n"
            "#if __SIZEOF_INTMAX_T__\nint imz;\n#endif\n"
            "#if __SIZEOF_UINTMAX_T__\nint umz;\n#endif\n"
            "#if __SIZEOF_WCHAR_T__\nint wcz;\n#endif\n"
            "#if __SIZEOF_WINT_T__\nint wiz;\n#endif\n"
            "#if __SIZE_WIDTH__ == 64\nint sw;\n#endif\n"
            "#if __PTRDIFF_WIDTH__ == 64\nint pw;\n#endif\n"
            "#if __INTPTR_WIDTH__ == 64\nint ipw;\n#endif\n"
            "#if __UINTPTR_WIDTH__ == 64\nint upw;\n#endif\n"
            "#if __INTMAX_WIDTH__ == 64\nint imw;\n#endif\n"
            "#if __UINTMAX_WIDTH__ == 64\nint umw;\n#endif\n"
            "#if __SIZE_MAX__ > 0\nint sm;\n#endif\n"
            "#if __PTRDIFF_MAX__ > 0\nint pm;\n#endif\n"
            "#if __PTRDIFF_MIN__ < 0\nint pmin;\n#endif\n"
            "#if __INTPTR_MAX__ > 0\nint ipmax;\n#endif\n"
            "#if __INTPTR_MIN__ < 0\nint ipmin;\n#endif\n"
            "#if __UINTPTR_MAX__ > 0\nint upmax;\n#endif\n"
            "#if __INTMAX_MIN__ < 0\nint imm;\n#endif\n"
            "#if __LONG_LONG_MIN__ < 0\nint llm;\n#endif\n"
            "#if __LONG_MIN__ < 0\nint lm;\n#endif\n"
            "#if __SCHAR_MIN__ < 0\nint scm;\n#endif\n"
            "#if __SHRT_MIN__ < 0\nint shm;\n#endif\n"
            "#if __INT_MIN__ < 0\nint imn;\n#endif\n"
            "#if __CHAR_BIT__ == 8\nint c;\n#endif\n"
            "#if defined(__LP64)\nint lp_alias;\n#endif\n"
            "#if defined(_LP64)\nint lp_legacy;\n#endif\n"
            "#if defined(__BYTE_ORDER__)\nint e;\n#endif\n"
            "#if defined(__LITTLE_ENDIAN__)\nint le;\n#endif\n"
            "#if defined(__FLOAT_WORD_ORDER__)\nint fwo;\n#endif\n"
            "#if __INCLUDE_LEVEL__\nint il;\n#endif\n"
            "#if __WCHAR_WIDTH__ == 32\nint ww;\n#endif\n"
            "#if __WINT_WIDTH__ == 32\nint wiw;\n#endif\n"
            "#if __WCHAR_MAX__ > 0\nint wmax;\n#endif\n"
            "#if __WCHAR_MIN__ < 0\nint wmin;\n#endif\n"
            "#if __WINT_MAX__ > 0\nint wimax;\n#endif\n"
            "#if defined(__WINT_MIN__)\nint wimin;\n#endif\n"
            "#if __SIG_ATOMIC_WIDTH__ == 32\nint saw;\n#endif\n"
            "#if __SIG_ATOMIC_MAX__ > 0\nint samax;\n#endif\n"
            "#if __SIG_ATOMIC_MIN__ < 0\nint samin;\n#endif\n"
            "#if defined(__STDC_ISO_10646__)\nint iso;\n#endif\n"
            "#if defined(__FILE_NAME__)\nint fn;\n#endif\n"
            "__SIZE_TYPE__ n;\n"
            "__INTPTR_TYPE__ ip;\n"
            "__UINTPTR_TYPE__ up;\n"
            "__WCHAR_TYPE__ w;\n"
        )
        result = preprocess_source(
            source,
            filename="main.c",
            options=FrontendOptions(
                undefs=(
                    "__INT_WIDTH__",
                    "__STDC_UTF_16__",
                    "__STDC_MB_MIGHT_NEQ_WC__",
                    "__STDC_NO_THREADS__",
                    "__SIZEOF_POINTER__",
                    "__SIZEOF_FLOAT__",
                    "__SIZEOF_DOUBLE__",
                    "__SIZEOF_LONG_DOUBLE__",
                    "__FLT_RADIX__",
                    "__FLT_MANT_DIG__",
                    "__DBL_MANT_DIG__",
                    "__LDBL_MANT_DIG__",
                    "__FLT_DIG__",
                    "__DBL_DIG__",
                    "__LDBL_DIG__",
                    "__FLT_EPSILON__",
                    "__DBL_EPSILON__",
                    "__LDBL_EPSILON__",
                    "__FLT_MIN__",
                    "__DBL_MIN__",
                    "__LDBL_MIN__",
                    "__FLT_MAX__",
                    "__DBL_MAX__",
                    "__LDBL_MAX__",
                    "__FLT_MIN_EXP__",
                    "__DBL_MIN_EXP__",
                    "__LDBL_MIN_EXP__",
                    "__FLT_MAX_EXP__",
                    "__DBL_MAX_EXP__",
                    "__LDBL_MAX_EXP__",
                    "__SIZEOF_SIZE_T__",
                    "__SIZEOF_PTRDIFF_T__",
                    "__SIZEOF_INTMAX_T__",
                    "__SIZEOF_UINTMAX_T__",
                    "__SIZEOF_WCHAR_T__",
                    "__SIZEOF_WINT_T__",
                    "__SIZE_WIDTH__",
                    "__PTRDIFF_WIDTH__",
                    "__INTPTR_WIDTH__",
                    "__UINTPTR_WIDTH__",
                    "__INTMAX_WIDTH__",
                    "__UINTMAX_WIDTH__",
                    "__SIZE_MAX__",
                    "__PTRDIFF_MAX__",
                    "__PTRDIFF_MIN__",
                    "__INTPTR_MAX__",
                    "__INTPTR_MIN__",
                    "__UINTPTR_MAX__",
                    "__INTMAX_MIN__",
                    "__LONG_LONG_MIN__",
                    "__LONG_MIN__",
                    "__SCHAR_MIN__",
                    "__SHRT_MIN__",
                    "__INT_MIN__",
                    "__CHAR_BIT__",
                    "__LP64",
                    "_LP64",
                    "__BYTE_ORDER__",
                    "__LITTLE_ENDIAN__",
                    "__FLOAT_WORD_ORDER__",
                    "__ORDER_LITTLE_ENDIAN__",
                    "__INCLUDE_LEVEL__",
                    "__WCHAR_WIDTH__",
                    "__WINT_WIDTH__",
                    "__WCHAR_MAX__",
                    "__WCHAR_MIN__",
                    "__WINT_MAX__",
                    "__WINT_MIN__",
                    "__SIG_ATOMIC_WIDTH__",
                    "__SIG_ATOMIC_MAX__",
                    "__SIG_ATOMIC_MIN__",
                    "__STDC_ISO_10646__",
                    "__FILE_NAME__",
                    "__SIZE_TYPE__",
                    "__INTPTR_TYPE__",
                    "__UINTPTR_TYPE__",
                    "__WCHAR_TYPE__",
                )
            ),
        )
        self.assertNotIn("int x;", result.source)
        self.assertNotIn("int y;", result.source)
        self.assertNotIn("int mw;", result.source)
        self.assertNotIn("int t;", result.source)
        self.assertNotIn("int z;", result.source)
        self.assertNotIn("int fsz;", result.source)
        self.assertNotIn("int dsz;", result.source)
        self.assertNotIn("int ldsz;", result.source)
        self.assertNotIn("int fr;", result.source)
        self.assertNotIn("int fm;", result.source)
        self.assertNotIn("int dm;", result.source)
        self.assertNotIn("int ldm;", result.source)
        self.assertNotIn("int fdig;", result.source)
        self.assertNotIn("int ddig;", result.source)
        self.assertNotIn("int lddig;", result.source)
        self.assertNotIn("int feps;", result.source)
        self.assertNotIn("int deps;", result.source)
        self.assertNotIn("int ldeps;", result.source)
        self.assertNotIn("int fmin;", result.source)
        self.assertNotIn("int dmin;", result.source)
        self.assertNotIn("int ldmin;", result.source)
        self.assertNotIn("int fmax;", result.source)
        self.assertNotIn("int dmax;", result.source)
        self.assertNotIn("int ldmax;", result.source)
        self.assertNotIn("int fminexp;", result.source)
        self.assertNotIn("int dminexp;", result.source)
        self.assertNotIn("int ldminexp;", result.source)
        self.assertNotIn("int fmaxexp;", result.source)
        self.assertNotIn("int dmaxexp;", result.source)
        self.assertNotIn("int ldmaxexp;", result.source)
        self.assertNotIn("int szz;", result.source)
        self.assertNotIn("int pdz;", result.source)
        self.assertNotIn("int imz;", result.source)
        self.assertNotIn("int umz;", result.source)
        self.assertNotIn("int wcz;", result.source)
        self.assertNotIn("int wiz;", result.source)
        self.assertNotIn("int sw;", result.source)
        self.assertNotIn("int pw;", result.source)
        self.assertNotIn("int ipw;", result.source)
        self.assertNotIn("int upw;", result.source)
        self.assertNotIn("int imw;", result.source)
        self.assertNotIn("int umw;", result.source)
        self.assertNotIn("int sm;", result.source)
        self.assertNotIn("int pm;", result.source)
        self.assertNotIn("int pmin;", result.source)
        self.assertNotIn("int ipmax;", result.source)
        self.assertNotIn("int ipmin;", result.source)
        self.assertNotIn("int upmax;", result.source)
        self.assertNotIn("int imm;", result.source)
        self.assertNotIn("int llm;", result.source)
        self.assertNotIn("int lm;", result.source)
        self.assertNotIn("int scm;", result.source)
        self.assertNotIn("int shm;", result.source)
        self.assertNotIn("int imn;", result.source)
        self.assertNotIn("int c;", result.source)
        self.assertNotIn("int lp_alias;", result.source)
        self.assertNotIn("int lp_legacy;", result.source)
        self.assertNotIn("int e;", result.source)
        self.assertNotIn("int le;", result.source)
        self.assertNotIn("int fwo;", result.source)
        self.assertNotIn("int il;", result.source)
        self.assertNotIn("int ww;", result.source)
        self.assertNotIn("int wiw;", result.source)
        self.assertNotIn("int wmax;", result.source)
        self.assertNotIn("int wmin;", result.source)
        self.assertNotIn("int wimax;", result.source)
        self.assertNotIn("int wimin;", result.source)
        self.assertNotIn("int saw;", result.source)
        self.assertNotIn("int samax;", result.source)
        self.assertNotIn("int samin;", result.source)
        self.assertNotIn("int iso;", result.source)
        self.assertNotIn("int fn;", result.source)
        self.assertIn("__SIZE_TYPE__ n;", result.source)
        self.assertIn("__INTPTR_TYPE__ ip;", result.source)
        self.assertIn("__UINTPTR_TYPE__ up;", result.source)
        self.assertIn("__WCHAR_TYPE__ w;", result.source)

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

    def test_elifdef_in_gnu_mode(self) -> None:
        source = "#if 0\n#elifdef FLAG\nint yes;\n#else\nint no;\n#endif\n"
        result = preprocess_source(
            source,
            filename="if.c",
            options=FrontendOptions(std="gnu11", defines=("FLAG=1",)),
        )
        self.assertIn("int yes", result.source)
        self.assertNotIn("int no", result.source)

    def test_elifndef_in_gnu_mode(self) -> None:
        source = "#if 0\n#elifndef FLAG\nint yes;\n#else\nint no;\n#endif\n"
        result = preprocess_source(
            source,
            filename="if.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertIn("int yes", result.source)
        self.assertNotIn("int no", result.source)

    def test_elifdef_errors_in_c11_mode(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if 0\n#elifdef FLAG\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0101")
        self.assertEqual(
            str(ctx.exception),
            "Unknown preprocessor directive: #elifdef at if.c:2:1",
        )

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

    def test_elifdef_after_else(self) -> None:
        source = "#if 0\n#else\n#elifdef FLAG\n#endif\n"
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(
                source,
                filename="if.c",
                options=FrontendOptions(std="gnu11", defines=("FLAG=1",)),
            )
        self.assertEqual(str(ctx.exception), "#elifdef after #else at if.c:3:1")

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

    def test_if_expression_with_has_include_quoted_uses_including_file_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_dir = root / "include"
            source_dir = root / "src"
            include_dir.mkdir()
            source_dir.mkdir()
            (include_dir / "local.h").write_text("\n", encoding="utf-8")
            (include_dir / "feature.h").write_text(
                '#if __has_include("local.h")\nint found;\n#endif\n',
                encoding="utf-8",
            )
            (source_dir / "main.c").write_text('#include "feature.h"\n', encoding="utf-8")
            options = FrontendOptions(include_dirs=(str(include_dir),))
            result = preprocess_source(
                (source_dir / "main.c").read_text(encoding="utf-8"),
                filename=str(source_dir / "main.c"),
                options=options,
            )
        self.assertIn("int found;", result.source)

    def test_if_expression_with_has_include_missing(self) -> None:
        result = preprocess_source(
            "#if __has_include(\"missing.h\")\nint bad;\n#endif\n",
            filename="main.c",
        )
        self.assertNotIn("int bad;", result.source)

    def test_if_expression_with_has_include_macro_expands_to_quoted_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "present.h").write_text("int x;\n", encoding="utf-8")
            source = '#define HDR "present.h"\n#if __has_include(HDR)\nint ok;\n#endif\n'
            result = preprocess_source(source, filename=str(root / "main.c"))
        self.assertIn("int ok ;", result.source)

    def test_if_expression_with_has_include_macro_expands_to_angle_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include = root / "include"
            include.mkdir()
            (include / "present.h").write_text("int x;\n", encoding="utf-8")
            source = "#define HDR <present.h>\n#if __has_include(HDR)\nint ok;\n#endif\n"
            result = preprocess_source(
                source,
                filename="main.c",
                options=FrontendOptions(include_dirs=(str(include),)),
            )
        self.assertIn("int ok ;", result.source)

    def test_if_expression_with_macro_expanded_has_include_operator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "present.h").write_text("int x;\n", encoding="utf-8")
            source = "#define HAS(x) __has_include(x)\n#if HAS(\"present.h\")\nint ok;\n#endif\n"
            result = preprocess_source(source, filename=str(root / "main.c"))
        self.assertIn("int ok ;", result.source)


    def test_if_expression_with_has_include_macro_expands_to_invalid_header(self) -> None:
        source = "#define HDR present.h\n#if __has_include(HDR)\nint bad;\n#endif\n"
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(source, filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertIn(
            "Invalid __has_include expression: header operand must be quoted or angled",
            str(ctx.exception),
        )

    def test_if_expression_with_has_include_invalid_form(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if __has_include(MISSING)\nint x;\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertIn(
            "Invalid __has_include expression: header operand must be quoted or angled",
            str(ctx.exception),
        )

    def test_if_expression_with_has_include_missing_operand(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if __has_include()\nint x;\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertIn("Invalid __has_include expression: missing header operand", str(ctx.exception))

    def test_if_expression_with_has_include_missing_closing_paren(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if __has_include(\"x.h\"\nint x;\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertIn("Invalid __has_include expression: missing closing ')'", str(ctx.exception))

    def test_if_expression_with_has_include_next_in_gnu11(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            include_dir = root / "include"
            source_dir.mkdir()
            include_dir.mkdir()
            (include_dir / "next.h").write_text("\n", encoding="utf-8")
            source = '#if __has_include_next("next.h")\nint ok;\n#endif\n'
            result = preprocess_source(
                source,
                filename=str(source_dir / "main.c"),
                options=FrontendOptions(std="gnu11", include_dirs=(str(include_dir),)),
            )
        self.assertIn("int ok;", result.source)

    def test_if_expression_with_has_include_next_skips_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            source_dir.mkdir()
            (source_dir / "next.h").write_text("\n", encoding="utf-8")
            source = '#if __has_include_next("next.h")\nint bad;\n#endif\n'
            result = preprocess_source(
                source,
                filename=str(source_dir / "main.c"),
                options=FrontendOptions(std="gnu11"),
            )
        self.assertNotIn("int bad;", result.source)

    def test_if_expression_with_has_include_next_errors_in_c11(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(
                '#if __has_include_next("missing.h")\nint x;\n#endif\n',
                filename="if.c",
            )
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

    def test_pragma_once_skips_second_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = root / "once.h"
            header.write_text("#pragma once\nint from_once;\n", encoding="utf-8")
            source_path = root / "main.c"
            source_path.write_text('#include "once.h"\n#include "once.h"\n', encoding="utf-8")
            result = preprocess_source(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        self.assertEqual(result.source, "\nint from_once;\n")

    def test_pragma_once_applies_across_nested_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "once.h").write_text("#pragma once\nint from_once;\n", encoding="utf-8")
            (root / "wrapper.h").write_text('#include "once.h"\n', encoding="utf-8")
            main = root / "main.c"
            main.write_text('#include "once.h"\n#include "wrapper.h"\n', encoding="utf-8")
            result = preprocess_source(main.read_text(encoding="utf-8"), filename=str(main))
        self.assertEqual(result.source, "\nint from_once;\n")

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

    def test_include_angle_prefers_include_dirs_over_system_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_dir = root / "include"
            system_dir = root / "sys"
            include_dir.mkdir()
            system_dir.mkdir()
            (include_dir / "inc.h").write_text("int from_include;\n", encoding="utf-8")
            (system_dir / "inc.h").write_text("int from_system;\n", encoding="utf-8")
            options = FrontendOptions(
                include_dirs=(str(include_dir),),
                system_include_dirs=(str(system_dir),),
            )
            result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int from_include;\n")

    def test_include_quoted_uses_cpath_when_include_dirs_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            cpath_dir = root / "cpath"
            source_dir.mkdir()
            cpath_dir.mkdir()
            (cpath_dir / "inc.h").write_text("int from_cpath;\n", encoding="utf-8")
            main = source_dir / "main.c"
            main.write_text('#include "inc.h"\n', encoding="utf-8")
            with patch.dict("os.environ", {"CPATH": str(cpath_dir)}, clear=False):
                result = preprocess_source(main.read_text(encoding="utf-8"), filename=str(main))
        self.assertEqual(result.source, "int from_cpath;\n")

    def test_include_angle_prefers_include_dirs_over_cpath(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_dir = root / "include"
            cpath_dir = root / "cpath"
            include_dir.mkdir()
            cpath_dir.mkdir()
            (include_dir / "inc.h").write_text("int from_include;\n", encoding="utf-8")
            (cpath_dir / "inc.h").write_text("int from_cpath;\n", encoding="utf-8")
            options = FrontendOptions(include_dirs=(str(include_dir),))
            with patch.dict("os.environ", {"CPATH": str(cpath_dir)}, clear=False):
                result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int from_include;\n")

    def test_nostdinc_disables_environment_include_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cpath_dir = root / "cpath"
            c_include_dir = root / "c_include"
            cpath_dir.mkdir()
            c_include_dir.mkdir()
            (cpath_dir / "inc.h").write_text("int from_cpath;\n", encoding="utf-8")
            (c_include_dir / "inc.h").write_text("int from_c_include;\n", encoding="utf-8")
            options = FrontendOptions(no_standard_includes=True)
            with patch.dict(
                "os.environ",
                {"CPATH": str(cpath_dir), "C_INCLUDE_PATH": str(c_include_dir)},
                clear=False,
            ):
                with self.assertRaises(PreprocessorError) as ctx:
                    preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertIn("Include not found", str(ctx.exception))

    def test_include_angle_uses_c_include_path_after_system_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            system_dir = root / "sys"
            c_include_dir = root / "c_include"
            after_dir = root / "after"
            system_dir.mkdir()
            c_include_dir.mkdir()
            after_dir.mkdir()
            (c_include_dir / "inc.h").write_text("int from_c_include_path;\n", encoding="utf-8")
            (after_dir / "inc.h").write_text("int from_after;\n", encoding="utf-8")
            options = FrontendOptions(
                system_include_dirs=(str(system_dir),),
                after_include_dirs=(str(after_dir),),
            )
            with patch.dict("os.environ", {"C_INCLUDE_PATH": str(c_include_dir)}, clear=False):
                result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int from_c_include_path;\n")

    def test_include_angle_prefers_system_dirs_over_idirafter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            system_dir = root / "sys"
            after_dir = root / "after"
            system_dir.mkdir()
            after_dir.mkdir()
            (system_dir / "inc.h").write_text("int from_system;\n", encoding="utf-8")
            (after_dir / "inc.h").write_text("int from_after;\n", encoding="utf-8")
            options = FrontendOptions(
                system_include_dirs=(str(system_dir),),
                after_include_dirs=(str(after_dir),),
            )
            result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int from_system;\n")

    def test_include_angle_uses_idirafter_when_earlier_roots_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_dir = root / "include"
            system_dir = root / "sys"
            after_dir = root / "after"
            include_dir.mkdir()
            system_dir.mkdir()
            after_dir.mkdir()
            (after_dir / "inc.h").write_text("int from_after;\n", encoding="utf-8")
            options = FrontendOptions(
                include_dirs=(str(include_dir),),
                system_include_dirs=(str(system_dir),),
                after_include_dirs=(str(after_dir),),
            )
            result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int from_after;\n")

    def test_include_quoted_prefers_quote_include_dirs_over_include_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            quote_dir = root / "quote"
            include_dir = root / "include"
            system_dir = root / "sys"
            source_dir.mkdir()
            quote_dir.mkdir()
            include_dir.mkdir()
            system_dir.mkdir()
            (quote_dir / "inc.h").write_text("int from_quote;\n", encoding="utf-8")
            (include_dir / "inc.h").write_text("int from_include;\n", encoding="utf-8")
            (system_dir / "inc.h").write_text("int from_system;\n", encoding="utf-8")
            main = source_dir / "main.c"
            main.write_text('#include "inc.h"\n', encoding="utf-8")
            options = FrontendOptions(
                quote_include_dirs=(str(quote_dir),),
                include_dirs=(str(include_dir),),
                system_include_dirs=(str(system_dir),),
            )
            result = preprocess_source(main.read_text(encoding="utf-8"), filename=str(main), options=options)
        self.assertEqual(result.source, "int from_quote;\n")

    def test_include_angle_ignores_quote_include_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quote_dir = root / "quote"
            include_dir = root / "include"
            quote_dir.mkdir()
            include_dir.mkdir()
            (quote_dir / "inc.h").write_text("int from_quote;\n", encoding="utf-8")
            (include_dir / "inc.h").write_text("int from_include;\n", encoding="utf-8")
            options = FrontendOptions(
                quote_include_dirs=(str(quote_dir),),
                include_dirs=(str(include_dir),),
            )
            result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int from_include;\n")

    def test_include_quoted_uses_system_dirs_when_include_dirs_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            include_dir = root / "include"
            system_dir = root / "sys"
            source_dir.mkdir()
            include_dir.mkdir()
            system_dir.mkdir()
            (system_dir / "inc.h").write_text("int from_system;\n", encoding="utf-8")
            main = source_dir / "main.c"
            main.write_text('#include "inc.h"\n', encoding="utf-8")
            options = FrontendOptions(
                include_dirs=(str(include_dir),),
                system_include_dirs=(str(system_dir),),
            )
            result = preprocess_source(main.read_text(encoding="utf-8"), filename=str(main), options=options)
        self.assertEqual(result.source, "int from_system;\n")

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

    def test_include_next_in_gnu_mode_uses_following_include_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_dir = root / "first"
            second_dir = root / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            (first_dir / "inc.h").write_text("#include_next <inc.h>\nint from_first;\n", encoding="utf-8")
            (second_dir / "inc.h").write_text("int from_second;\n", encoding="utf-8")
            options = FrontendOptions(
                std="gnu11",
                include_dirs=(str(first_dir), str(second_dir)),
            )
            result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int from_second;\nint from_first;\n")

    def test_include_next_in_gnu_mode_skips_source_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            include_dir = root / "include"
            source_dir.mkdir()
            include_dir.mkdir()
            (source_dir / "inc.h").write_text('#include_next "inc.h"\nint from_source;\n', encoding="utf-8")
            (include_dir / "inc.h").write_text("int from_include;\n", encoding="utf-8")
            main = source_dir / "main.c"
            options = FrontendOptions(std="gnu11", include_dirs=(str(include_dir),))
            result = preprocess_source('#include "inc.h"\n', filename=str(main), options=options)
        self.assertEqual(result.source, "int from_include;\nint from_source;\n")

    def test_include_next_skips_later_duplicate_of_current_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_dir = root / "first"
            second_dir = root / "second"
            first_alias = root / "first_alias"
            first_dir.mkdir()
            second_dir.mkdir()
            first_alias.symlink_to(first_dir, target_is_directory=True)
            (first_dir / "inc.h").write_text('#include_next "inc.h"\nint from_first;\n', encoding="utf-8")
            (second_dir / "inc.h").write_text("int from_second;\n", encoding="utf-8")
            options = FrontendOptions(
                std="gnu11",
                include_dirs=(str(first_dir), str(second_dir), str(first_alias)),
            )
            result = preprocess_source('#include "inc.h"\n', filename="main.c", options=options)
        self.assertEqual(result.source, "int from_second;\nint from_first;\n")

    def test_has_include_next_skips_later_duplicate_of_current_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_dir = root / "first"
            first_alias = root / "first_alias"
            first_dir.mkdir()
            first_alias.symlink_to(first_dir, target_is_directory=True)
            (first_dir / "inc.h").write_text(
                "#if __has_include_next(\"inc.h\")\nint has_next;\n#endif\n",
                encoding="utf-8",
            )
            options = FrontendOptions(
                std="gnu11",
                include_dirs=(str(first_dir), str(first_alias)),
            )
            result = preprocess_source('#include "inc.h"\n', filename="main.c", options=options)
        self.assertEqual(result.source.strip(), "")

    def test_include_next_missing_header_reports_include_next_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            include_dir = root / "include"
            source_dir.mkdir()
            include_dir.mkdir()
            (source_dir / "inc.h").write_text('#include_next "inc.h"\n', encoding="utf-8")
            main = source_dir / "main.c"
            options = FrontendOptions(std="gnu11", include_dirs=(str(include_dir),))
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source('#include "inc.h"\n', filename=str(main), options=options)
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual(
            ctx.exception.args[0],
            f'Include not found via #include_next: "inc.h"; searched: {include_dir.resolve()} at {(source_dir / "inc.h").resolve()}:1:1',
        )

    def test_include_next_trace_uses_include_next_directive_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_dir = root / "first"
            second_dir = root / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            (first_dir / "inc.h").write_text("#include_next <inc.h>\n", encoding="utf-8")
            (second_dir / "inc.h").write_text("int ok;\n", encoding="utf-8")
            options = FrontendOptions(std="gnu11", include_dirs=(str(first_dir), str(second_dir)))
            result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(len(result.include_trace), 2)
        self.assertIn("main.c:1: #include <inc.h>", result.include_trace[0])
        self.assertIn(f'{(first_dir / "inc.h").resolve()}:1: #include_next <inc.h>', result.include_trace[1])

    def test_include_next_is_rejected_in_c11_mode(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#include_next <inc.h>\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0101")
        self.assertEqual(ctx.exception.args[0], "Unknown preprocessor directive: #include_next at main.c:1:1")

    def test_include_expansion_preserves_line_map_for_header_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include = root / "inc.h"
            main = root / "main.c"
            include.write_text("int from_header;\n", encoding="utf-8")
            result = preprocess_source('#include "inc.h"\nint from_main;\n', filename=str(main))
        self.assertEqual(result.line_map, ((str(include.resolve()), 1), (str(main), 2)))

    def test_include_macro_expands_to_quoted_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text("int from_header;\n", encoding="utf-8")
            source_path = root / "main.c"
            source_path.write_text('#define HDR "inc.h"\n#include HDR\n', encoding="utf-8")
            result = preprocess_source(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        self.assertEqual(result.source, "\nint from_header ;\n")

    def test_include_macro_expands_to_angle_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_dir = root / "include"
            include_dir.mkdir()
            (include_dir / "inc.h").write_text("int from_include;\n", encoding="utf-8")
            options = FrontendOptions(include_dirs=(str(include_dir),))
            result = preprocess_source(
                "#define HDR <inc.h>\n#include HDR\n",
                filename="main.c",
                options=options,
            )
        self.assertEqual(result.source, "\nint from_include ;\n")

    def test_include_macro_rejects_non_header_expansion(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#define HDR bad\n#include HDR\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")

    def test_imacros_applies_macros_before_main_source_without_emitting_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_dir = root / "include"
            include_dir.mkdir()
            (include_dir / "defs.h").write_text("#define VALUE 17\nint ignored;\n", encoding="utf-8")
            options = FrontendOptions(
                include_dirs=(str(include_dir),),
                macro_includes=("defs.h",),
            )
            result = preprocess_source("VALUE\n", filename="main.c", options=options)
        self.assertEqual(result.source, "17\n")
        self.assertIn('#imacros "defs.h" ->', result.include_trace[0])

    def test_imacros_runs_before_forced_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_dir = root / "include"
            include_dir.mkdir()
            (include_dir / "defs.h").write_text("#define VALUE 17\n", encoding="utf-8")
            (include_dir / "forced.h").write_text("int from_forced = VALUE;\n", encoding="utf-8")
            options = FrontendOptions(
                include_dirs=(str(include_dir),),
                macro_includes=("defs.h",),
                forced_includes=("forced.h",),
            )
            result = preprocess_source("VALUE\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int from_forced = 17 ;\n17\n")

    def test_imacros_not_found(self) -> None:
        options = FrontendOptions(macro_includes=("missing.h",))
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("int x;\n", filename="main.c", options=options)
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual(
            ctx.exception.args[0],
            f'Macro include not found: "missing.h"; searched: {Path.cwd().resolve()} at <command line>:1:1',
        )

    def test_forced_include_applies_before_main_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_dir = root / "include"
            include_dir.mkdir()
            (include_dir / "forced.h").write_text("#define VALUE 13\n", encoding="utf-8")
            options = FrontendOptions(
                include_dirs=(str(include_dir),),
                forced_includes=("forced.h",),
            )
            result = preprocess_source("VALUE\n", filename="main.c", options=options)
        self.assertEqual(result.source, "\n13\n")
        self.assertIn('#include "forced.h" ->', result.include_trace[0])

    def test_forced_include_not_found(self) -> None:
        options = FrontendOptions(forced_includes=("missing.h",))
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("int x;\n", filename="main.c", options=options)
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual(
            ctx.exception.args[0],
            f'Forced include not found: "missing.h"; searched: {Path.cwd().resolve()} at <command line>:1:1',
        )

    def test_include_not_found(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source('#include "missing.h"\n', filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual((ctx.exception.filename, ctx.exception.line), ("main.c", 1))
        self.assertEqual(
            ctx.exception.args[0],
            f'Include not found: "missing.h"; searched: {Path.cwd().resolve()} at main.c:1:1',
        )

    def test_include_not_found_for_angle_include_reports_delimiters(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#include <missing.h>\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual(
            ctx.exception.args[0],
            "Include not found: <missing.h>; searched: <none> at main.c:1:1",
        )

    def test_include_not_found_reports_search_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_a = root / "inc_a"
            include_b = root / "inc_b"
            include_a.mkdir()
            include_b.mkdir()
            options = FrontendOptions(
                include_dirs=(str(include_a),),
                system_include_dirs=(str(include_b),),
            )
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source('#include "missing.h"\n', filename="main.c", options=options)
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual(
            ctx.exception.args[0],
            (
                f'Include not found: "missing.h"; searched: {Path.cwd().resolve()}, '
                f"{include_a.resolve()}, {include_b.resolve()} at main.c:1:1"
            ),
        )

    def test_include_search_roots_are_deduplicated_in_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_a = root / "inc_a"
            include_a.mkdir()
            include_a_alias = root / "inc_a_alias"
            include_a_alias.symlink_to(include_a, target_is_directory=True)
            options = FrontendOptions(
                include_dirs=(str(include_a), str(include_a_alias), str(include_a)),
            )
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source('#include "missing.h"\n', filename="main.c", options=options)
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual(
            ctx.exception.args[0],
            (
                f'Include not found: "missing.h"; searched: {Path.cwd().resolve()}, '
                f"{include_a.resolve()} at main.c:1:1"
            ),
        )

    def test_include_search_skips_duplicate_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_a = root / "inc_a"
            include_a.mkdir()
            include_a_alias = root / "inc_a_alias"
            include_a_alias.symlink_to(include_a, target_is_directory=True)
            (include_a / "present.h").write_text("int from_include;\n", encoding="utf-8")
            options = FrontendOptions(include_dirs=(str(include_a_alias), str(include_a)))
            result = preprocess_source('#include "present.h"\n', filename="main.c", options=options)
        self.assertEqual(result.source, "int from_include;\n")

    def test_invalid_include_directive(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#include bad\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")

    def test_circular_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_header = root / "a.h"
            b_header = root / "b.h"
            a_header.write_text('#include "b.h"\n', encoding="utf-8")
            b_header.write_text('#include "a.h"\n', encoding="utf-8")
            source = '#include "a.h"\n'
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source(source, filename=str(root / "main.c"))
            self.assertEqual(ctx.exception.code, "XCC-PP-0302")
            self.assertEqual(
                ctx.exception.args[0],
                (
                    "Circular include detected: "
                    f"{a_header.resolve()} -> {b_header.resolve()} -> {a_header.resolve()} "
                    f"at {b_header.resolve()}:1:1"
                ),
            )

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

    def test_line_directive_expands_macro_operands(self) -> None:
        result = preprocess_source(
            '#define LINE_NO 42\n#define FILE_NAME "mapped.c"\n#line LINE_NO FILE_NAME\nint x;\n',
            filename="main.c",
        )
        self.assertEqual(result.line_map[-1], ("mapped.c", 42))

    def test_line_directive_rejects_non_decimal_macro_expansion(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#define LINE_NO 0x2A\n#line LINE_NO\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")

    def test_predefined_standard_macros(self) -> None:
        result = preprocess_source(
            "int s = __STDC__;\n"
            "int h = __STDC_HOSTED__;\n"
            "long v = __STDC_VERSION__;\n"
            "int iec = __STDC_IEC_559__;\n"
            "int mw = __STDC_MB_MIGHT_NEQ_WC__;\n"
            "int u16 = __STDC_UTF_16__;\n"
            "int u32 = __STDC_UTF_32__;\n"
            "int na = __STDC_NO_ATOMICS__;\n"
            "int nc = __STDC_NO_COMPLEX__;\n"
            "int nt = __STDC_NO_THREADS__;\n"
            "int nv = __STDC_NO_VLA__;\n"
            "int lp = __LP64__;\n"
            "int lp_alias = __LP64;\n"
            "int lp_legacy = _LP64;\n"
            "int bits = __CHAR_BIT__;\n"
            "int szw = __SIZE_WIDTH__;\n"
            "int pdw = __PTRDIFF_WIDTH__;\n"
            "int ipw = __INTPTR_WIDTH__;\n"
            "int upw = __UINTPTR_WIDTH__;\n"
            "int imw = __INTMAX_WIDTH__;\n"
            "int umw = __UINTMAX_WIDTH__;\n"
            "int scmax = __SCHAR_MAX__;\n"
            "int scmin = __SCHAR_MIN__;\n"
            "int shmax = __SHRT_MAX__;\n"
            "int shmin = __SHRT_MIN__;\n"
            "int imax = __INT_MAX__;\n"
            "int imin = __INT_MIN__;\n"
            "long lmax = __LONG_MAX__;\n"
            "long lmin = __LONG_MIN__;\n"
            "unsigned int ucmax = __UCHAR_MAX__;\n"
            "unsigned int usmax = __USHRT_MAX__;\n"
            "unsigned int uimax = __UINT_MAX__;\n"
            "unsigned long ulmax = __ULONG_MAX__;\n"
            "unsigned long szmax = __SIZE_MAX__;\n"
            "long pdmax = __PTRDIFF_MAX__;\n"
            "long pdmin = __PTRDIFF_MIN__;\n"
            "long ipmax = __INTPTR_MAX__;\n"
            "long ipmin = __INTPTR_MIN__;\n"
            "unsigned long upmax = __UINTPTR_MAX__;\n"
            "int ssz = __SIZEOF_SHORT__;\n"
            "int isz = __SIZEOF_INT__;\n"
            "int fsz = __SIZEOF_FLOAT__;\n"
            "int dsz = __SIZEOF_DOUBLE__;\n"
            "int ldsz = __SIZEOF_LONG_DOUBLE__;\n"
            "int fr = __FLT_RADIX__;\n"
            "int fm = __FLT_MANT_DIG__;\n"
            "int dm = __DBL_MANT_DIG__;\n"
            "int ldm = __LDBL_MANT_DIG__;\n"
            "int fdig = __FLT_DIG__;\n"
            "int ddig = __DBL_DIG__;\n"
            "int lddig = __LDBL_DIG__;\n"
            "float feps = __FLT_EPSILON__;\n"
            "double deps = __DBL_EPSILON__;\n"
            "long double ldeps = __LDBL_EPSILON__;\n"
            "float fmin = __FLT_MIN__;\n"
            "double dmin = __DBL_MIN__;\n"
            "long double ldmin = __LDBL_MIN__;\n"
            "float fmax = __FLT_MAX__;\n"
            "double dmax = __DBL_MAX__;\n"
            "long double ldmax = __LDBL_MAX__;\n"
            "int fminexp = __FLT_MIN_EXP__;\n"
            "int dminexp = __DBL_MIN_EXP__;\n"
            "int ldminexp = __LDBL_MIN_EXP__;\n"
            "int fmaxexp = __FLT_MAX_EXP__;\n"
            "int dmaxexp = __DBL_MAX_EXP__;\n"
            "int ldmaxexp = __LDBL_MAX_EXP__;\n"
            "int psz = __SIZEOF_POINTER__;\n"
            "int lsz = __SIZEOF_LONG__;\n"
            "int llsz = __SIZEOF_LONG_LONG__;\n"
            "int szz = __SIZEOF_SIZE_T__;\n"
            "int pdz = __SIZEOF_PTRDIFF_T__;\n"
            "int imz = __SIZEOF_INTMAX_T__;\n"
            "int umz = __SIZEOF_UINTMAX_T__;\n"
            "int wcz = __SIZEOF_WCHAR_T__;\n"
            "int wiz = __SIZEOF_WINT_T__;\n"
            "int ord = __ORDER_LITTLE_ENDIAN__;\n"
            "int bo = __BYTE_ORDER__;\n"
            "int le = __LITTLE_ENDIAN__;\n"
            "int be = __BIG_ENDIAN__;\n"
            "int fwo = __FLOAT_WORD_ORDER__;\n"
            "int ww = __WCHAR_WIDTH__;\n"
            "int wiw = __WINT_WIDTH__;\n"
            "int wmax = __WCHAR_MAX__;\n"
            "int wmin = __WCHAR_MIN__;\n"
            "unsigned int wimax = __WINT_MAX__;\n"
            "unsigned int wimin = __WINT_MIN__;\n"
            "int saw = __SIG_ATOMIC_WIDTH__;\n"
            "int samax = __SIG_ATOMIC_MAX__;\n"
            "int samin = __SIG_ATOMIC_MIN__;\n"
            "long iso = __STDC_ISO_10646__;\n"
            "long long llmax = __LONG_LONG_MAX__;\n"
            "long long llmin = __LONG_LONG_MIN__;\n"
            "long long imx = __INTMAX_MAX__;\n"
            "long long imn = __INTMAX_MIN__;\n"
            "unsigned long long umx = __UINTMAX_MAX__;\n"
            "long long imc = __INTMAX_C(123);\n"
            "unsigned long long umc = __UINTMAX_C(456);\n"
            "const char *bf = __BASE_FILE__;\n"
            "const char *fn = __FILE_NAME__;\n"
            "__SIZE_TYPE__ n;\n"
            "__PTRDIFF_TYPE__ d;\n"
            "__INTPTR_TYPE__ ip;\n"
            "__UINTPTR_TYPE__ up;\n"
            "__WCHAR_TYPE__ wc;\n"
            "__WINT_TYPE__ wi;\n",
            filename="main.c",
        )
        self.assertIn("int s = 1 ;", result.source)
        self.assertIn("int h = 1 ;", result.source)
        self.assertIn("long v = 201112L ;", result.source)
        self.assertIn("int iec = 1 ;", result.source)
        self.assertIn("int mw = 1 ;", result.source)
        self.assertIn("int u16 = 1 ;", result.source)
        self.assertIn("int u32 = 1 ;", result.source)
        self.assertIn("int na = 1 ;", result.source)
        self.assertIn("int nc = 1 ;", result.source)
        self.assertIn("int nt = 1 ;", result.source)
        self.assertIn("int nv = 1 ;", result.source)
        self.assertIn("int lp = 1 ;", result.source)
        self.assertIn("int lp_alias = 1 ;", result.source)
        self.assertIn("int lp_legacy = 1 ;", result.source)
        self.assertIn("int bits = 8 ;", result.source)
        self.assertIn("int szw = 64 ;", result.source)
        self.assertIn("int pdw = 64 ;", result.source)
        self.assertIn("int ipw = 64 ;", result.source)
        self.assertIn("int upw = 64 ;", result.source)
        self.assertIn("int imw = 64 ;", result.source)
        self.assertIn("int umw = 64 ;", result.source)
        self.assertIn("int scmax = 127 ;", result.source)
        self.assertIn("int scmin = - 128 ;", result.source)
        self.assertIn("int shmax = 32767 ;", result.source)
        self.assertIn("int shmin = - 32768 ;", result.source)
        self.assertIn("int imax = 2147483647 ;", result.source)
        self.assertIn("int imin = - 2147483648 ;", result.source)
        self.assertIn("long lmax = 9223372036854775807L ;", result.source)
        self.assertIn("long lmin = - 9223372036854775808L ;", result.source)
        self.assertIn("unsigned int ucmax = 255 ;", result.source)
        self.assertIn("unsigned int usmax = 65535 ;", result.source)
        self.assertIn("unsigned int uimax = 4294967295U ;", result.source)
        self.assertIn("unsigned long ulmax = 18446744073709551615UL ;", result.source)
        self.assertIn("unsigned long szmax = 18446744073709551615UL ;", result.source)
        self.assertIn("long pdmax = 9223372036854775807L ;", result.source)
        self.assertIn("long pdmin = - 9223372036854775808L ;", result.source)
        self.assertIn("long ipmax = 9223372036854775807L ;", result.source)
        self.assertIn("long ipmin = - 9223372036854775808L ;", result.source)
        self.assertIn("unsigned long upmax = 18446744073709551615UL ;", result.source)
        self.assertIn("int ssz = 2 ;", result.source)
        self.assertIn("int isz = 4 ;", result.source)
        self.assertIn("int fsz = 4 ;", result.source)
        self.assertIn("int dsz = 8 ;", result.source)
        self.assertIn("int ldsz = 16 ;", result.source)
        self.assertIn("int fr = 2 ;", result.source)
        self.assertIn("int fm = 24 ;", result.source)
        self.assertIn("int dm = 53 ;", result.source)
        self.assertIn("int ldm = 113 ;", result.source)
        self.assertIn("int fdig = 6 ;", result.source)
        self.assertIn("int ddig = 15 ;", result.source)
        self.assertIn("int lddig = 33 ;", result.source)
        self.assertIn("float feps = 1.19209290e-7F ;", result.source)
        self.assertIn("double deps = 2.2204460492503131e-16 ;", result.source)
        self.assertIn("long double ldeps = 1.08420217248550443401e-19L ;", result.source)
        self.assertIn("float fmin = 1.17549435e-38F ;", result.source)
        self.assertIn("double dmin = 2.2250738585072014e-308 ;", result.source)
        self.assertIn("long double ldmin = 3.36210314311209350626e-4932L ;", result.source)
        self.assertIn("float fmax = 3.40282347e+38F ;", result.source)
        self.assertIn("double dmax = 1.7976931348623157e+308 ;", result.source)
        self.assertIn("long double ldmax = 1.18973149535723176502e+4932L ;", result.source)
        self.assertIn("int fminexp = - 125 ;", result.source)
        self.assertIn("int dminexp = - 1021 ;", result.source)
        self.assertIn("int ldminexp = - 16381 ;", result.source)
        self.assertIn("int fmaxexp = 128 ;", result.source)
        self.assertIn("int dmaxexp = 1024 ;", result.source)
        self.assertIn("int ldmaxexp = 16384 ;", result.source)
        self.assertIn("int psz = 8 ;", result.source)
        self.assertIn("int lsz = 8 ;", result.source)
        self.assertIn("int llsz = 8 ;", result.source)
        self.assertIn("int szz = 8 ;", result.source)
        self.assertIn("int pdz = 8 ;", result.source)
        self.assertIn("int imz = 8 ;", result.source)
        self.assertIn("int umz = 8 ;", result.source)
        self.assertIn("int wcz = 4 ;", result.source)
        self.assertIn("int wiz = 4 ;", result.source)
        self.assertIn("int ord = 1234 ;", result.source)
        self.assertIn("int bo = 1234 ;", result.source)
        self.assertIn("int le = 1234 ;", result.source)
        self.assertIn("int be = 4321 ;", result.source)
        self.assertIn("int fwo = 1234 ;", result.source)
        self.assertIn("int ww = 32 ;", result.source)
        self.assertIn("int wiw = 32 ;", result.source)
        self.assertIn("int wmax = 2147483647 ;", result.source)
        self.assertIn("int wmin = - 2147483648 ;", result.source)
        self.assertIn("unsigned int wimax = 4294967295U ;", result.source)
        self.assertIn("unsigned int wimin = 0U ;", result.source)
        self.assertIn("int saw = 32 ;", result.source)
        self.assertIn("int samax = 2147483647 ;", result.source)
        self.assertIn("int samin = - 2147483648 ;", result.source)
        self.assertIn("long iso = 201706L ;", result.source)
        self.assertIn("long long llmax = 9223372036854775807LL ;", result.source)
        self.assertIn("long long llmin = - 9223372036854775808LL ;", result.source)
        self.assertIn("long long imx = 9223372036854775807LL ;", result.source)
        self.assertIn("long long imn = - 9223372036854775808LL ;", result.source)
        self.assertIn("unsigned long long umx = 18446744073709551615ULL ;", result.source)
        self.assertIn("long long imc = 123LL ;", result.source)
        self.assertIn("unsigned long long umc = 456ULL ;", result.source)
        self.assertIn('const char * bf = "main.c" ;', result.source)
        self.assertIn('const char * fn = "main.c" ;', result.source)
        self.assertIn("unsigned long n ;", result.source)
        self.assertIn("long d ;", result.source)
        self.assertIn("long ip ;", result.source)
        self.assertIn("unsigned long up ;", result.source)
        self.assertIn("int wc ;", result.source)
        self.assertIn("unsigned int wi ;", result.source)

    def test_predefined_file_and_line_macros(self) -> None:
        result = preprocess_source(
            'const char *f = __FILE__;\nconst char *n = __FILE_NAME__;\nconst char *b = __BASE_FILE__;\nint l = __LINE__;\n#line 42 "mapped/path.c"\nint m = __LINE__;\nconst char *nm = __FILE_NAME__;\nconst char *bm = __BASE_FILE__;\n',
            filename="main.c",
        )
        self.assertIn('const char * f = "main.c" ;', result.source)
        self.assertIn('const char * n = "main.c" ;', result.source)
        self.assertIn('const char * b = "main.c" ;', result.source)
        self.assertIn("int l = 4 ;", result.source)
        self.assertIn("int m = 42 ;", result.source)
        self.assertIn('const char * nm = "path.c" ;', result.source)
        self.assertIn('const char * bm = "main.c" ;', result.source)
        self.assertEqual(result.line_map[-1], ("mapped/path.c", 44))

    def test_predefined_include_level_macro_tracks_nested_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "leaf.h").write_text("int leaf = __INCLUDE_LEVEL__;\n", encoding="utf-8")
            (root / "mid.h").write_text(
                '#include "leaf.h"\nint mid = __INCLUDE_LEVEL__;\n',
                encoding="utf-8",
            )
            source_path = root / "main.c"
            source_path.write_text('#include "mid.h"\nint top = __INCLUDE_LEVEL__;\n', encoding="utf-8")
            result = preprocess_source(source_path.read_text(encoding="utf-8"), filename=str(source_path))

        self.assertIn("int leaf = 2 ;", result.source)
        self.assertIn("int mid = 1 ;", result.source)
        self.assertIn("int top = 0 ;", result.source)

    def test_predefined_counter_macro_increments_per_expansion(self) -> None:
        result = preprocess_source(
            "int c0 = __COUNTER__;\n"
            "#define NEXT __COUNTER__\n"
            "int c1 = NEXT;\n"
            "int c2 = __COUNTER__;\n",
            filename="main.c",
        )
        self.assertIn("int c0 = 0 ;", result.source)
        self.assertIn("int c1 = 1 ;", result.source)
        self.assertIn("int c2 = 2 ;", result.source)

    def test_cli_undef_removes_predefined_include_level_macro(self) -> None:
        result = preprocess_source(
            "int level = __INCLUDE_LEVEL__;\n",
            filename="main.c",
            options=FrontendOptions(undefs=("__INCLUDE_LEVEL__",)),
        )
        self.assertEqual(result.source, "int level = __INCLUDE_LEVEL__;\n")

    def test_cli_undef_removes_predefined_counter_macro(self) -> None:
        result = preprocess_source(
            "int counter = __COUNTER__;\n",
            filename="main.c",
            options=FrontendOptions(undefs=("__COUNTER__",)),
        )
        self.assertEqual(result.source, "int counter = __COUNTER__;\n")

    def test_cli_undef_removes_predefined_intmax_constructor_macros(self) -> None:
        result = preprocess_source(
            "int a = __INTMAX_C(7);\nint b = __UINTMAX_C(9);\n",
            filename="main.c",
            options=FrontendOptions(undefs=("__INTMAX_C", "__UINTMAX_C")),
        )
        self.assertEqual(result.source, "int a = __INTMAX_C(7);\nint b = __UINTMAX_C(9);\n")

    def test_cli_undef_removes_predefined_base_file_macro(self) -> None:
        result = preprocess_source(
            "const char *base = __BASE_FILE__;\n",
            filename="main.c",
            options=FrontendOptions(undefs=("__BASE_FILE__",)),
        )
        self.assertEqual(result.source, "const char *base = __BASE_FILE__;\n")

    def test_cli_undef_removes_predefined_file_name_macro(self) -> None:
        result = preprocess_source(
            "const char *name = __FILE_NAME__;\n",
            filename="main.c",
            options=FrontendOptions(undefs=("__FILE_NAME__",)),
        )
        self.assertEqual(result.source, "const char *name = __FILE_NAME__;\n")

    def test_cli_undef_removes_predefined_timestamp_macro(self) -> None:
        result = preprocess_source(
            "const char *stamp = __TIMESTAMP__;\n",
            filename="main.c",
            options=FrontendOptions(undefs=("__TIMESTAMP__",)),
        )
        self.assertEqual(result.source, "const char *stamp = __TIMESTAMP__;\n")

    def test_predefined_date_time_and_timestamp_macros_use_translation_start_time(self) -> None:
        with patch("xcc.preprocessor.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 2, 23, 22, 21, 9)
            result = preprocess_source(
                'const char *d = __DATE__;\nconst char *t = __TIME__;\nconst char *ts = __TIMESTAMP__;\n',
                filename="main.c",
            )
        self.assertIn('const char * d = "Feb 23 2026" ;', result.source)
        self.assertIn('const char * t = "22:21:09" ;', result.source)
        self.assertIn('const char * ts = "Mon Feb 23 22:21:09 2026" ;', result.source)
        self.assertIn('__DATE__="Feb 23 2026"', result.macro_table)
        self.assertIn('__TIME__="22:21:09"', result.macro_table)
        self.assertIn('__TIMESTAMP__="Mon Feb 23 22:21:09 2026"', result.macro_table)

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

    def test_include_trace_uses_line_mapped_source_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text("int x;\n", encoding="utf-8")
            source = '#line 41 "mapped.c"\n#include "inc.h"\n'
            result = preprocess_source(source, filename=str(root / "main.c"))
        self.assertEqual(len(result.include_trace), 1)
        self.assertIn("mapped.c:41: #include", result.include_trace[0])

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
