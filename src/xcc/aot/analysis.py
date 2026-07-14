from dataclasses import dataclass
from pathlib import Path

from xcc.aot.binder import bind_types
from xcc.aot.module import AotModule, parse_path, parse_source
from xcc.aot.subset import AotModuleSummary, check_subset
from xcc.aot.types import AotClassInfo, AotFunctionInfo, AotTypeAnalysis


@dataclass(frozen=True)
class AotAnalysis:
    module: AotModule
    summary: AotModuleSummary
    types: AotTypeAnalysis


def analyze_source(
    source: str,
    *,
    filename: str = "<input>",
    extra_classes: dict[str, AotClassInfo] | None = None,
    extra_functions: dict[str, AotFunctionInfo] | None = None,
) -> AotAnalysis:
    module = parse_source(source, filename=filename)
    return analyze_module(
        module,
        extra_classes=extra_classes,
        extra_functions=extra_functions,
    )


def analyze_module(
    module: AotModule,
    *,
    extra_classes: dict[str, AotClassInfo] | None = None,
    extra_functions: dict[str, AotFunctionInfo] | None = None,
) -> AotAnalysis:
    summary = check_subset(module)
    type_analysis = bind_types(
        summary,
        module,
        extra_classes=extra_classes,
        extra_functions=extra_functions,
    )
    return AotAnalysis(module, summary, type_analysis)


def analyze_path(
    path: str | Path,
    *,
    extra_classes: dict[str, AotClassInfo] | None = None,
    extra_functions: dict[str, AotFunctionInfo] | None = None,
) -> AotAnalysis:
    module = parse_path(path)
    return analyze_module(
        module,
        extra_classes=extra_classes,
        extra_functions=extra_functions,
    )
