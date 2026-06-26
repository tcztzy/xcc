import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import AotError, analyze_path, analyze_source

ROOT = Path(__file__).resolve().parents[1]
AST_PATH = ROOT / "src/xcc/ast.py"
LEXER_PATH = ROOT / "src/xcc/lexer.py"


class AotMilestone4AdmissionTests(unittest.TestCase):
    def test_analyzes_ast_and_lexer_modules(self) -> None:
        for path in (AST_PATH, LEXER_PATH):
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.summary.classes), 0)
                self.assertGreater(len(analysis.types.classes), 0)

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


if __name__ == "__main__":
    unittest.main()
