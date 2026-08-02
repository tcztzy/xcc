import os
import shutil
import subprocess
import sys
from pathlib import Path


def host_system_include_dirs() -> tuple[str, ...]:
    # B661: os.environ may not be available in the AOT binary.
    try:
        _sdkroot = os.environ.get("SDKROOT", "")
        _platform = sys.platform
    except Exception:
        _sdkroot = ""
        _platform = "darwin"
    return _host_system_include_dirs(_platform, _sdkroot)


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
    except Exception:  # B661: AOT binary may raise unexpected exception types
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


# B661: @cache uses functools internals not available in the AOT subset.
# The function is cheap enough to call without caching.
def _host_system_include_dirs(platform: str, sdkroot: str) -> tuple[str, ...]:
    if platform.startswith("linux"):
        return _cc_system_include_dirs()
    if platform != "darwin":
        return ()

    # B661: The AOT binary may report a non-standard sys.platform and
    # subprocess/xcrun is not in the AOT Python subset.  Use filesystem
    # operations to locate Xcode SDK and Clang resource directories.
    include_dirs: list[str] = []
    try:
        sdk, sdk_path = _macos_sdk(sdkroot)
        resource_include = _macos_clang_resource_include_dir(sdk)
    except Exception:
        sdk_path = None
        resource_include = None
    if resource_include is not None:
        include_dirs.append(resource_include)
    else:
        _xcode_base = Path(
            "/Applications/Xcode.app/Contents/Developer/Toolchains/"
            "XcodeDefault.xctoolchain/usr/lib/clang"
        )
        if _xcode_base.is_dir():
            _versions = sorted(p for p in _xcode_base.iterdir() if p.is_dir())
            if _versions:
                include_dirs.append(str(_versions[-1] / "include"))
    if sdk_path is not None:
        include_dirs.append(str(sdk_path / "usr" / "include"))
    else:
        _sdk_base = Path(
            "/Applications/Xcode.app/Contents/Developer/Platforms/"
            "MacOSX.platform/Developer/SDKs/MacOSX.sdk"
        )
        if _sdk_base.is_dir():
            include_dirs.append(str(_sdk_base / "usr" / "include"))
    include_dirs.append("/usr/include")
    return _dedupe_in_order(include_dirs)
