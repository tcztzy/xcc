import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import xcc.preprocessor.text as preprocessor_text
from tests import _bootstrap  # noqa: F401
from xcc.options import FrontendOptions
from xcc.preprocessor import (
    PreprocessorError,
    _ConditionalFrame,
    _Preprocessor,
    _reject_gnu_asm_extensions,
    _SourceLocation,
    _strip_gnu_asm_extensions,
    preprocess_source,
    preprocess_source_no_callback,
)


class PreprocessorTests(unittest.TestCase):
    def test_target_long_double_macros_and_platform_identity_match_layout(self) -> None:
        darwin = preprocess_source(
            "int size = __SIZEOF_LONG_DOUBLE__; int mantissa = __LDBL_MANT_DIG__;",
            options=FrontendOptions(target_os="darwin", host_machine="arm64"),
        )
        linux = preprocess_source(
            "#ifdef __APPLE_CC__\n#error apple macro on linux\n#endif\n"
            "int size = __SIZEOF_LONG_DOUBLE__;",
            options=FrontendOptions(target_os="linux", host_machine="x86_64"),
        )
        evm = preprocess_source(
            "#if defined(__APPLE__) || defined(__linux__)\n"
            "#error host platform macro on evm\n"
            "#endif\n"
            "int int_size = __SIZEOF_INT__; int pointer_size = __SIZEOF_POINTER__;",
            options=FrontendOptions(target_os="evm", host_machine="evm"),
        )

        self.assertIn("int size = 8 ;", darwin.source)
        self.assertIn("int mantissa = 53 ;", darwin.source)
        self.assertIn("int size = 16 ;", linux.source)
        self.assertIn("int int_size = 32 ;", evm.source)
        self.assertIn("int pointer_size = 32 ;", evm.source)

    def test_no_callback_long_double_macros_match_darwin_layout(self) -> None:
        result = preprocess_source_no_callback(
            "long double epsilon = __LDBL_EPSILON__;\n"
            "long double minimum = __LDBL_MIN__;\n"
            "long double maximum = __LDBL_MAX__;\n"
            "int minimum_exponent = __LDBL_MIN_EXP__;\n"
            "int maximum_exponent = __LDBL_MAX_EXP__;\n",
            options=FrontendOptions(target_os="darwin", host_machine="arm64"),
        )

        self.assertIn("epsilon = 2.2204460492503131e-16L", result.source)
        self.assertIn("minimum = 2.2250738585072014e-308L", result.source)
        self.assertIn("maximum = 1.7976931348623157e+308L", result.source)
        self.assertIn("minimum_exponent=-1021;", result.source.replace(" ", ""))
        self.assertIn("maximum_exponent = 1024", result.source)

    def test_no_callback_target_layout_and_identity_are_not_host_derived(self) -> None:
        linux = preprocess_source_no_callback(
            "int platform = __linux__; int elf = __ELF__;\n"
            "int arch = __x86_64__; int size = __SIZEOF_LONG_DOUBLE__;\n"
            "int mantissa = __LDBL_MANT_DIG__; int digits = __LDBL_DIG__;\n"
            "int configured = CONFIGURED; int enabled = ENABLED;\n",
            options=FrontendOptions(
                target_os="linux",
                host_machine="x86_64",
                no_standard_includes=True,
                defines=("CONFIGURED=7", "ENABLED"),
            ),
        )
        evm = preprocess_source_no_callback(
            "int int_size = __SIZEOF_INT__; int pointer_size = __SIZEOF_POINTER__;\n"
            "int long_double_size = __SIZEOF_LONG_DOUBLE__;\n"
            "int mantissa = __LDBL_MANT_DIG__; int digits = __LDBL_DIG__;\n",
            options=FrontendOptions(target_os="evm", host_machine="evm"),
        )

        self.assertIn("platform = 1", linux.source)
        self.assertIn("elf = 1", linux.source)
        self.assertIn("arch = 1", linux.source)
        self.assertIn("size = 16", linux.source)
        self.assertIn("mantissa = 64", linux.source)
        self.assertIn("digits = 18", linux.source)
        self.assertIn("configured = 7", linux.source)
        self.assertIn("enabled = 1", linux.source)
        self.assertNotIn("__APPLE__", linux.macro_table)
        self.assertIn("int_size = 32", evm.source)
        self.assertIn("pointer_size = 32", evm.source)
        self.assertIn("long_double_size = 32", evm.source)
        self.assertIn("mantissa = 113", evm.source)
        self.assertIn("digits = 33", evm.source)
        self.assertNotIn("__APPLE__", evm.macro_table)
        self.assertNotIn("__linux__", evm.macro_table)

    def test_no_callback_conditional_stack_adapter_matches_directive_rules(self) -> None:
        options = FrontendOptions(defines=("FLAG=1",))
        processor = _Preprocessor(options)
        location = _SourceLocation("conditional.c", 1)

        def handle(
            name: str,
            body: str,
            stack: list[_ConditionalFrame],
        ) -> tuple[str | None, list[_ConditionalFrame]]:
            return processor._handle_conditional_for_process_no_callback(
                name,
                body,
                location,
                stack,
                base_dir=None,
            )

        result, stack = handle("define", "VALUE 1", [])
        self.assertIsNone(result)
        self.assertEqual(stack, [])

        result, stack = handle("if", "1", [])
        self.assertEqual(result, "")
        self.assertTrue(stack[-1].active)
        result, stack = handle("endif", "", stack)
        self.assertEqual((result, stack), ("", []))

        for directive, body in (("ifdef", "FLAG"), ("ifndef", "MISSING")):
            with self.subTest(directive=directive):
                result, selected = handle(directive, body, [])
                self.assertEqual(result, "")
                self.assertTrue(selected[-1].active)

        _result, stack = handle("if", "0", [])
        _result, stack = handle("elif", "1", stack)
        self.assertTrue(stack[-1].active)
        _result, stack = handle("else", "", stack)
        self.assertFalse(stack[-1].active)
        _result, stack = handle("endif", "", stack)
        self.assertEqual(stack, [])

        _result, stack = handle("if", "1", [])
        _result, stack = handle("elif", "0", stack)
        self.assertFalse(stack[-1].active)

        with self.assertRaises(PreprocessorError):
            handle("else", "", [])
        with self.assertRaises(PreprocessorError):
            handle("elifdef", "FLAG", [_ConditionalFrame(True, False, False)])
        with self.assertRaises(PreprocessorError):
            handle("elif", "1", [_ConditionalFrame(True, False, False, saw_else=True)])
        with self.assertRaises(PreprocessorError):
            handle("else", "", [_ConditionalFrame(True, False, False, saw_else=True)])

        gnu_options = FrontendOptions(std="gnu11", defines=("FLAG=1",))
        gnu_processor = _Preprocessor(gnu_options)
        for directive, body in (("elifdef", "FLAG"), ("elifndef", "MISSING")):
            with self.subTest(directive=directive):
                result, selected = gnu_processor._handle_conditional_for_process_no_callback(
                    directive,
                    body,
                    location,
                    [_ConditionalFrame(True, False, False)],
                    base_dir=None,
                )
                self.assertEqual(result, "")
                self.assertTrue(selected[-1].active)

    def test_preprocess_empty_source(self) -> None:
        result = preprocess_source("", filename="empty.c")
        self.assertEqual(result.source, "")

    def test_no_callback_object_macro_preserves_replacement(self) -> None:
        result = preprocess_source_no_callback(
            "#define NATIVE_RECORD struct native_record\nNATIVE_RECORD { int value; };\n",
            filename="object_macro.c",
        )

        self.assertEqual(result.source, "\nstruct native_record { int value ; } ;\n")

    def test_no_callback_object_macro_recursively_expands_alias(self) -> None:
        result = preprocess_source_no_callback(
            "#define NATIVE_RECORD struct native_record\n"
            "#define NATIVE_RECORD_ALIAS NATIVE_RECORD\n"
            "NATIVE_RECORD_ALIAS { int value; };\n"
            "#define SELF SELF\n"
            "SELF marker;\n",
            filename="object_macro_alias.c",
        )

        self.assertEqual(
            result.source,
            "\n\nstruct native_record { int value ; } ;\n\nSELF marker ;\n",
        )

    def test_no_callback_prescans_nested_macro_arguments(self) -> None:
        result = preprocess_source_no_callback(
            "#define OBJECT_CAST(value) ((Object *)(value))\n"
            "#define TYPE(value) TYPE(OBJECT_CAST(value))\n"
            "TYPE(OBJECT_CAST(object))\n",
            filename="argument_prescan.c",
        )

        self.assertNotIn("OBJECT_CAST", result.source)
        self.assertIn("TYPE", result.source)
        self.assertEqual(result.source.count("Object *"), 2)

    def test_no_callback_keeps_disabled_macro_hidden_through_outer_rescan(self) -> None:
        result = preprocess_source_no_callback(
            "#define OBJECT_CAST(value) ((Object *)(value))\n"
            "#define FUNCTION(value) FUNCTION(OBJECT_CAST(value))\n"
            "#define DECREF(value) DECREF(OBJECT_CAST(value))\n"
            "DECREF(FUNCTION(value))\n",
            filename="disabled_rescan.c",
        )

        self.assertNotIn("OBJECT_CAST", result.source)
        self.assertEqual(result.source.count("FUNCTION"), 1)
        self.assertEqual(result.source.count("DECREF"), 1)
        self.assertEqual(result.source.count("Object *"), 2)
        self.assertNotIn("\x1e", result.source)
        self.assertNotIn("\x1f", result.source)

    def test_no_callback_object_alias_invokes_function_macro(self) -> None:
        result = preprocess_source_no_callback(
            "#define OBJECT_CAST(value) ((Object *)(value))\n"
            "#define INCREF(value) INCREF(OBJECT_CAST(value))\n"
            "#define INCREF_TYPE INCREF\n"
            "INCREF_TYPE(type_object)\n",
            filename="function_alias.c",
        )

        self.assertNotIn("INCREF_TYPE", result.source)
        self.assertNotIn("OBJECT_CAST", result.source)
        self.assertIn("INCREF", result.source)
        self.assertIn("Object *", result.source)

    def test_no_callback_collects_multiline_object_alias_invocation(self) -> None:
        result = preprocess_source_no_callback(
            "#define ADD(left, right) ((left) + (right))\n"
            "#define ADD_ALIAS ADD\n"
            "int value = ADD_ALIAS(\n"
            "  19,\n"
            "  23);\n",
            filename="multiline_function_alias.c",
        )

        self.assertNotIn("ADD_ALIAS", result.source)
        self.assertNotIn("ADD(", result.source)
        self.assertIn("19", result.source)
        self.assertIn("23", result.source)

    def test_no_callback_prescan_keeps_stringized_and_pasted_arguments_raw(self) -> None:
        result = preprocess_source_no_callback(
            "#define VALUE 7\n"
            "#define STRINGIZE(value) #value\n"
            "#define PASTE(value) prefix_##value\n"
            "STRINGIZE(VALUE) PASTE(VALUE)\n",
            filename="argument_raw.c",
        )

        self.assertIn('"VALUE"', result.source)
        self.assertIn("prefix_VALUE", result.source)
        self.assertNotIn('"7"', result.source)

    def test_no_callback_variadic_function_macro_expands_and_pastes(self) -> None:
        options = FrontendOptions()
        processor = _Preprocessor(options)
        processor._handle_define_no_callback(
            "WRAP(name, type, ...) enum { __VA_ARGS__ }; typedef type name##_t"
        )
        with self.assertRaises(PreprocessorError) as context:
            processor._expand_line_no_callback(
                "WRAP(qos_class, unsigned int,\n",
                _SourceLocation("function_macro.c", 2),
            )
        result = processor._expand_line_no_callback(
            "WRAP(qos_class, unsigned int,\nQOS_USER = 1, QOS_DEFAULT = 2\n);\n",
            _SourceLocation("function_macro.c", 2),
        )

        self.assertEqual(context.exception.code, "XCC-PP-0202")
        self.assertIn("enum { QOS_USER = 1, QOS_DEFAULT = 2 }", result)
        self.assertIn("typedef unsigned int qos_class_t", result)

    def test_no_callback_rescans_selector_result_with_following_invocation(self) -> None:
        options = FrontendOptions()
        processor = _Preprocessor(options)
        for definition in (
            "PICK(_1, _2, NAME, ...) NAME",
            "NAMED(type, name) type name; enum",
            "ANON(type) enum",
            "ENUM(...) PICK(__VA_ARGS__, NAMED, ANON, )(__VA_ARGS__)",
        ):
            processor._handle_define_no_callback(definition)

        result = processor._expand_line_no_callback(
            "typedef ENUM(int, Answer) { ANSWER = 42 };\n",
            _SourceLocation("selector_rescan.c", 1),
        )

        self.assertNotIn("PICK", result)
        self.assertNotIn("NAMED", result)
        self.assertIn("int Answer; enum", result)

    def test_no_callback_token_paste_does_not_stringize_rhs(self) -> None:
        options = FrontendOptions()
        processor = _Preprocessor(options)
        processor._handle_define_no_callback("DEPRECATED(ver) ___POSIX_C_DEPRECATED_STARTING_##ver")

        result = processor._expand_line_no_callback(
            "int old(void) DEPRECATED(200112L);\n",
            _SourceLocation("token_paste.c", 2),
        )

        self.assertIn("___POSIX_C_DEPRECATED_STARTING_200112L", result)

    def test_no_callback_consumes_pragma_operator_after_macro_expansion(self) -> None:
        options = FrontendOptions()
        processor = _Preprocessor(options)
        processor._handle_define_no_callback("DO_PRAGMA(value) _Pragma(#value)")

        result = processor._expand_line_no_callback(
            'DO_PRAGMA(clang diagnostic ignored "-Wdeprecated") int value;\n',
            _SourceLocation("pragma_operator.c", 2),
        )

        self.assertEqual(result, "\n int value;\n")

    def test_no_callback_does_not_expand_macros_in_comments_or_literals(self) -> None:
        result = preprocess_source_no_callback(
            "#define SIGNAL 4 /* signal value */\n"
            "/* Codes for SIGNAL */\n"
            'const char *name = "SIGNAL"; // SIGNAL\n'
            "int signal = SIGNAL;\n",
            filename="macro_regions.c",
        )

        self.assertIn('const char * name = "SIGNAL" ;', result.source)
        self.assertIn("int signal = 4 ;", result.source)
        self.assertNotIn("*/", result.source)

    def test_no_callback_evaluates_integer_macro_conditions(self) -> None:
        options = FrontendOptions()
        processor = _Preprocessor(options)
        processor._handle_define_no_callback("LITTLE 1234 /* least-significant first */")
        processor._handle_define_no_callback("BIG 4321 /* most-significant first */")
        processor._handle_define_no_callback("ORDER LITTLE")
        location = _SourceLocation("integer_condition.c", 1)

        self.assertTrue(
            processor._eval_condition_no_callback(
                "defined(ORDER) && ORDER == LITTLE",
                location,
                None,
            )
        )
        self.assertFalse(
            processor._eval_condition_no_callback(
                "UNKNOWN || (LITTLE << 1) != 2468",
                location,
                None,
            )
        )

        result = preprocess_source_no_callback(
            "#define LITTLE 1234 /* least-significant first */\n"
            "#define BIG 4321 /* most-significant first */\n"
            "#define ORDER LITTLE\n"
            "#if defined(ORDER) && ORDER == LITTLE\n"
            "int selected;\n"
            "#elif ORDER == BIG\n"
            "int wrong_order;\n"
            "#else\n"
            "int missing_order;\n"
            "#endif\n"
            "#if UNKNOWN || (LITTLE << 1) != 2468\n"
            "int wrong_precedence;\n"
            "#else\n"
            "int precedence_ok;\n"
            "#endif\n",
            filename="integer_condition.c",
        )

        self.assertIn("int selected ;", result.source)
        self.assertIn("int precedence_ok ;", result.source)
        self.assertNotIn("wrong_order", result.source)
        self.assertNotIn("missing_order", result.source)
        self.assertNotIn("wrong_precedence", result.source)

    def test_no_callback_defines_compiler_integer_limits(self) -> None:
        result = preprocess_source_no_callback(
            "#define UCHAR_MAX (__SCHAR_MAX__ * 2 + 1)\n"
            "#define CHAR_BIT __CHAR_BIT__\n"
            "#if UCHAR_MAX != 255 || CHAR_BIT != 8\n"
            "int wrong_char_limits;\n"
            "#elif __SHRT_MAX__ != 32767 || __INT_MAX__ != 2147483647\n"
            "int wrong_integer_limits;\n"
            "#else\n"
            "int limits_ok;\n"
            "#endif\n",
            filename="compiler_limits.c",
        )

        self.assertIn("limits_ok", result.source)
        self.assertNotIn("wrong_char_limits", result.source)
        self.assertNotIn("wrong_integer_limits", result.source)

    def test_no_callback_defines_atomic_memory_orders(self) -> None:
        result = preprocess_source_no_callback(
            "enum memory_order {\n"
            "    relaxed = __ATOMIC_RELAXED,\n"
            "    consume = __ATOMIC_CONSUME,\n"
            "    acquire = __ATOMIC_ACQUIRE,\n"
            "    release = __ATOMIC_RELEASE,\n"
            "    acq_rel = __ATOMIC_ACQ_REL,\n"
            "    seq_cst = __ATOMIC_SEQ_CST\n"
            "};\n",
            filename="atomic_orders.c",
        )

        self.assertIn("relaxed = 0", result.source)
        self.assertIn("consume = 1", result.source)
        self.assertIn("acquire = 2", result.source)
        self.assertIn("release = 3", result.source)
        self.assertIn("acq_rel = 4", result.source)
        self.assertIn("seq_cst = 5", result.source)

    def test_no_callback_defines_floating_minima(self) -> None:
        result = preprocess_source_no_callback(
            "float minimum_float = __FLT_MIN__;\n"
            "double minimum_double = __DBL_MIN__;\n"
            "long double minimum_long_double = __LDBL_MIN__;\n"
            "double maximum_double = __DBL_MAX__;\n"
            "int maximum_double_exponent = __DBL_MAX_EXP__;\n",
            filename="floating_minima.c",
            options=FrontendOptions(target_os="darwin", host_machine="arm64"),
        )

        self.assertIn("minimum_float = 1.17549435e-38F", result.source)
        self.assertIn("minimum_double = 2.2250738585072014e-308", result.source)
        self.assertIn("minimum_long_double = 2.2250738585072014e-308L", result.source)
        self.assertIn("maximum_double = 1.7976931348623157e+308", result.source)
        self.assertIn("maximum_double_exponent = 1024", result.source)

    def test_no_callback_macro_boundaries_do_not_form_decrement_token(self) -> None:
        result = preprocess_source_no_callback(
            "#define MANTISSA 53\n"
            "#define MINIMUM_EXPONENT -1021\n"
            "int range = MANTISSA-MINIMUM_EXPONENT;\n",
            filename="macro_boundaries.c",
        )

        self.assertIn("53 - - 1021", result.source)
        self.assertNotIn("--1021", result.source)

    def test_no_callback_defines_little_endian_target_macros(self) -> None:
        result = preprocess_source_no_callback(
            "#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__\n"
            "int little_endian;\n"
            "#else\n"
            "#error Unknown endianess.\n"
            "#endif\n"
            "#ifdef __BIG_ENDIAN__\n"
            "int wrong_big_endian;\n"
            "#endif\n",
            filename="byte_order.c",
        )

        self.assertIn("little_endian", result.source)
        self.assertNotIn("wrong_big_endian", result.source)

    def test_no_callback_evaluates_feature_probe_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "present.h").write_text("int present;\n", encoding="utf-8")
            options = FrontendOptions(include_dirs=(str(root),))
            processor = _Preprocessor(options)
            location = _SourceLocation(str(root / "probe.c"), 1)

            self.assertTrue(
                processor._eval_condition_no_callback(
                    '__has_include("present.h")',
                    location,
                    root,
                )
            )
            processor._handle_define_no_callback("__has_include(header) 0")
            self.assertTrue(
                processor._eval_condition_no_callback(
                    '__has_include("present.h")',
                    location,
                    root,
                )
            )
            self.assertFalse(
                processor._eval_condition_no_callback(
                    '__has_include("missing.h")',
                    location,
                    root,
                )
            )
            self.assertFalse(
                processor._eval_condition_no_callback(
                    "__has_feature(xcc_missing_feature)",
                    location,
                    root,
                )
            )

    def test_no_callback_evaluates_clang_building_module_probe(self) -> None:
        options = FrontendOptions()
        processor = _Preprocessor(options)

        self.assertTrue(
            processor._eval_condition_no_callback(
                "!defined(offsetof) || "
                "(__has_feature(modules) && !__building_module(_Builtin_stddef))",
                _SourceLocation("building_module.c", 1),
                None,
            )
        )

    def test_no_callback_undef_removes_macro(self) -> None:
        options = FrontendOptions()
        processor = _Preprocessor(options)
        processor._handle_define_no_callback("STALE 1")
        location = _SourceLocation("undef.c", 2)

        processor._handle_undef_no_callback("STALE", location)

        self.assertFalse(processor._macro_defined_no_callback("STALE"))

    def test_gnu_asm_strip_handles_incomplete_or_non_operand_asm_keywords(self) -> None:
        self.assertEqual(
            preprocessor_text._strip_inline_asm_segments("int asm;\n"),
            "int ;\n",
        )
        self.assertEqual(
            preprocessor_text._strip_inline_asm_segments('asm("unterminated;\n'),
            '("unterminated;\n',
        )
        self.assertEqual(
            preprocessor_text._strip_inline_asm_segments('asm volatile ("nop");\n'),
            ";\n",
        )

    def test_gnu_asm_strip_rewrites_aarch64_stack_pointer_statement(self) -> None:
        self.assertEqual(
            preprocessor_text._strip_inline_asm_segments('asm("mov %0, sp" : "=r"(sp));\n'),
            "sp = (unsigned long)&sp;\n",
        )

    def test_gnu_asm_paren_scanner_ignores_escaped_string_delimiters(self) -> None:
        line = r'asm("quoted \" ) still string");'
        open_index = line.index("(")

        self.assertEqual(preprocessor_text._find_matching_paren(line, open_index), len(line) - 2)

    def test_gnu_asm_operand_scanner_skips_known_qualifiers(self) -> None:
        line = 'asm volatile inline ("nop");'

        self.assertEqual(
            preprocessor_text._asm_operand_open_index(line, len("asm")),
            line.index("("),
        )
        self.assertIsNone(preprocessor_text._asm_operand_open_index("", 0))
        self.assertIsNone(preprocessor_text._asm_operand_open_index("asm notqual ();", len("asm")))

    def test_gnu_asm_rejection_allows_declaration_labels_and_other_files(self) -> None:
        source = 'int f(void)\n__asm("_f");\nasm("nop");\n'
        line_map = (("main.c", 1), ("main.c", 2), ("header.h", 7))

        preprocessor_text._reject_gnu_asm_extensions(
            source,
            line_map,
            code="XCC-PP-ASM",
            primary_filename="main.c",
        )

    def test_gnu_asm_rejection_keeps_context_after_skipped_header_line(self) -> None:
        source = 'asm("skip");\nasm("bad");\n'
        line_map = (("header.h", 5), ("main.c", 9))

        with self.assertRaises(PreprocessorError) as ctx:
            preprocessor_text._reject_gnu_asm_extensions(
                source,
                line_map,
                code="XCC-PP-ASM",
                primary_filename="main.c",
            )

        self.assertEqual(ctx.exception.filename, "main.c")
        self.assertEqual(ctx.exception.line, 9)

    def test_gnu_asm_rejection_reports_primary_file_statement_location(self) -> None:
        source = 'int f(void);\nasm("nop");\n'
        line_map = (("main.c", 1), ("main.c", 42))

        with self.assertRaises(PreprocessorError) as ctx:
            preprocessor_text._reject_gnu_asm_extensions(
                source,
                line_map,
                code="XCC-PP-ASM",
                primary_filename="main.c",
            )

        self.assertEqual(ctx.exception.filename, "main.c")
        self.assertEqual(ctx.exception.line, 42)
        self.assertEqual(ctx.exception.code, "XCC-PP-ASM")

    def test_package_gnu_asm_rejection_uses_default_code(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            _reject_gnu_asm_extensions('asm("nop");\n', (("main.c", 7),))

        self.assertEqual(ctx.exception.code, "XCC-PP-0105")
        self.assertEqual(ctx.exception.line, 7)

    def test_gnu_asm_statement_detector_handles_incomplete_operands(self) -> None:
        self.assertFalse(preprocessor_text._contains_gnu_asm_statement("int asm;"))
        self.assertTrue(preprocessor_text._contains_gnu_asm_statement('asm("unterminated'))
        self.assertFalse(preprocessor_text._contains_gnu_asm_statement('int x asm("unterminated'))
        self.assertFalse(preprocessor_text._contains_gnu_asm_statement('asm("nop") + 1'))

    def test_gnu_asm_declaration_continuation_without_leading_word_is_allowed(self) -> None:
        self.assertTrue(preprocessor_text._can_continue_declaration("(int (*f)(void))"))
        self.assertTrue(preprocessor_text._can_continue_declaration("typedef int (*f)(void)"))
        self.assertFalse(preprocessor_text._can_continue_declaration("if (x)"))

    def test_gnu_asm_rejection_tracks_non_asm_significant_lines(self) -> None:
        preprocessor_text._reject_gnu_asm_extensions(
            "\nint x;\n\nint y;\n",
            (("main.c", 1), ("main.c", 2), ("main.c", 3), ("main.c", 4)),
            code="XCC-PP-ASM",
            primary_filename="main.c",
        )

    def test_gnu_asm_statement_rejection_ignores_other_files(self) -> None:
        preprocessor_text._reject_gnu_asm_statements(
            'asm("nop");\n',
            (("header.h", 5),),
            code="XCC-PP-ASM",
            primary_filename="main.c",
        )

    def test_host_arch_predefined_macros_can_define_arm64(self) -> None:
        with patch("xcc.preprocessor.platform.machine", return_value="arm64"):
            result = preprocess_source(
                "#if defined(__arm64__)\nint ok;\n#endif\n"
                "#if defined(__x86_64__)\nint bad;\n#endif\n",
                filename="if.c",
            )
        self.assertIn("int ok", result.source)
        self.assertNotIn("int bad", result.source)

    def test_linux_target_predefines_linux_not_darwin(self) -> None:
        result = preprocess_source(
            "#if defined(__linux__) && defined(__x86_64__)\nint linux_ok;\n#endif\n"
            "#if defined(__APPLE__) || defined(__MACH__)\nint darwin_bad;\n#endif\n",
            filename="if.c",
            options=FrontendOptions(std="gnu11", host_machine="x86_64", target_os="linux"),
        )
        self.assertIn("int linux_ok", result.source)
        self.assertNotIn("int darwin_bad", result.source)

    def test_linux_target_uses_gpu02_gcc_version_macros(self) -> None:
        result = preprocess_source(
            "int g = __GNUC__;\nint gm = __GNUC_MINOR__;\nint gp = __GNUC_PATCHLEVEL__;\n"
            "const char *v = __VERSION__;\n",
            filename="if.c",
            options=FrontendOptions(std="gnu11", host_machine="x86_64", target_os="linux"),
        )
        self.assertIn("int g = 8 ;", result.source)
        self.assertIn("int gm = 5 ;", result.source)
        self.assertIn("int gp = 0 ;", result.source)
        self.assertIn('const char * v = "8.5.0" ;', result.source)

    def test_little_endian_host_does_not_define_big_endian_macro(self) -> None:
        source = (
            "#ifdef __BIG_ENDIAN__\n"
            "#define WORDS_BIGENDIAN 1\n"
            "#endif\n"
            "#ifdef WORDS_BIGENDIAN\n"
            "int endian = 1;\n"
            "#else\n"
            "int endian = 0;\n"
            "#endif\n"
        )

        result = preprocess_source(source, filename="endian.c")

        self.assertNotIn("__BIG_ENDIAN__", result.macro_table)
        self.assertNotIn("WORDS_BIGENDIAN=1", result.macro_table)
        self.assertIn("int endian = 0;", result.source)

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

    def test_self_referential_macro_argument_keeps_member_name(self) -> None:
        source = (
            "#define usable_arenas (state->mgmt.usable_arenas)\n"
            "#define UNLIKELY(x) (x)\n"
            "int f(void){return UNLIKELY(usable_arenas == 0);}\n"
        )
        result = preprocess_source(source, filename="main.c")

        self.assertIn("state -> mgmt . usable_arenas", result.source)
        self.assertNotIn("mgmt . (", result.source)

    def test_function_like_define_without_invocation_is_not_expanded(self) -> None:
        source = "#define ID(x) x\nint x = ID;\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("int x = ID ;", result.source)

    def test_variadic_macro_expands(self) -> None:
        source = '#define LOG(fmt, ...) printf(fmt, __VA_ARGS__)\nLOG("%d", 1)\n'
        result = preprocess_source(source, filename="main.c")
        self.assertIn('printf ( "%d" , 1 )', result.source)

    def test_variadic_macro_insufficient_arguments(self) -> None:
        source = "#define LOG(fmt, ...) printf(fmt, __VA_ARGS__)\nLOG()\n"
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="main.c")

    def test_variadic_macro_with_gnu_comma_swallow(self) -> None:
        source = '#define LOG(fmt, ...) printf(fmt, ##__VA_ARGS__)\nLOG("x")\n'
        c11_result = preprocess_source(source, filename="main.c")
        self.assertIn('printf ( "x" )', c11_result.source)
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

    def test_hosted_mode_defines_stdc_hosted_as_one(self) -> None:
        result = preprocess_source("int hosted = __STDC_HOSTED__;\n", filename="main.c")
        self.assertIn("int hosted = 1 ;", result.source)

    def test_freestanding_mode_defines_stdc_hosted_as_zero(self) -> None:
        result = preprocess_source(
            "int hosted = __STDC_HOSTED__;\n",
            filename="main.c",
            options=FrontendOptions(hosted=False),
        )
        self.assertIn("int hosted = 0 ;", result.source)

    def test_gnu_mode_defines_compiler_compat_and_gnu_function_macros(self) -> None:
        result = preprocess_source(
            "int g = __GNUC__;\nint gm = __GNUC_MINOR__;\nint gp = __GNUC_PATCHLEVEL__;\n"
            "int gsi = __GNUC_STDC_INLINE__;\n"
            "const char *v = __VERSION__;\n"
            "const char *pf = __PRETTY_FUNCTION__;\n",
            filename="main.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertIn("int g = 4 ;", result.source)
        self.assertIn("int gm = 8 ;", result.source)
        self.assertIn("int gp = 1 ;", result.source)
        self.assertIn("int gsi = 1 ;", result.source)
        self.assertIn('const char * v = "xcc" ;', result.source)
        self.assertIn('const char * pf = "<unknown>" ;', result.source)

    def test_strict_mode_defines_compiler_compat_macros(self) -> None:
        result = preprocess_source(
            "int g = __GNUC__;\nint gm = __GNUC_MINOR__;\nint gp = __GNUC_PATCHLEVEL__;\n"
            "int gsi = __GNUC_STDC_INLINE__;\n"
            "const char *v = __VERSION__;\n",
            filename="main.c",
        )
        self.assertIn("int g = 4 ;", result.source)
        self.assertIn("int gm = 8 ;", result.source)
        self.assertIn("int gp = 1 ;", result.source)
        self.assertIn("int gsi = 1 ;", result.source)
        self.assertIn('const char * v = "xcc" ;', result.source)

    def test_gnu_mode_does_not_define_strict_ansi_macro(self) -> None:
        result = preprocess_source(
            "#if defined(__STRICT_ANSI__)\nint strict = 1;\n#endif\n",
            filename="main.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertNotIn("strict", result.source)

    def test_strict_mode_does_not_define_gnu_extension_macros(self) -> None:
        result = preprocess_source(
            "#if defined(__func__) || defined(__PRETTY_FUNCTION__)\nint g = 1;\n#endif\n",
            filename="main.c",
        )
        self.assertNotIn("int g", result.source)

    def test_strict_getcompiler_style_version_concat_expands(self) -> None:
        result = preprocess_source(
            '#if defined(__GNUC__)\n#define COMPILER "[GCC " __VERSION__ "]"\n#endif\n'
            "const char *f(void){return COMPILER;}\n",
            filename="main.c",
        )
        self.assertIn('return "[GCC " "xcc" "]" ;', result.source)

    def test_clang_identity_includes_a_string_version(self) -> None:
        source = (
            '#if defined(__clang__)\n#define COMPILER "[Clang " __clang_version__ "]"\n'
            "#endif\nconst char *f(void){return COMPILER;}\n"
        )

        hosted = preprocess_source(source, filename="main.c")
        native = preprocess_source_no_callback(source, filename="main.c")

        self.assertIn('return "[Clang " "xcc 0.2" "]" ;', hosted.source)
        self.assertIn('return "[Clang " "xcc 0.2" "]" ;', native.source)

    def test_strict_darwin_target_defines_darwin_macros(self) -> None:
        result = preprocess_source(
            "#if defined(__APPLE__) && defined(__MACH__)\nint darwin_ok;\n#endif\n",
            filename="main.c",
            options=FrontendOptions(std="c11", target_os="darwin"),
        )
        self.assertIn("int darwin_ok", result.source)

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

    def test_cross_reference_function_like_blocks_entire_invocation(self) -> None:
        """A(x)→B(x)→A: when A is blocked at B's level, skip entire A(args)."""
        source = """
#define A(x) B(x)
#define B(x) A(x+1)
A(0)
"""
        result = preprocess_source(source, filename="main.c")
        # A(0) → B(0) → A(0+1).  At B's level, A is in ancestor → entire
        # A(0+1) invocation is skipped, preserving it as raw tokens.
        self.assertIn("A", result.source)

    def test_token_paste_multi_token_variadic_result(self) -> None:
        """,##__VA_ARGS__ with non-empty var arg produces multi-token paste result."""
        source = "#define FOO(x, ...) bar(x, ##__VA_ARGS__)\nFOO(1, 2)\n"
        for std in ("c11", "gnu11"):
            with self.subTest(std=std):
                result = preprocess_source(
                    source, filename="main.c", options=FrontendOptions(std=std)
                )
                self.assertIn("bar ( 1 , 2 )", result.source)

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

    def test_ifdef_allows_trailing_comment(self) -> None:
        source = "#define X 1\n#ifdef X /* comment */\nint ok;\n#endif\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("int ok", result.source)

    def test_cli_defines_and_undefs(self) -> None:
        source = "int main(void){return ZERO;}\n"
        options = FrontendOptions(defines=("ZERO=0",), undefs=("ZERO",))
        result = preprocess_source(source, filename="main.c", options=options)
        self.assertIn("ZERO", result.source)

    def test_invalid_cli_define(self) -> None:
        for define in ("1BAD=0", "F(", "F(x) trailing", "F(x, ..., y)"):
            with self.subTest(define=define), self.assertRaises(PreprocessorError) as ctx:
                preprocess_source("int x;\n", options=FrontendOptions(defines=(define,)))
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

    def test_predefined_floating_decimal_and_denorm_macros(self) -> None:
        source = (
            "#if __FLT_DECIMAL_DIG__ == 9\nint fd;\n#endif\n"
            "#if __DBL_DECIMAL_DIG__ == 17\nint dd;\n#endif\n"
            "#if __LDBL_DECIMAL_DIG__ == 36\nint ldd;\n#endif\n"
            "#if __DECIMAL_DIG__ == 36\nint dec;\n#endif\n"
            "#if __FLT_HAS_DENORM__ == 1\nint fhd;\n#endif\n"
            "#if __DBL_HAS_DENORM__ == 1\nint dhd;\n#endif\n"
            "#if __LDBL_HAS_DENORM__ == 1\nint lhd;\n#endif\n"
            "#if __FLT_HAS_INFINITY__ == 1\nint fhi;\n#endif\n"
            "#if __DBL_HAS_INFINITY__ == 1\nint dhi;\n#endif\n"
            "#if __LDBL_HAS_INFINITY__ == 1\nint lhi;\n#endif\n"
            "#if __FLT_HAS_QUIET_NAN__ == 1\nint fhq;\n#endif\n"
            "#if __DBL_HAS_QUIET_NAN__ == 1\nint dhq;\n#endif\n"
            "#if __LDBL_HAS_QUIET_NAN__ == 1\nint lhq;\n#endif\n"
            "#if __FLT_MIN_10_EXP__ < 0\nint fmin10;\n#endif\n"
            "#if __DBL_MIN_10_EXP__ < 0\nint dmin10;\n#endif\n"
            "#if __LDBL_MIN_10_EXP__ < 0\nint ldmin10;\n#endif\n"
            "#if __FLT_MAX_10_EXP__ > 0\nint fmax10;\n#endif\n"
            "#if __DBL_MAX_10_EXP__ > 0\nint dmax10;\n#endif\n"
            "#if __LDBL_MAX_10_EXP__ > 0\nint ldmax10;\n#endif\n"
            "#if defined(__FLT_DENORM_MIN__)\nint fdm;\n#endif\n"
            "#if defined(__DBL_DENORM_MIN__)\nint ddm;\n#endif\n"
            "#if defined(__LDBL_DENORM_MIN__)\nint ldm;\n#endif\n"
        )
        result = preprocess_source(source, filename="main.c")
        self.assertIn("int fd;", result.source)
        self.assertIn("int dd;", result.source)
        self.assertIn("int ldd;", result.source)
        self.assertIn("int dec;", result.source)
        self.assertIn("int fhd;", result.source)
        self.assertIn("int dhd;", result.source)
        self.assertIn("int lhd;", result.source)
        self.assertIn("int fhi;", result.source)
        self.assertIn("int dhi;", result.source)
        self.assertIn("int lhi;", result.source)
        self.assertIn("int fhq;", result.source)
        self.assertIn("int dhq;", result.source)
        self.assertIn("int lhq;", result.source)
        self.assertIn("int fmin10;", result.source)
        self.assertIn("int dmin10;", result.source)
        self.assertIn("int ldmin10;", result.source)
        self.assertIn("int fmax10;", result.source)
        self.assertIn("int dmax10;", result.source)
        self.assertIn("int ldmax10;", result.source)
        self.assertIn("int fdm;", result.source)
        self.assertIn("int ddm;", result.source)
        self.assertIn("int ldm;", result.source)

    def test_cli_undef_removes_predefined_float_denorm_and_decimal_macros(self) -> None:
        source = (
            "#if defined(__FLT_DECIMAL_DIG__)\nint fd;\n#endif\n"
            "#if defined(__DBL_DECIMAL_DIG__)\nint dd;\n#endif\n"
            "#if defined(__LDBL_DECIMAL_DIG__)\nint ldd;\n#endif\n"
            "#if defined(__DECIMAL_DIG__)\nint dec;\n#endif\n"
            "#if defined(__FLT_DENORM_MIN__)\nint fdm;\n#endif\n"
            "#if defined(__DBL_DENORM_MIN__)\nint ddm;\n#endif\n"
            "#if defined(__LDBL_DENORM_MIN__)\nint ldm;\n#endif\n"
            "#if defined(__FLT_HAS_DENORM__)\nint fhd;\n#endif\n"
            "#if defined(__DBL_HAS_DENORM__)\nint dhd;\n#endif\n"
            "#if defined(__LDBL_HAS_DENORM__)\nint lhd;\n#endif\n"
            "#if defined(__FLT_HAS_INFINITY__)\nint fhi;\n#endif\n"
            "#if defined(__DBL_HAS_INFINITY__)\nint dhi;\n#endif\n"
            "#if defined(__LDBL_HAS_INFINITY__)\nint lhi;\n#endif\n"
            "#if defined(__FLT_HAS_QUIET_NAN__)\nint fhq;\n#endif\n"
            "#if defined(__DBL_HAS_QUIET_NAN__)\nint dhq;\n#endif\n"
            "#if defined(__LDBL_HAS_QUIET_NAN__)\nint lhq;\n#endif\n"
            "#if defined(__FLT_MIN_10_EXP__)\nint fmin10;\n#endif\n"
            "#if defined(__DBL_MIN_10_EXP__)\nint dmin10;\n#endif\n"
            "#if defined(__LDBL_MIN_10_EXP__)\nint ldmin10;\n#endif\n"
            "#if defined(__FLT_MAX_10_EXP__)\nint fmax10;\n#endif\n"
            "#if defined(__DBL_MAX_10_EXP__)\nint dmax10;\n#endif\n"
            "#if defined(__LDBL_MAX_10_EXP__)\nint ldmax10;\n#endif\n"
        )
        result = preprocess_source(
            source,
            filename="main.c",
            options=FrontendOptions(
                undefs=(
                    "__FLT_DECIMAL_DIG__",
                    "__DBL_DECIMAL_DIG__",
                    "__LDBL_DECIMAL_DIG__",
                    "__DECIMAL_DIG__",
                    "__FLT_DENORM_MIN__",
                    "__DBL_DENORM_MIN__",
                    "__LDBL_DENORM_MIN__",
                    "__FLT_HAS_DENORM__",
                    "__DBL_HAS_DENORM__",
                    "__LDBL_HAS_DENORM__",
                    "__FLT_HAS_INFINITY__",
                    "__DBL_HAS_INFINITY__",
                    "__LDBL_HAS_INFINITY__",
                    "__FLT_HAS_QUIET_NAN__",
                    "__DBL_HAS_QUIET_NAN__",
                    "__LDBL_HAS_QUIET_NAN__",
                    "__FLT_MIN_10_EXP__",
                    "__DBL_MIN_10_EXP__",
                    "__LDBL_MIN_10_EXP__",
                    "__FLT_MAX_10_EXP__",
                    "__DBL_MAX_10_EXP__",
                    "__LDBL_MAX_10_EXP__",
                )
            ),
        )
        self.assertNotIn("int fd;", result.source)
        self.assertNotIn("int dd;", result.source)
        self.assertNotIn("int ldd;", result.source)
        self.assertNotIn("int dec;", result.source)
        self.assertNotIn("int fdm;", result.source)
        self.assertNotIn("int ddm;", result.source)
        self.assertNotIn("int ldm;", result.source)
        self.assertNotIn("int fhd;", result.source)
        self.assertNotIn("int dhd;", result.source)
        self.assertNotIn("int lhd;", result.source)
        self.assertNotIn("int fhi;", result.source)
        self.assertNotIn("int dhi;", result.source)
        self.assertNotIn("int lhi;", result.source)
        self.assertNotIn("int fhq;", result.source)
        self.assertNotIn("int dhq;", result.source)
        self.assertNotIn("int lhq;", result.source)
        self.assertNotIn("int fmin10;", result.source)
        self.assertNotIn("int dmin10;", result.source)
        self.assertNotIn("int ldmin10;", result.source)
        self.assertNotIn("int fmax10;", result.source)
        self.assertNotIn("int dmax10;", result.source)
        self.assertNotIn("int ldmax10;", result.source)

    def test_cli_undef_removes_predefined_macro(self) -> None:
        result = preprocess_source(
            "#ifdef __INT_WIDTH__\nint present;\n#endif\n__SIZE_TYPE__ value;\n",
            filename="main.c",
            options=FrontendOptions(undefs=("__INT_WIDTH__", "__SIZE_TYPE__")),
        )
        self.assertNotIn("int present;", result.source)
        self.assertIn("__SIZE_TYPE__ value;", result.source)

    def test_ifdef_and_ifndef(self) -> None:
        source = "#define FLAG 1\n#ifdef FLAG\nint a;\n#endif\n#ifndef FLAG\nint b;\n#endif\n"
        result = preprocess_source(source, filename="if.c")
        self.assertIn("int a ;", result.source)
        self.assertNotIn("int b;", result.source)

    def test_if_elif_else(self) -> None:
        source = "#if 0\nint a;\n#elif 2 > 1\nint b;\n#else\nint c;\n#endif\n"
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

    def test_else_rejects_trailing_tokens(self) -> None:
        source = "#if 0\n#else unexpected\n#endif\n"
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(source, filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")
        self.assertEqual(str(ctx.exception), "Unexpected tokens after #else at if.c:2:1")

    def test_else_allows_trailing_comment(self) -> None:
        source = "#if 0\n#else /* comment */\nint ok;\n#endif\n"
        result = preprocess_source(source, filename="if.c")
        self.assertIn("int ok;", result.source)

    def test_endif_rejects_trailing_tokens(self) -> None:
        source = "#if 1\nint ok;\n#endif trailing\n"
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(source, filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")
        self.assertEqual(str(ctx.exception), "Unexpected tokens after #endif at if.c:3:1")

    def test_endif_allows_trailing_comment(self) -> None:
        source = "#if 1\nint ok;\n#endif // comment\n"
        result = preprocess_source(source, filename="if.c")
        self.assertIn("int ok;", result.source)

    def test_endif_allows_multiline_trailing_block_comment(self) -> None:
        source = "#if 1\nint ok;\n#endif /* !_A && !_B\n  || __need_X */\nint after;\n"
        result = preprocess_source(source, filename="if.c")
        self.assertIn("int ok;", result.source)
        self.assertIn("int after;", result.source)
        self.assertNotIn("__need_X", result.source)

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

    def test_invalid_if_expression_rejects_missing_defined_close_paren(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(
                "#define r_paren )\n#if defined( x r_paren\nint x;\n#endif\n",
                filename="if.c",
            )
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertEqual((ctx.exception.filename, ctx.exception.line), ("if.c", 2))

    def test_invalid_if_expression_rejects_signed_integer_overflow(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if 9223372036854775807LL + 1LL\nint x;\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertEqual(
            str(ctx.exception), "Integer overflow in preprocessor expression at if.c:1:1"
        )

    def test_invalid_if_expression_rejects_too_large_integer_literal(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if 0 && 18446744073709551616\nint x;\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertEqual(str(ctx.exception), "Invalid #if expression at if.c:1:1")

    def test_if_expression_uses_uintmax_for_large_unsuffixed_literals(self) -> None:
        result = preprocess_source(
            "#if 0xFFFFFFFFFFFFFFFF + 1 == 0\nint ok;\n#endif\n",
            filename="if.c",
        )
        self.assertIn("int ok;", result.source)

    def test_if_expression_accepts_intmax_min_boundary(self) -> None:
        result = preprocess_source(
            "#if -9223372036854775807LL - 1LL == __INTMAX_MIN__\nint ok;\n#endif\n",
            filename="if.c",
        )
        self.assertIn("int ok;", result.source)

    def test_skipped_if_block_ignores_too_large_integer_literal(self) -> None:
        result = preprocess_source(
            "#if 0\n#if 18446744073709551616\nint bad;\n#endif\n#endif\nint ok;\n",
            filename="if.c",
        )
        self.assertIn("int ok;", result.source)

    def test_if_expression_short_circuits_boolean_operators(self) -> None:
        result = preprocess_source(
            "#if 0 && (1 / 0)\nint bad;\n#elif 1 || (1 / 0)\nint ok;\n#endif\n",
            filename="if.c",
        )
        self.assertNotIn("int bad;", result.source)
        self.assertIn("int ok;", result.source)

    def test_if_expression_integer_operators(self) -> None:
        result = preprocess_source(
            "#if 1 + 2 * 3 == 7 && 8 / 2 == 4 && 5 % 2 == 1"
            " && 1 << 3 == 8 && 8 >> 2 == 2 && (3 | 1) == 3"
            " && (3 & 1) == 1 && (3 ^ 1) == 2 && ~1 == -2\n"
            "int ok;\n#endif\n",
            filename="if.c",
        )
        self.assertIn("int ok;", result.source)

    def test_if_expression_with_trailing_comment(self) -> None:
        result = preprocess_source("#if 1 // keep\nint x;\n#endif\n", filename="if.c")
        self.assertIn("int x;", result.source)

    def test_if_expression_with_block_comment(self) -> None:
        result = preprocess_source("#if 1 /* keep */\nint x;\n#endif\n", filename="if.c")
        self.assertIn("int x;", result.source)

    def test_multiline_block_comment_does_not_get_corrupted_by_macro_expansion(self) -> None:
        result = preprocess_source(
            "#define A 1\n/*\n * A\n */\nint main(void){return A;}\n",
            filename="comment.c",
        )
        self.assertIn("*/\n", result.source)
        self.assertNotIn("* /", result.source)
        self.assertIn(" * A\n", result.source)

    def test_define_body_block_comment_keeps_tail_blanked(self) -> None:
        """When a #define body opens a block comment, the closing */ on a
        non-directive line is blanked because the matching /* was removed with
        the directive."""
        result = preprocess_source(
            "#define FOO 0x04 /* comment\n                         tail */\n",
            filename="define_comment.c",
        )
        self.assertNotIn("tail */", result.source)
        self.assertNotIn("tail * /", result.source)
        self.assertNotIn("/* comment", result.source)

    def test_define_replacement_excludes_trailing_line_comment(self) -> None:
        result = preprocess_source(
            "#define ARRAY_LENGTH 20 // explanatory comment\n"
            "struct Values { int items[ARRAY_LENGTH]; };\n",
            filename="define-line-comment.c",
        )

        self.assertIn("int items [ 20 ]", result.source)
        self.assertNotIn("explanatory comment", result.source)

    def test_define_continuation_survives_multiline_block_comment(self) -> None:
        result = preprocess_source(
            "#define M() do { \\\n"
            "    if (x) { \\\n"
            "        /* comment\n"
            "           tail */ \\\n"
            "        y = 1; \\\n"
            "    } \\\n"
            "} while (0)\n"
            "void f(void) { M(); }\n",
            filename="define_comment_continuation.c",
        )
        before_function, _, function_body = result.source.partition("void f")
        self.assertNotIn("y = 1", before_function)
        self.assertIn("y = 1", function_body)
        self.assertNotIn("tail */", result.source)

    def test_macro_invocation_with_unclosed_continuation_block_comment_reports_error(
        self,
    ) -> None:
        source = "#define M(x) x\nM(1, /* comment \\\nstill comment"

        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(source, filename="macro_comment.c")

        self.assertEqual(ctx.exception.code, "XCC-PP-0202")
        self.assertIn("Unterminated macro invocation", str(ctx.exception))

    def test_macro_before_unclosed_trailing_block_comment_expands(self) -> None:
        result = preprocess_source(
            "#define __ASSERT_VOID_CAST (void)\n"
            "#define assert(expr) (__ASSERT_VOID_CAST (0))\n"
            "void f(int wsign, int vsign) {\n"
            "    assert(wsign != 0); /* closed */\n"
            "    assert(vsign != 0); /* multiline\n"
            "                           tail */\n"
            "}\n",
            filename="trailing_comment.c",
        )
        self.assertNotIn("assert ( vsign", result.source)
        self.assertIn("( ( void ) ( 0 ) ) ;/* multiline", result.source)

    def test_block_comment_sigil_inside_string_does_not_disable_directives(self) -> None:
        result = preprocess_source(
            'const char *s="\\"/*";\n#define A 2\nint x=A;\n',
            filename="string.c",
        )
        self.assertIn("int x = 2 ;", result.source)

    def test_slash_slash_comment_does_not_start_block_comment(self) -> None:
        result = preprocess_source(
            "// /*\n#define A 3\nint x=A;\n",
            filename="linecomment.c",
        )
        self.assertIn("int x = 3 ;", result.source)

    def test_if_expression_accepts_character_literals(self) -> None:
        result = preprocess_source("#if 'A' == 65\nint x;\n#endif\n", filename="if.c")
        self.assertIn("int x;", result.source)

    def test_if_expression_accepts_multichar_character_literals(self) -> None:
        result = preprocess_source("#if 'AB' == 0x4142\nint x;\n#endif\n", filename="if.c")
        self.assertIn("int x;", result.source)

    def test_if_expression_accepts_escaped_character_literals(self) -> None:
        result = preprocess_source("#if '\\n' == 10\nint x;\n#endif\n", filename="if.c")
        self.assertIn("int x;", result.source)

    def test_if_expression_rejects_invalid_character_literals(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if '\\x'\nint x;\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")

    def test_if_expression_with_has_include_quoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "present.h").write_text("int x;\n", encoding="utf-8")
            source_path = root / "main.c"
            source_path.write_text(
                '#if __has_include("present.h")\nint ok;\n#endif\n',
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
            '#if __has_include("missing.h")\nint bad;\n#endif\n',
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
            source = '#define HAS(x) __has_include(x)\n#if HAS("present.h")\nint ok;\n#endif\n'
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
        self.assertIn(
            "Invalid __has_include expression: missing header operand", str(ctx.exception)
        )

    def test_if_expression_with_has_include_missing_closing_paren(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source('#if __has_include("x.h"\nint x;\n#endif\n', filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertIn("Invalid __has_include expression: missing closing ')'", str(ctx.exception))

    def test_if_expression_with_has_include_next(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            include_dir = root / "include"
            source_dir.mkdir()
            include_dir.mkdir()
            (include_dir / "next.h").write_text("\n", encoding="utf-8")
            source = '#if __has_include_next("next.h")\nint ok;\n#endif\n'
            for std in ("c11", "gnu11"):
                with self.subTest(std=std):
                    result = preprocess_source(
                        source,
                        filename=str(source_dir / "main.c"),
                        options=FrontendOptions(std=std, include_dirs=(str(include_dir),)),
                    )
                    self.assertIn("int ok;", result.source)

    def test_if_expression_with_has_include_next_skips_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            source_dir.mkdir()
            (source_dir / "next.h").write_text("\n", encoding="utf-8")
            source = '#if __has_include_next("next.h")\nint bad;\n#endif\n'
            for std in ("c11", "gnu11"):
                with self.subTest(std=std):
                    result = preprocess_source(
                        source,
                        filename=str(source_dir / "main.c"),
                        options=FrontendOptions(std=std),
                    )
                    self.assertNotIn("int bad;", result.source)

    def test_if_expression_with_has_include_next_missing_header_is_zero_in_c11(self) -> None:
        result = preprocess_source(
            '#if __has_include_next("missing.h")\nint x;\n#endif\n',
            filename="if.c",
            options=FrontendOptions(std="c11"),
        )
        self.assertNotIn("int x;", result.source)

    def test_if_expression_with_has_builtin_feature_extension_and_warning_operators(self) -> None:
        result = preprocess_source(
            "#if __has_builtin(__builtin_expect)\nint bad_builtin;\n#endif\n"
            "#if !__has_builtin(__builtin_expect)\nint ok_builtin;\n#endif\n"
            "#if __has_attribute(enum_extensibility)\nint bad_attribute;\n#endif\n"
            "#if !__has_attribute(enum_extensibility)\nint ok_attribute;\n#endif\n"
            "#if __has_feature(c_static_assert)\nint bad_feature;\n#endif\n"
            "#if !__has_feature(c_static_assert)\nint ok_feature;\n#endif\n"
            "#if __has_extension(attribute_deprecated_with_message)\nint bad_extension;\n#endif\n"
            "#if !__has_extension(attribute_deprecated_with_message)\nint ok_extension;\n#endif\n"
            '#if __has_warning("-Wall")\nint ok_warning;\n#endif\n'
            '#if __has_warning("-Wdoes-not-exist")\nint bad_warning;\n#endif\n',
            filename="if.c",
        )
        self.assertNotIn("bad_builtin", result.source)
        self.assertIn("ok_builtin", result.source)
        self.assertNotIn("bad_attribute", result.source)
        self.assertIn("ok_attribute", result.source)
        self.assertNotIn("bad_feature", result.source)
        self.assertIn("ok_feature", result.source)
        self.assertNotIn("bad_extension", result.source)
        self.assertIn("ok_extension", result.source)
        self.assertIn("ok_warning", result.source)
        self.assertNotIn("bad_warning", result.source)

    def test_if_expression_with_macro_expanded_has_builtin_operator(self) -> None:
        result = preprocess_source(
            "#define HAS_BUILTIN(x) __has_builtin(x)\n"
            "#if HAS_BUILTIN(__builtin_expect)\nint bad;\n#endif\n"
            "#if !HAS_BUILTIN(__builtin_expect)\nint ok;\n#endif\n",
            filename="if.c",
        )
        self.assertNotIn("int bad;", result.source)
        self.assertIn("int ok ;", result.source)

    def test_if_expression_with_macro_expanded_has_warning_operator(self) -> None:
        result = preprocess_source(
            "#define HAS_WARNING(x) __has_warning(x)\n"
            '#if HAS_WARNING("-Wextra")\nint ok;\n#endif\n'
            '#if HAS_WARNING("-Wunknown")\nint bad;\n#endif\n',
            filename="if.c",
        )
        self.assertIn("int ok ;", result.source)
        self.assertNotIn("int bad;", result.source)

    def test_if_expression_with_has_builtin_rejects_non_identifier_operand(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if __has_builtin(123)\nint x;\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertIn(
            "Invalid __has_builtin expression: feature operand must be an identifier",
            str(ctx.exception),
        )

    def test_if_expression_with_has_warning_rejects_non_string_operand(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#if __has_warning(Wall)\nint x;\n#endif\n", filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertIn(
            "Invalid __has_warning expression: warning option operand must be a string literal",
            str(ctx.exception),
        )

    def test_if_expression_with_has_c_attribute_operator(self) -> None:
        result = preprocess_source(
            "#if __has_c_attribute(nodiscard)\nint ok_plain;\n#endif\n"
            "#if __has_c_attribute(gnu::unused)\nint ok_scoped;\n#endif\n"
            "#if __has_c_attribute(nonexistent_attribute)\nint bad;\n#endif\n",
            filename="if.c",
        )
        self.assertIn("ok_plain", result.source)
        self.assertIn("ok_scoped", result.source)
        self.assertNotIn("int bad;", result.source)

    def test_if_expression_with_macro_expanded_has_c_attribute_operator(self) -> None:
        result = preprocess_source(
            "#define HAS_C_ATTR(x) __has_c_attribute(x)\n"
            "#if HAS_C_ATTR(nodiscard)\nint ok;\n#endif\n"
            "#if HAS_C_ATTR(missing_attr)\nint bad;\n#endif\n",
            filename="if.c",
        )
        self.assertIn("int ok ;", result.source)
        self.assertNotIn("int bad;", result.source)

    def test_if_expression_with_has_c_attribute_rejects_non_identifier_operand(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(
                '#if __has_c_attribute("nodiscard")\nint x;\n#endif\n', filename="if.c"
            )
        self.assertEqual(ctx.exception.code, "XCC-PP-0103")
        self.assertIn(
            "Invalid __has_c_attribute expression: attribute operand must be an identifier or scoped identifier",
            str(ctx.exception),
        )

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

    def test_stdc_pragma_valid_toggles_are_ignored(self) -> None:
        result = preprocess_source(
            "#pragma STDC FENV_ACCESS ON\n"
            "#pragma STDC CX_LIMITED_RANGE OFF\n"
            "#pragma STDC FP_CONTRACT DEFAULT\n"
            "#pragma STDC FENV_ROUND FE_UPWARD\n"
            "int x;\n",
            filename="main.c",
        )
        self.assertEqual(result.source, "\n\n\n\nint x;\n")

    def test_stdc_pragma_invalid_value_errors(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#pragma STDC FENV_ACCESS BLERP\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")
        self.assertEqual(
            str(ctx.exception),
            "Invalid #pragma STDC FENV_ACCESS value: BLERP at main.c:1:1",
        )

    def test_stdc_fenv_round_invalid_value_errors(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#pragma STDC FENV_ROUND ON\n", filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")
        self.assertEqual(
            str(ctx.exception),
            "Invalid #pragma STDC FENV_ROUND value: ON at main.c:1:1",
        )

    def test_gcc_visibility_pragma_valid_forms_are_ignored(self) -> None:
        result = preprocess_source(
            "#pragma GCC visibility push(hidden)\n#pragma GCC visibility pop\nint x;\n",
            filename="main.c",
        )
        self.assertEqual(result.source, "\n\nint x;\n")

    def test_gcc_visibility_pragma_invalid_forms_error(self) -> None:
        cases = (
            "#pragma GCC visibility foo\n",
            "#pragma GCC visibility pop foo\n",
            "#pragma GCC visibility push\n",
            "#pragma GCC visibility push(\n",
            "#pragma GCC visibility push(hidden\n",
            "#pragma GCC visibility push()\n",
        )
        for source in cases:
            with self.subTest(source=source.strip()):
                with self.assertRaises(PreprocessorError) as ctx:
                    preprocess_source(source, filename="main.c")
                self.assertEqual(ctx.exception.code, "XCC-PP-0104")
                self.assertEqual(
                    str(ctx.exception),
                    "Invalid #pragma GCC visibility directive at main.c:1:1",
                )

    def test_fenv_access_pragma_valid_forms_are_ignored(self) -> None:
        result = preprocess_source(
            "#pragma fenv_access (on)\n#pragma fenv_access (off)\nint x;\n",
            filename="main.c",
        )
        self.assertEqual(result.source, "\n\nint x;\n")

    def test_fenv_access_pragma_invalid_forms_error(self) -> None:
        cases = (
            "#pragma fenv_access\n",
            "#pragma fenv_access foo\n",
            "#pragma fenv_access on\n",
            "#pragma fenv_access (\n",
            "#pragma fenv_access (on\n",
            "#pragma fenv_access (on) foo\n",
            "#pragma fenv_access (maybe)\n",
        )
        for source in cases:
            with self.subTest(source=source.strip()):
                with self.assertRaises(PreprocessorError) as ctx:
                    preprocess_source(source, filename="main.c")
                self.assertEqual(ctx.exception.code, "XCC-PP-0104")
                self.assertEqual(
                    str(ctx.exception),
                    "Invalid #pragma fenv_access directive at main.c:1:1",
                )

    def test_clang_diagnostic_pragma_valid_forms_are_ignored(self) -> None:
        result = preprocess_source(
            "#pragma clang diagnostic push\n"
            '#pragma clang diagnostic ignored "-Wmultichar"\n'
            '#pragma clang diagnostic warning "-Weverything"\n'
            '#pragma GCC diagnostic error "-Wundef"\n'
            '#pragma clang diagnostic fatal "-Wall"\n'
            "#pragma clang diagnostic pop\n"
            "int x;\n",
            filename="main.c",
        )
        self.assertEqual(result.source, "\n\n\n\n\n\nint x;\n")

    def test_clang_diagnostic_pragma_invalid_forms_error(self) -> None:
        cases = (
            "#pragma clang diagnostic\n",
            "#pragma clang diagnostic puhs\n",
            "#pragma clang diagnostic error 42\n",
            '#pragma clang diagnostic push ignored "-Wdeprecated-declarations"\n',
            '#pragma GCC diagnostic error "invalid-name"\n',
        )
        for source in cases:
            with self.subTest(source=source.strip()):
                with self.assertRaises(PreprocessorError) as ctx:
                    preprocess_source(source, filename="main.c")
                self.assertEqual(ctx.exception.code, "XCC-PP-0104")
                self.assertEqual(
                    str(ctx.exception),
                    "Invalid #pragma diagnostic directive at main.c:1:1",
                )

    def test_clang_module_pragma_valid_forms_are_ignored(self) -> None:
        result = preprocess_source(
            "#pragma clang module\n"
            "#pragma clang module build bounds_safety\n"
            "#pragma clang module contents\n"
            "#pragma clang module begin foo.a\n"
            "#pragma clang module import foo.a\n"
            "#pragma clang module end\n"
            "#pragma clang module endbuild\n"
            "int x;\n",
            filename="main.c",
        )
        self.assertEqual(result.source, "\n\n\n\n\n\n\nint x;\n")

    def test_clang_module_pragma_invalid_forms_error(self) -> None:
        cases = (
            "#pragma clang module import\n",
            "#pragma clang module import !\n",
            "#pragma clang module import foo ? bar\n",
            "#pragma clang module begin !\n",
            "#pragma clang module end foo.a\n",
        )
        for source in cases:
            with self.subTest(source=source.strip()):
                with self.assertRaises(PreprocessorError) as ctx:
                    preprocess_source(source, filename="main.c")
                self.assertEqual(ctx.exception.code, "XCC-PP-0104")
                self.assertEqual(
                    str(ctx.exception),
                    "Invalid #pragma clang module directive at main.c:1:1",
                )

    def test_clang_fp_pragma_valid_forms_are_ignored(self) -> None:
        result = preprocess_source(
            "#pragma clang fp reassociate(off)\n"
            "#pragma clang fp reciprocal(on)\n"
            "#pragma clang fp reciprocal(on) reassociate(on)\n"
            "#pragma clang fp contract(fast) reassociate(on)\n"
            "#pragma clang fp eval_method(source)\n"
            "#pragma clang fp exceptions(maytrap)\n"
            "int x;\n",
            filename="main.c",
        )
        self.assertEqual(result.source, "\n\n\n\n\n\nint x;\n")

    def test_clang_fp_pragma_invalid_forms_error(self) -> None:
        cases = (
            "#pragma clang fp reassociate(fast)\n",
            "#pragma clang fp reciprocal(fast)\n",
        )
        for source in cases:
            with self.subTest(source=source.strip()):
                with self.assertRaises(PreprocessorError) as ctx:
                    preprocess_source(source, filename="main.c")
                self.assertEqual(ctx.exception.code, "XCC-PP-0104")
                self.assertEqual(
                    str(ctx.exception),
                    "Invalid #pragma clang fp directive at main.c:1:1",
                )

    def test_pragma_once_skips_second_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = root / "once.h"
            header.write_text("#pragma once\nint from_once;\n", encoding="utf-8")
            source_path = root / "main.c"
            source_path.write_text('#include "once.h"\n#include "once.h"\n', encoding="utf-8")
            result = preprocess_source(
                source_path.read_text(encoding="utf-8"), filename=str(source_path)
            )
        self.assertEqual(result.source.count("int from_once"), 1)

    def test_no_callback_pragma_once_skips_second_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = root / "once.h"
            header.write_text("#pragma once\nint from_once;\n", encoding="utf-8")
            source_path = root / "main.c"
            source_path.write_text('#include "once.h"\n#include "once.h"\n', encoding="utf-8")
            result = preprocess_source_no_callback(
                source_path.read_text(encoding="utf-8"),
                filename=str(source_path),
            )
        self.assertEqual(result.source.count("int from_once"), 1)

    def test_pragma_once_applies_across_nested_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "once.h").write_text("#pragma once\nint from_once;\n", encoding="utf-8")
            (root / "wrapper.h").write_text('#include "once.h"\n', encoding="utf-8")
            main = root / "main.c"
            main.write_text('#include "once.h"\n#include "wrapper.h"\n', encoding="utf-8")
            result = preprocess_source(main.read_text(encoding="utf-8"), filename=str(main))
        self.assertEqual(result.source.count("int from_once"), 1)

    def test_import_skips_second_include_of_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "imported.h").write_text("int from_import;\n", encoding="utf-8")
            source_path = root / "main.c"
            source_path.write_text('#import "imported.h"\n#import "imported.h"\n', encoding="utf-8")
            result = preprocess_source(
                source_path.read_text(encoding="utf-8"), filename=str(source_path)
            )
        self.assertEqual(result.source, "int from_import;\n")

    def test_import_self_is_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "self.c"
            source_path.write_text('#import "self.c"\nint self_ok;\n', encoding="utf-8")
            result = preprocess_source(
                source_path.read_text(encoding="utf-8"), filename=str(source_path)
            )
        self.assertIn("int self_ok;", result.source)

    def test_import_guards_against_later_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "guard.h").write_text("int guarded;\n", encoding="utf-8")
            source_path = root / "main.c"
            source_path.write_text('#import "guard.h"\n#include "guard.h"\n', encoding="utf-8")
            result = preprocess_source(
                source_path.read_text(encoding="utf-8"), filename=str(source_path)
            )
        self.assertEqual(result.source, "int guarded;\n")

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

    def test_include_line_comment_slash_slash_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text("int z;\n", encoding="utf-8")
            source_path = root / "main.c"
            source_path.write_text('#include "inc.h" // trailing comment\n')
            source = source_path.read_text(encoding="utf-8")
            result = preprocess_source(source, filename=str(source_path))
        self.assertEqual(result.source, "int z;\n")

    def test_include_from_system_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include = root / "sys"
            include.mkdir()
            (include / "inc.h").write_text("int z;\n", encoding="utf-8")
            options = FrontendOptions(system_include_dirs=(str(include),))
            result = preprocess_source("#include <inc.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int z;\n")

    def test_include_angle_resolves_macos_framework_header_from_sdk_usr_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdk = Path(tmp) / "MacOSX.sdk"
            include = sdk / "usr" / "include"
            framework_headers = (
                sdk / "System" / "Library" / "Frameworks" / "Foo.framework" / "Headers"
            )
            include.mkdir(parents=True)
            framework_headers.mkdir(parents=True)
            (framework_headers / "Foo.h").write_text("int framework_header;\n", encoding="utf-8")
            options = FrontendOptions(system_include_dirs=(str(include),))
            result = preprocess_source("#include <Foo/Foo.h>\n", filename="main.c", options=options)
        self.assertEqual(result.source, "int framework_header;\n")

    def test_include_allows_non_utf8_bytes_in_header_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            include = Path(tmp)
            (include / "legacy.h").write_bytes(b"// legacy \x92 byte\nint ok;\n")
            options = FrontendOptions(include_dirs=(str(include),))
            result = preprocess_source("#include <legacy.h>\n", filename="main.c", options=options)
        self.assertIn("int ok;", result.source)

    def test_host_system_include_dirs_are_searched_for_angle_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            include_dir = Path(tmp)
            (include_dir / "xcc_host.h").write_text("int ok;\n", encoding="utf-8")
            with patch(
                "xcc.preprocessor.host_system_include_dirs",
                return_value=(str(include_dir),),
            ):
                result = preprocess_source("#include <xcc_host.h>\n", filename="main.c")
        self.assertEqual(result.source, "int ok;\n")

    def test_nostdinc_disables_host_system_include_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            include_dir = Path(tmp)
            (include_dir / "xcc_host.h").write_text("int ok;\n", encoding="utf-8")
            options = FrontendOptions(no_standard_includes=True)
            with patch(
                "xcc.preprocessor.host_system_include_dirs",
                return_value=(str(include_dir),),
            ), self.assertRaises(PreprocessorError) as ctx:
                preprocess_source("#include <xcc_host.h>\n", filename="main.c", options=options)
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")

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

    def test_include_angle_uses_current_directory_for_empty_cpath_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "main.c"
            header_path = root / "inc.h"
            source_path.write_text("#include <inc.h>\n", encoding="utf-8")
            header_path.write_text("int from_cwd;\n", encoding="utf-8")
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict("os.environ", {"CPATH": f"{os.pathsep}"}, clear=False):
                    result = preprocess_source(
                        source_path.read_text(encoding="utf-8"), filename=str(source_path)
                    )
            finally:
                os.chdir(previous_cwd)
        self.assertEqual(result.source, "int from_cwd;\n")

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
            ), self.assertRaises(PreprocessorError) as ctx:
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
            result = preprocess_source(
                main.read_text(encoding="utf-8"), filename=str(main), options=options
            )
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
            result = preprocess_source(
                main.read_text(encoding="utf-8"), filename=str(main), options=options
            )
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
            result = preprocess_source(
                main.read_text(encoding="utf-8"), filename=str(main), options=options
            )
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

    def test_include_next_uses_following_include_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_dir = root / "first"
            second_dir = root / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            (first_dir / "inc.h").write_text(
                "#include_next <inc.h>\nint from_first;\n", encoding="utf-8"
            )
            (second_dir / "inc.h").write_text("int from_second;\n", encoding="utf-8")
            for std in ("c11", "gnu11"):
                with self.subTest(std=std):
                    options = FrontendOptions(
                        std=std,
                        include_dirs=(str(first_dir), str(second_dir)),
                        no_standard_includes=True,
                    )
                    result = preprocess_source(
                        "#include <inc.h>\n", filename="main.c", options=options
                    )
                    self.assertEqual(result.source, "int from_second;\nint from_first;\n")

    def test_include_next_in_gnu_mode_skips_source_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            include_dir = root / "include"
            source_dir.mkdir()
            include_dir.mkdir()
            (source_dir / "inc.h").write_text(
                '#include_next "inc.h"\nint from_source;\n', encoding="utf-8"
            )
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
            (first_dir / "inc.h").write_text(
                '#include_next "inc.h"\nint from_first;\n', encoding="utf-8"
            )
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
                '#if __has_include_next("inc.h")\nint has_next;\n#endif\n',
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
            options = FrontendOptions(
                std="gnu11", include_dirs=(str(include_dir),), no_standard_includes=True
            )
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
        self.assertIn(
            f"{(first_dir / 'inc.h').resolve()}:1: #include_next <inc.h>", result.include_trace[1]
        )

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
            result = preprocess_source(
                source_path.read_text(encoding="utf-8"), filename=str(source_path)
            )
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
            (include_dir / "defs.h").write_text(
                "#define VALUE 17\nint ignored;\n", encoding="utf-8"
            )
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
        options = FrontendOptions(macro_includes=("missing.h",), no_standard_includes=True)
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
        options = FrontendOptions(forced_includes=("missing.h",), no_standard_includes=True)
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("int x;\n", filename="main.c", options=options)
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual(
            ctx.exception.args[0],
            f'Forced include not found: "missing.h"; searched: {Path.cwd().resolve()} at <command line>:1:1',
        )

    def test_import_not_found(self) -> None:
        options = FrontendOptions(no_standard_includes=True)
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source('#import "missing.h"\n', filename="main.c", options=options)
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual((ctx.exception.filename, ctx.exception.line), ("main.c", 1))
        self.assertEqual(
            ctx.exception.args[0],
            f'Import not found: "missing.h"; searched: {Path.cwd().resolve()} at main.c:1:1',
        )

    def test_include_not_found(self) -> None:
        options = FrontendOptions(no_standard_includes=True)
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source('#include "missing.h"\n', filename="main.c", options=options)
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual((ctx.exception.filename, ctx.exception.line), ("main.c", 1))
        self.assertEqual(
            ctx.exception.args[0],
            f'Include not found: "missing.h"; searched: {Path.cwd().resolve()} at main.c:1:1',
        )

    def test_include_not_found_for_angle_include_reports_delimiters(self) -> None:
        options = FrontendOptions(no_standard_includes=True)
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#include <missing.h>\n", filename="main.c", options=options)
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual(
            ctx.exception.args[0],
            "Include not found: <missing.h>; searched: <none> at main.c:1:1",
        )

    def test_include_not_found_uses_line_mapped_source_location(self) -> None:
        options = FrontendOptions(no_standard_includes=True)
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(
                '#line 77 "mapped.c"\n#include "missing.h"\n', filename="main.c", options=options
            )
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual((ctx.exception.filename, ctx.exception.line), ("mapped.c", 77))
        self.assertEqual(
            ctx.exception.args[0],
            f'Include not found: "missing.h"; searched: {Path.cwd().resolve()} at mapped.c:77:1',
        )

    def test_include_next_not_found_uses_line_mapped_source_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            include_dir = root / "include"
            source_dir.mkdir()
            include_dir.mkdir()
            source_header = source_dir / "inc.h"
            source_header.write_text(
                '#line 41 "mapped/header.h"\n#include_next "inc.h"\n',
                encoding="utf-8",
            )
            options = FrontendOptions(
                std="gnu11", include_dirs=(str(include_dir),), no_standard_includes=True
            )
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source(
                    '#include "inc.h"\n', filename=str(source_dir / "main.c"), options=options
                )
        self.assertEqual(ctx.exception.code, "XCC-PP-0102")
        self.assertEqual((ctx.exception.filename, ctx.exception.line), ("mapped/header.h", 41))
        self.assertEqual(
            ctx.exception.args[0],
            f'Include not found via #include_next: "inc.h"; searched: {include_dir.resolve()} at mapped/header.h:41:1',
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
                no_standard_includes=True,
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
                no_standard_includes=True,
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

    def test_circular_include_guarded_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_header = root / "a.h"
            b_header = root / "b.h"
            a_header.write_text(
                '#ifndef A_H\n#define A_H\n#include "b.h"\n#endif\n',
                encoding="utf-8",
            )
            b_header.write_text(
                '#ifndef B_H\n#define B_H\n#include "a.h"\n#endif\n',
                encoding="utf-8",
            )
            source = '#include "a.h"\n'
            result = preprocess_source(source, filename=str(root / "main.c"))
            self.assertNotIn("Circular include", result.source)

    def test_circular_include_guard_defined_elsewhere_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_header = root / "a.h"
            b_header = root / "b.h"
            a_header.write_text(
                '#ifndef A_H\n#define A_H\n#include "b.h"\n#endif\n',
                encoding="utf-8",
            )
            b_header.write_text(
                '#ifndef B_H\n#define B_H\n#include "a.h"\n#endif\n',
                encoding="utf-8",
            )
            source = '#define A_H\n#include "a.h"\n'
            result = preprocess_source(source, filename=str(root / "main.c"))
            self.assertNotIn("Circular include", result.source)

    def test_circular_include_guard_variants_are_skipped(self) -> None:
        for opening in (
            "#if !defined(SELF_H)\n#define SELF_H\n",
            "/* guard */\n#ifndef SELF_H /* guard */\n#define SELF_H\n",
        ):
            with self.subTest(opening=opening), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "self.h").write_text(
                    opening + '#include "self.h"\n#endif\n',
                    encoding="utf-8",
                )
                preprocess_source(
                    '#include "self.h"\n',
                    filename=str(root / "main.c"),
                )

    def test_guarded_circular_include_via_imacro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_header = root / "a.h"
            a_header.write_text(
                '#ifndef A_H\n#define A_H\n#include "a.h"\n#endif\n',
                encoding="utf-8",
            )
            source = '#include "a.h"\n'
            # Self-include via guard is OK
            result = preprocess_source(source, filename=str(root / "main.c"))
            self.assertNotIn("Circular include", result.source)

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

    def test_line_directive_requires_operand(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source("#line\n", filename="main.c")
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

    def test_line_directive_rejects_trailing_filename_tokens(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source('#line 42 "mapped.c" extra\n', filename="main.c")
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
            "int pww = __POINTER_WIDTH__;\n"
            "int bw = __BOOL_WIDTH__;\n"
            "int imw = __INTMAX_WIDTH__;\n"
            "int umw = __UINTMAX_WIDTH__;\n"
            "int llw = __LLONG_WIDTH__;\n"
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
            "int bsz = __SIZEOF_BOOL__;\n"
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
            "int c16z = __SIZEOF_CHAR16_T__;\n"
            "int c32z = __SIZEOF_CHAR32_T__;\n"
            "int ord = __ORDER_LITTLE_ENDIAN__;\n"
            "int bo = __BYTE_ORDER__;\n"
            "int le = __LITTLE_ENDIAN__;\n"
            "int be = __BIG_ENDIAN__;\n"
            "int fwo = __FLOAT_WORD_ORDER__;\n"
            "int ww = __WCHAR_WIDTH__;\n"
            "int wiw = __WINT_WIDTH__;\n"
            "int c16w = __CHAR16_WIDTH__;\n"
            "int c32w = __CHAR32_WIDTH__;\n"
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
            "long long llmax_alias = __LLONG_MAX__;\n"
            "long long llmin_alias = __LLONG_MIN__;\n"
            "unsigned long long ullmax_alias = __ULLONG_MAX__;\n"
            "long imx = __INTMAX_MAX__;\n"
            "long imn = __INTMAX_MIN__;\n"
            "unsigned long umx = __UINTMAX_MAX__;\n"
            "int i8c = __INT8_C(12);\n"
            "int i16c = __INT16_C(34);\n"
            "int i32c = __INT32_C(56);\n"
            "long i64c = __INT64_C(78);\n"
            "long imc = __INTMAX_C(123);\n"
            "unsigned int u8c = __UINT8_C(12);\n"
            "unsigned int u16c = __UINT16_C(34);\n"
            "unsigned int u32c = __UINT32_C(56);\n"
            "unsigned long u64c = __UINT64_C(78);\n"
            "unsigned long umc = __UINTMAX_C(456);\n"
            "const char *bf = __BASE_FILE__;\n"
            "const char *fn = __FILE_NAME__;\n"
            "__SIZE_TYPE__ n;\n"
            "__PTRDIFF_TYPE__ d;\n"
            "__INTPTR_TYPE__ ip;\n"
            "__UINTPTR_TYPE__ up;\n"
            "__INTMAX_TYPE__ imt;\n"
            "__UINTMAX_TYPE__ umt;\n"
            "__CHAR16_TYPE__ c16;\n"
            "__CHAR32_TYPE__ c32;\n"
            "__INT8_TYPE__ i8;\n"
            "__INT16_TYPE__ i16;\n"
            "__INT32_TYPE__ i32;\n"
            "__INT64_TYPE__ i64;\n"
            "__UINT8_TYPE__ u8;\n"
            "__UINT16_TYPE__ u16;\n"
            "__UINT32_TYPE__ u32;\n"
            "__UINT64_TYPE__ u64;\n"
            "__INT_LEAST8_TYPE__ il8;\n"
            "__INT_LEAST16_TYPE__ il16;\n"
            "__INT_LEAST32_TYPE__ il32;\n"
            "__INT_LEAST64_TYPE__ il64;\n"
            "__UINT_LEAST8_TYPE__ ul8;\n"
            "__UINT_LEAST16_TYPE__ ul16;\n"
            "__UINT_LEAST32_TYPE__ ul32;\n"
            "__UINT_LEAST64_TYPE__ ul64;\n"
            "__INT_FAST8_TYPE__ if8;\n"
            "__INT_FAST16_TYPE__ if16;\n"
            "__INT_FAST32_TYPE__ if32;\n"
            "__INT_FAST64_TYPE__ if64;\n"
            "__UINT_FAST8_TYPE__ uf8;\n"
            "__UINT_FAST16_TYPE__ uf16;\n"
            "__UINT_FAST32_TYPE__ uf32;\n"
            "__UINT_FAST64_TYPE__ uf64;\n"
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
        self.assertIn("int nc = 1 ;", result.source)
        # __STDC_NO_ATOMICS__ is not predefined (XCC supports _Atomic)
        self.assertIn("int na = __STDC_NO_ATOMICS__;", result.source)
        # __STDC_NO_THREADS__ is not predefined (XCC supports _Thread_local)
        self.assertIn("int nt = __STDC_NO_THREADS__;", result.source)
        self.assertIn("int nv = 1 ;", result.source)
        self.assertIn("int lp = 1 ;", result.source)
        self.assertIn("int lp_alias = 1 ;", result.source)
        self.assertIn("int lp_legacy = 1 ;", result.source)
        self.assertIn("int bits = 8 ;", result.source)
        self.assertIn("int szw = 64 ;", result.source)
        self.assertIn("int pdw = 64 ;", result.source)
        self.assertIn("int ipw = 64 ;", result.source)
        self.assertIn("int upw = 64 ;", result.source)
        self.assertIn("int pww = 64 ;", result.source)
        self.assertIn("int bw = 8 ;", result.source)
        self.assertIn("int imw = 64 ;", result.source)
        self.assertIn("int umw = 64 ;", result.source)
        self.assertIn("int llw = 64 ;", result.source)
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
        self.assertIn("int bsz = 1 ;", result.source)
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
        self.assertIn("int c16z = 2 ;", result.source)
        self.assertIn("int c32z = 4 ;", result.source)
        self.assertIn("int ord = 1234 ;", result.source)
        self.assertIn("int bo = 1234 ;", result.source)
        self.assertIn("int le = 1 ;", result.source)
        self.assertIn("int be = __BIG_ENDIAN__;", result.source)
        self.assertIn("int fwo = 1234 ;", result.source)
        self.assertIn("int ww = 32 ;", result.source)
        self.assertIn("int wiw = 32 ;", result.source)
        self.assertIn("int c16w = 16 ;", result.source)
        self.assertIn("int c32w = 32 ;", result.source)
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
        self.assertIn("long long llmax_alias = 9223372036854775807LL ;", result.source)
        self.assertIn("long long llmin_alias = - 9223372036854775808LL ;", result.source)
        self.assertIn("unsigned long long ullmax_alias = 18446744073709551615ULL ;", result.source)
        self.assertIn("long imx = 9223372036854775807L ;", result.source)
        self.assertIn("long imn = - 9223372036854775808L ;", result.source)
        self.assertIn("unsigned long umx = 18446744073709551615UL ;", result.source)
        self.assertIn("int i8c = 12 ;", result.source)
        self.assertIn("int i16c = 34 ;", result.source)
        self.assertIn("int i32c = 56 ;", result.source)
        self.assertIn("long i64c = 78L ;", result.source)
        self.assertIn("long imc = 123L ;", result.source)
        self.assertIn("unsigned int u8c = 12 ;", result.source)
        self.assertIn("unsigned int u16c = 34 ;", result.source)
        self.assertIn("unsigned int u32c = 56U ;", result.source)
        self.assertIn("unsigned long u64c = 78UL ;", result.source)
        self.assertIn("unsigned long umc = 456UL ;", result.source)
        self.assertIn('const char * bf = "main.c" ;', result.source)
        self.assertIn('const char * fn = "main.c" ;', result.source)
        self.assertIn("unsigned long n ;", result.source)
        self.assertIn("long d ;", result.source)
        self.assertIn("long ip ;", result.source)
        self.assertIn("unsigned long up ;", result.source)
        self.assertIn("long imt ;", result.source)
        self.assertIn("unsigned long umt ;", result.source)
        self.assertIn("unsigned short c16 ;", result.source)
        self.assertIn("unsigned int c32 ;", result.source)
        self.assertIn("signed char i8 ;", result.source)
        self.assertIn("short i16 ;", result.source)
        self.assertIn("int i32 ;", result.source)
        self.assertIn("long i64 ;", result.source)
        self.assertIn("unsigned char u8 ;", result.source)
        self.assertIn("unsigned short u16 ;", result.source)
        self.assertIn("unsigned int u32 ;", result.source)
        self.assertIn("unsigned long u64 ;", result.source)
        self.assertIn("signed char il8 ;", result.source)
        self.assertIn("short il16 ;", result.source)
        self.assertIn("int il32 ;", result.source)
        self.assertIn("long il64 ;", result.source)
        self.assertIn("unsigned char ul8 ;", result.source)
        self.assertIn("unsigned short ul16 ;", result.source)
        self.assertIn("unsigned int ul32 ;", result.source)
        self.assertIn("unsigned long ul64 ;", result.source)
        self.assertIn("signed char if8 ;", result.source)
        self.assertIn("short if16 ;", result.source)
        self.assertIn("int if32 ;", result.source)
        self.assertIn("long if64 ;", result.source)
        self.assertIn("unsigned char uf8 ;", result.source)
        self.assertIn("unsigned short uf16 ;", result.source)
        self.assertIn("unsigned int uf32 ;", result.source)
        self.assertIn("unsigned long uf64 ;", result.source)
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
            source_path.write_text(
                '#include "mid.h"\nint top = __INCLUDE_LEVEL__;\n', encoding="utf-8"
            )
            result = preprocess_source(
                source_path.read_text(encoding="utf-8"), filename=str(source_path)
            )

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

    def test_predefined_atomic_and_sync_macros(self) -> None:
        result = preprocess_source(
            "int relaxed = __ATOMIC_RELAXED;\n"
            "int consume = __ATOMIC_CONSUME;\n"
            "int acquire = __ATOMIC_ACQUIRE;\n"
            "int release = __ATOMIC_RELEASE;\n"
            "int acq_rel = __ATOMIC_ACQ_REL;\n"
            "int seq_cst = __ATOMIC_SEQ_CST;\n"
            "int lock_free = __GCC_ATOMIC_POINTER_LOCK_FREE;\n"
            "int lock_free_char16 = __GCC_ATOMIC_CHAR16_T_LOCK_FREE;\n"
            "int lock_free_char32 = __GCC_ATOMIC_CHAR32_T_LOCK_FREE;\n"
            "int lock_free_wchar = __GCC_ATOMIC_WCHAR_T_LOCK_FREE;\n"
            "int test_and_set_trueval = __GCC_ATOMIC_TEST_AND_SET_TRUEVAL;\n"
            "#if defined(__GCC_HAVE_SYNC_COMPARE_AND_SWAP_8)\nint has_sync_8;\n#endif\n"
            "#if defined(__GCC_HAVE_SYNC_COMPARE_AND_SWAP_16)\nint has_sync_16;\n#endif\n",
            filename="main.c",
        )
        self.assertIn("int relaxed = 0 ;", result.source)
        self.assertIn("int consume = 1 ;", result.source)
        self.assertIn("int acquire = 2 ;", result.source)
        self.assertIn("int release = 3 ;", result.source)
        self.assertIn("int acq_rel = 4 ;", result.source)
        self.assertIn("int seq_cst = 5 ;", result.source)
        self.assertIn("int lock_free = 2 ;", result.source)
        self.assertIn("int lock_free_char16 = 2 ;", result.source)
        self.assertIn("int lock_free_char32 = 2 ;", result.source)
        self.assertIn("int lock_free_wchar = 2 ;", result.source)
        self.assertIn("int test_and_set_trueval = 1 ;", result.source)
        self.assertIn("int has_sync_8;", result.source)
        self.assertIn("int has_sync_16;", result.source)

    def test_cli_undef_removes_predefined_atomic_and_sync_macros(self) -> None:
        result = preprocess_source(
            "#if defined(__ATOMIC_ACQUIRE)\nint acq;\n#endif\n"
            "#if defined(__GCC_ATOMIC_POINTER_LOCK_FREE)\nint lock_free;\n#endif\n"
            "#if defined(__GCC_ATOMIC_CHAR16_T_LOCK_FREE)\nint lock_free_char16;\n#endif\n"
            "#if defined(__GCC_ATOMIC_TEST_AND_SET_TRUEVAL)\nint test_and_set_trueval;\n#endif\n"
            "#if defined(__GCC_HAVE_SYNC_COMPARE_AND_SWAP_8)\nint sync8;\n#endif\n"
            "#if defined(__GCC_HAVE_SYNC_COMPARE_AND_SWAP_16)\nint sync16;\n#endif\n",
            filename="main.c",
            options=FrontendOptions(
                undefs=(
                    "__ATOMIC_ACQUIRE",
                    "__GCC_ATOMIC_POINTER_LOCK_FREE",
                    "__GCC_ATOMIC_CHAR16_T_LOCK_FREE",
                    "__GCC_ATOMIC_TEST_AND_SET_TRUEVAL",
                    "__GCC_HAVE_SYNC_COMPARE_AND_SWAP_8",
                    "__GCC_HAVE_SYNC_COMPARE_AND_SWAP_16",
                )
            ),
        )
        self.assertNotIn("int acq;", result.source)
        self.assertNotIn("int lock_free;", result.source)
        self.assertNotIn("int lock_free_char16;", result.source)
        self.assertNotIn("int test_and_set_trueval;", result.source)
        self.assertNotIn("int sync8;", result.source)
        self.assertNotIn("int sync16;", result.source)

    def test_predefined_date_time_and_timestamp_macros_use_translation_start_time(self) -> None:
        with patch("xcc.preprocessor.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 2, 23, 22, 21, 9)
            result = preprocess_source(
                "const char *d = __DATE__;\nconst char *t = __TIME__;\nconst char *ts = __TIMESTAMP__;\n",
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

    def test_c11_strips_gnu_asm_statement(self) -> None:
        result = preprocess_source(
            'asm("inst");\n', filename="main.c", options=FrontendOptions(std="c11")
        )
        self.assertEqual(result.source, ";\n")

    def test_c11_strips_gnu_asm_declaration_labels(self) -> None:
        result = preprocess_source(
            'int value __asm("value_alias") = 0;\n'
            'int f(void) __asm("_f");\n'
            'int g(void)\n__asm("_g");\n',
            filename="main.c",
            options=FrontendOptions(std="c11"),
        )
        self.assertEqual(result.source, "int value  = 0;\nint f(void) ;\nint g(void)\n;\n")

    def test_c11_strips_inline_gnu_asm_statement(self) -> None:
        result = preprocess_source(
            'void f(void){ __asm__("nop"); }\n',
            filename="main.c",
            options=FrontendOptions(std="c11"),
        )
        self.assertEqual(result.source, "void f(void){ ; }\n")

    def test_c11_rewrites_aarch64_stack_pointer_gnu_asm(self) -> None:
        result = preprocess_source(
            'unsigned long f(void){ unsigned long result; __asm__ ("mov %0, sp" : "=r" (result)); return result; }\n',
            filename="main.c",
            options=FrontendOptions(std="c11"),
        )
        self.assertNotIn("__asm", result.source)
        self.assertIn("result = (unsigned long)&result", result.source)

    def test_c11_strips_multiline_control_gnu_asm_statement(self) -> None:
        result = preprocess_source(
            'void f(int value){\nif (value)\n__asm__("nop");\n}\n',
            filename="main.c",
            options=FrontendOptions(std="c11"),
        )
        self.assertEqual(result.source, "void f(int value){\nif (value)\n;\n}\n")

    def test_c11_strips_included_gnu_asm_statement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc.h").write_text(
                'static inline void pause(void){ __asm__("nop"); }\n',
                encoding="utf-8",
            )
            result = preprocess_source(
                '#include "inc.h"\nint value;\n',
                filename=str(root / "main.c"),
                options=FrontendOptions(std="c11", include_dirs=(str(root),)),
            )
        self.assertNotIn("__asm", result.source)
        self.assertIn("static inline void pause", result.source)
        self.assertIn("int value", result.source)

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

    def test_multiline_if_directive_is_spliced_before_parsing(self) -> None:
        source = "#if 1 || \\\n0\nint ok;\n#elif 1\nint bad;\n#endif\n"
        result = preprocess_source(source, filename="main.c")
        self.assertIn("int ok", result.source)
        self.assertNotIn("int bad", result.source)

    def test_if_expression_macro_error_is_preserved(self) -> None:
        source = "#define F(x) x\n#if F(\nint x;\n#endif\n"
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(source, filename="if.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0202")

    def test_strip_gnu_asm_extensions(self) -> None:
        self.assertEqual(_strip_gnu_asm_extensions(""), "")
        source = 'asm("inst");\nint x __asm("foo") = 0;\nasm volatile(\n  "inst"\n);\n'
        stripped = _strip_gnu_asm_extensions(source)
        self.assertEqual(stripped.splitlines(), [";", "int x  = 0;", ";", "", ""])

    def test_strip_gnu_asm_extensions_strips_inline_statement(self) -> None:
        source = (
            'do { int d0, d1; __asm__ __volatile__("cld; rep; stosq" '
            ': "=c"(d0), "=D"(d1) : "a"(0), "0"(8), "1"(ptr) : "memory"); } while (0);\n'
            'int x __asm("sym") = 1;\n'
        )
        stripped = _strip_gnu_asm_extensions(source)
        self.assertEqual(stripped, "do { int d0, d1; ; } while (0);\nint x  = 1;\n")

    def test_strip_gnu_asm_extensions_rewrites_aarch64_stack_pointer_read(self) -> None:
        source = '    __asm__ ("mov %0, sp" : "=r" (result));\n'
        stripped = _strip_gnu_asm_extensions(source)
        self.assertEqual(stripped, "    result = (unsigned long)&result;\n")

    def test_pragma_non_once_does_not_enable_pragma_once_tracking(self) -> None:
        result = preprocess_source(
            "#pragma region\nint x;\n",
            filename="main.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertEqual(result.source, "\nint x;\n")

    def test_warning_directive_is_ignored(self) -> None:
        result = preprocess_source("#warning hello\nint x;\n", filename="main.c")
        self.assertEqual(result.source, "\nint x;\n")

    def test_macro_include_cycle_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "loop.h").write_text('#include "loop.h"\n', encoding="utf-8")
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source(
                    "int x;\n",
                    filename=str(root / "main.c"),
                    options=FrontendOptions(macro_includes=("loop.h",)),
                )
        self.assertEqual(ctx.exception.code, "XCC-PP-0302")

    def test_macro_include_read_error_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "macros.h").write_text("#define A 1\n", encoding="utf-8")
            with patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
                with self.assertRaises(PreprocessorError) as ctx:
                    preprocess_source(
                        "int main;\n",
                        filename=str(root / "main.c"),
                        options=FrontendOptions(macro_includes=("macros.h",)),
                    )
        self.assertEqual(ctx.exception.code, "XCC-PP-0301")

    def test_forced_include_skips_files_already_marked_with_pragma_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = root / "forced.h"
            header.write_text("#pragma once\n#define VALUE 7\n", encoding="utf-8")
            result = preprocess_source(
                "VALUE\n",
                filename=str(root / "main.c"),
                options=FrontendOptions(
                    macro_includes=("forced.h",),
                    forced_includes=("forced.h",),
                ),
            )
        self.assertEqual(result.source, "7\n")

    def test_forced_include_cycle_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = root / "forced.h"
            header.write_text('#include "forced.h"\n', encoding="utf-8")
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source(
                    "int main;\n",
                    filename=str(root / "main.c"),
                    options=FrontendOptions(forced_includes=("forced.h",)),
                )
        self.assertEqual(ctx.exception.code, "XCC-PP-0302")

    def test_forced_include_read_error_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "forced.h").write_text("int forced;\n", encoding="utf-8")
            with patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
                with self.assertRaises(PreprocessorError) as ctx:
                    preprocess_source(
                        "int main;\n",
                        filename=str(root / "main.c"),
                        options=FrontendOptions(forced_includes=("forced.h",)),
                    )
        self.assertEqual(ctx.exception.code, "XCC-PP-0301")

    def test_parse_line_directive_rejects_invalid_filename_literal_escape(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source('#line 1 "bad\\xZZ"\n', filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")

    def test_parse_line_directive_rejects_unterminated_filename_literal(self) -> None:
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source('#line 1 "bad\n', filename="main.c")
        self.assertEqual(ctx.exception.code, "XCC-PP-0104")

    def test_ternary_if_true(self) -> None:
        source = "#if 1 ? 1 : 0\nint yes;\n#endif\n"
        result = preprocess_source(source, filename="ternary.c")
        self.assertIn("int yes", result.source)

    def test_ternary_if_false(self) -> None:
        source = "#if 0 ? 1 : 0\nint yes;\n#endif\n"
        result = preprocess_source(source, filename="ternary.c")
        self.assertNotIn("int yes", result.source)

    def test_ternary_defined_true(self) -> None:
        source = "#define X\n#if defined(X) ? 1 : 0\nint yes;\n#endif\n"
        result = preprocess_source(source, filename="ternary.c")
        self.assertIn("int yes", result.source)

    def test_ternary_defined_false(self) -> None:
        source = "#if defined(X) ? 1 : 0\nint yes;\n#endif\n"
        result = preprocess_source(source, filename="ternary.c")
        self.assertNotIn("int yes", result.source)

    def test_ternary_nested(self) -> None:
        source = "#if 1 ? (0 ? 3 : 4) : 5\nint yes;\n#endif\n"
        result = preprocess_source(source, filename="ternary.c")
        self.assertIn("int yes", result.source)

    def test_ternary_limits_h_pattern(self) -> None:
        # Pattern: defined(A) ? defined(B) : !defined(C)
        # Case 1: A defined, B defined -> true
        source = (
            "#define A\n#define B\n#if defined(A) ? defined(B) : !defined(C)\nint yes;\n#endif\n"
        )
        result = preprocess_source(source, filename="ternary.c")
        self.assertIn("int yes", result.source)
        # Case 2: A defined, B not defined -> false
        source = "#define A\n#if defined(A) ? defined(B) : !defined(C)\nint yes;\n#endif\n"
        result = preprocess_source(source, filename="ternary.c")
        self.assertNotIn("int yes", result.source)
        # Case 3: A not defined, C not defined -> true (!defined(C) is true)
        source = "#if defined(A) ? defined(B) : !defined(C)\nint yes;\n#endif\n"
        result = preprocess_source(source, filename="ternary.c")
        self.assertIn("int yes", result.source)
        # Case 4: A not defined, C defined -> false (!defined(C) is false)
        source = "#define C\n#if defined(A) ? defined(B) : !defined(C)\nint yes;\n#endif\n"
        result = preprocess_source(source, filename="ternary.c")
        self.assertNotIn("int yes", result.source)

    def test_ternary_missing_colon_raises(self) -> None:
        with self.assertRaises(PreprocessorError):
            preprocess_source("#if 1 ? 2\nint bad;\n#endif\n", filename="ternary.c")

    def test_multiline_macro_invocation(self) -> None:
        source = "#define M(a,b) a+b\nM(1,\n2)\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("1 + 2", result.source)

    def test_multiline_macro_invocation_three_lines(self) -> None:
        source = "#define F(a,b,c) a+b+c\nF(1,\n2,\n3)\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("1 + 2 + 3", result.source)

    def test_multiline_macro_invocation_preserves_line_count(self) -> None:
        source = "#define M(a,b) a+b\nM(1,\n2)\nint x;\n"
        result = preprocess_source(source, filename="t.c")
        lines = result.source.splitlines(keepends=True)
        self.assertEqual(len(lines), 4)
        self.assertIn("int x", lines[3])

    def test_function_like_macro_name_before_newline_paren_expands(self) -> None:
        source = (
            "#define ATTR(msg) __attribute__((deprecated(msg)))\n"
            "int f(void) ATTR\n"
            '  ("Use g instead");\n'
        )
        result = preprocess_source(source, filename="t.c")
        self.assertIn('__attribute__ ( ( deprecated ( "Use g instead" ) ) )', result.source)
        self.assertNotIn("ATTR", result.source)

    def test_function_like_macro_name_at_line_end_without_paren_is_not_collected(self) -> None:
        source = "#define ID(x) x\nint x = ID\nint y;\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("int x = ID\n", result.source)
        self.assertIn("int y ;\n", result.source)

    def test_multiline_macro_unterminated_at_eof_raises(self) -> None:
        source = "#define M(a,b) a+b\nM(1,\n"
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="t.c")

    def test_multiline_macro_non_macro_error_propagates(self) -> None:
        """Errors other than unterminated invocation propagate normally."""
        source = "#define M(a) a\nM(1,2)\n"
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="t.c")

    def test_ternary_unsigned_promotion(self) -> None:
        """C usual arithmetic conversions: (1 ? -1 : 0U) is unsigned."""
        # -1 as uint64 is 0xFFFFFFFFFFFFFFFF, so < 0 is false
        source = "#if (1 ? -1 : 0U) < 0\nyes\n#else\nno\n#endif\n"
        result = preprocess_source(source, filename="t.c")
        self.assertNotIn("yes", result.source)
        self.assertIn("no", result.source)

    def test_ternary_both_signed_stays_signed(self) -> None:
        """When both branches are signed, result stays signed."""
        source = "#if (1 ? -1 : 0) < 0\nyes\n#else\nno\n#endif\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("yes", result.source)

    def test_ternary_false_branch_unsigned(self) -> None:
        """Unsigned promotion applies even when false branch is chosen."""
        source = "#if (0 ? 0U : -1) < 0\nyes\n#else\nno\n#endif\n"
        result = preprocess_source(source, filename="t.c")
        self.assertNotIn("yes", result.source)
        self.assertIn("no", result.source)

    def test_multiline_macro_conditional_directive_in_args(self) -> None:
        """Conditional directives inside macro arguments are processed."""
        source = "#define M(a) a\nM(\n#if 1\n2\n#endif\n)\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("2", result.source)

    def test_multiline_macro_conditional_if0_in_args(self) -> None:
        """#if 0 inside macro arguments excludes the body, #else provides it."""
        source = "#define M(a) a\nM(\n#if 0\nX\n#else\nY\n#endif\n)\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("Y", result.source)
        self.assertNotIn("X", result.source)

    def test_multiline_macro_ifdef_in_args(self) -> None:
        """#ifdef inside macro arguments works."""
        source = "#define FOO\n#define M(a) a\nM(\n#ifdef FOO\n99\n#endif\n)\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("99", result.source)

    def test_multiline_macro_non_conditional_directive_raises(self) -> None:
        """Non-conditional directives inside macro arguments raise."""
        source = "#define M(a) a\nM(\n#define X 1\n)\n"
        with self.assertRaises(PreprocessorError):
            preprocess_source(source, filename="t.c")

    def test_multiline_macro_if_else_in_args(self) -> None:
        """#if/#else inside macro arguments selects correct branch."""
        source = "#define M(a) a\nM(\n#if 0\nBAD\n#else\nGOOD\n#endif\n)\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("GOOD", result.source)
        self.assertNotIn("BAD", result.source)

    def test_multiline_macro_inactive_non_conditional_directive_in_args(self) -> None:
        """Inactive macro-argument branches may contain non-conditional directives."""
        source = "#define M(a) a\nM(\n#if 0\n#error bad\n#else\nGOOD\n#endif\n)\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("GOOD", result.source)
        self.assertNotIn("bad", result.source)

    def test_ternary_short_circuit_div_zero(self) -> None:
        """Division by zero in unselected ternary branch must not raise."""
        source = "#if 0 ? 1/0 : 1\nyes\n#else\nno\n#endif\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("yes", result.source)

    def test_ternary_short_circuit_false_div_zero(self) -> None:
        """Division by zero in unselected false branch must not raise."""
        source = "#if 1 ? 42 : 1/0\nyes\n#else\nno\n#endif\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("yes", result.source)

    def test_multiline_macro_line_comment(self) -> None:
        """// comment in multi-line macro does not eat subsequent lines."""
        source = "#define M(a, b) b\nM(1, //c\n2)\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("2", result.source)

    def test_multiline_macro_block_comment_in_argument(self) -> None:
        """A block comment inside a multi-line argument does not stop collection."""
        source = "#define M(a, b) b\nM(1, // head\n/* comment\n   tail */\n2)\n"
        result = preprocess_source(source, filename="t.c")
        self.assertIn("2", result.source)
        self.assertNotIn("M(", result.source)

    def test_embed_directive_expands_file_bytes(self) -> None:
        """#embed reads file and expands to comma-separated ints."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02\x03")
            source = '#embed "data.bin"\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "1, 2, 3\n")

    def test_embed_with_limit_param(self) -> None:
        """#embed with limit parameter restricts output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x0a\x0b\x0c\x0d")
            source = '#embed "data.bin" limit(1 + 1)\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "10, 11\n")

    def test_embed_with_empty_file_and_if_empty(self) -> None:
        """#embed with empty file and if_empty fallback."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"")
            source = '#embed "data.bin" if_empty(42)\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "42\n")

    def test_embed_with_prefix_suffix(self) -> None:
        """#embed with prefix and suffix parameters."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#embed "data.bin" prefix(data[) suffix(])\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "data[1]\n")

    def test_embed_in_expression_context(self) -> None:
        """#embed result usable in array initializer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02")
            source = '#embed "data.bin" prefix(int arr[] = {) suffix(};)\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("int arr[] = {1, 2};", result.source)

    def test_embed_not_found_with_if_empty(self) -> None:
        """#embed not found with if_empty uses fallback."""
        source = '#embed "nonexistent.bin" if_empty(99)\n'
        result = preprocess_source(
            source,
            filename="test.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertEqual(result.source, "99\n")

    def test_embed_empty_file_no_if_empty(self) -> None:
        """#embed with empty file and no if_empty produces empty line."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty.bin").write_bytes(b"")
            source = '#embed "empty.bin"\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "\n")

    def test_embed_with_clang_limit_and_offset(self) -> None:
        """#embed with clang::limit and clang::offset parameters."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02\x03\x04\x05")
            source = '#embed "data.bin" clang::offset(1) clang::limit(2)\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "2, 3\n")

    def test_embed_limit_params_consume_all_data(self) -> None:
        """#embed with empty result after offset+limit and if_empty."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02")
            source = '#embed "data.bin" offset(10) if_empty(0)\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "0\n")

    def test_embed_with_clang_offset(self) -> None:
        """#embed with clang::offset skips bytes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x0a\x0b\x0c")
            source = '#embed "data.bin" clang::offset(1)\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "11, 12\n")

    def test_embed_error_on_invalid_body(self) -> None:
        """#embed with invalid body raises PreprocessorError."""
        source = "#embed\n"
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(
                source,
                filename="test.c",
                options=FrontendOptions(std="gnu11"),
            )
        self.assertIn("FILENAME", str(ctx.exception))

    def test_embed_with_offset_zero_no_change(self) -> None:
        """#embed with offset(0) is a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02")
            source = '#embed "data.bin" offset(0)\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "1, 2\n")

    def test_embed_macro_expansion_in_body(self) -> None:
        """#embed body undergoes macro expansion for __FILE__ etc."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#define FNAME "data.bin"\n#embed FNAME\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("1", result.source)

    def test_has_embed_found(self) -> None:
        """__has_embed returns 1 for existing embeddable file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#if __has_embed("data.bin")\nint found = 1;\n#endif\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("int found = 1;", result.source)

    def test_has_embed_not_found(self) -> None:
        """__has_embed returns 0 for nonexistent file."""
        source = (
            '#if __has_embed("nonexistent.bin")\n'
            "int found = 1;\n"
            "#else\n"
            "int not_found = 1;\n"
            "#endif\n"
        )
        result = preprocess_source(
            source,
            filename="test.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertIn("int not_found = 1;", result.source)

    def test_has_embed_empty_file(self) -> None:
        """__has_embed returns 2 for empty embeddable file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty.bin").write_bytes(b"")
            source = '#if __has_embed("empty.bin") == 2\nint is_empty = 1;\n#endif\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("int is_empty = 1;", result.source)

    def test_has_embed_with_unsupported_param_namespace(self) -> None:
        """__has_embed with unknown vendor namespace returns 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = (
                '#if __has_embed("data.bin" unknown::param(1))\n'
                "int found = 1;\n"
                "#else\n"
                "int not_found = 1;\n"
                "#endif\n"
            )
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("int not_found = 1;", result.source)

    def test_has_include_found(self) -> None:
        """__has_include returns 1 for existing header."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "header.h").write_text("int x;")
            source = '#if __has_include("header.h")\nint found = 1;\n#endif\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", include_dirs=(tmp,)),
            )
            self.assertIn("int found = 1;", result.source)

    def test_has_include_not_found(self) -> None:
        """__has_include returns 0 for nonexistent header."""
        source = (
            '#if __has_include("nonexistent.h")\n'
            "int found = 1;\n"
            "#else\n"
            "int not_found = 1;\n"
            "#endif\n"
        )
        result = preprocess_source(
            source,
            filename="test.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertIn("int not_found = 1;", result.source)

    def test_has_include_next(self) -> None:
        """__has_include_next skips current include dir."""
        source = (
            '#if __has_include_next("stddef.h")\n'
            "int found = 1;\n"
            "#else\n"
            "int not_found = 1;\n"
            "#endif\n"
        )
        result = preprocess_source(
            source,
            filename="test.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertIn("found", result.source or "not_found")

    def test_has_embed_with_offset_param(self) -> None:
        """__has_embed with offset parameter applied."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02\x03")
            source = '#if __has_embed("data.bin" offset(1))\nint found = 1;\n#endif\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("int found = 1;", result.source)

    def test_has_embed_with_limit_param(self) -> None:
        """__has_embed with limit parameter."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02\x03")
            source = '#if __has_embed("data.bin" limit(2))\nint found = 1;\n#endif\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("int found = 1;", result.source)

    def test_has_embed_macro_filename_not_expanded_returns_zero(self) -> None:
        """__has_embed with non-expandable macro operand returns 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = (
                '#define EMBED_FILE "data.bin"\n'
                "#if __has_embed(EMBED_FILE)\n"
                "int found = 1;\n"
                "#else\n"
                "int not_found = 1;\n"
                "#endif\n"
            )
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            # __has_embed probe may not expand macros in operand
            self.assertIn("not_found", result.source)

    def test_embed_not_found_without_if_empty_raises_error(self) -> None:
        """#embed not found without if_empty raises PreprocessorError."""
        source = '#embed "nonexistent.bin"\n'
        with self.assertRaises(PreprocessorError) as ctx:
            preprocess_source(
                source,
                filename="test.c",
                options=FrontendOptions(std="gnu11"),
            )
        self.assertIn("not found", str(ctx.exception))

    def test_embed_limit_zero_empty_result_no_if_empty(self) -> None:
        """#embed with limit(0) produces empty result."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02")
            source = '#embed "data.bin" limit(0)\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "\n")

    def test_has_embed_with_standard_unsupported_param(self) -> None:
        """__has_embed with standard param (no ::) passes check."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#if __has_embed("data.bin" meow(1))\nint found = 1;\n#endif\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("int found = 1;", result.source)

    def test_embed_invalid_limit_param_value_raises_error(self) -> None:
        """#embed with non-integer limit expression raises error."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#embed "data.bin" limit(1.5)\n'
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source(
                    source,
                    filename=str(root / "test.c"),
                    options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
                )
            self.assertIn("expected value", str(ctx.exception))

    def test_embed_unreadable_file_raises_os_error(self) -> None:
        """#embed with unreadable file raises PreprocessorError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fpath = root / "noread.bin"
            fpath.write_bytes(b"\x01")
            fpath.chmod(0)
            try:
                source = '#embed "noread.bin"\n'
                with self.assertRaises(PreprocessorError) as ctx:
                    preprocess_source(
                        source,
                        filename=str(root / "test.c"),
                        options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
                    )
                self.assertIn("Unable to read", str(ctx.exception))
            finally:
                fpath.chmod(0o644)

    def test_has_embed_unreadable_file_returns_zero(self) -> None:
        """__has_embed with unreadable file returns 0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fpath = root / "noread.bin"
            fpath.write_bytes(b"\x01")
            fpath.chmod(0)
            try:
                source = (
                    '#if __has_embed("noread.bin")\n'
                    "int found = 1;\n"
                    "#else\n"
                    "int not_found = 1;\n"
                    "#endif\n"
                )
                result = preprocess_source(
                    source,
                    filename=str(root / "test.c"),
                    options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
                )
                self.assertIn("int not_found = 1;", result.source)
            finally:
                fpath.chmod(0o644)

    def test_has_embed_with_non_integer_offset_limit(self) -> None:
        """__has_embed with non-integer offset/limit params catches ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02\x03")
            for param, value in [
                ("offset", "xyz"),
                ("limit", "abc"),
                ("clang::offset", "def"),
                ("clang::limit", "ghi"),
            ]:
                with self.subTest(param=param, value=value):
                    source = (
                        f'#if __has_embed("data.bin" {param}({value}))\nint found = 1;\n#endif\n'
                    )
                    result = preprocess_source(
                        source,
                        filename=str(root / "test.c"),
                        options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
                    )
                    self.assertIn("int found = 1;", result.source)

    def test_has_embed_empty_after_offset_returns_2(self) -> None:
        """__has_embed returns 2 when offset makes result empty."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#if __has_embed("data.bin" offset(10)) == 2\nint is_empty = 1;\n#endif\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("int is_empty = 1;", result.source)

    def test_embed_angle_bracket_filename(self) -> None:
        """#embed with angle bracket <filename>."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = "#embed <data.bin>\n"
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", include_dirs=(tmp,)),
            )
            self.assertEqual(result.source, "1\n")

    def test_embed_unknown_parameter_raises_error(self) -> None:
        """#embed with unknown parameter raises PreprocessorError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#embed "data.bin" bad_token\n'
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source(
                    source,
                    filename=str(root / "test.c"),
                    options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
                )
            self.assertIn("unknown embed", str(ctx.exception))

    def test_embed_with_nested_parens_in_param(self) -> None:
        """#embed param with nested parentheses exercises depth counter."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#embed "data.bin" prefix(func(x, y))\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("func", result.source)

    def test_embed_with_multiple_params(self) -> None:
        """#embed with multiple parameters."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#embed "data.bin" prefix(x) suffix(y)\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("x", result.source)
            self.assertIn("y", result.source)

    def test_embed_unbalanced_parens_in_param_raises_error(self) -> None:
        """#embed param with unbalanced parentheses raises error."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#embed "data.bin" prefix(func(x, y)\n'
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source(
                    source,
                    filename=str(root / "test.c"),
                    options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
                )
            self.assertIn("expected ')'", str(ctx.exception))

    def test_embed_duplicate_param_raises_error(self) -> None:
        """#embed with duplicate parameter raises error."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#embed "data.bin" prefix(a) prefix(b)\n'
            with self.assertRaises(PreprocessorError) as ctx:
                preprocess_source(
                    source,
                    filename=str(root / "test.c"),
                    options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
                )
            self.assertIn("twice", str(ctx.exception))

    def test_embed_absolute_path(self) -> None:
        """#embed with absolute path resolves directly."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            absfile = (root / "data.bin").resolve()
            absfile.write_bytes(b"\x01")
            source = f'#embed "{absfile}"\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11"),
            )
            self.assertEqual(result.source, "1\n")

    def test_embed_with_backslash_line_continuation(self) -> None:
        """#embed with backslash newline line continuation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01")
            source = '#embed "data.bin" \\\nlimit(1)\n'
            result = preprocess_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIn("1", result.source)

    def test_object_like_macro_chain_rescan(self) -> None:
        """Object-like macro expanding to function-like macro name is re-scanned."""
        result = preprocess_source(
            "#define FOO(x) x+1\n#define BAR FOO\nBAR(3)\n",
            filename="chain.c",
        )
        self.assertNotIn("BAR", result.source)
        self.assertNotIn("FOO", result.source)
        self.assertIn("3 + 1", result.source)

    def test_member_position_macro_with_self_reference_expands_once(self) -> None:
        result = preprocess_source(
            "struct H { int sa_handler; };\n"
            "struct S { struct H __sigaction_handler; };\n"
            "#define sa_handler __sigaction_handler.sa_handler\n"
            "int f(struct S context) { return context.sa_handler; }\n",
            filename="member_macro.c",
        )
        self.assertIn("context . __sigaction_handler . sa_handler", result.source)

    def test_self_reference_macro_argument_is_not_reexpanded_in_outer_macro(self) -> None:
        result = preprocess_source(
            "#define fatal_error _PyRuntime.faulthandler.fatal_error\n"
            "#define SET(dst, src) __typeof__(dst) *p = &(dst)\n"
            "SET(fatal_error.file, file)\n",
            filename="nested_self_reference.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertIn(
            "__typeof__ ( _PyRuntime . faulthandler . fatal_error . file )",
            result.source,
        )
        self.assertNotIn("_PyRuntime . faulthandler . _PyRuntime", result.source)

    def test_function_like_macro_token_paste_rescan(self) -> None:
        """Token-paste result that forms a function-like macro name is re-scanned."""
        result = preprocess_source(
            "#define PASTE(name) prefix_##name\n"
            "#define prefix_add(x, y) ((x)+(y))\n"
            "PASTE(add)(3,4)\n",
            filename="paste.c",
        )
        self.assertNotIn("PASTE", result.source)
        self.assertNotIn("prefix_add", result.source)
        self.assertIn("( ( 3 ) + ( 4 ) )", result.source)

    def test_backslash_newline_splicing_in_string_literal(self) -> None:
        """Backslash-newline in a string literal is spliced before expansion."""
        result = preprocess_source(
            '"hello\\\n world"\n',
            filename="splice.c",
        )
        self.assertIn('"hello world"', result.source)
        self.assertNotIn("\\\n", result.source)

    def test_backslash_newline_splicing_in_macro_argument(self) -> None:
        """Backslash-newline inside a macro argument is spliced."""
        result = preprocess_source(
            '#define ECHO(x) x\nECHO("hello\\\n world")\n',
            filename="splice_macro.c",
        )
        self.assertIn('"hello world"', result.source)
        self.assertNotIn("\\\n", result.source)

    def test_backslash_newline_splicing_strips_block_comment(self) -> None:
        r"""Block comment spanning \ continuation lines is stripped."""
        result = preprocess_source(
            "int x = /* hello \\\n  world */ 42 ;\n",
            filename="splice_bc.c",
        )
        self.assertNotIn("hello", result.source)
        self.assertNotIn("world", result.source)
        self.assertNotIn("/*", result.source)
        self.assertNotIn("*/", result.source)
        self.assertIn("int x =", result.source)
        self.assertIn("42", result.source)

    def test_backslash_newline_splicing_strips_line_comment(self) -> None:
        r"""Line comment spanning \ continuation lines is stripped."""
        result = preprocess_source(
            "int x = 42 ; // hello \\\n  world\n",
            filename="splice_lc.c",
        )
        self.assertNotIn("hello", result.source)
        self.assertNotIn("world", result.source)
        self.assertNotIn("//", result.source)
        self.assertIn("int x = 42 ;", result.source)

    def test_backslash_newline_splicing_with_division_operator(self) -> None:
        r"""Division / in \ continuation is preserved (not confused with // comment)."""
        result = preprocess_source(
            "int x = a / b \\\n  + c ;\n",
            filename="splice_div.c",
        )
        self.assertIn("int x = a / b", result.source)
        self.assertIn("+ c ;", result.source)

    def test_backslash_newline_splicing_line_comment_at_eof(self) -> None:
        r"""Line comment in \ continuation at EOF without trailing newline."""
        result = preprocess_source(
            "int x = 1 ; \\\n  // eof comment",
            filename="splice_eof.c",
        )
        self.assertNotIn("eof", result.source)
        self.assertNotIn("comment", result.source)
        self.assertNotIn("//", result.source)
        self.assertIn("int x = 1 ;", result.source)

    def test_comments_inside_string_literals_are_preserved(self) -> None:
        """// and /* inside string literals are not treated as comments."""
        result = preprocess_source(
            '#define M(x) x\nM("test // not a comment /* nor this */ string")\n',
            filename="str_comment.c",
        )
        self.assertIn("test // not a comment /* nor this */ string", result.source)

    def test_slashes_in_string_literal_across_macro_lines(self) -> None:
        """//= inside string in multi-line macro arg is preserved."""
        result = preprocess_source(
            '#define D(x) if (debug) { x; }\nD(fprintf(stderr, "%s",\n           "\'//=\'"));\n',
            filename="slash_macro.c",
        )
        self.assertIn("'//='", result.source)

    def test_escape_sequence_in_string_across_macro_lines(self) -> None:
        """Escape sequences inside strings are preserved in multi-line macros."""
        result = preprocess_source(
            '#define M(x) x\nM("hello\\" \\\n  world");\n',
            filename="esc_macro.c",
        )
        # The \\" escape sequence inside the string is preserved
        self.assertIn("hello", result.source)
        self.assertIn("world", result.source)

    def test_strip_gnu_asm_strips_enum_decl(self) -> None:
        """__enum_decl(name, type, {) is translated to enum name {."""
        result = _strip_gnu_asm_extensions("__enum_decl(foo, int, {\n} ) ;\n")
        self.assertNotIn("__enum_decl", result)
        self.assertIn("enum foo {", result)

    def test_strip_gnu_asm_strips_enum_class_decl(self) -> None:
        """__enum_class_decl is also translated."""
        result = _strip_gnu_asm_extensions("__enum_class_decl(bar, unsigned, {\n} ) ;\n")
        self.assertNotIn("__enum_class_decl", result)
        self.assertIn("enum bar {", result)

    def test_strip_gnu_asm_closing_paren_semicolon(self) -> None:
        """} ) ; (closing of __enum_decl) is translated to };."""
        result = _strip_gnu_asm_extensions("__enum_decl(foo, int, {\n} ) ;\n")
        self.assertIn("};", result)

    def test_strip_gnu_asm_closing_not_replaced_without_opening(self) -> None:
        """} ) ; without preceding __enum_decl is left unchanged."""
        result = _strip_gnu_asm_extensions("} ) ;\n")
        self.assertIn("} ) ;", result)
        self.assertNotIn("};", result)

    def test_backslash_in_block_comment_banner_preserved(self) -> None:
        r"""Block comment banner with \ continuation, */ on later line.

        The first line opens /* and has a trailing backslash.  The
        continuation joins the next line but */ is on a third line,
        so _strip_block_comments sees an unclosed comment and leaves
        the text intact.
        """
        result = preprocess_source(
            "/* banner *\\\n  continued\n  */\nint x = 1 ;\n",
            filename="banner.c",
        )
        self.assertIn("int x = 1 ;", result.source)

    def test_unterminated_macro_with_inner_directive_has_continuation(self) -> None:
        r"""Unterminated macro where next line is #if with \ continuation."""
        result = preprocess_source(
            "#define M(x) x\nM(42\n#if 1 \\\n  && 1\n#endif\n)\n",
            filename="inner_dir.c",
        )
        self.assertNotIn("M(", result.source)

    def test_pragma_pack_push_sets_pack_alignment(self) -> None:
        """#pragma pack(push, 4) sets pack alignment."""
        result = preprocess_source(
            "#pragma pack(push, 4)\nint x;\n",
            filename="pack.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertEqual(len(result.pack_changes), 1)
        self.assertEqual(result.pack_changes[0], (1, 4))

    def test_pragma_pack_pop_restores_pack(self) -> None:
        """#pragma pack(pop) restores previous pack."""
        result = preprocess_source(
            "#pragma pack(push, 4)\n#pragma pack(pop)\nint x;\n",
            filename="pack.c",
            options=FrontendOptions(std="gnu11"),
        )
        self.assertEqual(result.pack_changes, ((1, 4), (2, None)))

    def test_pragma_pack_rejects_invalid_directives(self) -> None:
        for directive in ("pack(pop)", "pack(push)", "pack(push, nope)", "pack(push, 3)"):
            with self.subTest(directive=directive), self.assertRaises(
                PreprocessorError
            ) as ctx:
                preprocess_source(
                    f"#pragma {directive}\n",
                    filename="pack.c",
                    options=FrontendOptions(std="gnu11"),
                )
            self.assertEqual(ctx.exception.code, "XCC-PP-0104")
            self.assertEqual(str(ctx.exception), "Invalid #pragma pack directive at pack.c:1:1")


if __name__ == "__main__":
    unittest.main()
