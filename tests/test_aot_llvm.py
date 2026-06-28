import unittest

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotError,
    IrAssign,
    IrBinary,
    IrBoolType,
    IrBreak,
    IrBranch,
    IrCall,
    IrConstBool,
    IrConstFloat,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrContinue,
    IrEnumMember,
    IrField,
    IrForEach,
    IrFunction,
    IrGetField,
    IrIf,
    IrFloatType,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrParam,
    IrRaise,
    IrRecord,
    IrRecordType,
    IrReturn,
    IrSetItem,
    IrStringConcat,
    IrStringType,
    IrTuple,
    IrTupleType,
    IrWhile,
    emit_llvm_text,
    lower_source_to_ir,
)
from xcc.aot.llvm_text import (
    _block_is_terminated,
    _current_label,
    _EmittedValue,
    _Emitter,
    _branch_assigned_names,
    _for_each_targets,
    _llvm_symbol,
    _statement_assigned_names,
)


class AotLlvmTextTests(unittest.TestCase):
    def test_emits_int64_function_and_main_wrapper(self) -> None:
        module = lower_source_to_ir(
            "int64 = int\ndef answer() -> int64:\n    return 42\n",
            filename="scalar.py",
            entry="answer",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define i64 @answer()", llvm_ir)
        self.assertIn("ret i64 42", llvm_ir)
        self.assertIn("define i32 @main()", llvm_ir)
        self.assertIn("%result = call i64 @answer()", llvm_ir)
        self.assertIn("%exit = trunc i64 %result to i32", llvm_ir)

    def test_emits_float_constant_return(self) -> None:
        module = IrModule(
            "float.py",
            (),
            (
                IrFunction(
                    "zero",
                    (),
                    IrFloatType(),
                    (IrReturn(IrConstFloat(0.0)),),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define double @zero()", llvm_ir)
        self.assertIn("ret double 0.0", llvm_ir)

    def test_emits_signed_integer_floor_division(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "div.py",
            (),
            (
                IrFunction(
                    "div",
                    (IrParam("left", int64), IrParam("right", int64)),
                    int64,
                    (IrReturn(IrBinary("//", IrName("left", int64), IrName("right", int64), int64)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("sdiv i64 %left, %right", llvm_ir)
        self.assertIn("srem i64 %left, %right", llvm_ir)
        self.assertIn("select i1", llvm_ir)

    def test_emits_unsigned_integer_floor_division_and_modulo(self) -> None:
        uint64 = IrIntType(64, signed=False)
        module = IrModule(
            "unsigned_div.py",
            (),
            (
                IrFunction(
                    "ops",
                    (IrParam("left", uint64), IrParam("right", uint64)),
                    uint64,
                    (
                        IrAssign(
                            "quotient",
                            IrBinary(
                                "//",
                                IrName("left", uint64),
                                IrName("right", uint64),
                                uint64,
                            ),
                        ),
                        IrReturn(
                            IrBinary(
                                "%",
                                IrName("quotient", uint64),
                                IrName("right", uint64),
                                uint64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("udiv i64 %left, %right", llvm_ir)
        self.assertIn("urem i64 %udiv", llvm_ir)

    def test_rejects_non_integer_floor_division_and_modulo_emission(self) -> None:
        emitter = _Emitter(IrModule("bad.py", (), ()))
        with self.assertRaises(AotError) as ctx:
            emitter._emit_floor_div(
                IrStringType(),
                _EmittedValue("%left", IrStringType()),
                _EmittedValue("%right", IrStringType()),
                [],
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        with self.assertRaises(AotError) as ctx:
            emitter._emit_modulo(
                IrStringType(),
                _EmittedValue("%left", IrStringType()),
                _EmittedValue("%right", IrStringType()),
                [],
            )
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")

    def test_emits_integer_modulo_shifts_and_bitwise_operations(self) -> None:
        int64 = IrIntType(64, signed=True)
        cases = (
            ("mod", "%", "srem i64 %left, %right"),
            ("lshift", "<<", "shl i64 %left, %right"),
            ("rshift", ">>", "ashr i64 %left, %right"),
            ("or_", "|", "or i64 %left, %right"),
            ("and_", "&", "and i64 %left, %right"),
            ("xor_", "^", "xor i64 %left, %right"),
        )
        for name, op, expected in cases:
            with self.subTest(op=op):
                module = IrModule(
                    f"{name}.py",
                    (),
                    (
                        IrFunction(
                            name,
                            (IrParam("left", int64), IrParam("right", int64)),
                            int64,
                            (
                                IrReturn(
                                    IrBinary(
                                        op,
                                        IrName("left", int64),
                                        IrName("right", int64),
                                        int64,
                                    )
                                ),
                            ),
                        ),
                    ),
                )

                llvm_ir = emit_llvm_text(module)

                self.assertIn(expected, llvm_ir)
                if op == "%":
                    self.assertIn("select i1", llvm_ir)

    def test_emits_two_arg_integer_max_as_select(self) -> None:
        module = lower_source_to_ir(
            "int64 = int\n"
            "def choose(left: int64, right: int64) -> int64:\n"
            "    return max(left, right)\n",
            filename="max.py",
            entry="choose",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("icmp sge i64 %left, %right", llvm_ir)
        self.assertIn("select i1", llvm_ir)
        self.assertNotIn("@max", llvm_ir)

    def test_emits_object_name_narrowed_to_int_as_ptr_to_int(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "object_int_narrow.py",
            (),
            (
                IrFunction(
                    "choose",
                    (IrParam("value", IrRecordType("object")),),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__ifexp",
                                (
                                    IrCall(
                                        "__cmp_GtE",
                                        (IrName("value", int64), IrConstInt(0, int64)),
                                        IrBoolType(),
                                    ),
                                    IrName("value", int64),
                                    IrConstInt(0, int64),
                                ),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("ptrtoint ptr %value to i64", llvm_ir)
        self.assertIn("icmp sge i64", llvm_ir)
        self.assertIn("select i1", llvm_ir)

    def test_emits_object_name_narrowed_to_string_and_tuple_as_pointer(self) -> None:
        tuple_type = IrTupleType((IrStringType(),))
        module = IrModule(
            "object_pointer_narrow.py",
            (),
            (
                IrFunction(
                    "as_string",
                    (IrParam("value", IrRecordType("object")),),
                    IrStringType(),
                    (IrReturn(IrName("value", IrStringType())),),
                ),
                IrFunction(
                    "as_tuple",
                    (IrParam("value", IrRecordType("object")),),
                    tuple_type,
                    (IrReturn(IrName("value", tuple_type)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @as_string(ptr %value)", llvm_ir)
        self.assertIn("define ptr @as_tuple(ptr %value)", llvm_ir)
        self.assertIn("ret ptr %value", llvm_ir)

    def test_emits_string_return_with_puts_wrapper(self) -> None:
        module = lower_source_to_ir(
            'def message() -> str:\n    return "ok"\n',
            filename="string.py",
            entry="message",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn('c"ok\\00"', llvm_ir)
        self.assertIn("declare i32 @puts(ptr)", llvm_ir)
        self.assertIn("%printed = call i32 @puts(ptr %result)", llvm_ir)

    def test_emits_tuple_getitem_intrinsic(self) -> None:
        module = lower_source_to_ir(
            "def pick(argv: tuple[str, ...]) -> str:\n    return argv[2]\n",
            filename="tuple_getitem.py",
            entry="pick",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("%call1 = call ptr @__xcc_aot_tuple_get(ptr %argv, i64 2)", llvm_ir)
        self.assertNotIn("call ptr @__getitem", llvm_ir)

    def test_emits_tuple_getitem_unboxes_integer_result(self) -> None:
        int64 = IrIntType(64, signed=True)
        values_type = IrTupleType((int64,))
        module = IrModule(
            "tuple_getitem_int.py",
            (),
            (
                IrFunction(
                    "pick",
                    (IrParam("values", values_type),),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__getitem",
                                (IrName("values", values_type), IrConstInt(0, int64)),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %values, i64 0)", llvm_ir)
        self.assertIn("ptrtoint ptr", llvm_ir)

    def test_emits_tuple_getitem_coerces_object_index_to_int(self) -> None:
        values_type = IrTupleType((IrRecordType("RecordMemberInfo"),))
        module = IrModule(
            "tuple_getitem_object_index.py",
            (IrRecord("RecordMemberInfo", ()),),
            (
                IrFunction(
                    "pick",
                    (
                        IrParam("values", values_type),
                        IrParam("index", IrRecordType("object")),
                    ),
                    IrRecordType("RecordMemberInfo"),
                    (
                        IrReturn(
                            IrCall(
                                "__getitem",
                                (IrName("values", values_type), IrName("index", IrRecordType("object"))),
                                IrRecordType("RecordMemberInfo"),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("ptrtoint ptr %index to i64", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %values", llvm_ir)

    def test_emits_tuple_getitem_extends_and_truncates_non_i64_indexes(self) -> None:
        tuple_type = IrTupleType((IrStringType(),))
        cases = (
            (IrIntType(32, signed=True), "sext i32 0 to i64"),
            (IrIntType(32, signed=False), "zext i32 0 to i64"),
            (IrIntType(128, signed=True), "trunc i128 0 to i64"),
        )
        for index_type, expected in cases:
            with self.subTest(index_type=index_type):
                module = IrModule(
                    "tuple_getitem_index_width.py",
                    (),
                    (
                        IrFunction(
                            "pick",
                            (IrParam("values", tuple_type),),
                            IrStringType(),
                            (
                                IrReturn(
                                    IrCall(
                                        "__getitem",
                                        (
                                            IrName("values", tuple_type),
                                            IrConstInt(0, index_type),
                                        ),
                                        IrStringType(),
                                    )
                                ),
                            ),
                        ),
                    ),
                )

                llvm_ir = emit_llvm_text(module)

                self.assertIn(expected, llvm_ir)
                self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %values", llvm_ir)

    def test_emits_tuple_len_intrinsic(self) -> None:
        module = lower_source_to_ir(
            "int32 = int\n"
            "def check(argv: tuple[str, ...]) -> int32:\n"
            "    if len(argv) != 5:\n"
            "        return 1\n"
            "    return 0\n",
            filename="tuple_len.py",
            entry="check",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("%call1 = call i64 @__xcc_aot_tuple_len(ptr %argv)", llvm_ir)
        self.assertNotIn("call i64 @len", llvm_ir)
        self.assertNotIn("ptrtoint ptr %call1", llvm_ir)

    def test_emits_core_lexer_translate_source_leaf(self) -> None:
        cases = (
            (
                "xcc.lexer._aot_error_summary_for_source",
                "@__xcc_aot_lexer_error_summary_for_source",
            ),
            (
                "xcc.lexer._aot_header_summary_for_source",
                "@__xcc_aot_lexer_header_summary_for_source",
            ),
            (
                "xcc.lexer.translate_source",
                "@__xcc_aot_lexer_translate_source",
            ),
            (
                "xcc.lexer._aot_token_summary_for_source",
                "@__xcc_aot_lexer_token_summary_for_source",
            ),
        )
        for function_name, helper_name in cases:
            with self.subTest(function_name=function_name):
                module = IrModule(
                    "core.py",
                    (),
                    (
                        IrFunction(
                            function_name,
                            (IrParam("source", IrStringType()),),
                            IrStringType(),
                            (),
                        ),
                    ),
                    entry=function_name,
                )
                llvm_ir = emit_llvm_text(module)
                self.assertIn(f"define ptr @{function_name}(ptr %source)", llvm_ir)
                self.assertIn(f"call ptr {helper_name}(ptr %source)", llvm_ir)
                self.assertIn("define ptr @__xcc_aot_lexer_translate_source", llvm_ir)

    def test_rejects_malformed_aot_read_text_leaf(self) -> None:
        module = IrModule(
            "bad.py",
            (),
            (
                IrFunction(
                    "xcc.cc_driver._aot_read_text_file",
                    (),
                    IrStringType(),
                    (),
                ),
            ),
        )
        with self.assertRaises(AotError) as ctx:
            emit_llvm_text(module)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        self.assertIn("AOT read_text helper expects str -> str", ctx.exception.diagnostics[0].message)

    def test_rejects_malformed_aot_write_text_leaf(self) -> None:
        module = IrModule(
            "bad.py",
            (),
            (
                IrFunction(
                    "xcc.cc_driver._aot_write_text_file",
                    (IrParam("path", IrStringType()),),
                    IrBoolType(),
                    (),
                ),
            ),
        )
        with self.assertRaises(AotError) as ctx:
            emit_llvm_text(module)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        self.assertIn(
            "AOT write_text helper expects (str, str) -> bool",
            ctx.exception.diagnostics[0].message,
        )

    def test_rejects_malformed_aot_compile_source_to_llvm_leaf(self) -> None:
        module = IrModule(
            "bad.py",
            (),
            (
                IrFunction(
                    "xcc.cc_driver._aot_compile_source_to_llvm_ir",
                    (IrParam("path", IrStringType()),),
                    IrStringType(),
                    (),
                ),
            ),
        )
        with self.assertRaises(AotError) as ctx:
            emit_llvm_text(module)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        self.assertIn(
            "AOT source-to-LLVM helper expects (str, str) -> str",
            ctx.exception.diagnostics[0].message,
        )

    def test_emits_llvm_module_print_leaf(self) -> None:
        module = IrModule(
            "codegen.py",
            (),
            (
                IrFunction(
                    "xcc.codegen._llvm_print_module_to_string",
                    (IrParam("module", IrIntType(64, signed=True)),),
                    IrStringType(),
                    (),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn(
            "define ptr @xcc.codegen._llvm_print_module_to_string(i64 %module)",
            llvm_ir,
        )
        self.assertIn("%module.ptr = inttoptr i64 %module to ptr", llvm_ir)
        self.assertIn("call ptr @LLVMPrintModuleToString(ptr %module.ptr)", llvm_ir)
        self.assertIn("declare ptr @LLVMPrintModuleToString(ptr)", llvm_ir)

    def test_rejects_malformed_llvm_module_print_leaf(self) -> None:
        module = IrModule(
            "bad.py",
            (),
            (
                IrFunction(
                    "xcc.codegen._llvm_print_module_to_string",
                    (IrParam("module", IrStringType()),),
                    IrStringType(),
                    (),
                ),
            ),
        )
        with self.assertRaises(AotError) as ctx:
            emit_llvm_text(module)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        self.assertIn(
            "LLVM module print helper expects int -> str",
            ctx.exception.diagnostics[0].message,
        )

    def test_rejects_malformed_aot_exec_argv_leaf(self) -> None:
        module = IrModule(
            "bad.py",
            (),
            (
                IrFunction(
                    "xcc.cc_driver._aot_exec_argv",
                    (),
                    IrIntType(32, signed=True),
                    (),
                ),
            ),
        )
        with self.assertRaises(AotError) as ctx:
            emit_llvm_text(module)
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        self.assertIn(
            "AOT exec argv helper expects tuple[str, ...] -> int32",
            ctx.exception.diagnostics[0].message,
        )

    def test_emits_record_type_and_method_call(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "int64 = int\n"
            "@dataclass(frozen=True)\n"
            "class Pair:\n"
            "    left: int64\n"
            "    right: int64\n"
            "    def total(self) -> int64:\n"
            "        return self.left + self.right\n"
            "def entry() -> int64:\n"
            "    pair = Pair(2, 3)\n"
            "    return pair.total()\n"
        )
        llvm_ir = emit_llvm_text(lower_source_to_ir(source, filename="method.py", entry="entry"))
        self.assertIn("%Pair = type { i64, i64 }", llvm_ir)
        self.assertIn("define i64 @Pair.total(ptr %self)", llvm_ir)
        self.assertIn("call i64 @Pair.total(ptr %pair)", llvm_ir)

    def test_emits_module_without_entry_and_scalar_assignment(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "assign.py",
            (),
            (
                IrFunction(
                    "value",
                    (),
                    int64,
                    (
                        IrAssign("local", IrConstInt(7, int64)),
                        IrReturn(IrName("local", int64)),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertNotIn("define i32 @main()", llvm_ir)
        self.assertIn("ret i64 7", llvm_ir)

    def test_emits_scalar_parameter_function(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "param.py",
            (),
            (
                IrFunction(
                    "identity",
                    (IrParam("value", int64),),
                    int64,
                    (IrReturn(IrName("value", int64)),),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define i64 @identity(i64 %value)", llvm_ir)
        self.assertIn("ret i64 %value", llvm_ir)

    def test_emits_record_constructor_expression_and_escaped_string(self) -> None:
        int64 = IrIntType(64, signed=True)
        record_type = IrRecordType("Box")
        record = IrRecord("Box", (IrField("value", int64),))
        module = IrModule(
            "literal.py",
            (record,),
            (
                IrFunction(
                    "box",
                    (),
                    record_type,
                    (IrReturn(IrConstructRecord("Box", (IrConstInt(1, int64),), record_type)),),
                ),
                IrFunction(
                    "message",
                    (),
                    IrStringType(),
                    (IrReturn(IrConstString('"\\\n')),),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("%box1 = alloca %Box", llvm_ir)
        self.assertIn("\\22\\5C\\0A\\00", llvm_ir)

    def test_emits_bool_none_default_and_status_returns(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType(())
        record_type = IrRecordType("Box")
        module = IrModule(
            "defaults.py",
            (IrRecord("Box", (IrField("none", IrNoneType()),)),),
            (
                IrFunction("flag", (), IrBoolType(), (IrReturn(IrConstBool(True)),)),
                IrFunction("done", (), IrNoneType(), ()),
                IrFunction("count", (), int64, (IrReturn(IrName("COUNT", int64)),)),
                IrFunction("default_int", (), int64, ()),
                IrFunction("default_bool", (), IrBoolType(), ()),
                IrFunction("default_string", (), IrStringType(), ()),
                IrFunction("default_tuple", (), tuple_type, ()),
                IrFunction("default_record", (), record_type, ()),
                IrFunction(
                    "raise_bool",
                    (),
                    IrBoolType(),
                    (IrRaise("ValueError", IrConstString("b")),),
                ),
                IrFunction(
                    "raise_string",
                    (),
                    IrStringType(),
                    (IrRaise("ValueError", IrConstString("s")),),
                ),
                IrFunction(
                    "box",
                    (),
                    record_type,
                    (IrReturn(IrConstructRecord("Box", (IrConstNone(),), record_type)),),
                ),
            ),
            entry="flag",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("%exit = zext i1 %result to i32", llvm_ir)
        self.assertIn("define void @done()", llvm_ir)
        self.assertIn("ret i64 0", llvm_ir)
        self.assertIn("ret i1 false", llvm_ir)
        self.assertIn("ret ptr null", llvm_ir)
        self.assertIn("store ptr null", llvm_ir)

    def test_emits_none_entry_empty_concat_and_terminated_loop(self) -> None:
        tuple_type = IrTupleType(())
        module = IrModule(
            "edge.py",
            (),
            (
                IrFunction("done", (), IrNoneType(), ()),
                IrFunction(
                    "empty",
                    (),
                    IrStringType(),
                    (IrReturn(IrStringConcat(())),),
                ),
                IrFunction(
                    "loop_return",
                    (),
                    IrNoneType(),
                    (
                        IrForEach(
                            "item",
                            IrTuple((), tuple_type),
                            IrBranch((IrReturn(IrConstNone()),)),
                        ),
                    ),
                ),
            ),
            entry="done",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("call void @done()", llvm_ir)
        self.assertIn('c"\\00"', llvm_ir)
        self.assertIn("@__xcc_aot_tuple_len", llvm_ir)

    def test_emits_while_loop_control_flow(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "while.py",
            (),
            (
                IrFunction(
                    "spin",
                    (IrParam("limit", int64),),
                    int64,
                    (
                        IrAssign("value", IrConstInt(0, int64)),
                        IrWhile(
                            IrCall(
                                "__cmp_Lt",
                                (IrName("value", int64), IrName("limit", int64)),
                                IrBoolType(),
                            ),
                            IrBranch(
                                (
                                    IrAssign(
                                        "value",
                                        IrBinary(
                                            "+",
                                            IrName("value", int64),
                                            IrConstInt(1, int64),
                                            int64,
                                        ),
                                    ),
                                )
                            ),
                        ),
                        IrReturn(IrName("value", int64)),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("br label %while.cond", llvm_ir)
        self.assertIn("while.cond", llvm_ir)
        self.assertIn("while.body", llvm_ir)
        self.assertIn("while.end", llvm_ir)
        self.assertIn("br i1 %", llvm_ir)
        self.assertIn("phi i64", llvm_ir)
        self.assertIn("icmp slt i64", llvm_ir)

    def test_emits_terminated_while_loop_control_flow(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "while_return.py",
            (),
            (
                IrFunction(
                    "spin",
                    (),
                    int64,
                    (
                        IrAssign("value", IrConstInt(0, int64)),
                        IrWhile(
                            IrConstBool(True),
                            IrBranch(
                                (
                                    IrAssign("value", IrConstInt(1, int64)),
                                    IrReturn(IrName("value", int64)),
                                )
                            ),
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("while.cond", llvm_ir)
        self.assertIn("while.end", llvm_ir)
        self.assertIn("phi i64 [ 0, %entry ]", llvm_ir)

    def test_emits_while_loop_break_and_continue(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "loop_control.py",
            (),
            (
                IrFunction(
                    "spin",
                    (),
                    int64,
                    (
                        IrWhile(
                            IrConstBool(True),
                            IrBranch(
                                (
                                    IrIf(
                                        IrConstBool(True),
                                        IrBranch((IrContinue(),)),
                                        None,
                                    ),
                                    IrBreak(),
                                )
                            ),
                        ),
                        IrReturn(IrConstInt(0, int64)),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("br label %while.cond", llvm_ir)
        self.assertIn("br label %while.end", llvm_ir)

    def test_emits_for_each_continue_through_increment_block(self) -> None:
        module = IrModule(
            "for_continue.py",
            (),
            (
                IrFunction(
                    "walk",
                    (),
                    IrNoneType(),
                    (
                        IrForEach(
                            "item",
                            IrTuple((), IrTupleType(())),
                            IrBranch((IrContinue(),)),
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("for.next", llvm_ir)
        self.assertIn("br label %for.next", llvm_ir)

    def test_for_each_binds_homogeneous_tuple_element_type(self) -> None:
        int64 = IrIntType(64, signed=True)
        function_def = IrRecord("FunctionDef", (IrField("body", int64),))
        function_type = IrRecordType("FunctionDef")
        tuple_type = IrTupleType((function_type,))
        module = IrModule(
            "for_record.py",
            (function_def,),
            (
                IrFunction(
                    "first_body",
                    (IrParam("functions", tuple_type),),
                    int64,
                    (
                        IrForEach(
                            "func",
                            IrName("functions", tuple_type),
                            IrBranch(
                                (
                                    IrReturn(
                                        IrGetField(IrName("func", function_type), "body", int64)
                                    ),
                                )
                            ),
                        ),
                        IrReturn(IrConstInt(0, int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("%FunctionDef = type { i64 }", llvm_ir)
        self.assertIn("getelementptr inbounds %FunctionDef", llvm_ir)

    def test_for_each_destructures_homogeneous_tuple_element_type(self) -> None:
        int64 = IrIntType(64, signed=True)
        op_type = IrTupleType((IrStringType(), IrRecordType("object")))
        ops_type = IrTupleType((op_type,))
        module = IrModule(
            "for_tuple_target.py",
            (),
            (
                IrFunction(
                    "first_array_length",
                    (IrParam("ops", ops_type),),
                    int64,
                    (
                        IrForEach(
                            "(kind, value)",
                            IrName("ops", ops_type),
                            IrBranch(
                                (
                                    IrIf(
                                        IrCall(
                                            "__cmp_Eq",
                                            (IrName("kind", IrStringType()), IrConstString("arr")),
                                            IrBoolType(),
                                        ),
                                        IrBranch(
                                            (
                                                IrReturn(
                                                    IrCall(
                                                        "__ifexp",
                                                        (
                                                            IrCall(
                                                                "__cmp_GtE",
                                                                (
                                                                    IrName("value", int64),
                                                                    IrConstInt(0, int64),
                                                                ),
                                                                IrBoolType(),
                                                            ),
                                                            IrName("value", int64),
                                                            IrConstInt(0, int64),
                                                        ),
                                                        int64,
                                                    )
                                                ),
                                            )
                                        ),
                                    ),
                                )
                            ),
                        ),
                        IrReturn(IrConstInt(0, int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %item", llvm_ir)
        self.assertIn("i64 0)", llvm_ir)
        self.assertIn("i64 1)", llvm_ir)
        self.assertIn("ptrtoint ptr", llvm_ir)

    def test_for_each_destructures_unknown_tuple_element_type_as_object_slots(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "for_unknown_tuple_target.py",
            (),
            (
                IrFunction(
                    "first_array_length",
                    (IrParam("ops", IrTupleType(())),),
                    int64,
                    (
                        IrForEach(
                            "(kind, value)",
                            IrName("ops", IrTupleType(())),
                            IrBranch(
                                (
                                    IrReturn(
                                        IrCall(
                                            "__ifexp",
                                            (
                                                IrCall(
                                                    "__cmp_GtE",
                                                    (
                                                        IrName("value", int64),
                                                        IrConstInt(0, int64),
                                                    ),
                                                    IrBoolType(),
                                                ),
                                                IrName("value", int64),
                                                IrConstInt(0, int64),
                                            ),
                                            int64,
                                        )
                                    ),
                                )
                            ),
                        ),
                        IrReturn(IrConstInt(0, int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %item", llvm_ir)
        self.assertIn("ptrtoint ptr", llvm_ir)

    def test_for_each_skips_underscore_tuple_target_slot(self) -> None:
        int64 = IrIntType(64, signed=True)
        op_type = IrTupleType((IrStringType(), int64))
        ops_type = IrTupleType((op_type,))
        module = IrModule(
            "for_tuple_underscore_target.py",
            (),
            (
                IrFunction(
                    "first_kind",
                    (IrParam("ops", ops_type),),
                    IrStringType(),
                    (
                        IrForEach(
                            "(kind, _)",
                            IrName("ops", ops_type),
                            IrBranch((IrReturn(IrName("kind", IrStringType())),)),
                        ),
                        IrReturn(IrConstString("")),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %item", llvm_ir)
        self.assertIn("i64 0)", llvm_ir)

    def test_assignment_destructures_tuple_value(self) -> None:
        int64 = IrIntType(64, signed=True)
        op_type = IrTupleType((IrStringType(), IrRecordType("object")))
        module = IrModule(
            "assign_tuple_target.py",
            (),
            (
                IrFunction(
                    "length",
                    (IrParam("op", op_type),),
                    int64,
                    (
                        IrAssign("(kind, length_value)", IrName("op", op_type)),
                        IrReturn(
                            IrCall(
                                "__ifexp",
                                (
                                    IrCall(
                                        "__cmp_GtE",
                                        (IrName("length_value", int64), IrConstInt(0, int64)),
                                        IrBoolType(),
                                    ),
                                    IrName("length_value", int64),
                                    IrConstInt(0, int64),
                                ),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %op, i64 1)", llvm_ir)
        self.assertIn("ptrtoint ptr", llvm_ir)

    def test_assignment_destructures_object_and_skips_underscore_slot(self) -> None:
        module = IrModule(
            "assign_tuple_object_target.py",
            (),
            (
                IrFunction(
                    "kind",
                    (IrParam("packed", IrRecordType("object")),),
                    IrStringType(),
                    (
                        IrAssign("(kind, _)", IrName("packed", IrRecordType("object"))),
                        IrReturn(IrName("kind", IrStringType())),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %packed, i64 0)", llvm_ir)
        self.assertNotIn("call ptr @__xcc_aot_tuple_get(ptr %packed, i64 1)", llvm_ir)

    def test_assignment_destructures_pointer_sized_int_tuple_value(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "assign_tuple_int_target.py",
            (),
            (
                IrFunction(
                    "flag",
                    (IrParam("packed", int64),),
                    IrBoolType(),
                    (
                        IrAssign("(param_specs, is_variadic)", IrName("packed", int64)),
                        IrReturn(IrName("is_variadic", IrBoolType())),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("inttoptr i64 %packed to ptr", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get", llvm_ir)

    def test_emits_field_access_after_optional_name_narrowing(self) -> None:
        int64 = IrIntType(64, signed=True)
        box_type = IrRecordType("Box")
        optional_box_type = IrRecordType("Box | None")
        module = IrModule(
            "optional_record.py",
            (IrRecord("Box", (IrField("value", int64),)),),
            (
                IrFunction(
                    "read",
                    (),
                    int64,
                    (
                        IrAssign(
                            "box",
                            IrCall("maybe_box", (), optional_box_type),
                        ),
                        IrReturn(IrGetField(IrName("box", box_type), "value", int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @maybe_box()", llvm_ir)
        self.assertIn("getelementptr inbounds %Box", llvm_ir)

    def test_emits_field_access_after_union_name_narrowing(self) -> None:
        int64 = IrIntType(64, signed=True)
        var_symbol_type = IrRecordType("VarSymbol")
        union_type = IrRecordType("VarSymbol | EnumConstSymbol | None")
        module = IrModule(
            "union_record.py",
            (IrRecord("VarSymbol", (IrField("slot", int64),)),),
            (
                IrFunction(
                    "read",
                    (),
                    int64,
                    (
                        IrAssign(
                            "symbol",
                            IrCall("lookup_symbol", (), union_type),
                        ),
                        IrReturn(IrGetField(IrName("symbol", var_symbol_type), "slot", int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @lookup_symbol()", llvm_ir)
        self.assertIn("getelementptr inbounds %VarSymbol", llvm_ir)

    def test_emits_field_access_after_base_record_name_narrowing(self) -> None:
        int64 = IrIntType(64, signed=True)
        stmt_type = IrRecordType("Stmt")
        compound_type = IrRecordType("CompoundStmt")
        module = IrModule(
            "base_record.py",
            (IrRecord("CompoundStmt", (IrField("count", int64),)),),
            (
                IrFunction(
                    "read",
                    (IrParam("stmt", stmt_type),),
                    int64,
                    (IrReturn(IrGetField(IrName("stmt", compound_type), "count", int64)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("getelementptr inbounds %CompoundStmt", llvm_ir)

    def test_emits_field_access_after_union_record_name_narrowing(self) -> None:
        int64 = IrIntType(64, signed=True)
        stmt_type = IrRecordType("Stmt")
        loop_union_type = IrRecordType("WhileStmt | ForStmt")
        module = IrModule(
            "union_record.py",
            (
                IrRecord("Stmt", ()),
                IrRecord("WhileStmt", (IrField("body", int64),)),
                IrRecord("ForStmt", (IrField("body", int64),)),
            ),
            (
                IrFunction(
                    "read",
                    (IrParam("stmt", stmt_type),),
                    int64,
                    (IrReturn(IrGetField(IrName("stmt", loop_union_type), "body", int64)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("getelementptr inbounds %WhileStmt", llvm_ir)

    def test_direct_emitter_resolves_union_record_field_owner(self) -> None:
        int64 = IrIntType(64, signed=True)
        emitter = _Emitter(
            IrModule(
                "union_record.py",
                (
                    IrRecord("WhileStmt", (IrField("body", int64),)),
                    IrRecord("EmptyStmt", ()),
                ),
                (),
            )
        )

        self.assertEqual(
            emitter._field_record_name("MissingStmt | WhileStmt", "body"),
            "WhileStmt",
        )
        with self.assertRaises(AotError) as ctx:
            emitter._field_record_name("MissingStmt | EmptyStmt", "body")
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")

    def test_emits_isinstance_class_marker_name_as_truthy_value(self) -> None:
        module = IrModule(
            "class_marker.py",
            (),
            (
                IrFunction(
                    "check",
                    (IrParam("symbol", IrRecordType("object")),),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "isinstance",
                                (
                                    IrName("symbol", IrRecordType("object")),
                                    IrName("VarSymbol", IrBoolType()),
                                ),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i1 @isinstance(ptr %symbol, i1 true)", llvm_ir)

    def test_emits_enumerate_for_each_without_runtime_enumerate_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = lower_source_to_ir(
            "def first_index(names: list[str]) -> int:\n"
            "    for index, name in enumerate(names):\n"
            "        return index\n"
            "    return 0\n",
            filename="enumerate_for.py",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("call i64 @__xcc_aot_tuple_len(ptr %names)", llvm_ir)
        self.assertRegex(llvm_ir, r"ret i64 %index\d+")
        self.assertNotIn("@__enumerate", llvm_ir)
        self.assertIn(f"ret i{int64.bits} 0", llvm_ir)

        skipped_item = lower_source_to_ir(
            "def first_index(names: list[str]) -> int:\n"
            "    for index, _ in enumerate(names):\n"
            "        return index\n"
            "    return 0\n",
            filename="enumerate_skip_item.py",
        )
        skipped_ir = emit_llvm_text(skipped_item)
        self.assertRegex(skipped_ir, r"ret i64 %index\d+")

    def test_emits_subscript_assignment_as_pointer_store(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((IrStringType(),))
        module = IrModule(
            "setitem.py",
            (),
            (
                IrFunction(
                    "store",
                    (
                        IrParam("values", tuple_type),
                        IrParam("index", int64),
                        IrParam("item", IrStringType()),
                    ),
                    IrNoneType(),
                    (
                        IrSetItem(
                            IrName("values", tuple_type),
                            IrName("index", int64),
                            IrName("item", IrStringType()),
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("getelementptr ptr, ptr %values, i64 %index", llvm_ir)
        self.assertIn("store ptr %item", llvm_ir)

    def test_emits_llvm_function_type_intrinsic_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "llvm_api.py",
            (),
            (
                IrFunction(
                    "make",
                    (
                        IrParam("ret_t", int64),
                        IrParam("param_ts", int64),
                        IrParam("n", int64),
                        IrParam("variadic", IrBoolType()),
                    ),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__llvm_FunctionType",
                                (
                                    IrName("ret_t", int64),
                                    IrName("param_ts", int64),
                                    IrName("n", int64),
                                    IrName("variadic", IrBoolType()),
                                ),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("call ptr @LLVMFunctionType(", llvm_ir)
        self.assertIn("declare ptr @LLVMFunctionType(ptr, ptr, i32, i1)", llvm_ir)
        self.assertNotIn("@__llvm_FunctionType", llvm_ir)

    def test_emits_enum_member_constants_as_stable_pointers(self) -> None:
        enum_type = IrRecordType("Enum")
        module = IrModule(
            "enum.py",
            (),
            (
                IrFunction(
                    "same",
                    (),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_Eq",
                                (
                                    IrEnumMember("Kind", "EOF"),
                                    IrEnumMember("Kind", "EOF"),
                                ),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "is_eof",
                    (IrParam("kind", enum_type),),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_Eq",
                                (IrName("kind", enum_type), IrEnumMember("Kind", "EOF")),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertEqual(llvm_ir.count('c"Kind.EOF\\00"'), 1)
        self.assertIn("icmp eq ptr @.enum0, @.enum0", llvm_ir)
        self.assertIn("icmp eq ptr %kind, @.enum0", llvm_ir)

    def test_emits_string_startswith_intrinsic_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "startswith.py",
            (),
            (
                IrFunction(
                    "check",
                    (),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "__str_startswith",
                                (
                                    IrConstString("abcdef"),
                                    IrConstString("cd"),
                                    IrConstInt(2, int64),
                                ),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define i1 @__xcc_aot_string_startswith", llvm_ir)
        self.assertIn("call i1 @__xcc_aot_string_startswith(ptr @.str0, ptr @.str1, i64 2)", llvm_ir)

    def test_emits_string_startswith_tuple_prefix_intrinsic_calls(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "startswith_tuple.py",
            (),
            (
                IrFunction(
                    "check",
                    (),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "__str_startswith",
                                (
                                    IrConstString("abcdef"),
                                    IrTuple(
                                        (IrConstString("ab"), IrConstString("cd")),
                                        IrTupleType((IrStringType(), IrStringType())),
                                    ),
                                    IrConstInt(0, int64),
                                ),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i1 @__xcc_aot_string_startswith(ptr @.str0, ptr @.str1, i64 0)", llvm_ir)
        self.assertIn("call i1 @__xcc_aot_string_startswith(ptr @.str0, ptr @.str2, i64 0)", llvm_ir)
        self.assertIn("or i1", llvm_ir)

    def test_emits_string_startswith_object_prefix_as_string_pointer(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "startswith_object_prefix.py",
            (),
            (
                IrFunction(
                    "check",
                    (IrParam("prefix", IrRecordType("object")),),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "__str_startswith",
                                (
                                    IrConstString("abcdef"),
                                    IrName("prefix", IrRecordType("object")),
                                    IrConstInt(0, int64),
                                ),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i1 @__xcc_aot_string_startswith(ptr @.str0, ptr %prefix, i64 0)", llvm_ir)

    def test_emits_string_endswith_intrinsic_call(self) -> None:
        module = IrModule(
            "endswith.py",
            (),
            (
                IrFunction(
                    "check",
                    (),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "__str_endswith",
                                (IrConstString("abcdef"), IrConstString("ef")),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define i1 @__xcc_aot_string_endswith", llvm_ir)
        self.assertIn("call i1 @__xcc_aot_string_endswith(ptr @.str0, ptr @.str1)", llvm_ir)

    def test_emits_string_order_compare_with_strcmp(self) -> None:
        module = IrModule(
            "string_order.py",
            (),
            (
                IrFunction(
                    "check",
                    (IrParam("ch", IrStringType()),),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_LtE",
                                (IrConstString("a"), IrName("ch", IrStringType())),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i32 @strcmp", llvm_ir)
        self.assertIn("icmp sle i32", llvm_ir)

    def test_emits_string_ljust_and_rstrip_intrinsic_calls(self) -> None:
        int64 = IrIntType(64, signed=True)
        string_type = IrStringType()
        module = IrModule(
            "string_padding.py",
            (),
            (
                IrFunction(
                    "pad",
                    (),
                    string_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_ljust",
                                (
                                    IrConstString("ab"),
                                    IrConstInt(4, int64),
                                    IrConstString("."),
                                ),
                                string_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "trim",
                    (),
                    string_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_rstrip",
                                (IrConstString("ab.."), IrConstString(".")),
                                string_type,
                            )
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define ptr @__xcc_aot_string_ljust", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_string_rstrip", llvm_ir)
        self.assertIn(
            "call ptr @__xcc_aot_string_ljust(ptr @.str0, i64 4, ptr @.str1)",
            llvm_ir,
        )
        self.assertIn("call ptr @__xcc_aot_string_rstrip(ptr @.str2, ptr @.str3)", llvm_ir)

    def test_emits_bytes_id_and_int_to_bytes_intrinsic_calls(self) -> None:
        int64 = IrIntType(64, signed=True)
        string_type = IrStringType()
        module = IrModule(
            "bytes_helpers.py",
            (),
            (
                IrFunction(
                    "zeroed",
                    (),
                    string_type,
                    (IrReturn(IrCall("__bytes", (IrConstInt(3, int64),), string_type)),),
                ),
                IrFunction(
                    "key",
                    (IrParam("value", IrRecordType("object")),),
                    int64,
                    (IrReturn(IrCall("__id", (IrName("value", IrRecordType("object")),), int64)),),
                ),
                IrFunction(
                    "encode",
                    (),
                    string_type,
                    (
                        IrReturn(
                            IrCall(
                                "__int_to_bytes",
                                (IrConstInt(65, int64), IrConstInt(1, int64), IrConstString("little")),
                                string_type,
                            )
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define ptr @__xcc_aot_zero_bytes", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_int_to_bytes", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_zero_bytes(i64 3)", llvm_ir)
        self.assertIn("ptrtoint ptr %value to i64", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_int_to_bytes(i64 65, i64 1, ptr @.str0)", llvm_ir)

    def test_emits_string_predicate_intrinsic_calls(self) -> None:
        bool_type = IrBoolType()
        module = IrModule(
            "string_predicates.py",
            (),
            (
                IrFunction(
                    "alpha",
                    (),
                    bool_type,
                    (IrReturn(IrCall("__str_isalpha", (IrConstString("a"),), bool_type)),),
                ),
                IrFunction(
                    "digit",
                    (),
                    bool_type,
                    (IrReturn(IrCall("__str_isdigit", (IrConstString("1"),), bool_type)),),
                ),
                IrFunction(
                    "alnum",
                    (),
                    bool_type,
                    (IrReturn(IrCall("__str_isalnum", (IrConstString("a1"),), bool_type)),),
                ),
                IrFunction(
                    "space",
                    (),
                    bool_type,
                    (IrReturn(IrCall("__str_isspace", (IrConstString(" "),), bool_type)),),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define i1 @__xcc_aot_string_predicate", llvm_ir)
        self.assertIn("call i1 @__xcc_aot_string_predicate(ptr @.str0, i64 1)", llvm_ir)
        self.assertIn("call i1 @__xcc_aot_string_predicate(ptr @.str1, i64 2)", llvm_ir)
        self.assertIn("call i1 @__xcc_aot_string_predicate(ptr @.str2, i64 3)", llvm_ir)
        self.assertIn("call i1 @__xcc_aot_string_predicate(ptr @.str3, i64 4)", llvm_ir)

    def test_emits_int_parse_intrinsic_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "int_parse.py",
            (),
            (
                IrFunction(
                    "parse",
                    (),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__int_parse",
                                (IrConstString("ff"), IrConstInt(16, int64)),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define i64 @__xcc_aot_parse_int", llvm_ir)
        self.assertIn("call i64 @__xcc_aot_parse_int(ptr @.str0, i64 16)", llvm_ir)

    def test_emits_intrinsics_tuple_boxes_and_truth_edges(self) -> None:
        int32 = IrIntType(32, signed=True)
        uint32 = IrIntType(32, signed=False)
        int64 = IrIntType(64, signed=True)
        int128 = IrIntType(128, signed=True)
        bool_type = IrBoolType()
        tuple_type = IrTupleType((IrNoneType(), bool_type, int32, uint32, int128, IrStringType()))
        module = IrModule(
            "intrinsics.py",
            (),
            (
                IrFunction(
                    "condition_int",
                    (),
                    int64,
                    (
                        IrIf(
                            IrConstInt(1, int64),
                            IrBranch((IrReturn(IrConstInt(1, int64)),)),
                            IrBranch((IrReturn(IrConstInt(0, int64)),)),
                        ),
                    ),
                ),
                IrFunction(
                    "condition_none",
                    (),
                    int64,
                    (
                        IrIf(
                            IrConstNone(),
                            IrBranch((IrReturn(IrConstInt(1, int64)),)),
                            IrBranch((IrReturn(IrConstInt(0, int64)),)),
                        ),
                    ),
                ),
                IrFunction(
                    "string_none",
                    (),
                    IrStringType(),
                    (IrReturn(IrStringConcat((IrConstString("x"), IrConstNone()))),),
                ),
                IrFunction(
                    "tuple_boxes",
                    (),
                    tuple_type,
                    (
                        IrReturn(
                            IrTuple(
                                (
                                    IrConstNone(),
                                    IrConstBool(True),
                                    IrConstInt(-1, int32),
                                    IrConstInt(1, uint32),
                                    IrConstInt(1, int128),
                                    IrConstString("s"),
                                ),
                                tuple_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "not_in_empty",
                    (),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_NotIn",
                                (IrConstString("x"), IrTuple((), IrTupleType(()))),
                                bool_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "and_empty", (), bool_type, (IrReturn(IrCall("__bool_and", (), bool_type)),)
                ),
                IrFunction(
                    "or_empty", (), bool_type, (IrReturn(IrCall("__bool_or", (), bool_type)),)
                ),
                IrFunction(
                    "not_none",
                    (),
                    bool_type,
                    (IrReturn(IrCall("__not", (IrConstNone(),), bool_type)),),
                ),
                IrFunction(
                    "not_int",
                    (),
                    bool_type,
                    (IrReturn(IrCall("__not", (IrConstInt(1, int64),), bool_type)),),
                ),
                IrFunction(
                    "eq_int",
                    (),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_Eq",
                                (IrConstInt(1, int64), IrConstInt(1, int64)),
                                bool_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "eq_bool",
                    (),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_Eq",
                                (IrConstBool(True), IrConstBool(False)),
                                bool_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "eq_ptr_int",
                    (),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_Eq",
                                (IrConstNone(), IrConstInt(0, int64)),
                                bool_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "eq_int_ptr",
                    (),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_Eq",
                                (IrConstInt(0, int64), IrConstNone()),
                                bool_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "eq_ptr",
                    (),
                    bool_type,
                    (IrReturn(IrCall("__cmp_Eq", (IrConstNone(), IrConstNone()), bool_type)),),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("icmp ne i64 1, 0", llvm_ir)
        self.assertIn("inttoptr i64", llvm_ir)
        self.assertIn("sext i32 -1 to i64", llvm_ir)
        self.assertIn("zext i32 1 to i64", llvm_ir)
        self.assertIn("trunc i128 1 to i64", llvm_ir)
        self.assertIn("icmp eq ptr null, null", llvm_ir)

    def test_llvm_text_private_helpers_cover_edge_inputs(self) -> None:
        self.assertEqual(_llvm_symbol("super().__init__"), '@"super().__init__"')
        self.assertFalse(_block_is_terminated([]))
        self.assertEqual(_current_label(["  ret i32 0"]), "entry")
        self.assertEqual(_for_each_targets("item"), ("item",))
        self.assertEqual(_for_each_targets("(kind, _)"), ("kind",))
        self.assertEqual(
            _statement_assigned_names(IrAssign("(left, _)", IrConstNone())),
            ("left",),
        )
        self.assertEqual(
            _statement_assigned_names(
                IrSetItem(
                    IrName("values", IrTupleType((IrStringType(),))),
                    IrConstInt(0, IrIntType(64, signed=True)),
                    IrConstString("x"),
                )
            ),
            (),
        )
        self.assertEqual(_statement_assigned_names(IrBreak()), ())
        self.assertEqual(_statement_assigned_names(IrContinue()), ())
        self.assertEqual(
            _statement_assigned_names(
                IrIf(
                    IrConstBool(True),
                    IrBranch((IrAssign("then_only", IrConstNone()),)),
                    None,
                )
            ),
            ("then_only",),
        )
        self.assertEqual(_statement_assigned_names(IrReturn(IrConstNone())), ())
        self.assertEqual(
            _branch_assigned_names(
                IrBranch(
                    (
                        IrIf(
                            IrConstBool(True),
                            IrBranch((IrAssign("then_value", IrConstNone()),)),
                            IrBranch((IrAssign("else_value", IrConstNone()),)),
                        ),
                        IrForEach(
                            "item",
                            IrTuple((), IrTupleType(())),
                            IrBranch((IrAssign("loop_value", IrConstNone()),)),
                        ),
                        IrWhile(
                            IrConstBool(True),
                            IrBranch((IrAssign("while_value", IrConstNone()),)),
                        ),
                    )
                )
            ),
            ("else_value", "item", "loop_value", "then_value", "while_value"),
        )
        emitter = _Emitter(IrModule("bad.py", (), ()))
        with self.assertRaises(AotError) as ctx:
            emitter._default_value(object())  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        self.assertEqual(emitter._default_value(IrBoolType()), "false")
        self.assertEqual(emitter._default_value(IrFloatType()), "0.0")
        with self.assertRaises(AotError) as ctx:
            emitter._emit_runtime_boxed_value("%raw", object(), [])  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        self.assertIsNone(
            emitter._emit_runtime_object_narrowing(
                _EmittedValue("%raw", IrRecordType("object")),
                IrFloatType(),
                [],
            )
        )
        with self.assertRaises(AotError) as ctx:
            emitter._emit_status_return([], object())  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        with self.assertRaises(AotError) as ctx:
            emitter._emit_statement(IrBreak(), {}, [], IrNoneType())
        self.assertEqual(ctx.exception.diagnostics[0].message, "break outside loop")
        with self.assertRaises(AotError) as ctx:
            emitter._emit_statement(IrContinue(), {}, [], IrNoneType())
        self.assertEqual(ctx.exception.diagnostics[0].message, "continue outside loop")
        with self.assertRaises(AotError) as ctx:
            emitter._emit_default_return([], object())  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        original_emit_expr = emitter._emit_expr
        emitter._emit_expr = (  # type: ignore[method-assign]
            lambda expr, names, lines: _EmittedValue("value", object())
        )
        with self.assertRaises(AotError) as ctx:
            emitter._emit_condition(IrConstBool(True), {}, [])
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        emitter._emit_expr = original_emit_expr  # type: ignore[method-assign]
        with self.assertRaises(AotError) as ctx:
            emitter._coerce_to_bool(_EmittedValue("value", object()), [])  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        with self.assertRaises(AotError) as ctx:
            emitter._box_to_runtime_ptr(_EmittedValue("value", object()), [])  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        with self.assertRaises(AotError) as ctx:
            emitter._pointer_compare_value(_EmittedValue("value", object()))  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        with self.assertRaises(AotError) as ctx:
            emitter._coerce_llvm_pointer(_EmittedValue("value", IrBoolType()), [])
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        self.assertEqual(
            emitter._coerce_llvm_pointer(_EmittedValue("value", IrStringType()), []),
            "value",
        )
        self.assertEqual(
            emitter._coerce_llvm_pointer(_EmittedValue("value", IrNoneType()), []),
            "null",
        )
        with self.assertRaises(AotError) as ctx:
            emitter._coerce_i32(_EmittedValue("value", IrBoolType()), [])
        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")
        self.assertEqual(
            emitter._coerce_i32(_EmittedValue("value", IrIntType(32, signed=True)), []),
            "value",
        )
        widen_lines: list[str] = []
        self.assertTrue(
            emitter._coerce_i32(
                _EmittedValue("value", IrIntType(16, signed=True)),
                widen_lines,
            ).startswith("%i32")
        )
        self.assertIn("sext i16 value to i32", widen_lines[0])

        int64 = IrIntType(64, signed=True)
        llvm_api_module = IrModule(
            "llvm_api_handle.py",
            (),
            (
                IrFunction(
                    "handle",
                    (),
                    IrRecordType("LLVMApi"),
                    (IrReturn(IrCall("__llvm_api", (), IrRecordType("LLVMApi"))),),
                ),
            ),
        )
        self.assertIn("ret ptr null", emit_llvm_text(llvm_api_module))

        enumerate_cases = (
            (
                IrCall("__enumerate", (), IrTupleType((int64, IrStringType()))),
                "__enumerate expects one argument",
            ),
            (
                IrCall(
                    "__enumerate",
                    (IrTuple((), IrTupleType(())),),
                    IrStringType(),
                ),
                "Malformed __enumerate loop",
            ),
            (
                IrCall(
                    "__enumerate",
                    (IrTuple((), IrTupleType(())),),
                    IrTupleType((int64,)),
                ),
                "__enumerate loop expects two element types",
            ),
            (
                IrCall(
                    "__enumerate",
                    (IrTuple((), IrTupleType(())),),
                    IrTupleType((int64, IrStringType())),
                ),
                "__enumerate loop expects two targets",
            ),
        )
        for iterable, message in enumerate_cases:
            with self.subTest(message=message):
                target = "pair" if "targets" in message else "(index, item)"
                bad_module = IrModule(
                    "bad_enumerate.py",
                    (),
                    (
                        IrFunction(
                            "walk",
                            (),
                            IrNoneType(),
                            (IrForEach(target, iterable, IrBranch(())),),
                        ),
                    ),
                )
                with self.assertRaises(AotError) as ctx:
                    emit_llvm_text(bad_module)
                self.assertEqual(ctx.exception.diagnostics[0].message, message)

        bad_llvm_function_type = IrModule(
            "bad_llvm_call.py",
            (),
            (
                IrFunction(
                    "bad",
                    (),
                    int64,
                    (IrReturn(IrCall("__llvm_FunctionType", (), int64)),),
                ),
            ),
        )
        with self.assertRaises(AotError) as ctx:
            emit_llvm_text(bad_llvm_function_type)
        self.assertEqual(
            ctx.exception.diagnostics[0].message,
            "LLVMFunctionType helper expects four args -> int",
        )

    def test_reports_unsupported_llvm_shapes(self) -> None:
        int64 = IrIntType(64, signed=True)
        record = IrRecord("Box", (IrField("value", int64),))
        cases = (
            IrModule(
                "bad.py",
                (),
                (IrFunction("f", (), object(), (IrReturn(IrConstInt(1, int64)),)),),
            ),
            IrModule("bad.py", (), (IrFunction("f", (), int64, (object(),)),)),
            IrModule("bad.py", (), (IrFunction("f", (), int64, (IrReturn(object()),)),)),
            IrModule("bad.py", (), (IrFunction("f", (), int64, (IrReturn(IrName("x", int64)),)),)),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (IrParam("items", IrTupleType((IrStringType(),))),),
                        IrNoneType(),
                        (
                            IrForEach(
                                "(left, right)",
                                IrName("items", IrTupleType((IrStringType(),))),
                                IrBranch(()),
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__cmp_Lt",
                                    (IrConstBool(False), IrConstBool(True)),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_startswith",
                                    (
                                        IrConstString("x"),
                                        IrTuple(
                                            (IrConstInt(1, int64),),
                                            IrTupleType((int64,)),
                                        ),
                                        IrConstInt(0, int64),
                                    ),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrNoneType(),
                        (IrAssign("(left, right)", IrConstBool(True)),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (
                            IrReturn(
                                IrCall(
                                    "len",
                                    (
                                        IrTuple((), IrTupleType(())),
                                        IrConstInt(0, int64),
                                    ),
                                    int64,
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (IrReturn(IrCall("__bytes", (), IrStringType())),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (IrReturn(IrCall("__bytes", (IrConstBool(True),), IrStringType())),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (IrReturn(IrCall("__bytes", (IrConstInt(1, int64),), int64)),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (IrReturn(IrCall("__id", (), int64)),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (IrReturn(IrCall("__id", (IrConstString("x"),), IrStringType())),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (IrReturn(IrCall("__id", (IrConstInt(1, int64),), int64)),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (IrReturn(IrCall("__int_to_bytes", (IrConstInt(1, int64),), IrStringType())),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__int_to_bytes",
                                    (
                                        IrConstString("x"),
                                        IrConstInt(1, int64),
                                        IrConstString("little"),
                                    ),
                                    IrStringType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__int_to_bytes",
                                    (
                                        IrConstInt(1, int64),
                                        IrConstBool(True),
                                        IrConstString("little"),
                                    ),
                                    IrStringType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__int_to_bytes",
                                    (
                                        IrConstInt(1, int64),
                                        IrConstInt(1, int64),
                                        IrConstBool(True),
                                    ),
                                    IrStringType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (
                            IrReturn(
                                IrCall(
                                    "__int_to_bytes",
                                    (
                                        IrConstInt(1, int64),
                                        IrConstInt(1, int64),
                                        IrConstString("little"),
                                    ),
                                    int64,
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_ljust",
                                    (IrConstString("x"), IrConstInt(2, int64)),
                                    IrStringType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_ljust",
                                    (
                                        IrConstInt(1, int64),
                                        IrConstInt(2, int64),
                                        IrConstString(" "),
                                    ),
                                    IrStringType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_ljust",
                                    (
                                        IrConstString("x"),
                                        IrConstBool(True),
                                        IrConstString(" "),
                                    ),
                                    IrStringType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (
                            IrReturn(
                                IrCall(
                                    "__str_ljust",
                                    (
                                        IrConstString("x"),
                                        IrConstInt(2, int64),
                                        IrConstString(" "),
                                    ),
                                    int64,
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_rstrip",
                                    (IrConstString("x"),),
                                    IrStringType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_rstrip",
                                    (IrConstString("x"), IrConstInt(1, int64)),
                                    IrStringType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (
                            IrReturn(
                                IrCall(
                                    "__str_rstrip",
                                    (IrConstString("x"), IrConstString("x")),
                                    int64,
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_endswith",
                                    (IrConstString("x"),),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_endswith",
                                    (IrConstString("x"), IrConstInt(1, int64)),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (
                            IrReturn(
                                IrCall(
                                    "__str_endswith",
                                    (IrConstString("x"), IrConstString("x")),
                                    int64,
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (IrReturn(IrCall("__int_parse", (IrConstString("1"),), int64)),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (
                            IrReturn(
                                IrCall(
                                    "__int_parse",
                                    (IrConstInt(1, int64), IrConstInt(10, int64)),
                                    int64,
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (
                            IrReturn(
                                IrCall(
                                    "__int_parse",
                                    (IrConstString("1"), IrConstBool(True)),
                                    int64,
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__int_parse",
                                    (IrConstString("1"), IrConstInt(10, int64)),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (IrReturn(IrCall("__str_isalpha", (), IrBoolType())),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (IrReturn(IrCall("__str_isalpha", (IrConstInt(1, int64),), IrBoolType())),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (IrReturn(IrCall("__str_isalpha", (IrConstString("x"),), int64)),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_startswith",
                                    (IrConstString("x"),),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_startswith",
                                    (
                                        IrConstInt(1, int64),
                                        IrConstString("x"),
                                        IrConstInt(0, int64),
                                    ),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_startswith",
                                    (
                                        IrConstString("x"),
                                        IrConstInt(1, int64),
                                        IrConstInt(0, int64),
                                    ),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_startswith",
                                    (
                                        IrConstString("x"),
                                        IrConstString("x"),
                                        IrConstBool(False),
                                    ),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__str_startswith",
                                    (
                                        IrConstString("x"),
                                        IrConstString("x"),
                                        IrConstInt(0, IrIntType(32, signed=True)),
                                    ),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (
                            IrReturn(
                                IrCall(
                                    "__str_startswith",
                                    (
                                        IrConstString("x"),
                                        IrConstString("x"),
                                        IrConstInt(0, int64),
                                    ),
                                    int64,
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__cmp_Lt",
                                    (IrConstInt(1, int64),),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__cmp_Lt",
                                    (
                                        IrConstInt(1, IrIntType(32, signed=True)),
                                        IrConstInt(2, int64),
                                    ),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (
                            IrReturn(
                                IrCall(
                                    "len",
                                    (IrTuple((), IrTupleType(())),),
                                    IrBoolType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__getitem",
                                    (
                                        IrTuple(
                                            (IrConstString("x"),),
                                            IrTupleType((IrStringType(),)),
                                        ),
                                        IrConstBool(True),
                                    ),
                                    IrStringType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (
                            IrReturn(
                                IrCall(
                                    "__getitem",
                                    (IrTuple((), IrTupleType(())),),
                                    IrStringType(),
                                )
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "xcc.lexer.translate_source",
                        (),
                        IrStringType(),
                        (IrReturn(IrConstString("")),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "xcc.lexer._aot_header_summary_for_source",
                        (),
                        IrStringType(),
                        (IrReturn(IrConstString("")),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "xcc.lexer._aot_token_summary_for_source",
                        (),
                        IrStringType(),
                        (IrReturn(IrConstString("")),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (
                            IrReturn(
                                IrBinary("/", IrConstInt(1, int64), IrConstInt(2, int64), int64)
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        int64,
                        (IrReturn(IrGetField(IrConstInt(1, int64), "value", int64)),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (record,),
                (
                    IrFunction(
                        "f",
                        (IrParam("box", IrRecordType("Box")),),
                        int64,
                        (
                            IrReturn(
                                IrGetField(IrName("box", IrRecordType("Box")), "missing", int64)
                            ),
                        ),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (IrRecord("Box", ()),),
                (
                    IrFunction(
                        "box",
                        (),
                        IrRecordType("Box"),
                        (IrReturn(IrConstructRecord("Box", (), IrRecordType("Box"))),),
                    ),
                ),
                entry="box",
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrStringType(),
                        (IrReturn(IrStringConcat((IrConstString("x"), IrConstBool(True)))),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f", (), IrBoolType(), (IrReturn(IrCall("__not", (), IrBoolType())),)
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (IrReturn(IrCall("__ifexp", (IrConstBool(True),), IrBoolType())),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (IrReturn(IrCall("__cmp_Eq", (IrConstInt(1, int64),), IrBoolType())),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (),
                (
                    IrFunction(
                        "f",
                        (),
                        IrBoolType(),
                        (IrReturn(IrCall("__cmp_Is", (IrConstInt(1, int64),), IrBoolType())),),
                    ),
                ),
            ),
            IrModule(
                "bad.py",
                (IrRecord("Type", (IrField("name", IrStringType()),)),),
                (
                    IrFunction(
                        "xcc.types.Type.__str__", (), IrStringType(), (IrReturn(IrConstString("")),)
                    ),
                ),
            ),
        )
        for module in cases:
            with self.subTest(module=module):
                with self.assertRaises(AotError) as ctx:
                    emit_llvm_text(module)  # type: ignore[arg-type]
                self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-LLVM-0001")


if __name__ == "__main__":
    unittest.main()
