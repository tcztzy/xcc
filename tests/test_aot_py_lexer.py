import io
import token
import tokenize
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot.diag import AotError
from xcc.aot.py_lexer import PyToken, lex_python

ROOT = Path(__file__).resolve().parents[1]
_IGNORED_CPYTHON_KINDS = {tokenize.COMMENT, tokenize.NL}


def _byte_column(source_lines: list[str], line: int, column: int) -> int:
    if line < 1 or line > len(source_lines):
        return column
    return len(source_lines[line - 1][:column].encode("utf-8"))


def _cpython_tokens(source: str) -> tuple[tuple[object, ...], ...]:
    source_lines = source.splitlines(keepends=True)
    result: list[tuple[object, ...]] = []
    for item in tokenize.generate_tokens(io.StringIO(source).readline):
        if item.type in _IGNORED_CPYTHON_KINDS:
            continue
        kind = token.tok_name[item.type]
        if kind == "ENDMARKER":
            kind = "EOF"
        start_line, start_column = item.start
        end_line, end_column = item.end
        result.append(
            (
                kind,
                item.string,
                start_line,
                _byte_column(source_lines, start_line, start_column),
                end_line,
                _byte_column(source_lines, end_line, end_column),
            )
        )
    return tuple(result)


def _owned_tokens(source: str) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            item.kind,
            item.text,
            item.span.line,
            item.span.column,
            item.span.end_line,
            item.span.end_column,
        )
        for item in lex_python(source, filename="fixture.py")
    )


class AotPythonLexerTests(unittest.TestCase):
    def test_matches_cpython_for_indentation_continuations_and_literals(self) -> None:
        source = (
            "def choose(value: int) -> str:\n"
            "    # ignored comment\n"
            "    if value >= 0x10:\n"
            "        parts = [\n"
            "            f'value={value!r}',\n"
            "            r'raw\\n',\n"
            "        ]\n"
            "        return parts[0]\n"
            "    return (\n"
            "        'no'\n"
            "    )\n"
        )

        self.assertEqual(_owned_tokens(source), _cpython_tokens(source))

    def test_matches_cpython_for_multiline_and_explicit_continuation(self) -> None:
        source = (
            "value = 1 + \\\n"
            "    2\n"
            "text = '''first\nsecond'''\n"
            "data = b'\\x41\\n'\n"
        )

        self.assertEqual(_owned_tokens(source), _cpython_tokens(source))

    def test_uses_zero_based_utf8_byte_columns(self) -> None:
        tokens = lex_python('π = "é"\n', filename="unicode.py")
        name = tokens[0]
        value = tokens[2]

        self.assertEqual((name.kind, name.text), ("NAME", "π"))
        self.assertEqual(
            (name.span.line, name.span.column, name.span.end_line, name.span.end_column),
            (1, 0, 1, 2),
        )
        self.assertEqual(
            (value.span.line, value.span.column, value.span.end_line, value.span.end_column),
            (1, 5, 1, 9),
        )

    def test_reports_stable_unterminated_string_and_indent_diagnostics(self) -> None:
        cases = (
            ("value = 'unterminated\n", "XCC-AOT-PYLEX-0002"),
            ("if True:\n    value = 1\n  other = 2\n", "XCC-AOT-PYLEX-0003"),
            ("value = `bad`\n", "XCC-AOT-PYLEX-0001"),
            ("value = 1 \\", "XCC-AOT-PYLEX-0001"),
        )
        for source, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(AotError) as ctx:
                    lex_python(source, filename="bad.py")
                self.assertEqual(ctx.exception.diagnostics[0].code, code)

    def test_all_active_sources_match_cpython_token_stream(self) -> None:
        for path in sorted((ROOT / "src/xcc").rglob("*.py")):
            with self.subTest(path=path.relative_to(ROOT)):
                source = path.read_text(encoding="utf-8")
                owned = _owned_tokens(source)
                hosted = _cpython_tokens(source)
                if owned != hosted:
                    mismatch = next(
                        (
                            index
                            for index, (left, right) in enumerate(zip(owned, hosted, strict=False))
                            if left != right
                        ),
                        min(len(owned), len(hosted)),
                    )
                    left = owned[mismatch] if mismatch < len(owned) else "<missing>"
                    right = hosted[mismatch] if mismatch < len(hosted) else "<missing>"
                    self.fail(f"token {mismatch}: {left!r} != {right!r}")

    def test_token_records_are_immutable(self) -> None:
        item = lex_python("value = 1\n")[0]

        self.assertIsInstance(item, PyToken)
        with self.assertRaises(AttributeError):
            item.text = "changed"


if __name__ == "__main__":
    unittest.main()
