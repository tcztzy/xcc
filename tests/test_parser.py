import unittest

from tests import _bootstrap  # noqa: F401
from xcc.ast import (
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CaseStmt,
    CallExpr,
    CompoundStmt,
    ContinueStmt,
    DeclStmt,
    DefaultStmt,
    ExprStmt,
    ForStmt,
    Identifier,
    IfStmt,
    IntLiteral,
    NullStmt,
    Param,
    ReturnStmt,
    SubscriptExpr,
    SwitchStmt,
    TypeSpec,
    UnaryExpr,
    WhileStmt,
)
from xcc.lexer import lex
from xcc.parser import ParserError, parse


def _body(func):
    assert func.body is not None
    return func.body


class ParserTests(unittest.TestCase):
    def test_parse_function(self) -> None:
        source = "int main(){return 1+2*3;}"
        tokens = list(lex(source))
        unit = parse(tokens)
        self.assertEqual(len(unit.functions), 1)
        func = unit.functions[0]
        self.assertEqual(func.name, "main")
        self.assertEqual(func.params, [])
        stmt = _body(func).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, BinaryExpr)
        self.assertEqual(expr.op, "+")
        right = expr.right
        self.assertIsInstance(right, BinaryExpr)
        self.assertEqual(right.op, "*")

    def test_void_return(self) -> None:
        source = "void main(){return;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        self.assertIsNone(stmt.value)

    def test_function_parameters(self) -> None:
        unit = parse(list(lex("int add(int a, int b){return a+b;}")))
        func = unit.functions[0]
        self.assertEqual(
            func.params,
            [Param(TypeSpec("int"), "a"), Param(TypeSpec("int"), "b")],
        )

    def test_void_parameter_list(self) -> None:
        unit = parse(list(lex("int main(void){return 0;}")))
        self.assertEqual(unit.functions[0].params, [])

    def test_function_declaration(self) -> None:
        unit = parse(list(lex("int add(int a, int b); int main(){return 0;}")))
        decl = unit.functions[0]
        self.assertIsNone(decl.body)
        self.assertEqual(
            decl.params,
            [Param(TypeSpec("int"), "a"), Param(TypeSpec("int"), "b")],
        )

    def test_function_declaration_unnamed_params(self) -> None:
        unit = parse(list(lex("int add(int, int);")))
        decl = unit.functions[0]
        self.assertIsNone(decl.body)
        self.assertEqual([param.name for param in decl.params], [None, None])

    def test_declaration_void_parameter_list(self) -> None:
        unit = parse(list(lex("int ping(void);")))
        decl = unit.functions[0]
        self.assertIsNone(decl.body)
        self.assertEqual(decl.params, [])

    def test_definition_requires_parameter_names(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int add(int, int){return 0;}")))

    def test_void_parameter_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int f(void x){return 0;}")))

    def test_void_pointer_parameter_is_allowed(self) -> None:
        unit = parse(list(lex("int f(void *p){return 0;}")))
        self.assertEqual(unit.functions[0].params, [Param(TypeSpec("void", 1), "p")])

    def test_array_parameter_is_allowed(self) -> None:
        unit = parse(list(lex("int f(int a[4]){return a[0];}")))
        self.assertEqual(unit.functions[0].params, [Param(TypeSpec("int", 0, (4,)), "a")])

    def test_pointer_to_array_parameter(self) -> None:
        unit = parse(list(lex("int f(int (*p)[4]){return (*p)[0];}")))
        self.assertEqual(
            unit.functions[0].params,
            [Param(TypeSpec("int", declarator_ops=(("ptr", 0), ("arr", 4))), "p")],
        )

    def test_function_pointer_parameter(self) -> None:
        unit = parse(list(lex("int apply(int (*fn)(int), int x){return fn(x);}")))
        self.assertEqual(
            unit.functions[0].params,
            [
                Param(TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", 1))), "fn"),
                Param(TypeSpec("int"), "x"),
            ],
        )

    def test_call_expression(self) -> None:
        source = "int add(int a,int b){return a+b;} int main(){return add(1,2);}"
        unit = parse(list(lex(source)))
        call = _body(unit.functions[1]).statements[0].value
        self.assertIsInstance(call, CallExpr)
        self.assertIsInstance(call.callee, Identifier)
        self.assertEqual(call.callee.name, "add")
        self.assertEqual(len(call.args), 2)

    def test_call_with_no_arguments(self) -> None:
        source = "int foo(){return 0;} int main(){return foo();}"
        unit = parse(list(lex(source)))
        call = _body(unit.functions[1]).statements[0].value
        self.assertIsInstance(call, CallExpr)
        self.assertEqual(call.args, [])

    def test_if_else_statement(self) -> None:
        source = "int main(){if(1) return 1; else return 2;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, IfStmt)
        self.assertIsNotNone(stmt.else_body)

    def test_if_without_else(self) -> None:
        source = "int main(){if(1) return 1; return 0;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, IfStmt)
        self.assertIsNone(stmt.else_body)

    def test_dangling_else_binds_to_inner_if(self) -> None:
        source = "int main(){if(1) if(0) return 1; else return 2;}"
        unit = parse(list(lex(source)))
        outer = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(outer, IfStmt)
        self.assertIsNone(outer.else_body)
        self.assertIsInstance(outer.then_body, IfStmt)
        self.assertIsNotNone(outer.then_body.else_body)

    def test_while_statement(self) -> None:
        source = "int main(){while(1) return 0;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, WhileStmt)

    def test_compound_statement_as_statement(self) -> None:
        source = "int main(){if(1){return 0;} return 1;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, IfStmt)
        self.assertIsInstance(stmt.then_body, CompoundStmt)

    def test_for_statement_with_expression_init(self) -> None:
        source = "int main(){for(i=0;i<3;i=i+1) ;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ForStmt)
        self.assertIsInstance(stmt.init, AssignExpr)
        self.assertIsInstance(stmt.condition, BinaryExpr)
        self.assertIsInstance(stmt.post, AssignExpr)

    def test_for_statement_with_declaration_init(self) -> None:
        source = "int main(){for(int i=0;i<3;i=i+1) ;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ForStmt)
        self.assertIsInstance(stmt.init, DeclStmt)

    def test_for_statement_empty_clauses(self) -> None:
        unit = parse(list(lex("int main(){for(;;) ;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ForStmt)
        self.assertIsNone(stmt.init)
        self.assertIsNone(stmt.condition)
        self.assertIsNone(stmt.post)

    def test_break_and_continue_statements(self) -> None:
        source = "int main(){while(1){break;continue;}}"
        unit = parse(list(lex(source)))
        while_stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(while_stmt, WhileStmt)
        body = while_stmt.body
        self.assertIsInstance(body, CompoundStmt)
        self.assertIsInstance(body.statements[0], BreakStmt)
        self.assertIsInstance(body.statements[1], ContinueStmt)

    def test_switch_statement(self) -> None:
        source = "int main(){switch(x){case 1:return 1;default:return 0;}}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, SwitchStmt)
        body = stmt.body
        self.assertIsInstance(body, CompoundStmt)
        self.assertIsInstance(body.statements[0], CaseStmt)
        self.assertIsInstance(body.statements[1], DefaultStmt)

    def test_switch_consecutive_case_labels(self) -> None:
        source = "int main(){switch(x){case 1:case 2:return 0;}}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, SwitchStmt)
        body = stmt.body
        self.assertIsInstance(body, CompoundStmt)
        first = body.statements[0]
        self.assertIsInstance(first, CaseStmt)
        self.assertIsInstance(first.body, CaseStmt)

    def test_case_missing_colon(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){switch(x){case 1 return 0;}}")))

    def test_default_missing_colon(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){switch(x){default return 0;}}")))

    def test_relational_precedence(self) -> None:
        unit = parse(list(lex("int main(){return 1==2<3;}")))
        expr = _body(unit.functions[0]).statements[0].value
        self.assertIsInstance(expr, BinaryExpr)
        self.assertEqual(expr.op, "==")
        self.assertIsInstance(expr.right, BinaryExpr)
        self.assertEqual(expr.right.op, "<")

    def test_logical_precedence(self) -> None:
        source = "int main(){return 1==2||3==4&&5==6;}"
        unit = parse(list(lex(source)))
        expr = _body(unit.functions[0]).statements[0].value
        self.assertIsInstance(expr, BinaryExpr)
        self.assertEqual(expr.op, "||")
        self.assertIsInstance(expr.right, BinaryExpr)
        self.assertEqual(expr.right.op, "&&")

    def test_expression_statement(self) -> None:
        source = "int main(){x;return 0;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)

    def test_parenthesized_expression(self) -> None:
        source = "int main(){return (1+2)*3;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)

    def test_subtraction_and_division(self) -> None:
        source = "int main(){return 4-2/1;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)

    def test_unary_expression(self) -> None:
        unit = parse(list(lex("int main(){return -1;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, UnaryExpr)
        self.assertEqual(expr.op, "-")
        self.assertIsInstance(expr.operand, IntLiteral)

    def test_assignment_expression(self) -> None:
        unit = parse(list(lex("int main(){x=1+2*3;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, AssignExpr)
        self.assertEqual(expr.op, "=")
        self.assertIsInstance(expr.target, Identifier)
        self.assertIsInstance(expr.value, BinaryExpr)

    def test_assignment_is_right_associative(self) -> None:
        unit = parse(list(lex("int main(){a=b=1;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, AssignExpr)
        self.assertIsInstance(expr.target, Identifier)
        self.assertIsInstance(expr.value, AssignExpr)

    def test_empty_statement(self) -> None:
        unit = parse(list(lex("int main(){;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, NullStmt)

    def test_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int x;return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int"))
        self.assertEqual(stmt.name, "x")
        self.assertIsNone(stmt.init)

    def test_declaration_with_initializer(self) -> None:
        unit = parse(list(lex("int main(){int x=1+2;return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertIsInstance(stmt.init, BinaryExpr)

    def test_pointer_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int *p;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 1))

    def test_array_of_pointers_declaration(self) -> None:
        unit = parse(list(lex("int main(){int *p[4];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 1, (4,)))

    def test_pointer_to_array_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int (*p)[4];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("int", declarator_ops=(("ptr", 0), ("arr", 4))),
        )

    def test_function_pointer_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int (*fp)(int);return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", 1))),
        )

    def test_function_pointer_declaration_with_two_params(self) -> None:
        unit = parse(list(lex("int main(){int (*fp)(int, int);return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", 2))),
        )

    def test_function_pointer_declaration_with_void_suffix(self) -> None:
        unit = parse(list(lex("int main(){int (*fp)(void);return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", 0))),
        )

    def test_function_pointer_declaration_with_empty_suffix(self) -> None:
        unit = parse(list(lex("int main(){int (*fp)();return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", 0))),
        )

    def test_array_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int a[4];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 0, (4,)))

    def test_multidimensional_array_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int a[2][3];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 0, (2, 3)))

    def test_void_pointer_declaration_is_allowed(self) -> None:
        unit = parse(list(lex("int main(){void *p;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("void", 1))

    def test_pointer_parameter_and_return_type(self) -> None:
        unit = parse(list(lex("int *id(int *p){return p;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("int", 1))
        self.assertEqual(func.params, [Param(TypeSpec("int", 1), "p")])

    def test_multiple_pointer_levels(self) -> None:
        unit = parse(list(lex("int **id(int **pp){return pp;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("int", 2))
        self.assertEqual(func.params, [Param(TypeSpec("int", 2), "pp")])

    def test_unary_address_of_expression(self) -> None:
        unit = parse(list(lex("int main(){int x;return &x;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, UnaryExpr)
        self.assertEqual(expr.op, "&")

    def test_unary_dereference_expression(self) -> None:
        unit = parse(list(lex("int main(){int *p;return *p;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, UnaryExpr)
        self.assertEqual(expr.op, "*")

    def test_subscript_expression(self) -> None:
        unit = parse(list(lex("int main(){int a[4];return a[1];}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, SubscriptExpr)
        self.assertIsInstance(expr.base, Identifier)
        self.assertIsInstance(expr.index, IntLiteral)

    def test_nested_subscript_expression(self) -> None:
        unit = parse(list(lex("int main(){int a[2][3];return a[1][2];}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, SubscriptExpr)
        self.assertIsInstance(expr.base, SubscriptExpr)

    def test_array_size_must_be_positive(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int a[0];return 0;}")))

    def test_array_size_must_be_decimal_literal(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int a[0x10];return 0;}")))

    def test_void_declaration_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){void x;return 0;}")))

    def test_void_array_declaration_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){void x[1];return 0;}")))

    def test_missing_declarator_in_declaration(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int ;return 0;}")))

    def test_missing_semicolon(self) -> None:
        source = "int main(){return 1}"
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex(source)))
        self.assertIn(":", str(ctx.exception))

    def test_unexpected_token(self) -> None:
        source = "int main(){return int;}"
        with self.assertRaises(ParserError):
            parse(list(lex(source)))

    def test_unsupported_type(self) -> None:
        source = "return main(){return 0;}"
        with self.assertRaises(ParserError):
            parse(list(lex(source)))

    def test_missing_type(self) -> None:
        source = "main(){return 0;}"
        with self.assertRaises(ParserError):
            parse(list(lex(source)))

    def test_empty_function(self) -> None:
        source = "int main(){}"
        unit = parse(list(lex(source)))
        self.assertEqual(len(_body(unit.functions[0]).statements), 0)

    def test_empty_translation_unit(self) -> None:
        unit = parse(list(lex("")))
        self.assertEqual(unit.functions, [])


if __name__ == "__main__":
    unittest.main()
