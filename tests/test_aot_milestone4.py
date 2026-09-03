import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotError,
    analyze_path,
    analyze_source,
    collect_slice_inputs,
    core_entry_wrapper,
    lower_core_entry_slice,
    lower_core_slice,
    run_native_core_smoke,
)
from xcc.llvm_tools import find_llc

ROOT = Path(__file__).resolve().parents[1]
AST_PATH = ROOT / "src/xcc/ast.py"
LEXER_PATH = ROOT / "src/xcc/lexer.py"
LEXER_SLICE = (
    ROOT / "src/xcc/types.py",
    ROOT / "src/xcc/diag.py",
    ROOT / "src/xcc/options.py",
    AST_PATH,
    LEXER_PATH,
)


class AotMilestone4AdmissionTests(unittest.TestCase):
    def test_binds_lexer_token_kind_enum_and_token_dataclass(self) -> None:
        analysis = analyze_path(LEXER_PATH)
        self.assertIn("TokenKind", analysis.types.classes)
        self.assertIn("Token", analysis.types.classes)
        self.assertEqual(analysis.types.classes["Token"].fields["line"].name, "int")

    def test_binds_ast_forward_refs_lists_and_default_factories(self) -> None:
        analysis = analyze_path(AST_PATH)
        self.assertIn("TranslationUnit", analysis.types.classes)
        fields = analysis.types.classes["TranslationUnit"].fields
        self.assertEqual(fields["functions"].name, "list['FunctionDef']")
        self.assertEqual(fields["declarations"].name, "list['Stmt']")
        self.assertIn("TypeSpec", analysis.types.classes)


class AotMilestone4SubsetTests(unittest.TestCase):
    def test_accepts_enum_auto_and_compile_time_regex_constants(self) -> None:
        source = (
            "import re\n"
            "from enum import Enum, auto\n"
            "R = re.compile(r'^[0-9]+$')\n"
            "class Kind(Enum):\n"
            "    VALUE = auto()\n"
        )
        analysis = analyze_source(source, filename="enum_regex.py")
        self.assertIn("Kind", analysis.summary.classes)
        self.assertIn("re", analysis.summary.imports)

    def test_rejects_runtime_regex_search_in_milestone4(self) -> None:
        source = (
            "import re\n"
            "def f(value: str) -> bool:\n"
            "    return re.search('x', value) is not None\n"
        )
        with self.assertRaises(AotError) as ctx:
            analyze_source(source, filename="bad_regex.py")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SUBSET-0004")

    def test_accepts_attribute_call_with_computed_receiver_in_subset_scan(self) -> None:
        source = (
            "def build() -> object:\n"
            "    return object()\n"
            "def f() -> int:\n"
            "    build().touch()\n"
            "    return 1\n"
        )
        analysis = analyze_source(source, filename="computed_receiver.py")
        self.assertEqual(analysis.summary.functions, ("build", "f"))


class AotMilestone4SliceTests(unittest.TestCase):
    def test_collects_frontend_slice_modules(self) -> None:
        modules = collect_slice_inputs(LEXER_SLICE)
        self.assertEqual(
            [module.name for module in modules],
            ["xcc.ast", "xcc.diag", "xcc.lexer", "xcc.options", "xcc.types"],
        )

    def test_builds_lexer_entry_wrappers(self) -> None:
        translate = core_entry_wrapper("xcc.lexer:translate_source", "trigraph_splice")
        self.assertEqual(translate.name, "__xcc_aot_core_entry")
        self.assertEqual(translate.body[0].value.target, "xcc.lexer.translate_source")
        lexer = core_entry_wrapper("xcc.lexer:lex", "simple_declaration")
        self.assertEqual(lexer.name, "__xcc_aot_core_entry")
        self.assertEqual(lexer.body[0].value.target, "xcc.lexer._aot_token_summary_for_source")
        header = core_entry_wrapper("xcc.lexer:lex_pp", "header_name")
        self.assertEqual(header.name, "__xcc_aot_core_entry")
        self.assertEqual(header.body[0].value.target, "xcc.lexer._aot_header_summary_for_source")
        error = core_entry_wrapper("xcc.lexer:lex_error", "unterminated_string")
        self.assertEqual(error.name, "__xcc_aot_core_entry")
        self.assertEqual(error.body[0].value.target, "xcc.lexer._aot_error_summary_for_source")
        self.assertEqual(error.body[1].value.value, 2)

    def test_lowers_lexer_translate_entry_without_unrelated_frontend_methods(self) -> None:
        wrapper = core_entry_wrapper("xcc.lexer:translate_source", "trigraph_splice")
        module = lower_core_entry_slice(LEXER_SLICE, wrapper)
        names = {function.name for function in module.functions}
        self.assertEqual(names, {"xcc.lexer.translate_source", "__xcc_aot_core_entry"})
        translate = next(
            function for function in module.functions if function.name == "xcc.lexer.translate_source"
        )
        self.assertEqual(translate.body, ())

    def test_lowers_lexer_token_summary_entry_as_native_leaf(self) -> None:
        cases = (
            ("xcc.lexer:lex", "simple_declaration", "xcc.lexer._aot_token_summary_for_source"),
            ("xcc.lexer:lex_pp", "header_name", "xcc.lexer._aot_header_summary_for_source"),
            ("xcc.lexer:lex_error", "unterminated_string", "xcc.lexer._aot_error_summary_for_source"),
        )
        for entry, fixture, target in cases:
            with self.subTest(entry=entry, fixture=fixture):
                wrapper = core_entry_wrapper(entry, fixture)
                module = lower_core_entry_slice(LEXER_SLICE, wrapper)
                names = {function.name for function in module.functions}
                self.assertEqual(names, {target, "__xcc_aot_core_entry"})
                summary = next(function for function in module.functions if function.name == target)
                self.assertEqual(summary.body, ())

    def test_entry_driven_core_slice_handles_duplicate_roots_and_record_discovery(self) -> None:
        module = lower_core_slice(
            (ROOT / "src/xcc/options.py",),
            root_targets=(
                "xcc.options.normalize_options",
                "xcc.options.normalize_options",
            ),
        )
        self.assertEqual(
            [function.name for function in module.functions],
            [
                "xcc.options.normalize_options",
                "xcc.options.FrontendOptions.__post_init__",
            ],
        )
        self.assertIn("FrontendOptions", {record.name for record in module.records})


def _real_llc() -> str | None:
    try:
        path = find_llc()
    except ValueError:
        return None
    return path if Path(path).is_file() else None


class AotMilestone4NativeTests(unittest.TestCase):
    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_translate_source_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            LEXER_SLICE,
            entry="xcc.lexer:translate_source",
            fixture="trigraph_splice",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, "int#x=1;\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_lex_simple_declaration_matches_cpython_summary(self) -> None:
        result = run_native_core_smoke(
            LEXER_SLICE,
            entry="xcc.lexer:lex",
            fixture="simple_declaration",
            llc=_real_llc(),
        )
        self.assertEqual(
            result.native_stdout,
            "KEYWORD:int:1:1|IDENT:main:1:5|PUNCTUATOR:(:1:9|PUNCTUATOR:):1:10|"
            "PUNCTUATOR:{:1:12|KEYWORD:return:1:14|INT_CONST:0:1:21|"
            "PUNCTUATOR:;:1:22|PUNCTUATOR:}:1:24|EOF:None:1:25\n",
        )
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_lex_pp_header_name_matches_cpython_summary(self) -> None:
        result = run_native_core_smoke(
            LEXER_SLICE,
            entry="xcc.lexer:lex_pp",
            fixture="header_name",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, "HEADER_NAME:<stdio.h>:1:1|EOF:None:1:10\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_lexer_error_matches_cpython_message(self) -> None:
        result = run_native_core_smoke(
            LEXER_SLICE,
            entry="xcc.lexer:lex_error",
            fixture="unterminated_string",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_returncode, 2)
        self.assertIn("Unterminated string literal at 1:2", result.native_stdout)


if __name__ == "__main__":
    unittest.main()
