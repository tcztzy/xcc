# Lessons

- Keep diagnostics deterministic.
- Do not hard-code host paths, dates, or toolchain assumptions.
- Add a reproducer before changing behavior.
- Tier 1 backend should use existing infrastructure (LLVM), not hand-written asm.
- ctypes + system libLLVM is zero-dependency and sufficient for IR generation.
- Fallback mode (--backend=auto) unblocks real-world compilation while
  native path catches up.
