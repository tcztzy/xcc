from dataclasses import dataclass
from typing import Literal

DiagFormat = Literal["human", "json"]
StdMode = Literal["c11", "gnu11"]


@dataclass(frozen=True)
class FrontendOptions:
    std: StdMode = "c11"
    include_dirs: tuple[str, ...] = ()
    quote_include_dirs: tuple[str, ...] = ()
    system_include_dirs: tuple[str, ...] = ()
    after_include_dirs: tuple[str, ...] = ()
    forced_includes: tuple[str, ...] = ()
    defines: tuple[str, ...] = ()
    undefs: tuple[str, ...] = ()
    diag_format: DiagFormat = "human"
    warn_as_error: bool = False

    def __post_init__(self) -> None:
        if self.std not in {"c11", "gnu11"}:
            raise ValueError(f"Unsupported language standard: {self.std}")
        if self.diag_format not in {"human", "json"}:
            raise ValueError(f"Unsupported diagnostic format: {self.diag_format}")


def normalize_options(options: FrontendOptions | None) -> FrontendOptions:
    return FrontendOptions() if options is None else options
