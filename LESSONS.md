# Lessons

- Keep diagnostics deterministic and covered by negative tests.
- Do not hard-code host paths, dates, or toolchain assumptions.
- Compare against permissively licensed Clang fixtures.
- Treat ABI/layout bugs as high severity.
- Add a reproducer before changing behavior.
- For pure-Python Cython performance experiments, disable Cython function
  binding semantics unless the benchmark needs Python descriptor/signature
  fidelity; default binding overhead can hide the real throughput win.
- Wide string literal labels need the same alignment as their element type.
  Correct UTF-32 bytes are still unsafe if `L"..."` follows a byte string at an
  odd address; optimized libc routines may assume `wchar_t *` alignment.
- `_Bool` is not an integer truncation. When lowering scalar values to C bool,
  compare against zero and write 0/1; large bit flags often have a zero low
  byte.
- Direct-call selection must run after local shadowing checks. A block-local
  function pointer can legally have the same name as a file-scope function, and
  calls through that identifier must use the local slot instead of the global
  function signature.
- Conditional expression codegen has to apply the expression's final type to
  each branch, not just trust branch-local expression widths. Otherwise an
  `int -1` branch in a `long` conditional returns `0xffffffff` and breaks
  CPython runtime logic such as Unicode substring search.
- Block-scope function prototypes are still function declarations, not local
  storage. Sema must register them as callable signatures or direct-call codegen
  will fall back to identifier lookup and lose extern functions declared inside
  a CPython test helper body.
- Compound literals are lvalues with storage, even when they appear where the
  backend wants a scalar expression. Arrays and aggregates must be initialized
  into a temporary and decay to that address for call arguments.
- Compiler pseudo-identifiers can surface through system or project macros, not
  only direct source spelling. When the project already approximates
  `__func__` as a string macro, related GNU spellings such as
  `__PRETTY_FUNCTION__` need the same predefined compatibility surface.
- Target asm policy is target-specific. x64 Linux CPython headers can expand
  ordinary macros such as `__cpuid_count` into primary-file GNU asm, so the
  native x64 target must strip those statements before parsing even if another
  native target keeps a stricter rejection policy.
- Parallelize long frontend trial sweeps per translation unit, but keep reports ordered.
- When a build threatens memory, split frontend, IR generation, and `llc`
  under RSS monitoring before running `make`.
- Keep codegen's type canonicalization in lockstep with sema; a single
  `bool` vs `_Bool` mismatch can make anonymous record matching fall back to
  the default scalar size.
- Constant initializer evaluation must search function-local static globals
  before file-scope symbols, because nested CPython slot arrays refer to
  earlier local static arrays by identifier.
- Do not infer incomplete array length from initializer item count; sparse
  designators and ranges make the bound the largest initialized index plus one.
- Multi-line macro collection must operate on preprocessing structure, not just
  apparent physical lines; block comments and inactive conditional branches can
  appear inside macro arguments.
- Native codegen cannot treat inline-use discovery as direct-call-only. Inline
  functions can be required by function-pointer tables, conditional designators,
  or `extern inline` bodies even when no call expression names them directly.
- When a backend emits an inline body because it did not inline the call, emit
  it with translation-unit-local linkage. Header inline helpers commonly appear
  in many objects and must not become duplicate external definitions.
- Compiler builtins are not library calls. If the frontend accepts a
  `__builtin_*` name, each target backend needs either a real lowering or an
  early diagnostic; otherwise whole-program builds fail late at link time.
- On Darwin AArch64, imported data symbols are not ordinary page-addressable
  labels. Load their address through GOT relocations first, then load/store the
  variable value through that address.
- Direct calls and function designator addresses need different Mach-O
  relocations for external functions: `bl _name` is fine for calls, but taking
  an imported function's address must load it through the GOT.
- Function-call argument evaluation needs an ABI save plan, not just
  left-to-right emission. Any later argument or indirect callee that performs a
  nested call can overwrite x0-x7 or d0-d7 values already prepared for the
  outer call.
- Binary-expression lowering needs the same preservation discipline. A left
  operand kept only in a caller-scratch temp register can be overwritten by
  recursive RHS arithmetic or calls before the final compare/operator uses it.
- Compound assignment is a binary operation after the lvalue load. For local
  scalars, spill the old value across RHS lowering before applying `+=`,
  `*=`, shifts, or bitwise operators.
- Do not keep a local array element destination address live in x11 while
  evaluating a scalar initializer. Address calculation is cheap and
  side-effect-free; recompute it after the value is ready.
- Do not assume stack slots fit AArch64's immediate load/store operands. Large
  CPython frames can place scratch/spill slots past the direct SP-offset range;
  materialize the address in a scratch GPR first.
- Update expressions can be nested inside address formation. If the requested
  result register is also the usual lvalue-address scratch, pick a different
  address register for the load-modify-store.
- Large-offset stack helper code has its own scratch-register effects. When an
  aggregate source address is live in x12, reload saved destination addresses
  with a materialization scratch that cannot overwrite x12.
- Argument-preservation helpers must not make untracked dynamic `sp` changes
  before recursively lowering nested call arguments; local slot offsets are
  frame-relative only under the planned stack layout.
- When a call result occupying x0/x1 or d0/d1 becomes a later argument, move
  overlapping return registers high-to-low so x0→x1 does not overwrite the
  source for x1→x2.
- Pointer subscript scaling has three live roles: base, index, and scale. For
  non-power-of-two element sizes, choose a scale scratch distinct from both
  base and index before multiplying.
- In nested subscript lowering, an outer index register stays live while the
  base expression is recursively lowered. Allocate index scratch registers by
  nesting depth instead of reusing one fixed register for every level.
- Nested subscript scale materialization must also respect the live-index set;
  otherwise a non-power-of-two inner row size can overwrite the outer column
  index after the index-register allocation itself has been fixed.
- String literal prefix matters in native data emission. `L""`, `u""`, and
  `U""` are not byte cstrings; pointer initializers must reference storage
  encoded at the literal's target code-unit width.
- Real-build compiler wrappers must preserve the caller's working directory.
  For relative compile inputs, prefer a `PYTHONPATH=... python -c ...` wrapper
  over `uv --directory ... run xcc`, which changes cwd and makes
  project-relative source paths disappear.
- Target OS is part of preprocessing state, not just codegen state. A Linux
  native target must not inherit Darwin `__APPLE__`/`__MACH__` macros while
  compiling the same frontend on a Mac host.
- A no-LLVM Linux target needs driver tests that reject accidental `llc` and
  clang invocations; using generated assembly plus gpu02 `cc` keeps the first
  smoke gate honest.
- System headers use GNU spelling variants in ordinary declarations, not only
  in exotic corners. Treat `__restrict`/`__restrict__`, `__extension__`, and
  compiler version macros as part of the target contract before blaming glibc.
- Autoconf probes often fail closed: a compile/codegen error can be recorded
  as a libc bug such as broken `getaddrinfo`. Always inspect `config.log`
  before accepting the human-readable configure diagnosis.
- SysV floating codegen must stay in XMM registers for the full load/compute/
  store cycle. Integer fallback in a single compound-assignment edge can
  surface much later as an assembler error inside a runtime feature probe.
- File-scope enum constants from headers are ordinary integer constants at
  codegen time. If a backend only checks function-local enum bindings, Linux
  socket and address-family probes will lower `SOCK_STREAM`-style names as
  unresolved variables.
- SysV aggregate calls are not an optional late feature once CPython object
  compilation starts. Even parser code passes `Py_complex` by value, so small
  records need chunk classification and parameter spill paths before broad
  `make` progress is meaningful.
- CPython object headers rely on GNU anonymous struct/union member promotion.
  Parsing the anonymous fields is not enough; every native backend member
  address path must recursively find promoted fields such as `ob_refcnt`.
- Variadic support can surface from inline headers before compiling obvious
  formatting implementations. For x86_64 SysV, even a first-stage va_list
  lowering should be explicit about whether it handles stack-only variadics or
  the full register save area.
- CPython includes expose bit-fields in hot headers such as Unicode state and
  interpreter/thread state structs. Native backends need read-modify-write
  bit-field lowering early; writing the whole declared integer type corrupts
  neighboring flags.
- Tagged enums can escape the semantic resolver as `enum` object or parameter
  types in generated CPython AST helpers. Each native ABI layer should size
  them like `int` even when enum constants themselves already lower correctly.
- Generated parser tables use file-scope compound literals as anonymous
  storage. A native backend needs a data-section path for those literals before
  `Parser/parser.c` can compile.
- Lexer state setup uses compound literal assignment into an array element.
  Record assignment support should include both copy-by-size and direct
  designated-member initialization, not just scalar member stores.
- CPython's abstract/object headers use small struct returns for iterator send
  pairs and adaptive backoff counters. The x86_64 backend needs return-register
  classification as soon as object files start compiling, not only call
  argument classification.
- Local record initializer lists show up in ordinary object code (`Py_buffer`
  temporaries), not just generated parser data. Reuse the same in-place record
  initializer used for compound literal assignment.
- x86_64 has direct signed integer-to-float instructions, but unsigned 64-bit
  conversion needs a high-bit path. CPython bytearray sizing code reaches this
  through `size_t` arithmetic.
- `va_start` without `va_arg` only gets through parser headers. `bytesobject.c`
  needs the read-and-advance side of variadic lowering immediately afterward.
- Sizing enum objects is not enough; expression conversion paths must also see
  bare enum values as `int`, or pointer arithmetic can still fail after local
  loads succeed.
- Array-to-pointer decay is needed in binary pointer arithmetic, not just call
  arguments and identifier loads. Generated formatting code can form
  `char[N] + int` directly.
- Python `int(lexeme, 0)` is not a C integer parser: C legacy octal literals
  like `0377` need explicit base-8 handling.
- Array decay must be applied per expression form. Fixing calls and binary
  pointer arithmetic still leaves `*array` broken unless unary dereference
  handles it explicitly.
- Casts are another array-decay entry point. A string literal cast to `char *`
  should keep the address value, not enter scalar conversion for `char[N]`.
- A small aggregate call result is not addressable. Assignment must consume the
  return registers directly and store them to the destination lvalue.
- Comma expressions can still be lvalues through their right operand in GNU C
  macro-shaped code. Address formation needs to preserve the left side effect
  and then continue through the normal right-operand address path.
- `{0}` inside a record compound initializer may target an aggregate member.
  Since the destination record is already zeroed, that member needs no scalar
  store; treating the aggregate as one integer creates invalid wide moves.
- Designated initializer members can copy whole nested records, as in
  `.locals = locals`. Reuse the aggregate assignment copy path for these
  members rather than scalarizing the member type.
- SysV aggregate returns split sharply at 16 bytes. Larger records are not a
  "more chunks" case; they consume a hidden first integer argument pointing at
  caller-owned storage and shift the visible integer parameters.
- CPython's math-heavy object code can expose GNU builtins that are never real
  link symbols, such as `__builtin_isinf_sign`. Accepting the builtin in sema
  is only half the fix; native targets must lower it directly.
- A call returning a small aggregate can immediately feed another aggregate
  parameter. That value has no address; the outer call must consume the inner
  call's return registers once, in chunk order.
- Local aggregate initialization has the same call-result problem as aggregate
  assignment. `struct S s = make();` needs to store return chunks into `s`, not
  pass through scalar `_store_value_to_slot`.
- Expression result metadata matters for floating values. If a branch lowered
  into `xmm0`, the returned `_Value` must say `xmm0`; otherwise later stores
  can emit invalid integer-register `movsd`.
- Address computation and value loading have separate register classes. A
  floating dereference still needs the pointer in a GPR before loading the
  pointee into an XMM register.
- Floating contexts can request an XMM target for a child expression that is
  still integer or pointer typed. Each scalar lowering path must re-check the
  expression type and choose the matching register class locally.
- GNU inline asm can appear in the middle of a macro-expanded statement, not
  only as a whole physical source line. Strip it as a balanced statement
  segment or system-header macros can leave parser-visible asm operands behind.
- `__attribute__((__transparent_union__))` is a call-compatibility rule, not a
  harmless typedef decoration. Glibc socket prototypes rely on member pointer
  arguments being accepted while normal union assignments stay strict.
- Function-like macro invocation can cross a physical newline between the macro
  name and `(`. A line-oriented expander must collect that next line only when
  it begins an argument list, or Debian glibc attribute macros stay unexpanded.
- Function-pointer fields in CPython type objects may be initialized as
  `&function`. Global initializer code needs to classify those as relocatable
  addresses even when the internal type spelling starts with a function op.
- Flexible array members do not make their containing struct unsized for
  `sizeof`. The final array contributes no element storage but can force
  padding before the tail.
- The same flexible-array rule must be applied in member-offset walkers, not
  just in `sizeof`; code often immediately subscripts the flexible tail.
- Array member expressions should not ask for aggregate slot metadata in value
  contexts. They usually decay immediately to an address, and flexible arrays
  cannot provide a finite slot size anyway.
- Global initializers for structs with flexible tails should stop after fixed
  fields when the tail is absent. There is no implicit zero-sized array payload
  to emit.
- Local array initializers are not integer-only. The element store path must use
  the element type's register class, especially for temporary `float[]` and
  `double[]` buffers.
- Conditional aggregate expressions are not addressable as a whole. Assignment
  and initialization paths need to branch first, then copy the selected
  aggregate source into the already-computed destination.
- Register-class normalization belongs at expression entry points. Floating
  contexts often request XMM results from integer literals, identifiers, or
  `sizeof` values before an explicit conversion step can run.
- Passing `configure` once is not enough if early probes ran on a weaker
  backend. Re-run configure after fixing probe-shaped codegen failures, because
  pyconfig compatibility macros like `#define const /**/` can poison later
  full-source compilation.
- String literals are arrays with static storage, not only pointer rvalues.
  Any address path used by subscript, unary `&`, or decay must be able to
  materialize the literal label.
- Local array initialization must dispatch by element type. Record element
  initializer lists need per-element aggregate initialization, not the scalar
  store path.
- Static locals are emitted as data, but their references are bound while
  emitting function bodies. Complete incomplete array bounds during static-local
  collection, before creating the function-scope slot metadata.
- Conditional aggregate call arguments are their own ABI case. The condition
  selects a source aggregate; only after that should the call-lowering path
  read and push register/stack chunks.
- Function-scope compound literals have automatic storage. By-value aggregate
  call lowering should materialize them once in a frame slot and push chunks
  from that slot, or initializer side effects can be duplicated.
- `{0}` for aggregate storage is not an aggregate copy. Local arrays of unions
  can use scalar zero as an element initializer, and the destination storage
  should simply be zeroed.
- Conditional aggregate returns need their own materialization path. Assignment
  and call-argument fixes do not help `return flag ? left : right` unless the
  return lowering also avoids taking the conditional expression address.
- `call().member` on a small returned struct still needs storage. The call
  result lives in ABI return registers, so member-address formation must first
  spill those chunks into a frame slot.
- Incomplete arrays can still appear as extern objects. Identifier lowering
  must check array/aggregate decay before asking for slot size, or `T[]` looks
  like an impossible `T[-1]` object.
- Global pointer constants are often subobject addresses, not just bare symbols
  or direct members. Constant array subscripts need to fold into the relocation
  addend before member offsets are added.
- Conditional aggregate return handling must cover both SysV classes. Small
  returns use scratch plus return registers; large returns write directly into
  the hidden sret pointer.
- C macros expand even in member-name position. A self-reference inside the
  replacement list should be controlled by macro self-disable, not by skipping
  expansion after `.` or `->`.
- Global pointer initializers can rely on array-to-pointer decay of a nested
  global subobject, not only explicit `&subobject`. Fold the lvalue path first,
  then use the resulting relocation for the pointer field.
- A block-scope function prototype is still a function declaration, not an
  automatic object. Slot collection and declaration emission must both skip it.
- Ignoring a memory-class aggregate call result does not remove the ABI result
  path. The caller must still provide hidden sret storage for callee writes.
- CPython per-file flags can be semantically inert for xcc but still mandatory
  for make compatibility. Classify harmless flags before rejecting unknown
  native options.
- Global floating initializers are constant expressions, not just literals.
  Backend data emission needs the same folding surface as runtime expressions
  for arithmetic, casts, and compiler floating builtins.
- Constant expression helpers can be called while resolving declarator type
  specs, before every operand has a sema type-map entry. Fall back to scope
  symbols for `sizeof(local)` instead of indexing the map blindly.
- Macro self-disable is token state, not just recursion stack state. Expanded
  argument tokens can be substituted into outer macro bodies and rescanned, so
  unavailable identifiers must travel with the tokens.
- Static assertions often survive preprocessing inside initializers as comma
  constant expressions. Integer constant folding should treat `(side, value)`
  as the right operand when the side expression is itself constant-only.
- Compiler memory builtins are part of the C compiler contract even when libc
  has the real implementation. Accept them in sema and lower native calls to
  the corresponding libc symbol.
- Statement expressions need frame planning, not just emission support. Any
  local declarations inside `({ ... })` must be discovered before the native
  function prologue is emitted.
- Relocatable pointer initializers can hide behind constant conditionals.
  Fold the condition first and then run the existing lvalue-to-symbol path on
  the selected branch.
- Do not rely on libatomic being present on the target host. If configure adds
  `-latomic`, native atomics still need direct lowering and the link driver may
  need to drop the library when no helper calls remain.
- Link-only driver paths are separate from compile+link paths. If a target
  filters an unsupported library after compiling C inputs, apply the same
  filter when the driver is invoked only over existing object files.
- Unresolved `__builtin_*` references at link are backend bugs, not missing
  libraries. Treat GCC/Clang compiler builtins as target semantics and lower
  them directly, including objects compiled before the final link step.
- Comment preservation must not suppress macro expansion for code before the
  comment. If a line has `MACRO(args); /*` and the block comment closes later,
  expand the prefix before carrying the comment tail forward.
- Expression emitters must honor their declared result register. Address
  formation often asks subexpressions for `rcx`/`rdx`; returning that register
  while leaving the value in `rax` turns later stores into stale-register
  writes.
- On SysV x86_64, variadic arguments do not begin on the stack. `va_start`
  must expose the saved GP/FP argument registers first and only then advance
  through the overflow stack area.
- SysV call alignment is a property of the whole temporary evaluation stack,
  not just the current call's formal stack arguments. Nested argument calls
  must account for earlier pushed arguments before deciding whether to pad.
- SysV `va_list` parameters are pointer-like even when local `va_list` objects
  occupy the full register-save cursor structure. Builtins that consume a
  `va_list` expression must use the pointed storage for parameters and the
  local slot address for automatic objects.
- CPython extension-module builds exercise a wider compile-flag surface than
  the core interpreter. Classify semantically compatible platform flags such
  as `-fPIC` before the native unsupported-option check.
- Array-to-pointer decay applies before casts to integer types, not only before
  casts to pointer types. Remote-debugging code can cast a local `char[]`
  buffer to `uintptr_t` for validation.
- Accepting `-fPIC` is not enough for shared objects. External data references
  in text need GOT loads on ELF x86_64, or extension-module links fail with
  `R_X86_64_PC32` relocation diagnostics.
- System math macros can expand to compiler builtins even when the C source
  never names them directly. Keep sema's builtin table aligned with glibc
  macro output, including predicates such as `__builtin_signbit` and
  `__builtin_isnormal`.
- A backend can preserve `long double` layout while still lowering CPython's
  suffixed math constants through a narrower runtime path. Rejecting every
  `1.0L` literal blocks math modules before true x87 support is needed.
- In ELF shared objects, same-object non-static globals are still
  default-visible and preemptible. Treat their text references like external
  data and use GOT loads unless the C storage is static/local.
- x86_64 integer compare instructions do not accept 64-bit immediates. Switch
  lowering for large unsigned case labels must materialize the constant first.
- Function designator addresses are data-like under ELF PIC. A direct call can
  use the normal call relocation, but taking a non-local function's address
  needs a GOT load in shared objects.
- Function-scope tagged records are real scoped type bindings, not recoverable
  from the spelling `union tag` alone. Codegen passes that do not retain sema
  block scopes must rebuild enough tag-scope context before planning nested
  local slots.
- A function-level local-symbol map is not enough for block scopes with
  shadowing. Frame planning should trust syntactic array declarators when an
  inner block reuses an outer pointer name.
- SysV aggregate INTEGER eightbytes can contain odd-sized tails. Treat 3, 5,
  6, and 7-byte chunks as byte-packed register payloads instead of rejecting
  them or widening memory accesses past the object.
- Nested initializer lists inside records are not record-only. Array members
  commonly use `{0}` and should route through the same compound-initializer
  dispatcher as arrays, records, and scalar singletons.
- Static pointer tables often spell subobject addresses as `array + n`, not
  only `&array[n]`. Relocation folding must apply C pointer scaling before
  emitting the byte offset.
- Integer constant folding for static data needs the usual cast surface, not
  just integer-origin expressions. Float-to-integer casts in initializers are
  still constant expressions when the operand is a floating constant.
- Anonymous typedef records can share member names while differing in member
  types or array bounds. Codegen recovery of sema record identities must match
  the member types too, or `sizeof` can under-allocate objects even while
  member access uses larger offsets.
- Compound pointer assignment is pointer arithmetic, not integer arithmetic.
  The stored pointer update must apply element-size scaling just like `p + n`,
  especially when CPython walks typed entry arrays with runtime strides.
- Wide string literal storage has to follow the target element width even for
  ASCII-only contents. Packing `L"..."` as bytes silently breaks early
  bootstrap paths that compare `wchar_t *` strings before Python codecs exist.
- Anonymous typedef record matching should compare codegen-visible member
  types. Sema may already have lowered enum fields to the ABI integer type
  while the syntax body still says `enum`.
- Opaque tagged record pointers still need their tag identity. Even when
  `struct tag` is incomplete, collapsing it to bare `struct` makes anonymous
  parent records impossible to match back to sema.
- Static local scope markers are not stack storage. If a backend uses marker
  slots for C scope tracking, identifier and address emission must redirect
  them to the static data label before ordinary stack-slot handling.
- Frame planning may know a more precise local array type than sema. When a
  backend completes a local `T[]` or unevaluated-bound array for storage,
  later `sizeof(identifier)` must consult the active slot before stale symbol
  metadata.
- Update expressions used as address operands must keep the lvalue address
  storage separate from the expression result register. In `*sp++`, the yielded
  old pointer is the dereference address, while the incremented pointer still
  has to be stored through the original local `sp` slot.
- Function-local symbol maps are not a substitute for scoped declaration
  slots. Under shadowing, frame planning must verify the semantic symbol's
  declarator shape and storage size before reusing it, or a later pointer local
  can be loaded as an integer and corrupt bootstrap objects.
- Codegen stack-depth state has to model runtime paths, not emitted paths.
  Conditional aggregate arguments emit pushes in both branches, but only one
  branch executes; count one branch before deciding whether a later call needs
  an ABI alignment pad.
- Driver defaults are part of the target contract. If CPython is configured
  with `CC="xcc"` on x86_64 Linux, the host default must select the native ELF
  backend; otherwise the build silently depends on an explicit target flag and
  LLVM tooling.
- GCC stack allocation builtins are not linkable runtime calls. Native
  backends must lower `__builtin_alloca` by adjusting the stack pointer inline,
  and preserve ABI alignment for later calls.
- A `for` initializer declaration owns a statement scope. Leaving
  `for (int i = ...)` in the enclosing compound scope can hide an outer
  parameter after the loop; CPython flowgraph then rewrites the wrong
  instruction index and produces invalid bytecode CFG.
- External compiler tools need identity checks, not just paths. Discovering
  `llc` through environment/PATH is useful only if the driver verifies the
  candidate's own help output before trusting a same-name executable.
