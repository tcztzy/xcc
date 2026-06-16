import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_validation_module():
    path = _repo_root() / "scripts" / "validate_compiler.py"
    spec = importlib.util.spec_from_file_location("validate_compiler", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ValidationScriptTests(unittest.TestCase):
    def test_default_xcc_command_runs_current_source_tree(self) -> None:
        validate = _load_validation_module()

        command = validate._default_xcc_command()

        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1], "-c")
        self.assertIn("from xcc import main", command[2])

    def test_differential_case_compares_xcc_and_clang_execution(self) -> None:
        validate = _load_validation_module()
        calls: list[list[str]] = []

        def fake_run(command, *, cwd=None, env=None, timeout=None):
            calls.append(list(command))
            executable = Path(command[-1])
            if executable.name in {"xcc.out", "clang.out"}:
                executable.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
                executable.chmod(0o755)
            return validate.CommandResult(tuple(command), 0, "", "")

        case = validate.ProgramCase("returns-seven", "int main(void){return 7;}")
        with tempfile.TemporaryDirectory() as tmp:
            results = validate._run_program_case(
                case,
                work_root=Path(tmp),
                xcc_command=("xcc",),
                clang_command=("clang",),
                run=fake_run,
                timeout=3.0,
                env={},
            )

        self.assertEqual(results.status, "ok")
        self.assertTrue(any(call[:2] == ["xcc", "--target=llvm"] for call in calls))
        self.assertTrue(any(call[0] == "clang" for call in calls))
        self.assertEqual(results.details, "returncode=7 stdout='' stderr=''")

    def test_boundary_case_requires_expected_failure(self) -> None:
        validate = _load_validation_module()

        def fake_run(command, *, cwd=None, env=None, timeout=None):
            return validate.CommandResult(tuple(command), 1, "", "Invalid alignof operand\n")

        case = validate.BoundaryCase(
            "c11-alignof-expression",
            ("--target=llvm", "-std=c11", "-S"),
            "int f(void){int x; return _Alignof(x);}",
            "Invalid alignof operand",
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = validate._run_boundary_case(
                case,
                work_root=Path(tmp),
                xcc_command=("xcc",),
                run=fake_run,
                timeout=3.0,
                env={},
            )

        self.assertEqual(result.status, "ok")
        self.assertIn("rejected with", result.details)


if __name__ == "__main__":
    unittest.main()
