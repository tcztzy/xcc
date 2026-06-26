from dataclasses import dataclass
from pathlib import Path

from xcc.aot.binder import bind_types
from xcc.aot.module import AotModule, parse_path, parse_source
from xcc.aot.subset import AotModuleSummary, check_subset
from xcc.aot.types import AotTypeAnalysis


@dataclass(frozen=True)
class AotAnalysis:
    module: AotModule
    summary: AotModuleSummary
    types: AotTypeAnalysis


def analyze_source(source: str, *, filename: str = "<input>") -> AotAnalysis:
    module = parse_source(source, filename=filename)
    summary = check_subset(module)
    type_analysis = bind_types(summary, module)
    return AotAnalysis(module, summary, type_analysis)


def analyze_path(path: str | Path) -> AotAnalysis:
    module = parse_path(path)
    summary = check_subset(module)
    type_analysis = bind_types(summary, module)
    return AotAnalysis(module, summary, type_analysis)
