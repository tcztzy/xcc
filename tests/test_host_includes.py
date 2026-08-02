import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc import host_includes


class HostIncludesTests(unittest.TestCase):
    def test_is_pathlike(self) -> None:
        self.assertFalse(host_includes._is_pathlike("macosx"))
        self.assertTrue(host_includes._is_pathlike("/SDKs/MacOSX.sdk"))
        self.assertTrue(host_includes._is_pathlike(r"C:\SDKs\MacOSX.sdk"))

    def test_dedupe_in_order(self) -> None:
        self.assertEqual(host_includes._dedupe_in_order(["a", "a", "b", "a"]), ("a", "b"))

    def test_tool_path_from_env_resolves_pathless_names(self) -> None:
        with (
            patch.dict("os.environ", {"XCC_LLC": "llc"}, clear=True),
            patch("xcc.host_includes.shutil.which", return_value="/tools/llc") as which,
        ):
            self.assertEqual(host_includes._tool_path_from_env("XCC_LLC"), Path("/tools/llc"))
        which.assert_called_once_with("llc")

        with (
            patch.dict("os.environ", {"XCC_LLC": "llc"}, clear=True),
            patch("xcc.host_includes.shutil.which", return_value=None),
        ):
            self.assertIsNone(host_includes._tool_path_from_env("XCC_LLC"))

    def test_xcrun_stdout_returns_none_for_empty_output(self) -> None:
        completed = subprocess.CompletedProcess(("xcrun",), 0, stdout=" \n", stderr="")
        with patch("xcc.host_includes.subprocess.run", return_value=completed):
            self.assertIsNone(host_includes._xcrun_stdout("--version"))

    def test_host_system_include_dirs_unknown_platform_returns_empty(self) -> None:
        with (
            patch("xcc.host_includes.sys.platform", "win32"),
            patch("xcc.host_includes.subprocess.run") as run,
        ):
            self.assertEqual(host_includes.host_system_include_dirs(), ())
        run.assert_not_called()

    def test_host_system_include_dirs_linux_parses_cc_search_list(self) -> None:
        stderr = """
#include "..." search starts here:
#include <...> search starts here:
 /usr/lib/gcc/x86_64-redhat-linux/8/include
 /usr/local/include
 /usr/include
End of search list.
"""
        completed = subprocess.CompletedProcess(("cc",), 0, stdout="", stderr=stderr)
        with (
            patch("xcc.host_includes.sys.platform", "linux"),
            patch("xcc.host_includes.subprocess.run", return_value=completed) as run,
        ):
            self.assertEqual(
                host_includes.host_system_include_dirs(),
                (
                    "/usr/lib/gcc/x86_64-redhat-linux/8/include",
                    "/usr/local/include",
                    "/usr/include",
                ),
            )
        run.assert_called_once()

    def test_host_system_include_dirs_linux_falls_back_when_cc_fails(self) -> None:
        with (
            patch("xcc.host_includes.sys.platform", "linux"),
            patch("xcc.host_includes.subprocess.run", side_effect=OSError("cc missing")),
        ):
            self.assertEqual(
                host_includes.host_system_include_dirs(),
                ("/usr/local/include", "/usr/include"),
            )

    def test_host_system_include_dirs_linux_falls_back_without_search_list(self) -> None:
        completed = subprocess.CompletedProcess(("cc",), 0, stdout="", stderr="cc verbose")
        with (
            patch("xcc.host_includes.sys.platform", "linux"),
            patch("xcc.host_includes.subprocess.run", return_value=completed),
        ):
            self.assertEqual(
                host_includes.host_system_include_dirs(),
                ("/usr/local/include", "/usr/include"),
            )

    def test_host_system_include_dirs_darwin_uses_sdkroot_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdk_root = Path(tmp) / "MacOSX.sdk"
            sdk_root.mkdir()
            calls: list[tuple[str, ...]] = []

            def fake_run(
                cmd: tuple[str, ...], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                self.assertEqual(
                    cmd,
                    ("xcrun", "--sdk", "macosx", "clang", "-print-resource-dir"),
                )
                return subprocess.CompletedProcess(cmd, 0, stdout="/RES\n", stderr="")

            with (
                patch("xcc.host_includes.sys.platform", "darwin"),
                patch.dict("os.environ", {"SDKROOT": str(sdk_root)}, clear=True),
                patch("xcc.host_includes.subprocess.run", side_effect=fake_run),
            ):
                dirs = host_includes.host_system_include_dirs()
        self.assertEqual(
            dirs,
            ("/RES/include", str(sdk_root / "usr" / "include"), "/usr/include"),
        )
        self.assertEqual(len(calls), 1)

    def test_host_system_include_dirs_darwin_prefers_xcc_llc_sibling_clang(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk_root = root / "MacOSX.sdk"
            bin_dir = root / "bin"
            sdk_root.mkdir()
            bin_dir.mkdir()
            llc = bin_dir / "llc"
            clang = bin_dir / "clang"
            llc.touch()
            clang.touch()
            calls: list[tuple[str, ...]] = []

            def fake_run(
                cmd: tuple[str, ...], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                if cmd == (str(clang), "-print-resource-dir"):
                    return subprocess.CompletedProcess(cmd, 0, stdout="/LLVM_RES\n", stderr="")
                raise AssertionError(f"Unexpected resource probe: {cmd!r}")

            with (
                patch("xcc.host_includes.sys.platform", "darwin"),
                patch.dict(
                    "os.environ",
                    {"SDKROOT": str(sdk_root), "XCC_LLC": str(llc)},
                    clear=True,
                ),
                patch("xcc.host_includes.subprocess.run", side_effect=fake_run),
            ):
                dirs = host_includes.host_system_include_dirs()

        self.assertEqual(
            dirs,
            (
                "/LLVM_RES/include",
                str(sdk_root / "usr" / "include"),
                "/usr/include",
            ),
        )
        self.assertEqual(calls, [(str(clang), "-print-resource-dir")])

    def test_host_system_include_dirs_darwin_xcc_llc_without_sibling_clang_uses_xcrun(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk_root = root / "MacOSX.sdk"
            bin_dir = root / "bin"
            sdk_root.mkdir()
            bin_dir.mkdir()
            llc = bin_dir / "llc"
            llc.touch()
            calls: list[tuple[str, ...]] = []

            def fake_run(
                cmd: tuple[str, ...], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                self.assertEqual(
                    cmd,
                    ("xcrun", "--sdk", "macosx", "clang", "-print-resource-dir"),
                )
                return subprocess.CompletedProcess(cmd, 0, stdout="/RES\n", stderr="")

            with (
                patch("xcc.host_includes.sys.platform", "darwin"),
                patch.dict(
                    "os.environ",
                    {"SDKROOT": str(sdk_root), "XCC_LLC": str(llc)},
                    clear=True,
                ),
                patch("xcc.host_includes.subprocess.run", side_effect=fake_run),
            ):
                dirs = host_includes.host_system_include_dirs()

        self.assertEqual(
            dirs,
            ("/RES/include", str(sdk_root / "usr" / "include"), "/usr/include"),
        )
        self.assertEqual(calls, [("xcrun", "--sdk", "macosx", "clang", "-print-resource-dir")])

    def test_host_system_include_dirs_darwin_empty_sibling_clang_output_uses_xcrun(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdk_root = root / "MacOSX.sdk"
            bin_dir = root / "bin"
            sdk_root.mkdir()
            bin_dir.mkdir()
            llc = bin_dir / "llc"
            clang = bin_dir / "clang"
            llc.touch()
            clang.touch()
            calls: list[tuple[str, ...]] = []

            def fake_run(
                cmd: tuple[str, ...], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                if cmd == (str(clang), "-print-resource-dir"):
                    return subprocess.CompletedProcess(cmd, 0, stdout=" \n", stderr="")
                if cmd == ("xcrun", "--sdk", "macosx", "clang", "-print-resource-dir"):
                    return subprocess.CompletedProcess(cmd, 0, stdout="/RES\n", stderr="")
                raise AssertionError(f"Unexpected resource probe: {cmd!r}")

            with (
                patch("xcc.host_includes.sys.platform", "darwin"),
                patch.dict(
                    "os.environ",
                    {"SDKROOT": str(sdk_root), "XCC_LLC": str(llc)},
                    clear=True,
                ),
                patch("xcc.host_includes.subprocess.run", side_effect=fake_run),
            ):
                dirs = host_includes.host_system_include_dirs()

        self.assertEqual(
            dirs,
            ("/RES/include", str(sdk_root / "usr" / "include"), "/usr/include"),
        )
        self.assertEqual(
            calls,
            [
                (str(clang), "-print-resource-dir"),
                ("xcrun", "--sdk", "macosx", "clang", "-print-resource-dir"),
            ],
        )

    def test_host_system_include_dirs_darwin_uses_xcrun_for_sdk_name(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_run(cmd: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if cmd == ("xcrun", "--sdk", "macosx", "--show-sdk-path"):
                return subprocess.CompletedProcess(cmd, 0, stdout="/SDK\n", stderr="")
            if cmd == ("xcrun", "--sdk", "macosx", "clang", "-print-resource-dir"):
                return subprocess.CompletedProcess(cmd, 0, stdout="/RES\n", stderr="")
            raise AssertionError(f"Unexpected xcrun invocation: {cmd!r}")

        with (
            patch("xcc.host_includes.sys.platform", "darwin"),
            patch.dict("os.environ", {"SDKROOT": "macosx"}, clear=True),
            patch("xcc.host_includes.subprocess.run", side_effect=fake_run),
        ):
            dirs = host_includes.host_system_include_dirs()
        self.assertEqual(dirs, ("/RES/include", "/SDK/usr/include", "/usr/include"))
        self.assertEqual(
            calls,
            [
                ("xcrun", "--sdk", "macosx", "--show-sdk-path"),
                ("xcrun", "--sdk", "macosx", "clang", "-print-resource-dir"),
            ],
        )

    def test_host_system_include_dirs_darwin_xcrun_failure_falls_back_to_usr_include(self) -> None:
        def fail_run(*args: object, **kwargs: object) -> None:
            raise OSError("xcrun missing")

        with (
            patch("xcc.host_includes.sys.platform", "darwin"),
            patch.dict("os.environ", {}, clear=True),
            patch("xcc.host_includes.subprocess.run", side_effect=fail_run),
            patch.object(Path, "is_dir", return_value=False),
        ):
            self.assertEqual(host_includes.host_system_include_dirs(), ("/usr/include",))

    def test_host_system_include_dirs_darwin_uses_xcode_filesystem_fallback(self) -> None:
        xcode_base = Path(
            "/Applications/Xcode.app/Contents/Developer/Toolchains/"
            "XcodeDefault.xctoolchain/usr/lib/clang"
        )
        clang_version = xcode_base / "21.0.0"
        sdk_base = Path(
            "/Applications/Xcode.app/Contents/Developer/Platforms/"
            "MacOSX.platform/Developer/SDKs/MacOSX.sdk"
        )
        existing_dirs = {xcode_base, clang_version, sdk_base}

        def fail_run(*args: object, **kwargs: object) -> None:
            raise OSError("xcrun missing")

        def fake_is_dir(path: Path) -> bool:
            return path in existing_dirs

        def fake_iterdir(path: Path):
            self.assertEqual(path, xcode_base)
            return iter((clang_version,))

        with (
            patch("xcc.host_includes.sys.platform", "darwin"),
            patch.dict("os.environ", {}, clear=True),
            patch("xcc.host_includes.subprocess.run", side_effect=fail_run),
            patch.object(Path, "is_dir", fake_is_dir),
            patch.object(Path, "iterdir", fake_iterdir),
        ):
            self.assertEqual(
                host_includes.host_system_include_dirs(),
                (
                    str(clang_version / "include"),
                    str(sdk_base / "usr" / "include"),
                    "/usr/include",
                ),
            )
