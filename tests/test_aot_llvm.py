import unittest

from tests import _bootstrap  # noqa: F401
from xcc.aot import emit_llvm_text, lower_source_to_ir


class AotLlvmTextTests(unittest.TestCase):
    def test_emits_int64_function_and_main_wrapper(self) -> None:
        module = lower_source_to_ir(
            "int64 = int\ndef answer() -> int64:\n    return 42\n",
            filename="scalar.py",
            entry="answer",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn("define i64 @answer()", llvm_ir)
        self.assertIn("ret i64 42", llvm_ir)
        self.assertIn("define i32 @main()", llvm_ir)
        self.assertIn("%result = call i64 @answer()", llvm_ir)
        self.assertIn("%exit = trunc i64 %result to i32", llvm_ir)

    def test_emits_string_return_with_puts_wrapper(self) -> None:
        module = lower_source_to_ir(
            'def message() -> str:\n    return "ok"\n',
            filename="string.py",
            entry="message",
        )
        llvm_ir = emit_llvm_text(module)
        self.assertIn('c"ok\\00"', llvm_ir)
        self.assertIn("declare i32 @puts(ptr)", llvm_ir)
        self.assertIn("%printed = call i32 @puts(ptr %result)", llvm_ir)

    def test_emits_record_type_and_method_call(self) -> None:
        source = (
            "from dataclasses import dataclass\n"
            "int64 = int\n"
            "@dataclass(frozen=True)\n"
            "class Pair:\n"
            "    left: int64\n"
            "    right: int64\n"
            "    def total(self) -> int64:\n"
            "        return self.left + self.right\n"
            "def entry() -> int64:\n"
            "    pair = Pair(2, 3)\n"
            "    return pair.total()\n"
        )
        llvm_ir = emit_llvm_text(lower_source_to_ir(source, filename="method.py", entry="entry"))
        self.assertIn("%Pair = type { i64, i64 }", llvm_ir)
        self.assertIn("define i64 @Pair.total(ptr %self)", llvm_ir)
        self.assertIn("call i64 @Pair.total(ptr %pair)", llvm_ir)


if __name__ == "__main__":
    unittest.main()
