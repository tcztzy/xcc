import ast
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import py_ast
from xcc.aot.cpython_ast_adapter import parse_cpython_source
from xcc.aot.analysis import analyze_module
from xcc.aot.diag import AotError
from xcc.aot.lower import lower_analysis_to_ir
from xcc.aot.module import AotModule, parse_source
from xcc.aot.subset import check_subset

ROOT = Path(__file__).resolve().parents[1]


class AotOwnedAstTests(unittest.TestCase):
    def test_adapter_builds_project_owned_nodes_with_spans_and_fields(self) -> None:
        tree = parse_cpython_source(
            "def answer(value: int = 42) -> int:\n    return value\n",
            filename="x.py",
        )

        self.assertIsInstance(tree, py_ast.Module)
        self.assertNotIsInstance(tree, ast.AST)
        function = tree.body[0]
        self.assertIsInstance(function, py_ast.FunctionDef)
        self.assertEqual(function.name, "answer")
        self.assertEqual(function.lineno, 1)
        self.assertEqual(function.end_lineno, 2)
        self.assertEqual(py_ast.unparse(function.returns), "int")
        self.assertEqual(function.args.defaults[0].value, 42)

    def test_walk_and_visitor_use_owned_child_edges(self) -> None:
        tree = parse_cpython_source("value = left + right\n", filename="x.py")
        names = [node.id for node in py_ast.walk(tree) if isinstance(node, py_ast.Name)]

        self.assertEqual(names, ["value", "left", "right"])

    def test_nodes_accept_metadata_and_keep_child_sequences_immutable(self) -> None:
        load = py_ast.Load()
        name = py_ast.Name(
            "value",
            load,
            span=py_ast.SourceSpan(1, 0, 1, 5),
            children=(load,),
        )
        module = py_ast.Module(body=(py_ast.Expr(name),), type_ignores=())

        self.assertEqual((name.lineno, name.end_col_offset), (1, 5))
        self.assertEqual(name.children, (load,))
        self.assertIsInstance(module.body, tuple)
        with self.assertRaises(AttributeError):
            module.body.append(py_ast.Pass())

    def test_adapter_span_columns_are_utf8_bytes_and_end_exclusive(self) -> None:
        tree = parse_cpython_source('π = "é"\n', filename="unicode.py")
        assignment = tree.body[0]
        target = assignment.targets[0]
        value = assignment.value

        self.assertEqual(
            (target.lineno, target.col_offset, target.end_lineno, target.end_col_offset),
            (1, 0, 1, 2),
        )
        self.assertEqual(
            (value.lineno, value.col_offset, value.end_lineno, value.end_col_offset),
            (1, 5, 1, 9),
        )

    def test_common_renderer_does_not_depend_on_hosted_text(self) -> None:
        module = parse_source(
            "@(left + right)\ndef answer() -> int:\n    return 1\n",
            filename="decorator.py",
        )
        for node in py_ast.walk(module.tree):
            object.__setattr__(node, "text", "")

        with self.assertRaises(AotError) as ctx:
            check_subset(module)

        self.assertEqual(
            ctx.exception.diagnostics[0].message,
            "Unsupported decorator: left + right",
        )

    def test_module_parse_boundary_exposes_only_owned_ast(self) -> None:
        module = parse_source("value: int = 1\n", filename="owned.py")

        self.assertIsInstance(module.tree, py_ast.Module)
        self.assertNotIsInstance(module.tree, ast.Module)

    def test_common_analysis_and_lowering_accept_owned_module(self) -> None:
        module = parse_source("def answer() -> int:\n    return 42\n", filename="owned.py")

        analysis = analyze_module(module)
        lowered = lower_analysis_to_ir(analysis, entry="answer")

        self.assertEqual(lowered.entry, "answer")
        self.assertEqual(lowered.functions[0].name, "answer")

    def test_bound_defaults_do_not_leak_cpython_ast(self) -> None:
        module = parse_source(
            "def answer(value: int = 42) -> int:\n    return value\n",
            filename="owned.py",
        )

        analysis = analyze_module(module)
        default = analysis.types.functions["answer"].parameter_defaults[0]

        self.assertIsInstance(default, py_ast.Constant)
        self.assertNotIsInstance(default, ast.AST)
        for node in py_ast.walk(analysis.module.tree):
            self.assertNotIsInstance(node, ast.AST)

    def test_adapter_covers_every_active_source_without_unsupported_nodes(self) -> None:
        unsupported: list[str] = []
        node_kinds: set[str] = set()
        for path in sorted((ROOT / "src/xcc").rglob("*.py")):
            tree = parse_cpython_source(path.read_text(encoding="utf-8"), filename=str(path))
            for node in py_ast.walk(tree):
                node_kinds.add(type(node).__name__)
                if isinstance(node, py_ast.UnsupportedNode):
                    unsupported.append(f"{path.relative_to(ROOT)}:{node.kind}")

        self.assertEqual(unsupported, [])
        self.assertTrue(
            {
                "FunctionDef",
                "ClassDef",
                "For",
                "Try",
                "Dict",
                "Subscript",
                "JoinedStr",
            }.issubset(node_kinds)
        )


if __name__ == "__main__":
    unittest.main()
