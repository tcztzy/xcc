import ast
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import analyze_path, analyze_source
from xcc.aot.source_contract import HOSTED_ONLY_MODULES, source_module_name

ROOT = Path(__file__).resolve().parents[1]
CC_DRIVER_PATH = ROOT / "src/xcc/cc_driver.py"
CODEGEN_PATH = ROOT / "src/xcc/codegen.py"
PARSER_EXPRESSIONS_PATH = ROOT / "src/xcc/parser/expressions.py"
PARSER_EXTENSIONS_PATH = ROOT / "src/xcc/parser/extensions.py"
PREPROCESSOR_CONDITIONALS_PATH = ROOT / "src/xcc/preprocessor/conditionals.py"
PREPROCESSOR_INIT_PATH = ROOT / "src/xcc/preprocessor/__init__.py"
PREPROCESSOR_INCLUDES_PATH = ROOT / "src/xcc/preprocessor/includes.py"
PREPROCESSOR_MACROS_PATH = ROOT / "src/xcc/preprocessor/macros.py"
PREPROCESSOR_PRAGMAS_PATH = ROOT / "src/xcc/preprocessor/pragmas.py"
PREPROCESSOR_TEXT_PATH = ROOT / "src/xcc/preprocessor/text.py"
SEMA_CONSTANTS_PATH = ROOT / "src/xcc/sema/constants.py"
SEMA_CONVERSIONS_PATH = ROOT / "src/xcc/sema/conversions.py"
SEMA_EXPRESSIONS_PATH = ROOT / "src/xcc/sema/expressions.py"
SEMA_INIT_PATH = ROOT / "src/xcc/sema/__init__.py"
SEMA_INITIALIZERS_PATH = ROOT / "src/xcc/sema/initializers.py"
SEMA_STATEMENTS_PATH = ROOT / "src/xcc/sema/statements.py"
SEMA_TYPE_RESOLUTION_PATH = ROOT / "src/xcc/sema/type_resolution.py"
XCC_INIT_PATH = ROOT / "src/xcc/__init__.py"
HOST_INCLUDES_PATH = ROOT / "src/xcc/host_includes.py"
LLVM_API_PATH = ROOT / "src/xcc/llvm_api.py"
EVM_PATH = ROOT / "src/xcc/evm.py"
AARCH64_ASM_PATH = ROOT / "src/xcc/aarch64_asm.py"
X86_64_ASM_PATH = ROOT / "src/xcc/x86_64_asm.py"
AOT_BINDER_PATH = ROOT / "src/xcc/aot/binder.py"
AOT_LOWER_PATH = ROOT / "src/xcc/aot/lower.py"
AOT_NATIVE_PATH = ROOT / "src/xcc/aot/native.py"
AOT_SLICE_PATH = ROOT / "src/xcc/aot/slice.py"
AOT_SUBSET_PATH = ROOT / "src/xcc/aot/subset.py"


class AotMilestone6AdmissionTests(unittest.TestCase):
    def test_all_native_candidate_src_xcc_modules_are_aot_admitted(self) -> None:
        failures: list[str] = []
        source_root = ROOT / "src/xcc"
        for path in sorted(source_root.rglob("*.py")):
            if source_module_name(source_root, path) in HOSTED_ONLY_MODULES:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                try:
                    analyze_path(path)
                except Exception as exc:
                    failures.append(f"{path.relative_to(ROOT)}: {exc}")
        self.assertEqual([], failures)

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

    def test_admits_aot_diagnostic_modules_without_dynamic_getattr(self) -> None:
        for path in (AOT_BINDER_PATH, AOT_LOWER_PATH, AOT_SLICE_PATH, AOT_SUBSET_PATH):
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.types.functions), 0)

    def test_admits_aot_native_harness_without_exec(self) -> None:
        analysis = analyze_path(AOT_NATIVE_PATH)
        self.assertIn("run_native_smoke", analysis.types.functions)

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

    def test_admits_codegen_without_dynamic_loop_body_getattr(self) -> None:
        analysis = analyze_path(CODEGEN_PATH)
        self.assertIn("_LLVMGen._walk_allocas", analysis.types.functions)

    def test_admits_x86_64_backend_without_reflection_or_nonlocal_state(self) -> None:
        analysis = analyze_path(X86_64_ASM_PATH)
        self.assertIn("_X86_64AsmGen._prepare_frame", analysis.types.functions)
        self.assertIn("_X86_64AsmGen._walk_ast_children", analysis.types.functions)

    def test_admits_aarch64_backend_without_reflection_or_nonlocal_state(self) -> None:
        analysis = analyze_path(AARCH64_ASM_PATH)
        self.assertIn("_AArch64AsmGen._prepare_frame", analysis.types.functions)
        self.assertIn("_AArch64AsmGen._walk_ast_children", analysis.types.functions)

    def test_admits_llvm_api_without_global_cache_or_dynamic_getattr(self) -> None:
        analysis = analyze_path(LLVM_API_PATH)
        self.assertIn("llvm", analysis.types.functions)

    def test_admits_evm_without_nonlocal_layout_state(self) -> None:
        analysis = analyze_path(EVM_PATH)
        self.assertIn("_EvmGen._plan_function_layouts", analysis.types.functions)

    def test_admits_parser_and_sema_helpers_without_lambda_callbacks(self) -> None:
        for path in (PARSER_EXTENSIONS_PATH, SEMA_INIT_PATH):
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.types.functions), 0)

    def test_admits_parser_expressions_without_dynamic_getattr(self) -> None:
        analysis = analyze_path(PARSER_EXPRESSIONS_PATH)
        self.assertIn("parse_expression", analysis.types.functions)

    def test_admits_preprocessor_pragmas_without_runtime_regex_search(self) -> None:
        analysis = analyze_path(PREPROCESSOR_PRAGMAS_PATH)
        self.assertIn("_validate_pragma", analysis.types.functions)

    def test_admits_preprocessor_entry_without_lambda_or_runtime_regex_match(self) -> None:
        analysis = analyze_path(PREPROCESSOR_INIT_PATH)
        self.assertIn("_Preprocessor._parse_line_directive", analysis.types.functions)

    def test_admits_preprocessor_text_without_lambda_or_runtime_regex_match(self) -> None:
        analysis = analyze_path(PREPROCESSOR_TEXT_PATH)
        self.assertIn("_expand_object_like_macros", analysis.types.functions)

    def test_admits_sema_helpers_without_dynamic_getattr(self) -> None:
        for path in (
            SEMA_CONSTANTS_PATH,
            SEMA_CONVERSIONS_PATH,
            SEMA_EXPRESSIONS_PATH,
            SEMA_INITIALIZERS_PATH,
            SEMA_STATEMENTS_PATH,
            SEMA_TYPE_RESOLUTION_PATH,
        ):
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.types.functions), 0)


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

    def test_runtime_source_defines_no_marker_decorators(self) -> None:
        forbidden = {"nogil", "aot", "native", "compiled", "jit"}
        offenders: list[str] = []
        for path in sorted((ROOT / "src/xcc").rglob("*.py")):
            tree = compile(
                path.read_text(encoding="utf-8"),
                str(path),
                "exec",
                ast.PyCF_ONLY_AST,
            )
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for decorator in node.decorator_list:
                    name = ast.unparse(decorator).split("(", 1)[0]
                    if name.rsplit(".", 1)[-1] in forbidden:
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}:{name}")
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
