#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import agent_worktree, clang_frontier, harness_queue

DEFAULT_TODO = ROOT / "TODO.md"
DEFAULT_STATE = ROOT / ".worktrees" / "harness" / "tasks.json"
DEFAULT_MANIFEST = ROOT / "tests" / "external" / "clang" / "manifest.json"
_DEFAULT_OWNER = "supervisor"


def _blocked_payload(summary: str, blocked_reason: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "result": "BLOCKED",
        "summary": summary,
        "blocked_reason": blocked_reason,
    }
    payload.update(extra)
    return payload


def _failed_payload(summary: str, failed_reason: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "result": "FAILED",
        "summary": summary,
        "failed_reason": failed_reason,
    }
    payload.update(extra)
    return payload


def _stale_active_state_task_ids(todo_path: Path, state_path: Path) -> list[str]:
    todo_task_ids = {entry.task_id for entry in harness_queue._base_queue(todo_path)}
    state = harness_queue._load_state_file(state_path)
    return sorted(
        task_id
        for task_id, task_state in state.items()
        if task_state.get("status") in {"claimed", "review"} and task_id not in todo_task_ids
    )


def _run_git(args: list[str], *, repo_root: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _status_paths(output: str) -> list[str]:
    paths: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        if len(line) > 3:
            paths.append(line[3:])
            continue
        paths.append(line)
    return paths


def _worktree_task_id(path: Path, *, repo_root: Path) -> str | None:
    worktree_root = repo_root / ".worktrees"
    try:
        relative = path.relative_to(worktree_root)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) != 1 or not parts[0]:
        return None
    return parts[0]


def _parse_worktree_list(output: str, *, repo_root: Path) -> list[dict[str, object]]:
    blocks = [block for block in output.strip().split("\n\n") if block.strip()]
    worktrees: list[dict[str, object]] = []
    for block in blocks:
        metadata: dict[str, object] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if not _:
                continue
            metadata[key] = value
        raw_path = metadata.get("worktree")
        if not isinstance(raw_path, str):
            continue
        path = Path(raw_path)
        metadata["path"] = path
        metadata["task_id"] = _worktree_task_id(path, repo_root=repo_root)
        worktrees.append(metadata)
    return worktrees


def _frontier_index(manifest_path: Path) -> dict[tuple[str, str, str], dict[str, object]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    frontier = clang_frontier.build_frontier(payload)
    index: dict[tuple[str, str, str], dict[str, object]] = {}
    for item in frontier:
        key = (str(item["layer"]), str(item["family"]), str(item["subsystem"]))
        index[key] = item
    return index


def _select_ready_entry(
    entries: list[harness_queue.QueueEntry],
    frontier: dict[tuple[str, str, str], dict[str, object]],
    primary_entry: harness_queue.QueueEntry | None,
) -> tuple[harness_queue.QueueEntry | None, dict[str, object] | None]:
    ordered = sorted(
        (entry for entry in entries if entry.fields.get("status") == "todo"),
        key=lambda entry: (
            harness_queue._LAYER_ORDER.get(entry.fields.get("layer", ""), 99),
            entry.task_id,
        ),
    )
    if not ordered:
        return None, None
    if primary_entry is not None:
        key = (
            primary_entry.fields.get("layer", ""),
            primary_entry.fields.get("family", ""),
            primary_entry.fields.get("subsystem", ""),
        )
        matched = frontier.get(key)
        if matched is not None:
            return primary_entry, matched
    for entry in ordered:
        key = (entry.fields.get("layer", ""), entry.fields.get("family", ""), entry.fields.get("subsystem", ""))
        matched = frontier.get(key)
        if matched is not None:
            return entry, matched
    if primary_entry is not None:
        return primary_entry, None
    return ordered[0], None


def _selected_payload(
    entry: harness_queue.QueueEntry,
    frontier_item: dict[str, object] | None,
) -> dict[str, object]:
    payload: dict[str, object] = {"id": entry.task_id}
    payload.update(entry.fields)
    if frontier_item is None:
        payload["frontier_slice_id"] = None
        payload["frontier_case_count"] = 0
        payload["frontier_case_ids"] = []
        return payload
    payload["frontier_slice_id"] = frontier_item["slice_id"]
    payload["frontier_case_count"] = frontier_item["count"]
    payload["frontier_case_ids"] = list(frontier_item["case_ids"])
    return payload


def supervise(
    *,
    repo_root: Path = ROOT,
    todo_path: Path = DEFAULT_TODO,
    state_path: Path = DEFAULT_STATE,
    manifest_path: Path = DEFAULT_MANIFEST,
    claim: bool = False,
    owner: str = _DEFAULT_OWNER,
) -> dict[str, object]:
    dirty_root_paths = _status_paths(_run_git(["status", "--short"], repo_root=repo_root))
    blocked_root_paths = [
        path for path in dirty_root_paths if path not in agent_worktree._ALLOWED_METADATA_DIRTY_PATHS
    ]
    if blocked_root_paths:
        return _blocked_payload(
            "supervisor root has implementation dirtiness",
            "dirty_root",
            dirty_root_paths=blocked_root_paths,
            orphan_worktrees=[],
        )

    stale_active_state_task_ids = _stale_active_state_task_ids(todo_path, state_path)
    if stale_active_state_task_ids:
        return _blocked_payload(
            "queue state contains claimed or review task ids missing from TODO",
            "stale_active_state",
            stale_active_state_task_ids=stale_active_state_task_ids,
            orphan_worktrees=[],
        )

    entries = harness_queue.load_queue(todo_path, state_path)
    active_task_ids = sorted(
        entry.task_id for entry in entries if entry.fields.get("status") in {"claimed", "review"}
    )
    worktrees = _parse_worktree_list(_run_git(["worktree", "list", "--porcelain"], repo_root=repo_root), repo_root=repo_root)

    matched_active: set[str] = set()
    orphan_worktrees: list[str] = []
    dirty_orphan_worktrees: list[dict[str, str]] = []
    for worktree in worktrees:
        path = worktree["path"]
        if not isinstance(path, Path):
            continue
        if path == repo_root:
            continue
        task_id = worktree.get("task_id")
        if task_id in active_task_ids:
            matched_active.add(str(task_id))
            continue
        dirty_paths = _status_paths(_run_git(["-C", str(path), "status", "--short"], repo_root=repo_root))
        if dirty_paths:
            dirty_orphan_worktrees.append({"path": str(path), "task_id": str(task_id or "")})
            continue
        orphan_worktrees.append(str(path))

    if dirty_orphan_worktrees:
        return _blocked_payload(
            "dirty orphan worktrees require manual cleanup",
            "dirty_orphan_worktree",
            dirty_orphan_worktrees=dirty_orphan_worktrees,
            orphan_worktrees=sorted(orphan_worktrees),
        )

    missing_active_worktrees = sorted(task_id for task_id in active_task_ids if task_id not in matched_active)
    if missing_active_worktrees:
        return _blocked_payload(
            "claimed or review tasks are missing worktrees",
            "active_worktree_mismatch",
            missing_active_worktrees=missing_active_worktrees,
            orphan_worktrees=sorted(orphan_worktrees),
        )

    frontier = _frontier_index(manifest_path)
    primary_entry = harness_queue.next_claimable(todo_path, state_path)
    selected_entry, frontier_item = _select_ready_entry(entries, frontier, primary_entry)
    if selected_entry is None:
        return {
            "result": "IDLE",
            "summary": "no todo slice is ready",
            "blocked_reason": None,
            "orphan_worktrees": sorted(orphan_worktrees),
            "selected_task": None,
        }

    if claim:
        try:
            selected_entry = harness_queue.claim_entry(todo_path, selected_entry.task_id, owner=owner, state_path=state_path)
        except (TimeoutError, ValueError) as exc:
            return _blocked_payload(
                f"claim failed for {selected_entry.task_id}",
                "claim_conflict",
                claim_error=str(exc),
                orphan_worktrees=sorted(orphan_worktrees),
                selected_task=None,
            )
        except Exception as exc:
            return _failed_payload(
                f"claim raised unexpected error for {selected_entry.task_id}",
                "claim_error",
                claim_error=str(exc),
                orphan_worktrees=sorted(orphan_worktrees),
                selected_task=None,
            )
    selected_task = _selected_payload(selected_entry, frontier_item)
    return {
        "result": "SUCCESS",
        "summary": f"selected {selected_entry.task_id}",
        "blocked_reason": None,
        "orphan_worktrees": sorted(orphan_worktrees),
        "selected_task": selected_task,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--todo-path", type=Path, default=DEFAULT_TODO)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--claim", action="store_true")
    parser.add_argument("--owner", default=_DEFAULT_OWNER)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    payload = supervise(
        repo_root=args.repo_root,
        todo_path=args.todo_path,
        state_path=args.state_path,
        manifest_path=args.manifest_path,
        claim=args.claim,
        owner=args.owner,
    )
    print(json.dumps(payload, sort_keys=True))
    if payload["result"] == "BLOCKED":
        return 2
    if payload["result"] == "FAILED":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
