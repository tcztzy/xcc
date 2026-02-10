import unittest

from tests import _bootstrap  # noqa: F401
from xcc.lexer import Lexer, LexerError, TokenKind, lex, lex_pp, translate_source


class TranslateTests(unittest.TestCase):
    def test_translate_trigraphs_and_splice(self) -> None:
        self.assertEqual(translate_source("??=x"), "#x")
        self.assertEqual(translate_source("a\\\n b"), "a b")
        self.assertEqual(translate_source("??/\n"), "")

    def test_translate_newlines(self) -> None:
        self.assertEqual(translate_source("a\r\nb\rc"), "a\nb\nc")


class LexerTokenTests(unittest.TestCase):
    def test_basic_tokens(self) -> None:
        tokens = list(lex("int main(){return 42;}"))
        kinds = [t.kind for t in tokens]
        lexemes = [t.lexeme for t in tokens]
        self.assertEqual(
            kinds,
            [
                TokenKind.KEYWORD,
                TokenKind.IDENT,
                TokenKind.PUNCTUATOR,
                TokenKind.PUNCTUATOR,
                TokenKind.PUNCTUATOR,
                TokenKind.KEYWORD,
                TokenKind.INT_CONST,
                TokenKind.PUNCTUATOR,
                TokenKind.PUNCTUATOR,
                TokenKind.EOF,
            ],
        )
        self.assertEqual(
            lexemes,
            ["int", "main", "(", ")", "{", "return", "42", ";", "}", None],
        )

    def test_keyword_vs_identifier(self) -> None:
        tokens = list(lex("_Alignas alignas"))
        self.assertEqual(tokens[0].kind, TokenKind.KEYWORD)
        self.assertEqual(tokens[1].kind, TokenKind.IDENT)

    def test_extension_marker_keyword(self) -> None:
        tokens = list(lex("__extension__ ext"))
        self.assertEqual(tokens[0].kind, TokenKind.KEYWORD)
        self.assertEqual(tokens[1].kind, TokenKind.IDENT)

    def test_comments_and_whitespace(self) -> None:
        source = "int /*c*/\n// line\nmain() {return 0;}"
        tokens = list(lex(source))
        self.assertEqual(tokens[0].lexeme, "int")
        self.assertEqual(tokens[1].lexeme, "main")
        self.assertEqual(tokens[1].line, 3)

    def test_spliced_line_comment(self) -> None:
        tokens = list(lex("//\\\nint"))
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].kind, TokenKind.EOF)

    def test_unterminated_comment(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("/*"))

    def test_punctuators(self) -> None:
        tokens = list(lex("a>>=1;"))
        punct = [t.lexeme for t in tokens if t.kind == TokenKind.PUNCTUATOR]
        self.assertIn(">>=", punct)

    def test_digraphs(self) -> None:
        tokens = list(lex("<: :> <% %> %: %:%:"))
        punct = [t.lexeme for t in tokens if t.kind == TokenKind.PUNCTUATOR]
        self.assertEqual(punct[:6], ["<:", ":>", "<%", "%>", "%:", "%:%:"])


class IdentifierTests(unittest.TestCase):
    def test_identifier_with_ucn(self) -> None:
        tokens = list(lex("\\u00A0_name"))
        self.assertEqual(tokens[0].kind, TokenKind.IDENT)
        self.assertEqual(tokens[0].lexeme, "\\u00A0_name")

    def test_identifier_with_ucn_allowed_low(self) -> None:
        tokens = list(lex("\\u0040id"))
        self.assertEqual(tokens[0].lexeme, "\\u0040id")

    def test_ucn_invalid_hex(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("\\u12G4"))

    def test_ucn_invalid_low_codepoint(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("\\u0001"))

    def test_ucn_invalid_surrogate(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("\\uD800"))

    def test_ucn_invalid_too_large(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("\\U00110000"))

    def test_ucn_invalid_prefix(self) -> None:
        lexer = Lexer("u1234")
        with self.assertRaises(LexerError):
            lexer._read_ucn()

    def test_ucn_invalid_kind(self) -> None:
        lexer = Lexer("\\x1234")
        with self.assertRaises(LexerError):
            lexer._read_ucn()

    def test_identifier_direct_error(self) -> None:
        lexer = Lexer("1abc")
        with self.assertRaises(LexerError):
            lexer._read_identifier()


class LiteralTests(unittest.TestCase):
    def test_string_prefixes(self) -> None:
        source = '"a" u8"b" u"c" U"d" L"e"'
        tokens = [t for t in lex(source) if t.kind == TokenKind.STRING_LITERAL]
        self.assertEqual(
            [t.lexeme for t in tokens],
            ['"a"', 'u8"b"', 'u"c"', 'U"d"', 'L"e"'],
        )

    def test_string_escapes(self) -> None:
        source = '"' + '\\n\\t\\r\\0\\a\\b\\f\\v\\?\\\\\\"\\x41\\u00A0' + '"'
        tokens = list(lex(source))
        self.assertEqual(tokens[0].kind, TokenKind.STRING_LITERAL)

    def test_invalid_escape(self) -> None:
        with self.assertRaises(LexerError):
            list(lex(r'"\q"'))

    def test_invalid_hex_escape(self) -> None:
        with self.assertRaises(LexerError):
            list(lex('"\\xZ"'))

    def test_string_newline_error(self) -> None:
        with self.assertRaises(LexerError):
            list(lex('"line1\nline2"'))

    def test_char_constants(self) -> None:
        tokens = list(lex("'a' L'\\n' u'\\x41' U'\\u00A0' 'ab'"))
        chars = [t.lexeme for t in tokens if t.kind == TokenKind.CHAR_CONST]
        self.assertEqual(chars, ["'a'", "L'\\n'", "u'\\x41'", "U'\\u00A0'", "'ab'"])

    def test_char_empty_error(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("''"))

    def test_unterminated_char(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("'a"))

    def test_char_newline_error(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("'a\n'"))

    def test_octal_escape_lengths(self) -> None:
        tokens = list(lex(r'"\1" "\12" "\123"'))
        self.assertEqual(len([t for t in tokens if t.kind == TokenKind.STRING_LITERAL]), 3)


class NumberTests(unittest.TestCase):
    def test_integer_constants(self) -> None:
        source = "0 7 077 0x1f 123u 456UL 789llu 42LL 5lU"
        tokens = [t.lexeme for t in lex(source) if t.kind == TokenKind.INT_CONST]
        self.assertEqual(
            tokens, ["0", "7", "077", "0x1f", "123u", "456UL", "789llu", "42LL", "5lU"]
        )

    def test_floating_constants(self) -> None:
        source = "1.0 .5 1. 1e3 1e-3 1.2e+3 0x1p2 0x1.2p+3 0x.8p-1 1.0f 2.0L"
        tokens = [t.lexeme for t in lex(source) if t.kind == TokenKind.FLOAT_CONST]
        self.assertEqual(
            tokens,
            [
                "1.0",
                ".5",
                "1.",
                "1e3",
                "1e-3",
                "1.2e+3",
                "0x1p2",
                "0x1.2p+3",
                "0x.8p-1",
                "1.0f",
                "2.0L",
            ],
        )

    def test_invalid_numbers(self) -> None:
        for text in ["0x", "08", "1e", "1f", "0x1p"]:
            with self.subTest(text=text), self.assertRaises(LexerError):
                list(lex(text))

    def test_pp_numbers(self) -> None:
        tokens = list(lex_pp("1e+2 1E-2 .1e+2 1abc 0x1p+2", header_names=False))
        kinds = [t.kind for t in tokens]
        self.assertTrue(all(kind in {TokenKind.PP_NUMBER, TokenKind.EOF} for kind in kinds))
        self.assertEqual(tokens[0].lexeme, "1e+2")

    def test_pp_numbers_with_ucn(self) -> None:
        tokens = list(lex_pp("1\\u00A0", header_names=False))
        self.assertEqual(tokens[0].kind, TokenKind.PP_NUMBER)


class HeaderNameTests(unittest.TestCase):
    def test_header_name(self) -> None:
        tokens = list(lex_pp("<stdio.h>", header_names=True))
        self.assertEqual(tokens[0].kind, TokenKind.HEADER_NAME)
        self.assertEqual(tokens[0].lexeme, "<stdio.h>")

    def test_header_name_skipped(self) -> None:
        tokens = list(lex_pp("int", header_names=True))
        self.assertEqual(tokens[0].kind, TokenKind.IDENT)

    def test_header_name_invalid(self) -> None:
        for text in ["<a\\b>", "<a/*b>", '"a//b"', "<a\nb>", "<a"]:
            with self.subTest(text=text), self.assertRaises(LexerError):
                list(lex_pp(text, header_names=True))


class ErrorTests(unittest.TestCase):
    def test_unexpected_character(self) -> None:
        with self.assertRaises(LexerError):
            list(lex("@"))

    def test_invalid_mode(self) -> None:
        with self.assertRaises(ValueError):
            Lexer("", mode="bad")

    def test_advance_at_eof(self) -> None:
        lexer = Lexer("")
        self.assertEqual(lexer._advance(), "")

    def test_invalid_identifier_char(self) -> None:
        lexer = Lexer("@")
        with self.assertRaises(LexerError):
            lexer._read_identifier_char(initial=True)

    def test_expected_string_literal(self) -> None:
        lexer = Lexer("abc")
        with self.assertRaises(LexerError):
            lexer._read_string_literal(0)

    def test_unterminated_string_eof(self) -> None:
        lexer = Lexer('"unterminated')
        with self.assertRaises(LexerError):
            lexer._read_string_literal(0)

    def test_expected_char_constant(self) -> None:
        lexer = Lexer("abc")
        with self.assertRaises(LexerError):
            lexer._read_char_constant(0)

    def test_ucn_escape_invalid_kind(self) -> None:
        lexer = Lexer("x1234")
        with self.assertRaises(LexerError):
            lexer._read_ucn_escape()


if __name__ == "__main__":
    unittest.main()
