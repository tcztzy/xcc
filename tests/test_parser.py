import unittest

from tests import _bootstrap  # noqa: F401
from xcc.ast import (
    AlignofExpr,
    ArrayDecl,
    AssignExpr,
    BinaryExpr,
    BreakStmt,
    CaseStmt,
    CallExpr,
    CastExpr,
    CharLiteral,
    CompoundStmt,
    CompoundLiteralExpr,
    ContinueStmt,
    ConditionalExpr,
    CommaExpr,
    DeclGroupStmt,
    DeclStmt,
    DefaultStmt,
    DoWhileStmt,
    ExprStmt,
    FloatLiteral,
    ForStmt,
    FunctionDef,
    GotoStmt,
    Identifier,
    IndirectGotoStmt,
    InitItem,
    InitList,
    IfStmt,
    IntLiteral,
    LabelAddressExpr,
    LabelStmt,
    MemberExpr,
    NullStmt,
    Param,
    RecordMemberDecl,
    ReturnStmt,
    SizeofExpr,
    StaticAssertDecl,
    StatementExpr,
    StringLiteral,
    SubscriptExpr,
    SwitchStmt,
    GenericExpr,
    TypedefDecl,
    TypeSpec,
    UnaryExpr,
    UpdateExpr,
    WhileStmt,
)
from xcc.lexer import Token, TokenKind, lex
from xcc.parser import (
    Parser,
    ParserError,
    _array_size_non_ice_error,
    _parse_int_literal_value,
    parse,
)


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

    def test_leading_type_qualifiers_are_recorded_in_declarations(self) -> None:
        unit = parse(list(lex("int main(void){const int x=0; return x;}")))
        statements = _body(unit.functions[0]).statements
        self.assertIsInstance(statements[0], DeclStmt)
        self.assertEqual(statements[0].type_spec, TypeSpec("int", qualifiers=("const",)))

    def test_duplicate_leading_type_qualifiers_are_rejected(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(void){const const int x=0; return x;}")))
        self.assertEqual(ctx.exception.message, "Duplicate type qualifier: 'const'")

    def test_sizeof_parenthesized_type_name_allows_type_qualifier(self) -> None:
        unit = parse(list(lex("int main(void){return sizeof(const int*);}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        self.assertIsInstance(stmt.value, SizeofExpr)
        self.assertEqual(stmt.value.type_spec, TypeSpec("int", pointer_depth=1, qualifiers=("const",)))

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
        unit = parse(
            list(lex("int main(void){void *target=0; goto *target; return 0;}")),
            std="gnu11",
        )
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, IndirectGotoStmt)
        self.assertIsInstance(stmt.target, Identifier)
        self.assertEqual(stmt.target.name, "target")

    def test_label_address_expression(self) -> None:
        unit = parse(
            list(lex("int main(void){void *target = &&done; goto *target; done: return 0;}")),
            std="gnu11",
        )
        decl = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(decl, DeclStmt)
        self.assertIsInstance(decl.init, LabelAddressExpr)
        self.assertEqual(decl.init.label, "done")

    def test_statement_expression_in_for_init(self) -> None:
        source = "int main(void){for(({int x=0; x;});;); return 0;}"
        unit = parse(list(lex(source)), std="gnu11")
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ForStmt)
        self.assertIsInstance(stmt.init, StatementExpr)
        self.assertEqual(len(stmt.init.body.statements), 2)

    def test_c11_rejects_indirect_goto_statement(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(void){void *target=0; goto *target; return 0;}")), std="c11")
        self.assertEqual(ctx.exception.message, "Indirect goto is a GNU extension")

    def test_c11_rejects_label_address_expression(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(
                list(lex("int main(void){void *target = &&done; goto *target; done: return 0;}")),
                std="c11",
            )
        self.assertEqual(ctx.exception.message, "Label address is a GNU extension")

    def test_c11_rejects_statement_expression(self) -> None:
        source = "int main(void){for(({int x=0; x;});;); return 0;}"
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex(source)), std="c11")
        self.assertEqual(ctx.exception.message, "Statement expression is a GNU extension")

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

    def test_float_literal_expression(self) -> None:
        unit = parse(list(lex("double main(){return 1.0f;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, FloatLiteral)
        self.assertEqual(expr.value, "1.0f")

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

    def test_designated_array_initializer(self) -> None:
        unit = parse(list(lex("int main(){int a[4] = {[2] = 3}; return a[2];}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        init = stmt.init
        self.assertIsInstance(init, InitList)
        self.assertEqual(len(init.items), 1)
        item = init.items[0]
        self.assertIsInstance(item, InitItem)
        self.assertEqual(item.designators, (("index", IntLiteral("2")),))
        self.assertIsInstance(item.initializer, IntLiteral)

    def test_designated_struct_initializer(self) -> None:
        source = "int main(){struct S { int x; int y; } s = { .y = 2, .x = 1 }; return s.x + s.y;}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        init = stmt.init
        self.assertIsInstance(init, InitList)
        self.assertEqual(len(init.items), 2)
        self.assertEqual(init.items[0].designators, (("member", "y"),))
        self.assertEqual(init.items[1].designators, (("member", "x"),))

    def test_initializer_list_without_designator(self) -> None:
        unit = parse(list(lex("int main(){int a[2] = {1, 2}; return a[0];}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        init = stmt.init
        self.assertIsInstance(init, InitList)
        self.assertEqual(init.items[0].designators, ())

    def test_initializer_list_allows_trailing_comma(self) -> None:
        unit = parse(list(lex("int main(){int a[2] = {1,}; return a[0];}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertIsInstance(stmt.init, InitList)

    def test_empty_initializer_list_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){int a[1] = {}; return 0;}")))

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

    def test_bool_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){_Bool flag; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("_Bool"))

    def test_noreturn_function_definition(self) -> None:
        unit = parse(list(lex("_Noreturn int f(void){return 1;}")))
        function = unit.functions[0]
        self.assertEqual(function.name, "f")
        self.assertEqual(function.return_type, TypeSpec("int"))

    def test_thread_local_file_scope_declaration(self) -> None:
        unit = parse(list(lex("_Thread_local int g;")))
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, DeclStmt)
        self.assertEqual(declaration.type_spec, TypeSpec("int"))
        self.assertEqual(declaration.name, "g")

    def test_alignas_constant_expression_declaration(self) -> None:
        unit = parse(list(lex("int main(void){_Alignas(16) int x; return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int"))
        self.assertEqual(stmt.name, "x")
        self.assertEqual(stmt.alignment, 16)

    def test_alignas_type_name_declaration(self) -> None:
        unit = parse(list(lex("int main(void){_Alignas(int) int x; return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int"))
        self.assertEqual(stmt.name, "x")
        self.assertEqual(stmt.alignment, 4)

    def test_alignas_rejects_function_definition(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("_Alignas(16) int f(void){return 1;}")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_alignas_rejects_function_declaration(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("_Alignas(16) int f(void);")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_alignas_rejects_typedef_declaration(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("typedef _Alignas(16) int I;")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_alignas_rejects_parameter_declaration(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int f(_Alignas(8) int x){return x;}")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_alignas_rejects_file_scope_tag_only_declaration(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("_Alignas(16) struct S; int main(void){return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_alignas_rejects_block_scope_tag_only_declaration(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(void){_Alignas(16) struct S; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_alignas_rejects_named_type_name(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(void){_Alignas(int x) int y; return y;}")))

    def test_alignas_rejects_non_power_of_two_constant(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(void){_Alignas(3) int x; return x;}")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_alignas_rejects_non_positive_constant(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(void){_Alignas(0) int x; return x;}")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_alignas_rejects_void_type_name(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(void){_Alignas(void) int x; return x;}")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_alignas_accepts_constant_expression(self) -> None:
        unit = parse(list(lex("int main(void){_Alignas(1<<4) int x; return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int"))
        self.assertEqual(stmt.alignment, 16)

    def test_alignas_uses_stricter_alignment_from_multiple_specifiers(self) -> None:
        unit = parse(list(lex("int main(void){_Alignas(8) _Alignas(16) int x; return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.alignment, 16)

    def test_alignas_keeps_existing_stricter_alignment(self) -> None:
        unit = parse(list(lex("int main(void){_Alignas(16) _Alignas(8) int x; return x;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.alignment, 16)

    def test_alignas_record_member_declaration(self) -> None:
        unit = parse(list(lex("struct S {_Alignas(16) int x;};")))
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, DeclStmt)
        self.assertEqual(declaration.type_spec.record_members[0].name, "x")
        self.assertEqual(declaration.type_spec.record_members[0].alignment, 16)

    def test_alignas_record_member_uses_stricter_alignment(self) -> None:
        unit = parse(list(lex("struct S {_Alignas(8) _Alignas(16) int x;};")))
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, DeclStmt)
        self.assertEqual(declaration.type_spec.record_members[0].alignment, 16)

    def test_alignas_rejects_member_tag_only_declaration(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("struct S {_Alignas(16) struct T;};")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_alignas_rejects_member_function_declaration(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("struct S {_Alignas(16) int f(void);};")))
        self.assertEqual(ctx.exception.message, "Invalid alignment specifier")

    def test_record_member_rejects_typedef_specifier(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("struct S { typedef int T; };")))
        self.assertEqual(ctx.exception.message, "Expected type specifier")

    def test_record_member_rejects_missing_declarator(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("struct S { int; };")))
        self.assertEqual(ctx.exception.message, "Expected identifier")

    def test_unsupported_type_uses_declaration_context_diagnostic(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("_Complex int value;")))
        self.assertEqual(ctx.exception.message, "Unsupported declaration type: '_Complex'")

    def test_unsupported_type_uses_type_name_context_diagnostic(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(void){ return sizeof(_Complex int); }")))
        self.assertEqual(ctx.exception.message, "Unsupported type name: '_Complex'")

    def test_unknown_identifier_type_uses_declaration_context_diagnostic(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("foo value;")))
        self.assertEqual(ctx.exception.message, "Unknown declaration type name: 'foo'")

    def test_unknown_identifier_type_uses_type_name_context_diagnostic(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(void){ int x = 0; return _Generic(x, foo: 1, default: 0); }")))
        self.assertEqual(ctx.exception.message, "Unknown type name: 'foo'")

    def test_integer_type_rejects_duplicate_signedness(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("unsigned signed int value;")))
        self.assertEqual(
            ctx.exception.message,
            "Duplicate integer signedness specifier: 'signed'",
        )

    def test_integer_type_rejects_invalid_keyword_order_in_declaration(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("short char value;")))
        self.assertEqual(
            ctx.exception.message,
            "Invalid integer type keyword order: 'char' after 'short'",
        )

    def test_integer_type_rejects_invalid_keyword_order_in_type_name(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(void){ return sizeof(short char); }")))
        self.assertEqual(
            ctx.exception.message,
            "Invalid integer type keyword order: 'char' after 'short'",
        )

    def test_typespec_normalizes_legacy_record_member_with_alignment(self) -> None:
        record_type = TypeSpec("struct", record_members=((TypeSpec("int"), "x", 16),))
        self.assertEqual(record_type.record_members[0], RecordMemberDecl(TypeSpec("int"), "x", 16))

    def test_typespec_rejects_invalid_record_member_tuple(self) -> None:
        with self.assertRaises(TypeError):
            TypeSpec("struct", record_members=(("x",),))  # type: ignore[arg-type]

    def test_atomic_qualified_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){_Atomic int value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", is_atomic=True))

    def test_atomic_type_specifier_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){_Atomic(int) value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", is_atomic=True))

    def test_atomic_type_specifier_pointer_declaration_statement(self) -> None:
        unit = parse(list(lex("int main(){_Atomic(int) *value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 1, is_atomic=True))

    def test_atomic_qualified_declaration_statement_idempotent(self) -> None:
        unit = parse(list(lex("int main(){_Atomic _Atomic int value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", is_atomic=True))

    def test_atomic_qualified_over_atomic_type_specifier_is_idempotent(self) -> None:
        unit = parse(list(lex("int main(){_Atomic _Atomic(int) value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", is_atomic=True))

    def test_atomic_qualified_array_of_atomic_elements_is_allowed(self) -> None:
        unit = parse(list(lex("int main(){_Atomic int values[2]; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", array_lengths=(2,), is_atomic=True))

    def test_atomic_qualified_typedef_array_is_rejected(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("typedef int Arr[2]; int main(){_Atomic Arr values; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: array")

    def test_atomic_qualified_typedef_function_is_rejected(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("typedef int Fn(void); int main(){_Atomic Fn value; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: function")

    def test_atomic_type_specifier_rejects_typedef_array(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("typedef int Arr[2]; int main(){_Atomic(Arr) values; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: array")

    def test_atomic_type_specifier_rejects_typedef_function(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("typedef int Fn(void); int main(){_Atomic(Fn) value; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: function")

    def test_atomic_type_specifier_rejects_named_type_name(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){_Atomic(int value) x; return 0;}")))

    def test_atomic_type_specifier_rejects_array_type_name(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(){_Atomic(int [2]) value; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: array")

    def test_atomic_type_specifier_accepts_pointer_to_function_type_name(self) -> None:
        unit = parse(list(lex("int main(){_Atomic(int (*)(void)) value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec,
            TypeSpec("int", declarator_ops=(("ptr", 0), ("fn", ((), False))), is_atomic=True),
        )

    def test_atomic_type_specifier_rejects_atomic_typedef(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("typedef _Atomic(int) A; int main(){_Atomic(A) value; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: atomic")

    def test_atomic_type_specifier_rejects_qualified_typedef_alias(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("typedef const int CI; int main(){_Atomic(CI) value; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: qualified")

    def test_atomic_type_specifier_rejects_transitive_qualified_typedef_alias(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(
                list(
                    lex(
                        "typedef const int CI; typedef CI C2;"
                        "int main(){_Atomic(C2) value; return 0;}"
                    )
                )
            )
        self.assertEqual(ctx.exception.message, "Invalid atomic type: qualified")

    def test_atomic_type_specifier_rejects_pointer_qualified_typedef_alias(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("typedef int *const CP; int main(){_Atomic(CP) value; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: qualified")

    def test_atomic_type_specifier_rejects_transitive_pointer_qualified_typedef_alias(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(
                list(
                    lex(
                        "typedef int *const CP; typedef CP C2;"
                        "int main(){_Atomic(C2) value; return 0;}"
                    )
                )
            )
        self.assertEqual(ctx.exception.message, "Invalid atomic type: qualified")

    def test_atomic_type_specifier_accepts_pointer_to_qualified_typedef_alias(self) -> None:
        unit = parse(list(lex("typedef const int CI; int main(){_Atomic(CI *) value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 1, qualifiers=("const",), is_atomic=True))

    def test_atomic_type_specifier_accepts_unqualified_pointer_typedef_alias(self) -> None:
        unit = parse(list(lex("typedef const int *PCI; int main(){_Atomic(PCI) value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 1, qualifiers=("const",), is_atomic=True))

    def test_atomic_qualified_pointer_typedef_declaration(self) -> None:
        unit = parse(list(lex("typedef int *_Atomic AtomicIntPtr;")))
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, TypedefDecl)
        self.assertEqual(declaration.type_spec, TypeSpec("int", 1))

    def test_atomic_qualified_parenthesized_pointer_typedef_declaration(self) -> None:
        unit = parse(list(lex("typedef int (*_Atomic AtomicIntPtr);")))
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, TypedefDecl)
        self.assertEqual(declaration.type_spec, TypeSpec("int", 1))

    def test_atomic_qualified_before_pointer_typedef_declaration(self) -> None:
        unit = parse(list(lex("typedef int _Atomic *AtomicIntPtr;")))
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, TypedefDecl)
        self.assertEqual(declaration.type_spec, TypeSpec("int", 1))

    def test_atomic_type_specifier_accepts_transitive_unqualified_pointer_typedef_alias(self) -> None:
        unit = parse(
            list(
                lex("typedef const int CI; typedef CI *PCI; int main(){_Atomic(PCI) value; return 0;}")
            )
        )
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 1, qualifiers=("const",), is_atomic=True))

    def test_atomic_type_specifier_rejects_shadowed_typedef_name(self) -> None:
        source = "typedef const int CI; int main(){int CI=0; _Atomic(CI) value; return value;}"
        with self.assertRaises(ParserError):
            parse(list(lex(source)))

    def test_atomic_type_specifier_rejects_unknown_identifier_type_name(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){_Atomic(UnknownType) value; return 0;}")))

    def test_atomic_type_specifier_rejects_qualified_scalar_type(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(){_Atomic(const int) value; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: qualified")

    def test_atomic_type_specifier_rejects_trailing_qualified_scalar_type(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(){_Atomic(int const) value; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: qualified")

    def test_atomic_type_specifier_rejects_qualified_pointer_type(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(){_Atomic(int *const) value; return 0;}")))
        self.assertEqual(ctx.exception.message, "Invalid atomic type: qualified")

    def test_atomic_type_specifier_accepts_pointer_to_qualified_type(self) -> None:
        unit = parse(list(lex("int main(){_Atomic(const int *) value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 1, qualifiers=("const",), is_atomic=True))

    def test_atomic_type_specifier_accepts_pointer_to_qualified_pointer_type(self) -> None:
        unit = parse(list(lex("int main(){_Atomic(int *const *) value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 2, is_atomic=True))

    def test_atomic_type_specifier_rejects_atomic_qualified_pointer_type(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){_Atomic(int *_Atomic) value; return 0;}")))

    def test_atomic_type_specifier_accepts_pointer_to_atomic_qualified_pointer_type(self) -> None:
        unit = parse(list(lex("int main(){_Atomic(int *_Atomic *) value; return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 2, is_atomic=True))

    def test_atomic_typedef_ignores_gnu_attribute_before_name(self) -> None:
        unit = parse(
            list(lex("typedef _Atomic int __attribute__((address_space(1))) AtomicAddrInt;"))
        )
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, TypedefDecl)
        self.assertEqual(declaration.type_spec, TypeSpec("int", is_atomic=True))

    def test_atomic_typedef_ignores_gnu_attribute_inside_type_name(self) -> None:
        unit = parse(
            list(lex("typedef _Atomic(int __attribute__((vector_size(16)))) AtomicVectorInt;"))
        )
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, TypedefDecl)
        self.assertEqual(declaration.type_spec, TypeSpec("int", is_atomic=True))

    def test_atomic_typedef_ignores_gnu_attribute_after_name(self) -> None:
        unit = parse(
            list(lex("typedef _Atomic(int) AtomicInt __attribute__((address_space(1)));"))
        )
        declaration = unit.declarations[0]
        self.assertIsInstance(declaration, TypedefDecl)
        self.assertEqual(declaration.type_spec, TypeSpec("int", is_atomic=True))

    def test_function_declaration_marks_overloadable_attribute_before_name(self) -> None:
        unit = parse(list(lex("int __attribute__((overloadable)) test(int);")))
        self.assertTrue(unit.functions[0].is_overloadable)

    def test_function_declaration_marks_overloadable_attribute_after_name(self) -> None:
        unit = parse(list(lex("int test __attribute__((overloadable))(int);")))
        self.assertTrue(unit.functions[0].is_overloadable)

    def test_unterminated_gnu_attribute_reports_parser_error(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("typedef _Atomic int __attribute__((address_space(1)) Ptr;")))

    def test_atomic_keyword_requires_following_type(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(void){_Atomic; return 0;}")))

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

    def test_alignof_type_name(self) -> None:
        unit = parse(list(lex("int main(){return _Alignof(int*);}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, AlignofExpr)
        self.assertIsNone(expr.expr)
        self.assertEqual(expr.type_spec, TypeSpec("int", 1))

    def test_alignof_expression(self) -> None:
        unit = parse(list(lex("int main(){int x; return _Alignof(x);}")), std="gnu11")
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, AlignofExpr)
        self.assertIsNotNone(expr.expr)
        self.assertIsNone(expr.type_spec)

    def test_alignof_expression_rejected_in_c11(self) -> None:
        with self.assertRaises(ParserError) as ctx:
            parse(list(lex("int main(){int x; return _Alignof(x);}")), std="c11")
        self.assertEqual(ctx.exception.message, "Invalid alignof operand")

    def test_generic_selection_expression(self) -> None:
        unit = parse(list(lex("int main(){int x=0; return _Generic(x, int: 1, default: 2);}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, GenericExpr)
        self.assertEqual(len(expr.associations), 2)
        self.assertEqual(expr.associations[0][0], TypeSpec("int"))
        self.assertIsNone(expr.associations[1][0])

    def test_generic_selection_function_pointer_association(self) -> None:
        source = "int f(void){return 0;} int main(void){return _Generic(f, int(*)(void): 1, default: 2);}"
        unit = parse(list(lex(source)))
        stmt = _body(unit.functions[1]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, GenericExpr)
        assoc_type = expr.associations[0][0]
        self.assertIsNotNone(assoc_type)
        assert assoc_type is not None
        self.assertEqual(assoc_type.name, "int")
        self.assertEqual(assoc_type.declarator_ops[0], ("ptr", 0))
        self.assertEqual(assoc_type.declarator_ops[1], ("fn", ((), False)))
        self.assertIsNone(expr.associations[1][0])

    def test_generic_selection_allows_vla_type_name_in_parser(self) -> None:
        unit = parse(list(lex("int f(int n){return _Generic(0, int[n]: 1, default: 2);}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, GenericExpr)
        assoc_type = expr.associations[0][0]
        self.assertIsNotNone(assoc_type)
        assert assoc_type is not None
        self.assertEqual(
            assoc_type.declarator_ops,
            (("arr", ArrayDecl(Identifier("n"))),),
        )

    def test_cast_expression(self) -> None:
        unit = parse(list(lex("int main(){int *p; return (int)p;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, CastExpr)
        self.assertEqual(expr.type_spec, TypeSpec("int"))
        self.assertIsInstance(expr.expr, Identifier)

    def test_function_specifiers_and_storage_are_recorded(self) -> None:
        unit = parse(list(lex("static inline _Noreturn int f(void);")))
        func = unit.functions[0]
        self.assertEqual(func.storage_class, "static")
        self.assertTrue(func.is_inline)
        self.assertTrue(func.is_noreturn)

    def test_decl_stmt_storage_class_is_recorded(self) -> None:
        unit = parse(list(lex("extern int g;")))
        decl = unit.declarations[0]
        self.assertIsInstance(decl, DeclStmt)
        self.assertEqual(decl.storage_class, "extern")

    def test_parameter_array_static_qualifier(self) -> None:
        unit = parse(list(lex("int f(int a[static const 4]){return a[0];}")))
        param_type = unit.functions[0].params[0].type_spec
        self.assertEqual(
            param_type.declarator_ops,
            (("arr", ArrayDecl(IntLiteral("4"), ("const",), True)),),
        )

    def test_compound_literal_expression(self) -> None:
        unit = parse(list(lex("int main(void){return ((int){1});}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, ReturnStmt)
        expr = stmt.value
        self.assertIsInstance(expr, CompoundLiteralExpr)
        self.assertEqual(expr.type_spec, TypeSpec("int"))

    def test_bit_field_member_declaration(self) -> None:
        unit = parse(list(lex("struct S { unsigned x:3; unsigned :0; };")))
        decl = unit.declarations[0]
        self.assertIsInstance(decl, DeclStmt)
        member0 = decl.type_spec.record_members[0]
        member1 = decl.type_spec.record_members[1]
        self.assertEqual(member0.name, "x")
        self.assertEqual(member0.bit_width_expr, IntLiteral("3"))
        self.assertIsNone(member1.name)
        self.assertEqual(member1.bit_width_expr, IntLiteral("0"))

    def test_parameter_rejects_non_register_storage_class(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int f(static int x){return x;}")))

    def test_parameter_rejects_thread_local_specifier(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int f(_Thread_local int x){return x;}")))

    def test_record_member_rejects_function_specifier(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("struct S { inline int x; };")))

    def test_typedef_rejects_function_specifier(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("typedef inline int T;")))

    def test_array_declarator_rejects_missing_static_bound(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int f(int a[static]){return 0;}")))

    def test_array_parameter_allows_unsized_declarator(self) -> None:
        unit = parse(list(lex("int f(int a[]){return 0;}")))
        self.assertEqual(unit.functions[0].params[0].type_spec.declarator_ops, (("arr", ArrayDecl(None)),))
        unit = parse(list(lex("int f(int a[const volatile 4]){return 0;}")))
        self.assertEqual(
            unit.functions[0].params[0].type_spec.declarator_ops,
            (("arr", ArrayDecl(IntLiteral("4"), ("const", "volatile"), False)),),
        )

    def test_array_size_helpers_cover_error_paths(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        with self.assertRaisesRegex(
            ParserError, "Array size identifier 'n' is not an integer constant expression"
        ):
            parser._parse_array_size_expr(Identifier("n"), Token(TokenKind.IDENT, "n", 1, 1))
        with self.assertRaisesRegex(
            ParserError,
            "Array size unary operator '\\+' is not an integer constant expression",
        ):
            parser._parse_array_size_expr(
                UnaryExpr("+", Identifier("n")),
                Token(TokenKind.PUNCTUATOR, "+", 1, 1),
            )
        with self.assertRaisesRegex(
            ParserError,
            "Array size binary operator '\\*' is not an integer constant expression",
        ):
            parser._parse_array_size_expr(
                BinaryExpr("*", IntLiteral("1"), IntLiteral("n")),
                Token(TokenKind.PUNCTUATOR, "*", 1, 1),
            )
        with self.assertRaisesRegex(
            ParserError, "Array size call expression is not an integer constant expression"
        ):
            parser._parse_array_size_expr(
                CallExpr(Identifier("f"), []),
                Token(TokenKind.IDENT, "f", 1, 1),
            )
        with self.assertRaisesRegex(
            ParserError,
            "Array size generic selection is not an integer constant expression",
        ):
            parser._parse_array_size_expr(
                GenericExpr(IntLiteral("0"), ((TypeSpec("long"), IntLiteral("1")),)),
                Token(TokenKind.PUNCTUATOR, "_Generic", 1, 1),
            )
        with self.assertRaisesRegex(
            ParserError,
            "Array size comma expression is not an integer constant expression",
        ):
            parser._parse_array_size_expr(
                CommaExpr(IntLiteral("1"), Identifier("n")),
                Token(TokenKind.PUNCTUATOR, ",", 1, 1),
            )
        with self.assertRaisesRegex(
            ParserError,
            "Array size conditional condition is not an integer constant expression",
        ):
            parser._parse_array_size_expr(
                ConditionalExpr(Identifier("n"), IntLiteral("1"), IntLiteral("2")),
                Token(TokenKind.PUNCTUATOR, "?", 1, 1),
            )
        with self.assertRaisesRegex(
            ParserError,
            "Array size identifier 'n' is not an integer constant expression",
        ):
            parser._parse_array_size_expr(
                CastExpr(TypeSpec("int"), Identifier("n")),
                Token(TokenKind.PUNCTUATOR, "(", 1, 1),
            )
        with self.assertRaisesRegex(ParserError, "Array size must be positive"):
            parser._parse_array_size_expr(IntLiteral("0"), Token(TokenKind.INT_CONST, "0", 1, 1))
        self.assertEqual(parser._parse_array_size_expr_or_vla(Identifier("n"), Token(TokenKind.IDENT, "n", 1, 1)), -1)

    def test_sizeof_type_spec_handles_array_decl_forms(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        self.assertIsNone(parser._sizeof_type_spec(TypeSpec("int", declarator_ops=(("arr", object()),))))
        self.assertIsNone(
            parser._sizeof_type_spec(TypeSpec("int", declarator_ops=(("arr", ArrayDecl(None)),)))
        )
        self.assertIsNone(
            parser._sizeof_type_spec(TypeSpec("int", declarator_ops=(("arr", ArrayDecl(IntLiteral("n"))),)))
        )
        self.assertIsNone(
            parser._sizeof_type_spec(TypeSpec("int", declarator_ops=(("arr", ArrayDecl(IntLiteral("0"))),)))
        )
        self.assertEqual(
            parser._sizeof_type_spec(TypeSpec("int", declarator_ops=(("arr", ArrayDecl(2)),))),
            8,
        )
        self.assertEqual(
            parser._sizeof_type_spec(TypeSpec("int", declarator_ops=(("arr", ArrayDecl(IntLiteral("2"))),))),
            8,
        )

    def test_decl_specifier_duplicate_errors(self) -> None:
        with self.assertRaisesRegex(
            ParserError, "Duplicate storage class specifier: 'extern'"
        ):
            parse(list(lex("static extern int x;")))
        with self.assertRaisesRegex(
            ParserError, "Duplicate thread-local specifier: '_Thread_local'"
        ):
            parse(list(lex("_Thread_local _Thread_local int x;")))
        with self.assertRaisesRegex(ParserError, "Duplicate function specifier: 'inline'"):
            parse(list(lex("inline inline int f(void);")))
        with self.assertRaisesRegex(ParserError, "Duplicate function specifier: '_Noreturn'"):
            parse(list(lex("_Noreturn _Noreturn int f(void);")))
        with self.assertRaisesRegex(ParserError, "Duplicate type qualifier: 'volatile'"):
            parse(list(lex("volatile volatile int x;")))
        with self.assertRaisesRegex(ParserError, "Duplicate type qualifier: 'const'"):
            parse(list(lex("int f(int a[const const 4]){return 0;}")))
        with self.assertRaisesRegex(ParserError, "Duplicate array bound specifier: 'static'"):
            parse(list(lex("int f(int a[static static 4]){return 0;}")))

    def test_compound_literal_helper_errors(self) -> None:
        parser = Parser(list(lex("1")))
        self.assertFalse(parser._looks_like_compound_literal())
        parser = Parser(list(lex("(int)1")))
        with self.assertRaises(ParserError):
            parser._parse_compound_literal_expr()

    def test_array_declarator_helper_unsupported_paths(self) -> None:
        parser = Parser(list(lex("]")))
        with self.assertRaisesRegex(ParserError, "Array size is required in this context"):
            parser._parse_array_declarator(allow_vla=False, allow_parameter_arrays=False)
        parser = Parser(list(lex("n]")))
        with self.assertRaisesRegex(
            ParserError,
            "Array size identifier 'n' is not an integer constant expression",
        ):
            parser._parse_array_declarator(allow_vla=False, allow_parameter_arrays=False)
        parser = Parser(list(lex("1*2]")))
        with self.assertRaisesRegex(
            ParserError,
            "Array size binary operator '\*' is not an integer constant expression",
        ):
            parser._parse_array_declarator(allow_vla=False, allow_parameter_arrays=False)
        parser = Parser(list(lex("foo()]")))
        with self.assertRaisesRegex(
            ParserError,
            "Array size call expression is not an integer constant expression",
        ):
            parser._parse_array_declarator(allow_vla=False, allow_parameter_arrays=False)
        parser = Parser(
            [
                Token(TokenKind.INT_CONST, "1uu", 1, 1),
                Token(TokenKind.PUNCTUATOR, "]", 1, 4),
                Token(TokenKind.EOF, "", 1, 5),
            ]
        )
        with self.assertRaisesRegex(
            ParserError, "Array size literal has unsupported integer suffix"
        ):
            parser._parse_array_declarator(allow_vla=False, allow_parameter_arrays=False)
        parser = Parser(list(lex("n]")))

        def parse_assignment_with_malformed_int_literal() -> IntLiteral:
            parser._advance()
            return IntLiteral(1)

        parser._parse_assignment = parse_assignment_with_malformed_int_literal
        with self.assertRaisesRegex(ParserError, "Array size literal token is malformed"):
            parser._parse_array_declarator(allow_vla=False, allow_parameter_arrays=False)
        parser = Parser(list(lex("static ]")))
        with self.assertRaisesRegex(
            ParserError, "Array parameter with 'static' requires a size"
        ):
            parser._parse_array_declarator(allow_vla=False, allow_parameter_arrays=True)
        parser = Parser(list(lex("int]")))
        with self.assertRaises(ParserError):
            parser._parse_array_declarator(allow_vla=False, allow_parameter_arrays=True)

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

    def test_file_scope_static_assert_declaration(self) -> None:
        unit = parse(list(lex('_Static_assert(1, "ok"); int main(void){return 0;}')))
        self.assertIsInstance(unit.declarations[0], StaticAssertDecl)
        self.assertIsInstance(unit.externals[0], StaticAssertDecl)
        self.assertEqual(unit.functions[0].name, "main")

    def test_block_scope_static_assert_declaration(self) -> None:
        unit = parse(list(lex('int main(void){_Static_assert(1, "ok"); return 0;}')))
        statement = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(statement, StaticAssertDecl)

    def test_static_assert_requires_string_literal_message(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(void){_Static_assert(1, 2); return 0;}")))

    def test_parse_decl_stmt_static_assert_dispatch(self) -> None:
        parser = Parser(list(lex('_Static_assert(1, "ok");')))
        stmt = parser._parse_decl_stmt()
        self.assertIsInstance(stmt, StaticAssertDecl)

    def test_parse_static_assert_decl_requires_keyword(self) -> None:
        parser = Parser(list(lex("int value;")))
        with self.assertRaises(ParserError):
            parser._parse_static_assert_decl()

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
        with self.assertRaisesRegex(ParserError, "Array size must be positive"):
            parser._parse_array_size(Token(TokenKind.INT_CONST, "0", 1, 1))
        with self.assertRaisesRegex(ParserError, "Array size literal token is malformed"):
            parser._parse_array_size(Token(TokenKind.INT_CONST, None, 1, 1))
        with self.assertRaisesRegex(
            ParserError, "Array size literal has unsupported integer suffix"
        ):
            parser._parse_array_size(Token(TokenKind.INT_CONST, "1uu", 1, 1))
        with self.assertRaisesRegex(
            ParserError, "Array size octal literal contains non-octal digits"
        ):
            parser._parse_array_size(Token(TokenKind.INT_CONST, "08", 1, 1))
        with self.assertRaisesRegex(
            ParserError, "Array size hexadecimal literal requires at least one digit"
        ):
            parser._parse_array_size(Token(TokenKind.INT_CONST, "0x", 1, 1))
        with self.assertRaisesRegex(
            ParserError, "Array size literal must contain decimal digits"
        ):
            parser._parse_array_size(Token(TokenKind.INT_CONST, "u", 1, 1))

    def test_array_size_accepts_vla_non_constant_expression(self) -> None:
        unit = parse(list(lex("int main(){int n=4;int a[n];return 0;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec.declarator_ops, (("arr", ArrayDecl(Identifier("n"))),))

    def test_array_size_accepts_vla_negative_shift_amount_expression(self) -> None:
        unit = parse(list(lex("int main(){int a[1<<-1];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec.declarator_ops,
            (("arr", ArrayDecl(BinaryExpr("<<", IntLiteral("1"), UnaryExpr("-", IntLiteral("1"))))),),
        )

    def test_array_size_accepts_vla_unary_non_constant_expression(self) -> None:
        unit = parse(list(lex("int main(){int n=4;int a[+n];return 0;}")))
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec.declarator_ops,
            (("arr", ArrayDecl(UnaryExpr("+", Identifier("n")))),),
        )

    def test_array_size_accepts_vla_binary_operator_expression(self) -> None:
        unit = parse(list(lex("int main(){int a[4/2];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec.declarator_ops,
            (("arr", ArrayDecl(BinaryExpr("/", IntLiteral("4"), IntLiteral("2")))),),
        )

    def test_array_size_accepts_vla_sizeof_void_expression(self) -> None:
        unit = parse(list(lex("int main(){int a[(long long)sizeof(void)];return 0;}")))
        stmt = _body(unit.functions[0]).statements[0]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(
            stmt.type_spec.declarator_ops,
            (
                (
                    "arr",
                    ArrayDecl(
                        CastExpr(TypeSpec("long long"), SizeofExpr(None, TypeSpec("void"))),
                    ),
                ),
            ),
        )

    def test_array_size_helper_handles_sizeof_expression_forms(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        self.assertIsNone(parser._eval_array_size_expr(SizeofExpr(Identifier("x"), None)))
        self.assertEqual(parser._eval_array_size_expr(AlignofExpr(None, TypeSpec("int"))), 4)
        self.assertIsNone(parser._eval_array_size_expr(AlignofExpr(Identifier("x"), None)))
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

    def test_array_size_accepts_conditional_generic_expression(self) -> None:
        unit = parse(
            list(
                lex(
                    "void g(void); int main(){int a[_Generic(0,int:1,default:2)==1?1:-1];"
                    "int b[_Generic(\"x\",char*:1,default:2)==1?1:-1];"
                    "int c[_Generic(g,void(*)(void):1,default:2)==1?1:-1];return 0;}"
                )
            )
        )
        statements = _body(unit.functions[1]).statements
        self.assertIsInstance(statements[0], DeclStmt)
        self.assertEqual(statements[0].type_spec, TypeSpec("int", 0, (1,)))
        self.assertIsInstance(statements[1], DeclStmt)
        self.assertEqual(statements[1].type_spec, TypeSpec("int", 0, (1,)))
        self.assertIsInstance(statements[2], DeclStmt)
        self.assertEqual(statements[2].type_spec, TypeSpec("int", 0, (1,)))

    def test_array_size_accepts_generic_identifier_control_with_declared_int(self) -> None:
        unit = parse(
            list(lex("int main(){int i=12;int a[_Generic(i,int:1,default:2)==1?1:-1];return 0;}"))
        )
        stmt = _body(unit.functions[0]).statements[1]
        self.assertIsInstance(stmt, DeclStmt)
        self.assertEqual(stmt.type_spec, TypeSpec("int", 0, (1,)))

    def test_int_literal_type_spec_helper_suffixes(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        self.assertEqual(parser._int_literal_type_spec("1"), TypeSpec("int"))
        self.assertEqual(parser._int_literal_type_spec("1u"), TypeSpec("unsigned int"))
        self.assertEqual(parser._int_literal_type_spec("1L"), TypeSpec("long"))
        self.assertEqual(parser._int_literal_type_spec("1ll"), TypeSpec("long long"))
        self.assertEqual(parser._int_literal_type_spec("1ull"), TypeSpec("unsigned long long"))

    def test_array_size_generic_helpers_cover_unmatched_and_unknown_control(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        self.assertIsNone(parser._lookup_ordinary_type("missing"))
        self.assertEqual(
            parser._eval_array_size_expr(BinaryExpr("!=", IntLiteral("1"), IntLiteral("2"))),
            1,
        )
        self.assertIsNone(
            parser._eval_array_size_expr(
                ConditionalExpr(Identifier("x"), IntLiteral("1"), IntLiteral("2"))
            )
        )
        self.assertIsNone(
            parser._eval_array_size_expr(
                GenericExpr(IntLiteral("0"), ((TypeSpec("long"), IntLiteral("1")),))
            )
        )
        self.assertIsNone(parser._array_size_generic_control_type(Identifier("x")))
        self.assertIsNone(parser._array_size_generic_control_type(FloatLiteral("1.0")))
        self.assertEqual(
            parser._decay_type_spec(TypeSpec("int", declarator_ops=(("arr", 2),))),
            TypeSpec("int", declarator_ops=(("ptr", 0),)),
        )
        self.assertEqual(parser._alignof_type_spec(TypeSpec("int", pointer_depth=1)), 8)
        self.assertEqual(parser._alignof_type_spec(TypeSpec("int", array_lengths=(2,))), 4)
        self.assertIsNone(
            parser._alignof_type_spec(TypeSpec("int", declarator_ops=(("fn", (None, False)),)))
        )

    def test_array_size_helper_binary_with_non_constant_operand(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        expr = BinaryExpr("+", Identifier("x"), IntLiteral("1"))
        self.assertIsNone(parser._eval_array_size_expr(expr))

    def test_array_size_non_ice_error_helper_covers_conditional_and_cast_fallbacks(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        self.assertEqual(
            _array_size_non_ice_error(CastExpr(TypeSpec("int"), IntLiteral("1")), parser._eval_array_size_expr),
            "Array size cast expression is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(
                ConditionalExpr(IntLiteral("0"), IntLiteral("1"), IntLiteral("2")),
                parser._eval_array_size_expr,
            ),
            "Array size conditional expression is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(
                ConditionalExpr(IntLiteral("1"), Identifier("n"), IntLiteral("2")),
                parser._eval_array_size_expr,
            ),
            "Array size identifier 'n' is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(SizeofExpr(None, None), parser._eval_array_size_expr),
            "Array size sizeof expression is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(AlignofExpr(None, None), parser._eval_array_size_expr),
            "Array size alignof expression is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(
                StatementExpr(CompoundStmt([ExprStmt(IntLiteral("1"))])),
                parser._eval_array_size_expr,
            ),
            "Array size statement expression is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(LabelAddressExpr("target"), parser._eval_array_size_expr),
            "Array size label address expression is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(
                AssignExpr("=", Identifier("n"), IntLiteral("1")),
                parser._eval_array_size_expr,
            ),
            "Array size assignment expression is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(
                UpdateExpr("++", Identifier("n"), is_postfix=False),
                parser._eval_array_size_expr,
            ),
            "Array size update expression is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(
                SubscriptExpr(Identifier("arr"), IntLiteral("0")),
                parser._eval_array_size_expr,
            ),
            "Array size subscript expression is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(
                MemberExpr(Identifier("s"), "field", False),
                parser._eval_array_size_expr,
            ),
            "Array size member access expression is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(
                CompoundLiteralExpr(TypeSpec("int"), InitList((InitItem((), IntLiteral("1")),))),
                parser._eval_array_size_expr,
            ),
            "Array size compound literal is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(IntLiteral("0x"), parser._eval_array_size_expr),
            "Array size integer literal is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(FloatLiteral("1.0"), parser._eval_array_size_expr),
            "Array size floating literal is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(CharLiteral("'a'"), parser._eval_array_size_expr),
            "Array size character literal is not an integer constant expression",
        )
        self.assertEqual(
            _array_size_non_ice_error(StringLiteral('"x"'), parser._eval_array_size_expr),
            "Array size string literal is not an integer constant expression",
        )

    def test_array_size_helper_or_vla_accepts_constant_size(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        token = Token(TokenKind.INT_CONST, "4", 1, 1)
        self.assertEqual(parser._parse_array_size_expr_or_vla(IntLiteral("4"), token), 4)

    def test_array_size_helper_or_vla_rejects_non_positive_size(self) -> None:
        parser = Parser([Token(TokenKind.EOF, None, 1, 1)])
        token = Token(TokenKind.INT_CONST, "0", 1, 1)
        with self.assertRaises(ParserError):
            parser._parse_array_size_expr_or_vla(IntLiteral("0"), token)

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

    def test_generic_selection_rejects_duplicate_default(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(void){return _Generic(0, default:1, default:2);}")))

    def test_generic_selection_requires_type_name_association(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(void){return _Generic(0, int x:1);}")))

    def test_typedef_requires_identifier(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){typedef int;}")))

    def test_typedef_initializer_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){typedef int T=1;}")))

    def test_typedef_pointer_requires_identifier(self) -> None:
        with self.assertRaises(ParserError):
            parse(list(lex("int main(){typedef int *;}")))

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
