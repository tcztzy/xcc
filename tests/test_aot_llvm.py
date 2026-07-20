import unittest

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    AotError,
    IrAssign,
    IrBinary,
    IrBoolType,
    IrBreak,
    IrBranch,
    IrBytesType,
    IrCall,
    IrConstBool,
    IrConstFloat,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrContinue,
    IrDictType,
    IrEnumMember,
    IrExceptHandler,
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
    IrTry,
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
    _phase_intrinsic_is_no_capture,
    _statement_assignment_types,
    _statement_assigned_names,
)


class AotLlvmTextTests(unittest.TestCase):
    def test_routes_heap_allocations_through_bounded_runtime(self) -> None:
        int64 = IrIntType(64, signed=True)
        record_type = IrRecordType("Box")
        module = IrModule(
            "bounded_alloc.py",
            (IrRecord("Box", (IrField("value", int64),)),),
            (
                IrFunction(
                    "box",
                    (),
                    record_type,
                    (IrReturn(IrConstructRecord("Box", (IrConstInt(1, int64),), record_type)),),
                ),
                IrFunction(
                    "literal",
                    (),
                    IrStringType(),
                    (IrReturn(IrConstString("call ptr @malloc(i64 9)")),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("@__xcc_aot_allocation_limit = internal constant i64 536870912", llvm_ir)
        self.assertIn("define internal ptr @__xcc_aot_alloc(i64 %requested)", llvm_ir)
        self.assertIn("define internal ptr @__xcc_aot_calloc(i64 %count, i64 %item_size)", llvm_ir)
        self.assertIn("call void @_exit(i32 70)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_alloc(i64 16)", llvm_ir)
        self.assertNotRegex(llvm_ir, r"(?m)^\s+%.* = call ptr @malloc\(")
        self.assertNotRegex(llvm_ir, r"(?m)^\s+%.* = call ptr @calloc\(")
        self.assertIn('c"call ptr @malloc(i64 9)\\00"', llvm_ir)

    def test_v390_inserts_owned_phase_only_when_local_allocations_cannot_escape(
        self,
    ) -> None:
        for target in (
            "__dict_remove",
            "__dict_set",
            "__dict_setdefault",
            "__dict_update",
            "__llvm_AddIncoming",
            "__llvm_api",
            "__record_init__:Box.__init__",
            "__set_add",
            "__super_init__",
            "__tuple_pop_item",
            "__tuple_remove_item",
            "__tuple_set_slice",
        ):
            with self.subTest(no_capture_target=target):
                self.assertFalse(_phase_intrinsic_is_no_capture(target))
        for target in ("__cmp_Eq", "__dict_get", "__str_startswith"):
            with self.subTest(borrowing_target=target):
                self.assertTrue(_phase_intrinsic_is_no_capture(target))

        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((int64,))
        string_type = IrStringType()
        string_tuple_type = IrTupleType((string_type,))
        optional_int_type = IrRecordType("int | None")
        local_tuple = IrTuple((IrConstInt(1, int64),), tuple_type)
        module = IrModule(
            "owned_phase.py",
            (),
            (
                IrFunction(
                    "safe",
                    (),
                    int64,
                    (
                        IrAssign("items", local_tuple),
                        IrIf(
                            IrConstBool(True),
                            IrBranch((IrReturn(IrConstInt(1, int64)),)),
                            IrBranch((IrReturn(IrConstInt(2, int64)),)),
                        ),
                    ),
                ),
                IrFunction(
                    "returns_pointer",
                    (),
                    tuple_type,
                    (IrReturn(local_tuple),),
                ),
                IrFunction(
                    "returns_borrowed_pointer",
                    (IrParam("values", string_tuple_type),),
                    string_type,
                    (
                        IrAssign("scratch", local_tuple),
                        IrReturn(
                            IrCall(
                                "__getitem",
                                (IrName("values", string_tuple_type), IrConstInt(0, int64)),
                                string_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "returns_boxed_scalar_pointer",
                    (),
                    optional_int_type,
                    (
                        IrAssign("scratch", local_tuple),
                        IrReturn(IrConstInt(1, int64)),
                    ),
                ),
                IrFunction(
                    "sink",
                    (IrParam("value", tuple_type),),
                    IrNoneType(),
                    (),
                ),
                IrFunction(
                    "passes_to_known_call",
                    (),
                    int64,
                    (
                        IrAssign("items", local_tuple),
                        IrAssign(
                            "__expr",
                            IrCall(
                                "sink",
                                (IrName("items", tuple_type),),
                                IrNoneType(),
                            ),
                        ),
                        IrReturn(IrConstInt(0, int64)),
                    ),
                ),
                IrFunction(
                    "mutating_sink",
                    (IrParam("value", tuple_type),),
                    IrNoneType(),
                    (
                        IrSetItem(
                            IrName("value", tuple_type),
                            IrConstInt(0, int64),
                            IrConstInt(2, int64),
                        ),
                    ),
                ),
                IrFunction(
                    "passes_to_mutating_call",
                    (),
                    int64,
                    (
                        IrAssign("items", local_tuple),
                        IrAssign(
                            "__expr",
                            IrCall(
                                "mutating_sink",
                                (IrName("items", tuple_type),),
                                IrNoneType(),
                            ),
                        ),
                        IrReturn(IrConstInt(0, int64)),
                    ),
                ),
                IrFunction(
                    "writes_borrowed_container",
                    (IrParam("borrowed", tuple_type),),
                    int64,
                    (
                        IrAssign("items", local_tuple),
                        IrSetItem(
                            IrName("borrowed", tuple_type),
                            IrConstInt(0, int64),
                            IrConstInt(2, int64),
                        ),
                        IrReturn(IrConstInt(0, int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        safe_body = llvm_ir.split("define i64 @safe()", 1)[1].split("\n}", 1)[0]
        self.assertIn("call ptr @__xcc_aot_phase_mark()", safe_body)
        self.assertEqual(
            safe_body.count("call void @__xcc_aot_phase_reset"),
            safe_body.count("ret i64"),
        )
        known_call_body = llvm_ir.split(
            "define i64 @passes_to_known_call()", 1
        )[1].split("\n}", 1)[0]
        self.assertIn("call ptr @__xcc_aot_phase_mark()", known_call_body)
        self.assertIn("call void @__xcc_aot_phase_reset", known_call_body)
        borrowed_return_body = llvm_ir.split(
            "define ptr @returns_borrowed_pointer(ptr %values)", 1
        )[1].split("\n}", 1)[0]
        self.assertIn("call ptr @__xcc_aot_phase_mark()", borrowed_return_body)
        self.assertIn("call void @__xcc_aot_phase_reset", borrowed_return_body)
        for function, signature in (
            ("returns_pointer", "define ptr @returns_pointer()"),
            (
                "returns_boxed_scalar_pointer",
                "define ptr @returns_boxed_scalar_pointer()",
            ),
        ):
            with self.subTest(function=function):
                body = llvm_ir.split(signature, 1)[1].split("\n}", 1)[0]
                self.assertIn("call ptr @__xcc_aot_phase_mark()", body)
                self.assertIn('call void @"__xcc_aot_phase_promote:', body)
                self.assertIn("call void @__xcc_aot_phase_reset", body)
        for function, signature in (
            ("passes_to_mutating_call", "define i64 @passes_to_mutating_call()"),
            (
                "writes_borrowed_container",
                "define i64 @writes_borrowed_container(ptr %borrowed)",
            ),
        ):
            with self.subTest(function=function):
                body = llvm_ir.split(signature, 1)[1].split("\n}", 1)[0]
                self.assertNotIn("@__xcc_aot_phase_mark", body)
                self.assertNotIn("@__xcc_aot_phase_reset", body)

    def test_emits_integer_augmented_assignment_operators(self) -> None:
        module = lower_source_to_ir(
            "def update(value: int) -> int:\n"
            "    value //= 2\n"
            "    value %= 3\n"
            "    value <<= 4\n"
            "    value >>= 1\n"
            "    value &= 15\n"
            "    value |= 16\n"
            "    value ^= 7\n"
            "    return value\n",
            filename="integer_augassign.py",
            entry="update",
        )

        llvm_ir = emit_llvm_text(module)

        for opcode in ("sdiv", "srem", "shl", "ashr", "and", "or", "xor"):
            self.assertIn(f" = {opcode} i64 ", llvm_ir)

    def test_hoists_loop_expression_allocas_to_function_entry(self) -> None:
        module = lower_source_to_ir(
            "def count(items: tuple[str, ...], allowed: set[str]) -> int:\n"
            "    total = 0\n"
            "    for item in items:\n"
            "        if item in allowed:\n"
            "            total += 1\n"
            "    return total\n",
            filename="loop_alloca.py",
            entry="count",
        )

        llvm_ir = emit_llvm_text(module)
        function_body = llvm_ir.split("define i64 @count", 1)[1].split("\n}", 1)[0]
        active_label = ""
        allocations = 0
        for line in function_body.splitlines():
            if line.endswith(":"):
                active_label = line
            elif " = alloca " in line:
                allocations += 1
                self.assertEqual(active_label, "entry:")
        self.assertGreater(allocations, 0)

    def test_source_to_llvm_wrapper_uses_generic_status_handler_abi(self) -> None:
        unchecked_name = "xcc.cc_driver._aot_compile_source_to_llvm_ir_unchecked"
        wrapper_name = "xcc.cc_driver._aot_compile_source_to_llvm_ir"
        module = IrModule(
            "source_to_llvm_status.py",
            (IrRecord("FrontendError", (), ("Exception",)),),
            (
                IrFunction(
                    unchecked_name,
                    (),
                    IrStringType(),
                    (IrRaise("FrontendError", IrConstString("bad")),),
                ),
                IrFunction(
                    wrapper_name,
                    (),
                    IrStringType(),
                    (
                        IrTry(
                            IrBranch(
                                (
                                    IrReturn(
                                        IrCall(unchecked_name, (), IrStringType())
                                    ),
                                )
                            ),
                            (
                                IrExceptHandler(
                                    ("FrontendError",),
                                    None,
                                    IrBranch((IrReturn(IrConstString("")),)),
                                ),
                            ),
                            IrBranch(()),
                            IrBranch(()),
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn(f"define i32 @{wrapper_name}(ptr %result_out, ptr %error_out)", llvm_ir)
        self.assertIn(f"call i32 @{unchecked_name}(ptr %callresult", llvm_ir)
        self.assertNotIn(f"call ptr @{unchecked_name}()", llvm_ir)

    def test_v406_fallible_phase_commits_failure_and_resets_success(self) -> None:
        int64 = IrIntType(64, signed=True)
        worker = IrFunction(
            "worker",
            (IrParam("fail", IrBoolType()),),
            IrStringType(),
            (
                IrAssign(
                    "scratch",
                    IrTuple((IrConstInt(1, int64),), IrTupleType((int64,))),
                ),
                IrIf(
                    IrName("fail", IrBoolType()),
                    IrBranch(
                        (
                            IrRaise(
                                "ValueError",
                                IrStringConcat(
                                    (IrConstString("bad"), IrConstString(" message"))
                                ),
                            ),
                        )
                    ),
                    IrBranch((IrReturn(IrConstString("ok")),)),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(IrModule("fallible-phase.py", (), (worker,)))
        body = llvm_ir.split(
            "define i32 @worker(i1 %fail, ptr %result_out, ptr %error_out)", 1
        )[1].split("\n}", 1)[0]

        self.assertIn("call ptr @__xcc_aot_phase_mark()", body)
        self.assertIn("call void @__xcc_aot_phase_commit", body)
        self.assertIn("call void @__xcc_aot_phase_reset", body)
        self.assertLess(
            body.index("call void @__xcc_aot_phase_commit"),
            body.index("ret i32 2"),
        )

    def test_emits_bytes_concat_and_repeat_runtime_calls(self) -> None:
        module = lower_source_to_ir(
            "def combine(value: bytes, count: int) -> bytes:\n"
            "    return value + b'x' * count\n",
            filename="bytes_ops.py",
            entry="combine",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_bytes_repeat(", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_bytes_concat(", llvm_ir)

    def test_emits_string_encode_as_bytes_runtime_call(self) -> None:
        module = lower_source_to_ir(
            "def encode(value: str) -> bytes:\n"
            "    return value.encode()\n",
            filename="string_encode.py",
            entry="encode",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_string_encode(ptr %value)", llvm_ir)

    def test_emits_bytes_for_each_as_length_aware_byte_load(self) -> None:
        module = lower_source_to_ir(
            "def total(data: bytes) -> int:\n"
            "    result = 0\n"
            "    for byte in data:\n"
            "        result += byte\n"
            "    return result\n",
            filename="bytes_for.py",
            entry="total",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_bytes_data(ptr %data)", llvm_ir)
        self.assertIn("call i64 @__xcc_aot_bytes_len(ptr %data)", llvm_ir)
        self.assertRegex(llvm_ir, r"%byteitem\d+ = load i8, ptr %byteitemptr\d+")
        self.assertRegex(llvm_ir, r"zext i8 %byteitem\d+ to i64")

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

    def test_emits_float_binary_subtraction(self) -> None:
        float_type = IrFloatType()
        module = IrModule(
            "float_sub.py",
            (),
            (
                IrFunction(
                    "neg",
                    (IrParam("value", float_type),),
                    float_type,
                    (
                        IrReturn(
                            IrBinary(
                                "-",
                                IrConstFloat(0.0),
                                IrName("value", float_type),
                                float_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("fsub double 0.0, %value", llvm_ir)
        self.assertNotIn("= sub double", llvm_ir)

    def test_emits_float_intrinsic_from_integer(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "float_builtin.py",
            (),
            (
                IrFunction(
                    "as_float",
                    (IrParam("value", int64),),
                    IrFloatType(),
                    (IrReturn(IrCall("__float", (IrName("value", int64),), IrFloatType())),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("sitofp i64 %value to double", llvm_ir)
        self.assertNotIn("@__float", llvm_ir)

    def test_emits_float_intrinsic_from_string(self) -> None:
        module = IrModule(
            "float_string.py",
            (),
            (
                IrFunction(
                    "parse",
                    (IrParam("value", IrStringType()),),
                    IrFloatType(),
                    (IrReturn(IrCall("__float", (IrName("value", IrStringType()),), IrFloatType())),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare double @strtod(ptr, ptr)", llvm_ir)
        self.assertIn("call double @strtod(ptr %value, ptr null)", llvm_ir)
        self.assertNotIn("@__float", llvm_ir)

    def test_emits_float_fromhex_intrinsic_with_strtod(self) -> None:
        module = IrModule(
            "float_fromhex.py",
            (),
            (
                IrFunction(
                    "parse",
                    (IrParam("value", IrStringType()),),
                    IrFloatType(),
                    (
                        IrReturn(
                            IrCall("__float_fromhex", (IrName("value", IrStringType()),), IrFloatType())
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare double @strtod(ptr, ptr)", llvm_ir)
        self.assertIn("call double @strtod(ptr %value, ptr null)", llvm_ir)
        self.assertNotIn("@__float_fromhex", llvm_ir)

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

    def test_emits_two_arg_integer_max_as_branch_phi(self) -> None:
        module = lower_source_to_ir(
            "int64 = int\n"
            "def choose(left: int64, right: int64) -> int64:\n"
            "    return max(left, right)\n",
            filename="max.py",
            entry="choose",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("icmp sge i64 %left, %right", llvm_ir)
        self.assertIn("br i1 %cmp", llvm_ir)
        self.assertIn("phi i64 [ %left, %ifexp.true", llvm_ir)
        self.assertIn("[ %right, %ifexp.false", llvm_ir)
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

        self.assertIn("getelementptr i8, ptr %value, i64 8", llvm_ir)
        self.assertRegex(llvm_ir, r"%object\.int\d+ = load i64")
        self.assertNotIn("ptrtoint ptr %value to i64", llvm_ir)
        self.assertIn("icmp sge i64", llvm_ir)
        self.assertIn("phi i64", llvm_ir)

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
                IrFunction(
                    "as_bytes",
                    (IrParam("value", IrRecordType("bytes | None")),),
                    IrBytesType(),
                    (IrReturn(IrName("value", IrBytesType())),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @as_string(ptr %value)", llvm_ir)
        self.assertIn("define ptr @as_tuple(ptr %value)", llvm_ir)
        self.assertIn("define ptr @as_bytes(ptr %value)", llvm_ir)
        self.assertIn("ret ptr %value", llvm_ir)

    def test_emits_ifexp_select_with_typed_false_arm(self) -> None:
        module = IrModule(
            "ifexp_select.py",
            (),
            (
                IrFunction(
                    "choose_string",
                    (
                        IrParam("flag", IrBoolType()),
                        IrParam("left", IrStringType()),
                        IrParam("right", IrStringType()),
                    ),
                    IrStringType(),
                    (
                        IrReturn(
                            IrCall(
                                "__ifexp",
                                (
                                    IrName("flag", IrBoolType()),
                                    IrName("left", IrStringType()),
                                    IrName("right", IrStringType()),
                                ),
                                IrStringType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("br i1 %flag, label %ifexp.true", llvm_ir)
        self.assertIn("phi ptr [ %left, %ifexp.true", llvm_ir)
        self.assertIn("[ %right, %ifexp.false", llvm_ir)

    def test_emits_ifexp_none_arm_as_default_for_integer_result(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "ifexp_none_int.py",
            (),
            (
                IrFunction(
                    "maybe",
                    (IrParam("flag", IrBoolType()),),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__ifexp",
                                (IrName("flag", IrBoolType()), IrConstNone(), IrConstInt(7, int64)),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("br i1 %flag, label %ifexp.true", llvm_ir)
        self.assertIn("phi i64 [ 0, %ifexp.true", llvm_ir)
        self.assertIn("[ 7, %ifexp.false", llvm_ir)
        self.assertNotIn("i64 null", llvm_ir)

    def test_emits_ifexp_tags_bool_arm_for_mixed_union_result(self) -> None:
        result_type = IrRecordType("list | bool")
        module = IrModule(
            "ifexp_bool_union.py",
            (),
            (
                IrFunction(
                    "choose",
                    (IrParam("flag", IrBoolType()), IrParam("values", result_type)),
                    result_type,
                    (
                        IrReturn(
                            IrCall(
                                "__ifexp",
                                (
                                    IrName("flag", IrBoolType()),
                                    IrName("values", result_type),
                                    IrConstBool(False),
                                ),
                                result_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("store i64 1, ptr %object", llvm_ir)
        self.assertIn("br i1 %flag, label %ifexp.true", llvm_ir)
        self.assertIn("phi ptr [ %values, %ifexp.true", llvm_ir)
        self.assertIn("[ %object", llvm_ir)

    def test_emits_none_ifexp_without_void_select(self) -> None:
        module = IrModule(
            "ifexp_none.py",
            (),
            (
                IrFunction(
                    "choose",
                    (IrParam("flag", IrBoolType()),),
                    IrNoneType(),
                    (
                        IrReturn(
                            IrCall(
                                "__ifexp",
                                (IrName("flag", IrBoolType()), IrConstNone(), IrConstNone()),
                                IrNoneType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("ret void", llvm_ir)
        self.assertNotIn("select i1 %flag, void", llvm_ir)

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

    def test_emits_ord_intrinsic_as_first_byte_load(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "ord.py",
            (),
            (
                IrFunction(
                    "codepoint",
                    (),
                    int64,
                    (IrReturn(IrCall("__ord", (IrConstString("A"),), int64)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("load i8, ptr @.str0", llvm_ir)
        self.assertIn("zext i8", llvm_ir)
        self.assertNotIn("@__ord", llvm_ir)

    def test_emits_chr_intrinsic_as_single_byte_string(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "chr.py",
            (),
            (
                IrFunction(
                    "decoded",
                    (),
                    IrStringType(),
                    (IrReturn(IrCall("__chr", (IrConstInt(65, int64),), IrStringType())),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_single_byte_string(i8", llvm_ir)
        self.assertNotIn("call ptr @__xcc_aot_alloc(i64 2)", llvm_ir)
        self.assertIn("trunc i64 65 to i8", llvm_ir)
        self.assertIn("store i8 0", llvm_ir)
        self.assertNotIn("@__chr", llvm_ir)

    def test_emits_string_getitem_as_single_byte_string(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "string_getitem.py",
            (),
            (
                IrFunction(
                    "pick",
                    (IrParam("text", IrStringType()), IrParam("index", int64)),
                    IrStringType(),
                    (
                        IrReturn(
                            IrCall(
                                "__getitem",
                                (IrName("text", IrStringType()), IrName("index", int64)),
                                IrStringType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("getelementptr i8, ptr %text, i64 %index", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_single_byte_string(i8", llvm_ir)
        self.assertNotIn("call ptr @__xcc_aot_alloc(i64 2)", llvm_ir)
        self.assertNotIn("@__getitem", llvm_ir)

    def test_emits_tuple_getitem_intrinsic(self) -> None:
        module = lower_source_to_ir(
            "def pick(argv: tuple[str, ...]) -> str:\n    return argv[2]\n",
            filename="tuple_getitem.py",
            entry="pick",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertRegex(
            llvm_ir,
            r"%call\d+ = call ptr @__xcc_aot_tuple_get\(ptr %argv, i64 2\)",
        )
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

    def test_emits_object_getitem_as_runtime_tuple_get(self) -> None:
        int64 = IrIntType(64, signed=True)
        object_type = IrRecordType("object")
        module = IrModule(
            "object_getitem.py",
            (),
            (
                IrFunction(
                    "truthy_first",
                    (IrParam("value", object_type),),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "__getitem",
                                (IrName("value", object_type), IrConstInt(0, int64)),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %value, i64 0)", llvm_ir)
        self.assertIn("icmp ne ptr", llvm_ir)
        self.assertNotIn("@__getitem", llvm_ir)

    def test_boxed_typed_tuple_registers_layout_for_generic_object_reads(self) -> None:
        module = lower_source_to_ir(
            "class Node:\n"
            "    pass\n"
            "def accepts(values: object) -> bool:\n"
            "    if isinstance(values, tuple):\n"
            "        for item in values:\n"
            "            if isinstance(item, Node):\n"
            "                return True\n"
            "    return False\n"
            "def entry() -> int:\n"
            "    values: tuple[Node, ...] = (Node(),)\n"
            "    return 7 if accepts(values) else 1\n",
            filename="boxed-typed-tuple-layout.py",
            entry="entry",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("@__xcc_aot_tuple_object_layout_8", llvm_ir)
        self.assertIn("call void @__xcc_aot_tuple_object_layout_register", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get_object", llvm_ir)

    def test_mutated_typed_tuple_forwards_layout_for_union_parameter_reads(self) -> None:
        module = lower_source_to_ir(
            "class Node:\n"
            "    pass\n"
            "def accepts(\n"
            "    values: tuple[Node, ...] | tuple[tuple[str, int], ...],\n"
            ") -> bool:\n"
            "    for item in values:\n"
            "        if isinstance(item, Node):\n"
            "            return True\n"
            "    return False\n"
            "def entry() -> int:\n"
            "    values: list[Node] = []\n"
            "    values.append(Node())\n"
            "    return 7 if accepts(tuple(values)) else 1\n",
            filename="union-typed-tuple-layout.py",
            entry="entry",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("@__xcc_aot_tuple_object_layout_8", llvm_ir)
        self.assertIn("call void @__xcc_aot_tuple_object_layout_register", llvm_ir)
        self.assertIn("call void @__xcc_aot_tuple_object_layout_forward", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get_object", llvm_ir)

    def test_emits_tuple_alias_narrowing_from_record_union_getitem(self) -> None:
        int64 = IrIntType(64, signed=True)
        function_declarator = IrTupleType((IrTupleType((IrRecordType("TypeSpec"),)), IrBoolType()))
        module = IrModule(
            "tuple_alias_getitem.py",
            (),
            (
                IrFunction(
                    "is_variadic",
                    (IrParam("value", IrRecordType("int | ArrayDecl | FunctionDeclarator")),),
                    IrBoolType(),
                    (
                        IrAssign("function_declarator", IrName("value", function_declarator)),
                        IrReturn(
                            IrCall(
                                "__getitem",
                                (
                                    IrName("function_declarator", function_declarator),
                                    IrConstInt(1, int64),
                                ),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("getelementptr i8, ptr %value, i64 8", llvm_ir)
        self.assertRegex(
            llvm_ir,
            r"call ptr @__xcc_aot_tuple_get\(ptr %object\.pointer\d+, i64 1\)",
        )

    def test_mixed_scalar_record_union_uses_tagged_object_abi(self) -> None:
        module = lower_source_to_ir(
            "class Box:\n"
            "    def __init__(self, value: int) -> None:\n"
            "        self.value = value\n"
            "Value = int | Box | tuple[int, bool]\n"
            "def wrap(value: Value) -> tuple[str, object]:\n"
            "    return 'value', value\n"
            "def entry() -> int:\n"
            "    packed = wrap(128)\n"
            "    value = packed[1]\n"
            "    if isinstance(value, int):\n"
            "        return value\n"
            "    return 0\n",
            filename="mixed-union-object-abi.py",
            entry="entry",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(llvm_ir, r"store i64 2, ptr %object\d+")
        self.assertRegex(llvm_ir, r"call ptr @wrap\(ptr %object\d+\)")
        self.assertIn("%object.isinstance.builtin", llvm_ir)
        self.assertIn("icmp ne ptr", llvm_ir)
        self.assertNotIn("@__getitem", llvm_ir)

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

        self.assertIn("getelementptr i8, ptr %index, i64 8", llvm_ir)
        self.assertRegex(llvm_ir, r"%index\d+ = load i64, ptr %index\.payload\d+")
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

    def test_emits_tuple_truthiness_from_length(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((int64,))
        module = IrModule(
            "tuple_truth.py",
            (),
            (
                IrFunction(
                    "check",
                    (IrParam("stack", tuple_type),),
                    int64,
                    (
                        IrIf(
                            IrName("stack", tuple_type),
                            IrBranch((IrReturn(IrConstInt(1, int64)),)),
                        ),
                        IrReturn(IrConstInt(0, int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i64 @__xcc_aot_tuple_len(ptr %stack)", llvm_ir)
        self.assertIn("icmp ne i64 %tuplelen", llvm_ir)
        self.assertNotIn("icmp ne ptr %stack, null", llvm_ir)

    def test_emits_string_truthiness_from_length(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "string_truth.py",
            (),
            (
                IrFunction(
                    "check",
                    (IrParam("text", IrStringType()),),
                    int64,
                    (
                        IrIf(
                            IrName("text", IrStringType()),
                            IrBranch((IrReturn(IrConstInt(1, int64)),)),
                        ),
                        IrReturn(IrConstInt(0, int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i64 @strlen(ptr %text)", llvm_ir)
        self.assertIn("icmp ne i64 %strlen", llvm_ir)
        self.assertNotIn("icmp ne ptr %text, null", llvm_ir)

    def test_emits_preprocessor_pragma_operator_leaf_as_passthrough(self) -> None:
        module = IrModule(
            "pragma_passthrough.py",
            (),
            (
                IrFunction(
                    "xcc.preprocessor.__init__._Preprocessor._handle_pragma_operator",
                    (
                        IrParam("self", IrRecordType("_Preprocessor")),
                        IrParam("text", IrStringType()),
                    ),
                    IrStringType(),
                    (),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn(
            "define ptr @xcc.preprocessor.__init__._Preprocessor._handle_pragma_operator",
            llvm_ir,
        )
        self.assertIn("ret ptr %text", llvm_ir)
        self.assertNotIn("ret ptr null", llvm_ir)

    def test_emits_preprocessor_expand_line_leaf_as_passthrough(self) -> None:
        module = IrModule(
            "expand_line_passthrough.py",
            (),
            (
                IrFunction(
                    "xcc.preprocessor.__init__._Preprocessor._expand_line",
                    (
                        IrParam("self", IrRecordType("_Preprocessor")),
                        IrParam("line", IrStringType()),
                        IrParam("location", IrRecordType("_SourceLocation")),
                    ),
                    IrStringType(),
                    (),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @xcc.preprocessor.__init__._Preprocessor._expand_line", llvm_ir)
        self.assertIn("ret ptr %line", llvm_ir)
        self.assertNotIn("ret ptr null", llvm_ir)

    def test_emits_preprocessor_macro_continuation_leaf_as_false(self) -> None:
        module = IrModule(
            "macro_continuation_false.py",
            (),
            (
                IrFunction(
                    (
                        "xcc.preprocessor.__init__._Preprocessor."
                        "_should_collect_function_macro_continuation"
                    ),
                    (
                        IrParam("self", IrRecordType("_Preprocessor")),
                        IrParam("text", IrStringType()),
                        IrParam("next_line", IrStringType()),
                    ),
                    IrBoolType(),
                    (),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("_should_collect_function_macro_continuation", llvm_ir)
        self.assertIn("ret i1 false", llvm_ir)

    def test_emits_bool_and_with_short_circuit_blocks(self) -> None:
        module = lower_source_to_ir(
            "def guarded(values: tuple[str, ...]) -> bool:\n"
            "    index = 0\n"
            "    return index < len(values) and values[index] == 'x'\n",
            filename="bool_and_short_circuit.py",
            entry="guarded",
        )

        llvm_ir = emit_llvm_text(module)
        function_start = llvm_ir.index("define i1 @guarded")
        function_end = llvm_ir.index("\n}", function_start)
        function_ir = llvm_ir[function_start:function_end]

        next_pos = function_ir.find("bool.and.next")
        getitem_pos = function_ir.find("call ptr @__xcc_aot_tuple_get")
        self.assertGreater(next_pos, -1)
        self.assertGreater(getitem_pos, -1)
        self.assertLess(next_pos, getitem_pos)
        self.assertIn("bool.and.end", function_ir)
        self.assertIn("phi i1", function_ir)

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
        self.assertRegex(llvm_ir, r"call i64 @Pair\.total\(ptr %pair\d+\)")

    def test_emits_explicit_none_record_field_default_as_null(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class Box:\n"
            "    values: tuple[str, ...] | None = None\n"
            "def make() -> Box:\n"
            "    return Box()\n"
        )

        llvm_ir = emit_llvm_text(
            lower_source_to_ir(source, filename="record_none_field.py")
        )

        self.assertIn("%Box = type { ptr }", llvm_ir)
        self.assertRegex(llvm_ir, r"store ptr null, ptr %fieldptr\d+")

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
        self.assertRegex(
            llvm_ir,
            r"%box\.raw\d+ = call ptr @__xcc_aot_alloc\(i64 16\)",
        )
        self.assertRegex(llvm_ir, r"store i64 1, ptr %box\.raw\d+")
        self.assertRegex(
            llvm_ir,
            r"%box\d+ = getelementptr i8, ptr %box\.raw\d+, i64 8",
        )
        self.assertIn("\\22\\5C\\0A\\00", llvm_ir)

    def test_record_constructor_assignment_uses_unique_heap_names(self) -> None:
        int64 = IrIntType(64, signed=True)
        record_type = IrRecordType("Box")
        module = IrModule(
            "record_reassign.py",
            (IrRecord("Box", (IrField("value", int64),)),),
            (
                IrFunction(
                    "replace",
                    (),
                    int64,
                    (
                        IrAssign(
                            "box",
                            IrConstructRecord("Box", (IrConstInt(1, int64),), record_type),
                        ),
                        IrAssign(
                            "box",
                            IrConstructRecord("Box", (IrConstInt(2, int64),), record_type),
                        ),
                        IrReturn(IrGetField(IrName("box", record_type), "value", int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        heap_names = [
            line.split(" =", 1)[0].strip()
            for line in llvm_ir.splitlines()
            if "%box.raw" in line and "call ptr @__xcc_aot_alloc(i64 16)" in line
        ]
        self.assertEqual(len(heap_names), 2)
        self.assertEqual(len(set(heap_names)), 2)
        self.assertNotIn("\n  %box = call ptr @__xcc_aot_alloc", llvm_ir)

    def test_emits_record_field_assignment_store(self) -> None:
        int64 = IrIntType(64, signed=True)
        record_type = IrRecordType("Box")
        module = IrModule(
            "record_field_store.py",
            (IrRecord("Box", (IrField("value", int64),)),),
            (
                IrFunction(
                    "replace",
                    (IrParam("box", record_type),),
                    int64,
                    (
                        IrAssign("box.value", IrConstInt(3, int64)),
                        IrReturn(IrGetField(IrName("box", record_type), "value", int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("getelementptr inbounds %Box, ptr %box, i32 0, i32 0", llvm_ir)
        self.assertIn("store i64 3, ptr %fieldptr", llvm_ir)

    def test_emits_protocol_record_field_access_with_concrete_layout(self) -> None:
        int64 = IrIntType(64, signed=True)
        protocol_type = IrRecordType("_StatementParser")
        module = IrModule(
            "statement_parser_protocol_field.py",
            (
                IrRecord("Parser", (IrField("tokens", IrTupleType(())), IrField("_index", int64))),
                IrRecord("_StatementParser", (IrField("_index", int64),)),
            ),
            (
                IrFunction(
                    "rewind",
                    (IrParam("parser", protocol_type),),
                    int64,
                    (
                        IrAssign("parser._index", IrConstInt(0, int64)),
                        IrReturn(IrGetField(IrName("parser", protocol_type), "_index", int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("getelementptr inbounds %Parser, ptr %parser, i32 0, i32 1", llvm_ir)
        self.assertNotIn("getelementptr inbounds %_StatementParser", llvm_ir)

    def test_emits_tuple_backed_record_field_assignment_store(self) -> None:
        int64 = IrIntType(64, signed=True)
        string_tuple = IrTupleType((IrStringType(),))
        record_type = IrRecordType("Builder")
        module = IrModule(
            "record_tuple_field_store.py",
            (IrRecord("Builder", (IrField("chunks", string_tuple),)),),
            (
                IrFunction(
                    "append",
                    (IrParam("builder", record_type),),
                    int64,
                    (
                        IrAssign(
                            "builder.chunks",
                            IrCall(
                                "__tuple_concat",
                                (
                                    IrGetField(
                                        IrName("builder", record_type),
                                        "chunks",
                                        string_tuple,
                                    ),
                                    IrTuple((IrConstString("x"),), string_tuple),
                                ),
                                string_tuple,
                            ),
                        ),
                        IrReturn(
                            IrCall(
                                "len",
                                (
                                    IrGetField(
                                        IrName("builder", record_type),
                                        "chunks",
                                        string_tuple,
                                    ),
                                ),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("getelementptr inbounds %Builder, ptr %builder, i32 0, i32 0", llvm_ir)
        self.assertRegex(llvm_ir, r"store ptr %tupleconcat\d+, ptr %fieldptr\d+")

    def test_record_constructor_stores_none_as_field_default(self) -> None:
        int64 = IrIntType(64, signed=True)
        record_type = IrRecordType("Box")
        module = IrModule(
            "record_none_default.py",
            (IrRecord("Box", (IrField("count", int64),)),),
            (
                IrFunction(
                    "box",
                    (),
                    record_type,
                    (IrReturn(IrConstructRecord("Box", (IrConstNone(),), record_type)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("store i64 0", llvm_ir)
        self.assertNotIn("store i64 null", llvm_ir)

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

    def test_emits_none_return_as_default_for_integer_return_type(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "none_integer_return.py",
            (),
            (IrFunction("maybe", (), int64, (IrReturn(IrConstNone()),)),),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("ret i64 0", llvm_ir)
        self.assertNotIn("ret i64 null", llvm_ir)

    def test_emits_integer_return_tagged_for_mixed_union_return_type(self) -> None:
        int64 = IrIntType(64, signed=True)
        result_type = IrRecordType("int | Box")
        module = IrModule(
            "boxed_union_return.py",
            (),
            (
                IrFunction(
                    "value",
                    (),
                    result_type,
                    (IrReturn(IrConstInt(7, int64)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("store i64 2, ptr %object", llvm_ir)
        self.assertIn("store i64 7, ptr %object.payload", llvm_ir)
        self.assertNotIn("inttoptr i64 7 to ptr", llvm_ir)

    def test_emits_string_repeat_intrinsic(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "string_repeat.py",
            (),
            (
                IrFunction(
                    "repeat",
                    (IrParam("count", int64),),
                    IrStringType(),
                    (
                        IrReturn(
                            IrCall(
                                "__str_repeat",
                                (IrConstString("x"), IrName("count", int64)),
                                IrStringType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @__xcc_aot_string_repeat", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_string_repeat(ptr @.str0, i64 %count)", llvm_ir)

    def test_emits_tuple_concat_and_repeat_intrinsics(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((int64,))
        module = IrModule(
            "tuple_repeat.py",
            (),
            (
                IrFunction(
                    "pad",
                    (IrParam("values", tuple_type), IrParam("count", int64)),
                    tuple_type,
                    (
                        IrReturn(
                            IrCall(
                                "__tuple_concat",
                                (
                                    IrName("values", tuple_type),
                                    IrCall(
                                        "__tuple_repeat",
                                        (
                                            IrTuple((IrConstInt(0, int64),), tuple_type),
                                            IrName("count", int64),
                                        ),
                                        tuple_type,
                                    ),
                                ),
                                tuple_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @__xcc_aot_tuple_concat", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_tuple_repeat", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_repeat", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_concat", llvm_ir)

    def test_v387_unique_tuple_rebind_uses_owned_append(self) -> None:
        module = lower_source_to_ir(
            "def grow(count: int) -> int:\n"
            "    values: tuple[int, ...] = ()\n"
            "    for value in range(count):\n"
            "        values = (*values, value)\n"
            "    return len(values)\n",
            filename="v387_unique_tuple_rebind.py",
            entry="grow",
        )

        llvm_ir = emit_llvm_text(module)
        grow_ir = llvm_ir.split("define i64 @grow", 1)[1].split("\ndefine ", 1)[0]

        self.assertIn("call ptr @__xcc_aot_tuple_append(ptr %", grow_ir)
        self.assertNotIn("call ptr @__xcc_aot_tuple_concat(", grow_ir)

    def test_v387_aliased_tuple_rebind_preserves_copy_semantics(self) -> None:
        module = lower_source_to_ir(
            "def grow(value: int) -> int:\n"
            "    values: tuple[int, ...] = ()\n"
            "    alias = values\n"
            "    values = (*values, value)\n"
            "    return len(alias) * 10 + len(values)\n",
            filename="v387_aliased_tuple_rebind.py",
            entry="grow",
        )

        llvm_ir = emit_llvm_text(module)
        grow_ir = llvm_ir.split("define i64 @grow", 1)[1].split("\ndefine ", 1)[0]

        self.assertIn("call ptr @__xcc_aot_tuple_concat(", grow_ir)

    def test_emits_if_assignment_phi_for_existing_local(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "if_phi.py",
            (),
            (
                IrFunction(
                    "choose",
                    (IrParam("use_replacement", IrBoolType()), IrParam("replacement", int64)),
                    int64,
                    (
                        IrAssign("value", IrConstInt(7, int64)),
                        IrIf(
                            IrName("use_replacement", IrBoolType()),
                            IrBranch((IrAssign("value", IrName("replacement", int64)),)),
                        ),
                        IrReturn(IrName("value", int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("phi i64", llvm_ir)
        self.assertRegex(llvm_ir, r"\[ 7, %entry \]")
        self.assertRegex(llvm_ir, r"\[ %replacement, %if\.then\d+ \]")

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

    def test_emits_while_phi_for_none_initialized_pointer_local(self) -> None:
        string_type = IrStringType()
        module = IrModule(
            "while_optional_pointer.py",
            (),
            (
                IrFunction(
                    "resolve",
                    (),
                    string_type,
                    (
                        IrAssign("expanded", IrConstNone()),
                        IrWhile(
                            IrCall(
                                "__cmp_Is",
                                (IrName("expanded", IrNoneType()), IrConstNone()),
                                IrBoolType(),
                            ),
                            IrBranch((IrAssign("expanded", IrConstString("done")),)),
                        ),
                        IrReturn(IrName("expanded", string_type)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(
            llvm_ir,
            r"%loop\d+ = phi ptr \[ null, %entry \], \[ @\.str\d+, %while\.body\d+ \]",
        )
        self.assertNotIn("icmp eq ptr null, null", llvm_ir)

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
        self.assertIn("while.end", llvm_ir)

    def test_break_exit_phi_preserves_current_loop_carried_values(self) -> None:
        module = lower_source_to_ir(
            "def collect() -> int:\n"
            "    values: list[int] = []\n"
            "    while True:\n"
            "        values.append(7)\n"
            "        break\n"
            "    more: list[int] = []\n"
            "    for value in (8, 9):\n"
            "        more.append(value)\n"
            "        break\n"
            "    return len(values) + len(more)\n",
            filename="break_carried.py",
            entry="collect",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(
            llvm_ir,
            r"%loopexit\d+ = phi ptr \[ %loop\d+, %while\.cond\d+ \], "
            r"\[ %loop\d+, %while\.body\d+ \]",
        )
        self.assertRegex(
            llvm_ir,
            r"%loopexit\d+ = phi ptr \[ %loop\d+, %for\.cond\d+ \], "
            r"\[ %loop\d+, %for\.body\d+ \]",
        )

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

    def test_emits_for_each_loop_carried_assignment_phi(self) -> None:
        module = lower_source_to_ir(
            "def count(values: tuple[int, ...]) -> int:\n"
            "    out: list[int] = []\n"
            "    for value in values:\n"
            "        out.append(value)\n"
            "    return len(out)\n",
            filename="for_carried.py",
            entry="count",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(
            llvm_ir,
            r"%loop(\d+) = phi ptr \[ %tuple\d+, %entry \], "
            r"\[ %loop\1, %for\.next\d+ \]",
        )
        self.assertRegex(llvm_ir, r"call i64 @__xcc_aot_tuple_len\(ptr %loop\d+\)")

    def test_emits_optional_integer_for_loop_phi_for_zero_iterations(self) -> None:
        module = lower_source_to_ir(
            "def last(values: tuple[int, ...]) -> int:\n"
            "    selected = None\n"
            "    for value in values:\n"
            "        selected = value\n"
            "    if selected is None:\n"
            "        return 9\n"
            "    return selected\n",
            filename="optional-int-for-loop.py",
            entry="last",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(
            llvm_ir,
            r"%loop\d+ = phi ptr \[ null, %entry \], \[ %object\d+, %for\.next\d+ \]",
        )
        self.assertRegex(llvm_ir, r"%optional\.int\.payload\d+ = getelementptr i8")

    def test_coerces_optional_integer_to_nullable_llvm_pointer(self) -> None:
        emitter = _Emitter(IrModule("optional-pointer.py", (), ()))
        lines: list[str] = []

        pointer = emitter._coerce_llvm_pointer(
            _EmittedValue("%optional", IrRecordType("int | None")),
            lines,
        )

        self.assertRegex("\n".join(lines), r"icmp ne ptr %optional, null")
        self.assertRegex("\n".join(lines), r"load i64, ptr %optional\.int\.payload\d+")
        self.assertRegex("\n".join(lines), r"inttoptr i64 %optional\.int\d+ to ptr")
        self.assertRegex("\n".join(lines), rf"{pointer} = phi ptr")

    def test_boxes_optional_integer_on_break_exit_edge(self) -> None:
        module = lower_source_to_ir(
            "def find() -> int:\n"
            "    found = None\n"
            "    for index in range(5):\n"
            "        if index == 3:\n"
            "            found = index\n"
            "            break\n"
            "    if found is None:\n"
            "        return 9\n"
            "    return found\n",
            filename="optional-int-break-exit.py",
            entry="find",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(
            llvm_ir,
            r"%loopexit\d+ = phi ptr \[ %loop\d+, %for\.cond\d+ \], "
            r"\[ %object\d+, %if\.then\d+ \]",
        )
        self.assertRegex(
            llvm_ir,
            r"store i64 %[\w.]+, ptr %object\.payload\d+\n  br label %for\.end\d+",
        )

    def test_compares_optional_integer_payload_to_concrete_zero(self) -> None:
        module = lower_source_to_ir(
            "def maybe(value: int, present: bool) -> int | None:\n"
            "    if present:\n"
            "        return value\n"
            "    return None\n"
            "def is_zero(value: int | None) -> bool:\n"
            "    return value == 0\n",
            filename="optional-int-equality.py",
            entry="is_zero",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(llvm_ir, r"%optional\.int\.eq\.left\.present\d+ = icmp ne ptr")
        self.assertRegex(llvm_ir, r"%optional\.int\.eq\.left\d+ = load i64")
        self.assertNotRegex(llvm_ir, r"ptrtoint ptr %value to i64")

    def test_compares_flow_narrowed_bool_identity_to_none_by_tag(self) -> None:
        module = lower_source_to_ir(
            "def classify(flag: bool) -> int:\n"
            "    value: bool | None = None\n"
            "    while flag:\n"
            "        if value is None:\n"
            "            value = False\n"
            "        if value is None:\n"
            "            return 1\n"
            "        return 7\n"
            "    return 0\n",
            filename="optional-bool-identity.py",
            entry="classify",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(
            llvm_ir,
            r"%optional\.bool\.tag\d+ = add i64 %optional\.bool\d+, 1",
        )
        self.assertRegex(
            llvm_ir,
            r"%is\d+ = icmp eq i64 %optional\.bool\.tag\d+, 0",
        )

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

        self.assertIn("call ptr @__xcc_aot_tuple_get_object(ptr %item", llvm_ir)
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

        self.assertIn("call ptr @__xcc_aot_tuple_get_object(ptr %item", llvm_ir)
        self.assertIn("getelementptr i8, ptr %itemslot", llvm_ir)
        self.assertIn("load i64, ptr %object.payload", llvm_ir)

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

    def test_for_each_unboxes_homogeneous_integer_element_type(self) -> None:
        int64 = IrIntType(64, signed=True)
        units_type = IrTupleType((int64,))
        module = IrModule(
            "for_integer_item.py",
            (),
            (
                IrFunction(
                    "first_byte",
                    (IrParam("units", units_type),),
                    int64,
                    (
                        IrForEach(
                            "unit",
                            IrName("units", units_type),
                            IrBranch(
                                (
                                    IrReturn(
                                        IrBinary(
                                            "&",
                                            IrName("unit", int64),
                                            IrConstInt(255, int64),
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

        self.assertIn("ptrtoint ptr %item", llvm_ir)
        self.assertIn("and i64 %narrowint", llvm_ir)

    def test_for_each_over_string_uses_cached_one_character_strings(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "string_for_each.py",
            (),
            (
                IrFunction(
                    "fold",
                    (IrParam("data", IrStringType()),),
                    int64,
                    (
                        IrAssign("raw", IrConstInt(0, int64)),
                        IrForEach(
                            "character",
                            IrName("data", IrStringType()),
                            IrBranch(
                                (
                                    IrAssign(
                                        "raw",
                                        IrBinary(
                                            "|",
                                            IrName("raw", int64),
                                            IrBinary(
                                                "<<",
                                                IrCall(
                                                    "__ord",
                                                    (IrName("character", IrStringType()),),
                                                    int64,
                                                ),
                                                IrConstInt(0, int64),
                                                int64,
                                            ),
                                            int64,
                                        ),
                                    ),
                                )
                            ),
                        ),
                        IrReturn(IrName("raw", int64)),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i64 @strlen(ptr %data)", llvm_ir)
        self.assertIn("getelementptr i8, ptr %data", llvm_ir)
        self.assertIn("load i8, ptr", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_single_byte_string(i8", llvm_ir)
        self.assertNotIn("call ptr @__xcc_aot_alloc(i64 2)", llvm_ir)
        self.assertIn("store i8", llvm_ir)
        self.assertIn("zext i8", llvm_ir)
        self.assertIn("shl i64", llvm_ir)
        self.assertNotIn("@__xcc_aot_tuple_get(ptr %data", llvm_ir)

    def test_enumerate_unboxes_homogeneous_integer_element_type(self) -> None:
        int64 = IrIntType(64, signed=True)
        units_type = IrTupleType((int64,))
        module = IrModule(
            "enumerate_integer_item.py",
            (),
            (
                IrFunction(
                    "first_sum",
                    (IrParam("units", units_type),),
                    int64,
                    (
                        IrForEach(
                            "(index, unit)",
                            IrCall(
                                "__enumerate",
                                (IrName("units", units_type),),
                                IrTupleType((int64, int64)),
                            ),
                            IrBranch(
                                (
                                    IrReturn(
                                        IrBinary(
                                            "+",
                                            IrName("index", int64),
                                            IrName("unit", int64),
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

        self.assertIn("ptrtoint ptr %item", llvm_ir)
        self.assertIn("add i64 %index", llvm_ir)
        self.assertIn("%narrowint", llvm_ir)

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

        self.assertIn("call ptr @__xcc_aot_tuple_get_object(ptr %op, i64 1)", llvm_ir)
        self.assertIn("getelementptr i8, ptr %itemslot", llvm_ir)
        self.assertIn("load i64, ptr %object.payload", llvm_ir)

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

        self.assertIn("call ptr @__xcc_aot_tuple_get_object(ptr %packed, i64 0)", llvm_ir)
        self.assertNotIn("call ptr @__xcc_aot_tuple_get_object(ptr %packed, i64 1)", llvm_ir)

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

        self.assertIn("icmp ne ptr %symbol, null", llvm_ir)
        self.assertNotIn("@isinstance", llvm_ir)

    def test_emits_record_isinstance_as_type_tag_check(self) -> None:
        module = IrModule(
            "record_isinstance.py",
            (
                IrRecord("Stmt", ()),
                IrRecord("DeclStmt", (), ("Stmt",)),
                IrRecord("ReturnStmt", (IrField("value", IrRecordType("object")),), ("Stmt",)),
            ),
            (
                IrFunction(
                    "check",
                    (IrParam("stmt", IrRecordType("object")),),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "isinstance",
                                (
                                    IrName("stmt", IrRecordType("object")),
                                    IrName("ReturnStmt", IrBoolType()),
                                ),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(llvm_ir, r"%object\.tag\d+ = load i64, ptr %stmt")
        self.assertRegex(llvm_ir, r"icmp eq i64 %object\.tag\d+, 8")
        self.assertRegex(
            llvm_ir,
            r"getelementptr i8, ptr %object\.record\d+, i64 -8",
        )
        self.assertRegex(llvm_ir, r"icmp eq i64 %object\.record\.tag\d+, 2")

    def test_emits_type_constant_name_as_global_singleton(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((IrRecordType("object"),))
        type_record = IrRecord(
            "Type",
            (
                IrField("name", IrStringType()),
                IrField("pointer_depth", int64),
                IrField("array_lengths", tuple_type),
                IrField("declarator_ops", tuple_type),
                IrField("qualifiers", tuple_type),
            ),
        )
        type_type = IrRecordType("Type")
        module = IrModule(
            "type_constant.py",
            (type_record,),
            (
                IrFunction(
                    "get",
                    (),
                    type_type,
                    (IrReturn(IrName("INT", type_type)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("@__xcc_aot_type_INT = private global { i64, %Type }", llvm_ir)
        self.assertIn('c"int\\00"', llvm_ir)
        self.assertIn("getelementptr inbounds { i64, %Type }, ptr @__xcc_aot_type_INT", llvm_ir)
        self.assertNotIn("ret ptr null", llvm_ir)

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
        self.assertRegex(llvm_ir, r"ret i64 %narrowint\d+")
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
        self.assertRegex(skipped_ir, r"ret i64 %narrowint\d+")

        started_item = lower_source_to_ir(
            "def first_index(names: list[str]) -> int:\n"
            "    for index, name in enumerate(names, start=1):\n"
            "        return index\n"
            "    return 0\n",
            filename="enumerate_start.py",
        )
        started_ir = emit_llvm_text(started_item)
        self.assertRegex(started_ir, r"%enumindex\d+ = add i64 %index\d+, 1")
        self.assertRegex(
            started_ir,
            r"call ptr @__xcc_aot_tuple_get\(ptr %names, i64 %index\d+\)",
        )

    def test_emits_enumerate_nested_target_via_temp_pair(self) -> None:
        module = lower_source_to_ir(
            "def first(values: list[tuple[str, int]]) -> int:\n"
            "    for index, (name, value) in enumerate(values, start=1):\n"
            "        return value\n"
            "    return 0\n",
            filename="enumerate_nested.py",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("; build enumerate pair", llvm_ir)
        self.assertRegex(
            llvm_ir,
            r"%enumpair\d+ = call ptr @__xcc_aot_tuple_new\(i64 2\)",
        )
        self.assertRegex(llvm_ir, r"%enumindex\d+ = add i64 %index\d+, 1")

    def test_emits_subscript_assignment_via_tuple_set(self) -> None:
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
        self.assertIn(
            "call void @__xcc_aot_tuple_set(ptr %values, i64 %index, ptr %item)",
            llvm_ir,
        )

    def test_emits_nested_dict_assignment_without_pointer_indexing_key(self) -> None:
        module = lower_source_to_ir(
            "def store(stack: list[dict[str, int]], name: str, item: int) -> None:\n"
            "    stack[-1][name] = item\n",
            filename="nested_dict_assign.py",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_concat", llvm_ir)
        self.assertIn("call void @__xcc_aot_tuple_set", llvm_ir)
        self.assertNotIn("ptrtoint ptr %name to i64", llvm_ir)

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

    def test_v399_startswith_string_concat_borrows_parts(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "startswith_concat.py",
            (),
            (
                IrFunction(
                    "check",
                    (IrParam("text", IrStringType()), IrParam("name", IrStringType())),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "__str_startswith",
                                (
                                    IrName("text", IrStringType()),
                                    IrStringConcat(
                                        (IrName("name", IrStringType()), IrConstString("."))
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
        start = llvm_ir.index("define i1 @check")
        end = llvm_ir.index("\n}", start)
        function_ir = llvm_ir[start:end]

        self.assertEqual(function_ir.count("call i1 @__xcc_aot_string_startswith"), 2)
        self.assertNotIn("call ptr @__xcc_aot_string_concat2", function_ir)

    def test_v399_single_use_concat_assignment_is_forwarded_to_startswith(self) -> None:
        int64 = IrIntType(64, signed=True)
        concat = IrStringConcat((IrName("name", IrStringType()), IrConstString(".")))
        module = IrModule(
            "startswith_concat_assignment.py",
            (),
            (
                IrFunction(
                    "check",
                    (IrParam("text", IrStringType()), IrParam("name", IrStringType())),
                    IrBoolType(),
                    (
                        IrAssign("prefix", concat),
                        IrReturn(
                            IrCall(
                                "__str_startswith",
                                (
                                    IrName("text", IrStringType()),
                                    IrName("prefix", IrStringType()),
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
        start = llvm_ir.index("define i1 @check")
        end = llvm_ir.index("\n}", start)
        function_ir = llvm_ir[start:end]

        self.assertEqual(function_ir.count("call i1 @__xcc_aot_string_startswith"), 2)
        self.assertNotIn("call ptr @__xcc_aot_string_concat2", function_ir)

    def test_v400_keeps_cross_statement_multi_use_concat_materialized(self) -> None:
        int64 = IrIntType(64, signed=True)
        concat = IrStringConcat((IrName("name", IrStringType()), IrConstString(".")))
        startswith = IrCall(
            "__str_startswith",
            (
                IrName("text", IrStringType()),
                IrName("prefix", IrStringType()),
                IrConstInt(0, int64),
            ),
            IrBoolType(),
        )
        module = IrModule(
            "startswith_concat_multi_use.py",
            (),
            (
                IrFunction(
                    "check",
                    (IrParam("text", IrStringType()), IrParam("name", IrStringType())),
                    IrBoolType(),
                    (
                        IrAssign("prefix", concat),
                        IrAssign("__expr", startswith),
                        IrReturn(startswith),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)
        start = llvm_ir.index("define i1 @check")
        end = llvm_ir.index("\n}", start)
        function_ir = llvm_ir[start:end]

        self.assertEqual(function_ir.count("call ptr @__xcc_aot_string_concat2"), 1)
        self.assertEqual(function_ir.count("call i1 @__xcc_aot_string_startswith"), 2)

    def test_v400_borrows_concat_for_startswith_and_nested_len(self) -> None:
        int64 = IrIntType(64, signed=True)
        concat = IrStringConcat((IrName("name", IrStringType()), IrConstString(".")))
        module = IrModule(
            "startswith_concat_len.py",
            (),
            (
                IrFunction(
                    "check",
                    (IrParam("text", IrStringType()), IrParam("name", IrStringType())),
                    int64,
                    (
                        IrAssign("prefix", concat),
                        IrIf(
                            IrCall(
                                "__str_startswith",
                                (
                                    IrName("text", IrStringType()),
                                    IrName("prefix", IrStringType()),
                                    IrConstInt(0, int64),
                                ),
                                IrBoolType(),
                            ),
                            IrBranch(
                                (
                                    IrReturn(
                                        IrCall(
                                            "len",
                                            (IrName("prefix", IrStringType()),),
                                            int64,
                                        )
                                    ),
                                )
                            ),
                            IrBranch((IrReturn(IrConstInt(0, int64)),)),
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)
        start = llvm_ir.index("define i64 @check")
        end = llvm_ir.index("\n}", start)
        function_ir = llvm_ir[start:end]

        self.assertEqual(function_ir.count("call i1 @__xcc_aot_string_startswith"), 2)
        self.assertEqual(function_ir.count("call i64 @strlen"), 3)
        self.assertNotIn("call ptr @__xcc_aot_string_concat2", function_ir)

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

    def test_emits_string_split_intrinsic_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((IrStringType(),))
        module = IrModule(
            "split.py",
            (),
            (
                IrFunction(
                    "split",
                    (),
                    tuple_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_split",
                                (IrConstString("a.b"), IrConstString(".")),
                                tuple_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "split_whitespace",
                    (),
                    tuple_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_split_whitespace",
                                (IrConstString("a b  c"), IrConstInt(1, int64)),
                                tuple_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "split_limit",
                    (),
                    tuple_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_split_limit",
                                (
                                    IrConstString("a//b//c"),
                                    IrConstString("//"),
                                    IrConstInt(1, int64),
                                ),
                                tuple_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @__xcc_aot_string_split", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_string_split_limit", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_string_split_whitespace", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_string_split(ptr @.str0, ptr @.str1)", llvm_ir)
        self.assertIn(
            "call ptr @__xcc_aot_string_split_whitespace(ptr @.str2, i64 1)",
            llvm_ir,
        )
        self.assertIn(
            "call ptr @__xcc_aot_string_split_limit(ptr @.str3, ptr @.str4, i64 1)",
            llvm_ir,
        )
        self.assertNotIn("@__str_split", llvm_ir)

    def test_emits_string_splitlines_intrinsic_call(self) -> None:
        tuple_type = IrTupleType((IrStringType(),))
        module = IrModule(
            "splitlines.py",
            (),
            (
                IrFunction(
                    "splitlines",
                    (),
                    tuple_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_splitlines",
                                (IrConstString("a\nb\n"), IrConstBool(True)),
                                tuple_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @__xcc_aot_string_splitlines", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_string_splitlines(ptr @.str0, i1 true)", llvm_ir)
        self.assertNotIn("@__str_splitlines", llvm_ir)

    def test_emits_string_replace_intrinsic_call(self) -> None:
        string_type = IrStringType()
        module = IrModule(
            "replace.py",
            (),
            (
                IrFunction(
                    "replace",
                    (),
                    string_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_replace",
                                (
                                    IrConstString("a\\\nb"),
                                    IrConstString("\\\n"),
                                    IrConstString(""),
                                ),
                                string_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @__xcc_aot_string_replace", llvm_ir)
        self.assertIn(
            "call ptr @__xcc_aot_string_replace(ptr @.str0, ptr @.str1, ptr @.str2)",
            llvm_ir,
        )
        self.assertNotIn("@__str_replace", llvm_ir)

    def test_emits_string_remove_affix_intrinsic_calls(self) -> None:
        string_type = IrStringType()
        module = IrModule(
            "remove_affix.py",
            (),
            (
                IrFunction(
                    "drop_prefix",
                    (),
                    string_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_removeprefix",
                                (IrConstString("clang fp contract"), IrConstString("clang fp")),
                                string_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "drop_suffix",
                    (),
                    string_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_removesuffix",
                                (IrConstString("main.c"), IrConstString(".c")),
                                string_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @__xcc_aot_string_removeprefix", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_string_removesuffix", llvm_ir)
        self.assertIn(
            "call ptr @__xcc_aot_string_removeprefix(ptr @.str0, ptr @.str1)",
            llvm_ir,
        )
        self.assertIn(
            "call ptr @__xcc_aot_string_removesuffix(ptr @.str2, ptr @.str3)",
            llvm_ir,
        )

    def test_emits_string_lower_intrinsic_call(self) -> None:
        string_type = IrStringType()
        module = IrModule(
            "lower.py",
            (),
            (
                IrFunction(
                    "lower",
                    (),
                    string_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_lower",
                                (IrConstString("ON"),),
                                string_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @__xcc_aot_string_lower", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_string_lower(ptr @.str0)", llvm_ir)

    def test_emits_string_find_intrinsic_with_strstr(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "find.py",
            (),
            (
                IrFunction(
                    "find",
                    (IrParam("start", int64),),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__str_find",
                                (
                                    IrConstString("abcdef"),
                                    IrConstString("de"),
                                    IrName("start", int64),
                                ),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare ptr @strstr(ptr, ptr)", llvm_ir)
        self.assertIn("call ptr @strstr(", llvm_ir)
        self.assertIn("select i1", llvm_ir)
        self.assertIn("i64 -1", llvm_ir)
        self.assertNotIn("@__str_find", llvm_ir)

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

    def test_emits_assert_as_abort_branch_without_runtime_assert_call(self) -> None:
        module = IrModule(
            "assert_emit.py",
            (),
            (
                IrFunction(
                    "check",
                    (IrParam("value", IrStringType()),),
                    IrNoneType(),
                    (
                        IrAssign(
                            "__assert",
                            IrCall("__assert", (IrName("value", IrStringType()),), IrNoneType()),
                        ),
                        IrReturn(IrConstNone()),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare void @abort()", llvm_ir)
        self.assertIn("call void @abort()", llvm_ir)
        self.assertIn("unreachable", llvm_ir)
        self.assertNotIn("@__assert", llvm_ir)

    def test_emits_string_padding_and_strip_intrinsic_calls(self) -> None:
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
                    "ltrim",
                    (),
                    string_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_lstrip",
                                (IrConstString("<<ab"), IrConstString("<")),
                                string_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "rtrim",
                    (),
                    string_type,
                    (
                        IrReturn(
                            IrCall(
                                "__str_rstrip",
                                (IrConstString("ab>>"), IrConstString(">")),
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
                                "__str_strip",
                                (IrConstString("|ab|"), IrConstString("|")),
                                string_type,
                            )
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define ptr @__xcc_aot_string_ljust", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_string_lstrip", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_string_rstrip", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_string_strip", llvm_ir)
        self.assertIn(
            "call ptr @__xcc_aot_string_ljust(ptr @.str0, i64 4, ptr @.str1)",
            llvm_ir,
        )
        self.assertIn("call ptr @__xcc_aot_string_lstrip(ptr @.str2, ptr @.str3)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_string_rstrip(ptr @.str4, ptr @.str5)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_string_strip(ptr @.str6, ptr @.str7)", llvm_ir)

    def test_emits_bytes_id_and_int_to_bytes_intrinsic_calls(self) -> None:
        int64 = IrIntType(64, signed=True)
        bytes_type = IrBytesType()
        module = IrModule(
            "bytes_helpers.py",
            (),
            (
                IrFunction(
                    "zeroed",
                    (),
                    bytes_type,
                    (IrReturn(IrCall("__bytes", (IrConstInt(3, int64),), bytes_type)),),
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
                    bytes_type,
                    (
                        IrReturn(
                            IrCall(
                                "__int_to_bytes",
                                (IrConstInt(65, int64), IrConstInt(1, int64), IrConstString("little")),
                                bytes_type,
                            )
                        ),
                    ),
                ),
            ),
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define ptr @__xcc_aot_bytes_new", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_int_to_bytes", llvm_ir)
        self.assertIn("%payload_size = add i64 %count, 1", llvm_ir)
        self.assertIn("call ptr @memset(ptr %data, i32 0, i64 %payload_size)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_bytes_new(i64 3)", llvm_ir)
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

    def test_emits_tuple_membership_for_variable_tuple(self) -> None:
        bool_type = IrBoolType()
        tuple_type = IrTupleType((IrStringType(),))
        module = IrModule(
            "tuple_membership.py",
            (),
            (
                IrFunction(
                    "contains",
                    (IrParam("needle", IrStringType()), IrParam("values", tuple_type)),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_In",
                                (IrName("needle", IrStringType()), IrName("values", tuple_type)),
                                bool_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "missing",
                    (IrParam("needle", IrStringType()), IrParam("values", tuple_type)),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_NotIn",
                                (IrName("needle", IrStringType()), IrName("values", tuple_type)),
                                bool_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i64 @__xcc_aot_tuple_len(ptr %values)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %values", llvm_ir)
        self.assertNotIn("@__cmp_In", llvm_ir)
        self.assertNotIn("@__cmp_NotIn", llvm_ir)

    def test_emits_null_safe_string_equality(self) -> None:
        bool_type = IrBoolType()
        optional_string = IrRecordType("str | None")
        module = IrModule(
            "optional_string_equality.py",
            (),
            (
                IrFunction(
                    "is_typedef",
                    (IrParam("value", optional_string),),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_Eq",
                                (IrName("value", optional_string), IrConstString("typedef")),
                                bool_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("icmp ne ptr %value, null", llvm_ir)
        self.assertIn("call i32 @strcmp(ptr %value, ptr @.str0)", llvm_ir)
        self.assertRegex(llvm_ir, r"%eq\d+ = phi i1")

    def test_emits_homogeneous_string_tuple_membership_with_strcmp(self) -> None:
        bool_type = IrBoolType()
        module = IrModule(
            "string_tuple_membership.py",
            (),
            (
                IrFunction(
                    "is_record_keyword",
                    (IrParam("needle", IrStringType()),),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_In",
                                (
                                    IrName("needle", IrStringType()),
                                    IrTuple(
                                        (IrConstString("struct"), IrConstString("union")),
                                        IrTupleType((IrStringType(), IrStringType())),
                                    ),
                                ),
                                bool_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(llvm_ir, r"call i32 @strcmp\(ptr %needle, ptr %contains\.item\d+\)")
        self.assertNotIn("@__cmp_In", llvm_ir)

    def test_emits_string_membership_as_substring_search(self) -> None:
        bool_type = IrBoolType()
        module = IrModule(
            "string_membership.py",
            (),
            (
                IrFunction(
                    "contains",
                    (IrParam("needle", IrStringType()), IrParam("haystack", IrStringType())),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_In",
                                (
                                    IrName("needle", IrStringType()),
                                    IrName("haystack", IrStringType()),
                                ),
                                bool_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare ptr @strstr(ptr, ptr)", llvm_ir)
        self.assertIn("call ptr @strstr(ptr %haystack, ptr %needle)", llvm_ir)
        self.assertNotIn("@__cmp_In", llvm_ir)

    def test_emits_string_membership_with_integer_byte_needle(self) -> None:
        bool_type = IrBoolType()
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "string_byte_membership.py",
            (),
            (
                IrFunction(
                    "contains",
                    (IrParam("needle", int64), IrParam("haystack", IrStringType())),
                    bool_type,
                    (
                        IrReturn(
                            IrCall(
                                "__cmp_NotIn",
                                (
                                    IrName("needle", int64),
                                    IrName("haystack", IrStringType()),
                                ),
                                bool_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("trunc i64 %needle to i8", llvm_ir)
        self.assertIn("call i64 @strlen(ptr %haystack)", llvm_ir)
        self.assertNotIn("@__cmp_NotIn", llvm_ir)

    def test_emits_dict_get_as_tuple_pair_scan(self) -> None:
        int64 = IrIntType(64, signed=True)
        dict_type = IrDictType(IrStringType(), int64)
        module = IrModule(
            "dict_get.py",
            (),
            (
                IrFunction(
                    "lookup",
                    (IrParam("values", dict_type), IrParam("key", IrStringType())),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__dict_get",
                                (IrName("values", dict_type), IrName("key", IrStringType())),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i64 @__xcc_aot_tuple_len(ptr %values)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_get(ptr %values", llvm_ir)
        self.assertIn("call i32 @strcmp", llvm_ir)
        self.assertNotIn("@__dict_get", llvm_ir)

    def test_emits_dict_items_as_tuple_identity(self) -> None:
        int64 = IrIntType(64, signed=True)
        dict_type = IrDictType(IrStringType(), int64)
        items_type = IrTupleType((IrTupleType((IrStringType(), int64)),))
        module = IrModule(
            "dict_items.py",
            (),
            (
                IrFunction(
                    "items",
                    (IrParam("values", dict_type),),
                    items_type,
                    (IrReturn(IrCall("__dict_items", (IrName("values", dict_type),), items_type)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("ret ptr %values", llvm_ir)
        self.assertNotIn("@__dict_items", llvm_ir)

    def test_emits_global_tuple_as_lazy_process_stable_handle(self) -> None:
        int64 = IrIntType(64, signed=True)
        dict_type = IrDictType(IrStringType(), int64)
        pair_type = IrTupleType((IrStringType(), int64))
        literal = IrTuple(
            (IrTuple((IrConstString("x"), IrConstInt(1, int64)), pair_type),),
            dict_type,
        )
        global_value = IrCall(
            "__global_tuple",
            (IrConstString("module:VALUES"), literal),
            dict_type,
        )
        module = IrModule(
            "global_tuple.py",
            (),
            (
                IrFunction(
                    "values",
                    (),
                    dict_type,
                    (IrReturn(global_value),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("@__xcc_aot_global_tuple_0 = private global ptr null", llvm_ir)
        self.assertIn("load ptr, ptr @__xcc_aot_global_tuple_0", llvm_ir)
        self.assertIn("global.tuple.init", llvm_ir)
        self.assertIn("global.tuple.ready", llvm_ir)
        self.assertIn("= phi ptr", llvm_ir)
        self.assertIn("store ptr %tuple", llvm_ir)

    def test_emits_bool_builtin_as_truthiness(self) -> None:
        tuple_type = IrTupleType((IrStringType(),))
        module = IrModule(
            "bool.py",
            (),
            (
                IrFunction(
                    "truth",
                    (IrParam("values", tuple_type),),
                    IrBoolType(),
                    (IrReturn(IrCall("bool", (IrName("values", tuple_type),), IrBoolType())),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i64 @__xcc_aot_tuple_len(ptr %values)", llvm_ir)
        self.assertIn("icmp ne i64", llvm_ir)
        self.assertNotIn("@bool", llvm_ir)

    def test_emits_len_builtin_for_string_with_strlen(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "len_string.py",
            (),
            (
                IrFunction(
                    "size",
                    (IrParam("value", IrStringType()),),
                    int64,
                    (IrReturn(IrCall("len", (IrName("value", IrStringType()),), int64)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i64 @strlen(ptr %value)", llvm_ir)
        self.assertNotIn("@len", llvm_ir)

    def test_emits_len_builtin_for_optional_string_with_strlen(self) -> None:
        int64 = IrIntType(64, signed=True)
        optional_string = IrRecordType("str | None")
        module = IrModule(
            "len_optional_string.py",
            (),
            (
                IrFunction(
                    "size",
                    (IrParam("value", optional_string),),
                    int64,
                    (IrReturn(IrCall("len", (IrName("value", optional_string),), int64)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i64 @strlen(ptr %value)", llvm_ir)
        self.assertNotIn("@len", llvm_ir)

    def test_emits_path_parent_intrinsic(self) -> None:
        path_type = IrRecordType("Path")
        module = IrModule(
            "path_helpers.py",
            (),
            (
                IrFunction(
                    "parent",
                    (IrParam("path", path_type),),
                    path_type,
                    (IrReturn(IrCall("__path_parent", (IrName("path", path_type),), path_type)),),
                ),
                IrFunction(
                    "join",
                    (IrParam("path", path_type), IrParam("child", IrStringType())),
                    path_type,
                    (
                        IrReturn(
                            IrCall(
                                "__path_join",
                                (IrName("path", path_type), IrName("child", IrStringType())),
                                path_type,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "name",
                    (IrParam("path", path_type),),
                    IrStringType(),
                    (IrReturn(IrCall("__path_name", (IrName("path", path_type),), IrStringType())),),
                ),
                IrFunction(
                    "resolved",
                    (IrParam("filename", IrStringType()),),
                    IrStringType(),
                    (
                        IrReturn(
                            IrCall(
                                "__path_to_string",
                                (
                                    IrCall(
                                        "__path_resolve",
                                        (
                                            IrCall(
                                                "__path_from_string",
                                                (IrName("filename", IrStringType()),),
                                                path_type,
                                            ),
                                        ),
                                        path_type,
                                    ),
                                ),
                                IrStringType(),
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "read",
                    (IrParam("path", path_type),),
                    IrStringType(),
                    (
                        IrReturn(
                            IrCall(
                                "__path_read_text",
                                (IrName("path", path_type),),
                                IrStringType(),
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "exists",
                    (IrParam("path", path_type),),
                    IrBoolType(),
                    (
                        IrReturn(
                            IrCall(
                                "__path_is_file",
                                (IrName("path", path_type),),
                                IrBoolType(),
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_path_parent(ptr %path)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_path_name(ptr %path)", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_path_join(ptr %path, ptr %child)", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_path_parent(ptr %path)", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_path_name(ptr %path)", llvm_ir)
        self.assertIn("define ptr @__xcc_aot_path_join(ptr %path, ptr %child)", llvm_ir)
        self.assertIn("define ptr @resolved(ptr %filename)", llvm_ir)
        self.assertIn("ret ptr %filename", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_read_text_file(ptr %path)", llvm_ir)
        self.assertIn("call i1 @__xcc_aot_path_is_file(ptr %path)", llvm_ir)
        self.assertIn("define i1 @__xcc_aot_path_is_file(ptr %path)", llvm_ir)
        self.assertNotIn("@Path", llvm_ir)
        self.assertNotIn("call ptr @str(", llvm_ir)

    def test_emits_len_for_tuple_narrowed_from_union_record(self) -> None:
        int64 = IrIntType(64, signed=True)
        function_params = IrTupleType((IrTupleType((IrRecordType("Type"),)), IrBoolType()))
        module = IrModule(
            "len_union_tuple.py",
            (),
            (
                IrFunction(
                    "size",
                    (IrParam("value", IrRecordType("int | FunctionParams")),),
                    int64,
                    (IrReturn(IrCall("len", (IrName("value", function_params),), int64)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("getelementptr i8, ptr %value, i64 8", llvm_ir)
        self.assertRegex(
            llvm_ir,
            r"call i64 @__xcc_aot_tuple_len\(ptr %object\.pointer\d+\)",
        )
        self.assertNotIn("@len", llvm_ir)

    def test_fixed_tuple_literal_boxes_nested_tuple_for_object_slot(self) -> None:
        module = lower_source_to_ir(
            "FunctionParams = tuple[tuple[str, ...] | None, bool]\n"
            "TypeOp = tuple[str, int | FunctionParams]\n"
            "def make_function_op(params: tuple[str, ...]) -> TypeOp:\n"
            "    return ('fn', (params, False))\n",
            filename="fixed-tuple-object-slot.py",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertRegex(llvm_ir, r"store i64 9, ptr %object\d+")
        self.assertRegex(llvm_ir, r"store ptr %tuple\d+, ptr %object\.payload\d+")
        self.assertRegex(
            llvm_ir,
            r"call void @__xcc_aot_tuple_set\(ptr %tuple\d+, i64 \d+, ptr %object\d+\)",
        )

    def test_tuple_concat_keeps_homogeneous_declared_object_layout(self) -> None:
        module = lower_source_to_ir(
            "from dataclasses import dataclass\n"
            "FunctionParams = tuple[tuple['Type', ...] | None, bool]\n"
            "TypeOp = tuple[str, int | FunctionParams]\n"
            "@dataclass(frozen=True)\n"
            "class Type:\n"
            "    name: str\n"
            "    declarator_ops: tuple[TypeOp, ...]\n"
            "def build(inferred: int, tail: tuple[TypeOp, ...]) -> Type:\n"
            "    new_ops = (('arr', inferred),) + tail\n"
            "    return Type('int', new_ops)\n",
            filename="tuple-concat-tagged-object-slot.py",
        )

        assignment = module.functions[-1].body[0]
        self.assertIsInstance(assignment, IrAssign)
        assert isinstance(assignment, IrAssign)
        self.assertIsInstance(assignment.value, IrCall)
        assert isinstance(assignment.value, IrCall)
        concat_type = assignment.value.type
        self.assertIsInstance(concat_type, IrTupleType)
        assert isinstance(concat_type, IrTupleType)
        self.assertEqual(len(concat_type.elements), 1)
        type_op = concat_type.elements[0]
        self.assertIsInstance(type_op, IrTupleType)
        assert isinstance(type_op, IrTupleType)
        self.assertIsInstance(type_op.elements[1], IrRecordType)
        self.assertIn("int | tuple", type_op.elements[1].name)

        llvm_ir = emit_llvm_text(module)
        self.assertRegex(llvm_ir, r"store i64 2, ptr %object\d+")
        self.assertRegex(
            llvm_ir,
            r"call void @__xcc_aot_tuple_set\(ptr %tuple\d+, i64 \d+, ptr %object\d+\)",
        )

    def test_emits_range_intrinsic_as_runtime_tuple(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((int64,))
        module = IrModule(
            "range.py",
            (),
            (
                IrFunction(
                    "values",
                    (IrParam("n", int64),),
                    tuple_type,
                    (IrReturn(IrCall("range", (IrName("n", int64),), tuple_type)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_range(i64 0, i64 %n, i64 1)", llvm_ir)
        self.assertNotIn("@range", llvm_ir)

    def test_emits_reversed_intrinsic_as_runtime_tuple(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((int64,))
        module = IrModule(
            "reversed.py",
            (),
            (
                IrFunction(
                    "values",
                    (IrParam("items", tuple_type),),
                    tuple_type,
                    (IrReturn(IrCall("reversed", (IrName("items", tuple_type),), tuple_type)),),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_reversed(ptr %items)", llvm_ir)
        self.assertNotIn("@reversed", llvm_ir)

    def test_emits_tuple_append_method_as_tuple_concat(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((int64,))
        module = IrModule(
            "append.py",
            (),
            (
                IrFunction(
                    "append",
                    (IrParam("values", tuple_type), IrParam("value", int64)),
                    tuple_type,
                    (
                        IrReturn(
                            IrCall(
                                "values.append",
                                (IrName("values", tuple_type), IrName("value", int64)),
                                tuple_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_append(ptr %values", llvm_ir)
        self.assertIn("call void @__xcc_aot_tuple_forward(ptr %values", llvm_ir)
        self.assertNotIn("@values.append", llvm_ir)

    def test_emits_set_add_with_membership_guard(self) -> None:
        module = lower_source_to_ir(
            "def add_name(values: set[str], name: str) -> int:\n"
            "    values.add(name)\n"
            "    return len(values)\n",
            filename="set_add.py",
            entry="add_name",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i64 @__xcc_aot_tuple_len(ptr %values)", llvm_ir)
        self.assertIn("setadd.keep", llvm_ir)
        self.assertIn("setadd.append", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_tuple_append(ptr %values", llvm_ir)
        self.assertNotIn("call ptr @__xcc_aot_tuple_concat(ptr %values", llvm_ir)
        self.assertNotIn("call void @__xcc_aot_tuple_forward(ptr %values", llvm_ir)
        self.assertNotIn("@__set_add", llvm_ir)

    def test_emits_set_difference_update_with_alias_forwarding(self) -> None:
        module = lower_source_to_ir(
            "def subtract(values: set[str], removed: set[str]) -> int:\n"
            "    values.difference_update(removed)\n"
            "    return len(values)\n",
            filename="set_difference_update.py",
            entry="subtract",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call i64 @__xcc_aot_tuple_len(ptr %removed)", llvm_ir)
        self.assertIn("%setop.include", llvm_ir)
        self.assertIn("call void @__xcc_aot_tuple_forward(ptr %values", llvm_ir)
        self.assertNotIn("@__set_difference_update", llvm_ir)

    def test_dict_insertions_append_pairs_without_full_container_copies(self) -> None:
        module = lower_source_to_ir(
            "def update(values: dict[str, int]) -> int:\n"
            "    values.setdefault('first', 1)\n"
            "    values['second'] = 2\n"
            "    return len(values)\n",
            filename="dict_stable_insert.py",
            entry="update",
        )

        llvm_ir = emit_llvm_text(module)
        function_body = llvm_ir.split("define i64 @update", 1)[1].split("\n}", 1)[0]

        self.assertEqual(function_body.count("call ptr @__xcc_aot_tuple_append"), 2)
        self.assertNotIn("call ptr @__xcc_aot_tuple_concat", function_body)
        self.assertNotIn("call void @__xcc_aot_tuple_forward", function_body)

    def test_runtime_slice_assignment_mutates_stable_handle_without_temporaries(self) -> None:
        module = lower_source_to_ir(
            "def replace(values: list[int], incoming: list[int]) -> int:\n"
            "    values[1:-1] = incoming\n"
            "    return len(values)\n",
            filename="list_slice_assignment.py",
            entry="replace",
        )

        llvm_ir = emit_llvm_text(module)
        runtime_body = llvm_ir.split(
            "define ptr @__xcc_aot_tuple_set_slice(",
            1,
        )[1].split("\n}", 1)[0]

        self.assertIn("call ptr @memmove", runtime_body)
        self.assertIn("call void @__xcc_aot_tuple_register_capacity", runtime_body)
        self.assertNotIn("@__xcc_aot_tuple_slice", runtime_body)
        self.assertNotIn("@__xcc_aot_tuple_concat", runtime_body)
        self.assertNotIn("@__xcc_aot_tuple_forward", runtime_body)

    def test_emits_record_append_method_as_direct_call(self) -> None:
        output_type = IrRecordType("Output")
        module = IrModule(
            "record_append.py",
            (IrRecord("Output", ()),),
            (
                IrFunction(
                    "Output.append",
                    (IrParam("self", output_type), IrParam("text", IrStringType())),
                    IrNoneType(),
                    (IrReturn(IrConstNone()),),
                ),
                IrFunction(
                    "use",
                    (IrParam("out", output_type),),
                    IrNoneType(),
                    (
                        IrAssign(
                            "__expr",
                            IrCall(
                                "Output.append",
                                (IrName("out", output_type), IrConstString("x")),
                                IrNoneType(),
                            ),
                        ),
                        IrReturn(IrConstNone()),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call void @Output.append(ptr %out", llvm_ir)
        self.assertNotIn("@__xcc_aot_tuple_concat", llvm_ir)

    def test_emits_tuple_pop_method_as_runtime_tuple_pop(self) -> None:
        int64 = IrIntType(64, signed=True)
        tuple_type = IrTupleType((int64,))
        module = IrModule(
            "pop.py",
            (),
            (
                IrFunction(
                    "drop",
                    (IrParam("values", tuple_type),),
                    IrNoneType(),
                    (
                        IrAssign(
                            "__expr",
                            IrCall("values.pop", (IrName("values", tuple_type),), IrNoneType()),
                        ),
                        IrReturn(IrConstNone()),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("call ptr @__xcc_aot_tuple_pop(ptr %values)", llvm_ir)
        self.assertNotIn("@values.pop", llvm_ir)

    def test_emits_tuple_comprehension_with_stable_builder_append(self) -> None:
        module = lower_source_to_ir(
            "def gather(values: tuple[int, ...]) -> tuple[int, ...]:\n"
            "    return tuple(value + 1 for value in values)\n"
            "def entry() -> int:\n"
            "    return len(gather((1, 2)))\n",
            filename="tuple_comprehension_append.py",
            entry="entry",
        )

        llvm_ir = emit_llvm_text(module)
        start = llvm_ir.index("define ptr @gather")
        end = llvm_ir.index("\n}", start)
        function_ir = llvm_ir[start:end]

        self.assertIn("call ptr @__xcc_aot_tuple_append", function_ir)
        self.assertNotIn("call ptr @__xcc_aot_tuple_concat", function_ir)

    def test_emits_zip_intrinsic_as_runtime_tuple_pairs(self) -> None:
        int64 = IrIntType(64, signed=True)
        names_type = IrTupleType((IrStringType(),))
        values_type = IrTupleType((int64,))
        result_type = IrTupleType((IrTupleType((IrStringType(), int64)),))
        module = IrModule(
            "zip.py",
            (),
            (
                IrFunction(
                    "zipped",
                    (IrParam("names", names_type), IrParam("values", values_type)),
                    result_type,
                    (
                        IrReturn(
                            IrCall(
                                "__zip",
                                (IrName("names", names_type), IrName("values", values_type)),
                                result_type,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("define ptr @__xcc_aot_zip2", llvm_ir)
        self.assertIn("call ptr @__xcc_aot_zip2(ptr %names, ptr %values)", llvm_ir)
        self.assertNotIn("@__zip", llvm_ir)

    def test_emits_llvm_add_case_as_void_c_api_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "llvm_add_case.py",
            (),
            (
                IrFunction(
                    "add_case",
                    (
                        IrParam("switch", int64),
                        IrParam("value", int64),
                        IrParam("block", int64),
                    ),
                    IrNoneType(),
                    (
                        IrAssign(
                            "__expr",
                            IrCall(
                                "__llvm_AddCase",
                                (
                                    IrName("switch", int64),
                                    IrName("value", int64),
                                    IrName("block", int64),
                                ),
                                IrNoneType(),
                            ),
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare void @LLVMAddCase(ptr, ptr, ptr)", llvm_ir)
        self.assertIn("call void @LLVMAddCase(", llvm_ir)
        self.assertNotIn("@__llvm_AddCase", llvm_ir)

    def test_emits_llvm_add_function_as_handle_returning_c_api_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "llvm_add_function.py",
            (),
            (
                IrFunction(
                    "add_function",
                    (
                        IrParam("module", int64),
                        IrParam("name", IrStringType()),
                        IrParam("fn_type", int64),
                    ),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__llvm_AddFunction",
                                (
                                    IrName("module", int64),
                                    IrName("name", IrStringType()),
                                    IrName("fn_type", int64),
                                ),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare ptr @LLVMAddFunction(ptr, ptr, ptr)", llvm_ir)
        self.assertIn("call ptr @LLVMAddFunction(", llvm_ir)
        self.assertIn("ptrtoint ptr", llvm_ir)
        self.assertNotIn("@__llvm_AddFunction", llvm_ir)

    def test_emits_llvm_add_global_as_handle_returning_c_api_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        object_type = IrRecordType("object")
        module = IrModule(
            "llvm_add_global.py",
            (),
            (
                IrFunction(
                    "add_global",
                    (
                        IrParam("module", int64),
                        IrParam("type_ref", int64),
                        IrParam("name", IrStringType()),
                    ),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__llvm_AddGlobal",
                                (
                                    IrName("module", int64),
                                    IrName("type_ref", int64),
                                    IrName("name", IrStringType()),
                                ),
                                int64,
                            )
                        ),
                    ),
                ),
                IrFunction(
                    "add_global_object_name",
                    (
                        IrParam("module", int64),
                        IrParam("type_ref", int64),
                        IrParam("name", object_type),
                    ),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__llvm_AddGlobal",
                                (
                                    IrName("module", int64),
                                    IrName("type_ref", int64),
                                    IrName("name", object_type),
                                ),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare ptr @LLVMAddGlobal(ptr, ptr, ptr)", llvm_ir)
        self.assertIn("call ptr @LLVMAddGlobal(", llvm_ir)
        self.assertIn("ptrtoint ptr", llvm_ir)
        self.assertNotIn("@__llvm_AddGlobal", llvm_ir)

    def test_emits_llvm_module_create_with_name_as_c_api_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "llvm_module_create.py",
            (),
            (
                IrFunction(
                    "make",
                    (IrParam("name", IrStringType()),),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__llvm_ModuleCreateWithName",
                                (IrName("name", IrStringType()),),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare ptr @LLVMModuleCreateWithName(ptr)", llvm_ir)
        self.assertIn("call ptr @LLVMModuleCreateWithName(ptr %name)", llvm_ir)
        self.assertIn("ptrtoint ptr", llvm_ir)
        self.assertNotIn("@__llvm_ModuleCreateWithName", llvm_ir)

    def test_emits_llvm_add_incoming_as_void_c_api_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "llvm_add_incoming.py",
            (),
            (
                IrFunction(
                    "add_incoming",
                    (
                        IrParam("phi", int64),
                        IrParam("values", IrTupleType((int64,))),
                        IrParam("blocks", IrTupleType((int64,))),
                        IrParam("count", int64),
                    ),
                    IrNoneType(),
                    (
                        IrAssign(
                            "__expr",
                            IrCall(
                                "__llvm_AddIncoming",
                                (
                                    IrName("phi", int64),
                                    IrName("values", IrTupleType((int64,))),
                                    IrName("blocks", IrTupleType((int64,))),
                                    IrName("count", int64),
                                ),
                                IrNoneType(),
                            ),
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare void @LLVMAddIncoming(ptr, ptr, ptr, i32)", llvm_ir)
        self.assertIn("call void @LLVMAddIncoming(", llvm_ir)
        self.assertNotIn("@__llvm_AddIncoming", llvm_ir)

    def test_emits_llvm_append_basic_block_as_handle_returning_c_api_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "llvm_append_basic_block.py",
            (),
            (
                IrFunction(
                    "append_block",
                    (IrParam("function", int64), IrParam("name", IrStringType())),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__llvm_AppendBasicBlock",
                                (IrName("function", int64), IrName("name", IrStringType())),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare ptr @LLVMAppendBasicBlock(ptr, ptr)", llvm_ir)
        self.assertIn("call ptr @LLVMAppendBasicBlock(", llvm_ir)
        self.assertNotIn("@__llvm_AppendBasicBlock", llvm_ir)

    def test_emits_llvm_array_type_as_handle_returning_c_api_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "llvm_array_type.py",
            (),
            (
                IrFunction(
                    "array_type",
                    (IrParam("element_type", int64), IrParam("count", int64)),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__llvm_ArrayType",
                                (IrName("element_type", int64), IrName("count", int64)),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare ptr @LLVMArrayType2(ptr, i64)", llvm_ir)
        self.assertIn("call ptr @LLVMArrayType2(", llvm_ir)
        self.assertNotIn("@__llvm_ArrayType", llvm_ir)

    def test_emits_llvm_binary_builder_as_handle_returning_c_api_call(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "llvm_build_binary.py",
            (),
            (
                IrFunction(
                    "build_ashr",
                    (
                        IrParam("builder", int64),
                        IrParam("left", int64),
                        IrParam("right", int64),
                    ),
                    int64,
                    (
                        IrReturn(
                            IrCall(
                                "__llvm_BuildAShr",
                                (
                                    IrName("builder", int64),
                                    IrName("left", int64),
                                    IrName("right", int64),
                                    IrConstString("binop"),
                                ),
                                int64,
                            )
                        ),
                    ),
                ),
            ),
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn("declare ptr @LLVMBuildAShr(ptr, ptr, ptr, ptr)", llvm_ir)
        self.assertIn("call ptr @LLVMBuildAShr(", llvm_ir)
        self.assertIn("ptrtoint ptr", llvm_ir)
        self.assertNotIn("@__llvm_BuildAShr", llvm_ir)

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
        int64 = IrIntType(64, signed=True)
        self.assertEqual(
            _statement_assignment_types(
                IrAssign(
                    "(left, right)",
                    IrTuple(
                        (IrConstBool(True), IrConstInt(1, int64)),
                        IrTupleType((IrBoolType(), int64)),
                    ),
                )
            ),
            {"left": (IrBoolType(),), "right": (int64,)},
        )
        self.assertEqual(_statement_assigned_names(IrAssign("__expr", IrConstNone())), ())
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
        narrowing_lines: list[str] = []
        narrowed = emitter._emit_runtime_object_narrowing(
            _EmittedValue("%raw", IrRecordType("object")),
            IrFloatType(),
            narrowing_lines,
        )
        self.assertIsNotNone(narrowed)
        assert narrowed is not None
        self.assertEqual(narrowed.type, IrFloatType())
        self.assertIn("  %object.payload1 = getelementptr i8, ptr %raw, i64 8", narrowing_lines)
        self.assertIn("  %object.float2 = load double, ptr %object.payload1", narrowing_lines)
        with self.assertRaises(AotError) as ctx:
            emitter._emit_error_record(
                IrRaise("ValueError", IrConstString("bad")),
                {},
                [],
            )
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
                "__enumerate expects one or two arguments",
            ),
            (
                IrCall(
                    "__enumerate",
                    (IrTuple((), IrTupleType(())),),
                    IrStringType(),
                ),
                "__enumerate loop expects two element types",
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
                "tuple assignment target expects tuple value",
            ),
        )
        for iterable, message in enumerate_cases:
            with self.subTest(message=message):
                target = (
                    "(index, item, extra)"
                    if message == "tuple assignment target expects tuple value"
                    else "(index, item)"
                )
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
