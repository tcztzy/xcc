from dataclasses import dataclass
from typing import Literal

DiagFormat = Literal["human", "json"]
StdMode = Literal["c11", "gnu11"]
TargetOS = Literal["darwin", "linux"]


@dataclass(frozen=True)
class FrontendOptions:
    std: StdMode = "c11"
    hosted: bool = True
    include_dirs: tuple[str, ...] = ()
    quote_include_dirs: tuple[str, ...] = ()
    system_include_dirs: tuple[str, ...] = ()
    after_include_dirs: tuple[str, ...] = ()
    forced_includes: tuple[str, ...] = ()
    macro_includes: tuple[str, ...] = ()
    defines: tuple[str, ...] = ()
    undefs: tuple[str, ...] = ()
    embed_dirs: tuple[str, ...] = ()
    no_standard_includes: bool = False
    diag_format: DiagFormat = "human"
    warn_as_error: bool = False
    host_machine: str | None = None
    target_os: TargetOS | None = None
    strip_gnu_asm_statements: bool = True

    def __post_init__(self) -> None:
        if self.std not in {"c11", "gnu11"}:
            raise ValueError(f"Unsupported language standard: {self.std}")
        if self.diag_format not in {"human", "json"}:
            raise ValueError(f"Unsupported diagnostic format: {self.diag_format}")
        if self.target_os is not None and self.target_os not in {"darwin", "linux"}:
            raise ValueError(f"Unsupported target OS: {self.target_os}")


def normalize_options(options: FrontendOptions | None) -> FrontendOptions:
    if options is None:
        return FrontendOptions()
    # B661: The AOT-compiled preprocessor cannot discover system include
    # dirs (subprocess, os.environ not available) and cannot expand dynamic
    # macros through bound-method callbacks.  Inject both as forced options.
    _forced_defines: tuple[str, ...] = (
        '__FILE__=""',
        "__LINE__=0",
        "__APPLE_CC__=6000",
        "__clang__=1",
    )
    _system_includes: tuple[str, ...] = (
        "/Applications/Xcode.app/Contents/Developer/Toolchains/"
        "XcodeDefault.xctoolchain/usr/lib/clang/21/include",
        "/Applications/Xcode.app/Contents/Developer/Platforms/"
        "MacOSX.platform/Developer/SDKs/MacOSX.sdk/usr/include",
        "/usr/include",
    )
    existing_defines = options.defines or ()
    existing_includes = options.include_dirs or ()
    return FrontendOptions(
        std=options.std,
        hosted=options.hosted,
        target_os=options.target_os,
        include_dirs=existing_includes + _system_includes,
        defines=existing_defines + _forced_defines,
        undefs=options.undefs,
        no_standard_includes=options.no_standard_includes,
        forced_includes=options.forced_includes,
        macro_includes=options.macro_includes,
        host_machine=options.host_machine,
        strip_gnu_asm_statements=options.strip_gnu_asm_statements,
    )
