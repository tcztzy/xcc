# XCC Frontend Benchmark

This page records the benchmark setup used for the interpreter and compiled
frontend comparison. The latest retest in this file was run on 2026-06-18.

The benchmark measures XCC frontend throughput by running `xcc.main()` over
configured CPython C source files. Each measured run starts a fresh Python
subprocess, imports XCC through a selected `PYTHONPATH`, redirects frontend
stdout/stderr, and records elapsed wall-clock seconds with
`time.perf_counter()`.

## Machine

| Item | Value |
| --- | --- |
| Host | Apple MacBook Air |
| OS | macOS 26.5.1, build 25F80 |
| Kernel | Darwin 25.5.0 arm64 |
| CPU | Apple M2 |
| CPU count | 8 |
| Memory | 16 GiB |
| XCC checkout | `60c9b25c` plus the benchmark working-tree changes in this commit |
| CPython checkout | `../cpython` at `0f1f7c78898` |
| CPython configuration | `../cpython/pyconfig.h` present |

The local LLVM installation had a broken Homebrew linkage during this run:
`/opt/homebrew/Cellar/llvm/22.1.6/lib/libLLVM.dylib` referenced
`/opt/homebrew/opt/z3/lib/libz3.4.15.dylib`, while the installed Z3 was 4.16.
This affected full backend/unit-test runs that invoke Homebrew LLVM tools, but
not the frontend benchmark below.

## Tooling

| Tool | Version |
| --- | --- |
| `uv` | 0.11.7 |
| `tox` | 4.54.0 |
| `tox-uv` | 1.35.2 |

Interpreter matrix:

| Label | Version |
| --- | --- |
| `py311` | CPython 3.11.15 |
| `py312` | CPython 3.12.13 |
| `py313` | CPython 3.13.13 |
| `py314` | CPython 3.14.4 |
| `pypy311` | PyPy 7.3.21, Python 3.11.15 |
| `graalpy311` | GraalPy 3.11.7, Oracle GraalVM Native 24.2.2 |
| `graalpy312` | GraalPy 3.12.8, Oracle GraalVM Native 25.0.2 |

The compiled variants run on CPython 3.11:

| Label | Import Tree |
| --- | --- |
| `cython` | `build/cython/lib`, Cython extension modules named `*.cpython-311-darwin.so` |
| `mypyc` | `build/mypyc/lib`, mypyc extension modules named `*.cpython-311-darwin.so` |

For toolchain performance comparisons, the XCC number must use the `mypyc`
compiled import tree. Pure-Python XCC timings are still useful for development
diagnostics, but they are not the representative XCC-vs-GCC-vs-Clang number.
On this macOS host, `/usr/bin/gcc` is an Apple Clang wrapper; use
`/opt/homebrew/bin/gcc-15` when a real GCC comparison is required.

## Benchmark Commands

The measured sample was a single configured CPython source file:
`Objects/listobject.c`.

Pure interpreter matrix:

```bash
uv run tox -e bench-py311,bench-py312,bench-py313,bench-py314,bench-pypy311,bench-graalpy311,bench-graalpy312 -- --source Objects/listobject.c --runs 3 --warmups 1
```

Compiled CPython 3.11 variants:

```bash
uv run tox -e bench-cython,bench-mypyc -- --source Objects/listobject.c --runs 3 --warmups 1 --skip-build
```

`--skip-build` means the Cython and mypyc import trees were reused from the
existing `build/` directory. Rebuild them before measuring fresh compiled
artifacts:

```bash
uv run python scripts/cythonize_xcc.py --clean --force
uv run python scripts/mypycize_xcc.py --clean --force
```

Omit `--source Objects/listobject.c` to run the default five-file CPython
sample:

- `Objects/listobject.c`
- `Objects/dictobject.c`
- `Python/compile.c`
- `Parser/parser.c`
- `Modules/_json.c`

This frontend benchmark is deliberately separate from real-project build
validation. For a clean CPython `configure && make` check with XCC as `CC`, run:

```bash
uv run tox -e cpython-build -- /path/to/cpython
```

That tox gate rebuilds `build/mypyc/lib` and prepends it to `PYTHONPATH` before
running CPython's configure/make path, so the real-project check uses the
first-tier mypyc import tree instead of the pure-Python frontend.

## Results

### 2026-06-17 Profile-Guided Frontend Optimization

This run used a profiling -> optimizing -> profiling loop on the configured
CPython tree at `../cpython`. The stable cProfile sample was
`Python/getcompiler.c`, which is small as a source file but still pulls in the
real CPython header stack. Larger `Objects/listobject.c` runs were attempted,
but the subprocess benchmark became too slow and noisy for iteration on this
machine, so the completed before/after comparison below uses the smaller real
CPython translation unit.

Commands:

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

Profile comparison:

| Metric | Baseline | Optimized | Change |
| --- | ---: | ---: | ---: |
| cProfile total time | 49.608 s | 17.690 s | 2.80x faster |
| Function calls | 47,746,647 | 37,295,989 | 21.9% fewer |
| `preprocess_source` cumulative | 25.420 s | 12.177 s | 2.09x faster |
| `lex_pp` cumulative | 17.296 s | 3.521 s | 4.91x faster |
| `Lexer.tokenize` cumulative | 19.390 s | 5.964 s | 3.25x faster |

The accepted changes were deliberately small:

- `FrontendResult.pp_tokens` is now materialized lazily, so ordinary compile
  paths no longer re-lex the full preprocessed translation unit unless a caller
  asks for preprocessor tokens.
- `_Preprocessor._line_needs_macro_expansion()` now uses a cheap identifier
  candidate scan before calling the full preprocessor lexer. To preserve legacy
  output formatting, lines containing ordinary identifiers still take the old
  token-rendering path once non-predefined macros exist; the shortcut applies
  only where it cannot change visible spacing.

One attempted parser micro-optimization was reverted. Replacing
`any(parser._check_punct(...))` with direct token checks passed focused parser
tests, but did not produce a reliable win on the CPython benchmark loop and
made the profiling signal harder to interpret. The profiling loop kept the
change out of the final patch.

Integration and toolchain checks:

| Check | Result |
| --- | --- |
| `XCC_LLC=/opt/homebrew/opt/llvm/bin/llc uv run xcc --target=llvm -c ... Python/getcompiler.c` | passed; wrote `build/benchmark/getcompiler-xcc.o` |
| `/opt/homebrew/bin/gcc-15 -fsyntax-only` on `Objects/listobject.c` | passed; median 0.181 s over 3 measured runs |
| `/opt/homebrew/opt/llvm/bin/clang -fsyntax-only` on `Objects/listobject.c` | passed; median 0.140 s over 3 measured runs |
| clean CPython out-of-tree `configure && make -j1` with `CC=/Users/tcztzy/GitHub/xcc/.venv/bin/xcc` and `XCC_LLC=/opt/homebrew/opt/llvm/bin/llc` | passed in `build/cpython-xcc-final-20260618-post-gnu-return`; checked 116 modules: 37 built-in, 78 shared, 1 missing `_gdbm` local dependency, 0 failed imports |

The repeated issue in this optimization cycle was mistaking local hot-looking
code for the true workload bottleneck. CPython-scale frontend time was dominated
by repeated preprocessing tokenization and cold include/configuration work, not
by a single parser punctuation branch. Optimizations that bypass tokenization
also have to respect the preprocessor's token-rendered spacing behavior, which
is observable in existing tests.

The 2026-06-18 clean CPython retest also showed why partial verification is not
enough. Three-object smoke checks missed later failures in `_ssl.c` and
`_testcapimodule.c`: OpenSSL macros pass `const char **` through `void *`, and
CPython uses GNU `__extension__ __alignof__(expr)` while compiling as C11.
Both cases matched GCC/Clang behavior after minimization, so the fixes were
made as generic C/GNU compatibility changes and then validated by a fresh
full build.

Single-file `Objects/listobject.c`, three measured runs after one warmup:

| Variant | Times (s) | Median (s) | Min (s) | Speed vs `py311` |
| --- | ---: | ---: | ---: | ---: |
| `py311` | 9.387, 9.190, 8.890 | 9.190 | 8.890 | 1.00x |
| `py312` | 8.700, 8.314, 7.913 | 8.314 | 7.913 | 1.11x |
| `py313` | 9.357, 8.472, 8.662 | 8.662 | 8.472 | 1.06x |
| `py314` | 7.626, 7.924, 7.671 | 7.671 | 7.626 | 1.20x |
| `pypy311` | 7.852, 7.596, 7.765 | 7.765 | 7.596 | 1.18x |
| `graalpy311` | 95.852, 95.124, 81.845 | 95.124 | 81.845 | 0.10x |
| `graalpy312` | 20.629, 28.695, 27.986 | 27.986 | 20.629 | 0.33x |
| `cython` | 6.123, 5.817, 5.793 | 5.817 | 5.793 | 1.58x |
| `mypyc` | 4.349, 4.362, 3.988 | 4.349 | 3.988 | 2.11x |

2026-06-18 retest after rebuilding the mypyc import tree:

| Tool | Workload | Times (s) | Median (s) | Min (s) |
| --- | --- | ---: | ---: | ---: |
| `xcc` via `bench-mypyc` | frontend on `Objects/listobject.c` | 4.608, 4.592, 4.510 | 4.592 | 4.510 |
| `gcc-15` | `-fsyntax-only Objects/listobject.c` | 0.187, 0.176, 0.181 | 0.181 | 0.176 |
| Homebrew `clang` | `-fsyntax-only Objects/listobject.c` | 0.140, 0.118, 0.140 | 0.140 | 0.118 |

This table is a frontend/syntax benchmark, not a full object-code throughput
comparison. XCC is measured through the mypyc-precompiled frontend; GCC and
Clang are measured through syntax-only checks on the same configured CPython
source file.

## Interpretation

On this sample, `mypyc` was the fastest measured variant, at about 2.1x the
CPython 3.11 pure-Python baseline. The Cython import tree was also faster than
the baseline, at about 1.6x.

Among pure interpreters, CPython 3.14 and PyPy 3.11 were close on this workload,
both around 1.2x faster than CPython 3.11. GraalPy was much slower in this
subprocess-per-run frontend workload, especially GraalPy 3.11.

These numbers should be read as a focused frontend micro-benchmark, not as a
full compiler throughput result. The default five-file CPython sample and full
CPython build workflows are larger and may change the ranking.

## Reproducibility Notes

- The benchmark does not include Cython or mypyc extension build time when
  `--skip-build` is used.
- `PYTHONDONTWRITEBYTECODE=1` is set for measured subprocesses.
- Each timed run imports XCC from scratch in a new subprocess.
- The pure benchmark tox environments use `package = "skip"` and
  `no_default_groups = true`; they do not install the dev dependency group.
- The compiled benchmark tox environments use the dev dependency group so that
  Cython and mypyc build tools are available when `--skip-build` is not used.
- JSON output from the run is written under `build/benchmark/*.json`.
