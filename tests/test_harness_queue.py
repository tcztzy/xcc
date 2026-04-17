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
  - status: `claimed`
  - notes: claimed by worker-a
"""


class HarnessQueueTests(unittest.TestCase):
    def test_load_queue_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            entries = harness_queue.load_queue(todo_path)
        self.assertEqual([entry.task_id for entry in entries], ["clang-p0-types-001", "clang-p2-pp-001"])
        self.assertEqual(entries[0].fields["layer"], "P0")
        self.assertEqual(entries[1].fields["status"], "claimed")

    def test_claim_entry_updates_status_and_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            updated = harness_queue.claim_entry(todo_path, "clang-p0-types-001", owner="worker-b")
            text = todo_path.read_text(encoding="utf-8")
        self.assertEqual(updated.fields["status"], "claimed")
        self.assertIn("status: `claimed`", text)
        self.assertIn("claimed by worker-b", text)

    def test_claim_entry_rejects_non_todo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            with self.assertRaises(ValueError):
                harness_queue.claim_entry(todo_path, "clang-p2-pp-001", owner="worker-c")

    def test_set_status_rewrites_target_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            updated = harness_queue.set_status(todo_path, "clang-p0-types-001", "review")
            text = todo_path.read_text(encoding="utf-8")
        self.assertEqual(updated.fields["status"], "review")
        self.assertIn("status: `review`", text)

    def test_next_claimable_prefers_lowest_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            next_entry = harness_queue.next_claimable(todo_path)
        self.assertIsNotNone(next_entry)
        self.assertEqual(next_entry.task_id, "clang-p0-types-001")

    def test_load_queue_rejects_duplicate_ids(self) -> None:
        duplicated = _SAMPLE_TODO + _SAMPLE_TODO.split("## Harness Queue\n", 1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            todo_path.write_text(duplicated, encoding="utf-8")
            with self.assertRaises(ValueError):
                harness_queue.load_queue(todo_path)

    def test_acquire_lock_reaps_stale_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            todo_path = Path(tmp) / "TODO.md"
            todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
            lock_path = todo_path.with_suffix(".md.lock")
            lock_path.write_text("999999:0", encoding="utf-8")
            fd = harness_queue._acquire_lock(todo_path, timeout_seconds=0.1)
            harness_queue._release_lock(todo_path, fd)
            self.assertFalse(lock_path.exists())
