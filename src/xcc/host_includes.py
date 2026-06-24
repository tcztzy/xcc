import os
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path


def host_system_include_dirs() -> tuple[str, ...]:
    return _host_system_include_dirs(sys.platform, os.environ.get("SDKROOT", ""))


def _is_pathlike(value: str) -> bool:
    return "/" in value or "\\" in value


def _xcrun_stdout(*args: str) -> str | None:
    return _command_stdout(("xcrun", *args))


def _command_stdout(command: tuple[str, ...]) -> str | None:
    try:
        proc = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    stdout = proc.stdout.strip()
    return stdout or None


def _tool_path_from_env(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None
    if _is_pathlike(value):
        return Path(value)
    resolved = shutil.which(value)
    return Path(resolved) if resolved is not None else None


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
    xcc_llc = _tool_path_from_env("XCC_LLC")
    if xcc_llc is not None:
        sibling_clang = xcc_llc.with_name("clang")
        if sibling_clang.is_file():
            resource_dir = _command_stdout((str(sibling_clang), "-print-resource-dir"))
            if resource_dir is not None:
                return str(Path(resource_dir) / "include")
    resource_dir = _xcrun_stdout("--sdk", sdk, "clang", "-print-resource-dir")
    if resource_dir is None:
        return None
    return str(Path(resource_dir) / "include")


def _cc_system_include_dirs() -> tuple[str, ...]:
    try:
        proc = subprocess.run(
            ("cc", "-E", "-v", "-x", "c", "-"),
            input="",
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ("/usr/local/include", "/usr/include")
    include_dirs: list[str] = []
    in_search_list = False
    for raw_line in proc.stderr.splitlines():
        line = raw_line.strip()
        if line == "#include <...> search starts here:":
            in_search_list = True
            continue
        if line == "End of search list.":
            break
        if in_search_list and line:
            include_dirs.append(line)
    if not include_dirs:
        include_dirs.extend(("/usr/local/include", "/usr/include"))
    return _dedupe_in_order(include_dirs)


@cache
def _host_system_include_dirs(platform: str, sdkroot: str) -> tuple[str, ...]:
    if platform.startswith("linux"):
        return _cc_system_include_dirs()
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
