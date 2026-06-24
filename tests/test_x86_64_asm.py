import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.ast import (
    AlignofExpr,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    BuiltinOffsetofExpr,
    BuiltinVaArgExpr,
    CallExpr,
    CaseStmt,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundLiteralExpr,
    CompoundStmt,
    ConditionalExpr,
    ContinueStmt,
    DeclStmt,
    DefaultStmt,
    FloatLiteral,
    FunctionDef,
    Identifier,
    IndirectGotoStmt,
    InitItem,
    InitList,
    IntLiteral,
    MemberExpr,
    NullStmt,
    Param,
    RecordMemberDecl,
    ReturnStmt,
    SizeofExpr,
    StatementExpr,
    StringLiteral,
    SubscriptExpr,
    SwitchStmt,
    TypedefDecl,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
)
from xcc.diag import CodegenError
from xcc.frontend import compile_source
from xcc.options import FrontendOptions
from xcc.sema.symbols import RecordMemberInfo
from xcc.types import BOOL, DOUBLE, FLOAT, INT, VOID, Type
from xcc.x86_64_asm import (
    _AggregateChunk,
    _CallArg,
    _Global,
    _MemberAccess,
    _ScalarInfo,
    _Slot,
    _StaticLocal,
    _Value,
    _X86_64AsmGen,
    generate_x86_64_asm,
)


class X86_64AsmTests(unittest.TestCase):
    def _asm(self, source: str) -> str:
        options = FrontendOptions(
            std="gnu11",
            no_standard_includes=True,
            host_machine="x86_64",
            target_os="linux",
        )
        return generate_x86_64_asm(compile_source(source, filename="test.c", options=options))

    def _run(self, source: str) -> int:
        if not (platform.system() == "Linux" and platform.machine() == "x86_64"):
            self.skipTest("native x86_64 Linux assembler is not available on this host")
        if shutil.which("cc") is None:
            self.skipTest("cc is not available")
        asm = self._asm(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asm_path = root / "input.s"
            exe_path = root / "a.out"
            asm_path.write_text(asm, encoding="utf-8")
            assemble = subprocess.run(
                ["cc", str(asm_path), "-o", str(exe_path)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(assemble.returncode, 0, assemble.stderr)
            run = subprocess.run([str(exe_path)], check=False)
            return run.returncode

    def test_emits_constant_return_function(self) -> None:
        asm = self._asm("int f(void){return 7;}")
        self.assertIn(".intel_syntax noprefix", asm)
        self.assertIn(".globl f\nf:", asm)
        self.assertIn("    mov eax, 7", asm)
        self.assertNotIn("define i32", asm)

    def test_block_scope_function_declaration_does_not_allocate_local_slot(self) -> None:
        asm = self._asm(
            """
int main(void) {
  long magic(void);
  return magic() == 17 ? 0 : 1;
}
long magic(void) {
  return 17;
}
"""
        )
        self.assertIn("    call magic", asm)
        self.assertNotIn("Unknown local declaration", asm)

    def test_block_scope_extern_function_declaration_emits_direct_call(self) -> None:
        asm = self._asm(
            """
int main(void) {
  extern int callee(int);
  return callee(7);
}
"""
        )
        self.assertIn("    call callee", asm)
        self.assertNotIn("call r11", asm)

    def test_helper_control_guards_and_unnamed_parameters_are_covered(self) -> None:
        result = compile_source(
            "void vf(void) { return; }\nint f(void) { return 0; }",
            filename="x86_helper_control_edges.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)
        gen._func_sym = result.sema.functions["f"]

        self.assertEqual(gen._referenced_function_names(object()), [])
        self.assertEqual(gen._index_local_record_type_specs(object()), {})

        gen._spill_parameters(
            FunctionDef(
                TypeSpec("int"), "unnamed", [Param(TypeSpec("int"), None)], CompoundStmt([])
            )
        )
        gen._prepare_frame(
            FunctionDef(
                TypeSpec("int"), "unnamed", [Param(TypeSpec("int"), None)], CompoundStmt([])
            ),
            CompoundStmt([]),
        )
        with self.assertRaisesRegex(CodegenError, "Missing parameter symbol: missing"):
            gen._prepare_frame(
                FunctionDef(
                    TypeSpec("int"),
                    "missing_param_symbol",
                    [Param(TypeSpec("int"), "missing")],
                    CompoundStmt([]),
                ),
                CompoundStmt([]),
            )

        with self.assertRaisesRegex(CodegenError, "case outside switch"):
            gen._emit_stmt(CaseStmt(IntLiteral("1"), NullStmt()))
        with self.assertRaisesRegex(CodegenError, "default outside switch"):
            gen._emit_stmt(DefaultStmt(NullStmt()))
        with self.assertRaisesRegex(CodegenError, "continue outside loop"):
            gen._emit_stmt(ContinueStmt())
        with self.assertRaisesRegex(CodegenError, "break outside loop or switch"):
            gen._emit_stmt(BreakStmt())
        with self.assertRaisesRegex(CodegenError, "does not support IndirectGotoStmt"):
            gen._emit_stmt(IndirectGotoStmt(Identifier("target")))
        with self.assertRaisesRegex(CodegenError, "missing variadic register save slot"):
            gen._spill_variadic_registers()

        gen._switch_stack.append(({1: ".L.case"}, None, ".L.end"))
        with self.assertRaisesRegex(CodegenError, "default label missing"):
            gen._emit_stmt(DefaultStmt(NullStmt()))
        gen._switch_stack.pop()

        nested_cases, nested_default = gen._collect_switch_cases(
            SwitchStmt(IntLiteral("0"), CaseStmt(IntLiteral("1"), NullStmt()))
        )
        self.assertEqual(nested_cases, [])
        self.assertIsNone(nested_default)

        collected: list[str | None] = []
        gen._collect_local_slots(
            IndirectGotoStmt(StatementExpr(DeclStmt(TypeSpec("int"), "inside", None))),
            lambda stmt, _type, _alignment: collected.append(stmt.name),
        )
        self.assertEqual(collected, ["inside"])

        gen._collect_local_slots(ReturnStmt(None), lambda _stmt, _type, _alignment: None)
        gen._collect_statement_expr_local_slots(object(), lambda _stmt, _type, _alignment: None)
        gen._collect_compound_literal_slots(object(), lambda _expr, _type: None)
        gen._collect_aggregate_call_slots(object(), lambda _expr, _type: None)

        void_gen = _X86_64AsmGen(result)
        void_gen._func_sym = result.sema.functions["vf"]
        void_gen._return_label = ".L.vf.return"
        void_gen._emit_return(ReturnStmt(None))
        void_return_value = IntLiteral("1")
        void_gen._type_map.set(void_return_value, INT)
        void_gen._emit_return(ReturnStmt(void_return_value))
        self.assertIn("    jmp .L.vf.return", void_gen._lines)

    def test_helper_backend_guard_record_va_atomic_and_call_arg_edges(self) -> None:
        result = compile_source(
            """
struct Mixed { double d; int i; };
struct Big { long a; long b; long c; };
int f(int anchor, ...) { return anchor; }
""",
            filename="x86_helper_backend_edges.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)
        function = next(item for item in result.unit.functions if item.name == "f")
        gen._func = function
        gen._func_sym = result.sema.functions["f"]

        file_scope = gen._sema.file_scope
        object.__setattr__(gen._sema, "file_scope", None)
        try:
            gen._collect_globals()
        finally:
            object.__setattr__(gen._sema, "file_scope", file_scope)

        with self.assertRaisesRegex(CodegenError, "Missing semantic function symbol: missing"):
            gen._emit_function(FunctionDef(TypeSpec("int"), "missing", [], CompoundStmt([])))
        gen._func = function
        gen._func_sym = result.sema.functions["f"]

        tagged_record = TypeSpec(
            "struct",
            record_tag="Local",
            record_members=(RecordMemberDecl(TypeSpec("int"), "value"),),
        )
        tagged_reference = TypeSpec("struct", record_tag="Local")
        atomic_reference = TypeSpec("int", is_atomic=True, atomic_target=tagged_reference)
        typeof_reference = TypeSpec("int", typeof_expr=Identifier("anchor"))
        indexed_records = gen._index_local_record_type_specs(
            CompoundStmt(
                [
                    DeclStmt(tagged_record, "record_value", None),
                    TypedefDecl(atomic_reference, "AtomicLocal"),
                    DeclStmt(typeof_reference, "copy", None),
                    CompoundStmt([DeclStmt(tagged_reference, "late_reference", None)]),
                ]
            )
        )
        self.assertEqual(indexed_records[id(tagged_reference)], indexed_records[id(tagged_record)])

        empty_statement_value = gen._emit_statement_expr(StatementExpr(CompoundStmt([])), "rax")
        self.assertEqual(empty_statement_value.type_, VOID)
        non_expr_statement_value = gen._emit_statement_expr(
            StatementExpr(CompoundStmt([NullStmt()])), "rax"
        )
        self.assertEqual(non_expr_statement_value.type_, VOID)

        compound_literal = CompoundLiteralExpr(
            TypeSpec("int"), InitList((InitItem((), IntLiteral("1")),))
        )
        with self.assertRaisesRegex(CodegenError, "missing compound literal storage"):
            gen._emit_compound_literal(compound_literal, "rax")

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        comma_expr = typed_expr(
            CommaExpr(typed_expr(IntLiteral("1"), INT), typed_expr(IntLiteral("2"), INT)),
            INT,
        )
        self.assertEqual(gen._emit_expr(comma_expr, "r10").reg, "r10")

        aggregate_static_type = Type("struct Mixed")
        gen._static_locals[("f", "static_record")] = _StaticLocal(
            ".L.f.static_record", aggregate_static_type, None
        )
        gen._scope_stack.append(
            {"static_record": _Slot(0, aggregate_static_type, _ScalarInfo(16, 8, False))}
        )
        self.assertEqual(
            gen._emit_identifier(Identifier("static_record"), "rax").type_,
            aggregate_static_type.pointer_to(),
        )
        gen._scope_stack.pop()

        va_list_slot = _Slot(24, Type("__builtin_va_list"), _ScalarInfo(24, 8, False))
        gen._param_slots["ap"] = va_list_slot
        self.assertEqual(gen._emit_identifier(Identifier("ap"), "rax").type_, VOID.pointer_to())
        gen._param_slots.clear()

        gen._static_locals[("f", "static_scalar")] = _StaticLocal(".L.f.static_scalar", INT, None)
        self.assertEqual(gen._emit_identifier(Identifier("static_scalar"), "r10").reg, "r10")
        gen._static_locals[("f", "static_array")] = _StaticLocal(
            ".L.f.static_array", INT.array_of(2), None
        )
        self.assertEqual(
            gen._emit_identifier(Identifier("static_array"), "r11").type_,
            INT.array_of(2).pointer_to(),
        )
        gen._globals["global_record"] = _Global("global_record", aggregate_static_type, False)
        self.assertEqual(
            gen._emit_identifier(Identifier("global_record"), "rax").type_,
            aggregate_static_type.pointer_to(),
        )
        with self.assertRaisesRegex(CodegenError, "Unknown identifier: missing_identifier"):
            gen._emit_identifier(Identifier("missing_identifier"), "rax")

        with self.assertRaisesRegex(CodegenError, "requires two arguments for va_start"):
            gen._emit_va_start(CallExpr(Identifier("__builtin_va_start"), []))
        with self.assertRaisesRegex(CodegenError, "requires named va_start anchor"):
            gen._emit_va_start(
                CallExpr(Identifier("__builtin_va_start"), [Identifier("ap"), IntLiteral("0")])
            )
        gen._param_slots["anchor"] = _Slot(4, INT, _ScalarInfo(4, 4, True))
        with self.assertRaisesRegex(CodegenError, "missing variadic register save area"):
            gen._emit_va_start(
                CallExpr(Identifier("__builtin_va_start"), [Identifier("ap"), Identifier("anchor")])
            )
        with self.assertRaisesRegex(CodegenError, "requires one argument for va_end"):
            gen._emit_va_end(CallExpr(Identifier("__builtin_va_end"), []))
        with self.assertRaisesRegex(CodegenError, "requires two arguments for va_copy"):
            gen._emit_va_copy(CallExpr(Identifier("__builtin_va_copy"), [Identifier("dst")]))

        gen._func = None
        with self.assertRaisesRegex(CodegenError, "va_start outside function"):
            gen._variadic_start_state("anchor")
        gen._func = function
        with self.assertRaisesRegex(CodegenError, "cannot find va_start anchor missing_anchor"):
            gen._variadic_start_state("missing_anchor")
        gen._func = FunctionDef(
            TypeSpec("int"),
            "unnamed_anchor",
            [Param(TypeSpec("int"), None), Param(TypeSpec("int"), "anchor")],
            CompoundStmt([]),
        )
        self.assertEqual(gen._variadic_start_state("anchor"), (8, 48, 16))
        gen._func = function

        mixed_arg = typed_expr(Identifier("mixed"), aggregate_static_type)
        aggregate_va_arg = typed_expr(
            BuiltinVaArgExpr(Identifier("ap"), TypeSpec("struct", record_tag="Mixed")),
            aggregate_static_type,
        )
        with self.assertRaisesRegex(CodegenError, "aggregate va_arg"):
            gen._emit_va_arg(aggregate_va_arg, "rax")

        original_emit_address = gen._emit_address
        gen._emit_address = lambda _expr, _target: INT.pointer_to()
        try:
            self.assertEqual(
                gen._emit_va_list_storage_address(UnaryExpr("*", Identifier("ap")), "rcx"),
                INT.pointer_to(),
            )
        finally:
            gen._emit_address = original_emit_address

        register_chunks = gen._classify_call_args([mixed_arg])
        self.assertEqual([arg.location for arg in register_chunks], ["fp_reg", "int_reg"])
        big_arg = typed_expr(Identifier("big"), Type("struct Big"))
        self.assertTrue(all(arg.location == "stack" for arg in gen._classify_call_args([big_arg])))
        double_arg = typed_expr(FloatLiteral("1.0"), DOUBLE)
        int_arg = typed_expr(IntLiteral("7"), INT)
        stack_scalars = gen._classify_call_args([double_arg, int_arg], int_arg_reg=6, fp_arg_reg=8)
        self.assertEqual([arg.location for arg in stack_scalars], ["stack", "stack"])
        self.assertEqual(_X86_64AsmGen._used_fp_arg_regs(register_chunks), 1)
        gen._push_call_value(_Value(DOUBLE, _ScalarInfo(8, 8, True, is_float=True), "xmm2"))

        with self.assertRaisesRegex(CodegenError, "requires atomic pointer argument"):
            gen._emit_atomic_pointer_arg(CallExpr(Identifier("__atomic_load_n"), []), 0, "rcx")
        with self.assertRaisesRegex(CodegenError, "requires pointer atomic argument"):
            gen._emit_atomic_pointer_arg(
                CallExpr(Identifier("__atomic_load_n"), [typed_expr(IntLiteral("1"), INT)]),
                0,
                "rcx",
            )

        original_emit_expr = gen._emit_expr

        def emit_pointer_arg(_expr, _target: str = "rax") -> _Value:
            return _Value(INT.pointer_to(), _ScalarInfo(8, 8, False), "rax")

        gen._emit_expr = emit_pointer_arg
        try:
            pointee, info = gen._emit_atomic_pointer_arg(
                CallExpr(Identifier("__atomic_load_n"), [Identifier("p")]), 0, "rcx"
            )
        finally:
            gen._emit_expr = original_emit_expr
        self.assertEqual((pointee, info), (INT, _ScalarInfo(4, 4, True)))

    def test_helper_builtin_atomic_unary_and_binary_edges(self) -> None:
        result = compile_source(
            """
struct S { int field; };
int f(void) { return 0; }
""",
            filename="x86_builtin_atomic_expr_helper_edges.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)
        gen._func = result.unit.functions[0]
        gen._func_sym = result.sema.functions["f"]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        unknown_atomic_callee = typed_expr(
            Identifier("__atomic_unknown"), INT.function_of(())
        )
        unknown_atomic = typed_expr(CallExpr(unknown_atomic_callee, []), INT)
        with self.assertRaisesRegex(CodegenError, "Unknown identifier"):
            gen._emit_call(unknown_atomic, "rax")

        with self.assertRaisesRegex(CodegenError, "requires size argument"):
            gen._emit_alloca_builtin(
                "__builtin_alloca", CallExpr(Identifier("__builtin_alloca"), []), "rax"
            )

        float_alloca = typed_expr(
            CallExpr(
                Identifier("__builtin_alloca"),
                [typed_expr(FloatLiteral("1.0"), DOUBLE)],
            ),
            VOID.pointer_to(),
        )
        with self.assertRaisesRegex(CodegenError, "requires integer size"):
            gen._emit_alloca_builtin("__builtin_alloca", float_alloca, "rax")

        original_emit_expr = gen._emit_expr

        def emit_r10_integer(_expr, _target: str = "rax") -> _Value:
            return _Value(INT, _ScalarInfo(4, 4, True), "r10")

        alloca = typed_expr(
            CallExpr(Identifier("__builtin_alloca"), [typed_expr(IntLiteral("8"), INT)]),
            VOID.pointer_to(),
        )
        gen._emit_expr = emit_r10_integer
        try:
            alloca_value = gen._emit_alloca_builtin("__builtin_alloca", alloca, "r11")
        finally:
            gen._emit_expr = original_emit_expr
        self.assertEqual(alloca_value.reg, "r11")
        self.assertIn("    mov eax, r10d", gen._lines)

        gen._emit_expr = emit_r10_integer
        try:
            alloca_rsp_value = gen._emit_alloca_builtin("__builtin_alloca", alloca, "rsp")
        finally:
            gen._emit_expr = original_emit_expr
        self.assertEqual(alloca_rsp_value.reg, "rsp")

        with self.assertRaisesRegex(CodegenError, "requires argument"):
            gen._emit_integer_bit_builtin(
                "__builtin_ctz", CallExpr(Identifier("__builtin_ctz"), []), "rax"
            )

        float_bits = typed_expr(
            CallExpr(Identifier("__builtin_ctz"), [typed_expr(FloatLiteral("1.0"), DOUBLE)]),
            INT,
        )
        with self.assertRaisesRegex(CodegenError, "requires integer argument"):
            gen._emit_integer_bit_builtin("__builtin_ctz", float_bits, "rax")

        bit_count = typed_expr(
            CallExpr(Identifier("__builtin_ctz"), [typed_expr(IntLiteral("16"), INT)]),
            INT,
        )
        gen._emit_expr = emit_r10_integer
        try:
            bit_value = gen._emit_integer_bit_builtin("__builtin_ctz", bit_count, "r10")
        finally:
            gen._emit_expr = original_emit_expr
        self.assertEqual(bit_value.reg, "r10")
        self.assertIn("    bsf eax, eax", gen._lines)
        self.assertIn("    mov r10d, eax", gen._lines)

        popcount = typed_expr(
            CallExpr(Identifier("__builtin_popcount"), [typed_expr(IntLiteral("7"), INT)]),
            INT,
        )
        gen._emit_expr = emit_r10_integer
        try:
            popcount_value = gen._emit_integer_bit_builtin("__builtin_popcount", popcount, "rax")
        finally:
            gen._emit_expr = original_emit_expr
        self.assertEqual(popcount_value.reg, "rax")
        self.assertIn("popcount_loop", "\n".join(gen._lines))

        gen._emit_expr = emit_r10_integer
        try:
            passthrough_bit_value = gen._emit_integer_bit_builtin("__builtin_ffs", popcount, "rax")
        finally:
            gen._emit_expr = original_emit_expr
        self.assertEqual(passthrough_bit_value.reg, "rax")

        def emit_atomic_operand(expr, _target: str = "rax") -> _Value:
            if isinstance(expr, Identifier) and expr.name == "ptr":
                return _Value(INT.pointer_to(), _ScalarInfo(8, 8, False), "rbx")
            if isinstance(expr, Identifier) and expr.name == "expected":
                return _Value(INT.pointer_to(), _ScalarInfo(8, 8, False), "rdx")
            return _Value(INT, _ScalarInfo(4, 4, True), "rdx")

        gen._emit_expr = emit_atomic_operand
        try:
            fetch_add = gen._emit_atomic_builtin(
                "__atomic_fetch_add",
                CallExpr(
                    Identifier("__atomic_fetch_add"), [Identifier("ptr"), Identifier("value")]
                ),
                "rax",
            )
            fetch_or = gen._emit_atomic_builtin(
                "__atomic_fetch_or",
                CallExpr(Identifier("__atomic_fetch_or"), [Identifier("ptr"), Identifier("value")]),
                "rax",
            )
            compare_exchange = gen._emit_atomic_builtin(
                "__atomic_compare_exchange_n",
                CallExpr(
                    Identifier("__atomic_compare_exchange_n"),
                    [Identifier("ptr"), Identifier("expected"), Identifier("desired")],
                ),
                "r8",
            )
        finally:
            gen._emit_expr = original_emit_expr
        self.assertEqual(fetch_add, _Value(INT, _ScalarInfo(4, 4, True), "rax"))
        self.assertEqual(fetch_or, _Value(INT, _ScalarInfo(4, 4, True), "rax"))
        self.assertEqual(compare_exchange, _Value(INT, _ScalarInfo(4, 4, False), "r8"))
        self.assertIn("    mov eax, edx", gen._lines)
        self.assertIn("    mov r10d, edx", gen._lines)
        self.assertIn("    mov r11d, edx", gen._lines)
        self.assertIn("    mov r8d, r10d", gen._lines)
        self.assertIsNone(
            gen._emit_atomic_builtin(
                "__atomic_unknown", CallExpr(Identifier("__atomic_unknown"), []), "rax"
            )
        )

        def emit_scalar_or_record_pointer(expr, target: str = "rax") -> _Value:
            if isinstance(expr, Identifier) and expr.name == "record_ptr":
                return _Value(Type("struct S").pointer_to(), _ScalarInfo(8, 8, False), target)
            if isinstance(expr, Identifier) and expr.name == "scalar":
                return _Value(INT, _ScalarInfo(4, 4, True), target)
            return original_emit_expr(expr, target)

        gen._emit_expr = emit_scalar_or_record_pointer
        try:
            record_deref = typed_expr(
                UnaryExpr("*", typed_expr(Identifier("record_ptr"), Type("struct S").pointer_to())),
                Type("struct S"),
            )
            self.assertEqual(gen._emit_unary(record_deref, "r10").type_, Type("struct S"))
            bad_deref = typed_expr(UnaryExpr("*", typed_expr(Identifier("scalar"), INT)), INT)
            with self.assertRaisesRegex(CodegenError, "Cannot dereference non-pointer"):
                gen._emit_unary(bad_deref, "rax")
        finally:
            gen._emit_expr = original_emit_expr

        unary_plus = typed_expr(UnaryExpr("+", typed_expr(IntLiteral("1"), INT)), INT)
        self.assertEqual(gen._emit_unary(unary_plus, "r10").reg, "r10")
        float_neg = typed_expr(UnaryExpr("-", typed_expr(FloatLiteral("1.0"), DOUBLE)), DOUBLE)
        self.assertEqual(gen._emit_unary(float_neg, "xmm1").reg, "xmm1")
        unsupported_unary = typed_expr(UnaryExpr("@", typed_expr(IntLiteral("1"), INT)), INT)
        with self.assertRaisesRegex(CodegenError, "does not support unary @"):
            gen._emit_unary(unsupported_unary, "rax")

        unsigned_int = Type("unsigned int")
        unsigned_division = typed_expr(
            BinaryExpr(
                "/",
                typed_expr(IntLiteral("9"), unsigned_int),
                typed_expr(IntLiteral("2"), unsigned_int),
            ),
            unsigned_int,
        )
        self.assertEqual(gen._emit_binary(unsigned_division, "r10").reg, "r10")
        shift = typed_expr(
            BinaryExpr(">>", typed_expr(IntLiteral("8"), INT), typed_expr(IntLiteral("1"), INT)),
            INT,
        )
        self.assertEqual(gen._emit_binary(shift, "rax").reg, "rax")
        bad_common_type = typed_expr(
            BinaryExpr(
                "+",
                typed_expr(Identifier("left_record"), Type("struct S")),
                typed_expr(Identifier("right_record"), Type("struct S")),
            ),
            INT,
        )
        with self.assertRaisesRegex(CodegenError, "cannot convert operands"):
            gen._emit_binary(bad_common_type, "rax")
        with self.assertRaisesRegex(CodegenError, "cannot convert floating operands"):
            gen._emit_float_binary(bad_common_type, "rax")
        integer_float_path = typed_expr(
            BinaryExpr("+", typed_expr(IntLiteral("1"), INT), typed_expr(IntLiteral("2"), INT)),
            INT,
        )
        with self.assertRaisesRegex(CodegenError, "expected floating operands"):
            gen._emit_float_binary(integer_float_path, "rax")

        float_sum = typed_expr(
            BinaryExpr(
                "+",
                typed_expr(FloatLiteral("1.0"), DOUBLE),
                typed_expr(FloatLiteral("2.0"), DOUBLE),
            ),
            DOUBLE,
        )
        self.assertEqual(gen._emit_float_binary(float_sum, "xmm1").reg, "xmm1")
        self.assertIn("    movsd xmm1, xmm0", gen._lines)

        float_compare = typed_expr(
            BinaryExpr(
                "<",
                typed_expr(FloatLiteral("1.0"), DOUBLE),
                typed_expr(FloatLiteral("2.0"), DOUBLE),
            ),
            INT,
        )
        self.assertEqual(gen._emit_float_binary(float_compare, "r10").reg, "r10")
        self.assertIn("    mov r10d, eax", gen._lines)

        unsupported_float = typed_expr(
            BinaryExpr(
                "%",
                typed_expr(FloatLiteral("3.0"), DOUBLE),
                typed_expr(FloatLiteral("2.0"), DOUBLE),
            ),
            DOUBLE,
        )
        with self.assertRaisesRegex(CodegenError, "does not support floating binary %"):
            gen._emit_float_binary(unsupported_float, "xmm0")
        unsupported_binary = typed_expr(
            BinaryExpr("@", typed_expr(IntLiteral("1"), INT), typed_expr(IntLiteral("2"), INT)),
            INT,
        )
        with self.assertRaisesRegex(CodegenError, "does not support binary @"):
            gen._emit_binary(unsupported_binary, "rax")

    def test_helper_aggregate_return_and_call_argument_edges(self) -> None:
        result = compile_source(
            """
struct Mixed { double d; int i; };
struct Big { long a; long b; long c; };
struct ThreeInts { int a; int b; int c; };
int f(void) { return 0; }
""",
            filename="x86_aggregate_return_arg_helper_edges.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)
        gen._func = result.unit.functions[0]
        gen._func_sym = result.sema.functions["f"]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        with self.assertRaisesRegex(CodegenError, "cannot size aggregate return"):
            gen._emit_small_aggregate_return_from_expr(IntLiteral("0"), Type("struct Missing"))

        with self.assertRaisesRegex(CodegenError, "missing indirect aggregate return slot"):
            gen._emit_indirect_aggregate_return(IntLiteral("0"), Type("struct Big"))

        gen._sret_slot = _Slot(32, Type("struct Big").pointer_to(), _ScalarInfo(8, 8, False))
        with self.assertRaisesRegex(CodegenError, "cannot size indirect aggregate return"):
            gen._emit_indirect_aggregate_return(IntLiteral("0"), Type("struct Missing"))

        original_emit_call = gen._emit_call

        def emit_call(_expr, _target: str, aggregate_return_address=None) -> _Value:
            gen._emit(f"; aggregate call {aggregate_return_address or _target}")
            return _Value(Type("struct Big"), _ScalarInfo(24, 8, False), "rax")

        big_call = typed_expr(CallExpr(Identifier("make_big"), []), Type("struct Big"))
        gen._emit_call = emit_call
        try:
            gen._emit_indirect_aggregate_return(big_call, Type("struct Big"))
        finally:
            gen._emit_call = original_emit_call
        self.assertIn("    ; aggregate call rcx", gen._lines)

        original_small_chunks = gen._small_aggregate_return_chunks

        def three_fp_chunks(_type: Type) -> list[_AggregateChunk]:
            return [
                _AggregateChunk(0, _ScalarInfo(8, 8, True, is_float=True)),
                _AggregateChunk(8, _ScalarInfo(8, 8, True, is_float=True)),
                _AggregateChunk(16, _ScalarInfo(8, 8, True, is_float=True)),
            ]

        gen._small_aggregate_return_chunks = three_fp_chunks
        try:
            with self.assertRaisesRegex(CodegenError, "cannot return aggregate FP chunk"):
                gen._emit_aggregate_return_from_address(Type("struct Mixed"), "rcx")
            with self.assertRaisesRegex(CodegenError, "cannot store aggregate FP return chunk"):
                gen._emit_aggregate_return_to_address(Type("struct Mixed"), "rcx")
        finally:
            gen._small_aggregate_return_chunks = original_small_chunks

        def three_integer_chunks(_type: Type) -> list[_AggregateChunk]:
            return [
                _AggregateChunk(0, _ScalarInfo(8, 8, True)),
                _AggregateChunk(8, _ScalarInfo(8, 8, True)),
                _AggregateChunk(16, _ScalarInfo(8, 8, True)),
            ]

        gen._small_aggregate_return_chunks = three_integer_chunks
        try:
            with self.assertRaisesRegex(CodegenError, "cannot return aggregate integer chunk"):
                gen._emit_aggregate_return_from_address(Type("struct Mixed"), "rcx")
            with self.assertRaisesRegex(
                CodegenError, "cannot store aggregate integer return chunk"
            ):
                gen._emit_aggregate_return_to_address(Type("struct Mixed"), "rcx")
        finally:
            gen._small_aggregate_return_chunks = original_small_chunks

        with self.assertRaisesRegex(CodegenError, "cannot size zero aggregate initializer"):
            gen._emit_aggregate_expr_to_address(Type("struct Missing"), IntLiteral("0"), "rcx")

        mismatched = typed_expr(Identifier("big_value"), Type("struct Big"))
        with self.assertRaisesRegex(CodegenError, "cannot initialize aggregate value"):
            gen._emit_aggregate_expr_to_address(Type("struct Mixed"), mismatched, "rcx")

        scalar_two_items = InitList(
            (
                InitItem((), IntLiteral("1")),
                InitItem((), IntLiteral("2")),
            )
        )
        with self.assertRaisesRegex(CodegenError, "requires scalar compound initializer"):
            gen._emit_compound_literal_to_address(INT, scalar_two_items, "rcx")

        scalar_non_expr = InitList((InitItem((), InitList(())),))
        with self.assertRaisesRegex(
            CodegenError, "requires scalar compound initializer expression"
        ):
            gen._emit_compound_literal_to_address(INT, scalar_non_expr, "rcx")

        missing_array_element = InitList(())
        with self.assertRaisesRegex(CodegenError, "cannot initialize non-array as array"):
            gen._emit_array_initializer_to_address(INT, missing_array_element, "rcx")

        unknown_length_array = Type("int", declarator_ops=(("arr", -1),))
        original_complete_array_type = gen._complete_array_initializer_type

        def keep_unknown_array_length(_type: Type, _init: InitList) -> Type:
            return unknown_length_array

        gen._complete_array_initializer_type = keep_unknown_array_length
        try:
            with self.assertRaisesRegex(CodegenError, "requires known compound array length"):
                gen._emit_array_initializer_to_address(unknown_length_array, InitList(()), "rcx")
        finally:
            gen._complete_array_initializer_type = original_complete_array_type

        with self.assertRaisesRegex(CodegenError, "cannot pass indirect aggregate call result"):
            gen._push_aggregate_call_result_arg(big_call, [])

        mixed_call = typed_expr(CallExpr(Identifier("make_mixed"), []), Type("struct Mixed"))
        missing_chunk = _CallArg(
            mixed_call,
            INT,
            _ScalarInfo(4, 4, True),
            "stack",
            0,
            offset=99,
            aggregate_type=Type("struct Mixed"),
        )
        gen._emit_call = emit_call
        try:
            with self.assertRaisesRegex(CodegenError, "cannot find aggregate return chunk"):
                gen._push_aggregate_call_result_arg(mixed_call, [missing_chunk])
        finally:
            gen._emit_call = original_emit_call

        three_ints_call = typed_expr(
            CallExpr(Identifier("make_three"), []), Type("struct ThreeInts")
        )
        int_tail_chunk = _CallArg(
            three_ints_call,
            INT,
            _ScalarInfo(4, 4, True),
            "stack",
            0,
            offset=8,
            aggregate_type=Type("struct ThreeInts"),
        )
        gen._emit_call = emit_call
        try:
            gen._push_aggregate_call_result_arg(three_ints_call, [int_tail_chunk])
        finally:
            gen._emit_call = original_emit_call
        self.assertIn("    mov eax, edx", gen._lines)

        original_push_chunks = gen._push_aggregate_expr_arg_chunks

        def push_mismatched_chunks(expr, _chunks: list[_CallArg]) -> None:
            gen._stack_depth += (
                1 if isinstance(expr, Identifier) and expr.name == "then_value" else 2
            )

        conditional = typed_expr(
            ConditionalExpr(
                typed_expr(IntLiteral("1"), INT),
                typed_expr(Identifier("then_value"), Type("struct Mixed")),
                typed_expr(Identifier("else_value"), Type("struct Mixed")),
            ),
            Type("struct Mixed"),
        )
        gen._push_aggregate_expr_arg_chunks = push_mismatched_chunks
        try:
            with self.assertRaisesRegex(
                CodegenError, "conditional aggregate argument stack mismatch"
            ):
                gen._push_aggregate_conditional_arg(conditional, [])
        finally:
            gen._push_aggregate_expr_arg_chunks = original_push_chunks
            gen._stack_depth = 0

        dispatched: list[str] = []

        def record_call_dispatch(_expr: CallExpr, _chunks: list[_CallArg]) -> None:
            dispatched.append("call")

        def record_conditional_dispatch(_expr: ConditionalExpr, _chunks: list[_CallArg]) -> None:
            dispatched.append("conditional")

        original_push_call_result = gen._push_aggregate_call_result_arg
        original_push_conditional = gen._push_aggregate_conditional_arg
        gen._push_aggregate_call_result_arg = record_call_dispatch
        gen._push_aggregate_conditional_arg = record_conditional_dispatch
        try:
            gen._push_aggregate_expr_arg_chunks(mixed_call, [])
            gen._push_aggregate_expr_arg_chunks(conditional, [])
        finally:
            gen._push_aggregate_call_result_arg = original_push_call_result
            gen._push_aggregate_conditional_arg = original_push_conditional
        self.assertEqual(dispatched, ["call", "conditional"])

        original_emit_address = gen._emit_address

        def emit_address(_expr, target: str) -> None:
            gen._emit(f"; address {target}")

        aggregate_value = typed_expr(Identifier("aggregate_value"), Type("struct Mixed"))
        aggregate_chunks = [
            _CallArg(
                aggregate_value,
                DOUBLE,
                _ScalarInfo(8, 8, True, is_float=True),
                "stack",
                0,
                aggregate_type=Type("struct Mixed"),
            ),
            _CallArg(
                aggregate_value,
                INT,
                _ScalarInfo(4, 4, True),
                "stack",
                1,
                offset=8,
                aggregate_type=Type("struct Mixed"),
            ),
        ]
        gen._emit_address = emit_address
        try:
            gen._push_aggregate_expr_arg_chunks(aggregate_value, aggregate_chunks)
        finally:
            gen._emit_address = original_emit_address
        self.assertIn("    movsd xmm0, [r11]", gen._lines)
        self.assertIn("    mov eax, DWORD PTR [r11 + 8]", gen._lines)

    def test_helper_array_call_assignment_and_access_edges(self) -> None:
        result = compile_source(
            """
struct Mixed { double d; int i; };
struct Big { long a; long b; long c; };
struct Big make_big(void);
double returns_double(void);
int returns_int(void);
int f(void) { return 0; }
""",
            filename="x86_array_call_assignment_helper_edges.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)
        gen._func = result.unit.functions[0]
        gen._func_sym = result.sema.functions["f"]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        int_array = INT.array_of(1)
        original_type_size = gen._type_size

        def unsized_int_array(type_: Type) -> int | None:
            if type_ == int_array:
                return None
            return original_type_size(type_)

        gen._type_size = unsized_int_array
        try:
            with self.assertRaisesRegex(CodegenError, "cannot size compound array literal"):
                gen._emit_array_initializer_to_address(
                    int_array, InitList((InitItem((), IntLiteral("1")),)), "rcx"
                )
        finally:
            gen._type_size = original_type_size

        out_of_range = InitList((InitItem((("index", IntLiteral("3")),), IntLiteral("7")),))
        gen._emit_array_initializer_to_address(int_array, out_of_range, "rcx")

        mixed_array = Type("struct Mixed").array_of(1)
        original_compound_literal = gen._emit_compound_literal_to_address
        original_aggregate_expr = gen._emit_aggregate_expr_to_address
        aggregate_init_calls: list[str] = []

        def record_compound_literal(_type: Type, _init: InitList, _target: str) -> None:
            aggregate_init_calls.append("compound")

        def record_aggregate_expr(_type: Type, _expr, _target: str) -> None:
            aggregate_init_calls.append("expr")

        gen._emit_compound_literal_to_address = record_compound_literal
        try:
            gen._emit_array_initializer_to_address(
                mixed_array, InitList((InitItem((), InitList(())),)), "rcx"
            )
        finally:
            gen._emit_compound_literal_to_address = original_compound_literal

        gen._emit_aggregate_expr_to_address = record_aggregate_expr
        try:
            gen._emit_array_initializer_to_address(
                mixed_array,
                InitList(
                    (
                        InitItem(
                            (),
                            typed_expr(Identifier("mixed_value"), Type("struct Mixed")),
                        ),
                    )
                ),
                "rcx",
            )
        finally:
            gen._emit_aggregate_expr_to_address = original_aggregate_expr
        self.assertEqual(aggregate_init_calls, ["compound", "expr"])

        with self.assertRaisesRegex(CodegenError, "requires aggregate array initializer"):
            gen._emit_array_initializer_to_address(
                mixed_array, InitList((InitItem((), object()),)), "rcx"
            )
        with self.assertRaisesRegex(CodegenError, "requires scalar array initializer"):
            gen._emit_array_initializer_to_address(
                int_array, InitList((InitItem((), InitList(())),)), "rcx"
            )

        gen._scope_stack.append({})
        try:
            with self.assertRaisesRegex(CodegenError, "Unknown static local"):
                gen._emit_decl(
                    DeclStmt(TypeSpec("int"), "missing_static", None, storage_class="static")
                )
        finally:
            gen._scope_stack.pop()

        scalar_decl = DeclStmt(TypeSpec("int"), "scalar_init", InitList(()))
        gen._decl_slots[id(scalar_decl)] = _Slot(8, INT, _ScalarInfo(4, 4, True))
        gen._scope_stack.append({})
        try:
            with self.assertRaisesRegex(CodegenError, "aggregate local initializer"):
                gen._emit_decl(scalar_decl)
        finally:
            gen._scope_stack.pop()
            gen._decl_slots.pop(id(scalar_decl), None)

        array_decl = DeclStmt(TypeSpec("int"), "array_expr", IntLiteral("1"))
        gen._decl_slots[id(array_decl)] = _Slot(16, int_array, _ScalarInfo(4, 4, False))
        gen._scope_stack.append({})
        try:
            with self.assertRaisesRegex(CodegenError, "cannot initialize array from expression"):
                gen._emit_decl(array_decl)
        finally:
            gen._scope_stack.pop()
            gen._decl_slots.pop(id(array_decl), None)

        unsupported_expr = typed_expr(NullStmt(), INT)
        with self.assertRaisesRegex(CodegenError, "NullStmt"):
            gen._emit_expr(unsupported_expr, "rax")

        big_call = typed_expr(CallExpr(Identifier("make_big"), []), Type("struct Big"))
        with self.assertRaisesRegex(CodegenError, "needs address for indirect aggregate return"):
            gen._emit_call(big_call, "rax")

        double_call = typed_expr(CallExpr(Identifier("returns_double"), []), DOUBLE)
        self.assertEqual(gen._emit_call(double_call, "xmm1").reg, "xmm1")
        int_call = typed_expr(CallExpr(Identifier("returns_int"), []), INT)
        self.assertEqual(gen._emit_call(int_call, "r10").reg, "r10")

        logic = typed_expr(
            BinaryExpr("||", typed_expr(IntLiteral("0"), INT), typed_expr(IntLiteral("1"), INT)),
            INT,
        )
        self.assertEqual(gen._emit_short_circuit(logic, "r10").reg, "r10")

        pointer_type = INT.pointer_to()
        bad_pointer_binary = typed_expr(
            BinaryExpr(
                "*",
                typed_expr(Identifier("left_ptr"), pointer_type),
                typed_expr(Identifier("right_ptr"), pointer_type),
            ),
            INT,
        )
        with self.assertRaisesRegex(CodegenError, "does not support pointer binary"):
            gen._emit_pointer_binary(bad_pointer_binary, "rax")

        missing_aggregate = typed_expr(Identifier("missing_aggregate"), Type("struct Missing"))
        missing_assign = typed_expr(
            AssignExpr(
                "=", missing_aggregate, typed_expr(Identifier("rhs"), Type("struct Missing"))
            ),
            Type("struct Missing"),
        )
        with self.assertRaisesRegex(CodegenError, "cannot size aggregate assignment target"):
            gen._emit_assign(missing_assign, "rax")

        original_emit_expr = gen._emit_expr
        original_record_access = gen._record_member_access
        original_member_address = gen._emit_member_access_address
        original_emit_address = gen._emit_address

        def bitfield_access(_expr) -> _MemberAccess:
            return _MemberAccess(0, INT, 0, 3)

        def emit_member_address(_expr, target: str, _access: _MemberAccess) -> None:
            gen._emit(f"; member address {target}")

        def emit_r10_integer(_expr, _target: str = "rax") -> _Value:
            return _Value(INT, _ScalarInfo(4, 4, True), "r10")

        member = typed_expr(MemberExpr(Identifier("bits"), "flag", False), INT)
        bitfield_assign = typed_expr(
            AssignExpr("=", member, typed_expr(IntLiteral("1"), INT)),
            INT,
        )
        gen._record_member_access = bitfield_access
        gen._emit_member_access_address = emit_member_address
        gen._emit_expr = emit_r10_integer
        try:
            self.assertEqual(gen._emit_assign(bitfield_assign, "r11").reg, "rax")
        finally:
            gen._record_member_access = original_record_access
            gen._emit_member_access_address = original_member_address
            gen._emit_expr = original_emit_expr
        self.assertIn("    mov eax, r10d", gen._lines)

        def emit_address(_expr, target: str) -> None:
            gen._emit(f"; address {target}")

        pointer_target = typed_expr(Identifier("ptr"), pointer_type)
        pointer_offset = typed_expr(FloatLiteral("1.0"), DOUBLE)
        pointer_assign = typed_expr(AssignExpr("+=", pointer_target, pointer_offset), pointer_type)
        gen._emit_address = emit_address
        gen._emit_expr = lambda _expr, _target="rax": _Value(
            DOUBLE, _ScalarInfo(8, 8, True, is_float=True), "xmm0"
        )
        try:
            with self.assertRaisesRegex(CodegenError, "requires integer pointer offset"):
                gen._emit_compound_assign(pointer_assign, "rax")
        finally:
            gen._emit_expr = original_emit_expr

        pointer_int_assign = typed_expr(
            AssignExpr("+=", pointer_target, typed_expr(IntLiteral("2"), INT)), pointer_type
        )
        gen._emit_expr = lambda _expr, _target="rax": _Value(INT, _ScalarInfo(4, 4, True), "rax")
        try:
            self.assertEqual(gen._emit_compound_assign(pointer_int_assign, "r10").reg, "r10")
        finally:
            gen._emit_expr = original_emit_expr
            gen._emit_address = original_emit_address
        self.assertIn("    mov r10, rax", gen._lines)

        with self.assertRaisesRegex(CodegenError, "does not support compound assignment @="):
            gen._emit_integer_compound_op("@", _ScalarInfo(4, 4, True))

        float_assign = typed_expr(
            AssignExpr(
                "+=", typed_expr(Identifier("flt"), DOUBLE), typed_expr(FloatLiteral("1.0"), DOUBLE)
            ),
            DOUBLE,
        )
        with self.assertRaisesRegex(CodegenError, "does not support floating compound assignment"):
            gen._emit_float_compound_assign(
                float_assign, "%", DOUBLE, _ScalarInfo(8, 8, True, is_float=True), "xmm0"
            )

        gen._emit_address = emit_address
        gen._emit_expr = lambda _expr, _target="xmm0": _Value(
            DOUBLE, _ScalarInfo(8, 8, True, is_float=True), "xmm2"
        )
        try:
            self.assertEqual(
                gen._emit_float_compound_assign(
                    float_assign, "+", DOUBLE, _ScalarInfo(8, 8, True, is_float=True), "xmm1"
                ).reg,
                "xmm1",
            )
        finally:
            gen._emit_expr = original_emit_expr
            gen._emit_address = original_emit_address

        bad_subscript = typed_expr(
            SubscriptExpr(typed_expr(Identifier("scalar"), INT), typed_expr(IntLiteral("0"), INT)),
            INT,
        )
        with self.assertRaisesRegex(CodegenError, "Subscript requires array or pointer base"):
            gen._emit_subscript(bad_subscript, "rax")

        aggregate_subscript = typed_expr(
            SubscriptExpr(
                typed_expr(Identifier("mixed_array"), mixed_array),
                typed_expr(IntLiteral("0"), INT),
            ),
            Type("struct Mixed"),
        )
        gen._emit_address = emit_address
        try:
            self.assertEqual(
                gen._emit_subscript(aggregate_subscript, "r10").type_, Type("struct Mixed")
            )
        finally:
            gen._emit_address = original_emit_address

        def aggregate_member_access(_expr) -> _MemberAccess:
            return _MemberAccess(0, Type("struct Mixed"))

        gen._record_member_access = aggregate_member_access
        gen._emit_member_access_address = emit_member_address
        try:
            self.assertEqual(
                gen._emit_member(MemberExpr(Identifier("holder"), "field", False), "r11").type_,
                Type("struct Mixed"),
            )
        finally:
            gen._record_member_access = original_record_access
            gen._emit_member_access_address = original_member_address

    def test_helper_address_sizeof_and_initializer_edges(self) -> None:
        result = compile_source(
            """
extern int external_data;
int callee(void);
struct Mixed { double d; int i; };
struct Big { long a; long b; long c; };
union Small { int i; char c; };
int f(void) { struct Mixed local_mixed; return 0; }
""",
            filename="x86_address_sizeof_initializer_helper_edges.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)
        gen._func = next(function for function in result.unit.functions if function.name == "f")
        gen._func_sym = result.sema.functions["f"]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        class BrokenArray(Type):
            def element_type(self) -> Type | None:
                return None

        gen._static_locals[("f", "loose_static")] = _StaticLocal(".L.f.loose_static", INT, None)
        self.assertEqual(gen._emit_address(Identifier("loose_static"), "r10"), INT)
        self.assertIn("    lea r10, [rip + .L.f.loose_static]", gen._lines)

        old_scope_stack = gen._scope_stack
        gen._scope_stack = [{"cached_static": _Slot(0, INT, _ScalarInfo(4, 4, True))}]
        try:
            gen._emit_decl(DeclStmt(TypeSpec("int"), "cached_static", None, storage_class="static"))
        finally:
            gen._scope_stack = old_scope_stack

        callee = typed_expr(Identifier("callee"), INT.function_of(()))
        self.assertEqual(gen._emit_address(callee, "r11"), INT.function_of(()))
        self.assertIn("callee", "\n".join(gen._lines))

        self.assertEqual(gen._emit_address(Identifier("external_data"), "rax"), INT)
        with self.assertRaisesRegex(CodegenError, "Unknown identifier address"):
            gen._emit_address(Identifier("missing_address"), "rax")
        file_scope = gen._sema.file_scope
        object.__setattr__(gen._sema, "file_scope", None)
        try:
            with self.assertRaisesRegex(CodegenError, "Unknown identifier address"):
                gen._emit_address(Identifier("missing_no_scope_address"), "rax")
            with self.assertRaisesRegex(CodegenError, "Unknown identifier"):
                gen._emit_identifier(Identifier("missing_no_scope_value"), "rax")
        finally:
            object.__setattr__(gen._sema, "file_scope", file_scope)

        compound_literal = typed_expr(
            CompoundLiteralExpr(TypeSpec("int"), InitList((InitItem((), IntLiteral("1")),))),
            INT,
        )
        with self.assertRaisesRegex(CodegenError, "missing compound literal storage"):
            gen._emit_address(compound_literal, "rax")
        gen._compound_literal_slots[id(compound_literal)] = _Slot(40, INT, _ScalarInfo(4, 4, True))
        gen._type_map.set(compound_literal.initializer.items[0].initializer, INT)
        self.assertEqual(gen._emit_address(compound_literal, "r10"), INT)
        self.assertIn("    mov r10, rcx", gen._lines)

        mixed_literal = typed_expr(
            CompoundLiteralExpr(TypeSpec("struct", record_tag="Mixed"), InitList(())),
            Type("struct Mixed"),
        )
        gen._compound_literal_slots[id(mixed_literal)] = _Slot(
            56, Type("struct Mixed"), _ScalarInfo(16, 8, False)
        )
        self.assertEqual(gen._emit_compound_literal(mixed_literal, "rcx").reg, "rcx")
        self.assertEqual(gen._emit_address(mixed_literal, "rcx"), Type("struct Mixed"))

        scalar_call = typed_expr(CallExpr(Identifier("callee"), []), INT)
        with self.assertRaisesRegex(CodegenError, "cannot form address of scalar call result"):
            gen._emit_address(scalar_call, "rax")

        original_emit_call = gen._emit_call

        def emit_call(_expr, _target: str, aggregate_return_address=None) -> _Value:
            gen._emit(f"; call result {aggregate_return_address or _target}")
            return _Value(Type("struct Mixed"), _ScalarInfo(16, 8, False), "rax")

        mixed_call = typed_expr(CallExpr(Identifier("make_mixed"), []), Type("struct Mixed"))
        gen._aggregate_call_slots[id(mixed_call)] = _Slot(
            64, Type("struct Mixed"), _ScalarInfo(16, 8, False)
        )
        gen._emit_call = emit_call
        try:
            self.assertEqual(gen._emit_address(mixed_call, "r9"), Type("struct Mixed"))
        finally:
            gen._emit_call = original_emit_call
        self.assertIn("    lea r9, [rbp - 64]", gen._lines)

        big_call = typed_expr(CallExpr(Identifier("make_big"), []), Type("struct Big"))
        gen._aggregate_call_slots[id(big_call)] = _Slot(
            96, Type("struct Big"), _ScalarInfo(24, 8, False)
        )
        gen._emit_call = emit_call
        try:
            self.assertEqual(gen._emit_address(big_call, "r8"), Type("struct Big"))
        finally:
            gen._emit_call = original_emit_call
        self.assertIn("    ; call result rcx", gen._lines)

        mismatched_return_call = typed_expr(CallExpr(Identifier("make_big"), []), Type("struct Big"))
        original_emit_address_for_return = gen._emit_address
        original_aggregate_return_from_address = gen._emit_aggregate_return_from_address
        gen._emit_address = lambda _expr, _target: Type("struct Big")
        gen._emit_aggregate_return_from_address = (
            lambda _type, _address_reg: gen._emit("; aggregate return")
        )
        try:
            gen._emit_aggregate_return(mismatched_return_call, Type("struct Mixed"))
        finally:
            gen._emit_aggregate_return_from_address = original_aggregate_return_from_address
            gen._emit_address = original_emit_address_for_return

        aggregate_conditional = typed_expr(
            ConditionalExpr(
                typed_expr(IntLiteral("1"), INT),
                typed_expr(Identifier("then_mixed"), Type("struct Mixed")),
                typed_expr(Identifier("else_mixed"), Type("struct Mixed")),
            ),
            Type("struct Mixed"),
        )
        original_branch_if_zero = gen._emit_branch_if_zero
        original_emit_expr_for_conditional = gen._emit_expr

        def emit_aggregate_expr(expr, target: str = "rax") -> _Value:
            if expr is aggregate_conditional.condition:
                return _Value(INT, _ScalarInfo(4, 4, True), "rax")
            return _Value(Type("struct Mixed"), _ScalarInfo(16, 8, False), target)

        gen._emit_branch_if_zero = lambda _expr, label: gen._emit(f"; branch {label}")
        gen._emit_expr = emit_aggregate_expr
        try:
            conditional_value = gen._emit_conditional(aggregate_conditional, "r10")
        finally:
            gen._emit_expr = original_emit_expr_for_conditional
            gen._emit_branch_if_zero = original_branch_if_zero
        self.assertEqual(conditional_value.type_, Type("struct Mixed"))

        original_emit_expr = gen._emit_expr
        gen._emit_expr = lambda _expr, _target="rax": _Value(INT, _ScalarInfo(4, 4, True), "rax")
        try:
            with self.assertRaisesRegex(CodegenError, "Cannot dereference non-pointer"):
                gen._emit_address(UnaryExpr("*", typed_expr(Identifier("scalar"), INT)), "rax")
        finally:
            gen._emit_expr = original_emit_expr

        pointer_to_missing = Type("struct Missing").pointer_to()

        def emit_subscript_expr(expr, _target: str = "rax") -> _Value:
            if isinstance(expr, Identifier) and expr.name == "missing_ptr":
                return _Value(pointer_to_missing, _ScalarInfo(8, 8, False), "rax")
            return _Value(INT, _ScalarInfo(4, 4, True), "rax")

        missing_subscript = typed_expr(
            SubscriptExpr(
                typed_expr(Identifier("missing_ptr"), pointer_to_missing),
                typed_expr(IntLiteral("0"), INT),
            ),
            Type("struct Missing"),
        )
        gen._emit_expr = emit_subscript_expr
        try:
            with self.assertRaisesRegex(CodegenError, "cannot size subscript element"):
                gen._emit_address(missing_subscript, "rax")
        finally:
            gen._emit_expr = original_emit_expr

        bad_subscript = typed_expr(
            SubscriptExpr(typed_expr(Identifier("scalar"), INT), typed_expr(IntLiteral("0"), INT)),
            INT,
        )
        gen._emit_expr = lambda _expr, _target="rax": _Value(INT, _ScalarInfo(4, 4, True), "rax")
        try:
            with self.assertRaisesRegex(CodegenError, "Subscript requires array or pointer base"):
                gen._emit_address(bad_subscript, "rax")
        finally:
            gen._emit_expr = original_emit_expr

        comma_address = CommaExpr(typed_expr(IntLiteral("0"), INT), Identifier("loose_static"))
        self.assertEqual(gen._emit_address(comma_address, "r10"), INT)

        original_member_address = gen._emit_member_access_address

        def bitfield_member_address(_expr, _target: str, _access=None) -> _MemberAccess:
            return _MemberAccess(0, INT, 0, 3)

        gen._emit_member_access_address = bitfield_member_address
        try:
            with self.assertRaisesRegex(CodegenError, "cannot take address of bit-field member"):
                gen._emit_address(MemberExpr(Identifier("bits"), "flag", False), "rax")
        finally:
            gen._emit_member_access_address = original_member_address

        with self.assertRaisesRegex(CodegenError, "cannot form address of NullStmt"):
            gen._emit_address(NullStmt(), "rax")

        gen._emit_expr = lambda _expr, _target="rax": _Value(INT, _ScalarInfo(4, 4, True), "rax")
        try:
            with self.assertRaisesRegex(CodegenError, "Arrow base is not pointer"):
                gen._emit_member_storage_address(
                    MemberExpr(typed_expr(Identifier("not_pointer"), INT), "field", True),
                    "rax",
                )
        finally:
            gen._emit_expr = original_emit_expr

        sizeof_missing = typed_expr(
            SizeofExpr(None, TypeSpec("struct", record_tag="Missing")),
            Type("unsigned long"),
        )
        with self.assertRaisesRegex(CodegenError, "cannot size struct Missing"):
            gen._emit_sizeof(sizeof_missing, "rax")

        align_missing = typed_expr(
            AlignofExpr(None, TypeSpec("struct", record_tag="Missing")),
            Type("unsigned long"),
        )
        with self.assertRaisesRegex(CodegenError, "cannot align struct Missing"):
            gen._emit_alignof(align_missing, "rax")

        self.assertEqual(
            gen._sizeof_operand_type(SizeofExpr(MemberExpr(Identifier("local_mixed"), "d", False), None)),
            DOUBLE,
        )
        self.assertEqual(
            gen._sizeof_operand_type(
                SizeofExpr(
                    MemberExpr(
                        typed_expr(Identifier("mixed_sizeof_base"), Type("struct Mixed")),
                        "i",
                        False,
                    ),
                    None,
                )
            ),
            INT,
        )
        with self.assertRaisesRegex(CodegenError, "cannot resolve sizeof operand type"):
            gen._sizeof_operand_type(SizeofExpr(Identifier("callee"), None))
        with self.assertRaisesRegex(CodegenError, "cannot resolve sizeof operand type"):
            gen._sizeof_operand_type(SizeofExpr(IntLiteral("1"), None))
        with self.assertRaisesRegex(CodegenError, "cannot resolve sizeof operand type"):
            gen._sizeof_operand_type(
                SizeofExpr(
                    MemberExpr(
                        typed_expr(Identifier("bad_sizeof_base"), Type("struct Mixed")),
                        "missing",
                        False,
                    ),
                    None,
                )
            )
        with self.assertRaisesRegex(CodegenError, "cannot resolve sizeof operand type"):
            gen._sizeof_operand_type(SizeofExpr(MemberExpr(FloatLiteral("1.0"), "missing", False), None))
        with self.assertRaisesRegex(CodegenError, "cannot resolve sizeof operand type"):
            gen._sizeof_operand_type(SizeofExpr(MemberExpr(Identifier("callee"), "missing", False), None))

        offsetof_missing = typed_expr(
            BuiltinOffsetofExpr(TypeSpec("struct", record_tag="Mixed"), "missing"),
            Type("unsigned long"),
        )
        with self.assertRaisesRegex(CodegenError, "cannot evaluate __builtin_offsetof"):
            gen._emit_offsetof(offsetof_missing, "rax")

        with self.assertRaisesRegex(CodegenError, "array initializer needs array destination"):
            gen._emit_local_array_initializer(_Slot(8, INT, _ScalarInfo(4, 4, True)), InitList(()))

        unknown_array = Type("int", declarator_ops=(("arr", -1),))
        with self.assertRaisesRegex(CodegenError, "requires known local array length"):
            gen._emit_local_array_initializer(
                _Slot(16, unknown_array, _ScalarInfo(0, 1, False)), InitList(())
            )

        int_array = INT.array_of(1)
        gen._emit_local_array_initializer(
            _Slot(24, int_array, _ScalarInfo(4, 4, False)),
            InitList((InitItem((("index", IntLiteral("4")),), IntLiteral("9")),)),
        )

        mixed_array = Type("struct Mixed").array_of(1)
        original_record_init = gen._emit_record_compound_initializer_to_address
        original_aggregate_expr = gen._emit_aggregate_expr_to_address
        local_aggregate_calls: list[str] = []

        def record_local_record_init(_type: Type, _init: InitList, _target: str) -> None:
            local_aggregate_calls.append("record")

        def record_local_aggregate_expr(_type: Type, _expr, _target: str) -> None:
            local_aggregate_calls.append("expr")

        gen._emit_record_compound_initializer_to_address = record_local_record_init
        try:
            gen._emit_local_array_initializer(
                _Slot(32, mixed_array, _ScalarInfo(16, 8, False)),
                InitList((InitItem((), InitList(())),)),
            )
        finally:
            gen._emit_record_compound_initializer_to_address = original_record_init

        gen._emit_aggregate_expr_to_address = record_local_aggregate_expr
        try:
            gen._emit_local_array_initializer(
                _Slot(48, mixed_array, _ScalarInfo(16, 8, False)),
                InitList(
                    (InitItem((), typed_expr(Identifier("mixed_value"), Type("struct Mixed"))),)
                ),
            )
        finally:
            gen._emit_aggregate_expr_to_address = original_aggregate_expr
        self.assertEqual(local_aggregate_calls, ["record", "expr"])

        with self.assertRaisesRegex(CodegenError, "requires aggregate array initializer"):
            gen._emit_local_array_initializer(
                _Slot(64, mixed_array, _ScalarInfo(16, 8, False)),
                InitList((InitItem((), object()),)),
            )
        with self.assertRaisesRegex(CodegenError, "only supports scalar array initializers"):
            gen._emit_local_array_initializer(
                _Slot(80, int_array, _ScalarInfo(4, 4, False)),
                InitList((InitItem((), InitList(())),)),
            )
        nested_array = INT.array_of(2).array_of(1)
        with self.assertRaisesRegex(CodegenError, "only supports record array initializers"):
            gen._emit_local_array_initializer(
                _Slot(84, nested_array, _ScalarInfo(8, 4, False)),
                InitList((InitItem((), InitList((InitItem((), IntLiteral("1")),))),)),
            )

        char_unknown = Type("char", declarator_ops=(("arr", -1),))
        with self.assertRaisesRegex(CodegenError, "requires known char array length"):
            gen._emit_local_char_array_string_initializer(
                _Slot(88, char_unknown, _ScalarInfo(0, 1, False)),
                StringLiteral('"x"'),
            )

        with self.assertRaisesRegex(CodegenError, "aggregate global initializer"):
            gen._emit_global_initializer(
                INT,
                InitList((InitItem((), IntLiteral("1")), InitItem((), IntLiteral("2")))),
            )
        gen._unit.declarations.append(DeclStmt(TypeSpec("int"), "f", IntLiteral("1")))
        gen._collect_globals()

        compound_global = typed_expr(
            CompoundLiteralExpr(TypeSpec("int"), InitList((InitItem((), IntLiteral("7")),))),
            INT,
        )
        gen._emit_global_initializer(INT, compound_global)

        with self.assertRaisesRegex(CodegenError, "cannot initialize non-array as array"):
            gen._emit_global_array_initializer(INT, InitList(()))
        broken_array_type = BrokenArray("int", declarator_ops=(("arr", 1),))
        self.assertIsNone(gen._type_size(broken_array_type))
        broken_array = typed_expr(Identifier("broken_array"), broken_array_type)
        self.assertIsNone(
            gen._global_lvalue_initializer_symbol(SubscriptExpr(broken_array, IntLiteral("0")))
        )
        broken_cast = typed_expr(
            CastExpr(TypeSpec("int", pointer_depth=1), broken_array),
            INT.pointer_to(),
        )
        with self.assertRaisesRegex(CodegenError, "cannot decay array type"):
            gen._emit_cast(broken_cast, "rax")

        original_complete_array_type = gen._complete_array_initializer_type

        def keep_unknown_array_length(_type: Type, _init: InitList) -> Type:
            return unknown_array

        gen._complete_array_initializer_type = keep_unknown_array_length
        try:
            with self.assertRaisesRegex(
                CodegenError, "requires known global array initializer length"
            ):
                gen._emit_global_array_initializer(unknown_array, InitList(()))
        finally:
            gen._complete_array_initializer_type = original_complete_array_type

        with self.assertRaisesRegex(CodegenError, "cannot initialize record struct Missing"):
            gen._emit_global_record_initializer(Type("struct Missing"), InitList(()))

        gen._emit_global_record_initializer(Type("union Small"), InitList(()))
        original_type_size = gen._type_size
        gen._type_size = lambda type_: (
            None if type_ == Type("struct Mixed") else original_type_size(type_)
        )
        try:
            with self.assertRaisesRegex(CodegenError, "cannot size type struct Mixed"):
                gen._emit_global_record_initializer(Type("struct Mixed"), InitList(()))
        finally:
            gen._type_size = original_type_size

        gen._unit.declarations.append(DeclStmt(TypeSpec("int"), "covered_tentative", None))
        gen._unit.declarations.append(
            DeclStmt(TypeSpec("int"), "covered_tentative", IntLiteral("1"))
        )
        gen._unit.declarations.append(
            DeclStmt(TypeSpec("int"), "covered_missing_global", IntLiteral("2"))
        )
        gen._emit_global_data()

        compound_only = _X86_64AsmGen(result)
        compound_only._compound_literals.append(
            (".Lcompound0", INT, InitList((InitItem((), IntLiteral("7")),)))
        )
        compound_only._emit_global_data()
        self.assertIn(".data", compound_only._lines)
        self.assertIn(".Lcompound0:", compound_only._lines)

    def test_helper_scalar_memory_constant_and_symbol_edges(self) -> None:
        result = compile_source(
            """
union Small { int i; char c; };
static int local_static(void) { return 1; }
inline int inline_fn(void) { return 2; }
int extern_fn(void);
int f(void) { enum { LOCAL_ENUM = 5 }; return local_static() + inline_fn() + LOCAL_ENUM; }
""",
            filename="x86_scalar_memory_helper_edges.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)
        gen._func = next(function for function in result.unit.functions if function.name == "f")
        gen._func_sym = result.sema.functions["f"]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        local_enum = gen._lookup_enum_const("LOCAL_ENUM")
        self.assertIsNotNone(local_enum)
        assert local_enum is not None
        self.assertEqual(local_enum.value, 5)

        with self.assertRaisesRegex(CodegenError, "cannot scalarize array type"):
            gen._scalar_info(INT.array_of(2))
        self.assertEqual(gen._scalar_info(Type("union Small")), _ScalarInfo(4, 4, True))
        self.assertEqual(gen._scalar_union_info(Type("union Small")), _ScalarInfo(4, 4, False))
        with self.assertRaisesRegex(CodegenError, "cannot size scalar type"):
            gen._scalar_info(Type("struct Missing"))
        original_type_size = gen._type_size
        gen._type_size = lambda type_: None if type_ == FLOAT else original_type_size(type_)
        try:
            with self.assertRaisesRegex(CodegenError, "cannot size floating type float"):
                gen._scalar_info(FLOAT)
        finally:
            gen._type_size = original_type_size
        with self.assertRaisesRegex(CodegenError, "cannot size aggregate type"):
            gen._slot_info(Type("struct Missing"))

        gen._coerce_value(
            _Value(FLOAT, _ScalarInfo(4, 4, True, is_float=True), "xmm1"),
            DOUBLE,
            _ScalarInfo(8, 8, True, is_float=True),
        )
        gen._coerce_value(
            _Value(FLOAT, _ScalarInfo(4, 4, True, is_float=True), "xmm1"),
            INT,
            _ScalarInfo(4, 4, True),
        )
        gen._coerce_value(
            _Value(Type("unsigned long"), _ScalarInfo(8, 8, False), "rax"),
            DOUBLE,
            _ScalarInfo(8, 8, True, is_float=True),
        )
        gen._coerce_value(
            _Value(INT, _ScalarInfo(4, 4, True), "rax"),
            FLOAT,
            _ScalarInfo(4, 4, True, is_float=True),
        )
        gen._coerce_value(
            _Value(FLOAT, _ScalarInfo(4, 4, True, is_float=True), "xmm0"),
            BOOL,
            _ScalarInfo(1, 1, False),
        )
        gen._coerce_value(
            _Value(BOOL, _ScalarInfo(1, 1, False), "rax"),
            BOOL,
            _ScalarInfo(1, 1, False),
        )
        line_count = len(gen._lines)
        gen._coerce_value(
            _Value(INT, _ScalarInfo(4, 4, True), "rax"), VOID, _ScalarInfo(4, 4, False)
        )
        self.assertEqual(len(gen._lines), line_count)
        gen._coerce_scalar_to_bool(_Value(Type("unsigned short"), _ScalarInfo(2, 2, False), "rax"))
        gen._coerce_register(_ScalarInfo(2, 2, False), _ScalarInfo(4, 4, False), "rax")
        gen._coerce_register(_ScalarInfo(1, 1, True), _ScalarInfo(8, 8, True), "rax")
        gen._coerce_register(_ScalarInfo(4, 4, False), _ScalarInfo(8, 8, False), "rax")
        gen._coerce_register(_ScalarInfo(4, 4, False), _ScalarInfo(2, 2, False), "rax")
        self.assertEqual(
            gen._coerced_reg(
                _Value(FLOAT, _ScalarInfo(4, 4, True, is_float=True), "xmm2"),
                _ScalarInfo(4, 4, True, is_float=True),
            ),
            "xmm2",
        )
        self.assertEqual(
            gen._coerced_reg(
                _Value(FLOAT, _ScalarInfo(4, 4, True, is_float=True), "xmm2"),
                _ScalarInfo(4, 4, True),
            ),
            "rax",
        )

        int_slot = _Slot(16, INT, _ScalarInfo(4, 4, True))
        float_slot = _Slot(24, FLOAT, _ScalarInfo(4, 4, True, is_float=True))
        gen._store_value_to_slot(int_slot, _Value(INT, _ScalarInfo(4, 4, True), "rax"))
        gen._store_value_to_slot(
            float_slot, _Value(FLOAT, _ScalarInfo(4, 4, True, is_float=True), "xmm0")
        )
        gen._emit_copy_memory("rdi", "rsi", 15)
        gen._emit_zero_memory("rdi", 15)
        gen._emit_address_offset("rax", "rbx", 8)
        gen._emit_address_offset("rax", "rbx", 0)
        gen._emit_load_from_address(_ScalarInfo(3, 1, False), "rax", "[rbx]")
        gen._emit_store_to_address(_ScalarInfo(3, 1, False), "rax", "[rbx]")
        gen._emit_load_from_address(_ScalarInfo(8, 8, True, is_float=True), "xmm0", "[rbx]")
        gen._emit_store_to_address(_ScalarInfo(8, 8, True, is_float=True), "xmm0", "[rbx]")

        bit_access = _MemberAccess(0, Type("unsigned int"), 3, 5)
        zero_offset_bit_access = _MemberAccess(0, Type("unsigned int"), 0, 5)
        gen._emit_bitfield_load(zero_offset_bit_access, _ScalarInfo(4, 4, True), "rax", "[rbx]")
        full_width_bit_access = _MemberAccess(0, Type("unsigned int"), 0, 32)
        gen._emit_bitfield_load(full_width_bit_access, _ScalarInfo(4, 4, True), "rax", "[rbx]")
        gen._emit_bitfield_load(bit_access, _ScalarInfo(4, 4, True), "rax", "[rbx]")
        gen._emit_bitfield_load(bit_access, _ScalarInfo(4, 4, False), "rax", "[rbx]")
        gen._emit_bitfield_store(bit_access, _ScalarInfo(4, 4, False), "rax", "[rbx]")
        pointer_bitfield = MemberExpr(Identifier("ptr_bits"), "flag", False)
        gen._type_map.set(pointer_bitfield, INT.pointer_to())
        original_record_member_access = gen._record_member_access
        original_member_access_address = gen._emit_member_access_address
        gen._record_member_access = lambda _expr: _MemberAccess(0, INT.pointer_to(), 0, 3)
        gen._emit_member_access_address = lambda _expr, _target, _access: None
        try:
            gen._emit_update(UpdateExpr("++", pointer_bitfield, False), "rax")
        finally:
            gen._emit_member_access_address = original_member_access_address
            gen._record_member_access = original_record_member_access

        plain_member = MemberExpr(Identifier("plain"), "value", False)
        gen._type_map.set(plain_member, INT)
        original_emit_address = gen._emit_address
        gen._record_member_access = lambda _expr: _MemberAccess(0, INT)
        gen._emit_address = lambda _expr, _target: INT
        try:
            gen._emit_update(UpdateExpr("++", plain_member, False), "rax")
            compound_member_value = IntLiteral("1")
            gen._type_map.set(compound_member_value, INT)
            gen._emit_compound_assign(AssignExpr("+=", plain_member, compound_member_value), "rax")
        finally:
            gen._emit_address = original_emit_address
            gen._record_member_access = original_record_member_access

        char_pointer = Identifier("char_pointer")
        char_pointer_value = IntLiteral("1")
        gen._type_map.set(char_pointer, Type("char").pointer_to())
        gen._type_map.set(char_pointer_value, INT)
        gen._emit_address = lambda _expr, _target: Type("char").pointer_to()
        try:
            gen._emit_compound_assign(AssignExpr("+=", char_pointer, char_pointer_value), "rax")
        finally:
            gen._emit_address = original_emit_address

        aggregate_result_call = typed_expr(
            CallExpr(Identifier("make_small_aggregate"), []), Type("struct SmallReturn")
        )
        original_aggregate_return_uses_memory = gen._aggregate_return_uses_memory
        original_aggregate_return_registers = gen._aggregate_return_registers
        original_emit_call = gen._emit_call
        gen._aggregate_return_uses_memory = lambda _type: False
        gen._aggregate_return_registers = lambda _type: {0: "rax"}
        gen._emit_call = lambda _expr, _target, aggregate_return_address=None: _Value(
            Type("struct SmallReturn"), _ScalarInfo(4, 4, True), "rax"
        )
        try:
            gen._push_aggregate_call_result_arg(
                aggregate_result_call,
                [
                    _CallArg(
                        aggregate_result_call,
                        INT,
                        _ScalarInfo(4, 4, True),
                        "int_reg",
                        0,
                        0,
                        Type("struct SmallReturn"),
                    )
                ],
            )
        finally:
            gen._emit_call = original_emit_call
            gen._aggregate_return_registers = original_aggregate_return_registers
            gen._aggregate_return_uses_memory = original_aggregate_return_uses_memory
        self.assertEqual(
            _X86_64AsmGen._bitfield_op_info(_ScalarInfo(8, 8, True)), _ScalarInfo(8, 8, True)
        )
        gen._emit_and_immediate("rax", _ScalarInfo(4, 4, False), (1 << 32) - 1)
        gen._emit_and_immediate("rax", _ScalarInfo(4, 4, False), 7)
        gen._emit_and_immediate("rax", _ScalarInfo(8, 8, False), 0xFFFFFFFF00000000)
        gen._emit_and_immediate("rdx", _ScalarInfo(8, 8, False), 0xFFFFFFFF00000000)
        gen._emit_load_immediate("rax", 7, _ScalarInfo(4, 4, True))
        with self.assertRaisesRegex(CodegenError, "floating immediates"):
            gen._emit_load_immediate("xmm0", 1, _ScalarInfo(4, 4, True, is_float=True))
        gen._emit_integer_to_64(_Value(INT, _ScalarInfo(4, 4, True), "rax"))
        gen._emit_integer_to_64(_Value(Type("unsigned int"), _ScalarInfo(4, 4, False), "rax"))
        gen._emit_integer_to_64(_Value(Type("packed3"), _ScalarInfo(3, 1, False), "rcx"))
        gen._emit_integer_to_64(_Value(Type("signed char"), _ScalarInfo(1, 1, True), "rax"))
        gen._emit_integer_to_64(_Value(Type("unsigned short"), _ScalarInfo(2, 2, False), "rax"))

        self.assertEqual(_X86_64AsmGen._parse_int_value("077u"), 63)
        self.assertEqual(_X86_64AsmGen._parse_int_value("0b1010LL"), 10)
        self.assertEqual(_X86_64AsmGen._char_value("'ab'"), 0x6162)
        self.assertEqual(_X86_64AsmGen._float_bits("1.0f", 4), 0x3F800000)
        self.assertEqual(gen._eval_int_constant(CharLiteral("'A'")), 65)
        self.assertEqual(gen._eval_int_constant(UnaryExpr("~", IntLiteral("0"))), -1)
        self.assertEqual(gen._eval_int_constant(UnaryExpr("!", IntLiteral("0"))), 1)
        self.assertIsNone(gen._eval_int_constant(UnaryExpr("&", IntLiteral("1"))))
        self.assertEqual(
            gen._eval_int_constant(BinaryExpr("/", IntLiteral("7"), IntLiteral("0"))), None
        )
        self.assertIsNone(
            gen._eval_int_constant(BinaryExpr("+", Identifier("missing"), IntLiteral("1")))
        )
        self.assertEqual(
            gen._eval_int_constant(BinaryExpr("-", IntLiteral("7"), IntLiteral("5"))), 2
        )
        self.assertEqual(
            gen._eval_int_constant(BinaryExpr(">=", IntLiteral("7"), IntLiteral("7"))), 1
        )
        self.assertEqual(gen._eval_int_constant(CastExpr(TypeSpec("int"), FloatLiteral("3.5"))), 3)
        self.assertEqual(gen._eval_int_constant(CommaExpr(IntLiteral("0"), IntLiteral("5"))), 5)
        self.assertEqual(
            gen._eval_float_constant(CastExpr(TypeSpec("double"), IntLiteral("5"))), 5.0
        )
        self.assertEqual(
            gen._eval_float_constant(BinaryExpr("+", FloatLiteral("1.5"), FloatLiteral("2.0"))), 3.5
        )
        self.assertIsNone(gen._eval_float_constant(UnaryExpr("+", Identifier("missing_float"))))
        self.assertIsNone(gen._eval_float_constant(UnaryExpr("~", FloatLiteral("1.0"))))
        self.assertEqual(
            gen._eval_float_constant(CastExpr(TypeSpec("double"), UnaryExpr("~", IntLiteral("1")))),
            -2.0,
        )
        self.assertIsNone(
            gen._eval_float_constant(
                ConditionalExpr(
                    Identifier("missing_condition"),
                    FloatLiteral("1.0"),
                    FloatLiteral("2.0"),
                )
            )
        )
        self.assertIsNone(
            gen._eval_binary_float_constant(
                BinaryExpr("+", Identifier("missing"), FloatLiteral("2.0"))
            )
        )
        self.assertIsNone(
            gen._eval_binary_float_constant(
                BinaryExpr("%", FloatLiteral("4.0"), FloatLiteral("2.0"))
            )
        )
        self.assertIsNone(
            gen._eval_float_constant(BinaryExpr("/", FloatLiteral("1.0"), FloatLiteral("0.0")))
        )
        self.assertEqual(
            gen._eval_call_float_constant(CallExpr(Identifier("__builtin_inf"), [])),
            float("inf"),
        )
        nan_value = gen._eval_call_float_constant(CallExpr(Identifier("__builtin_nan"), []))
        self.assertIsNotNone(nan_value)
        assert nan_value is not None
        self.assertNotEqual(nan_value, nan_value)
        self.assertEqual(
            gen._eval_call_float_constant(
                CallExpr(Identifier("__builtin_fabs"), [FloatLiteral("-6.0")])
            ),
            6.0,
        )
        self.assertIsNone(
            gen._eval_call_float_constant(
                CallExpr(Identifier("__builtin_fabs"), [Identifier("runtime_float")])
            )
        )
        self.assertIsNone(gen._eval_call_float_constant(CallExpr(FloatLiteral("1.0"), [])))
        self.assertIsNone(gen._eval_call_float_constant(CallExpr(Identifier("runtime_float"), [])))
        with self.assertRaisesRegex(CodegenError, "cannot evaluate switch case"):
            gen._eval_case_value(Identifier("missing"))

        self.assertEqual(gen._string_literal_bytes(StringLiteral('"AZ"')), b"AZ\x00")
        self.assertEqual(gen._string_literal_bytes(StringLiteral('u"AZ"')), b"A\x00Z\x00\x00\x00")
        self.assertEqual(gen._string_literal_label(StringLiteral('L"x"')), ".LC0")
        self.assertEqual(gen._string_literal_label(StringLiteral('L"x"')), ".LC0")
        self.assertEqual(gen._string_literal_alignment(StringLiteral('L"x"')), 2)
        with self.assertRaisesRegex(CodegenError, "does not support string literal"):
            gen._string_literal_units(StringLiteral("not-a-string"))
        original_string_units = gen._string_literal_units
        gen._string_literal_units = lambda _expr: [256]
        try:
            with self.assertRaisesRegex(CodegenError, "non-byte string literal unit"):
                gen._string_literal_bytes(StringLiteral('"wide"'))
        finally:
            gen._string_literal_units = original_string_units
        gen._string_literal_units = lambda _expr: [1 << 32]
        try:
            with self.assertRaisesRegex(CodegenError, "out-of-range string literal unit"):
                gen._string_literal_bytes(StringLiteral('L"wide"'))
        finally:
            gen._string_literal_units = original_string_units

        self.assertEqual(_X86_64AsmGen._subscript_element_type(INT.array_of(3)), INT)
        self.assertEqual(_X86_64AsmGen._subscript_element_type(INT.pointer_to()), INT)
        self.assertIsNone(_X86_64AsmGen._subscript_element_type(INT))
        self.assertIsNone(_X86_64AsmGen._subscript_element_type(INT.function_of((VOID,))))
        self.assertTrue(_X86_64AsmGen._is_record_type(Type("struct S")))
        self.assertTrue(_X86_64AsmGen._is_aggregate_type(INT.array_of(1)))
        self.assertTrue(_X86_64AsmGen._is_function_type(INT.function_of((VOID,))))
        self.assertTrue(_X86_64AsmGen._is_void_type(VOID))
        self.assertTrue(_X86_64AsmGen._is_pointer_type(INT.pointer_to()))
        self.assertTrue(_X86_64AsmGen._is_pointer_like_type(INT.array_of(1)))
        self.assertTrue(
            _X86_64AsmGen._is_flexible_array_member(Type("int", declarator_ops=(("arr", -1),)))
        )
        self.assertTrue(_X86_64AsmGen._is_pointer_binary("+", INT.pointer_to(), INT))
        self.assertTrue(_X86_64AsmGen._is_pointer_binary("-", INT.pointer_to(), INT))
        self.assertFalse(_X86_64AsmGen._is_pointer_binary("*", INT.pointer_to(), INT))
        self.assertEqual(gen._pointer_step_size(INT), 1)
        self.assertEqual(gen._pointer_step_size(INT.pointer_to()), 4)
        self.assertEqual(gen._pointer_step_size(Type("struct Missing").pointer_to()), 1)
        self.assertEqual(
            _X86_64AsmGen._function_designator_value_type(INT.function_of((VOID,))),
            INT.function_of((VOID,)).pointer_to(),
        )
        self.assertEqual(_X86_64AsmGen._function_designator_value_type(INT), INT)
        self.assertTrue(gen._is_null_pointer_initializer(IntLiteral("0")))
        self.assertTrue(gen._is_zero_initializer(IntLiteral("0")))
        self.assertEqual(_X86_64AsmGen._comparison_condition("<", False), "b")
        self.assertEqual(_X86_64AsmGen._comparison_condition("<=", False), "be")
        self.assertEqual(_X86_64AsmGen._comparison_condition(">", True), "g")
        self.assertEqual(_X86_64AsmGen._comparison_condition(">=", False), "ae")
        with self.assertRaisesRegex(AssertionError, "==="):
            _X86_64AsmGen._comparison_condition("===", True)

        self.assertEqual(_X86_64AsmGen._sized_reg("r10", _ScalarInfo(1, 1, False)), "r10b")
        self.assertEqual(_X86_64AsmGen._float_target("rax"), "xmm0")
        self.assertEqual(_X86_64AsmGen._gpr_target("xmm1"), "rax")
        self.assertEqual(gen._update_address_register("rcx"), "r8")
        self.assertEqual(gen._postfix_old_value_register("rdx", "r9"), "r9")
        self.assertEqual(
            _X86_64AsmGen._mem(_ScalarInfo(16, 16, False), "[rax]"), "XMMWORD PTR [rax]"
        )
        self.assertEqual(_X86_64AsmGen._address_operand("rax", -4), "[rax - 4]")
        self.assertEqual(gen._slot_addr(_Slot(16, INT, _ScalarInfo(4, 4, True)), 4), "[rbp - 12]")
        self.assertEqual(_X86_64AsmGen._align_to(17, 8), 24)
        self.assertEqual(_X86_64AsmGen._symbol_name("puts"), "puts")
        self.assertEqual(_X86_64AsmGen._global_symbol_name("value", True), ".L.value")
        self.assertEqual(_X86_64AsmGen._global_symbol_name("value", False), "value")

        gen._emit_external_data_address("external_value", "rax")
        gen._emit_function_address("local_static", "rax")
        gen._emit_function_address("extern_fn", "rax")
        gen._emit_cmp_rax_immediate(7)
        gen._emit_cmp_rax_immediate(1 << 40)
        gen._emit_global_address(_Global(".L.local", INT, True), "rax")
        gen._emit_global_address(_Global("external_value", INT, False), "rax")
        self.assertTrue(gen._is_local_function("local_static"))
        self.assertFalse(gen._is_local_function("extern_fn"))
        self.assertEqual(gen._user_label("again"), ".L.f.again")
        self.assertEqual(gen._new_label("tmp"), ".L.f.tmp.3")

        gen._scope_stack.append({"local": _Slot(8, INT, _ScalarInfo(4, 4, True))})
        self.assertEqual(gen._require_slot("local").offset, 8)
        self.assertIsNone(gen._static_local("missing"))
        previous_func = gen._func
        gen._func = None
        try:
            self.assertIsNone(gen._static_local("missing"))
        finally:
            gen._func = previous_func
        gen._static_locals[(gen._func.name, "typed_static")] = _StaticLocal(
            ".L.f.typed_static",
            DOUBLE,
            InitList((InitItem((), FloatLiteral("1.0")),)),
        )
        self.assertIsNone(
            gen._static_local_slot_marker(
                "typed_static",
                _Slot(0, INT, _ScalarInfo(4, 4, True)),
            )
        )
        self.assertIsNone(
            gen._static_local_slot_marker("missing", _Slot(1, INT, _ScalarInfo(4, 4, True)))
        )
        self.assertIsNone(gen._static_local_initializer("missing"))
        with self.assertRaisesRegex(CodegenError, "Unknown local variable"):
            gen._require_slot("missing")
        with self.assertRaisesRegex(CodegenError, "Unknown local declaration"):
            gen._require_decl_slot(DeclStmt(TypeSpec("int"), "missing_decl", None))
        gen._push_stack("rax")
        gen._pop_stack("rax")

    def test_helper_record_aggregate_classification_edges(self) -> None:
        result = compile_source(
            """
struct Mixed { double d; int i; };
struct TwoDoubles { double a; double b; };
struct Bits { unsigned a:3; unsigned :0; unsigned b:5; int tail; };
struct PackedBits { unsigned a:3; unsigned b:5; int tail; };
struct Flex { int len; char data[]; };
struct ThreeInts { int a; int b; int c; };
struct Big { long a; long b; long c; };
union U { double d; long l; };
int f(void) { return 0; }
""",
            filename="x86_record_aggregate_helper_edges.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)

        self.assertTrue(
            _X86_64AsmGen._record_member_types_match(INT.pointer_to(), INT.pointer_to())
        )
        self.assertFalse(
            _X86_64AsmGen._record_member_types_match(INT.pointer_to(), DOUBLE.pointer_to())
        )
        self.assertFalse(
            _X86_64AsmGen._record_member_types_match(
                INT.pointer_to(), INT.pointer_to().pointer_to()
            )
        )
        self.assertFalse(
            _X86_64AsmGen._record_member_types_match(INT.pointer_to(), INT.array_of(1))
        )
        self.assertFalse(_X86_64AsmGen._record_member_types_match(INT.array_of(2), INT.array_of(3)))
        self.assertTrue(
            _X86_64AsmGen._record_member_types_match(
                INT.function_of((INT,)),
                INT.function_of((DOUBLE,)),
            )
        )

        mixed_chunks = gen._aggregate_chunks(Type("struct Mixed"))
        two_double_chunks = gen._aggregate_chunks(Type("struct TwoDoubles"))
        self.assertEqual(
            mixed_chunks,
            [
                _AggregateChunk(0, _ScalarInfo(8, 8, True, is_float=True)),
                _AggregateChunk(8, _ScalarInfo(8, 1, False)),
            ],
        )
        self.assertEqual(
            two_double_chunks,
            [
                _AggregateChunk(0, _ScalarInfo(8, 8, True, is_float=True)),
                _AggregateChunk(8, _ScalarInfo(8, 8, True, is_float=True)),
            ],
        )
        self.assertEqual(
            gen._aggregate_chunks(Type("struct Flex")),
            [_AggregateChunk(0, _ScalarInfo(4, 1, False))],
        )
        with self.assertRaisesRegex(CodegenError, "cannot size aggregate argument"):
            gen._aggregate_chunks(Type("struct Missing"))

        self.assertTrue(gen._aggregate_uses_registers(Type("struct Mixed"), mixed_chunks, 0, 0))
        self.assertFalse(gen._aggregate_uses_registers(Type("struct Big"), mixed_chunks, 0, 0))
        self.assertFalse(gen._aggregate_uses_registers(Type("struct Mixed"), mixed_chunks, 6, 8))
        self.assertFalse(gen._aggregate_return_uses_memory(Type("struct Mixed")))
        self.assertTrue(gen._aggregate_return_uses_memory(Type("struct Big")))
        with self.assertRaisesRegex(CodegenError, "cannot size aggregate return"):
            gen._aggregate_return_uses_memory(Type("struct Missing"))
        with self.assertRaisesRegex(CodegenError, "indirect aggregate returns"):
            gen._small_aggregate_return_chunks(Type("struct Big"))
        with self.assertRaisesRegex(CodegenError, "cannot size aggregate return"):
            gen._small_aggregate_return_chunks(Type("struct Missing"))

        self.assertEqual(
            gen._aggregate_return_registers(Type("struct Mixed")), {0: "xmm0", 8: "rax"}
        )
        self.assertEqual(
            gen._aggregate_return_registers(Type("struct TwoDoubles")),
            {0: "xmm0", 8: "xmm1"},
        )
        self.assertEqual(
            gen._aggregate_fp_chunk_infos(Type("struct TwoDoubles"), 16),
            {
                0: _ScalarInfo(8, 8, True, is_float=True),
                8: _ScalarInfo(8, 8, True, is_float=True),
            },
        )
        self.assertEqual(gen._aggregate_fp_chunk_infos(Type("struct Bits"), 16), {})

        self.assertEqual(
            gen._record_member_offsets(Type("union U")),
            [(0, DOUBLE, None), (0, Type("long"), None)],
        )
        self.assertEqual(
            gen._record_member_offsets(Type("struct Bits")),
            [
                (0, Type("unsigned int"), 3),
                (4, Type("unsigned int"), 5),
                (8, INT, None),
            ],
        )
        self.assertEqual(
            gen._record_member_offsets(Type("struct PackedBits")),
            [
                (0, Type("unsigned int"), 3),
                (0, Type("unsigned int"), 5),
                (4, INT, None),
            ],
        )
        self.assertEqual(
            gen._record_member_access_by_index(Type("struct PackedBits"), 1),
            _MemberAccess(0, Type("unsigned int"), 3, 5),
        )
        self.assertEqual(gen._record_member_offsets(Type("struct Missing")), [])

        self.assertEqual(
            gen._standalone_fp_member_info(DOUBLE), _ScalarInfo(8, 8, True, is_float=True)
        )
        self.assertIsNone(gen._standalone_fp_member_info(INT))
        self.assertTrue(gen._is_va_list_type(Type("__builtin_va_list")))
        self.assertFalse(gen._is_va_list_type(INT.pointer_to()))

        self.assertEqual(gen._type_size(Type("__builtin_va_list")), 24)
        self.assertEqual(gen._type_size(INT.pointer_to()), 8)
        self.assertIsNone(gen._type_size(INT.function_of((VOID,))))
        self.assertIsNone(gen._type_size(Type("int", declarator_ops=(("arr", -1),))))
        self.assertEqual(gen._type_size(INT.array_of(3)), 12)
        self.assertIsNone(gen._type_size(Type("struct Missing")))
        self.assertEqual(gen._type_align(Type("__builtin_va_list")), 8)
        self.assertEqual(gen._type_align(INT.pointer_to()), 8)
        self.assertIsNone(gen._type_align(INT.function_of((VOID,))))
        self.assertEqual(gen._type_align(INT.array_of(3)), 4)
        self.assertIsNone(gen._type_align(Type("struct Missing")))
        self.assertEqual(gen._member_align(RecordMemberInfo("wide", INT, alignment=16)), 16)
        self.assertIsNone(gen._member_align(RecordMemberInfo("missing", Type("struct Missing"))))
        self.assertEqual(gen._record_size(Type("union U")), 8)
        self.assertEqual(gen._record_size(Type("struct Flex")), 4)
        self.assertIsNone(gen._record_size(Type("struct Missing")))
        gen._sema.record_definitions["struct BadMember"] = (
            RecordMemberInfo("missing", Type("struct Missing")),
        )
        gen._sema.record_definitions["union BadMember"] = (
            RecordMemberInfo("missing", Type("struct Missing")),
        )
        gen._sema.record_definitions["union Wide"] = (
            RecordMemberInfo("values", Type("long").array_of(2)),
        )
        gen._sema.record_definitions["struct AnonymousOuter"] = (
            RecordMemberInfo(None, Type("struct Mixed")),
            RecordMemberInfo("tail", INT),
        )
        self.assertEqual(gen._record_member_offsets(Type("struct BadMember")), [])
        self.assertIsNone(gen._type_align(Type("struct BadMember")))
        self.assertIsNone(gen._record_size(Type("struct BadMember")))
        self.assertIsNone(gen._record_size(Type("union BadMember")))
        self.assertIsNone(gen._scalar_union_info(Type("union Wide")))
        self.assertIsNone(gen._record_member_access_match(Type("struct AnonymousOuter"), "missing"))
        self.assertEqual(
            gen._record_initializer_member_index(
                gen._sema.record_definitions["struct AnonymousOuter"], "missing"
            ),
            (-1, False),
        )

        original_type_size = gen._type_size
        gen._type_size = lambda type_: (
            0 if type_ == Type("struct Empty") else original_type_size(type_)
        )
        try:
            self.assertEqual(gen._aggregate_chunks(Type("struct Empty")), [])
        finally:
            gen._type_size = original_type_size
        gen._type_size = lambda type_: (
            None if type_ == Type("union U") else original_type_size(type_)
        )
        try:
            self.assertEqual(gen._scalar_info(Type("union U")), _ScalarInfo(8, 8, False))
        finally:
            gen._type_size = original_type_size

        original_aggregate_chunks = gen._aggregate_chunks
        gen._aggregate_chunks = lambda _type: [
            _AggregateChunk(0, _ScalarInfo(4, 4, True)),
            _AggregateChunk(4, _ScalarInfo(4, 4, True)),
            _AggregateChunk(8, _ScalarInfo(4, 4, True)),
        ]
        try:
            with self.assertRaisesRegex(CodegenError, "cannot classify aggregate return"):
                gen._small_aggregate_return_chunks(Type("struct Mixed"))
        finally:
            gen._aggregate_chunks = original_aggregate_chunks

        original_small_return_chunks = gen._small_aggregate_return_chunks
        gen._small_aggregate_return_chunks = lambda _type: [
            _AggregateChunk(0, _ScalarInfo(4, 4, True, is_float=True)),
            _AggregateChunk(4, _ScalarInfo(4, 4, True, is_float=True)),
            _AggregateChunk(8, _ScalarInfo(4, 4, True, is_float=True)),
        ]
        try:
            with self.assertRaisesRegex(CodegenError, "aggregate FP return register"):
                gen._aggregate_return_registers(Type("struct Mixed"))
        finally:
            gen._small_aggregate_return_chunks = original_small_return_chunks
        gen._small_aggregate_return_chunks = lambda _type: [
            _AggregateChunk(0, _ScalarInfo(4, 4, True)),
            _AggregateChunk(4, _ScalarInfo(4, 4, True)),
            _AggregateChunk(8, _ScalarInfo(4, 4, True)),
        ]
        try:
            with self.assertRaisesRegex(CodegenError, "aggregate integer return register"):
                gen._aggregate_return_registers(Type("struct Mixed"))
        finally:
            gen._small_aggregate_return_chunks = original_small_return_chunks

        mismatch_spec = TypeSpec(
            "struct",
            record_members=(RecordMemberDecl(TypeSpec("int"), "other"),),
            has_record_body=True,
        )
        gen._sema.record_definitions["struct Mismatch"] = (RecordMemberInfo("value", INT),)
        self.assertFalse(gen._record_members_match_type_spec("struct Mismatch", mismatch_spec))
        self.assertEqual(
            _X86_64AsmGen._complete_array_initializer_type(
                Type("int", declarator_ops=(("arr", -1),)),
                InitList((InitItem((("member", "ignored"),), IntLiteral("1")),)),
            ),
            INT.array_of(1),
        )
        self.assertEqual(
            gen._resolve_type_spec(TypeSpec("int", declarator_ops=(("unknown", 0),))), INT
        )
        self.assertEqual(
            gen._record_name_for_type_spec(TypeSpec("struct", record_tag="OnlyForward")),
            "struct OnlyForward",
        )
        self.assertEqual(gen._record_name_for_type_spec(TypeSpec("struct")), "struct")
        self.assertEqual(
            gen._record_name_for_type_spec(
                TypeSpec(
                    "union",
                    record_members=(RecordMemberDecl(TypeSpec("int"), "only"),),
                    has_record_body=True,
                )
            ),
            "union",
        )

    def test_unused_inline_body_is_not_emitted(self) -> None:
        asm = self._asm(
            """
extern inline int unused(int x) { while (x) return 1; return 0; }
static inline int also_unused(int x) { while (x) return 2; return 0; }
int main(void) { return 0; }
"""
        )

        self.assertIn(".globl main\nmain:", asm)
        self.assertNotIn("unused:", asm)
        self.assertNotIn("also_unused:", asm)

    def test_referenced_inline_function_designators_are_emitted(self) -> None:
        asm = self._asm(
            """
typedef int (*fn)(int);
static inline int add_one(int x) { return x + 1; }
extern inline int add_two(int x) { return x + 2; }
static fn table[] = { add_one, add_two };
int apply(int flag, int x) {
  fn chosen = flag ? add_one : add_two;
  int left = chosen(x);
  int right = table[flag](x);
  return left * 10 + right;
}
"""
        )

        self.assertIn("add_one:", asm)
        self.assertNotIn(".globl add_one", asm)
        self.assertIn("add_two:", asm)
        self.assertNotIn(".globl add_two", asm)
        self.assertIn(".L.table:\n    .quad add_one\n    .quad add_two", asm)

    def test_local_function_pointer_shadows_same_named_function(self) -> None:
        asm = self._asm(
            """
int dict_contains(int x) { return x + 100; }
int dictkeys_contains(int x) { return x + 7; }
int caller(int x) {
  int (*dict_contains)(int);
  dict_contains = dictkeys_contains;
  return dict_contains(x);
}
"""
        )
        caller_asm = asm.split("caller:", 1)[1]
        self.assertIn("    call r11", caller_asm)
        self.assertNotIn("    call dict_contains", caller_asm)

    def test_integer_to_bool_normalizes_nonzero_before_store(self) -> None:
        asm = self._asm(
            """
int f(void) {
  _Bool future_annotations = 0x1000000;
  return future_annotations ? 0 : 1;
}
"""
        )
        self.assertIn("    cmp eax, 0", asm)
        self.assertIn("    setne al", asm)
        self.assertIn("    movzx eax, al", asm)
        self.assertNotIn("    and eax, 255", asm)

    def test_transparent_union_parameter_call_accepts_member_pointer(self) -> None:
        asm = self._asm(
            """
struct sockaddr { int family; };
typedef union {
  struct sockaddr *sa;
} SockArg __attribute__((__transparent_union__));
int accept4(int fd, SockArg addr, unsigned int *len, int flags);
int f(struct sockaddr *addr, unsigned int *len) {
  return accept4(3, addr, len, 0);
}
"""
        )
        self.assertIn("    call accept4", asm)

    def test_discarded_indirect_aggregate_call_gets_sret_slot(self) -> None:
        asm = self._asm(
            """
struct Status { long a; long b; long c; };
struct Status init_runtime(void);
void f(void) {
  init_runtime();
}
"""
        )
        self.assertIn("    lea rcx, [rbp -", asm)
        self.assertIn("    push rcx", asm)
        self.assertIn("    mov rdi, QWORD PTR [rsp + 8]", asm)
        self.assertIn("    call init_runtime", asm)

    def test_nested_call_argument_preserves_sysv_stack_alignment(self) -> None:
        asm = self._asm(
            """
long first(void);
long second(void);
void sink(long a, long b);
void f(void) {
  sink(first(), second());
}
"""
        )
        self.assertIn(
            "    call second\n"
            "    push rax\n"
            "    push 0\n"
            "    mov eax, 0\n"
            "    call first\n"
            "    add rsp, 8\n"
            "    push rax",
            asm,
        )

    def test_global_double_initializer_accepts_constant_expression(self) -> None:
        asm = self._asm(
            """
static const double value = 9007199254740992. * 9007199254740992.e-256;
double f(void) { return value; }
"""
        )
        self.assertIn("    .quad 0x1168062864ac6f43", asm)

    def test_global_double_initializer_folds_float_constant_forms(self) -> None:
        asm = self._asm(
            """
static const double plus_value = +1.5;
static const double minus_value = -2.25;
static const double cast_value = (double)7;
static const double comma_value = ((void)0, 3.5);
static const double cond_true = 1 ? 4.5 : 8.5;
static const double cond_false = 0 ? 4.5 : 8.5;
static const double add_value = 1.5 + 2.25;
static const double sub_value = 5.5 - 1.0;
static const double div_value = 9.0 / 3.0;
static const double fabs_value = __builtin_fabs(-6.25);
static const double int_value = 5;
double sum(void) {
  return plus_value + minus_value + cast_value + comma_value + cond_true
      + cond_false + add_value + sub_value + div_value + fabs_value + int_value;
}
"""
        )

        self.assertIn(".L.plus_value:\n    .quad 0x3ff8000000000000", asm)
        self.assertIn(".L.minus_value:\n    .quad 0xc002000000000000", asm)
        self.assertIn(".L.cast_value:\n    .quad 0x401c000000000000", asm)
        self.assertIn(".L.comma_value:\n    .quad 0x400c000000000000", asm)
        self.assertIn(".L.cond_true:\n    .quad 0x4012000000000000", asm)
        self.assertIn(".L.cond_false:\n    .quad 0x4021000000000000", asm)
        self.assertIn(".L.add_value:\n    .quad 0x400e000000000000", asm)
        self.assertIn(".L.sub_value:\n    .quad 0x4012000000000000", asm)
        self.assertIn(".L.div_value:\n    .quad 0x4008000000000000", asm)
        self.assertIn(".L.fabs_value:\n    .quad 0x4019000000000000", asm)
        self.assertIn(".L.int_value:\n    .quad 0x4014000000000000", asm)

    def test_local_array_bound_sizeof_prior_local_identifier(self) -> None:
        asm = self._asm(
            """
typedef unsigned long uint64_t;
typedef unsigned char uint8_t;
void f(void) {
  uint64_t marker;
  uint8_t tmp[sizeof(marker)];
  tmp[0] = 0;
}
"""
        )
        self.assertIn("    sub rsp, 16", asm)
        self.assertIn("    lea rcx, [rbp - 16]", asm)
        self.assertIn("    mov BYTE PTR [rcx], al", asm)

    def test_sizeof_completed_local_array_uses_frame_slot_type(self) -> None:
        asm = self._asm(
            """
struct State { unsigned char c[8]; };
struct Obj { struct State state; };
void sink(unsigned long);
void f(struct Obj *self) {
  unsigned char statebytes[1 + 2 * 4 + sizeof(self->state.c)];
  sink(sizeof(statebytes));
}
"""
        )
        self.assertIn("    sub rsp, 32", asm)
        self.assertIn("    mov eax, 17", asm)

    def test_global_integer_initializer_accepts_comma_constant_expression(self) -> None:
        asm = self._asm(
            """
static int handlers[3];
static const unsigned long count =
    sizeof(handlers) / sizeof(handlers[0]) + ((void)sizeof(struct { int dummy; }), 0);
unsigned long f(void) { return count; }
"""
        )
        self.assertIn("    .quad 3", asm)

    def test_global_integer_initializer_folds_constant_expression_matrix(self) -> None:
        asm = self._asm(
            """
struct Pair { char x; long y; };
enum { C_ENUM = 9 };
static const int c_char = 'A';
static const int c_enum = C_ENUM;
static const int c_unary = (+7) + (-2) + (!0) + (~0);
static const int c_cast = (int)7;
static const int c_comma = ((void)0, 23);
static const int c_mul = 6 * 7;
static const int c_div = 17 / 4;
static const int c_mod = 17 % 5;
static const int c_shl = 3 << 4;
static const int c_shr = 64 >> 3;
static const int c_cmp = (1 < 2) + (2 <= 2) + (3 > 2) + (3 >= 3) + (4 == 4) + (4 != 5);
static const int c_bitwise = (12 & 10) + (1 | 4) + (7 ^ 2);
static const int c_logic = (0 && 5) + (4 && 5) + (4 || 0) + (0 || 0);
static const int c_cond = (1 ? 11 : 22) + (0 ? 33 : 44);
static const long c_size_align = sizeof(long) + _Alignof(long);
static const long c_offset = __builtin_offsetof(struct Pair, y);
long sum(void) {
  return c_char + c_enum + c_unary + c_cast + c_comma + c_mul + c_div + c_mod
      + c_shl + c_shr + c_cmp + c_bitwise + c_logic + c_cond + c_size_align
      + c_offset;
}
"""
        )

        expected_scalars = {
            "c_char": 65,
            "c_enum": 9,
            "c_unary": 5,
            "c_cast": 7,
            "c_comma": 23,
            "c_mul": 42,
            "c_div": 4,
            "c_mod": 2,
            "c_shl": 48,
            "c_shr": 8,
            "c_cmp": 6,
            "c_bitwise": 18,
            "c_logic": 2,
            "c_cond": 55,
        }
        for name, value in expected_scalars.items():
            with self.subTest(name=name):
                self.assertIn(f".L.{name}:\n    .long {value}", asm)
        self.assertIn(".L.c_size_align:\n    .quad 16", asm)
        self.assertIn(".L.c_offset:\n    .quad 8", asm)

    def test_grouped_globals_and_static_locals_emit_each_object(self) -> None:
        asm = self._asm(
            """
static int first = 1, second = 2;
static char text[] = "hi";

int f(void) {
  static int local_first = 3, local_second = 4;
  return first + second + local_first + local_second + text[0];
}
"""
        )

        self.assertIn(".L.first:\n    .long 1", asm)
        self.assertIn(".L.second:\n    .long 2", asm)
        self.assertIn(".L.text:\n    .byte 104, 105, 0", asm)
        self.assertIn(".L.f.local_first:\n    .long 3", asm)
        self.assertIn(".L.f.local_second:\n    .long 4", asm)

    def test_global_union_and_bitfield_initializers_emit_storage_units(self) -> None:
        asm = self._asm(
            """
union Big { int tag; char bytes[8]; };
static union Big big = { .tag = 7 };

struct Bits { unsigned a:3; unsigned :0; unsigned b:5; int tail; };
static struct Bits bits = { .a = 5, .b = 17, .tail = 9 };

struct Packed { unsigned a:3; unsigned b:5; unsigned c:8; };
static struct Packed packed = { .a = 5, .b = 17, .c = 201 };

int f(void) { return big.tag + bits.tail; }
"""
        )

        self.assertIn(".L.big:\n    .long 7\n    .zero 4", asm)
        self.assertIn(".L.bits:\n    .long 5\n    .long 17\n    .long 9", asm)
        self.assertIn(".L.packed:\n    .long 51597", asm)

    def test_global_integer_initializer_accepts_float_to_int_cast(self) -> None:
        asm = self._asm(
            """
static const long max_amp = (long)100.0f;
long f(void) { return max_amp; }
"""
        )
        self.assertIn("    .quad 100", asm)

    def test_global_pointer_initializer_accepts_constant_conditional_subobject(self) -> None:
        asm = self._asm(
            """
struct Obj { int value; };
struct Obj ascii[128];
struct Obj latin1[128];
struct Obj *name = 'n' < 128 ? &ascii['n'] : &latin1['n' - 128];
"""
        )
        self.assertIn("    .quad ascii + 440", asm)

    def test_global_pointer_initializer_accepts_array_symbol_plus_offset(self) -> None:
        asm = self._asm(
            """
static const unsigned short table[] = {1, 2, 3};
struct Index { const unsigned short *map; int lo; int hi; };
static const struct Index indexes[] = {
  {table + 1, 33, 126},
};
const unsigned short *f(void) { return indexes[0].map; }
"""
        )
        self.assertIn("    .quad .L.table + 2", asm)

    def test_global_array_initializer_accepts_sparse_index_designators(self) -> None:
        asm = self._asm(
            """
static int values[5] = { [2] = 7, [4] = 9 };
int f(void) { return values[2] + values[4]; }
"""
        )

        self.assertIn(".L.values:\n    .zero 4\n    .zero 4\n    .long 7", asm)
        self.assertIn("    .zero 4\n    .long 9", asm)

    def test_global_record_initializer_handles_flexible_zero_and_padding_edges(
        self,
    ) -> None:
        asm = self._asm(
            """
struct FlexNone { char tag; int data[]; };
static struct FlexNone flex_none = { .tag = 1 };

struct FlexZero { char tag; int data[]; };
static struct FlexZero flex_zero = { .tag = 2, .data = 0 };

struct PaddedBits { char prefix; unsigned a:3; int tail; };
static struct PaddedBits padded_bits = { .prefix = 4, .a = 5, .tail = 9 };

struct ZeroWidthPad { char prefix; unsigned :0; int tail; };
static struct ZeroWidthPad zero_width = { .prefix = 6, .tail = 11 };

int f(void) { return flex_none.tag + flex_zero.tag + padded_bits.tail + zero_width.tail; }
"""
        )

        self.assertIn(".L.flex_none:\n    .byte 1\n    .zero 3", asm)
        self.assertIn(".L.flex_zero:\n    .byte 2\n    .zero 3", asm)
        self.assertIn(".L.padded_bits:\n    .byte 4\n    .zero 3\n    .long 5\n    .long 9", asm)
        self.assertIn(".L.zero_width:\n    .byte 6\n    .zero 3\n    .long 11", asm)

    def test_emits_params_locals_and_arithmetic(self) -> None:
        asm = self._asm("int add(int a, int b){ int c=a+b; return c*2; }")
        self.assertIn("    mov DWORD PTR [rbp - 4], edi", asm)
        self.assertIn("    mov DWORD PTR [rbp - 8], esi", asm)
        self.assertIn("    add eax, r10d", asm)
        self.assertIn("    imul eax, r10d", asm)

    def test_stack_aggregate_parameter_spills_float_and_integer_chunks(self) -> None:
        asm = self._asm(
            """
struct Mixed { double f; long i; };
long take_stack_aggregate(
    long a, long b, long c, long d, long e, long g, struct Mixed value
) {
  return (long)value.f + value.i + a + g;
}
"""
        )

        self.assertIn("    movsd xmm0, [rbp + 16]", asm)
        self.assertIn("    movsd [rbp - 64], xmm0", asm)
        self.assertIn("    mov rax, QWORD PTR [rbp + 24]", asm)
        self.assertIn("    mov QWORD PTR [rbp - 56], rax", asm)

    def test_bitfield_aggregate_return_keeps_integer_and_fp_chunks(self) -> None:
        asm = self._asm(
            """
struct BitsAndDouble {
  unsigned flag : 1;
  unsigned : 0;
  unsigned code : 5;
  double value;
};

struct BitsAndDouble make_bits(double value)
{
  struct BitsAndDouble out;
  out.flag = 1;
  out.code = 17;
  out.value = value;
  return out;
}
"""
        )

        self.assertIn("make_bits:", asm)
        self.assertIn("    mov eax,", asm)
        self.assertIn("    movsd xmm0,", asm)

    def test_sizeof_record_with_flexible_array_excludes_tail_array(self) -> None:
        asm = self._asm(
            "struct S { char tag; long values[]; }; long f(void) { return sizeof(struct S); }"
        )
        self.assertIn("    mov eax, 8", asm)
        self.assertIn("    movsxd rax, eax", asm)

    def test_sizeof_record_respects_explicit_member_alignment(self) -> None:
        asm = self._asm(
            """
struct ExplicitlyAligned { _Alignas(16) char tag; };
long size(void) { return sizeof(struct ExplicitlyAligned); }
long align(void) { return __alignof__(struct ExplicitlyAligned); }
"""
        )

        size_asm = asm.split("size:", 1)[1].split("align:", 1)[0]
        align_asm = asm.split("align:", 1)[1]
        self.assertIn("    mov eax, 16", size_asm)
        self.assertIn("    mov eax, 16", align_asm)

    def test_nested_offsetof_member_path_folds_to_constant(self) -> None:
        asm = self._asm(
            """
struct Inner { char c; long value; };
struct Outer { int tag; struct Inner inner; };
long f(void) { return __builtin_offsetof(struct Outer, inner.value); }
"""
        )

        self.assertIn("f:\n    push rbp\n    mov rbp, rsp\n    mov rax, 16", asm)

    def test_local_incomplete_arrays_infer_initializer_storage(self) -> None:
        asm = self._asm(
            """
int f(void) {
  int values[] = { 1, 2, [4] = 5 };
  char text[] = "hi";
  return sizeof(values) + sizeof(text);
}
"""
        )

        self.assertIn("    mov eax, 20", asm)
        self.assertIn("    mov eax, 3", asm)
        self.assertIn("    mov BYTE PTR [rbp - 21], 0", asm)

    def test_anonymous_typedef_record_matching_uses_member_array_lengths(self) -> None:
        asm = self._asm(
            """
typedef struct { long ref; void *type; } Obj;
#define HEAD Obj ob_base; long hashcode; char hastzinfo;
typedef struct { HEAD unsigned char data[6]; } BaseTime;
typedef struct { HEAD unsigned char data[6]; unsigned char fold; void *tzinfo; } Time;
typedef struct { HEAD unsigned char data[10]; } BaseDateTime;
typedef struct { HEAD unsigned char data[10]; unsigned char fold; void *tzinfo; } DateTime;
long base_size(void) { return sizeof(BaseDateTime); }
long full_size(void) { return sizeof(DateTime); }
long fold_offset(DateTime *p) { return (char *)&p->fold - (char *)p; }
long tz_offset(DateTime *p) { return (char *)&p->tzinfo - (char *)p; }
"""
        )
        self.assertIn("base_size:\n    push rbp\n    mov rbp, rsp\n    mov eax, 40", asm)
        self.assertIn("full_size:\n    push rbp\n    mov rbp, rsp\n    mov eax, 48", asm)
        self.assertIn("    add rax, 35", asm)
        self.assertIn("    add rax, 40", asm)

    def test_anonymous_typedef_record_matching_normalizes_enum_members(self) -> None:
        asm = self._asm(
            """
typedef struct {
  enum { STATUS_OK = 0, STATUS_ERR = 1 } kind;
  const char *message;
} Status;
Status make_status(void);
Status f(void) {
  Status status = make_status();
  return status;
}
"""
        )
        self.assertIn(".globl f\nf:", asm)

    def test_anonymous_typedef_record_matching_preserves_opaque_tagged_pointers(self) -> None:
        asm = self._asm(
            """
struct Arena;
typedef struct {
  int level;
  struct Arena *arena;
} Parser;
long f(void) { return sizeof(Parser); }
"""
        )
        self.assertIn("f:\n    push rbp\n    mov rbp, rsp\n    mov eax, 16", asm)

    def test_flexible_array_member_access_has_offset(self) -> None:
        asm = self._asm(
            "struct S { char tag; long values[]; }; long *f(struct S *s) { return &s->values[1]; }"
        )
        self.assertIn("    add rax, 8", asm)
        self.assertIn("    add rax, r10", asm)

    def test_flexible_array_member_expression_decays_to_pointer(self) -> None:
        asm = self._asm(
            "struct S { int used; char bytes[]; }; "
            "char *f(struct S *s) { return (char *)s->bytes; }"
        )
        self.assertIn("    mov rax, QWORD PTR [rbp - 8]", asm)
        self.assertIn("    add rax, 4", asm)

    def test_global_record_initializer_omits_flexible_array_storage(self) -> None:
        asm = self._asm("struct S { int used; char bytes[]; }; struct S value = { .used = 1 };")
        self.assertIn("value:", asm)
        self.assertIn("    .long 1", asm)
        self.assertNotIn(".zero -1", asm)

    def test_emits_sysv_floating_parameters_calls_and_return(self) -> None:
        asm = self._asm(
            """
double add(double a, double b) { return a + b; }
double ninth(
  double a, double b, double c, double d, double e,
  double f, double g, double h, double i
) { return i; }
int main(void) {
  double x = add(1.25, 2.75);
  double y = ninth(1, 2, 3, 4, 5, 6, 7, 8, 9);
  return x == 4.0 && y == 9.0 ? 0 : 1;
}
"""
        )
        self.assertIn("    movsd [rbp - 8], xmm0", asm)
        self.assertIn("    movsd [rbp - 16], xmm1", asm)
        self.assertIn("    addsd xmm0, xmm1", asm)
        self.assertIn("    movsd xmm0, [rbp + 16]", asm)
        self.assertIn("    mov eax, 8", asm)
        self.assertIn("    ucomisd xmm0, xmm1", asm)

    def test_builtin_isinf_sign_lowers_without_external_call(self) -> None:
        asm = self._asm("int sign_inf(double value) { return __builtin_isinf_sign(value); }")
        self.assertIn("    movq r11, xmm0", asm)
        self.assertIn("    cmp r10, rax", asm)
        self.assertIn("    neg eax", asm)
        self.assertNotIn("call __builtin_isinf_sign", asm)

    def test_builtin_isnan_lowers_without_external_call(self) -> None:
        asm = self._asm(
            """
int isnanf_value(float value) { return __builtin_isnan(value); }
int isnan_double(double value) { return __builtin_isnan(value); }
"""
        )

        self.assertIn("    ucomiss xmm0, xmm0", asm)
        self.assertIn("    ucomisd xmm0, xmm0", asm)
        self.assertGreaterEqual(asm.count("    setp al"), 2)
        self.assertNotIn("call __builtin_isnan", asm)

    def test_builtin_signbit_lowers_without_external_call(self) -> None:
        asm = self._asm("int sign(double value) { return __builtin_signbit(value); }")
        self.assertIn("    movq r11, xmm0", asm)
        self.assertIn("    shr r11, 63", asm)
        self.assertNotIn("call __builtin_signbit", asm)

    def test_builtin_isnormal_lowers_without_external_call(self) -> None:
        asm = self._asm("int normal(double value) { return __builtin_isnormal(value); }")
        self.assertIn("    mov rax, 0x000fffffffffffff", asm)
        self.assertIn("    setb r11b", asm)
        self.assertNotIn("call __builtin_isnormal", asm)

    def test_float_class_builtin_variants_cover_float_and_fallback_paths(self) -> None:
        asm = self._asm(
            """
int finite_f(float value) { return __builtin_isfinite(value); }
int inf_f(float value) { return __builtin_isinf(value); }
int sign_f(float value) { return __builtin_signbit(value); }
int normal_f(float value) { return __builtin_isnormal(value); }
int finite_i(int value) { return __builtin_isfinite(value); }
int no_arg(void) { return __builtin_isinf(); }
"""
        )

        self.assertIn("    and r10d, 0x7fffffff", asm)
        self.assertIn("    cmp r10d, 0x7f800000", asm)
        self.assertIn("    cmp r10d, 0x007fffff", asm)
        self.assertIn("    movd r11d, xmm0", asm)
        self.assertIn("    shr r11d, 31", asm)
        self.assertIn("    cvtsi2sd xmm0, rax", asm)
        self.assertIn("no_arg:\n    push rbp\n    mov rbp, rsp\n    mov eax, 0", asm)
        self.assertNotIn("call __builtin_isfinite", asm)
        self.assertNotIn("call __builtin_isinf", asm)
        self.assertNotIn("call __builtin_signbit", asm)
        self.assertNotIn("call __builtin_isnormal", asm)

    def test_float_class_helper_moves_result_to_requested_register(self) -> None:
        result = compile_source(
            "int f(void) { return 0; }",
            filename="float_class_helper.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        def builtin_call(name: str, arg: FloatLiteral, arg_type: Type) -> CallExpr:
            expr = CallExpr(Identifier(name), [typed_expr(arg, arg_type)])
            typed_expr(expr, INT)
            return expr

        for name, arg, arg_type in (
            ("__builtin_isnan", FloatLiteral("1.0f"), FLOAT),
            ("__builtin_signbit", FloatLiteral("-1.0"), DOUBLE),
            ("__builtin_isfinite", FloatLiteral("1.0"), DOUBLE),
        ):
            value = gen._emit_float_class_builtin(name, builtin_call(name, arg, arg_type), "r10")
            self.assertEqual(value.reg, "r10")

        self.assertGreaterEqual(gen._lines.count("    mov r10d, eax"), 3)

    def test_long_double_literal_uses_double_constant_path(self) -> None:
        asm = self._asm("double value(void) { return (double)1.25L; }")
        self.assertIn("    movsd xmm0, [rip + .LCF0]", asm)
        self.assertIn("    .quad 0x3ff4000000000000", asm)

    def test_builtin_memset_lowers_to_libc_symbol(self) -> None:
        asm = self._asm("void *f(char *p) { return __builtin_memset(p, 0, 4); }")
        self.assertIn("    call memset", asm)
        self.assertNotIn("call __builtin_memset", asm)

    def test_common_gcc_builtins_lower_without_external_symbols(self) -> None:
        asm = self._asm(
            """
typedef __builtin_va_list va_list;
int bits(unsigned x, unsigned long y, unsigned long long z) {
  return __builtin_bswap32(x) + __builtin_ctzll(z)
      + __builtin_popcount(x) + __builtin_clzl(y);
}
void *frame(void) {
  return __builtin_frame_address(0);
}
void *stack_alloc(unsigned long size) {
  return __builtin_alloca(size);
}
float constants(void) {
  return __builtin_inff() + __builtin_nanf("");
}
void copy_va(int marker, ...) {
  va_list src;
  va_list dst;
  __builtin_va_start(src, marker);
  __builtin_va_copy(dst, src);
  __builtin_va_end(dst);
}
void stop(void) {
  __builtin_unreachable();
}
"""
        )
        self.assertIn("    bswap eax", asm)
        self.assertIn("    bsf rax, rax", asm)
        self.assertIn("    bsr rax, rax", asm)
        self.assertIn("popcount_loop", asm)
        self.assertIn("    mov rax, rbp", asm)
        self.assertIn("    sub rsp, rax", asm)
        self.assertIn("    ud2", asm)
        self.assertIn("    mov QWORD PTR [rcx], r10", asm)
        self.assertNotIn("call __builtin_", asm)

    def test_extended_common_gcc_builtins_cover_inline_x86_paths(self) -> None:
        asm = self._asm(
            """
unsigned short swap16(unsigned short x) { return __builtin_bswap16(x); }
unsigned swap32(unsigned x) { return __builtin_bswap32(x); }
unsigned long long swap64(unsigned long long x) { return __builtin_bswap64(x); }
int leading(unsigned x) { return __builtin_clz(x); }
int trailing(unsigned x) { return __builtin_ctz(x); }
int count64(unsigned long long x) { return __builtin_popcountll(x); }
long expect_long(long x) { return __builtin_expect(x, 1); }
void *aligned(char *p) { return __builtin_assume_aligned(p, 16); }
void *stack_align(unsigned long size) { return __builtin_alloca_with_align(size, 128); }
void *retaddr(void) { return __builtin_return_address(0); }
void *outer_frame(void) { return __builtin_frame_address(1); }
double inf_value(void) { return __builtin_inf(); }
double nan_value(void) { return __builtin_nan(""); }
long double huge_long(void) { return __builtin_infl(); }
"""
        )

        self.assertIn("    rol ax, 8", asm)
        self.assertIn("    bswap eax", asm)
        self.assertIn("    bswap rax", asm)
        self.assertIn("    bsr eax, eax", asm)
        self.assertIn("    bsf eax, eax", asm)
        self.assertIn("popcount_loop", asm)
        self.assertIn("    sub rsp, rax", asm)
        self.assertIn("    mov rax, QWORD PTR [rbp + 8]", asm)
        self.assertIn("outer_frame:\n    push rbp\n    mov rbp, rsp\n    mov rax, 0", asm)
        self.assertIn("huge_long:", asm)
        self.assertIn("    cvtsd2ss xmm0, xmm0", asm)
        self.assertIn("    movsd xmm0, [rip + .LCF", asm)
        self.assertNotIn("call __builtin_", asm)

    def test_cast_pointer_deref_assignment_uses_requested_address_register(self) -> None:
        asm = self._asm("void f(void *dst, void *src) { *(int *)dst = *(int *)src; }")
        self.assertIn("    mov rax, QWORD PTR [rbp - 8]", asm)
        self.assertIn("    mov rcx, rax", asm)
        self.assertIn("    mov DWORD PTR [rcx], eax", asm)

    def test_statement_expression_with_local_decl_returns_last_expression(self) -> None:
        asm = self._asm(
            """
unsigned long f(unsigned long cpu, unsigned long setsize) {
  return ({ unsigned long __cpu = cpu; __cpu < setsize ? __cpu + 1 : 0; });
}
"""
        )
        self.assertIn("    mov QWORD PTR [rbp -", asm)
        self.assertIn("    add rax, r10", asm)
        self.assertIn("    cmp rax, r10", asm)

    def test_atomic_fetch_and_compare_exchange_lower_without_libatomic_calls(self) -> None:
        asm = self._asm(
            """
unsigned long add(unsigned long *p) {
  return __atomic_fetch_add(p, 1, 5);
}
int cas(int *p, int *expected, int desired) {
  return __atomic_compare_exchange_n(p, expected, desired, 0, 5, 5);
}
"""
        )
        self.assertIn("    lock xadd QWORD PTR [rcx], rax", asm)
        self.assertIn("    lock cmpxchg DWORD PTR [rcx], r11d", asm)
        self.assertNotIn("call __atomic", asm)

    def test_atomic_load_store_exchange_fence_and_bitwise_fetch_lower_inline(self) -> None:
        asm = self._asm(
            """
void ops(unsigned long *p, unsigned long *out) {
  __atomic_store_n(p, 2, 5);
  out[0] = __atomic_load_n(p, 5);
  __atomic_store(p, &out[0], 5);
  __atomic_load(p, &out[1], 5);
  out[2] = __atomic_exchange_n(p, 7, 5);
  out[3] = __atomic_fetch_sub(p, 1, 5);
  out[4] = __atomic_fetch_and(p, 3, 5);
  out[5] = __atomic_fetch_or(p, 4, 5);
  out[6] = __atomic_fetch_xor(p, 8, 5);
  __atomic_thread_fence(5);
}
"""
        )

        self.assertIn("    mfence", asm)
        self.assertIn("    xchg QWORD PTR [rcx], rax", asm)
        self.assertIn("    neg rax", asm)
        self.assertIn("    lock xadd QWORD PTR [rcx], rax", asm)
        self.assertIn("    and r11, r10", asm)
        self.assertIn("    or r11, r10", asm)
        self.assertIn("    xor r11, r10", asm)
        self.assertIn("    lock cmpxchg QWORD PTR [rcx], r11", asm)
        self.assertNotIn("call __atomic", asm)

    def test_integer_compound_assignment_ops_lower_to_sized_integer_instructions(self) -> None:
        asm = self._asm(
            """
long signed_ops(long value, int shift) {
  value += 3;
  value -= 1;
  value *= 5;
  value &= 31;
  value |= 64;
  value ^= 7;
  value /= 3;
  value %= 5;
  value <<= 1;
  value >>= shift;
  return value;
}
unsigned long unsigned_ops(unsigned long value, int shift) {
  value /= 3;
  value %= 5;
  value >>= shift;
  return value;
}
"""
        )

        self.assertIn("    add rax, r10", asm)
        self.assertIn("    sub rax, r10", asm)
        self.assertIn("    imul rax, r10", asm)
        self.assertIn("    and rax, r10", asm)
        self.assertIn("    or rax, r10", asm)
        self.assertIn("    xor rax, r10", asm)
        self.assertIn("    cqo", asm)
        self.assertIn("    idiv r10", asm)
        self.assertIn("    div r10", asm)
        self.assertIn("    sal rax, cl", asm)
        self.assertIn("    sar rax, cl", asm)
        self.assertIn("    shr rax, cl", asm)

    def test_float_logical_not_uses_unordered_zero_compare(self) -> None:
        asm = self._asm("int f(double value) { return !value; }\n")

        self.assertIn("    ucomisd xmm0, xmm15", asm)
        self.assertIn("    sete al", asm)
        self.assertIn("    setnp r10b", asm)
        self.assertIn("    and al, r10b", asm)

    def test_float_conditions_branch_on_unordered_nonzero(self) -> None:
        asm = self._asm(
            """
int choose(double x, double y) {
  if (x) return 1;
  return x || y;
}
int not_equal(double x, double y) { return x != y; }
"""
        )

        self.assertIn(".L.choose.float_not_zero.", asm)
        self.assertIn("    jp .L.choose.float_not_zero.", asm)
        self.assertIn("    je .L.choose.if_else.", asm)
        self.assertIn("    jp .L.choose.logic_selected.", asm)
        self.assertIn("    jne .L.choose.logic_selected.", asm)
        self.assertIn("    setp r10b", asm)
        self.assertIn("    or al, r10b", asm)

    def test_float_compound_and_cast_paths_emit_expected_conversions(self) -> None:
        asm = self._asm(
            """
double float_compound_used_as_rhs(double x) {
  double y = x;
  return 1.0 + (y += 2.0);
}
int cast_float_to_int(double x) { return (int)x; }
double cast_uint64_to_double(unsigned long x) { return (double)x; }
"""
        )

        self.assertIn("float_compound_used_as_rhs:", asm)
        self.assertIn("    movsd xmm1, xmm0", asm)
        self.assertIn("    addsd xmm0, xmm1", asm)
        self.assertIn("cast_float_to_int:", asm)
        self.assertIn("    cvttsd2si rax, xmm0", asm)
        self.assertIn("cast_uint64_to_double:", asm)
        self.assertIn(".L.cast_uint64_to_double.uint64_float_slow.", asm)
        self.assertIn("    addsd xmm0, xmm0", asm)

    def test_int_division_and_bitwise_not_use_sized_integer_ops(self) -> None:
        asm = self._asm(
            """
int divrem(int a, int b) { return a / b + a % b; }
int flip(int x) { return ~x; }
"""
        )

        self.assertIn("    cdq", asm)
        self.assertIn("    idiv r10d", asm)
        self.assertIn("    mov eax, edx", asm)
        self.assertIn("    not eax", asm)

    def test_call_arguments_decay_string_literals_to_pointers(self) -> None:
        asm = self._asm(
            """
int first(const char *s) { return s[0]; }
int main(void) { return first("ok") == 'o' ? 0 : 1; }
"""
        )
        self.assertIn("    lea rax, [rip + .LC0]", asm)
        self.assertIn("    pop rdi", asm)
        self.assertIn("    call first", asm)

    def test_array_operands_decay_for_pointer_arithmetic(self) -> None:
        asm = self._asm(
            """
	char *advance(int offset) { return "abcdefghijklmnopqrst" + offset; }
"""
        )
        self.assertIn("    lea rax, [rip + .LC0]", asm)
        self.assertIn("    add rax, r10", asm)

    def test_pointer_compound_assignment_scales_variable_offset(self) -> None:
        asm = self._asm(
            """
	typedef unsigned long size_t;
	void bump(long **cursor, size_t offs) { cursor += offs; }
"""
        )
        self.assertIn("    imul rax, 8", asm)
        self.assertIn("    add rax, r10", asm)

    def test_pointer_difference_scales_by_element_size(self) -> None:
        asm = self._asm("long diff(int *left, int *right) { return left - right; }\n")

        self.assertIn("    sub rax, r10", asm)
        self.assertIn("    cqo", asm)
        self.assertIn("    mov r10, 4", asm)
        self.assertIn("    idiv r10", asm)

    def test_pointer_right_add_and_void_cast_expression_paths(self) -> None:
        asm = self._asm(
            """
int *right_pointer_add(long index, int *base) { return index + base; }
void *cast_array_to_void(void) { int values[2]; return (void *)values; }
int discard_with_void_cast(int x) { (void)(x + 1); return x; }
"""
        )

        self.assertIn("right_pointer_add:", asm)
        self.assertIn("    imul rax, 4", asm)
        self.assertIn("    add rax, r10", asm)
        self.assertIn("cast_array_to_void:", asm)
        self.assertIn("    lea rax, [rbp - 8]", asm)
        self.assertIn("discard_with_void_cast:", asm)
        self.assertIn("    add eax, r10d", asm)

    def test_postfix_pointer_update_under_deref_updates_pointer_slot(self) -> None:
        asm = self._asm(
            """
void f(long **stack, long *value) {
  long **sp = stack;
  *sp++ = value;
}
"""
        )
        self.assertIn("    lea r8, [rbp -", asm)
        self.assertIn("    mov rcx, QWORD PTR [r8]", asm)
        self.assertIn("    add rcx, 8", asm)
        self.assertIn("    mov QWORD PTR [r8], rcx", asm)
        self.assertNotIn("    mov QWORD PTR [rcx], rcx", asm)

    def test_for_init_declaration_scope_does_not_escape(self) -> None:
        asm = self._asm(
            """
int f(int i, int n) {
  for (int i = 0; i < n; i++) {
  }
  return i;
}
"""
        )
        self.assertIn(".L.f.for_end.3:\n    mov eax, DWORD PTR [rbp - 4]", asm)

    def test_shadowed_pointer_local_slot_keeps_pointer_width(self) -> None:
        asm = self._asm(
            """
struct C {
  void *filename;
  void *name;
  void *qualname;
  int flags;
  void *code;
  int first;
};
void *read(void);
void sink(struct C *);
void f(int tag) {
  int code = tag;
  if (tag) {
    void *filename = read();
    void *name = read();
    void *qualname = read();
    void *code = read();
    struct C con = {
      .filename = filename,
      .name = name,
      .qualname = qualname,
      .flags = 7,
      .code = code,
      .first = 11,
    };
    sink(&con);
  }
}
"""
        )
        self.assertIn(
            "    mov rax, QWORD PTR [rbp - 40]\n"
            "    pop rcx\n"
            "    lea r11, [rcx + 32]\n"
            "    mov QWORD PTR [r11], rax",
            asm,
        )
        self.assertNotIn(
            "    movsxd rax, eax\n    pop rcx\n    lea r11, [rcx + 32]",
            asm,
        )

    def test_array_operand_decays_for_unary_deref(self) -> None:
        asm = self._asm('int first(void) { return *"x"; }')
        self.assertIn("    lea rax, [rip + .LC0]", asm)
        self.assertIn("    movsx eax, BYTE PTR [rax]", asm)

    def test_wide_string_literal_emits_wchar_sized_units(self) -> None:
        asm = self._asm('int *errors(void) { return L"ab"; }')
        self.assertIn(
            "    .byte 97, 0, 0, 0, 98, 0, 0, 0, 0, 0, 0, 0",
            asm,
        )

    def test_wide_string_literal_is_aligned_after_byte_string(self) -> None:
        asm = self._asm('char *dash(void) { return "-"; } int *wide(void) { return L"strict"; }')
        wide_label = asm.index("    .byte 115, 0, 0, 0, 116, 0, 0, 0")
        self.assertIn(".p2align 2\n.LC1:", asm[:wide_label])

    def test_string_literal_subscript_forms_literal_address(self) -> None:
        asm = self._asm('int second(void) { return "abc"[1]; }')
        self.assertIn("    lea rax, [rip + .LC0]", asm)
        self.assertIn("    add rax, r10", asm)
        self.assertIn("    movsx eax, BYTE PTR [rax]", asm)

    def test_floating_unary_deref_uses_gpr_address_and_xmm_load(self) -> None:
        asm = self._asm("int f(double *value) { return *value < 1.0; }")
        self.assertIn("    mov rax, QWORD PTR [rbp - 8]", asm)
        self.assertIn("    movsd xmm0, [rax]", asm)

    def test_array_operand_decays_before_pointer_cast(self) -> None:
        asm = self._asm('char *empty(void) { return (char *)""; }')
        self.assertIn("    lea rax, [rip + .LC0]", asm)
        self.assertNotIn("cannot scalarize", asm)

    def test_array_operand_decays_before_integer_cast(self) -> None:
        asm = self._asm(
            """
typedef unsigned long uintptr_t;
int f(void) {
  char frame[88];
  return (uintptr_t)frame != 0;
}
"""
        )
        self.assertIn("    lea rax, [rbp -", asm)
        self.assertIn("    cmp rax, r10", asm)

    def test_extern_data_symbols_use_got_relocations(self) -> None:
        asm = self._asm(
            """
extern long PyExc_ValueError;
extern int _Py_NoneStruct;
long value(void) { return PyExc_ValueError; }
int *addr(void) { return &_Py_NoneStruct; }
"""
        )
        self.assertIn(
            "    mov rax, QWORD PTR [rip + PyExc_ValueError@GOTPCREL]\n"
            "    mov rax, QWORD PTR [rax]",
            asm,
        )
        self.assertIn("    mov rax, QWORD PTR [rip + _Py_NoneStruct@GOTPCREL]", asm)

    def test_extern_function_designator_uses_got_relocation(self) -> None:
        asm = self._asm(
            """
int target(void);
int (*addr(void))(void) { return target; }
"""
        )
        self.assertIn("    mov rax, QWORD PTR [rip + target@GOTPCREL]", asm)

    def test_comma_array_expression_address_uses_right_operand(self) -> None:
        asm = self._asm("int second(void) { int values[2]; return (0, values)[1]; }")
        self.assertIn("    lea rax, [rbp - 8]", asm)
        self.assertIn("    add rax, r10", asm)

    def test_file_scope_enum_identifier_lowers_to_constant(self) -> None:
        asm = self._asm(
            """
enum { SOCK_STREAM = 1, AF_INET = 2 };
int main(void) { return SOCK_STREAM + AF_INET == 3 ? 0 : 1; }
"""
        )
        self.assertIn("    mov eax, 1", asm)
        self.assertIn("    mov eax, 2", asm)
        self.assertNotIn("SOCK_STREAM", asm)
        self.assertNotIn("AF_INET", asm)

    def test_c_octal_integer_literals_parse(self) -> None:
        asm = self._asm("int main(void) { return 0377 == 255 ? 0 : 1; }")
        self.assertIn("    mov eax, 255", asm)

    def test_large_unsigned_switch_case_materializes_compare_immediate(self) -> None:
        asm = self._asm(
            """
int f(unsigned long value) {
  switch (value) {
    case 4611686018427387905UL: return 1;
    default: return 0;
  }
}
"""
        )
        self.assertIn("    mov r10, 4611686018427387905", asm)
        self.assertIn("    cmp rax, r10", asm)

    def test_control_flow_statements_lower_to_labels_and_jumps(self) -> None:
        asm = self._asm(
            """
int flow(int x) {
  int total = 0;
  int i = 0;
  while (i < 5) {
    i++;
    if (i == 2) continue;
    if (i == 4) break;
    total += i;
  }
  do {
    total += 10;
  } while (0);
  for (;;) {
    total += 20;
    break;
  }
  switch (x) {
    case 1:
      total += 100;
      goto done;
    case 2:
      total += 200;
      break;
    default:
      total += 300;
      break;
  }
done:
  return total;
}
"""
        )

        self.assertIn(".L.flow.while_cond.", asm)
        self.assertIn(".L.flow.while_end.", asm)
        self.assertIn(".L.flow.do_body.", asm)
        self.assertIn(".L.flow.do_cond.", asm)
        self.assertIn(".L.flow.for_cond.", asm)
        self.assertIn(".L.flow.for_post.", asm)
        self.assertIn(".L.flow.switch_case.", asm)
        self.assertIn(".L.flow.switch_default.", asm)
        self.assertIn(".L.flow.switch_end.", asm)
        self.assertIn(".L.flow.done:", asm)
        self.assertIn("    jmp .L.flow.done", asm)

    def test_statement_slot_collection_handles_else_for_expr_and_static_assert(self) -> None:
        asm = self._asm(
            """
int shape(int x) {
  int total = 0;
  _Static_assert(sizeof(int) == 4, "int");
  if (x) {
    int then_value = x + 1;
    total += then_value;
  } else {
    int else_value = x + 2;
    total += else_value;
  }
  int i = 0;
  for (i = 0; i < 2; i = i + 1) {
    int loop_value = i + total;
    total += loop_value;
  }
  return total;
}
"""
        )

        self.assertIn(".L.shape.if_else.", asm)
        self.assertIn(".L.shape.for_cond.", asm)
        self.assertIn(".L.shape.for_post.", asm)
        self.assertIn("    sub rsp, 32", asm)

    def test_tagged_enum_parameters_use_int_abi_slots(self) -> None:
        asm = self._asm(
            """
enum _expr_context { Load = 1, Store = 2, Del = 3 };
int use(enum _expr_context ctx) { return ctx == Store ? 0 : 1; }
"""
        )
        self.assertIn("    mov DWORD PTR [rbp - 4], edi", asm)
        self.assertIn("    cmp eax, r10d", asm)

    def test_enum_objects_participate_in_pointer_arithmetic_as_ints(self) -> None:
        asm = self._asm(
            """
enum Offset { ONE = 1 };
char *advance(char *p, enum Offset offset) { return p + offset; }
"""
        )
        self.assertIn("    add rax, r10", asm)

    def test_global_pointer_initializer_accepts_compound_literal_array(self) -> None:
        asm = self._asm(
            """
struct Entry { char *str; int type; };
struct Entry *sentinel = (struct Entry[]){ { (void *)0, -1 } };
"""
        )
        self.assertIn("sentinel:\n    .quad .Lcompound0", asm)
        self.assertIn(".Lcompound0:", asm)
        self.assertIn("    .quad 0", asm)
        self.assertIn("    .long 4294967295", asm)

    def test_array_compound_literal_decays_as_call_argument(self) -> None:
        asm = self._asm(
            """
long sum(int *items, long count);
long f(int a, int b, int c) {
  return sum((int[]){a, b, c}, 3);
}
"""
        )
        self.assertIn("    lea rcx, [rbp -", asm)
        self.assertIn("    mov rax, rcx", asm)
        self.assertIn("    call sum", asm)

    def test_global_record_initializer_accepts_function_pointer_address(self) -> None:
        asm = self._asm(
            """
struct Methods { int (*call)(int); };
int invoke(int value) { return value; }
struct Methods methods = { .call = &invoke };
"""
        )
        self.assertIn("methods:", asm)
        self.assertIn("    .quad invoke", asm)

    def test_global_pointer_initializer_accepts_array_element_member_address(self) -> None:
        asm = self._asm(
            """
struct Node { struct Node *next; long value; };
struct Bucket { long tag; struct Node root; struct Node *ptr; };
struct Bucket buckets[1] = { { 7, { 0, 0 }, &buckets[0].root } };
"""
        )
        self.assertIn("buckets:", asm)
        self.assertIn("    .quad buckets + 8", asm)

    def test_global_pointer_initializer_decays_nested_array_member_address(self) -> None:
        asm = self._asm(
            """
struct Dtoa { int tag; double preallocated[4]; };
struct Interp { long head; struct Dtoa dtoa; };
struct Runtime { long prefix; struct Interp main; };
struct Runtime runtime;
struct Holder { double *ptr; };
struct Holder holder = { .ptr = (&runtime.main)->dtoa.preallocated };
"""
        )
        self.assertIn("holder:", asm)
        self.assertIn("    .quad runtime + 24", asm)

    def test_global_pointer_initializer_folds_extern_static_compound_and_commuted_offsets(
        self,
    ) -> None:
        asm = self._asm(
            """
extern int external_value;
int *extern_ptr = &external_value;
int invoke(int value) { return value; }
int (*bare_fn)(int) = invoke;
int *literal_ptr = &(int){7};
static int table[4];
int *reverse_ptr = 1 + table;
int *minus_ptr = table + 3 - 1;
int f(void) {
  static int target = 5;
  static int *target_ptr = &target;
  return *target_ptr;
}
"""
        )

        self.assertIn("extern_ptr:\n    .quad external_value", asm)
        self.assertIn("bare_fn:\n    .quad invoke", asm)
        self.assertIn("literal_ptr:\n    .quad .Lcompound0", asm)
        self.assertIn("reverse_ptr:\n    .quad .L.table + 4", asm)
        self.assertIn("minus_ptr:\n    .quad .L.table + 8", asm)
        self.assertIn(".L.f.target_ptr:\n    .quad .L.f.target", asm)
        self.assertIn(".Lcompound0:\n    .long 7", asm)

    def test_global_pointer_initializer_helper_rejects_nonconstant_edges(self) -> None:
        result = compile_source(
            """
int scalar;
int table[4];
enum { FILE_ENUM = 4 };
int f(void) { enum { LOCAL_ENUM = 5 }; return LOCAL_ENUM; }
""",
            filename="pointer_initializer_helper.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)
        gen._func_sym = result.sema.functions["f"]

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        def typed_int(value: str = "1") -> IntLiteral:
            return typed_expr(IntLiteral(value), INT)

        scalar = typed_expr(Identifier("scalar"), INT)
        table = typed_expr(Identifier("table"), INT.array_of(4))
        self.assertEqual(gen._global_pointer_initializer_address(scalar), ("scalar", 0))
        local_enum = gen._lookup_enum_const("LOCAL_ENUM")
        self.assertIsNotNone(local_enum)
        assert local_enum is not None
        self.assertEqual(local_enum.value, 5)
        self.assertIsNone(
            gen._global_pointer_initializer_address(
                ConditionalExpr(
                    Identifier("not_constant"), StringLiteral('"a"'), StringLiteral('"b"')
                )
            )
        )
        self.assertIsNone(
            gen._global_pointer_binary_initializer_address(
                BinaryExpr("*", StringLiteral('"a"'), typed_int("1"))
            )
        )
        self.assertIsNone(
            gen._global_pointer_binary_initializer_address(BinaryExpr("-", typed_int("1"), table))
        )
        base_literal = StringLiteral('"base"')
        gen._type_map._map.pop(id(base_literal), None)
        self.assertIsNone(
            gen._global_pointer_offset_initializer_address(
                base_literal,
                typed_int("1"),
                "+",
            )
        )
        self.assertIsNone(
            gen._global_pointer_offset_initializer_address(scalar, typed_int("1"), "+")
        )
        self.assertIsNone(
            gen._global_lvalue_initializer_symbol(
                MemberExpr(Identifier("missing_record"), "field", False)
            )
        )
        self.assertIsNone(
            gen._global_lvalue_initializer_symbol(SubscriptExpr(scalar, typed_int("0")))
        )
        self.assertIsNone(
            gen._global_lvalue_initializer_symbol(SubscriptExpr(table, Identifier("not_constant")))
        )
        fn_array = typed_expr(Identifier("fn_array"), INT.function_of(()).array_of(2))
        self.assertIsNone(
            gen._global_lvalue_initializer_symbol(SubscriptExpr(fn_array, typed_int("0")))
        )
        missing_array = typed_expr(Identifier("missing_array"), INT.array_of(2))
        self.assertIsNone(
            gen._global_lvalue_initializer_symbol(SubscriptExpr(missing_array, typed_int("0")))
        )
        file_scope = gen._sema.file_scope
        object.__setattr__(gen._sema, "file_scope", None)
        try:
            self.assertIsNone(gen._global_lvalue_initializer_symbol(Identifier("missing_global")))
        finally:
            object.__setattr__(gen._sema, "file_scope", file_scope)
        self.assertIsNone(gen._global_lvalue_initializer_symbol(FloatLiteral("1.0")))
        with self.assertRaises(CodegenError):
            gen._emit_global_scalar_initializer(INT, Identifier("not_constant"))
        with self.assertRaises(CodegenError):
            gen._emit_global_zero(INT.function_of(()))

    def test_global_record_initializer_helper_edges(self) -> None:
        result = compile_source(
            """
int scalar;
union SameSize { int i; unsigned u; };
struct BitsPad { char c; unsigned a:3; int tail; };
struct Scalar { int value; int tail; };
struct HasArray { int values[2]; int tail; };
struct Flex { int len; char data[]; };
int f(void) { return 0; }
""",
            filename="x86_global_record_initializer_helper_edges.c",
            options=FrontendOptions(
                std="gnu11",
                no_standard_includes=True,
                host_machine="x86_64",
                target_os="linux",
            ),
        )
        gen = _X86_64AsmGen(result)

        def typed_expr(expr, type_: Type):
            gen._type_map.set(expr, type_)
            return expr

        def member(name: str) -> tuple[tuple[str, str], ...]:
            return (("member", name),)

        bits_pad = Type("struct BitsPad")
        scalar_record = Type("struct Scalar")
        has_array = Type("struct HasArray")
        flex_record = Type("struct Flex")

        gen._emit_global_record_initializer(
            Type("union SameSize"),
            InitList((InitItem(member("i"), IntLiteral("1")),)),
        )

        gen._emit_global_record_initializer(
            bits_pad,
            InitList(
                (
                    InitItem(member("c"), IntLiteral("1")),
                    InitItem(member("a"), IntLiteral("5")),
                    InitItem(member("tail"), IntLiteral("9")),
                )
            ),
        )
        self.assertIn("    .zero 3", gen._lines)

        gen._emit_global_record_initializer(
            bits_pad,
            InitList((InitItem(member("c"), IntLiteral("1")),)),
        )
        gen._emit_global_record_initializer(
            scalar_record,
            InitList((InitItem(member("value"), IntLiteral("11")),)),
        )
        gen._emit_global_record_initializer(
            has_array,
            InitList(
                (
                    InitItem(member("values"), IntLiteral("0")),
                    InitItem(member("tail"), IntLiteral("3")),
                )
            ),
        )
        gen._emit_global_record_initializer(
            flex_record,
            InitList(
                (
                    InitItem(member("len"), IntLiteral("1")),
                    InitItem(member("data"), InitList((InitItem((), IntLiteral("65")),))),
                )
            ),
        )
        gen._emit_global_record_initializer(
            flex_record,
            InitList((InitItem(member("len"), IntLiteral("1")),)),
        )
        self.assertIn("    .zero 8", gen._lines)
        self.assertIn("    .byte 65", gen._lines)

        with self.assertRaisesRegex(CodegenError, "scalar bit-field initializer"):
            gen._emit_global_record_initializer(
                bits_pad,
                InitList((InitItem(member("a"), InitList(())),)),
            )
        with self.assertRaisesRegex(CodegenError, "constant bit-field initializer"):
            gen._emit_global_record_initializer(
                bits_pad,
                InitList((InitItem(member("a"), Identifier("runtime_value")),)),
            )

        gen._sema.record_definitions["struct BadMember"] = (
            RecordMemberInfo("missing", Type("struct Missing")),
        )
        with self.assertRaisesRegex(CodegenError, "cannot size record member missing"):
            gen._emit_global_record_initializer(Type("struct BadMember"), InitList(()))

        original_type_size = gen._type_size
        gen._sema.record_definitions["struct EmptyMember"] = (
            RecordMemberInfo("empty", Type("struct Empty")),
        )
        original_member_align = gen._member_align
        gen._member_align = lambda _member: 1
        gen._type_size = lambda type_: (
            0
            if type_ in {Type("struct Empty"), Type("struct EmptyMember")}
            else original_type_size(type_)
        )
        try:
            gen._emit_global_record_initializer(Type("struct EmptyMember"), InitList(()))
        finally:
            gen._type_size = original_type_size
            gen._member_align = original_member_align

        gen._sema.record_definitions["union BadSize"] = (RecordMemberInfo("i", INT),)
        original_global_initializer = gen._emit_global_initializer

        def bad_union_member_size(type_: Type) -> int | None:
            if type_ == Type("union BadSize"):
                return 8
            if type_ == INT:
                return None
            return original_type_size(type_)

        gen._type_size = bad_union_member_size
        gen._emit_global_initializer = lambda _type, _init: None
        try:
            with self.assertRaisesRegex(CodegenError, "cannot size record union BadSize"):
                gen._emit_global_record_initializer(
                    Type("union BadSize"),
                    InitList((InitItem(member("i"), IntLiteral("1")),)),
                )
        finally:
            gen._emit_global_initializer = original_global_initializer
            gen._type_size = original_type_size

        with self.assertRaisesRegex(CodegenError, "cannot initialize record struct Missing"):
            gen._emit_record_compound_initializer_to_address(
                Type("struct Missing"), InitList(()), "rcx"
            )

        gen._type_size = lambda type_: None if type_ == scalar_record else original_type_size(type_)
        try:
            with self.assertRaisesRegex(CodegenError, "cannot size record struct Scalar"):
                gen._emit_record_compound_initializer_to_address(scalar_record, InitList(()), "rcx")
        finally:
            gen._type_size = original_type_size

        original_access_by_index = gen._record_member_access_by_index
        gen._record_member_access_by_index = lambda _type, _index: None
        try:
            with self.assertRaisesRegex(CodegenError, "cannot find record initializer member"):
                gen._emit_record_compound_initializer_to_address(
                    scalar_record,
                    InitList((InitItem(member("value"), IntLiteral("1")),)),
                    "rcx",
                )
        finally:
            gen._record_member_access_by_index = original_access_by_index

        with self.assertRaisesRegex(CodegenError, "scalar bit-field initializer"):
            gen._emit_record_compound_initializer_to_address(
                bits_pad,
                InitList((InitItem(member("a"), object()),)),
                "rcx",
            )
        with self.assertRaisesRegex(CodegenError, "requires aggregate initializer list"):
            gen._emit_record_compound_initializer_to_address(
                has_array,
                InitList((InitItem(member("values"), object()),)),
                "rcx",
            )

        gen._record_member_access_by_index = lambda _type, _index: _MemberAccess(
            0, Type("struct Missing")
        )
        try:
            with self.assertRaisesRegex(CodegenError, "cannot size aggregate initializer member"):
                gen._emit_record_compound_initializer_to_address(
                    scalar_record,
                    InitList((InitItem(member("value"), Identifier("missing_value")),)),
                    "rcx",
                )
        finally:
            gen._record_member_access_by_index = original_access_by_index

        with self.assertRaisesRegex(CodegenError, "requires scalar initializer"):
            gen._emit_record_compound_initializer_to_address(
                scalar_record,
                InitList((InitItem(member("value"), object()),)),
                "rcx",
            )

        original_emit_expr = gen._emit_expr
        gen._emit_expr = lambda _expr, _target="rax": _Value(INT, _ScalarInfo(4, 4, True), "r10")
        try:
            gen._emit_record_compound_initializer_to_address(
                scalar_record,
                InitList((InitItem(member("value"), IntLiteral("7")),)),
                "rcx",
            )
        finally:
            gen._emit_expr = original_emit_expr
        self.assertIn("    mov eax, r10d", gen._lines)

        self.assertIsNone(gen._record_member_access_by_index(Type("struct Missing"), 0))
        self.assertIsNone(gen._record_member_access_by_index(scalar_record, 99))
        flex_access = gen._record_member_access_by_index(flex_record, 1)
        self.assertEqual(flex_access, _MemberAccess(4, Type("char", array_lengths=(-1,))))
        self.assertIsNone(gen._record_member_access_by_index(Type("struct BadMember"), 0))

        with self.assertRaisesRegex(CodegenError, "nested array designators"):
            gen._array_initializer_items_by_index(
                InitList(
                    (
                        InitItem(
                            (("index", IntLiteral("0")), ("index", IntLiteral("1"))),
                            IntLiteral("7"),
                        ),
                    )
                )
            )
        with self.assertRaisesRegex(CodegenError, "global array designator"):
            gen._array_initializer_items_by_index(
                InitList((InitItem(member("value"), IntLiteral("7")),))
            )
        with self.assertRaisesRegex(CodegenError, "constant array designator"):
            gen._array_initializer_items_by_index(
                InitList((InitItem((("index", Identifier("index")),), IntLiteral("7")),))
            )

        scalar_members = gen._sema.record_definitions["struct Scalar"]
        with self.assertRaisesRegex(CodegenError, "too many record initializers"):
            gen._record_initializer_items_by_index(
                scalar_members,
                InitList(
                    (
                        InitItem((), IntLiteral("1")),
                        InitItem((), IntLiteral("2")),
                        InitItem((), IntLiteral("3")),
                    )
                ),
            )
        with self.assertRaisesRegex(CodegenError, "cannot find member missing"):
            gen._record_initializer_items_by_index(
                scalar_members,
                InitList((InitItem(member("missing"), IntLiteral("1")),)),
            )
        nested_items = gen._record_initializer_items_by_index(
            gen._sema.record_definitions["struct HasArray"],
            InitList(
                (
                    InitItem(
                        (("member", "values"), ("index", IntLiteral("1"))),
                        IntLiteral("7"),
                    ),
                )
            ),
        )
        self.assertIsInstance(nested_items[0].initializer, InitList)
        self.assertEqual(
            _X86_64AsmGen._record_initializer_next_positional_index(
                (RecordMemberInfo(None, INT, bit_width=3),),
                0,
            ),
            1,
        )

        gen._sema.record_definitions["struct AnonymousInner"] = (
            RecordMemberInfo("inner_field", INT),
        )
        gen._sema.record_definitions["struct AnonymousOuter"] = (
            RecordMemberInfo(None, Type("struct AnonymousInner")),
            RecordMemberInfo("tail", INT),
        )
        self.assertEqual(
            gen._record_initializer_member_index(
                gen._sema.record_definitions["struct AnonymousOuter"],
                "inner_field",
            ),
            (0, False),
        )

        with self.assertRaisesRegex(CodegenError, "known string array length"):
            gen._emit_global_char_array_string_initializer(
                Type("char", array_lengths=(-1,)),
                StringLiteral('"x"'),
            )
        with self.assertRaisesRegex(CodegenError, "constant floating initializer"):
            gen._emit_global_scalar_initializer(DOUBLE, Identifier("runtime_value"))
        gen._emit_global_scalar_initializer(FLOAT, FloatLiteral("1.0"))
        gen._emit_global_scalar_initializer(Type("long double"), FloatLiteral("1.0"))

        bad_ptr = typed_expr(Identifier("bad_ptr"), Type("struct Missing").pointer_to())
        gen._globals["bad_ptr"] = _Global("bad_ptr", Type("struct Missing").pointer_to(), False)
        self.assertIsNone(
            gen._global_pointer_offset_initializer_address(bad_ptr, IntLiteral("1"), "+")
        )

        with self.assertRaisesRegex(CodegenError, "cannot emit 3-byte integer"):
            gen._emit_global_int_constant(_ScalarInfo(3, 1, False), 1)
        line_count = len(gen._lines)
        gen._emit_bytes(b"")
        self.assertEqual(len(gen._lines), line_count)

        with self.assertRaisesRegex(CodegenError, "missing operand"):
            gen._sizeof_operand_type(SizeofExpr(None, None))
        typeof_seed = typed_expr(IntLiteral("1"), INT)
        self.assertEqual(
            gen._resolve_type_spec(TypeSpec("typeof", typeof_expr=typeof_seed)),
            INT,
        )
        self.assertEqual(gen._sizeof_operand_type(SizeofExpr(Identifier("scalar"), None)), INT)
        member_expr = MemberExpr(
            typed_expr(Identifier("scalar_holder"), scalar_record),
            "tail",
            False,
        )
        self.assertEqual(gen._sizeof_operand_type(SizeofExpr(member_expr, None)), INT)
        pointer_member_expr = MemberExpr(
            typed_expr(Identifier("scalar_holder_ptr"), scalar_record.pointer_to()),
            "tail",
            True,
        )
        self.assertEqual(gen._sizeof_operand_type(SizeofExpr(pointer_member_expr, None)), INT)
        bad_chain = MemberExpr(
            MemberExpr(
                typed_expr(Identifier("broken_holder"), scalar_record),
                "missing",
                False,
            ),
            "tail",
            False,
        )
        with self.assertRaisesRegex(CodegenError, "cannot resolve sizeof operand type"):
            gen._sizeof_operand_type(SizeofExpr(bad_chain, None))

        with self.assertRaisesRegex(CodegenError, "Arrow base is not pointer"):
            gen._record_member_access(
                MemberExpr(typed_expr(Identifier("record_value"), scalar_record), "value", True)
            )
        with self.assertRaisesRegex(CodegenError, "cannot find member missing"):
            gen._record_member_access(
                MemberExpr(typed_expr(Identifier("record_value"), scalar_record), "missing", False)
            )
        self.assertIsNone(gen._record_member_access_match(Type("struct Missing"), "field"))
        self.assertIsNone(gen._record_member_access_match(Type("union Small"), "missing"))
        gen._sema.record_definitions["union AnonymousScalar"] = (
            RecordMemberInfo(None, scalar_record),
        )
        self.assertIsNone(gen._record_member_access_match(Type("union AnonymousScalar"), "missing"))
        self.assertIsNone(gen._record_member_access_match(Type("struct BadMember"), "missing"))
        self.assertIsNone(gen._record_member_access_by_index(scalar_record, -1))
        self.assertIsNone(
            _X86_64AsmGen._record_init_first_member_designator_name(
                InitItem((("index", IntLiteral("0")),), IntLiteral("1"))
            )
        )
        self.assertEqual(
            gen._complete_array_string_initializer_type(INT, StringLiteral('"x"')),
            INT,
        )

        resolved_array = gen._complete_local_array_bound_type(
            DeclStmt(TypeSpec("int", array_lengths=(3,)), "values", None),
            Type("int", array_lengths=(-1,)),
        )
        self.assertEqual(resolved_array, Type("int", array_lengths=(3,)))
        unresolved_array = Type("int", array_lengths=(-1,))
        self.assertEqual(
            gen._complete_local_array_bound_type(
                DeclStmt(TypeSpec("int", array_lengths=(-1,)), "values", None),
                unresolved_array,
            ),
            unresolved_array,
        )

    def test_record_compound_literal_assignment_stores_members(self) -> None:
        asm = self._asm(
            """
enum Mode { REGULAR = 1 };
struct ModeState { int kind; char quote; int in_debug; };
int main(void) {
  struct ModeState stack[1];
  stack[0] = (struct ModeState){.kind = REGULAR, .quote = '\\0', .in_debug = 0};
  return stack[0].kind == REGULAR ? 0 : 1;
}
"""
        )
        self.assertIn("    mov DWORD PTR [r11], eax", asm)
        self.assertIn("    mov BYTE PTR [r11], al", asm)
        self.assertIn("    mov QWORD PTR [rcx], 0", asm)

    def test_record_compound_literal_zeroes_aggregate_member(self) -> None:
        asm = self._asm(
            """
union Payload { char bytes[56]; };
struct Holder { union Payload payload; int tag; };
int main(void) {
  struct Holder holder;
  holder = (struct Holder){0};
  return holder.tag;
}
"""
        )
        self.assertIn("    mov QWORD PTR [rcx], 0", asm)
        self.assertNotIn("XMMWORD PTR [r11], rax", asm)

    def test_record_compound_literal_copies_aggregate_member(self) -> None:
        asm = self._asm(
            """
struct Counts { int total; int extra; };
struct Result { int prefix; struct Counts counts; };
int main(void) {
  struct Counts counts = {1, 2};
  struct Result result;
  result = (struct Result){ .prefix = 3, .counts = counts };
  return result.counts.extra;
}
"""
        )
        self.assertIn("    lea rdx, [rbp - 8]", asm)
        self.assertIn("    mov r10, QWORD PTR [rdx]", asm)
        self.assertIn("    mov QWORD PTR [r11], r10", asm)

    def test_record_compound_literal_initializes_bitfields_and_array_members(self) -> None:
        asm = self._asm(
            """
struct Bits { unsigned a:3; unsigned :0; unsigned b:5; int tail; };
struct Holder { int tag; int values[2]; };

int bitfield_value(void) {
  struct Bits bits;
  bits = (struct Bits){ .a = 5, .b = 17, .tail = 9 };
  return bits.tail;
}

int bitfield_positional_value(void) {
  struct Bits bits;
  bits = (struct Bits){ 5, 17, 9 };
  return bits.tail;
}

int array_value(void) {
  struct Holder holder;
  holder = (struct Holder){ .tag = 3, .values = { 4, 5 } };
  return holder.values[1];
}
"""
        )

        self.assertIn("and r10d, 7", asm)
        self.assertIn("and r10d, 31", asm)
        self.assertIn("lea r11, [rcx + 8]", asm)
        self.assertIn("mov DWORD PTR [r11], eax", asm)

    def test_bitfield_member_compound_assignment_and_updates_emit_masks(self) -> None:
        asm = self._asm(
            """
struct State { unsigned kind:3; unsigned compact:5; int tail; };
void adjust(struct State *state) {
  state->kind += 2;
  state->compact--;
  ++state->kind;
  state->compact++;
}
"""
        )

        self.assertIn("    and eax, 7", asm)
        self.assertIn("    shr eax, 3", asm)
        self.assertIn("    sal r10d, 3", asm)
        self.assertIn("    mov edx, 4294967047", asm)

    def test_bitfield_postfix_update_preserves_old_result(self) -> None:
        asm = self._asm(
            """
struct State { unsigned kind:3; unsigned compact:5; int tail; };
int adjust(struct State *state) {
  int before = state->kind++;
  int after = state->kind--;
  return before * 10 + after;
}
"""
        )

        self.assertIn("    mov edx, eax", asm)
        self.assertIn("    add eax, 1", asm)
        self.assertIn("    sub eax, 1", asm)
        self.assertIn("    mov eax, edx", asm)

    def test_record_conditional_assignment_copies_selected_branch(self) -> None:
        asm = self._asm(
            """
struct Pair { long first; long second; };
void choose(int flag, struct Pair *out, struct Pair *left, struct Pair *right) {
  *out = flag ? *left : *right;
}
"""
        )
        self.assertIn(".L.choose.aggregate_cond_false.", asm)
        self.assertIn(".L.choose.aggregate_cond_end.", asm)
        self.assertIn("    mov r10, QWORD PTR [rdx]", asm)
        self.assertIn("    mov QWORD PTR [rcx], r10", asm)

    def test_conditional_union_return_uses_selected_branch_storage(self) -> None:
        asm = self._asm(
            """
union Ref { long value; void *ptr; };
union Ref choose(int flag, union Ref *left, union Ref *right) {
  return flag ? *left : *right;
}
"""
        )
        self.assertIn(".L.choose.aggregate_cond_false.", asm)
        self.assertIn(".L.choose.aggregate_cond_end.", asm)
        self.assertIn("    sub rsp, 16", asm)
        self.assertIn("    mov rax, QWORD PTR [rcx]", asm)

    def test_member_access_of_aggregate_call_results_uses_temporary_storage(self) -> None:
        asm = self._asm(
            """
struct Pair { int a; int b; };
struct Big { long a; long b; long c; };

struct Pair make_pair(void) { return (struct Pair){3, 4}; }
struct Big make_big(void) { return (struct Big){5, 6, 7}; }

int read_pair(void) { return make_pair().b; }
long read_big(void) { return make_big().c; }
"""
        )

        self.assertIn("call make_pair", asm)
        self.assertIn("    mov QWORD PTR [rcx], rax", asm)
        self.assertIn("    add rax, 4", asm)
        self.assertIn("call make_big", asm)
        self.assertIn("    lea rcx, [rbp - 24]", asm)
        self.assertIn("    add rax, 16", asm)

    def test_record_local_initializer_list_stores_members(self) -> None:
        asm = self._asm(
            """
struct View { void *buf; void *obj; };
int main(void) {
  struct View view = { (void *)0, (void *)0 };
  return view.buf == (void *)0 && view.obj == (void *)0 ? 0 : 1;
}
"""
        )
        self.assertIn("    lea rcx, [rbp - 16]", asm)
        self.assertIn("    mov QWORD PTR [rcx], 0", asm)
        self.assertIn("    mov QWORD PTR [rcx + 8], 0", asm)

    def test_record_initializer_accepts_array_member_initializer_list(self) -> None:
        asm = self._asm(
            """
struct Sip { unsigned long v0; unsigned char buf[8]; unsigned long c; };
unsigned long f(void) {
  struct Sip state = {0, {0}, 7};
  return state.c;
}
"""
        )
        self.assertIn("f:", asm)
        self.assertIn("    mov BYTE PTR [r10], al", asm)
        self.assertIn("    mov QWORD PTR [r11], rax", asm)

    def test_local_array_of_records_initializer_lists_store_elements(self) -> None:
        asm = self._asm(
            """
struct Entry { int count; int kind; };
int f(int left, int right) {
  struct Entry entries[3] = {
    {left, 1},
    {right, 2},
    {-1, 0},
  };
  return entries[1].kind;
}
"""
        )
        self.assertIn("    lea rcx, [rbp - 32]", asm)
        self.assertIn("    lea rcx, [rbp - 24]", asm)
        self.assertIn("    mov DWORD PTR [r11], eax", asm)
        self.assertIn("    lea r11, [rcx + 4]", asm)

    def test_local_array_of_unions_accepts_zero_element_initializer(self) -> None:
        asm = self._asm(
            """
union Ref { long value; void *ptr; };
long f(void) {
  union Ref refs[2] = {0};
  return refs[0].value;
}
"""
        )
        self.assertIn("f:", asm)
        self.assertIn("    mov QWORD PTR [rcx], 0", asm)

    def test_block_array_declaration_shadows_outer_pointer_for_initializer(self) -> None:
        asm = self._asm(
            """
void f(unsigned char *b3, int flag) {
  if (flag) {
    unsigned char b3[256] = {0};
    b3[0] = 1;
  }
}
"""
        )
        self.assertIn("f:", asm)
        self.assertIn("    mov BYTE PTR [rcx], al", asm)
        self.assertNotIn("does not support aggregate local initializer", asm)

    def test_nested_block_local_uses_enclosing_tagged_union_type(self) -> None:
        asm = self._asm(
            """
unsigned long f(double x, int flag) {
  union pun { double f; unsigned long i; };
  union pun ux = {x};
  if (flag) {
    union pun result = {.i = ux.i + 1};
    return result.i;
  }
  return ux.i;
}
"""
        )
        self.assertIn("f:", asm)
        self.assertNotIn("cannot size scalar type union", asm)
        self.assertIn("    mov QWORD PTR [r11], rax", asm)

    def test_three_byte_aggregate_parameter_uses_bytewise_integer_chunk(self) -> None:
        asm = self._asm(
            """
struct Tiny { unsigned char key_length; unsigned char digest_length; _Bool last_node; };
int take(struct Tiny index) {
  return index.key_length + index.digest_length + index.last_node;
}
int f(void) {
  struct Tiny index = {1, 2, 1};
  return take(index);
}
"""
        )
        self.assertIn("take:", asm)
        self.assertIn("    mov BYTE PTR [r10 + 2], r11b", asm)
        self.assertIn("    movzx r11d, BYTE PTR [r10 + 2]", asm)

    def test_compound_literals_initialize_scalar_and_array_storage(self) -> None:
        asm = self._asm(
            """
struct Pair { long left; long right; };

int scalar_literal(void) {
  int *p = &(int){7};
  return *p;
}

long array_of_records(void) {
  struct Pair *items = (struct Pair[]){{1, 2}, {3, 4}};
  return items[0].left + items[1].right * 10;
}
"""
        )

        self.assertIn("scalar_literal:", asm)
        self.assertIn("    mov DWORD PTR [rcx], eax", asm)
        self.assertIn("array_of_records:", asm)
        self.assertIn("    lea rcx, [rcx + 16]", asm)
        self.assertIn("    mov QWORD PTR [r11], rax", asm)
        self.assertIn("    lea r11, [rcx + 8]", asm)

    def test_statement_expression_void_forms_and_static_scalar_local_compile(self) -> None:
        asm = self._asm(
            """
int scalar_compound(void) { return (int){7}; }
int empty_statement_expr(void) { ({ }); return 3; }
int nonexpr_tail_statement_expr(int x) { ({ if (x) { x = x + 1; } }); return x; }
int static_scalar(void) { static int value = 7; return value; }
"""
        )

        self.assertIn("scalar_compound:", asm)
        self.assertIn("    mov DWORD PTR [rcx], eax", asm)
        self.assertIn("    mov eax, DWORD PTR [rbp - 4]", asm)
        self.assertIn("empty_statement_expr:", asm)
        self.assertIn("    mov eax, 3", asm)
        self.assertIn("nonexpr_tail_statement_expr:", asm)
        self.assertIn(".L.nonexpr_tail_statement_expr.if_else.", asm)
        self.assertIn("static_scalar:", asm)
        self.assertIn("    mov eax, DWORD PTR [rip + .L.static_scalar.value]", asm)
        self.assertIn(".L.static_scalar.value:\n    .long 7", asm)

    def test_ansi_const_probe_static_aggregate_initializers_compile(self) -> None:
        asm = self._asm(
            """
int main(void) {
  typedef int charset[2];
  const charset cs = { 0, 0 };
  struct point { int x, y; };
  static struct point const zero = {0, 0};
  return !cs[0] && !zero.x ? 0 : 1;
}
"""
        )
        self.assertIn(".L.main.zero:", asm)
        self.assertGreaterEqual(asm.count("    .long 0"), 2)
        self.assertIn("    mov DWORD PTR [rbp - 8], eax", asm)

    def test_static_local_incomplete_pointer_array_uses_initializer_length(self) -> None:
        asm = self._asm(
            """
int f(int index) {
  static char *keywords[] = {"left", "right", 0};
  return keywords[index] != 0;
}
"""
        )
        self.assertIn(".L.f.keywords:", asm)
        self.assertIn("    .quad .LC0", asm)
        self.assertIn("    .quad .LC1", asm)
        self.assertIn("    .quad 0", asm)
        self.assertIn("    lea rax, [rip + .L.f.keywords]", asm)

    def test_static_aggregate_identifier_and_func_name_literal_emit_addresses(self) -> None:
        options = FrontendOptions(
            std="c11",
            no_standard_includes=True,
            host_machine="x86_64",
            target_os="linux",
        )
        source = """
int callee(int x) { return x + 1; }
int (*function_address(void))(int) { return &callee; }
struct Point { int x; int y; };
struct Point get_static(void) {
  static struct Point point = { 4, 5 };
  return point;
}
int *static_scalar_address(void) { static int value = 9; return &value; }
const char *func_name(void) { return __func__; }
"""
        asm = generate_x86_64_asm(compile_source(source, filename="test.c", options=options))

        self.assertIn("    mov rax, QWORD PTR [rip + callee@GOTPCREL]", asm)
        self.assertIn("    lea rcx, [rip + .L.get_static.point]", asm)
        self.assertIn("    mov rax, QWORD PTR [rcx]", asm)
        self.assertIn("    lea rax, [rip + .L.static_scalar_address.value]", asm)
        self.assertIn("    lea rax, [rip + .LC", asm)
        self.assertIn(".L.get_static.point:\n    .long 4\n    .long 5", asm)
        self.assertIn(".L.static_scalar_address.value:\n    .long 9", asm)
        self.assertIn(
            ".byte 102, 117, 110, 99, 95, 110, 97, 109, 101, 0",
            asm,
        )

    def test_extern_incomplete_record_array_identifier_decays_without_sizing(self) -> None:
        asm = self._asm(
            """
struct Entry { long value; };
extern struct Entry table[];
struct Entry *cursor;
void f(void) { cursor = table; }
"""
        )
        self.assertIn("    mov rax, QWORD PTR [rip + table@GOTPCREL]", asm)
        self.assertIn("    mov rcx, QWORD PTR [rip + cursor@GOTPCREL]", asm)
        self.assertIn("    mov QWORD PTR [rcx], rax", asm)

    def test_local_floating_array_initializer_uses_xmm_store(self) -> None:
        asm = self._asm(
            """
double f(double value) {
  double values[2] = { value, value };
  float narrowed[1] = { (float)value };
  return values[0] + narrowed[0];
}
"""
        )
        self.assertIn("    movsd [rbp - 24], xmm0", asm)
        self.assertIn("    movss [rbp - 28], xmm0", asm)
        self.assertNotIn("movsd [rbp - 24], rax", asm)
        self.assertNotIn("movss [rbp - 28], rax", asm)

    def test_small_record_return_uses_integer_register_chunks(self) -> None:
        asm = self._asm(
            """
struct Pair { int kind; void *object; };
struct Pair make_pair(void) {
  struct Pair pair;
  pair.kind = 2;
  pair.object = (void *)0;
  return pair;
}
"""
        )
        self.assertIn("    mov rax, QWORD PTR [rcx]", asm)
        self.assertIn("    mov rdx, QWORD PTR [rcx + 8]", asm)

    def test_compound_literal_record_return_uses_stack_scratch(self) -> None:
        asm = self._asm(
            """
struct Counter { unsigned short value; };
struct Counter make_counter(unsigned short value) {
  return (struct Counter){ .value = value };
}
struct Counter wrap(unsigned short value) {
  return make_counter(value);
}
"""
        )
        self.assertIn("    sub rsp, 16", asm)
        self.assertIn("    mov WORD PTR [r11], ax", asm)
        self.assertIn("    movzx eax, WORD PTR [rcx]", asm)
        self.assertIn("    call make_counter", asm)

    def test_record_assignment_from_call_stores_return_chunks(self) -> None:
        asm = self._asm(
            """
struct Pair { int kind; void *object; };
struct Pair make_pair(void);
int main(void) {
  struct Pair pair;
  pair = make_pair();
  return pair.kind;
}
"""
        )
        self.assertIn("    call make_pair", asm)
        self.assertIn("    mov QWORD PTR [rcx], rax", asm)
        self.assertIn("    mov QWORD PTR [rcx + 8], rdx", asm)

    def test_record_local_initializer_from_call_stores_return_chunks(self) -> None:
        asm = self._asm(
            """
struct Pair { double real; double imag; };
struct Pair make_pair(void);
double f(void) {
  struct Pair pair = make_pair();
  return pair.imag;
}
"""
        )
        self.assertIn("    call make_pair", asm)
        self.assertIn("    movsd [rcx], xmm0", asm)
        self.assertIn("    movsd [rcx + 8], xmm1", asm)
        self.assertNotIn("XMMWORD PTR", asm)

    def test_mixed_aggregate_return_and_call_argument_use_fp_and_integer_chunks(
        self,
    ) -> None:
        asm = self._asm(
            """
struct Mixed { double real; int code; };
struct Mixed make_mixed(int code) {
  struct Mixed value;
  value.real = 1.5;
  value.code = code;
  return value;
}
struct Mixed choose_mixed(int flag) {
  return flag ? (struct Mixed){2.5, 3} : (struct Mixed){4.5, 5};
}
void take_mixed(struct Mixed value);
void calls(void) {
  take_mixed(make_mixed(7));
  take_mixed(choose_mixed(1));
}
"""
        )

        self.assertIn("make_mixed:", asm)
        self.assertIn("    movsd xmm0, [rcx]", asm)
        self.assertIn("    mov rax, QWORD PTR [rcx + 8]", asm)
        self.assertIn(".L.choose_mixed.aggregate_cond_false.", asm)
        self.assertIn("    movsd [rsp], xmm0", asm)
        self.assertIn("    pop rdi", asm)
        self.assertIn("    call take_mixed", asm)

    def test_record_call_result_can_be_record_call_argument(self) -> None:
        asm = self._asm(
            """
struct Pair { long first; long second; };
struct Pair make_pair(void);
struct Pair use_pair(struct Pair pair);
struct Pair wrap(void) { return use_pair(make_pair()); }
"""
        )
        self.assertEqual(asm.count("call make_pair"), 1)
        self.assertIn("    push rdx", asm)
        self.assertIn("    push rax", asm)
        self.assertIn("    call use_pair", asm)

    def test_record_call_result_member_access_materializes_slot(self) -> None:
        asm = self._asm(
            """
struct Pair { long first; long second; };
struct Pair make_pair(void);
long f(void) { return make_pair().second; }
"""
        )
        self.assertIn("    call make_pair", asm)
        self.assertIn("    mov QWORD PTR [rcx], rax", asm)
        self.assertIn("    mov QWORD PTR [rcx + 8], rdx", asm)
        self.assertIn("    mov rax, QWORD PTR [rax]", asm)

    def test_conditional_record_can_be_record_call_argument(self) -> None:
        asm = self._asm(
            """
struct Pair { long first; long second; };
long use_pair(struct Pair pair);
long choose(int flag, struct Pair *left, struct Pair *right) {
  return use_pair(flag ? *left : *right);
}
"""
        )
        self.assertIn(".L.choose.aggregate_arg_cond_false.", asm)
        self.assertIn(".L.choose.aggregate_arg_cond_end.", asm)
        self.assertIn("    mov r11, QWORD PTR [rbp - 16]", asm)
        self.assertIn("    mov rax, QWORD PTR [r11 + 8]", asm)
        self.assertIn("    call use_pair", asm)

    def test_conditional_aggregate_call_arg_does_not_leave_stale_stack_depth(self) -> None:
        asm = self._asm(
            """
struct S { long value; };
void take(struct S value);
void next(void *a, void *b, long c, void *d);
void f(int flag, struct S a, struct S b, void *p) {
  take(flag ? a : b);
  next(p, p, 1, p);
}
"""
        )
        self.assertIn("    call take\n", asm)
        self.assertNotIn("    call take\n    push 0\n", asm)
        self.assertIn("    call next\n", asm)

    def test_compound_literal_record_can_be_record_call_argument_once(self) -> None:
        asm = self._asm(
            """
struct Pair { long first; long second; };
long next(void);
long use_pair(struct Pair pair);
long f(void) { return use_pair((struct Pair){ next(), 2 }); }
"""
        )
        self.assertEqual(asm.count("call next"), 1)
        self.assertIn("    mov QWORD PTR [r11], rax", asm)
        self.assertIn("    mov rax, QWORD PTR [r11 + 8]", asm)
        self.assertIn("    call use_pair", asm)

    def test_floating_conditional_initializer_keeps_xmm_result(self) -> None:
        asm = self._asm(
            """
double choose(int flag, double left, double right) {
  double value = flag ? left : right;
  return value;
}
"""
        )
        self.assertIn("    movsd [rbp - 32], xmm0", asm)
        self.assertNotIn("movsd [rbp - 32], rax", asm)

    def test_conditional_result_coerces_each_branch_to_result_type(self) -> None:
        asm = self._asm(
            """
long f(int mode, long count) {
  return mode == 2 ? count : -1;
}
"""
        )
        self.assertIn("    movsxd rax, eax", asm)

    def test_large_record_return_uses_indirect_sret_pointer(self) -> None:
        asm = self._asm(
            """
struct Big { long a; long b; long c; };
struct Big make_big(long value) {
  struct Big big = { value, 2, 3 };
  return big;
}
int main(void) {
  struct Big big;
  big = make_big(1);
  return big.c == 3 ? 0 : 1;
}
"""
        )
        self.assertIn("    mov QWORD PTR [rbp - 8], rdi", asm)
        self.assertIn("    mov QWORD PTR [rbp - 16], rsi", asm)
        self.assertIn("    mov rdi, QWORD PTR [rsp + 8]", asm)
        self.assertIn("    call make_big", asm)

    def test_large_record_conditional_return_writes_sret_storage(self) -> None:
        asm = self._asm(
            """
struct Big { long a; long b; long c; };
struct Big choose(int flag, struct Big *left, struct Big *right) {
  return flag ? *left : *right;
}
"""
        )
        self.assertIn(".L.choose.aggregate_cond_false.", asm)
        self.assertIn(".L.choose.aggregate_cond_end.", asm)
        self.assertIn("    mov QWORD PTR [rbp - 8], rdi", asm)
        self.assertIn("    mov r10, QWORD PTR [rdx + 16]", asm)

    def test_floating_compound_assignment_uses_xmm_registers(self) -> None:
        asm = self._asm(
            """
static double values[] = {1.5, 0.0};
double addend(void) { return 2.5; }
int main(void) {
  values[0] += addend();
  return values[0] == 4.0 ? 0 : 1;
}
"""
        )
        self.assertIn("    addsd xmm0, xmm1", asm)
        self.assertIn("    movsd [rcx], xmm0", asm)
        self.assertNotIn("movsd rax", asm)

    def test_integer_rhs_of_floating_compound_assignment_uses_gpr(self) -> None:
        asm = self._asm(
            """
double f(double value, int exponent) {
  value *= 1 - exponent;
  value += exponent;
  value += 1;
  return value;
}
"""
        )
        self.assertIn("    mov eax, 1", asm)
        self.assertIn("    sub eax, r10d", asm)
        self.assertIn("    mov eax, DWORD PTR [rbp - 12]", asm)
        self.assertIn("    cvtsi2sd xmm0, rax", asm)
        self.assertNotIn("mov xmm0, 1", asm)

    def test_uint64_to_double_conversion_handles_high_bit(self) -> None:
        asm = self._asm(
            """
double to_double(unsigned long value) { return (double)value; }
"""
        )
        self.assertIn("    js .L.to_double.uint64_float_slow.", asm)
        self.assertIn("    cvtsi2sd xmm0, rax", asm)
        self.assertIn("    addsd xmm0, xmm0", asm)

    def test_two_double_record_call_argument_uses_sse_chunks(self) -> None:
        asm = self._asm(
            """
typedef struct { double real; double imag; } Py_complex;
double sum_complex(Py_complex value) { return value.real + value.imag; }
int main(void) {
  Py_complex value;
  value.real = 1.25;
  value.imag = 2.75;
  return sum_complex(value) == 4.0 ? 0 : 1;
}
"""
        )
        self.assertIn("    movsd [rbp - 16], xmm0", asm)
        self.assertIn("    movsd [rbp - 8], xmm1", asm)
        self.assertIn("    movsd xmm0, [rsp]", asm)
        self.assertIn("    movsd xmm1, [rsp]", asm)
        self.assertIn("    call sum_complex", asm)

    def test_anonymous_record_member_access_uses_promoted_offset(self) -> None:
        asm = self._asm(
            """
struct Obj {
  union {
    long full;
    struct {
      unsigned int ob_refcnt;
      unsigned short ob_overflow;
    };
  };
  long type;
};
int main(void) {
  struct Obj obj;
  obj.ob_refcnt = 7;
  return obj.ob_refcnt == 7 ? 0 : 1;
}
"""
        )
        self.assertIn("    mov DWORD PTR [rcx], eax", asm)
        self.assertIn("    mov eax, DWORD PTR [rax]", asm)

    def test_bitfield_member_read_write_masks_storage_unit(self) -> None:
        asm = self._asm(
            """
struct State {
  unsigned int interned:2;
  unsigned int kind:3;
  unsigned int compact:1;
};
int main(void) {
  struct State state;
  state.kind = 5;
  state.compact = 1;
  return state.kind == 5 && state.compact == 1 ? 0 : 1;
}
"""
        )
        self.assertIn("    sal r10d, 2", asm)
        self.assertIn("    mov edx, 4294967267", asm)
        self.assertIn("    and r11d, edx", asm)
        self.assertIn("    shr eax, 2", asm)
        self.assertIn("    and eax, 7", asm)

    def test_va_start_for_stack_variadic_args_initializes_va_list_slot(self) -> None:
        asm = self._asm(
            """
void sink(__builtin_va_list);
static inline void wrapper(
  int a, int b, int c, int d, int e, int f, const char *format, ...
) {
  __builtin_va_list va;
  __builtin_va_start(va, format);
  sink(va);
  __builtin_va_end(va);
}
int main(void) {
  wrapper(1, 2, 3, 4, 5, 6, "x", 42);
  return 0;
}
"""
        )
        self.assertIn("    mov DWORD PTR [rcx], 48", asm)
        self.assertIn("    lea r10, [rbp + 24]", asm)
        self.assertIn("    mov QWORD PTR [rcx + 8], r10", asm)
        self.assertIn("    mov QWORD PTR [rcx + 16], r10", asm)
        self.assertIn("    call sink", asm)
        self.assertNotIn("call __builtin_va_start", asm)
        self.assertNotIn("call __builtin_va_end", asm)

    def test_va_start_accounts_for_aggregate_and_float_fixed_parameters(self) -> None:
        asm = self._asm(
            """
struct Pair { long a; long b; };
void sink(__builtin_va_list);
void va_after_reg_aggregate(int prefix, struct Pair pair, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, pair);
  sink(ap);
  __builtin_va_end(ap);
}
void va_after_stack_aggregate(int a, int b, int c, int d, int e, int f, struct Pair pair, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, pair);
  sink(ap);
  __builtin_va_end(ap);
}
void va_after_double(double marker, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, marker);
  sink(ap);
  __builtin_va_end(ap);
}
void va_after_stack_double(
    double a, double b, double c, double d, double e, double f, double g, double h,
    double marker, ...
) {
  __builtin_va_list ap;
  __builtin_va_start(ap, marker);
  sink(ap);
  __builtin_va_end(ap);
}
"""
        )

        reg_aggregate = asm.split("va_after_reg_aggregate:", 1)[1].split(
            ".globl va_after_stack_aggregate", 1
        )[0]
        stack_aggregate = asm.split("va_after_stack_aggregate:", 1)[1].split(
            ".globl va_after_double", 1
        )[0]
        reg_double = asm.split("va_after_double:", 1)[1].split(".globl va_after_stack_double", 1)[0]
        stack_double = asm.split("va_after_stack_double:", 1)[1]

        self.assertIn("    mov DWORD PTR [rcx], 24", reg_aggregate)
        self.assertIn("    mov DWORD PTR [rcx + 4], 48", reg_aggregate)
        self.assertIn("    lea r10, [rbp + 16]", reg_aggregate)
        self.assertIn("    mov DWORD PTR [rcx], 48", stack_aggregate)
        self.assertIn("    lea r10, [rbp + 32]", stack_aggregate)
        self.assertIn("    mov DWORD PTR [rcx], 0", reg_double)
        self.assertIn("    mov DWORD PTR [rcx + 4], 64", reg_double)
        self.assertIn("    mov DWORD PTR [rcx + 4], 176", stack_double)
        self.assertIn("    lea r10, [rbp + 24]", stack_double)

    def test_va_arg_reads_register_save_area_and_advances_va_list(self) -> None:
        asm = self._asm(
            """
void *first_reg_arg(char *a, char *b, char *format, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, format);
  void *value = __builtin_va_arg(ap, void *);
  __builtin_va_end(ap);
  return value;
}
"""
        )
        self.assertIn("    mov QWORD PTR [rbp -", asm)
        self.assertIn("], rcx", asm)
        self.assertIn("    mov DWORD PTR [rcx], 24", asm)
        self.assertIn("    mov r11, QWORD PTR [rcx + 16]", asm)
        self.assertIn("    add DWORD PTR [rcx + 0], 8", asm)

    def test_va_arg_overflow_path_reads_stack_slot_and_advances_va_list(self) -> None:
        asm = self._asm(
            """
int first_stack_arg(int a, int b, int c, int d, int e, int f, const char *format, ...) {
  __builtin_va_list ap;
  __builtin_va_start(ap, format);
  int value = __builtin_va_arg(ap, int);
  __builtin_va_end(ap);
  return value;
}
"""
        )
        self.assertIn("    mov DWORD PTR [rcx], 48", asm)
        self.assertIn("    mov r11, QWORD PTR [rcx + 8]", asm)
        self.assertIn("    mov eax, DWORD PTR [r11]", asm)
        self.assertIn("    add r11, 8", asm)
        self.assertIn("    mov QWORD PTR [rcx + 8], r11", asm)

    def test_va_copy_from_parameter_uses_pointed_sysv_va_list(self) -> None:
        asm = self._asm(
            """
void use(__builtin_va_list);
void copy_param(const char *format, __builtin_va_list incoming) {
  __builtin_va_list local;
  __builtin_va_copy(local, incoming);
  use(local);
}
"""
        )
        self.assertIn("    mov QWORD PTR [rbp -", asm)
        self.assertIn("], rsi", asm)
        self.assertIn("    lea rcx, [rbp -", asm)
        self.assertIn("    mov rdx, QWORD PTR [rbp -", asm)
        self.assertIn("    mov r10, QWORD PTR [rdx]", asm)
        self.assertIn("    mov QWORD PTR [rcx + 16], rax", asm)

    def test_va_arg_from_parameter_uses_pointed_sysv_va_list(self) -> None:
        asm = self._asm(
            """
void *next_param(__builtin_va_list incoming) {
  return __builtin_va_arg(incoming, void *);
}
"""
        )
        self.assertIn("    mov rcx, QWORD PTR [rbp -", asm)
        self.assertIn("    mov eax, DWORD PTR [rcx + 0]", asm)
        self.assertIn("    mov r11, QWORD PTR [rcx + 16]", asm)

    def test_control_flow_calls_and_pointers_run_on_native_linux(self) -> None:
        source = """
int add(int a, int b) { return a + b; }
int main(void) {
  int values[3] = {1, 2, 3};
  int *p = values;
  int sum = 0;
  for (int i = 0; i < 3; i++) {
    sum += *(p + i);
  }
  if (add(sum, 1) != 7) return 1;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_records_globals_switch_and_offsetof_run_on_native_linux(self) -> None:
        source = """
struct Pair { int a; long b; };
int g = 4;
static int h = 5;
int pick(int x) {
  switch (x) {
  case 1: return g;
  case 2: return h;
  default: return 9;
  }
}
int main(void) {
  struct Pair p;
  p.a = 3;
  p.b = 8;
  if (__builtin_offsetof(struct Pair, b) != 8) return 1;
  if (sizeof(struct Pair) != 16) return 2;
  if (p.a + (int)p.b != 11) return 3;
  if (pick(1) != 4 || pick(2) != 5 || pick(3) != 9) return 4;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_floating_calls_and_stack_args_run_on_native_linux(self) -> None:
        source = """
double add(double a, double b) { return a + b; }
double ninth(
  double a, double b, double c, double d, double e,
  double f, double g, double h, double i
) { return i; }
int main(void) {
  double x = add(1.25, 2.75);
  double y = ninth(1, 2, 3, 4, 5, 6, 7, 8, 9);
  if (x != 4.0) return 1;
  if (y != 9.0) return 2;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_string_literal_call_argument_decay_runs_on_native_linux(self) -> None:
        source = """
int first(const char *s) { return s[0]; }
int main(void) { return first("ok") == 'o' ? 0 : 1; }
"""
        self.assertEqual(self._run(source), 0)

    def test_floating_compound_assignment_runs_on_native_linux(self) -> None:
        source = """
static double values[] = {1.5, 0.0};
double addend(void) { return 2.5; }
int main(void) {
  values[0] += addend();
  return values[0] == 4.0 ? 0 : 1;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_two_double_record_call_argument_runs_on_native_linux(self) -> None:
        source = """
typedef struct { double real; double imag; } Py_complex;
double sum_complex(Py_complex value) { return value.real + value.imag; }
int main(void) {
  Py_complex value;
  value.real = 1.25;
  value.imag = 2.75;
  return sum_complex(value) == 4.0 ? 0 : 1;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_anonymous_record_member_access_runs_on_native_linux(self) -> None:
        source = """
struct Obj {
  union {
    long full;
    struct {
      unsigned int ob_refcnt;
      unsigned short ob_overflow;
    };
  };
  long type;
};
int main(void) {
  struct Obj obj;
  obj.ob_refcnt = 7;
  return obj.ob_refcnt == 7 ? 0 : 1;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_bitfield_member_access_runs_on_native_linux(self) -> None:
        source = """
struct State {
  unsigned int interned:2;
  unsigned int kind:3;
  unsigned int compact:1;
};
int main(void) {
  struct State state;
  state.interned = 3;
  state.kind = 5;
  state.compact = 1;
  if (state.interned != 3) return 1;
  if (state.kind != 5) return 2;
  if (state.compact != 1) return 3;
  state.kind += 1;
  if (state.kind != 6) return 4;
  state.compact--;
  return state.compact == 0 ? 0 : 5;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_postfix_pointer_update_under_deref_runs_on_native_linux(self) -> None:
        source = """
int main(void) {
  long first = 1;
  long second = 2;
  long *items[2] = {0, 0};
  long **sp = items;
  *sp++ = &first;
  *sp++ = &second;
  if (sp != items + 2) return 1;
  if (items[0] != &first) return 2;
  if (items[1] != &second) return 3;
  return 0;
}
"""
        self.assertEqual(self._run(source), 0)

    def test_for_init_shadow_does_not_overwrite_parameter_on_native_linux(self) -> None:
        source = """
int keep_outer_for_index(int i, int n) {
  for (int i = 0; i < n; i++) {
  }
  return i == 7 ? 0 : 1;
}
int main(void) {
  return keep_outer_for_index(7, 3);
}
"""
        self.assertEqual(self._run(source), 0)


if __name__ == "__main__":
    unittest.main()
