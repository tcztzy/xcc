from dataclasses import dataclass

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.py_ast import SourceSpan

_MULTI_OPERATORS = (
    "**=",
    "//=",
    "<<=",
    ">>=",
    "...",
    ":=",
    "->",
    "**",
    "//",
    "<<",
    ">>",
    "<=",
    ">=",
    "==",
    "!=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "@=",
    "&=",
    "|=",
    "^=",
)
_SINGLE_OPERATORS = "()[]{}:,.;+-*/%@&|^~<>="
_STRING_PREFIXES = {
    "b",
    "br",
    "f",
    "fr",
    "r",
    "rb",
    "rf",
    "u",
}


@dataclass(frozen=True)
class PyToken:
    kind: str
    text: str
    span: SourceSpan


def lex_python(source: str, *, filename: str = "<input>") -> tuple[PyToken, ...]:
    return _PythonLexer(source, filename).lex()


class _PythonLexer:
    def __init__(self, source: str, filename: str) -> None:
        self.source = source
        self.filename = filename
        self.index = 0
        self.line = 1
        self.column = 0
        self.indents = [0]
        self.nesting = 0
        self.at_line_start = True
        self.continued_line = False
        self.line_has_code = False
        self.tokens: list[PyToken] = []

    def lex(self) -> tuple[PyToken, ...]:
        while not self._at_end():
            if self.at_line_start:
                self._lex_line_start()
                if self._at_end():
                    break
            ch = self._peek()
            if ch in " \t\f":
                self._advance()
                continue
            if ch == "#":
                self._skip_comment()
                continue
            if ch in "\r\n":
                self._lex_newline()
                continue
            if ch == "\\":
                self._lex_explicit_continuation()
                continue
            prefix_length = self._string_prefix_length()
            if ch in {'"', "'"} or prefix_length > 0:
                self._lex_string(prefix_length)
                continue
            if _is_identifier_start(ch):
                self._lex_name()
                continue
            if ch.isdigit() or ch == "." and self._peek(1).isdigit():
                self._lex_number()
                continue
            if self._lex_operator():
                continue
            self._raise(
                "XCC-AOT-PYLEX-0001",
                f"Unsupported character: {ch!r}",
                self.line,
                self.column,
            )
        self._finish()
        return tuple(self.tokens)

    def _lex_line_start(self) -> None:
        start_line = self.line
        start_column = self.column
        start_index = self.index
        visual_indent = 0
        while not self._at_end() and self._peek() in " \t\f":
            ch = self._advance()
            if ch == " ":
                visual_indent += 1
            elif ch == "\t":
                visual_indent = (visual_indent // 8 + 1) * 8
            else:
                visual_indent = 0
        ch = self._peek()
        if self.nesting > 0 or self.continued_line:
            self.at_line_start = False
            self.continued_line = False
            return
        if not ch or ch in "\r\n#":
            self.at_line_start = False
            return
        current = self.indents[-1]
        if visual_indent > current:
            self.indents.append(visual_indent)
            self._emit_from(
                "INDENT",
                start_index,
                start_line,
                start_column,
            )
        elif visual_indent < current:
            while len(self.indents) > 1 and visual_indent < self.indents[-1]:
                self.indents.pop()
                self._emit_point("DEDENT", "")
            if visual_indent != self.indents[-1]:
                self._raise(
                    "XCC-AOT-PYLEX-0003",
                    "Unindent does not match an outer indentation level",
                    self.line,
                    self.column,
                )
        self.at_line_start = False

    def _skip_comment(self) -> None:
        while not self._at_end() and self._peek() not in "\r\n":
            self._advance()

    def _lex_newline(self) -> None:
        start_line = self.line
        start_column = self.column
        start_index = self.index
        self._consume_newline()
        if self.nesting == 0 and self.line_has_code:
            text = self.source[start_index : self.index]
            self.tokens.append(
                PyToken(
                    "NEWLINE",
                    text,
                    SourceSpan(
                        start_line,
                        start_column,
                        start_line,
                        start_column + len(text.encode("utf-8")),
                    ),
                )
            )
        self.at_line_start = True
        self.line_has_code = False

    def _lex_explicit_continuation(self) -> None:
        line = self.line
        column = self.column
        self._advance()
        if not _is_one_of(self._peek(), "\r\n"):
            self._raise(
                "XCC-AOT-PYLEX-0001",
                "Unexpected character after line continuation",
                line,
                column,
            )
        self._consume_newline()
        self.at_line_start = True
        self.continued_line = True

    def _lex_name(self) -> None:
        start_line = self.line
        start_column = self.column
        start_index = self.index
        self._advance()
        while _is_identifier_continue(self._peek()):
            self._advance()
        self._emit_from("NAME", start_index, start_line, start_column)
        self.line_has_code = True

    def _lex_number(self) -> None:
        start_line = self.line
        start_column = self.column
        start_index = self.index
        if self._peek() == ".":
            self._advance()
            self._consume_decimal_digits()
            self._consume_exponent()
        elif self._peek() == "0" and _is_one_of(self._peek(1), "xXbBoO"):
            self._advance()
            self._advance()
            while _is_number_digit(self._peek()):
                self._advance()
        else:
            self._consume_decimal_digits()
            if self._peek() == ".":
                self._advance()
                self._consume_decimal_digits()
            self._consume_exponent()
        if _is_one_of(self._peek(), "jJ"):
            self._advance()
        self._emit_from("NUMBER", start_index, start_line, start_column)
        self.line_has_code = True

    def _consume_decimal_digits(self) -> None:
        while self._peek().isdigit() or self._peek() == "_":
            self._advance()

    def _consume_exponent(self) -> None:
        if not _is_one_of(self._peek(), "eE"):
            return
        self._advance()
        if _is_one_of(self._peek(), "+-"):
            self._advance()
        self._consume_decimal_digits()

    def _string_prefix_length(self) -> int:
        if self._peek() in {'"', "'"}:
            return 0
        first = self._peek()
        if first.lower() not in {"b", "f", "r", "u"}:
            return 0
        one = first.lower()
        if self._peek(1) in {'"', "'"} and one in _STRING_PREFIXES:
            return 1
        two = (first + self._peek(1)).lower()
        if self._peek(2) in {'"', "'"} and two in _STRING_PREFIXES:
            return 2
        return 0

    def _lex_string(self, prefix_length: int) -> None:
        start_line = self.line
        start_column = self.column
        start_index = self.index
        for _ in range(prefix_length):
            self._advance()
        quote = self._advance()
        triple = self._peek() == quote and self._peek(1) == quote
        if triple:
            self._advance()
            self._advance()
        while not self._at_end():
            ch = self._peek()
            if ch == "\\":
                self._advance()
                if _is_one_of(self._peek(), "\r\n"):
                    self._consume_newline()
                elif not self._at_end():
                    self._advance()
                continue
            if ch == quote:
                if triple:
                    if self._peek(1) == quote and self._peek(2) == quote:
                        self._advance()
                        self._advance()
                        self._advance()
                        self._emit_from("STRING", start_index, start_line, start_column)
                        self.line_has_code = True
                        return
                    self._advance()
                    continue
                self._advance()
                self._emit_from("STRING", start_index, start_line, start_column)
                self.line_has_code = True
                return
            if ch in "\r\n":
                if not triple:
                    self._raise(
                        "XCC-AOT-PYLEX-0002",
                        "Unterminated string literal",
                        start_line,
                        start_column,
                    )
                self._consume_newline()
                continue
            self._advance()
        self._raise(
            "XCC-AOT-PYLEX-0002",
            "Unterminated string literal",
            start_line,
            start_column,
        )

    def _lex_operator(self) -> bool:
        start_line = self.line
        start_column = self.column
        start_index = self.index
        for operator in _MULTI_OPERATORS:
            if self.source.startswith(operator, self.index):
                for _ in range(len(operator)):
                    self._advance()
                self._emit_from("OP", start_index, start_line, start_column)
                self._update_nesting(operator)
                self.line_has_code = True
                return True
        ch = self._peek()
        if not _is_one_of(ch, _SINGLE_OPERATORS):
            return False
        self._advance()
        self._emit_from("OP", start_index, start_line, start_column)
        self._update_nesting(ch)
        self.line_has_code = True
        return True

    def _update_nesting(self, operator: str) -> None:
        if operator in {"(", "[", "{"}:
            self.nesting += 1
        elif operator in {
            ")",
            "]",
            "}",
        }:
            self.nesting -= 1
            if self.nesting < 0:
                self._raise(
                    "XCC-AOT-PYLEX-0001",
                    f"Unmatched closing delimiter: {operator}",
                    self.line,
                    self.column - 1,
                )

    def _finish(self) -> None:
        if self.line_has_code:
            self._emit_point("NEWLINE", "")
        while len(self.indents) > 1:
            self.indents.pop()
            self._emit_point("DEDENT", "")
        self._emit_point("EOF", "")

    def _emit_from(
        self,
        kind: str,
        start_index: int,
        start_line: int,
        start_column: int,
    ) -> None:
        self.tokens.append(
            PyToken(
                kind,
                self.source[start_index : self.index],
                SourceSpan(start_line, start_column, self.line, self.column),
            )
        )

    def _emit_point(self, kind: str, text: str) -> None:
        self.tokens.append(
            PyToken(
                kind,
                text,
                SourceSpan(self.line, self.column, self.line, self.column),
            )
        )

    def _consume_newline(self) -> None:
        if self._peek() == "\r":
            self.index += 1
            if self._peek() == "\n":
                self.index += 1
        elif self._peek() == "\n":
            self.index += 1
        self.line += 1
        self.column = 0

    def _advance(self) -> str:
        ch = self._peek()
        if not ch:
            return ""
        self.index += 1
        self.column += len(ch.encode("utf-8"))
        return ch

    def _peek(self, offset: int = 0) -> str:
        index = self.index + offset
        if index < 0 or index >= len(self.source):
            return ""
        return self.source[index]

    def _at_end(self) -> bool:
        return self.index >= len(self.source)

    def _raise(self, code: str, message: str, line: int, column: int) -> None:
        raise AotError(
            (
                AotDiagnostic(
                    code,
                    message,
                    filename=self.filename,
                    line=line,
                    column=column,
                ),
            )
        )


def _is_identifier_start(ch: str) -> bool:
    return bool(ch) and (ch == "_" or ch.isalpha())


def _is_identifier_continue(ch: str) -> bool:
    return bool(ch) and (ch == "_" or ch.isalnum())


def _is_number_digit(ch: str) -> bool:
    return bool(ch) and (ch.isalnum() or ch == "_")


def _is_one_of(ch: str, choices: str) -> bool:
    return bool(ch) and ch in choices
