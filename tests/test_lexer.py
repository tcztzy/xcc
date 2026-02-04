from __future__ import annotations

import unittest

from tests import _bootstrap  # noqa: F401
from xcc.lexer import Lexer, LexerError, TokenKind, lex


class LexerTests(unittest.TestCase):
    def test_basic_tokens(self) -> None:
        source = "int main(){return 42;}"
        tokens = list(lex(source))
        kinds_values = [(t.kind, t.value) for t in tokens]
        self.assertEqual(
            kinds_values,
            [
                (TokenKind.KEYWORD, "int"),
                (TokenKind.IDENT, "main"),
                (TokenKind.PUNCT, "("),
                (TokenKind.PUNCT, ")"),
                (TokenKind.PUNCT, "{"),
                (TokenKind.KEYWORD, "return"),
                (TokenKind.INT, 42),
                (TokenKind.PUNCT, ";"),
                (TokenKind.PUNCT, "}"),
                (TokenKind.EOF, None),
            ],
        )

    def test_comments_and_whitespace(self) -> None:
        source = "int /*c*/\n// line\nmain() {return 0;}"
        tokens = list(lex(source))
        self.assertEqual(tokens[0].value, "int")
        self.assertEqual(tokens[1].value, "main")
        self.assertEqual(tokens[1].line, 3)

    def test_hex_literal(self) -> None:
        tokens = list(lex("int x=0x1f;"))
        values = [t.value for t in tokens if t.kind == TokenKind.INT]
        self.assertEqual(values, [31])

    def test_punctuator_longest_match(self) -> None:
        tokens = list(lex("a>>=1;"))
        punct = [t.value for t in tokens if t.kind == TokenKind.PUNCT]
        self.assertIn(">>=", punct)

    def test_unterminated_comment(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("/*"))

    def test_unterminated_string(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("\"unterminated"))

    def test_string_newline_error(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("\"line1\nline2\""))

    def test_invalid_hex(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("0x"))

    def test_char_literal(self) -> None:
        tokens = list(lex("'a'"))
        self.assertEqual(tokens[0].value, "a")

    def test_char_escape_quote(self) -> None:
        tokens = list(lex("'\\''"))
        self.assertEqual(tokens[0].value, "'")

    def test_string_escapes(self) -> None:
        source = "\"\\n\\t\\r\\0\\\\\\\"\""
        tokens = list(lex(source))
        self.assertEqual(tokens[0].value, "\n\t\r\0\\\"")

    def test_invalid_escape(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("'\\q'"))

    def test_unexpected_character(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("@"))

    def test_unterminated_char(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("'a"))

    def test_unterminated_char_eof(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("'"))

    def test_internal_eof_paths(self) -> None:
        lexer = Lexer("")
        self.assertEqual(lexer._advance(), "")
        self.assertEqual(lexer._read_identifier(), "")


if __name__ == "__main__":
    unittest.main()
