# XCC Claude Code Instructions

Supplement to AGENTS.md. Project-specific conventions for Claude Code sessions.

## Clang Suite Test Policy

### Platform-specific intrinsics

XCC targets the **host platform only** (currently macOS/ARM64). Platform-specific intrinsics
headers for the host architecture (e.g., `arm_neon.h` on ARM64) are resolved through the
host system include path. Headers for non-host architectures (RISC-V, LoongArch, x86 on ARM64)
will not be found and tests including them should be skipped.

Reason format: `"platform-specific intrinsics header not available for <arch>"`

### Determining skip-worthy tests

- Test includes `<riscv_*.h>`, `<lasx*.h>`, `<lsx*.h>` → skip (non-host arch)
- Test validates header values against compiler builtins (`_Static_assert(FLT_RADIX == __FLT_RADIX__)`) → skip (needs matching compiler+header, not a language test)
- Test needs `INTN_C` macros with exact integer promotion semantics → skip (requires compiler builtins `__INT8_C` etc.)
- Test expects Clang-specific diagnostics (format warnings, analyzer checks) → skip

## Test Speed

- clang_suite gate: `uv run tox -e clang_suite` (~22s target)
- All other gates combined: ~12s
- Before modifying the clang suite test infrastructure, verify with a full tox run
