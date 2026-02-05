import io
import unittest
from contextlib import redirect_stdout

from tests import _bootstrap  # noqa: F401
from xcc import main


class CliTests(unittest.TestCase):
    def test_main_output(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main()
        self.assertIn("Hello", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
