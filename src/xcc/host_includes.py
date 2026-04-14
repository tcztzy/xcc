import os
import subprocess
import sys
from functools import cache
from pathlib import Path


def host_system_include_dirs() -> tuple[str, ...]:
    return _host_system_include_dirs(sys.platform, os.environ.get("SDKROOT", ""))


def _is_pathlike(value: str) -> bool:
    return "/" in value or "\\" in value


def _xcrun_stdout(*args: str) -> str | None:
    try:
        proc = subprocess.run(
            ("xcrun", *args),
            check=True,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    stdout = proc.stdout.strip()
    return stdout or None


def _dedupe_in_order(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _macos_sdk(sdkroot: str) -> tuple[str, Path | None]:
    if sdkroot and _is_pathlike(sdkroot):
        return "macosx", Path(sdkroot)
    sdk = sdkroot or "macosx"
    resolved = _xcrun_stdout("--sdk", sdk, "--show-sdk-path")
    if resolved is None:
        return sdk, None
    return sdk, Path(resolved)


def _macos_clang_resource_include_dir(sdk: str) -> str | None:
    resource_dir = _xcrun_stdout("--sdk", sdk, "clang", "-print-resource-dir")
    if resource_dir is None:
        return None
    return str(Path(resource_dir) / "include")


@cache
def _host_system_include_dirs(platform: str, sdkroot: str) -> tuple[str, ...]:
    if platform != "darwin":
        return ()

    sdk, sdk_path = _macos_sdk(sdkroot)
    include_dirs: list[str] = []
    resource_include = _macos_clang_resource_include_dir(sdk)
    if resource_include is not None:
        include_dirs.append(resource_include)
    if sdk_path is not None:
        include_dirs.append(str(sdk_path / "usr" / "include"))
    include_dirs.append("/usr/include")
    return _dedupe_in_order(include_dirs)
