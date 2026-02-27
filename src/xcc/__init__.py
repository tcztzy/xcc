import argparse
import json
import sys
from collections.abc import Sequence
from typing import TextIO, cast

from xcc import cc_driver
from xcc.frontend import FrontendError, compile_source, format_tokens, read_source
from xcc.options import FrontendOptions


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the XCC frontend pipeline on C source input.")
    parser.add_argument(
        "--frontend",
        action="store_true",
        help="run the frontend pipeline without invoking the system toolchain",
    )
    parser.add_argument("input", help="path to a C source file, or - to read from stdin")
    parser.add_argument("-std", choices=("c11", "gnu11"), default="c11", help="language mode")
    parser.add_argument(
        "-fhosted",
        dest="hosted",
        action="store_const",
        const=True,
        default=True,
        help="compile for a hosted C environment (__STDC_HOSTED__=1)",
    )
    parser.add_argument(
        "-ffreestanding",
        dest="hosted",
        action="store_const",
        const=False,
        help="compile for a freestanding C environment (__STDC_HOSTED__=0)",
    )
    parser.add_argument("-I", dest="include_dirs", action="append", default=[], help="include path")
    parser.add_argument(
        "-iquote",
        dest="quote_include_dirs",
        action="append",
        default=[],
        help="quote include path",
    )
    parser.add_argument(
        "-isystem",
        dest="system_include_dirs",
        action="append",
        default=[],
        help="system include path",
    )
    parser.add_argument(
        "-idirafter",
        dest="after_include_dirs",
        action="append",
        default=[],
        help="post-system include path",
    )
    parser.add_argument(
        "-include",
        dest="forced_includes",
        action="append",
        default=[],
        help="force include before the main source",
    )
    parser.add_argument(
        "-imacros",
        dest="macro_includes",
        action="append",
        default=[],
        help="include file for macro definitions only before the main source",
    )
    parser.add_argument(
        "--diag-format",
        choices=("human", "json"),
        default="human",
        help="diagnostic output format",
    )
    parser.add_argument("-D", dest="defines", action="append", default=[], help="define macro")
    parser.add_argument("-U", dest="undefs", action="append", default=[], help="undefine macro")
    parser.add_argument(
        "-nostdinc",
        dest="no_standard_includes",
        action="store_true",
        help="disable environment-provided standard include search paths",
    )
    parser.add_argument(
        "--dump-pp-tokens",
        action="store_true",
        help="print preprocessor token stream",
    )
    parser.add_argument(
        "--dump-include-trace",
        action="store_true",
        help="print include resolution trace",
    )
    parser.add_argument(
        "--dump-macro-table",
        action="store_true",
        help="print final macro table",
    )
    parser.add_argument("--dump-tokens", action="store_true", help="print token stream")
    parser.add_argument("--dump-ast", action="store_true", help="print parsed AST")
    parser.add_argument("--dump-sema", action="store_true", help="print semantic model")
    return parser


def main(argv: Sequence[str] | None = None, *, stdin: TextIO | None = None) -> int:
    parser = _build_arg_parser()
    effective_argv = list(argv) if argv is not None else sys.argv[1:]
    if cc_driver.looks_like_cc_driver(effective_argv):
        return cc_driver.main(effective_argv, stdin=stdin)
    try:
        args, unknown = parser.parse_known_args(effective_argv)
    except SystemExit as error:
        return cast(int, error.code)
    if args.frontend and unknown:
        print(
            f"xcc: frontend mode error: unknown options: {' '.join(unknown)}",
            file=sys.stderr,
        )
        return 2
    if unknown:
        return cc_driver.main(effective_argv, stdin=stdin)
    options = FrontendOptions(
        std=args.std,
        hosted=args.hosted,
        include_dirs=tuple(args.include_dirs),
        quote_include_dirs=tuple(args.quote_include_dirs),
        system_include_dirs=tuple(args.system_include_dirs),
        after_include_dirs=tuple(args.after_include_dirs),
        forced_includes=tuple(args.forced_includes),
        macro_includes=tuple(args.macro_includes),
        defines=tuple(args.defines),
        undefs=tuple(args.undefs),
        no_standard_includes=args.no_standard_includes,
        diag_format=args.diag_format,
    )
    try:
        filename, source = read_source(args.input, stdin=stdin)
    except (OSError, UnicodeError) as error:
        print(f"xcc: I/O error: {error}", file=sys.stderr)
        return 1
    try:
        result = compile_source(source, filename=filename, options=options)
    except FrontendError as error:
        if args.diag_format == "json":
            diagnostic = error.diagnostic
            print(
                json.dumps(
                    {
                        "stage": diagnostic.stage,
                        "filename": diagnostic.filename,
                        "line": diagnostic.line,
                        "column": diagnostic.column,
                        "code": diagnostic.code,
                        "message": diagnostic.message,
                    },
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )
        else:
            print(error, file=sys.stderr)
        return 1
    if args.dump_pp_tokens:
        for line in format_tokens(result.pp_tokens):
            print(line)
    if args.dump_include_trace:
        for line in result.include_trace:
            print(line)
    if args.dump_macro_table:
        for line in result.macro_table:
            print(line)
    if args.dump_tokens:
        for line in format_tokens(result.tokens):
            print(line)
    if args.dump_ast:
        print(result.unit)
    if args.dump_sema:
        print(result.sema)
    if not (
        args.dump_pp_tokens
        or args.dump_include_trace
        or args.dump_macro_table
        or args.dump_tokens
        or args.dump_ast
        or args.dump_sema
    ):
        print(f"xcc: ok: {result.filename}")
    return 0
