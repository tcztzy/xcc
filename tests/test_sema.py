import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
import xcc.sema.constants as sema_constants
import xcc.sema.declarations as sema_declarations
import xcc.sema.expressions as sema_expressions
import xcc.sema.initializers as sema_initializers
import xcc.sema.layout as sema_layout
import xcc.sema.records as sema_records
import xcc.sema.statements as sema_statements
import xcc.sema.symbols as sema_symbols
import xcc.sema.type_helpers as sema_types
import xcc.sema.type_resolution as sema_type_resolution
from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CallExpr,
    CaseStmt,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundStmt,
    ConditionalExpr,
    DeclStmt,
    DefaultStmt,
    Expr,
    ExprStmt,
    FunctionDef,
    GenericExpr,
    FloatLiteral,
    Identifier,
    IfStmt,
    InitItem,
    InitList,
    IntLiteral,
    Param,
    RecordMemberDecl,
    ReturnStmt,
    SizeofExpr,
    StaticAssertDecl,
    Stmt,
    StringLiteral,
    SwitchStmt,
    TypedefDecl,
    TranslationUnit,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
)
from xcc.frontend import FrontendOptions, compile_source
from xcc.lexer import lex
from xcc.parser import parse
from xcc.sema import (
    Analyzer,
    FunctionSignature,
    RecordMemberInfo,
    Scope,
    SemaError,
    VarSymbol,
    analyze,
)
from xcc.types import (
    BOOL,
    CHAR,
    DOUBLE,
    FLOAT,
    INT,
    INT128,
    LLONG,
    LONG,
    LONGDOUBLE,
    SHORT,
    UCHAR,
    UINT,
    UINT128,
    ULLONG,
    ULONG,
    USHORT,
    VOID,
    Type,
)


def _body(func):
    assert func.body is not None
    return func.body


class SemaTests(unittest.TestCase):
    def test_sema_symbol_helpers_live_outside_entrypoint(self) -> None:
        self.assertEqual(
            sema_declarations.analyze_file_scope_decl.__module__, "xcc.sema.declarations"
        )
        self.assertEqual(sema_expressions.analyze_expr.__module__, "xcc.sema.expressions")
        self.assertEqual(sema_statements.analyze_stmt.__module__, "xcc.sema.statements")
        self.assertEqual(sema_type_resolution.resolve_type.__module__, "xcc.sema.type_resolution")
        self.assertEqual(
            sema_type_resolution.register_type_spec.__module__, "xcc.sema.type_resolution"
        )
        self.assertEqual(sema_symbols.SemaError.__module__, "xcc.sema.symbols")
        self.assertEqual(sema_symbols.Scope.__module__, "xcc.sema.symbols")
        self.assertEqual(sema_symbols.TypeMap.__module__, "xcc.sema.symbols")
        self.assertEqual(SemaError.__module__, "xcc.sema.symbols")
        self.assertEqual(Scope.__module__, "xcc.sema.symbols")
        self.assertEqual(VarSymbol.__module__, "xcc.sema.symbols")

    def test_sema_type_helpers_live_outside_entrypoint(self) -> None:
        analyzer = Analyzer()
        const_int = Type("int", qualifiers=("const",))
        self.assertEqual(sema_types.is_integer_type.__module__, "xcc.sema.type_helpers")
        self.assertTrue(sema_types.is_integer_type(INT))
        self.assertEqual(sema_types.integer_promotion(USHORT), INT)
        self.assertEqual(sema_types.usual_arithmetic_conversion(UINT, LONG), LONG)
        self.assertTrue(analyzer._is_floating_type(FLOAT))
        self.assertTrue(analyzer._is_arithmetic_type(DOUBLE))
        self.assertEqual(analyzer._unqualified_type(const_int), INT)
        self.assertEqual(analyzer._integer_rank(LLONG), 6)
        self.assertTrue(analyzer._is_signed_integer_type(LONG))
        self.assertEqual(analyzer._integer_promotion(USHORT), INT)
        self.assertEqual(analyzer._signed_range(INT), (-(1 << 31), (1 << 31) - 1))
        self.assertEqual(analyzer._unsigned_max(UINT), (1 << 32) - 1)
        self.assertTrue(analyzer._signed_can_represent_unsigned(LONG, UINT))
        self.assertEqual(analyzer._usual_arithmetic_conversion(UINT, LONG), LONG)
        self.assertTrue(analyzer._qualifiers_contain(const_int, INT))

    def test_sema_record_helpers_live_outside_entrypoint(self) -> None:
        analyzer = Analyzer()
        members = (RecordMemberInfo("value", INT),)
        record_spec = TypeSpec(
            "struct",
            record_members=(RecordMemberDecl(TypeSpec("int"), "value"),),
            has_record_body=True,
        )
        self.assertEqual(sema_records.record_key.__module__, "xcc.sema.records")
        self.assertEqual(sema_records.record_key("struct", "S"), "struct S")
        self.assertEqual(analyzer._record_key("struct", "S"), "struct S")
        self.assertEqual(analyzer._normalize_record_members((("value", INT),)), members)
        analyzer._record_definitions["struct S"] = members
        self.assertEqual(analyzer._record_members("struct S"), members)
        self.assertFalse(analyzer._is_anonymous_record_member(members[0]))
        self.assertEqual(analyzer._record_member_lookup("struct S"), {"value": (INT, 0)})
        self.assertEqual(analyzer._record_type_name(record_spec), "struct <anon:1>")

    def test_sema_initializer_constant_layout_helpers_live_outside_entrypoint(self) -> None:
        analyzer = Analyzer()
        scope = Scope()
        self.assertEqual(sema_constants.parse_int_literal.__module__, "xcc.sema.constants")
        self.assertEqual(sema_constants.decode_escaped_units.__module__, "xcc.sema.constants")
        self.assertEqual(sema_initializers.analyze_initializer.__module__, "xcc.sema.initializers")
        self.assertEqual(
            sema_initializers.lookup_initializer_member.__module__, "xcc.sema.initializers"
        )
        self.assertEqual(sema_layout.sizeof_type.__module__, "xcc.sema.layout")
        self.assertEqual(sema_layout.alignof_type.__module__, "xcc.sema.layout")

        self.assertEqual(analyzer._parse_int_literal("42"), (42, INT))
        self.assertTrue(analyzer._fits_integer_literal_value(255, UINT))
        self.assertEqual(analyzer._eval_int_constant_expr(IntLiteral("4"), scope), 4)
        self.assertEqual(analyzer._char_const_value("'\\n'"), 10)
        self.assertEqual(analyzer._char_literal_body("'x'"), "x")
        self.assertEqual(analyzer._decode_escaped_units("x\\n"), [ord("x"), 10])

        self.assertEqual(analyzer._sizeof_type(INT), 4)
        self.assertEqual(analyzer._alignof_type(LONG), 8)
        self.assertEqual(analyzer._sizeof_object_base_type(INT, None), 4)
        self.assertEqual(analyzer._alignof_object_base_type(INT), 4)

        string_expr = StringLiteral('"ab"')
        self.assertTrue(analyzer._is_char_array_string_initializer(CHAR.array_of(3), string_expr))
        self.assertEqual(analyzer._string_literal_required_length('"ab"'), 3)
        self.assertEqual(analyzer._string_literal_body('"ab"'), "ab")
        analyzer._analyze_initializer(INT, IntLiteral("1"), scope)

    def test_type_str(self) -> None:
        self.assertEqual(str(INT), "int")
        self.assertEqual(str(UINT), "unsigned int")
        self.assertEqual(str(SHORT), "short")
        self.assertEqual(str(USHORT), "unsigned short")
        self.assertEqual(str(LONG), "long")
        self.assertEqual(str(ULONG), "unsigned long")
        self.assertEqual(str(LLONG), "long long")
        self.assertEqual(str(ULLONG), "unsigned long long")
        self.assertEqual(str(INT128), "__int128_t")
        self.assertEqual(str(UINT128), "__uint128_t")
        self.assertEqual(str(CHAR), "char")
        self.assertEqual(str(UCHAR), "unsigned char")
        self.assertEqual(str(BOOL), "_Bool")
        self.assertEqual(str(FLOAT), "float")
        self.assertEqual(str(DOUBLE), "double")
        self.assertEqual(str(LONGDOUBLE), "long double")
        self.assertEqual(str(Type("int", qualifiers=("const",))), "const int")
        array = Type("int").array_of(4)
        self.assertEqual(str(array), "int[4]")

    def test_function_invalid_storage_class_error(self) -> None:
        unit = parse(list(lex("auto int f(void);")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception), "Invalid storage class for file-scope function declaration: 'auto'"
        )

    def test_typedef_function_type_invalid_storage_class_error(self) -> None:
        source = "typedef int unary_int_func(int arg); auto unary_int_func add_one;"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception), "Invalid storage class for file-scope function declaration: 'auto'"
        )

    def test_file_scope_invalid_storage_class_error(self) -> None:
        unit = parse(list(lex("register int g;")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid storage class for file-scope object declaration: 'register'",
        )

    def test_file_scope_auto_storage_class_error(self) -> None:
        unit = parse(list(lex("auto int g;")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid storage class for file-scope object declaration: 'auto'",
        )

    def test_extern_initializer_error(self) -> None:
        unit = parse(list(lex("int f(void){extern int x=1; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid initializer for block-scope object declaration with storage class 'extern'",
        )

    def test_invalid_thread_local_storage_class_error(self) -> None:
        unit = parse(list(lex("int f(void){_Thread_local int x; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid storage class for block-scope thread-local object declaration: 'none'; "
            "'_Thread_local' requires 'static' or 'extern'",
        )

    def test_block_scope_thread_local_rejects_register_storage_class(self) -> None:
        unit = parse(list(lex("int f(void){_Thread_local register int x; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid storage class for block-scope thread-local object declaration: 'register'; "
            "'_Thread_local' requires 'static' or 'extern'",
        )

    def test_file_scope_thread_local_rejects_invalid_storage_class(self) -> None:
        unit = parse(list(lex("_Thread_local auto int x;")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid storage class for file-scope thread-local object declaration: 'auto'; "
            "'_Thread_local' requires 'static' or 'extern'",
        )

    def test_file_scope_object_declaration_rejects_typedef_storage_class(self) -> None:
        unit = TranslationUnit(
            declarations=[DeclStmt(TypeSpec("int"), "x", None, storage_class="typedef")],
            functions=[],
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid storage class for file-scope object declaration: 'typedef'; use a typedef declaration instead",
        )

    def test_block_scope_object_declaration_rejects_typedef_storage_class(self) -> None:
        unit = parse(list(lex("int f(void){int x=0; return x;}")))
        body = _body(unit.functions[0])
        body.statements.insert(
            0,
            DeclStmt(TypeSpec("int"), "y", IntLiteral("1"), storage_class="typedef"),
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid storage class for block-scope object declaration: 'typedef'; use a typedef declaration instead",
        )

    def test_file_scope_vla_error(self) -> None:
        unit = parse(list(lex("int n; int a[n];")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Variable length array not allowed at file scope")

    def test_function_thread_local_error(self) -> None:
        unit = parse(list(lex("_Thread_local int f(void);")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid declaration specifier for function declaration: '_Thread_local'",
        )

    def test_typedef_function_type_thread_local_error(self) -> None:
        source = "typedef int unary_int_func(int arg); _Thread_local unary_int_func add_one;"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid declaration specifier for function declaration: '_Thread_local'",
        )

    def test_function_definition_thread_local_error(self) -> None:
        unit = parse(list(lex("_Thread_local int f(void){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid declaration specifier for function declaration: '_Thread_local'",
        )

    def test_block_scope_function_rejects_static_storage_class(self) -> None:
        unit = parse(list(lex("int main(void){ static int f(void); return 0; }")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid storage class for block-scope function declaration: 'static'",
        )

    def test_block_scope_function_rejects_register_storage_class(self) -> None:
        unit = parse(list(lex("int main(void){ register int f(void); return 0; }")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid storage class for block-scope function declaration: 'register'",
        )

    def test_block_scope_function_rejects_thread_local_specifier(self) -> None:
        unit = parse(list(lex("int main(void){ extern _Thread_local int f(void); return 0; }")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid declaration specifier for function declaration: '_Thread_local'",
        )

    def test_file_scope_storage_without_identifier_error(self) -> None:
        unit = parse(list(lex("static struct S;")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Expected identifier for file-scope object declaration with storage class 'static'",
        )

    def test_file_scope_thread_local_without_identifier_error(self) -> None:
        unit = parse(list(lex("_Thread_local struct S;")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Expected identifier for file-scope object declaration with '_Thread_local'",
        )

    def test_block_scope_storage_without_identifier_error(self) -> None:
        unit = parse(list(lex("int main(void){ extern struct S; return 0; }")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Expected identifier for block-scope object declaration with storage class 'extern'",
        )

    def test_block_scope_thread_local_without_identifier_error(self) -> None:
        unit = parse(list(lex("int main(void){ extern _Thread_local struct S; return 0; }")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Expected identifier for block-scope object declaration with storage class 'extern' and '_Thread_local'",
        )

    def test_file_scope_extern_initializer_error(self) -> None:
        unit = parse(list(lex("extern int x=1;")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid initializer for file-scope object declaration with storage class 'extern'",
        )

    def test_extern_then_definition_file_scope(self) -> None:
        unit = parse(list(lex("extern int x; int x = 42; int f(void){return x;}")))
        sema = analyze(unit)
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        assert stmt.value is not None
        self.assertEqual(sema.type_map.require(stmt.value), INT)

    def test_extern_then_definition_thread_local(self) -> None:
        unit = parse(
            list(lex("extern _Thread_local int x; _Thread_local int x = 2; int f(void){return x;}"))
        )
        sema = analyze(unit)
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        assert stmt.value is not None
        self.assertEqual(sema.type_map.require(stmt.value), INT)

    def test_extern_redecl_type_mismatch_error(self) -> None:
        unit = parse(list(lex("extern int x; char x;")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: x")

    def test_compound_literal_type(self) -> None:
        unit = parse(list(lex("int main(void){int *p=&(int){1}; return *p;}")))
        sema = analyze(unit)
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        assert stmt.value is not None
        self.assertEqual(sema.type_map.require(stmt.value), INT)

    def test_bit_field_width_exceeds_type_error(self) -> None:
        unit = parse(list(lex("struct S { unsigned int x:33; };")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Bit-field width exceeds type width")

    def test_unnamed_bit_field_nonzero_width_ok(self) -> None:
        # C11 allows unnamed bit-fields with non-zero width (padding)
        analyze(parse(list(lex("struct S { unsigned :1; };"))))

    def test_unnamed_bit_field_zero_width_ok(self) -> None:
        analyze(parse(list(lex("struct S { unsigned :0; unsigned x:1; };"))))

    def test_named_bit_field_zero_width_error(self) -> None:
        unit = parse(list(lex("struct S { unsigned x:0; };")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Named bit-field width must be greater than zero")

    def test_bit_field_non_integer_type_error(self) -> None:
        unit = parse(list(lex("struct S { float x:1; };")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Bit-field type must be integer")

    def test_bit_field_non_constant_width_error(self) -> None:
        unit = parse(list(lex("int n; struct S { unsigned x:n; };")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Bit-field width is not integer constant")

    def test_bit_field_negative_width_error(self) -> None:
        unit = parse(list(lex("struct S { unsigned x:-1; };")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Bit-field width must be non-negative")

    def test_compound_literal_invalid_object_type_errors(self) -> None:
        unit = parse(list(lex("int main(void){return (void){0};}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid object type for compound literal: void")
        unit = parse(list(lex("int main(void){return (struct S){0};}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid object type for compound literal: incomplete")

    def test_compound_literal_invalid_atomic_object_type_error(self) -> None:
        unit = parse(list(lex("int main(void){return (_Atomic(void)){0};}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid object type for compound literal: atomic")

    def test_internal_vla_helpers_cover_fallback_paths(self) -> None:
        analyzer = Analyzer()
        self.assertEqual(analyzer._resolve_array_bound("bad"), -1)
        self.assertEqual(analyzer._resolve_array_bound(ArrayDecl(None)), -1)
        self.assertEqual(analyzer._resolve_array_bound(ArrayDecl(1)), 1)
        self.assertEqual(analyzer._resolve_array_bound(ArrayDecl(IntLiteral("1"))), 1)
        self.assertEqual(analyzer._resolve_array_bound(ArrayDecl(Identifier("n"))), -1)
        self.assertTrue(
            analyzer._is_variably_modified_type_spec(TypeSpec("int", declarator_ops=(("arr", -1),)))
        )
        self.assertFalse(
            analyzer._is_variably_modified_type_spec(TypeSpec("int", declarator_ops=(("arr", 1),)))
        )
        self.assertTrue(
            analyzer._is_variably_modified_type_spec(
                TypeSpec("int", declarator_ops=(("arr", ArrayDecl(None)),))
            )
        )
        self.assertTrue(
            analyzer._is_variably_modified_type_spec(
                TypeSpec("int", declarator_ops=(("arr", object()),))
            )
        )
        self.assertFalse(
            analyzer._is_variably_modified_type_spec(
                TypeSpec("int", declarator_ops=(("arr", ArrayDecl(IntLiteral("1"))),))
            )
        )
        self.assertFalse(
            analyzer._is_variably_modified_type_spec(
                TypeSpec("int", declarator_ops=(("arr", ArrayDecl(1)),))
            )
        )
        self.assertFalse(
            analyzer._is_file_scope_vla_type_spec(
                TypeSpec("int", declarator_ops=(("arr", ArrayDecl(None)),))
            )
        )
        self.assertTrue(
            analyzer._is_file_scope_vla_type_spec(
                TypeSpec("int", declarator_ops=(("arr", object()),))
            )
        )
        self.assertFalse(
            analyzer._is_file_scope_vla_type_spec(TypeSpec("int", declarator_ops=(("arr", 1),)))
        )
        self.assertFalse(
            analyzer._is_file_scope_vla_type_spec(
                TypeSpec("int", declarator_ops=(("arr", ArrayDecl(1)),))
            )
        )
        self.assertFalse(
            analyzer._is_file_scope_vla_type_spec(
                TypeSpec("int", declarator_ops=(("arr", ArrayDecl(IntLiteral("1"))),))
            )
        )
        self.assertIsNone(analyzer._sizeof_type(Type("int", declarator_ops=(("arr", -1),))))
        self.assertEqual(analyzer._sizeof_type(Type("int", declarator_ops=(("arr", 1),))), 4)

    def test_internal_stmt_storage_edge_paths(self) -> None:
        analyzer = Analyzer()
        with self.assertRaises(SemaError):
            analyzer._analyze_stmt(
                DeclStmt(TypeSpec("int"), "x", None, storage_class="typedef"),
                Scope(),
                INT,
            )
        with self.assertRaises(SemaError):
            analyzer._analyze_stmt(
                DeclStmt(TypeSpec("struct", record_tag="S"), None, None, storage_class="static"),
                Scope(),
                INT,
            )

    def test_record_member_len4_normalization(self) -> None:
        type_spec = TypeSpec(
            "struct",
            record_members=((TypeSpec("int"), "x", 8, IntLiteral("1")),),
        )
        member = type_spec.record_members[0]
        self.assertEqual(member.alignment, 8)
        self.assertEqual(member.bit_width_expr, IntLiteral("1"))

    def test_record_member_lookup_anonymous_edge_paths(self) -> None:
        analyzer = Analyzer()
        self.assertEqual(analyzer._flatten_hoisted_record_members(Type("struct Missing"), 0), [])
        analyzer._record_definitions["struct Inner"] = (
            RecordMemberInfo("x", INT),
            RecordMemberInfo(None, INT, bit_width=0),
        )
        self.assertEqual(analyzer._record_member_lookup("struct Inner"), {"x": (INT, 0)})
        analyzer._record_definitions["struct Outer"] = (
            RecordMemberInfo("x", INT),
            RecordMemberInfo(None, Type("struct Inner")),
        )
        with self.assertRaises(SemaError) as ctx:
            analyzer._record_member_lookup("struct Outer")
        self.assertEqual(str(ctx.exception), "Duplicate declaration: x")

    def test_register_type_spec_handles_missing_nested_lookup_entry(self) -> None:
        analyzer = Analyzer()
        original_lookup = analyzer._record_member_lookup
        analyzer._record_member_lookup = lambda _record_name: None  # type: ignore[method-assign]
        try:
            analyzer._register_type_spec(
                TypeSpec(
                    "struct",
                    record_members=(
                        (
                            TypeSpec(
                                "struct",
                                record_members=((TypeSpec("int"), "x"),),
                            ),
                            None,
                        ),
                    ),
                )
            )
        finally:
            analyzer._record_member_lookup = original_lookup  # type: ignore[method-assign]

    def test_type_helper_methods(self) -> None:
        analyzer = Analyzer()
        array = Type("int").array_of(4)
        pointer = array.pointer_to()
        self.assertEqual(str(Type("int", 1)), "int*")
        self.assertEqual(pointer, Type("int", declarator_ops=(("ptr", 0), ("arr", 4))))
        self.assertEqual(pointer.pointee(), array)
        self.assertEqual(array.element_type(), Type("int"))
        func = Type("int").function_of((INT, INT))
        self.assertEqual(str(func), "int(int,int)")
        self.assertEqual(func.callable_signature(), (Type("int"), ((INT, INT), False)))
        self.assertEqual(str(Type("int").function_of(None)), "int()")
        self.assertEqual(str(Type("int").function_of(())), "int(void)")
        self.assertEqual(str(Type("int").function_of((INT,), is_variadic=True)), "int(int,...)")
        self.assertEqual(
            func.decay_parameter_type(),
            Type("int", declarator_ops=(("ptr", 0), ("fn", ((INT, INT), False)))),
        )
        self.assertIsNone(Type("int").pointee())
        self.assertIsNone(Type("int").element_type())
        self.assertIs(analyzer._integer_promotion(FLOAT), FLOAT)
        self.assertFalse(analyzer._is_pointer_conversion_compatible(INT, Type("int", 1)))

    def test_scope_lookup_typedef_from_parent(self) -> None:
        parent = Scope()
        parent.define_typedef("T", INT)
        child = Scope(parent)
        self.assertEqual(child.lookup_typedef("T"), INT)

    def test_analyze_success_and_typemap(self) -> None:
        source = "int main(){int x=1; x=2+3; return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["x"].type_, INT)
        assign_stmt = _body(unit.functions[0]).statements[1]
        assign_expr = assign_stmt.expr
        binary_expr = assign_expr.value
        self.assertIs(sema.type_map.get(assign_expr), INT)
        self.assertIs(sema.type_map.get(binary_expr), INT)

    def test_unary_expression(self) -> None:
        source = "int main(){int x=1; return -x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        self.assertIs(sema.type_map.get(return_expr), INT)

    def test_logical_not_expression_typemap(self) -> None:
        unit = parse(list(lex("int main(){int x=1; return !x;}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        self.assertIs(sema.type_map.get(return_expr), INT)

    def test_bitwise_not_expression_typemap(self) -> None:
        unit = parse(list(lex("int main(){int x=1; return ~x;}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        self.assertIs(sema.type_map.get(return_expr), INT)

    def test_update_expression_typemap(self) -> None:
        source = "int main(){int x=1; ++x; x--; return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        prefix_expr = _body(unit.functions[0]).statements[1].expr
        postfix_expr = _body(unit.functions[0]).statements[2].expr
        self.assertIsInstance(prefix_expr, UpdateExpr)
        self.assertIsInstance(postfix_expr, UpdateExpr)
        self.assertIs(sema.type_map.get(prefix_expr), INT)
        self.assertIs(sema.type_map.get(postfix_expr), INT)

    def test_update_expression_pointer_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; p++; return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        update_expr = _body(unit.functions[0]).statements[2].expr
        self.assertIsInstance(update_expr, UpdateExpr)
        self.assertEqual(sema.type_map.get(update_expr), Type("int", 1))

    def test_char_declaration_and_update_typemap(self) -> None:
        source = "int main(){char c=1; c++; return c;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["c"].type_, CHAR)
        update_expr = _body(unit.functions[0]).statements[1].expr
        self.assertIsInstance(update_expr, UpdateExpr)
        self.assertIs(sema.type_map.get(update_expr), CHAR)

    def test_bool_declaration_typemap(self) -> None:
        unit = parse(list(lex("int main(void){_Bool flag=1; return flag;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["flag"].type_, BOOL)

    def test_noreturn_function_definition_typemap(self) -> None:
        unit = parse(list(lex("_Noreturn int f(void){return 1;}")))
        sema = analyze(unit)
        self.assertIs(sema.functions["f"].return_type, INT)

    def test_thread_local_file_scope_declaration_typemap(self) -> None:
        unit = parse(list(lex("_Thread_local int g; int main(void){return g;}")))
        sema = analyze(unit)
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        self.assertIsNotNone(stmt.value)
        assert stmt.value is not None
        self.assertIs(sema.type_map.get(stmt.value), INT)

    def test_gnu_thread_local_file_scope_declaration_typemap(self) -> None:
        unit = parse(list(lex("__thread int g; int main(void){return g;}")))
        sema = analyze(unit)
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        self.assertIsNotNone(stmt.value)
        assert stmt.value is not None
        self.assertIs(sema.type_map.get(stmt.value), INT)

    def test_alignas_constant_expression_declaration_typemap(self) -> None:
        unit = parse(list(lex("int main(void){_Alignas(16) int x=1; return x;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["x"].type_, INT)
        self.assertEqual(func_symbol.locals["x"].alignment, 16)

    def test_alignas_type_name_declaration_typemap(self) -> None:
        unit = parse(list(lex("int main(void){_Alignas(int) int x=1; return x;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["x"].type_, INT)
        self.assertEqual(func_symbol.locals["x"].alignment, 4)

    def test_alignas_rejects_weaker_alignment_than_type(self) -> None:
        unit = parse(list(lex("int main(void){_Alignas(1) int x=1; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid alignment specifier for block-scope object declaration: alignment 1 is weaker than natural alignment 4",
        )

    def test_alignas_tag_only_declaration_error(self) -> None:
        unit = TranslationUnit([], [DeclStmt(TypeSpec("struct", record_tag="S"), None, None, 16)])
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid alignment specifier for file-scope object declaration without identifier",
        )

    def test_alignas_file_scope_weaker_alignment_error(self) -> None:
        unit = parse(list(lex("_Alignas(1) int g; int main(void){return g;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid alignment specifier for file-scope object declaration: alignment 1 is weaker than natural alignment 4",
        )

    def test_alignas_block_scope_tag_only_declaration_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([DeclStmt(TypeSpec("struct", record_tag="S"), None, None, 16)]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid alignment specifier for block-scope object declaration without identifier",
        )

    def test_alignas_file_scope_missing_identifier_reports_qualifiers(self) -> None:
        unit = TranslationUnit(
            [],
            [
                DeclStmt(
                    TypeSpec("int"),
                    None,
                    None,
                    16,
                    storage_class="extern",
                    is_thread_local=True,
                )
            ],
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid alignment specifier for file-scope object declaration without identifier "
            "with storage class 'extern' and '_Thread_local'",
        )

    def test_alignas_block_scope_missing_identifier_reports_qualifiers(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(
                                TypeSpec("int"),
                                None,
                                None,
                                16,
                                storage_class="extern",
                                is_thread_local=True,
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid alignment specifier for block-scope object declaration without identifier "
            "with storage class 'extern' and '_Thread_local'",
        )

    def test_alignas_member_increases_record_alignof(self) -> None:
        unit = parse(
            list(
                lex(
                    "struct S {_Alignas(16) char c;};int main(void){return _Alignof(struct S)==16;}"
                )
            )
        )
        sema = analyze(unit)
        return_stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(return_stmt, ReturnStmt)
        self.assertIsNotNone(return_stmt.value)
        assert return_stmt.value is not None
        self.assertIs(sema.type_map.get(return_stmt.value), INT)

    def test_alignas_rejects_member_weaker_than_natural_alignment(self) -> None:
        unit = TranslationUnit(
            [],
            [
                DeclStmt(
                    TypeSpec(
                        "struct",
                        record_tag="S",
                        record_members=(RecordMemberDecl(TypeSpec("int"), "x", 1),),
                    ),
                    None,
                    None,
                )
            ],
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid alignment specifier for record member declaration: alignment 1 is weaker than natural alignment 4",
        )

    def test_alignas_rejects_block_scope_non_power_of_two_alignment(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [DeclStmt(TypeSpec("int"), "x", None, 3), ReturnStmt(IntLiteral(0))]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid alignment specifier for block-scope object declaration: alignment 3 is not a power of two",
        )

    def test_atomic_declaration_typemap(self) -> None:
        unit = parse(list(lex("int main(void){_Atomic int value=1; return value;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["value"].type_, INT)

    def test_atomic_type_specifier_typemap(self) -> None:
        unit = parse(list(lex("int main(void){_Atomic(int) value=1; return value;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["value"].type_, INT)

    def test_atomic_function_return_type_is_allowed(self) -> None:
        unit = parse(list(lex("_Atomic int f(void){return 1;}")))
        sema = analyze(unit)
        self.assertIn("f", sema.functions)

    def test_atomic_array_of_scalar_elements_is_allowed(self) -> None:
        unit = parse(list(lex("int main(void){_Atomic int values[2]={1,2}; return values[0];}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_atomic_incomplete_record_pointer_error(self) -> None:
        unit = parse(list(lex("int main(void){struct S; _Atomic struct S *p; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for block-scope object declaration: atomic",
        )

    def test_atomic_function_object_file_scope_error(self) -> None:
        atomic_function_type = TypeSpec(
            "int",
            declarator_ops=(("fn", ((), False)),),
            is_atomic=True,
        )
        unit = TranslationUnit([], [DeclStmt(atomic_function_type, "g", None)])
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for file-scope object declaration: atomic",
        )

    def test_atomic_function_object_block_scope_error(self) -> None:
        atomic_function_type = TypeSpec(
            "int",
            declarator_ops=(("fn", ((), False)),),
            is_atomic=True,
        )
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [DeclStmt(atomic_function_type, "g", None), ReturnStmt(IntLiteral("0"))]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for block-scope object declaration: atomic",
        )

    def test_atomic_void_return_type_error(self) -> None:
        unit = parse(list(lex("_Atomic(void) f(void){return;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid return type: atomic")

    def test_atomic_void_return_type_without_prototype_error(self) -> None:
        unit = parse(list(lex("_Atomic(void) f(){return;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid return type: atomic")

    def test_atomic_function_parameter_type_error(self) -> None:
        atomic_function_type = TypeSpec(
            "int",
            declarator_ops=(("fn", ((), False)),),
            is_atomic=True,
        )
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "f",
                    [Param(atomic_function_type, "p")],
                    CompoundStmt([ReturnStmt(IntLiteral("0"))]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid parameter type: atomic")

    def test_atomic_invalid_typedef_type_error(self) -> None:
        atomic_function_type = TypeSpec(
            "int",
            declarator_ops=(("fn", ((), False)),),
            is_atomic=True,
        )
        unit = TranslationUnit([], [TypedefDecl(atomic_function_type, "Fn")])
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid atomic type for file-scope typedef declaration",
        )

    def test_atomic_invalid_block_typedef_type_error(self) -> None:
        atomic_function_type = TypeSpec(
            "int",
            declarator_ops=(("fn", ((), False)),),
            is_atomic=True,
        )
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [TypedefDecl(atomic_function_type, "Fn"), ReturnStmt(IntLiteral("0"))]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid atomic type for block-scope typedef declaration",
        )

    def test_atomic_invalid_member_type_error(self) -> None:
        atomic_function_type = TypeSpec(
            "int",
            declarator_ops=(("fn", ((), False)),),
            is_atomic=True,
        )
        struct_with_atomic_member = TypeSpec(
            "struct",
            record_tag="S",
            record_members=((atomic_function_type, "x"),),
        )
        unit = TranslationUnit([], [DeclStmt(struct_with_atomic_member, None, None)])
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for record member declaration: atomic",
        )

    def test_atomic_invalid_parameter_in_function_pointer_typedef_error(self) -> None:
        atomic_function_type = TypeSpec(
            "int",
            declarator_ops=(("fn", ((), False)),),
            is_atomic=True,
        )
        pointer_to_function = TypeSpec(
            "int",
            declarator_ops=(("ptr", 0), ("fn", ((atomic_function_type,), False))),
        )
        unit = TranslationUnit([], [TypedefDecl(pointer_to_function, "Fn")])
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid parameter type: atomic")

    def test_long_declaration_and_update_typemap(self) -> None:
        source = "int main(){long value=1; value++; return value;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["value"].type_, LONG)
        update_expr = _body(unit.functions[0]).statements[1].expr
        self.assertIsInstance(update_expr, UpdateExpr)
        self.assertIs(sema.type_map.get(update_expr), LONG)

    def test_short_declaration_and_update_typemap(self) -> None:
        source = "int main(){short value=1; value++; return value;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["value"].type_, SHORT)
        update_expr = _body(unit.functions[0]).statements[1].expr
        self.assertIsInstance(update_expr, UpdateExpr)
        self.assertIs(sema.type_map.get(update_expr), SHORT)

    def test_unsigned_int_declaration_and_update_typemap(self) -> None:
        source = "int main(){unsigned value=1; value++; return value;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["value"].type_, UINT)
        update_expr = _body(unit.functions[0]).statements[1].expr
        self.assertIsInstance(update_expr, UpdateExpr)
        self.assertIs(sema.type_map.get(update_expr), UINT)

    def test_unsigned_short_declaration_typemap(self) -> None:
        source = "int main(){unsigned short value=1; value++; return value;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["value"].type_, USHORT)
        update_expr = _body(unit.functions[0]).statements[1].expr
        self.assertIsInstance(update_expr, UpdateExpr)
        self.assertIs(sema.type_map.get(update_expr), USHORT)

    def test_array_size_additive_constant_expression_typemap(self) -> None:
        source = "int main(){int a[536870912U - 1U]; return a[0];}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertEqual(func_symbol.locals["a"].type_, Type("int", 0, (536870911,)))

    def test_array_size_shift_constant_expression_typemap(self) -> None:
        source = "int main(){int a[1LL<<4]; return a[0];}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertEqual(func_symbol.locals["a"].type_, Type("int", 0, (16,)))

    def test_array_size_sizeof_typedef_cast_expression_typemap(self) -> None:
        source = "int main(){typedef char a[1LL<<10]; char b[(long long)sizeof(a)-1]; return b[0];}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertEqual(func_symbol.locals["b"].type_, Type("char", 0, (1023,)))

    def test_array_size_too_large_error(self) -> None:
        unit = parse(list(lex("int main(){int a[2147483647U][2147483647U];return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "array is too large")

    def test_typedef_array_size_too_large_error(self) -> None:
        unit = parse(list(lex("int main(){typedef char a[1LL<<61]; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "array is too large")

    def test_array_size_too_large_due_to_int_element_width_error(self) -> None:
        unit = parse(list(lex("int main(){int a[2147483647U]; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "array is too large")

    def test_array_size_too_large_due_to_pointer_element_width_error(self) -> None:
        unit = parse(list(lex("int main(){int *a[268435456]; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "array is too large")

    def test_long_long_declaration_and_update_typemap(self) -> None:
        source = "int main(){long long value=1; value++; return value;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["value"].type_, LLONG)
        update_expr = _body(unit.functions[0]).statements[1].expr
        self.assertIsInstance(update_expr, UpdateExpr)
        self.assertIs(sema.type_map.get(update_expr), LLONG)

    def test_unsigned_char_declaration_typemap(self) -> None:
        source = "int main(){unsigned char c=1; c++; return c;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["c"].type_, UCHAR)
        update_expr = _body(unit.functions[0]).statements[1].expr
        self.assertIsInstance(update_expr, UpdateExpr)
        self.assertIs(sema.type_map.get(update_expr), UCHAR)

    def test_integer_type_conversions_in_initializer_and_assignment(self) -> None:
        source = "int main(){char c=1; int x=c; char d=x; x=d; return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["c"].type_, CHAR)
        self.assertIs(func_symbol.locals["x"].type_, INT)
        self.assertIs(func_symbol.locals["d"].type_, CHAR)

    def test_long_and_int_type_conversions(self) -> None:
        source = "int main(){long a=1; int b=a; a=b; return b;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["a"].type_, LONG)
        self.assertIs(func_symbol.locals["b"].type_, INT)

    def test_short_and_int_type_conversions(self) -> None:
        source = "int main(){short a=1; int b=a; a=b; return b;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["a"].type_, SHORT)
        self.assertIs(func_symbol.locals["b"].type_, INT)

    def test_unsigned_and_int_type_conversions(self) -> None:
        source = "int main(){unsigned long a=1; int b=a; a=b; return b;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["a"].type_, ULONG)
        self.assertIs(func_symbol.locals["b"].type_, INT)

    def test_long_long_and_int_type_conversions(self) -> None:
        source = "int main(){long long a=1; int b=a; a=b; return b;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["a"].type_, LLONG)
        self.assertIs(func_symbol.locals["b"].type_, INT)

    def test_char_parameter_accepts_int_argument(self) -> None:
        source = "char id(char x){return x;} int main(){return id(1);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_long_function_signature(self) -> None:
        source = "long id(long x){return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func = sema.functions["id"]
        self.assertIs(func.return_type, LONG)
        self.assertIs(func.locals["x"].type_, LONG)

    def test_short_function_signature(self) -> None:
        source = "short id(short x){return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func = sema.functions["id"]
        self.assertIs(func.return_type, SHORT)
        self.assertIs(func.locals["x"].type_, SHORT)

    def test_unsigned_function_signature(self) -> None:
        source = "unsigned id(unsigned x){return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func = sema.functions["id"]
        self.assertIs(func.return_type, UINT)
        self.assertIs(func.locals["x"].type_, UINT)

    def test_unsigned_short_function_signature(self) -> None:
        source = "unsigned short id(unsigned short x){return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func = sema.functions["id"]
        self.assertIs(func.return_type, USHORT)
        self.assertIs(func.locals["x"].type_, USHORT)

    def test_long_long_function_signature(self) -> None:
        source = "long long id(long long x){return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func = sema.functions["id"]
        self.assertIs(func.return_type, LLONG)
        self.assertIs(func.locals["x"].type_, LLONG)

    def test_unsigned_long_long_function_signature(self) -> None:
        source = "unsigned long long id(unsigned long long x){return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func = sema.functions["id"]
        self.assertIs(func.return_type, ULLONG)
        self.assertIs(func.locals["x"].type_, ULLONG)

    def test_int128_t_function_signature(self) -> None:
        source = "__int128_t id(__int128_t x){return x;}"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit)
        func = sema.functions["id"]
        self.assertIs(func.return_type, INT128)
        self.assertIs(func.locals["x"].type_, INT128)

    def test_uint128_t_function_signature(self) -> None:
        source = "__uint128_t id(__uint128_t x){return x;}"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit)
        func = sema.functions["id"]
        self.assertIs(func.return_type, UINT128)
        self.assertIs(func.locals["x"].type_, UINT128)

    def test_uint128_t_type_helpers(self) -> None:
        analyzer = Analyzer()
        self.assertEqual(analyzer._sizeof_type(UINT128), 16)
        self.assertEqual(analyzer._alignof_type(UINT128), 16)

    def test_char_literal_typemap(self) -> None:
        unit = parse(list(lex("int main(){return 'a';}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[0].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), INT)

    def test_int_literal_suffix_typemap(self) -> None:
        cases = [
            ("1", INT),
            ("1u", UINT),
            ("1L", LONG),
            ("1Ul", ULONG),
            ("1ll", LLONG),
            ("1LLU", ULLONG),
        ]
        for literal, expected in cases:
            with self.subTest(literal=literal):
                unit = parse(list(lex(f"int main(){{return {literal};}}")))
                sema = analyze(unit)
                expr = _body(unit.functions[0]).statements[0].value
                assert expr is not None
                self.assertIs(sema.type_map.get(expr), expected)

    def test_int_literal_value_driven_typemap(self) -> None:
        cases = [
            ("4294967296", LONG),
            ("0x100000000", LONG),
            ("040000000000", LONG),
        ]
        for literal, expected in cases:
            with self.subTest(literal=literal):
                unit = parse(list(lex(f"int main(){{return {literal};}}")))
                sema = analyze(unit)
                expr = _body(unit.functions[0]).statements[0].value
                assert expr is not None
                self.assertIs(sema.type_map.get(expr), expected)

    def test_float_literal_suffix_typemap(self) -> None:
        cases = [
            ("1.0", DOUBLE),
            ("1.0f", FLOAT),
            ("1.0L", LONGDOUBLE),
        ]
        for literal, expected in cases:
            with self.subTest(literal=literal):
                unit = parse(list(lex(f"double main(){{return {literal};}}")))
                sema = analyze(unit)
                expr = _body(unit.functions[0]).statements[0].value
                assert expr is not None
                self.assertIs(sema.type_map.get(expr), expected)

    def test_enum_member_non_decimal_constant_expression_values(self) -> None:
        unit = parse(list(lex("int main(){enum E { A=0x10, B=010, C=A+B }; return C;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertEqual(getattr(func_symbol.locals["A"], "value"), 16)
        self.assertEqual(getattr(func_symbol.locals["B"], "value"), 8)
        self.assertEqual(getattr(func_symbol.locals["C"], "value"), 24)

    def test_string_literal_typemap(self) -> None:
        unit = parse(list(lex('int main(){"abc";return 0;}')))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[0].expr
        self.assertEqual(sema.type_map.get(expr), Type("char", 1))

    def test_string_literal_assign_to_char_pointer(self) -> None:
        unit = parse(list(lex('int main(){char *s="abc";return 0;}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_char_array_string_initializer_ok(self) -> None:
        unit = parse(list(lex('int main(){char s[4]="abc";return 0;}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_char_array_u8_string_initializer_ok(self) -> None:
        unit = parse(list(lex('int main(){char s[4]=u8"abc";return 0;}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_char_array_concatenated_string_initializer_ok(self) -> None:
        unit = parse(list(lex('int main(){char s[3]="a""b";return 0;}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_char_array_concatenated_u8_string_initializer_ok(self) -> None:
        unit = parse(list(lex('int main(){char s[3]=u8"a""b";return 0;}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_char_array_string_initializer_too_long_error(self) -> None:
        unit = parse(list(lex('int main(){char s[3]="abc";return 0;}')))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_char_array_concatenated_string_initializer_too_long_error(self) -> None:
        unit = parse(list(lex('int main(){char s[2]="a""b";return 0;}')))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_char_array_escape_string_initializer_ok(self) -> None:
        unit = parse(list(lex(r'int main(){char s[2]="\n";return 0;}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_char_array_hex_escape_string_initializer_ok(self) -> None:
        unit = parse(list(lex(r'int main(){char s[2]="\x41";return 0;}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_char_array_wide_string_initializer_error(self) -> None:
        unit = parse(list(lex('int main(){char s[2]=L"a";return 0;}')))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_non_char_array_string_initializer_error(self) -> None:
        unit = parse(list(lex('int main(){int s[4]="abc";return 0;}')))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_case_char_literal_constant_ok(self) -> None:
        unit = parse(list(lex("int main(){switch(1){case 'a': break; default: return 0;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_case_escaped_char_literal_constant_ok(self) -> None:
        unit = parse(list(lex(r"int main(){switch(1){case '\n': break; default: return 0;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_case_hex_char_literal_constant_ok(self) -> None:
        unit = parse(list(lex(r"int main(){switch(1){case '\x41': break; default: return 0;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_case_octal_char_literal_constant_ok(self) -> None:
        unit = parse(list(lex(r"int main(){switch(1){case '\101': break; default: return 0;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_case_single_digit_octal_char_literal_constant_ok(self) -> None:
        unit = parse(list(lex(r"int main(){switch(1){case '\1': break; default: return 0;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_case_two_digit_octal_char_literal_constant_ok(self) -> None:
        unit = parse(list(lex(r"int main(){switch(1){case '\12': break; default: return 0;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_case_utf16_char_literal_constant_ok(self) -> None:
        unit = parse(list(lex(r"int main(){switch(1){case u'\u00A9': break; default: return 0;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_case_utf32_char_literal_constant_ok(self) -> None:
        unit = parse(
            list(lex(r"int main(){switch(1){case U'\U000000A9': break; default: return 0;}}"))
        )
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_case_wide_char_literal_constant_ok(self) -> None:
        unit = parse(list(lex("int main(){switch(1){case L'a': break; default: return 0;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_case_multichar_literal_constant_error(self) -> None:
        unit = parse(list(lex("int main(){switch(1){case 'ab': break; default: return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_case_invalid_char_literal_constant_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            SwitchStmt(
                                IntLiteral("1"),
                                CompoundStmt(
                                    [
                                        CaseStmt(CharLiteral("bad"), BreakStmt()),
                                        DefaultStmt(ReturnStmt(IntLiteral("0"))),
                                    ]
                                ),
                            ),
                            ReturnStmt(IntLiteral("0")),
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_conditional_expression_typemap(self) -> None:
        source = "int main(){int x=1; return x ? x : 2;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertIs(sema.type_map.get(expr), INT)

    def test_conditional_integer_promotion(self) -> None:
        source = "int main(){char c=1; return c ? c : 2;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertIs(sema.type_map.get(expr), INT)

    def test_conditional_usual_arithmetic_conversion_typemap(self) -> None:
        source = "int main(){unsigned long a=1; int b=2; return 1 ? a : b;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].value
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertIs(sema.type_map.get(expr), ULONG)

    def test_conditional_floating_usual_arithmetic_conversion_typemap(self) -> None:
        source = "int main(){float a=1.0f; double b=2.0; return 1 ? a : b;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].value
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertIs(sema.type_map.get(expr), DOUBLE)

    def test_conditional_pointer_same_type_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; int *q=1 ? p : p; return q!=0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].init
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertEqual(sema.type_map.get(expr), Type("int", 1))

    def test_conditional_pointer_and_null_constant_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; int *q=1 ? p : 0; return q!=0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].init
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertEqual(sema.type_map.get(expr), Type("int", 1))

    def test_conditional_null_constant_and_pointer_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; int *q=1 ? 0 : p; return q!=0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].init
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertEqual(sema.type_map.get(expr), Type("int", 1))

    def test_conditional_void_pointer_and_object_pointer_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; void *vp=0; void *r=1 ? vp : p; return r!=0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[3].init
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertEqual(sema.type_map.get(expr), Type("void", 1))

    def test_conditional_object_pointer_and_void_pointer_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; void *vp=0; void *r=1 ? p : vp; return r!=0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[3].init
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertEqual(sema.type_map.get(expr), Type("void", 1))

    def test_conditional_pointer_compatible_pointee_qualifier_union_typemap(self) -> None:
        source = (
            "int main(){int x=1; const int *cp=&x; volatile int *vp=&x; "
            "const volatile int *rp=1 ? cp : vp; return rp!=0;}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[3].init
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertEqual(sema.type_map.get(expr), Type("int", 1, qualifiers=("const", "volatile")))

    def test_conditional_void_pointer_qualifier_union_typemap(self) -> None:
        source = "int main(){int x=1; const int *cp=&x; void *vp=0; const void *rp=1 ? vp : cp; return rp!=0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[3].init
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertEqual(sema.type_map.get(expr), Type("void", 1, qualifiers=("const",)))

    def test_conditional_pointer_and_casted_void_null_pointer_constant_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; int *q=1 ? p : (void *)0; return q!=0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].init
        assert expr is not None
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertEqual(sema.type_map.get(expr), Type("int", 1))

    def test_generic_selection_typemap(self) -> None:
        unit = parse(list(lex("int main(void){int x=0; return _Generic(x, int: 1, default: 2);}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIsInstance(expr, GenericExpr)
        self.assertIs(sema.type_map.get(expr), INT)

    def test_generic_selection_default_typemap(self) -> None:
        unit = parse(
            list(lex("int main(void){char c=0; return _Generic(c, long: 1, default: 2);}"))
        )
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), INT)

    def test_generic_selection_control_array_decays_to_pointer_typemap(self) -> None:
        unit = parse(
            list(lex("int main(void){int a[2]={0,1}; return _Generic(a, int*: 1L, default: 2);}"))
        )
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), LONG)

    def test_generic_selection_control_function_decays_to_pointer_typemap(self) -> None:
        unit = parse(
            list(
                lex(
                    "int f(void){return 0;} int main(void){return _Generic(f, int(*)(void): 1L, default: 2);}"
                )
            )
        )
        sema = analyze(unit)
        expr = _body(unit.functions[1]).statements[0].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), LONG)

    def test_generic_selection_checks_unselected_association_expression(self) -> None:
        unit = parse(
            list(lex("int main(void){int x=0; return _Generic(x, int: 1, default: missing);}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Undeclared identifier: missing")

    def test_generic_selection_without_match_error(self) -> None:
        unit = parse(list(lex("int main(void){char c=0; return _Generic(c, int: 1);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "No matching generic association for control type 'char'; available association types: 'int' at position 1 (line 1, column 45)",
        )

    def test_generic_selection_without_match_reports_all_association_types(self) -> None:
        unit = parse(list(lex("int main(void){char c=0; return _Generic(c, int: 1, long: 2);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "No matching generic association for control type 'char'; available association types: 'int' at position 1 (line 1, column 45), 'long' at position 2 (line 1, column 53)",
        )

    def test_generic_selection_without_match_reports_position_without_locations(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    FloatLiteral("1.0"),
                                    ((TypeSpec("int"), IntLiteral("1")),),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "No matching generic association for control type 'double'; available association types: 'int' at position 1",
        )

    def test_generic_selection_without_match_uses_association_location_fallback(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    FloatLiteral("1.0"),
                                    ((TypeSpec("int"), IntLiteral("1")),),
                                    ((7, 22),),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "No matching generic association for control type 'double'; available association types: 'int' at position 1 (line 7, column 22)",
        )

    def test_generic_selection_duplicate_compatible_type_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    IntLiteral("0"),
                                    (
                                        (TypeSpec("int"), IntLiteral("1")),
                                        (TypeSpec("int"), IntLiteral("2")),
                                    ),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Duplicate generic association type at position 2 ('int'): previous compatible type was at position 1 ('int')",
        )

    def test_generic_selection_typedef_alias_duplicate_compatible_type_error(self) -> None:
        unit = parse(
            list(lex("typedef int I; int main(void){int x=0; return _Generic(x, int: 1, I: 2);}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Duplicate generic association type at position 2 at line 1, column 67 ('int'): previous compatible type was at position 1 at line 1, column 59 ('int')",
        )

    def test_generic_selection_qualified_typedef_alias_duplicate_compatible_type_error(
        self,
    ) -> None:
        unit = parse(
            list(
                lex(
                    "typedef int I; int main(void){int x=0; return _Generic(x, const int: 1, const I: 2);}"
                )
            )
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Duplicate generic association type at position 2 at line 1, column 73 ('const int'): previous compatible type was at position 1 at line 1, column 59 ('const int')",
        )

    def test_generic_selection_duplicate_default_association_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    IntLiteral("0"),
                                    ((None, IntLiteral("1")), (None, IntLiteral("2"))),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Duplicate default generic association at position 2: previous default was at position 1; only one default association is allowed",
        )

    def test_generic_selection_duplicate_default_association_error_with_location(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    IntLiteral("0"),
                                    ((None, IntLiteral("1")), (None, IntLiteral("2"))),
                                    ((4, 12), (4, 24)),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Duplicate default generic association at position 2 at line 4, column 24: previous default was at position 1 at line 4, column 12; only one default association is allowed",
        )

    def test_generic_selection_duplicate_default_association_error_with_partial_location(
        self,
    ) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    IntLiteral("0"),
                                    ((None, IntLiteral("1")), (None, IntLiteral("2"))),
                                    ((4, None), (None, 24)),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Duplicate default generic association at position 2 at column 24: previous default was at position 1 at line 4; only one default association is allowed",
        )

    def test_generic_selection_void_association_type_error(self) -> None:
        unit = parse(list(lex("int main(void){return _Generic(0, void: 1, default: 2);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid generic association type at position 1 ('void') at line 1, column 35: void type",
        )

    def test_generic_selection_atomic_association_type_error(self) -> None:
        unit = parse(list(lex("int main(void){return _Generic(0, _Atomic(void): 1, default: 2);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid generic association type at position 1 ('void') at line 1, column 35: atomic type",
        )

    def test_generic_selection_incomplete_record_association_type_error(self) -> None:
        unit = parse(
            list(lex("struct S; int main(void){return _Generic(0, struct S: 1, default: 2);}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid generic association type at position 1 ('struct') at line 1, column 45: incomplete type",
        )

    def test_generic_selection_vla_association_type_error(self) -> None:
        unit = parse(list(lex("int f(int n){return _Generic(0, int[n]: 1, default: 2);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid generic association type at position 1 ('int[-1]') at line 1, column 33: variably modified type",
        )

    def test_generic_selection_invalid_association_type_error_without_location(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    IntLiteral("0"),
                                    ((TypeSpec("void"), IntLiteral("1")), (None, IntLiteral("2"))),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid generic association type at position 1 ('void'): void type",
        )

    def test_generic_selection_duplicate_type_uses_association_location_fallback(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    IntLiteral("0"),
                                    (
                                        (TypeSpec("int"), IntLiteral("1")),
                                        (TypeSpec("int"), IntLiteral("2")),
                                    ),
                                    ((3, 11), (3, 19)),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Duplicate generic association type at position 2 at line 3, column 19 ('int'): previous compatible type was at position 1 at line 3, column 11 ('int')",
        )

    def test_generic_selection_duplicate_type_uses_partial_association_location_fallback(
        self,
    ) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    IntLiteral("0"),
                                    (
                                        (TypeSpec("int"), IntLiteral("1")),
                                        (TypeSpec("int"), IntLiteral("2")),
                                    ),
                                    ((3, None), (None, 19)),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Duplicate generic association type at position 2 at column 19 ('int'): previous compatible type was at position 1 at line 3 ('int')",
        )

    def test_generic_selection_invalid_type_uses_association_location_fallback(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    IntLiteral("0"),
                                    ((TypeSpec("void"), IntLiteral("1")), (None, IntLiteral("2"))),
                                    ((9, 4), (9, 16)),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid generic association type at position 1 ('void') at line 9, column 4: void type",
        )

    def test_generic_selection_invalid_type_uses_partial_association_location_fallback(
        self,
    ) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                GenericExpr(
                                    IntLiteral("0"),
                                    ((TypeSpec("void"), IntLiteral("1")), (None, IntLiteral("2"))),
                                    ((None, 8), (9, 16)),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid generic association type at position 1 ('void') at column 8: void type",
        )

    def test_generic_selection_pointer_to_incomplete_record_association_ok(self) -> None:
        unit = parse(
            list(
                lex(
                    "struct S; int main(void){struct S *p=0; return _Generic(p, struct S *: 1, default: 2);}"
                )
            )
        )
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), INT)

    def test_comma_expression_typemap(self) -> None:
        source = "int main(){int x=1; int y=2; return (x=3, y);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].value
        assert expr is not None
        self.assertIsInstance(expr, CommaExpr)
        self.assertIs(sema.type_map.get(expr), INT)

    def test_shift_and_bitwise_expression_typemap(self) -> None:
        source = "int main(){return (1<<2) ^ (3|4) & 7;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[0].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), INT)

    def test_multiplicative_usual_arithmetic_conversion_typemap(self) -> None:
        unit = parse(list(lex("int main(){float f=1.0f; return f*2;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), FLOAT)

    def test_multiplicative_long_double_typemap(self) -> None:
        unit = parse(list(lex("int main(){long double f=1.0L; return f*2.0;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), LONGDOUBLE)

    def test_additive_unsigned_long_and_long_long_typemap(self) -> None:
        unit = parse(list(lex("int main(){unsigned long a=1; long long b=2; return a+b;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), ULLONG)

    def test_bitwise_usual_arithmetic_conversion_typemap(self) -> None:
        unit = parse(list(lex("int main(){long a=1; unsigned b=2; return a|b;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), LONG)

    def test_shift_uses_left_integer_promotion_typemap(self) -> None:
        unit = parse(list(lex("int main(){unsigned short s=1; return s<<1;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), INT)

    def test_shift_requires_integer_left_operand_error(self) -> None:
        unit = parse(list(lex("int main(){float f=1.0f; return f<<1;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Shift left operand must be integer")

    def test_shift_requires_integer_right_operand_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; float f=1.0f; return x<<f;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Shift right operand must be integer")

    def test_modulo_usual_arithmetic_conversion_typemap(self) -> None:
        unit = parse(list(lex("int main(){unsigned long a=7; int b=3; return a%b;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), ULONG)

    def test_division_usual_arithmetic_conversion_typemap(self) -> None:
        unit = parse(list(lex("int main(){float a=8.0f; int b=2; return a/b;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), FLOAT)

    def test_modulo_requires_integer_left_operand_error(self) -> None:
        unit = parse(list(lex("int main(){float f=1.0f; return f%2;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Modulo left operand must be integer")

    def test_modulo_requires_integer_right_operand_error(self) -> None:
        unit = parse(list(lex("int main(){int x=2; float f=1.0f; return x%f;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Modulo right operand must be integer")

    def test_bitwise_requires_integer_left_operand_error(self) -> None:
        unit = parse(list(lex("int main(){float f=1.0f; return f|1;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Bitwise left operand must be integer")

    def test_bitwise_requires_integer_right_operand_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; float f=1.0f; return x|f;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Bitwise right operand must be integer")

    def test_logical_expression_typemap(self) -> None:
        unit = parse(list(lex("int main(){return (1&&2) || 0;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[0].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), INT)

    def test_equality_integer_expression_typemap(self) -> None:
        unit = parse(list(lex("int main(){int x=1; return x==1;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), INT)

    def test_additive_ignores_const_qualifier_typemap(self) -> None:
        unit = parse(list(lex("int main(){const int x=1; return x+2;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].value
        assert expr is not None
        self.assertIs(sema.type_map.get(expr), INT)

    def test_void_return_ok(self) -> None:
        unit = parse(list(lex("void main(){return;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_function_parameters(self) -> None:
        unit = parse(list(lex("int add(int a, int b){return a+b;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["add"]
        self.assertIn("a", func_symbol.locals)
        self.assertIn("b", func_symbol.locals)

    def test_floating_function_signature(self) -> None:
        unit = parse(list(lex("float id(float x){return x;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["id"]
        self.assertEqual(func_symbol.return_type, FLOAT)
        self.assertEqual(func_symbol.locals["x"].type_, FLOAT)

    def test_integer_argument_converts_to_floating_parameter(self) -> None:
        source = "float id(float x){return x;} int main(void){return (int)id(1);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_long_double_function_signature(self) -> None:
        unit = parse(list(lex("long double id(long double x){return x;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["id"]
        self.assertEqual(func_symbol.return_type, LONGDOUBLE)
        self.assertEqual(func_symbol.locals["x"].type_, LONGDOUBLE)

    def test_void_pointer_parameter_is_allowed(self) -> None:
        unit = parse(list(lex("int f(void *p){return 0;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["f"]
        self.assertEqual(func_symbol.locals["p"].type_, Type("void", 1))

    def test_array_parameter_decays_to_pointer(self) -> None:
        unit = parse(list(lex("int f(int a[4]){return a[0];}")))
        sema = analyze(unit)
        func_symbol = sema.functions["f"]
        self.assertEqual(func_symbol.locals["a"].type_, Type("int", 1))

    def test_array_argument_decays_on_call(self) -> None:
        source = "int f(int a[4]){return a[0];} int main(){int x[4]; return f(x);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_function_parameter_decays_to_pointer(self) -> None:
        source = "int apply(int fn(int), int x){return fn(x);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["apply"]
        self.assertEqual(
            func_symbol.locals["fn"].type_,
            Type("int", declarator_ops=(("ptr", 0), ("fn", ((INT,), False)))),
        )

    def test_function_pointer_call_typemap(self) -> None:
        source = "int inc(int x){return x;} int main(){int (*fp)(int)=inc; return fp(1);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[1]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_function_pointer_call_with_two_arguments(self) -> None:
        source = (
            "int add(int a,int b){return a+b;} int main(){int (*fp)(int, int)=add; return fp(1,2);}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[1]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_function_pointer_call_argument_count_mismatch(self) -> None:
        source = "int inc(int x){return x;} int main(){int (*fp)(int)=inc; return fp();}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument count mismatch (expected 1, got 0)")

    def test_function_pointer_call_argument_type_mismatch(self) -> None:
        source = "int inc(int x){return x;} int main(){int (*fp)(int)=inc; int *p; return fp(p);}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument 1 type mismatch")

    def test_function_pointer_without_prototype_call(self) -> None:
        source = "int apply(int (*fp)(), int x){return fp(x,x);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("apply", sema.functions)

    def test_variadic_function_pointer_call(self) -> None:
        source = "int apply(int (*fp)(int, ...), int x){return fp(x, x, x);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("apply", sema.functions)

    def test_variadic_function_pointer_call_argument_count_mismatch(self) -> None:
        source = "int apply(int (*fp)(int, ...)){return fp();}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument count mismatch (expected at least 1, got 0)")

    def test_void_function_pointer_parameter_is_allowed(self) -> None:
        unit = parse(list(lex("int f(void (*cb)(void)){return 0;}")))
        sema = analyze(unit)
        self.assertIn("f", sema.functions)

    def test_function_declaration_then_definition(self) -> None:
        source = (
            "int add(int a, int b);int main(){return add(1,2);}int add(int a, int b){return a+b;}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("add", sema.functions)

    def test_no_prototype_declaration_then_definition(self) -> None:
        source = "int add(); int add(int a){return a;} int main(){return add(1);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("add", sema.functions)

    def test_no_prototype_function_call_allows_any_arguments(self) -> None:
        source = "int add(); int main(){return add(1,2,3);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_prototype_declaration_then_no_prototype_declaration(self) -> None:
        source = "int add(int a); int add(); int main(){return add(1);} int add(int a){return a;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("add", sema.functions)

    def test_variadic_function_call_allows_extra_arguments(self) -> None:
        source = "int logf(int level, ...){return level;} int main(){return logf(1,2,3);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_variadic_function_call_requires_fixed_arguments(self) -> None:
        source = "int logf(int level, ...){return level;} int main(){return logf();}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Argument count mismatch (expected at least 1, got 0): logf",
        )

    def test_variadic_function_call_fixed_argument_type_mismatch(self) -> None:
        source = "int logf(int level, ...){return level;} int main(){int *p; return logf(p, 1);}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument 1 type mismatch: logf")

    def test_function_declaration_without_definition(self) -> None:
        unit = parse(list(lex("int add(int a, int b);")))
        sema = analyze(unit)
        self.assertEqual(sema.functions, {})

    def test_conflicting_function_declaration(self) -> None:
        unit = parse(list(lex("int add(int a); int add(int a, int b);")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conflicting declaration: add")

    def test_overloadable_function_redeclaration_with_different_signature_ok(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(int); "
                    "double __attribute__((overloadable)) test(double);"
                )
            )
        )
        sema = analyze(unit)
        self.assertEqual(sema.functions, {})

    def test_non_overloadable_conflicting_redeclaration_still_errors(self) -> None:
        unit = parse(list(lex("int __attribute__((overloadable)) test(int); double test(double);")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conflicting declaration: test")

    def test_overloadable_compatible_redeclaration_keeps_accepting(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(int); "
                    "int __attribute__((overloadable)) test(int);"
                )
            )
        )
        sema = analyze(unit)
        self.assertEqual(sema.functions, {})

    def test_merge_signature_helper_rejects_incompatible_signatures(self) -> None:
        analyzer = Analyzer()
        with self.assertRaises(SemaError) as ctx:
            analyzer._merge_signature(
                FunctionSignature(INT, (INT,), False),
                FunctionSignature(DOUBLE, (INT,), False),
                "f",
            )
        self.assertEqual(str(ctx.exception), "Conflicting declaration: f")

    def test_overload_resolution_helpers_cover_fallback_and_match_paths(self) -> None:
        analyzer = Analyzer()
        scope = Scope()
        scope.define(VarSymbol("x", INT))
        default = FunctionSignature(INT, (INT,), False)
        self.assertEqual(
            analyzer._resolve_call_signature("f", [Identifier("x")], scope, default=default),
            default,
        )
        analyzer._function_overloads["f"] = [FunctionSignature(INT, (CHAR.pointer_to(),), False)]
        self.assertEqual(
            analyzer._resolve_call_signature("f", [Identifier("x")], scope, default=default),
            default,
        )
        self.assertEqual(
            analyzer._match_overload_signature(
                [Identifier("x")],
                [INT],
                FunctionSignature(INT, None, False),
                scope,
            ),
            (0, 0),
        )
        self.assertIsNone(
            analyzer._match_overload_signature(
                [Identifier("x")],
                [INT],
                FunctionSignature(INT, (INT, INT), False),
                scope,
            )
        )
        self.assertIsNone(
            analyzer._match_overload_signature(
                [],
                [],
                FunctionSignature(INT, (INT,), True),
                scope,
            )
        )
        self.assertEqual(
            analyzer._match_overload_signature(
                [Identifier("x")],
                [INT],
                FunctionSignature(INT, (INT,), True),
                scope,
            ),
            (1, 0),
        )

    def test_overload_cast_helper_paths_and_unhashable_expr_tracking(self) -> None:
        analyzer = Analyzer()
        unhashable_expr = CallExpr(Identifier("f"), [])
        analyzer._set_overload_expr_name(unhashable_expr, "f")
        self.assertEqual(analyzer._get_overload_expr_name(unhashable_expr), "f")
        signature = FunctionSignature(INT, (INT,), False)
        self.assertFalse(analyzer._signature_matches_callable_type(signature, INT))
        self.assertIsNone(analyzer._resolve_overload_for_cast("missing", INT.pointer_to()))

    def test_register_function_typed_file_scope_decl_error_paths(self) -> None:
        function_type = TypeSpec(
            "int",
            declarator_ops=(("fn", ((TypeSpec("int"),), False)),),
        )

        with self.subTest(case="storage_class"):
            analyzer = Analyzer()
            with self.assertRaises(SemaError) as ctx:
                analyzer._register_function_typed_file_scope_decl(
                    DeclStmt(function_type, "add_one", None, storage_class="auto")
                )
            self.assertEqual(
                str(ctx.exception),
                "Invalid storage class for file-scope function declaration: 'auto'",
            )

        with self.subTest(case="thread_local"):
            analyzer = Analyzer()
            with self.assertRaises(SemaError) as ctx:
                analyzer._register_function_typed_file_scope_decl(
                    DeclStmt(function_type, "add_one", None, is_thread_local=True)
                )
            self.assertEqual(
                str(ctx.exception),
                "Invalid declaration specifier for function declaration: '_Thread_local'",
            )

        with self.subTest(case="object_conflict"):
            analyzer = Analyzer()
            analyzer._file_scope.define(VarSymbol("add_one", INT))
            with self.assertRaises(SemaError) as ctx:
                analyzer._register_function_typed_file_scope_decl(
                    DeclStmt(function_type, "add_one", None)
                )
            self.assertEqual(str(ctx.exception), "Conflicting declaration: add_one")

        with self.subTest(case="typedef_conflict"):
            analyzer = Analyzer()
            analyzer._file_scope.define_typedef("add_one", INT)
            with self.assertRaises(SemaError) as ctx:
                analyzer._register_function_typed_file_scope_decl(
                    DeclStmt(function_type, "add_one", None)
                )
            self.assertEqual(str(ctx.exception), "Conflicting declaration: add_one")

    def test_overloadable_call_resolves_exact_match(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(int);"
                    "char * __attribute__((overloadable)) test(double);"
                    "int main(void){return test(1);}"
                )
            )
        )
        sema = analyze(unit)
        stmt = _body(next(func for func in unit.functions if func.name == "main")).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        assert stmt.value is not None
        self.assertEqual(sema.type_map.require(stmt.value), INT)

    def test_overloadable_call_resolves_alternative_match(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(int);"
                    "char * __attribute__((overloadable)) test(double);"
                    "int main(void){char *p; p=test(1.0); return 0;}"
                )
            )
        )
        sema = analyze(unit)
        stmt = _body(next(func for func in unit.functions if func.name == "main")).statements[1]
        self.assertIsInstance(stmt, ExprStmt)
        self.assertEqual(sema.type_map.require(stmt.expr), CHAR.pointer_to())

    def test_overloadable_call_ambiguous_error(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(long);"
                    "int __attribute__((overloadable)) test(unsigned long);"
                    "int main(void){return test(1);}"
                )
            )
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Ambiguous overloaded call: test")

    def test_overloadable_call_resolves_through_generic_callee(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(int);"
                    "double __attribute__((overloadable)) test(double);"
                    "int main(void){double d=_Generic(0, default:test)(1.0); return 0;}"
                )
            )
        )
        sema = analyze(unit)
        stmt = _body(next(func for func in unit.functions if func.name == "main")).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        assert stmt.init is not None
        self.assertEqual(sema.type_map.require(stmt.init), DOUBLE)

    def test_overloadable_call_ambiguous_through_generic_callee(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(long);"
                    "int __attribute__((overloadable)) test(unsigned long);"
                    "int main(void){return _Generic(0, default:test)(1);}"
                )
            )
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Ambiguous overloaded call: test")

    def test_overloadable_call_resolves_through_comma_callee(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(int);"
                    "double __attribute__((overloadable)) test(double);"
                    "int main(void){double d=(0, test)(1.0); return 0;}"
                )
            )
        )
        sema = analyze(unit)
        stmt = _body(next(func for func in unit.functions if func.name == "main")).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        assert stmt.init is not None
        self.assertEqual(sema.type_map.require(stmt.init), DOUBLE)

    def test_overloadable_call_resolves_through_conditional_callee(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(int);"
                    "double __attribute__((overloadable)) test(double);"
                    "int main(void){int c; double d=(c ? test : test)(1.0); return 0;}"
                )
            )
        )
        sema = analyze(unit)
        stmt = _body(next(func for func in unit.functions if func.name == "main")).statements[1]
        self.assertIsInstance(stmt, DeclStmt)
        assert stmt.init is not None
        self.assertEqual(sema.type_map.require(stmt.init), DOUBLE)

    def test_overloadable_call_ambiguous_through_conditional_callee(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(long);"
                    "int __attribute__((overloadable)) test(unsigned long);"
                    "int main(void){int c; return (c ? test : test)(1);}"
                )
            )
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Ambiguous overloaded call: test")

    def test_overloadable_call_resolves_through_constant_conditional_callee(self) -> None:
        unit = parse(
            list(
                lex(
                    "double __attribute__((overloadable)) test(double);"
                    "int __attribute__((overloadable)) test(int);"
                    "double alt(double);"
                    "int main(void){double d=(1 ? test : alt)(1.0); return 0;}"
                )
            )
        )
        sema = analyze(unit)
        stmt = _body(next(func for func in unit.functions if func.name == "main")).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        assert stmt.init is not None
        self.assertEqual(sema.type_map.require(stmt.init), DOUBLE)

    def test_overloadable_call_constant_conditional_without_selected_overload_uses_fallback(
        self,
    ) -> None:
        unit = parse(
            list(
                lex(
                    "double __attribute__((overloadable)) test(double);"
                    "int __attribute__((overloadable)) test(int);"
                    "double alt(double);"
                    "int main(void){double d=(0 ? test : alt)(1.0); return 0;}"
                )
            )
        )
        sema = analyze(unit)
        stmt = _body(next(func for func in unit.functions if func.name == "main")).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        assert stmt.init is not None
        self.assertEqual(sema.type_map.require(stmt.init), DOUBLE)

    def test_overloadable_call_non_constant_conditional_without_selected_overload_uses_fallback(
        self,
    ) -> None:
        unit = parse(
            list(
                lex(
                    "double __attribute__((overloadable)) test(double);"
                    "int __attribute__((overloadable)) test(int);"
                    "double alt(double);"
                    "int main(void){int c; double d=(c ? test : alt)(1.0); return 0;}"
                )
            )
        )
        sema = analyze(unit)
        stmt = _body(next(func for func in unit.functions if func.name == "main")).statements[1]
        self.assertIsInstance(stmt, DeclStmt)
        assert stmt.init is not None
        self.assertEqual(sema.type_map.require(stmt.init), DOUBLE)

    def test_overloadable_call_resolves_through_cast_callee(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(int);"
                    "double __attribute__((overloadable)) test(double);"
                    "int main(void){double d=((double (*)(double))test)(1.0); return 0;}"
                )
            )
        )
        sema = analyze(unit)
        stmt = _body(next(func for func in unit.functions if func.name == "main")).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        assert stmt.init is not None
        self.assertEqual(sema.type_map.require(stmt.init), DOUBLE)

    def test_overloadable_cast_without_matching_signature_errors(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(int);"
                    "double __attribute__((overloadable)) test(double);"
                    "int main(void){return ((char *(*)(int))test)(1);}"
                )
            )
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Cast target is not compatible with overload set")

    def test_overloadable_call_resolves_through_statement_expression_callee(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(int);"
                    "double __attribute__((overloadable)) test(double);"
                    "int main(void){double d=({test;})(1.0); return 0;}"
                )
            ),
            std="gnu11",
        )
        sema = analyze(unit, std="gnu11")
        stmt = _body(next(func for func in unit.functions if func.name == "main")).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        assert stmt.init is not None
        self.assertEqual(sema.type_map.require(stmt.init), DOUBLE)

    def test_overloadable_call_ambiguous_through_statement_expression_callee(self) -> None:
        unit = parse(
            list(
                lex(
                    "int __attribute__((overloadable)) test(long);"
                    "int __attribute__((overloadable)) test(unsigned long);"
                    "int main(void){return ({test;})(1);}"
                )
            ),
            std="gnu11",
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertEqual(str(ctx.exception), "Ambiguous overloaded call: test")

    def test_conflicting_function_return_type_declaration(self) -> None:
        unit = parse(list(lex("int add(); void add();")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conflicting declaration: add")

    def test_argument_count_mismatch(self) -> None:
        unit = parse(list(lex("int add(int a,int b){return a+b;} int main(){return add(1);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument count mismatch (expected 2, got 1): add")

    def test_missing_parameter_name_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [Param(TypeSpec("int"), None)],
                    CompoundStmt([]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Missing parameter name")

    def test_if_and_while_ok(self) -> None:
        source = "int main(){if(1) return 1;if(1) return 2; else return 3;while(1) ;return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_do_while_ok(self) -> None:
        source = "int main(){do {continue;} while(0); return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_goto_and_label_ok(self) -> None:
        source = "int main(){goto done; return 1; done: return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_goto_label_shares_name_with_object(self) -> None:
        source = "int main(){int x=0; goto x; x: return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_indirect_goto_pointer_operand_ok(self) -> None:
        source = "int main(void){void const *target=0; goto *target; return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIn("main", sema.functions)

    def test_indirect_goto_label_address_operand_ok(self) -> None:
        source = "int main(void){void *target = &&done; goto *target; done: return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIn("main", sema.functions)

    def test_indirect_goto_requires_pointer_operand(self) -> None:
        unit = parse(list(lex("int main(void){long long x=0; goto *x; return 0;}")), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertEqual(str(ctx.exception), "Indirect goto target must be pointer")

    def test_indirect_goto_requires_void_pointer_operand(self) -> None:
        source = "int main(void){int x=0; int *target=&x; goto *target; return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertEqual(str(ctx.exception), "Indirect goto target must be pointer to void")

    def test_indirect_goto_rejects_function_pointer_operand(self) -> None:
        source = "int main(void){int (*target)(void)=0; goto *target; return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertEqual(str(ctx.exception), "Indirect goto target must be pointer to void")

    def test_statement_expression_break_reports_outside_loop(self) -> None:
        source = "int main(int first){switch(({ if(first){ first=0; break; } 1; })){case 2:return 2;default:return 0;}}"
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertEqual(str(ctx.exception), "break not in loop")

    def test_statement_expression_continue_reports_outside_loop(self) -> None:
        source = "int main(void){for(({continue;});;);}"
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertEqual(str(ctx.exception), "continue not in loop")

    def test_statement_expression_with_decl_and_value_ok(self) -> None:
        source = "int main(void){int x = ({int y=1; y;}); return x;}"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIn("main", sema.functions)

    def test_statement_expression_outside_function_error(self) -> None:
        unit = parse(list(lex("int x = ({1;});")), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertEqual(str(ctx.exception), "Statement expression outside of a function")

    def test_goto_undefined_label_error(self) -> None:
        unit = parse(list(lex("int main(){goto missing; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Undefined label: missing")

    def test_duplicate_label_error(self) -> None:
        unit = parse(list(lex("int main(){x: ; x: return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate label: x")

    def test_compound_statement_inherits_scope(self) -> None:
        source = "int main(){int x=1; { return x; }}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_for_statement_ok(self) -> None:
        source = "int main(){for(int i=0;i<3;i=i+1){break;} return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_block_scope_multi_declarator_ok(self) -> None:
        source = "int main(){int x=1, y=x; return y;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_block_scope_multi_typedef_ok(self) -> None:
        source = "int main(){typedef int T, U; T x=1; U y=2; return x+y;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_for_expression_init_no_condition_or_post(self) -> None:
        source = "int main(){int i=0; for(i=0;;) continue; return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_switch_statement_ok(self) -> None:
        source = "int main(){int x=1;switch(x){case 1: break; default: return 0;}return 1;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_enum_constants_are_defined_in_scope(self) -> None:
        unit = parse(list(lex("int main(){enum E { A, B=3, C }; return C;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["A"].type_, INT)
        self.assertEqual(getattr(func_symbol.locals["B"], "value"), 3)
        self.assertEqual(getattr(func_symbol.locals["C"], "value"), 4)

    def test_enum_member_constant_expression_values(self) -> None:
        unit = parse(list(lex("int main(){enum E { A=1, B=A+2, C=B<<1 }; return C;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertEqual(getattr(func_symbol.locals["A"], "value"), 1)
        self.assertEqual(getattr(func_symbol.locals["B"], "value"), 3)
        self.assertEqual(getattr(func_symbol.locals["C"], "value"), 6)

    def test_enum_member_non_constant_value_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; enum E { A=x }; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Enumerator value is not integer constant")

    def test_enum_object_type_resolves_to_int(self) -> None:
        unit = parse(list(lex("int main(){enum E { A=1 } x=A; return x;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["x"].type_, INT)

    def test_pointer_to_enum_resolves_to_int_pointer(self) -> None:
        unit = parse(list(lex("int main(){enum E *p; return 0;}")))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertEqual(func_symbol.locals["p"].type_, Type("int", 1))

    def test_case_accepts_enum_constant_and_unary_sign(self) -> None:
        source = (
            "int main(){"
            "enum E { A=1, B=2 };"
            "switch(B){case A: break; case +2: break; case -1: break; default: return 0;}"
            "return 1;"
            "}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_struct_object_type_is_assignable(self) -> None:
        source = "int main(){struct Node { int value; } a;struct Node b;b=a;return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_union_object_type_is_assignable(self) -> None:
        source = "int main(){union Data { int x; int y; } a;union Data b;b=a;return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_anonymous_struct_object_type(self) -> None:
        unit = parse(list(lex("int main(){struct { int x; } v; return 0;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_forward_declare_then_define_struct_ok(self) -> None:
        source = "int main(){struct S; struct S { int x; }; struct S value; return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_pointer_to_incomplete_struct_is_allowed(self) -> None:
        unit = parse(list(lex("int main(){struct Node *next; return 0;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_anonymous_enum_in_struct_members_visible_at_file_scope(self) -> None:
        source = (
            "struct S { enum { A=0, B=1 } tag; int x; };"
            "int val = A;"
            "int main(){return 0;}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_anonymous_enum_in_nested_struct_ok(self) -> None:
        source = (
            "struct Outer { struct Inner { enum { X=5 } e; } in; };"
            "int val = X;"
            "int main(){return 0;}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_function_call_typemap(self) -> None:
        source = "int add(int a,int b){return a+b;} int main(){return add(1,2);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        call_expr = _body(unit.functions[1]).statements[0].value
        self.assertIsInstance(call_expr, CallExpr)
        self.assertIs(sema.type_map.get(call_expr), INT)

    def test_pointer_address_of_and_dereference_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; return *p;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        pointer_init = _body(unit.functions[0]).statements[1].init
        assert pointer_init is not None
        self.assertEqual(sema.type_map.get(pointer_init), Type("int", 1))
        return_expr = _body(unit.functions[0]).statements[2].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_assignment_through_dereference(self) -> None:
        source = "int main(){int x=1; int *p=&x; *p=2; return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        assign_stmt = _body(unit.functions[0]).statements[2]
        assign_expr = assign_stmt.expr
        self.assertEqual(sema.type_map.get(assign_expr), INT)

    def test_address_of_dereference_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; int *q=&*p; return *q;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        pointer_init = _body(unit.functions[0]).statements[2].init
        assert pointer_init is not None
        self.assertEqual(sema.type_map.get(pointer_init), Type("int", 1))

    def test_pointer_plus_integer_typemap(self) -> None:
        source = "int main(){int a[3]; int *p=&a[1]; int *q=p+1; return q-p;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        plus_expr = _body(unit.functions[0]).statements[2].init
        assert plus_expr is not None
        self.assertEqual(sema.type_map.get(plus_expr), Type("int", 1))
        minus_expr = _body(unit.functions[0]).statements[3].value
        assert minus_expr is not None
        self.assertEqual(sema.type_map.get(minus_expr), INT)

    def test_integer_plus_pointer_typemap(self) -> None:
        source = "int main(){int a[3]; int *p=&a[1]; int *q=1+p; return q-p;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        plus_expr = _body(unit.functions[0]).statements[2].init
        assert plus_expr is not None
        self.assertEqual(sema.type_map.get(plus_expr), Type("int", 1))

    def test_pointer_minus_integer_typemap(self) -> None:
        source = "int main(){int a[3]; int *p=&a[2]; int *q=p-1; return q-p;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        minus_expr = _body(unit.functions[0]).statements[2].init
        assert minus_expr is not None
        self.assertEqual(sema.type_map.get(minus_expr), Type("int", 1))

    def test_array_decay_pointer_subtraction_typemap(self) -> None:
        source = "int main(){int a[3]; return &a[2]-a;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_pointer_subtraction_compatible_qualified_pointers_typemap(self) -> None:
        source = "int main(){int a[2]; int *p=&a[1]; const int *q=&a[0]; return p-q;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[3].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_relational_pointer_same_type_typemap(self) -> None:
        source = "int main(){int a[2]; int *p=&a[0]; int *q=&a[1]; return p<q;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[3].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_relational_pointer_compatible_qualified_types_typemap(self) -> None:
        source = "int main(){int a[2]; int *p=&a[0]; const int *q=&a[1]; return p<q;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[3].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_relational_nested_pointer_qualifier_mismatch_error(self) -> None:
        source = "int main(){int x=1; int *p=&x; int **pp=&p; const int **cpp=0; return pp<cpp;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Relational operator requires integer or compatible object pointer operands",
        )

    def test_equality_pointer_same_type_typemap(self) -> None:
        source = "int main(){int a[2]; int *p=&a[0]; int *q=&a[1]; return p==q;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[3].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_equality_null_pointer_constant_left_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; return 0==p;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[2].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_equality_function_pointer_and_casted_null_pointer_constant_typemap(self) -> None:
        source = "int f(void){return 0;} int main(){int (*fp)(void)=f; return fp==(void*)0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[1]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_equality_casted_null_pointer_constant_and_function_pointer_typemap(self) -> None:
        source = "int f(void){return 0;} int main(){int (*fp)(void)=f; return (void*)0==fp;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[1]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_equality_void_pointer_and_object_pointer_typemap(self) -> None:
        source = "int main(){int x=1; int *p=&x; void *vp=p; return vp==p;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[3].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_array_subscript_typemap(self) -> None:
        source = "int main(){int a[3]; a[0]=1; return a[0];}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        assign_expr = _body(unit.functions[0]).statements[1].expr
        return_expr = _body(unit.functions[0]).statements[2].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(assign_expr), INT)
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_nested_array_subscript_typemap(self) -> None:
        source = "int main(){int a[2][3]; return a[1][2];}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_address_of_subscript_typemap(self) -> None:
        source = "int main(){int a[2]; int *p=&a[0]; return *p;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        pointer_init = _body(unit.functions[0]).statements[1].init
        assert pointer_init is not None
        self.assertEqual(sema.type_map.get(pointer_init), Type("int", 1))

    def test_member_access_typemap(self) -> None:
        source = "int main(){struct S { int x; } s; return s.x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_pointer_member_access_typemap(self) -> None:
        source = "int main(){struct S { int x; } s; struct S *p=&s; return p->x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[2].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_anonymous_struct_union_member_access_typemap(self) -> None:
        source = (
            "struct holder { union { struct { int x; int y; }; long packed; }; };"
            "int main(void){struct holder value; value.x=1; value.y=2; return value.x + value.y;}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[3].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_anonymous_struct_in_union_member_access_typemap(self) -> None:
        source = (
            "union cell { struct { int x; int y; }; long pair; };"
            "int main(void){union cell value; value.x=1; value.y=2; return value.x + value.y;}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[3].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_anonymous_union_in_struct_member_access_typemap(self) -> None:
        source = (
            "struct holder { union { int x; int y; }; long packed; };"
            "int main(void){struct holder value; value.x=1; value.packed=2; return value.x;}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[3].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_member_assignment_is_allowed(self) -> None:
        source = "int main(){struct S { int x; } s; s.x=1; return s.x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        assign_expr = _body(unit.functions[0]).statements[1].expr
        self.assertEqual(sema.type_map.get(assign_expr), INT)

    def test_pointer_member_assignment_is_allowed(self) -> None:
        source = "int main(){struct S { int x; } s; struct S *p=&s; p->x=1; return p->x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        assign_expr = _body(unit.functions[0]).statements[2].expr
        self.assertEqual(sema.type_map.get(assign_expr), INT)

    def test_sizeof_expression_typemap(self) -> None:
        unit = parse(list(lex("int main(){int x; return sizeof x;}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_sizeof_type_name_typemap(self) -> None:
        unit = parse(list(lex("int main(){return sizeof(int*);}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[0].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_sizeof_unsigned_short_type_name_typemap(self) -> None:
        unit = parse(list(lex("int main(){return sizeof(unsigned short);}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[0].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_sizeof_complete_record_expression_typemap(self) -> None:
        source = "int main(){struct S { int x; } s; return sizeof(s);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_sizeof_pointer_to_incomplete_record_type_name_ok(self) -> None:
        unit = parse(list(lex("int main(){return sizeof(struct S*);}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_sizeof_record_type_name_with_definition_ok(self) -> None:
        unit = parse(list(lex("int main(){return sizeof(struct S { int x; });}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_alignof_type_name_typemap(self) -> None:
        unit = parse(list(lex("int main(){return _Alignof(int*);}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[0].value
        assert return_expr is not None
        self.assertIsInstance(return_expr, AlignofExpr)
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_alignof_expression_typemap(self) -> None:
        unit = parse(list(lex("int main(){int x; return _Alignof(x);}")), std="gnu11")
        sema = analyze(unit, std="gnu11")
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_alignof_expression_rejected_in_c11(self) -> None:
        unit = parse(list(lex("int main(){int x; return _Alignof(x);}")), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="c11")
        self.assertEqual(
            str(ctx.exception), "Invalid alignof operand: expression form requires GNU mode"
        )

    def test_alignof_expression_rejected_in_c11_ast_path(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([ReturnStmt(AlignofExpr(Identifier("x"), None))]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="c11")
        self.assertEqual(
            str(ctx.exception), "Invalid alignof operand: expression form requires GNU mode"
        )

    def test_cast_expression_typemap(self) -> None:
        unit = parse(list(lex("int main(){int *p; return (int)p;}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_unsigned_long_cast_expression_typemap(self) -> None:
        unit = parse(list(lex("int main(){int x=1; return (unsigned long)x;}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), ULONG)

    def test_unsigned_long_long_cast_expression_typemap(self) -> None:
        unit = parse(list(lex("int main(){int x=1; return (unsigned long long)x;}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), ULLONG)

    def test_cast_to_pointer_typemap(self) -> None:
        unit = parse(list(lex("int main(){int x; int *p=(int*)x; return p!=0;}")))
        sema = analyze(unit)
        init_expr = _body(unit.functions[0]).statements[1].init
        assert init_expr is not None
        self.assertEqual(sema.type_map.get(init_expr), Type("int", 1))

    def test_void_cast_statement_ok(self) -> None:
        unit = parse(list(lex("int f(void){return 0;} int main(){(void)f(); return 0;}")))
        sema = analyze(unit)
        expr_stmt = _body(unit.functions[1]).statements[0]
        assert isinstance(expr_stmt, ExprStmt)
        self.assertEqual(sema.type_map.get(expr_stmt.expr), Type("void"))

    def test_typedef_alias_declaration_typemap(self) -> None:
        unit = parse(list(lex("int main(){typedef int T; T x=1; return x;}")))
        sema = analyze(unit)
        self.assertEqual(sema.functions["main"].locals["x"].type_, INT)

    def test_typedef_pointer_alias_typemap(self) -> None:
        source = "int main(){typedef int *P; int x=1; P p=&x; return *p;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[3].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_typedef_inner_scope_shadowing(self) -> None:
        source = "int main(){typedef int T; {typedef int* T; int x=1; T p=&x;} T y=2; return y;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertEqual(sema.functions["main"].locals["y"].type_, INT)

    def test_typedef_in_for_init_ok(self) -> None:
        unit = parse(list(lex("int main(){for(typedef int T;;) break; return 0;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_file_scope_typedef_function_signature_and_body(self) -> None:
        unit = parse(list(lex("typedef int T; T main(){T x=1; return x;}")))
        sema = analyze(unit)
        self.assertEqual(sema.functions["main"].return_type, INT)
        self.assertEqual(sema.functions["main"].locals["x"].type_, INT)

    def test_file_scope_typedef_function_declaration_then_definition(self) -> None:
        source = "typedef int T; T add(T a, T b); T main(){return add(1,2);} T add(T a, T b){return a+b;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("add", sema.functions)
        self.assertIn("main", sema.functions)

    def test_file_scope_typedef_function_type_declaration_then_definition(self) -> None:
        source = (
            "typedef int unary_int_func(int arg); "
            "unary_int_func add_one; "
            "int add_one(int arg){return arg + 1;}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("add_one", sema.functions)

    def test_file_scope_typedef_incomplete_record_pointer_ok(self) -> None:
        source = "typedef struct S S; int main(){S *p; return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_file_scope_object_access_typemap(self) -> None:
        unit = parse(list(lex("int g=1; int main(){return g;}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[0].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_file_scope_object_initializer_type_mismatch(self) -> None:
        unit = parse(list(lex("int *g=1; int main(){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_file_scope_null_pointer_initializer_ok(self) -> None:
        unit = parse(list(lex("int *g=0; int main(){return g==0;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_file_scope_void_pointer_initializer_from_function_pointer_error(self) -> None:
        source = "int f(void); void *g=f; int f(void){return 0;} int main(){return 0;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_gnu_cross_pointer_init_allowed(self) -> None:
        # char* = int* is rejected in c11 but allowed in gnu11
        source = "int *p = 0; char *q = p; int main(){return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIn("main", sema.functions)

    def test_gnu_non_null_integer_to_pointer_init_allowed(self) -> None:
        # void* = 1 (non-zero integer) is rejected in c11 but allowed in gnu11
        source = "void *p = 1; int main(){return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIn("main", sema.functions)

    def test_gnu_pointer_to_integer_init_allowed(self) -> None:
        # char = char* (pointer in integer) OK only in gnu11
        source = "int main(){char *p = 0; char c = p; return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIn("main", sema.functions)

    def test_file_scope_char_array_string_initializer_ok(self) -> None:
        unit = parse(list(lex('char s[4]="abc"; int main(){return s[0];}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_incomplete_char_array_string_initializer_ok(self) -> None:
        unit = parse(list(lex('int main(){char s[]="abc";return 0;}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_incomplete_const_char_array_string_initializer_ok(self) -> None:
        unit = parse(list(lex('const char s[]="hello"; int main(){return s[0];}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_incomplete_char_array_concatenated_string_initializer_ok(self) -> None:
        unit = parse(list(lex('int main(){char s[]="a""b";return 0;}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_duplicate_file_scope_object_declaration(self) -> None:
        unit = parse(list(lex("int g; int g; int main(){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: g")

    def test_file_scope_incomplete_object_error(self) -> None:
        unit = parse(list(lex("struct S g; int main(){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for file-scope object declaration: incomplete",
        )

    def test_duplicate_file_scope_typedef_declaration(self) -> None:
        unit = parse(list(lex("typedef int T; typedef int T; int main(){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: T")

    def test_struct_definition_before_function_declaration_ok(self) -> None:
        source = "struct S { int x; }; struct S f(void); int main(){return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_function_declaration_before_struct_definition_error(self) -> None:
        source = "struct S f(void); struct S { int x; }; int main(){return 0;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid return type: incomplete")

    def test_file_scope_object_then_function_conflict_error(self) -> None:
        unit = parse(list(lex("int f; int f(void); int main(){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conflicting declaration: f")

    def test_function_then_file_scope_object_conflict_error(self) -> None:
        unit = parse(list(lex("int f(void); int f; int main(){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conflicting declaration: f")

    def test_file_scope_typedef_then_function_conflict_error(self) -> None:
        unit = parse(list(lex("typedef int f; int f(void); int main(){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conflicting declaration: f")

    def test_function_then_file_scope_typedef_conflict_error(self) -> None:
        unit = parse(list(lex("int f(void); typedef int f; int main(){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conflicting declaration: f")

    def test_file_scope_tag_declaration_ok(self) -> None:
        unit = parse(list(lex("struct S; int main(){return 0;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_null_stmt_at_file_scope_is_ignored(self) -> None:
        """Empty statements (lone ';') at file scope should be ignored."""
        unit = parse(list(lex("; int main(){return 0;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_file_scope_multi_declarator_declaration_ok(self) -> None:
        source = "int x=1, y=2; int main(){return x+y;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_file_scope_static_assert_ok(self) -> None:
        unit = parse(list(lex('_Static_assert(1, "ok"); int main(void){return 0;}')))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_block_scope_static_assert_ok(self) -> None:
        unit = parse(list(lex('int main(void){_Static_assert(1, "ok"); return 0;}')))
        sema = analyze(unit)
        statement = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(statement, StaticAssertDecl)
        self.assertIn("main", sema.functions)

    def test_file_scope_void_object_error(self) -> None:
        unit = TranslationUnit([], [DeclStmt(TypeSpec("void"), "g", None)])
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for file-scope object declaration: void",
        )

    def test_unsupported_file_scope_declaration_node_error(self) -> None:
        unit = TranslationUnit([], [ExprStmt(IntLiteral("1"))])
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Unsupported file-scope declaration node: ExprStmt (internal sema bug: unexpected AST file-scope declaration node)",
        )

    def test_parenthesized_pointer_to_array_typemap(self) -> None:
        source = "int main(){int a[4]; int (*p)[4]=&a; return (*p)[1];}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        pointer_init = _body(unit.functions[0]).statements[1].init
        assert pointer_init is not None
        self.assertEqual(
            sema.type_map.get(pointer_init),
            Type("int", declarator_ops=(("ptr", 0), ("arr", 4))),
        )

    def test_pointer_to_array_assignment_is_allowed(self) -> None:
        source = (
            "int main(){int a[4]; int b[4]; int (*p)[4]=&a; int (*q)[4]=&b; p=q; return (*p)[0];}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_subscript_non_integer_index_error(self) -> None:
        unit = parse(list(lex("int main(){int a[2]; int *p=&a[0]; return a[p];}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Array subscript is not an integer")

    def test_subscript_non_array_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; return x[0];}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Subscripted value is not an array or pointer")

    def test_array_assignment_is_rejected(self) -> None:
        unit = parse(list(lex("int main(){int a[2]; int b[2]; a=b; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment target is not assignable")

    def test_null_statement(self) -> None:
        unit = parse(list(lex("int main(){; return 0;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_undeclared_identifier(self) -> None:
        unit = parse(list(lex("int main(){return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Undeclared identifier: x")

    def test_initializer_type_mismatch(self) -> None:
        unit = parse(list(lex("int main(){int *p=1; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_designated_array_initializer_ok(self) -> None:
        unit = parse(list(lex("int main(){int a[4] = {[2] = 3, [0] = 1}; return a[2];}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_designated_range_initializer_ok(self) -> None:
        unit = parse(list(lex("int a[6] = {[0 ... 3] = 8, [4] = 1, [5] = 2};")))
        analyze(unit)

    def test_designated_range_incomplete_array_ok(self) -> None:
        unit = parse(list(lex("int a[] = {[0 ... 3] = 8, [4] = 1};")))
        analyze(unit)

    def test_designated_range_out_of_bounds_error(self) -> None:
        with self.assertRaises(SemaError) as ctx:
            unit = parse(list(lex("int a[4] = {[0 ... 5] = 8};")))
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer range out of bounds")

    def test_designated_range_nested_in_multidim_array(self) -> None:
        unit = parse(list(lex("int a[2][3] = {[0 ... 1] = {1, 2, 3}};")))
        analyze(unit)

    def test_designated_struct_initializer_ok(self) -> None:
        source = "int main(){struct S { int x; int y; } s = {.y = 2, .x = 1}; return s.x + s.y;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_designated_initializer_index_not_constant_error(self) -> None:
        unit = parse(list(lex("int main(void){int i=1; int a[4] = {[i] = 2}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer index is not integer constant")

    def test_designated_initializer_index_out_of_range_error(self) -> None:
        unit = parse(list(lex("int main(void){int a[2] = {[2] = 1}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer index out of range")

    def test_designated_initializer_unknown_member_error(self) -> None:
        unit = parse(list(lex("int main(void){struct S { int x; } s = {.y = 1}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "No such member: y")

    def test_scalar_braced_initializer_with_multiple_items_error(self) -> None:
        unit = parse(list(lex("int main(void){int x = {1, 2}; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception), "Scalar initializer list must contain exactly one item"
        )

    def test_scalar_braced_initializer_with_designator_error(self) -> None:
        unit = parse(list(lex("int main(void){int x = {[0] = 1}; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Scalar initializer list item cannot be designated")

    def test_scalar_braced_initializer_single_item_ok(self) -> None:
        unit = parse(list(lex("int main(void){int x = {1}; return x;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_array_initializer_rejects_member_designator_error(self) -> None:
        unit = parse(list(lex("int main(void){int a[2] = {.x = 1}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Array initializer designator must use index")

    def test_array_initializer_rejects_too_many_positional_items_error(self) -> None:
        unit = parse(list(lex("int main(void){int a[1] = {1, 2}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer index out of range")

    def test_union_initializer_rejects_multiple_positional_items_error(self) -> None:
        unit = parse(list(lex("int main(void){union U { int x; int y; } u = {1, 2}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_union_designated_initializer_ok(self) -> None:
        unit = parse(
            list(lex("int main(void){union U { int x; int y; } u = {.y = 2}; return u.y;}"))
        )
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_union_initializer_rejects_multiple_designated_items_error(self) -> None:
        unit = parse(
            list(lex("int main(void){union U { int x; int y; } u = {.x = 1, .y = 2}; return 0;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_union_initializer_rejects_designated_after_positional_item_error(self) -> None:
        unit = parse(
            list(lex("int main(void){union U { int x; int y; } u = {1, .y = 2}; return 0;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_struct_initializer_rejects_too_many_positional_items_error(self) -> None:
        unit = parse(list(lex("int main(void){struct S { int x; } s = {1, 2}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_struct_initializer_rejects_index_designator_error(self) -> None:
        unit = parse(list(lex("int main(void){struct S { int x; } s = {[0] = 1}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Record initializer designator must use member")

    def test_nested_array_designated_initializer_ok(self) -> None:
        unit = parse(list(lex("int main(void){int a[2][2] = {[0][1] = 1}; return a[0][1];}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_nested_member_designated_initializer_ok(self) -> None:
        source = "int main(void){struct T { struct S { int x; } s; } t = {.s.x = 1}; return t.s.x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_incomplete_array_initializer_ok(self) -> None:
        unit = parse(list(lex("int main(void){int a[] = {1, 2, 3}; return a[0];}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_incomplete_array_initializer_with_designator_ok(self) -> None:
        unit = parse(list(lex("int main(void){int a[] = {[2] = 5, 1}; return a[0];}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_incomplete_array_with_member_designator_error(self) -> None:
        unit = parse(list(lex("int main(void){int a[] = {.x = 1}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Array initializer designator must use index")

    def test_incomplete_array_file_scope_ok(self) -> None:
        unit = parse(list(lex("int g[] = {10, 20}; int main(void){return g[0];}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_nested_member_designator_on_scalar_error(self) -> None:
        unit = parse(list(lex("int main(void){int a[1] = {[0].x = 1}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_nested_index_designator_on_scalar_error(self) -> None:
        unit = parse(list(lex("int main(void){int a[1] = {[0][0] = 1}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_nested_index_designator_out_of_range_error(self) -> None:
        unit = parse(list(lex("int main(void){int a[1][1] = {[0][1] = 1}; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer index out of range")

    def test_assignment_type_mismatch(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; x=p; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment value is not compatible with target type")

    def test_compound_assignment_int_ok(self) -> None:
        source = "int main(){int x=8; x+=2; x<<=1; x%=3; return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_compound_assignment_arithmetic_float_ok(self) -> None:
        source = "int main(){float x=1.0f; x+=2; x*=3.0f; x/=2; return 0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        plus_assign = _body(unit.functions[0]).statements[1].expr
        mul_assign = _body(unit.functions[0]).statements[2].expr
        div_assign = _body(unit.functions[0]).statements[3].expr
        self.assertIs(sema.type_map.get(plus_assign), FLOAT)
        self.assertIs(sema.type_map.get(mul_assign), FLOAT)
        self.assertIs(sema.type_map.get(div_assign), FLOAT)

    def test_compound_assignment_bitwise_requires_integer_target_error(self) -> None:
        unit = parse(list(lex("int main(){float x=1.0f; x|=1; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Compound bitwise/shift/modulo assignment requires integer operands",
        )

    def test_compound_assignment_multiplicative_requires_arithmetic_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; p*=2; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Compound multiplicative assignment requires arithmetic operands",
        )

    def test_compound_assignment_type_mismatch(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; x+=p; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Compound additive assignment requires arithmetic operands or pointer/integer",
        )

    def test_compound_assignment_pointer_plus_equals_int_ok(self) -> None:
        unit = parse(list(lex("int main(){int a[3]; int *p=&a[0]; p+=1; return p-a;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].expr
        self.assertEqual(sema.type_map.get(expr), Type("int", 1))

    def test_compound_assignment_pointer_minus_equals_int_ok(self) -> None:
        unit = parse(list(lex("int main(){int a[3]; int *p=&a[2]; p-=1; return p-a;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[2].expr
        self.assertEqual(sema.type_map.get(expr), Type("int", 1))

    def test_compound_assignment_pointer_plus_equals_pointer_error(self) -> None:
        unit = parse(
            list(lex("int main(){int x=1; int y=2; int *p=&x; int *q=&y; p+=q; return 0;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Compound additive assignment requires arithmetic operands or pointer/integer",
        )

    def test_compound_assignment_void_pointer_plus_equals_int_error(self) -> None:
        unit = parse(list(lex("int main(){void *p=0; p+=1; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Compound additive assignment requires arithmetic operands or pointer/integer",
        )

    def test_compound_assignment_function_pointer_minus_equals_int_error(self) -> None:
        source = "int f(void){return 0;} int main(){int (*fp)(void)=f; fp-=1; return 0;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Compound additive assignment requires arithmetic operands or pointer/integer",
        )

    def test_compound_assignment_shift_value_type_mismatch(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; x<<=p; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Compound bitwise/shift/modulo assignment requires integer operands",
        )

    def test_manual_assignment_expression_still_analyzes_supported_operator(self) -> None:
        expr = AssignExpr("|=", Identifier("x"), IntLiteral("1"))
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(TypeSpec("int"), "x", IntLiteral("0")),
                            ExprStmt(expr),
                            ReturnStmt(Identifier("x")),
                        ]
                    ),
                )
            ]
        )
        sema = analyze(unit)
        self.assertIs(sema.type_map.get(expr), INT)

    def test_unsupported_assignment_operator_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(TypeSpec("int"), "x", IntLiteral("1")),
                            ExprStmt(AssignExpr("?=", Identifier("x"), IntLiteral("2"))),
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Unsupported assignment operator: ?=")

    def test_manual_update_expression_still_analyzes_supported_operator(self) -> None:
        expr = UpdateExpr("++", Identifier("x"), False)
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(TypeSpec("int"), "x", IntLiteral("1")),
                            ExprStmt(expr),
                            ReturnStmt(Identifier("x")),
                        ]
                    ),
                )
            ]
        )
        sema = analyze(unit)
        self.assertIs(sema.type_map.get(expr), INT)

    def test_unsupported_update_operator_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(TypeSpec("int"), "x", IntLiteral("1")),
                            ExprStmt(UpdateExpr("?!", Identifier("x"), False)),
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Unsupported update operator: ?!")

    def test_assignment_pointer_null_constant_ok(self) -> None:
        unit = parse(list(lex("int main(){int *p; p=0; return p==0;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_assignment_to_const_object_error(self) -> None:
        unit = parse(list(lex("int main(){const int x=0; x=1; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment target is not assignable")

    def test_update_const_object_error(self) -> None:
        unit = parse(list(lex("int main(){const int x=0; ++x; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment target is not assignable")

    def test_assignment_non_constant_integer_to_pointer_error(self) -> None:
        unit = parse(list(lex("int main(){int z=0; int *p; p=z; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment value is not compatible with target type")

    def test_assignment_void_pointer_conversion_ok(self) -> None:
        source = "int main(){int x=1; int *p=&x; void *vp=0; vp=p; p=vp; return p!=0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_initializer_pointer_adds_const_qualifier_ok(self) -> None:
        source = "int main(){int x=1; int *p=&x; const int *cp=p; return *cp;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_assignment_pointer_drops_const_qualifier_error(self) -> None:
        source = "int main(){int x=1; const int *cp=&x; int *p=0; p=cp; return *p;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment value is not compatible with target type")

    def test_assignment_nested_pointer_adds_const_qualifier_error(self) -> None:
        source = "int main(){int x=1; int *p=&x; int **pp=&p; const int **cpp=pp; return 0;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_assignment_function_pointer_to_void_pointer_error(self) -> None:
        source = (
            "int f(void){return 0;} int main(){int (*fp)(void)=f; void *vp=0; vp=fp; return 0;}"
        )
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment value is not compatible with target type")

    def test_assignment_function_pointer_to_void_pointer_ok_in_gnu_mode(self) -> None:
        source = (
            "int f(void){return 0;} int main(){int (*fp)(void)=f; void *vp=0; vp=fp; return 0;}"
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIn("main", sema.functions)

    def test_gnu_cross_pointer_assignment_allowed(self) -> None:
        source = "int main(){int *p = 0; char *q; q = p; return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIn("main", sema.functions)

    def test_gnu_non_pointer_assignment_still_rejected(self) -> None:
        # Non-pointer types are still rejected even in gnu11
        source = "int main(){int x; struct S { int a; } s; s = x; return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not compatible", str(ctx.exception))

    def test_assignment_void_pointer_to_function_pointer_error(self) -> None:
        source = (
            "int f(void){return 0;} int main(){int (*fp)(void)=f; void *vp=0; fp=vp; return 0;}"
        )
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment value is not compatible with target type")

    def test_assignment_incompatible_object_pointers_error(self) -> None:
        source = "int main(){int x=1; char y=97; int *p=&x; char *q=&y; p=q; return 0;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment value is not compatible with target type")

    def test_return_type_mismatch(self) -> None:
        unit = parse(list(lex("int *f(int *p){return 1;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception), "Return value is not compatible with function return type"
        )

    def test_return_null_pointer_constant_ok(self) -> None:
        unit = parse(list(lex("int *f(void){return 0;} int main(){return f()==0;}")))
        sema = analyze(unit)
        self.assertIn("f", sema.functions)
        self.assertIn("main", sema.functions)

    def test_return_void_pointer_from_object_pointer_ok(self) -> None:
        source = "void *f(int *p){return p;} int main(){int x=1; int *p=&x; return f(p)!=0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("f", sema.functions)

    def test_return_void_pointer_from_function_pointer_error(self) -> None:
        source = "void *f(int (*fp)(void)){return fp;} int g(void){return 0;} int main(){return 0;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception), "Return value is not compatible with function return type"
        )

    def test_argument_type_mismatch(self) -> None:
        unit = parse(list(lex("int *id(int *p){return p;} int main(){int x=1; return id(x);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument 1 type mismatch: id")

    def test_argument_null_pointer_constant_ok(self) -> None:
        unit = parse(list(lex("int *id(int *p){return p;} int main(){return id(0)==0;}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_argument_void_pointer_from_object_pointer_ok(self) -> None:
        source = "int ok(void *p){return p!=0;} int main(){int x=1; int *p=&x; return ok(p);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("ok", sema.functions)

    def test_argument_object_pointer_from_void_pointer_ok(self) -> None:
        source = "int *id(int *p){return p;} int main(){void *vp=0; return id(vp)==0;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_argument_pointer_adds_const_qualifier_ok(self) -> None:
        source = "int f(const int *p){return *p;} int main(){int x=1; int *p=&x; return f(p);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("f", sema.functions)

    def test_argument_pointer_drops_const_qualifier_error(self) -> None:
        source = "int f(int *p){return *p;} int main(){int x=1; const int *p=&x; return f(p);}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument 1 type mismatch: f")

    def test_argument_nested_pointer_adds_const_qualifier_error(self) -> None:
        source = "int f(const int **p){return 0;} int main(){int x=1; int *p=&x; int **pp=&p; return f(pp);}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument 1 type mismatch: f")

    def test_argument_void_pointer_from_function_pointer_error(self) -> None:
        source = "int takes(void *p){return 0;} int f(void){return 0;} int main(){return takes(f);}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument 1 type mismatch: takes")

    def test_dereference_non_pointer_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; return *x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Cannot dereference non-pointer")

    def test_unary_minus_requires_arithmetic_operand_error(self) -> None:
        unit = parse(list(lex("int main(){int *p; return -p;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Unary minus operand must be arithmetic")

    def test_unary_plus_requires_arithmetic_operand_error(self) -> None:
        unit = parse(list(lex("int main(){int *p; return +p;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Unary plus operand must be arithmetic")

    def test_bitwise_not_requires_integer_operand_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; return ~p;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Bitwise not operand must be integer")

    def test_unary_minus_float_typemap(self) -> None:
        unit = parse(list(lex("int main(){float f=1.0f; -f; return 0;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].expr
        self.assertIs(sema.type_map.get(expr), FLOAT)

    def test_unary_plus_float_typemap(self) -> None:
        unit = parse(list(lex("int main(){float f=1.0f; +f; return 0;}")))
        sema = analyze(unit)
        expr = _body(unit.functions[0]).statements[1].expr
        self.assertIs(sema.type_map.get(expr), FLOAT)

    def test_logical_not_scalar_operand_error(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; } s; return !s;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Logical not requires scalar operand")

    def test_multiplication_requires_arithmetic_left_operand_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; return p*1;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Multiplication left operand must be arithmetic")

    def test_multiplication_requires_arithmetic_right_operand_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; return 1*p;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Multiplication right operand must be arithmetic")

    def test_division_requires_arithmetic_left_operand_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; return p/1;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Division left operand must be arithmetic")

    def test_division_requires_arithmetic_right_operand_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; return 1/p;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Division right operand must be arithmetic")

    def test_additive_pointer_plus_pointer_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int y=2; int *p=&x; int *q=&y; return p+q;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Addition operands must be arithmetic or pointer/integer",
        )

    def test_additive_integer_minus_pointer_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; return 1-p;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Subtraction operands must be arithmetic, pointer/integer, or compatible pointers",
        )

    def test_additive_pointer_mismatch_error(self) -> None:
        unit = parse(
            list(lex("int main(){int x=1; char y='a'; int *p=&x; char *q=&y; return p-q;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Subtraction operands must be arithmetic, pointer/integer, or compatible pointers",
        )

    def test_additive_void_pointer_subtraction_error(self) -> None:
        unit = parse(list(lex("int main(){void *p=0; void *q=0; return p-q;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Subtraction operands must be arithmetic, pointer/integer, or compatible pointers",
        )

    def test_additive_void_pointer_plus_integer_error(self) -> None:
        unit = parse(list(lex("int main(){void *p=0; return p+1==0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Addition operands must be arithmetic or pointer/integer",
        )

    def test_additive_function_pointer_plus_integer_error(self) -> None:
        source = "int f(void){return 0;} int main(){int (*fp)(void)=f; return fp+1==0;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Addition operands must be arithmetic or pointer/integer",
        )

    def test_relational_pointer_mismatch_error(self) -> None:
        unit = parse(
            list(lex("int main(){int x=1; char y='a'; int *p=&x; char *q=&y; return p<q;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Relational operator requires integer or compatible object pointer operands",
        )

    def test_relational_pointer_and_integer_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; return p<1;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Relational operator requires integer or compatible object pointer operands",
        )

    def test_relational_void_pointer_error(self) -> None:
        unit = parse(list(lex("int main(){void *p; void *q; return p<q;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Relational operator requires integer or compatible object pointer operands",
        )

    def test_relational_function_pointer_left_error(self) -> None:
        source = (
            "int f(void){return 0;} int main(){int (*fp)(void)=f; int x=1; int *p=&x; return fp<p;}"
        )
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Relational operator requires integer or compatible object pointer operands",
        )

    def test_relational_function_pointer_right_error(self) -> None:
        source = (
            "int f(void){return 0;} int main(){int (*fp)(void)=f; int x=1; int *p=&x; return p<fp;}"
        )
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Relational operator requires integer or compatible object pointer operands",
        )

    def test_equality_pointer_mismatch_error(self) -> None:
        unit = parse(
            list(lex("int main(){int x=1; char y='a'; int *p=&x; char *q=&y; return p==q;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Equality operator requires integer or compatible pointer operands",
        )

    def test_equality_nested_pointer_qualifier_mismatch_error(self) -> None:
        source = "int main(){int x=1; int *p=&x; int **pp=&p; const int **cpp=0; return pp==cpp;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Equality operator requires integer or compatible pointer operands",
        )

    def test_conditional_nested_pointer_qualifier_mismatch_error(self) -> None:
        source = "int main(){int x=1; int *p=&x; int **pp=&p; const int **cpp=0; return (1 ? pp : cpp)==0;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conditional type mismatch")

    def test_equality_void_pointer_and_function_pointer_error(self) -> None:
        source = "int f(void){return 0;} int main(){void *vp=0; int (*fp)(void)=f; return vp==fp;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Equality operator requires integer or compatible pointer operands",
        )

    def test_equality_pointer_and_integer_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; return p==1;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Equality operator requires integer or compatible pointer operands",
        )

    def test_equality_integer_and_pointer_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; return 1==p;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Equality operator requires integer or compatible pointer operands",
        )

    def test_equality_scalar_left_operand_error(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; } a; struct S b; return a==b;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Equality left operand must be scalar")

    def test_equality_scalar_right_operand_error(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; } s; return 1==s;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Equality right operand must be scalar")

    def test_logical_scalar_left_operand_error(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; } s; return s&&1;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Logical left operand must be scalar")

    def test_logical_scalar_right_operand_error(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; } s; return 1&&s;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Logical right operand must be scalar")

    def test_address_of_non_assignable_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; return &(x+1);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Address-of operand is not assignable")

    def test_unsupported_unary_operator_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([ExprStmt(UnaryExpr("?", IntLiteral(1)))]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Unsupported unary operator: ?")

    def test_manual_unary_expression_still_analyzes_supported_operator(self) -> None:
        expr = UnaryExpr("-", IntLiteral("1"))
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([ExprStmt(expr)]),
                )
            ]
        )
        sema = analyze(unit)
        self.assertEqual(sema.type_map.get(expr), INT)

    def test_invalid_integer_literal_expression_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([ExprStmt(IntLiteral("1uu"))]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid integer literal")

    def test_parse_int_literal_helper_rejects_invalid_forms(self) -> None:
        analyzer = Analyzer()
        self.assertIsNone(analyzer._parse_int_literal(None))
        self.assertIsNone(analyzer._parse_int_literal("1uu"))
        self.assertIsNone(analyzer._parse_int_literal("0xU"))
        self.assertIsNone(analyzer._parse_int_literal("08"))
        self.assertIsNone(analyzer._parse_int_literal("abc"))
        self.assertIsNone(analyzer._parse_int_literal("18446744073709551616ULL"))

    def test_record_member_normalization_helpers(self) -> None:
        analyzer = Analyzer()
        normalized = analyzer._normalize_record_members(
            (
                RecordMemberInfo("x", INT),
                ("y", LONG),
                ("z", SHORT, 16),
            )
        )
        self.assertEqual(
            normalized,
            (
                RecordMemberInfo("x", INT),
                RecordMemberInfo("y", LONG),
                RecordMemberInfo("z", SHORT, 16),
            ),
        )
        with self.assertRaises(TypeError):
            analyzer._normalize_record_members((("bad",),))

    def test_explicit_alignment_helper_rejects_non_power_of_two(self) -> None:
        analyzer = Analyzer()
        self.assertFalse(analyzer._is_valid_explicit_alignment(3, 4))

    def test_sizeof_type_helpers_cover_non_object_and_record_paths(self) -> None:
        analyzer = Analyzer()
        function_type = Type("int", declarator_ops=(("fn", (None, False)),))
        self.assertIsNone(analyzer._sizeof_type(function_type))
        self.assertIsNone(
            analyzer._sizeof_type(Type("int", declarator_ops=(("arr", 2), ("fn", (None, False)))))
        )
        self.assertIsNone(analyzer._sizeof_object_base_type(Type("_unknown"), None))
        self.assertIsNone(analyzer._sizeof_object_base_type(Type("struct Missing"), None))

        analyzer._record_definitions["struct S"] = (("x", INT), ("y", LONG))
        self.assertEqual(analyzer._sizeof_object_base_type(Type("struct S"), None), 12)
        self.assertEqual(analyzer._sizeof_object_base_type(Type("struct S"), 8), 9)

        analyzer._record_definitions["struct Bad"] = (("f", function_type),)
        self.assertIsNone(analyzer._sizeof_object_base_type(Type("struct Bad"), None))

        analyzer._record_definitions["union U"] = (("x", INT), ("y", LONG))
        self.assertEqual(analyzer._sizeof_object_base_type(Type("union U"), None), 8)
        self.assertEqual(analyzer._sizeof_object_base_type(Type("union U"), 4), 5)

        analyzer._record_definitions["union V"] = (("x", LONG), ("y", INT))
        self.assertEqual(analyzer._sizeof_object_base_type(Type("union V"), None), 8)

        analyzer._record_definitions["union Bad"] = (("f", function_type),)
        self.assertIsNone(analyzer._sizeof_object_base_type(Type("union Bad"), None))

    def test_alignof_type_helpers_cover_non_object_and_record_paths(self) -> None:
        analyzer = Analyzer()
        function_type = Type("int", declarator_ops=(("fn", (None, False)),))
        self.assertEqual(analyzer._alignof_type(Type("int", declarator_ops=(("ptr", 0),))), 8)
        self.assertIsNone(analyzer._alignof_type(function_type))
        self.assertEqual(
            analyzer._alignof_type(Type("int", declarator_ops=(("arr", 2), ("ptr", 0)))),
            8,
        )
        self.assertIsNone(analyzer._alignof_object_base_type(Type("_unknown")))
        self.assertIsNone(analyzer._alignof_object_base_type(Type("struct Missing")))
        analyzer._record_definitions["struct S"] = (("x", INT), ("y", LONG))
        self.assertEqual(analyzer._alignof_object_base_type(Type("struct S")), 8)
        analyzer._record_definitions["struct Small"] = (("x", INT), ("y", SHORT))
        self.assertEqual(analyzer._alignof_object_base_type(Type("struct Small")), 4)
        analyzer._record_definitions["struct Bad"] = (("f", function_type),)
        self.assertIsNone(analyzer._alignof_object_base_type(Type("struct Bad")))

    def test_initializer_member_lookup_helper_errors(self) -> None:
        analyzer = Analyzer()
        with self.assertRaises(SemaError) as ctx:
            analyzer._lookup_initializer_member(Type("int"), "x")
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")
        with self.assertRaises(SemaError) as ctx:
            analyzer._lookup_initializer_member(Type("struct Missing"), "x")
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")
        analyzer._record_definitions["struct S"] = (("x", INT),)
        self.assertEqual(analyzer._lookup_initializer_member(Type("struct S"), "x"), (INT, 0))

    def test_record_initializer_helper_rejects_empty_definition(self) -> None:
        analyzer = Analyzer()
        analyzer._record_definitions["struct Empty"] = ()
        with self.assertRaises(SemaError) as ctx:
            analyzer._analyze_record_initializer_list(
                Type("struct Empty"),
                InitList((InitItem((), IntLiteral("1")),)),
                Scope(),
            )
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_designated_initializer_helper_rejects_unknown_designator_kind(self) -> None:
        analyzer = Analyzer()
        with self.assertRaises(SemaError) as ctx:
            analyzer._analyze_designated_initializer(
                INT,
                (("other", "x"),),
                IntLiteral("1"),
                Scope(),
            )
        self.assertEqual(str(ctx.exception), "Initializer type mismatch")

    def test_eval_int_constant_expr_helpers_for_sizeof_alignof_and_generic(self) -> None:
        analyzer = Analyzer()
        scope = Scope()
        self.assertIsNone(
            analyzer._eval_int_constant_expr(SizeofExpr(Identifier("x"), None), scope)
        )
        self.assertEqual(
            analyzer._eval_int_constant_expr(SizeofExpr(None, TypeSpec("int")), scope), 4
        )
        self.assertIsNone(
            analyzer._eval_int_constant_expr(SizeofExpr(None, TypeSpec("void")), scope)
        )
        self.assertIsNone(
            analyzer._eval_int_constant_expr(AlignofExpr(Identifier("x"), None), scope)
        )
        self.assertEqual(
            analyzer._eval_int_constant_expr(AlignofExpr(None, TypeSpec("int", 1)), scope), 8
        )
        self.assertIsNone(
            analyzer._eval_int_constant_expr(AlignofExpr(None, TypeSpec("void")), scope)
        )
        generic = GenericExpr(IntLiteral("1"), ((TypeSpec("int"), IntLiteral("3")),))
        self.assertEqual(analyzer._eval_int_constant_expr(generic, scope), 3)
        generic_default = GenericExpr(
            IntLiteral("1u"),
            ((TypeSpec("int"), IntLiteral("3")), (None, IntLiteral("5"))),
        )
        self.assertEqual(analyzer._eval_int_constant_expr(generic_default, scope), 5)
        cached_control = IntLiteral("1")
        analyzer._type_map.set(cached_control, INT)
        generic_cached = GenericExpr(cached_control, ((TypeSpec("int"), IntLiteral("7")),))
        self.assertEqual(analyzer._eval_int_constant_expr(generic_cached, scope), 7)
        generic_no_match = GenericExpr(IntLiteral("1u"), ((TypeSpec("int"), IntLiteral("3")),))
        self.assertIsNone(analyzer._eval_int_constant_expr(generic_no_match, scope))

    def test_null_pointer_constant_helper_accepts_casted_void_zero(self) -> None:
        analyzer = Analyzer()
        scope = Scope()
        self.assertTrue(
            analyzer._is_null_pointer_constant(
                CastExpr(TypeSpec("void", 1), IntLiteral("0")), scope
            )
        )
        self.assertFalse(
            analyzer._is_null_pointer_constant(
                CastExpr(TypeSpec("void", 1), IntLiteral("1")), scope
            )
        )

    def test_duplicate_declaration(self) -> None:
        unit = parse(list(lex("int main(){int x; int x; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: x")

    def test_duplicate_declaration_in_multi_declarator(self) -> None:
        unit = parse(list(lex("int main(){int x=1, x=2; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: x")

    def test_typedef_then_object_duplicate_declaration(self) -> None:
        unit = parse(list(lex("int main(){typedef int T; int T; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: T")

    def test_object_then_typedef_duplicate_declaration(self) -> None:
        unit = parse(list(lex("int main(){int T; typedef int T; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: T")

    def test_duplicate_typedef_declaration(self) -> None:
        unit = parse(list(lex("int main(){typedef int T; typedef int T; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: T")

    def test_duplicate_enumerator_declaration(self) -> None:
        unit = parse(list(lex("int main(){enum E { A, A }; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: A")

    def test_if_condition_enum_members_visible_in_then_body(self) -> None:
        unit = parse(list(lex("int main(){if(sizeof(enum { A })) return A; return 0;}")))
        sema = analyze(unit)
        if_stmt = _body(unit.functions[0]).statements[0]
        assert isinstance(if_stmt, IfStmt)
        assert isinstance(if_stmt.then_body, ReturnStmt)
        assert if_stmt.then_body.value is not None
        self.assertEqual(sema.type_map.get(if_stmt.then_body.value), INT)

    def test_if_condition_enum_members_do_not_escape_if_scope(self) -> None:
        unit = parse(list(lex("int main(){if(sizeof(enum { A })) return A; return A;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Undeclared identifier: A")

    def test_if_condition_duplicate_enumerator_declaration(self) -> None:
        unit = parse(
            list(
                lex(
                    "int f(int z){if(z + sizeof(enum { A })) return 1 + sizeof(enum { A }); return 0;}"
                )
            )
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: A")

    def test_if_condition_enum_scope_shadows_outer_enum(self) -> None:
        source = (
            "enum { A, B };"
            "int main(){"
            'if(sizeof(enum { B, A }) != sizeof(int)){_Static_assert(A == 1, "");}'
            '_Static_assert(B == 1, "");'
            "return 0;}"
        )
        sema = analyze(parse(list(lex(source))))
        self.assertIn("main", sema.functions)

    def test_define_scoped_enum_members_ignores_repeated_binding(self) -> None:
        unit = parse(list(lex("int main(){sizeof(enum { A }); return 0;}")))
        expr_stmt = _body(unit.functions[0]).statements[0]
        assert isinstance(expr_stmt, ExprStmt)
        assert isinstance(expr_stmt.expr, SizeofExpr)
        assert expr_stmt.expr.type_spec is not None
        analyzer = Analyzer()
        scope = Scope()
        analyzer._define_scoped_enum_members(expr_stmt.expr.type_spec, scope)
        analyzer._define_scoped_enum_members(expr_stmt.expr.type_spec, scope)
        symbol = scope.lookup("A")
        self.assertIsNotNone(symbol)
        assert symbol is not None
        self.assertEqual(symbol.value, 0)

    def test_duplicate_struct_definition_error(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; }; struct S { int y; }; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate definition: struct S")

    def test_typedef_struct_reuse_no_duplicate_error(self) -> None:
        src = (
            "typedef struct _object { long ob_refcnt; } PyObject;"
            "PyObject *borrow(PyObject *o) { return o; }"
        )
        unit = parse(list(lex(src)))
        result = analyze(unit)
        self.assertIsNotNone(result)

    def test_incomplete_struct_object_error(self) -> None:
        unit = parse(list(lex("int main(){struct Node value; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for block-scope object declaration: incomplete",
        )

    def test_incomplete_union_object_error(self) -> None:
        unit = parse(list(lex("int main(){union Data value; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for block-scope object declaration: incomplete",
        )

    def test_empty_struct_gnu11_is_complete(self) -> None:
        source = "struct E {}; int main(){struct E e; return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        analyze(unit, std="gnu11")  # should not raise

    def test_empty_union_gnu11_is_complete(self) -> None:
        source = "union U {}; int main(){union U u; return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        analyze(unit, std="gnu11")  # should not raise

    def test_incomplete_anonymous_record_object_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([DeclStmt(TypeSpec("struct"), "value", None)]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for block-scope object declaration: incomplete",
        )

    def test_invalid_record_member_type_void_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(
                                TypeSpec(
                                    "struct",
                                    record_members=((TypeSpec("void"), "x"),),
                                ),
                                None,
                                None,
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for record member declaration: void",
        )

    def test_invalid_record_member_function_type_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(
                                TypeSpec(
                                    "struct",
                                    record_members=(
                                        (
                                            TypeSpec("int", declarator_ops=(("fn", ((), False)),)),
                                            "call",
                                        ),
                                    ),
                                ),
                                None,
                                None,
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for record member declaration: function",
        )

    def test_invalid_record_member_incomplete_type_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(
                                TypeSpec(
                                    "struct",
                                    record_members=(
                                        (TypeSpec("struct", record_tag="Node"), "next"),
                                    ),
                                ),
                                None,
                                None,
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for record member declaration: incomplete",
        )

    def test_void_function_return_value_error(self) -> None:
        unit = parse(list(lex("void main(){return 1;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Void function should not return a value")

    def test_non_void_return_without_value_error(self) -> None:
        unit = parse(list(lex("int main(){return;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Non-void function must return a value")

    def test_assignment_target_not_assignable(self) -> None:
        unit = parse(list(lex("int main(){(1+2)=3; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment target is not assignable")

    def test_update_target_not_assignable(self) -> None:
        unit = parse(list(lex("int main(){++(1+2); return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment target is not assignable")

    def test_update_type_mismatch(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; } s; ++s; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Update operand must be integer or pointer")

    def test_update_void_pointer_error(self) -> None:
        unit = parse(list(lex("int main(){void *p=0; ++p; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Update operand must be integer or pointer")

    def test_update_function_pointer_error(self) -> None:
        source = "int f(void){return 0;} int main(){int (*fp)(void)=f; ++fp; return 0;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Update operand must be integer or pointer")

    def test_update_array_target_not_assignable(self) -> None:
        unit = parse(list(lex("int main(){int a[2]; a++; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment target is not assignable")

    def test_assignment_to_enum_constant_is_rejected(self) -> None:
        unit = parse(list(lex("int main(){enum E { A=1 }; A=2; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment target is not assignable")

    def test_update_enum_constant_is_rejected(self) -> None:
        unit = parse(list(lex("int main(){enum E { A=1 }; ++A; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment target is not assignable")

    def test_duplicate_function_definition(self) -> None:
        unit = parse(list(lex("int main(){} int main(){}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate function definition: main")

    def test_invalid_object_type_void(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([DeclStmt(TypeSpec("void"), "x", None)]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Invalid object type for block-scope object declaration: void",
        )

    def test_invalid_parameter_type(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [Param(TypeSpec("void"), "x")],
                    CompoundStmt([]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid parameter type: void")

    def test_invalid_parameter_type_incomplete_record(self) -> None:
        unit = parse(list(lex("int f(struct Node x){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid parameter type: incomplete")

    def test_invalid_function_pointer_parameter_type_incomplete_record(self) -> None:
        unit = parse(list(lex("int main(){int (*fp)(struct Node); return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid parameter type: incomplete")

    def test_invalid_return_type_incomplete_record(self) -> None:
        unit = parse(list(lex("struct Node f(void){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid return type: incomplete")

    def test_invalid_return_type_incomplete_record_without_prototype(self) -> None:
        unit = parse(list(lex("struct Node f();")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid return type: incomplete")

    def test_pointer_parameter_to_incomplete_record_is_allowed(self) -> None:
        unit = parse(list(lex("int f(struct Node *x){return 0;}")))
        sema = analyze(unit)
        self.assertIn("f", sema.functions)

    def test_duplicate_record_member_name_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(
                                TypeSpec(
                                    "struct",
                                    record_members=((TypeSpec("int"), "x"), (TypeSpec("int"), "x")),
                                ),
                                None,
                                None,
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: x")

    def test_duplicate_hoisted_record_member_name_error(self) -> None:
        source = "struct S { int x; struct { int x; }; };"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: x")

    def test_invalid_function_declarator_parameter_type(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(
                                TypeSpec(
                                    "int",
                                    declarator_ops=(
                                        ("ptr", 0),
                                        ("fn", ((TypeSpec("void"),), False)),
                                    ),
                                ),
                                "fp",
                                None,
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid parameter type: void")

    def test_invalid_variadic_function_declarator_without_prototype(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(
                                TypeSpec(
                                    "int",
                                    declarator_ops=(("ptr", 0), ("fn", (None, True))),
                                ),
                                "fp",
                                None,
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Variadic function requires a prototype")

    def test_variadic_function_without_prototype_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([]),
                    has_prototype=False,
                    is_variadic=True,
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Variadic function requires a prototype")

    def test_for_void_condition_error(self) -> None:
        unit = parse(list(lex("void foo(){return;} int main(){for(;foo(););}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be non-void")

    def test_break_outside_loop_error(self) -> None:
        unit = parse(list(lex("int main(){break;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "break not in loop")

    def test_continue_outside_loop_error(self) -> None:
        unit = parse(list(lex("int main(){continue;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "continue not in loop")

    def test_case_outside_switch_error(self) -> None:
        unit = parse(list(lex("int main(){case 1:return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case not in switch")

    def test_default_outside_switch_error(self) -> None:
        unit = parse(list(lex("int main(){default:return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "default not in switch")

    def test_duplicate_case_value_error(self) -> None:
        unit = parse(list(lex("int main(){switch(1){case 1:return 0;case 1:return 1;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate case value")

    def test_duplicate_case_value_from_enumerator_error(self) -> None:
        unit = parse(
            list(
                lex("int main(){enum E { A=1, B=1 }; switch(1){case A:return 0;case B:return 1;}}")
            )
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate case value")

    def test_duplicate_default_label_error(self) -> None:
        unit = parse(list(lex("int main(){switch(1){default:return 0;default:return 1;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate default label")

    def test_non_integer_constant_case_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1;switch(x){case x:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_unary_non_constant_case_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1;switch(x){case -x:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_non_decimal_case_constant_ok(self) -> None:
        unit = parse(
            list(
                lex("int main(){switch(0){case 0x10:return 0;case 010:return 1;default:return 2;}}")
            )
        )
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_suffixed_case_constant_ok(self) -> None:
        unit = parse(
            list(
                lex(
                    "int main(){switch(0){case 0x10u:return 0;case 077ULL:return 1;default:return 2;}}"
                )
            )
        )
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_binary_case_constant_ok(self) -> None:
        source = (
            "int main(){switch(0){"
            "case 1+2: break;"
            "case 7-2: break;"
            "case 2*3: break;"
            "case 8/2: break;"
            "case 7%4+100: break;"
            "case 1<<4: break;"
            "case 32>>2: break;"
            "case 14&3: break;"
            "case 10^3: break;"
            "case 8|2: break;"
            "case !0: break;"
            "case ~0: break;"
            "case (1<2)+20: break;"
            "case (2<=2)+30: break;"
            "case (3>4)+40: break;"
            "case (4>=5)+50: break;"
            "case (6==6)+60: break;"
            "case (7!=7)+70: break;"
            "case (1&&2)+80: break;"
            "case (0||5)+90: break;"
            "case 1?11:12: break;"
            "case 0?13:14: break;"
            "default:return 0;"
            "}}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_binary_non_constant_case_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1;switch(0){case 1+x:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_division_by_zero_case_constant_error(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case 1/0:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_logical_and_short_circuit_case_constant_ok(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case 0&&1/0:return 0;default:return 1;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_logical_or_short_circuit_case_constant_ok(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case 1||1/0:return 0;default:return 1;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_logical_and_rhs_non_constant_case_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1;switch(0){case 1&&x:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_logical_or_rhs_non_constant_case_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1;switch(0){case 0||x:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_modulo_by_zero_case_constant_error(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case 1%0:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_negative_shift_case_constant_error(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case 1<<-1:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_negative_right_shift_case_constant_error(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case 8>>-1:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_comma_case_constant_error(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case (1,2):return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_relational_non_constant_case_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1;switch(0){case x<2:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_conditional_non_constant_case_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1;switch(0){case 1?x:2:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_conditional_short_circuit_case_constant_ok(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case 0?1/0:2:return 0;default:return 1;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_conditional_condition_non_constant_case_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1;switch(0){case x?1:2:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_cast_case_constant_ok(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case (int)'a':return 0;default:return 1;}}")))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_cast_non_constant_operand_case_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1;switch(0){case (int)x:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_cast_non_integer_target_case_error(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case (void)1:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_unsupported_binary_case_constant_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            SwitchStmt(
                                IntLiteral("0"),
                                CompoundStmt(
                                    [
                                        CaseStmt(
                                            BinaryExpr("?", IntLiteral("1"), IntLiteral("2")),
                                            ReturnStmt(IntLiteral("0")),
                                        )
                                    ]
                                ),
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

    def test_switch_void_condition_error(self) -> None:
        unit = parse(list(lex("void foo(){return;} int main(){switch(foo()){default:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be non-void")

    def test_switch_non_integer_condition_error(self) -> None:
        unit = parse(list(lex("int main(){float f=1.0f; switch(f){default:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Switch condition must be integer")

    def test_for_scope_does_not_leak(self) -> None:
        unit = parse(list(lex("int main(){for(int i=0;i<1;i=i+1) ; return i;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Undeclared identifier: i")

    def test_if_void_condition_error(self) -> None:
        unit = parse(list(lex("void foo(){return;} int main(){if(foo()) return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be non-void")

    def test_if_non_scalar_condition_error(self) -> None:
        unit = parse(
            list(lex("struct S{int x;}; int main(){struct S s={0}; if(s) return 0; return 1;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be scalar")

    def test_conditional_void_condition_error(self) -> None:
        unit = parse(list(lex("void foo(){return;} int main(){return foo() ? 1 : 2;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be non-void")

    def test_conditional_non_scalar_condition_error(self) -> None:
        unit = parse(list(lex("struct S{int x;}; int main(){struct S s={0}; return s ? 1 : 2;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be scalar")

    def test_static_assert_non_constant_condition_error(self) -> None:
        unit = parse(list(lex('int main(void){int x=1; _Static_assert(x, "bad"); return 0;}')))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Static assertion condition is not integer constant")

    def test_static_assert_false_condition_error(self) -> None:
        unit = parse(list(lex('_Static_assert(0, "broken"); int main(void){return 0;}')))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Static assertion failed: broken")

    def test_conditional_type_mismatch_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p; return x ? x : p;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conditional type mismatch")

    def test_conditional_pointer_mismatch_error(self) -> None:
        unit = parse(
            list(lex("int main(){int x=1; char y='a'; int *p=&x; char *q=&y; return 1 ? p : q;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conditional type mismatch")

    def test_conditional_void_pointer_and_function_pointer_error(self) -> None:
        source = (
            "int f(void){return 0;} int main(){void *vp=0; int (*fp)(void)=f; return 1 ? vp : fp;}"
        )
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conditional type mismatch")

    def test_while_void_condition_error(self) -> None:
        unit = parse(list(lex("void foo(){return;} int main(){while(foo()) return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be non-void")

    def test_while_non_scalar_condition_error(self) -> None:
        unit = parse(
            list(lex("struct S{int x;}; int main(){struct S s={0}; while(s){return 0;} return 1;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be scalar")

    def test_do_while_void_condition_error(self) -> None:
        unit = parse(list(lex("void foo(){return;} int main(){do return 0; while(foo());}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be non-void")

    def test_do_while_non_scalar_condition_error(self) -> None:
        unit = parse(
            list(
                lex(
                    "struct S{int x;}; int main(){struct S s={0}; do {return 0;} while(s); return 1;}"
                )
            )
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be scalar")

    def test_for_non_scalar_condition_error(self) -> None:
        unit = parse(
            list(lex("struct S{int x;}; int main(){struct S s={0}; for(;s;){return 0;} return 1;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be scalar")

    def test_undeclared_function_call(self) -> None:
        unit = parse(list(lex("int main(){return foo(1);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Undeclared function: foo")

    def test_call_target_not_function(self) -> None:
        unit = parse(list(lex("int main(){return 1(2);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Call target is not a function")

    def test_member_access_on_non_record_type_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; return x.y;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Member access on non-record type")

    def test_member_access_on_non_record_pointer_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; return p->y;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Member access on non-record pointer")

    def test_member_access_on_incomplete_type_error(self) -> None:
        unit = parse(list(lex("int main(){struct S *p; return p->x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Member access on incomplete type")

    def test_no_such_member_error(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; } s; return s.y;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "No such member: y")

    def test_union_member_access_typemap(self) -> None:
        unit = parse(list(lex("int main(){union U { int x; int y; } u; return u.y;}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_sizeof_void_type_error(self) -> None:
        unit = parse(list(lex("int main(){return sizeof(void);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand: void type")

    def test_sizeof_atomic_void_type_error(self) -> None:
        unit = parse(list(lex("int main(void){return sizeof(_Atomic(void));}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand: atomic type")

    def test_sizeof_incomplete_record_type_error(self) -> None:
        unit = parse(list(lex("int main(){return sizeof(struct S);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand: incomplete type")

    def test_sizeof_function_type_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                SizeofExpr(
                                    None,
                                    TypeSpec(
                                        "int", declarator_ops=(("fn", ((TypeSpec("int"),), False)),)
                                    ),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand: function type")

    def test_sizeof_function_designator_error(self) -> None:
        unit = parse(list(lex("int f(int x){return x;} int main(){return sizeof(f);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand: function type")

    def test_sizeof_void_expression_error(self) -> None:
        unit = parse(list(lex("void f(void){return;} int main(){return sizeof(f());}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand: void type")

    def test_sizeof_incomplete_record_expression_error(self) -> None:
        unit = parse(list(lex("int main(){struct S *p; return sizeof(*p);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand: incomplete type")

    def test_alignof_void_type_error(self) -> None:
        unit = parse(list(lex("int main(void){return _Alignof(void);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid alignof operand: void type")

    def test_alignof_function_designator_error(self) -> None:
        unit = parse(
            list(lex("int f(int x){return x;} int main(void){return _Alignof(f);}")),
            std="gnu11",
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertEqual(str(ctx.exception), "Invalid alignof operand: function type")

    def test_alignof_unknown_type_name_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([ReturnStmt(AlignofExpr(None, TypeSpec("_unknown")))]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid alignof operand: unknown or unsupported type")

    def test_alignof_unknown_expression_type_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            DeclStmt(TypeSpec("_unknown"), "x", None),
                            ReturnStmt(AlignofExpr(Identifier("x"), None)),
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertEqual(str(ctx.exception), "Invalid alignof operand: unknown or unsupported type")

    def test_cast_void_expression_to_int_error(self) -> None:
        unit = parse(list(lex("void f(void){return;} int main(){return (int)f();}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Cast operand is not castable to target type")

    def test_cast_struct_target_error(self) -> None:
        source = "int main(){struct S { int x; } s; return (struct S)s;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Cast target type is not castable")

    def test_cast_incomplete_record_target_error(self) -> None:
        unit = parse(list(lex("int main(){int x; return (struct S)x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Cast target type is not castable")

    def test_cast_array_target_error(self) -> None:
        unit = parse(list(lex("int main(){int x; return (int[2])x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Cast target type is not castable")

    def test_cast_function_type_target_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt(
                        [
                            ReturnStmt(
                                CastExpr(
                                    TypeSpec(
                                        "int", declarator_ops=(("fn", ((TypeSpec("int"),), False)),)
                                    ),
                                    IntLiteral("1"),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Cast target type is not castable")

    def test_unsupported_expression(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([ExprStmt(Expr())]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Unsupported expression node: Expr (internal sema bug: unexpected AST expression node)",
        )

    def test_supported_expression_does_not_hit_fallback(self) -> None:
        expr = IntLiteral("1")
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([ExprStmt(expr)]),
                )
            ]
        )
        sema = analyze(unit)
        self.assertEqual(sema.type_map.get(expr), INT)

    def test_unsupported_binary_expression_error(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([ExprStmt(BinaryExpr("?", IntLiteral("1"), IntLiteral("2")))]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Unsupported binary operator: ?")

    def test_manual_binary_expression_still_analyzes_supported_operator(self) -> None:
        expr = BinaryExpr("+", IntLiteral("1"), IntLiteral("2"))
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([ExprStmt(expr)]),
                )
            ]
        )
        sema = analyze(unit)
        self.assertEqual(sema.type_map.get(expr), INT)

    def test_unsupported_statement_node(self) -> None:
        unit = TranslationUnit(
            [
                FunctionDef(
                    TypeSpec("int"),
                    "main",
                    [],
                    CompoundStmt([Stmt()]),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(
            str(ctx.exception),
            "Unsupported statement node: Stmt (internal sema bug: unexpected AST statement node)",
        )

    def test_missing_file_scope_identifier_message_without_qualifiers(self) -> None:
        analyzer = Analyzer()
        message = analyzer._missing_object_identifier_message(
            "file-scope",
            DeclStmt(TypeSpec("int"), None, None),
        )
        self.assertEqual(message, "Expected identifier for file-scope object declaration")

    def test_invalid_alignment_message_helper_paths(self) -> None:
        analyzer = Analyzer()
        self.assertEqual(
            analyzer._invalid_alignment_message(
                "file-scope object declaration", 0, natural_alignment=4
            ),
            "Invalid alignment specifier for file-scope object declaration: alignment must be positive",
        )
        self.assertEqual(
            analyzer._invalid_alignment_message(
                "file-scope object declaration", 8, natural_alignment=None
            ),
            "Invalid alignment specifier for file-scope object declaration: cannot determine natural alignment",
        )

    def test_sizeof_alignof_and_generic_invalid_type_helpers(self) -> None:
        analyzer = Analyzer()
        self.assertTrue(analyzer._is_invalid_sizeof_type(VOID))
        self.assertTrue(analyzer._is_invalid_alignof_type(VOID))
        self.assertTrue(analyzer._is_invalid_generic_association_type_spec(TypeSpec("void")))

    def test_generic_association_location_fallback_mixed_partial_coordinates(self) -> None:
        analyzer = Analyzer()
        scope = Scope()
        expr = GenericExpr(
            IntLiteral("1"),
            (
                (TypeSpec("long", source_line=10, source_column=None), IntLiteral("2")),
                (TypeSpec("char", source_line=None, source_column=11), IntLiteral("3")),
            ),
            association_source_locations=((100, 20), (200, 30)),
        )
        with self.assertRaises(SemaError) as ctx:
            analyzer._analyze_expr(expr, scope)
        self.assertIn("No matching generic association for control type", str(ctx.exception))

    def test_generic_expr_without_associations_reports_plain_no_match_error(self) -> None:
        analyzer = Analyzer()
        with self.assertRaises(SemaError) as ctx:
            analyzer._analyze_expr(GenericExpr(IntLiteral("1"), ()), Scope())
        self.assertEqual(
            str(ctx.exception), "No matching generic association for control type 'int'"
        )

    def test_typeof_expression_resolves_variable_type(self) -> None:
        unit = parse(list(lex("int f(int x) { typeof(x) y = x + 3; return y; }")), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_typeof_dunder_expression_resolves_variable_type(self) -> None:
        unit = parse(
            list(lex("int f(long x) { __typeof__(x) y = x + 4; return (int)y; }")), std="gnu11"
        )
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_typeof_unqual_expression_resolves_variable_type(self) -> None:
        unit = parse(
            list(lex("int f(int x) { typeof_unqual(x) y = x + 5; return y; }")), std="gnu11"
        )
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_typeof_type_name_resolves(self) -> None:
        unit = parse(list(lex("int f(void) { typeof(int) y = 42; return y; }")), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_typeof_with_pointer(self) -> None:
        unit = parse(list(lex("int f(int *p) { typeof(p) q = p; return *q; }")), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_typeof_declarator_ops_pointer(self) -> None:
        unit = parse(list(lex("int f(int x) { typeof(x) *p = &x; return *p; }")), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_typeof_declarator_ops_array(self) -> None:
        unit = parse(
            list(lex("int f(void) { int x; typeof(x) a[3]; a[0] = 1; return a[0]; }")), std="gnu11"
        )
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_typeof_declarator_ops_pointer_and_array(self) -> None:
        """Cover the loop-back branch in typeof declarator_ops."""
        unit = parse(list(lex("void f(int x) { typeof(x) a[2][3]; (void)a; }")), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)
        self.assertIsNotNone(sema)

    def test_builtin_offsetof_returns_ulong(self) -> None:
        unit = parse(
            list(
                lex(
                    "struct S { int a; long b; }; unsigned long f(void) { return __builtin_offsetof(struct S, b); }"
                )
            ),
            std="gnu11",
        )
        sema = analyze(unit, std="gnu11")
        ret = _body(unit.functions[0]).statements[0].value
        assert ret is not None
        self.assertEqual(sema.type_map.get(ret), ULONG)

    def test_builtin_offsetof_nested_member_returns_ulong(self) -> None:
        unit = parse(
            list(
                lex(
                    "struct I { int leaf; }; struct O { int tag; struct I in; }; unsigned long f(void) { return __builtin_offsetof(struct O, in.leaf); }"
                )
            ),
            std="gnu11",
        )
        sema = analyze(unit, std="gnu11")
        ret = _body(unit.functions[0]).statements[0].value
        assert ret is not None
        self.assertEqual(sema.type_map.get(ret), ULONG)

    def test_builtin_offsetof_in_constant_expr_context(self) -> None:
        """offsetof in array size triggers _eval_int_constant_expr path (returns None → VLA)."""
        unit = parse(
            list(
                lex(
                    "struct S { int a; long b; }; void f(void) { int arr[__builtin_offsetof(struct S, b)]; (void)arr; }"
                )
            ),
            std="gnu11",
        )
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_builtin_types_compatible_p_returns_int(self) -> None:
        source = "int f(void) { return __builtin_types_compatible_p(int, int); }"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_builtin_expect_accepted_in_gnu11(self) -> None:
        source = "int f(int x) { if (__builtin_expect(x == 0, 0)) return -1; return x; }"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_builtin_expect_accepted_in_c11(self) -> None:
        source = "int f(int x) { if (__builtin_expect(x == 0, 0)) return -1; return x; }"
        unit = parse(list(lex(source)), std="c11")
        sema = analyze(unit, std="c11")
        self.assertIsNotNone(sema)

    def test_builtin_unreachable_accepted_in_gnu11(self) -> None:
        source = (
            "int f(int x) { switch(x) { case 0: return 0; default: __builtin_unreachable(); } }"
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_builtin_unreachable_accepted_in_c11(self) -> None:
        source = (
            "int f(int x) { switch(x) { case 0: return 0; default: __builtin_unreachable(); } }"
        )
        unit = parse(list(lex(source)), std="c11")
        sema = analyze(unit, std="c11")
        self.assertIsNotNone(sema)

    def test_builtin_float_compare_family_accepted_in_c11(self) -> None:
        for builtin in (
            "__builtin_isgreater",
            "__builtin_isgreaterequal",
            "__builtin_isless",
            "__builtin_islessequal",
            "__builtin_islessgreater",
            "__builtin_isunordered",
        ):
            with self.subTest(builtin=builtin):
                source = f"int f(double x, long double y) {{ return {builtin}(x, y); }}"
                unit = parse(list(lex(source)), std="c11")
                sema = analyze(unit, std="c11")
                self.assertIsNotNone(sema)

    def test_const_qualified_type_is_detected(self) -> None:
        """is_const_qualified returns True for const-qualified type."""
        source = "const int x = 5; void f(void) { int y = x; }"
        unit = parse(list(lex(source)), std="c11")
        sema = analyze(unit, std="c11")
        self.assertIsNotNone(sema)

    def test_init_list_single_scalar_item_evaluated(self) -> None:
        """InitList with single non-designated item is unwrapped for scalar eval."""
        source = "const int x = {42};"
        unit = parse(list(lex(source)), std="c11")
        sema = analyze(unit, std="c11")
        self.assertIsNotNone(sema)

    def test_scalar_init_for_record_with_first_member(self) -> None:
        """Scalar initializer for struct initializes first member."""
        source = "struct S { int a; char b; }; struct S s = 5;"
        unit = parse(list(lex(source)), std="c11")
        sema = analyze(unit, std="c11")
        self.assertIsNotNone(sema)

    def test_scalar_init_for_array_sets_all_elements(self) -> None:
        """Scalar initializer for array initializes element type."""
        source = "int arr[3] = 5;"
        unit = parse(list(lex(source)), std="c11")
        sema = analyze(unit, std="c11")
        self.assertIsNotNone(sema)

    def test_const_target_non_const_init_qualifier_mismatch(self) -> None:
        """const target with non-const initializer is accepted (6.7.9p11)."""
        source = "const int x = 5;"
        unit = parse(list(lex(source)), std="c11")
        sema = analyze(unit, std="c11")
        self.assertIsNotNone(sema)

    def test_generic_return_builtin_detected(self) -> None:
        """Generic builtin (params=None) is detected in stmt analysis."""
        source = "int f(void) { __builtin_bswap32(42); return 0; }"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_generic_builtin_allows_return_type_mismatch(self) -> None:
        """Generic builtin allows mismatched return type."""
        source = "char *f(void) { return __builtin_bswap32(42); }"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_init_list_stored_as_init_expr(self) -> None:
        """InitList expression is stored on the VarSymbol for later reference."""
        source = "int arr[] = {1, 2, 3};"
        unit = parse(list(lex(source)), std="c11")
        sema = analyze(unit, std="c11")
        self.assertIsNotNone(sema)

    def test_static_assert_with_const_variable_ref(self) -> None:
        """Static assert can fold const variable references."""
        source = "const int x = 5; _Static_assert(x == 5, \"bad\");"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_static_assert_with_array_subscript_const(self) -> None:
        """Static assert can fold array subscript with const init."""
        source = (
            "const int arr[] = {10, 20, 30};\n"
            '_Static_assert(arr[1] == 20, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_static_assert_with_struct_member_const(self) -> None:
        """Static assert can fold struct member access with const init."""
        source = (
            "struct S { int a; int b; };\n"
            "const struct S s = {1, 2};\n"
            '_Static_assert(s.a == 1, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_sizeof_expr_operand_in_constant_expr(self) -> None:
        """sizeof(expr) in constant expression context."""
        source = "int x; _Static_assert(sizeof(x) == 4, \"bad\");"
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_static_assert_with_non_const_condition_fails(self) -> None:
        """Static assert with non-constant condition raises error."""
        source = 'int x = 5; _Static_assert(x == 5, "bad");'
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not integer constant", str(ctx.exception))

    def test_static_assert_failure_raises_error(self) -> None:
        """Static assert with false condition raises SemaError."""
        source = '_Static_assert(0, "fail");'
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("fail", str(ctx.exception))

    def test_const_array_subscript_as_vla_size(self) -> None:
        """Const array subscript without const folding becomes VLA."""
        source = (
            "const int arr[3] = {10, 20, 30};\n"
            "void f(void) {\n"
            "    int x[arr[1]];\n"
            "    (void)x;\n"
            "}\n"
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_static_assert_designated_init_subscript_returns_none(self) -> None:
        """Static assert with designated init subscript can't evaluate."""
        source = (
            "const int arr[3] = {[0] = 1};\n"
            '_Static_assert(arr[0] == 1, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not integer constant", str(ctx.exception))

    def test_static_assert_non_const_struct_member(self) -> None:
        """Static assert with non-const struct member access fails."""
        source = (
            "struct S { int a; };\n"
            "struct S s = {5};\n"
            '_Static_assert(s.a == 5, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not integer constant", str(ctx.exception))

    def test_static_assert_extern_const_no_init(self) -> None:
        """Static assert with extern const (no const value) fails."""
        source = 'extern const int x; _Static_assert(x == 5, "bad");'
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not integer constant", str(ctx.exception))

    def test_static_assert_subscript_non_const_index(self) -> None:
        """Static assert with non-constant index fails."""
        source = (
            "int idx = 0;\n"
            "const int arr[] = {1, 2, 3};\n"
            '_Static_assert(arr[idx] == 1, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not integer constant", str(ctx.exception))

    def test_static_assert_nested_init_list_subscript(self) -> None:
        """Static assert with nested init list subscript can't evaluate."""
        source = (
            "const int arr[2][2] = {{1, 2}, {3, 4}};\n"
            '_Static_assert(arr[0][0] == 1, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not integer constant", str(ctx.exception))

    def test_return_value_type_mismatch_non_builtin(self) -> None:
        """Return value incompatible with function return type raises error."""
        source = "char *f(void) { return 5; }"
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not compatible", str(ctx.exception))

    def test_const_var_as_vla_size_no_folding(self) -> None:
        """Const var used as array size without const folding flag."""
        source = (
            "const int n = 10;\n"
            "void f(void) {\n"
            "    int x[n];\n"
            "    (void)x;\n"
            "}\n"
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_static_assert_non_const_struct_member_fails(self) -> None:
        """Static assert with non-const struct member access fails."""
        source = (
            "struct S { int a; };\n"
            "struct S s = {5};\n"
            '_Static_assert(s.a == 5, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not integer constant", str(ctx.exception))

    def test_static_assert_subscript_non_const_base_fails(self) -> None:
        """Static assert subscript on non-const array base can't evaluate."""
        source = (
            "int arr[3] = {1, 2, 3};\n"
            '_Static_assert(arr[0] == 1, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not integer constant", str(ctx.exception))

    def test_embed_produces_excess_init_tolerance_for_array(self) -> None:
        """#embed with excess elements tolerated for array initializer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02\x03\x04\x05")
            source = (
                "int arr[3] = {\n"
                '#embed "data.bin"\n'
                "};\n"
            )
            result = compile_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIsNotNone(result)

    def test_embed_produces_excess_init_tolerance_for_struct(self) -> None:
        """#embed with excess elements tolerated for struct initializer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.bin").write_bytes(b"\x01\x02\x03\x04\x05")
            source = (
                "struct S { int a; int b; };\n"
                "struct S s = {\n"
                '#embed "data.bin"\n'
                "};\n"
            )
            result = compile_source(
                source,
                filename=str(root / "test.c"),
                options=FrontendOptions(std="gnu11", embed_dirs=(tmp,)),
            )
            self.assertIsNotNone(result)

    def test_struct_member_as_vla_size_no_folding(self) -> None:
        """Struct member access without const folding flag."""
        source = (
            "struct S { int a; };\n"
            "const struct S s = {10};\n"
            "void f(void) {\n"
            "    int x[s.a];\n"
            "    (void)x;\n"
            "}\n"
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_const_struct_member_in_static_assert(self) -> None:
        """Const struct member access evaluated in static_assert."""
        source = (
            "struct S { int a; int b; };\n"
            "const struct S s = {5, 10};\n"
            '_Static_assert(s.b == 10, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_forward_declared_record_member_init(self) -> None:
        """Forward-declared struct with no members triggers empty members path."""
        source = (
            "struct S;\n"
            "struct S { int a; };\n"
            "struct S s = {5};\n"
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_extern_identifier_sizeof_in_static_assert(self) -> None:
        """sizeof(extern_var) in static_assert with type not in map."""
        source = (
            "extern int x;\n"
            '_Static_assert(sizeof(x) == sizeof(int), "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_two_dimensional_array_subscript_static_assert(self) -> None:
        """2D array subscript in static_assert hits nested init list path."""
        source = (
            "const int arr[2][2] = {{1, 2}, {3, 4}};\n"
            '_Static_assert(arr[0][0] == 1, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not integer constant", str(ctx.exception))

    def test_sizeof_expr_global_array_size_vla_error(self) -> None:
        """sizeof(expr) as global array size without type in map — VLA error."""
        source = "int x; int arr[sizeof(x)];"
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("Variable length array", str(ctx.exception))

    def test_subscript_on_non_identifier_base_static_assert(self) -> None:
        """SubscriptExpr base not an Identifier can't be constant-evaluated."""
        source = (
            "const int arr[3] = {1, 2, 3};\n"
            "int *p = (int *)arr;\n"
            '_Static_assert(p[0] == 1, "bad");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        with self.assertRaises(SemaError) as ctx:
            analyze(unit, std="gnu11")
        self.assertIn("not integer constant", str(ctx.exception))

    def test_eval_int_constant_sizeof_expr_both_none(self) -> None:
        """_eval_int_constant_expr SizeofExpr with both type and expr None."""
        from xcc.ast import SizeofExpr

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)
        result = analyzer._eval_int_constant_expr(
            SizeofExpr(type_spec=None, expr=None),
            analyzer._file_scope,
        )
        self.assertIsNone(result)

    def test_eval_int_constant_subscript_non_identifier_base(self) -> None:
        """_eval_int_constant_expr SubscriptExpr base not Identifier returns None."""
        from xcc.ast import Identifier, IntLiteral, MemberExpr, SubscriptExpr

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)
        analyzer._allow_const_var_folding = True
        try:
            result = analyzer._eval_int_constant_expr(
                SubscriptExpr(
                    base=MemberExpr(base=Identifier("x"), member="a", through_pointer=False),
                    index=IntLiteral("0"),
                ),
                analyzer._file_scope,
            )
            self.assertIsNone(result)
        finally:
            analyzer._allow_const_var_folding = False

    def test_eval_int_constant_member_expr_non_identifier_base(self) -> None:
        """_eval_member_expr with non-Identifier base returns None."""
        from xcc.ast import Identifier, IntLiteral, MemberExpr, SubscriptExpr

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)
        analyzer._allow_const_var_folding = True
        try:
            result = analyzer._eval_int_constant_expr(
                MemberExpr(
                    base=SubscriptExpr(
                        base=Identifier("x"),
                        index=IntLiteral("0"),
                    ),
                    member="a",
                    through_pointer=False,
                ),
                analyzer._file_scope,
            )
            self.assertIsNone(result)
        finally:
            analyzer._allow_const_var_folding = False

    def test_eval_member_expr_base_not_identifier(self) -> None:
        """_eval_member_expr where base is not Identifier and not scalar."""
        from xcc.ast import Identifier, IntLiteral, MemberExpr, SubscriptExpr

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)
        analyzer._allow_const_var_folding = True
        try:
            result = analyzer._eval_int_constant_expr(
                MemberExpr(
                    base=MemberExpr(base=Identifier("x"), member="a", through_pointer=False),
                    member="b",
                    through_pointer=False,
                ),
                analyzer._file_scope,
            )
            self.assertIsNone(result)
        finally:
            analyzer._allow_const_var_folding = False

    def test_analyze_initializer_array_element_type_none(self) -> None:
        """analyze_initializer with pointer type raises type mismatch."""
        from xcc.ast import IntLiteral
        from xcc.types import Type

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)
        ptr_type = Type("int", declarator_ops=(("ptr", 0),))
        with self.assertRaises(SemaError):
            sema_initializers.analyze_initializer(
                analyzer,
                ptr_type,
                IntLiteral("5"),
                analyzer._file_scope,
            )

    def test_lookup_member_in_init_non_record_type(self) -> None:
        """_lookup_member_in_init with non-record type name returns None."""
        from xcc.ast import InitItem, InitList, IntLiteral
        from xcc.types import INT

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)

        init_list = InitList(
            items=(InitItem(designators=(), initializer=IntLiteral("5")),)
        )
        result = sema_constants._lookup_member_in_init(
            analyzer,
            init_list,
            INT,
            "a",
            analyzer._file_scope,
        )
        self.assertIsNone(result)

    def test_lookup_member_in_init_no_members(self) -> None:
        """_lookup_member_in_init where _record_members returns None."""
        from xcc.ast import InitItem, InitList, IntLiteral

        # Forward-declared struct is a record name with no members
        source = "struct S;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)

        struct_type = analyzer._resolve_type(unit.declarations[0].type_spec)
        init_list = InitList(
            items=(InitItem(designators=(), initializer=IntLiteral("5")),)
        )
        result = sema_constants._lookup_member_in_init(
            analyzer,
            init_list,
            struct_type,
            "a",
            analyzer._file_scope,
        )
        self.assertIsNone(result)

    def test_lookup_member_in_init_designated_item(self) -> None:
        """_lookup_member_in_init with designated item returns None."""
        from xcc.ast import InitItem, InitList, IntLiteral

        source = (
            "struct S { int a; int b; };\n"
            "const struct S s = {5, 10};\n"
        )
        unit = parse(list(lex(source)), std="gnu11")
        analyzer = Analyzer(std="gnu11")
        analyzer.analyze(unit)

        init_list = InitList(
            items=(
                InitItem(
                    designators=(("[", IntLiteral("0")),),
                    initializer=IntLiteral("5"),
                ),
            )
        )
        result = sema_constants._lookup_member_in_init(
            analyzer,
            init_list,
            analyzer._resolve_type(unit.declarations[0].type_spec),
            "a",
            analyzer._file_scope,
        )
        self.assertIsNone(result)

    def test_qualifier_only_mismatch_is_initializer_compatible(self) -> None:
        """is_initializer_compatible returns True for qualifier-only diff."""
        from xcc.ast import IntLiteral
        from xcc.types import INT, Type
        from xcc.sema.symbols import Scope

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)

        const_int = Type("int", qualifiers=("const",))
        result = sema_initializers.is_initializer_compatible(
            analyzer,
            const_int,  # target: const int
            IntLiteral("5"),  # init expression
            INT,  # init type: int (non-const)
            analyzer._file_scope,
        )
        self.assertTrue(result)

    def test_analyze_initializer_empty_record_members(self) -> None:
        """analyze_initializer with record type having no members raises error."""
        from xcc.ast import IntLiteral

        source = "struct S;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)

        struct_type = analyzer._resolve_type(unit.declarations[0].type_spec)
        with self.assertRaises(SemaError):
            sema_initializers.analyze_initializer(
                analyzer,
                struct_type,
                IntLiteral("5"),
                analyzer._file_scope,
            )

    def test_lookup_member_in_init_member_index_out_of_range(self) -> None:
        """_lookup_member_in_init member found but init list too short."""
        from xcc.ast import InitItem, InitList, IntLiteral

        source = "struct S { int a; int b; };"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)

        struct_type = analyzer._resolve_type(unit.declarations[0].type_spec)
        init_list = InitList(
            items=(InitItem(designators=(), initializer=IntLiteral("5")),)
        )
        result = sema_constants._lookup_member_in_init(
            analyzer,
            init_list,
            struct_type,
            "b",
            analyzer._file_scope,
        )
        self.assertIsNone(result)

    def test_lookup_member_in_init_member_not_found(self) -> None:
        """_lookup_member_in_init with non-existent member name returns None."""
        from xcc.ast import InitItem, InitList, IntLiteral

        source = "struct S { int a; };"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)

        struct_type = analyzer._resolve_type(unit.declarations[0].type_spec)
        init_list = InitList(
            items=(InitItem(designators=(), initializer=IntLiteral("5")),)
        )
        result = sema_constants._lookup_member_in_init(
            analyzer,
            init_list,
            struct_type,
            "nonexistent",
            analyzer._file_scope,
        )
        self.assertIsNone(result)

    def test_subscript_non_identifier_base_with_folding(self) -> None:
        """SubscriptExpr base not Identifier returns None (branch 177→189)."""
        from xcc.ast import Identifier, IntLiteral, MemberExpr, SubscriptExpr

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)
        analyzer._allow_const_var_folding = True
        try:
            result = analyzer._eval_int_constant_expr(
                SubscriptExpr(
                    base=MemberExpr(
                        base=Identifier("x"), member="a", through_pointer=False
                    ),
                    index=IntLiteral("0"),
                ),
                analyzer._file_scope,
            )
            self.assertIsNone(result)
        finally:
            analyzer._allow_const_var_folding = False

    def test_subscript_nested_init_list_item_returns_none(self) -> None:
        """Subscript into array where init item is itself InitList → None."""
        from xcc.ast import Identifier, InitItem, InitList, IntLiteral, SubscriptExpr
        from xcc.sema.symbols import VarSymbol
        from xcc.types import INT

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)
        nested_list = InitList(
            items=(
                InitItem(
                    designators=(),
                    initializer=InitList(
                        items=(InitItem(designators=(), initializer=IntLiteral("1")),)
                    ),
                ),
            )
        )
        analyzer._file_scope.define(
            VarSymbol(name="arr2d", type_=INT, _init_expr=nested_list)
        )
        analyzer._allow_const_var_folding = True
        try:
            result = analyzer._eval_int_constant_expr(
                SubscriptExpr(
                    base=Identifier("arr2d"),
                    index=IntLiteral("0"),
                ),
                analyzer._file_scope,
            )
            self.assertIsNone(result)
        finally:
            analyzer._allow_const_var_folding = False

    def test_member_expr_base_evaluates_to_scalar(self) -> None:
        """MemberExpr where base _eval_int_constant_expr returns scalar."""
        from xcc.ast import Identifier, IntLiteral, MemberExpr

        source = (
            "struct S { int a; };\n"
            "const struct S s = {42};\n"
            '_Static_assert(s.a == 42, "ok");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        analyzer = Analyzer(std="gnu11")
        analyzer.analyze(unit)
        analyzer._allow_const_var_folding = True
        try:
            result = analyzer._eval_int_constant_expr(
                MemberExpr(
                    base=Identifier("s"), member="a", through_pointer=False
                ),
                analyzer._file_scope,
            )
            self.assertEqual(result, 42)
        finally:
            analyzer._allow_const_var_folding = False

    def test_member_expr_base_scalar_returns_base_val(self) -> None:
        """_eval_member_expr returns base_val when base evaluates to scalar."""
        from xcc.ast import Identifier, IntLiteral, MemberExpr

        source = "const int x = 5;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)
        analyzer._allow_const_var_folding = True
        try:
            result = analyzer._eval_int_constant_expr(
                MemberExpr(
                    base=Identifier("x"), member="a", through_pointer=False
                ),
                analyzer._file_scope,
            )
            # base evaluates to 5 (scalar), returned directly
            self.assertEqual(result, 5)
        finally:
            analyzer._allow_const_var_folding = False

    def test_const_struct_init_from_non_const_function(self) -> None:
        """Qualifier-only mismatch: const struct from non-const function return."""
        source = (
            "struct S { int a; };\n"
            "struct S get_s(void);\n"
            "const struct S cs = get_s();\n"
        )
        unit = parse(list(lex(source)), std="gnu11")
        sema = analyze(unit, std="gnu11")
        self.assertIsNotNone(sema)

    def test_subscript_index_out_of_range_skips_to_next_check(self) -> None:
        """Subscript with index >= len(init_list.items) → branch 181→189."""
        from xcc.ast import Identifier, IntLiteral, SubscriptExpr

        source = (
            "const int arr[3] = {1, 2, 3};\n"
            '_Static_assert(arr[0] == 1, "ok");'
        )
        unit = parse(list(lex(source)), std="gnu11")
        analyzer = Analyzer(std="gnu11")
        analyzer.analyze(unit)
        analyzer._allow_const_var_folding = True
        try:
            # arr[99] where arr has only 3 items → index out of range
            result = analyzer._eval_int_constant_expr(
                SubscriptExpr(
                    base=Identifier("arr"),
                    index=IntLiteral("99"),
                ),
                analyzer._file_scope,
            )
            self.assertIsNone(result)
        finally:
            analyzer._allow_const_var_folding = False

    def test_member_expr_non_const_base_init_expr_not_init_list(self) -> None:
        """MemberExpr base is non-const Identifier, _init_expr not InitList."""
        from xcc.ast import Identifier, IntLiteral, MemberExpr
        from xcc.sema.symbols import VarSymbol
        from xcc.types import INT

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)
        # Manually define symbol with _init_expr = IntLiteral (not InitList)
        analyzer._file_scope.define(
            VarSymbol(name="y", type_=INT, _init_expr=IntLiteral("10"))
        )
        analyzer._allow_const_var_folding = True
        try:
            result = analyzer._eval_int_constant_expr(
                MemberExpr(
                    base=Identifier("y"), member="a", through_pointer=False
                ),
                analyzer._file_scope,
            )
            self.assertIsNone(result)
        finally:
            analyzer._allow_const_var_folding = False

    def test_array_element_type_none_raises_mismatch(self) -> None:
        """Dead branch 49->52: element_type() returns None for array type."""
        from unittest.mock import patch

        from xcc.ast import IntLiteral
        from xcc.types import INT, Type

        source = "int x;"
        unit = parse(list(lex(source)), std="c11")
        analyzer = Analyzer(std="c11")
        analyzer.analyze(unit)

        arr_type = Type("int", declarator_ops=(("arr", 10),))
        self.assertTrue(arr_type.is_array())

        with patch.object(Type, "element_type", return_value=None):
            with self.assertRaises(SemaError):
                sema_initializers.analyze_initializer(
                    analyzer,
                    arr_type,
                    IntLiteral("5"),
                    analyzer._file_scope,
                )


if __name__ == "__main__":
    unittest.main()
