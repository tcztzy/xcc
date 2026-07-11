import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    IrCall,
    IrConstInt,
    IrConstString,
    IrFunction,
    IrIntType,
    IrModule,
    IrRaise,
    IrReturn,
    IrSourceSpan,
    analyze_fallibility,
    emit_llvm_text,
)


class AotStatusAnalysisTests(unittest.TestCase):
    def test_fallibility_propagates_through_project_call_graph(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "status.py",
            (),
            (
                IrFunction(
                    "leaf",
                    (),
                    int64,
                    (
                        IrRaise(
                            "ValueError",
                            IrConstString("bad"),
                            IrSourceSpan(4, 8, 4, 31),
                        ),
                    ),
                ),
                IrFunction(
                    "middle",
                    (),
                    int64,
                    (IrReturn(IrCall("leaf", (), int64)),),
                ),
                IrFunction(
                    "entry",
                    (),
                    int64,
                    (IrReturn(IrCall("middle", (), int64)),),
                ),
                IrFunction(
                    "constant",
                    (),
                    int64,
                    (IrReturn(IrConstInt(0, int64)),),
                ),
            ),
            entry="entry",
        )

        self.assertEqual(analyze_fallibility(module), frozenset({"leaf", "middle", "entry"}))


class AotStatusLlvmTests(unittest.TestCase):
    def test_internal_raise_uses_status_result_error_abi(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "status.py",
            (),
            (
                IrFunction(
                    "leaf",
                    (),
                    int64,
                    (
                        IrRaise(
                            "ValueError",
                            IrConstString("bad"),
                            IrSourceSpan(4, 8, 4, 31),
                        ),
                    ),
                ),
                IrFunction(
                    "middle",
                    (),
                    int64,
                    (IrReturn(IrCall("leaf", (), int64)),),
                ),
                IrFunction(
                    "entry",
                    (),
                    int64,
                    (IrReturn(IrCall("middle", (), int64)),),
                ),
            ),
            entry="entry",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn(
            "%__xcc_aot_error = type { ptr, ptr, ptr, i32, i32, i32, i32, ptr }",
            llvm_ir,
        )
        self.assertIn("define i32 @leaf(ptr %result_out, ptr %error_out)", llvm_ir)
        self.assertIn("define i32 @middle(ptr %result_out, ptr %error_out)", llvm_ir)
        self.assertNotIn("declare void @exit(i32)", llvm_ir)
        self.assertNotIn("call void @exit(i32 2)", llvm_ir)
        self.assertRegex(
            llvm_ir,
            r"%callstatus\d+ = call i32 @leaf\(ptr %callresult\d+, ptr %error_out\)",
        )
        self.assertRegex(llvm_ir, r"store ptr @\.str\d+, ptr %errortype\d+")
        self.assertRegex(llvm_ir, r"store i32 4, ptr %errorline\d+")
        self.assertRegex(llvm_ir, r"store i32 8, ptr %errorcolumn\d+")
        self.assertRegex(llvm_ir, r"store i32 4, ptr %errorendline\d+")
        self.assertRegex(llvm_ir, r"store i32 31, ptr %errorendcolumn\d+")

    def test_only_main_translates_uncaught_error_to_process_status(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "uncaught.py",
            (),
            (
                IrFunction(
                    "entry",
                    (),
                    int64,
                    (
                        IrRaise(
                            "RuntimeError",
                            IrConstString("boom"),
                            IrSourceSpan(2, 4, 2, 30),
                        ),
                    ),
                ),
            ),
            entry="entry",
        )

        llvm_ir = emit_llvm_text(module)
        function_body = re.search(r"define i32 @entry\(.*?\n}\n", llvm_ir, re.DOTALL)
        main_body = re.search(r"define i32 @main\(.*?\n}\n?", llvm_ir, re.DOTALL)

        self.assertIsNotNone(function_body)
        self.assertIsNotNone(main_body)
        assert function_body is not None
        assert main_body is not None
        self.assertNotIn("dprintf", function_body.group())
        self.assertIn(
            "call i32 (i32, ptr, ...) @dprintf(i32 2",
            main_body.group(),
        )
        self.assertIn("ret i32 %status", main_body.group())

    def test_uncaught_status_module_passes_llc(self) -> None:
        int64 = IrIntType(64, signed=True)
        module = IrModule(
            "llc-status.py",
            (),
            (
                IrFunction(
                    "entry",
                    (),
                    int64,
                    (
                        IrRaise(
                            "ValueError",
                            IrConstString("bad"),
                            IrSourceSpan(1, 0, 1, 23),
                        ),
                    ),
                ),
            ),
            entry="entry",
        )
        llvm_ir = emit_llvm_text(module)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "status.ll"
            output = root / "status.o"
            source.write_text(llvm_ir, encoding="utf-8")
            result = subprocess.run(
                (
                    "/opt/homebrew/opt/llvm/bin/llc",
                    "-filetype=obj",
                    str(source),
                    "-o",
                    str(output),
                ),
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
