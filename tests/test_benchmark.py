import importlib.util
import io
import json
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_benchmark_module():
    path = _repo_root() / "scripts" / "benchmark_xcc.py"
    spec = importlib.util.spec_from_file_location("benchmark_xcc", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BenchmarkToxConfigTests(unittest.TestCase):
    def test_tox_defines_interpreter_benchmark_matrix(self) -> None:
        config = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
        envs = config["tool"]["tox"]["env"]
        expected = {
            "bench-py311": ("python3.11", "pure", "py311"),
            "bench-py312": ("python3.12", "pure", "py312"),
            "bench-py313": ("python3.13", "pure", "py313"),
            "bench-py314": ("python3.14", "pure", "py314"),
            "bench-pypy311": ("pypy3.11", "pure", "pypy311"),
            "bench-graalpy311": ("graalpy3.11", "pure", "graalpy311"),
            "bench-graalpy312": ("graalpy3.12", "pure", "graalpy312"),
            "bench-cython": ("python3.11", "cython", "cython"),
            "bench-mypyc": ("python3.11", "mypyc", "mypyc"),
        }

        for name, (base_python, variant, label) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, envs)
                env = envs[name]
                self.assertEqual(env["runner"], "uv-venv-lock-runner")
                self.assertEqual(env["package"], "skip")
                self.assertEqual(env["base_python"], [base_python])
                if variant == "pure":
                    self.assertTrue(env["no_default_groups"])
                command = env["commands"][0]
                self.assertIn("scripts/benchmark_xcc.py", command)
                self.assertEqual(command[command.index("--variant") + 1], variant)
                self.assertEqual(command[command.index("--label") + 1], label)

    def test_tox_defines_first_tier_mypyc_test_gate(self) -> None:
        config = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
        env = config["tool"]["tox"]["env"]["mypyc"]

        self.assertEqual(env["runner"], "uv-venv-lock-runner")
        self.assertEqual(env["dependency_groups"], ["dev"])
        self.assertEqual(env["package"], "skip")
        self.assertEqual(env["base_python"], ["python3.11"])
        self.assertIn("scripts/mypycize_xcc.py", env["commands"][0])
        self.assertIn("--clean", env["commands"][0])
        self.assertIn("--force", env["commands"][0])
        self.assertIn("scripts/run_tests.py", env["commands"][1])
        self.assertIn("--pythonpath", env["commands"][1])
        self.assertIn("build/mypyc/lib", env["commands"][1])


class BenchmarkScriptTests(unittest.TestCase):
    def test_main_writes_labeled_pure_json_without_building_extensions(self) -> None:
        benchmark = _load_benchmark_module()

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out_tmp:
            cpython_root = Path(tmp)
            (cpython_root / "pyconfig.h").write_text("", encoding="utf-8")
            source = cpython_root / "Objects" / "listobject.c"
            source.parent.mkdir()
            source.write_text("int value;\n", encoding="utf-8")
            output = Path(out_tmp) / "bench.json"
            calls = []

            def fake_run_variant(*, python, variant, jobs, warmups, runs):
                calls.append((python, variant, jobs, warmups, runs))
                return benchmark.VariantResult(variant.name, (0.125,))

            with (
                patch.object(benchmark, "_run_variant", fake_run_variant),
                redirect_stdout(
                    io.StringIO(),
                ),
            ):
                code = benchmark.main(
                    [
                        "--cpython",
                        str(cpython_root),
                        "--source",
                        "Objects/listobject.c",
                        "--variant",
                        "pure",
                        "--label",
                        "py311",
                        "--runs",
                        "1",
                        "--warmups",
                        "0",
                        "--json",
                        str(output),
                        "",
                    ],
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1].name, "py311")
        self.assertEqual(calls[0][1].kind, "pure")
        self.assertEqual(payload["runs"]["py311"]["variant"], "pure")
        self.assertEqual(payload["runs"]["py311"]["python"], sys.executable)
        self.assertEqual(payload["runs"]["py311"]["times"], [0.125])

    def test_main_splits_tox_posargs_collapsed_into_one_argument(self) -> None:
        benchmark = _load_benchmark_module()

        with tempfile.TemporaryDirectory() as tmp:
            cpython_root = Path(tmp)
            (cpython_root / "pyconfig.h").write_text("", encoding="utf-8")
            source = cpython_root / "Objects" / "listobject.c"
            source.parent.mkdir()
            source.write_text("int value;\n", encoding="utf-8")
            run_args = []

            def fake_run_variant(*, python, variant, jobs, warmups, runs):
                run_args.append((jobs, warmups, runs))
                return benchmark.VariantResult(variant.name, (0.25,))

            with (
                patch.object(benchmark, "_run_variant", fake_run_variant),
                redirect_stdout(io.StringIO()),
            ):
                code = benchmark.main(
                    [
                        "--cpython",
                        str(cpython_root),
                        "--variant",
                        "pure",
                        "--source Objects/listobject.c --runs 1 --warmups 0",
                    ],
                )

        self.assertEqual(code, 0)
        self.assertEqual(run_args[0][1:], (0, 1))
        self.assertEqual(Path(run_args[0][0][0][-1]).resolve(), source.resolve())

    def test_all_variant_combines_pure_cython_and_mypyc_import_trees(self) -> None:
        benchmark = _load_benchmark_module()

        with tempfile.TemporaryDirectory() as tmp:
            cpython_root = Path(tmp)
            (cpython_root / "pyconfig.h").write_text("", encoding="utf-8")
            source = cpython_root / "Objects" / "listobject.c"
            source.parent.mkdir()
            source.write_text("int value;\n", encoding="utf-8")
            build_calls = []
            run_names = []

            def fake_build_import_tree(kind, *, python, args):
                build_calls.append((kind, python, args))
                return cpython_root / f"{kind}-lib"

            def fake_run_variant(*, python, variant, jobs, warmups, runs):
                run_names.append(variant.name)
                return benchmark.VariantResult(variant.name, (float(len(run_names)),))

            with (
                patch.object(benchmark, "_build_import_tree", fake_build_import_tree),
                patch.object(benchmark, "_run_variant", fake_run_variant),
                redirect_stdout(io.StringIO()),
            ):
                code = benchmark.main(
                    [
                        "--cpython",
                        str(cpython_root),
                        "--source",
                        "Objects/listobject.c",
                        "--variant",
                        "all",
                        "--runs",
                        "1",
                        "--warmups",
                        "0",
                    ],
                )

        self.assertEqual(code, 0)
        self.assertEqual([call[0] for call in build_calls], ["cython", "mypyc"])
        self.assertEqual(run_names, ["pure", "cython", "mypyc"])


if __name__ == "__main__":
    unittest.main()
