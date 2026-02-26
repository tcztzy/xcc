# Roadmap

## Phase 0: Research and scaffolding

- Collect specifications and requirements.
- Establish documentation, linting, typing, and test policy.

## Phase 1: Front end MVP

- Preprocessor, lexer, parser, and AST.
- Basic semantic analysis and type checking.

## Phase 2: IR and code generation

- Initial IR and minimal backend for a single platform.
- Produce object files and link with the system toolchain on macOS.
- Establish Docker-based Linux/ELF build environments.

## Phase 3: CPython compilation

- Compile CPython core and standard library modules.
- Expand feature coverage based on CPython build failures.

## Phase 3a: ELF linking and libc coverage

- Integrate mold as the initial linker for ELF targets.
- Validate CPython builds against glibc and musl environments.

## Phase 4: Optimization and hardening

- Performance tuning with benchmarks.
- Extensive regression tests and diagnostics polish.
