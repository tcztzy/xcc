#!/usr/bin/env python3
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests/external/clang/manifest.json"


def _run_git(repo_dir: Path, *args: str, capture_output: bool = False) -> bytes:
    command = ["git", "-C", str(repo_dir), *args]
    if capture_output:
        completed = subprocess.run(command, check=True, capture_output=True)
        return completed.stdout
    subprocess.run(command, check=True)
    return b""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _assert_relpath(value: str, *, field: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid {field}: {value}")


def _read_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    upstream = payload.get("upstream")
    if not isinstance(upstream, dict):
        raise ValueError("manifest missing upstream object")
    repository = upstream.get("repository")
    if not isinstance(repository, str) or not repository:
        raise ValueError("manifest upstream.repository must be a non-empty string")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("manifest cases must be a list")
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("manifest case must be an object")
        for key in ("id", "upstream", "fixture", "expect", "sha256"):
            if not isinstance(case.get(key), str) or not case[key]:
                raise ValueError(f"manifest case missing string key: {key}")
        _assert_relpath(case["upstream"], field="upstream")
        _assert_relpath(case["fixture"], field="fixture")
    return payload


def _ensure_checkout(repo_dir: Path, repository: str) -> None:
    if (repo_dir / ".git").is_dir():
        return
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            repository,
            str(repo_dir),
        ],
        check=True,
    )


def _get_blob(repo_dir: Path, commit: str, upstream_path: str) -> bytes:
    return _run_git(repo_dir, "show", f"{commit}:{upstream_path}", capture_output=True)


def _run_check(*, payload: dict[str, Any], repo_dir: Path, commit: str) -> int:
    failures: list[str] = []
    for case in payload["cases"]:
        fixture_path = (ROOT / case["fixture"]).resolve()
        if ROOT.resolve() not in fixture_path.parents:
            failures.append(f"fixture escapes repository root: {case['id']}")
            continue
        if not fixture_path.is_file():
            failures.append(f"missing fixture: {fixture_path}")
            continue
        upstream_data = _get_blob(repo_dir, commit, case["upstream"])
        local_data = fixture_path.read_bytes()
        if local_data != upstream_data:
            failures.append(f"content mismatch: {case['id']}")
        if _sha256(local_data) != case["sha256"]:
            failures.append(f"checksum mismatch: {case['id']}")
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print(f"clang fixtures check passed for {len(payload['cases'])} cases")
    return 0


def _run_sync(*, payload: dict[str, Any], manifest_path: Path, repo_dir: Path, commit: str) -> None:
    for case in payload["cases"]:
        fixture_path = (ROOT / case["fixture"]).resolve()
        if ROOT.resolve() not in fixture_path.parents:
            raise ValueError(f"fixture escapes repository root: {case['id']}")
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        data = _get_blob(repo_dir, commit, case["upstream"])
        fixture_path.write_bytes(data)
        case["sha256"] = _sha256(data)
    payload["upstream"]["commit"] = commit
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"synced {len(payload['cases'])} clang fixture(s) at {commit}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync curated LLVM/Clang fixtures from a pinned commit.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="path to tests/external/clang/manifest.json",
    )
    parser.add_argument(
        "--checkout-dir",
        type=Path,
        help="reuse this llvm-project checkout instead of a temporary clone",
    )
    parser.add_argument(
        "--commit",
        help="override upstream commit from the manifest",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify local fixtures and checksums against upstream without writing files",
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    payload = _read_manifest(manifest_path)
    repository = payload["upstream"]["repository"]
    commit = args.commit or payload["upstream"]["commit"]

    if args.checkout_dir is None:
        with tempfile.TemporaryDirectory(prefix="xcc-llvm-project-") as temp_dir:
            repo_dir = Path(temp_dir) / "llvm-project"
            _ensure_checkout(repo_dir, repository)
            _run_git(repo_dir, "fetch", "--depth", "1", "origin", commit)
            if args.check:
                return _run_check(payload=payload, repo_dir=repo_dir, commit=commit)
            _run_sync(payload=payload, manifest_path=manifest_path, repo_dir=repo_dir, commit=commit)
            return 0

    repo_dir = args.checkout_dir.resolve()
    _ensure_checkout(repo_dir, repository)
    _run_git(repo_dir, "fetch", "--depth", "1", "origin", commit)
    if args.check:
        return _run_check(payload=payload, repo_dir=repo_dir, commit=commit)
    _run_sync(payload=payload, manifest_path=manifest_path, repo_dir=repo_dir, commit=commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
