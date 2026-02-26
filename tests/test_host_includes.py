import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401
from xcc import host_includes


class HostIncludesTests(unittest.TestCase):
    def setUp(self) -> None:
        host_includes._host_system_include_dirs.cache_clear()

    def test_is_pathlike(self) -> None:
        self.assertFalse(host_includes._is_pathlike("macosx"))
        self.assertTrue(host_includes._is_pathlike("/SDKs/MacOSX.sdk"))
        self.assertTrue(host_includes._is_pathlike(r"C:\SDKs\MacOSX.sdk"))

    def test_dedupe_in_order(self) -> None:
        self.assertEqual(host_includes._dedupe_in_order(["a", "a", "b", "a"]), ("a", "b"))

    def test_xcrun_stdout_returns_none_for_empty_output(self) -> None:
        completed = subprocess.CompletedProcess(("xcrun",), 0, stdout=" \n", stderr="")
        with patch("xcc.host_includes.subprocess.run", return_value=completed):
            self.assertIsNone(host_includes._xcrun_stdout("--version"))

    def test_host_system_include_dirs_non_darwin_returns_empty(self) -> None:
        with patch("xcc.host_includes.sys.platform", "linux"):
            with patch("xcc.host_includes.subprocess.run") as run:
                self.assertEqual(host_includes.host_system_include_dirs(), ())
        run.assert_not_called()

    def test_host_system_include_dirs_darwin_uses_sdkroot_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sdk_root = Path(tmp) / "MacOSX.sdk"
            sdk_root.mkdir()
            calls: list[tuple[str, ...]] = []

            def fake_run(cmd: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(cmd)
                self.assertEqual(
                    cmd,
                    ("xcrun", "--sdk", "macosx", "clang", "-print-resource-dir"),
                )
                return subprocess.CompletedProcess(cmd, 0, stdout="/RES\n", stderr="")

            with patch("xcc.host_includes.sys.platform", "darwin"):
                with patch.dict("os.environ", {"SDKROOT": str(sdk_root)}, clear=False):
                    with patch("xcc.host_includes.subprocess.run", side_effect=fake_run):
                        dirs = host_includes.host_system_include_dirs()
        self.assertEqual(
            dirs,
            ("/RES/include", str(sdk_root / "usr" / "include"), "/usr/include"),
        )
        self.assertEqual(len(calls), 1)

    def test_host_system_include_dirs_darwin_uses_xcrun_for_sdk_name(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_run(cmd: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if cmd == ("xcrun", "--sdk", "macosx", "--show-sdk-path"):
                return subprocess.CompletedProcess(cmd, 0, stdout="/SDK\n", stderr="")
            if cmd == ("xcrun", "--sdk", "macosx", "clang", "-print-resource-dir"):
                return subprocess.CompletedProcess(cmd, 0, stdout="/RES\n", stderr="")
            raise AssertionError(f"Unexpected xcrun invocation: {cmd!r}")

        with patch("xcc.host_includes.sys.platform", "darwin"):
            with patch.dict("os.environ", {"SDKROOT": "macosx"}, clear=False):
                with patch("xcc.host_includes.subprocess.run", side_effect=fake_run):
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

        with patch("xcc.host_includes.sys.platform", "darwin"):
            with patch.dict("os.environ", {}, clear=True):
                with patch("xcc.host_includes.subprocess.run", side_effect=fail_run):
                    self.assertEqual(host_includes.host_system_include_dirs(), ("/usr/include",))

