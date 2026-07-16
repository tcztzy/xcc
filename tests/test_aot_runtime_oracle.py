import unittest
from pathlib import Path

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

    def test_break_preserves_assignments_from_current_iteration(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: list[int] = []\n"
            "    while True:\n"
            "        values.append(7)\n"
            "        break\n"
            "    more: list[int] = []\n"
            "    for value in (8, 9):\n"
            "        more.append(value)\n"
            "        break\n"
            "    return len(values) + len(more)\n",
            expected=2,
            filename="break-current-iteration.py",
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

    def test_tuple_ordering_is_lexicographic_and_uses_prefix_length(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    left: tuple[str, ...] = ('alpha', 'zeta')\n"
            "    right: tuple[str, ...] = ('beta',)\n"
            "    prefix: tuple[str, ...] = ('alpha', 'zeta', 'tail')\n"
            "    if not left < right or not left <= right:\n"
            "        return 1\n"
            "    if not right > left or not right >= left:\n"
            "        return 2\n"
            "    if not left < prefix or not prefix > left:\n"
            "        return 3\n"
            "    if left >= prefix or prefix <= left:\n"
            "        return 4\n"
            "    return len(prefix)\n",
            expected=3,
            filename="tuple-ordering.py",
        )

    def test_starred_tuple_inference_merges_dynamic_item_type(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    tail: tuple[int, ...] = (3, 4)\n"
            "    values = (1, 2, *(value for value in tail))\n"
            "    return len(values) + values[-1]\n",
            expected=8,
            filename="starred-tuple-inference.py",
        )

    def test_three_way_zip_preserves_tuple_values(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    left: tuple[int, ...] = (1, 2)\n"
            "    middle: tuple[int, ...] = (3, 4)\n"
            "    right: tuple[int, ...] = (5, 6)\n"
            "    total = 0\n"
            "    for a, b, c in zip(left, middle, right, strict=True):\n"
            "        total += a + b + c\n"
            "    return total\n",
            expected=21,
            filename="three-way-zip.py",
        )

    def test_unannotated_tuple_repetition_infers_tuple_result(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    unit = (3,)\n"
            "    values = unit * 4\n"
            "    return len(values) + values[-1]\n",
            expected=7,
            filename="tuple-repeat-inference.py",
        )

    def test_list_pop_returns_item_and_mutates_for_positive_and_negative_index(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values = [2, 3, 5]\n"
            "    first = values.pop(0)\n"
            "    last = values.pop(-1)\n"
            "    if values != [3]:\n"
            "        return 1\n"
            "    return first + last + len(values)\n",
            expected=8,
            filename="list-pop-item.py",
        )

    def test_large_list_append_is_alias_visible(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: list[int] = []\n"
            "    alias = values\n"
            "    for value in range(4096):\n"
            "        values.append(value)\n"
            "    if len(alias) != 4096:\n"
            "        return 1\n"
            "    return alias[0] + alias[-1] - 4000\n",
            expected=95,
            filename="list-append-capacity.py",
        )

    def test_long_membership_loop_reuses_entry_stack_slots(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    allowed: set[str] = {'x'}\n"
            "    total = 0\n"
            "    for _ in range(300000):\n"
            "        if 'x' in allowed:\n"
            "            total += 1\n"
            "    return 7 if total == 300000 else 1\n",
            expected=7,
            filename="loop-entry-alloca.py",
        )

    def test_container_alias_lookup_isolated_from_unrelated_growth(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    first: list[int] = []\n"
            "    alias = first\n"
            "    first.append(7)\n"
            "    for value in range(4096):\n"
            "        other = [value]\n"
            "        other.append(value + 1)\n"
            "    total = 0\n"
            "    for _ in range(4096):\n"
            "        total += len(alias)\n"
            "    if total != 4096 or alias[0] != 7:\n"
            "        return 1\n"
            "    return 0\n",
            expected=0,
            filename="container-alias-buckets.py",
        )

    def test_repeated_forwarding_keeps_unrelated_alias_lookups_stable(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: list[int] = []\n"
            "    alias = values\n"
            "    for value in range(4096):\n"
            "        values.append(value)\n"
            "    keepers: list[list[int]] = []\n"
            "    for value in range(8192):\n"
            "        candidate = [value]\n"
            "        keepers.append(candidate)\n"
            "    total = 0\n"
            "    for candidate in keepers:\n"
            "        total += len(candidate)\n"
            "    for _ in range(4096):\n"
            "        total += len(alias)\n"
            "    if total != 16785408 or len(alias) != 4096:\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="container-alias-bucket-update.py",
        )

    def test_capacity_lookup_isolated_from_unrelated_growth(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    keepers: list[list[int]] = []\n"
            "    for value in range(8192):\n"
            "        candidate: list[int] = []\n"
            "        candidate.append(value)\n"
            "        keepers.append(candidate)\n"
            "    values: list[int] = []\n"
            "    alias = values\n"
            "    for value in range(4096):\n"
            "        values.append(value)\n"
            "    total = 0\n"
            "    for candidate in keepers:\n"
            "        total += candidate[0]\n"
            "    if total != 33550336:\n"
            "        return 1\n"
            "    if len(alias) != 4096 or alias[-1] != 4095:\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="container-capacity-buckets.py",
        )

    def test_dynamic_and_negative_list_slice_bounds(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values = [10, 20, 30, 40, 50]\n"
            "    start = 1\n"
            "    stop = len(values) - 1\n"
            "    selected = values[start:stop]\n"
            "    negative = values[-3:-1]\n"
            "    prefix = values[:stop]\n"
            "    suffix = values[start:]\n"
            "    if len(selected) != 3 or len(negative) != 2:\n"
            "        return 1\n"
            "    if len(prefix) != 4 or len(suffix) != 4:\n"
            "        return 2\n"
            "    return selected[0] + selected[-1] + negative[0] + negative[-1] - 130\n",
            expected=0,
            filename="dynamic-negative-list-slice.py",
        )

    def test_break_assignment_preserves_optional_loop_value(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    found = None\n"
            "    for index in range(5):\n"
            "        if index == 3:\n"
            "            found = index\n"
            "            break\n"
            "    if found is None:\n"
            "        return 1\n"
            "    values = [10, 20, 30, 40, 50]\n"
            "    selected = values[:found]\n"
            "    return selected[-1] - 30\n",
            expected=0,
            filename="optional-loop-break-value.py",
        )

    def test_page_aligned_container_growth_keeps_alias_buckets_distributed(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    keepers: list[list[int]] = []\n"
            "    for _ in range(512):\n"
            "        values: list[int] = []\n"
            "        alias = values\n"
            "        for value in range(512):\n"
            "            values.append(value)\n"
            "        keepers.append(alias)\n"
            "    total = 0\n"
            "    for values in keepers:\n"
            "        total += values[-1]\n"
            "    return total - 261632\n",
            expected=0,
            filename="page-aligned-container-alias-hash.py",
        )

    def test_list_slice_assignment_inserts_and_updates_alias(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values = [3, 4]\n"
            "    alias = values\n"
            "    values[0:0] = [1, 2]\n"
            "    values[2:3] = [9]\n"
            "    if alias != [1, 2, 9, 4]:\n"
            "        return 1\n"
            "    return len(values) + values[2]\n",
            expected=13,
            filename="list-slice-assignment.py",
        )

    def test_list_remove_uses_value_equality_and_updates_alias(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values = ['first', 'middle', 'first']\n"
            "    alias = values\n"
            "    values.remove('first')\n"
            "    if alias != ['middle', 'first']:\n"
            "        return 1\n"
            "    return len(values) + len(values[0])\n",
            expected=8,
            filename="list-remove-value.py",
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

    def test_dict_update_overwrites_and_appends(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: dict[str, int] = {'alpha': 1}\n"
            "    incoming: dict[str, int] = {'alpha': 2, 'beta': 3}\n"
            "    values.update(incoming)\n"
            "    return values['alpha'] * 10 + values['beta']\n",
            expected=23,
            filename="dict-update.py",
        )

    def test_dict_setdefault_inserts_once_and_updates_alias(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: dict[str, int] = {'kept': 3}\n"
            "    alias = values\n"
            "    inserted = values.setdefault('new', 7)\n"
            "    existing = values.setdefault('kept', 9)\n"
            "    if inserted != 7 or existing != 3:\n"
            "        return 1\n"
            "    if len(alias) != 2 or alias['new'] != 7 or alias['kept'] != 3:\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="dict-setdefault.py",
        )

    def test_set_intersection_accepts_dict_keys_view(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    functions = {'left': 1, 'right': 2}\n"
            "    targets = set(('right', 'missing')) & functions.keys()\n"
            "    if 'missing' in targets:\n"
            "        return 1\n"
            "    return len(targets) + functions['right']\n",
            expected=3,
            filename="set-intersection-dict-keys.py",
        )

    def test_set_methods_accept_dictionary_key_iterables(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values = set(('left', 'right'))\n"
            "    mapping = {'right': 1, 'other': 2}\n"
            "    remaining = values.difference(mapping)\n"
            "    common = values.intersection(mapping)\n"
            "    combined = remaining.union(common)\n"
            "    changed = combined.symmetric_difference({'missing': 3})\n"
            "    if 'right' not in changed or 'missing' not in changed:\n"
            "        return 1\n"
            "    return len(changed)\n",
            expected=3,
            filename="set-methods-dict-keys.py",
        )

    def test_set_discard_removes_existing_value_and_ignores_missing_value(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values = set(('left', 'right'))\n"
            "    alias = values\n"
            "    values.discard('missing')\n"
            "    values.discard('left')\n"
            "    if 'left' in alias or 'right' not in alias:\n"
            "        return 1\n"
            "    return len(alias)\n",
            expected=1,
            filename="set-discard.py",
        )

    def test_dict_values_preserve_value_iteration(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values = {'left': 2, 'right': 5}\n"
            "    total = 0\n"
            "    for value in values.values():\n"
            "        total += value\n"
            "    return total\n",
            expected=7,
            filename="dict-values-view.py",
        )

    def test_dict_pop_statement_removes_only_existing_key(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: dict[str, int] = {'alpha': 1, 'beta': 2}\n"
            "    values.pop('alpha', None)\n"
            "    values.pop('missing', None)\n"
            "    if 'alpha' in values or 'beta' not in values:\n"
            "        return 1\n"
            "    return values['beta']\n",
            expected=2,
            filename="dict-pop.py",
        )

    def test_constructor_maps_normalized_optional_field_by_parameter(self) -> None:
        self.assert_native_matches_cpython(
            "class Box:\n"
            "    def __init__(\n"
            "        self, ignored: int, values: dict[str, int] | None = None\n"
            "    ) -> None:\n"
            "        self.values = values or {}\n"
            "        self.cache: dict[str, int] = {}\n"
            "def entry() -> int:\n"
            "    box = Box(99, {'answer': 4})\n"
            "    return box.values['answer'] + len(box.cache)\n",
            expected=4,
            filename="constructor-field-map.py",
        )

    def test_constructor_executes_computed_field_initialization(self) -> None:
        self.assert_native_matches_cpython(
            "class Box:\n"
            "    def __init__(self, values: list[int]) -> None:\n"
            "        self.values = values\n"
            "        self.size = len(values)\n"
            "def entry() -> int:\n"
            "    box = Box([3, 4])\n"
            "    alias = box\n"
            "    return alias.size + len(alias.values)\n",
            expected=4,
            filename="constructor-executes-init.py",
        )

    def test_constructor_propagates_initializer_status_to_handler(self) -> None:
        self.assert_native_matches_cpython(
            "class Box:\n"
            "    def __init__(self, value: int) -> None:\n"
            "        if value < 0:\n"
            "            raise ValueError('negative')\n"
            "        self.value = value\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        Box(-1)\n"
            "    except ValueError:\n"
            "        return Box(7).value\n"
            "    return 1\n",
            expected=7,
            filename="constructor-init-status.py",
        )

    def test_zero_argument_super_dispatches_project_base_initializer(self) -> None:
        self.assert_native_matches_cpython(
            "class Base:\n"
            "    def __init__(self, value: int) -> None:\n"
            "        self.value = value\n"
            "class Child(Base):\n"
            "    def __init__(self, value: int) -> None:\n"
            "        super().__init__(value + 1)\n"
            "def entry() -> int:\n"
            "    return Child(6).value\n",
            expected=7,
            filename="project-super-init.py",
        )

    def test_builtin_exception_super_initializer_stays_native(self) -> None:
        self.assert_native_matches_cpython(
            "class Problem(ValueError):\n"
            "    def __init__(self, code: int) -> None:\n"
            "        super().__init__('problem')\n"
            "        self.code = code\n"
            "def entry() -> int:\n"
            "    return Problem(9).code\n",
            expected=9,
            filename="builtin-super-init.py",
        )

    def test_unannotated_homogeneous_tuple_concat_preserves_item_type(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    left = (1, 2)\n"
            "    right = (3, 4)\n"
            "    values = left + right\n"
            "    total: int = 0\n"
            "    for value in values:\n"
            "        total = total + value\n"
            "    return total\n",
            expected=10,
            filename="tuple-concat-inference.py",
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

    def test_large_positive_string_subscript_loop_preserves_negative_index(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    text = 'abcd' * 4096\n"
            "    matches = 0\n"
            "    for index in range(len(text)):\n"
            "        if text[index] == 'd':\n"
            "            matches += 1\n"
            "    if matches != 4096 or text[-1] != 'd':\n"
            "        return 1\n"
            "    return 0\n",
            expected=0,
            filename="string-positive-index.py",
        )

    def test_large_repeated_string_startswith_uses_stable_text_length(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    text = 'abcd' * 4096\n"
            "    matches = 0\n"
            "    for index in range(len(text)):\n"
            "        if text.startswith('bc', index):\n"
            "            matches += 1\n"
            "    if matches != 4096:\n"
            "        return 1\n"
            "    if text.startswith('', len(text) + 1):\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="string-startswith-length-cache.py",
        )

    def test_string_rfind_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    text: str = 'ababa'\n"
            "    if text.rfind('ba') != 3:\n"
            "        return 1\n"
            "    if text.rfind('ba', 0, 4) != 1:\n"
            "        return 2\n"
            "    if text.rfind('ba', -4, -1) != 1:\n"
            "        return 3\n"
            "    if 'abc'.rfind('', 4) != -1:\n"
            "        return 4\n"
            "    if 'abc'.rfind('', 0, -10) != 0:\n"
            "        return 5\n"
            "    return 0\n",
            expected=0,
            filename="string-rfind.py",
        )

    def test_string_count_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    if 'aaaa'.count('aa') != 2:\n"
            "        return 1\n"
            "    if 'aaaa'.count('aa', 1, 4) != 1:\n"
            "        return 2\n"
            "    if 'abc'.count('') != 4:\n"
            "        return 3\n"
            "    if 'abc'.count('', 4) != 0:\n"
            "        return 4\n"
            "    if 'abc'.count('', 0, -10) != 1:\n"
            "        return 5\n"
            "    return 0\n",
            expected=0,
            filename="string-count.py",
        )

    def test_opaque_complex_constructor_truthiness(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    if complex(0.0, 0.0):\n"
            "        return 1\n"
            "    if not complex(0.0, 2.5):\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="complex-truthiness.py",
        )

    def test_string_iteration_yields_characters(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    normalized: str = ''\n"
            "    for ch in 'Ab':\n"
            "        normalized += ch.lower()\n"
            "    if normalized != 'ab':\n"
            "        return 1\n"
            "    return 0\n",
            expected=0,
            filename="string-iteration.py",
        )

    def test_enumerate_string_iteration_yields_indexed_characters(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    normalized: str = ''\n"
            "    total = 0\n"
            "    for index, ch in enumerate('Ab', start=1):\n"
            "        normalized += ch.lower()\n"
            "        total += index\n"
            "    return total if normalized == 'ab' else 1\n",
            expected=3,
            filename="enumerate-string-iteration.py",
        )

    def test_enumerate_bytes_iteration_yields_indexed_integers(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    total = 0\n"
            "    for index, value in enumerate(b'\\x02\\x03', start=1):\n"
            "        total += index * value\n"
            "    return total\n",
            expected=8,
            filename="enumerate-bytes-iteration.py",
        )

    def test_list_clear_preserves_alias_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: list[int] = [1, 2]\n"
            "    alias = values\n"
            "    values.clear()\n"
            "    return len(alias)\n",
            expected=0,
            filename="list-clear.py",
        )

    def test_any_all_generator_predicates(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: list[str | None] = [None, 'x']\n"
            "    if not any(value is not None for value in values):\n"
            "        return 1\n"
            "    if all(value is not None for value in values):\n"
            "        return 2\n"
            "    present: list[str | None] = ['x', 'y']\n"
            "    if not all(value is not None for value in present):\n"
            "        return 3\n"
            "    empty: list[str | None] = []\n"
            "    if any(value is not None for value in empty):\n"
            "        return 4\n"
            "    if not all(value is not None for value in empty):\n"
            "        return 5\n"
            "    return 0\n",
            expected=0,
            filename="any-all-generators.py",
        )

    def test_nested_any_all_generator_predicates(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    left: tuple[int, ...] = (1, 2)\n"
            "    right: tuple[int, ...] = (2, 3)\n"
            "    if not any(a + b == 3 for a in left for b in right):\n"
            "        return 1\n"
            "    if all(a < b for a in left for b in right):\n"
            "        return 2\n"
            "    if not all(a <= b for a in left for b in right):\n"
            "        return 3\n"
            "    return 0\n",
            expected=0,
            filename="nested-any-all-generators.py",
        )

    def test_optional_bool_distinguishes_none_and_false(self) -> None:
        self.assert_native_matches_cpython(
            "def classify(flag: bool) -> int:\n"
            "    value: bool | None = None\n"
            "    while flag:\n"
            "        if value is None:\n"
            "            value = False\n"
            "        if value is None:\n"
            "            return 1\n"
            "        if value != False:\n"
            "            return 2\n"
            "        return 7\n"
            "    return 0\n"
            "def entry() -> int:\n"
            "    if classify(True) != 7:\n"
            "        return 1\n"
            "    if classify(False) != 0:\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="optional-bool.py",
        )

    def test_noreturn_call_propagates_guard_narrowing(self) -> None:
        self.assert_native_matches_cpython(
            "from typing import NoReturn\n"
            "def stop() -> NoReturn:\n"
            "    raise ValueError('bytes required')\n"
            "def require_bytes(value: str | bytes) -> bytes:\n"
            "    if not isinstance(value, bytes):\n"
            "        stop()\n"
            "    return value\n"
            "def entry() -> int:\n"
            "    return len(require_bytes(b'ab'))\n",
            expected=2,
            filename="noreturn-narrowing.py",
        )

    def test_noreturn_call_has_no_success_continuation(self) -> None:
        self.assert_native_matches_cpython(
            "from typing import NoReturn\n"
            "def stop() -> NoReturn:\n"
            "    raise ValueError('stop')\n"
            "def choose(flag: bool) -> int:\n"
            "    if flag:\n"
            "        value = 7\n"
            "    else:\n"
            "        stop()\n"
            "    return value\n"
            "def entry() -> int:\n"
            "    if choose(True) != 7:\n"
            "        return 1\n"
            "    try:\n"
            "        return choose(False)\n"
            "    except ValueError:\n"
            "        return 9\n",
            expected=9,
            filename="noreturn-cfg.py",
        )

    def test_noreturn_else_closes_nested_if_assignment_path(self) -> None:
        self.assert_native_matches_cpython(
            "from typing import NoReturn\n"
            "def stop() -> NoReturn:\n"
            "    raise ValueError('stop')\n"
            "def choose(value: int) -> int:\n"
            "    if value == 1:\n"
            "        selected = 10\n"
            "    elif value == 2:\n"
            "        selected = 20\n"
            "    else:\n"
            "        stop()\n"
            "    return selected\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return choose(1) + choose(2) + choose(0)\n"
            "    except ValueError:\n"
            "        return choose(1) + choose(2)\n",
            expected=30,
            filename="noreturn-nested-if.py",
        )

    def test_assert_never_raises_catchable_assertion_error_status(self) -> None:
        self.assert_native_matches_cpython(
            "from typing import assert_never\n"
            "def classify(value: int) -> int:\n"
            "    if value == 1:\n"
            "        return 7\n"
            "    assert_never(value)\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return classify(2)\n"
            "    except AssertionError:\n"
            "        return classify(1)\n",
            expected=7,
            filename="assert-never-status.py",
        )

    def test_branch_local_assignment_does_not_escape_partial_paths(self) -> None:
        self.assert_native_matches_cpython(
            "def branch(value: int) -> int:\n"
            "    result = 0\n"
            "    if value > 0:\n"
            "        if value == 1:\n"
            "            scratch = 3\n"
            "        else:\n"
            "            result = 1\n"
            "        result = 7\n"
            "    else:\n"
            "        result = 8\n"
            "    return result\n"
            "def entry() -> int:\n"
            "    return branch(2)\n",
            expected=7,
            filename="branch-definite-assignment.py",
        )

    def test_bytes_from_integer_iterable(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: list[int] = [65, 66, 255]\n"
            "    if bytes(values) != b'AB\\xff':\n"
            "        return 1\n"
            "    return 0\n",
            expected=0,
            filename="bytes-from-iterable.py",
        )

    def test_string_endswith_tuple_suffixes(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    if not 'valueJ'.endswith(('j', 'J')):\n"
            "        return 1\n"
            "    if 'valuex'.endswith(('j', 'J')):\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="endswith-tuple.py",
        )

    def test_float_tuple_storage_round_trip(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: list[float] = [1.5, 2.5]\n"
            "    if values[0] != 1.5:\n"
            "        return 1\n"
            "    if values[-1] != 2.5:\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="float-list-storage.py",
        )

    def test_string_isidentifier_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    if not '_alpha2'.isidentifier():\n"
            "        return 1\n"
            "    if '2alpha'.isidentifier():\n"
            "        return 2\n"
            "    if 'bad-name'.isidentifier():\n"
            "        return 3\n"
            "    if ''.isidentifier():\n"
            "        return 4\n"
            "    return 0\n",
            expected=0,
            filename="string-isidentifier.py",
        )

    def test_string_rsplit_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    parts = 'a.b.c'.rsplit('.', 1)\n"
            "    if len(parts) != 2 or parts[0] != 'a.b' or parts[1] != 'c':\n"
            "        return 1\n"
            "    multi = 'ab--cd--ef'.rsplit('--', 1)\n"
            "    if len(multi) != 2 or multi[0] != 'ab--cd' or multi[1] != 'ef':\n"
            "        return 2\n"
            "    unsplit = 'a.b'.rsplit('.', 0)\n"
            "    if len(unsplit) != 1 or unsplit[0] != 'a.b':\n"
            "        return 3\n"
            "    return 0\n",
            expected=0,
            filename="string-rsplit.py",
        )

    def test_string_isupper_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    if not 'TYPE_2'.isupper():\n"
            "        return 1\n"
            "    if 'Type'.isupper():\n"
            "        return 2\n"
            "    if '123'.isupper():\n"
            "        return 3\n"
            "    if ''.isupper():\n"
            "        return 4\n"
            "    return 0\n",
            expected=0,
            filename="string-isupper.py",
        )

    def test_tagged_object_repr_and_isinstance(self) -> None:
        self.assert_native_matches_cpython(
            "def identity(value: object) -> object:\n"
            "    return value\n"
            "def render(value: object) -> str:\n"
            "    return repr(value)\n"
            "def entry() -> int:\n"
            "    if render('Type') != \"'Type'\":\n"
            "        return 1\n"
            "    if render(7) != '7':\n"
            "        return 2\n"
            "    if render(False) != 'False':\n"
            "        return 3\n"
            "    if render(None) != 'None':\n"
            "        return 4\n"
            "    if render(1.5) != '1.5':\n"
            "        return 5\n"
            "    if render(Ellipsis) != 'Ellipsis':\n"
            "        return 6\n"
            "    if not isinstance(identity('x'), str):\n"
            "        return 7\n"
            "    if isinstance(identity(7), str):\n"
            "        return 8\n"
            "    if not isinstance(identity(7), int):\n"
            "        return 9\n"
            "    if not isinstance(identity(False), int):\n"
            "        return 10\n"
            "    return 0\n",
            expected=0,
            filename="tagged-object.py",
        )

    def test_nullable_record_boxed_as_object_preserves_none(self) -> None:
        self.assert_native_matches_cpython(
            "class Node:\n"
            "    pass\n"
            "def maybe(flag: bool) -> Node | None:\n"
            "    if flag:\n"
            "        return Node()\n"
            "    return None\n"
            "def accepts(value: object) -> bool:\n"
            "    return isinstance(value, Node)\n"
            "def entry() -> int:\n"
            "    if accepts(maybe(False)):\n"
            "        return 1\n"
            "    if not accepts(maybe(True)):\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="nullable-record-object.py",
        )

    def test_branch_join_preserves_nullable_record_for_object_boxing(self) -> None:
        self.assert_native_matches_cpython(
            "class Node:\n"
            "    pass\n"
            "def accepts(value: object) -> bool:\n"
            "    return isinstance(value, Node)\n"
            "def choose(flag: bool) -> bool:\n"
            "    item: Node | None = None\n"
            "    if flag:\n"
            "        item = Node()\n"
            "    return accepts(item)\n"
            "def entry() -> int:\n"
            "    if choose(False):\n"
            "        return 1\n"
            "    if not choose(True):\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="branch-joined-nullable-record.py",
        )

    def test_branch_join_preserves_nullable_base_record_for_object_boxing(self) -> None:
        self.assert_native_matches_cpython(
            "class Node:\n"
            "    pass\n"
            "class Leaf(Node):\n"
            "    pass\n"
            "def accepts(value: object) -> bool:\n"
            "    return isinstance(value, Node)\n"
            "def choose(flag: bool) -> bool:\n"
            "    item: Node | None = None\n"
            "    if flag:\n"
            "        item = Leaf()\n"
            "    return accepts(item)\n"
            "def entry() -> int:\n"
            "    if choose(False):\n"
            "        return 1\n"
            "    if not choose(True):\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="branch-joined-nullable-base-record.py",
        )

    def test_isinstance_accepts_pep604_type_union(self) -> None:
        self.assert_native_matches_cpython(
            "class Node:\n"
            "    pass\n"
            "class Name(Node):\n"
            "    pass\n"
            "class Attribute(Node):\n"
            "    pass\n"
            "def accepts(value: Node) -> bool:\n"
            "    return isinstance(value, Name | Attribute)\n"
            "def entry() -> int:\n"
            "    if not accepts(Name()):\n"
            "        return 1\n"
            "    if not accepts(Attribute()):\n"
            "        return 2\n"
            "    if accepts(Node()):\n"
            "        return 3\n"
            "    return 0\n",
            expected=0,
            filename="isinstance-pep604.py",
        )

    def test_sorted_tuple_and_dict_with_static_key(self) -> None:
        self.assert_native_matches_cpython(
            "def string_length(value: str) -> int:\n"
            "    return len(value)\n"
            "def entry() -> int:\n"
            "    values: list[str] = sorted(\n"
            "        ('aa', 'b', 'ccc'), key=string_length, reverse=True\n"
            "    )\n"
            "    if values != ['ccc', 'aa', 'b']:\n"
            "        return 1\n"
            "    mapping: dict[str, int] = {'beta': 2, 'alpha': 1}\n"
            "    keys: list[str] = sorted(mapping)\n"
            "    if keys != ['alpha', 'beta']:\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="sorted-values.py",
        )

    def test_continue_narrows_optional_record(self) -> None:
        self.assert_native_matches_cpython(
            "class Item:\n"
            "    def __init__(self, value: int) -> None:\n"
            "        self.value = value\n"
            "def entry() -> int:\n"
            "    values: tuple[Item | None, ...] = (Item(1), None, Item(2))\n"
            "    total: int = 0\n"
            "    for value in values:\n"
            "        if value is None:\n"
            "            continue\n"
            "        total = total + value.value\n"
            "    return total\n",
            expected=3,
            filename="continue-optional-record.py",
        )

    def test_union_attribute_dispatches_field_and_property(self) -> None:
        self.assert_native_matches_cpython(
            "class Stored:\n"
            "    def __init__(self, value: int) -> None:\n"
            "        self.padding = 99\n"
            "        self.value = value\n"
            "class Computed:\n"
            "    @property\n"
            "    def value(self) -> int:\n"
            "        return 4\n"
            "def select(stored: bool) -> Stored | Computed:\n"
            "    if stored:\n"
            "        return Stored(3)\n"
            "    return Computed()\n"
            "def read(value: Stored | Computed) -> int:\n"
            "    return value.value\n"
            "def entry() -> int:\n"
            "    selected = select(True)\n"
            "    computed = select(False)\n"
            "    return read(selected) + read(computed) + selected.value + computed.value\n",
            expected=14,
            filename="union-field-property.py",
        )

    def test_any_all_generator_unpack_tuple_target(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    pairs: tuple[tuple[int, int], ...] = ((1, 1), (2, 3))\n"
            "    if not any(left != right for left, right in pairs):\n"
            "        return 1\n"
            "    if all(left == right for left, right in pairs):\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="generator-unpack.py",
        )

    def test_eager_comprehension_values_filters_and_set_deduplication(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: list[int] = [value * 2 for value in (1, 2, 3) if value != 2]\n"
            "    if values != [2, 6]:\n"
            "        return 1\n"
            "    generated: tuple[int, ...] = tuple(value + 1 for value in (1, 2, 3))\n"
            "    if generated != (2, 3, 4):\n"
            "        return 2\n"
            "    unique: set[int] = {value for value in (2, 1, 2)}\n"
            "    if len(unique) != 2 or 1 not in unique or 2 not in unique:\n"
            "        return 3\n"
            "    return 0\n",
            expected=0,
            filename="comprehensions.py",
        )

    def test_outer_comprehension_filter_precedes_inner_iterable(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: tuple[int, ...] = (0, 2)\n"
            "    result = tuple(\n"
            "        normalized\n"
            "        for value in values\n"
            "        if value != 0\n"
            "        for normalized in (10 // value,)\n"
            "    )\n"
            "    if result != (5,):\n"
            "        return 1\n"
            "    return 0\n",
            expected=0,
            filename="comprehension-filter-order.py",
        )

    def test_union_resolves_inherited_property(self) -> None:
        self.assert_native_matches_cpython(
            "class Base:\n"
            "    @property\n"
            "    def line(self) -> int:\n"
            "        return 5\n"
            "class First(Base):\n"
            "    pass\n"
            "class Second(Base):\n"
            "    pass\n"
            "def read(value: First | Second) -> int:\n"
            "    return value.line\n"
            "def entry() -> int:\n"
            "    return read(First()) + read(Second())\n",
            expected=10,
            filename="inherited-property.py",
        )

    def test_nested_union_alias_narrows_to_concrete_record(self) -> None:
        self.assert_native_matches_cpython(
            "class Left:\n"
            "    def __init__(self, value: int) -> None:\n"
            "        self.value = value\n"
            "class Right:\n"
            "    pass\n"
            "Choice = Left | Right\n"
            "def read(value: Choice | None) -> int:\n"
            "    if not isinstance(value, Left):\n"
            "        return 0\n"
            "    return value.value\n"
            "def entry() -> int:\n"
            "    return read(Left(3)) + read(Right()) + read(None)\n",
            expected=3,
            filename="nested-union-alias.py",
        )

    def test_inline_nonempty_dict_literal_infers_get_types(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    value: str | None = {'left': 'x', 'right': 'yy'}.get('right')\n"
            "    if value is None:\n"
            "        return 1\n"
            "    return len(value)\n",
            expected=2,
            filename="inline-dict-get.py",
        )

    def test_dict_get_uses_explicit_default_only_for_missing_key(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: dict[str, int] = {'known': 3}\n"
            "    return values.get('missing', 7) + values.get('known', 7)\n",
            expected=10,
            filename="dict-get-default.py",
        )

    def test_set_binary_operations_preserve_value_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    left: set[int] = {1, 2, 2}\n"
            "    right: set[int] = {2, 3}\n"
            "    union: set[int] = left | right\n"
            "    intersection: set[int] = left & right\n"
            "    difference: set[int] = left - right\n"
            "    symmetric: set[int] = left ^ right\n"
            "    if len(union) != 3 or 1 not in union or 3 not in union:\n"
            "        return 1\n"
            "    if len(intersection) != 1 or 2 not in intersection:\n"
            "        return 2\n"
            "    if len(difference) != 1 or 1 not in difference:\n"
            "        return 3\n"
            "    if len(symmetric) != 2 or 1 not in symmetric or 3 not in symmetric:\n"
            "        return 4\n"
            "    return 0\n",
            expected=0,
            filename="set-binary.py",
        )

    def test_direct_set_equality_is_unordered_and_ignores_duplicates(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    if {part.strip() for part in 'int|None'.split('|')} != {'None', 'int'}:\n"
            "        return 1\n"
            "    if {1, 1, 2} != {2, 1}:\n"
            "        return 2\n"
            "    if {'a', 'b'} == {'a', 'c'}:\n"
            "        return 3\n"
            "    if {'a'} == {'a', 'b'}:\n"
            "        return 4\n"
            "    return 7\n",
            expected=7,
            filename="set-equality.py",
        )

    def test_unannotated_set_union_infers_literal_element_type(self) -> None:
        self.assert_native_matches_cpython(
            "def extend(seen: frozenset[str]) -> int:\n"
            "    nested = seen | {'beta'}\n"
            "    return len(nested)\n"
            "def entry() -> int:\n"
            "    return extend(frozenset({'alpha'}))\n",
            expected=2,
            filename="set-union-inference.py",
        )

    def test_container_constructor_preserves_set_intersection_type(self) -> None:
        self.assert_native_matches_cpython(
            "def overlap(values: set[str], names: set[str]) -> int:\n"
            "    if frozenset(values) & names:\n"
            "        return len(frozenset(values) & names)\n"
            "    return 0\n"
            "def entry() -> int:\n"
            "    return overlap({'alpha', 'beta'}, {'beta', 'gamma'})\n",
            expected=1,
            filename="container-constructor-set-intersection.py",
        )

    def test_container_constructors_iterate_dict_keys(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: dict[str, int] = {'pkg': 1, 'pkg.helper': 2}\n"
            "    frozen = frozenset(values)\n"
            "    listed = list(values)\n"
            "    if len(frozen) != 2 or 'pkg.helper' not in frozen:\n"
            "        return 1\n"
            "    if listed != ['pkg', 'pkg.helper']:\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="container-from-dict.py",
        )

    def test_nested_enumerate_target_in_dict_comprehension(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    pairs: tuple[tuple[int, int], ...] = ((10, 20), (30, 40))\n"
            "    indexes: dict[int, int] = {\n"
            "        name: index\n"
            "        for index, (name, _value) in enumerate(pairs, start=4)\n"
            "    }\n"
            "    return indexes[10] * 10 + indexes[30]\n",
            expected=45,
            filename="nested-enumerate-comprehension.py",
        )

    def test_string_upper_conversion_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    if 'aZ_1'.upper() != 'AZ_1':\n"
            "        return 1\n"
            "    if ''.upper() != '':\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="string-upper.py",
        )

    def test_string_repetition_in_comparison_preserves_string_type(self) -> None:
        self.assert_native_matches_cpython(
            "def quoted(text: str, index: int) -> bool:\n"
            "    quote = text[index]\n"
            "    return text[index:index + 3] == quote * 3\n"
            "def entry() -> int:\n"
            "    return 7 if quoted(\"'''value\", 0) else 1\n",
            expected=7,
            filename="string-repeat-compare.py",
        )

    def test_fstring_list_literal_preserves_string_element_type(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n    lines = [f'value={7}']\n    return len(lines[0])\n",
            expected=7,
            filename="fstring-list.py",
        )

    def test_integer_fstring_hex_format_matches_cpython_bytes(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    rendered = f'{10:02X}:{255:02x}:{-10:02X}'\n"
            "    return 0 if rendered == '0A:ff:-A' else 1\n",
            expected=0,
            filename="fstring-hex.py",
        )

    def test_ord_arithmetic_in_conditional_expression_stays_integer(self) -> None:
        self.assert_native_matches_cpython(
            "def digit(ch: str) -> int:\n"
            "    return (\n"
            "        ord(ch) - ord('0')\n"
            "        if '0' <= ch <= '9'\n"
            "        else ord(ch.lower()) - ord('a') + 10\n"
            "    )\n"
            "def entry() -> int:\n"
            "    return digit('f')\n",
            expected=15,
            filename="ord-ifexp.py",
        )

    def test_unannotated_integer_invert_ignores_string_return_fallback(self) -> None:
        self.assert_native_matches_cpython(
            "uint32 = int\n"
            "def render(value: uint32) -> str:\n"
            "    inverted = (~value) & 0xFFFFFFFF\n"
            "    return 'ok' if inverted == 0xFFFFFFF0 else 'bad'\n"
            "def entry() -> int:\n"
            "    return len(render(0xF))\n",
            expected=2,
            filename="integer-invert-inference.py",
        )

    def test_unsigned_word_shift_accepts_dynamic_int_count(self) -> None:
        self.assert_native_matches_cpython(
            "uint32 = int\n"
            "def shift(value: uint32, count: int) -> uint32:\n"
            "    return (value >> count) & 0xFFFFFFFF\n"
            "def entry() -> int:\n"
            "    return 7 if shift(0x80000000, 4) == 0x08000000 else 1\n",
            expected=7,
            filename="uint32-dynamic-shift.py",
        )

    def test_owned_sha256_matches_known_vector_natively(self) -> None:
        path = Path(__file__).resolve().parents[1] / "src/xcc/aot/sha256.py"
        source = path.read_text(encoding="utf-8")
        source += (
            "\n\ndef entry() -> int:\n"
            "    return 7 if sha256_hex(b'abc') == "
            "'ba7816bf8f01cfea414140de5dae2223"
            "b00361a396177a9cb410ff61f20015ad' else 1\n"
        )
        self.assert_native_matches_cpython(
            source,
            expected=7,
            filename=str(path),
        )

    def test_conditional_expression_evaluates_only_selected_string_arm(self) -> None:
        self.assert_native_matches_cpython(
            "def qualify(owner: str | None, name: str) -> str:\n"
            "    return owner + '.' + name if owner is not None else name\n"
            "def entry() -> int:\n"
            "    if qualify(None, 'main') != 'main':\n"
            "        return 1\n"
            "    return 7 if qualify('demo', 'main') == 'demo.main' else 2\n",
            expected=7,
            filename="lazy-string-ifexp.py",
        )

    def test_conditional_optional_string_remains_nullable_for_truthiness(self) -> None:
        self.assert_native_matches_cpython(
            "def choose(flag: bool, fallback: str) -> str:\n"
            "    value = 'present' if flag else None\n"
            "    return value or fallback\n"
            "def entry() -> int:\n"
            "    return len(choose(False, 'end')) + len(choose(True, 'end'))\n",
            expected=10,
            filename="optional-string-ifexp-or.py",
        )

    def test_local_optional_string_or_in_void_function_infers_string_result(self) -> None:
        self.assert_native_matches_cpython(
            "def append_label(flag: bool, lines: list[str]) -> None:\n"
            "    optional = 'else' if flag else None\n"
            "    end = 'end'\n"
            "    selected = optional or end\n"
            "    lines.append(f'%{selected}')\n"
            "def entry() -> int:\n"
            "    lines: list[str] = []\n"
            "    append_label(False, lines)\n"
            "    return len(lines[0])\n",
            expected=4,
            filename="local-optional-string-or.py",
        )

    def test_narrowed_string_add_overrides_object_field_context(self) -> None:
        self.assert_native_matches_cpython(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Box:\n"
            "    value: object\n"
            "def combine(left: object, right: object) -> Box:\n"
            "    if isinstance(left, str) and isinstance(right, str):\n"
            "        return Box(left + right)\n"
            "    return Box('')\n"
            "def entry() -> int:\n"
            "    value = combine('a', 'b').value\n"
            "    if not isinstance(value, str):\n"
            "        return 1\n"
            "    return len(value) + 5\n",
            expected=7,
            filename="narrowed-string-add.py",
        )

    def test_and_chain_none_narrows_optional_scalar_attributes(self) -> None:
        self.assert_native_matches_cpython(
            "class TypeInfo:\n"
            "    def __init__(self, bits: int | None, signed: bool | None) -> None:\n"
            "        self.bits = bits\n"
            "        self.signed = signed\n"
            "class IntType:\n"
            "    def __init__(self, bits: int, signed: bool) -> None:\n"
            "        self.bits = bits\n"
            "        self.signed = signed\n"
            "def convert(type_info: TypeInfo) -> IntType:\n"
            "    if type_info.bits is not None and type_info.signed is not None:\n"
            "        return IntType(type_info.bits, type_info.signed)\n"
            "    return IntType(0, False)\n"
            "def entry() -> int:\n"
            "    result = convert(TypeInfo(32, False))\n"
            "    if result.signed:\n"
            "        return 1\n"
            "    return result.bits\n",
            expected=32,
            filename="and-none-scalar-attributes.py",
        )

    def test_conditional_empty_list_infers_typed_nonempty_arm(self) -> None:
        self.assert_native_matches_cpython(
            "def collect(args: str) -> int:\n"
            "    call_args = [] if not args else [args]\n"
            "    call_args.append('tail')\n"
            "    return len(call_args)\n"
            "def entry() -> int:\n"
            "    return collect('') * 10 + collect('head')\n",
            expected=12,
            filename="conditional-empty-list.py",
        )

    def test_optional_integer_field_distinguishes_zero_from_none(self) -> None:
        self.assert_native_matches_cpython(
            "class Span:\n"
            "    def __init__(self, column: int | None = None) -> None:\n"
            "        self.column = column\n"
            "    @property\n"
            "    def required_column(self) -> int:\n"
            "        if self.column is None:\n"
            "            raise AttributeError('missing column')\n"
            "        return self.column\n"
            "def entry() -> int:\n"
            "    zero = Span(0)\n"
            "    seven = Span(7)\n"
            "    if zero.required_column:\n"
            "        return 1\n"
            "    return seven.required_column\n",
            expected=7,
            filename="optional-int-field-zero.py",
        )

    def test_optional_integer_return_boxes_negative_value(self) -> None:
        self.assert_native_matches_cpython(
            "def maybe(value: int) -> int | None:\n"
            "    return -value\n"
            "def entry() -> int:\n"
            "    result = maybe(7)\n"
            "    if result is None:\n"
            "        return 1\n"
            "    return result + 10\n",
            expected=3,
            filename="optional-int-unary.py",
        )

    def test_optional_integer_or_fallback_unboxes_truthy_value(self) -> None:
        self.assert_native_matches_cpython(
            "def fallback(value: int | None) -> int:\n"
            "    return value or 0\n"
            "def entry() -> int:\n"
            "    return fallback(None) + fallback(0) + fallback(7)\n",
            expected=7,
            filename="optional-int-or.py",
        )

    def test_optional_integer_assignment_narrows_then_merges(self) -> None:
        self.assert_native_matches_cpython(
            "def use(value: int) -> int:\n"
            "    return value\n"
            "def choose(flag: bool) -> tuple[int | None, int]:\n"
            "    selected: int | None = None\n"
            "    if flag:\n"
            "        selected = 3\n"
            "        close = use(selected)\n"
            "    else:\n"
            "        close = 0\n"
            "    return selected, close\n"
            "def entry() -> int:\n"
            "    present, close = choose(True)\n"
            "    missing, empty = choose(False)\n"
            "    if present is None or missing is not None:\n"
            "        return 1\n"
            "    return present + close + empty + 1\n",
            expected=7,
            filename="optional-int-flow.py",
        )

    def test_exiting_positive_isinstance_narrows_union_complement(self) -> None:
        self.assert_native_matches_cpython(
            "class Handler:\n"
            "    def __init__(self, status: int) -> None:\n"
            "        self.status = status\n"
            "class Finalizer:\n"
            "    def __init__(self, body: int) -> None:\n"
            "        self.body = body\n"
            "_Scope = Handler | Finalizer\n"
            "def body_or_zero(scope: _Scope) -> int:\n"
            "    if isinstance(scope, Handler):\n"
            "        return 0\n"
            "    return scope.body\n"
            "def entry() -> int:\n"
            "    return body_or_zero(Finalizer(7))\n",
            expected=7,
            filename="positive-isinstance-complement.py",
        )

    def test_else_branch_narrows_isinstance_union_complement(self) -> None:
        self.assert_native_matches_cpython(
            "class Named:\n"
            "    def __init__(self, name: str) -> None:\n"
            "        self.name = name\n"
            "class Sized:\n"
            "    def __init__(self, size: int) -> None:\n"
            "        self.size = size\n"
            "Value = Named | Sized\n"
            "def measure(value: Value) -> int:\n"
            "    if isinstance(value, Named):\n"
            "        return len(value.name)\n"
            "    else:\n"
            "        return value.size\n"
            "def entry() -> int:\n"
            "    return measure(Sized(9))\n",
            expected=9,
            filename="isinstance-else-complement.py",
        )

    def test_joined_isinstance_branches_restore_union_type(self) -> None:
        self.assert_native_matches_cpython(
            "class Named:\n"
            "    def __init__(self, name: str) -> None:\n"
            "        self.name = name\n"
            "class Sized:\n"
            "    def __init__(self, size: int) -> None:\n"
            "        self.size = size\n"
            "Value = Named | Sized\n"
            "def measure(value: Value) -> int:\n"
            "    if isinstance(value, Named):\n"
            "        tag = 1\n"
            "    else:\n"
            "        tag = 2\n"
            "    if isinstance(value, Named):\n"
            "        return tag + len(value.name)\n"
            "    return tag + value.size\n"
            "def entry() -> int:\n"
            "    return measure(Named('x')) * 10 + measure(Sized(3))\n",
            expected=25,
            filename="isinstance-branch-join.py",
        )

    def test_min_max_reduce_nonempty_generator(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: tuple[int, ...] = (7, 2, 5)\n"
            "    return max(value for value in values) * 10 + min(\n"
            "        value for value in values\n"
            "    )\n",
            expected=72,
            filename="min-max-generator.py",
        )

    def test_nested_set_comprehension_flattens_and_deduplicates(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    groups: tuple[tuple[int, ...], ...] = ((1, 2), (2, 3))\n"
            "    values = {value for group in groups for value in group}\n"
            "    return len(values) * 10 + sum_value(values)\n"
            "def sum_value(values: set[int]) -> int:\n"
            "    result = 0\n"
            "    for value in values:\n"
            "        result += value\n"
            "    return result\n",
            expected=36,
            filename="nested-set-comprehension.py",
        )

    def test_global_literal_map_resolves_named_scalar_values(self) -> None:
        self.assert_native_matches_cpython(
            "FIRST = 4\n"
            "SECOND = 7\n"
            "VALUES = {'one': (FIRST,), 'kept': (FIRST, SECOND)}\n"
            "def entry() -> int:\n"
            "    values = VALUES.get('kept', ())\n"
            "    return len(VALUES.get('one', ())) * 100 + values[0] * 10 + values[1]\n",
            expected=147,
            filename="global-named-literal-map.py",
        )

    def test_set_update_preserves_value_deduplication(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: set[int] = {1}\n"
            "    alias = values\n"
            "    values.update({1: 'one', 2: 'two', 3: 'three'})\n"
            "    if len(values) != 3 or len(alias) != 3:\n"
                "        return 1\n"
            "    return len(alias) * 10 + (2 if 2 in alias else 0)\n",
            expected=32,
            filename="set-update.py",
        )

    def test_list_append_mutation_is_visible_across_call(self) -> None:
        self.assert_native_matches_cpython(
            "def append_line(lines: list[str]) -> None:\n"
            "    lines.append('beta')\n"
            "def entry() -> int:\n"
            "    lines: list[str] = ['alpha']\n"
            "    append_line(lines)\n"
            "    return len(lines)\n",
            expected=2,
            filename="cross-call-list-append.py",
        )

    def test_dict_and_set_mutations_are_visible_across_call(self) -> None:
        self.assert_native_matches_cpython(
            "def update(values: dict[str, int], names: set[str]) -> None:\n"
            "    values['beta'] = 2\n"
            "    names.add('beta')\n"
            "def entry() -> int:\n"
            "    values: dict[str, int] = {'alpha': 1}\n"
            "    names: set[str] = {'alpha'}\n"
            "    update(values, names)\n"
            "    return len(values) * 10 + len(names) * 2 + values['beta']\n",
            expected=26,
            filename="cross-call-dict-set.py",
        )

    def test_dict_copy_snapshots_forwarded_mutations(self) -> None:
        self.assert_native_matches_cpython(
            "def update(values: dict[str, int]) -> None:\n"
            "    values['beta'] = 2\n"
            "def entry() -> int:\n"
            "    values: dict[str, int] = {'alpha': 1}\n"
            "    update(values)\n"
            "    copied = dict(values)\n"
            "    values['gamma'] = 3\n"
            "    return len(copied) * 100 + copied['beta'] * 10 + len(values)\n",
            expected=223,
            filename="dict-copy-forwarded.py",
        )

    def test_dict_copy_and_update_preserve_record_base_values(self) -> None:
        self.assert_native_matches_cpython(
            "class ValueType:\n"
            "    pass\n"
            "class TupleType(ValueType):\n"
            "    pass\n"
            "def merge(values: dict[str, ValueType]) -> None:\n"
            "    incoming = dict(values)\n"
            "    values.update(incoming)\n"
            "def entry() -> int:\n"
            "    values: dict[str, ValueType] = {'seen': TupleType()}\n"
            "    merge(values)\n"
            "    return 7 if isinstance(values['seen'], TupleType) else 1\n",
            expected=7,
            filename="dict-copy-record-base.py",
        )

    def test_branch_join_preserves_record_union_for_shared_field_access(self) -> None:
        self.assert_native_matches_cpython(
            "class Call:\n"
            "    def __init__(self, target: str, type_value: int) -> None:\n"
            "        self.target = target\n"
            "        self.type_value = type_value\n"
            "class Binary:\n"
            "    def __init__(\n"
            "        self, op: str, left: int, right: int, type_value: int\n"
            "    ) -> None:\n"
            "        self.op = op\n"
            "        self.left = left\n"
            "        self.right = right\n"
            "        self.type_value = type_value\n"
            "Expr = Call | Binary\n"
            "def choose(call: bool) -> int:\n"
            "    if call:\n"
            "        result: Expr = Call('target', 7)\n"
            "    else:\n"
            "        result = Binary('+', 1, 2, 9)\n"
            "    return result.type_value\n"
            "def entry() -> int:\n"
            "    return choose(True) * 10 + choose(False)\n",
            expected=79,
            filename="branch-joined-record-union-field.py",
        )

    def test_bool_infers_set_intersection_operand_independently(self) -> None:
        self.assert_native_matches_cpython(
            "def intersects(left: set[int], right: set[int]) -> bool | None:\n"
            "    return bool(left & right)\n"
            "def entry() -> int:\n"
            "    return 7 if intersects({1, 2}, {2, 3}) else 1\n",
            expected=7,
            filename="bool-set-intersection.py",
        )

    def test_nested_dict_comprehension_builds_cross_product(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    keys: tuple[int, ...] = (1, 2)\n"
            "    offsets: tuple[int, ...] = (0, 10)\n"
            "    values = {\n"
            "        key + offset: key\n"
            "        for offset in offsets\n"
            "        for key in keys\n"
            "    }\n"
            "    return len(values) * 10 + values[12]\n",
            expected=42,
            filename="nested-dict-comprehension.py",
        )

    def test_dict_comprehension_infers_record_constructor_values(self) -> None:
        self.assert_native_matches_cpython(
            "class Param:\n"
            "    def __init__(self, name: str, kind: int) -> None:\n"
            "        self.name = name\n"
            "        self.kind = kind\n"
            "class Emitted:\n"
            "    def __init__(self, value: str, kind: int) -> None:\n"
            "        self.value = value\n"
            "        self.kind = kind\n"
            "def entry() -> int:\n"
            "    params: tuple[Param, ...] = (Param('argc', 7), Param('argv', 9))\n"
            "    values = {\n"
            "        param.name: Emitted('%' + param.name, param.kind)\n"
            "        for param in params\n"
            "    }\n"
            "    value = values.get('argc')\n"
            "    if value is None:\n"
            "        return 1\n"
            "    return value.kind\n",
            expected=7,
            filename="dict-comprehension-record-values.py",
        )

    def test_exact_type_identity(self) -> None:
        self.assert_native_matches_cpython(
            "def identity(value: object) -> object:\n"
            "    return value\n"
            "def entry() -> int:\n"
            "    if type(identity(7)) is not int:\n"
            "        return 1\n"
            "    if type(identity(False)) is int:\n"
            "        return 2\n"
            "    if type(identity(False)) is not bool:\n"
            "        return 3\n"
            "    if type(identity(None)) is not type(None):\n"
            "        return 4\n"
            "    if type(identity('x')) is not str:\n"
            "        return 5\n"
            "    return 0\n",
            expected=0,
            filename="exact-type.py",
        )

    def test_exact_type_name_uses_runtime_record_union_member(self) -> None:
        self.assert_native_matches_cpython(
            "class Equal:\n"
            "    pass\n"
            "class NotEqual:\n"
            "    pass\n"
            "Operation = Equal | NotEqual\n"
            "def type_name(value: Operation) -> str:\n"
            "    return type(value).__name__\n"
            "def entry() -> int:\n"
            "    if type_name(Equal()) != 'Equal':\n"
            "        return 1\n"
            "    if type_name(NotEqual()) != 'NotEqual':\n"
            "        return 2\n"
            "    return 0\n",
            expected=0,
            filename="exact-type-name-record-union.py",
        )

    def test_one_argument_int_parses_decimal_string(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n    return int('32')\n",
            expected=32,
            filename="one-argument-int.py",
        )

    def test_frozen_dataclass_equality_compares_record_fields(self) -> None:
        self.assert_native_matches_cpython(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class IntegerType:\n"
            "    bits: int\n"
            "    signed: bool\n"
            "def entry() -> int:\n"
            "    left = IntegerType(32, True)\n"
            "    right = IntegerType(32, True)\n"
            "    return 7 if left == right else 1\n",
            expected=7,
            filename="frozen-dataclass-equality.py",
        )

    def test_record_union_equality_dispatches_and_compares_nested_fields(self) -> None:
        self.assert_native_matches_cpython(
            "from dataclasses import dataclass\n"
            "@dataclass(frozen=True)\n"
            "class IntegerType:\n"
            "    bits: int\n"
            "@dataclass(frozen=True)\n"
            "class SequenceType:\n"
            "    element: IntegerType\n"
            "ValueType = IntegerType | SequenceType\n"
            "def equal(left: ValueType, right: ValueType) -> bool:\n"
            "    return left == right\n"
            "def entry() -> int:\n"
            "    if not equal(SequenceType(IntegerType(32)), SequenceType(IntegerType(32))):\n"
            "        return 1\n"
            "    if equal(IntegerType(32), SequenceType(IntegerType(32))):\n"
            "        return 2\n"
            "    return 7\n",
            expected=7,
            filename="record-union-equality.py",
        )

    def test_exact_type_guard_narrows_true_branch(self) -> None:
        self.assert_native_matches_cpython(
            "def exact_int(value: object) -> int:\n"
            "    if type(value) is int:\n"
            "        return value\n"
            "    return 0\n"
            "def entry() -> int:\n"
            "    return exact_int(7) + exact_int(False)\n",
            expected=7,
            filename="exact-type-guard.py",
        )

    def test_tagged_object_bool_identity(self) -> None:
        self.assert_native_matches_cpython(
            "def identity(value: object) -> object:\n"
            "    return value\n"
            "def entry() -> int:\n"
            "    if identity(True) is not True:\n"
            "        return 1\n"
            "    if identity(False) is True:\n"
            "        return 2\n"
            "    if identity(1) is True:\n"
            "        return 3\n"
            "    return 0\n",
            expected=0,
            filename="object-bool-identity.py",
        )

    def test_and_chain_none_narrowing_reaches_true_branch(self) -> None:
        self.assert_native_matches_cpython(
            "class Annotation:\n"
            "    text: str\n"
            "class Argument:\n"
            "    annotation: Annotation | None\n"
            "class Arguments:\n"
            "    vararg: Argument | None\n"
            "def annotation_text(args: Arguments) -> str:\n"
            "    if args.vararg is not None and args.vararg.annotation is not None:\n"
            "        return args.vararg.annotation.text\n"
            "    return ''\n"
            "def entry() -> int:\n"
            "    annotation = Annotation()\n"
            "    annotation.text = 'ok'\n"
            "    argument = Argument()\n"
            "    argument.annotation = annotation\n"
            "    args = Arguments()\n"
            "    args.vararg = argument\n"
            "    return len(annotation_text(args))\n",
            expected=2,
            filename="and-none-branch.py",
        )

    def test_dict_comprehension_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def increment(values: dict[str, int]) -> dict[str, int]:\n"
            "    return {name: value + 1 for name, value in values.items() if value > 0}\n"
            "def entry() -> int:\n"
            "    result = increment({'skip': 0, 'kept': 4})\n"
            "    if 'skip' in result:\n"
            "        return 1\n"
            "    return result['kept']\n",
            expected=5,
            filename="dict-comprehension.py",
        )

    def test_homogeneous_tuple_assignment(self) -> None:
        self.assert_native_matches_cpython(
            "def add_pair(values: tuple[int, ...]) -> int:\n"
            "    left, right = values\n"
            "    return left + right\n"
            "def entry() -> int:\n"
            "    return add_pair((2, 3))\n",
            expected=5,
            filename="homogeneous-tuple-assignment.py",
        )

    def test_global_literal_dict_lookup(self) -> None:
        self.assert_native_matches_cpython(
            "WIDTHS = {'i8': (8, True), 'u16': (16, False)}\n"
            "def lookup(name: str) -> tuple[int, bool] | None:\n"
            "    return WIDTHS.get(name)\n"
            "def entry() -> int:\n"
            "    value = lookup('u16')\n"
            "    if value is None:\n"
            "        return 1\n"
            "    bits, signed = value\n"
            "    if signed:\n"
            "        return 2\n"
            "    return bits\n",
            expected=16,
            filename="global-literal-dict.py",
        )

    def test_global_literal_dict_merges_empty_nested_tuple(self) -> None:
        self.assert_native_matches_cpython(
            "TABLE = {\n"
            "    'none': ('zero', ()),\n"
            "    'one': ('single', ('value',)),\n"
            "}\n"
            "def entry() -> int:\n"
            "    return len(TABLE['none'][1]) + len(TABLE['one'][1])\n",
            expected=1,
            filename="global-empty-nested-tuple.py",
        )

    def test_global_container_constructor_and_starred_reference(self) -> None:
        self.assert_native_matches_cpython(
            "BASE = frozenset({'alpha', 'beta'})\n"
            "ALL = {'gamma', *BASE}\n"
            "def entry() -> int:\n"
            "    if 'alpha' not in ALL or 'gamma' not in ALL:\n"
            "        return 1\n"
            "    return len(ALL)\n",
            expected=3,
            filename="global-starred-container.py",
        )

    def test_equivalent_tuple_list_union_preserves_nested_dict_type(self) -> None:
        self.assert_native_matches_cpython(
            "def total(\n"
            "    values: tuple[tuple[str, dict[str, int]], ...]\n"
            "    | list[tuple[str, dict[str, int]]],\n"
            ") -> int:\n"
            "    result = 0\n"
            "    for name, mapping in values:\n"
            "        result += mapping.get(name, 0)\n"
            "    return result\n"
            "def entry() -> int:\n"
            "    return total([('answer', {'answer': 7})])\n",
            expected=7,
            filename="tuple-list-union.py",
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

    def test_try_except_catches_exception_returned_by_factory(self) -> None:
        self.assert_native_matches_cpython(
            "class Problem(ValueError):\n"
            "    pass\n"
            "def make_problem() -> Problem:\n"
            "    return Problem()\n"
            "def fail() -> int:\n"
            "    raise make_problem()\n"
            "def entry() -> int:\n"
            "    try:\n"
            "        return fail()\n"
            "    except Problem:\n"
            "        return 9\n",
            expected=9,
            filename="try-factory-exception.py",
        )

    def test_constructor_and_string_bytes_semantics(self) -> None:
        self.assert_native_matches_cpython(
            "def entry() -> int:\n"
            "    values: tuple[int, ...] = tuple([1, 2, 3])\n"
            "    data: bytes = bytes(4)\n"
            "    encoded: bytes = (65).to_bytes(2, 'big')\n"
            "    padded: bytes = encoded[:1].ljust(3, b'Z')\n"
            "    combined: bytes = b'A' + b'B' * 2\n"
            "    text_bytes: bytes = 'AB'.encode()\n"
            "    byte_total: int = 0\n"
            "    for byte in b'\\x01\\x02':\n"
            "        byte_total += byte\n"
            "    text: str = 'alpha,beta'.replace('beta', 'gamma')\n"
            "    if text.split(',')[1] != 'gamma':\n"
            "        return 1\n"
            "    if encoded != b'\\x00A':\n"
            "        return 2\n"
            "    if encoded[-1] != 65:\n"
            "        return 3\n"
            "    if padded != b'\\x00ZZ' or len(padded) != 3:\n"
            "        return 4\n"
            "    if combined != b'ABB':\n"
            "        return 5\n"
            "    if text_bytes != b'AB':\n"
            "        return 6\n"
            "    if byte_total != 3:\n"
            "        return 7\n"
            "    return len(values) + len(data)\n",
            expected=7,
            filename="constructors-strings-bytes.py",
        )

    def test_bytes_subscripts_preserve_explicit_unsigned_word_width(self) -> None:
        self.assert_native_matches_cpython(
            "uint32 = int\n"
            "def word(data: bytes) -> uint32:\n"
            "    return (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]\n"
            "def entry() -> int:\n"
            "    return 7 if word(b'\\x12\\x34\\x56\\x78') == 0x12345678 else 1\n",
            expected=7,
            filename="bytes-uint32-word.py",
        )

    def test_unannotated_bytes_concat_ignores_string_return_fallback(self) -> None:
        self.assert_native_matches_cpython(
            "def render(data: bytes) -> str:\n"
            "    message = data + b'x'\n"
            "    message += b'y'\n"
            "    return 'ok' if message == b'axy' else 'bad'\n"
            "def entry() -> int:\n"
            "    return len(render(b'a'))\n",
            expected=2,
            filename="bytes-concat-string-return.py",
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

    def test_path_record_field_uses_path_value_type(self) -> None:
        self.assert_native_matches_cpython(
            "from dataclasses import dataclass\n"
            "from pathlib import Path\n"
            "@dataclass(frozen=True)\n"
            "class Source:\n"
            "    path: Path\n"
            "def entry() -> int:\n"
            "    source = Source(Path('root/child.py'))\n"
            "    return len(str(source.path))\n",
            expected=13,
            filename="path-record-field.py",
        )


if __name__ == "__main__":
    unittest.main()
