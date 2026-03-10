import io
import platform
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc import main


@unittest.skipUnless(
    platform.system() == "Darwin" and platform.machine() == "arm64",
    "native smoke tests require macOS arm64",
)
class NativeBackendSmokeTests(unittest.TestCase):
    def _compile_and_run(self, source_text: str) -> tuple[int, str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "smoke.c"
            binary = root / "smoke"
            source.write_text(source_text, encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                compile_code = main([str(source), "--backend=xcc", "-o", str(binary)])
            if compile_code != 0:
                self.fail(f"native compile failed: {stderr.getvalue()}")
            completed = subprocess.run(
                (str(binary),),
                check=False,
                capture_output=True,
                text=True,
            )
        return completed.returncode, completed.stdout, completed.stderr

    def test_native_backend_smoke_matrix(self) -> None:
        cases = {
            "constant_return": (
                "int main(void) { return 0; }\n",
                0,
            ),
            "scalar_arithmetic": (
                "int main(void) { return 2 + 3 * 4; }\n",
                14,
            ),
            "assignment": (
                "int main(void) { int value = 1; value = value + 4; return value; }\n",
                5,
            ),
            "comparison": (
                "int main(void) { return (9 > 3) == 1; }\n",
                1,
            ),
            "if_else": (
                "int main(void) { int x = 0; if (4 > 1) { x = 7; } else { x = 1; } return x; }\n",
                7,
            ),
            "while": (
                "int main(void) { int i = 0; int sum = 0; while (i < 4) { sum = sum + i; i = i + 1; } return sum; }\n",
                6,
            ),
            "for": (
                "int main(void) { int i; int sum = 0; for (i = 0; i < 4; i = i + 1) { sum = sum + i; } return sum; }\n",
                6,
            ),
            "global_read_write": (
                "int counter = 1; int main(void) { counter = counter + 4; return counter; }\n",
                5,
            ),
            "internal_function_call": (
                "int add(int x, int y) { return x + y; } int main(void) { return add(2, 5); }\n",
                7,
            ),
            "external_libc_call": (
                'int puts(char *); int main(void) { return puts("hi") < 0; }\n',
                0,
            ),
        }
        for name, (source_text, expected) in cases.items():
            with self.subTest(case=name):
                returncode, _stdout, _stderr = self._compile_and_run(source_text)
                self.assertEqual(returncode, expected)


if __name__ == "__main__":
    unittest.main()
