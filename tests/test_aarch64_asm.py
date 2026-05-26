import unittest

from tests import _bootstrap  # noqa: F401
from xcc.aarch64_asm import generate_aarch64_asm
from xcc.diag import CodegenError
from xcc.frontend import compile_source


class AArch64AsmTests(unittest.TestCase):
    def _asm(self, source: str) -> str:
        return generate_aarch64_asm(compile_source(source, filename="test.c"))

    def test_emits_constant_return_function(self) -> None:
        asm = self._asm("int f(void){return 7;}")
        self.assertIn(".section __TEXT,__text,regular,pure_instructions", asm)
        self.assertIn(".globl _f\n_f:", asm)
        self.assertIn("    mov w0, #7", asm)
        self.assertIn("    ret", asm)
        self.assertNotIn("define i32", asm)

    def test_emits_params_locals_and_arithmetic(self) -> None:
        asm = self._asm("int add(int a, int b){ int c=a+b; return c*2; }")
        self.assertIn("    sub sp, sp, #16", asm)
        self.assertIn("    str w0, [sp, #0]", asm)
        self.assertIn("    str w1, [sp, #4]", asm)
        self.assertIn("    add w0, w9, w10", asm)
        self.assertIn("    str w0, [sp, #8]", asm)
        self.assertIn("    mul w0, w9, w10", asm)

    def test_shift_uses_result_register_width(self) -> None:
        asm = self._asm("int shift(int x, long y){ return x << y; }")
        self.assertIn("    lsl w0, w9, w10", asm)
        self.assertNotIn("lsl w0, x9, x10", asm)

    def test_rejects_control_flow_until_backend_supports_it(self) -> None:
        result = compile_source("int f(int x){ if (x) return 1; return 0; }", filename="test.c")
        with self.assertRaises(CodegenError) as caught:
            generate_aarch64_asm(result)
        self.assertIn("AArch64 target does not support IfStmt yet", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
