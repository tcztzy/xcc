#!/usr/bin/env python3
"""Smoke-test the installed XCC package and console entry point."""

import os
import shutil
import subprocess
import sys
import tempfile
from importlib.util import find_spec
from pathlib import Path


def _run(command: tuple[str, ...], *, cwd: Path, env: dict[str, str]) -> bool:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode == 0:
        return True
    print(f"package smoke command failed: {' '.join(command)}", file=sys.stderr)
    if completed.stdout:
        print(completed.stdout, end="", file=sys.stderr)
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return False


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    source_root = (repository / "src").resolve()
    package_spec = find_spec("xcc")
    if package_spec is None or package_spec.origin is None:
        print("package smoke could not import the installed xcc package", file=sys.stderr)
        return 1
    imported_package = Path(package_spec.origin).resolve()
    if source_root == imported_package or source_root in imported_package.parents:
        print(
            f"package smoke imported the source tree instead of the installed wheel: "
            f"{imported_package}",
            file=sys.stderr,
        )
        return 1

    executable = shutil.which("xcc")
    if executable is None:
        print("package smoke could not find the installed xcc entry point", file=sys.stderr)
        return 1

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="xcc-package-smoke-") as temporary:
        workdir = Path(temporary)
        source = workdir / "smoke.c"
        source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
        if not _run((executable, "--help"), cwd=workdir, env=env):
            return 1
        if not _run(
            (executable, "--frontend", "-nostdinc", str(source)),
            cwd=workdir,
            env=env,
        ):
            return 1
    print(f"installed package smoke passed: {imported_package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
