#!/usr/bin/env python3
import argparse
import hashlib
import json
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib import parse
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests/external/clang/manifest.json"
DEFAULT_CACHE_DIR = ROOT / ".cache/external-artifacts"
CASE_REQUIRED_KEYS = ("id", "upstream", "fixture", "expect", "sha256")
UPSTREAM_REQUIRED_KEYS = (
    "repository",
    "release_tag",
    "archive_url",
    "archive_name",
    "archive_sha256",
    "license",
    "strip_components",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while True:
            chunk = file.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _assert_relpath(value: str, *, field: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid {field}: {value}")


def _fixture_path(case: dict[str, Any]) -> Path:
    fixture = (ROOT / case["fixture"]).resolve()
    root = ROOT.resolve()
    if fixture != root and root not in fixture.parents:
        raise ValueError(f"fixture escapes repository root: {case['id']}")
    return fixture


def _is_external_case(case: dict[str, Any]) -> bool:
    return case["upstream"].startswith("clang/test/")


def _read_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    upstream = payload.get("upstream")
    if not isinstance(upstream, dict):
        raise ValueError("manifest missing upstream object")
    for key in UPSTREAM_REQUIRED_KEYS:
        value = upstream.get(key)
        if key == "strip_components":
            if not isinstance(value, int) or value < 0:
                raise ValueError("manifest upstream.strip_components must be >= 0")
            continue
        if not isinstance(value, str) or not value:
            raise ValueError(f"manifest upstream.{key} must be a non-empty string")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("manifest cases must be a list")
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("manifest case must be an object")
        for key in CASE_REQUIRED_KEYS:
            if not isinstance(case.get(key), str) or not case[key]:
                raise ValueError(f"manifest case missing string key: {key}")
        _assert_relpath(case["upstream"], field="upstream")
        _assert_relpath(case["fixture"], field="fixture")
    return payload


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


def _ensure_archive(
    *,
    upstream: dict[str, Any],
    cache_dir: Path,
    archive_path_override: Path | None,
) -> Path:
    expected_sha = upstream["archive_sha256"]
    if archive_path_override is not None:
        archive_path = archive_path_override.resolve()
        if not archive_path.is_file():
            raise ValueError(f"archive file does not exist: {archive_path}")
    else:
        archive_path = (cache_dir / upstream["archive_name"]).resolve()
        if archive_path.is_file() and _sha256_file(archive_path) == expected_sha:
            return archive_path
        if archive_path.is_file():
            archive_path.unlink()
        print(f"downloading {upstream['archive_url']}")
        _download_archive(upstream["archive_url"], archive_path)
    actual_sha = _sha256_file(archive_path)
    if actual_sha != expected_sha:
        raise ValueError(
            f"archive sha256 mismatch: expected {expected_sha}, got {actual_sha} ({archive_path})"
        )
    return archive_path


def _build_member_index(archive: tarfile.TarFile, *, strip_components: int) -> dict[str, str]:
    index: dict[str, str] = {}
    for member in archive.getmembers():
        if not member.isfile():
            continue
        parts = [part for part in PurePosixPath(member.name).parts if part not in ("", ".")]
        if len(parts) <= strip_components:
            continue
        relative = "/".join(parts[strip_components:])
        index[relative] = member.name
    return index


def _read_member_bytes(
    archive: tarfile.TarFile,
    *,
    member_index: dict[str, str],
    upstream_path: str,
    case_id: str,
) -> bytes:
    member_name = member_index.get(upstream_path)
    if member_name is None:
        raise ValueError(f"archive missing upstream fixture for {case_id}: {upstream_path}")
    extracted = archive.extractfile(member_name)
    if extracted is None:
        raise ValueError(f"archive member is unreadable for {case_id}: {member_name}")
    return extracted.read()


def _materialize_external_cases(
    *,
    payload: dict[str, Any],
    archive_path: Path,
    update_sha: bool,
    clean_external: bool,
    manifest_path: Path,
) -> None:
    upstream = payload["upstream"]
    strip_components = upstream["strip_components"]
    changed = False
    expected_external_paths: set[Path] = set()

    with tarfile.open(archive_path, mode="r:*") as archive:
        member_index = _build_member_index(archive, strip_components=strip_components)
        for case in payload["cases"]:
            if not _is_external_case(case):
                continue
            fixture_path = _fixture_path(case)
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
            data = _read_member_bytes(
                archive,
                member_index=member_index,
                upstream_path=case["upstream"],
                case_id=case["id"],
            )
            digest = _sha256(data)
            if case["sha256"] != digest:
                if not update_sha:
                    raise ValueError(
                        "manifest checksum mismatch for "
                        f"{case['id']}: expected {case['sha256']}, got {digest}"
                    )
                case["sha256"] = digest
                changed = True
            if not fixture_path.is_file() or fixture_path.read_bytes() != data:
                fixture_path.write_bytes(data)
            expected_external_paths.add(fixture_path.resolve())

    if clean_external:
        generated_root = ROOT / "tests/external/clang/generated"
        if generated_root.is_dir():
            for candidate in generated_root.rglob("*"):
                if candidate.is_file() and candidate.resolve() not in expected_external_paths:
                    candidate.unlink()
            for directory in sorted(generated_root.rglob("*"), reverse=True):
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()

    if changed:
        manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print("updated manifest checksums for external fixtures")


def _run_check(*, payload: dict[str, Any], archive_path: Path) -> int:
    failures: list[str] = []
    upstream = payload["upstream"]
    strip_components = upstream["strip_components"]
    with tarfile.open(archive_path, mode="r:*") as archive:
        member_index = _build_member_index(archive, strip_components=strip_components)
        for case in payload["cases"]:
            fixture = _fixture_path(case)
            if not fixture.is_file():
                failures.append(f"missing fixture: {fixture}")
                continue
            local_data = fixture.read_bytes()
            local_sha = _sha256(local_data)
            if local_sha != case["sha256"]:
                failures.append(f"checksum mismatch: {case['id']}")
                continue
            if _is_external_case(case):
                upstream_data = _read_member_bytes(
                    archive,
                    member_index=member_index,
                    upstream_path=case["upstream"],
                    case_id=case["id"],
                )
                if upstream_data != local_data:
                    failures.append(f"content mismatch: {case['id']}")
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print(f"clang fixtures check passed for {len(payload['cases'])} cases")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize curated LLVM/Clang fixtures from a pinned release archive."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="path to tests/external/clang/manifest.json",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="cache directory for downloaded upstream archives",
    )
    parser.add_argument(
        "--archive-path",
        type=Path,
        help="use this local archive instead of downloading from manifest upstream.archive_url",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify local fixtures and checksums against the pinned release archive",
    )
    parser.add_argument(
        "--update-sha",
        action="store_true",
        help="rewrite manifest checksums for external fixtures during materialization",
    )
    parser.add_argument(
        "--clean-external",
        action="store_true",
        help="remove untracked files under tests/external/clang/generated not in the manifest",
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    payload = _read_manifest(manifest_path)
    archive_path = _ensure_archive(
        upstream=payload["upstream"],
        cache_dir=args.cache_dir.resolve(),
        archive_path_override=args.archive_path,
    )
    if args.check:
        return _run_check(payload=payload, archive_path=archive_path)
    _materialize_external_cases(
        payload=payload,
        archive_path=archive_path,
        update_sha=args.update_sha,
        clean_external=args.clean_external,
        manifest_path=manifest_path,
    )
    external_count = sum(1 for case in payload["cases"] if _is_external_case(case))
    print(
        "materialized "
        f"{external_count} external fixtures from {parse.urlparse(payload['upstream']['archive_url']).netloc}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
