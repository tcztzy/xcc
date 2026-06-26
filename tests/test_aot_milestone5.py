import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import IrRecordType, analyze_path, lower_core_slice


ROOT = Path(__file__).resolve().parents[1]
PARSER_INIT_PATH = ROOT / "src/xcc/parser/__init__.py"
SEMA_SYMBOLS_PATH = ROOT / "src/xcc/sema/symbols.py"
SEMA_TYPE_HELPERS_PATH = ROOT / "src/xcc/sema/type_helpers.py"
PARSER_TYPE_SPECS_PATH = ROOT / "src/xcc/parser/type_specs.py"
TYPE_HELPER_SLICE = (
    ROOT / "src/xcc/types.py",
    ROOT / "src/xcc/sema/type_helpers.py",
)


class AotMilestone5AdmissionTests(unittest.TestCase):
    def test_analyzes_parser_and_sema_entry_modules(self) -> None:
        for path in (PARSER_INIT_PATH, SEMA_SYMBOLS_PATH, SEMA_TYPE_HELPERS_PATH):
            with self.subTest(path=path.name):
                analysis = analyze_path(path)
                self.assertGreater(len(analysis.summary.functions), 0)
                self.assertGreater(len(analysis.types.functions), 0)

    def test_binds_parser_methods_with_receiver_and_keyword_only_parameters(self) -> None:
        analysis = analyze_path(PARSER_INIT_PATH)
        functions = analysis.types.functions
        self.assertIn("Parser.__init__", functions)
        self.assertIn("Parser._lookup_typedef", functions)
        self.assertEqual(
            functions["Parser.__init__"].parameters,
            (("self", "Parser"), ("tokens", "list[Token]"), ("std", "StdMode")),
        )
        self.assertEqual(functions["Parser._lookup_typedef"].return_type.name, "TypeSpec | None")

    def test_binds_nested_dict_and_set_annotations_from_sema_symbols(self) -> None:
        analysis = analyze_path(SEMA_SYMBOLS_PATH)
        fields = analysis.types.classes["SemaUnit"].fields
        self.assertEqual(fields["functions"].name, "dict[str, FunctionSymbol]")
        self.assertEqual(
            fields["record_definitions"].name,
            "dict[str, tuple[RecordMemberInfo, ...]]",
        )
        self.assertEqual(fields["transparent_union_types"].name, "set[str]")

    def test_accepts_property_getter_as_method_signature(self) -> None:
        analysis = analyze_path(SEMA_SYMBOLS_PATH)
        function = analysis.types.functions["Scope.symbols"]
        self.assertEqual(function.parameters, (("self", "Scope"),))
        self.assertEqual(function.return_type.name, "dict[str, VarSymbol | EnumConstSymbol]")


class AotMilestone5SliceTests(unittest.TestCase):
    def test_lowers_sema_type_helper_signature_with_imported_type_record(self) -> None:
        module = lower_core_slice(
            TYPE_HELPER_SLICE,
            root_targets=("xcc.sema.type_helpers.is_integer_type",),
            required_records=("Type",),
        )
        records = {record.name for record in module.records}
        functions = {function.name: function for function in module.functions}
        self.assertIn("Type", records)
        function = functions["xcc.sema.type_helpers.is_integer_type"]
        self.assertEqual(function.params[0].type, IrRecordType("Type"))
        self.assertEqual(function.return_type.__class__.__name__, "IrBoolType")


class AotMilestone5ParserSubsetTests(unittest.TestCase):
    def test_analyzes_parser_type_specs_without_rejected_syntax(self) -> None:
        analysis = analyze_path(PARSER_TYPE_SPECS_PATH)
        self.assertIn("ParserError", analysis.types.classes)
        self.assertIn("ParserError.__str__", analysis.types.functions)
        self.assertIn("parse_integer_type_spec", analysis.types.functions)


if __name__ == "__main__":
    unittest.main()
