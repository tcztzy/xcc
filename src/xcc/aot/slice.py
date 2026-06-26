from dataclasses import dataclass
from pathlib import Path

from xcc.aot.diag import AotDiagnostic, AotError


@dataclass(frozen=True)
class AotSliceInput:
    name: str
    path: Path


def collect_slice_inputs(paths: tuple[Path, ...]) -> tuple[AotSliceInput, ...]:
    root = (Path.cwd() / "src" / "xcc").resolve()
    modules: list[AotSliceInput] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise AotError(
                (
                    AotDiagnostic(
                        "XCC-AOT-SLICE-0001",
                        f"Module is outside src/xcc: {resolved}",
                        filename=str(resolved),
                    ),
                )
            ) from exc
        if relative.suffix != ".py":
            raise AotError(
                (
                    AotDiagnostic(
                        "XCC-AOT-SLICE-0001",
                        f"Module is not Python source: {resolved}",
                        filename=str(resolved),
                    ),
                )
            )
        modules.append(AotSliceInput("xcc." + ".".join(relative.with_suffix("").parts), resolved))
    return tuple(sorted(modules, key=lambda module: module.name))
