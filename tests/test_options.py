import unittest

from tests import _bootstrap  # noqa: F401
from xcc.options import FrontendOptions, normalize_options


class FrontendOptionsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        options = FrontendOptions()
        self.assertEqual(options.std, "c11")
        self.assertTrue(options.hosted)
        self.assertEqual(options.include_dirs, ())
        self.assertEqual(options.quote_include_dirs, ())
        self.assertEqual(options.system_include_dirs, ())
        self.assertEqual(options.after_include_dirs, ())
        self.assertEqual(options.forced_includes, ())
        self.assertEqual(options.macro_includes, ())
        self.assertEqual(options.defines, ())
        self.assertEqual(options.undefs, ())
        self.assertFalse(options.no_standard_includes)
        self.assertEqual(options.diag_format, "human")
        self.assertFalse(options.warn_as_error)
        self.assertIsNone(options.target_os)

    def test_invalid_standard(self) -> None:
        with self.assertRaises(ValueError):
            FrontendOptions(std="c99")  # type: ignore[arg-type]

    def test_invalid_diag_format(self) -> None:
        with self.assertRaises(ValueError):
            FrontendOptions(diag_format="xml")  # type: ignore[arg-type]

    def test_invalid_target_os(self) -> None:
        with self.assertRaises(ValueError):
            FrontendOptions(target_os="plan9")  # type: ignore[arg-type]

    def test_normalize_options(self) -> None:
        normalized = normalize_options(None)
        self.assertEqual(normalized, FrontendOptions())
        options = FrontendOptions(std="gnu11", hosted=False)
        self.assertIs(normalize_options(options), options)

    def test_normalize_options_preserves_every_field_and_is_idempotent(self) -> None:
        options = FrontendOptions(
            std="gnu11",
            hosted=False,
            include_dirs=("include",),
            quote_include_dirs=("quote",),
            system_include_dirs=("system",),
            after_include_dirs=("after",),
            forced_includes=("forced.h",),
            macro_includes=("macros.h",),
            defines=("VALUE=1",),
            undefs=("OLD_VALUE",),
            embed_dirs=("embed",),
            no_standard_includes=True,
            diag_format="json",
            warn_as_error=True,
            host_machine="x86_64",
            target_os="linux",
            strip_gnu_asm_statements=False,
        )

        normalized = normalize_options(options)

        self.assertIs(normalized, options)
        self.assertIs(normalize_options(normalized), normalized)


if __name__ == "__main__":
    unittest.main()
