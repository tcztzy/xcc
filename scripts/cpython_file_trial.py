#!/usr/bin/env python3
"""Run compile-only frontend trials against pinned CPython source files."""

import argparse
import hashlib
import shutil
import sys
import sysconfig
import tarfile
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xcc.diag import FrontendError
from xcc.frontend import compile_path
from xcc.options import FrontendOptions
from xcc.cpython_harness import (
    CPythonTrialResult,
    bucket_location,
    normalize_trial_detail,
    summarize_trial_results,
    top_failure_bucket,
)

ARCHIVE_URL = "https://www.python.org/ftp/python/3.11.12/Python-3.11.12.tgz"
ARCHIVE_NAME = "Python-3.11.12.tgz"
ARCHIVE_SHA256 = "379c9929a989a9d65a1f5d854e011f4872b142259f4fc0a8c4062d2815ed7fba"
ARCHIVE_ROOT = "Python-3.11.12"
DEFAULT_CACHE_DIR = ROOT / ".cache/external-artifacts"


@dataclass(frozen=True)
class TrialCase:
    path: str
    include_dirs: tuple[str, ...] = ()


DEFAULT_CASES = (
    TrialCase("Programs/python.c"),
    TrialCase("Parser/token.c"),
    TrialCase("Python/fileutils.c"),
    TrialCase("Python/pyfpe.c"),
    TrialCase("Modules/getaddrinfo.c"),
    TrialCase("Modules/getnameinfo.c"),
    TrialCase("Modules/_sha3/sha3.c", ("Modules/_sha3",)),
    TrialCase("Modules/expat/xmlrole.c", ("Modules/expat",)),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while True:
            chunk = file.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _download_archive(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=destination.parent,
        prefix=f"{destination.name}.",
        suffix=".part",
        delete=False,
    ) as temp_file:
        temp_path = Path(temp_file.name)
        with request.urlopen(url, timeout=120) as response:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                temp_file.write(chunk)
    temp_path.replace(destination)


def _ensure_archive(cache_dir: Path, archive_path_override: Path | None) -> Path:
    if archive_path_override is not None:
        archive_path = archive_path_override.resolve()
        if not archive_path.is_file():
            raise ValueError(f"archive file does not exist: {archive_path}")
    else:
        archive_path = (cache_dir / ARCHIVE_NAME).resolve()
        if archive_path.is_file() and _sha256_file(archive_path) == ARCHIVE_SHA256:
            return archive_path
        if archive_path.exists():
            archive_path.unlink()
        print(f"downloading {ARCHIVE_URL}")
        _download_archive(ARCHIVE_URL, archive_path)
    actual_sha = _sha256_file(archive_path)
    if actual_sha != ARCHIVE_SHA256:
        raise ValueError(
            f"archive sha256 mismatch: expected {ARCHIVE_SHA256}, got {actual_sha} ({archive_path})"
        )
    return archive_path


def _extract_archive(archive_path: Path, destination: Path) -> Path:
    root = destination.resolve()
    with tarfile.open(archive_path, mode="r:*") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"archive member escapes extraction root: {member.name}")
        archive.extractall(destination)
    source_root = destination / ARCHIVE_ROOT
    if not source_root.is_dir():
        raise ValueError(f"archive missing expected root directory: {ARCHIVE_ROOT}")
    return source_root


def _prepare_overlay(overlay: Path) -> None:
    config_h = Path(sysconfig.get_config_h_filename()).resolve()
    if not config_h.is_file():
        raise ValueError(f"host pyconfig.h not found: {config_h}")
    overlay.mkdir(parents=True, exist_ok=True)
    shutil.copy(config_h, overlay / "pyconfig.h")


def _base_include_dirs(source_root: Path, overlay: Path) -> tuple[str, ...]:
    return (
        str(overlay),
        str(source_root),
        str(source_root / "Include"),
        str(source_root / "Include/internal"),
        str(source_root / "Programs"),
        str(source_root / "Parser"),
        str(source_root / "Python"),
        str(source_root / "Objects"),
        str(source_root / "Modules"),
    )


def _normalize_diagnostic_file(filename: str | None, source_root: Path, overlay: Path) -> str | None:
    if filename is None:
        return None
    resolved = Path(filename).resolve()
    source_root = source_root.resolve()
    overlay = overlay.resolve()
    try:
        return resolved.relative_to(source_root).as_posix()
    except ValueError:
        pass
    try:
        relative = resolved.relative_to(overlay).as_posix()
    except ValueError:
        return str(resolved)
    return f"overlay/{relative}"


def select_cases(selected: tuple[str, ...]) -> tuple[TrialCase, ...]:
    if not selected:
        return DEFAULT_CASES
    known = {case.path: case for case in DEFAULT_CASES}
    missing = [path for path in selected if path not in known]
    if missing:
        raise ValueError(f"unknown case(s): {', '.join(missing)}")
    return tuple(known[path] for path in selected)


def _run_case(source_root: Path, overlay: Path, case: TrialCase) -> CPythonTrialResult:
    include_dirs = _base_include_dirs(source_root, overlay) + tuple(
        str(source_root / extra) for extra in case.include_dirs
    )
    options = FrontendOptions(std="gnu11", include_dirs=include_dirs)
    path = source_root / case.path
    try:
        compile_path(path, options=options)
    except FrontendError as error:
        return CPythonTrialResult(
            path=case.path,
            ok=False,
            detail=normalize_trial_detail(error.diagnostic.message),
            stage=error.diagnostic.stage,
            diagnostic_file=_normalize_diagnostic_file(
                error.diagnostic.filename,
                source_root,
                overlay,
            ),
            line=error.diagnostic.line,
            column=error.diagnostic.column,
        )
    return CPythonTrialResult(path=case.path, ok=True, detail="ok", stage="ok")


def run_curated_trial(
    *,
    cache_dir: Path,
    archive_path_override: Path | None,
    cases: tuple[TrialCase, ...],
) -> tuple[CPythonTrialResult, ...]:
    archive_path = _ensure_archive(cache_dir, archive_path_override)
    with tempfile.TemporaryDirectory() as tmp:
        work_root = Path(tmp)
        source_root = _extract_archive(archive_path, work_root)
        overlay = work_root / "overlay"
        _prepare_overlay(overlay)
        return tuple(_run_case(source_root, overlay, case) for case in cases)


def _print_summary(
    results: tuple[CPythonTrialResult, ...],
    *,
    emit_failure_lines: bool,
) -> None:
    for result in results:
        if result.ok:
            print(f"PASS {result.path}")
            continue
        print(f"FAIL {result.path} [{result.stage}] {result.detail}")
        if emit_failure_lines:
            print(f"FAIL [{result.stage}] {result.path}: {result.detail}")
    passed = sum(result.ok for result in results)
    print(f"\nCPython real-file trial: {passed}/{len(results)} passed")
    failures = Counter(result.stage for result in results if not result.ok)
    if failures:
        print("Failure stages:")
        for stage, count in sorted(failures.items()):
            print(f"- {stage}: {count}")
        summary = summarize_trial_results(results)
        print("Failure buckets:")
        for bucket in summary.buckets:
            print(
                f"- {bucket.code} [{bucket.stage}] x{bucket.count}: "
                f"{bucket.detail} @ {bucket_location(bucket)}"
            )
        top_bucket = top_failure_bucket(summary)
        if top_bucket is not None:
            examples = ", ".join(top_bucket.case_paths[:3])
            print(
                "Top blocker: "
                f"{top_bucket.code} [{top_bucket.stage}] x{top_bucket.count} "
                f"({examples})"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run compile-only frontend trials against pinned CPython source files."
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="cache directory for the pinned CPython archive",
    )
    parser.add_argument(
        "--archive-path",
        type=Path,
        default=None,
        help="use this local archive instead of the pinned download URL",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="run only the named case path (repeatable)",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="list the curated case paths and exit",
    )
    parser.add_argument(
        "--allow-failures",
        action="store_true",
        help="return success even when some curated files still fail",
    )
    parser.add_argument(
        "--emit-failure-lines",
        action="store_true",
        help="emit legacy machine-readable failure lines for blocker tools",
    )
    args = parser.parse_args()

    cases = select_cases(tuple(args.case))
    if args.list_cases:
        for case in cases:
            print(case.path)
        return 0

    results = run_curated_trial(
        cache_dir=args.cache_dir,
        archive_path_override=args.archive_path,
        cases=cases,
    )
    _print_summary(results, emit_failure_lines=args.emit_failure_lines)
    if args.allow_failures:
        return 0
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
