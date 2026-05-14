# XCC Claude Code Instructions

Supplement to AGENTS.md. Project-specific conventions for Claude Code sessions.

## Clang Suite Test Policy

### Platform-specific intrinsics

XCC targets the **host platform only** (currently macOS/ARM64). Clang tests that
include platform-specific intrinsics headers for unsupported architectures MUST
be skipped, not "pass by accident" through host system includes.

Intrinsics headers that should NEVER be resolved:
- ARM: `arm_neon.h`, `arm_sve.h`, `arm_sme.h`, `arm_mve.h`
- RISC-V: `riscv_vector.h`, `riscv_bitmanip.h`
- LoongArch: `lasxintrin.h`, `lsxintrin.h`
- x86: `x86intrin.h`, `avx*.h`, `emmintrin.h`, etc.
- Others: `altivec.h`, `opencl-c.h`, `builtins.h`

When a test fails because of `#include <arm_sme.h>` or similar: skip it.
Reason format: `"platform-specific intrinsics header not available for <arch>"`

### System includes during testing

The clang suite uses `tests/external/clang/stubs/` for standard C headers.
Do NOT enable host system includes (`no_standard_includes=True` is the default
in `test_clang_suite.py`). Host includes pull in Xcode's clang resource dir
(3.1MB `arm_neon.h`, etc.) causing 9x slowdown.

Only add stubs for standard C headers (`stdint.h`, `stddef.h`, etc.) when
multiple tests need them. One-off platform header tests get skipped.

### Determining skip-worthy tests

- Test includes `<riscv_*.h>`, `<arm_*.h>`, `<lasx*.h>`, `<lsx*.h>` → skip
- Test validates header values against compiler builtins (`_Static_assert(FLT_RADIX == __FLT_RADIX__)`) → skip (needs matching compiler+header, not a language test)
- Test needs `INTN_C` macros with exact integer promotion semantics → skip (requires compiler builtins `__INT8_C` etc.)
- Test expects Clang-specific diagnostics (format warnings, analyzer checks) → skip

## Test Speed

- clang_suite gate: `uv run tox -e clang_suite` (~22s target)
- All other gates combined: ~12s
- Before modifying the clang suite test infrastructure, verify with a full tox run
