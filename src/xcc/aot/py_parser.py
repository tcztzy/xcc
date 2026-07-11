from typing import NoReturn

from xcc.aot import py_ast as ast
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.module import AotModule
from xcc.aot.py_lexer import PyToken, lex_python

_AUGMENTED_OPERATORS = {
    "+=": ast.Add,
    "-=": ast.Sub,
    "*=": ast.Mult,
    "/=": ast.Div,
    "//=": ast.FloorDiv,
    "%=": ast.Mod,
    "<<=": ast.LShift,
    ">>=": ast.RShift,
    "&=": ast.BitAnd,
    "|=": ast.BitOr,
    "^=": ast.BitXor,
    "@=": ast.MatMult,
}


def parse_subset_source(source: str, *, filename: str = "<input>") -> AotModule:
    tree = _PythonParser(source, filename).parse_module()
    return AotModule(filename, source, tree)


def parse_subset_expression(source: str, *, filename: str = "<input>") -> ast.Expression:
    return _PythonParser(source, filename).parse_expression_root()


class _PythonParser:
    def __init__(
        self,
        source: str,
        filename: str,
        *,
        line_offset: int = 0,
        column_offset: int = 0,
    ) -> None:
        tokens = lex_python(source, filename=filename)
        if line_offset or column_offset:
            tokens = tuple(_shift_token(token, line_offset, column_offset) for token in tokens)
        self.source = source
        self.filename = filename
        self.tokens = tokens
        self.index = 0
        self.stop_at_in = False
        self.expression_extents: list[tuple[ast.expr, ast.SourceSpan]] = []

    def parse_module(self) -> ast.Module:
        body: list[ast.stmt] = []
        while not self._at_kind("EOF"):
            if self._at_kind("DEDENT"):
                self._syntax("Unexpected indentation boundary")
            body.extend(self._parse_statement())
        return ast.Module(
            tuple(body),
            (),
            children=tuple(body),
        )

    def parse_expression_root(self) -> ast.Expression:
        body = self._parse_expression_list()
        self._match_kind("NEWLINE")
        self._expect_kind("EOF", "Expected end of expression")
        return ast.Expression(body, children=(body,))

    def _parse_statement(self) -> tuple[ast.stmt, ...]:
        if self._at("@"):
            return (self._parse_decorated(),)
        if self._at("def"):
            return (self._parse_function(()),)
        if self._at("class"):
            return (self._parse_class(()),)
        if self._at("if"):
            return (self._parse_if(),)
        if self._at("while"):
            return (self._parse_while(),)
        if self._at("for"):
            return (self._parse_for(),)
        if self._at("try"):
            return (self._parse_try(),)
        if self._at("with"):
            return (self._parse_with(),)
        if self._at("async"):
            self._excluded("async statements are outside the bootstrap subset")
        if self._at("match") and self._looks_like_match_statement():
            self._excluded("match statements are outside the bootstrap subset")
        return (self._parse_simple_line(),)

    def _parse_decorated(self) -> ast.stmt:
        decorators: list[ast.expr] = []
        while self._match("@"):
            decorators.append(self._parse_expression())
            self._expect_kind("NEWLINE", "Expected newline after decorator")
        if self._at("def"):
            return self._parse_function(tuple(decorators))
        if self._at("class"):
            return self._parse_class(tuple(decorators))
        self._syntax("Decorator must precede a function or class")

    def _parse_function(self, decorators: tuple[ast.expr, ...]) -> ast.FunctionDef:
        start = self._expect("def")
        name = self._expect_kind("NAME", "Expected function name")
        self._expect("(")
        arguments = self._parse_parameters()
        self._expect(")")
        returns: ast.expr | None = None
        if self._match("->"):
            returns = self._parse_expression()
        self._expect(":")
        body = self._parse_suite()
        end = body[-1]
        children = _children(arguments, body, decorators, returns)
        return ast.FunctionDef(
            name.text,
            arguments,
            body,
            decorators,
            returns,
            None,
            (),
            span=self._span_between(start, end),
            children=children,
        )

    def _parse_parameters(self) -> ast.arguments:
        posonlyargs: list[ast.arg] = []
        positional: list[ast.arg] = []
        positional_defaults: list[ast.expr | None] = []
        vararg: ast.arg | None = None
        kwonlyargs: list[ast.arg] = []
        kw_defaults: list[ast.expr | None] = []
        kwarg: ast.arg | None = None
        keyword_only = False
        saw_positional_only = False

        while not self._at(")"):
            if self._match("**"):
                if kwarg is not None:
                    self._syntax("Duplicate variadic keyword parameter")
                kwarg = self._parse_parameter()
                if self._match(",") and not self._at(")"):
                    self._syntax("Variadic keyword parameter must be last")
                break
            if self._match("*"):
                if keyword_only:
                    self._syntax("Duplicate variadic positional marker")
                keyword_only = True
                if self._at_kind("NAME"):
                    vararg = self._parse_parameter()
                if self._match(","):
                    if self._at(")"):
                        self._syntax("Named keyword-only parameters must follow '*'")
                    continue
                if not self._at(")"):
                    self._syntax("Expected ',' after variadic positional parameter")
                continue
            if self._match("/"):
                if saw_positional_only or not positional or keyword_only:
                    self._syntax("Invalid positional-only parameter marker")
                posonlyargs.extend(positional)
                positional.clear()
                saw_positional_only = True
                if self._match(","):
                    continue
                if not self._at(")"):
                    self._syntax("Expected ',' after positional-only marker")
                continue

            item = self._parse_parameter()
            default: ast.expr | None = None
            if self._match("="):
                default = self._parse_expression()
            if keyword_only:
                kwonlyargs.append(item)
                kw_defaults.append(default)
            else:
                if default is None and any(value is not None for value in positional_defaults):
                    self._syntax("Non-default parameter follows default parameter")
                positional.append(item)
                positional_defaults.append(default)
            if not self._match(","):
                break

        defaults = tuple(value for value in positional_defaults if value is not None)
        children = _children(
            tuple(posonlyargs),
            tuple(positional),
            vararg,
            tuple(kwonlyargs),
            tuple(kw_defaults),
            kwarg,
            defaults,
        )
        return ast.arguments(
            tuple(posonlyargs),
            tuple(positional),
            vararg,
            tuple(kwonlyargs),
            tuple(kw_defaults),
            kwarg,
            defaults,
            children=children,
        )

    def _parse_parameter(self) -> ast.arg:
        name = self._expect_kind("NAME", "Expected parameter name")
        annotation: ast.expr | None = None
        if self._match(":"):
            annotation = self._parse_expression()
        end: PyToken | ast.AST = annotation if annotation is not None else name
        return ast.arg(
            name.text,
            annotation,
            None,
            span=self._span_between(name, end),
            children=_children(annotation),
        )

    def _parse_class(self, decorators: tuple[ast.expr, ...]) -> ast.ClassDef:
        start = self._expect("class")
        name = self._expect_kind("NAME", "Expected class name")
        bases: tuple[ast.expr, ...] = ()
        keywords: tuple[ast.keyword, ...] = ()
        if self._match("("):
            parsed_bases, parsed_keywords = self._parse_call_items(")")
            bases = tuple(parsed_bases)
            keywords = tuple(parsed_keywords)
            self._expect(")")
        self._expect(":")
        body = self._parse_suite()
        end = body[-1]
        return ast.ClassDef(
            name.text,
            bases,
            keywords,
            body,
            decorators,
            (),
            span=self._span_between(start, end),
            children=_children(bases, keywords, body, decorators),
        )

    def _parse_if(self) -> ast.If:
        start = self._expect("if")
        test = self._parse_expression()
        self._expect(":")
        body = self._parse_suite()
        orelse: tuple[ast.stmt, ...] = ()
        if self._at("elif"):
            orelse = (self._parse_elif(),)
        elif self._match("else"):
            self._expect(":")
            orelse = self._parse_suite()
        end = orelse[-1] if orelse else body[-1]
        return ast.If(
            test,
            body,
            orelse,
            span=self._span_between(start, end),
            children=_children(test, body, orelse),
        )

    def _parse_elif(self) -> ast.If:
        start = self._expect("elif")
        test = self._parse_expression()
        self._expect(":")
        body = self._parse_suite()
        orelse: tuple[ast.stmt, ...] = ()
        if self._at("elif"):
            orelse = (self._parse_elif(),)
        elif self._match("else"):
            self._expect(":")
            orelse = self._parse_suite()
        end = orelse[-1] if orelse else body[-1]
        return ast.If(
            test,
            body,
            orelse,
            span=self._span_between(start, end),
            children=_children(test, body, orelse),
        )

    def _parse_while(self) -> ast.While:
        start = self._expect("while")
        test = self._parse_expression()
        self._expect(":")
        body = self._parse_suite()
        orelse: tuple[ast.stmt, ...] = ()
        if self._match("else"):
            self._expect(":")
            orelse = self._parse_suite()
        end = orelse[-1] if orelse else body[-1]
        return ast.While(
            test,
            body,
            orelse,
            span=self._span_between(start, end),
            children=_children(test, body, orelse),
        )

    def _parse_for(self) -> ast.For:
        start = self._expect("for")
        previous = self.stop_at_in
        self.stop_at_in = True
        target = self._parse_expression_list()
        self.stop_at_in = previous
        self._expect("in")
        iterator = self._parse_expression_list()
        self._expect(":")
        body = self._parse_suite()
        orelse: tuple[ast.stmt, ...] = ()
        if self._match("else"):
            self._expect(":")
            orelse = self._parse_suite()
        stored = self._store(target)
        end = orelse[-1] if orelse else body[-1]
        return ast.For(
            stored,
            iterator,
            body,
            orelse,
            None,
            span=self._span_between(start, end),
            children=_children(stored, iterator, body, orelse),
        )

    def _parse_try(self) -> ast.Try:
        start = self._expect("try")
        self._expect(":")
        body = self._parse_suite()
        handlers: list[ast.ExceptHandler] = []
        orelse: tuple[ast.stmt, ...] = ()
        finalbody: tuple[ast.stmt, ...] = ()
        while self._match("except"):
            handler_start = self._previous()
            exception_type: ast.expr | None = None
            name: str | None = None
            if not self._at(":"):
                exception_type = self._parse_expression()
                if self._match("as"):
                    name = self._expect_kind("NAME", "Expected exception target").text
            self._expect(":")
            handler_body = self._parse_suite()
            handlers.append(
                ast.ExceptHandler(
                    exception_type,
                    name,
                    handler_body,
                    span=self._span_between(handler_start, handler_body[-1]),
                    children=_children(exception_type, handler_body),
                )
            )
        if self._match("else"):
            self._expect(":")
            orelse = self._parse_suite()
        if self._match("finally"):
            self._expect(":")
            finalbody = self._parse_suite()
        if not handlers and not finalbody:
            self._syntax("try statement requires except or finally")
        end: ast.AST = body[-1]
        if handlers:
            end = handlers[-1]
        if orelse:
            end = orelse[-1]
        if finalbody:
            end = finalbody[-1]
        return ast.Try(
            body,
            tuple(handlers),
            orelse,
            finalbody,
            span=self._span_between(start, end),
            children=_children(body, tuple(handlers), orelse, finalbody),
        )

    def _parse_with(self) -> ast.With:
        start = self._expect("with")
        items: list[ast.withitem] = []
        while True:
            context = self._parse_expression()
            optional_vars: ast.expr | None = None
            if self._match("as"):
                optional_vars = self._store(self._parse_expression())
            items.append(
                ast.withitem(
                    context,
                    optional_vars,
                    children=_children(context, optional_vars),
                )
            )
            if not self._match(","):
                break
        self._expect(":")
        body = self._parse_suite()
        return ast.With(
            tuple(items),
            body,
            None,
            span=self._span_between(start, body[-1]),
            children=_children(tuple(items), body),
        )

    def _parse_suite(self) -> tuple[ast.stmt, ...]:
        if not self._match_kind("NEWLINE"):
            return (self._parse_simple_line(),)
        self._expect_kind("INDENT", "Expected an indented block")
        body: list[ast.stmt] = []
        while not self._at_kind("DEDENT") and not self._at_kind("EOF"):
            body.extend(self._parse_statement())
        if not body:
            self._syntax("Expected a non-empty block")
        self._expect_kind("DEDENT", "Expected end of indented block")
        return tuple(body)

    def _parse_simple_line(self) -> ast.stmt:
        start = self._current()
        if self._match("return"):
            value = None if self._at_kind("NEWLINE") else self._parse_expression_list()
            statement: ast.stmt = ast.Return(
                value,
                span=self._span_between(start, value if value is not None else start),
                children=_children(value),
            )
        elif self._match("raise"):
            exception = None if self._at_kind("NEWLINE") else self._parse_expression()
            cause: ast.expr | None = None
            if exception is not None and self._match("from"):
                cause = self._parse_expression()
            end: PyToken | ast.AST = cause or exception or start
            statement = ast.Raise(
                exception,
                cause,
                span=self._span_between(start, end),
                children=_children(exception, cause),
            )
        elif self._match("assert"):
            test = self._parse_expression()
            message: ast.expr | None = None
            if self._match(","):
                message = self._parse_expression()
            statement = ast.Assert(
                test,
                message,
                span=self._span_between(start, message or test),
                children=_children(test, message),
            )
        elif self._match("import"):
            statement = self._parse_import(start)
        elif self._match("from"):
            statement = self._parse_import_from(start)
        elif self._match("pass"):
            statement = ast.Pass(span=start.span)
        elif self._match("break"):
            statement = ast.Break(span=start.span)
        elif self._match("continue"):
            statement = ast.Continue(span=start.span)
        elif self._at("del") or self._at("global") or self._at("nonlocal"):
            self._excluded(f"{self._current().text} is outside the bootstrap subset")
        else:
            statement = self._parse_assignment_or_expression(start)
        if self._match(";"):
            self._excluded("semicolon-separated statements are outside the bootstrap subset")
        self._expect_kind("NEWLINE", "Expected newline after statement")
        return statement

    def _parse_import(self, start: PyToken) -> ast.Import:
        names: list[ast.alias] = []
        while True:
            names.append(self._parse_alias(dotted=True))
            if not self._match(","):
                break
        return ast.Import(
            tuple(names),
            span=self._span_between(start, names[-1]),
            children=tuple(names),
        )

    def _parse_import_from(self, start: PyToken) -> ast.ImportFrom:
        level = 0
        while self._at(".") or self._at("..."):
            level += 3 if self._current().text == "..." else 1
            self._advance()
        module: str | None = None
        if not self._at("import"):
            module = self._parse_dotted_name()
        self._expect("import")
        parenthesized = self._match("(")
        names: list[ast.alias] = []
        if self._match("*"):
            star = self._previous()
            names.append(ast.alias("*", None, span=star.span))
        else:
            while True:
                names.append(self._parse_alias(dotted=False))
                if not self._match(","):
                    break
                if parenthesized and self._at(")"):
                    break
        end: PyToken | ast.AST = names[-1]
        if parenthesized:
            end = self._expect(")")
        return ast.ImportFrom(
            module,
            tuple(names),
            level,
            span=self._span_between(start, end),
            children=tuple(names),
        )

    def _parse_alias(self, *, dotted: bool) -> ast.alias:
        start = self._current()
        name = (
            self._parse_dotted_name()
            if dotted
            else self._expect_kind("NAME", "Expected imported name").text
        )
        asname: str | None = None
        end: PyToken = self._previous()
        if self._match("as"):
            end = self._expect_kind("NAME", "Expected import alias")
            asname = end.text
        return ast.alias(
            name,
            asname,
            span=self._span_between(start, end),
        )

    def _parse_dotted_name(self) -> str:
        parts = [self._expect_kind("NAME", "Expected module name").text]
        while self._match("."):
            parts.append(self._expect_kind("NAME", "Expected name after '.'").text)
        return ".".join(parts)

    def _parse_assignment_or_expression(self, start: PyToken) -> ast.stmt:
        left = self._parse_expression_list()
        if self._match(":"):
            annotation = self._parse_expression()
            value: ast.expr | None = None
            if self._match("="):
                value = self._parse_expression_list()
            target = self._store(left)
            end: ast.AST = value or annotation
            return ast.AnnAssign(
                target,
                annotation,
                value,
                1 if isinstance(left, ast.Name) else 0,
                span=self._span_between(start, end),
                children=_children(target, annotation, value),
            )
        operator_type = _AUGMENTED_OPERATORS.get(self._current().text)
        if operator_type is not None:
            self._advance()
            value = self._parse_expression_list()
            target = self._store(left)
            operator = operator_type()
            return ast.AugAssign(
                target,
                operator,
                value,
                span=self._span_between(start, value),
                children=_children(target, operator, value),
            )
        if self._at("="):
            targets: list[ast.expr] = []
            current = left
            while self._match("="):
                targets.append(self._store(current))
                current = self._parse_expression_list()
                if not self._at("="):
                    break
            return ast.Assign(
                tuple(targets),
                current,
                None,
                span=self._span_between(start, current),
                children=_children(tuple(targets), current),
            )
        return ast.Expr(
            left,
            span=self._span_between(start, left),
            children=(left,),
        )

    def _parse_expression_list(self) -> ast.expr:
        start = self._current()
        elements = [self._parse_star_expression()]
        trailing = False
        trailing_token: PyToken | None = None
        while self._match(","):
            trailing = True
            if self._expression_list_ended():
                trailing_token = self._previous()
                break
            elements.append(self._parse_star_expression())
        if len(elements) == 1 and not trailing:
            return elements[0]
        context = ast.Load()
        end: PyToken | ast.AST = trailing_token or elements[-1]
        return ast.Tuple(
            tuple(elements),
            context,
            span=self._span_between(start, end),
            children=_children(tuple(elements), context),
        )

    def _expression_list_ended(self) -> bool:
        if self._at_kind("NEWLINE") or self._at_kind("EOF"):
            return True
        if self._current().text in {")", "]", "}", ":", ";"}:
            return True
        return self.stop_at_in and self._at("in")

    def _parse_star_expression(self) -> ast.expr:
        if not self._match("*"):
            return self._parse_expression()
        start = self._previous()
        value = self._parse_expression()
        context = ast.Load()
        return ast.Starred(
            value,
            context,
            span=self._span_between(start, value),
            children=_children(value, context),
        )

    def _parse_expression(self) -> ast.expr:
        if self._at("lambda"):
            self._excluded("lambda expressions are outside the bootstrap subset")
        if self._at("yield") or self._at("await"):
            self._excluded(f"{self._current().text} is outside the bootstrap subset")
        body = self._parse_or()
        if self._match("if"):
            test = self._parse_or()
            self._expect("else")
            orelse = self._parse_expression()
            body = ast.IfExp(
                test,
                body,
                orelse,
                span=self._span_between(body, orelse),
                children=_children(test, body, orelse),
            )
        if self._at(":="):
            self._excluded("assignment expressions are outside the bootstrap subset")
        return body

    def _parse_or(self) -> ast.expr:
        values = [self._parse_and()]
        while self._match("or"):
            values.append(self._parse_and())
        if len(values) == 1:
            return values[0]
        operator = ast.Or()
        return ast.BoolOp(
            operator,
            tuple(values),
            span=self._span_between(values[0], values[-1]),
            children=_children(operator, tuple(values)),
        )

    def _parse_and(self) -> ast.expr:
        values = [self._parse_not()]
        while self._match("and"):
            values.append(self._parse_not())
        if len(values) == 1:
            return values[0]
        operator = ast.And()
        return ast.BoolOp(
            operator,
            tuple(values),
            span=self._span_between(values[0], values[-1]),
            children=_children(operator, tuple(values)),
        )

    def _parse_not(self) -> ast.expr:
        if not self._match("not"):
            return self._parse_comparison()
        start = self._previous()
        operand = self._parse_not()
        operator = ast.Not()
        return ast.UnaryOp(
            operator,
            operand,
            span=self._span_between(start, operand),
            children=_children(operator, operand),
        )

    def _parse_comparison(self) -> ast.expr:
        left = self._parse_bitwise_or()
        operators: list[ast.cmpop] = []
        comparators: list[ast.expr] = []
        while True:
            operator: ast.cmpop | None = None
            if self._match("=="):
                operator = ast.Eq()
            elif self._match("!="):
                operator = ast.NotEq()
            elif self._match("<"):
                operator = ast.Lt()
            elif self._match("<="):
                operator = ast.LtE()
            elif self._match(">"):
                operator = ast.Gt()
            elif self._match(">="):
                operator = ast.GtE()
            elif self._match("is"):
                operator = ast.IsNot() if self._match("not") else ast.Is()
            elif not self.stop_at_in and self._match("in"):
                operator = ast.In()
            elif self._at("not") and self._peek_token().text == "in":
                self._advance()
                self._advance()
                operator = ast.NotIn()
            if operator is None:
                break
            operators.append(operator)
            comparators.append(self._parse_bitwise_or())
        if not operators:
            return left
        return ast.Compare(
            left,
            tuple(operators),
            tuple(comparators),
            span=self._span_between(left, comparators[-1]),
            children=_children(left, tuple(operators), tuple(comparators)),
        )

    def _parse_bitwise_or(self) -> ast.expr:
        left = self._parse_bitwise_xor()
        while self._match("|"):
            right = self._parse_bitwise_xor()
            operator = ast.BitOr()
            left = ast.BinOp(
                left,
                operator,
                right,
                span=self._span_between(left, right),
                children=_children(left, operator, right),
            )
        return left

    def _parse_bitwise_xor(self) -> ast.expr:
        left = self._parse_bitwise_and()
        while self._match("^"):
            right = self._parse_bitwise_and()
            operator = ast.BitXor()
            left = ast.BinOp(
                left,
                operator,
                right,
                span=self._span_between(left, right),
                children=_children(left, operator, right),
            )
        return left

    def _parse_bitwise_and(self) -> ast.expr:
        left = self._parse_shift()
        while self._match("&"):
            right = self._parse_shift()
            operator = ast.BitAnd()
            left = ast.BinOp(
                left,
                operator,
                right,
                span=self._span_between(left, right),
                children=_children(left, operator, right),
            )
        return left

    def _parse_shift(self) -> ast.expr:
        left = self._parse_sum()
        while self._at("<<") or self._at(">>"):
            if self._match("<<"):
                operator: ast.operator = ast.LShift()
            else:
                self._expect(">>")
                operator = ast.RShift()
            right = self._parse_sum()
            left = ast.BinOp(
                left,
                operator,
                right,
                span=self._span_between(left, right),
                children=_children(left, operator, right),
            )
        return left

    def _parse_sum(self) -> ast.expr:
        left = self._parse_term()
        while self._at("+") or self._at("-"):
            if self._match("+"):
                operator: ast.operator = ast.Add()
            else:
                self._expect("-")
                operator = ast.Sub()
            right = self._parse_term()
            left = ast.BinOp(
                left,
                operator,
                right,
                span=self._span_between(left, right),
                children=_children(left, operator, right),
            )
        return left

    def _parse_term(self) -> ast.expr:
        left = self._parse_factor()
        while self._current().text in {"*", "@", "/", "//", "%"}:
            text = self._advance().text
            if text == "*":
                operator: ast.operator = ast.Mult()
            elif text == "@":
                operator = ast.MatMult()
            elif text == "/":
                operator = ast.Div()
            elif text == "//":
                operator = ast.FloorDiv()
            else:
                operator = ast.Mod()
            right = self._parse_factor()
            left = ast.BinOp(
                left,
                operator,
                right,
                span=self._span_between(left, right),
                children=_children(left, operator, right),
            )
        return left

    def _parse_factor(self) -> ast.expr:
        if self._at("+") or self._at("-") or self._at("~"):
            start = self._advance()
            if start.text == "+":
                operator: ast.unaryop = ast.UAdd()
            elif start.text == "-":
                operator = ast.USub()
            else:
                operator = ast.Invert()
            operand = self._parse_factor()
            return ast.UnaryOp(
                operator,
                operand,
                span=self._span_between(start, operand),
                children=_children(operator, operand),
            )
        return self._parse_power()

    def _parse_power(self) -> ast.expr:
        value = self._parse_primary()
        if self._at("**"):
            self._excluded("power expressions are outside the bootstrap subset")
        return value

    def _parse_primary(self) -> ast.expr:
        value = self._parse_atom()
        while True:
            if self._match("."):
                name = self._expect_kind("NAME", "Expected attribute name")
                context = ast.Load()
                value = ast.Attribute(
                    value,
                    name.text,
                    context,
                    span=self._span_between(value, name),
                    children=_children(value, context),
                )
                continue
            if self._match("["):
                slice_value = self._parse_subscript_slice()
                end = self._expect("]")
                context = ast.Load()
                value = ast.Subscript(
                    value,
                    slice_value,
                    context,
                    span=self._span_between(value, end),
                    children=_children(value, slice_value, context),
                )
                continue
            if self._match("("):
                opening = self._previous()
                arguments, keywords = self._parse_call_items(")")
                end = self._expect(")")
                if (
                    len(arguments) == 1
                    and not keywords
                    and isinstance(arguments[0], ast.GeneratorExp)
                ):
                    generator = arguments[0]
                    arguments[0] = ast.GeneratorExp(
                        generator.elt,
                        generator.generators,
                        span=self._span_between(opening, end),
                        children=generator.children,
                    )
                value = ast.Call(
                    value,
                    tuple(arguments),
                    tuple(keywords),
                    span=self._span_between(value, end),
                    children=_children(value, tuple(arguments), tuple(keywords)),
                )
                continue
            break
        return value

    def _parse_atom(self) -> ast.expr:
        token = self._current()
        if self._match("True"):
            return ast.Constant(True, None, span=token.span)
        if self._match("False"):
            return ast.Constant(False, None, span=token.span)
        if self._match("None"):
            return ast.Constant(None, None, span=token.span)
        if self._match("..."):
            return ast.Constant(Ellipsis, None, span=token.span)
        if token.kind == "NUMBER":
            self._advance()
            return ast.Constant(_decode_number(token.text), None, span=token.span)
        if token.kind == "STRING":
            return self._parse_strings()
        if token.kind == "NAME":
            if token.text in {"lambda", "yield", "await"}:
                self._excluded(f"{token.text} is outside the bootstrap subset")
            self._advance()
            context = ast.Load()
            return ast.Name(
                token.text,
                context,
                span=token.span,
                children=(context,),
            )
        if self._match("("):
            start = token
            if self._match(")"):
                context = ast.Load()
                return ast.Tuple(
                    (),
                    context,
                    span=self._span_between(start, self._previous()),
                    children=(context,),
                )
            value = self._parse_star_expression()
            if self._at("for"):
                if isinstance(value, ast.Starred):
                    self._syntax("Iterable unpacking is not allowed in a comprehension")
                generators = self._parse_comprehensions()
                end = self._expect(")")
                return ast.GeneratorExp(
                    value,
                    generators,
                    span=self._span_between(start, end),
                    children=_children(value, generators),
                )
            if self._match(","):
                elements = [value]
                while not self._at(")"):
                    elements.append(self._parse_star_expression())
                    if not self._match(","):
                        break
                end = self._expect(")")
                context = ast.Load()
                return ast.Tuple(
                    tuple(elements),
                    context,
                    span=self._span_between(start, end),
                    children=_children(tuple(elements), context),
                )
            end = self._expect(")")
            if isinstance(value, ast.Starred):
                self._syntax("Iterable unpacking requires a tuple display")
            self.expression_extents.append((value, self._span_between(start, end)))
            return value
        if self._match("["):
            return self._parse_list_display(token)
        if self._match("{"):
            return self._parse_brace_display(token)
        self._syntax(f"Expected expression, found {token.text!r}")

    def _parse_strings(self) -> ast.expr:
        start = self._current()
        end = start
        joined_values: list[ast.expr] = []
        text_value = ""
        byte_value = b""
        byte_mode: bool | None = None
        saw_fstring = False
        while self._at_kind("STRING"):
            token = self._advance()
            end = token
            prefix, content, content_offset = _split_string_token(token.text)
            is_raw = "r" in prefix
            is_bytes = "b" in prefix
            is_fstring = "f" in prefix
            if byte_mode is None:
                byte_mode = is_bytes
            elif byte_mode != is_bytes:
                self._raise_at(
                    "XCC-AOT-PYPARSE-0001",
                    "Cannot mix bytes and non-bytes string literals",
                    token.span,
                )
            if is_fstring:
                if is_bytes:
                    self._raise_at(
                        "XCC-AOT-PYPARSE-0001",
                        "Formatted bytes literals are invalid",
                        token.span,
                    )
                if not saw_fstring and text_value:
                    _append_joined_value(
                        joined_values,
                        ast.Constant(text_value, None, span=start.span),
                    )
                    text_value = ""
                saw_fstring = True
                for value in self._parse_fstring_parts(
                    token,
                    content,
                    is_raw,
                    content_offset,
                ):
                    _append_joined_value(joined_values, value)
                continue
            try:
                decoded = _decode_string_content(content, is_raw, is_bytes)
            except ValueError as error:
                self._raise_at(
                    "XCC-AOT-PYPARSE-0001",
                    str(error),
                    token.span,
                )
            if is_bytes:
                if not isinstance(decoded, bytes):
                    self._syntax("Internal bytes literal error")
                byte_value += decoded
            elif saw_fstring:
                if not isinstance(decoded, str):
                    self._syntax("Internal string literal error")
                _append_joined_value(
                    joined_values,
                    ast.Constant(decoded, None, span=token.span),
                )
            else:
                if not isinstance(decoded, str):
                    self._syntax("Internal string literal error")
                text_value += decoded
        span = self._span_between(start, end)
        if saw_fstring:
            if text_value:
                _append_joined_value(
                    joined_values,
                    ast.Constant(text_value, None, span=span),
                )
            respanned = _respan_fstring_values(tuple(joined_values), span)
            return ast.JoinedStr(
                respanned,
                span=span,
                children=respanned,
            )
        literal_value: object = byte_value if byte_mode else text_value
        return ast.Constant(literal_value, None, span=span)

    def _parse_fstring_parts(
        self,
        token: PyToken,
        content: str,
        is_raw: bool,
        content_offset: int,
    ) -> tuple[ast.expr, ...]:
        values: list[ast.expr] = []
        literal = ""
        index = 0
        while index < len(content):
            ch = content[index]
            if ch == "{" and index + 1 < len(content) and content[index + 1] == "{":
                literal += "{"
                index += 2
                continue
            if ch == "}" and index + 1 < len(content) and content[index + 1] == "}":
                literal += "}"
                index += 2
                continue
            if ch == "}":
                self._raise_at(
                    "XCC-AOT-PYPARSE-0001",
                    "Single '}' is not allowed in a formatted string",
                    token.span,
                )
            if ch != "{":
                literal += ch
                index += 1
                continue
            if literal:
                decoded = _decode_string_content(literal, is_raw, False)
                if not isinstance(decoded, str):
                    self._syntax("Internal formatted string literal error")
                _append_joined_value(
                    values,
                    ast.Constant(decoded, None, span=token.span),
                )
                literal = ""
            field = self._scan_fstring_field(token, content, index + 1)
            expression_end, debug_end, conversion, spec_start, close = field
            expression_text = content[index + 1 : expression_end]
            leading = len(expression_text) - len(expression_text.lstrip())
            expression_text = expression_text.strip()
            if not expression_text:
                self._raise_at(
                    "XCC-AOT-PYPARSE-0001",
                    "Empty formatted string expression",
                    token.span,
                )
            expression_offset = content_offset + index + 1 + leading
            expression = self._parse_embedded_expression(
                token,
                expression_text,
                expression_offset,
            )
            if debug_end is not None:
                debug_text = content[index + 1 : debug_end]
                _append_joined_value(
                    values,
                    ast.Constant(debug_text, None, span=token.span),
                )
                if conversion == -1:
                    conversion = ord("r")
            format_spec: ast.expr | None = None
            if spec_start is not None:
                spec_text = content[spec_start:close]
                spec_values = self._parse_fstring_parts(
                    token,
                    spec_text,
                    is_raw,
                    content_offset + spec_start,
                )
                format_spec = ast.JoinedStr(
                    spec_values,
                    span=token.span,
                    children=spec_values,
                )
            formatted = ast.FormattedValue(
                expression,
                conversion,
                format_spec,
                span=token.span,
                children=_children(expression, format_spec),
            )
            values.append(formatted)
            index = close + 1
        if literal:
            decoded = _decode_string_content(literal, is_raw, False)
            if not isinstance(decoded, str):
                self._syntax("Internal formatted string literal error")
            _append_joined_value(
                values,
                ast.Constant(decoded, None, span=token.span),
            )
        return tuple(values)

    def _scan_fstring_field(
        self,
        token: PyToken,
        content: str,
        start: int,
    ) -> tuple[int, int | None, int, int | None, int]:
        index = start
        stack: list[str] = []
        delimiter = ""
        expression_end = -1
        debug_end: int | None = None
        while index < len(content):
            ch = content[index]
            if ch in {"'", '"'}:
                index = _skip_quoted_text(content, index)
                continue
            if ch in "([{":
                stack.append(ch)
                index += 1
                continue
            if ch in ")]":
                if not stack or not _delimiters_match(stack[-1], ch):
                    self._raise_at(
                        "XCC-AOT-PYPARSE-0001",
                        "Mismatched delimiter in formatted string expression",
                        token.span,
                    )
                stack.pop()
                index += 1
                continue
            if ch == "}":
                if stack:
                    if stack[-1] != "{":
                        self._raise_at(
                            "XCC-AOT-PYPARSE-0001",
                            "Mismatched delimiter in formatted string expression",
                            token.span,
                        )
                    stack.pop()
                    index += 1
                    continue
                delimiter = "}"
                expression_end = index
                break
            if not stack and ch == "!" and _char_at(content, index + 1) != "=":
                delimiter = "!"
                expression_end = index
                break
            if not stack and ch == ":" and _char_at(content, index + 1) != "=":
                delimiter = ":"
                expression_end = index
                break
            if not stack and ch == "=" and _is_debug_equals(content, index):
                delimiter = "="
                expression_end = index
                break
            index += 1
        if expression_end < 0:
            self._raise_at(
                "XCC-AOT-PYPARSE-0001",
                "Unterminated formatted string expression",
                token.span,
            )

        if delimiter == "=":
            index += 1
            while _char_at(content, index) in {" ", "\t", "\f"}:
                index += 1
            debug_end = index
            delimiter = _char_at(content, index)
            if delimiter not in {"!", ":", "}"}:
                self._raise_at(
                    "XCC-AOT-PYPARSE-0001",
                    "Invalid debug formatted string expression",
                    token.span,
                )

        conversion = -1
        if delimiter == "!":
            conversion_text = _char_at(content, index + 1)
            if conversion_text not in {"a", "r", "s"}:
                self._raise_at(
                    "XCC-AOT-PYPARSE-0001",
                    "Invalid formatted string conversion",
                    token.span,
                )
            conversion = ord(conversion_text)
            index += 2
            delimiter = _char_at(content, index)
            if delimiter not in {":", "}"}:
                self._raise_at(
                    "XCC-AOT-PYPARSE-0001",
                    "Expected ':' or '}' after formatted string conversion",
                    token.span,
                )

        spec_start: int | None = None
        if delimiter == ":":
            spec_start = index + 1
            close = _find_format_spec_end(content, spec_start)
            if close < 0:
                self._raise_at(
                    "XCC-AOT-PYPARSE-0001",
                    "Unterminated formatted string format specifier",
                    token.span,
                )
        else:
            close = index
        return expression_end, debug_end, conversion, spec_start, close

    def _parse_embedded_expression(
        self,
        token: PyToken,
        source: str,
        token_offset: int,
    ) -> ast.expr:
        line, column = _token_text_position(token, token_offset)
        parser = _PythonParser(
            source,
            self.filename,
            line_offset=line - 1,
            column_offset=column,
        )
        return parser.parse_expression_root().body

    def _parse_call_items(
        self,
        closing: str,
    ) -> tuple[list[ast.expr], list[ast.keyword]]:
        arguments: list[ast.expr] = []
        keywords: list[ast.keyword] = []
        while not self._at(closing):
            start = self._current()
            if self._match("**"):
                value = self._parse_expression()
                keywords.append(
                    ast.keyword(
                        None,
                        value,
                        span=self._span_between(start, value),
                        children=(value,),
                    )
                )
            elif self._match("*"):
                value = self._parse_expression()
                context = ast.Load()
                arguments.append(
                    ast.Starred(
                        value,
                        context,
                        span=self._span_between(start, value),
                        children=_children(value, context),
                    )
                )
            elif self._at_kind("NAME") and self._peek_token().text == "=":
                name = self._advance()
                self._advance()
                value = self._parse_expression()
                keywords.append(
                    ast.keyword(
                        name.text,
                        value,
                        span=self._span_between(name, value),
                        children=(value,),
                    )
                )
            else:
                value = self._parse_expression()
                if self._at("for"):
                    generators = self._parse_comprehensions()
                    value = ast.GeneratorExp(
                        value,
                        generators,
                        span=self._span_between(value, generators[-1].iter),
                        children=_children(value, generators),
                    )
                arguments.append(value)
            if not self._match(","):
                break
            if self._at(closing):
                break
        return arguments, keywords

    def _parse_subscript_slice(self) -> ast.expr:
        start = self._current()
        values = [self._parse_slice_item()]
        trailing = False
        trailing_token: PyToken | None = None
        while self._match(","):
            trailing = True
            if self._at("]"):
                trailing_token = self._previous()
                break
            values.append(self._parse_slice_item())
        if len(values) == 1 and not trailing:
            return values[0]
        context = ast.Load()
        return ast.Tuple(
            tuple(values),
            context,
            span=self._span_between(start, trailing_token or values[-1]),
            children=_children(tuple(values), context),
        )

    def _parse_slice_item(self) -> ast.expr:
        start = self._current()
        lower: ast.expr | None = None
        if not self._at(":"):
            lower = self._parse_expression()
        if not self._match(":"):
            if lower is None:
                self._syntax("Expected subscript expression")
            return lower
        last_colon = self._previous()
        upper: ast.expr | None = None
        step: ast.expr | None = None
        if not self._at(":") and not self._at(",") and not self._at("]"):
            upper = self._parse_expression()
        if self._match(":"):
            last_colon = self._previous()
            if not self._at(",") and not self._at("]"):
                step = self._parse_expression()
        end: PyToken | ast.AST = step or upper or last_colon
        return ast.Slice(
            lower,
            upper,
            step,
            span=self._span_between(start, end),
            children=_children(lower, upper, step),
        )

    def _parse_list_display(self, start: PyToken) -> ast.expr:
        if self._match("]"):
            context = ast.Load()
            return ast.List(
                (),
                context,
                span=self._span_between(start, self._previous()),
                children=(context,),
            )
        first = self._parse_star_expression()
        if self._at("for"):
            if isinstance(first, ast.Starred):
                self._syntax("Iterable unpacking is not allowed in a comprehension")
            generators = self._parse_comprehensions()
            end = self._expect("]")
            return ast.ListComp(
                first,
                generators,
                span=self._span_between(start, end),
                children=_children(first, generators),
            )
        elements = [first]
        while self._match(","):
            if self._at("]"):
                break
            elements.append(self._parse_star_expression())
        end = self._expect("]")
        context = ast.Load()
        return ast.List(
            tuple(elements),
            context,
            span=self._span_between(start, end),
            children=_children(tuple(elements), context),
        )

    def _parse_brace_display(self, start: PyToken) -> ast.expr:
        if self._match("}"):
            return ast.Dict((), (), span=self._span_between(start, self._previous()))
        if self._match("**"):
            first_value = self._parse_expression()
            keys: list[ast.expr | None] = [None]
            values = [first_value]
            return self._parse_dict_tail(start, keys, values)
        first = self._parse_expression()
        if self._match(":"):
            first_value = self._parse_expression()
            if self._at("for"):
                generators = self._parse_comprehensions()
                end = self._expect("}")
                return ast.DictComp(
                    first,
                    first_value,
                    generators,
                    span=self._span_between(start, end),
                    children=_children(first, first_value, generators),
                )
            return self._parse_dict_tail(start, [first], [first_value])
        if self._at("for"):
            generators = self._parse_comprehensions()
            end = self._expect("}")
            return ast.SetComp(
                first,
                generators,
                span=self._span_between(start, end),
                children=_children(first, generators),
            )
        elements = [first]
        while self._match(","):
            if self._at("}"):
                break
            elements.append(self._parse_star_expression())
        end = self._expect("}")
        return ast.Set(
            tuple(elements),
            span=self._span_between(start, end),
            children=tuple(elements),
        )

    def _parse_dict_tail(
        self,
        start: PyToken,
        keys: list[ast.expr | None],
        values: list[ast.expr],
    ) -> ast.Dict:
        while self._match(","):
            if self._at("}"):
                break
            if self._match("**"):
                keys.append(None)
                values.append(self._parse_expression())
                continue
            keys.append(self._parse_expression())
            self._expect(":")
            values.append(self._parse_expression())
        end = self._expect("}")
        return ast.Dict(
            tuple(keys),
            tuple(values),
            span=self._span_between(start, end),
            children=_children(tuple(keys), tuple(values)),
        )

    def _parse_comprehensions(self) -> tuple[ast.comprehension, ...]:
        generators: list[ast.comprehension] = []
        while self._match("for"):
            previous = self.stop_at_in
            self.stop_at_in = True
            target = self._parse_expression_list()
            self.stop_at_in = previous
            self._expect("in")
            iterator = self._parse_or()
            filters: list[ast.expr] = []
            while self._match("if"):
                filters.append(self._parse_or())
            stored = self._store(target)
            generators.append(
                ast.comprehension(
                    stored,
                    iterator,
                    tuple(filters),
                    0,
                    children=_children(stored, iterator, tuple(filters)),
                )
            )
        if not generators:
            self._syntax("Expected comprehension clause")
        return tuple(generators)

    def _store(self, value: ast.expr) -> ast.expr:
        context = ast.Store()
        if isinstance(value, ast.Name):
            return ast.Name(
                value.id,
                context,
                span=value.span,
                children=(context,),
            )
        if isinstance(value, ast.Attribute):
            return ast.Attribute(
                value.value,
                value.attr,
                context,
                span=value.span,
                children=_children(value.value, context),
            )
        if isinstance(value, ast.Subscript):
            return ast.Subscript(
                value.value,
                value.slice,
                context,
                span=value.span,
                children=_children(value.value, value.slice, context),
            )
        if isinstance(value, ast.Starred):
            stored = self._store(value.value)
            return ast.Starred(
                stored,
                context,
                span=value.span,
                children=_children(stored, context),
            )
        if isinstance(value, ast.List):
            elements = tuple(self._store(element) for element in value.elts)
            return ast.List(
                elements,
                context,
                span=value.span,
                children=_children(elements, context),
            )
        if isinstance(value, ast.Tuple):
            elements = tuple(self._store(element) for element in value.elts)
            return ast.Tuple(
                elements,
                context,
                span=value.span,
                children=_children(elements, context),
            )
        self._raise_at(
            "XCC-AOT-PYPARSE-0001",
            "Invalid assignment target",
            value.span,
        )

    def _current(self) -> PyToken:
        return self.tokens[self.index]

    def _span_between(
        self,
        start: PyToken | ast.AST,
        end: PyToken | ast.AST,
    ) -> ast.SourceSpan:
        start_span = self._expression_extent(start)
        end_span = self._expression_extent(end)
        return ast.SourceSpan(
            start_span.line,
            start_span.column,
            end_span.end_line,
            end_span.end_column,
        )

    def _expression_extent(self, value: PyToken | ast.AST) -> ast.SourceSpan:
        if isinstance(value, ast.expr):
            for expression, span in reversed(self.expression_extents):
                if expression is value:
                    return span
        return value.span

    def _looks_like_match_statement(self) -> bool:
        depth = 0
        offset = 1
        if self._peek_token().text == ":":
            return False
        while True:
            token = self._peek_token(offset)
            if token.kind in {"NEWLINE", "EOF"}:
                return False
            if token.text in {"(", "[", "{"}:
                depth += 1
            elif token.text in {")", "]", "}"}:
                depth -= 1
            elif depth == 0 and token.text == ":":
                return True
            elif depth == 0 and (token.text == "=" or token.text in _AUGMENTED_OPERATORS):
                return False
            offset += 1

    def _previous(self) -> PyToken:
        return self.tokens[self.index - 1]

    def _peek_token(self, offset: int = 1) -> PyToken:
        index = self.index + offset
        if index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[index]

    def _advance(self) -> PyToken:
        token = self._current()
        if token.kind != "EOF":
            self.index += 1
        return token

    def _at(self, text: str) -> bool:
        return self._current().text == text

    def _at_kind(self, kind: str) -> bool:
        return self._current().kind == kind

    def _match(self, text: str) -> bool:
        if not self._at(text):
            return False
        self._advance()
        return True

    def _match_kind(self, kind: str) -> bool:
        if not self._at_kind(kind):
            return False
        self._advance()
        return True

    def _expect(self, text: str) -> PyToken:
        if not self._at(text):
            self._syntax(f"Expected {text!r}, found {self._current().text!r}")
        return self._advance()

    def _expect_kind(self, kind: str, message: str) -> PyToken:
        if not self._at_kind(kind):
            self._syntax(message)
        return self._advance()

    def _syntax(self, message: str) -> NoReturn:
        self._raise_at("XCC-AOT-PYPARSE-0001", message, self._current().span)

    def _excluded(self, message: str) -> NoReturn:
        self._raise_at("XCC-AOT-PYPARSE-0002", message, self._current().span)

    def _raise_at(self, code: str, message: str, span: ast.SourceSpan) -> NoReturn:
        raise AotError(
            (
                AotDiagnostic(
                    code,
                    message,
                    filename=self.filename,
                    line=span.line,
                    column=span.column,
                ),
            )
        )


def _split_string_token(text: str) -> tuple[str, str, int]:
    quote_index = 0
    while quote_index < len(text) and text[quote_index] not in {"'", '"'}:
        quote_index += 1
    prefix = text[:quote_index].lower()
    quote_length = 1
    if text[quote_index : quote_index + 3] in {"'''", '"""'}:
        quote_length = 3
    content_offset = quote_index + quote_length
    return prefix, text[content_offset:-quote_length], content_offset


def _decode_string_content(
    content: str,
    is_raw: bool,
    is_bytes: bool,
) -> str | bytes:
    if is_bytes:
        return _decode_bytes_content(content, is_raw)
    if is_raw:
        return content
    result = ""
    index = 0
    while index < len(content):
        ch = content[index]
        if ch != "\\":
            result += ch
            index += 1
            continue
        index += 1
        if index >= len(content):
            raise ValueError("Trailing backslash in string literal")
        escaped = content[index]
        if escaped == "\n":
            index += 1
            continue
        if escaped == "\r":
            index += 1
            if index < len(content) and content[index] == "\n":
                index += 1
            continue
        mapped = _simple_escape(escaped)
        if mapped is not None:
            result += mapped
            index += 1
            continue
        if "0" <= escaped <= "7":
            value, index = _consume_octal_escape(content, index)
            result += chr(value)
            continue
        if escaped == "x":
            value, index = _consume_hex_escape(content, index + 1, 2)
            result += chr(value)
            continue
        if escaped == "u":
            value, index = _consume_hex_escape(content, index + 1, 4)
            result += chr(value)
            continue
        if escaped == "U":
            value, index = _consume_hex_escape(content, index + 1, 8)
            result += chr(value)
            continue
        if escaped == "N":
            raise ValueError("Named Unicode escapes are outside the bootstrap subset")
        result += "\\" + escaped
        index += 1
    return result


def _decode_bytes_content(content: str, is_raw: bool) -> bytes:
    result: list[int] = []
    index = 0
    while index < len(content):
        ch = content[index]
        if ch != "\\" or is_raw:
            value = ord(ch)
            if value > 127:
                raise ValueError("Bytes literals may contain only ASCII source characters")
            result.append(value)
            index += 1
            continue
        index += 1
        if index >= len(content):
            raise ValueError("Trailing backslash in bytes literal")
        escaped = content[index]
        if escaped == "\n":
            index += 1
            continue
        if escaped == "\r":
            index += 1
            if index < len(content) and content[index] == "\n":
                index += 1
            continue
        mapped = _simple_escape(escaped)
        if mapped is not None:
            result.append(ord(mapped))
            index += 1
            continue
        if "0" <= escaped <= "7":
            value, index = _consume_octal_escape(content, index)
            result.append(value & 255)
            continue
        if escaped == "x":
            value, index = _consume_hex_escape(content, index + 1, 2)
            result.append(value)
            continue
        result.append(ord("\\"))
        result.append(ord(escaped))
        index += 1
    return bytes(result)


def _simple_escape(ch: str) -> str | None:
    if ch == "\\":
        return "\\"
    if ch == "'":
        return "'"
    if ch == '"':
        return '"'
    if ch == "a":
        return "\a"
    if ch == "b":
        return "\b"
    if ch == "f":
        return "\f"
    if ch == "n":
        return "\n"
    if ch == "r":
        return "\r"
    if ch == "t":
        return "\t"
    if ch == "v":
        return "\v"
    return None


def _consume_octal_escape(content: str, start: int) -> tuple[int, int]:
    value = 0
    index = start
    count = 0
    while index < len(content) and count < 3 and "0" <= content[index] <= "7":
        value = value * 8 + ord(content[index]) - ord("0")
        index += 1
        count += 1
    return value, index


def _consume_hex_escape(content: str, start: int, length: int) -> tuple[int, int]:
    end = start + length
    if end > len(content):
        raise ValueError("Truncated hexadecimal escape in string literal")
    value = 0
    for ch in content[start:end]:
        digit = _hex_digit(ch)
        if digit < 0:
            raise ValueError("Invalid hexadecimal escape in string literal")
        value = value * 16 + digit
    return value, end


def _hex_digit(ch: str) -> int:
    if "0" <= ch <= "9":
        return ord(ch) - ord("0")
    lowered = ch.lower()
    if "a" <= lowered <= "f":
        return ord(lowered) - ord("a") + 10
    return -1


def _append_joined_value(values: list[ast.expr], value: ast.expr) -> None:
    if isinstance(value, ast.Constant) and value.value == "":
        return
    if values and isinstance(values[-1], ast.Constant) and isinstance(value, ast.Constant):
        previous = values[-1]
        previous_text = previous.value
        value_text = value.value
        if isinstance(previous_text, str) and isinstance(value_text, str):
            values[-1] = ast.Constant(
                previous_text + value_text,
                None,
                span=_span_between(previous, value),
            )
            return
    values.append(value)


def _respan_fstring_values(
    values: tuple[ast.expr, ...],
    span: ast.SourceSpan,
) -> tuple[ast.expr, ...]:
    result: list[ast.expr] = []
    for value in values:
        if isinstance(value, ast.Constant):
            result.append(ast.Constant(value.value, value.kind, span=span))
            continue
        if isinstance(value, ast.FormattedValue):
            format_spec = value.format_spec
            if isinstance(format_spec, ast.JoinedStr):
                spec_values = _respan_fstring_values(format_spec.values, span)
                format_spec = ast.JoinedStr(
                    spec_values,
                    span=span,
                    children=spec_values,
                )
            result.append(
                ast.FormattedValue(
                    value.value,
                    value.conversion,
                    format_spec,
                    span=span,
                    children=_children(value.value, format_spec),
                )
            )
            continue
        result.append(value)
    return tuple(result)


def _skip_quoted_text(text: str, start: int) -> int:
    quote = text[start]
    triple = text[start : start + 3] == quote * 3
    index = start + (3 if triple else 1)
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if triple and text[index : index + 3] == quote * 3:
            return index + 3
        if not triple and text[index] == quote:
            return index + 1
        index += 1
    return len(text)


def _delimiters_match(opening: str, closing: str) -> bool:
    return (
        opening == "("
        and closing == ")"
        or opening == "["
        and closing == "]"
        or opening == "{"
        and closing == "}"
    )


def _is_debug_equals(text: str, index: int) -> bool:
    previous = _char_at(text, index - 1)
    following = _char_at(text, index + 1)
    return previous not in {"=", "!", "<", ">", ":"} and following != "="


def _find_format_spec_end(text: str, start: int) -> int:
    depth = 0
    index = start
    while index < len(text):
        ch = text[index]
        if ch in {"'", '"'} and depth > 0:
            index = _skip_quoted_text(text, index)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            if depth == 0:
                return index
            depth -= 1
        index += 1
    return -1


def _token_text_position(token: PyToken, offset: int) -> tuple[int, int]:
    prefix = token.text[:offset]
    line = token.span.line or 1
    column = token.span.column or 0
    newline = prefix.rfind("\n")
    if newline >= 0:
        line += prefix.count("\n")
        column = len(prefix[newline + 1 :].encode("utf-8"))
    else:
        column += len(prefix.encode("utf-8"))
    return line, column


def _char_at(text: str, index: int) -> str:
    if index < 0 or index >= len(text):
        return ""
    return text[index]


def _decode_number(text: str) -> object:
    cleaned = text.replace("_", "")
    if cleaned.endswith(("j", "J")):
        return complex(0.0, float(cleaned[:-1]))
    if cleaned.lower().startswith("0x"):
        return _decode_integer(cleaned[2:], 16)
    if cleaned.lower().startswith("0b"):
        return _decode_integer(cleaned[2:], 2)
    if cleaned.lower().startswith("0o"):
        return _decode_integer(cleaned[2:], 8)
    if "." in cleaned or "e" in cleaned.lower():
        return float(cleaned)
    return _decode_integer(cleaned, 10)


def _decode_integer(text: str, base: int) -> int:
    result = 0
    for ch in text:
        value = ord(ch) - ord("0") if "0" <= ch <= "9" else ord(ch.lower()) - ord("a") + 10
        result = result * base + value
    return result


def _children(*values: object) -> tuple[ast.AST, ...]:
    result: list[ast.AST] = []
    for value in values:
        if isinstance(value, ast.AST):
            result.append(value)
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, ast.AST):
                    result.append(item)
    return tuple(result)


def _span_between(
    start: PyToken | ast.AST,
    end: PyToken | ast.AST,
) -> ast.SourceSpan:
    start_span = start.span
    end_span = end.span
    return ast.SourceSpan(
        start_span.line,
        start_span.column,
        end_span.end_line,
        end_span.end_column,
    )


def _shift_token(token: PyToken, line_offset: int, column_offset: int) -> PyToken:
    span = token.span
    if span.line is None or span.end_line is None:
        return token
    column = span.column
    end_column = span.end_column
    if span.line == 1 and column is not None:
        column += column_offset
    if span.end_line == 1 and end_column is not None:
        end_column += column_offset
    return PyToken(
        token.kind,
        token.text,
        ast.SourceSpan(
            span.line + line_offset,
            column,
            span.end_line + line_offset,
            end_column,
        ),
    )
