import unittest

from tests import _bootstrap  # noqa: F401
from xcc.ast import (
    AssignExpr,
    BinaryExpr,
    CallExpr,
    DeclStmt,
    ExprStmt,
    Identifier,
    IntLiteral,
    NullStmt,
    Param,
    ReturnStmt,
    TypeSpec,
    UnaryExpr,
)
from xcc.lexer import lex
from xcc.parser import ParserError, parse


class ParserTests(unittest.TestCase):
    def test_parse_function(self) -> None:
        source = "int main(){return 1+2*3;}"
        tokens = list(lex(source))
        unit = parse(tokens)
        self.assertEqual(len(unit.functions), 1)
        func = unit.functions[0]
        self.assertEqual(func.name, "main")
        self.assertEqual(func.params, [])
        stmt = func.body.statements[0]
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
        stmt = unit.functions[0].body.statements[0]
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

    def test_void_parameter_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int f(void x){return 0;}")))

    def test_call_expression(self) -> None:
        source = "int add(int a,int b){return a+b;} int main(){return add(1,2);}"
        unit = parse(list(lex(source)))
        call = unit.functions[1].body.statements[0].value
        self.assertIsInstance(call, CallExpr)
        self.assertIsInstance(call.callee, Identifier)
        self.assertEqual(call.callee.name, "add")
        self.assertEqual(len(call.args), 2)

    def test_call_with_no_arguments(self) -> None:
        source = "int foo(){return 0;} int main(){return foo();}"
        unit = parse(list(lex(source)))
        call = unit.functions[1].body.statements[0].value
        self.assertIsInstance(call, CallExpr)
        self.assertEqual(call.args, [])

    def test_relational_precedence(self) -> None:
        unit = parse(list(lex("int main(){return 1==2<3;}")))
        expr = unit.functions[0].body.statements[0].value
        self.assertIsInstance(expr, BinaryExpr)
        self.assertEqual(expr.op, "==")
        self.assertIsInstance(expr.right, BinaryExpr)
        self.assertEqual(expr.right.op, "<")

    def test_logical_precedence(self) -> None:
        source = "int main(){return 1==2||3==4&&5==6;}"
        unit = parse(list(lex(source)))
        expr = unit.functions[0].body.statements[0].value
        self.assertIsInstance(expr, BinaryExpr)
        self.assertEqual(expr.op, "||")
        self.assertIsInstance(expr.right, BinaryExpr)
        self.assertEqual(expr.right.op, "&&")

    def test_expression_statement(self) -> None:
        source = "int main(){x;return 0;}"
        unit = parse(list(lex(source)))
        stmt = unit.functions[0].body.statements[0]
        self.assertIsInstance(stmt, ExprStmt)

    def test_parenthesized_expression(self) -> None:
        source = "int main(){return (1+2)*3;}"
        unit = parse(list(lex(source)))
        stmt = unit.functions[0].body.statements[0]
        self.assertIsInstance(stmt, ReturnStmt)

    def test_subtraction_and_division(self) -> None:
        source = "int main(){return 4-2/1;}"
        unit = parse(list(lex(source)))
        stmt = unit.functions[0].body.statements[0]
        self.assertIsInstance(stmt, ReturnStmt)

    def test_unary_expression(self) -> None:
        unit = parse(list(lex("int main(){return -1;}")))
        stmt = unit.functions[0].body.statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, UnaryExpr)
        self.assertEqual(expr.op, "-")
        self.assertIsInstance(expr.operand, IntLiteral)

    def test_assignment_expression(self) -> None:
        unit = parse(list(lex("int main(){x=1+2*3;return 0;}")))
        stmt = unit.functions[0].body.statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, AssignExpr)
        self.assertEqual(expr.op, "=")
        self.assertIsInstance(expr.target, Identifier)
        self.assertIsInstance(expr.value, BinaryExpr)

    def test_assignment_is_right_associative(self) -> None:
        unit = parse(list(lex("int main(){a=b=1;return 0;}")))
        stmt = unit.functions[0].body.statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, AssignExpr)
        self.assertIsInstance(expr.target, Identifier)
        self.assertIsInstance(expr.value, AssignExpr)

    def test_empty_statement(self) -> None:
        unit = parse(list(lex("int main(){;return 0;}")))
        stmt = unit.functions[0].body.statements[0]
        self.assertIsInstance(stmt, NullStmt)

    def test_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int x;return x;}")))
        stmt = unit.functions[0].body.statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int"))
        self.assertEqual(stmt.name, "x")
        self.assertIsNone(stmt.init)

    def test_declaration_with_initializer(self) -> None:
        unit = parse(list(lex("int main(){int x=1+2;return x;}")))
        stmt = unit.functions[0].body.statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertIsInstance(stmt.init, BinaryExpr)

    def test_void_declaration_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){void x;return 0;}")))

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
        self.assertEqual(len(unit.functions[0].body.statements), 0)

    def test_empty_translation_unit(self) -> None:
        unit = parse(list(lex("")))
        self.assertEqual(unit.functions, [])


if __name__ == "__main__":
    unittest.main()
