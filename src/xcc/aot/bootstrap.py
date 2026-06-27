from dataclasses import dataclass
from pathlib import Path

from xcc.aot.analysis import analyze_path
from xcc.aot.diag import AotDiagnostic, AotError
from xcc.aot.slice import AotSliceInput


@dataclass(frozen=True)
class AotBootstrapAdmissionReport:
    total: int
    failed: tuple[str, ...]


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


def _bootstrap_module_name(relative: Path) -> str:
    return "xcc." + ".".join(relative.with_suffix("").parts)


def _bootstrap_input_name(module: AotSliceInput) -> str:
    return module.name
