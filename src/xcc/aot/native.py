import os
import pickle
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from xcc.aot import py_ast as ast
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.lower import lower_source_to_ir
from xcc.aot.module import parse_source
from xcc.aot.slice import core_entry_wrapper, lower_core_entry_slice


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
    wrapper = core_entry_wrapper(entry, fixture)
    module = lower_core_entry_slice(paths, wrapper)
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


def compile_llvm_executable(
    llvm_ir: str,
    output: Path,
    *,
    filename: str,
    llc: str | None = None,
    assembler: str | None = None,
    linker: str = "cc",
    extra_link_args: tuple[str, ...] = (),
    diagnostic_code: str = "XCC-AOT-NATIVE-0001",
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    ll_path = output.parent / f"{output.name}.ll"
    assembly_path = output.parent / f"{output.name}.s"
    obj_path = output.parent / f"{output.name}.o"
    ll_path.write_text(llvm_ir, encoding="utf-8")
    llc_path = llc or os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    if assembler is None:
        _run_tool(
            (llc_path, "-filetype=obj", str(ll_path), "-o", str(obj_path)),
            filename,
            diagnostic_code=diagnostic_code,
        )
    else:
        _run_tool(
            (llc_path, "-filetype=asm", str(ll_path), "-o", str(assembly_path)),
            filename,
            diagnostic_code=diagnostic_code,
        )
        _run_tool(
            (assembler, str(assembly_path), "-o", str(obj_path)),
            filename,
            diagnostic_code=diagnostic_code,
        )
    _run_tool(
        (linker, str(obj_path), *extra_link_args, "-o", str(output)),
        filename,
        diagnostic_code=diagnostic_code,
    )
    return output


def _run_python_entry(source: str, entry: str) -> object:
    if not _source_defines_entry_function(source, entry):
        raise TypeError(f"{entry} is not callable")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script_path = root / "oracle.py"
        result_path = root / "result.pickle"
        script_path.write_text(_python_oracle_script(source, entry), encoding="utf-8")
        completed = subprocess.run(
            (sys.executable, str(script_path), str(result_path)),
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            message = (
                completed.stderr.strip() or completed.stdout.strip() or "CPython oracle failed"
            )
            raise AotError((AotDiagnostic("XCC-AOT-NATIVE-0001", message, filename="<python>"),))
        with result_path.open("rb") as result_file:
            return pickle.load(result_file)


def _source_defines_entry_function(source: str, entry: str) -> bool:
    if not entry.isidentifier():
        return False
    module = parse_source(source, filename="<python-oracle>").tree
    for statement in module.body:
        if isinstance(statement, ast.FunctionDef) and statement.name == entry:
            return True
    return False


def _python_oracle_script(source: str, entry: str) -> str:
    prefix = source if source.endswith("\n") else source + "\n"
    suffix = (
        "if __name__ == '__main__':\n"
        "    import pickle as __xcc_pickle\n"
        "    import sys as __xcc_sys\n"
        f"    __xcc_result = {entry}()\n"
        "    with open(__xcc_sys.argv[1], 'wb') as __xcc_result_file:\n"
        "        __xcc_pickle.dump(__xcc_result, __xcc_result_file)\n"
    )
    return prefix + suffix


def _run_tool(
    command: tuple[str, ...],
    filename: str,
    *,
    diagnostic_code: str = "XCC-AOT-NATIVE-0001",
) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        message = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"command failed: {' '.join(command)}"
        )
        raise AotError((AotDiagnostic(diagnostic_code, message, filename=filename),))
