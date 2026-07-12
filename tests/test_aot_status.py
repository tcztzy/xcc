import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc.aot import (
    IrBranch,
    IrCall,
    IrConstInt,
    IrConstString,
    IrExceptHandler,
    IrFunction,
    IrIntType,
    IrModule,
    IrRaise,
    IrReturn,
    IrSourceSpan,
    IrTry,
    analyze_fallibility,
    emit_llvm_text,
    lower_source_to_ir,
    run_native_smoke,
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

    def test_lowering_preserves_handlers_and_raise_span(self) -> None:
        module = lower_source_to_ir(
            "def fail() -> int:\n"
            "    raise ValueError('bad')\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return fail()\n"
            "    except ValueError:\n"
            "        return 7\n",
            filename="caught.py",
            entry="entry",
        )

        raised = module.functions[0].body[0]
        guarded = module.functions[1].body[0]
        self.assertEqual(
            raised,
            IrRaise(
                "ValueError",
                IrConstString("bad"),
                IrSourceSpan(2, 4, 2, 27),
                IrConstString("bad"),
            ),
        )
        self.assertIsInstance(guarded, IrTry)
        assert isinstance(guarded, IrTry)
        self.assertEqual(
            guarded.handlers,
            (
                IrExceptHandler(
                    ("ValueError",),
                    None,
                    guarded.handlers[0].body,
                ),
            ),
        )


class AotStatusNativeTests(unittest.TestCase):
    def test_matching_handler_catches_cross_call_error(self) -> None:
        result = run_native_smoke(
            "def fail() -> int:\n"
            "    raise ValueError('bad')\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return fail()\n"
            "    except ValueError:\n"
            "        return 7\n",
            filename="caught.py",
            entry="entry",
        )

        self.assertEqual(result.python_result, 7)
        self.assertEqual(result.native_returncode, 7)
        self.assertEqual(result.native_stdout, "")
        self.assertEqual(result.native_stderr, "")

    def test_matching_handler_and_finally_both_run(self) -> None:
        result = run_native_smoke(
            "def fail() -> int:\n"
            "    raise ValueError('bad')\n"
            "def entry() -> int:\n"
            "    result: int = 1\n"
            "    try:\n"
            "        fail()\n"
            "    except ValueError:\n"
            "        result = 2\n"
            "    finally:\n"
            "        result = result + 3\n"
            "    return result\n",
            filename="caught-finally.py",
            entry="entry",
        )

        self.assertEqual(result.python_result, 5)
        self.assertEqual(result.native_returncode, 5)
        self.assertEqual(result.native_stdout, "")
        self.assertEqual(result.native_stderr, "")

    def test_inner_finally_runs_before_outer_handler(self) -> None:
        result = run_native_smoke(
            "def fail() -> int:\n"
            "    raise ValueError('bad')\n"
            "def inner() -> int:\n"
            "    try:\n"
            "        return fail()\n"
            "    finally:\n"
            "        print('cleanup')\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return inner()\n"
            "    except ValueError:\n"
            "        return 9\n",
            filename="nested-finally.py",
            entry="entry",
        )

        self.assertEqual(result.python_result, 9)
        self.assertEqual(result.native_returncode, 9)
        self.assertEqual(result.native_stdout, "cleanup\n")
        self.assertEqual(result.native_stderr, "")

    def test_nonmatching_handler_propagates_to_outer_handler(self) -> None:
        result = run_native_smoke(
            "def fail() -> int:\n"
            "    raise ValueError('bad')\n"
            "def middle() -> int:\n"
            "    try:\n"
            "        return fail()\n"
            "    except TypeError:\n"
            "        return 1\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return middle()\n"
            "    except ValueError:\n"
            "        return 8\n",
            filename="nonmatching.py",
            entry="entry",
        )

        self.assertEqual(result.python_result, 8)
        self.assertEqual(result.native_returncode, 8)
        self.assertEqual(result.native_stdout, "")
        self.assertEqual(result.native_stderr, "")

    def test_bare_reraise_preserves_active_error(self) -> None:
        result = run_native_smoke(
            "def fail() -> int:\n"
            "    raise ValueError('bad')\n"
            "def middle() -> int:\n"
            "    try:\n"
            "        return fail()\n"
            "    except ValueError:\n"
            "        raise\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return middle()\n"
            "    except ValueError:\n"
            "        return 11\n",
            filename="reraise.py",
            entry="entry",
        )

        self.assertEqual(result.python_result, 11)
        self.assertEqual(result.native_returncode, 11)
        self.assertEqual(result.native_stdout, "")
        self.assertEqual(result.native_stderr, "")

    def test_handler_matches_project_exception_base(self) -> None:
        result = run_native_smoke(
            "class ParentError(Exception):\n"
            "    pass\n"
            "class ChildError(ParentError):\n"
            "    pass\n"
            "def fail() -> int:\n"
            "    raise ChildError('bad')\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return fail()\n"
            "    except ParentError:\n"
            "        return 12\n",
            filename="inheritance.py",
            entry="entry",
        )

        self.assertEqual(result.python_result, 12)
        self.assertEqual(result.native_returncode, 12)
        self.assertEqual(result.native_stdout, "")
        self.assertEqual(result.native_stderr, "")

    def test_handler_target_exposes_error_message(self) -> None:
        result = run_native_smoke(
            "def fail() -> int:\n"
            "    raise ValueError('bad')\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return fail()\n"
            "    except ValueError as error:\n"
            "        print(str(error))\n"
            "        return 0\n",
            filename="handler-target.py",
            entry="entry",
        )

        self.assertEqual(result.python_result, 0)
        self.assertEqual(result.native_returncode, 0)
        self.assertEqual(result.native_stdout, "bad\n")
        self.assertEqual(result.native_stderr, "")

    def test_handler_target_exposes_typed_error_payload(self) -> None:
        result = run_native_smoke(
            "class TaggedError(Exception):\n"
            "    def __init__(self, code: int) -> None:\n"
            "        self.code = code\n"
            "def fail() -> int:\n"
            "    raise TaggedError(13)\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return fail()\n"
            "    except TaggedError as error:\n"
            "        return error.code\n",
            filename="typed-payload.py",
            entry="entry",
        )

        self.assertEqual(result.python_result, 13)
        self.assertEqual(result.native_returncode, 13)
        self.assertEqual(result.native_stdout, "")
        self.assertEqual(result.native_stderr, "")

    def test_try_else_runs_only_after_success(self) -> None:
        result = run_native_smoke(
            "def okay() -> int:\n"
            "    return 3\n"
            "def entry() -> int:\n"
            "    result: int = 0\n"
            "    try:\n"
            "        result = okay()\n"
            "    except ValueError:\n"
            "        result = 9\n"
            "    else:\n"
            "        result = result + 4\n"
            "    return result\n",
            filename="try-else.py",
            entry="entry",
        )

        self.assertEqual(result.python_result, 7)
        self.assertEqual(result.native_returncode, 7)
        self.assertEqual(result.native_stdout, "")
        self.assertEqual(result.native_stderr, "")

    def test_finally_return_overrides_pending_return(self) -> None:
        result = run_native_smoke(
            "def entry() -> int:\n"
            "    try:\n"
            "        return 1\n"
            "    finally:\n"
            "        return 6\n",
            filename="finally-return.py",
            entry="entry",
        )

        self.assertEqual(result.python_result, 6)
        self.assertEqual(result.native_returncode, 6)
        self.assertEqual(result.native_stdout, "")
        self.assertEqual(result.native_stderr, "")


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

    def test_bootstrap_main_reports_preserved_caught_error_on_failure_result(self) -> None:
        int32 = IrIntType(32, signed=True)
        module = IrModule(
            "bootstrap-caught.py",
            (),
            (
                IrFunction(
                    "leaf",
                    (),
                    int32,
                    (IrRaise("PreprocessorError", IrConstString("Include not found")),),
                ),
                IrFunction(
                    "aot_bootstrap_smoke_main",
                    (),
                    int32,
                    (
                        IrTry(
                            IrBranch((IrReturn(IrCall("leaf", (), int32)),)),
                            (
                                IrExceptHandler(
                                    ("PreprocessorError",),
                                    None,
                                    IrBranch((IrReturn(IrConstInt(2, int32)),)),
                                ),
                            ),
                            IrBranch(()),
                            IrBranch(()),
                        ),
                    ),
                ),
            ),
            entry="aot_bootstrap_smoke_main",
        )

        llvm_ir = emit_llvm_text(module)

        self.assertIn(
            "store %__xcc_aot_error zeroinitializer, ptr %error_record",
            llvm_ir,
        )
        self.assertIn("%report_preserved_error = and i1", llvm_ir)
        self.assertIn("caught_error:", llvm_ir)
        self.assertIn("%caught.error.diagnostic = call i32", llvm_ir)

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
