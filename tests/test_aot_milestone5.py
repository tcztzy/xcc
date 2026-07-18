import os
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotError,
    IrFunction,
    IrIntType,
    IrModule,
    IrRecord,
    IrRecordType,
    IrStringType,
    analyze_path,
    analyze_source,
    emit_llvm_text,
    lower_core_slice,
    lower_source_to_ir,
    run_native_core_smoke,
)
from xcc.aot.slice import _add_missing_records
from xcc.lexer import Token, TokenKind
from xcc.parser.type_specs import ParserError
from xcc.sema.type_helpers import _aot_integer_type_summary


ROOT = Path(__file__).resolve().parents[1]
PARSER_INIT_PATH = ROOT / "src/xcc/parser/__init__.py"
SEMA_SYMBOLS_PATH = ROOT / "src/xcc/sema/symbols.py"
SEMA_TYPE_HELPERS_PATH = ROOT / "src/xcc/sema/type_helpers.py"
PARSER_TYPE_SPECS_PATH = ROOT / "src/xcc/parser/type_specs.py"
TYPE_HELPER_SLICE = (
    ROOT / "src/xcc/types.py",
    ROOT / "src/xcc/sema/type_helpers.py",
)
PARSER_SEMA_SLICE = (
    ROOT / "src/xcc/types.py",
    ROOT / "src/xcc/lexer.py",
    ROOT / "src/xcc/parser/type_specs.py",
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

    def test_reports_missing_keyword_only_method_parameter_annotation(self) -> None:
        source = (
            "class Box:\n"
            "    def update(self, *, value) -> None:\n"
            "        return None\n"
        )
        with self.assertRaises(AotError) as ctx:
            analyze_source(source, filename="bad_method.py")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-TYPE-0001")
        self.assertEqual(
            ctx.exception.diagnostics[0].message,
            "Missing annotation for parameter: Box.update.value",
        )


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

    def test_missing_record_adder_skips_records_already_present(self) -> None:
        records = {"Known": IrRecord("Known", ())}
        _add_missing_records({"Known"}, records, {}, {}, {}, {}, {})
        self.assertEqual(records, {"Known": IrRecord("Known", ())})


class AotMilestone5LoweringTests(unittest.TestCase):
    def test_lowers_enum_annotation_to_opaque_record(self) -> None:
        source = (
            "from enum import Enum\n"
            "def echo(value: Enum) -> Enum:\n"
            "    return value\n"
        )
        module = lower_source_to_ir(
            source,
            filename="enum_signature.py",
            include_functions={"echo"},
            bodyless_functions={"echo"},
        )
        function = module.functions[0]
        self.assertEqual(function.params[0].type, IrRecordType("Enum"))
        self.assertEqual(function.return_type, IrRecordType("Enum"))


class AotMilestone5LlvmTests(unittest.TestCase):
    def test_reports_bad_core_parser_error_str_signature(self) -> None:
        module = IrModule(
            "bad.py",
            (),
            (
                IrFunction(
                    "xcc.parser.type_specs.ParserError.__str__",
                    (),
                    IrStringType(),
                    (),
                ),
            ),
        )
        with self.assertRaises(AotError) as ctx:
            emit_llvm_text(module)
        self.assertEqual(
            ctx.exception.diagnostics[0].message,
            "core ParserError.__str__ expects ParserError -> str",
        )

    def test_reports_bad_core_constant_string_signature(self) -> None:
        module = IrModule(
            "bad.py",
            (),
            (
                IrFunction(
                    "xcc.sema.type_helpers._aot_integer_type_summary",
                    (),
                    IrIntType(64, signed=True),
                    (),
                ),
            ),
        )
        with self.assertRaises(AotError) as ctx:
            emit_llvm_text(module)
        self.assertEqual(
            ctx.exception.diagnostics[0].message,
            "core sema integer type summary expects () -> str",
        )


class AotMilestone5ParserSubsetTests(unittest.TestCase):
    def test_analyzes_parser_type_specs_without_rejected_syntax(self) -> None:
        analysis = analyze_path(PARSER_TYPE_SPECS_PATH)
        self.assertIn("ParserError", analysis.types.classes)
        self.assertIn("ParserError.__str__", analysis.types.functions)
        self.assertIn("parse_integer_type_spec", analysis.types.functions)


def _real_llc() -> str | None:
    path = os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    return path if Path(path).exists() else None


class AotMilestone5NativeTests(unittest.TestCase):
    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_parser_error_str_matches_cpython(self) -> None:
        expected = str(
            ParserError(
                "Type name is missing before ';'",
                Token(TokenKind.PUNCTUATOR, ";", 4, 9),
            )
        )
        result = run_native_core_smoke(
            PARSER_SEMA_SLICE,
            entry="xcc.parser.type_specs:ParserError.__str__",
            fixture="missing_type_name",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, f"{expected}\n")
        self.assertEqual(result.native_returncode, 0)

    @unittest.skipIf(_real_llc() is None, "LLVM llc is not available")
    def test_native_sema_integer_helper_matches_cpython(self) -> None:
        result = run_native_core_smoke(
            PARSER_SEMA_SLICE,
            entry="xcc.sema.type_helpers:is_integer_type",
            fixture="int_and_void",
            llc=_real_llc(),
        )
        self.assertEqual(result.native_stdout, f"{_aot_integer_type_summary()}\n")
        self.assertEqual(result.native_returncode, 0)


if __name__ == "__main__":
    unittest.main()
