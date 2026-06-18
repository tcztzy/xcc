# XCC Performance Profiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce XCC frontend runtime on real CPython C translation units using a profile-first optimization loop.

**Architecture:** Use CPython source files as the representative workload, cProfile for hotspot discovery, and `scripts/benchmark_xcc.py` for wall-clock before/after measurements. Keep runtime code stdlib-only and preserve the public `FrontendResult.pp_tokens` attribute by making unnecessary work lazy rather than removing behavior.

**Tech Stack:** Python 3.11+ standard library, XCC frontend/preprocessor/parser, CPython source tree, `uv`, `tox`, local `gcc` and `clang` commands.

---

### Task 1: Baseline Profile And Benchmark

**Files:**
- Read: `/Users/tcztzy/GitHub/xcc/scripts/benchmark_xcc.py`
- Output: `/Users/tcztzy/GitHub/xcc/build/profile/baseline-getcompiler.prof`
- Output: `/Users/tcztzy/GitHub/xcc/build/benchmark/baseline-cpython-sample.json`

- [x] **Step 1: Run cProfile on a real CPython translation unit**

```bash
PYTHONPATH=src uv run python - <<'PY'
import cProfile
from xcc import main

argv = [
    "--frontend", "-std=gnu11", "-DPy_BUILD_CORE",
    "-I", "../cpython", "-I", "../cpython/Include", "-I", "../cpython/Include/internal",
    "../cpython/Python/getcompiler.c",
]
prof = cProfile.Profile()
prof.enable()
code = main(argv)
prof.disable()
if code != 0:
    raise SystemExit(code)
prof.dump_stats("build/profile/baseline-getcompiler.prof")
PY
```

- [x] **Step 2: Run the CPython wall-clock baseline**

```bash
uv run python scripts/benchmark_xcc.py \
  --cpython ../cpython \
  --source Python/getcompiler.c \
  --source Modules/_json.c \
  --source Objects/listobject.c \
  --runs 1 \
  --warmups 0 \
  --json build/benchmark/baseline-cpython-sample.json
```

Expected baseline observed before implementation: `pure` ran in `59.396` seconds for the three-source sample.

### Task 2: Lazy Preprocessor Token Materialization

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/frontend.py`
- Test: `/Users/tcztzy/GitHub/xcc/tests/test_frontend.py`
- Test: `/Users/tcztzy/GitHub/xcc/tests/test_cli.py`

- [x] **Step 1: Replace eager `pp_tokens` storage with a cached property**

```python
@dataclass(frozen=True)
class FrontendResult:
    filename: str
    source: str
    preprocessed_source: str
    tokens: list[Token]
    unit: TranslationUnit
    sema: SemaUnit
    include_trace: tuple[str, ...]
    macro_table: tuple[str, ...]
    _pp_tokens: list[Token] | None = None

    @property
    def pp_tokens(self) -> list[Token]:
        tokens = self._pp_tokens
        if tokens is None:
            tokens = lex_pp(self.preprocessed_source)
            object.__setattr__(self, "_pp_tokens", tokens)
        return tokens
```

- [x] **Step 2: Keep `compile_source()` behavior while avoiding the extra scan**

```python
return FrontendResult(
    filename,
    source,
    pp_result.source,
    tokens,
    unit,
    sema,
    pp_result.include_trace,
    pp_result.macro_table,
)
```

- [x] **Step 3: Run focused frontend and CLI tests**

```bash
uv run python -m unittest tests.test_frontend tests.test_cli -v
```

Expected: all tests pass, including tests that read `result.pp_tokens` or `--dump-pp-tokens`.

Observed: `uv run python -m unittest tests.test_preprocessor tests.test_frontend tests.test_cli -v` passed, 462 tests in 26.737 seconds.

### Task 2.5: Guard Preprocessor Macro Tokenization

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/preprocessor/__init__.py`
- Test: `/Users/tcztzy/GitHub/xcc/tests/test_preprocessor.py`

- [x] **Step 1: Add a cheap identifier candidate scan before full macro tokenization**

```python
def _line_needs_macro_expansion(self, text: str) -> bool:
    has_identifier = False
    for match in _IDENT_RE.finditer(text):
        has_identifier = True
        if match.group(0) in self._macros:
            return True
    if self._macros.keys() <= _PREDEFINED_MACRO_NAMES:
        return False
    return has_identifier
```

- [x] **Step 2: Preserve token-rendered spacing when user/header macros exist**

The first attempt skipped every line without a macro-name hit and failed tests
that expect `int ok ;` style token-rendered spacing. The accepted version skips
only lines that cannot affect observable token rendering.

- [x] **Step 3: Run preprocessor tests**

```bash
uv run python -m unittest tests.test_preprocessor -v
```

Observed: 345 tests passed in 6.384 seconds.

### Task 3: Reduce Parser Punctuation Checks

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/src/xcc/parser/expressions.py`
- Test: `/Users/tcztzy/GitHub/xcc/tests/test_parser.py`
- Test: `/Users/tcztzy/GitHub/xcc/tests/test_frontend.py`

- [x] **Step 1: Replace generator-based binary operator checks**

```python
def parse_binary_left_associative(
    parser: object,
    operand_name: str,
    operators: tuple[str, ...],
) -> Expr:
    operand = getattr(parser, operand_name)
    expr = operand()
    while True:
        token = parser._current()  # type: ignore
        if token.kind != TokenKind.PUNCTUATOR or token.lexeme not in operators:
            return expr
        op = str(token.lexeme)
        parser._advance()  # type: ignore
        right = operand()
        expr = BinaryExpr(op, expr, right)
```

- [x] **Step 2: Apply the same direct-token check to unary and postfix loops**

```python
token = parser._current()  # type: ignore
if token.kind == TokenKind.PUNCTUATOR and token.lexeme in _UNARY_PUNCTUATORS:
    op = str(token.lexeme)
    parser._advance()  # type: ignore
    operand = parser._parse_unary()  # type: ignore
    return UnaryExpr(op, operand)
```

- [x] **Step 3: Run parser-focused tests**

```bash
uv run python -m unittest tests.test_parser tests.test_frontend -v
```

Expected: parser behavior remains unchanged.

Observed: focused parser/frontend/CLI tests passed, but the CPython benchmark
loop did not show a reliable throughput win and became harder to interpret. The
parser change was reverted; final code keeps the original parser punctuation
checks.

### Task 4: Re-profile, Benchmark, And Compare Toolchains

**Files:**
- Output: `/Users/tcztzy/GitHub/xcc/build/profile/optimized-getcompiler.prof`
- Output: `/Users/tcztzy/GitHub/xcc/build/benchmark/optimized-cpython-sample.json`
- Output: `/Users/tcztzy/GitHub/xcc/build/benchmark/gcc-clang-cpython-syntax.json`

- [x] **Step 1: Re-run the same cProfile command with optimized output path**

```bash
PYTHONPATH=src uv run python - <<'PY'
import cProfile
from xcc import main

argv = [
    "--frontend", "-std=gnu11", "-DPy_BUILD_CORE",
    "-I", "../cpython", "-I", "../cpython/Include", "-I", "../cpython/Include/internal",
    "../cpython/Python/getcompiler.c",
]
prof = cProfile.Profile()
prof.enable()
code = main(argv)
prof.disable()
if code != 0:
    raise SystemExit(code)
prof.dump_stats("build/profile/optimized-getcompiler.prof")
PY
```

- [x] **Step 2: Re-run the same three-source benchmark**

```bash
uv run python scripts/benchmark_xcc.py \
  --cpython ../cpython \
  --source Python/getcompiler.c \
  --source Modules/_json.c \
  --source Objects/listobject.c \
  --runs 1 \
  --warmups 0 \
  --json build/benchmark/optimized-cpython-sample.json
```

- [x] **Step 3: Compare local `gcc` and `clang` on the same CPython files**

```bash
uv run python - <<'PY'
import json
import subprocess
import time
from pathlib import Path

sources = [
    "Python/getcompiler.c",
    "Modules/_json.c",
    "Objects/listobject.c",
]
root = Path("../cpython")
common = [
    "-fsyntax-only",
    "-std=gnu11",
    "-DPy_BUILD_CORE",
    "-I", str(root),
    "-I", str(root / "Include"),
    "-I", str(root / "Include" / "internal"),
]
payload = {}
for tool in ("gcc", "clang"):
    started = time.perf_counter()
    results = []
    for source in sources:
        cmd = [tool, *common, str(root / source)]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        results.append({"source": source, "returncode": completed.returncode})
        if completed.returncode != 0:
            raise SystemExit(completed.stderr + completed.stdout)
    payload[tool] = {"elapsed": time.perf_counter() - started, "results": results}
Path("build/benchmark/gcc-clang-cpython-syntax.json").write_text(
    json.dumps(payload, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(payload, indent=2))
PY
```

Expected: both local commands accept the same CPython files; on macOS, `/usr/bin/gcc` may report Apple clang.

Observed:
- cProfile on `Python/getcompiler.c`: 49.608 seconds baseline, 17.690 seconds optimized.
- `lex_pp` cumulative time: 17.296 seconds baseline, 3.521 seconds optimized.
- three-source baseline completed once at 59.396 seconds before edits; optimized three-source and `Objects/listobject.c` subprocess reruns were interrupted after exceeding the iteration budget.
- in-process optimized `Python/getcompiler.c` timings were 45.128, 12.590, and 6.843 seconds, showing large cold/warm cache differences.
- local `gcc` is Apple clang 21.0.0 and accepted all three CPython files in 0.872 seconds.
- Homebrew `clang` 22.1.7 accepted all three CPython files in 0.656 seconds.
- 2026-06-18 retest: performance comparison uses the mypyc-precompiled XCC
  import tree. Rebuilt `bench-mypyc` on `Objects/listobject.c` measured
  4.608, 4.592, and 4.510 seconds. Real GCC was `/opt/homebrew/bin/gcc-15`,
  not `/usr/bin/gcc`; `gcc-15 -fsyntax-only Objects/listobject.c` measured
  0.187, 0.176, and 0.181 seconds, and Homebrew clang measured 0.140, 0.118,
  and 0.140 seconds.

### Task 5: Integration And Handoff Gates

**Files:**
- Modify: `/Users/tcztzy/GitHub/xcc/docs/benchmark.md`
- Modify: `/Users/tcztzy/GitHub/xcc/docs/optimization.en.md`
- Modify: `/Users/tcztzy/GitHub/xcc/docs/optimization.zh.md`
- Modify: `/Users/tcztzy/GitHub/xcc/CHANGELOG.md`
- Modify: `/Users/tcztzy/GitHub/xcc/LESSONS.md`

- [x] **Step 1: Run CPython integration through a clean configured tree**

```bash
mkdir -p build/cpython-xcc-final-20260618-post-gnu-return
cd build/cpython-xcc-final-20260618-post-gnu-return
XCC_LLC=/opt/homebrew/opt/llvm/bin/llc \
  CC=/Users/tcztzy/GitHub/xcc/.venv/bin/xcc \
  /Users/tcztzy/GitHub/xcc/build/cpython-src-clean/configure
XCC_LLC=/opt/homebrew/opt/llvm/bin/llc make -j1
```

Observed:
- `XCC_LLC=/opt/homebrew/opt/llvm/bin/llc uv run xcc --target=llvm -c ... ../cpython/Python/getcompiler.c -o build/benchmark/getcompiler-xcc.o` passed.
- The clean full build completed with exit code 0. CPython checked 116 modules:
  37 built-in, 78 shared, 1 missing `_gdbm` local dependency, and 0 failed
  imports.
- The full build exposed two compatibility failures not covered by the earlier
  three-file smoke: OpenSSL `const char **` output pointers passing through
  `void *`, and GNU `__extension__ __alignof__(expr)` under C11. Both were
  minimized against GCC and Clang, fixed generically, and then revalidated by
  the clean build above.

- [x] **Step 2: Update documentation and lessons with measured numbers**

Record the baseline, optimized benchmark, cProfile hotspot movement, gcc/clang comparison, integration result, repeated issue class, and root cause.

- [x] **Step 3: Run handoff gates**

```bash
uv run python -m unittest discover -v
uv run tox -e lint
uv run tox -e type
```

Expected: unit tests, lint, and type checks pass before handoff, or any environmental failure is documented precisely.

Observed:
- `uv run python -m unittest discover -v`: 2253 tests passed, 10 skipped, in 48.670 seconds.
- `uv run tox -e lint`: passed.
- `uv run tox -e type`: passed.
