import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc.aot import slice as aot_slice
from xcc.aot.analysis import analyze_source
from xcc.aot.ir import (
    IrAssign,
    IrCall,
    IrConstructRecord,
    IrIntType,
    IrName,
    IrRecordType,
    IrReturn,
    IrTuple,
    IrTupleType,
)
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.lower import lower_source_to_ir
from xcc.aot.module import parse_source
from xcc.aot.slice import (
    AotSliceInput,
    _add_missing_records,
    _function_record_names,
    _slice_class_tables,
    lower_core_slice,
    lower_named_slice,
    render_native_reachability,
)
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotType

ROOT = Path(__file__).resolve().parents[1]
AOT_ROOT = ROOT / "src/xcc/aot"


class AotReachabilityTests(unittest.TestCase):
    def test_v441_reachability_caches_sorted_names_and_uses_dict_membership(
        self,
    ) -> None:
        source = inspect.getsource(render_native_reachability)
        self.assertNotIn(".keys()", source)
        self.assertNotIn(" & ", source)
        self.assertEqual(source.count("sorted(functions)"), 1)
        self.assertEqual(source.count("sorted(records)"), 1)

    def test_v401_reachability_materializes_each_record_once(self) -> None:
        source = (
            "class Left:\n"
            "    value: int\n"
            "class Right:\n"
            "    value: int\n"
            "def consume(value: Right) -> int:\n"
            "    return value.value\n"
            "def main(left: Left, right: Right) -> int:\n"
            "    return left.value + consume(right)\n"
        )
        inputs = (AotSliceInput("pkg.model", Path("pkg/model.py"), source),)
        seen: set[str] = set()

        with patch(
            "xcc.aot.slice.lower_analysis_to_ir",
            wraps=aot_slice.lower_analysis_to_ir,
        ) as lower_analysis:
            module = lower_named_slice(inputs, root_targets=("pkg.model.main",))

        for call in lower_analysis.call_args_list:
            included = set(call.kwargs.get("include_records") or ())
            self.assertTrue(seen.isdisjoint(included), (seen, included))
            seen.update(included)
        self.assertEqual(seen, {"Left", "Right"})
        self.assertEqual({record.name for record in module.records}, seen)

    def test_module_function_alias_table_excludes_shared_base_entries(self) -> None:
        run = AotFunctionInfo("run", (), AotType("int"))
        step = AotFunctionInfo("Worker.step", (), AotType("int"))
        unrelated = AotFunctionInfo("skip", (), AotType("int"))

        aliased = aot_slice._function_types_with_module_aliases(
            {
                "pkg.target.run": run,
                "pkg.target.Worker.step": step,
                "pkg.unrelated.skip": unrelated,
            },
            {"local_run": "pkg.target.run", "target": "pkg.target"},
        )

        self.assertEqual(
            aliased,
            {"local_run": run, "target.run": run, "target.Worker.step": step},
        )

    def test_named_slice_reuses_source_contract_parsed_snapshot(self) -> None:
        source = "def main() -> int:\n    return 0\n"
        parsed = parse_source(source, filename="pkg/cli.py")
        modules = (AotSliceInput("pkg.cli", Path("pkg/cli.py"), source, parsed),)

        with patch("xcc.aot.slice.parse_source", side_effect=AssertionError("reparsed")):
            module = lower_named_slice(modules, root_targets=("pkg.cli.main",))

        self.assertEqual(tuple(function.name for function in module.functions), ("pkg.cli.main",))

    def test_named_slice_closes_reachable_record_layout_over_base_chain(self) -> None:
        source = (
            "class Root:\n"
            "    value: int\n"
            "class Middle(Root):\n"
            "    pass\n"
            "class Leaf(Middle):\n"
            "    label: str\n"
            "def main(value: Leaf) -> int:\n"
            "    return value.value\n"
        )
        parsed = parse_source(source, filename="pkg/model.py")
        with (
            patch(
                "xcc.aot.slice._function_types_with_module_aliases",
                wraps=aot_slice._function_types_with_module_aliases,
            ) as expand_function_types,
            patch(
                "xcc.aot.slice._prepare_analysis_lowerer",
                wraps=aot_slice._prepare_analysis_lowerer,
            ) as prepare_lowerer,
            patch(
                "xcc.aot.slice._collect_global_string_container_constants",
                wraps=aot_slice._collect_global_string_container_constants,
            ) as collect_global_containers,
        ):
            module = lower_named_slice(
                (AotSliceInput("pkg.model", Path("pkg/model.py"), source, parsed),),
                root_targets=("pkg.model.main",),
            )

        self.assertEqual(expand_function_types.call_count, 1)
        self.assertEqual(prepare_lowerer.call_count, 1)
        self.assertEqual(collect_global_containers.call_count, 1)
        self.assertEqual(
            {record.name for record in module.records},
            {"Leaf", "Middle", "Root"},
        )
        reachability = render_native_reachability(
            module,
            root="pkg.model.main",
            parser="subset",
        )
        self.assertIn("edge=record:Leaf->record:Middle;reason=layout", reachability)
        self.assertIn("edge=record:Middle->record:Root;reason=layout", reachability)

    def test_missing_record_closure_batches_one_module_frontier(self) -> None:
        source = "class Left:\n    value: int\nclass Right:\n    label: str\n"
        module_input = AotSliceInput("pkg.model", Path("pkg/model.py"), source)
        analysis = analyze_source(source, filename="pkg/model.py")
        records = {}

        with patch(
            "xcc.aot.slice.lower_analysis_to_ir",
            wraps=aot_slice.lower_analysis_to_ir,
        ) as lower_analysis:
            _add_missing_records(
                {"Left", "Right"},
                records,
                {"Left": "pkg.model", "Right": "pkg.model"},
                {"pkg.model": module_input},
                {"pkg.model": source},
                analysis.types.classes,
                {},
                analysis_cache={"pkg.model": analysis},
                module_function_types={"pkg.model": {}},
            )

        self.assertEqual(lower_analysis.call_count, 1)
        self.assertEqual(set(lower_analysis.call_args.kwargs["include_records"]), {"Left", "Right"})
        self.assertEqual(set(records), {"Left", "Right"})

    def test_v376_class_refinement_preserves_deterministic_owner(self) -> None:
        modules = (
            AotSliceInput("xcc.aot.py_ast", AOT_ROOT / "py_ast.py"),
            AotSliceInput("xcc.ast", ROOT / "src/xcc/ast.py"),
        )
        source_cache = {module.name: module.path.read_text(encoding="utf-8") for module in modules}

        classes, owners = _slice_class_tables(modules, source_cache, {})

        self.assertEqual(owners["FunctionDef"], "xcc.aot.py_ast")
        self.assertIn("args", classes["FunctionDef"].fields)
        self.assertNotIn("is_variadic", classes["FunctionDef"].fields)

    def test_v376_binder_infers_comprehension_backed_init_fields(self) -> None:
        analysis = analyze_source(
            "class Item:\n"
            "    name: str\n"
            "class Module:\n"
            "    items: tuple[Item, ...]\n"
            "class Index:\n"
            "    def __init__(self, module: Module) -> None:\n"
            "        self.by_name = {item.name: item for item in module.items}\n"
            "        self.ids = {\n"
            "            name: index + 1\n"
            "            for index, name in enumerate(sorted(self.by_name))\n"
            "        }\n",
            filename="comprehension-fields.py",
        )

        fields = analysis.types.classes["Index"].fields
        self.assertEqual(fields["by_name"].name, "dict[str, Item]")
        self.assertEqual(fields["ids"].name, "dict[str, int]")

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

    def test_v376_binder_preserves_value_type_for_optional_dict_or_empty(self) -> None:
        analysis = analyze_source(
            "class Registry:\n"
            "    def __init__(self, values: dict[str, int] | None = None) -> None:\n"
            "        self.values = values or {}\n",
            filename="registry.py",
        )

        self.assertEqual(
            analysis.types.classes["Registry"].fields["values"].name,
            "dict[str, int]",
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
        self.assertIn("xcc.aot.py_lexer._PythonLexer.__init__", names)
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

    def test_v376_isinstance_expands_global_ast_type_marker_tuple(self) -> None:
        module = lower_source_to_ir(
            "from xcc.aot import py_ast as ast\n"
            "_UNSUPPORTED = (ast.AsyncFor, ast.Yield)\n"
            "def rejected(node: ast.AST) -> bool:\n"
            "    return isinstance(node, _UNSUPPORTED)\n",
            filename="type-marker-tuple.py",
            include_functions={"rejected"},
            extra_classes={name: AotClassInfo(name, {}) for name in ("AST", "AsyncFor", "Yield")},
        )

        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        assert isinstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        assert isinstance(returned.value, IrCall)
        marker = returned.value.args[1]
        self.assertIsInstance(marker, IrTuple)
        assert isinstance(marker, IrTuple)
        self.assertEqual(
            tuple(element.name for element in marker.elements if isinstance(element, IrName)),
            ("AsyncFor", "Yield"),
        )
        self.assertTrue({"AsyncFor", "Yield"}.issubset(_function_record_names(module.functions[0])))

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

    def test_v376_isinstance_narrows_qualified_record_union(self) -> None:
        module = lower_source_to_ir(
            "from xcc.aot import py_ast as ast\n"
            "def name_id(node: ast.expr | None) -> str:\n"
            "    if isinstance(node, ast.Name):\n"
            "        return node.id\n"
            "    return ''\n",
            filename="qualified_union.py",
            include_functions={"name_id"},
            extra_classes={
                "AST": AotClassInfo("AST", {}),
                "expr": AotClassInfo("expr", {}, ("AST",)),
                "Name": AotClassInfo("Name", {"id": AotType("str")}, ("expr",)),
            },
        )

        branch = module.functions[0].body[0]
        self.assertEqual(
            branch.then_branch.statements[0].value.value.type,
            IrRecordType("Name"),
        )

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
        self.assertIn("call ptr @__xcc_aot_alloc", llvm_text)

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

    def test_v376_record_layout_flattens_keyword_only_base_fields(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True, kw_only=True)\n"
            "class Base:\n"
            "    meta: str = ''\n"
            "@dataclass(frozen=True)\n"
            "class Child(Base):\n"
            "    value: int = 0\n"
            "def build() -> Child:\n"
            "    return Child(7, meta='owned')\n"
            "def read(child: Child) -> str:\n"
            "    return child.meta\n",
            filename="inherited_layout.py",
        )

        records = {record.name: record for record in module.records}
        self.assertEqual(
            tuple(field.name for field in records["Child"].fields),
            ("meta", "value"),
        )
        emit_llvm_text(module)

    def test_v376_annotated_varargs_use_tuple_abi(self) -> None:
        module = lower_source_to_ir(
            "def count(*values: int) -> int:\n"
            "    return len(values)\n"
            "def invoke() -> int:\n"
            "    return count(1, 2, 3)\n",
            filename="varargs.py",
        )

        functions = {function.name: function for function in module.functions}
        self.assertEqual(functions["count"].params[0].name, "values")
        self.assertEqual(len(functions["invoke"].body[0].value.args), 1)
        emit_llvm_text(module)

    def test_v376_ellipsis_has_distinct_native_object_identity(self) -> None:
        module = lower_source_to_ir(
            "def is_ellipsis(value: object) -> bool:\n"
            "    return value is Ellipsis\n"
            "def invoke() -> bool:\n"
            "    return is_ellipsis(Ellipsis)\n",
            filename="ellipsis.py",
        )

        llvm_text = emit_llvm_text(module)
        self.assertIn("@__xcc_aot_object_ellipsis = private global", llvm_text)
        self.assertIn("ptr @__xcc_aot_object_ellipsis", llvm_text)
        self.assertNotIn("inttoptr (i64 -1 to ptr)", llvm_text)

    def test_v376_builtin_isinstance_markers_narrow_bytes(self) -> None:
        module = lower_source_to_ir(
            "def require_bytes(value: str | bytes) -> bytes:\n"
            "    if not isinstance(value, bytes):\n"
            "        raise ValueError('bytes required')\n"
            "    return value\n",
            filename="builtin_markers.py",
        )

        function = module.functions[0]
        final_return = function.body[-1]
        self.assertIsInstance(final_return, IrReturn)
        self.assertEqual(final_return.value.type.__class__.__name__, "IrBytesType")
        emit_llvm_text(module)

    def test_v376_and_chain_applies_each_isinstance_narrowing(self) -> None:
        module = lower_source_to_ir(
            "class Node:\n"
            "    pass\n"
            "class Text(Node):\n"
            "    value: str\n"
            "def combine(left: Node, right: Node) -> str:\n"
            "    if isinstance(left, Text) and isinstance(right, Text):\n"
            "        return left.value + right.value\n"
            "    return ''\n",
            filename="and_narrowing.py",
        )

        emit_llvm_text(module)

    def test_v376_string_rfind_reaches_native_runtime(self) -> None:
        module = lower_source_to_ir(
            "def last_newline(prefix: str) -> int:\n    return prefix.rfind('\\n')\n",
            filename="rfind.py",
        )

        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__str_rfind")
        self.assertIn("@__xcc_aot_string_rfind", emit_llvm_text(module))

    def test_v376_string_count_reaches_native_runtime(self) -> None:
        module = lower_source_to_ir(
            "def line_count(prefix: str) -> int:\n    return prefix.count('\\n')\n",
            filename="count.py",
        )

        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__str_count")
        self.assertIn("@__xcc_aot_string_count", emit_llvm_text(module))

    def test_v376_complex_constructor_reaches_native_runtime(self) -> None:
        module = lower_source_to_ir(
            "def decode_imaginary(text: str) -> object:\n    return complex(0.0, float(text))\n",
            filename="complex_value.py",
        )

        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__complex")
        self.assertIn("@__xcc_aot_complex_new", emit_llvm_text(module))

    def test_v376_string_iteration_binds_one_character_strings(self) -> None:
        module = lower_source_to_ir(
            "def normalize(text: str) -> str:\n"
            "    for ch in text:\n"
            "        return ch.lower()\n"
            "    return ''\n",
            filename="string_iteration.py",
        )

        emit_llvm_text(module)

    def test_v376_tuple_backed_clear_reaches_native_runtime(self) -> None:
        module = lower_source_to_ir(
            "def reset(values: list[int]) -> int:\n    values.clear()\n    return len(values)\n",
            filename="clear.py",
        )

        self.assertIn("@__xcc_aot_tuple_clear", emit_llvm_text(module))

    def test_v376_any_generator_predicate_reaches_native_loop(self) -> None:
        module = lower_source_to_ir(
            "def has_value(values: list[str | None]) -> bool:\n"
            "    return any(value is not None for value in values)\n",
            filename="any_generator.py",
        )

        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__any_generator")
        llvm_text = emit_llvm_text(module)
        self.assertIn("any.cond", llvm_text)
        self.assertNotIn("@__any_generator", llvm_text)

    def test_v376_owned_parser_record_layout_matches_constructor(self) -> None:
        module = lower_core_slice(
            (
                AOT_ROOT / "diag.py",
                AOT_ROOT / "py_ast.py",
                AOT_ROOT / "py_lexer.py",
                AOT_ROOT / "module.py",
                AOT_ROOT / "py_parser.py",
            ),
            root_targets=("xcc.aot.py_parser.parse_subset_source",),
        )

        parser_record = next(record for record in module.records if record.name == "_PythonParser")
        self.assertIn("tokens", {field.name for field in parser_record.fields})
        emit_llvm_text(module)

    def test_v376_owned_binder_root_has_real_method_reachability(self) -> None:
        module = lower_core_slice(
            (
                AOT_ROOT / "diag.py",
                AOT_ROOT / "py_ast.py",
                AOT_ROOT / "module.py",
                AOT_ROOT / "subset.py",
                AOT_ROOT / "types.py",
                AOT_ROOT / "binder.py",
            ),
            root_targets=("xcc.aot.binder.bind_types",),
        )

        names = {function.name for function in module.functions}
        self.assertIn("xcc.aot.binder.bind_types", names)
        self.assertIn("xcc.aot.binder._TypeBinder.bind", names)
        emit_llvm_text(module)

    def test_v376_owned_lowerer_root_has_real_method_reachability(self) -> None:
        module = lower_core_slice(
            (
                AOT_ROOT / "diag.py",
                AOT_ROOT / "py_ast.py",
                AOT_ROOT / "module.py",
                AOT_ROOT / "subset.py",
                AOT_ROOT / "types.py",
                AOT_ROOT / "binder.py",
                AOT_ROOT / "analysis.py",
                AOT_ROOT / "ir.py",
                AOT_ROOT / "lower.py",
            ),
            root_targets=("xcc.aot.lower.lower_analysis_to_ir",),
        )

        names = {function.name for function in module.functions}
        self.assertIn("xcc.aot.lower.lower_analysis_to_ir", names)
        self.assertIn("xcc.aot.lower._Lowerer.lower_function", names)
        self.assertIn("xcc.aot.lower._Lowerer.lower_record", names)
        emit_llvm_text(module)

    def test_v376_cross_module_inherited_property_uses_canonical_target(self) -> None:
        module = lower_core_slice(
            (
                AOT_ROOT / "diag.py",
                AOT_ROOT / "py_ast.py",
                AOT_ROOT / "module.py",
                AOT_ROOT / "subset.py",
                AOT_ROOT / "types.py",
                AOT_ROOT / "binder.py",
                AOT_ROOT / "analysis.py",
                AOT_ROOT / "ir.py",
                AOT_ROOT / "lower.py",
            ),
            root_targets=("xcc.aot.lower._Lowerer._lower_statement",),
        )

        llvm_text = emit_llvm_text(module)
        self.assertIn("@xcc.aot.py_ast.AST.col_offset", llvm_text)
        self.assertNotIn("call i64 @AST.col_offset", llvm_text)

    def test_v376_tuple_concat_inference_ignores_function_return_fallback(self) -> None:
        module = lower_source_to_ir(
            "class Parts:\n"
            "    left: tuple[int, ...]\n"
            "    right: tuple[int, ...]\n"
            "def merge(parts: Parts) -> tuple[tuple[int, ...], dict[str, int]]:\n"
            "    values = parts.left + parts.right\n"
            "    return values, {}\n",
            filename="tuple-concat-fallback.py",
        )

        assigned = module.functions[0].body[0]
        self.assertIsInstance(assigned, IrAssign)
        self.assertEqual(
            assigned.value.type,
            IrTupleType((IrIntType(64, signed=True),)),
        )

    def test_v376_continue_guard_propagates_isinstance_narrowing(self) -> None:
        module = lower_source_to_ir(
            "class Node:\n"
            "    pass\n"
            "class Named(Node):\n"
            "    name: str\n"
            "def first_name(nodes: list[Node]) -> str:\n"
            "    for node in nodes:\n"
            "        if not isinstance(node, Named):\n"
            "            continue\n"
            "        return node.name\n"
            "    return ''\n",
            filename="continue_guard.py",
        )

        emit_llvm_text(module)

    def test_v376_string_isidentifier_reaches_native_runtime(self) -> None:
        module = lower_source_to_ir(
            "def valid(name: str) -> bool:\n    return name.isidentifier()\n",
            filename="isidentifier.py",
        )

        self.assertIn("@__xcc_aot_string_predicate", emit_llvm_text(module))

    def test_v376_string_rsplit_reaches_native_runtime(self) -> None:
        module = lower_source_to_ir(
            "def leaf(name: str) -> str:\n    return name.rsplit('.', 1)[-1]\n",
            filename="rsplit.py",
        )

        self.assertIn("@__xcc_aot_string_rsplit_limit", emit_llvm_text(module))

    def test_v376_string_isupper_reaches_native_runtime(self) -> None:
        module = lower_source_to_ir(
            "def upper(name: str) -> bool:\n    return name.isupper()\n",
            filename="isupper.py",
        )

        self.assertIn("@__xcc_aot_string_predicate", emit_llvm_text(module))

    def test_v376_object_repr_reaches_tagged_native_runtime(self) -> None:
        module = lower_source_to_ir(
            "def render(value: object) -> str:\n    return repr(value)\n",
            filename="object_repr.py",
        )

        llvm_text = emit_llvm_text(module)
        self.assertIn("@__xcc_aot_object_repr", llvm_text)
        self.assertIn("load i64, ptr %object", llvm_text)

    def test_v376_exact_type_identity_reaches_tagged_native_runtime(self) -> None:
        module = lower_source_to_ir(
            "def exact_int(value: object) -> bool:\n    return type(value) is int\n",
            filename="exact_type.py",
        )

        llvm_text = emit_llvm_text(module)
        self.assertIn("object.type", llvm_text)

    def test_v376_exact_type_guard_narrows_true_branch(self) -> None:
        module = lower_source_to_ir(
            "def collect(value: object) -> dict[str, int]:\n"
            "    result: dict[str, int] = {}\n"
            "    if type(value) is int:\n"
            "        result['value'] = value\n"
            "    return result\n",
            filename="exact_type_guard.py",
        )

        emit_llvm_text(module)

    def test_v376_tagged_object_bool_identity_reaches_native_tag_check(self) -> None:
        module = lower_source_to_ir(
            "def is_true(value: object) -> bool:\n    return value is True\n",
            filename="object_bool_identity.py",
        )

        self.assertIn("object.identity", emit_llvm_text(module))

    def test_v376_and_chain_none_narrowing_reaches_true_branch(self) -> None:
        module = lower_source_to_ir(
            "class Annotation:\n"
            "    text: str\n"
            "class Argument:\n"
            "    annotation: Annotation | None\n"
            "class Arguments:\n"
            "    vararg: Argument | None\n"
            "def annotation_text(args: Arguments) -> str:\n"
            "    if args.vararg is not None and args.vararg.annotation is not None:\n"
            "        return args.vararg.annotation.text\n"
            "    return ''\n",
            filename="and_none_branch.py",
        )

        emit_llvm_text(module)

    def test_v376_dict_comprehension_reaches_native_loop(self) -> None:
        module = lower_source_to_ir(
            "def increment(values: dict[str, int]) -> dict[str, int]:\n"
            "    return {name: value + 1 for name, value in values.items() if value > 0}\n",
            filename="dict_comprehension.py",
        )

        llvm_text = emit_llvm_text(module)
        self.assertIn("dictcomp.cond", llvm_text)
        self.assertIn("@__xcc_aot_string_dict_find_index", llvm_text)
        self.assertNotIn("dictset.cond", llvm_text)

    def test_v376_homogeneous_tuple_assignment_preserves_element_types(self) -> None:
        module = lower_source_to_ir(
            "def add_pair(values: tuple[int, ...]) -> int:\n"
            "    left, right = values\n"
            "    return left + right\n",
            filename="homogeneous_tuple_assignment.py",
        )

        emit_llvm_text(module)

    def test_v376_global_literal_dict_reaches_native_lookup(self) -> None:
        module = lower_source_to_ir(
            "WIDTHS = {'i8': (8, True), 'u16': (16, False)}\n"
            "def lookup(name: str) -> tuple[int, bool] | None:\n"
            "    return WIDTHS.get(name)\n",
            filename="global_literal_dict.py",
        )

        llvm_text = emit_llvm_text(module)
        self.assertIn("@__xcc_aot_tuple_get", llvm_text)
        self.assertNotIn("@WIDTHS", llvm_text)

    def test_v376_optional_bool_uses_distinct_native_tags(self) -> None:
        module = lower_source_to_ir(
            "def classify(flag: bool) -> int:\n"
            "    value: bool | None = None\n"
            "    while flag:\n"
            "        if value is None:\n"
            "            value = False\n"
            "        if value is not None and value == False:\n"
            "            return 7\n"
            "        break\n"
            "    return 0\n",
            filename="optional_bool.py",
        )

        llvm_text = emit_llvm_text(module)
        self.assertIn("inttoptr i64", llvm_text)

    def test_v376_noreturn_guard_propagates_isinstance_narrowing(self) -> None:
        module = lower_source_to_ir(
            "from typing import NoReturn\n"
            "def stop() -> NoReturn:\n"
            "    raise ValueError('stop')\n"
            "def require_bytes(value: str | bytes) -> bytes:\n"
            "    if not isinstance(value, bytes):\n"
            "        stop()\n"
            "    return value\n",
            filename="noreturn_guard.py",
        )

        final_return = module.functions[1].body[-1]
        self.assertIsInstance(final_return, IrReturn)
        self.assertEqual(final_return.value.type.__class__.__name__, "IrBytesType")
        emit_llvm_text(module)

    def test_v376_bytes_accepts_tuple_backed_integer_iterable(self) -> None:
        module = lower_source_to_ir(
            "def build(values: list[int]) -> bytes:\n    return bytes(values)\n",
            filename="bytes_iterable.py",
        )

        returned = module.functions[0].body[0]
        self.assertIsInstance(returned, IrReturn)
        self.assertIsInstance(returned.value, IrCall)
        self.assertEqual(returned.value.target, "__bytes_from_ints")
        self.assertIn("@__xcc_aot_bytes_from_ints", emit_llvm_text(module))

    def test_v376_string_endswith_accepts_tuple_suffixes(self) -> None:
        module = lower_source_to_ir(
            "def is_imaginary(text: str) -> bool:\n    return text.endswith(('j', 'J'))\n",
            filename="endswith_tuple.py",
        )

        llvm_text = emit_llvm_text(module)
        self.assertEqual(llvm_text.count("call i1 @__xcc_aot_string_endswith"), 2)
        self.assertIn("or i1", llvm_text)

    def test_v376_float_can_cross_opaque_pointer_storage(self) -> None:
        module = lower_source_to_ir(
            "def decode() -> object:\n    return 1.5\n",
            filename="opaque_float.py",
        )

        llvm_text = emit_llvm_text(module)
        self.assertIn("store double 1.5", llvm_text)

    def test_v376_float_equality_uses_floating_comparison(self) -> None:
        module = lower_source_to_ir(
            "def same(left: float, right: float) -> bool:\n    return left == right\n",
            filename="float_equality.py",
        )

        self.assertIn("fcmp oeq double", emit_llvm_text(module))


if __name__ == "__main__":
    unittest.main()
