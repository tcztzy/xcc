import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import analyze_path, analyze_source


ROOT = Path(__file__).resolve().parents[1]
CC_DRIVER_PATH = ROOT / "src/xcc/cc_driver.py"
PREPROCESSOR_CONDITIONALS_PATH = ROOT / "src/xcc/preprocessor/conditionals.py"
PREPROCESSOR_INCLUDES_PATH = ROOT / "src/xcc/preprocessor/includes.py"
PREPROCESSOR_MACROS_PATH = ROOT / "src/xcc/preprocessor/macros.py"
XCC_INIT_PATH = ROOT / "src/xcc/__init__.py"
HOST_INCLUDES_PATH = ROOT / "src/xcc/host_includes.py"
AOT_BINDER_PATH = ROOT / "src/xcc/aot/binder.py"
AOT_LOWER_PATH = ROOT / "src/xcc/aot/lower.py"
AOT_SLICE_PATH = ROOT / "src/xcc/aot/slice.py"
AOT_SUBSET_PATH = ROOT / "src/xcc/aot/subset.py"


class AotMilestone6AdmissionTests(unittest.TestCase):
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

    def test_admits_aot_diagnostic_modules_without_dynamic_getattr(self) -> None:
        for path in (AOT_BINDER_PATH, AOT_LOWER_PATH, AOT_SLICE_PATH, AOT_SUBSET_PATH):
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.types.functions), 0)

    def test_admits_preprocessor_modules_blocked_by_common_annotations(self) -> None:
        for path in (
            HOST_INCLUDES_PATH,
            PREPROCESSOR_CONDITIONALS_PATH,
            PREPROCESSOR_INCLUDES_PATH,
            PREPROCESSOR_MACROS_PATH,
            XCC_INIT_PATH,
        ):
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.types.functions), 0)

    def test_admits_driver_without_lambda_callbacks(self) -> None:
        analysis = analyze_path(CC_DRIVER_PATH)
        self.assertIn("main", analysis.types.functions)


if __name__ == "__main__":
    unittest.main()
