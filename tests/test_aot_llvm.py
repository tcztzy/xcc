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
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrParam,
    IrRaise,
    IrRecord,
    IrRecordType,
    IrReturn,
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
                                    (IrConstString("x"), IrConstString("y")),
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
                        int64,
                        (
                            IrReturn(
                                IrCall(
                                    "__getitem",
                                    (
                                        IrTuple(
                                            (IrConstString("x"),),
                                            IrTupleType((IrStringType(),)),
                                        ),
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
