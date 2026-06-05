# Linux x86_64 Target Spec

## §G GOAL
The `x86_64-linux-gnu` target emits native ELF x86_64 SysV assembly and aims for
`CC="xcc" ./configure && make` in CPython to succeed on gpu02-class Linux
without LLVM, `llc`, or clang target fallbacks.

## §C CONSTRAINTS
- `--target=x86_64-linux-gnu` selects this target explicitly.
- x86_64 Linux hosts default to this target through `driver.md`.
- Object and executable paths use direct native ELF assembly assembled/linked by
  gpu02 GNU-compatible `cc`, not LLVM IR, `llc`, or clang.
- Predefined macros, include discovery, ABI rules, assembly syntax, relocation
  model, PIC behavior, and delegation must match the Linux x86_64 target
  contract closely enough for CPython-scale builds.
- Backend fixes generalize to C semantics, ABI, driver compatibility, or
  diagnostics; CPython file/path identity branches are forbidden.

## §I INTERFACES
- cmd: `xcc --target=x86_64-linux-gnu -S source.c -o source.s` → native ELF
  x86_64 SysV assembly; no LLVM IR/`llc`.
- cmd: `xcc --target=x86_64-linux-gnu -c source.c -o source.o` → native ELF
  x86_64 SysV assembly + gpu02 `cc` assembler object; no LLVM IR/`llc`/clang.
- cmd: `xcc --target=x86_64-linux-gnu source.c -o exe` → native ELF x86_64
  executable through gpu02 GNU-compatible `cc`; no LLVM IR/`llc`/clang.
- cmd: `CC="xcc --target=x86_64-linux-gnu" ./configure && make` on gpu02-class
  Linux → native x86_64 no-LLVM CPython integration gate.
- file: `src/xcc/x86_64_asm.py` → native Linux x86_64 SysV backend.

## §V INVARIANTS
V169: Native x86_64 Linux object/executable path → LLVM IR, `llc`, and clang invocations ⊥; generated ELF assembly is assembled/linked with gpu02 GNU-compatible `cc`.
V170: Native x86_64 Linux preprocessing ! define Linux/x86_64/ELF target macros and avoid Darwin `__APPLE__`/`__MACH__` macros.
V171: Native x86_64 Linux backend ! implement SysV C semantics generically; CPython path/file/project identity branches ⊥.
V172: Native x86_64 Linux CPython gate ! produced ELF `python` starts and runs a smoke import on gpu02-class Linux.
V173: Native x86_64 Linux driver delegation ! preprocessing/dependency/version/no-input paths invoke gpu02 GNU-compatible `cc`, not host clang.
V174: Preprocessor conditional directives ! strip trailing block comments after `#endif` even when the comment spans physical lines.
V175: GNU restrict aliases ! lex/parse/canonicalize `__restrict` and `__restrict__` exactly as `restrict`, including duplicate qualifier diagnostics.
V176: Linux target GNU predefined macros ! match gpu02 GCC-compatible version macros closely enough that glibc exposes the same supported type branches.
V177: GNU `__extension__` before record members ! ignore the marker without treating it as a member type or leaking it into the AST.
V178: Native x86_64 Linux call ABI ! decay array and string literal call arguments to pointers before classifying scalar SysV arguments.
V179: Native x86_64 Linux SysV floating ABI ! pass/return `float`/`double` in XMM registers, set `%al` for FP argument registers, and use stack slots for overflow FP args.
V180: Native x86_64 Linux enum constants ! lower local and file-scope enumerators as integer immediates; unresolved symbol references for enum constants ⊥.
V181: Native x86_64 Linux floating compound assignment ! load/compute/store through XMM registers and preserve stack alignment across RHS calls.
V182: Native x86_64 Linux SysV aggregate call ABI ! pass and receive small record chunks in the required integer/SSE registers, including two-double records such as `Py_complex`; blanket aggregate-argument rejection ⊥.
V183: Native x86_64 Linux record member access ! resolve promoted members inside anonymous struct/union fields such as CPython `PyObject.ob_refcnt` and add nested offsets before load/store.
V184: Native x86_64 Linux variadic builtins ! size `__builtin_va_list`, lower `__builtin_va_start` for stack-based variadic arguments, and lower `__builtin_va_end` without unresolved builtin calls.
V185: Native x86_64 Linux bit-field members ! load, assign, compound-assign, and update integer bit-fields by masking the declared storage unit; full-width member stores or address-taking for bit-fields ⊥.
V186: Native x86_64 Linux enum objects ! treat tagged and typedef enum object/parameter types as 4-byte signed integer ABI slots, not unsized scalar names.
V187: Native x86_64 Linux global compound literals ! place file-scope compound literal storage in ELF data and allow pointer initializers to reference it, including arrays of initialized records.
V188: Native x86_64 Linux aggregate assignment ! assign record values by copying equal-sized storage and lower record compound literal assignment by zeroing the destination then storing designated members.
V189: Native x86_64 Linux small aggregate returns ! return SysV-classified records/unions up to 16 bytes in integer/SSE return registers, including local lvalues, compound literals, and forwarded call results.
V190: Native x86_64 Linux local record initializers ! lower function-scope record initializer lists by zeroing the stack slot and storing positional/designated members.
V191: Native x86_64 Linux numeric conversion ! convert unsigned 64-bit integers to `float`/`double` without rejecting high-bit values; signed-only `cvtsi2s*` lowering alone ⊥.
V192: Native x86_64 Linux variadic reads ! lower scalar `__builtin_va_arg` by loading through the backend's `__builtin_va_list` cursor and advancing it by the SysV stack slot width.
V193: Native x86_64 Linux enum expressions ! normalize bare enum object expression types to `int` before pointer/arithmetic conversion checks.
V194: Native x86_64 Linux pointer arithmetic ! decay array operands, including string literals, to element pointers before classifying pointer/integer binary operations.
V195: Native x86_64 Linux integer literals ! parse C octal integer lexemes such as `0377` as base 8 after stripping integer suffixes; Python-style base-0 parsing alone ⊥.
V196: Native x86_64 Linux unary dereference ! decay array operands to element pointers before lowering `*array_expr`.
V197: Native x86_64 Linux pointer casts ! decay array operands before casting them to pointer types so string literal casts do not scalarize array types.
V198: Native x86_64 Linux aggregate call assignment ! store small aggregate call return chunks from SysV return registers into aggregate lvalue destinations; taking a call-result address ⊥.
V199: Native x86_64 Linux comma-expression address ! when forming an lvalue address for `(left, right)`, evaluate `left` for side effects and form the address from addressable `right`; rejecting comma expressions before checking the right operand ⊥.
V200: Native x86_64 Linux aggregate member zero initialization ! record compound initializers that zero an aggregate member rely on the already-zeroed destination storage; lowering that member as an oversized scalar register store ⊥.
V201: Native x86_64 Linux aggregate member copy initialization ! record compound initializers with aggregate expression members such as `.locals = locals` copy source storage into the destination member; treating the member expression as scalar ⊥.
V202: Native x86_64 Linux indirect aggregate returns ! records/unions returned in SysV MEMORY class use a hidden first integer argument pointing at caller-owned storage, shift explicit integer arguments, and return the same pointer in `rax`; rejecting return types larger than 16 bytes ⊥.
V203: GNU floating classification builtins ! `__builtin_isinf_sign` is declared as an integer-returning generic builtin and native x86_64 lowers it directly from float/double bits; emitting an unresolved external builtin call ⊥.
V204: Native x86_64 Linux aggregate call-result arguments ! when a small aggregate call result is passed as an aggregate argument, evaluate the inner call once and push its SysV return chunks for the outer call; forming an address of the call expression or re-calling per chunk ⊥.
V205: Native x86_64 Linux aggregate local call initializers ! local record declarations initialized from aggregate-returning calls store SysV return chunks into the stack slot; scalarizing the record into an oversized integer store ⊥.
V206: Native x86_64 Linux floating conditional expressions ! conditional expressions of float/double type report the XMM result register after both arms, so local stores use `xmm*`; carrying `rax` as the result register ⊥.
V207: Native x86_64 Linux floating pointer dereference ! unary `*` evaluates pointer operands into GPR address registers even when the loaded pointee is float/double and the result target is XMM; loading pointer values into XMM ⊥.
V208: Native x86_64 Linux integer subexpressions under floating contexts ! non-floating binary and pointer expressions normalize requested XMM targets to GPRs before lowering; integer immediates or pointer arithmetic emitted into XMM registers ⊥.
V209: Native x86_64 Linux global function-pointer initializers ! scalar fields with function-pointer type accept function designators and `&function` as relocatable `.quad` addresses; treating them as integer constants ⊥.
V210: Native x86_64 Linux flexible array record size ! `sizeof(struct { ...; T tail[]; })` excludes the final flexible array member while preserving its alignment padding; treating the record as unsized ⊥.
V211: Native x86_64 Linux flexible array member access ! final flexible array members have a concrete offset for member access, subscript, and `offsetof` even though their element storage is unsized; failing member lookup because the member size is unknown ⊥.
V212: Native x86_64 Linux array member expression decay ! record member expressions of array type, including flexible arrays, produce an address value for expression contexts and casts instead of requiring slot-sized aggregate metadata.
V213: Native x86_64 Linux global flexible-array record initializers ! global records with final flexible array members emit initialized fixed fields and omit storage for the absent tail when the tail has no initializer; requiring a finite array size ⊥.
V214: Native x86_64 Linux local floating array initializers ! function-scope `float[]`/`double[]` initializer elements are evaluated and stored through XMM registers; hard-coded integer `rax` element stores ⊥.
V215: Native x86_64 Linux aggregate conditional assignment ! conditional expressions of record/union type copy only the selected branch into the destination aggregate storage; forming an address of the conditional expression ⊥.
V216: Native x86_64 Linux expression register classes ! any non-floating scalar expression requested by a floating context lowers through a GPR before conversion to XMM; integer literals, identifiers, `sizeof`, or `offsetof` emitted directly into `xmm*` ⊥.
V217: Native x86_64 Linux Autoconf const probe ! compile function-scope `const` typedef arrays and `static struct const` initializer lists so `configure` never writes `#define const /**/` from a backend limitation.
V218: Native x86_64 Linux string literal addresses ! string literals are addressable static arrays for subscript and unary-address contexts; rejecting `_emit_address(StringLiteral)` ⊥.
V219: Native x86_64 Linux local aggregate arrays ! function-scope arrays of records/unions with nested initializer lists initialize each element at its stack address; rejecting non-scalar array initializer items ⊥.
V220: Native x86_64 Linux static local incomplete arrays ! block-scope `static T a[] = {...}` completes its storage length from the initializer before stack-scope references are bound; sizing `T[-1]` ⊥.
V221: Native x86_64 Linux conditional aggregate call arguments ! small record/union conditional expressions used as by-value call arguments branch once, then push ABI chunks from the selected branch; taking the conditional expression address ⊥.
V222: Native x86_64 Linux compound-literal aggregate call arguments ! function-scope record/union compound literals used as by-value call arguments materialize once in compiler-owned frame storage, then push ABI chunks from that storage; taking an unmaterialized compound literal address or repeating initializer side effects ⊥.
V223: Native x86_64 Linux aggregate zero initializers ! scalar zero expressions used to initialize record/union/array storage zero the aggregate destination; treating zero as a smaller source aggregate to copy ⊥.
V224: Native x86_64 Linux conditional small aggregate returns ! record/union conditional expressions returned by value materialize the selected branch in aligned scratch storage before loading SysV return chunks; taking the conditional expression address ⊥.
V225: Native x86_64 Linux aggregate call-result member access ! member/subobject access on a record/union call result materializes the aggregate return into compiler-owned frame storage before forming the member address; taking the address of the call expression ⊥.
V226: Native x86_64 Linux incomplete array identifiers ! extern or file-scope incomplete arrays decay to symbol addresses before slot sizing; requiring a fixed `T[-1]` object size ⊥.
V227: Native x86_64 Linux global subobject pointer initializers ! relocatable pointer initializers accept constant-index global array elements and member offsets such as `&array[0].field`; requiring a pure integer constant ⊥.
V228: Native x86_64 Linux conditional indirect aggregate returns ! record/union conditional expressions returned through SysV hidden sret write the selected branch into caller-provided result storage; taking the conditional expression address ⊥.
V229: Preprocessor member-position self-reference macros ! object-like macros after `.`/`->` still expand once when their replacement contains the same identifier, relying on normal self-disable for replacement rescans; suppressing glibc `sa_handler`-style macros ⊥.
V230: Native x86_64 Linux global array-member pointer initializers ! array-typed global subobject expressions, including `(&global.member)->field.array`, decay to relocatable addresses with accumulated member offsets; treating them as nonconstant scalars ⊥.
V231: Native x86_64 Linux block-scope function prototypes ! function declarations inside function bodies are non-object declarations that allocate no local storage and lower calls by symbol; requiring a stack slot for such prototypes ⊥.
V232: Native x86_64 Linux discarded indirect aggregate calls ! calls returning SysV memory-class records/unions still receive a compiler-owned hidden sret slot even when their result is unused; calling them without an sret address ⊥.
V233: Native x86_64 Linux CPython compile flags ! accepted CPython compile flags that do not change frontend semantics, including `-fno-strict-aliasing`, do not block native object generation; rejecting them as unsupported native flags ⊥.
V234: Native x86_64 Linux global floating initializers ! file-scope float/double constants accept arithmetic constant expressions, unary/cast/comma/conditional forms, and common floating builtins; requiring a bare literal ⊥.
V235: Native x86_64 Linux `sizeof` in declarator bounds ! `sizeof`/`_Alignof` operands inside local declarator array bounds resolve prior locals, file-scope objects, and member chains even when sema did not attach expression type-map entries; leaking raw `KeyError` ids ⊥.
V236: Preprocessor macro self-disable through arguments ! identifiers suppressed by a macro's self-disable in an expanded argument remain unavailable when substituted into an outer function-like macro replacement; re-expanding CPython state aliases such as `fatal_error` inside `Py_XSETREF` ⊥.
V237: Native x86_64 Linux global integer constant expressions ! file-scope integer scalar initializers fold comma expressions by their right operand, including static-assert-style `((void)sizeof(...), 0)` fragments; rejecting them as nonconstant ⊥.
V238: Native x86_64 Linux memory builtins ! frontend accepts `__builtin_memset`, `__builtin_memcpy`, and `__builtin_memmove` as void*-returning generic builtins, and native x86_64 lowers them to libc symbols; treating them as undeclared or emitting `call __builtin_*` ⊥.
V239: Native x86_64 Linux statement expressions ! GNU statement expressions allocate frame slots for inner declarations, execute body statements in a nested scope, and return the final expression value; rejecting `StatementExpr` in CPython macros ⊥.
V240: Native x86_64 Linux conditional pointer initializers ! global pointer initializers fold integer-constant conditional expressions before resolving relocatable subobject addresses; rejecting CPython static singleton conditionals ⊥.
V241: Native x86_64 Linux atomics without libatomic ! CPython atomic builtins used by `pyatomic_gcc.h` lower directly to x86_64 load/store/xchg/xadd/cmpxchg/fence sequences and x86_64 links omit `-latomic`; depending on a missing system libatomic ⊥.
V242: Native x86_64 Linux object-only links ! when `xcc --target=x86_64-linux-gnu` is invoked as a linker over existing objects, it still filters unsupported target libraries such as `-latomic`; compile+link-only filtering that misses CPython `_freeze_module` links ⊥.
V243: Native x86_64 Linux compiler builtins ! common GCC/Clang builtins used by CPython/system C (`unreachable`, `frame_address`, `return_address`, `va_copy`, bit operations, inf/nan constants, `expect`, `assume_aligned`) lower directly without unresolved `__builtin_*` symbols.
V244: Preprocessor trailing block comments ! macro invocations before an unclosed trailing `/* ...` block comment on the same physical line expand before the comment tail is preserved; leaking raw calls such as `assert(expr); /* multiline` into sema/codegen ⊥.
V245: Native x86_64 Linux scalar casts ! scalar cast expressions return their value in the requested GPR, including pointer casts used by lvalue address formation; reporting `rcx` while leaving the value in `rax` ⊥.
V246: Native x86_64 Linux variadic functions ! `__builtin_va_start`, `__builtin_va_arg`, and `__builtin_va_copy` use the SysV `va_list` layout with GP/FP register save offsets, overflow pointer, and register save area; stack-only cursors that skip register-passed varargs ⊥.
V247: Native x86_64 Linux call alignment ! direct and nested calls account for already-pushed temporary call arguments when deciding SysV stack padding; calling a callee with `%rsp` 8-byte misaligned before `call` ⊥.
V248: Native x86_64 Linux `va_list` parameters ! treat `__builtin_va_list` function parameters as pointers to SysV `va_list` storage for forwarding, `va_copy`, and `va_arg`; copying from the parameter slot bytes themselves ⊥.
V249: Native x86_64 Linux CPython extension flags ! accept position-independent code flags such as `-fPIC` on native compile paths; rejecting shared-object compile flags before code generation ⊥.
V250: Native x86_64 Linux array casts ! array expressions decay to element pointers before scalar casts, including integer casts such as `(uintptr_t)local_array`; scalarizing the array object itself ⊥.
V251: Native x86_64 Linux PIC external data ! references to undefined external data symbols in generated text load the symbol address through `@GOTPCREL` before reading or returning it; direct PC-relative data relocations in shared objects ⊥.
V252: Native x86_64 Linux math builtins ! accept and lower `__builtin_signbit` as an integer-returning sign-bit test without emitting unresolved builtin calls.
V253: Native x86_64 Linux long-double literals ! CPython math-module long-double constants compile on the native path using the backend's double-precision floating constant machinery while preserving 16-byte `long double` layout for storage and `sizeof`; rejecting `1.0L`-style literals ⊥.
V254: Native x86_64 Linux PIC default-visible data ! text references to non-static file-scope data, including data defined in the same translation unit, load addresses through `@GOTPCREL`; direct PC-relative references to preemptible default-visible data in shared objects ⊥.
V255: Native x86_64 Linux math builtins ! accept and lower `__builtin_isnormal` using exponent-range tests without unresolved builtin calls.
V256: Native x86_64 Linux switch lowering ! case values outside signed 32-bit immediate range are materialized in a register before comparison; emitting invalid `cmp r64, imm64` assembly ⊥.
V257: Native x86_64 Linux PIC function designators ! taking the address of external or default-visible functions loads through `@GOTPCREL`, while direct calls remain calls; direct PC-relative function-address relocations in shared objects ⊥.
V258: Native x86_64 Linux local tagged records ! function-scope tagged struct/union definitions remain bound for nested block declarations that reuse the tag; resolving an inner `union tag` reference to bare `union` instead of the enclosing scoped record ⊥.
V259: Native x86_64 Linux shadowed array locals ! block-scope array declarations use their syntactic array type for frame planning even when an outer local with the same name has pointer type; treating the inner array initializer as a pointer scalar ⊥.
V260: Native x86_64 Linux small aggregate chunks ! SysV INTEGER aggregate chunks of any tail size from 1 through 8 bytes are loaded and stored without over-wide scalar assumptions; rejecting 3/5/6/7-byte structs passed by value ⊥.
V261: Native x86_64 Linux record member initializer lists ! record compound initializers accept nested initializer lists for array members as well as record members; treating `member_array = { ... }` as an invalid scalar list ⊥.
V262: Native x86_64 Linux global pointer arithmetic initializers ! file-scope pointer initializers accept global array/object addresses plus or minus integer constant element offsets and emit byte-scaled relocations; rejecting `global_array + n` as nonconstant ⊥.
V263: Native x86_64 Linux global integer casts ! file-scope integer scalar initializers fold casts from floating constants to integer types using C truncation semantics; rejecting `(long)100.0f` as nonconstant ⊥.
V264: Native x86_64 Linux anonymous typedef records ! matching a typedef's anonymous record body back to sema's record identity compares member types and array lengths, not only member names; confusing same-shaped prefixes such as time `data[6]` and datetime `data[10]` records ⊥.
V265: Native x86_64 Linux pointer compound assignment ! `ptr += integer` and `ptr -= integer` scale the integer operand by the pointed-to type size before storing the updated pointer; adding the raw integer byte count to a pointer lvalue ⊥.
V266: Native x86_64 Linux wide string literals ! `L"..."`, `u"..."`, and `U"..."` string literals emit code units with the target element width and nul terminator, not packed narrow bytes; making `wchar_t *` literals unreadable by `wcscmp()` ⊥.
V267: Native x86_64 Linux anonymous typedef record matching with enum members ! syntax-side anonymous record bodies compare member types after codegen canonicalization, so enum fields match sema's int-sized ABI representation; falling back to bare `struct` for `typedef struct { enum {...}; } T` ⊥.
V268: Native x86_64 Linux opaque tagged record pointer members ! resolving `struct tag`/`union tag` type specs without a visible body preserves the tag name even when the record is incomplete, so anonymous record matching can compare opaque pointer members; erasing them to bare `struct *`/`union *` ⊥.
V269: Native x86_64 Linux static local references ! scope markers for function-local static variables resolve to their static data labels for rvalue and address formation, never to `[rbp]` stack addresses; reading a static local array through the marker slot ⊥.
V270: Native x86_64 Linux `sizeof` local arrays ! `sizeof(local_array)` uses the frame-planned slot type after codegen completes an otherwise sema-incomplete array bound; re-reading stale `T[-1]` symbol/type-map metadata ⊥.
V271: Native x86_64 Linux update expressions ! postfix/prefix scalar updates keep the lvalue address register distinct from the expression result register and store the updated value back through the original lvalue slot; `*sp++` writing the incremented pointer through the yielded old address ⊥.
V272: Native x86_64 Linux shadowed local slot types ! frame-planned declaration slots reject flat same-name semantic locals whose declarator shape or concrete size disagrees with the declaration being planned; reading a scoped pointer local as a 32-bit integer because an outer `int code` shares its name ⊥.
V273: Native x86_64 Linux conditional aggregate call arguments ! codegen stack-depth accounting treats a conditional aggregate argument as the one branch executed at runtime, not the sum of both emitted branches; leaving a stale odd stack depth that inserts a bogus `push 0` before the next register-only call ⊥.
V274: Native x86_64 Linux default target ! on x86_64 Linux hosts, driver mode defaults to `x86_64-linux-gnu` so `CC="xcc"` uses the native ELF backend without LLVM; keeping the default at `llvm` makes CPython configure require an explicit target and Homebrew `llc` ⊥.
V275: Native x86_64 Linux stack allocation builtins ! `__builtin_alloca` and `__builtin_alloca_with_align` lower by dynamically subtracting aligned stack space and returning the new stack pointer; leaving them as external calls makes CPython `_freeze_module` links fail with undefined builtin symbols ⊥.
V276: Native x86_64 Linux `for` scopes ! declarations in a `for` initializer bind only for the `for` statement, including condition, body, and post expressions; leaking a same-name loop variable into following statements and hiding an outer parameter/local ⊥.
V277: Native x86_64 Linux GNU inline asm stripping ! preprocessing removes GNU `asm`/`__asm__` statements as balanced statement segments even when they appear after ordinary tokens inside a macro-expanded line; stripping only line-start asm leaves parser-visible glibc asm tokens in CPython modules ⊥.
V278: Native x86_64 Linux transparent union parameters ! typedefs marked `__attribute__((__transparent_union__))` make function-call arguments compatible with any union member type while ordinary assignments remain unchanged; treating glibc socket transparent unions as ordinary union parameters rejects `accept4` calls ⊥.
V279: Native x86_64 Linux multiline function-like macros ! preprocessing treats a known function-like macro name at physical line end followed by `(` on the next active line as one macro invocation while preserving non-invocation line breaks; leaving split glibc attribute macros unexpanded makes QEMU/Debian headers parser-visible identifiers ⊥.
V280: Native x86_64 Linux target asm policy ! driver options enable GNU asm statement stripping for `x86_64-linux-gnu` so macro-expanded primary-file asm such as CPython HACL `__cpuid_count` is removed before parsing; reusing AArch64's strict asm rejection for x64 Linux modules ⊥.
V281: GNU predefined function-name identifiers ! gnu11 preprocessing defines `__PRETTY_FUNCTION__` to the same string-compatible fallback surface as `__func__`; leaving GCC assertion/debug macro expansions as undeclared identifiers blocks CPython internal test modules ⊥.
V282: Native x86_64 Linux compound literal expressions ! expression-position compound literals allocate and initialize a frame temporary; array/aggregate literals evaluate to that temporary address for decay/call arguments, while scalar literals load the initialized value; rejecting `(T[]){...}` as a call argument ⊥.
V283: Block-scope extern function declarations ! a function prototype declared inside a block registers a function signature for calls/codegen while preserving same-scope declaration conflicts; treating `extern int f(...);` as only a local object symbol makes direct calls look like unknown identifiers ⊥.
V284: Native x86_64 Linux conditional scalar results ! both branches of `cond ? a : b` are coerced to the conditional expression result type before control rejoins; returning a 32-bit signed `-1` branch from a `long` conditional without sign-extension ⊥.
V285: Native x86_64 Linux function-pointer shadowing ! a local callable object or function pointer shadows any same-named file-scope function signature during call lowering; emitting a direct call when a same-name local slot exists bypasses the function pointer value and can pass the wrong receiver object ⊥.
V286: Native x86_64 Linux `_Bool` conversion ! scalar-to-`_Bool` lowering normalizes by comparing against zero and storing exactly 0 or 1; truncating the low byte of a nonzero integer such as `0x1000000` makes true values false ⊥.
V287: Native x86_64 Linux wide string literals ! labels for non-byte string literals are aligned to the target code-unit width before emitting UTF-16/UTF-32 storage; placing `L"..."` after arbitrary byte strings without `.p2align 2` can hand glibc `wcscmp` an unaligned `wchar_t *` and crash bootstrap ⊥.

## §T TASKS
id|status|task|cites
T23|x|add `x86_64-linux-gnu` target driver, Linux target macros/includes, and initial native SysV assembly backend smoke path|V169,V170,V171,I.cmd
T24|.|expand native x86_64 Linux backend from scalar/control-flow/call subset to CPython configure/build semantics|V169,V171,V182,V183,V184,V185,V186,V187,V188,V189,V190,V191,V192,V193,V194,V195,V196,V197,V198,V199,V200,V201,V202,V203,V204,V205,V206,V207,V208,V209,V210,V211,V212,V213,V214,V215,V216,V217,V218,V219,V220,V221,V222,V223,V224,V225,V226,V227,V228,V229,V230,V231,V232,V233,V234,V235,V236,V237,V238,V239,V240,V241,V242,V243,V244,V245,V246,V247,V248,V249,V250,V251,V252,V253,V254,V255,V256,V257,V274,V275,V276,V277,V278,V279,V280,V281,V282,V283,V284,V285,V286,V287,I.cmd
T25|.|compile and link CPython on gpu02 with `CC="xcc"` and run smoke import|V169,V172,V274,V275,V276,V277,V278,V279,V280,V281,V282,V283,V284,V285,V286,V287,I.cmd

## §B BUGS
id|date|cause|fix
B150|2026-05-31|native x86_64 Linux target delegation still used host clang for non-compile driver paths, hiding gpu02 preprocessor/dependency behavior|V173
B151|2026-05-31|glibc `stddef.h` left multi-line trailing block comments after `#endif`, so the preprocessor reported unexpected tokens|V174
B152|2026-05-31|glibc declarations using `__restrict`/`__restrict__` parsed as ordinary identifiers and broke function declarators|V175
B153|2026-05-31|Linux target claimed very old GNU version macros, exposing glibc `__float128` branches unsupported by the frontend|V176
B154|2026-05-31|glibc record declarations with `__extension__` before anonymous members were parsed as unsupported declaration types|V177
B155|2026-05-31|native x86_64 Linux call lowering classified string literals and arrays as aggregate arguments instead of decayed pointers|V178
B156|2026-05-31|native x86_64 Linux file-scope enum constants from system headers such as `SOCK_STREAM` lowered as unknown identifiers|V180
B157|2026-05-31|native x86_64 Linux floating compound assignment emitted integer-register `movsd` operands and failed CPython's float word-order probe|V181
B158|2026-05-31|native x86_64 Linux rejected `Py_complex` by-value calls in `Parser/pegen.c` instead of classifying the two-double record into SysV SSE argument chunks|V182
B159|2026-05-31|native x86_64 Linux direct record lookup ignored promoted members inside anonymous struct/union fields, so CPython `PyObject.ob_refcnt` loads/stores failed in `Py_DECREF` expansions|V183
B160|2026-05-31|native x86_64 Linux treated `__builtin_va_list` as an unsized scalar and emitted no lowering for `__builtin_va_start`/`__builtin_va_end`, blocking CPython parser inline variadic helpers|V184
B161|2026-05-31|native x86_64 Linux rejected CPython header bit-field reads in `Parser/pegen.c` instead of lowering integer bit-field access through mask/shift operations|V185
B162|2026-05-31|native x86_64 Linux treated tagged enum parameters such as CPython AST context enums as unsized `enum` scalars instead of int-sized ABI values|V186
B163|2026-05-31|native x86_64 Linux rejected CPython parser keyword tables because global pointer initializers could not reference compound literal record arrays|V187
B164|2026-05-31|native x86_64 Linux rejected lexer tokenizer-mode compound literal assignment instead of zeroing and storing aggregate members in place|V188
B165|2026-05-31|native x86_64 Linux rejected small aggregate-return functions such as `_PyIter_Send` and backoff-counter helpers instead of loading SysV return chunks into registers|V189
B166|2026-05-31|native x86_64 Linux rejected local `Py_buffer sub_view = {NULL, NULL}` initializers instead of initializing record stack slots in place|V190
B167|2026-05-31|native x86_64 Linux rejected `size_t`/`uint64_t` to floating conversions in bytearray object code because only signed 64-bit `cvtsi2s*` was implemented|V191
B168|2026-05-31|native x86_64 Linux rejected `va_arg` in bytes formatting code because `__builtin_va_arg` had no scalar cursor load/advance lowering|V192
B169|2026-05-31|native x86_64 Linux sized enum objects as ABI values but left enum expression types unnormalized, so pointer/arithmetic conversion rejected `+` in bytes object code|V193
B170|2026-05-31|native x86_64 Linux rejected `char[21] + int` in bytes formatting code because array operands were not decayed before pointer arithmetic classification|V194
B171|2026-05-31|native x86_64 Linux parsed C octal literal `0377` with Python `int(..., 0)`, which rejects legacy C octal syntax|V195
B172|2026-05-31|native x86_64 Linux rejected unary dereference of `char[1]` string/array expressions because `*array` did not decay to an element pointer|V196
B173|2026-05-31|native x86_64 Linux cast `char[1]` string literals to pointer types through scalar conversion and failed to scalarize the array type|V197
B174|2026-05-31|native x86_64 Linux tried to form the address of a small aggregate call result during assignment in `Objects/call.c` instead of storing return registers into the target|V198
B175|2026-05-31|native x86_64 Linux rejected address formation for comma expressions in `Objects/codeobject.c` instead of evaluating the left operand and taking the address of the right lvalue|V199
B176|2026-05-31|native x86_64 Linux lowered a zero initializer for a 56-byte aggregate member in `Objects/codeobject.c` as an oversized scalar store instead of relying on the zeroed destination storage|V200
B177|2026-05-31|native x86_64 Linux rejected aggregate expression members in `Objects/codeobject.c` compound initializers such as `.locals = locals` instead of copying source aggregate storage|V201
B178|2026-05-31|native x86_64 Linux rejected `Objects/codeobject.c` functions returning large aggregate var-count records instead of using SysV hidden sret pointer calling convention|V202
B179|2026-05-31|gpu02 CPython `Objects/complexobject.c` reached GNU `__builtin_isinf_sign`, but sema had no builtin signature and x86_64 had no direct lowering for the non-linkable builtin|V203
B180|2026-05-31|native x86_64 Linux tried to form the address of a small aggregate call result while returning nested complex arithmetic calls in `Objects/complexobject.c`|V204
B181|2026-05-31|native x86_64 Linux local `Py_complex` declarations initialized from aggregate calls in `Objects/complexobject.c` were lowered as invalid scalar `movzx`/wide stores|V205
B182|2026-05-31|native x86_64 Linux floating conditional initializers in `Objects/complexobject.c` reported `rax` as the result register, producing invalid `movsd mem, rax` assembly|V206
B183|2026-05-31|native x86_64 Linux evaluated `*double_pointer` inside `Objects/floatobject.c` floating comparisons by loading the pointer operand into `xmm0` instead of a GPR address register|V207
B184|2026-05-31|native x86_64 Linux let integer RHS subexpressions of `Objects/floatobject.c` floating compound assignments inherit an XMM target, causing integer immediates to be lowered through `_sized_reg(\"xmm0\")`|V208
B185|2026-05-31|native x86_64 Linux treated `&framelocalsproxy_repr` in `Objects/frameobject.c` global `PyTypeObject` function-pointer fields as a nonconstant integer initializer|V209
B186|2026-05-31|native x86_64 Linux could not compute `sizeof(PyDictKeysObject)` in `Objects/dictobject.c` because the final flexible array member made the whole record look unsized|V210
B187|2026-05-31|native x86_64 Linux could size `PyDictKeysObject` but still failed to find its final `dk_indices` flexible array member during address/subscript lowering in `Objects/dictobject.c`|V211
B188|2026-05-31|native x86_64 Linux treated `dk->dk_indices` in `Objects/dictobject.c` as a slot-sized `char[-1]` aggregate expression instead of an address value that can decay to a pointer|V212
B189|2026-05-31|native x86_64 Linux global initialization of the empty dict keys object in `Objects/dictobject.c` still tried to size and zero the final `dk_indices` flexible array member|V213
B190|2026-05-31|native x86_64 Linux local `double[]`/`float[]` initializers in `Objects/memoryobject.c` stored floating initializer values from `rax`, producing invalid `movsd`/`movss` assembly|V214
B191|2026-05-31|native x86_64 Linux aggregate assignment from a conditional record expression in `Objects/typeobject.c` tried to form the address of the whole conditional instead of copying the selected branch|V215
B192|2026-05-31|native x86_64 Linux floating compound assignment in `Objects/unicode_formatter.c` requested `xmm0` for an integer RHS literal and crashed looking up `xmm0` as a GPR|V216
B193|2026-05-31|an earlier gpu02 `configure` run failed the ANSI const probe on a static aggregate initializer, wrote `#define const /**/`, and later made `Objects/unicodeobject.c` declarations conflict|V217
B194|2026-05-31|native x86_64 Linux subscript lowering in `Objects/unicodeobject.c` tried to form an address for a string literal but `_emit_address` only handled named arrays|V218
B195|2026-05-31|native x86_64 Linux rejected `Python/assemble.c` function-scope arrays of small records because local array initialization only accepted scalar element initializers|V219
B196|2026-05-31|native x86_64 Linux collected block-scope static `char *keywords[]` in `Python/bltinmodule.c` with length `-1`, then failed to size it when binding the static local reference|V220
B197|2026-05-31|native x86_64 Linux by-value aggregate call arguments in `Python/ceval.c` tried to take the address of a conditional expression instead of selecting a branch and pushing its chunks|V221
B198|2026-05-31|native x86_64 Linux by-value aggregate call arguments in `Python/ceval.c` tried to take the address of an unmaterialized compound literal instead of storing it once and pushing its chunks|V222
B199|2026-05-31|native x86_64 Linux local aggregate array initialization in `Python/ceval.c` treated scalar zero for `union _PyStackRef` as a source aggregate copy and rejected the size mismatch|V223
B200|2026-05-31|native x86_64 Linux small aggregate return in `Python/ceval.c` tried to form the address of a conditional union expression instead of materializing the selected branch|V224
B201|2026-05-31|native x86_64 Linux member access on a small aggregate call result in `Python/codegen.c` tried to take the address of the call expression instead of materializing its return chunks|V225
B202|2026-05-31|native x86_64 Linux identifier lowering in `Python/import.c` sized extern incomplete array `_PyImport_Inittab` before decaying it to its symbol address|V226
B203|2026-05-31|native x86_64 Linux global pointer initializer in `Python/parking_lot.c` treated `&buckets[0].root` as a nonconstant scalar instead of a relocatable subobject address|V227
B204|2026-05-31|native x86_64 Linux indirect aggregate return in `Python/preconfig.c` tried to form the address of a conditional status struct instead of writing the selected branch to the hidden sret pointer|V228
B205|2026-05-31|glibc `sa_handler` macro in `Python/pylifecycle.c` was skipped after `.`, so sema looked for a direct `struct sigaction.sa_handler` member instead of the expanded nested member|V229
B206|2026-05-31|native x86_64 Linux global pointer initializer in `Python/pylifecycle.c` treated `(&_PyRuntime._main_interpreter)->dtoa.preallocated` as a nonconstant scalar instead of a decayed array subobject address|V230
B207|2026-05-31|native x86_64 Linux codegen in `Python/pythonrun.c` treated block-scope prototype `long PyImport_GetMagicNumber(void);` as a local object requiring a stack slot|V231
B208|2026-05-31|native x86_64 Linux codegen in `Python/sysmodule.c` called discarded memory-class aggregate return `_PyRuntime_Initialize()` without providing the required hidden sret address|V232
B209|2026-05-31|native x86_64 Linux driver rejected CPython's `-fno-strict-aliasing` flag while compiling `Python/dtoa.c`, stopping make before code generation|V233
B210|2026-05-31|native x86_64 Linux global double initializer in `Python/dtoa.c` rejected `9007199254740992. * 9007199254740992.e-256` because only bare floating literals were constant-folded|V234
B211|2026-05-31|native x86_64 Linux frame collection in `Python/perf_jit_trampoline.c` leaked a raw type-map `KeyError` for local array bound `uint8_t tmp[sizeof(marker)]`|V235
B212|2026-05-31|preprocessing `Modules/faulthandler.c` re-expanded the self-referential `fatal_error` macro after it was substituted through `Py_XSETREF`, producing `_PyRuntime.faulthandler._PyRuntime...` and a sema member lookup failure|V236
B213|2026-05-31|native x86_64 Linux global integer initializer in `Modules/faulthandler.c` rejected a `sizeof(array) / sizeof(array[0]) + ((void)sizeof(struct {...}), 0)` constant expression|V237
B214|2026-05-31|sema rejected `__builtin_memset` while compiling `Modules/posixmodule.c` instead of accepting the compiler memory builtin and lowering it to libc `memset` on native x86_64|V238
B215|2026-05-31|native x86_64 Linux codegen rejected GNU statement expressions from CPU-set macros in `Modules/posixmodule.c` instead of allocating inner locals and returning the final expression|V239
B216|2026-05-31|native x86_64 Linux global pointer initializer in `Modules/itertoolsmodule.c` rejected a constant conditional selecting between static singleton subobject addresses|V240
B217|2026-05-31|gpu02 linked CPython objects with unresolved `__atomic_*` calls and a broken `-latomic` linker script pointing at missing `/usr/lib64/libatomic.so.1.2.0`|V241
B218|2026-05-31|gpu02 `_freeze_module` object-only link still delegated `-latomic` even after object recompilation removed `__atomic_*` references|V242
B219|2026-05-31|gpu02 `_freeze_module` linked old CPython objects with unresolved `__builtin_unreachable`, `__builtin_frame_address`, `__builtin_va_copy`, bit-operation builtins, and inf/nan constants|V243
B220|2026-05-31|gpu02 `_freeze_module` link found unresolved `assert` because a CPython `assert(vsign != 0); /* multiline ... */` line kept the raw macro call when macro tokenization hit an unclosed trailing block comment|V244
B221|2026-05-31|gpu02 `_freeze_module` segfaulted in `_PyConfig_Copy` because `(int *)member` address formation asked for `rcx` but cast lowering left the pointer in `rax`, so `*(int*)member = ...` stored through stale `rcx` and corrupted the config-spec loop pointer|V245
B222|2026-05-31|gpu02 `_freeze_module` segfaulted in `vsnprintf` while formatting build info because x86_64 `va_start` initialized a stack-only cursor and skipped `PyOS_snprintf` varargs passed in `rcx`/`r8`/`r9`|V246
B223|2026-05-31|gpu02 `_freeze_module` still segfaulted at `PyOS_snprintf` entry because nested call-argument evaluation left one pending argument on the stack, then called `Py_GetBuildInfo` without an alignment pad, so its variadic prologue spilled XMM registers with misaligned `movaps`|V247
B224|2026-05-31|gpu02 `_freeze_module` segfaulted in `PyUnicode_FromFormat("%S.%s", ...)` because `va_copy(vargs2, vargs)` copied bytes from the `va_list` parameter slot instead of the pointed SysV `va_list` storage, making `%S` read the format string as a PyObject|V248
B225|2026-05-31|clean gpu02 CPython rebuild reached extension modules and stopped at `Modules/arraymodule.c` because native x86_64 rejected the ordinary Linux shared-object compile flag `-fPIC`|V249
B226|2026-05-31|gpu02 `Modules/_remote_debugging/frames.c` rejected `(uintptr_t)frame` for local `char frame[SIZEOF_INTERP_FRAME]` because cast lowering tried to scalarize the `char[88]` array instead of decaying it to a pointer first|V250
B227|2026-05-31|gpu02 shared extension links rejected `Modules/arraymodule.o`, `_bisectmodule.o`, and `_csv.o` because native x86_64 emitted direct PC-relative text relocations against external data symbols such as `_Py_NoneStruct` and `PyExc_ValueError` instead of GOT loads|V251
B228|2026-05-31|gpu02 `Modules/mathmodule.c` failed sema because glibc's `signbit` macro expanded to undeclared `__builtin_signbit`|V252
B229|2026-05-31|gpu02 `Modules/cmathmodule.c` rejected long-double suffixed floating constants during native x86_64 codegen instead of compiling them through the backend's double constant path|V253
B230|2026-05-31|gpu02 shared extension link for `_csv` rejected a direct PC-relative text relocation against same-object default-visible data symbol `Dialect_Type_spec`; non-static globals are still preemptible under ELF PIC|V254
B231|2026-05-31|gpu02 `Modules/mathmodule.c` failed sema because glibc's `isnormal` macro expanded to undeclared `__builtin_isnormal`|V255
B232|2026-05-31|gpu02 `_lzmamodule.c` produced invalid `cmp rax, 4611686018427387905` for a large unsigned switch case; x86_64 has no `cmp r64, imm64` encoding|V256
B233|2026-05-31|gpu02 shared links for `_pickle` and `_remote_debugging` rejected direct PC-relative text relocations against function symbols such as `PyUnicode_AsUTF8String` and `cached_code_metadata_destroy` when function addresses were formed with `lea` instead of GOT loads|V257
B234|2026-05-31|gpu02 `Modules/mathmodule.c` failed frame planning for `union pun result` inside a nested branch because codegen lost the enclosing function-scope `union pun` tag binding and resolved it as unsized bare `union`|V258
B235|2026-05-31|gpu02 `Modules/_hacl/Hacl_Hash_SHA3.c` rejected `uint8_t b3[256] = {0}` inside an inner block because a same-name outer pointer symbol made codegen plan the inner array declaration as scalar pointer storage|V259
B236|2026-05-31|gpu02 `Modules/_hacl/Hacl_Hash_Blake2s.c` rejected by-value `struct Hacl_Hash_Blake2b_index_s` parameters because the native SysV aggregate classifier only accepted 1/2/4/8-byte integer chunks, not the struct's 3-byte tail chunk|V260
B237|2026-05-31|gpu02 `Modules/expat/xmlparse.c` rejected `struct siphash` initialization because its `unsigned char buf[8]` member used a nested `{0}` initializer list and record initialization only allowed nested lists for record members|V261
B238|2026-05-31|gpu02 `Modules/cjkcodecs/_codecs_cn.c` rejected global codec index entries such as `__gb2312_decmap + 94` because pointer initializers did not fold global array symbol plus integer element offsets into relocations|V262
B239|2026-05-31|gpu02 `Modules/expat/xmlparse.c` rejected static feature-table values such as `(long)100.0f` because global integer constant folding ignored casts from floating constants to integer types|V263
B240|2026-05-31|gpu02 `_freeze_module` corrupted obmalloc free lists while initializing datetime objects because anonymous typedef record matching confused `_PyDateTime_BaseDateTime`/`PyDateTime_DateTime` with earlier time records that had the same member names but shorter `data[6]` arrays|V264
B241|2026-05-31|gpu02 `_freeze_module` segfaulted in `clone_combined_dict_keys` because x86_64 compound assignment lowered `PyObject **pvalue += offs` as raw byte addition, so the copied dict-entry cursor became misaligned and `Py_INCREF` received an invalid pointer|V265
B242|2026-05-31|gpu02 `_freeze_module` raised `ValueError: unsupported error handler` because x86_64 emitted `L"surrogateescape"` as packed narrow bytes, so `get_error_handler_wide()` could not match the CPython filesystem-error wide string|V266
B243|2026-05-31|gpu02 recompiling `Python/initconfig.c` rejected `PyStatus status = ...` because anonymous record matching compared the syntax-side enum member against sema's canonical int member without normalization and returned bare unsized `struct`|V267
B244|2026-05-31|gpu02 recompiling `Parser/pegen.c` rejected `sizeof(Parser)` because anonymous `Parser` matching erased opaque tagged pointer members such as `struct _arena *arena` to bare `struct *` and could not recover the sema record identity|V268
B245|2026-05-31|gpu02 `_freeze_module` segfaulted in `_PyPegen_new_identifier` because the function-local static `forbidden[]` table was referenced through its static-local scope marker as an `[rbp]` stack slot, producing `0x800` instead of the `"None"` string address|V269
B246|2026-05-31|gpu02 `Modules/cjkcodecs/multibytecodec.c` rejected `sizeof(statebytes)` because codegen completed the local array bound for frame layout but `sizeof(identifier)` used stale sema metadata `unsigned char[-1]` instead of the slot type|V270
B247|2026-06-02|gpu02 `_freeze_module` segfaulted in `basicblock_last_instr` because x86_64 postfix pointer update inside `*sp++ = value` overwrote the updated pointer through the yielded old address instead of the local `sp` slot, corrupting CPython's CFG traversal stack|V271
B248|2026-06-02|gpu02 `_bootstrap_python` segfaulted importing frozen `abc` because x86_64 frame planning used a flat same-name local symbol for scoped `PyObject *code`, so later reads truncated the pointer to 32 bits when initializing `_PyCodeConstructor.code`|V272
B249|2026-06-02|gpu02 `_bootstrap_python` segfaulted in `PyArg_UnpackTuple` because a previous conditional aggregate call argument left x86_64 codegen's stack-depth model one slot too deep, so `_PyEval_EvalFrameDefault` emitted a bogus `push 0` before calling `_Py_VectorCall_StackRefSteal` and misaligned the variadic callee's `movaps` prologue|V273
B250|2026-06-02|QEMU x86_64 Linux smoke showed `xcc` still defaulted to `llvm`, so CPython's required `CC="xcc"` path would invoke LLVM/`llc` unless the user passed an explicit target|V274
B251|2026-06-02|gpu02 `CC="xcc"` `_freeze_module` link failed with undefined `__builtin_alloca` from `Python/traceback.o` because native x86_64 treated the stack allocation builtin as an external function call instead of adjusting `rsp` inline|V275
B252|2026-06-02|gpu02 `_bootstrap_python` compiled three-element list literals into an invalid CFG because x86_64 kept a `for (int i = ...)` loop variable in the enclosing scope, so CPython `flowgraph.c` reused the inner `i` after the loop and rewrote the wrong instruction index|V276
B253|2026-06-02|gpu02 `Modules/selectmodule.c` exposed glibc GNU inline asm statements embedded inside macro-expanded `do { ... } while (0)` lines, but preprocessing only stripped asm at statement-line starts and left parser-visible asm tokens|V277
B254|2026-06-02|gpu02 `Modules/socketmodule.c` rejected `accept4` because glibc declares the socket address parameter as a `__transparent_union__` typedef, while sema checked the parameter as an ordinary union instead of accepting member pointer argument types|V278
B255|2026-06-02|QEMU/Debian `Modules/selectmodule.c` left `__attribute_deprecated_msg__` unexpanded in `/usr/include/signal.h` because the function-like macro name ended one physical line and its argument list began on the next line|V279
B256|2026-06-02|gpu02 CPython `Modules/blake2module.c` and `Modules/hmacmodule.c` rejected HACL `__cpuid_count` macro expansions because `x86_64-linux-gnu` inherited AArch64's strict function-body asm rejection instead of stripping target-irrelevant GNU asm statements|V280
B257|2026-06-02|gpu02 CPython `_testinternalcapi` modules left assertion/debug macro uses of `__PRETTY_FUNCTION__` as undeclared identifiers because gnu11 predefined macros only stubbed `__func__`|V281
B258|2026-06-02|gpu02 CPython `Modules/_testinternalcapi.c` rejected `PyTuple_FromArray((PyObject*[]){...}, 3)` because x86_64 codegen collected compound literal frame slots but `_emit_expr` had no expression-position lowering for compound literals|V282
B259|2026-06-02|gpu02 CPython `Modules/_testcapimodule.c` could not call block-scope prototype `extern PyObject* PyCFunction_Call(...)` because sema stored it as a local object declaration without registering a function signature for codegen|V283
B260|2026-06-02|gpu02 `./python -m sysconfig --generate-posix-vars` failed importing `json` because x86_64 conditional lowering returned `mode == FAST_COUNT ? count : -1` from Unicode fastsearch as zero-extended `4294967295`, making multi-character string containment report false positives|V284
B261|2026-06-03|gpu02 `make` segfaulted in `generate-build-details.py` and QEMU minimized it to `dict(a=1).keys() & [chr(97)]` because `_PyDictView_Intersect` declared a local function pointer named `dict_contains` but x86_64 call lowering ignored the local slot and emitted a direct call to the same-named file-scope function|V285
B262|2026-06-03|gpu02 `check_extension_modules.py` rejected `typing.NamedTuple` fields under `from __future__ import annotations` because x86_64 lowered `bool future_annotations = flags & CO_FUTURE_ANNOTATIONS` by truncating `0x1000000` to a zero low byte instead of normalizing nonzero to `_Bool` true|V286
B263|2026-06-03|gpu02 `_bootstrap_python` segfaulted in glibc `wcscmp` during command-line/config parsing because x86_64 emitted UTF-32 `L"..."` storage correctly but let the label follow arbitrary byte strings without 4-byte alignment, producing unaligned `wchar_t *` arguments on gpu02|V287
