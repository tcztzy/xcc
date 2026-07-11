import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import py_ast
from xcc.aot.cpython_ast_adapter import parse_cpython_source
from xcc.aot.diag import AotError
from xcc.aot.py_parser import parse_subset_source

ROOT = Path(__file__).resolve().parents[1]


class AotPythonParserTests(unittest.TestCase):
    def assert_matches_cpython(self, source: str) -> None:
        subset = parse_subset_source(source, filename="fixture.py")
        hosted = parse_cpython_source(source, filename="fixture.py")

        self.assertEqual(subset.tree, hosted)
        self.assertIsInstance(subset.tree, py_ast.Module)
        self.assertEqual(subset.source, source)

    def test_definitions_decorators_imports_and_parameter_shapes(self) -> None:
        self.assert_matches_cpython(
            "from .types import Item as Renamed\n"
            "import os.path as path\n"
            "\n"
            "@dataclass(frozen=True, kw_only=True)\n"
            "class Box(Base):\n"
            "    value: int = 1\n"
            "\n"
            "    @property\n"
            "    def doubled(self) -> int:\n"
            "        return self.value * 2\n"
            "\n"
            "    def choose(\n"
            "        self, item: int = 2, *values: int, flag: bool = False, **options: str\n"
            "    ) -> int:\n"
            "        return item if flag else values[0]\n"
        )

    def test_control_flow_assignments_and_exception_forms(self) -> None:
        self.assert_matches_cpython(
            "def run(items: list[int]) -> int:\n"
            "    total = 0\n"
            "    left = right = 1\n"
            "    for index, item in enumerate(items):\n"
            "        if index < 0:\n"
            "            continue\n"
            "        elif item == 0:\n"
            "            break\n"
            "        total += item\n"
            "    else:\n"
            "        total -= 1\n"
            "    while total > 10:\n"
            "        total = total // 2\n"
            "    try:\n"
            "        result: int = items[-1]\n"
            "    except ValueError as error:\n"
            "        raise RuntimeError(str(error)) from error\n"
            "    finally:\n"
            "        total = total | 1\n"
            "    with open('value.txt') as stream:\n"
            "        result = int(stream.read())\n"
            "    assert result >= 0, 'negative'\n"
            "    return result\n"
        )

    def test_containers_calls_comprehensions_and_slices(self) -> None:
        self.assert_matches_cpython(
            "def collect(values: list[int]) -> tuple[object, ...]:\n"
            "    pairs = {str(value): value for value in values if value not in {0, 1}}\n"
            "    doubled = [value * 2 for value in values if value > 0]\n"
            "    unique = {value for value in values}\n"
            "    lazy = (value + 1 for value in values)\n"
            "    call = target(*values, named=doubled[1:-1:2], **pairs)\n"
            "    return ({'pairs': pairs, **extra}, doubled, unique, lazy, call)\n"
        )

    def test_string_bytes_fstrings_and_adjacent_literals(self) -> None:
        self.assert_matches_cpython(
            "def render(name: str, value: int) -> tuple[str, bytes]:\n"
            "    text = 'prefix ' r'raw\\n' f'{name}={value!r:04d}' '{{done}}'\n"
            "    data = b'\\x41' b'\\n'\n"
            "    return text, data\n"
        )

    def test_owned_nodes_preserve_utf8_byte_spans_and_children(self) -> None:
        module = parse_subset_source('π = "é"\n', filename="unicode.py")
        assignment = module.tree.body[0]
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
        self.assertIn(target, assignment.children)
        self.assertIn(value, assignment.children)

    def test_nested_grouping_extent_matches_cpython(self) -> None:
        source = "value = ((left + right)) * 2\n"
        subset = parse_subset_source(source, filename="grouped.py").tree
        hosted = parse_cpython_source(source, filename="grouped.py")

        subset_spans = tuple(node.span for node in py_ast.walk(subset))
        hosted_spans = tuple(node.span for node in py_ast.walk(hosted))
        self.assertEqual(subset_spans, hosted_spans)

    def test_all_active_sources_match_cpython_owned_ast(self) -> None:
        failures: list[str] = []
        for path in sorted((ROOT / "src/xcc").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            try:
                subset = parse_subset_source(source, filename=str(path)).tree
                hosted = parse_cpython_source(source, filename=str(path))
            except Exception as error:
                failures.append(f"{path.relative_to(ROOT)}: {error}")
                continue
            if subset != hosted:
                failures.append(f"{path.relative_to(ROOT)}: owned AST differs")
        self.assertEqual(failures, [])

    def test_all_active_source_spans_and_child_edges_match_cpython(self) -> None:
        failures: list[str] = []
        for path in sorted((ROOT / "src/xcc").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            subset = parse_subset_source(source, filename=str(path)).tree
            hosted = parse_cpython_source(source, filename=str(path))
            subset_nodes = py_ast.walk(subset)
            hosted_nodes = py_ast.walk(hosted)
            subset_kinds = tuple(type(node).__name__ for node in subset_nodes)
            hosted_kinds = tuple(type(node).__name__ for node in hosted_nodes)
            if subset_kinds != hosted_kinds:
                failures.append(f"{path.relative_to(ROOT)}: child edge order differs")
                continue
            for index, (left, right) in enumerate(zip(subset_nodes, hosted_nodes)):
                if left.span != right.span:
                    failures.append(
                        f"{path.relative_to(ROOT)} node {index} {type(left).__name__}: "
                        f"{left.span!r} != {right.span!r}"
                    )
                    break
        self.assertEqual(failures, [])

    def test_rejected_syntax_has_stable_diagnostics(self) -> None:
        cases = (
            ("async def run():\n    pass\n", "XCC-AOT-PYPARSE-0002"),
            ("match value:\n    case 1:\n        pass\n", "XCC-AOT-PYPARSE-0002"),
            ("value = lambda item: item\n", "XCC-AOT-PYPARSE-0002"),
            ("value = (item := 1)\n", "XCC-AOT-PYPARSE-0002"),
            ("if True print('bad')\n", "XCC-AOT-PYPARSE-0001"),
        )
        for source, code in cases:
            with self.subTest(source=source):
                with self.assertRaises(AotError) as ctx:
                    parse_subset_source(source, filename="bad.py")
                self.assertEqual(ctx.exception.diagnostics[0].code, code)


if __name__ == "__main__":
    unittest.main()
