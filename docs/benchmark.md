# XCC Frontend Benchmark

This page records the benchmark setup used for the interpreter and compiled
frontend comparison on 2026-06-11.

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

## Results

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
