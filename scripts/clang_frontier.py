#!/usr/bin/env python3
import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests/external/clang/manifest.json"
_STAGE_RE = re.compile(r"got (ok|lex|pp|parse|sema)\b")
_LAYER_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_P0_DECLARATOR_HINTS = ("declar", "storage class", "typedef", "symbol", "lookup")
_P0_TYPE_HINTS = (
    "type",
    "convert",
    "conversion",
    "promotion",
    "compatib",
    "cast",
    "pointer",
    "array",
    "enum",
    "struct",
    "union",
    "integer",
)
_P2_HINTS = ("macro", "include", "pragma", "ifdef", "ifndef", "elif", "define")
_P3_HINTS = ("diagnostic", "warning", "error message", "line ", "column ")


@dataclass(frozen=True)
class SliceBucket:
    layer: str
    family: str
    subsystem: str


def load_skipped_cases(manifest_path: Path = DEFAULT_MANIFEST) -> list[dict[str, Any]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [case for case in payload.get("cases", []) if isinstance(case.get("skip_reason"), str)]


def extract_actual_stage(skip_reason: str) -> str | None:
    match = _STAGE_RE.search(skip_reason)
    if match is None:
        return None
    return match.group(1)


def classify_case(case: dict[str, Any]) -> SliceBucket:
    upstream = str(case.get("upstream", "")).lower()
    reason = str(case.get("skip_reason", "")).lower()
    stage = extract_actual_stage(reason)
    text = f"{upstream} {reason}"

    if stage == "lex":
        return SliceBucket(layer="P2", family="lexing-and-tokens", subsystem="lexer")
    if stage == "pp" or any(hint in text for hint in _P2_HINTS):
        return SliceBucket(layer="P2", family="macro-and-include-edges", subsystem="preprocessor")
    if any(hint in text for hint in _P0_DECLARATOR_HINTS):
        return SliceBucket(layer="P0", family="declarators-and-symbol-binding", subsystem="parser,sema")
    if any(hint in text for hint in _P0_TYPE_HINTS) or stage == "sema":
        return SliceBucket(layer="P0", family="types-and-conversions", subsystem="sema")
    if "diag" in upstream or any(hint in text for hint in _P3_HINTS):
        return SliceBucket(layer="P3", family="diagnostic-alignment", subsystem="diagnostics")
    return SliceBucket(layer="P1", family="expression-semantics", subsystem="parser,sema")


def build_frontier(payload: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for case in payload.get("cases", []):
        if not isinstance(case, dict) or not isinstance(case.get("skip_reason"), str):
            continue
        bucket = classify_case(case)
        key = (bucket.layer, bucket.family, bucket.subsystem)
        grouped.setdefault(key, []).append(str(case.get("id", "<missing-id>")))
    frontier: list[dict[str, Any]] = []
    for (layer, family, subsystem), case_ids in grouped.items():
        normalized_family = family.replace("_", "-")
        normalized_subsystem = subsystem.replace(",", "-").replace("/", "-")
        frontier.append(
            {
                "slice_id": f"clang-{layer.lower()}-{normalized_family}-{normalized_subsystem}",
                "layer": layer,
                "family": family,
                "subsystem": subsystem,
                "count": len(case_ids),
                "case_ids": sorted(case_ids),
            }
        )
    frontier.sort(
        key=lambda item: (
            _LAYER_ORDER.get(item["layer"], 99),
            -item["count"],
            item["slice_id"],
        )
    )
    return frontier


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--limit", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(json.dumps(build_frontier(payload)[: args.limit], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
