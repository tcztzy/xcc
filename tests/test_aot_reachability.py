import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot.analysis import analyze_source
from xcc.aot.ir import IrCall, IrConstructRecord, IrName, IrRecordType, IrReturn
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.lower import lower_source_to_ir
from xcc.aot.slice import lower_core_slice
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotType


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

    def test_v376_lowerer_resolves_qualified_project_record_type(self) -> None:
        module = lower_source_to_ir(
            "from xcc.aot import py_ast as ast\n"
            "def identity(node: ast.Module) -> ast.Module:\n"
            "    return node\n",
            filename="qualified.py",
            include_functions={"identity"},
            extra_classes={"Module": AotClassInfo("Module", {})},
        )

        function = module.functions[0]
        self.assertEqual(function.params[0].type, IrRecordType("Module"))
        self.assertEqual(function.return_type, IrRecordType("Module"))

    def test_v376_binder_flows_imported_call_type_through_init_local(self) -> None:
        analysis = analyze_source(
            "class Parser:\n"
            "    def __init__(self, source: str) -> None:\n"
            "        tokens = lex_python(source)\n"
            "        self.tokens = tokens\n",
            filename="parser.py",
            extra_functions={
                "lex_python": AotFunctionInfo(
                    "lex_python",
                    (("source", "str"),),
                    AotType("tuple[PyToken, ...]"),
                )
            },
        )

        self.assertEqual(
            analysis.types.classes["Parser"].fields["tokens"].name,
            "tuple[PyToken, ...]",
        )

    def test_v376_lowerer_resolves_qualified_record_checks_and_constructors(self) -> None:
        module = lower_source_to_ir(
            "from xcc.aot import py_ast as ast\n"
            "def is_name(node: ast.AST) -> bool:\n"
            "    return isinstance(node, ast.Name)\n"
            "def make_name() -> ast.Name:\n"
            "    return ast.Name()\n",
            filename="qualified_records.py",
            include_functions={"is_name", "make_name"},
            extra_classes={
                "AST": AotClassInfo("AST", {}),
                "Name": AotClassInfo("Name", {}, ("AST",)),
            },
        )

        check = module.functions[0].body[0]
        construct = module.functions[1].body[0]
        self.assertIsInstance(check, IrReturn)
        self.assertIsInstance(check.value, IrCall)
        self.assertEqual(check.value.target, "isinstance")
        self.assertEqual(check.value.args[1], IrName("Name", IrRecordType("object")))
        self.assertIsInstance(construct, IrReturn)
        self.assertIsInstance(construct.value, IrConstructRecord)
        self.assertEqual(construct.value.record, "Name")

    def test_v376_global_record_constructor_map_lowers_to_runtime_dispatch(self) -> None:
        module = lower_source_to_ir(
            "class Node:\n"
            "    pass\n"
            "class Add(Node):\n"
            "    pass\n"
            "class Sub(Node):\n"
            "    pass\n"
            "OPS = {'+': Add, '-': Sub}\n"
            "def choose(symbol: str) -> Node:\n"
            "    constructor = OPS.get(symbol)\n"
            "    if constructor is None:\n"
            "        return Add()\n"
            "    return constructor()\n",
            filename="constructor_map.py",
        )

        final_return = module.functions[0].body[-1]
        self.assertIsInstance(final_return, IrReturn)
        self.assertIsInstance(final_return.value, IrCall)
        self.assertEqual(final_return.value.target, "__record_construct0")
        llvm_text = emit_llvm_text(module)
        self.assertNotIn("@__record_construct0", llvm_text)
        self.assertIn("call ptr @malloc", llvm_text)

    def test_v376_isinstance_narrows_stable_subscript_assignment(self) -> None:
        module = lower_source_to_ir(
            "class Node:\n"
            "    pass\n"
            "class Generator(Node):\n"
            "    elt: Node\n"
            "def first(items: list[Node]) -> Node:\n"
            "    if isinstance(items[0], Generator):\n"
            "        generator = items[0]\n"
            "        return generator.elt\n"
            "    return items[0]\n",
            filename="subscript_narrowing.py",
        )

        function = module.functions[0]
        self.assertEqual(function.name, "first")
        emit_llvm_text(module)


if __name__ == "__main__":
    unittest.main()
