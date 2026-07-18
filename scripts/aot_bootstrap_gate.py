#!/usr/bin/env python3

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_USAGE = (
    "usage: python scripts/aot_bootstrap_gate.py compare-behavior STAGE2_XCC_AOT STAGE3_XCC_AOT"
)
_FIXTURE_ENTRY = "behavior_fixture.program:main"


class BehaviorMismatch(RuntimeError):
    pass


def main(arguments: tuple[str, ...] | None = None) -> int:
    args = tuple(sys.argv[1:]) if arguments is None else arguments
    if len(args) != 3 or args[0] != "compare-behavior":
        print(_USAGE, file=sys.stderr)
        return 2
    try:
        compare_behavior(Path(args[1]), Path(args[2]))
    except (BehaviorMismatch, OSError, subprocess.SubprocessError) as error:
        print(f"aot-bootstrap-gate: {error}", file=sys.stderr)
        return 1
    print("aot-bootstrap-gate: Stage 2/3 behavior equivalent")
    return 0


def compare_behavior(stage2: Path, stage3: Path) -> None:
    stage2 = _require_executable(stage2, "Stage 2")
    stage3 = _require_executable(stage3, "Stage 3")
    probes = (
        ("version", ("--version",), 0),
        ("help", ("--help",), 0),
        ("unknown command", ("__xcc_invalid_command__",), 2),
    )
    for label, arguments, expected_returncode in probes:
        left = _run_command((str(stage2), *arguments))
        right = _run_command((str(stage3), *arguments))
        compare_process_observations(label, left, right)
        _require_returncode(label, left, expected_returncode)
    if "native-contract" not in _run_command((str(stage2), "--version")).stdout:
        raise BehaviorMismatch("version output does not identify native-contract mode")

    with tempfile.TemporaryDirectory(prefix="xcc-aot-bootstrap-behavior-") as temp_dir:
        root = Path(temp_dir)
        source_root = root / "behavior_fixture"
        _write_fixture(source_root)
        stage2_output = root / "stage2"
        stage3_output = root / "stage3"
        stage2_output.mkdir()
        stage3_output.mkdir()
        left_build = _build_fixture(stage2, source_root, stage2_output)
        right_build = _build_fixture(stage3, source_root, stage3_output)
        compare_process_observations("fixture build", left_build, right_build)
        _require_returncode("Stage 2 fixture build", left_build, 0)
        _require_returncode("Stage 3 fixture build", right_build, 0)
        for label, filename in (
            ("normalized fixture IR", "program.norm.ll"),
            ("fixture source manifest", "sources.json"),
            ("fixture reachability", "program.reachability"),
        ):
            compare_artifacts(label, stage2_output / filename, stage3_output / filename)
        _compare_tool_logs(stage2_output / "tools.log", stage3_output / "tools.log")
        left_program = _run_command((str(stage2_output / "program"),))
        right_program = _run_command((str(stage3_output / "program"),))
        compare_process_observations("fixture program", left_program, right_program)
        _require_returncode("Stage 2 fixture program", left_program, 7)
        _require_returncode("Stage 3 fixture program", right_program, 7)
        if left_program.stdout or left_program.stderr:
            raise BehaviorMismatch("fixture program produced unexpected output")


def compare_process_observations(
    label: str,
    left: subprocess.CompletedProcess[str],
    right: subprocess.CompletedProcess[str],
) -> None:
    if left.returncode != right.returncode:
        raise BehaviorMismatch(
            f"{label} return code differs: Stage 2={left.returncode}, Stage 3={right.returncode}"
        )
    if left.stdout != right.stdout:
        raise BehaviorMismatch(f"{label} stdout differs")
    if left.stderr != right.stderr:
        raise BehaviorMismatch(f"{label} stderr differs")


def compare_artifacts(label: str, left: Path, right: Path) -> None:
    if not left.is_file():
        raise BehaviorMismatch(f"{label} missing for Stage 2: {left}")
    if not right.is_file():
        raise BehaviorMismatch(f"{label} missing for Stage 3: {right}")
    if left.read_bytes() != right.read_bytes():
        raise BehaviorMismatch(f"{label} differs")


def _require_executable(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise BehaviorMismatch(f"{label} compiler is not executable: {path}")
    return resolved


def _run_command(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _require_returncode(
    label: str,
    result: subprocess.CompletedProcess[str],
    expected: int,
) -> None:
    if result.returncode != expected:
        output = result.stderr.strip() or result.stdout.strip()
        suffix = "" if not output else f": {output}"
        raise BehaviorMismatch(f"{label} returned {result.returncode}, expected {expected}{suffix}")


def _write_fixture(source_root: Path) -> None:
    source_root.mkdir()
    (source_root / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "helper.py").write_text(
        "def answer() -> int:\n    return 7\n",
        encoding="utf-8",
    )
    (source_root / "program.py").write_text(
        "def main() -> int:\n    from behavior_fixture.helper import answer\n    return answer()\n",
        encoding="utf-8",
    )


def _build_fixture(
    compiler: Path,
    source_root: Path,
    output_root: Path,
) -> subprocess.CompletedProcess[str]:
    output = output_root / "program"
    llc = os.environ.get("XCC_LLC") or "/opt/homebrew/opt/llvm/bin/llc"
    return _run_command(
        (
            str(compiler),
            "build",
            "--parser=subset",
            "--no-cache",
            f"--source-root={source_root}",
            f"--entry={_FIXTURE_ENTRY}",
            f"--emit-llvm={output_root / 'program.ll'}",
            f"--emit-normalized-ir={output_root / 'program.norm.ll'}",
            f"--source-manifest={output_root / 'sources.json'}",
            f"--tool-log={output_root / 'tools.log'}",
            f"--llc={llc}",
            f"--output={output}",
        )
    )


def _compare_tool_logs(left: Path, right: Path) -> None:
    left_tools = _tool_names(left)
    right_tools = _tool_names(right)
    if left_tools != right_tools:
        raise BehaviorMismatch(
            f"fixture tool sequence differs: Stage 2={left_tools}, Stage 3={right_tools}"
        )
    if left_tools != ("llc", "cc"):
        raise BehaviorMismatch(f"fixture used unexpected tools: {left_tools}")
    if any("python" in tool.lower() for tool in left_tools):
        raise BehaviorMismatch(f"fixture launched Python tool: {left_tools}")


def _tool_names(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        raise BehaviorMismatch(f"fixture tool log is missing: {path}")
    return tuple(
        Path(line.removeprefix("command=").split("\t", 1)[0]).name
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("command=")
    )


if __name__ == "__main__":
    raise SystemExit(main())
