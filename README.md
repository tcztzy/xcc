# XCC

XCC is a working C11 compiler written in Python. It uses only the Python
standard library at runtime and can be used as a `CC` driver for real build
systems: CPython builds with `CC="xcc" ./configure && make` on the supported
targets. The implementation is still compact and readable, but the validation
bar is CPython-scale C rather than toy examples.

## Pipeline

```
.c → [preprocessor → lexer → parser → sema] → target assembly
   → assembler/linker when object or executable output is requested
```

- `--target=llvm`: emit LLVM IR and lower objects through a discovered LLVM
  `llc` executable
- `--target=aarch64-apple-darwin`: emit native Darwin AArch64 assembly directly
- `--target=x86_64-linux-gnu`: emit native ELF x86_64 SysV assembly directly
- `-S`: write target assembly; for `llvm`, this is textual LLVM IR
- `-c`: write an object file

On x86_64 Linux hosts, the driver defaults to `x86_64-linux-gnu`; otherwise it
defaults to `llvm`.

For the LLVM target, XCC looks for `llc` through `XCC_LLC`, `LLVM_CONFIG`, and
`PATH`. A candidate is accepted only after `llc --help` prints the LLVM `llc`
help text on stdout, so an unrelated same-name program is not used
accidentally.

## Status

- CPython: all three targets are verified at `CC="xcc" ./configure && make`
  scale, without CPython-specific compiler fallback paths
- Frontend: preprocesses, parses, and analyzes real C translation units plus
  the CPython-relevant GNU extensions encountered in system headers
- Targets: LLVM IR, native Darwin AArch64, and native x86_64 Linux all have
  working object/link driver paths
- Platform: macOS ARM64 and x86_64 Linux; optional CPython extension modules
  still depend on the local system libraries available to the build

## Commands

- Install: `uv sync --dev`
- CPython build: `CC="xcc" ./configure && make`
- CPython with explicit target:
  `CC="xcc --target=aarch64-apple-darwin" ./configure && make`
- Lint: `uv run tox -e lint`
- Type check: `uv run tox -e type`
- Test: `uv run python -m unittest discover -v`

## Cython Performance Experiment

Cython is optional benchmark tooling, not an XCC runtime dependency. Build a
temporary Cython import tree, then benchmark the configured CPython checkout:

```
uv run --with cython --with setuptools python scripts/cythonize_xcc.py --clean --force
uv run python scripts/benchmark_cython_cpython.py --cpython /path/to/cpython --skip-cython-build --runs 3 --warmups 1
```

The benchmark runs XCC frontend compilation on a default CPython sample:
`Objects/listobject.c`, `Objects/dictobject.c`, `Python/compile.c`,
`Parser/parser.c`, and `Modules/_json.c`. In the local run recorded under
`build/cython`, that sample measured pure Python at 27.086s median and the
Cython import tree at 22.131s median, a 1.22x median speedup.

## Rules

- Standard library only at runtime
- No GPL-derived code or tests
