# Linux x86_64 Target Contract

## Goal and Output

On x86_64 Linux, `xcc` defaults to `--target=x86_64-linux-gnu`. The target emits
native ELF x86_64 SysV assembly through `src/xcc/x86_64_asm.py`; a
GNU-compatible system `cc` assembles and links it. LLVM IR, `llc`, and clang
fallbacks are forbidden on this target path.

The release integration gate is:

```text
CC="xcc" ./configure && make
```

The produced ELF Python executable must start and pass a smoke import on the
supported Linux environment.

## Target Environment

- Predefined macros, include discovery, GNU extensions, accepted build flags,
  dependency actions, and driver delegation describe Linux/x86_64/ELF rather
  than the host running the test controller.
- Assembly uses GNU-compatible ELF syntax and SysV relocation, visibility, PIC,
  and GOT/PLT rules.
- External and default-visible symbols remain valid in shared objects; direct
  non-PIC text relocations are forbidden.
- Object-only link actions apply the same target-library filtering as
  compile-and-link actions.

## SysV ABI and Data Model

- Integer/pointer and SSE register classes, stack overflow arguments, return
  registers, `%al` for variadic floating arguments, and call-site stack
  alignment follow the SysV AMD64 ABI.
- Aggregates are classified by eightbyte class. Small mixed INTEGER/SSE values
  use the required registers; MEMORY-class values use caller-owned hidden
  result storage and by-value copies.
- `va_list`, `va_start`, `va_arg`, `va_copy`, and forwarded variadic parameters
  use the SysV register-save and overflow-area model.
- Enum, array, record, union, flexible-array, bit-field, wide-character,
  long-double, and atomic layout agrees with shared semantic layout and the
  target ABI.
- Large constants, frames, offsets, and switch values use encodable instruction
  sequences rather than invalid immediates.

## Language Semantics

- Native lowering supports C scalar and aggregate values, pointer scaling,
  array decay, casts, calls and function pointers, lexical scopes, all control
  flow, compound literals, statement expressions, and addressable subobjects.
- Aggregate assignment, calls, returns, conditional values, and local,
  static, and file-scope initialization preserve designators, zero-fill,
  storage duration, and copy isolation.
- Floating expressions stay in the correct register class; integer-to-floating
  conversions preserve signed and unsigned values.
- Bit-field operations update only the declared field bits.
- Supported GNU/compiler/math/memory/atomic builtins lower directly or to the
  documented libc symbol; unresolved `__builtin_*` or `__atomic_*` symbols and
  a required `libatomic` fallback are forbidden.

## Acceptance

Use minimized native execution tests for semantic behavior and assembly/object
tests for ABI, PIC, relocation, and host-independent branches. High-risk
changes run a clean no-LLVM CPython build on the supported Linux environment.
