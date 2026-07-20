import importlib.util
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_run_tests_module():
    path = _repo_root() / "scripts" / "run_tests.py"
    spec = importlib.util.spec_from_file_location("run_tests", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RunTestsScriptTests(unittest.TestCase):
    def test_default_worker_count_is_serial(self) -> None:
        runner = _load_run_tests_module()

        with patch.dict(os.environ, {}, clear=True):
            args = runner._build_arg_parser().parse_args([])

        self.assertEqual(runner._parse_jobs(args.jobs), 1)

    def test_discover_test_modules_returns_importable_sorted_names(self) -> None:
        runner = _load_run_tests_module()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests = root / "tests"
            nested = tests / "sub"
            nested.mkdir(parents=True)
            (tests / "__init__.py").write_text("", encoding="utf-8")
            (tests / "test_b.py").write_text("", encoding="utf-8")
            (tests / "test_a.py").write_text("", encoding="utf-8")
            (nested / "test_c.py").write_text("", encoding="utf-8")

            modules = runner.discover_test_modules(root=root, start_dir=tests)

        self.assertEqual(modules, ["tests.sub.test_c", "tests.test_a", "tests.test_b"])

    def test_build_module_command_uses_coverage_parallel_mode(self) -> None:
        runner = _load_run_tests_module()

        command = runner.build_module_command(
            module="tests.test_lexer",
            use_coverage=True,
            verbose=True,
        )

        self.assertEqual(
            command,
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--parallel-mode",
                "-m",
                "unittest",
                "-v",
                "tests.test_lexer",
            ],
        )

    def test_run_modules_prepends_pythonpath_for_subprocesses(self) -> None:
        runner = _load_run_tests_module()
        calls = []

        def fake_run(command, *, cwd, env):
            calls.append((command, cwd, env))
            return runner.CommandResult(tuple(command), 0, "stdout", "stderr")

        results = runner.run_modules(
            modules=["tests.test_lexer"],
            jobs=1,
            use_coverage=False,
            pythonpath=Path("/tmp/xcc-compiled/lib"),
            verbose=False,
            root=_repo_root(),
            run_command=fake_run,
        )

        self.assertEqual(results[0].returncode, 0)
        self.assertEqual(calls[0][0][-1], "tests.test_lexer")
        self.assertEqual(
            calls[0][2]["PYTHONPATH"].split(os.pathsep)[0],
            "/tmp/xcc-compiled/lib",
        )

    def test_run_modules_preserves_isolated_coverage_file_for_workers(self) -> None:
        runner = _load_run_tests_module()
        calls = []

        def fake_run(command, *, cwd, env):
            calls.append((command, cwd, env))
            return runner.CommandResult(tuple(command), 0, "", "")

        runner.run_modules(
            modules=["tests.test_lexer"],
            jobs=1,
            use_coverage=True,
            pythonpath=None,
            verbose=False,
            root=_repo_root(),
            base_env={"COVERAGE_FILE": "/tmp/xcc-coverage/.coverage"},
            run_command=fake_run,
        )

        self.assertEqual(calls[0][2]["COVERAGE_FILE"], "/tmp/xcc-coverage/.coverage")

    def test_coverage_report_command_can_require_100_percent(self) -> None:
        runner = _load_run_tests_module()

        command = runner.coverage_report_command(fail_under=100)

        self.assertEqual(
            command,
            [sys.executable, "-m", "coverage", "report", "--fail-under", "100"],
        )


class GateConfigTests(unittest.TestCase):
    def test_tox_test_envs_use_serial_coverage_runner(self) -> None:
        config = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))

        env_run_base = config["tool"]["tox"]["env_run_base"]
        commands = env_run_base["commands"]

        self.assertEqual(env_run_base["dependency_groups"], ["dev"])
        self.assertEqual(commands[0][:2], ["python", "scripts/run_tests.py"])
        self.assertIn("--coverage", commands[0])
        self.assertEqual(commands[0][-2:], ["--jobs", "1"])

        mypyc_command = config["tool"]["tox"]["env"]["mypyc"]["commands"][1]
        self.assertEqual(mypyc_command[-2:], ["--jobs", "1"])

    def test_coverage_report_uses_current_ratchet(self) -> None:
        config = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(config["tool"]["coverage"]["report"]["fail_under"], 94.76)

    def test_coverage_report_preserves_decimal_ratchet_precision(self) -> None:
        config = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertGreaterEqual(config["tool"]["coverage"]["report"]["precision"], 1)

    def test_pre_commit_runs_test_lint_and_type_gates(self) -> None:
        text = (_repo_root() / ".pre-commit-config.yaml").read_text(encoding="utf-8")

        self.assertIn("id: xcc-test-gate", text)
        self.assertIn("entry: uv run tox -e py311", text)
        self.assertIn("id: xcc-lint-gate", text)
        self.assertIn("entry: uv run tox -e lint", text)
        self.assertIn("id: xcc-type-gate", text)
        self.assertIn("entry: uv run tox -e type", text)

    def test_ci_uses_same_tox_test_gate_as_local_handoff(self) -> None:
        text = (_repo_root() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("uv run tox -e py311", text)
        self.assertNotIn("python -m unittest discover", text)


if __name__ == "__main__":
    unittest.main()
