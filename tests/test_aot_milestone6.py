import ast
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import analyze_path, analyze_source
from xcc.aot.source_contract import HOSTED_ONLY_MODULES, source_module_name

ROOT = Path(__file__).resolve().parents[1]


class AotMilestone6AdmissionTests(unittest.TestCase):
    def test_all_native_candidate_src_xcc_modules_are_aot_admitted(self) -> None:
        source_root = ROOT / "src/xcc"
        for path in sorted(source_root.rglob("*.py")):
            if source_module_name(source_root, path) in HOSTED_ONLY_MODULES:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                analyze_path(path)

    def test_hosted_only_modules_are_explicit_and_cpython_parseable(self) -> None:
        source_root = ROOT / "src/xcc"
        self.assertEqual(
            {
                "xcc.aot.__main__",
                "xcc.aot.cpython_ast_adapter",
                "xcc.aot.hosted_cli",
                "xcc.aot.parser_oracle",
            },
            set(HOSTED_ONLY_MODULES),
        )
        for module_name in sorted(HOSTED_ONLY_MODULES):
            relative = module_name.split(".")[1:]
            path = source_root.joinpath(*relative).with_suffix(".py")
            with self.subTest(module=module_name):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_binds_bootstrap_container_and_callable_annotations(self) -> None:
        source = (
            "from collections.abc import Callable\n"
            "from pathlib import Path\n"
            "from . import _SourceLocation\n"
            "class _MacroToken:\n"
            "    text: str\n"
            "def expand(\n"
            "    names: list[str],\n"
            "    tokens: list[_MacroToken],\n"
            "    groups: list[list[_MacroToken]],\n"
            "    disabled: frozenset[str],\n"
            "    location: _SourceLocation,\n"
            "    callback: Callable[[str, _SourceLocation, Path | None], bool],\n"
            ") -> dict[str, tuple[list[_MacroToken], frozenset[str]]]:\n"
            "    return {}\n"
        )
        analysis = analyze_source(source, filename="bootstrap_annotations.py")
        function = analysis.types.functions["expand"]
        self.assertEqual(function.parameters[0], ("names", "list[str]"))
        self.assertEqual(function.parameters[1], ("tokens", "list[_MacroToken]"))
        self.assertEqual(function.parameters[2], ("groups", "list[list[_MacroToken]]"))
        self.assertEqual(function.parameters[3], ("disabled", "frozenset[str]"))
        self.assertEqual(function.parameters[4], ("location", "_SourceLocation"))
        self.assertEqual(
            function.parameters[5],
            ("callback", "Callable[[str, _SourceLocation, Path | None], bool]"),
        )
        self.assertEqual(
            function.return_type.name,
            "dict[str, tuple[list[_MacroToken], frozenset[str]]]",
        )

    def test_binds_read_only_iterable_annotations(self) -> None:
        source = (
            "from collections.abc import Iterable, Sequence\n"
            "def choose(argv: Sequence[str] | None, roots: Iterable[str]) -> tuple[str, ...]:\n"
            "    return tuple(roots if argv is None else argv)\n"
        )
        analysis = analyze_source(source, filename="iterable_annotations.py")
        function = analysis.types.functions["choose"]
        self.assertEqual(function.parameters[0], ("argv", "Sequence[str] | None"))
        self.assertEqual(function.parameters[1], ("roots", "Iterable[str]"))
        self.assertEqual(function.return_type.name, "tuple[str, ...]")

    def test_accepts_builtin_method_and_cache_decorators(self) -> None:
        source = (
            "from functools import cache\n"
            "class Factory:\n"
            "    @staticmethod\n"
            "    def make(value: int) -> int:\n"
            "        return value\n"
            "    @classmethod\n"
            "    def wrap(cls, value: int) -> int:\n"
            "        return value\n"
            "@cache\n"
            "def cached(value: int) -> int:\n"
            "    return value\n"
        )
        analysis = analyze_source(source, filename="decorators.py")
        self.assertEqual(
            analysis.types.functions["Factory.make"].parameters,
            (("value", "int"),),
        )
        self.assertEqual(
            analysis.types.functions["Factory.wrap"].parameters,
            (("cls", "Factory"), ("value", "int")),
        )
        self.assertIn("cached", analysis.types.functions)

class AotRepositorySourceContractTests(unittest.TestCase):
    def test_runtime_source_uses_no_future_annotations(self) -> None:
        offenders: list[str] = []
        for path in sorted((ROOT / "src/xcc").rglob("*.py")):
            tree = compile(
                path.read_text(encoding="utf-8"),
                str(path),
                "exec",
                ast.PyCF_ONLY_AST,
            )
            for statement in tree.body:
                if (
                    isinstance(statement, ast.ImportFrom)
                    and statement.module == "__future__"
                    and any(alias.name == "annotations" for alias in statement.names)
                ):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual([], offenders)

if __name__ == "__main__":
    unittest.main()
