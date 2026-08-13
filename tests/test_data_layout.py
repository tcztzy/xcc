import unittest

from tests import _bootstrap  # noqa: F401
from xcc.data_layout import (
    DARWIN_AARCH64_DATA_LAYOUT,
    EVM_WORD_DATA_LAYOUT,
    GENERIC_LP64_DATA_LAYOUT,
    X86_64_DATA_LAYOUT,
    data_layout_for_target,
)


class TargetDataLayoutTests(unittest.TestCase):
    def test_common_scalar_layout_and_unknown_type(self) -> None:
        self.assertEqual(GENERIC_LP64_DATA_LAYOUT.scalar_size("int"), 4)
        self.assertEqual(GENERIC_LP64_DATA_LAYOUT.scalar_alignment("__int128"), 16)
        self.assertIsNone(GENERIC_LP64_DATA_LAYOUT.scalar_size("struct Missing"))
        self.assertIsNone(GENERIC_LP64_DATA_LAYOUT.scalar_alignment("struct Missing"))

    def test_long_double_layout_is_target_specific(self) -> None:
        self.assertEqual(DARWIN_AARCH64_DATA_LAYOUT.scalar_size("long double"), 8)
        self.assertEqual(DARWIN_AARCH64_DATA_LAYOUT.scalar_alignment("long double"), 8)
        self.assertEqual(X86_64_DATA_LAYOUT.scalar_size("long double"), 16)
        self.assertEqual(X86_64_DATA_LAYOUT.scalar_alignment("long double"), 16)

    def test_target_selection_normalizes_architecture_aliases(self) -> None:
        self.assertEqual(data_layout_for_target("darwin", "arm64"), DARWIN_AARCH64_DATA_LAYOUT)
        self.assertEqual(data_layout_for_target("darwin", "AARCH64"), DARWIN_AARCH64_DATA_LAYOUT)
        self.assertEqual(data_layout_for_target("linux", "amd64"), X86_64_DATA_LAYOUT)
        self.assertEqual(data_layout_for_target("linux", "X86_64"), X86_64_DATA_LAYOUT)
        self.assertEqual(data_layout_for_target(None, "evm"), EVM_WORD_DATA_LAYOUT)
        self.assertEqual(data_layout_for_target(None, None), GENERIC_LP64_DATA_LAYOUT)

    def test_evm_uses_word_sized_object_storage(self) -> None:
        self.assertEqual(EVM_WORD_DATA_LAYOUT.pointer_size, 32)
        self.assertEqual(EVM_WORD_DATA_LAYOUT.scalar_size("char"), 32)
        self.assertEqual(EVM_WORD_DATA_LAYOUT.scalar_size("int"), 32)
        self.assertEqual(EVM_WORD_DATA_LAYOUT.scalar_size("long double"), 32)
        self.assertEqual(EVM_WORD_DATA_LAYOUT.scalar_alignment("long double"), 32)
        self.assertEqual(EVM_WORD_DATA_LAYOUT.scalar_alignment("__evm_uint256"), 32)
        self.assertIsNone(EVM_WORD_DATA_LAYOUT.scalar_size("struct Missing"))
        self.assertIsNone(EVM_WORD_DATA_LAYOUT.scalar_alignment("struct Missing"))


if __name__ == "__main__":
    unittest.main()
