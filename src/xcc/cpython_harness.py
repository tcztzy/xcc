import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

_STAGE_ORDER = {"pp": 0, "lex": 1, "parse": 2, "sema": 3}


@dataclass(frozen=True)
class CPythonTrialResult:
    path: str
    ok: bool
    stage: str
    detail: str
    diagnostic_file: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class CPythonFailureBucket:
    code: str
    stage: str
    detail: str
    diagnostic_file: str | None
    line: int | None
    column: int | None
    case_paths: tuple[str, ...]
    count: int


@dataclass(frozen=True)
class CPythonTrialSummary:
    total: int
    passed: int
    failed: int
    buckets: tuple[CPythonFailureBucket, ...]


def normalize_trial_detail(detail: str) -> str:
    return " ".join(detail.split())


def blocker_code_for_result(result: CPythonTrialResult) -> str:
    location = result.diagnostic_file or result.path
    line = result.line if result.line is not None else 0
    column = result.column if result.column is not None else 0
    detail = normalize_trial_detail(result.detail)
    payload = f"{result.stage}:{location}:{line}:{column}:{detail}"
    digest = hashlib.sha1(payload.encode()).hexdigest()[:8]
    return f"CPY_{result.stage.upper()}_{digest.upper()}"


def bucket_location(bucket: CPythonFailureBucket) -> str:
    location = bucket.diagnostic_file or bucket.case_paths[0]
    if bucket.line is None:
        return location
    if bucket.column is None:
        return f"{location}:{bucket.line}"
    return f"{location}:{bucket.line}:{bucket.column}"


def summarize_trial_results(results: Iterable[CPythonTrialResult]) -> CPythonTrialSummary:
    materialized = tuple(results)
    passed = 0
    grouped: dict[
        tuple[str, str | None, int | None, int | None, str],
        list[CPythonTrialResult],
    ] = {}
    for result in materialized:
        if result.ok:
            passed += 1
            continue
        detail = normalize_trial_detail(result.detail)
        key = (
            result.stage,
            result.diagnostic_file,
            result.line,
            result.column,
            detail,
        )
        grouped.setdefault(key, []).append(result)

    buckets: list[CPythonFailureBucket] = []
    for entries in grouped.values():
        exemplar = entries[0]
        detail = normalize_trial_detail(exemplar.detail)
        buckets.append(
            CPythonFailureBucket(
                code=blocker_code_for_result(
                    CPythonTrialResult(
                        path=exemplar.path,
                        ok=False,
                        stage=exemplar.stage,
                        detail=detail,
                        diagnostic_file=exemplar.diagnostic_file,
                        line=exemplar.line,
                        column=exemplar.column,
                    )
                ),
                stage=exemplar.stage,
                detail=detail,
                diagnostic_file=exemplar.diagnostic_file,
                line=exemplar.line,
                column=exemplar.column,
                case_paths=tuple(sorted(entry.path for entry in entries)),
                count=len(entries),
            )
        )

    buckets.sort(
        key=lambda bucket: (
            -bucket.count,
            _STAGE_ORDER.get(bucket.stage, 99),
            bucket_location(bucket),
            bucket.detail,
        )
    )
    total = len(materialized)
    failed = total - passed
    return CPythonTrialSummary(total=total, passed=passed, failed=failed, buckets=tuple(buckets))


def top_failure_bucket(summary: CPythonTrialSummary) -> CPythonFailureBucket | None:
    if not summary.buckets:
        return None
    return summary.buckets[0]


def trial_gate_verdict(summary: CPythonTrialSummary, *, enabled: bool = True) -> str:
    if not enabled:
        return "skip"
    if summary.failed:
        return "fail"
    return "pass"
