import os
import shutil
import subprocess
from pathlib import Path

_LLVM_LLC_OVERVIEW = "OVERVIEW: llvm system compiler"
_LLVM_LLC_USAGE = "USAGE: llc [options] <input bitcode>"


def unique_tool_candidates(candidates: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return tuple(result)


def llvm_config_bindir(llvm_config: str) -> str | None:
    try:
        completed = subprocess.run(
            (llvm_config, "--bindir"),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    bindir = (completed.stdout or "").strip().splitlines()
    return None if not bindir else bindir[0]


def llc_candidates() -> tuple[str, ...]:
    candidates: list[str] = []
    llvm_config = os.environ.get("LLVM_CONFIG") or shutil.which("llvm-config")
    if llvm_config:
        bindir = llvm_config_bindir(llvm_config)
        if bindir:
            candidates.append(str(Path(bindir) / "llc"))
    path_llc = shutil.which("llc")
    if path_llc:
        candidates.append(path_llc)
    return unique_tool_candidates(candidates)


def is_llvm_llc(path: str) -> bool:
    try:
        completed = subprocess.run(
            (path, "--help"),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    stdout = completed.stdout or ""
    return completed.returncode == 0 and _LLVM_LLC_OVERVIEW in stdout and _LLVM_LLC_USAGE in stdout


def find_llc(explicit: str | None = None) -> str:
    configured = explicit or os.environ.get("XCC_LLC")
    if configured:
        return configured
    for candidate in llc_candidates():
        if is_llvm_llc(candidate):
            return candidate
    raise ValueError("unable to find LLVM llc; set XCC_LLC or put LLVM llc on PATH")
