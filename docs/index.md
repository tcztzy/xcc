# XCC

XCC is a C compiler implemented in modern Python (CPython and PyPy, Python 3.11+). A long-term compatibility target is to compile the CPython source tree without relying on any third party runtime dependencies. Code quality and correctness are prioritized over short term convenience.

## Goals

- Long-term: compile the CPython source tree with full fidelity.
- Implement a C11 compiler that follows the standard closely while keeping GNU/Clang compatibility behavior explicit and mode-gated.
- Provide strict diagnostics and deterministic output.
- Run on CPython and PyPy with identical behavior.
- Enforce complete test coverage and zero warnings.

## Non-goals (initially)

- C++ support.
- Targeting every platform at launch.
- JIT or interactive REPL features.

## Guiding principles

- Correctness first, then performance.
- Small, explicit modules with minimal coupling.
- Zero third party runtime dependencies.
- Reproducible builds and transparent provenance.

## Document map

- Requirements: technical and compatibility requirements.
- CPython Compatibility: long-term compatibility constraints and future validation goals.
- Architecture: compiler pipeline and module boundaries.
- Front End: preprocessing, parsing, and semantic analysis.
- Back End: direct native code generation, `clang` delegation, and future backend work.
- Testing and Quality: tests, coverage, linting, and typing.
- Performance: benchmarking and optimization discipline.
- Licensing: source policy and third party review.
- Roadmap: phased delivery plan.
- References: external specifications and documentation.
