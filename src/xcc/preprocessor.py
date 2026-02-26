import ast
import os
import platform
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from xcc.host_includes import host_system_include_dirs
from xcc.lexer import LexerError, TokenKind, lex_pp
from xcc.options import FrontendOptions, normalize_options

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_INCLUDE_RE = re.compile(r"^(?:\"(?P<quote>[^\"\n]+)\"|<(?P<angle>[^>\n]+)>)$")
_DIRECTIVE_RE = re.compile(r"^\s*#\s*(?P<name>[A-Za-z_]\w*)(?P<body>.*)$")
_DEFINED_PAREN_RE = re.compile(r"\bdefined\s*\(\s*([A-Za-z_]\w*)\s*\)")
_DEFINED_BARE_RE = re.compile(r"\bdefined\s+([A-Za-z_]\w*)")
_PP_INT_RE = re.compile(
    r"^(?:0[xX][0-9A-Fa-f]+|[0-9]+)(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?$"
)
_EXPR_TOKEN_RE = re.compile(
    r"0[xX][0-9A-Fa-f]+(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?"
    r"|[0-9]+(?:[uU](?:ll|LL|[lL])?|(?:ll|LL|[lL])[uU]?)?"
    r"|(?:u8|[uUL])?'(?:[^'\\\n]|\\.)+'"
    r"|[A-Za-z_]\w*"
    r"|\|\||&&|==|!=|<=|>=|<<|>>|[()!~+\-*/%<>&^|]"
)

_PP_UNKNOWN_DIRECTIVE = "XCC-PP-0101"
_PP_INCLUDE_NOT_FOUND = "XCC-PP-0102"
_PP_INVALID_IF_EXPR = "XCC-PP-0103"
_PP_INVALID_DIRECTIVE = "XCC-PP-0104"
_PP_GNU_EXTENSION = "XCC-PP-0105"
_PP_INVALID_MACRO = "XCC-PP-0201"
_PP_INCLUDE_READ_ERROR = "XCC-PP-0301"
_PP_INCLUDE_CYCLE = "XCC-PP-0302"
_PREDEFINED_MACROS = (
    "__STDC__=1",
    "__STDC_VERSION__=201112L",
    "__STDC_IEC_559__=1",
    "__STDC_MB_MIGHT_NEQ_WC__=1",
    "__STDC_UTF_16__=1",
    "__STDC_UTF_32__=1",
    "__STDC_NO_ATOMICS__=1",
    "__STDC_NO_COMPLEX__=1",
    "__STDC_NO_THREADS__=1",
    "__STDC_NO_VLA__=1",
    "__ATOMIC_RELAXED=0",
    "__ATOMIC_CONSUME=1",
    "__ATOMIC_ACQUIRE=2",
    "__ATOMIC_RELEASE=3",
    "__ATOMIC_ACQ_REL=4",
    "__ATOMIC_SEQ_CST=5",
    "__GCC_ATOMIC_BOOL_LOCK_FREE=2",
    "__GCC_ATOMIC_CHAR_LOCK_FREE=2",
    "__GCC_ATOMIC_SHORT_LOCK_FREE=2",
    "__GCC_ATOMIC_INT_LOCK_FREE=2",
    "__GCC_ATOMIC_LONG_LOCK_FREE=2",
    "__GCC_ATOMIC_LLONG_LOCK_FREE=2",
    "__GCC_ATOMIC_POINTER_LOCK_FREE=2",
    "__GCC_ATOMIC_CHAR16_T_LOCK_FREE=2",
    "__GCC_ATOMIC_CHAR32_T_LOCK_FREE=2",
    "__GCC_ATOMIC_WCHAR_T_LOCK_FREE=2",
    "__GCC_ATOMIC_TEST_AND_SET_TRUEVAL=1",
    "__GCC_HAVE_SYNC_COMPARE_AND_SWAP_1=1",
    "__GCC_HAVE_SYNC_COMPARE_AND_SWAP_2=1",
    "__GCC_HAVE_SYNC_COMPARE_AND_SWAP_4=1",
    "__GCC_HAVE_SYNC_COMPARE_AND_SWAP_8=1",
    "__GCC_HAVE_SYNC_COMPARE_AND_SWAP_16=1",
    "__INT_WIDTH__=32",
    "__LONG_WIDTH__=64",
    "__LONG_LONG_WIDTH__=64",
    "__LLONG_WIDTH__=64",
    "__INTMAX_WIDTH__=64",
    "__UINTMAX_WIDTH__=64",
    "__SIZE_WIDTH__=64",
    "__PTRDIFF_WIDTH__=64",
    "__INTPTR_WIDTH__=64",
    "__UINTPTR_WIDTH__=64",
    "__POINTER_WIDTH__=64",
    "__BOOL_WIDTH__=8",
    "__SCHAR_MAX__=127",
    "__SCHAR_MIN__=-128",
    "__SHRT_MAX__=32767",
    "__SHRT_MIN__=-32768",
    "__INT_MAX__=2147483647",
    "__INT_MIN__=-2147483648",
    "__LONG_MAX__=9223372036854775807L",
    "__LONG_MIN__=-9223372036854775808L",
    "__INTMAX_MAX__=9223372036854775807L",
    "__INTMAX_MIN__=-9223372036854775808L",
    "__INT8_C(value)=value",
    "__INT16_C(value)=value",
    "__INT32_C(value)=value",
    "__INT64_C(value)=value##L",
    "__INTMAX_C(value)=value##L",
    "__UCHAR_MAX__=255",
    "__USHRT_MAX__=65535",
    "__UINT_MAX__=4294967295U",
    "__ULONG_MAX__=18446744073709551615UL",
    "__SIZE_MAX__=18446744073709551615UL",
    "__PTRDIFF_MAX__=9223372036854775807L",
    "__PTRDIFF_MIN__=-9223372036854775808L",
    "__INTPTR_MAX__=9223372036854775807L",
    "__INTPTR_MIN__=-9223372036854775808L",
    "__UINTPTR_MAX__=18446744073709551615UL",
    "__LONG_LONG_MAX__=9223372036854775807LL",
    "__LONG_LONG_MIN__=-9223372036854775808LL",
    "__LLONG_MAX__=9223372036854775807LL",
    "__LLONG_MIN__=-9223372036854775808LL",
    "__ULLONG_MAX__=18446744073709551615ULL",
    "__UINT8_C(value)=value",
    "__UINT16_C(value)=value",
    "__UINT32_C(value)=value##U",
    "__UINT64_C(value)=value##UL",
    "__UINTMAX_MAX__=18446744073709551615UL",
    "__UINTMAX_C(value)=value##UL",
    "__LP64__=1",
    "__LP64=1",
    "_LP64=1",
    "__CHAR_BIT__=8",
    "__SIZEOF_BOOL__=1",
    "__SIZEOF_SHORT__=2",
    "__SIZEOF_INT__=4",
    "__SIZEOF_FLOAT__=4",
    "__SIZEOF_DOUBLE__=8",
    "__SIZEOF_LONG_DOUBLE__=16",
    "__FLT_RADIX__=2",
    "__FLT_MANT_DIG__=24",
    "__DBL_MANT_DIG__=53",
    "__LDBL_MANT_DIG__=113",
    "__FLT_DIG__=6",
    "__DBL_DIG__=15",
    "__LDBL_DIG__=33",
    "__FLT_DECIMAL_DIG__=9",
    "__DBL_DECIMAL_DIG__=17",
    "__LDBL_DECIMAL_DIG__=36",
    "__DECIMAL_DIG__=36",
    "__FLT_EPSILON__=1.19209290e-7F",
    "__DBL_EPSILON__=2.2204460492503131e-16",
    "__LDBL_EPSILON__=1.08420217248550443401e-19L",
    "__FLT_MIN__=1.17549435e-38F",
    "__DBL_MIN__=2.2250738585072014e-308",
    "__LDBL_MIN__=3.36210314311209350626e-4932L",
    "__FLT_DENORM_MIN__=1.40129846e-45F",
    "__DBL_DENORM_MIN__=4.9406564584124654e-324",
    "__LDBL_DENORM_MIN__=3.64519953188247460253e-4951L",
    "__FLT_MAX__=3.40282347e+38F",
    "__DBL_MAX__=1.7976931348623157e+308",
    "__LDBL_MAX__=1.18973149535723176502e+4932L",
    "__FLT_MIN_EXP__=-125",
    "__DBL_MIN_EXP__=-1021",
    "__LDBL_MIN_EXP__=-16381",
    "__FLT_MIN_10_EXP__=-37",
    "__DBL_MIN_10_EXP__=-307",
    "__LDBL_MIN_10_EXP__=-4931",
    "__FLT_MAX_EXP__=128",
    "__DBL_MAX_EXP__=1024",
    "__LDBL_MAX_EXP__=16384",
    "__FLT_MAX_10_EXP__=38",
    "__DBL_MAX_10_EXP__=308",
    "__LDBL_MAX_10_EXP__=4932",
    "__FLT_HAS_DENORM__=1",
    "__DBL_HAS_DENORM__=1",
    "__LDBL_HAS_DENORM__=1",
    "__FLT_HAS_INFINITY__=1",
    "__DBL_HAS_INFINITY__=1",
    "__LDBL_HAS_INFINITY__=1",
    "__FLT_HAS_QUIET_NAN__=1",
    "__DBL_HAS_QUIET_NAN__=1",
    "__LDBL_HAS_QUIET_NAN__=1",
    "__SIZEOF_POINTER__=8",
    "__SIZEOF_LONG__=8",
    "__SIZEOF_LONG_LONG__=8",
    "__SIZEOF_SIZE_T__=8",
    "__SIZEOF_PTRDIFF_T__=8",
    "__SIZEOF_INTMAX_T__=8",
    "__SIZEOF_UINTMAX_T__=8",
    "__SIZEOF_WCHAR_T__=4",
    "__SIZEOF_WINT_T__=4",
    "__SIZEOF_CHAR16_T__=2",
    "__SIZEOF_CHAR32_T__=4",
    "__ORDER_LITTLE_ENDIAN__=1234",
    "__ORDER_BIG_ENDIAN__=4321",
    "__BYTE_ORDER__=__ORDER_LITTLE_ENDIAN__",
    "__LITTLE_ENDIAN__=__ORDER_LITTLE_ENDIAN__",
    "__BIG_ENDIAN__=__ORDER_BIG_ENDIAN__",
    "__FLOAT_WORD_ORDER__=__ORDER_LITTLE_ENDIAN__",
    "__SIZE_TYPE__=unsigned long",
    "__PTRDIFF_TYPE__=long",
    "__INTPTR_TYPE__=long",
    "__UINTPTR_TYPE__=unsigned long",
    "__INTMAX_TYPE__=long",
    "__UINTMAX_TYPE__=unsigned long",
    "__CHAR16_TYPE__=unsigned short",
    "__CHAR32_TYPE__=unsigned int",
    "__INT8_TYPE__=signed char",
    "__INT16_TYPE__=short",
    "__INT32_TYPE__=int",
    "__INT64_TYPE__=long",
    "__UINT8_TYPE__=unsigned char",
    "__UINT16_TYPE__=unsigned short",
    "__UINT32_TYPE__=unsigned int",
    "__UINT64_TYPE__=unsigned long",
    "__INT_LEAST8_TYPE__=signed char",
    "__INT_LEAST16_TYPE__=short",
    "__INT_LEAST32_TYPE__=int",
    "__INT_LEAST64_TYPE__=long",
    "__UINT_LEAST8_TYPE__=unsigned char",
    "__UINT_LEAST16_TYPE__=unsigned short",
    "__UINT_LEAST32_TYPE__=unsigned int",
    "__UINT_LEAST64_TYPE__=unsigned long",
    "__INT_FAST8_TYPE__=signed char",
    "__INT_FAST16_TYPE__=short",
    "__INT_FAST32_TYPE__=int",
    "__INT_FAST64_TYPE__=long",
    "__UINT_FAST8_TYPE__=unsigned char",
    "__UINT_FAST16_TYPE__=unsigned short",
    "__UINT_FAST32_TYPE__=unsigned int",
    "__UINT_FAST64_TYPE__=unsigned long",
    "__WCHAR_TYPE__=int",
    "__WINT_TYPE__=unsigned int",
    "__WCHAR_WIDTH__=32",
    "__WINT_WIDTH__=32",
    "__CHAR16_WIDTH__=16",
    "__CHAR32_WIDTH__=32",
    "__WCHAR_MAX__=2147483647",
    "__WCHAR_MIN__=-2147483648",
    "__WINT_MAX__=4294967295U",
    "__WINT_MIN__=0U",
    "__SIG_ATOMIC_TYPE__=int",
    "__SIG_ATOMIC_WIDTH__=32",
    "__SIG_ATOMIC_MAX__=2147483647",
    "__SIG_ATOMIC_MIN__=-2147483648",
    "__STDC_ISO_10646__=201706L",
    "__FILE__=0",
    "__FILE_NAME__=0",
    "__BASE_FILE__=0",
    "__LINE__=0",
    "__INCLUDE_LEVEL__=0",
    "__COUNTER__=0",
)
_HOST_ARCH_PREDEFINED_MACROS: dict[str, tuple[str, ...]] = {
    "aarch64": ("__arm64__=1",),
    "arm64": ("__arm64__=1",),
    "amd64": ("__x86_64__=1",),
    "x86_64": ("__x86_64__=1",),
    "i386": ("__i386__=1",),
    "i686": ("__i386__=1",),
    "arm": ("__arm__=1",),
    "armv7l": ("__arm__=1",),
}
_HOST_ARCH_DEFINE_STRINGS = tuple(
    define for defines in _HOST_ARCH_PREDEFINED_MACROS.values() for define in defines
)
_PREDEFINED_DYNAMIC_MACROS = frozenset(
    {"__FILE__", "__FILE_NAME__", "__BASE_FILE__", "__LINE__", "__INCLUDE_LEVEL__", "__COUNTER__"}
)
_PREDEFINED_STATIC_MACROS = frozenset({"__DATE__", "__TIME__", "__TIMESTAMP__"})
_STRICT_MODE_PREDEFINED_MACROS = ("__STRICT_ANSI__=1",)
_GNU_MODE_PREDEFINED_MACROS = (
    "__GNUC__=4",
    "__GNUC_MINOR__=2",
    "__GNUC_PATCHLEVEL__=1",
    "__GNUC_STDC_INLINE__=1",
    '__VERSION__="xcc gnu11"',
)
_SUPPORTED_WARNINGS = frozenset(
    {
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-Wdeprecated-declarations",
    }
)
_SUPPORTED_C_ATTRIBUTES = frozenset(
    {
        "deprecated",
        "fallthrough",
        "maybe_unused",
        "nodiscard",
        "noreturn",
        "reproducible",
        "unsequenced",
        "gnu::unused",
    }
)


def _env_path_list(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    if not raw:
        return ()
    parts = raw.split(os.pathsep)
    # GCC/Clang treat empty path entries in include env vars as the current working directory.
    return tuple(part if part else "." for part in parts)


def _macro_name_from_cli_define(define: str) -> str:
    head = define.split("=", 1)[0].strip()
    if "(" not in head:
        return head
    open_index = head.find("(")
    close_index = head.rfind(")")
    if close_index <= open_index:
        return head
    return head[:open_index].strip()


_PREDEFINED_MACRO_NAMES = frozenset(
    _macro_name_from_cli_define(item)
    for item in (
        *_PREDEFINED_MACROS,
        *_STRICT_MODE_PREDEFINED_MACROS,
        *_GNU_MODE_PREDEFINED_MACROS,
        *_HOST_ARCH_DEFINE_STRINGS,
    )
) | frozenset(_PREDEFINED_DYNAMIC_MACROS | _PREDEFINED_STATIC_MACROS | {"__STDC_HOSTED__"})


@dataclass(frozen=True)
class PreprocessResult:
    source: str
    line_map: tuple[tuple[str, int], ...]
    include_trace: tuple[str, ...]
    macro_table: tuple[str, ...]


@dataclass(frozen=True)
class _ProcessedText:
    source: str
    line_map: tuple[tuple[str, int], ...]


class PreprocessorError(ValueError):
    def __init__(
        self,
        message: str,
        line: int | None = None,
        column: int | None = None,
        *,
        filename: str | None = None,
        code: str = _PP_INVALID_MACRO,
    ) -> None:
        if line is None or column is None:
            super().__init__(message)
        else:
            location = f"{filename}:{line}:{column}" if filename is not None else f"{line}:{column}"
            super().__init__(f"{message} at {location}")
        self.line = line
        self.column = column
        self.filename = filename
        self.code = code


@dataclass(frozen=True)
class _SourceLocation:
    filename: str
    line: int
    include_level: int = 0


def _location_tuple(location: _SourceLocation) -> tuple[str, int]:
    return location.filename, location.line


class _LineMapBuilder:
    def __init__(self) -> None:
        self._entries: list[tuple[str, int]] = []

    def append_line(self, text: str, location: _SourceLocation) -> None:
        if text:
            self._entries.append(_location_tuple(location))

    def extend(self, mappings: tuple[tuple[str, int], ...]) -> None:
        self._entries.extend(mappings)

    def build(self) -> tuple[tuple[str, int], ...]:
        return tuple(self._entries)


class _OutputBuilder:
    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._line_map = _LineMapBuilder()

    def append(self, text: str, location: _SourceLocation) -> None:
        self._chunks.append(text)
        self._line_map.append_line(text, location)

    def extend_processed(self, processed: _ProcessedText) -> None:
        self._chunks.append(processed.source)
        self._line_map.extend(processed.line_map)

    def build(self) -> _ProcessedText:
        return _ProcessedText("".join(self._chunks), self._line_map.build())


class _LogicalCursor:
    def __init__(self, filename: str, *, include_level: int = 0) -> None:
        self.filename = filename
        self.line = 1
        self.include_level = include_level

    def current(self) -> _SourceLocation:
        return _SourceLocation(self.filename, self.line, self.include_level)

    def advance(self, count: int = 1) -> None:
        self.line += count

    def rebase(self, line: int, filename: str | None) -> None:
        self.line = line
        if filename is not None:
            self.filename = filename


class _DirectiveCursor:
    def __init__(self, cursor: _LogicalCursor, count: int) -> None:
        self._locations = tuple(
            _SourceLocation(cursor.filename, cursor.line + index) for index in range(count)
        )

    def line_location(self, index: int) -> _SourceLocation:
        return self._locations[index]

    def first_location(self) -> _SourceLocation:
        return self._locations[0]

    def all_locations(self) -> tuple[_SourceLocation, ...]:
        return self._locations


def _macro_table_line(macro: "_Macro") -> str:
    if macro.parameters is None:
        signature = macro.name
    else:
        params = list(macro.parameters)
        if macro.is_variadic:
            params.append("...")
        signature = f"{macro.name}({','.join(params)})"
    body = _render_macro_tokens(list(macro.replacement))
    return f"{signature}={body}"


def _format_include_trace(
    source: str,
    line: int,
    include_name: str,
    include_path: str,
    is_angled: bool,
    *,
    directive: str = "include",
) -> str:
    delim_open, delim_close = ("<", ">") if is_angled else ('"', '"')
    return (
        f"{source}:{line}: #{directive} {delim_open}{include_name}{delim_close} -> {include_path}"
    )


def _format_include_reference(include_name: str, is_angled: bool) -> str:
    if is_angled:
        return f"<{include_name}>"
    return f'"{include_name}"'


def _format_include_cycle(include_stack: tuple[str, ...], include_path: str) -> str:
    cycle_start = include_stack.index(include_path)
    cycle_chain = (*include_stack[cycle_start:], include_path)
    return " -> ".join(cycle_chain)


def _format_include_search_roots(search_roots: tuple[Path, ...]) -> str:
    if not search_roots:
        return "<none>"
    return ", ".join(str(root) for root in search_roots)


@dataclass
class _ConditionalFrame:
    parent_active: bool
    active: bool
    branch_taken: bool
    saw_else: bool = False


@dataclass(frozen=True)
class _MacroToken:
    kind: TokenKind
    text: str


@dataclass(frozen=True)
class _Macro:
    name: str
    replacement: tuple[_MacroToken, ...]
    parameters: tuple[str, ...] | None = None
    is_variadic: bool = False


_EMPTY_MACRO_TOKEN = _MacroToken(TokenKind.PUNCTUATOR, "")
_COMMA_MACRO_TOKEN = _MacroToken(TokenKind.PUNCTUATOR, ",")


def preprocess_source(
    source: str,
    *,
    filename: str = "<input>",
    options: FrontendOptions | None = None,
) -> PreprocessResult:
    normalized_options = normalize_options(options)
    processor = _Preprocessor(normalized_options)
    processed = processor.process(source, filename=filename)
    if normalized_options.std == "gnu11":
        stripped = _strip_gnu_asm_extensions(processed.source)
    else:
        _reject_gnu_asm_extensions(processed.source, processed.line_map)
        stripped = processed.source
    return PreprocessResult(
        stripped,
        processed.line_map,
        tuple(processor.include_trace),
        tuple(_macro_table_line(macro) for _, macro in sorted(processor.macro_table.items())),
    )


class _Preprocessor:
    def __init__(self, options: FrontendOptions) -> None:
        self._options = options
        translation_start = datetime.now()
        self._date_literal = _quote_string_literal(_format_date_macro(translation_start))
        self._time_literal = _quote_string_literal(translation_start.strftime("%H:%M:%S"))
        self._timestamp_literal = _quote_string_literal(_format_timestamp_macro(translation_start))
        self._counter = 0
        self._base_filename = "<input>"
        self._macros: dict[str, _Macro] = {}
        for define in _PREDEFINED_MACROS:
            macro = self._parse_cli_define(define)
            self._macros[macro.name] = macro
        hosted_define = "__STDC_HOSTED__=1" if options.hosted else "__STDC_HOSTED__=0"
        hosted_macro = self._parse_cli_define(hosted_define)
        self._macros[hosted_macro.name] = hosted_macro
        mode_defines = (
            _GNU_MODE_PREDEFINED_MACROS
            if options.std == "gnu11"
            else _STRICT_MODE_PREDEFINED_MACROS
        )
        for define in mode_defines:
            macro = self._parse_cli_define(define)
            self._macros[macro.name] = macro
        for define in _HOST_ARCH_PREDEFINED_MACROS.get(platform.machine(), ()):
            macro = self._parse_cli_define(define)
            self._macros[macro.name] = macro
        self._macros["__DATE__"] = _Macro(
            "__DATE__",
            (_MacroToken(TokenKind.STRING_LITERAL, self._date_literal),),
        )
        self._macros["__TIME__"] = _Macro(
            "__TIME__",
            (_MacroToken(TokenKind.STRING_LITERAL, self._time_literal),),
        )
        self._macros["__TIMESTAMP__"] = _Macro(
            "__TIMESTAMP__",
            (_MacroToken(TokenKind.STRING_LITERAL, self._timestamp_literal),),
        )
        self.include_trace: list[str] = []
        self._pragma_once_files: set[str] = set()
        for define in options.defines:
            macro = self._parse_cli_define(define)
            self._macros[macro.name] = macro
        for name in options.undefs:
            if _IDENT_RE.fullmatch(name) is None:
                raise PreprocessorError(f"Invalid macro name in -U: {name}")
            self._macros.pop(name, None)
        self.macro_table = self._macros
        if options.no_standard_includes:
            self._cpath_include_dirs = ()
            self._c_include_path_dirs = ()
            self._host_system_include_dirs = ()
        else:
            self._cpath_include_dirs = _env_path_list("CPATH")
            self._c_include_path_dirs = _env_path_list("C_INCLUDE_PATH")
            self._host_system_include_dirs = host_system_include_dirs()

    def process(self, source: str, *, filename: str) -> _ProcessedText:
        self._base_filename = filename
        base_dir = self._source_dir(filename)
        out = _OutputBuilder()
        command_line_index = 1
        for include_name in self._options.macro_includes:
            self._process_macro_include(
                include_name,
                location=_SourceLocation("<command line>", command_line_index),
                base_dir=base_dir,
                include_stack=(filename,),
            )
            command_line_index += 1
        for include_name in self._options.forced_includes:
            out.extend_processed(
                self._process_forced_include(
                    include_name,
                    location=_SourceLocation("<command line>", command_line_index),
                    base_dir=base_dir,
                    include_stack=(filename,),
                )
            )
            command_line_index += 1
        out.extend_processed(
            self._process_text(
                source,
                filename=filename,
                source_id=filename,
                base_dir=base_dir,
                include_stack=(filename,),
            )
        )
        return out.build()

    def _source_dir(self, filename: str) -> Path | None:
        if filename in {"<input>", "<stdin>"}:
            return None
        return Path(filename).resolve().parent

    def _process_text(
        self,
        source: str,
        *,
        filename: str,
        source_id: str,
        base_dir: Path | None,
        include_stack: tuple[str, ...],
    ) -> _ProcessedText:
        lines = source.splitlines(keepends=True)
        if not lines:
            return _ProcessedText(source, ())
        out = _OutputBuilder()
        logical_cursor = _LogicalCursor(filename, include_level=max(len(include_stack) - 1, 0))
        stack: list[_ConditionalFrame] = []
        line_index = 0
        while line_index < len(lines):
            line = lines[line_index]
            parsed = _parse_directive(line)
            if parsed is None:
                location = logical_cursor.current()
                if _is_active(stack):
                    out.append(self._expand_line(line, location), location)
                else:
                    out.append(_blank_line(line), location)
                logical_cursor.advance()
                line_index += 1
                continue
            directive_lines = [line]
            while directive_lines[-1].rstrip().endswith("\\") and line_index + 1 < len(lines):
                line_index += 1
                directive_lines.append(lines[line_index])
            directive_cursor = _DirectiveCursor(logical_cursor, len(directive_lines))
            directive_text = "".join(directive_lines).replace("\\\n", "")
            parsed = _parse_directive(directive_text)
            if parsed is None:
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            name, body = parsed
            conditional_result = self._handle_conditional(
                name,
                body,
                directive_cursor.first_location(),
                stack,
                base_dir=base_dir,
            )
            if conditional_result is not None:
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if not _is_active(stack):
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if name == "define":
                self._handle_define(body)
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if name == "undef":
                self._handle_undef(body, directive_cursor.first_location())
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if name in {"include", "include_next"}:
                if name == "include_next" and self._options.std == "c11":
                    raise PreprocessorError(
                        "Unknown preprocessor directive: #include_next",
                        directive_cursor.first_location().line,
                        1,
                        filename=directive_cursor.first_location().filename,
                        code=_PP_UNKNOWN_DIRECTIVE,
                    )
                include_processed = self._handle_include(
                    body,
                    directive_cursor.first_location(),
                    base_dir=base_dir,
                    include_stack=include_stack,
                    include_next=name == "include_next",
                )
                out.extend_processed(include_processed)
                for directive_index, chunk in enumerate(directive_lines[1:], start=1):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if name == "error":
                message = body.strip() or "#error"
                raise PreprocessorError(
                    message,
                    directive_cursor.first_location().line,
                    1,
                    filename=directive_cursor.first_location().filename,
                    code=_PP_INVALID_DIRECTIVE,
                )
            if name == "warning":
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if name == "line":
                line_value, filename_value = self._parse_line_directive(
                    body, directive_cursor.first_location()
                )
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.rebase(line_value, filename_value)
                line_index += 1
                continue
            if name == "pragma":
                if body.strip() == "once":
                    self._pragma_once_files.add(source_id)
                for directive_index, chunk in enumerate(directive_lines):
                    out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
                logical_cursor.advance(len(directive_lines))
                line_index += 1
                continue
            if self._options.std == "c11":
                raise PreprocessorError(
                    f"Unknown preprocessor directive: #{name}",
                    directive_cursor.first_location().line,
                    1,
                    filename=directive_cursor.first_location().filename,
                    code=_PP_UNKNOWN_DIRECTIVE,
                )
            for directive_index, chunk in enumerate(directive_lines):
                out.append(_blank_line(chunk), directive_cursor.line_location(directive_index))
            logical_cursor.advance(len(directive_lines))
            line_index += 1
            continue
        if stack:
            location = logical_cursor.current()
            raise PreprocessorError(
                "Unterminated conditional directive",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )
        return out.build()

    def _require_empty_conditional_tail(
        self,
        directive: str,
        body: str,
        location: _SourceLocation,
    ) -> None:
        if _strip_condition_comments(body).strip():
            raise PreprocessorError(
                f"Unexpected tokens after #{directive}",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )

    def _handle_conditional(
        self,
        name: str,
        body: str,
        location: _SourceLocation,
        stack: list[_ConditionalFrame],
        *,
        base_dir: Path | None,
    ) -> str | None:
        if name not in {
            "if",
            "ifdef",
            "ifndef",
            "elif",
            "elifdef",
            "elifndef",
            "else",
            "endif",
        }:
            return None
        if name == "if":
            parent_active = _is_active(stack)
            condition = parent_active and self._eval_condition(body, location, base_dir=base_dir)
            stack.append(_ConditionalFrame(parent_active, condition, condition))
            return ""
        if name == "ifdef":
            parent_active = _is_active(stack)
            macro_name = self._require_macro_name(body, location)
            condition = parent_active and macro_name in self._macros
            stack.append(_ConditionalFrame(parent_active, condition, condition))
            return ""
        if name == "ifndef":
            parent_active = _is_active(stack)
            macro_name = self._require_macro_name(body, location)
            condition = parent_active and macro_name not in self._macros
            stack.append(_ConditionalFrame(parent_active, condition, condition))
            return ""
        if not stack:
            raise PreprocessorError(
                f"Unexpected #{name}",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )
        frame = stack[-1]
        if name in {"elif", "elifdef", "elifndef"}:
            if name in {"elifdef", "elifndef"} and self._options.std == "c11":
                raise PreprocessorError(
                    f"Unknown preprocessor directive: #{name}",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_UNKNOWN_DIRECTIVE,
                )
            if frame.saw_else:
                raise PreprocessorError(
                    f"#{name} after #else",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_DIRECTIVE,
                )
            if not frame.parent_active or frame.branch_taken:
                frame.active = False
                return ""
            if name == "elif":
                condition = self._eval_condition(body, location, base_dir=base_dir)
            else:
                macro_name = self._require_macro_name(body, location)
                if name == "elifdef":
                    condition = macro_name in self._macros
                else:
                    condition = macro_name not in self._macros
            frame.active = condition
            frame.branch_taken = frame.branch_taken or condition
            return ""
        if name == "else":
            self._require_empty_conditional_tail("else", body, location)
            if frame.saw_else:
                raise PreprocessorError(
                    "Duplicate #else",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_DIRECTIVE,
                )
            frame.saw_else = True
            frame.active = frame.parent_active and not frame.branch_taken
            frame.branch_taken = True
            return ""
        self._require_empty_conditional_tail("endif", body, location)
        stack.pop()
        return ""

    def _handle_define(self, body: str) -> None:
        macro = self._parse_define(body)
        if macro is None:
            return
        self._macros[macro.name] = macro

    def _parse_define(self, body: str) -> _Macro | None:
        define_body = body.lstrip()
        if not define_body:
            return None
        name_match = _IDENT_RE.match(define_body)
        if name_match is None:
            return None
        name = name_match.group(0)
        tail = define_body[name_match.end() :]
        if tail.startswith("("):
            return self._parse_function_like_define(name, tail)
        replacement = tail.strip()
        return _Macro(name, tuple(_tokenize_macro_replacement(replacement)))

    def _parse_function_like_define(self, name: str, tail: str) -> _Macro | None:
        close_index = tail.find(")")
        if close_index < 0:
            return None
        params_text = tail[1:close_index].strip()
        replacement = tail[close_index + 1 :].strip()
        parsed = _parse_macro_parameters(params_text)
        if parsed is None:
            return None
        parameters, is_variadic = parsed
        return _Macro(
            name,
            tuple(_tokenize_macro_replacement(replacement)),
            parameters=tuple(parameters),
            is_variadic=is_variadic,
        )

    def _expand_line(self, line: str, location: _SourceLocation) -> str:
        if not self._macros:
            return line
        trailing_newline = "\n" if line.endswith("\n") else ""
        text = line[:-1] if trailing_newline else line
        if self._macros.keys() <= _PREDEFINED_MACRO_NAMES and not self._line_needs_macro_expansion(
            text
        ):
            return line
        expanded = self._expand_macro_text(text, location)
        return expanded + trailing_newline

    def _line_needs_macro_expansion(self, text: str) -> bool:
        tokens = _tokenize_macro_text(text)
        if tokens is None:
            return False
        return any(token.kind == TokenKind.IDENT and token.text in self._macros for token in tokens)

    def _expand_macro_text(self, text: str, location: _SourceLocation) -> str:
        tokens = _tokenize_macro_text(text)
        if tokens is None:
            return text
        expanded = _expand_macro_tokens(
            tokens,
            self._macros,
            self._options.std,
            location,
            dynamic_macro_resolver=self._resolve_dynamic_macro,
        )
        return _render_macro_tokens(expanded)

    def _resolve_dynamic_macro(self, name: str, location: _SourceLocation) -> _MacroToken:
        if name == "__LINE__":
            return _MacroToken(TokenKind.INT_CONST, str(location.line))
        if name == "__BASE_FILE__":
            return _MacroToken(TokenKind.STRING_LITERAL, _quote_string_literal(self._base_filename))
        if name == "__INCLUDE_LEVEL__":
            return _MacroToken(TokenKind.INT_CONST, str(location.include_level))
        if name == "__COUNTER__":
            current = self._counter
            self._counter += 1
            return _MacroToken(TokenKind.INT_CONST, str(current))
        if name == "__FILE_NAME__":
            return _MacroToken(
                TokenKind.STRING_LITERAL,
                _quote_string_literal(Path(location.filename).name),
            )
        return _MacroToken(TokenKind.STRING_LITERAL, _quote_string_literal(location.filename))

    def _handle_undef(self, body: str, location: _SourceLocation) -> None:
        macro_name = self._require_macro_name(body, location)
        self._macros.pop(macro_name, None)

    def _handle_include(
        self,
        body: str,
        location: _SourceLocation,
        *,
        base_dir: Path | None,
        include_stack: tuple[str, ...],
        include_next: bool = False,
    ) -> _ProcessedText:
        include_name, is_angled = self._parse_include_target(body, location)
        include_path, search_roots = self._resolve_include(
            include_name,
            is_angled=is_angled,
            base_dir=base_dir,
            include_next_from=base_dir if include_next else None,
        )
        if include_path is None:
            prefix = "Include not found via #include_next" if include_next else "Include not found"
            raise PreprocessorError(
                (
                    f"{prefix}: "
                    f"{_format_include_reference(include_name, is_angled)}; searched: "
                    f"{_format_include_search_roots(search_roots)}"
                ),
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_NOT_FOUND,
            )
        include_path_text = str(include_path)
        if include_path_text in self._pragma_once_files:
            return _ProcessedText("", ())
        self.include_trace.append(
            _format_include_trace(
                location.filename,
                location.line,
                include_name,
                include_path_text,
                is_angled,
                directive="include_next" if include_next else "include",
            )
        )
        if include_path_text in include_stack:
            raise PreprocessorError(
                (
                    "Circular include detected: "
                    f"{_format_include_cycle(include_stack, include_path_text)}"
                ),
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_CYCLE,
            )
        try:
            include_source = include_path.read_text(encoding="utf-8")
        except OSError as error:
            raise PreprocessorError(
                f"Unable to read include: {include_name}: {error}",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_READ_ERROR,
            ) from error
        return self._process_text(
            include_source,
            filename=include_path_text,
            source_id=include_path_text,
            base_dir=include_path.parent,
            include_stack=(*include_stack, include_path_text),
        )

    def _process_macro_include(
        self,
        include_name: str,
        *,
        location: _SourceLocation,
        base_dir: Path | None,
        include_stack: tuple[str, ...],
    ) -> None:
        include_path, search_roots = self._resolve_include(
            include_name,
            is_angled=False,
            base_dir=base_dir,
        )
        if include_path is None:
            raise PreprocessorError(
                (
                    "Macro include not found: "
                    f"{_format_include_reference(include_name, False)}; searched: "
                    f"{_format_include_search_roots(search_roots)}"
                ),
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_NOT_FOUND,
            )
        include_path_text = str(include_path)
        self.include_trace.append(
            _format_include_trace(
                location.filename,
                location.line,
                include_name,
                include_path_text,
                False,
                directive="imacros",
            )
        )
        if include_path_text in include_stack:
            raise PreprocessorError(
                (
                    "Circular include detected: "
                    f"{_format_include_cycle(include_stack, include_path_text)}"
                ),
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_CYCLE,
            )
        try:
            include_source = include_path.read_text(encoding="utf-8")
        except OSError as error:
            raise PreprocessorError(
                f"Unable to read include: {include_name}: {error}",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_READ_ERROR,
            ) from error
        self._process_text(
            include_source,
            filename=include_path_text,
            source_id=include_path_text,
            base_dir=include_path.parent,
            include_stack=(*include_stack, include_path_text),
        )

    def _process_forced_include(
        self,
        include_name: str,
        *,
        location: _SourceLocation,
        base_dir: Path | None,
        include_stack: tuple[str, ...],
    ) -> _ProcessedText:
        include_path, search_roots = self._resolve_include(
            include_name,
            is_angled=False,
            base_dir=base_dir,
        )
        if include_path is None:
            raise PreprocessorError(
                (
                    "Forced include not found: "
                    f"{_format_include_reference(include_name, False)}; searched: "
                    f"{_format_include_search_roots(search_roots)}"
                ),
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_NOT_FOUND,
            )
        include_path_text = str(include_path)
        if include_path_text in self._pragma_once_files:
            return _ProcessedText("", ())
        self.include_trace.append(
            _format_include_trace(
                location.filename,
                location.line,
                include_name,
                include_path_text,
                False,
                directive="include",
            )
        )
        if include_path_text in include_stack:
            raise PreprocessorError(
                (
                    "Circular include detected: "
                    f"{_format_include_cycle(include_stack, include_path_text)}"
                ),
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_CYCLE,
            )
        try:
            include_source = include_path.read_text(encoding="utf-8")
        except OSError as error:
            raise PreprocessorError(
                f"Unable to read include: {include_name}: {error}",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INCLUDE_READ_ERROR,
            ) from error
        return self._process_text(
            include_source,
            filename=include_path_text,
            source_id=include_path_text,
            base_dir=include_path.parent,
            include_stack=(*include_stack, include_path_text),
        )

    def _parse_include_target(self, body: str, location: _SourceLocation) -> tuple[str, bool]:
        return self._parse_header_name_operand(body.strip(), location)

    def _parse_header_name_operand(
        self,
        operand: str,
        location: _SourceLocation,
    ) -> tuple[str, bool]:
        direct = _INCLUDE_RE.match(operand)
        if direct is not None:
            quoted_name = direct.group("quote")
            angle_name = direct.group("angle")
            include_name = quoted_name if quoted_name is not None else angle_name
            assert include_name is not None
            return include_name, angle_name is not None

        expanded = self._expand_macro_text(operand, location).strip()
        tokens = _tokenize_macro_text(expanded)
        if tokens is None:
            raise PreprocessorError(
                "Invalid #include directive",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )

        if len(tokens) == 1 and tokens[0].kind == TokenKind.STRING_LITERAL:
            literal = tokens[0].text
            return literal[1:-1], False

        if (
            len(tokens) >= 3
            and tokens[0].kind == TokenKind.PUNCTUATOR
            and tokens[-1].kind == TokenKind.PUNCTUATOR
            and tokens[0].text == "<"
            and tokens[-1].text == ">"
        ):
            return "".join(token.text for token in tokens[1:-1]), True

        raise PreprocessorError(
            "Invalid #include directive",
            location.line,
            1,
            filename=location.filename,
            code=_PP_INVALID_DIRECTIVE,
        )

    def _resolve_include(
        self,
        include_name: str,
        *,
        is_angled: bool,
        base_dir: Path | None,
        include_next_from: Path | None = None,
    ) -> tuple[Path | None, tuple[Path, ...]]:
        search_roots: list[Path] = []
        if not is_angled and base_dir is not None:
            search_roots.append(base_dir)
            search_roots.extend(Path(path) for path in self._options.quote_include_dirs)
        search_roots.extend(Path(path) for path in self._options.include_dirs)
        search_roots.extend(Path(path) for path in self._cpath_include_dirs)
        search_roots.extend(Path(path) for path in self._options.system_include_dirs)
        search_roots.extend(Path(path) for path in self._host_system_include_dirs)
        search_roots.extend(Path(path) for path in self._c_include_path_dirs)
        search_roots.extend(Path(path) for path in self._options.after_include_dirs)

        start_index = 0
        if include_next_from is not None:
            include_next_from_resolved = include_next_from.resolve()
            for index, root in enumerate(search_roots):
                if root.resolve() == include_next_from_resolved:
                    start_index = index + 1
                    break

        searched_roots_list: list[Path] = []
        seen_roots: set[Path] = set()
        if include_next_from is not None:
            # `#include_next` must not re-enter the same resolved include root,
            # even if that root appears again later via a duplicate/symlink path.
            seen_roots.add(include_next_from.resolve())
        for root in search_roots[start_index:]:
            resolved_root = root.resolve()
            if resolved_root in seen_roots:
                continue
            seen_roots.add(resolved_root)
            searched_roots_list.append(resolved_root)

        searched_roots = tuple(searched_roots_list)
        for root in searched_roots:
            candidate = root / include_name
            if candidate.is_file():
                return candidate.resolve(), searched_roots
        return None, searched_roots

    def _parse_cli_define(self, define: str) -> _Macro:
        if "=" in define:
            head, replacement = define.split("=", 1)
        else:
            head, replacement = define, "1"

        parsed_function = _parse_cli_define_head(head)
        if parsed_function is None:
            name = head.strip()
            if _IDENT_RE.fullmatch(name) is None:
                raise PreprocessorError(
                    f"Invalid macro definition: {define}",
                    code=_PP_INVALID_MACRO,
                )
            return _Macro(name, tuple(_tokenize_macro_replacement(replacement.strip())))

        name, params, variadic = parsed_function
        return _Macro(
            name,
            tuple(_tokenize_macro_replacement(replacement.strip())),
            parameters=params,
            is_variadic=variadic,
        )

    def _require_macro_name(self, body: str, location: _SourceLocation) -> str:
        stripped = _strip_condition_comments(body).strip()
        parts = stripped.split()
        macro_name = parts[0] if parts else ""
        if len(parts) != 1 or _IDENT_RE.fullmatch(macro_name) is None:
            raise PreprocessorError(
                "Expected macro name",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )
        return macro_name

    def _eval_condition(
        self,
        body: str,
        location: _SourceLocation,
        *,
        base_dir: Path | None,
    ) -> bool:
        def replace_defined(match: re.Match[str]) -> str:
            macro_name = match.group(1)
            return "1" if macro_name in self._macros else "0"

        condition = _strip_condition_comments(body)
        expanded = _DEFINED_PAREN_RE.sub(replace_defined, condition)
        expanded = _DEFINED_BARE_RE.sub(replace_defined, expanded)
        try:
            expanded = self._replace_has_include_operators(
                expanded,
                location,
                base_dir=base_dir,
            )
            expanded = self._replace_feature_probe_operators(expanded, location)
            expanded = self._expand_macro_text(expanded, location)
            # Run include-operator rewriting again so operators introduced via
            # macro expansion (for example HAS(x) -> __has_include(x)) are handled.
            expanded = self._replace_has_include_operators(
                expanded,
                location,
                base_dir=base_dir,
            )
            expanded = self._replace_feature_probe_operators(expanded, location)
            py_expr = _translate_expr_to_python(expanded)
            return bool(_safe_eval_pp_expr(py_expr))
        except PreprocessorError:
            raise
        except ValueError as error:
            raise PreprocessorError(
                "Invalid #if expression",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_IF_EXPR,
            ) from error

    def _replace_has_include_operators(
        self,
        expr: str,
        location: _SourceLocation,
        *,
        base_dir: Path | None,
    ) -> str:
        # Handle include-probing operators before expression tokenization.
        rewritten = expr
        rewritten = self._replace_single_has_include_operator(
            rewritten,
            marker="__has_include_next",
            location=location,
            base_dir=base_dir,
            include_next=True,
        )
        rewritten = self._replace_single_has_include_operator(
            rewritten,
            marker="__has_include",
            location=location,
            base_dir=base_dir,
            include_next=False,
        )
        return rewritten

    def _replace_feature_probe_operators(self, expr: str, location: _SourceLocation) -> str:
        rewritten = expr
        rewritten = self._replace_single_feature_probe_operator(
            rewritten,
            marker="__has_builtin",
            location=location,
            supported=(),
        )
        rewritten = self._replace_single_feature_probe_operator(
            rewritten,
            marker="__has_attribute",
            location=location,
            supported=(),
        )
        rewritten = self._replace_single_feature_probe_operator(
            rewritten,
            marker="__has_feature",
            location=location,
            supported=(),
        )
        rewritten = self._replace_single_feature_probe_operator(
            rewritten,
            marker="__has_extension",
            location=location,
            supported=(),
        )
        rewritten = self._replace_single_warning_probe_operator(
            rewritten,
            marker="__has_warning",
            location=location,
            supported=_SUPPORTED_WARNINGS,
        )
        rewritten = self._replace_single_attribute_probe_operator(
            rewritten,
            marker="__has_c_attribute",
            location=location,
            supported=_SUPPORTED_C_ATTRIBUTES,
        )
        return rewritten

    def _replace_single_feature_probe_operator(
        self,
        expr: str,
        *,
        marker: str,
        location: _SourceLocation,
        supported: tuple[str, ...],
    ) -> str:
        supported_names = frozenset(supported)
        chunks: list[str] = []
        index = 0
        while True:
            found = expr.find(marker, index)
            if found < 0:
                chunks.append(expr[index:])
                return "".join(chunks)
            prev = expr[found - 1] if found > 0 else ""
            next_pos = found + len(marker)
            next_char = expr[next_pos] if next_pos < len(expr) else ""
            if (prev and (prev.isalnum() or prev == "_")) or (
                next_char and (next_char.isalnum() or next_char == "_")
            ):
                chunks.append(expr[index : found + len(marker)])
                index = found + len(marker)
                continue

            chunks.append(expr[index:found])
            cursor = next_pos
            while cursor < len(expr) and expr[cursor].isspace():
                cursor += 1
            if cursor >= len(expr) or expr[cursor] != "(":
                raise PreprocessorError(
                    f"Invalid {marker} expression: expected '(' after operator",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            close_paren = self._find_matching_has_include_close(expr, cursor)
            if close_paren < 0:
                raise PreprocessorError(
                    f"Invalid {marker} expression: missing closing ')'",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )

            operand = expr[cursor + 1 : close_paren].strip()
            if not operand:
                raise PreprocessorError(
                    f"Invalid {marker} expression: missing feature operand",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", operand):
                raise PreprocessorError(
                    f"Invalid {marker} expression: feature operand must be an identifier",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )

            chunks.append("1" if operand in supported_names else "0")
            index = close_paren + 1

    def _replace_single_warning_probe_operator(
        self,
        expr: str,
        *,
        marker: str,
        location: _SourceLocation,
        supported: frozenset[str],
    ) -> str:
        chunks: list[str] = []
        index = 0
        while True:
            found = expr.find(marker, index)
            if found < 0:
                chunks.append(expr[index:])
                return "".join(chunks)
            prev = expr[found - 1] if found > 0 else ""
            next_pos = found + len(marker)
            next_char = expr[next_pos] if next_pos < len(expr) else ""
            if (prev and (prev.isalnum() or prev == "_")) or (
                next_char and (next_char.isalnum() or next_char == "_")
            ):
                chunks.append(expr[index : found + len(marker)])
                index = found + len(marker)
                continue

            chunks.append(expr[index:found])
            cursor = next_pos
            while cursor < len(expr) and expr[cursor].isspace():
                cursor += 1
            if cursor >= len(expr) or expr[cursor] != "(":
                raise PreprocessorError(
                    f"Invalid {marker} expression: expected '(' after operator",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            close_paren = self._find_matching_has_include_close(expr, cursor)
            if close_paren < 0:
                raise PreprocessorError(
                    f"Invalid {marker} expression: missing closing ')'",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )

            operand = expr[cursor + 1 : close_paren].strip()
            if not operand:
                raise PreprocessorError(
                    f"Invalid {marker} expression: missing warning option operand",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            if not re.fullmatch(r'"(?:[^"\\\n]|\\.)*"', operand):
                raise PreprocessorError(
                    f"Invalid {marker} expression: warning option operand must be a string literal",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )

            option = operand[1:-1]
            chunks.append("1" if option in supported else "0")
            index = close_paren + 1

    def _replace_single_attribute_probe_operator(
        self,
        expr: str,
        *,
        marker: str,
        location: _SourceLocation,
        supported: frozenset[str],
    ) -> str:
        chunks: list[str] = []
        index = 0
        while True:
            found = expr.find(marker, index)
            if found < 0:
                chunks.append(expr[index:])
                return "".join(chunks)
            prev = expr[found - 1] if found > 0 else ""
            next_pos = found + len(marker)
            next_char = expr[next_pos] if next_pos < len(expr) else ""
            if (prev and (prev.isalnum() or prev == "_")) or (
                next_char and (next_char.isalnum() or next_char == "_")
            ):
                chunks.append(expr[index : found + len(marker)])
                index = found + len(marker)
                continue

            chunks.append(expr[index:found])
            cursor = next_pos
            while cursor < len(expr) and expr[cursor].isspace():
                cursor += 1
            if cursor >= len(expr) or expr[cursor] != "(":
                raise PreprocessorError(
                    f"Invalid {marker} expression: expected '(' after operator",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            close_paren = self._find_matching_has_include_close(expr, cursor)
            if close_paren < 0:
                raise PreprocessorError(
                    f"Invalid {marker} expression: missing closing ')'",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )

            operand = expr[cursor + 1 : close_paren].strip()
            if not operand:
                raise PreprocessorError(
                    f"Invalid {marker} expression: missing attribute operand",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*", operand):
                raise PreprocessorError(
                    f"Invalid {marker} expression: attribute operand must be an "
                    "identifier or scoped identifier",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )

            chunks.append("1" if operand in supported else "0")
            index = close_paren + 1

    def _replace_single_has_include_operator(
        self,
        expr: str,
        *,
        marker: str,
        location: _SourceLocation,
        base_dir: Path | None,
        include_next: bool,
    ) -> str:
        if include_next and self._options.std == "c11" and marker in expr:
            raise PreprocessorError(
                "Invalid #if expression",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_IF_EXPR,
            )

        chunks: list[str] = []
        index = 0
        while True:
            found = expr.find(marker, index)
            if found < 0:
                chunks.append(expr[index:])
                return "".join(chunks)
            prev = expr[found - 1] if found > 0 else ""
            next_pos = found + len(marker)
            next_char = expr[next_pos] if next_pos < len(expr) else ""
            if (prev and (prev.isalnum() or prev == "_")) or (
                next_char and (next_char.isalnum() or next_char == "_")
            ):
                chunks.append(expr[index : found + len(marker)])
                index = found + len(marker)
                continue
            chunks.append(expr[index:found])
            cursor = next_pos
            while cursor < len(expr) and expr[cursor].isspace():
                cursor += 1
            if cursor >= len(expr) or expr[cursor] != "(":
                raise PreprocessorError(
                    f"Invalid {marker} expression: expected '(' after operator",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            close_paren = self._find_matching_has_include_close(expr, cursor)
            if close_paren < 0:
                raise PreprocessorError(
                    f"Invalid {marker} expression: missing closing ')'",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            operand = expr[cursor + 1 : close_paren].strip()
            if not operand:
                raise PreprocessorError(
                    f"Invalid {marker} expression: missing header operand",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                )
            try:
                include_name, is_angled = self._parse_header_name_operand(operand, location)
            except PreprocessorError as error:
                raise PreprocessorError(
                    f"Invalid {marker} expression: header operand must be quoted or angled",
                    location.line,
                    1,
                    filename=location.filename,
                    code=_PP_INVALID_IF_EXPR,
                ) from error
            cursor = close_paren + 1
            include_path, _ = self._resolve_include(
                include_name,
                is_angled=is_angled,
                base_dir=base_dir,
                include_next_from=base_dir if include_next else None,
            )
            chunks.append("1" if include_path is not None else "0")
            index = cursor

    def _find_matching_has_include_close(self, expr: str, open_paren: int) -> int:
        depth = 0
        index = open_paren
        while index < len(expr):
            char = expr[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
            index += 1
        return -1

    def _parse_line_directive(
        self,
        body: str,
        location: _SourceLocation,
    ) -> tuple[int, str | None]:
        expanded = self._expand_macro_text(body, location).strip()
        match = re.match(r'^(\d+)(?:\s+("(?:[^"\n]|\\.)*"))?\s*$', expanded)
        if match is None:
            raise PreprocessorError(
                "Invalid #line directive",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )

        line = int(match.group(1))
        if line <= 0:
            raise PreprocessorError(
                "Invalid #line directive",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            )

        filename_literal = match.group(2)
        if filename_literal is None:
            return line, None
        try:
            mapped_filename = cast(str, ast.literal_eval(filename_literal))
        except (SyntaxError, ValueError) as error:
            raise PreprocessorError(
                "Invalid #line directive",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_DIRECTIVE,
            ) from error
        return line, mapped_filename


def _parse_cli_define_head(head: str) -> tuple[str, tuple[str, ...], bool] | None:
    stripped = head.strip()
    if "(" not in stripped:
        return None
    open_index = stripped.find("(")
    close_index = stripped.rfind(")")
    if close_index <= open_index:
        return None
    if stripped[close_index + 1 :].strip():
        return None

    name = stripped[:open_index].strip()
    if _IDENT_RE.fullmatch(name) is None:
        return None

    parsed = _parse_macro_parameters(stripped[open_index + 1 : close_index])
    if parsed is None:
        return None
    params, variadic = parsed
    return name, tuple(params), variadic


def _parse_macro_parameters(text: str) -> tuple[list[str], bool] | None:
    if not text:
        return [], False
    items = [item.strip() for item in text.split(",")]
    params: list[str] = []
    is_variadic = False
    for index, item in enumerate(items):
        if item == "...":
            if index != len(items) - 1:
                return None
            is_variadic = True
            break
        if _IDENT_RE.fullmatch(item) is None or item in params:
            return None
        params.append(item)
    return params, is_variadic


def _tokenize_macro_replacement(text: str) -> list[_MacroToken]:
    if not text:
        return []
    tokens = _tokenize_macro_text(text)
    if tokens is None:
        return [_MacroToken(TokenKind.IDENT, text)]
    return tokens


def _tokenize_macro_text(text: str) -> list[_MacroToken] | None:
    if not text:
        return []
    try:
        tokens = lex_pp(text)
    except LexerError:
        return None
    out: list[_MacroToken] = []
    for token in tokens:
        if token.kind == TokenKind.EOF:
            continue
        lexeme = token.lexeme
        assert lexeme is not None
        out.append(_MacroToken(token.kind, lexeme))
    return out


def _render_macro_tokens(tokens: list[_MacroToken]) -> str:
    return " ".join(token.text for token in tokens if token.text)


def _expand_macro_tokens(
    tokens: list[_MacroToken],
    macros: dict[str, _Macro],
    std: str,
    location: _SourceLocation,
    disabled: frozenset[str] = frozenset(),
    dynamic_macro_resolver: Callable[[str, _SourceLocation], _MacroToken] | None = None,
) -> list[_MacroToken]:
    expanded: list[_MacroToken] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind != TokenKind.IDENT:
            expanded.append(token)
            index += 1
            continue
        if token.text in _PREDEFINED_DYNAMIC_MACROS and token.text in macros:
            if dynamic_macro_resolver is not None:
                expanded.append(dynamic_macro_resolver(token.text, location))
            else:
                expanded.append(_MacroToken(TokenKind.INT_CONST, "0"))
            index += 1
            continue
        macro = macros.get(token.text)
        if macro is None or macro.name in disabled:
            expanded.append(token)
            index += 1
            continue
        next_disabled = frozenset((*disabled, macro.name))
        if macro.parameters is None:
            replacement = _expand_macro_tokens(
                list(macro.replacement),
                macros,
                std,
                location,
                disabled=next_disabled,
                dynamic_macro_resolver=dynamic_macro_resolver,
            )
            expanded.extend(replacement)
            index += 1
            continue
        parsed = _parse_macro_invocation(tokens, index + 1, location)
        if parsed is None:
            expanded.append(token)
            index += 1
            continue
        args, next_index = parsed
        replacement = _expand_function_like_macro(
            macro,
            args,
            macros,
            std=std,
            location=location,
            disabled=disabled,
            dynamic_macro_resolver=dynamic_macro_resolver,
        )
        replacement = _expand_macro_tokens(
            replacement,
            macros,
            std,
            location,
            disabled=next_disabled,
            dynamic_macro_resolver=dynamic_macro_resolver,
        )
        expanded.extend(replacement)
        index = next_index
    return expanded


def _parse_macro_invocation(
    tokens: list[_MacroToken],
    index: int,
    location: _SourceLocation,
) -> tuple[list[list[_MacroToken]], int] | None:
    if index >= len(tokens) or tokens[index].text != "(":
        return None
    if index + 1 < len(tokens) and tokens[index + 1].text == ")":
        return [], index + 2
    args: list[list[_MacroToken]] = []
    current: list[_MacroToken] = []
    depth = 1
    index += 1
    while index < len(tokens):
        token = tokens[index]
        if token.text == "(":
            depth += 1
            current.append(token)
        elif token.text == ")":
            depth -= 1
            if depth == 0:
                args.append(current)
                return args, index + 1
            current.append(token)
        elif token.text == "," and depth == 1:
            args.append(current)
            current = []
        else:
            current.append(token)
        index += 1
    raise PreprocessorError(
        "Unterminated macro invocation",
        location.line,
        1,
        filename=location.filename,
        code=_PP_INVALID_MACRO,
    )


def _expand_function_like_macro(
    macro: _Macro,
    args: list[list[_MacroToken]],
    macros: dict[str, _Macro],
    *,
    std: str,
    location: _SourceLocation,
    disabled: frozenset[str],
    dynamic_macro_resolver: Callable[[str, _SourceLocation], _MacroToken] | None,
) -> list[_MacroToken]:
    assert macro.parameters is not None
    expected = len(macro.parameters)
    if macro.is_variadic:
        if len(args) < expected:
            raise PreprocessorError(
                "Insufficient macro arguments",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_MACRO,
            )
    elif len(args) != expected:
        raise PreprocessorError(
            "Macro argument count mismatch",
            location.line,
            1,
            filename=location.filename,
            code=_PP_INVALID_MACRO,
        )
    raw_named_args = {name: args[index] for index, name in enumerate(macro.parameters)}
    expanded_named_args = {
        name: _expand_macro_tokens(
            arg,
            macros,
            std,
            location,
            disabled=disabled,
            dynamic_macro_resolver=dynamic_macro_resolver,
        )
        for name, arg in raw_named_args.items()
    }
    raw_var_args: list[_MacroToken] = []
    expanded_var_args: list[_MacroToken] = []
    if macro.is_variadic:
        variadic_args = args[expected:]
        raw_var_args = _join_macro_arguments(variadic_args)
        expanded_var_args = _join_macro_arguments(
            [
                _expand_macro_tokens(
                    arg,
                    macros,
                    std,
                    location,
                    disabled=disabled,
                    dynamic_macro_resolver=dynamic_macro_resolver,
                )
                for arg in variadic_args
            ]
        )
    pieces: list[_MacroToken] = []
    replacement = list(macro.replacement)
    index = 0
    while index < len(replacement):
        token = replacement[index]
        token_text = token.text
        if token_text == "#" and index + 1 < len(replacement):
            target = replacement[index + 1].text
            target_tokens = _lookup_macro_argument(
                target,
                raw_named_args,
                expanded_named_args,
                raw_var_args,
                expanded_var_args,
                macro.is_variadic,
                want_raw=True,
            )
            if target_tokens is not None:
                pieces.append(
                    _MacroToken(TokenKind.STRING_LITERAL, _stringize_tokens(target_tokens))
                )
                index += 2
                continue
        is_paste_context = (
            index > 0
            and replacement[index - 1].text == "##"
            or index + 1 < len(replacement)
            and replacement[index + 1].text == "##"
        )
        target_tokens = _lookup_macro_argument(
            token_text,
            raw_named_args,
            expanded_named_args,
            raw_var_args,
            expanded_var_args,
            macro.is_variadic,
            want_raw=is_paste_context,
        )
        if target_tokens is not None:
            if target_tokens:
                pieces.extend(target_tokens)
            elif is_paste_context:
                pieces.append(_EMPTY_MACRO_TOKEN)
            index += 1
            continue
        pieces.append(token)
        index += 1
    return _apply_token_paste(pieces, std=std, location=location)


def _lookup_macro_argument(
    name: str,
    raw_named_args: dict[str, list[_MacroToken]],
    expanded_named_args: dict[str, list[_MacroToken]],
    raw_var_args: list[_MacroToken],
    expanded_var_args: list[_MacroToken],
    is_variadic: bool,
    *,
    want_raw: bool,
) -> list[_MacroToken] | None:
    if name in raw_named_args:
        return raw_named_args[name] if want_raw else expanded_named_args[name]
    if is_variadic and name == "__VA_ARGS__":
        return raw_var_args if want_raw else expanded_var_args
    return None


def _join_macro_arguments(args: list[list[_MacroToken]]) -> list[_MacroToken]:
    if not args:
        return []
    out: list[_MacroToken] = []
    for index, arg in enumerate(args):
        if index > 0:
            out.append(_COMMA_MACRO_TOKEN)
        out.extend(arg)
    return out


def _stringize_tokens(tokens: list[_MacroToken]) -> str:
    text = " ".join(token.text for token in tokens if token.text)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _apply_token_paste(
    tokens: list[_MacroToken], *, std: str, location: _SourceLocation
) -> list[_MacroToken]:
    out = list(tokens)
    index = 0
    while index < len(out):
        if out[index].text != "##":
            index += 1
            continue
        if index == 0 or index + 1 >= len(out):
            raise PreprocessorError(
                "Invalid token paste",
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_MACRO,
            )
        left = out[index - 1]
        right = out[index + 1]
        pasted = _paste_token_pair(left, right, std=std, location=location)
        out[index - 1 : index + 2] = pasted
        index -= 1
    return [token for token in out if token.text]


def _paste_token_pair(
    left: _MacroToken,
    right: _MacroToken,
    *,
    std: str,
    location: _SourceLocation | None = None,
    line_no: int | None = None,
) -> list[_MacroToken]:
    actual_location = location
    if actual_location is None:
        actual_location = _SourceLocation("<input>", 1 if line_no is None else line_no)
    left_text = left.text
    right_text = right.text
    if not left_text and not right_text:
        return []
    if not left_text:
        return [right]
    if not right_text:
        if std == "gnu11" and left_text == ",":
            return []
        return [left]
    pasted = _tokenize_macro_text(left_text + right_text)
    if pasted is None or len(pasted) != 1:
        raise PreprocessorError(
            "Invalid token paste result",
            actual_location.line,
            1,
            filename=actual_location.filename,
            code=_PP_INVALID_MACRO,
        )
    return pasted


def _translate_expr_to_python(expr: str) -> str:
    tokens = _tokenize_expr(expr)
    tokens = _collapse_function_invocations(tokens)
    mapped: list[str] = []
    for token in tokens:
        value = _parse_pp_integer_literal(token)
        if value is not None:
            if _is_unsigned_pp_integer(token):
                mapped.append(f"u64({value})")
            else:
                mapped.append(str(value))
            continue
        char_value = _parse_pp_char_literal(token)
        if char_value is not None:
            mapped.append(str(char_value))
            continue
        if _IDENT_RE.fullmatch(token):
            mapped.append("0")
            continue
        if token == "&&":
            mapped.append("and")
            continue
        if token == "||":
            mapped.append("or")
            continue
        if token == "!":
            mapped.append("not")
            continue
        if token == "/":
            mapped.append("//")
            continue
        mapped.append(token)
    return " ".join(mapped)


def _collapse_function_invocations(tokens: list[str]) -> list[str]:
    collapsed: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _IDENT_RE.fullmatch(token) and index + 1 < len(tokens) and tokens[index + 1] == "(":
            depth = 0
            index += 1
            while index < len(tokens):
                next_token = tokens[index]
                if next_token == "(":
                    depth += 1
                elif next_token == ")":
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
            if depth != 0:
                raise ValueError("Invalid token")
            collapsed.append("0")
            continue
        collapsed.append(token)
        index += 1
    return collapsed


def _parse_pp_integer_literal(token: str) -> int | None:
    if _PP_INT_RE.fullmatch(token) is None:
        return None
    index = len(token)
    while index > 0 and token[index - 1] in "uUlL":
        index -= 1
    digits = token[:index]
    if digits.startswith(("0x", "0X")):
        return int(digits, 16)
    if digits.startswith("0") and len(digits) > 1:
        if any(ch not in "01234567" for ch in digits):
            return None
        return int(digits, 8)
    return int(digits, 10)


def _is_unsigned_pp_integer(token: str) -> bool:
    if _PP_INT_RE.fullmatch(token) is None:
        return False
    return any(ch in "uU" for ch in token)


def _parse_pp_char_literal(token: str) -> int | None:
    literal = token
    for prefix in ("u8", "u", "U", "L"):
        if literal.startswith(prefix):
            literal = literal[len(prefix) :]
            break
    try:
        value = ast.literal_eval(literal)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(value, str) or not value:
        return None
    result = 0
    for char in value:
        result = (result << 8) | (ord(char) & 0xFF)
    return result


def _strip_condition_comments(expr: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", " ", expr)
    if "//" in without_block:
        return without_block.split("//", 1)[0]
    return without_block


def _tokenize_expr(expr: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(expr):
        if expr[index].isspace():
            index += 1
            continue
        match = _EXPR_TOKEN_RE.match(expr, index)
        if match is None:
            raise ValueError("Invalid token")
        tokens.append(match.group(0))
        index = match.end()
    return tokens


def _safe_eval_int_expr(expr: str) -> int:
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError as error:
        raise ValueError("Invalid expression") from error
    return _eval_node(node)


_UINT64_MASK = (1 << 64) - 1


@dataclass(frozen=True)
class _PPValue:
    value: int
    is_unsigned: bool = False

    def as_unsigned(self) -> int:
        return self.value & _UINT64_MASK

    def normalize(self) -> "_PPValue":
        if not self.is_unsigned:
            return self
        return _PPValue(self.value & _UINT64_MASK, True)


def _safe_eval_pp_expr(expr: str) -> int:
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError as error:
        raise ValueError("Invalid expression") from error
    try:
        return _eval_pp_node(node).value
    except ZeroDivisionError as error:
        raise ValueError("Invalid expression") from error


def _eval_pp_node(node: ast.AST) -> _PPValue:
    if isinstance(node, ast.Expression):
        return _eval_pp_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return _PPValue(int(node.value))
        if isinstance(node.value, int):
            return _PPValue(node.value)
        raise ValueError(f"Unsupported preprocessor literal type: {type(node.value).__name__}")
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "u64"
            and len(node.args) == 1
            and not node.keywords
        ):
            value = _eval_pp_node(node.args[0])
            return _PPValue(value.as_unsigned(), True)
        raise ValueError("Unsupported preprocessor call expression")
    if isinstance(node, ast.UnaryOp):
        operand = _eval_pp_node(node.operand)
        if isinstance(node.op, ast.Not):
            return _PPValue(0 if operand.value else 1)
        if isinstance(node.op, ast.UAdd):
            return operand.normalize()
        if isinstance(node.op, ast.USub):
            value = -operand.value
            result = _PPValue(value, operand.is_unsigned)
            return result.normalize()
        if isinstance(node.op, ast.Invert):
            value = ~operand.value
            result = _PPValue(value, operand.is_unsigned)
            return result.normalize()
        raise ValueError(f"Unsupported preprocessor unary operator: {type(node.op).__name__}")
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if _eval_pp_node(value).value == 0:
                    return _PPValue(0)
            return _PPValue(1)
        if isinstance(node.op, ast.Or):
            for value in node.values:
                if _eval_pp_node(value).value != 0:
                    return _PPValue(1)
            return _PPValue(0)
        raise ValueError(f"Unsupported preprocessor boolean operator: {type(node.op).__name__}")
    if isinstance(node, ast.BinOp):
        left = _eval_pp_node(node.left)
        right = _eval_pp_node(node.right)
        is_unsigned = left.is_unsigned or right.is_unsigned
        left_value = left.as_unsigned() if is_unsigned else left.value
        right_value = right.as_unsigned() if is_unsigned else right.value
        if isinstance(node.op, ast.Add):
            value = left_value + right_value
        elif isinstance(node.op, ast.Sub):
            value = left_value - right_value
        elif isinstance(node.op, ast.Mult):
            value = left_value * right_value
        elif isinstance(node.op, ast.FloorDiv):
            value = left_value // right_value
        elif isinstance(node.op, ast.Mod):
            value = left_value % right_value
        elif isinstance(node.op, ast.LShift):
            value = left_value << right_value
        elif isinstance(node.op, ast.RShift):
            value = left_value >> right_value
        elif isinstance(node.op, ast.BitOr):
            value = left_value | right_value
        elif isinstance(node.op, ast.BitAnd):
            value = left_value & right_value
        elif isinstance(node.op, ast.BitXor):
            value = left_value ^ right_value
        else:
            raise ValueError(f"Unsupported preprocessor binary operator: {type(node.op).__name__}")
        result = _PPValue(value, is_unsigned)
        return result.normalize()
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise ValueError(
                "Unsupported preprocessor comparison shape: "
                f"expected 1 operator, got {len(node.ops)}"
            )
        if len(node.comparators) != 1:
            raise ValueError(
                "Unsupported preprocessor comparison shape: "
                f"expected 1 comparator, got {len(node.comparators)}"
            )
        left = _eval_pp_node(node.left)
        right = _eval_pp_node(node.comparators[0])
        is_unsigned = left.is_unsigned or right.is_unsigned
        left_value = left.as_unsigned() if is_unsigned else left.value
        right_value = right.as_unsigned() if is_unsigned else right.value
        op = node.ops[0]
        if isinstance(op, ast.Eq):
            return _PPValue(int(left_value == right_value))
        if isinstance(op, ast.NotEq):
            return _PPValue(int(left_value != right_value))
        if isinstance(op, ast.Lt):
            return _PPValue(int(left_value < right_value))
        if isinstance(op, ast.LtE):
            return _PPValue(int(left_value <= right_value))
        if isinstance(op, ast.Gt):
            return _PPValue(int(left_value > right_value))
        if isinstance(op, ast.GtE):
            return _PPValue(int(left_value >= right_value))
        raise ValueError(f"Unsupported preprocessor comparison operator: {type(op).__name__}")
    raise ValueError(f"Unsupported preprocessor expression node: {type(node).__name__}")


def _eval_node(node: ast.AST) -> int:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return int(node.value)
        if isinstance(node.value, int):
            return node.value
        raise ValueError(
            f"Unsupported integer-expression literal type: {type(node.value).__name__}"
        )
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand)
        if isinstance(node.op, ast.Not):
            return 0 if value else 1
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.Invert):
            return ~value
        raise ValueError(f"Unsupported integer-expression unary operator: {type(node.op).__name__}")
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if _eval_node(value) == 0:
                    return 0
            return 1
        if isinstance(node.op, ast.Or):
            for value in node.values:
                if _eval_node(value) != 0:
                    return 1
            return 0
        raise ValueError(
            f"Unsupported integer-expression boolean operator: {type(node.op).__name__}"
        )
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.LShift):
            return left << right
        if isinstance(node.op, ast.RShift):
            return left >> right
        if isinstance(node.op, ast.BitOr):
            return left | right
        if isinstance(node.op, ast.BitAnd):
            return left & right
        if isinstance(node.op, ast.BitXor):
            return left ^ right
        raise ValueError(
            f"Unsupported integer-expression binary operator: {type(node.op).__name__}"
        )
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise ValueError(
                "Unsupported integer-expression comparison shape: "
                f"expected 1 operator, got {len(node.ops)}"
            )
        if len(node.comparators) != 1:
            raise ValueError(
                "Unsupported integer-expression comparison shape: "
                f"expected 1 comparator, got {len(node.comparators)}"
            )
        left = _eval_node(node.left)
        right = _eval_node(node.comparators[0])
        op = node.ops[0]
        if isinstance(op, ast.Eq):
            return int(left == right)
        if isinstance(op, ast.NotEq):
            return int(left != right)
        if isinstance(op, ast.Lt):
            return int(left < right)
        if isinstance(op, ast.LtE):
            return int(left <= right)
        if isinstance(op, ast.Gt):
            return int(left > right)
        if isinstance(op, ast.GtE):
            return int(left >= right)
        raise ValueError(f"Unsupported integer-expression comparison operator: {type(op).__name__}")
    raise ValueError(f"Unsupported integer-expression node: {type(node).__name__}")


def _parse_directive(line: str) -> tuple[str, str] | None:
    if not line.lstrip().startswith("#"):
        return None
    match = _DIRECTIVE_RE.match(line)
    if match is None:
        return None
    return match.group("name"), match.group("body")


def _blank_line(line: str) -> str:
    return "\n" if line.endswith("\n") else ""


def _is_active(stack: list[_ConditionalFrame]) -> bool:
    return all(frame.active for frame in stack)


def _expand_object_like_macros(line: str, macros: dict[str, str]) -> str:
    if not macros:
        return line
    names = cast(list[str], sorted(macros, key=len, reverse=True))
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in names) + r")\b")
    return pattern.sub(lambda match: macros[match.group(0)], line)


_ASM_PREFIX_RE = re.compile(r"^\s*(?:__asm__|__asm|asm)\b")
_ASM_LABEL_RE = re.compile(r"(?<!\w)(?:__asm__|__asm|asm)\s*\([^;\n]*\)")


def _strip_gnu_asm_extensions(source: str) -> str:
    lines = source.splitlines(keepends=True)
    if not lines:
        return source
    stripped_lines: list[str] = []
    in_asm_statement = False
    for line in lines:
        if in_asm_statement:
            stripped_lines.append(_blank_line(line))
            if ";" in line:
                in_asm_statement = False
            continue
        if _ASM_PREFIX_RE.match(line):
            stripped_lines.append(_blank_line(line))
            in_asm_statement = ";" not in line
            continue
        stripped_lines.append(_ASM_LABEL_RE.sub("", line))
    return "".join(stripped_lines)


def _quote_string_literal(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _format_date_macro(now: datetime) -> str:
    month = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )[now.month - 1]
    return f"{month} {now.day:2d} {now.year:04d}"


def _format_timestamp_macro(now: datetime) -> str:
    weekday = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[now.weekday()]
    month = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )[now.month - 1]
    return f"{weekday} {month} {now.day:2d} {now:%H:%M:%S} {now.year:04d}"


def _reject_gnu_asm_extensions(
    source: str,
    line_map: tuple[tuple[str, int], ...],
) -> None:
    for line_number, line in enumerate(source.splitlines(), start=1):
        if _ASM_PREFIX_RE.match(line) or _ASM_LABEL_RE.search(line):
            mapped_filename, mapped_line = (
                line_map[line_number - 1]
                if 1 <= line_number <= len(line_map)
                else ("<input>", line_number)
            )
            raise PreprocessorError(
                "GNU asm extension is not allowed in c11",
                mapped_line,
                1,
                filename=mapped_filename,
                code=_PP_GNU_EXTENSION,
            )
