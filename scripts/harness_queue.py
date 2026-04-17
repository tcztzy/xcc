#!/usr/bin/env python3
import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TODO = ROOT / "TODO.md"
_VALID_STATUSES = {"todo", "claimed", "review", "done", "blocked"}
_REQUIRED_FIELDS = {"layer", "family", "subsystem", "status"}
_LAYER_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_STALE_LOCK_SECONDS = 300.0


@dataclass(frozen=True)
class QueueEntry:
    task_id: str
    fields: dict[str, str]
    start_line: int
    end_line: int


def _queue_bounds(lines: list[str]) -> tuple[int, int]:
    start = -1
    for index, line in enumerate(lines):
        if line == "## Harness Queue":
            start = index + 1
            break
    if start < 0:
        raise ValueError("missing ## Harness Queue section")
    end = len(lines)
    for index in range(start, len(lines)):
        if index > start and lines[index].startswith("## "):
            end = index
            break
    return start, end


def _parse_entry(lines: list[str], start: int, end: int) -> QueueEntry:
    header = lines[start].strip()
    if not header.startswith("- `") or "`" not in header[3:]:
        raise ValueError(f"invalid queue item header: {header}")
    task_id = header.split("`", 2)[1]
    fields: dict[str, str] = {}
    for index in range(start + 1, end):
        line = lines[index]
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        key, _, value = stripped[2:].partition(":")
        if not _:
            continue
        value = value.strip()
        if value.startswith("`") and value.endswith("`") and value.count("`") == 2:
            value = value[1:-1]
        fields[key.strip()] = value
    missing = sorted(_REQUIRED_FIELDS - set(fields))
    if missing:
        raise ValueError(f"queue entry {task_id} missing required fields: {', '.join(missing)}")
    return QueueEntry(task_id=task_id, fields=fields, start_line=start, end_line=end)


def load_queue(todo_path: Path = DEFAULT_TODO) -> list[QueueEntry]:
    lines = todo_path.read_text(encoding="utf-8").splitlines()
    start, end = _queue_bounds(lines)
    entries: list[QueueEntry] = []
    seen_task_ids: set[str] = set()
    index = start
    while index < end:
        if lines[index].startswith("- `"):
            next_index = index + 1
            while next_index < end and not lines[next_index].startswith("- `"):
                next_index += 1
            entry = _parse_entry(lines, index, next_index)
            if entry.task_id in seen_task_ids:
                raise ValueError(f"duplicate queue entry: {entry.task_id}")
            seen_task_ids.add(entry.task_id)
            entries.append(entry)
            index = next_index
            continue
        index += 1
    return entries


def _replace_field(entry_lines: list[str], key: str, value: str) -> list[str]:
    rendered = f"`{value}`" if key in {"layer", "family", "subsystem", "expected_files", "verification", "status"} else value
    prefix = f"  - {key}:"
    for index, line in enumerate(entry_lines):
        if line.startswith(prefix):
            entry_lines[index] = f"{prefix} {rendered}"
            return entry_lines
    entry_lines.append(f"  - {key}: {rendered}")
    return entry_lines


def _rewrite_entry(todo_path: Path, entry: QueueEntry, updates: dict[str, str]) -> QueueEntry:
    lines = todo_path.read_text(encoding="utf-8").splitlines()
    entry_lines = lines[entry.start_line : entry.end_line]
    for key, value in updates.items():
        entry_lines = _replace_field(entry_lines, key, value)
    new_lines = lines[: entry.start_line] + entry_lines + lines[entry.end_line :]
    rendered = "\n".join(new_lines) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=todo_path.parent,
        prefix=f"{todo_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(rendered)
        temp_path = Path(handle.name)
    temp_path.replace(todo_path)
    for candidate in load_queue(todo_path):
        if candidate.task_id == entry.task_id:
            return candidate
    raise ValueError(f"queue entry disappeared: {entry.task_id}")


def _find_entry(todo_path: Path, task_id: str) -> QueueEntry:
    for entry in load_queue(todo_path):
        if entry.task_id == task_id:
            return entry
    raise ValueError(f"unknown queue entry: {task_id}")


def _lock_path(todo_path: Path) -> Path:
    return todo_path.with_suffix(todo_path.suffix + ".lock")


def _read_lock_metadata(lock_path: Path) -> tuple[int, float] | None:
    if not lock_path.is_file():
        return None
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        pid_text, _, created_text = raw.partition(":")
        if not _:
            return None
        return int(pid_text), float(created_text)
    except (OSError, ValueError):
        return None


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _stale_lock(lock_path: Path) -> bool:
    metadata = _read_lock_metadata(lock_path)
    if metadata is None:
        return True
    pid, created_at = metadata
    if not _pid_is_alive(pid):
        return True
    return time.time() - created_at > _STALE_LOCK_SECONDS


def _acquire_lock(todo_path: Path, *, timeout_seconds: float = 5.0) -> int:
    deadline = time.monotonic() + timeout_seconds
    lock_path = _lock_path(todo_path)
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()}:{time.time()}".encode("utf-8"))
            return fd
        except FileExistsError:
            if _stale_lock(lock_path):
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"queue lock busy: {lock_path}")
            time.sleep(0.05)


def _release_lock(todo_path: Path, fd: int) -> None:
    os.close(fd)
    _lock_path(todo_path).unlink(missing_ok=True)


def claim_entry(todo_path: Path, task_id: str, *, owner: str | None = None) -> QueueEntry:
    fd = _acquire_lock(todo_path)
    try:
        entry = _find_entry(todo_path, task_id)
        if entry.fields.get("status") != "todo":
            raise ValueError(f"entry is not claimable: {task_id}")
        notes = entry.fields.get("notes", "")
        if owner:
            note = f"claimed by {owner}"
            notes = note if not notes else f"{notes}; {note}"
        updates = {"status": "claimed"}
        if notes:
            updates["notes"] = notes
        return _rewrite_entry(todo_path, entry, updates)
    finally:
        _release_lock(todo_path, fd)


def set_status(todo_path: Path, task_id: str, status: str) -> QueueEntry:
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    fd = _acquire_lock(todo_path)
    try:
        entry = _find_entry(todo_path, task_id)
        return _rewrite_entry(todo_path, entry, {"status": status})
    finally:
        _release_lock(todo_path, fd)


def next_claimable(todo_path: Path = DEFAULT_TODO) -> QueueEntry | None:
    candidates = [entry for entry in load_queue(todo_path) if entry.fields.get("status") == "todo"]
    if not candidates:
        return None
    candidates.sort(
        key=lambda entry: (
            _LAYER_ORDER.get(entry.fields.get("layer", ""), 99),
            entry.task_id,
        )
    )
    return candidates[0]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--todo-path", type=Path, default=DEFAULT_TODO)

    claim_parser = subparsers.add_parser("claim")
    claim_parser.add_argument("task_id")
    claim_parser.add_argument("--owner")
    claim_parser.add_argument("--todo-path", type=Path, default=DEFAULT_TODO)

    status_parser = subparsers.add_parser("set-status")
    status_parser.add_argument("task_id")
    status_parser.add_argument("status")
    status_parser.add_argument("--todo-path", type=Path, default=DEFAULT_TODO)

    next_parser = subparsers.add_parser("next")
    next_parser.add_argument("--todo-path", type=Path, default=DEFAULT_TODO)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "list":
        print(json.dumps([entry.fields | {"id": entry.task_id} for entry in load_queue(args.todo_path)]))
        return 0
    if args.command == "claim":
        entry = claim_entry(args.todo_path, args.task_id, owner=args.owner)
        print(json.dumps(entry.fields | {"id": entry.task_id}))
        return 0
    if args.command == "set-status":
        entry = set_status(args.todo_path, args.task_id, args.status)
        print(json.dumps(entry.fields | {"id": entry.task_id}))
        return 0
    entry = next_claimable(args.todo_path)
    print(json.dumps(None if entry is None else entry.fields | {"id": entry.task_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
