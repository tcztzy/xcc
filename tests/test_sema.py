import unittest

from tests import _bootstrap  # noqa: F401
from xcc.ast import (
    BinaryExpr,
    CallExpr,
    CaseStmt,
    CastExpr,
    CommaExpr,
    CompoundStmt,
    ConditionalExpr,
    DeclStmt,
    Expr,
    ExprStmt,
    FunctionDef,
    IntLiteral,
    Param,
    ReturnStmt,
    SizeofExpr,
    Stmt,
    SwitchStmt,
    TranslationUnit,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
)
from xcc.lexer import lex
from xcc.parser import parse
from xcc.sema import Scope, SemaError, analyze
from xcc.types import CHAR, INT, Type


def _body(func):
    assert func.body is not None
    return func.body


class SemaTests(unittest.TestCase):
    def test_type_str(self) -> None:
        self.assertEqual(str(INT), "int")
        self.assertEqual(str(CHAR), "char")
        array = Type("int").array_of(4)
        self.assertEqual(str(array), "int[4]")
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

    def test_integer_type_conversions_in_initializer_and_assignment(self) -> None:
        source = "int main(){char c=1; int x=c; char d=x; x=d; return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        func_symbol = sema.functions["main"]
        self.assertIs(func_symbol.locals["c"].type_, CHAR)
        self.assertIs(func_symbol.locals["x"].type_, INT)
        self.assertIs(func_symbol.locals["d"].type_, CHAR)

    def test_char_parameter_accepts_int_argument(self) -> None:
        source = "char id(char x){return x;} int main(){return id(1);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

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
        self.assertEqual(func_symbol.locals["fn"].type_, Type("int", declarator_ops=(("ptr", 0), ("fn", ((INT,), False)))))

    def test_function_pointer_call_typemap(self) -> None:
        source = "int inc(int x){return x;} int main(){int (*fp)(int)=inc; return fp(1);}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        return_expr = _body(unit.functions[1]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

    def test_function_pointer_call_with_two_arguments(self) -> None:
        source = "int add(int a,int b){return a+b;} int main(){int (*fp)(int, int)=add; return fp(1,2);}"
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
        self.assertEqual(str(ctx.exception), "Argument count mismatch")

    def test_function_pointer_call_argument_type_mismatch(self) -> None:
        source = "int inc(int x){return x;} int main(){int (*fp)(int)=inc; int *p; return fp(p);}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument type mismatch")

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
        self.assertEqual(str(ctx.exception), "Argument count mismatch")

    def test_void_function_pointer_parameter_is_allowed(self) -> None:
        unit = parse(list(lex("int f(void (*cb)(void)){return 0;}")))
        sema = analyze(unit)
        self.assertIn("f", sema.functions)

    def test_function_declaration_then_definition(self) -> None:
        source = (
            "int add(int a, int b);"
            "int main(){return add(1,2);}"
            "int add(int a, int b){return a+b;}"
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
        self.assertEqual(str(ctx.exception), "Argument count mismatch: logf")

    def test_variadic_function_call_fixed_argument_type_mismatch(self) -> None:
        source = "int logf(int level, ...){return level;} int main(){int *p; return logf(p, 1);}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument type mismatch: logf")

    def test_function_declaration_without_definition(self) -> None:
        unit = parse(list(lex("int add(int a, int b);")))
        sema = analyze(unit)
        self.assertEqual(sema.functions, {})

    def test_conflicting_function_declaration(self) -> None:
        unit = parse(list(lex("int add(int a); int add(int a, int b);")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conflicting declaration: add")

    def test_conflicting_function_return_type_declaration(self) -> None:
        unit = parse(list(lex("int add(); void add();")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conflicting declaration: add")

    def test_argument_count_mismatch(self) -> None:
        unit = parse(list(lex("int add(int a,int b){return a+b;} int main(){return add(1);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument count mismatch: add")

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
        source = (
            "int main(){"
            "if(1) return 1;"
            "if(1) return 2; else return 3;"
            "while(1) ;"
            "return 0;"
            "}"
        )
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
        source = (
            "int main(){"
            "int x=1;"
            "switch(x){case 1: break; default: return 0;}"
            "return 1;"
            "}"
        )
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
        source = (
            "int main(){"
            "struct Node { int value; } a;"
            "struct Node b;"
            "b=a;"
            "return 0;"
            "}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_union_object_type_is_assignable(self) -> None:
        source = (
            "int main(){"
            "union Data { int x; int y; } a;"
            "union Data b;"
            "b=a;"
            "return 0;"
            "}"
        )
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

    def test_cast_expression_typemap(self) -> None:
        unit = parse(list(lex("int main(){int *p; return (int)p;}")))
        sema = analyze(unit)
        return_expr = _body(unit.functions[0]).statements[1].value
        assert return_expr is not None
        self.assertEqual(sema.type_map.get(return_expr), INT)

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

    def test_duplicate_file_scope_object_declaration(self) -> None:
        unit = parse(list(lex("int g; int g; int main(){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate declaration: g")

    def test_file_scope_incomplete_object_error(self) -> None:
        unit = parse(list(lex("struct S g; int main(){return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid object type: incomplete")

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

    def test_file_scope_multi_declarator_declaration_ok(self) -> None:
        source = "int x=1, y=2; int main(){return x+y;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_file_scope_void_object_error(self) -> None:
        unit = TranslationUnit([], [DeclStmt(TypeSpec("void"), "g", None)])
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid object type: void")

    def test_unsupported_file_scope_declaration_error(self) -> None:
        unit = TranslationUnit([], [ExprStmt(IntLiteral("1"))])
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Unsupported file-scope declaration")

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
        source = "int main(){int a[4]; int b[4]; int (*p)[4]=&a; int (*q)[4]=&b; p=q; return (*p)[0];}"
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

    def test_assignment_type_mismatch(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; x=p; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment type mismatch")

    def test_compound_assignment_int_ok(self) -> None:
        source = "int main(){int x=8; x+=2; x<<=1; x%=3; return x;}"
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("main", sema.functions)

    def test_compound_assignment_type_mismatch(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; x+=p; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment type mismatch")

    def test_compound_assignment_pointer_target_mismatch(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p=&x; p+=1; return x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Assignment type mismatch")

    def test_return_type_mismatch(self) -> None:
        unit = parse(list(lex("int *f(int *p){return 1;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Return type mismatch")

    def test_argument_type_mismatch(self) -> None:
        unit = parse(list(lex("int *id(int *p){return p;} int main(){int x=1; return id(x);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Argument type mismatch: id")

    def test_dereference_non_pointer_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; return *x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Cannot dereference non-pointer")

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
        self.assertEqual(str(ctx.exception), "Unsupported expression")

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

    def test_duplicate_struct_definition_error(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; }; struct S { int y; }; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate definition: struct S")

    def test_incomplete_struct_object_error(self) -> None:
        unit = parse(list(lex("int main(){struct Node value; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid object type: incomplete")

    def test_incomplete_union_object_error(self) -> None:
        unit = parse(list(lex("int main(){union Data value; return 0;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid object type: incomplete")

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
        self.assertEqual(str(ctx.exception), "Invalid object type: incomplete")

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
        self.assertEqual(str(ctx.exception), "Invalid member type")

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
                                        (TypeSpec("int", declarator_ops=(("fn", ((), False)),)), "call"),
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
        self.assertEqual(str(ctx.exception), "Invalid member type")

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
                                    record_members=((TypeSpec("struct", record_tag="Node"), "next"),),
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
        self.assertEqual(str(ctx.exception), "Invalid member type")

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
        self.assertEqual(str(ctx.exception), "Assignment type mismatch")

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
        self.assertEqual(str(ctx.exception), "Invalid object type: void")

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
                                    declarator_ops=(("ptr", 0), ("fn", ((TypeSpec("void"),), False))),
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
        unit = parse(list(lex("int main(){enum E { A=1, B=1 }; switch(1){case A:return 0;case B:return 1;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Duplicate case value")

    def test_duplicate_default_label_error(self) -> None:
        unit = parse(
            list(lex("int main(){switch(1){default:return 0;default:return 1;}}"))
        )
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

    def test_non_decimal_case_constant_error(self) -> None:
        unit = parse(list(lex("int main(){switch(0){case 0x10:return 0;}}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "case value is not integer constant")

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

    def test_conditional_void_condition_error(self) -> None:
        unit = parse(list(lex("void foo(){return;} int main(){return foo() ? 1 : 2;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be non-void")

    def test_conditional_type_mismatch_error(self) -> None:
        unit = parse(list(lex("int main(){int x=1; int *p; return x ? x : p;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Conditional type mismatch")

    def test_while_void_condition_error(self) -> None:
        unit = parse(
            list(lex("void foo(){return;} int main(){while(foo()) return 0;}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be non-void")

    def test_do_while_void_condition_error(self) -> None:
        unit = parse(
            list(lex("void foo(){return;} int main(){do return 0; while(foo());}"))
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Condition must be non-void")

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
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand")

    def test_sizeof_incomplete_record_type_error(self) -> None:
        unit = parse(list(lex("int main(){return sizeof(struct S);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand")

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
                                    TypeSpec("int", declarator_ops=(("fn", ((TypeSpec("int"),), False)),)),
                                )
                            )
                        ]
                    ),
                )
            ]
        )
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand")

    def test_sizeof_function_designator_error(self) -> None:
        unit = parse(list(lex("int f(int x){return x;} int main(){return sizeof(f);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand")

    def test_sizeof_void_expression_error(self) -> None:
        unit = parse(list(lex("void f(void){return;} int main(){return sizeof(f());}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand")

    def test_sizeof_incomplete_record_expression_error(self) -> None:
        unit = parse(list(lex("int main(){struct S *p; return sizeof(*p);}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid sizeof operand")

    def test_cast_void_expression_to_int_error(self) -> None:
        unit = parse(list(lex("void f(void){return;} int main(){return (int)f();}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid cast")

    def test_cast_struct_target_error(self) -> None:
        source = "int main(){struct S { int x; } s; return (struct S)s;}"
        unit = parse(list(lex(source)))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid cast")

    def test_cast_incomplete_record_target_error(self) -> None:
        unit = parse(list(lex("int main(){int x; return (struct S)x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid cast")

    def test_cast_array_target_error(self) -> None:
        unit = parse(list(lex("int main(){int x; return (int[2])x;}")))
        with self.assertRaises(SemaError) as ctx:
            analyze(unit)
        self.assertEqual(str(ctx.exception), "Invalid cast")

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
                                    TypeSpec("int", declarator_ops=(("fn", ((TypeSpec("int"),), False)),)),
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
        self.assertEqual(str(ctx.exception), "Invalid cast")

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
        self.assertEqual(str(ctx.exception), "Unsupported expression")

    def test_unsupported_statement(self) -> None:
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
        self.assertEqual(str(ctx.exception), "Unsupported statement")


if __name__ == "__main__":
    unittest.main()
