import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from scripts import agent_worktree


class AgentWorktreeTests(unittest.TestCase):
    def test_branch_and_worktree_path_use_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                agent_worktree.branch_name("clang-p0-types-001"),
                "codex/clang-p0-types-001",
            )
            self.assertEqual(
                agent_worktree.worktree_path("clang-p0-types-001", worktree_root=root),
                root / "clang-p0-types-001",
            )

    def test_invalid_task_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            agent_worktree.branch_name("../bad")

    @patch("scripts.agent_worktree._run_git")
    def test_create_worktree_calls_git_with_branch(self, run_git: unittest.mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = agent_worktree.create_worktree(
                "clang-p0-types-001",
                worktree_root=root,
                base_ref="master",
            )
        self.assertEqual(result.branch, "codex/clang-p0-types-001")
        self.assertEqual(result.path, root / "clang-p0-types-001")
        run_git.assert_called_once_with(
            [
                "worktree",
                "add",
                str(root / "clang-p0-types-001"),
                "-b",
                "codex/clang-p0-types-001",
                "master",
            ],
            repo_root=agent_worktree.ROOT,
        )

    @patch("scripts.agent_worktree._run_git")
    def test_remove_worktree_prunes_and_deletes_branch(self, run_git: unittest.mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            info = agent_worktree.WorktreeInfo(
                task_id="clang-p0-types-001",
                branch="codex/clang-p0-types-001",
                path=root / "clang-p0-types-001",
            )
            agent_worktree.remove_worktree(info)
        self.assertEqual(
            run_git.call_args_list,
            [
                unittest.mock.call(
                    ["worktree", "remove", str(root / "clang-p0-types-001")],
                    repo_root=agent_worktree.ROOT,
                ),
                unittest.mock.call(["worktree", "prune"], repo_root=agent_worktree.ROOT),
                unittest.mock.call(
                    ["branch", "-D", "codex/clang-p0-types-001"],
                    repo_root=agent_worktree.ROOT,
                ),
            ],
        )

    @patch("scripts.agent_worktree._run_git")
    def test_merge_branch_uses_no_ff_merge(self, run_git: unittest.mock.Mock) -> None:
        run_git.side_effect = [
            unittest.mock.Mock(stdout="master\n"),
            unittest.mock.Mock(stdout=""),
            unittest.mock.Mock(stdout=""),
            unittest.mock.Mock(stdout=""),
        ]
        agent_worktree.merge_branch("codex/clang-p0-types-001", target_branch="master")
        self.assertEqual(
            run_git.call_args_list,
            [
                unittest.mock.call(["branch", "--show-current"], repo_root=agent_worktree.ROOT),
                unittest.mock.call(["status", "--short"], repo_root=agent_worktree.ROOT),
                unittest.mock.call(["checkout", "master"], repo_root=agent_worktree.ROOT),
                unittest.mock.call(
                    ["merge", "--no-ff", "--no-edit", "codex/clang-p0-types-001"],
                    repo_root=agent_worktree.ROOT,
                ),
            ],
        )

    @patch("scripts.agent_worktree._run_git")
    def test_merge_branch_rejects_implementation_dirtiness(self, run_git: unittest.mock.Mock) -> None:
        run_git.side_effect = [
            unittest.mock.Mock(stdout="master\n"),
            unittest.mock.Mock(stdout=" M src/xcc/sema/__init__.py\n"),
        ]
        with self.assertRaises(RuntimeError):
            agent_worktree.merge_branch("codex/clang-p0-types-001", target_branch="master")

    @patch("scripts.agent_worktree._run_git")
    def test_merge_branch_rejects_todo_dirtiness(self, run_git: unittest.mock.Mock) -> None:
        run_git.side_effect = [
            unittest.mock.Mock(stdout="master\n"),
            unittest.mock.Mock(stdout=" M TODO.md\n"),
        ]
        with self.assertRaises(RuntimeError):
            agent_worktree.merge_branch("codex/clang-p0-types-001", target_branch="master")

    @patch("scripts.agent_worktree._run_git")
    def test_merge_branch_allows_other_metadata_on_target_branch(self, run_git: unittest.mock.Mock) -> None:
        run_git.side_effect = [
            unittest.mock.Mock(stdout="master\n"),
            unittest.mock.Mock(stdout=" M HARNESS.md\n M CHANGELOG.md\n"),
            unittest.mock.Mock(stdout=""),
            unittest.mock.Mock(stdout=""),
        ]
        agent_worktree.merge_branch("codex/clang-p0-types-001", target_branch="master")
        self.assertEqual(
            run_git.call_args_list,
            [
                unittest.mock.call(["branch", "--show-current"], repo_root=agent_worktree.ROOT),
                unittest.mock.call(["status", "--short"], repo_root=agent_worktree.ROOT),
                unittest.mock.call(["checkout", "master"], repo_root=agent_worktree.ROOT),
                unittest.mock.call(
                    ["merge", "--no-ff", "--no-edit", "codex/clang-p0-types-001"],
                    repo_root=agent_worktree.ROOT,
                ),
            ],
        )
