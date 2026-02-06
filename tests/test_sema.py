import unittest

from tests import _bootstrap  # noqa: F401
from xcc.ast import (
    CompoundStmt,
    DeclStmt,
    Expr,
    ExprStmt,
    FunctionDef,
    CallExpr,
    IntLiteral,
    Param,
    Stmt,
    TranslationUnit,
    TypeSpec,
    UnaryExpr,
)
from xcc.lexer import lex
from xcc.parser import parse
from xcc.sema import SemaError, analyze
from xcc.types import INT, Type


def _body(func):
    assert func.body is not None
    return func.body


class SemaTests(unittest.TestCase):
    def test_type_str(self) -> None:
        self.assertEqual(str(INT), "int")
        array = Type("int").array_of(4)
        self.assertEqual(str(array), "int[4]")
        pointer = array.pointer_to()
        self.assertEqual(pointer, Type("int", 1, (4,)))
        self.assertEqual(pointer.pointee(), array)
        self.assertEqual(array.element_type(), Type("int"))
        self.assertIsNone(Type("int").pointee())
        self.assertIsNone(Type("int").element_type())

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

    def test_function_declaration_then_definition(self) -> None:
        source = (
            "int add(int a, int b);"
            "int main(){return add(1,2);}"
            "int add(int a, int b){return a+b;}"
        )
        unit = parse(list(lex(source)))
        sema = analyze(unit)
        self.assertIn("add", sema.functions)

    def test_function_declaration_without_definition(self) -> None:
        unit = parse(list(lex("int add(int a, int b);")))
        sema = analyze(unit)
        self.assertEqual(sema.functions, {})

    def test_conflicting_function_declaration(self) -> None:
        unit = parse(list(lex("int add(int a); int add(int a, int b);")))
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

    def test_while_void_condition_error(self) -> None:
        unit = parse(
            list(lex("void foo(){return;} int main(){while(foo()) return 0;}"))
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
