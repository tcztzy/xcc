import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from scripts import harness_queue

_SAMPLE_TODO = """# TODO

## Harness Queue

- `clang-p0-types-001`
  - layer: `P0`
  - family: `types-and-conversions`
  - subsystem: `sema`
  - targets: current failures
  - expected_files: `src/xcc/sema/**`
  - verification: `uv run tox -e py311`
  - status: `todo`
  - notes: core layer

- `clang-p2-pp-001`
  - layer: `P2`
  - family: `macro-and-include-edges`
  - subsystem: `preprocessor`
  - targets: current failures
  - expected_files: `src/xcc/preprocessor/**`
  - verification: `uv run tox -e py311`
  - status: `todo`
  - notes: safe parallel candidate
"""


class HarnessQueueTests(unittest.TestCase):
    def test_load_queue_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            state_path = Path(tmp) / ".worktrees" / "harness" / "tasks.json"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            entries = harness_queue.load_queue(todo_path, state_path)
        self.assertEqual([entry.task_id for entry in entries], ["clang-p0-types-001", "clang-p2-pp-001"])
        self.assertEqual(entries[0].fields["layer"], "P0")
        self.assertEqual(entries[1].fields["status"], "todo")

    def test_claim_entry_writes_state_file_without_mutating_todo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            state_path = Path(tmp) / ".worktrees" / "harness" / "tasks.json"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            original_text = todo_path.read_text(encoding="utf-8")
            updated = harness_queue.claim_entry(todo_path, "clang-p0-types-001", owner="worker-b", state_path=state_path)
            text = todo_path.read_text(encoding="utf-8")
            state = state_path.read_text(encoding="utf-8")
        self.assertEqual(updated.fields["status"], "claimed")
        self.assertEqual(updated.fields["owner"], "worker-b")
        self.assertEqual(text, original_text)
        self.assertIn('"status": "claimed"', state)
        self.assertIn('"owner": "worker-b"', state)

    def test_claim_entry_rejects_non_todo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            state_path = Path(tmp) / ".worktrees" / "harness" / "tasks.json"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            harness_queue.set_status(todo_path, "clang-p2-pp-001", "review", state_path=state_path)
            with self.assertRaises(ValueError):
                harness_queue.claim_entry(todo_path, "clang-p2-pp-001", owner="worker-c", state_path=state_path)

    def test_set_status_updates_state_file_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            state_path = Path(tmp) / ".worktrees" / "harness" / "tasks.json"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            original_text = todo_path.read_text(encoding="utf-8")
            updated = harness_queue.set_status(todo_path, "clang-p0-types-001", "review", state_path=state_path)
            text = todo_path.read_text(encoding="utf-8")
            state = state_path.read_text(encoding="utf-8")
        self.assertEqual(updated.fields["status"], "review")
        self.assertEqual(text, original_text)
        self.assertIn('"status": "review"', state)

    def test_set_status_to_base_status_clears_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            state_path = Path(tmp) / ".worktrees" / "harness" / "tasks.json"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            harness_queue.claim_entry(todo_path, "clang-p0-types-001", owner="worker-b", state_path=state_path)
            updated = harness_queue.set_status(todo_path, "clang-p0-types-001", "todo", state_path=state_path)
            entries = harness_queue.load_queue(todo_path, state_path)
            state = state_path.read_text(encoding="utf-8")
        self.assertEqual(updated.fields["status"], "todo")
        self.assertNotIn("owner", updated.fields)
        self.assertEqual(entries[0].fields["status"], "todo")
        self.assertNotIn('clang-p0-types-001', state)

    def test_next_claimable_prefers_lowest_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            state_path = Path(tmp) / ".worktrees" / "harness" / "tasks.json"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            next_entry = harness_queue.next_claimable(todo_path, state_path)
        self.assertIsNotNone(next_entry)
        self.assertEqual(next_entry.task_id, "clang-p0-types-001")

    def test_load_queue_rejects_duplicate_ids(self) -> None:
        duplicated = _SAMPLE_TODO + _SAMPLE_TODO.split("## Harness Queue\n", 1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            state_path = Path(tmp) / ".worktrees" / "harness" / "tasks.json"
            todo_path.write_text(duplicated, encoding="utf-8")
            with self.assertRaises(ValueError):
                harness_queue.load_queue(todo_path, state_path)

    def test_load_queue_applies_state_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            state_path = Path(tmp) / ".worktrees" / "harness" / "tasks.json"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                '{"version": 1, "tasks": {"clang-p2-pp-001": {"status": "claimed", "owner": "worker-z"}}}\n',
                encoding="utf-8",
            )
            entries = harness_queue.load_queue(todo_path, state_path)
        self.assertEqual(entries[1].fields["status"], "claimed")
        self.assertEqual(entries[1].fields["owner"], "worker-z")

    def test_acquire_lock_reaps_stale_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / ".worktrees" / "harness" / "tasks.json"
            lock_path = state_path.with_suffix(".json.lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text("999999:0", encoding="utf-8")
            fd = harness_queue._acquire_lock(state_path, timeout_seconds=0.1)
            harness_queue._release_lock(state_path, fd)
            self.assertFalse(lock_path.exists())
