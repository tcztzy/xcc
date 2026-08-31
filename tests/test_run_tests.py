import importlib.util
import os
import subprocess
import sys
import tempfile
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
        self.assertEqual(args.timeout, 1800.0)

    def test_run_command_converts_timeout_to_reported_failure(self) -> None:
        runner = _load_run_tests_module()
        timeout = subprocess.TimeoutExpired(
            ("python", "-m", "unittest"),
            3,
            output="partial stdout",
            stderr="partial stderr",
        )

        with patch.object(runner.subprocess, "run", side_effect=timeout):
            result = runner._run_command(
                ("python", "-m", "unittest"),
                cwd=_repo_root(),
                env={},
                timeout=3,
            )

        self.assertEqual(result.returncode, 124)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.stdout, "partial stdout")
        self.assertIn("partial stderr", result.stderr)
        self.assertIn("timed out after 3s", result.stderr)

    def test_run_modules_forwards_timeout_to_each_test_process(self) -> None:
        runner = _load_run_tests_module()
        timeouts = []

        def fake_run(command, *, cwd, env, timeout):
            timeouts.append(timeout)
            return runner.CommandResult(tuple(command), 0, "", "")

        runner.run_modules(
            modules=["tests.test_lexer"],
            jobs=1,
            use_coverage=False,
            pythonpath=None,
            verbose=False,
            root=_repo_root(),
            timeout=42,
            run_command=fake_run,
        )

        self.assertEqual(timeouts, [42])

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

    def test_aot_v2_native_bootstrap_matrix_is_detached_from_coverage(self) -> None:
        runner = _load_run_tests_module()
        calls = []

        def fake_run_modules(**kwargs):
            calls.append(kwargs)
            return [runner.ModuleResult(module, (), 0, "", "", 0.0) for module in kwargs["modules"]]

        def fake_run_command(command, **_kwargs):
            return runner.CommandResult(tuple(command), 0, "", "")

        with (
            patch.object(runner, "run_modules", side_effect=fake_run_modules),
            patch.object(runner, "_run_command", side_effect=fake_run_command),
            patch.object(runner, "_print_module_result"),
        ):
            status = runner.main(
                [
                    "--coverage",
                    "tests.test_aot_bootstrap",
                ]
            )

        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0]["use_coverage"])
        self.assertEqual(calls[0]["modules"], ["tests.test_aot_bootstrap"])
        self.assertEqual(
            calls[0]["base_env"]["XCC_SKIP_NATIVE_BOOTSTRAP_TESTS"],
            "1",
        )
        self.assertFalse(calls[1]["use_coverage"])
        self.assertEqual(
            calls[1]["modules"],
            ["tests.test_aot_bootstrap.AotBootstrapNativeBuildTests"],
        )
        self.assertNotIn("XCC_SKIP_NATIVE_BOOTSTRAP_TESTS", calls[1]["base_env"])

if __name__ == "__main__":
    unittest.main()
