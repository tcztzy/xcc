import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from xcc import cc_driver

LLVM_BIN = Path("/opt/homebrew/opt/llvm/bin")


def _profiling_source() -> str:
    return (
        "static unsigned long leaf(unsigned long value) {\n"
        "  unsigned long index = 0;\n"
        "  while (index < 4UL) {\n"
        "    value = value * 3UL + 1UL;\n"
        "    index = index + 1;\n"
        "  }\n"
        "  return value;\n"
        "}\n"
        "static unsigned long middle(unsigned long value) {\n"
        "  return leaf(value);\n"
        "}\n"
        "int main(void) {\n"
        "  return middle(1UL) == 0;\n"
        "}\n"
    )


class NativeCProfilingTests(unittest.TestCase):
    @unittest.skipUnless(
        sys.platform == "darwin"
        and Path("/usr/bin/dwarfdump").is_file()
        and Path("/usr/bin/atos").is_file()
        and (LLVM_BIN / "llvm-dwarfdump").is_file()
        and (LLVM_BIN / "llvm-objdump").is_file(),
        "macOS DWARF and LLVM inspection tools are required",
    )
    def test_macos_debug_program_has_source_dwarf_unwind_and_atos_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "profile.c"
            object_path = root / "profile.o"
            executable = root / "profile"
            source.write_text(_profiling_source(), encoding="utf-8")

            self.assertEqual(
                cc_driver.main(["-g", "-nostdinc", "-c", str(source), "-o", str(object_path)]),
                0,
            )
            self.assertEqual(
                cc_driver.main(["-g", "-nostdinc", str(source), "-o", str(executable)]),
                0,
            )
            dwarf = subprocess.run(
                ("/usr/bin/dwarfdump", "--debug-info", "--debug-line", str(object_path)),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            unwind = subprocess.run(
                (str(LLVM_BIN / "llvm-dwarfdump"), "--eh-frame", str(object_path)),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            disassembly = subprocess.run(
                (str(LLVM_BIN / "llvm-objdump"), "--disassemble", str(object_path)),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            symbols = subprocess.run(
                ("nm", "-n", str(executable)),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            middle_match = re.search(
                r"^([0-9a-fA-F]+)\s+[a-zA-Z]\s+_middle$", symbols, re.MULTILINE
            )
            self.assertIsNotNone(middle_match, symbols)
            assert middle_match is not None
            middle_body_address = int(middle_match.group(1), 16) + 16
            resolved = subprocess.run(
                (
                    "/usr/bin/atos",
                    "-o",
                    str(executable),
                    "-arch",
                    "arm64",
                    "-l",
                    "0x100000000",
                    f"0x{middle_body_address:x}",
                ),
                check=True,
                capture_output=True,
                text=True,
            ).stdout

            self.assertTrue(Path(str(executable) + ".dSYM").is_dir())

        for tag in ("DW_TAG_compile_unit", "DW_TAG_subprogram"):
            self.assertIn(tag, dwarf)
        for function, line in (("leaf", 1), ("middle", 9), ("main", 12)):
            self.assertRegex(
                dwarf,
                rf'DW_AT_name\s+\("{function}"\)[\s\S]*?DW_AT_decl_line\s+\({line}\)',
            )
        self.assertRegex(dwarf, r"0x[0-9a-f]+\s+4\s+[1-9]\s+1")
        self.assertIn("FDE", unwind)
        self.assertRegex(disassembly, r"stp\s+x29, x30")
        self.assertRegex(disassembly, r"add\s+x29, sp")
        self.assertIn("middle", resolved)
        self.assertIn("profile.c:10", resolved)

    @unittest.skipUnless(
        all(
            (LLVM_BIN / tool).is_file()
            for tool in ("llc", "llvm-dwarfdump", "llvm-objdump", "llvm-readelf")
        ),
        "LLVM cross-target inspection tools are required",
    )
    def test_linux_perf_object_has_dwarf_eh_frame_and_rbp_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "profile.c"
            object_path = root / "profile.o"
            source.write_text(_profiling_source(), encoding="utf-8")

            self.assertEqual(
                cc_driver.main(
                    [
                        "--target=x86_64-linux-gnu",
                        "-g",
                        "-nostdinc",
                        "-c",
                        str(source),
                        "-o",
                        str(object_path),
                    ]
                ),
                0,
            )
            sections = subprocess.run(
                (str(LLVM_BIN / "llvm-readelf"), "--sections", str(object_path)),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            dwarf = subprocess.run(
                (
                    str(LLVM_BIN / "llvm-dwarfdump"),
                    "--debug-info",
                    "--debug-line",
                    "--eh-frame",
                    str(object_path),
                ),
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            disassembly = subprocess.run(
                (str(LLVM_BIN / "llvm-objdump"), "--disassemble", str(object_path)),
                check=True,
                capture_output=True,
                text=True,
            ).stdout

        for section in (".debug_info", ".debug_line", ".eh_frame"):
            self.assertIn(section, sections)
        self.assertIn("DW_TAG_compile_unit", dwarf)
        self.assertIn("DW_TAG_subprogram", dwarf)
        self.assertIn("FDE", dwarf)
        self.assertRegex(disassembly, r"pushq?\s+%rbp")
        self.assertRegex(disassembly, r"movq?\s+%rsp,\s*%rbp")


if __name__ == "__main__":
    unittest.main()
