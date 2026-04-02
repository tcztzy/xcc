# Roadmap

## Phase 0: Research and scaffolding

- Collect specifications and requirements.
- Establish documentation, linting, typing, and test policy.

## Phase 1: Language and semantics

- Preprocessor, lexer, parser, and AST.
- Basic semantic analysis and type checking.

## Phase 2: Native code generation

- Direct lowering from the typed AST to AArch64 assembly for macOS `arm64`.
- Assemble and link through the system `clang` toolchain.
- Establish Docker-based Linux/ELF build environments.

## Phase 3: CPython compilation

- Expand the curated CPython real-file trial and drive selected translation units to green.
- Compile CPython core and standard library modules.
- Expand feature coverage based on CPython build failures.

## Phase 3a: ELF linking and libc coverage

- Integrate mold as the initial linker for ELF targets.
- Validate CPython builds against glibc and musl environments.

## Phase 4: Optimization and hardening

- Revisit standalone object emission and any backend IR requirements as native backend coverage expands.
- Performance tuning with benchmarks.
- Extensive regression tests and diagnostics polish.
