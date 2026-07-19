import importlib.util
import io
import os
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_cpython_build_module():
    path = _repo_root() / "scripts" / "validate_cpython_build.py"
    spec = importlib.util.spec_from_file_location("validate_cpython_build", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CPythonBuildScriptTests(unittest.TestCase):
    def test_default_make_parallelism_is_serial(self) -> None:
        validate = _load_cpython_build_module()

        args = validate._build_arg_parser().parse_args([])

        self.assertEqual(args.jobs, 1)

    def test_build_commands_use_clean_out_of_tree_configure_and_make(self) -> None:
        validate = _load_cpython_build_module()
        env = {"PATH": os.environ.get("PATH", "")}
        args = validate.BuildOptions(
            cpython_root=Path("/src/cpython"),
            build_dir=Path("/tmp/cpython-build"),
            cc="xcc",
            jobs=4,
            pythonpath=(Path("/tmp/mypyc/lib"),),
            configure_args=("--with-pydebug",),
            make_args=("profile-opt",),
            skip_configure=False,
            keep_going=True,
            timeout=60.0,
        )

        steps = validate.build_steps(args, base_env=env, llc=Path("/opt/homebrew/opt/llvm/bin/llc"))

        self.assertEqual(steps[0].command, ("/src/cpython/configure", "--with-pydebug"))
        self.assertEqual(steps[0].cwd, Path("/tmp/cpython-build"))
        self.assertEqual(steps[0].env["CC"], "xcc")
        self.assertEqual(steps[0].env["PYTHONPATH"], "/tmp/mypyc/lib")
        self.assertEqual(steps[0].env["XCC_LLC"], "/opt/homebrew/opt/llvm/bin/llc")
        self.assertEqual(steps[1].command, ("make", "-j4", "-k", "profile-opt"))
        self.assertEqual(steps[1].cwd, Path("/tmp/cpython-build"))

    def test_skip_configure_runs_only_make(self) -> None:
        validate = _load_cpython_build_module()
        args = validate.BuildOptions(
            cpython_root=Path("/src/cpython"),
            build_dir=Path("/tmp/cpython-build"),
            cc="xcc",
            jobs=1,
            pythonpath=(),
            configure_args=(),
            make_args=(),
            skip_configure=True,
            keep_going=False,
            timeout=None,
        )

        steps = validate.build_steps(args, base_env={}, llc=None)

        self.assertEqual([step.command for step in steps], [("make", "-j1")])

    def test_default_cc_prefers_current_python_environment_xcc(self) -> None:
        validate = _load_cpython_build_module()

        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            python = bin_dir / "python"
            xcc = bin_dir / "xcc"
            xcc.write_text("#!/bin/sh\n", encoding="utf-8")

            with (
                patch.object(validate.sys, "executable", str(python)),
                patch.object(validate.shutil, "which", return_value="/old/bin/xcc"),
            ):
                cc = validate.default_cc()

        self.assertEqual(cc, str(xcc))

    def test_main_executes_steps_in_order(self) -> None:
        validate = _load_cpython_build_module()
        calls = []

        def fake_run(step):
            calls.append(step.command)
            return validate.CommandResult(step.command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            cpython = Path(tmp) / "cpython"
            cpython.mkdir()
            (cpython / "configure").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = validate.main(
                    [
                        "--cpython",
                        str(cpython),
                        "--build-dir",
                        str(Path(tmp) / "build"),
                        "--jobs",
                        "2",
                    ],
                    run_step=fake_run,
                )

        self.assertEqual(code, 0)
        self.assertEqual(calls, [(str(cpython.resolve() / "configure"),), ("make", "-j2")])

    def test_main_prepends_pythonpath_for_mypyc_acceleration(self) -> None:
        validate = _load_cpython_build_module()
        seen_pythonpath = []

        def fake_run(step):
            seen_pythonpath.append(step.env.get("PYTHONPATH"))
            return validate.CommandResult(step.command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            cpython = Path(tmp) / "cpython"
            mypyc_lib = Path(tmp) / "mypyc-lib"
            existing_pythonpath = str(Path(tmp) / "existing-pythonpath")
            cpython.mkdir()
            mypyc_lib.mkdir()
            (cpython / "configure").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            with (
                patch.dict(validate.os.environ, {"PYTHONPATH": existing_pythonpath}, clear=True),
                redirect_stdout(io.StringIO()),
            ):
                code = validate.main(
                    [
                        "--cpython",
                        str(cpython),
                        "--build-dir",
                        str(Path(tmp) / "build"),
                        "--pythonpath",
                        str(mypyc_lib),
                    ],
                    run_step=fake_run,
                )

        self.assertEqual(code, 0)
        expected_pythonpath = os.pathsep.join((str(mypyc_lib.resolve()), existing_pythonpath))
        self.assertEqual(seen_pythonpath, [expected_pythonpath, expected_pythonpath])

    def test_main_can_build_native_aot_cc_before_cpython_steps(self) -> None:
        validate = _load_cpython_build_module()
        calls = []

        def fake_build_native(root, output, *, llc=None, cc="cc"):
            calls.append(("build_native", root, output, llc, cc))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            return output

        def fake_run(step):
            calls.append(("run", step.command, step.env["CC"]))
            return validate.CommandResult(step.command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            cpython = Path(tmp) / "cpython"
            cpython.mkdir()
            (cpython / "configure").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            with (
                patch.object(validate, "build_native_bootstrap", fake_build_native),
                redirect_stdout(io.StringIO()),
            ):
                code = validate.main(
                    [
                        "--cpython",
                        str(cpython),
                        "--build-dir",
                        str(Path(tmp) / "build"),
                        "--native-aot-cc",
                        str(Path(tmp) / "native-xcc"),
                    ],
                    run_step=fake_run,
                )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0][0], "build_native")
        self.assertEqual(calls[1][0], "run")
        self.assertEqual(calls[1][2], str((Path(tmp) / "native-xcc").resolve()))

    def test_main_rejects_parallel_native_aot_validation(self) -> None:
        validate = _load_cpython_build_module()

        with self.assertRaisesRegex(
            SystemExit,
            "--native-aot-cc requires --jobs 1",
        ):
            validate.main(
                [
                    "--native-aot-cc",
                    "/tmp/native-xcc",
                    "--jobs",
                    "2",
                ]
            )


class CPythonBuildToxConfigTests(unittest.TestCase):
    def test_tox_defines_explicit_cpython_build_gate(self) -> None:
        config = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))

        env = config["tool"]["tox"]["env"]["cpython-build"]
        mypyc_command = env["commands"][0]
        command = env["commands"][1]

        self.assertEqual(env["runner"], "uv-venv-lock-runner")
        self.assertNotEqual(env.get("package"), "skip")
        self.assertIn("scripts/mypycize_xcc.py", mypyc_command)
        self.assertIn("scripts/validate_cpython_build.py", command)
        self.assertIn("--clean", command)
        self.assertIn("--pythonpath", command)
        self.assertIn("build/mypyc/lib", command)
        self.assertIn("--cpython", command)
        self.assertIn("{posargs:../cpython}", command)


if __name__ == "__main__":
    unittest.main()
