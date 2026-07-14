import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot.analysis import analyze_source
from xcc.aot.slice import lower_core_slice


ROOT = Path(__file__).resolve().parents[1]
AOT_ROOT = ROOT / "src/xcc/aot"


class AotReachabilityTests(unittest.TestCase):
    def test_v376_binder_infers_homogeneous_init_list_field(self) -> None:
        analysis = analyze_source(
            "class Cursor:\n"
            "    def __init__(self) -> None:\n"
            "        self.indents = [0]\n"
            "\n"
            "    def depth(self) -> int:\n"
            "        return len(self.indents)\n",
            filename="cursor.py",
        )

        self.assertEqual(
            analysis.types.classes["Cursor"].fields["indents"].name,
            "list[int]",
        )

    def test_v376_owned_lexer_root_has_real_method_reachability(self) -> None:
        module = lower_core_slice(
            (
                AOT_ROOT / "diag.py",
                AOT_ROOT / "py_ast.py",
                AOT_ROOT / "py_lexer.py",
            ),
            root_targets=("xcc.aot.py_lexer.lex_python",),
        )

        names = {function.name for function in module.functions}
        self.assertIn("xcc.aot.py_lexer.lex_python", names)
        self.assertIn("xcc.aot.py_lexer._PythonLexer.lex", names)
        self.assertIn("xcc.aot.py_lexer._PythonLexer._finish", names)


if __name__ == "__main__":
    unittest.main()
