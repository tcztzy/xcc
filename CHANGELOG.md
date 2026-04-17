# CHANGELOG

## Current

- Parser, preprocessor, and sema are package-based modules with compatibility entrypoints.
- Driver mode validates with XCC before native or `clang` backend selection.
- Native backend emits macOS `arm64` assembly for the implemented subset; assembly and linking still use `clang`.
- Curated LLVM/Clang fixture metadata is pinned in `tests/external/clang/manifest.json`.
- Clang fixture skip reasons are sanitized so local host paths do not enter the manifest.
- Clang fixture materialization/checking scans the pinned tarball sequentially for faster setup.
- Clang fixture baseline entries match the current frontend behavior and pass `clang_suite`.
- Developer commands use `uv run`, and MkDocs is part of the locked dev toolchain.
- Documentation is reduced to current state, active priorities, and roadmap.
