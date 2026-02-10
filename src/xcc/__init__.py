import argparse
import sys
from collections.abc import Sequence
from typing import TextIO, cast

from xcc.frontend import FrontendError, compile_source, format_tokens, read_source


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the XCC frontend pipeline on C source input.")
    parser.add_argument("input", help="path to a C source file, or - to read from stdin")
    parser.add_argument("--dump-tokens", action="store_true", help="print token stream")
    parser.add_argument("--dump-ast", action="store_true", help="print parsed AST")
    parser.add_argument("--dump-sema", action="store_true", help="print semantic model")
    return parser


def main(argv: Sequence[str] | None = None, *, stdin: TextIO | None = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as error:
        return cast(int, error.code)
    try:
        filename, source = read_source(args.input, stdin=stdin)
    except (OSError, UnicodeError) as error:
        print(f"xcc: I/O error: {error}", file=sys.stderr)
        return 1
    try:
        result = compile_source(source, filename=filename)
    except FrontendError as error:
        print(error, file=sys.stderr)
        return 1
    if args.dump_tokens:
        for line in format_tokens(result.tokens):
            print(line)
    if args.dump_ast:
        print(result.unit)
    if args.dump_sema:
        print(result.sema)
    if not (args.dump_tokens or args.dump_ast or args.dump_sema):
        print(f"xcc: ok: {result.filename}")
    return 0
