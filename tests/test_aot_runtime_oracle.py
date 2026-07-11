import unittest

from tests import _bootstrap  # noqa: F401
from xcc.aot import run_native_smoke


class AotRuntimeOracleTests(unittest.TestCase):
    def assert_native_matches_cpython(
        self,
        source: str,
        *,
        expected: int,
        filename: str,
    ) -> None:
        result = run_native_smoke(source, filename=filename, entry="entry")
        self.assertEqual(result.python_result, expected)
        self.assertEqual(result.native_returncode, expected)
        self.assertEqual(result.native_stdout, "")
        self.assertEqual(result.native_stderr, "")

    def test_for_break_continue(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    total: int = 0\n"
            "    for value in (1, 2, 3, 4):\n"
            "        if value == 2:\n"
            "            continue\n"
            "        if value == 4:\n"
            "            break\n"
            "        total = total + value\n"
            "    index: int = 0\n"
            "    while True:\n"
            "        index = index + 1\n"
            "        if index == 3:\n"
            "            break\n"
            "        total = total + index\n"
            "    return total\n",
            expected=7,
            filename="for-break-continue.py",
        )

    def test_tuple_value_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    left: tuple[str, ...] = ('alpha', 'beta')\n"
            "    right: tuple[str, ...] = ('alpha', 'beta')\n"
            "    if left != right:\n"
            "        return 1\n"
            "    pairs: tuple[tuple[str, ...], ...] = (left, ('gamma',))\n"
            "    if right not in pairs:\n"
            "        return 2\n"
            "    return len(left + ('gamma',))\n",
            expected=3,
            filename="tuple-values.py",
        )

    def test_dict_lookup_membership(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: dict[str, int] = {'alpha': 1, 'beta': 2}\n"
            "    values['alpha'] = 3\n"
            "    if 'alpha' not in values:\n"
            "        return 1\n"
            "    if 'missing' in values:\n"
            "        return 2\n"
            "    return values['alpha'] + values['beta']\n",
            expected=5,
            filename="dict-values.py",
        )

    def test_negative_index(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: tuple[int, ...] = (4, 5, 6)\n"
            "    text: str = 'abc'\n"
            "    if values[-1] != 6:\n"
            "        return 1\n"
            "    if text[-2] != 'b':\n"
            "        return 2\n"
            "    return values[-2]\n",
            expected=5,
            filename="negative-index.py",
        )

    def test_try_except_cross_call(self) -> None:
        self.assert_native_matches_cpython(
            "def fail() -> int:\n"
            "    raise ValueError('bad')\n"
            "def middle() -> int:\n"
            "    return fail()\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return middle()\n"
            "    except ValueError:\n"
            "        return 7\n",
            expected=7,
            filename="try-cross-call.py",
        )

    def test_constructor_and_string_bytes_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: tuple[int, ...] = tuple([1, 2, 3])\n"
            "    data: bytes = bytes(4)\n"
            "    encoded: bytes = (65).to_bytes(2, 'big')\n"
            "    text: str = 'alpha,beta'.replace('beta', 'gamma')\n"
            "    if text.split(',')[1] != 'gamma':\n"
            "        return 1\n"
            "    if encoded != b'\\x00A':\n"
            "        return 2\n"
            "    if encoded[-1] != 65:\n"
            "        return 3\n"
            "    return len(values) + len(data)\n",
            expected=7,
            filename="constructors-strings-bytes.py",
        )

    def test_path_value_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "from pathlib import Path\n"
            "def entry() -> int:\n"
            "    left: Path = Path('root/child')\n"
            "    right: Path = Path('root/child')\n"
            "    if left != right:\n"
            "        return 1\n"
            "    if left.name != 'child':\n"
            "        return 2\n"
            "    if left.parent != Path('root'):\n"
            "        return 3\n"
            "    return 0\n",
            expected=0,
            filename="path-values.py",
        )


if __name__ == "__main__":
    unittest.main()
