from dataclasses import dataclass
from pathlib import Path

from xcc.aot.analysis import analyze_path
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.ir import (
    IrAssign,
    IrCall,
    IrConstBool,
    IrConstInt,
    IrConstNone,
    IrConstructRecord,
    IrConstString,
    IrFunction,
    IrIntType,
    IrModule,
    IrNoneType,
    IrRecordType,
    IrReturn,
)
from xcc.aot.llvm_text import emit_llvm_text
from xcc.aot.native import compile_llvm_executable
from xcc.aot.slice import AotSliceInput, lower_core_entry_slice


@dataclass(frozen=True)
class AotBootstrapAdmissionReport:
    total: int
    failed: tuple[str, ...]


@dataclass(frozen=True)
class AotBootstrapEntryPlan:
    entry_symbol: str
    modules: tuple[str, ...]


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
        modules.append(AotSliceInput(_bootstrap_module_name(relative), resolved))
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
    return lower_core_entry_slice(
        (root / "src/xcc/options.py",),
        _bootstrap_entry_smoke_wrapper(),
    )


def build_native_bootstrap(
    root: Path,
    output: Path,
    *,
    llc: str | None = None,
    cc: str = "cc",
) -> Path:
    plan_bootstrap_entry(root)
    module = lower_bootstrap_entry_smoke(root)
    llvm_ir = emit_llvm_text(module)
    return compile_llvm_executable(
        llvm_ir,
        output,
        filename="<bootstrap>",
        llc=llc,
        cc=cc,
        diagnostic_code="XCC-AOT-BOOTSTRAP-0003",
    )


def _bootstrap_module_name(relative: Path) -> str:
    return "xcc." + ".".join(relative.with_suffix("").parts)


def _bootstrap_input_name(module: AotSliceInput) -> str:
    return module.name


def _bootstrap_entry_smoke_wrapper() -> IrFunction:
    int32 = IrIntType(32, signed=True)
    options_type = IrRecordType("FrontendOptions")
    empty_tuple = IrConstNone()
    return IrFunction(
        "aot_bootstrap_smoke_main",
        (),
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
                                IrConstNone(),
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
            IrReturn(IrConstInt(0, int32)),
        ),
    )
