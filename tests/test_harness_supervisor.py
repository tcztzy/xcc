import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from scripts import harness_supervisor

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

_SAMPLE_MANIFEST = {
    "cases": [
        {
            "id": "clang-sema-int-conv",
            "upstream": "clang/test/Sema/int-conv.c",
            "expect": "ok",
            "skip_reason": "baseline skip: expected ok, got sema (incompatible integer conversion)",
        },
        {
            "id": "clang-pp-macro",
            "upstream": "clang/test/Preprocessor/macro.c",
            "expect": "ok",
            "skip_reason": "baseline skip: expected ok, got pp (macro expansion mismatch)",
        },
    ]
}


class HarnessSupervisorTests(unittest.TestCase):
    def _write_fixture_tree(self, root: Path) -> tuple[Path, Path, Path, Path]:
        repo_root = root / "repo"
        todo_path = repo_root / "TODO.md"
        state_path = repo_root / ".worktrees" / "harness" / "tasks.json"
        manifest_path = repo_root / "tests" / "external" / "clang" / "manifest.json"
        todo_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        todo_path.write_text(_SAMPLE_TODO, encoding="utf-8")
        state_path.write_text('{"version": 1, "tasks": {}}\n', encoding="utf-8")
        manifest_path.write_text(json.dumps(_SAMPLE_MANIFEST) + "\n", encoding="utf-8")
        return repo_root, todo_path, state_path, manifest_path

    def _run_git(self, dirty_root: str = "", worktree_list: str = "", dirty_paths: dict[str, str] | None = None):
        worktree_status = dict(dirty_paths or {})

        def fake_run_git(args: list[str], *, repo_root: Path | None = None) -> str:
            del repo_root
            if args == ["status", "--short"]:
                return dirty_root
            if args == ["worktree", "list", "--porcelain"]:
                return worktree_list
            if len(args) == 4 and args[:3] == ["-C", args[1], "status"] and args[3] == "--short":
                return worktree_status.get(args[1], "")
            self.fail(f"unexpected git call: {args}")

        return fake_run_git

    def test_supervisor_blocks_on_dirty_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(dirty_root=" M src/xcc/sema/type_resolution.py\n"),
            ):
                result = harness_supervisor.supervise(
                    repo_root=repo_root,
                    todo_path=todo_path,
                    state_path=state_path,
                    manifest_path=manifest_path,
                )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["blocked_reason"], "dirty_root")
        self.assertEqual(result["dirty_root_paths"], ["src/xcc/sema/type_resolution.py"])

    def test_supervisor_allows_metadata_only_dirty_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(
                    dirty_root=" M HARNESS.md\n M CHANGELOG.md\n",
                    worktree_list=f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/master\n\n",
                ),
            ):
                result = harness_supervisor.supervise(
                    repo_root=repo_root,
                    todo_path=todo_path,
                    state_path=state_path,
                    manifest_path=manifest_path,
                )
        self.assertEqual(result["result"], "SUCCESS")
        self.assertEqual(result["selected_task"]["id"], "clang-p0-types-001")

    def test_supervisor_blocks_when_claimed_task_has_matching_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            active_worktree = repo_root / ".worktrees" / "clang-p0-types-001"
            state_path.write_text(
                '{"version": 1, "tasks": {"clang-p0-types-001": {"status": "claimed", "owner": "worker-a"}}}\n',
                encoding="utf-8",
            )
            worktree_list = (
                f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/master\n\n"
                f"worktree {active_worktree}\nHEAD def\nbranch refs/heads/codex/clang-p0-types-001\n\n"
            )
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(worktree_list=worktree_list),
            ):
                result = harness_supervisor.supervise(
                    repo_root=repo_root,
                    todo_path=todo_path,
                    state_path=state_path,
                    manifest_path=manifest_path,
                )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["blocked_reason"], "active_task_in_progress")
        self.assertEqual(result["active_task_ids"], ["clang-p0-types-001"])
        self.assertEqual(result["selected_task"], None)

    def test_supervisor_blocks_when_claimed_task_has_no_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            state_path.write_text(
                '{"version": 1, "tasks": {"clang-p0-types-001": {"status": "claimed", "owner": "worker-a"}}}\n',
                encoding="utf-8",
            )
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(worktree_list=f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/master\n\n"),
            ):
                result = harness_supervisor.supervise(
                    repo_root=repo_root,
                    todo_path=todo_path,
                    state_path=state_path,
                    manifest_path=manifest_path,
                )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["blocked_reason"], "active_worktree_mismatch")
        self.assertEqual(result["missing_active_worktrees"], ["clang-p0-types-001"])

    def test_supervisor_blocks_on_stale_active_state_entry_missing_from_todo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            state_path.write_text(
                (
                    '{"version": 1, "tasks": {'
                    '"clang-p0-types-001": {"status": "claimed", "owner": "worker-a"}, '
                    '"clang-p9-missing-001": {"status": "review"}'
                    '}}\n'
                ),
                encoding="utf-8",
            )
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(worktree_list=f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/master\n\n"),
            ):
                result = harness_supervisor.supervise(
                    repo_root=repo_root,
                    todo_path=todo_path,
                    state_path=state_path,
                    manifest_path=manifest_path,
                )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["blocked_reason"], "stale_active_state")
        self.assertEqual(result["stale_active_state_task_ids"], ["clang-p9-missing-001"])

    def test_supervisor_reports_clean_orphans_and_selects_ready_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            orphan = repo_root / ".worktrees" / "orphan-task"
            worktree_list = (
                f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/master\n\n"
                f"worktree {orphan}\nHEAD def\nbranch refs/heads/codex/orphan-task\n\n"
            )
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(worktree_list=worktree_list),
            ):
                result = harness_supervisor.supervise(
                    repo_root=repo_root,
                    todo_path=todo_path,
                    state_path=state_path,
                    manifest_path=manifest_path,
                )
        self.assertEqual(result["result"], "SUCCESS")
        self.assertEqual(result["selected_task"]["id"], "clang-p0-types-001")
        self.assertEqual(result["selected_task"]["frontier_slice_id"], "clang-p0-types-and-conversions-sema")
        self.assertEqual(result["selected_task"]["frontier_case_count"], 1)
        self.assertEqual(result["orphan_worktrees"], [str(orphan)])

    def test_supervisor_blocks_on_dirty_orphan_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            orphan = repo_root / ".worktrees" / "orphan-task"
            worktree_list = (
                f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/master\n\n"
                f"worktree {orphan}\nHEAD def\nbranch refs/heads/codex/orphan-task\n\n"
            )
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(
                    worktree_list=worktree_list,
                    dirty_paths={str(orphan): " M tests/test_preprocessor.py\n"},
                ),
            ):
                result = harness_supervisor.supervise(
                    repo_root=repo_root,
                    todo_path=todo_path,
                    state_path=state_path,
                    manifest_path=manifest_path,
                )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["blocked_reason"], "dirty_orphan_worktree")
        self.assertEqual(result["dirty_orphan_worktrees"], [{"path": str(orphan), "task_id": "orphan-task"}])

    def test_supervisor_claims_selected_task_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(worktree_list=f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/master\n\n"),
            ):
                result = harness_supervisor.supervise(
                    repo_root=repo_root,
                    todo_path=todo_path,
                    state_path=state_path,
                    manifest_path=manifest_path,
                    claim=True,
                    owner="cron",
                )
            state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(result["result"], "SUCCESS")
        self.assertEqual(result["selected_task"]["status"], "claimed")
        self.assertEqual(result["selected_task"]["owner"], "cron")
        self.assertEqual(state["tasks"]["clang-p0-types-001"], {"status": "claimed", "owner": "cron"})

    def test_supervisor_reports_claim_conflict_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(worktree_list=f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/master\n\n"),
            ):
                with patch(
                    "scripts.harness_supervisor.harness_queue.claim_entry",
                    side_effect=ValueError("entry is not claimable: clang-p0-types-001"),
                ):
                    result = harness_supervisor.supervise(
                        repo_root=repo_root,
                        todo_path=todo_path,
                        state_path=state_path,
                        manifest_path=manifest_path,
                        claim=True,
                        owner="cron",
                    )
        self.assertEqual(result["result"], "BLOCKED")
        self.assertEqual(result["blocked_reason"], "claim_conflict")
        self.assertEqual(result["claim_error"], "entry is not claimable: clang-p0-types-001")

    def test_main_returns_failed_json_when_claim_raises_unexpected_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            stdout = io.StringIO()
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(worktree_list=f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/master\n\n"),
            ):
                with patch(
                    "scripts.harness_supervisor.harness_queue.claim_entry",
                    side_effect=RuntimeError("boom"),
                ):
                    with patch("sys.stdout", stdout):
                        code = harness_supervisor.main(
                            [
                                "--repo-root",
                                str(repo_root),
                                "--todo-path",
                                str(todo_path),
                                "--state-path",
                                str(state_path),
                                "--manifest-path",
                                str(manifest_path),
                                "--claim",
                            ]
                        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["result"], "FAILED")
        self.assertEqual(payload["failed_reason"], "claim_error")
        self.assertEqual(payload["claim_error"], "boom")

    def test_main_writes_stable_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, todo_path, state_path, manifest_path = self._write_fixture_tree(Path(tmp))
            stdout = io.StringIO()
            with patch(
                "scripts.harness_supervisor._run_git",
                side_effect=self._run_git(worktree_list=f"worktree {repo_root}\nHEAD abc\nbranch refs/heads/master\n\n"),
            ):
                with patch("sys.stdout", stdout):
                    code = harness_supervisor.main(
                        [
                            "--repo-root",
                            str(repo_root),
                            "--todo-path",
                            str(todo_path),
                            "--state-path",
                            str(state_path),
                            "--manifest-path",
                            str(manifest_path),
                        ]
                    )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["result"], "SUCCESS")
        self.assertEqual(payload["selected_task"]["id"], "clang-p0-types-001")
