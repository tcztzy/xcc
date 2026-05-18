import tempfile
import unittest
from collections.abc import Callable, Iterable
from pathlib import Path
from unittest.mock import patch

from scripts import cpython_trial

from tests import _bootstrap  # noqa: F401


class CPythonTrialHelperTests(unittest.TestCase):
    def test_parse_jobs_accepts_auto_and_positive_counts(self) -> None:
        self.assertEqual(cpython_trial.parse_jobs("1"), 1)
        self.assertEqual(cpython_trial.parse_jobs("3"), 3)
        self.assertGreaterEqual(cpython_trial.parse_jobs("auto"), 1)

    def test_parse_jobs_rejects_non_positive_counts(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            cpython_trial.parse_jobs("0")
        with self.assertRaisesRegex(ValueError, "positive"):
            cpython_trial.parse_jobs("-2")

    def test_run_compiles_in_file_order_when_parallel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "Python"
            source_dir.mkdir()
            first = source_dir / "alpha.c"
            second = source_dir / "beta.c"
            first.write_text("int alpha;", encoding="utf-8")
            second.write_text("int beta;", encoding="utf-8")

            def fake_compile(
                _root: Path, file_path: Path
            ) -> tuple[bool, str, str, int | None, int | None]:
                message = f"compiled {file_path.name}"
                return True, "ok", message, None, None

            workers: list[int] = []

            class FakePool:
                def __init__(self, max_workers: int, **_kwargs: object) -> None:
                    workers.append(max_workers)

                def __enter__(self) -> "FakePool":
                    return self

                def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                    return None

                def map(
                    self,
                    func: Callable[[tuple[Path, Path]], dict],
                    items: Iterable[tuple[Path, Path]],
                ) -> list[dict]:
                    return [func(item) for item in items]

            with (
                patch("scripts.cpython_trial.compile_file", side_effect=fake_compile),
                patch("scripts.cpython_trial.ProcessPoolExecutor", FakePool),
            ):
                data = cpython_trial.run(root, core_only=True, jobs=2)

        self.assertEqual(workers, [2])
        self.assertEqual(data["passed"], 2)
        self.assertEqual(data["failed"], 0)
        self.assertEqual(data["stages"], {"ok": 2})
        self.assertEqual(
            [(r["path"], r["message"]) for r in data["results"]],
            [("Python/alpha.c", "compiled alpha.c"), ("Python/beta.c", "compiled beta.c")],
        )

    def test_run_rejects_invalid_job_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "positive"):
            cpython_trial.run(Path(tmp), jobs=0)
