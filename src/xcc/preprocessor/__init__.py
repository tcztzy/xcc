import ast
import platform
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from xcc.host_includes import host_system_include_dirs
from xcc.lexer import TokenKind
from xcc.options import FrontendOptions, normalize_options

from . import common as _common
from . import conditionals as _conditionals
from . import expressions as _expressions
from . import includes as _includes
from . import macro_expansion as _macro_expansion
from . import macros as _macros
from . import pragmas as _pragmas
from . import probes as _probes
from . import process as _process
from . import text as _text

_DirectiveCursor = _common._DirectiveCursor
_LineMapBuilder = _common._LineMapBuilder
_LogicalCursor = _common._LogicalCursor
_OutputBuilder = _common._OutputBuilder
_ProcessedText = _common._ProcessedText
_SourceLocation = _common._SourceLocation
_location_tuple = _common._location_tuple
PreprocessorError = _common.PreprocessorError
_ConditionalFrame = _conditionals._ConditionalFrame
_handle_conditional = _conditionals._handle_conditional
_is_active = _conditionals._is_active
_EXPR_TOKEN_RE = _expressions._EXPR_TOKEN_RE
_INT64_MAX = _expressions._INT64_MAX
_INT64_MIN = _expressions._INT64_MIN
_PPExprOverflow = _expressions._PPExprOverflow
_PPValue = _expressions._PPValue
_PP_INT_RE = _expressions._PP_INT_RE
_UINT64_MASK = _expressions._UINT64_MASK
_collapse_function_invocations = _expressions._collapse_function_invocations
_eval_node = _expressions._eval_node
_eval_pp_node = _expressions._eval_pp_node
_is_unsigned_pp_integer = _expressions._is_unsigned_pp_integer
_parse_pp_char_literal = _expressions._parse_pp_char_literal
_parse_pp_integer_literal = _expressions._parse_pp_integer_literal
_rewrite_ternary = _expressions._rewrite_ternary
_safe_eval_int_expr = _expressions._safe_eval_int_expr
_safe_eval_pp_expr = _expressions._safe_eval_pp_expr
_strip_condition_comments = _expressions._strip_condition_comments
_tokenize_expr = _expressions._tokenize_expr
_translate_expr_to_python = _expressions._translate_expr_to_python
_env_path_list = _includes._env_path_list
_parse_header_name_operand = _includes._parse_header_name_operand
_parse_include_target = _includes._parse_include_target
_resolve_include = _includes._resolve_include
_source_dir = _includes._source_dir
_apply_token_paste = _macro_expansion._apply_token_paste
_expand_function_like_macro = _macro_expansion._expand_function_like_macro
_parse_macro_invocation = _macro_expansion._parse_macro_invocation
_paste_token_pair = _macro_expansion._paste_token_pair
_COMMA_MACRO_TOKEN = _macros._COMMA_MACRO_TOKEN
_EMPTY_MACRO_TOKEN = _macros._EMPTY_MACRO_TOKEN
_Macro = _macros._Macro
_MacroToken = _macros._MacroToken
_join_macro_arguments = _macros._join_macro_arguments
_lookup_macro_argument = _macros._lookup_macro_argument
_parse_cli_define_head = _macros._parse_cli_define_head
_parse_macro_parameters = _macros._parse_macro_parameters
_render_macro_tokens = _macros._render_macro_tokens
_stringize_tokens = _macros._stringize_tokens
_tokenize_macro_replacement = _macros._tokenize_macro_replacement
_tokenize_macro_text = _macros._tokenize_macro_text
_raise_pragma_error = _pragmas._raise_pragma_error
_validate_clang_fp_pragma = _pragmas._validate_clang_fp_pragma
_validate_clang_module_pragma = _pragmas._validate_clang_module_pragma
_validate_defined_syntax = _pragmas._validate_defined_syntax
_validate_diagnostic_pragma = _pragmas._validate_diagnostic_pragma
_validate_fenv_access_pragma = _pragmas._validate_fenv_access_pragma
_validate_gcc_visibility_pragma = _pragmas._validate_gcc_visibility_pragma
_validate_pragma = _pragmas._validate_pragma
_validate_stdc_pragma = _pragmas._validate_stdc_pragma
_blank_line = _text._blank_line
_expand_object_like_macros = _text._expand_object_like_macros
_format_date_macro = _text._format_date_macro
_format_include_cycle = _text._format_include_cycle
_format_include_reference = _text._format_include_reference
_format_include_search_roots = _text._format_include_search_roots
_format_include_trace = _text._format_include_trace
_format_timestamp_macro = _text._format_timestamp_macro
_macro_table_line = _text._macro_table_line
_parse_directive = _text._parse_directive
_quote_string_literal = _text._quote_string_literal
_scan_block_comment_state = _text._scan_block_comment_state
_strip_gnu_asm_extensions = _text._strip_gnu_asm_extensions

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_DEFINED_PAREN_RE = re.compile(r"\bdefined\s*\(\s*([A-Za-z_]\w*)\s*\)")
_DEFINED_BARE_RE = re.compile(r"\bdefined\s+([A-Za-z_]\w*)")

_PP_UNKNOWN_DIRECTIVE = "XCC-PP-0101"
_PP_INCLUDE_NOT_FOUND = "XCC-PP-0102"
_PP_INVALID_IF_EXPR = "XCC-PP-0103"
_PP_INVALID_DIRECTIVE = "XCC-PP-0104"
_PP_GNU_EXTENSION = "XCC-PP-0105"
_PP_INVALID_MACRO = "XCC-PP-0201"
_PP_UNTERMINATED_MACRO = "XCC-PP-0202"
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
        return _source_dir(filename)

    def _process_text(
        self,
        source: str,
        *,
        filename: str,
        source_id: str,
        base_dir: Path | None,
        include_stack: tuple[str, ...],
    ) -> _ProcessedText:
        return _process.process_text(
            self,
            source,
            filename=filename,
            source_id=source_id,
            base_dir=base_dir,
            include_stack=include_stack,
            parse_directive=_parse_directive,
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
        return _handle_conditional(
            name,
            body,
            location,
            stack,
            base_dir=base_dir,
            std=self._options.std,
            macros=self._macros,
            eval_condition=lambda text, loc, root: self._eval_condition(
                text,
                loc,
                base_dir=root,
            ),
            require_macro_name=self._require_macro_name,
            invalid_directive_code=_PP_INVALID_DIRECTIVE,
            unknown_directive_code=_PP_UNKNOWN_DIRECTIVE,
        )

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
            dynamic_macro_names=_PREDEFINED_DYNAMIC_MACROS,
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
        return _parse_include_target(
            body,
            location,
            expand_macro_text=self._expand_macro_text,
            invalid_directive_code=_PP_INVALID_DIRECTIVE,
        )

    def _parse_header_name_operand(
        self,
        operand: str,
        location: _SourceLocation,
    ) -> tuple[str, bool]:
        return _parse_header_name_operand(
            operand,
            location,
            expand_macro_text=self._expand_macro_text,
            invalid_directive_code=_PP_INVALID_DIRECTIVE,
        )

    def _resolve_include(
        self,
        include_name: str,
        *,
        is_angled: bool,
        base_dir: Path | None,
        include_next_from: Path | None = None,
    ) -> tuple[Path | None, tuple[Path, ...]]:
        return _resolve_include(
            include_name,
            is_angled=is_angled,
            base_dir=base_dir,
            quote_include_dirs=self._options.quote_include_dirs,
            include_dirs=self._options.include_dirs,
            cpath_include_dirs=self._cpath_include_dirs,
            system_include_dirs=self._options.system_include_dirs,
            host_system_include_dirs=self._host_system_include_dirs,
            c_include_path_dirs=self._c_include_path_dirs,
            after_include_dirs=self._options.after_include_dirs,
            include_next_from=include_next_from,
        )

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
        _validate_defined_syntax(condition, location)
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
        except _PPExprOverflow as error:
            raise PreprocessorError(
                str(error).capitalize(),
                location.line,
                1,
                filename=location.filename,
                code=_PP_INVALID_IF_EXPR,
            ) from error
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
        return _probes._replace_has_include_operators(
            expr,
            location=location,
            base_dir=base_dir,
            parse_header_name_operand=self._parse_header_name_operand,
            resolve_include=self._resolve_include,
            code=_PP_INVALID_IF_EXPR,
        )

    def _replace_feature_probe_operators(self, expr: str, location: _SourceLocation) -> str:
        return _probes._replace_feature_probe_operators(
            expr,
            location=location,
            supported_warnings=_SUPPORTED_WARNINGS,
            supported_c_attributes=_SUPPORTED_C_ATTRIBUTES,
            code=_PP_INVALID_IF_EXPR,
        )

    def _replace_single_feature_probe_operator(
        self,
        expr: str,
        *,
        marker: str,
        location: _SourceLocation,
        supported: tuple[str, ...],
    ) -> str:
        return _probes._replace_single_feature_probe_operator(
            expr,
            marker=marker,
            location=location,
            supported=supported,
            code=_PP_INVALID_IF_EXPR,
        )

    def _replace_single_warning_probe_operator(
        self,
        expr: str,
        *,
        marker: str,
        location: _SourceLocation,
        supported: frozenset[str],
    ) -> str:
        return _probes._replace_single_warning_probe_operator(
            expr,
            marker=marker,
            location=location,
            supported=supported,
            code=_PP_INVALID_IF_EXPR,
        )

    def _replace_single_attribute_probe_operator(
        self,
        expr: str,
        *,
        marker: str,
        location: _SourceLocation,
        supported: frozenset[str],
    ) -> str:
        return _probes._replace_single_attribute_probe_operator(
            expr,
            marker=marker,
            location=location,
            supported=supported,
            code=_PP_INVALID_IF_EXPR,
        )

    def _replace_single_has_include_operator(
        self,
        expr: str,
        *,
        marker: str,
        location: _SourceLocation,
        base_dir: Path | None,
        include_next: bool,
    ) -> str:
        return _probes._replace_single_has_include_operator(
            expr,
            marker=marker,
            location=location,
            base_dir=base_dir,
            include_next=include_next,
            parse_header_name_operand=self._parse_header_name_operand,
            resolve_include=self._resolve_include,
            code=_PP_INVALID_IF_EXPR,
        )

    def _find_matching_has_include_close(self, expr: str, open_paren: int) -> int:
        return _probes._find_matching_has_include_close(expr, open_paren)

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


def _expand_macro_tokens(
    tokens: list[_MacroToken],
    macros: dict[str, _Macro],
    std: str,
    location: _SourceLocation,
    disabled: frozenset[str] = frozenset(),
    dynamic_macro_resolver: Callable[[str, _SourceLocation], _MacroToken] | None = None,
    dynamic_macro_names: frozenset[str] = _PREDEFINED_DYNAMIC_MACROS,
) -> list[_MacroToken]:
    return _macro_expansion._expand_macro_tokens(
        tokens,
        macros,
        std,
        location,
        disabled=disabled,
        dynamic_macro_resolver=dynamic_macro_resolver,
        dynamic_macro_names=dynamic_macro_names,
    )


def _reject_gnu_asm_extensions(
    source: str,
    line_map: tuple[tuple[str, int], ...],
) -> None:
    _text._reject_gnu_asm_extensions(source, line_map, code=_PP_GNU_EXTENSION)
