import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import analyze_path

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


if __name__ == "__main__":
    unittest.main()
