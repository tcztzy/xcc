import unittest

from xcc.llvm_api import optional_zero_ptr_array, ptr_array, zero_ptr_array


class LLVMApiTests(unittest.TestCase):
    def test_ptr_array_preserves_pointer_values(self) -> None:
        arr = ptr_array([11, 22, 33])

        self.assertEqual(len(arr), 3)
        self.assertEqual([arr[i] for i in range(3)], [11, 22, 33])

    def test_zero_ptr_array_allocates_mutable_null_pointer_array(self) -> None:
        arr = zero_ptr_array(2)

        self.assertEqual(len(arr), 2)
        self.assertEqual([arr[i] for i in range(2)], [None, None])
        arr[1] = 99
        self.assertEqual(arr[1], 99)

    def test_optional_zero_ptr_array_uses_none_for_empty_llvm_arrays(self) -> None:
        self.assertIsNone(optional_zero_ptr_array(0))
        self.assertEqual(len(optional_zero_ptr_array(2)), 2)


if __name__ == "__main__":
    unittest.main()
