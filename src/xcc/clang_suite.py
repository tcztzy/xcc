import hashlib
import re
from pathlib import PurePosixPath

STAGE_EXPECTATIONS = frozenset({"lex", "pp", "parse", "sema"})
ALLOWED_EXPECTATIONS = frozenset({"ok", "error", *STAGE_EXPECTATIONS})
SKIP_REASON_KEY = "skip_reason"
SUPPORTED_SUFFIXES = (".c",)
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")
_NO_DIAGNOSTICS_MARKER = "expected-no-diagnostics"
_DIAGNOSTIC_MARKERS = (
    "expected-error",
    "expected-warning",
    "expected-note",
    "expected-remark",
    "expected-fatal",
)


def is_clang_test_case_path(
    upstream_path: str,
    *,
    suffixes: tuple[str, ...] = SUPPORTED_SUFFIXES,
) -> bool:
    path = PurePosixPath(upstream_path)
    return upstream_path.startswith("clang/test/") and path.suffix in suffixes


def fixture_path_from_upstream_path(upstream_path: str) -> str:
    relative = PurePosixPath(upstream_path).relative_to("clang/test")
    return str(PurePosixPath("tests/external/clang/generated") / relative)


def case_id_from_upstream_path(upstream_path: str) -> str:
    relative = str(PurePosixPath(upstream_path).relative_to("clang/test")).lower()
    case_id = _NON_ALNUM_RE.sub("-", relative).strip("-")
    digest = hashlib.sha1(upstream_path.encode("utf-8")).hexdigest()[:10]
    return f"clang-{case_id}-{digest}"


def infer_expectation_from_source(source: str) -> str:
    if _NO_DIAGNOSTICS_MARKER in source:
        return "ok"
    return "error" if any(marker in source for marker in _DIAGNOSTIC_MARKERS) else "ok"


def matches_expectation(expectation: str, actual: str) -> bool:
    if expectation == "error":
        return actual != "ok"
    return actual == expectation


def baseline_skip_reason(expectation: str, actual: str, detail: str | None = None) -> str:
    message = f"baseline skip: expected {expectation}, got {actual}"
    return f"{message} ({detail})" if detail else message
