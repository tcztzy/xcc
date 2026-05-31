# CHANGELOG

## Current

- LLVM IR target triple changed from `arm64-apple-macosx15.0.0` to
  `aarch64-apple-darwin` for portability and CPython configure compatibility.
- LLVM IR backend via libLLVM-C ctypes. Generates IR programmatically,
  pipes through llc for .o files, clang for linking.
- Driver target model replaces backend modes: `--target=llvm` is the default
  and LLVM IR is treated as the target assembly language.
- Added `--target=aarch64-apple-darwin` for direct native Darwin AArch64
  assembly output on scalar integer leaf functions; `-c`/link assemble that
  generated `.s` through clang.
- Removed clang fallback backend mode; XCC failures now fail the compile.
- Removed CPython-specific `scripts/cpython_trial.py` triage harness.
- Frontend passes 442/442 CPython files.
- Deleted: ARM64 asm codegen, Clang suite, Docker infra, harness scripts,
  Clang test fixtures, CPython stubs.
- SemaUnit extended with `record_definitions` for codegen struct layout.
- Codegen emits incomplete arrays as `[0 x T]` and indexes arrays through
  their address, avoiding `llc` memory blowups from `[4294967295 x T]`.
- CPython `CC="xcc" ./configure && make -j1` now completes
  `checksharedmods`, including a clean-object rebuild after deleting `.o`
  files; optional `_gdbm` and `_tkinter` remain missing due to local
  dependencies, with 0 extension import failures.
- Fixed CPython-discovered generic C bugs: GNU `void return expr;` now
  analyzes/emits operand side effects, multi-line macro invocation collection
  survives block comments and inactive branch directives, and incomplete array
  bounds now account for sparse designators/ranges.
- Native Darwin AArch64 now emits referenced inline function bodies reached
  through function designators, conditional function pointers, global tables,
  and `extern inline` definitions as TU-local symbols while keeping unused
  inline bodies skipped.
- Native Darwin AArch64 now lowers common GCC/Clang compiler builtins used by
  CPython and Darwin headers, including bit operations, float constants and
  classifiers, `fabs`, `expect`, `unreachable`, `assume_aligned`, `alloca`, `va_copy`,
  `frame_address`, and fallback `assert`.
- Native Darwin AArch64 now uses GOT relocations for external data symbols
  such as Darwin's `__stderrp`.
- Native Darwin AArch64 now uses GOT relocations for external function
  designators while keeping direct calls as branch relocations.
- Native Darwin AArch64 now preserves earlier argument registers when a later
  call argument or indirect callee expression contains a nested call, avoiding
  ABI clobbers such as `f(ptr, strlen(ptr))`.
- Native Darwin AArch64 now preserves binary-expression left operands while
  evaluating nested RHS arithmetic, comparisons, shifts, or calls, avoiding
  false overflow/no-memory branches such as `len > MAX / sizeof(T) - 1`.
- Native Darwin AArch64 now preserves local scalar compound-assignment left
  values across RHS evaluation, fixing `_PyObject_VAR_SIZE`-style size
  accumulation during CPython bootstrap.
- Native Darwin AArch64 local array scalar initializers now compute the
  initializer value before recomputing the element destination address, so
  pointer arithmetic initializers cannot store through a clobbered x11.
- Native Darwin AArch64 large-frame scratch, spill, and outgoing argument
  stack accesses now materialize addresses before load/store when SP offsets
  exceed the assembler immediate range.
- Native Darwin AArch64 update expressions now keep lvalue addresses separate
  from result registers in nested dereference/update forms such as
  `*(*p_format)++`.
- Native Darwin AArch64 aggregate copies now preserve source addresses while
  reloading saved destination addresses from large-frame scratch slots.
- Native Darwin AArch64 call-returned small record and HFA arguments now use
  planned scratch spills instead of dynamic `sp` pushes, and move overlapping
  return registers into later argument registers without duplicating fields.
- Native Darwin AArch64 subscript address scaling for non-power-of-two element
  sizes now keeps the scale scratch separate from the live base/index
  registers.
- Native Darwin AArch64 nested subscript address formation now uses distinct
  index scratch registers across recursive levels, fixing argv parsing in
  `_bootstrap_python`.
- Native Darwin AArch64 nested subscript scaling now avoids all live outer
  index registers when materializing non-power-of-two element sizes.
- Native Darwin AArch64 now emits wide string literals as target-width
  zero-terminated storage instead of narrow `__cstring` data.
- Native Darwin AArch64 now clean-builds CPython's native objects, links
  `_bootstrap_python` and `python.exe`, regenerates frozen module headers, and
  starts `python.exe` for a `PYTHONPATH=Lib` smoke import on this machine.
- Codegen canonicalizes `bool` to `_Bool` for LLVM type selection and
  anonymous-record typedef matching, fixing CPython `pyexpat` type sizes.
- Static local references in constant initializers now resolve to the
  function-local static global instead of creating undefined externals.
- Simplified internal module structure by folding parser helper/diagnostic
  modules, preprocessor common helpers, and call argument checks into their
  owning packages/classes.
- Split raw libLLVM-C ctypes loading/signature bindings into `llvm_api.py`,
  leaving `codegen.py` focused on AST-to-LLVM lowering.
- Tightened helper-module contracts with typed Protocol boundaries in
  preprocessor text processing, parser statement parsing, and file-scope sema
  declaration analysis; removed avoidable local alias imports and type ignores.
