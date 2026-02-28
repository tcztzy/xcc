# Licensing and Provenance

## Policy

- Do not copy or derive code from GPL licensed sources.
- Track provenance for every borrowed idea or snippet.
- Prefer permissive licenses (MIT, BSD, Apache-2.0) for reference material.

## ShivyC usage

- ShivyC is MIT licensed and may be used as a reference for ideas and tests.
- Use ShivyC only for conceptual guidance, never for direct code reuse.

## Third party review

- Maintain a log of external sources used for design decisions.
- Add explicit references in documentation when a specification is consulted.

## LLVM/Clang test fixtures

- Curated upstream fixtures from `llvm/llvm-project` are allowed under Apache-2.0 with LLVM exceptions.
- Keep fixture provenance pinned by release archive URL and SHA-256 in `tests/external/clang/manifest.json`.
- Materialize upstream fixtures from the pinned archive and keep them byte-identical to upstream.

## References

- ShivyC (PyPI metadata and project description).
