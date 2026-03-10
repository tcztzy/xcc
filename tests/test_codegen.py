import unittest
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc.ast import (
    AlignofExpr,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CallExpr,
    CastExpr,
    CharLiteral,
    CompoundStmt,
    ConditionalExpr,
    ContinueStmt,
    DeclGroupStmt,
    DeclStmt,
    DoWhileStmt,
    Expr,
    ExprStmt,
    FloatLiteral,
    ForStmt,
    FunctionDef,
    Identifier,
    IfStmt,
    InitItem,
    InitList,
    IntLiteral,
    NullStmt,
    Param,
    ReturnStmt,
    SizeofExpr,
    Stmt,
    StringLiteral,
    TypeSpec,
    TypedefDecl,
    UnaryExpr,
    UpdateExpr,
    WhileStmt,
    TranslationUnit,
)
from xcc.codegen import (
    _FunctionLayout,
    _GlobalObject,
    _NativeCodeGenerator,
    _StackSlot,
    generate_native_assembly,
)
from xcc.diag import CodegenError
from xcc.frontend import FrontendResult, compile_source
from xcc.options import FrontendOptions
from xcc.sema import SemaUnit, TypeMap
from xcc.types import INT, LONG, VOID, Type


class _UnsupportedStmt(Stmt):
    pass


class _UnsupportedExpr(Expr):
    pass


class CodegenTests(unittest.TestCase):
    def _compile(self, source: str, *, std: str = "gnu11") -> FrontendResult:
        return compile_source(source, filename="<codegen>", options=FrontendOptions(std=std))

    def _generator(self, source: str = "") -> _NativeCodeGenerator:
        result = FrontendResult(
            filename="<codegen>",
            source=source,
            preprocessed_source=source,
            pp_tokens=[],
            tokens=[],
            unit=TranslationUnit(functions=[], declarations=[], externals=[]),
            sema=SemaUnit({}, TypeMap()),
            include_trace=(),
            macro_table=(),
        )
        return _NativeCodeGenerator(result)

    def _enter_function(self, generator: _NativeCodeGenerator) -> None:
        generator._current_function = FunctionDef(TypeSpec("int"), "main", [], CompoundStmt([]))
        generator._current_layout = _FunctionLayout({}, {}, 0)
        generator._current_scopes = [{}]
        generator._return_label = "L_return"

    def _set_type(self, generator: _NativeCodeGenerator, expr: Expr, type_: Type) -> None:
        generator._type_map.set(expr, type_)

    def test_generate_native_assembly_platform_gate_and_source_scanner(self) -> None:
        result = self._compile("int main(void){return 0;}\n")
        with patch("xcc.codegen.native_backend_available", return_value=False):
            with self.assertRaisesRegex(CodegenError, "only available on macOS arm64"):
                generate_native_assembly(result)

        generator = self._generator('/* asm */ char *s = "asm"; // asm\n')
        generator._reject_asm_source()
        generator = self._generator('char *s = "unterminated;\n')
        generator._reject_asm_source()
        generator = self._generator("char q = '\\''; __asm__(\"x\");\n")
        with self.assertRaisesRegex(CodegenError, "GNU asm is not supported"):
            generator._reject_asm_source()

    def test_generate_native_assembly_emits_supported_program(self) -> None:
        source = """
int puts(const char *);
void noop(void) { return; }
int zero(void) { return 0; }
long gl = 1;
int helper(int x, int y) { return x + y; }
int main(void) {
    int a = 1, b = 2;
    long big = 0x123456789abcL;
    { int c = 3; a = c; }
    if (a) a = 4;
    if (a) a = 5; else a = 6;
	    while (a) { a--; if (a) continue; break; }
	    do { a++; } while (a < 2);
	    for (int i = 0; i < 2; i++) { a += i; }
	    for (a = 0; a < 2; a++) { a |= 1; }
	    for (; a < 3;) { a++; }
	    a = +a;
    a = -a;
    a = ~a;
    a = !a;
    a = a + b;
    a = a - b;
    a = a * b;
    a = a / b;
    a = a % b;
    a = a & b;
    a = a ^ b;
    a = a | b;
    a = a << 1;
    a = a >> 1;
    a += 1;
    a -= 1;
    a *= 1;
    a /= 1;
    a %= 1;
    a &= 1;
    a ^= 1;
    a |= 1;
    a <<= 1;
    a >>= 1;
    a++;
    a--;
    a = a && b;
    a = a || b;
    a = a < b;
    a = a <= b;
    a = a > b;
    a = a >= b;
    a = a == b;
    a = a != b;
    a = (a, b ? a : b);
    (void)a;
    a = (int)big;
    gl = (long)a;
    a = sizeof(long);
    a = _Alignof(long);
    noop();
    zero();
    puts("hi");
    return helper(a, (int)gl) + 'a';
}
"""
        with patch("xcc.codegen.native_backend_available", return_value=True):
            assembly = generate_native_assembly(self._compile(source))
        for text in (
            ".data",
            ".text",
            ".section __TEXT,__cstring,cstring_literals",
            "bl _helper",
            "bl _noop",
            "bl _zero",
            "bl _puts",
            "movk",
            "add ",
            "sub ",
            "mul ",
            "sdiv ",
            "msub ",
            "and ",
            "eor ",
            "orr ",
            "lsl ",
            "asr ",
            "cset w0, eq",
            "cbz w0",
            "cbnz w0",
            "_gl:",
        ):
            self.assertIn(text, assembly)

    def test_codegen_helper_methods_cover_manual_paths(self) -> None:
        generator = self._generator()
        typedef = TypedefDecl(TypeSpec("int"), "word")
        static_assert = TypedefDecl(TypeSpec("int"), "other")
        generator._collect_top_level(DeclGroupStmt([DeclStmt(TypeSpec("int"), "g", None)]))
        self.assertIn("g", generator._global_objects)
        generator._collect_top_level(typedef)
        generator._collect_top_level(static_assert)
        generator._collect_top_level(DeclStmt(TypeSpec("int"), None, None))
        with self.assertRaisesRegex(CodegenError, "Unsupported native codegen declaration"):
            generator._collect_top_level(_UnsupportedStmt())
        with self.assertRaisesRegex(CodegenError, "storage for global 's'"):
            generator._collect_top_level(
                DeclStmt(TypeSpec("int"), "s", None, storage_class="static")
            )
        with self.assertRaisesRegex(CodegenError, "Aggregate initializer"):
            generator._collect_top_level(
                DeclStmt(
                    TypeSpec("int"),
                    "agg",
                    InitList((InitItem((), IntLiteral("1")),)),
                )
            )

        generator = self._generator()
        generator._global_objects = {
            "ext": _GlobalObject("ext", INT, None, True),
            "zero": _GlobalObject("zero", INT, None, False),
            "one": _GlobalObject("one", LONG, IntLiteral("1"), False),
        }
        generator._emit_globals()
        self.assertIn(".data", generator._lines)
        self.assertIn(".zero 4", generator._lines)
        self.assertIn(".quad 1", generator._lines)
        empty_lines = list(generator._lines)
        generator._emit_strings()
        self.assertEqual(generator._lines, empty_lines)
        self.assertEqual(generator._intern_string('"hi"'), generator._intern_string('"hi"'))
        generator._string_labels = {'"hi"': "L_str"}
        generator._emit_strings()
        self.assertIn(".section __TEXT,__cstring,cstring_literals", generator._lines)

        self.assertEqual(generator._parse_int_literal("42"), 42)
        self.assertEqual(generator._parse_int_literal("077"), 0o77)
        self.assertEqual(generator._parse_int_literal("0x10"), 16)
        self.assertEqual(generator._parse_char_literal("'a'"), 97)
        self.assertEqual(generator._parse_char_literal("'\\n'"), 10)
        self.assertEqual(
            generator._eval_global_initializer(UnaryExpr("+", IntLiteral("7")), INT), 7
        )
        with self.assertRaisesRegex(CodegenError, "Unsupported native character literal"):
            generator._parse_char_literal("'ab'")
        with self.assertRaisesRegex(CodegenError, "Unsupported native character literal"):
            generator._parse_char_literal("'\\x'")
        with self.assertRaisesRegex(CodegenError, "Unsupported native character literal"):
            generator._parse_char_literal("a")

        self.assertEqual(generator._resolve_object_type(TypeSpec("int"), "x"), INT)
        self.assertEqual(generator._resolve_object_type(TypeSpec("long"), "x"), LONG)
        self.assertEqual(generator._resolve_object_type(TypeSpec("void"), "x"), VOID)
        self.assertEqual(
            generator._resolve_object_type(TypeSpec("char", declarator_ops=(("ptr", 0),)), "x"),
            Type("char", declarator_ops=(("ptr", 0),)),
        )
        with self.assertRaisesRegex(CodegenError, "declarator"):
            generator._resolve_object_type(TypeSpec("int", declarator_ops=(("arr", 1),)), "x")
        with self.assertRaisesRegex(CodegenError, "struct pair"):
            generator._resolve_object_type(TypeSpec("struct pair"), "x")

        self.assertEqual(generator._asm_string('"hi"'), '"hi"')
        self.assertEqual(generator._asm_string('u8"hi\\n"'), '"hi\\\\n"')
        self.assertEqual(generator._eval_global_initializer(IntLiteral("7"), INT), 7)
        self.assertEqual(generator._eval_global_initializer(CharLiteral("'a'"), INT), 97)
        self.assertEqual(
            generator._eval_global_initializer(UnaryExpr("-", IntLiteral("7")), INT), -7
        )
        self.assertEqual(
            generator._eval_global_initializer(UnaryExpr("~", IntLiteral("1")), INT), ~1
        )
        self.assertEqual(
            generator._eval_global_initializer(UnaryExpr("!", IntLiteral("0")), INT), 1
        )
        self.assertEqual(
            generator._eval_global_initializer(
                BinaryExpr("+", IntLiteral("2"), IntLiteral("3")), INT
            ),
            5,
        )
        self.assertEqual(
            generator._eval_global_initializer(
                BinaryExpr("&&", IntLiteral("1"), IntLiteral("2")), INT
            ),
            1,
        )
        self.assertEqual(
            generator._eval_global_initializer(
                CastExpr(TypeSpec("int"), IntLiteral("9")),
                INT,
            ),
            9,
        )
        expr = Identifier("x")
        self._set_type(generator, expr, LONG)
        self.assertEqual(generator._eval_sizeof(SizeofExpr(expr, None)), 8)
        self.assertEqual(generator._eval_sizeof(SizeofExpr(None, TypeSpec("int"))), 4)
        self.assertEqual(generator._eval_alignof(AlignofExpr(expr, None)), 8)
        self.assertEqual(generator._eval_alignof(AlignofExpr(None, TypeSpec("int"))), 4)
        self.assertEqual(
            generator._eval_global_initializer(SizeofExpr(None, TypeSpec("int")), INT),
            4,
        )
        self.assertEqual(
            generator._eval_global_initializer(AlignofExpr(None, TypeSpec("long")), INT),
            8,
        )
        with self.assertRaisesRegex(CodegenError, "Unsupported global initializer"):
            generator._eval_global_initializer(StringLiteral('"nope"'), INT)
        with self.assertRaisesRegex(CodegenError, "Unsupported global initializer"):
            generator._eval_global_initializer(UnaryExpr("&", IntLiteral("1")), INT)
        with self.assertRaisesRegex(CodegenError, "Unsupported global initializer"):
            generator._eval_global_initializer(
                BinaryExpr("??", IntLiteral("1"), IntLiteral("2")), INT
            )

        generator._emit_immediate(0, 0, INT)
        generator._emit_immediate(0, 0x12345678, LONG)
        with patch.object(generator, "_storage_width", return_value=0):
            generator._emit_immediate(0, 0, INT)
        generator._emit_address("_x")
        slot = _StackSlot(8, INT)
        generator._load_local(slot, 0)
        generator._store_local(slot, 0)
        generator._spill_primary(INT)
        generator._reload_secondary()
        generator._reload_primary()
        self.assertIn("movz w0, #0, lsl #0", generator._lines)
        self.assertIn("movk x0, #4660, lsl #16", generator._lines)

    def test_codegen_error_paths_cover_direct_helpers(self) -> None:
        generator = self._generator()
        self._enter_function(generator)

        local = Identifier("local")
        other = Identifier("other")
        pointer = Identifier("pointer")
        generator._current_scopes = [
            {"local": _StackSlot(8, INT), "pointer": _StackSlot(16, INT.pointer_to())}
        ]
        generator._current_layout = _FunctionLayout({}, {}, 0)
        generator._function_names.add("func_value")
        generator._global_objects["glob"] = _GlobalObject("glob", INT, None, False)

        self._set_type(generator, local, INT)
        self._set_type(generator, other, INT)
        self._set_type(generator, pointer, INT.pointer_to())

        generator._emit_identifier("local")
        generator._emit_identifier("glob")
        with self.assertRaisesRegex(CodegenError, "Function designators are not supported"):
            generator._emit_identifier("func_value")
        with self.assertRaisesRegex(CodegenError, "Unsupported native identifier reference"):
            generator._emit_identifier("missing")
        with self.assertRaisesRegex(CodegenError, "Unsupported native assignment target: missing"):
            generator._store_target("missing", INT)

        with self.assertRaisesRegex(CodegenError, "Unsupported native codegen statement"):
            generator._reserve_stmt_slots(_UnsupportedStmt(), {}, 0)
        with self.assertRaisesRegex(CodegenError, "Unsupported native codegen statement"):
            generator._emit_stmt(_UnsupportedStmt())
        with self.assertRaisesRegex(CodegenError, "break is not supported here"):
            generator._emit_stmt(BreakStmt())
        with self.assertRaisesRegex(CodegenError, "continue is not supported here"):
            generator._emit_stmt(ContinueStmt())

        local_decl = DeclStmt(
            TypeSpec("int"),
            "tmp",
            InitList((InitItem((), IntLiteral("1")),)),
        )
        generator._current_layout = _FunctionLayout({}, {id(local_decl): _StackSlot(8, INT)}, 0)
        with self.assertRaisesRegex(CodegenError, "Aggregate initializer"):
            generator._emit_stmt(local_decl)
        generator._emit_stmt(DeclStmt(TypeSpec("int"), None, None))
        generator._emit_stmt(NullStmt())
        generator._emit_stmt(TypedefDecl(TypeSpec("int"), "word"))

        float_expr = FloatLiteral("1.0")
        with self.assertRaisesRegex(CodegenError, "Floating-point expressions"):
            generator._emit_expr(float_expr)
        unary = UnaryExpr("&", IntLiteral("1"))
        self._set_type(generator, unary.operand, INT)
        self._set_type(generator, unary, INT)
        with self.assertRaisesRegex(CodegenError, "Unsupported native codegen unary operator"):
            generator._emit_expr(unary)
        with self.assertRaisesRegex(CodegenError, "Unsupported native codegen expression"):
            generator._emit_expr(_UnsupportedExpr())

        assign = AssignExpr("=", local, IntLiteral("1"))
        self._set_type(generator, assign.value, INT)
        self.assertEqual(generator._emit_assign_expr(assign), INT)
        with self.assertRaisesRegex(CodegenError, "only supports assignments to identifiers"):
            generator._emit_assign_expr(AssignExpr("=", IntLiteral("1"), IntLiteral("2")))
        self._set_type(generator, other, INT)
        missing_assign = AssignExpr("=", other, IntLiteral("1"))
        self._set_type(generator, missing_assign.value, INT)
        with self.assertRaisesRegex(CodegenError, "Unsupported native assignment target: other"):
            generator._emit_assign_expr(missing_assign)
        bad_op = AssignExpr("**=", local, IntLiteral("1"))
        self._set_type(generator, bad_op.value, INT)
        with self.assertRaisesRegex(CodegenError, "assignment operator"):
            generator._emit_assign_expr(bad_op)
        bad_type = AssignExpr("+=", pointer, IntLiteral("1"))
        self._set_type(generator, bad_type.value, INT)
        with self.assertRaisesRegex(CodegenError, "assignment target type"):
            generator._emit_assign_expr(bad_type)

        update = UpdateExpr("++", local, True)
        self._set_type(generator, update, INT)
        self.assertEqual(generator._emit_update_expr(update), INT)
        with self.assertRaisesRegex(CodegenError, "only supports updates on identifiers"):
            generator._emit_update_expr(UpdateExpr("++", IntLiteral("1"), False))
        bad_update_type = UpdateExpr("++", pointer, False)
        self._set_type(generator, bad_update_type, INT.pointer_to())
        with self.assertRaisesRegex(CodegenError, "update operand type"):
            generator._emit_update_expr(bad_update_type)
        bad_update_op = UpdateExpr("**", local, False)
        self._set_type(generator, bad_update_op, INT)
        with self.assertRaisesRegex(CodegenError, "update operator"):
            generator._emit_update_expr(bad_update_op)

        callee = Identifier("callee")
        direct_call = CallExpr(callee, [])
        generator._function_types["callee"] = INT.function_of(())
        self.assertEqual(generator._emit_call_expr(direct_call), INT)
        with self.assertRaisesRegex(CodegenError, "direct function calls"):
            generator._emit_call_expr(CallExpr(IntLiteral("1"), []))
        with self.assertRaisesRegex(CodegenError, "Unknown function"):
            generator._emit_call_expr(CallExpr(Identifier("missing_fn"), []))
        generator._function_types["value"] = INT
        with self.assertRaisesRegex(CodegenError, "Call target is not supported"):
            generator._emit_call_expr(CallExpr(Identifier("value"), []))
        generator._function_types["proto"] = INT.function_of(None)
        with self.assertRaisesRegex(CodegenError, "requires a prototype"):
            generator._emit_call_expr(CallExpr(Identifier("proto"), []))
        generator._function_types["var"] = INT.function_of((INT,), is_variadic=True)
        with self.assertRaisesRegex(CodegenError, "Variadic calls"):
            generator._emit_call_expr(CallExpr(Identifier("var"), [IntLiteral("1")]))
        generator._function_types["many"] = INT.function_of((INT,) * 9)
        with self.assertRaisesRegex(CodegenError, "at most 8 call arguments"):
            generator._emit_call_expr(
                CallExpr(Identifier("many"), [IntLiteral("1") for _ in range(9)])
            )

        long_expr = IntLiteral("1")
        self._set_type(generator, long_expr, LONG)
        generator._emit_branch_if_zero(long_expr, "L_wide")
        self.assertIn("cbz x0, L_wide", generator._lines)
        generator._emit_compare(INT)
        generator._emit_compare_zero(INT, 0)

        binary = BinaryExpr("??", IntLiteral("1"), IntLiteral("2"))
        self._set_type(generator, binary.left, INT)
        self._set_type(generator, binary.right, INT)
        self._set_type(generator, binary, INT)
        with self.assertRaisesRegex(CodegenError, "binary operator: \\?\\?"):
            generator._emit_binary_expr(binary)
        with self.assertRaisesRegex(CodegenError, "operand types"):
            generator._emit_binary_op("+", Type("struct bad"), INT)
        with self.assertRaisesRegex(CodegenError, "binary operator: \\?\\?"):
            generator._emit_binary_op("??", INT, INT)

        pointer_eq = BinaryExpr("==", pointer, pointer)
        self._set_type(generator, pointer_eq.left, INT.pointer_to())
        self._set_type(generator, pointer_eq.right, INT.pointer_to())
        self._set_type(generator, pointer_eq, INT)
        self.assertEqual(generator._binary_operand_type(pointer_eq), INT.pointer_to())
        pointer_add = BinaryExpr("+", pointer, pointer)
        self._set_type(generator, pointer_add.left, INT.pointer_to())
        self._set_type(generator, pointer_add.right, INT.pointer_to())
        self._set_type(generator, pointer_add, INT.pointer_to())
        with self.assertRaisesRegex(CodegenError, "Pointer operands are not supported"):
            generator._binary_operand_type(pointer_add)

        self.assertEqual(
            generator._resolve_return_type(
                FunctionDef(TypeSpec("void"), "noop", [], CompoundStmt([]))
            ),
            VOID,
        )
        with self.assertRaisesRegex(CodegenError, "at most 8 parameters"):
            generator._prepare_function_layout(
                FunctionDef(
                    TypeSpec("int"),
                    "wide",
                    [Param(TypeSpec("int"), f"p{index}") for index in range(9)],
                    CompoundStmt([]),
                )
            )
        self.assertEqual(
            generator._reserve_stmt_slots(DeclStmt(TypeSpec("int"), None, None), {}, 0),
            0,
        )
        with self.assertRaisesRegex(CodegenError, "storage for local 'tmp'"):
            generator._reserve_stmt_slots(
                DeclStmt(TypeSpec("int"), "tmp", None, storage_class="static"),
                {},
                0,
            )
        with self.assertRaisesRegex(CodegenError, "function storage"):
            generator._check_function_contract(
                FunctionDef(TypeSpec("int"), "f", [], CompoundStmt([]), storage_class="static")
            )
        with self.assertRaisesRegex(CodegenError, "function attributes"):
            generator._check_function_contract(
                FunctionDef(TypeSpec("int"), "f", [], CompoundStmt([]), is_inline=True)
            )
        with self.assertRaisesRegex(CodegenError, "Variadic functions"):
            generator._check_function_contract(
                FunctionDef(TypeSpec("int"), "f", [], CompoundStmt([]), is_variadic=True)
            )

        generator._ensure_supported_runtime_type(VOID, "void")
        generator._ensure_supported_runtime_type(INT.pointer_to(), "ptr")
        generator._ensure_supported_runtime_type(INT, "int")
        with self.assertRaisesRegex(CodegenError, "Unsupported native codegen type in bad"):
            generator._ensure_supported_runtime_type(Type("struct bad"), "bad")

        long_expr = IntLiteral("2")
        self._set_type(generator, long_expr, LONG)
        self._set_type(generator, BinaryExpr("||", long_expr, long_expr), INT)
        logical_or = BinaryExpr("||", long_expr, long_expr)
        self._set_type(generator, logical_or.left, LONG)
        self._set_type(generator, logical_or.right, LONG)
        self._set_type(generator, logical_or, INT)
        self.assertEqual(generator._emit_binary_expr(logical_or), INT)

        prefix = UpdateExpr("++", local, False)
        self._set_type(generator, prefix, INT)
        self.assertEqual(generator._emit_update_expr(prefix), INT)

        do_stmt = DoWhileStmt(CompoundStmt([]), long_expr)
        generator._emit_stmt(do_stmt)
        for_stmt = ForStmt(IntLiteral("1"), None, None, CompoundStmt([]))
        self._set_type(generator, for_stmt.init, INT)
        generator._emit_stmt(for_stmt)
        raw = generator._asm_string("raw")
        self.assertEqual(raw, '"raw"')
        generator._coerce_primary(INT, VOID)

        with patch.object(generator, "_ensure_supported_runtime_type"):
            with patch.object(
                generator,
                "_storage_width",
                side_effect=lambda type_: 4 if type_ == INT else 16,
            ):
                with self.assertRaisesRegex(CodegenError, "Unsupported native conversion"):
                    generator._coerce_primary(INT, LONG)
