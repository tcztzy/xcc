import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import IrModule
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.lower import lower_source_to_ir
from xcc.aot.slice import core_entry_wrapper, lower_core_slice


@dataclass(frozen=True)
class NativeSmokeResult:
    python_result: object
    native_returncode: int
    native_stdout: str
    native_stderr: str
    llvm_ir: str


def run_native_smoke(
    source: str,
    *,
    entry: str,
    filename: str = "<smoke>",
    llc: str | None = None,
    cc: str = "cc",
) -> NativeSmokeResult:
    python_result = _run_python_entry(source, entry)
    module = lower_source_to_ir(source, filename=filename, entry=entry)
    llvm_ir = emit_llvm_text(module)
    llc_path = llc or os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ll_path = root / "module.ll"
        obj_path = root / "module.o"
        exe_path = root / "module"
        ll_path.write_text(llvm_ir, encoding="utf-8")
        _run_tool((llc_path, "-filetype=obj", str(ll_path), "-o", str(obj_path)), filename)
        _run_tool((cc, str(obj_path), "-o", str(exe_path)), filename)
        completed = subprocess.run(
            (str(exe_path),),
            check=False,
            capture_output=True,
            text=True,
        )
    return NativeSmokeResult(
        python_result,
        completed.returncode,
        completed.stdout,
        completed.stderr,
        llvm_ir,
    )


def run_native_core_smoke(
    paths: tuple[Path, ...],
    *,
    entry: str,
    fixture: str,
    llc: str | None = None,
    cc: str = "cc",
) -> NativeSmokeResult:
    module = lower_core_slice(paths)
    wrapper = core_entry_wrapper(entry, fixture)
    module = IrModule(
        module.filename,
        module.records,
        module.functions + (wrapper,),
        entry=wrapper.name,
    )
    llvm_ir = emit_llvm_text(module)
    llc_path = llc or os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ll_path = root / "core.ll"
        obj_path = root / "core.o"
        exe_path = root / "core"
        ll_path.write_text(llvm_ir, encoding="utf-8")
        _run_tool((llc_path, "-filetype=obj", str(ll_path), "-o", str(obj_path)), "<core>")
        _run_tool((cc, str(obj_path), "-o", str(exe_path)), "<core>")
        completed = subprocess.run(
            (str(exe_path),),
            check=False,
            capture_output=True,
            text=True,
        )
    return NativeSmokeResult(
        None,
        completed.returncode,
        completed.stdout,
        completed.stderr,
        llvm_ir,
    )


def _run_python_entry(source: str, entry: str) -> object:
    namespace: dict[str, object] = {}
    exec(source, namespace)
    function = namespace[entry]
    if not callable(function):
        raise TypeError(f"{entry} is not callable")
    typed_function = cast(Callable[[], object], function)
    return typed_function()


def _run_tool(command: tuple[str, ...], filename: str) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        message = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"command failed: {' '.join(command)}"
        )
        raise AotError((AotDiagnostic("XCC-AOT-NATIVE-0001", message, filename=filename),))
