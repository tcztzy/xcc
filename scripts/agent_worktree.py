#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKTREE_ROOT = ROOT / ".worktrees"
_TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
_ALLOWED_METADATA_DIRTY_PATHS = {"HARNESS.md", "CHANGELOG.md"}


@dataclass(frozen=True)
class WorktreeInfo:
    task_id: str
    branch: str
    path: Path


def _assert_task_id(task_id: str) -> None:
    if not _TASK_ID_RE.fullmatch(task_id):
        raise ValueError(f"invalid task id: {task_id}")


def branch_name(task_id: str, *, prefix: str = "codex") -> str:
    _assert_task_id(task_id)
    return f"{prefix}/{task_id}"


def worktree_path(task_id: str, *, worktree_root: Path = DEFAULT_WORKTREE_ROOT) -> Path:
    _assert_task_id(task_id)
    return worktree_root / task_id


def _run_git(args: list[str], *, repo_root: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def _current_branch() -> str:
    return _run_git(["branch", "--show-current"], repo_root=ROOT).stdout.strip()


def _dirty_paths() -> list[str]:
    output = _run_git(["status", "--short"], repo_root=ROOT).stdout
    paths: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        paths.append(line[3:])
    return paths


def _assert_merge_safe(target_branch: str) -> None:
    current_branch = _current_branch()
    dirty_paths = _dirty_paths()
    blocked_paths = [path for path in dirty_paths if path not in _ALLOWED_METADATA_DIRTY_PATHS]
    if blocked_paths:
        raise RuntimeError(f"supervisor root has implementation dirtiness: {blocked_paths}")
    if current_branch != target_branch and dirty_paths:
        raise RuntimeError(
            f"cannot switch from {current_branch} to {target_branch} with dirty supervisor metadata"
        )


def create_worktree(
    task_id: str,
    *,
    worktree_root: Path = DEFAULT_WORKTREE_ROOT,
    base_ref: str = "HEAD",
    prefix: str = "codex",
) -> WorktreeInfo:
    branch = branch_name(task_id, prefix=prefix)
    path = worktree_path(task_id, worktree_root=worktree_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_git(["worktree", "add", str(path), "-b", branch, base_ref], repo_root=ROOT)
    return WorktreeInfo(task_id=task_id, branch=branch, path=path)


def remove_worktree(info: WorktreeInfo, *, delete_branch: bool = True) -> None:
    _run_git(["worktree", "remove", str(info.path)], repo_root=ROOT)
    _run_git(["worktree", "prune"], repo_root=ROOT)
    if delete_branch:
        _run_git(["branch", "-D", info.branch], repo_root=ROOT)


def merge_branch(branch: str, *, target_branch: str = "master") -> None:
    _assert_merge_safe(target_branch)
    _run_git(["checkout", target_branch], repo_root=ROOT)
    _run_git(["merge", "--no-ff", "--no-edit", branch], repo_root=ROOT)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("task_id")
    create.add_argument("--base-ref", default="HEAD")
    create.add_argument("--prefix", default="codex")
    create.add_argument("--worktree-root", type=Path, default=DEFAULT_WORKTREE_ROOT)

    remove = subparsers.add_parser("remove")
    remove.add_argument("task_id")
    remove.add_argument("--prefix", default="codex")
    remove.add_argument("--worktree-root", type=Path, default=DEFAULT_WORKTREE_ROOT)
    remove.add_argument("--keep-branch", action="store_true")

    merge = subparsers.add_parser("merge")
    merge.add_argument("task_id")
    merge.add_argument("--prefix", default="codex")
    merge.add_argument("--target-branch", default="master")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "create":
        info = create_worktree(
            args.task_id,
            worktree_root=args.worktree_root,
            base_ref=args.base_ref,
            prefix=args.prefix,
        )
        print(json.dumps({"task_id": info.task_id, "branch": info.branch, "path": str(info.path)}))
        return 0
    if args.command == "remove":
        info = WorktreeInfo(
            task_id=args.task_id,
            branch=branch_name(args.task_id, prefix=args.prefix),
            path=worktree_path(args.task_id, worktree_root=args.worktree_root),
        )
        remove_worktree(info, delete_branch=not args.keep_branch)
        print(json.dumps(asdict(info), default=str))
        return 0
    merge_branch(branch_name(args.task_id, prefix=args.prefix), target_branch=args.target_branch)
    print(json.dumps({"task_id": args.task_id, "branch": branch_name(args.task_id, prefix=args.prefix)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
