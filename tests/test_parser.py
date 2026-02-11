import unittest

from tests import _bootstrap  # noqa: F401
from xcc.ast import (
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CaseStmt,
    CallExpr,
    CastExpr,
    CharLiteral,
    CompoundStmt,
    ContinueStmt,
    ConditionalExpr,
    CommaExpr,
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
    DoWhileStmt,
    ExprStmt,
    ForStmt,
    FunctionDef,
    GotoStmt,
    Identifier,
    IndirectGotoStmt,
    IfStmt,
    IntLiteral,
    LabelAddressExpr,
    LabelStmt,
    MemberExpr,
    NullStmt,
    Param,
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
    WhileStmt,
)
from xcc.lexer import Token, TokenKind, lex
from xcc.parser import Parser, ParserError, _parse_int_literal_value, parse


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

    def test_char_function_signature(self) -> None:
        unit = parse(list(lex("char id(char c){return c;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("char"))
        self.assertEqual(func.params, [Param(TypeSpec("char"), "c")])

    def test_long_function_signature(self) -> None:
        unit = parse(list(lex("long id(long x){return x;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("long"))
        self.assertEqual(func.params, [Param(TypeSpec("long"), "x")])

    def test_short_function_signature(self) -> None:
        unit = parse(list(lex("short id(short x){return x;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("short"))
        self.assertEqual(func.params, [Param(TypeSpec("short"), "x")])

    def test_unsigned_function_signature(self) -> None:
        unit = parse(list(lex("unsigned add(unsigned a, unsigned int b){return a+b;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("unsigned int"))
        self.assertEqual(
            func.params,
            [Param(TypeSpec("unsigned int"), "a"), Param(TypeSpec("unsigned int"), "b")],
        )

    def test_unsigned_long_function_signature(self) -> None:
        unit = parse(list(lex("unsigned long id(unsigned long x){return x;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("unsigned long"))
        self.assertEqual(func.params, [Param(TypeSpec("unsigned long"), "x")])

    def test_long_long_function_signature(self) -> None:
        unit = parse(list(lex("long long id(long long x){return x;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("long long"))
        self.assertEqual(func.params, [Param(TypeSpec("long long"), "x")])

    def test_unsigned_long_long_function_signature(self) -> None:
        unit = parse(list(lex("unsigned long long id(unsigned long long x){return x;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("unsigned long long"))
        self.assertEqual(func.params, [Param(TypeSpec("unsigned long long"), "x")])

    def test_floating_function_signature(self) -> None:
        unit = parse(list(lex("double f(float x, long double y){return x;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("double"))
        self.assertEqual(func.params, [Param(TypeSpec("float"), "x"), Param(TypeSpec("long double"), "y")])

    def test_complex_specifier_is_ignored_in_type_spec(self) -> None:
        unit = parse(list(lex("float _Complex cabsf(float _Complex x);")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("float"))
        self.assertEqual(func.params, [Param(TypeSpec("float"), "x")])

    def test_complex_specifier_requires_floating_base_type(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(void){_Complex int x; return 0;}")))

    def test_extension_marker_allows_file_scope_typedef(self) -> None:
        source = "__extension__ typedef struct { long long int quot; long long int rem; } lldiv_t;"
        unit = parse(list(lex(source)))
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, TypedefDecl)
        self.assertEqual(declaration.name, "lldiv_t")
        self.assertEqual(declaration.type_spec.name, "struct")
        self.assertEqual(len(declaration.type_spec.record_members), 2)

    def test_extension_marker_allows_block_declaration_and_expression(self) -> None:
        source = "int main(void){__extension__ int i; int j; __extension__ (j = 10LL); __extension__ j = 10LL; return j;}"
        unit = parse(list(lex(source)))
        statements = _body(unit.functions[0]).statements
        self.assertIsInstance(statements[0], DeclStmt)
        self.assertIsInstance(statements[2], ExprStmt)
        self.assertIsInstance(statements[3], ExprStmt)
        self.assertIsInstance(statements[2].expr, AssignExpr)
        self.assertIsInstance(statements[3].expr, AssignExpr)

    def test_extension_marker_allows_empty_translation_unit(self) -> None:
        unit = parse(list(lex("__extension__")))
        self.assertEqual(unit.functions, [])
        self.assertEqual(unit.declarations, [])

    def test_extension_marker_allows_for_init_declaration(self) -> None:
        source = "int main(void){for(__extension__ int i=0; i<1; i++){} return 0;}"
        unit = parse(list(lex(source)))
        for_stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(for_stmt, ForStmt)
        self.assertIsInstance(for_stmt.init, DeclStmt)

    def test_extension_marker_allowed_inside_expression(self) -> None:
        source = "int main(void){int j=0; j = __extension__ (j + 1); return j;}"
        unit = parse(list(lex(source)))
        assign_stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(assign_stmt, ExprStmt)
        self.assertIsInstance(assign_stmt.expr, AssignExpr)
        self.assertIsInstance(assign_stmt.expr.value, BinaryExpr)

    def test_unsigned_short_function_signature(self) -> None:
        unit = parse(list(lex("unsigned short id(unsigned short x){return x;}")))
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("unsigned short"))
        self.assertEqual(func.params, [Param(TypeSpec("unsigned short"), "x")])

    def test_signed_int_parameter_is_canonicalized(self) -> None:
        unit = parse(list(lex("int f(signed int value){return value;}")))
        func = unit.functions[0]
        self.assertEqual(func.params, [Param(TypeSpec("int"), "value")])

    def test_signed_short_parameter_is_canonicalized(self) -> None:
        unit = parse(list(lex("int f(signed short value){return value;}")))
        func = unit.functions[0]
        self.assertEqual(func.params, [Param(TypeSpec("short"), "value")])

    def test_signed_long_long_parameter_is_canonicalized(self) -> None:
        unit = parse(list(lex("int f(signed long long value){return value;}")))
        func = unit.functions[0]
        self.assertEqual(func.params, [Param(TypeSpec("long long"), "value")])

    def test_type_qualifiers_are_ignored_in_declarations(self) -> None:
        unit = parse(list(lex("int main(void){void const* p; int *const q; return 0;}")))
        statements = _body(unit.functions[0]).statements
        self.assertIsInstance(statements[0], DeclStmt)
        self.assertIsInstance(statements[1], DeclStmt)
        self.assertEqual(statements[0].type_spec, TypeSpec("void", pointer_depth=1))
        self.assertEqual(statements[1].type_spec, TypeSpec("int", pointer_depth=1))

    def test_sizeof_parenthesized_type_name_allows_type_qualifier(self) -> None:
        unit = parse(list(lex("int main(void){return sizeof(const int*);}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        self.assertIsInstance(stmt.value, SizeofExpr)
        self.assertEqual(stmt.value.type_spec, TypeSpec("int", pointer_depth=1))

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

    def test_declaration_without_prototype(self) -> None:
        unit = parse(list(lex("int ping();")))
        decl = unit.functions[0]
        self.assertFalse(decl.has_prototype)
        self.assertFalse(decl.is_variadic)
        self.assertEqual(decl.params, [])

    def test_variadic_function_declaration(self) -> None:
        unit = parse(list(lex("int logf(int level, ...);")))
        decl = unit.functions[0]
        self.assertTrue(decl.has_prototype)
        self.assertTrue(decl.is_variadic)
        self.assertEqual(decl.params, [Param(TypeSpec("int"), "level")])

    def test_variadic_requires_fixed_parameter(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int logf(...);")))

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
                Param(TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", ((TypeSpec("int"),), False)))), "fn"),
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

    def test_do_while_statement(self) -> None:
        source = "int main(){do return 0; while(1);}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DoWhileStmt)
        self.assertIsInstance(stmt.body, ReturnStmt)
        self.assertIsInstance(stmt.condition, IntLiteral)

    def test_do_while_requires_while_clause(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){do return 0;}")))

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

    def test_label_statement(self) -> None:
        unit = parse(list(lex("int main(){entry: return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, LabelStmt)
        self.assertEqual(stmt.name, "entry")
        self.assertIsInstance(stmt.body, ReturnStmt)

    def test_goto_statement(self) -> None:
        unit = parse(list(lex("int main(){goto done; done: return 0;}")))
        body = _body(unit.functions[0]).statements
        self.assertIsInstance(body[0], GotoStmt)
        self.assertEqual(body[0].label, "done")
        self.assertIsInstance(body[1], LabelStmt)

    def test_indirect_goto_statement(self) -> None:
        unit = parse(list(lex("int main(void){void *target=0; goto *target; return 0;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, IndirectGotoStmt)
        self.assertIsInstance(stmt.target, Identifier)
        self.assertEqual(stmt.target.name, "target")

    def test_label_address_expression(self) -> None:
        unit = parse(list(lex("int main(void){void *target = &&done; goto *target; done: return 0;}")))
        decl = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(decl, DeclStmt)
        self.assertIsInstance(decl.init, LabelAddressExpr)
        self.assertEqual(decl.init.label, "done")

    def test_statement_expression_in_for_init(self) -> None:
        source = "int main(void){for(({int x=0; x;});;); return 0;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ForStmt)
        self.assertIsInstance(stmt.init, StatementExpr)
        self.assertEqual(len(stmt.init.body.statements), 2)

    def test_goto_requires_label_name(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){goto; return 0;}")))

    def test_case_missing_colon(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){switch(x){case 1 return 0;}}")))

    def test_conditional_missing_colon(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){return 1?2;}")))

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

    def test_shift_precedence(self) -> None:
        unit = parse(list(lex("int main(){return 1<<2+3;}")))
        expr = _body(unit.functions[0]).statements[0].value
        self.assertIsInstance(expr, BinaryExpr)
        self.assertEqual(expr.op, "<<")
        self.assertIsInstance(expr.right, BinaryExpr)
        self.assertEqual(expr.right.op, "+")

    def test_bitwise_precedence(self) -> None:
        unit = parse(list(lex("int main(){return 1|2^3&4;}")))
        expr = _body(unit.functions[0]).statements[0].value
        self.assertIsInstance(expr, BinaryExpr)
        self.assertEqual(expr.op, "|")
        self.assertIsInstance(expr.right, BinaryExpr)
        self.assertEqual(expr.right.op, "^")
        and_expr = expr.right.right
        self.assertIsInstance(and_expr, BinaryExpr)
        self.assertEqual(and_expr.op, "&")

    def test_logical_and_with_bitwise_or_precedence(self) -> None:
        unit = parse(list(lex("int main(){return 1|2&&3;}")))
        expr = _body(unit.functions[0]).statements[0].value
        self.assertIsInstance(expr, BinaryExpr)
        self.assertEqual(expr.op, "&&")
        self.assertIsInstance(expr.left, BinaryExpr)
        self.assertEqual(expr.left.op, "|")

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

    def test_modulo_precedence(self) -> None:
        unit = parse(list(lex("int main(){return 8%3+1;}")))
        expr = _body(unit.functions[0]).statements[0].value
        self.assertIsInstance(expr, BinaryExpr)
        self.assertEqual(expr.op, "+")
        self.assertIsInstance(expr.left, BinaryExpr)
        self.assertEqual(expr.left.op, "%")

    def test_unary_expression(self) -> None:
        unit = parse(list(lex("int main(){return -1;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, UnaryExpr)
        self.assertEqual(expr.op, "-")
        self.assertIsInstance(expr.operand, IntLiteral)

    def test_char_literal_expression(self) -> None:
        unit = parse(list(lex("int main(){return 'a';}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, CharLiteral)
        self.assertEqual(expr.value, "'a'")

    def test_string_literal_expression(self) -> None:
        unit = parse(list(lex('int main(){"hi";return 0;}')))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        self.assertIsInstance(stmt.expr, StringLiteral)
        self.assertEqual(stmt.expr.value, '"hi"')

    def test_string_literal_initializer(self) -> None:
        unit = parse(list(lex('int main(){char s[4]="abc";return 0;}')))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        init = stmt.init
        self.assertIsInstance(init, StringLiteral)
        self.assertEqual(init.value, '"abc"')

    def test_adjacent_string_literals_are_concatenated(self) -> None:
        unit = parse(list(lex('int main(){"a" "b";return 0;}')))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        self.assertIsInstance(stmt.expr, StringLiteral)
        self.assertEqual(stmt.expr.value, '"ab"')

    def test_adjacent_string_literals_keep_utf8_prefix(self) -> None:
        unit = parse(list(lex('int main(){u8"a" "b";return 0;}')))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        self.assertIsInstance(stmt.expr, StringLiteral)
        self.assertEqual(stmt.expr.value, 'u8"ab"')

    def test_adjacent_string_literals_adopt_utf8_prefix(self) -> None:
        unit = parse(list(lex('int main(){"a" u8"b";return 0;}')))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        self.assertIsInstance(stmt.expr, StringLiteral)
        self.assertEqual(stmt.expr.value, 'u8"ab"')

    def test_adjacent_string_literals_incompatible_prefix_error(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex('int main(){u8"a" L"b";return 0;}')))

    def test_invalid_string_literal_token_error(self) -> None:
        tokens = [
            Token(TokenKind.KEYWORD, "int", 1, 1),
            Token(TokenKind.IDENT, "main", 1, 5),
            Token(TokenKind.PUNCTUATOR, "(", 1, 9),
            Token(TokenKind.PUNCTUATOR, ")", 1, 10),
            Token(TokenKind.PUNCTUATOR, "{", 1, 11),
            Token(TokenKind.STRING_LITERAL, "invalid", 1, 12),
            Token(TokenKind.PUNCTUATOR, ";", 1, 19),
            Token(TokenKind.KEYWORD, "return", 1, 20),
            Token(TokenKind.INT_CONST, "0", 1, 27),
            Token(TokenKind.PUNCTUATOR, ";", 1, 28),
            Token(TokenKind.PUNCTUATOR, "}", 1, 29),
            Token(TokenKind.EOF, None, 1, 30),
        ]
        with self.assertRaises(ParserError) as ctx:
            parse(tokens)
        self.assertEqual(str(ctx.exception), "Invalid string literal at 1:12")

    def test_prefix_update_expression(self) -> None:
        unit = parse(list(lex("int main(){++x;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, UpdateExpr)
        self.assertEqual(expr.op, "++")
        self.assertFalse(expr.is_postfix)
        self.assertIsInstance(expr.operand, Identifier)

    def test_postfix_update_expression(self) -> None:
        unit = parse(list(lex("int main(){x--;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, UpdateExpr)
        self.assertEqual(expr.op, "--")
        self.assertTrue(expr.is_postfix)
        self.assertIsInstance(expr.operand, Identifier)

    def test_prefix_and_postfix_update_precedence(self) -> None:
        unit = parse(list(lex("int main(){return ++x + y--; }")))
        expr = _body(unit.functions[0]).statements[0].value
        self.assertIsInstance(expr, BinaryExpr)
        self.assertIsInstance(expr.left, UpdateExpr)
        self.assertFalse(expr.left.is_postfix)
        self.assertIsInstance(expr.right, UpdateExpr)
        self.assertTrue(expr.right.is_postfix)

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

    def test_compound_assignment_expression(self) -> None:
        unit = parse(list(lex("int main(){x+=1;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, AssignExpr)
        self.assertEqual(expr.op, "+=")
        self.assertIsInstance(expr.target, Identifier)
        self.assertIsInstance(expr.value, IntLiteral)

    def test_compound_assignment_is_right_associative(self) -> None:
        unit = parse(list(lex("int main(){a+=b+=1;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, AssignExpr)
        self.assertEqual(expr.op, "+=")
        self.assertIsInstance(expr.value, AssignExpr)
        self.assertEqual(expr.value.op, "+=")

    def test_shift_compound_assignment_expression(self) -> None:
        unit = parse(list(lex("int main(){x<<=1;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, AssignExpr)
        self.assertEqual(expr.op, "<<=")

    def test_conditional_expression(self) -> None:
        unit = parse(list(lex("int main(){return 1?2:3;}")))
        expr = _body(unit.functions[0]).statements[0].value
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertIsInstance(expr.condition, IntLiteral)
        self.assertIsInstance(expr.then_expr, IntLiteral)
        self.assertIsInstance(expr.else_expr, IntLiteral)

    def test_conditional_is_right_associative(self) -> None:
        unit = parse(list(lex("int main(){return a?b:c?d:e;}")))
        expr = _body(unit.functions[0]).statements[0].value
        self.assertIsInstance(expr, ConditionalExpr)
        self.assertIsInstance(expr.else_expr, ConditionalExpr)

    def test_comma_expression(self) -> None:
        unit = parse(list(lex("int main(){x=1,2;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, CommaExpr)
        self.assertIsInstance(expr.left, AssignExpr)
        self.assertIsInstance(expr.right, IntLiteral)

    def test_comma_expression_precedence(self) -> None:
        unit = parse(list(lex("int main(){a=b, c=d;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ExprStmt)
        expr = stmt.expr
        self.assertIsInstance(expr, CommaExpr)
        self.assertIsInstance(expr.left, AssignExpr)
        self.assertIsInstance(expr.right, AssignExpr)

    def test_comma_expression_in_argument_requires_parentheses(self) -> None:
        source = "int f(int x,int y){return x+y;} int main(){return f((1,2),3);}"
        unit = parse(list(lex(source)))
        call = _body(unit.functions[1]).statements[0].value
        self.assertIsInstance(call, CallExpr)
        self.assertEqual(len(call.args), 2)
        self.assertIsInstance(call.args[0], CommaExpr)

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

    def test_tagged_enum_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){enum E { A, B=3, C }; return C;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec(
                "enum",
                enum_tag="E",
                enum_members=(("A", None), ("B", IntLiteral("3")), ("C", None)),
            ),
        )
        self.assertIsNone(stmt.name)
        self.assertIsNone(stmt.init)

    def test_enum_object_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){enum E x;return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("enum", enum_tag="E"))
        self.assertEqual(stmt.name, "x")
        self.assertIsNone(stmt.init)

    def test_unnamed_enum_object_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){enum { A=1, B } x;return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("enum", enum_members=(("A", IntLiteral("1")), ("B", None))),
        )
        self.assertEqual(stmt.name, "x")

    def test_enum_declaration_allows_trailing_comma(self) -> None:
        unit = parse(list(lex("int main(){enum { A, B, } x;return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("enum", enum_members=(("A", None), ("B", None))),
        )

    def test_enum_member_signed_value(self) -> None:
        unit = parse(list(lex("int main(){enum { A=-1, B=+2 } x;return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec(
                "enum",
                enum_members=(("A", UnaryExpr("-", IntLiteral("1"))), ("B", UnaryExpr("+", IntLiteral("2")))),
            ),
        )

    def test_pointer_to_enum_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){enum E *p;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("enum", 1, enum_tag="E"))

    def test_enum_member_value_constant_expression(self) -> None:
        unit = parse(list(lex("int main(){enum E { A=1<<2, B=A+1 } x;return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec(
                "enum",
                enum_tag="E",
                enum_members=(
                    ("A", BinaryExpr("<<", IntLiteral("1"), IntLiteral("2"))),
                    ("B", BinaryExpr("+", Identifier("A"), IntLiteral("1"))),
                ),
            ),
        )

    def test_tagged_struct_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){struct Node { int value; }; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec(
                "struct",
                record_tag="Node",
                record_members=((TypeSpec("int"), "value"),),
            ),
        )
        self.assertIsNone(stmt.name)
        self.assertIsNone(stmt.init)

    def test_tagged_struct_forward_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){struct Node;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("struct", record_tag="Node"))
        self.assertIsNone(stmt.name)

    def test_struct_object_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){struct Node { int value; } n; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec(
                "struct",
                record_tag="Node",
                record_members=((TypeSpec("int"), "value"),),
            ),
        )
        self.assertEqual(stmt.name, "n")

    def test_unnamed_struct_object_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){struct { int x; } v; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("struct", record_members=((TypeSpec("int"), "x"),)),
        )
        self.assertEqual(stmt.name, "v")

    def test_struct_pointer_to_incomplete_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){struct Node *next; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("struct", 1, record_tag="Node"))
        self.assertEqual(stmt.name, "next")

    def test_union_object_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){union Data { int x; int y; } d; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec(
                "union",
                record_tag="Data",
                record_members=((TypeSpec("int"), "x"), (TypeSpec("int"), "y")),
            ),
        )
        self.assertEqual(stmt.name, "d")

    def test_record_member_declaration_list(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x, y; } s; return s.x + s.y;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec(
                "struct",
                record_tag="S",
                record_members=((TypeSpec("int"), "x"), (TypeSpec("int"), "y")),
            ),
        )

    def test_pointer_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int *p;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 1))

    def test_char_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){char c;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("char"))

    def test_long_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){long value;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("long"))

    def test_short_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){short value;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("short"))

    def test_unsigned_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){unsigned value;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("unsigned int"))

    def test_unsigned_char_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){unsigned char c;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("unsigned char"))

    def test_unsigned_short_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){unsigned short value;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("unsigned short"))

    def test_long_int_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){long int value;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("long"))

    def test_long_long_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){long long value;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("long long"))

    def test_unsigned_long_long_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){unsigned long long value;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("unsigned long long"))

    def test_int_short_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int short value;return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("short"))

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
            TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", ((TypeSpec("int"),), False)))),
        )

    def test_function_pointer_declaration_with_two_params(self) -> None:
        unit = parse(list(lex("int main(){int (*fp)(int, int);return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", ((TypeSpec("int"), TypeSpec("int")), False)))),
        )

    def test_variadic_function_pointer_declaration(self) -> None:
        unit = parse(list(lex("int main(){int (*fp)(int, ...);return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", ((TypeSpec("int"),), True)))),
        )

    def test_variadic_function_pointer_requires_fixed_parameter(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int (*fp)(...);return 0;}")))

    def test_function_pointer_declaration_with_void_suffix(self) -> None:
        unit = parse(list(lex("int main(){int (*fp)(void);return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", ((), False)))),
        )

    def test_function_pointer_declaration_with_empty_suffix(self) -> None:
        unit = parse(list(lex("int main(){int (*fp)();return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", (None, False)))),
        )

    def test_array_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int a[4];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 0, (4,)))

    def test_multi_declarator_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){int a=1,b=a;return b;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclGroupStmt)
        first, second = stmt.declarations
        self.assertEqual(first, DeclStmt(TypeSpec("int"), "a", IntLiteral("1")))
        self.assertEqual(second.type_spec, TypeSpec("int"))
        self.assertEqual(second.name, "b")
        self.assertIsInstance(second.init, Identifier)

    def test_multi_typedef_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){typedef int T, U; T x=1; U y=2;return x+y;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclGroupStmt)
        self.assertEqual(
            stmt.declarations,
            [TypedefDecl(TypeSpec("int"), "T"), TypedefDecl(TypeSpec("int"), "U")],
        )

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

    def test_member_expression(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; } s;return s.x;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, MemberExpr)
        self.assertFalse(expr.through_pointer)
        self.assertEqual(expr.member, "x")

    def test_pointer_member_expression(self) -> None:
        unit = parse(list(lex("int main(){struct S { int x; } s;struct S *p=&s;return p->x;}")))
        stmt = _body(unit.functions[0]).statements[2]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, MemberExpr)
        self.assertTrue(expr.through_pointer)
        self.assertEqual(expr.member, "x")

    def test_sizeof_expression(self) -> None:
        unit = parse(list(lex("int main(){int x;return sizeof x;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, SizeofExpr)
        self.assertIsNotNone(expr.expr)
        self.assertIsNone(expr.type_spec)

    def test_sizeof_parenthesized_expression(self) -> None:
        unit = parse(list(lex("int main(){int x;return sizeof(x+1);}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, SizeofExpr)
        self.assertIsNotNone(expr.expr)

    def test_sizeof_type_name(self) -> None:
        unit = parse(list(lex("int main(){return sizeof(int*);}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, SizeofExpr)
        self.assertIsNone(expr.expr)
        self.assertEqual(expr.type_spec, TypeSpec("int", 1))

    def test_sizeof_unsigned_short_type_name(self) -> None:
        unit = parse(list(lex("int main(){return sizeof(unsigned short);}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, SizeofExpr)
        self.assertEqual(expr.type_spec, TypeSpec("unsigned short"))

    def test_sizeof_struct_type_name(self) -> None:
        unit = parse(list(lex("int main(){return sizeof(struct S { int x; });}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, SizeofExpr)
        self.assertIsNone(expr.expr)
        self.assertIsNotNone(expr.type_spec)

    def test_cast_expression(self) -> None:
        unit = parse(list(lex("int main(){int *p; return (int)p;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, CastExpr)
        self.assertEqual(expr.type_spec, TypeSpec("int"))
        self.assertIsInstance(expr.expr, Identifier)

    def test_unsigned_long_cast_expression(self) -> None:
        unit = parse(list(lex("int main(){int x; return (unsigned long)x;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, CastExpr)
        self.assertEqual(expr.type_spec, TypeSpec("unsigned long"))

    def test_unsigned_long_long_cast_expression(self) -> None:
        unit = parse(list(lex("int main(){int x; return (unsigned long long)x;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, CastExpr)
        self.assertEqual(expr.type_spec, TypeSpec("unsigned long long"))

    def test_nested_cast_expression(self) -> None:
        unit = parse(list(lex("int main(){int *p; return (int)(void*)p;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        outer_expr = stmt.value
        self.assertIsInstance(outer_expr, CastExpr)
        inner_expr = outer_expr.expr
        self.assertIsInstance(inner_expr, CastExpr)
        self.assertEqual(inner_expr.type_spec, TypeSpec("void", 1))

    def test_typedef_declaration_and_use(self) -> None:
        unit = parse(list(lex("int main(){typedef int T; T x=1; return (T)x;}")))
        typedef_stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(typedef_stmt, TypedefDecl)
        self.assertEqual(typedef_stmt.type_spec, TypeSpec("int"))
        self.assertEqual(typedef_stmt.name, "T")
        decl_stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(decl_stmt, DeclStmt)
        self.assertEqual(decl_stmt.type_spec, TypeSpec("int"))
        return_stmt = _body(unit.functions[0]).statements[2]
        self.assertIsInstance(return_stmt, ReturnStmt)
        return_expr = return_stmt.value
        self.assertIsInstance(return_expr, CastExpr)
        self.assertEqual(return_expr.type_spec, TypeSpec("int"))

    def test_typedef_name_in_sizeof_type_name(self) -> None:
        unit = parse(list(lex("int main(){typedef int T; return sizeof(T*);}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, SizeofExpr)
        self.assertEqual(expr.type_spec, TypeSpec("int", 1))

    def test_typedef_name_shadowed_by_local_object(self) -> None:
        unit = parse(list(lex("int main(){typedef int T; {int T=1; (T);} return 0;}")))
        block_stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(block_stmt, CompoundStmt)
        expr_stmt = block_stmt.statements[1]
        self.assertIsInstance(expr_stmt, ExprStmt)
        self.assertIsInstance(expr_stmt.expr, Identifier)

    def test_file_scope_typedef_only_translation_unit(self) -> None:
        unit = parse(list(lex("typedef int T;")))
        self.assertEqual(unit.functions, [])

    def test_file_scope_typedef_function_uses_alias(self) -> None:
        unit = parse(list(lex("typedef int T; T main(){T x=1; return x;}")))
        self.assertEqual(len(unit.functions), 1)
        func = unit.functions[0]
        self.assertEqual(func.return_type, TypeSpec("int"))
        decl_stmt = _body(func).statements[0]
        self.assertIsInstance(decl_stmt, DeclStmt)
        self.assertEqual(decl_stmt.type_spec, TypeSpec("int"))

    def test_file_scope_typedef_chain(self) -> None:
        unit = parse(list(lex("typedef int T; typedef T U; U main(){return 0;}")))
        self.assertEqual(len(unit.functions), 1)
        self.assertEqual(unit.functions[0].return_type, TypeSpec("int"))

    def test_file_scope_object_declaration(self) -> None:
        unit = parse(list(lex("int g; int main(){return g;}")))
        self.assertEqual(len(unit.functions), 1)
        self.assertEqual(len(unit.declarations), 1)
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, DeclStmt)
        self.assertEqual(declaration.type_spec, TypeSpec("int"))
        self.assertEqual(declaration.name, "g")
        self.assertIsNone(declaration.init)

    def test_file_scope_object_declaration_with_initializer(self) -> None:
        unit = parse(list(lex("int g=1; int main(){return g;}")))
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, DeclStmt)
        self.assertEqual(declaration.name, "g")
        self.assertIsNotNone(declaration.init)

    def test_file_scope_declaration_between_functions(self) -> None:
        source = "int f(void){return 0;} int g=1; int main(){return g+f();}"
        unit = parse(list(lex(source)))
        self.assertEqual(len(unit.functions), 2)
        self.assertEqual(len(unit.declarations), 1)

    def test_translation_unit_tracks_external_order(self) -> None:
        source = "struct S { int x; }; struct S f(void); int g;"
        unit = parse(list(lex(source)))
        self.assertEqual(len(unit.externals), 3)
        self.assertIsInstance(unit.externals[0], DeclStmt)
        self.assertIsInstance(unit.externals[1], FunctionDef)
        self.assertIsInstance(unit.externals[2], DeclStmt)

    def test_translation_unit_groups_multi_declarator_external(self) -> None:
        source = "int x=1, y=2; int main(){return x+y;}"
        unit = parse(list(lex(source)))
        self.assertEqual(len(unit.externals), 2)
        self.assertIsInstance(unit.externals[0], DeclGroupStmt)

    def test_array_size_must_be_positive(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int a[0];return 0;}")))

    def test_array_size_accepts_hex_literal(self) -> None:
        unit = parse(list(lex("int main(){int a[0x10];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 0, (16,)))

    def test_array_size_accepts_octal_literal(self) -> None:
        unit = parse(list(lex("int main(){int a[012];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 0, (10,)))

    def test_array_size_accepts_unsigned_suffix(self) -> None:
        unit = parse(list(lex("int main(){int a[10U];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 0, (10,)))

    def test_array_size_accepts_additive_constant_expression(self) -> None:
        unit = parse(list(lex("int main(){int a[1073741820U + 5U - 1U];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 0, (1073741824,)))

    def test_array_size_accepts_shift_constant_expression(self) -> None:
        unit = parse(list(lex("int main(){int a[1LL<<4];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 0, (16,)))

    def test_array_size_accepts_sizeof_typedef_cast_expression(self) -> None:
        source = "int main(){typedef char a[1LL<<61]; char b[(long long)sizeof(a)-1]; return 0;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("char", 0, (2305843009213693951,)))

    def test_array_size_accepts_sizeof_int_shift_expression(self) -> None:
        source = "int main(){int a[(long long)sizeof(int)<<1]; return 0;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 0, (8,)))

    def test_array_size_accepts_sizeof_pointer_expression(self) -> None:
        source = "int main(){char a[(long long)sizeof(int*)]; return 0;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("char", 0, (8,)))

    def test_array_size_must_be_positive_after_literal_conversion(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int a[0x0u];return 0;}")))

    def test_array_size_helper_rejects_invalid_literals(self) -> None:
        self.assertIsNone(_parse_int_literal_value("1uu"))
        self.assertIsNone(_parse_int_literal_value("08"))
        self.assertIsNone(_parse_int_literal_value("abc"))

    def test_array_size_rejects_non_string_or_invalid_literal_tokens(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        self.assertEqual(parser._parse_array_size(Token(TokenKind.INT_CONST, "1", 1, 1)), 1)
        with self.assertRaises(ParserError):
            parser._parse_array_size(Token(TokenKind.INT_CONST, "0", 1, 1))
        with self.assertRaises(ParserError):
            parser._parse_array_size(Token(TokenKind.INT_CONST, None, 1, 1))
        with self.assertRaises(ParserError):
            parser._parse_array_size(Token(TokenKind.INT_CONST, "1uu", 1, 1))

    def test_array_size_rejects_non_constant_expression(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int n=4;int a[n];return 0;}")))

    def test_array_size_rejects_negative_shift_amount(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int a[1<<-1];return 0;}")))

    def test_array_size_rejects_unary_non_constant_expression(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int n=4;int a[+n];return 0;}")))

    def test_array_size_rejects_unsupported_binary_operator_expression(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int a[4/2];return 0;}")))

    def test_array_size_rejects_sizeof_void_expression(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int a[(long long)sizeof(void)];return 0;}")))

    def test_array_size_helper_handles_sizeof_expression_forms(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        self.assertIsNone(parser._eval_array_size_expr(SizeofExpr(Identifier("x"), None)))
        self.assertIsNone(
            parser._eval_array_size_expr(
                SizeofExpr(None, TypeSpec("struct", record_tag="S", record_members=((TypeSpec("int"), "x"),)))
            )
        )
        self.assertEqual(parser._eval_array_size_expr(SizeofExpr(None, TypeSpec("int", 1))), 8)
        self.assertIsNone(
            parser._eval_array_size_expr(
                SizeofExpr(None, TypeSpec("int", declarator_ops=(("fn", (None, False)),)))
            )
        )

    def test_array_size_helper_binary_with_non_constant_operand(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        expr = BinaryExpr("+", Identifier("x"), IntLiteral("1"))
        self.assertIsNone(parser._eval_array_size_expr(expr))

    def test_void_declaration_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){void x;return 0;}")))

    def test_void_array_declaration_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){void x[1];return 0;}")))

    def test_missing_declarator_in_declaration(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int ;return 0;}")))

    def test_parenthesized_missing_declarator_in_declaration(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int ();return 0;}")))

    def test_enum_requires_tag_or_definition(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){enum ;return 0;}")))

    def test_empty_enum_definition_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){enum E {};return 0;}")))

    def test_enum_without_declarator_rejects_initializer(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){enum E = 1;return 0;}")))

    def test_enum_value_allows_non_decimal_constant_expression(self) -> None:
        unit = parse(list(lex("int main(){enum E { A=0x10 };return A;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("enum", enum_tag="E", enum_members=(("A", IntLiteral("0x10")),)))

    def test_struct_requires_tag_or_definition(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){struct ;return 0;}")))

    def test_union_requires_tag_or_definition(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){union ;return 0;}")))

    def test_empty_struct_definition_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){struct S {};return 0;}")))

    def test_empty_union_definition_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){union U {};return 0;}")))

    def test_struct_without_declarator_rejects_initializer(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){struct S = 1;return 0;}")))

    def test_invalid_void_struct_member_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){struct S { void x; };return 0;}")))

    def test_parenthesized_missing_struct_member_declarator(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){struct S { int (); };return 0;}")))

    def test_member_expression_missing_identifier_after_dot(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){struct S { int x; } s;return s.;}")))

    def test_member_expression_missing_identifier_after_arrow(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){struct S { int x; } s;struct S *p=&s;return p->;}")))

    def test_sizeof_type_name_rejects_identifier(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){return sizeof(int x);}")))

    def test_cast_type_name_rejects_identifier(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int x; return (int y)x;}")))

    def test_typedef_requires_identifier(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){typedef int;}")))

    def test_typedef_initializer_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){typedef int T=1;}")))

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

    def test_statement_outside_function(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("while(1){}")))
        self.assertEqual(ctx.exception.message, "while statement outside of a function")
        self.assertEqual((ctx.exception.token.line, ctx.exception.token.column), (1, 1))

    def test_long_long_long_type_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){long long long value;return 0;}")))

    def test_short_long_type_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){short long value;return 0;}")))

    def test_duplicate_signedness_type_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){unsigned signed value;return 0;}")))

    def test_duplicate_short_type_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){short short value;return 0;}")))

    def test_char_after_int_type_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int char value;return 0;}")))

    def test_int_after_char_type_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){char int value;return 0;}")))

    def test_non_type_keyword_after_type_spec_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int static value;return 0;}")))

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
