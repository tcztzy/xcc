import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from xcc.aot.diag import AotError
from xcc.aot.module import parse_source
from xcc.aot.source_contract import ParserBackend, render_source_manifest, resolve_source_set

ROOT = Path(__file__).resolve().parents[1]


def _hosted_parser(source: str, filename: str):
    return parse_source(source, filename=filename)


HOSTED_BACKEND = ParserBackend("cpython", _hosted_parser)


class AotSourceContractTests(unittest.TestCase):
    def test_resolves_entry_closure_relative_imports_and_dependency_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "entry.py").write_text(
                "from . import helper\nfrom pkg.cycle_a import value\n",
                encoding="utf-8",
            )
            (root / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "cycle_a.py").write_text("from pkg import cycle_b\nvalue = 1\n", encoding="utf-8")
            (root / "cycle_b.py").write_text("from pkg import cycle_a\n", encoding="utf-8")
            (root / "unused.py").write_text("UNUSED = True\n", encoding="utf-8")

            source_set = resolve_source_set(root, "pkg.entry", HOSTED_BACKEND)

        modules = tuple(unit.module for unit in source_set.units)
        self.assertEqual(
            modules,
            ("pkg", "pkg.cycle_a", "pkg.cycle_b", "pkg.helper", "pkg.entry"),
        )
        self.assertNotIn("pkg.unused", modules)
        self.assertEqual(tuple(unit.order for unit in source_set.units), (0, 1, 2, 3, 4))
        entry = next(unit for unit in source_set.units if unit.module == "pkg.entry")
        self.assertEqual(entry.source, "from . import helper\nfrom pkg.cycle_a import value\n")
        self.assertEqual(entry.parsed.source, entry.source)

    def test_includes_parent_packages_and_nested_static_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pkg"
            child = root / "child"
            child.mkdir(parents=True)
            (root / "__init__.py").write_text("ROOT = 1\n", encoding="utf-8")
            (child / "__init__.py").write_text("CHILD = 1\n", encoding="utf-8")
            (child / "entry.py").write_text(
                "def load() -> int:\n    from pkg import helper\n    return helper.VALUE\n",
                encoding="utf-8",
            )
            (root / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")

            source_set = resolve_source_set(root, "pkg.child.entry", HOSTED_BACKEND)

        self.assertEqual(
            tuple(unit.module for unit in source_set.units),
            ("pkg", "pkg.child", "pkg.helper", "pkg.child.entry"),
        )

    def test_subset_backend_rejects_hosted_only_module(self) -> None:
        root = ROOT / "src/xcc"
        subset_backend = ParserBackend("subset", _hosted_parser)

        with self.assertRaises(AotError) as ctx:
            resolve_source_set(root, "xcc.aot.hosted_cli", subset_backend)

        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SOURCE-0006")

    def test_records_allowed_stdlib_and_rejects_unknown_external_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("import json\n", encoding="utf-8")

            source_set = resolve_source_set(root, "pkg", HOSTED_BACKEND)
            self.assertEqual(source_set.units[0].external_dependencies, ("json",))

            (root / "bad.py").write_text("import third_party\n", encoding="utf-8")
            with self.assertRaises(AotError) as ctx:
                resolve_source_set(root, "pkg.bad", HOSTED_BACKEND)

        self.assertEqual(ctx.exception.diagnostics[0].code, "XCC-AOT-SOURCE-0007")

    def test_manifest_is_canonical_and_hashes_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pkg"
            root.mkdir()
            (root / "__init__.py").write_bytes(b"VALUE = 1\r\n")
            source_set = resolve_source_set(root, "pkg", HOSTED_BACKEND)
            first = render_source_manifest(source_set)
            second = render_source_manifest(source_set)

        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))
        payload = json.loads(first)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["units"][0]["relative_path"], "__init__.py")
        self.assertEqual(payload["units"][0]["sha256"], hashlib.sha256(b"VALUE = 1\r\n").hexdigest())

    def test_rejects_invalid_root_entry_missing_module_and_non_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with self.assertRaises(AotError):
                resolve_source_set(base / "missing", "pkg.entry", HOSTED_BACKEND)
            root = base / "pkg"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            with self.assertRaises(AotError):
                resolve_source_set(root, "other.entry", HOSTED_BACKEND)
            with self.assertRaises(AotError):
                resolve_source_set(root, "pkg.missing", HOSTED_BACKEND)
            (root / "bad.py").write_bytes(b"\xff")
            with self.assertRaises(AotError):
                resolve_source_set(root, "pkg.bad", HOSTED_BACKEND)


if __name__ == "__main__":
    unittest.main()
