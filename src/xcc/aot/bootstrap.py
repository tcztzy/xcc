import subprocess
from dataclasses import dataclass
from pathlib import Path

from xcc.aot.analysis import analyze_path
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrCall,
    IrConstBool,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrFunction,
    IrIntType,
    IrModule,
    IrName,
    IrNoneType,
    IrParam,
    IrRecordType,
    IrReturn,
    IrTupleType,
)
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.native import compile_llvm_executable
from xcc.aot.slice import AotSliceInput, lower_core_entry_slice
from xcc.aot.source_contract import HOSTED_ONLY_MODULES


@dataclass(frozen=True)
class AotBootstrapAdmissionReport:
    total: int
    failed: tuple[str, ...]


@dataclass(frozen=True)
class AotBootstrapEntryPlan:
    entry_symbol: str
    modules: tuple[str, ...]


@dataclass(frozen=True)
class AotBootstrapRunResult:
    returncode: int
    stdout: str
    stderr: str


_BOOTSTRAP_REQUIRED_MODULES = (
    "xcc.__init__",
    "xcc.aarch64_asm",
    "xcc.ast",
    "xcc.cc_driver",
    "xcc.codegen",
    "xcc.diag",
    "xcc.frontend",
    "xcc.lexer",
    "xcc.llvm_api",
    "xcc.options",
    "xcc.parser.__init__",
    "xcc.preprocessor.__init__",
    "xcc.sema.__init__",
    "xcc.types",
    "xcc.x86_64_asm",
)


def collect_bootstrap_sources(root: Path) -> tuple[AotSliceInput, ...]:
    src_xcc = root / "src" / "xcc"
    if not src_xcc.is_dir():
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-BOOTSTRAP-0001",
                    f"Bootstrap root does not contain src/xcc: {root}",
                    filename=str(root),
                ),
            )
        )
    src_xcc = src_xcc.resolve()
    modules: list[AotSliceInput] = []
    for path in sorted(src_xcc.rglob("*.py")):
        resolved = path.resolve()
        relative = resolved.relative_to(src_xcc)
        module_name = _bootstrap_module_name(relative)
        if module_name in HOSTED_ONLY_MODULES:
            continue
        modules.append(AotSliceInput(module_name, resolved))
    modules.sort(key=_bootstrap_input_name)
    return tuple(modules)


def summarize_bootstrap_admission(root: Path) -> AotBootstrapAdmissionReport:
    failures: list[str] = []
    modules = collect_bootstrap_sources(root)
    for module in modules:
        try:
            analyze_path(module.path)
        except AotError as exc:
            failures.append(f"{module.name}: {exc}")
    return AotBootstrapAdmissionReport(len(modules), tuple(failures))


def plan_bootstrap_entry(root: Path) -> AotBootstrapEntryPlan:
    available = {module.name for module in collect_bootstrap_sources(root)}
    missing = tuple(name for name in _BOOTSTRAP_REQUIRED_MODULES if name not in available)
    if missing:
        raise AotError(
            (
                AotDiagnostic(
                    "XCC-AOT-BOOTSTRAP-0002",
                    f"Missing bootstrap modules: {', '.join(missing)}",
                    filename=str(root),
                ),
            )
        )
    return AotBootstrapEntryPlan("xcc.cc_driver.main", _BOOTSTRAP_REQUIRED_MODULES)


def lower_bootstrap_entry_smoke(root: Path) -> IrModule:
    plan_bootstrap_entry(root)
    modules = tuple(
        module
        for module in collect_bootstrap_sources(root)
        if not module.name.startswith("xcc.aot.")
    )
    return lower_core_entry_slice(
        tuple(module.path for module in modules),
        _bootstrap_entry_smoke_wrapper(),
    )


def build_native_bootstrap(
    root: Path,
    output: Path,
    *,
    llc: str | None = None,
    cc: str = "cc",
    debug: bool = False,
    profile: bool = False,
) -> Path:
    plan_bootstrap_entry(root)
    module = lower_bootstrap_entry_smoke(root)
    llvm_ir = emit_llvm_text(module, debug or profile)
    return compile_llvm_executable(
        llvm_ir,
        output,
        filename="<bootstrap>",
        llc=llc,
        linker=cc,
        extra_link_args=_llvm_c_link_args(llc),
        diagnostic_code="XCC-AOT-BOOTSTRAP-0003",
        debug=debug,
        profile=profile,
        optimize=True,
    )


def run_bootstrap_self_host_smoke(
    root: Path,
    *,
    llc: str | None = None,
    cc: str = "cc",
) -> AotBootstrapRunResult:
    output = root / "build/aot/xcc"
    executable = build_native_bootstrap(root, output, llc=llc, cc=cc)
    smoke_dir = output.parent
    smoke_dir.mkdir(parents=True, exist_ok=True)
    source_path = smoke_dir / "self-host-smoke.c"
    object_path = smoke_dir / "self-host-smoke.o"
    source_path.write_text("int main(void){return 0;}\n", encoding="utf-8")
    object_path.unlink(missing_ok=True)
    completed = subprocess.run(
        (str(executable), "-c", str(source_path), "-o", str(object_path)),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0 and not object_path.exists():
        return AotBootstrapRunResult(
            1,
            completed.stdout,
            completed.stderr or f"missing output object: {object_path}\n",
        )
    return AotBootstrapRunResult(completed.returncode, completed.stdout, completed.stderr)


def _bootstrap_module_name(relative: Path) -> str:
    return "xcc." + ".".join(relative.with_suffix("").parts)


def _llvm_c_link_args(llc: str | None) -> tuple[str, ...]:
    llc_path = Path(llc or "/opt/homebrew/opt/llvm/bin/llc")
    lib_dir = llc_path.parent.parent / "lib"
    if not (lib_dir / "libLLVM.dylib").exists():
        return ()
    return (f"-L{lib_dir}", "-lLLVM")


def _bootstrap_input_name(module: AotSliceInput) -> str:
    return module.name


def _bootstrap_entry_smoke_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    options_type = IrRecordType("FrontendOptions")
    argv_type = IrTupleType(())
    empty_tuple = IrConstNone()
    return IrFunction(
        "aot_bootstrap_smoke_main",
        (IrParam("argc", int32), IrParam("argv", argv_type)),
        int32,
        (
            IrAssign(
                "__expr",
                IrCall(
                    "xcc.options.FrontendOptions.__post_init__",
                    (
                        IrConstructRecord(
                            "FrontendOptions",
                            (
                                IrConstString("c11"),
                                IrConstBool(True),
                                empty_tuple,
                                empty_tuple,
                                empty_tuple,
                                empty_tuple,
                                empty_tuple,
                                empty_tuple,
                                empty_tuple,
                                empty_tuple,
                                empty_tuple,
                                IrConstBool(False),
                                IrConstString("human"),
                                IrConstBool(False),
                                IrConstNone(),
                                IrConstString("linux"),
                                IrConstBool(True),
                            ),
                            options_type,
                        ),
                    ),
                    IrNoneType(),
                ),
            ),
            IrAssign(
                "__entry",
                IrConstString("xcc.cc_driver.main"),
            ),
            IrReturn(
                IrCall(
                    "xcc.cc_driver._aot_compile_smoke_source_to_object",
                    (IrName("argc", int32), IrName("argv", argv_type)),
                    int32,
                )
            ),
        ),
    )
