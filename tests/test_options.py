import unittest

from tests import _bootstrap  # noqa: F401
from xcc.options import FrontendOptions, normalize_options


class FrontendOptionsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        options = FrontendOptions()
        self.assertEqual(options.std, "c11")
        self.assertEqual(options.include_dirs, ())
        self.assertEqual(options.quote_include_dirs, ())
        self.assertEqual(options.system_include_dirs, ())
        self.assertEqual(options.defines, ())
        self.assertEqual(options.undefs, ())
        self.assertEqual(options.diag_format, "human")
        self.assertFalse(options.warn_as_error)

    def test_invalid_standard(self) -> None:
        with self.assertRaises(ValueError):
            FrontendOptions(std="c99")  # type: ignore[arg-type]

    def test_invalid_diag_format(self) -> None:
        with self.assertRaises(ValueError):
            FrontendOptions(diag_format="xml")  # type: ignore[arg-type]

    def test_normalize_options(self) -> None:
        normalized = normalize_options(None)
        self.assertEqual(normalized, FrontendOptions())
        options = FrontendOptions(std="gnu11")
        self.assertIs(normalize_options(options), options)


if __name__ == "__main__":
    unittest.main()
