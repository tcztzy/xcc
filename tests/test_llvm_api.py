import unittest
from unittest.mock import patch

import xcc.llvm_api as llvm_api
from xcc.llvm_api import optional_zero_ptr_array, ptr_array, zero_ptr_array


class _FakeLLVMFunction:
    def __init__(self) -> None:
        self.restype: object | None = None
        self.argtypes: tuple[object, ...] = ()


class _FakeLLVMLibrary:
    def __init__(self) -> None:
        self.lookups: list[str] = []
        self.function = _FakeLLVMFunction()

    def __getitem__(self, name: str) -> _FakeLLVMFunction:
        self.lookups.append(name)
        return self.function


class LLVMApiTests(unittest.TestCase):
    def test_llvm_loader_uses_discovered_library(self) -> None:
        sentinel = object()
        with (
            patch("xcc.llvm_api.find_libllvm", return_value="/toolchain/lib/libLLVM.so"),
            patch("xcc.llvm_api.ctypes.CDLL", return_value=sentinel) as load,
        ):
            self.assertIs(llvm_api._load_llvm(), sentinel)
        load.assert_called_once_with("/toolchain/lib/libLLVM.so")

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

    def test_get_aggregate_element_reads_const_array_entries(self) -> None:
        c = llvm_api.llvm()
        values = zero_ptr_array(2)
        values[0] = c.ConstInt(c.Int8Type(), 4, False)
        values[1] = c.ConstInt(c.Int8Type(), 7, False)
        const_array = c.ConstArray(c.Int8Type(), values, 2)

        first = c.GetAggregateElement(const_array, 0)
        second = c.GetAggregateElement(const_array, 1)

        self.assertEqual(c.ConstIntGetZExtValue(first), 4)
        self.assertEqual(c.ConstIntGetZExtValue(second), 7)

    def test_llvm_loader_reuses_cached_library(self) -> None:
        sentinel = object()
        previous = llvm_api._LLVM_STATE.library
        llvm_api._LLVM_STATE.library = sentinel  # type: ignore[assignment]
        try:
            self.assertIs(llvm_api._llvm(), sentinel)
        finally:
            llvm_api._LLVM_STATE.library = previous

    def test_llvm_api_reuses_cached_binding_wrapper(self) -> None:
        sentinel = object()
        previous = llvm_api._LLVM_STATE.api
        llvm_api._LLVM_STATE.api = sentinel  # type: ignore[assignment]
        try:
            self.assertIs(llvm_api.llvm(), sentinel)
        finally:
            llvm_api._LLVM_STATE.api = previous

    def test_bind_uses_library_symbol_lookup(self) -> None:
        library = _FakeLLVMLibrary()
        wrapper = llvm_api._LLVMC(library)  # type: ignore[arg-type]

        function = wrapper._bind("LLVMExample", int, str, bytes)

        self.assertIs(function, library.function)
        self.assertEqual(library.lookups, ["LLVMExample"])
        self.assertIs(library.function.restype, int)
        self.assertEqual(library.function.argtypes, (str, bytes))


if __name__ == "__main__":
    unittest.main()
