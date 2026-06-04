# SPEC

## §G GOAL
Python stdlib-only C11 compiler with target-driven codegen; default `llvm`, `--target=aarch64-apple-darwin` can compile CPython to a native executable that runs on this machine, and `--target=x86_64-linux-gnu` can compile CPython to a native ELF executable on gpu02-class x64 Linux without LLVM.

## §C CONSTRAINTS
- Runtime deps = Python standard library only.
- Host Python support: CPython 3.11+.
- `from __future__ import annotations` ⊥.
- GPL sources/tests ⊥.
- Target default = host-sensitive; x86_64 Linux hosts default to
  `x86_64-linux-gnu`, other hosts default to `llvm`.
- Target selection ! use `--target=<name>`; internal `--backend` mode flag ⊥.
- LLVM target object output ! via discovered LLVM `llc`, verified by `llc --help` stdout.
- Darwin AArch64 target object/executable output ! direct native assembly; LLVM IR/`llc` path ⊥.
- Linux x86_64 target object/executable output ! direct native ELF assembly assembled/linked by gpu02 GNU-compatible `cc`; LLVM IR/`llc`/clang path ⊥.
- `CHANGELOG.md` records status changes.
- `LESSONS.md` records reusable bug lessons.
- Handoff ! run `uv run tox -e lint` & `uv run tox -e type`.
- Vibe coding allowed; unverified generated code ⊥ accepted.
- Behavior changes ! have smallest reproducer test before broad fix.
- Existing user changes ! preserved; unrelated refactor ⊥.
- Compiler pipeline special-cases for CPython paths/files/macros ⊥.
- CPython fixes ! generalize to C semantics, ABI, driver compatibility, or diagnostics.

## §I INTERFACES
- cmd: `xcc [--target=llvm] ...` → CC-style compile/link driver; target defaults to host platform (`x86_64-linux-gnu` on x86_64 Linux, otherwise `llvm`).
- cmd: `xcc -c source.c -o source.o` → XCC frontend + LLVM IR + discovered/verified `llc` object.
- cmd: `xcc --target=llvm -c source.c -o source.o` → same explicit target form.
- cmd: `xcc --target=aarch64-apple-darwin -c source.c -o source.o` → XCC frontend + native Darwin AArch64 assembly + assembler object.
- cmd: `xcc --target=aarch64-apple-darwin source.c -o exe` → native Darwin AArch64 executable; no LLVM IR/`llc`.
- cmd: `xcc --target=x86_64-linux-gnu -S source.c -o source.s` → XCC frontend + native ELF x86_64 SysV assembly; no LLVM IR/`llc`.
- cmd: `xcc --target=x86_64-linux-gnu -c source.c -o source.o` → XCC frontend + native ELF x86_64 SysV assembly + gpu02 `cc` assembler object; no LLVM IR/`llc`/clang.
- cmd: `xcc --target=x86_64-linux-gnu source.c -o exe` → native ELF x86_64 executable through gpu02 GNU-compatible `cc`; no LLVM IR/`llc`/clang.
- cmd: `uv run python -m unittest discover -v` → unit regression suite.
- cmd: `uv run tox -e lint` → ruff check + format check.
- cmd: `uv run tox -e type` → `ty check src`.
- cmd: `CC="xcc" ./configure && make` in CPython tree → flagship integration gate.
- cmd: `CC="xcc --target=aarch64-apple-darwin" ./configure && make` in CPython tree → native AArch64 integration gate.
- cmd: `CC="xcc --target=x86_64-linux-gnu" ./configure && make` on gpu02-class Linux → native x86_64 no-LLVM CPython integration gate.
- file: `src/xcc/preprocessor/` → C preprocessing.
- file: `src/xcc/lexer.py` → C tokenization.
- file: `src/xcc/parser/` → AST parse.
- file: `src/xcc/sema/` → type resolution, constants, layout, conversions.
- file: `src/xcc/codegen.py` → AST/sema unit → LLVM IR via libLLVM-C ctypes.
- file: `src/xcc/llvm_api.py` → raw libLLVM-C loading/signature boundary.
- file: `src/xcc/cc_driver.py` → compiler-driver arg handling, `llc`, clang link.
- file: `CHANGELOG.md` → current capability/status ledger.
- file: `LESSONS.md` → backprop lesson ledger.

## §V INVARIANTS
V1: ∀ runtime import path → stdlib only; dev deps ∉ runtime.
V2: ∀ Python src → CPython 3.11 syntax valid & `from __future__ import annotations` absent.
V3: ∀ borrowed external test/source → license Apache/BSD/MIT/PSF/permissive; GPL ⊥.
V4: ∀ bug fix → minimal failing C or CLI reproducer exists before behavior change.
V5: ∀ parser/sema/codegen semantic claim → clang or CPython behavior used as oracle when practical.
V6: ∀ ABI/layout change → tests cover `sizeof`, `alignof`, `offsetof`, field order, bit-field? relevant case.
V7: ∀ integer conversion/promotion change → tests cover signedness, width, constant folding, runtime IR? relevant case.
V8: ∀ initializer change → tests cover scalar, aggregate, nested aggregate, static storage? relevant case.
V9: ∀ control-flow codegen change → emitted IR passes discovered/verified LLVM `llc` for reproducer.
V10: LLVM builder position ! read from `GetInsertBlock` after recursive emit; stale assumed block ⊥.
V11: LLVM null pointer checks ! handle `None` and `0`.
V12: `LLVMPositionBuilderAtEnd` on terminated block ⊥ unless caller proves insertion-before-terminator intended.
V13: `--backend` and `--no-backend-fallback` CLI options ⊥.
V14: `--target` accepted values ! explicit; unsupported target exits nonzero before compile.
V15: CPython-specific harnesses ⊥; compiler correctness comes from C semantics, clang oracle, unit reproducers, and real build.
V16: Compiler code ! never branch on CPython path/file/project identity.
V17: Integration gates ! use real build commands or project-agnostic replay of captured compile commands; curated project allowlists ⊥ gate.
V18: ∀ diagnostics test → message/location deterministic.
V19: ∀ `target=llvm` object path → `llc` command includes explicit optimization/filetype args expected by driver tests.
V20: Handoff after code edit ! `uv run tox -e lint` & `uv run tox -e type` pass or failure documented.
V21: Broad CPython build run ! delete stale `.o` first when object cache can mask regression.
V22: Vibe-coded patch accepted only after reproducer, local oracle/gate, and lesson/changelog update when behavior/status changes.
V23: GNU `void` return expression ! analyze operand + emit side effects before `ret void`; c11 keeps reject.
V24: Multi-line macro args ! collect through block comments and inactive conditional-directive lines; inactive branch directives do not abort expansion.
V25: Incomplete array init length ! largest initialized designator/range index + 1, not initializer item count; file/block sema and codegen agree.
V26: ∀ `target=aarch64-apple-darwin` object/executable path → `llc` and LLVM IR emission ⊥.
V27: Native AArch64 backend ! implement C semantics generically; CPython path/file/project identity branches ⊥.
V28: Native AArch64 CPython gate ! produced `python.exe` starts and runs a smoke import on this machine.
V29: Native AArch64 `NullStmt` ! no-op; empty statements in configure probes compile/link/run.
V30: Native AArch64 unused inline definitions ! no emitted body; unused header inline bodies do not block codegen.
V31: Native AArch64 cast-to-void ! emit operand side effects, discard value, and allow no-op function designators.
V32: Native AArch64 `sizeof`/`alignof` ! emit target ABI constants for scalar, pointer, array, and record types used by configure probes.
V33: Native AArch64 block-scope declarations ! allocate stack slots from declaration type in nested statements.
V34: Native AArch64 Darwin variadic calls ! pass unnamed integer/pointer args in stack 8-byte slots, not x-registers.
V35: Native AArch64 `__builtin_offsetof` ! fold record member offsets used by alignment probes.
V36: Native AArch64 Autoconf float-endian probes ! compile/link without target-mismatched inline-asm false positives; global numeric arrays, subscript loads/stores, compound assignment, and floating compare follow Darwin little-endian AArch64 semantics.
V37: Native AArch64 `switch` ! dispatch integer case/default labels generically, support nested switches and `break` without CPython file identity branches.
V38: Native AArch64 global string pointer arrays ! emit Mach-O data relocations to cstring literals for file-scope pointer arrays.
V39: Native AArch64 global emission ! file-scope `extern` declarations never emit storage even when a later definition resolves the same symbol.
V40: Native AArch64 member access ! compute `.`/`->` addresses from generic record layout and load scalar members without project identity branches.
V41: Native AArch64 member assignment ! store scalar values through generic `.`/`->` member lvalues.
V42: Native AArch64 compound assignment ! update scalar local/member/subscript lvalues for `+=`, `|=`, and `&=` without losing lvalue address across RHS calls.
V43: Native AArch64 pointer lvalues ! support unary `*` load/store and unary `&` address formation for local/member/subscript lvalues.
V44: Native AArch64 `while` ! implement condition/body/end labels plus `break`/`continue` stacks for generic loop control flow.
V45: Native AArch64 extern globals ! load scalar/pointer file-scope extern variables through Mach-O symbol relocations, distinct from direct function calls.
V46: Native AArch64 update expressions ! implement prefix/postfix `++`/`--` on scalar lvalues with correct stored value and expression result.
V47: Native AArch64 pointer operations ! compare object pointers as 64-bit addresses and scale pointer arithmetic by pointee size without routing through integer arithmetic conversions.
V48: Native AArch64 `for` ! emit init, optional condition, body, post expression, and `break`/`continue` targets in C execution order.
V49: Native AArch64 conditional expressions ! evaluate only the selected branch and materialize scalar/pointer or void side effects through a common continuation label.
V50: Native AArch64 aggregate locals ! allocate stack storage for local arrays/records and form addresses for `&local` and `local.member` without treating aggregate values as scalars.
V51: Native AArch64 labels/goto ! lower function-local C labels to deterministic assembly labels and `goto` to unconditional branches.
V52: Native AArch64 block-scope static/extern declarations ! emit static local storage with function-local labels and treat extern locals as declarations of external storage, not stack slots.
V53: Native AArch64 local array initializers ! initialize scalar/pointer array elements in stack storage and zero-fill omitted tail elements.
V54: Native AArch64 array expression decay ! emit the base address for local/static/global array expressions used as rvalues instead of loading aggregate storage.
V55: Native AArch64 call ABI ! pass homogeneous double record arguments through a separate consecutive FP argument-register cursor instead of loading aggregate values as scalars.
V56: Native AArch64 call ABI ! pass and receive integer/pointer arguments beyond x0-x7 through 8-byte stack slots while preserving local-frame addressing during argument evaluation.
V57: Native AArch64 Darwin variadic definitions ! treat `__builtin_va_list` as pointer-sized storage, lower `va_start` to the incoming variadic stack area, and lower `va_end` to no-op.
V58: Native AArch64 address formation ! materialize large byte offsets in registers when they exceed AArch64 add-immediate encoding range.
V59: Native AArch64 anonymous record resolution ! normalize enum members to their integer representation when structurally matching anonymous records for sizeof/layout.
V60: Native AArch64 `do while` ! execute body before condition and route `continue` to the condition check with `break` exiting the loop.
V61: Native AArch64 function designators ! emit function symbol addresses when function names are used as rvalues or with unary `&`, distinct from direct calls.
V62: Native AArch64 block locals ! bind identifiers through C block scope declarations, so same-name locals in disjoint or nested blocks get distinct stack slots and member access uses the active declaration type.
V63: Native AArch64 compound assignment ! update scalar local/member/subscript lvalues for arithmetic, bitwise, and shift compound operators without evaluating the lvalue address twice.
V64: Native AArch64 file-scope compound literals ! allocate anonymous static storage for compound literal initializers and let pointer globals relocate to that storage without project-specific symbol handling.
V65: Native AArch64 bit-field member reads ! pack struct bit-fields into their declared storage unit and extract scalar member values by bit offset and width.
V66: Native AArch64 calls ! lower function-pointer callees with the same argument ABI as direct calls and branch via the computed callee address.
V67: Native AArch64 `typeof` declarations ! resolve `typeof(expr)` from sema's expression type and then apply declarator ops such as pointer suffixes.
V68: Native AArch64 record compound assignment ! assign record compound literals to addressable lvalues by zeroing the destination and storing positional or member-designated scalar fields.
V69: Native AArch64 global assignment ! store scalar and pointer values to file-scope objects through symbol addresses instead of requiring a local stack slot.
V70: Native AArch64 local declaration types ! allocate local slots from sema-bound `VarSymbol.type_` when available, preserving anonymous record identities and function-pointer member types.
V71: Native AArch64 address formation ! allow pointer-valued cast expressions as effective addresses for subscript and dereference lowering.
V72: Native AArch64 function declarator types ! preserve resolved parameter types in `fn` declarator ops when matching anonymous records and computing layout/offsetof.
V73: Native AArch64 record returns ! return small integer/pointer-only records in x0/x1 according to field order and layout offsets.
V74: Native AArch64 global char arrays ! emit string-literal initializers into file-scope `char`/`signed char`/`unsigned char` arrays with C null-padding/truncation rules.
V75: Native AArch64 global pointer initializers ! emit Mach-O relocations for identifier function designators and file-scope object addresses in pointer-typed data.
V76: Native AArch64 global record initializers ! support member designators by mapping initializer items to fields before emission and zero-fill omitted fields/padding.
V77: Native AArch64 global record initializers ! initialize positional anonymous struct/union members at their direct layout offset.
V78: Native AArch64 array expression decay ! emit member-array addresses as rvalues, matching local/static/global array decay.
V79: Native AArch64 local initializers ! dispatch block-scope `InitList` by destination type, supporting record locals as well as arrays.
V80: Native AArch64 address formation ! allow pointer-valued call results as subscript/dereference bases and preserve index/address/RHS value registers across calls used while computing the lvalue address.
V81: Native AArch64 conversions ! lower mixed integer/floating conversions with target signedness for usual arithmetic conversions, casts, and comparisons.
V82: Native AArch64 function pointers ! lower unary `*` of function pointers as a function designator value that decays back to the callable pointer in rvalue contexts.
V83: Native AArch64 global pointer initializers ! emit relocations to addressable global/static object members as `symbol+layout_offset`.
V84: Native AArch64 static locals ! resolve pointer initializers between static locals in the same function to function-local data labels.
V85: Native AArch64 subscript ! load pointer-valued member/subscript bases as pointer rvalues while keeping array bases as addresses.
V86: Native AArch64 prologue/epilogue ! materialize frame-record addresses when stack offsets exceed `stp/ldp` immediate encoding limits.
V87: Native AArch64 variadic definitions ! `__builtin_va_arg` reads the current Darwin stack slot, advances `__builtin_va_list`, and returns scalar integer/pointer values.
V88: Native AArch64 pointer arithmetic ! decay array expression values to element pointers before binary pointer arithmetic or comparison.
V89: Native AArch64 unary dereference ! treat array expression operands as decayed element addresses so `*record.array` reads the first element.
V90: Native AArch64 compound literals ! allocate function-scope compound literals in anonymous stack slots and initialize them before address-based use such as record return.
V91: Native AArch64 small unions ! pass, return, load, and store integer-sized unions as same-sized unsigned integer register values.
V92: Native AArch64 global union initializers ! honor member designators by selecting the named union member before emitting data and zero-padding the union tail.
V93: Native AArch64 address formation ! evaluate comma-expression left operands for side effects and form the address of the right lvalue operand.
V94: Native AArch64 aggregate assignment ! copy same-sized addressable aggregate lvalues byte-for-byte for struct/union assignment.
V95: Native AArch64 record compound initialization ! copy aggregate field initializers into designated aggregate fields by layout size.
V96: Native AArch64 HFA returns ! return and assign homogeneous double records through consecutive FP return registers.
V97: Native AArch64 large record returns ! callee writes indirect aggregate return values through the hidden x8 result buffer.
V98: Native AArch64 local aggregate initialization ! initialize aggregate locals from same-sized addressable aggregate expressions by memory copy.
V99: Native AArch64 record returns ! forward call-returned small/HFA aggregate registers directly when returning a call expression of the same ABI shape.
V100: Native AArch64 HFA call arguments ! spill earlier FP argument registers around nested HFA-returning argument calls and then move returned FP registers into the argument slot.
V101: Native AArch64 scalar conditions ! compare floating conditions and unary `!` operands with `fcmp reg, #0.0`, not integer `cmp`.
V102: Native AArch64 local arrays ! complete block-scope incomplete array slot lengths from initializer lists before frame layout.
V103: Native AArch64 global array initializers ! honor constant index designators, including enum constants, and zero-fill sparse elements.
V104: Native AArch64 unary arithmetic ! lower floating unary minus with `fneg`, not integer `neg`.
V105: Native AArch64 float literals ! emit 4-byte float constants in Darwin `__literal4` and 8-byte double constants in `__literal8`.
V106: Native AArch64 call ABI ! pass and spill small integer/pointer records by value through consecutive x argument registers.
V107: Native AArch64 stack frames ! materialize stack adjustments and local slot addresses when frame sizes or offsets exceed instruction immediate ranges.
V108: Native AArch64 declarations ! treat sema-validated `_Static_assert` declarations as codegen no-ops.
V109: Native AArch64 record layout ! size structs with trailing flexible array members as the aligned offset of the flexible member, while allowing static initializers to append explicit flexible-array bytes.
V110: Native AArch64 global emission ! a file-scope tentative definition followed by an initialized definition emits exactly one data symbol, using the initialized definition.
V111: Native AArch64 aggregate initialization ! brace-elided scalar zero initializers for nested aggregate members leave the already-zeroed aggregate storage valid.
V112: Native AArch64 global record initializers ! member designators that name promoted fields inside anonymous nested records initialize the containing anonymous field without losing sibling designators.
V113: Native AArch64 call ABI ! pass and return non-HFA records up to 16 bytes as consecutive integer chunks even when they contain more than two scalar or anonymous aggregate fields.
V114: Native AArch64 type resolution ! block-scope tagged record definitions and later same-tag uses resolve to sema's scoped record identity when sizing locals and member access.
V115: Native AArch64 call ABI ! when a call-returned small record/union is used as a later argument, preserve earlier argument registers and move returned chunks into the target argument registers.
V116: Native AArch64 bit-field member writes ! assign scalar values to bit-field members by updating only the selected bit range in the containing storage unit.
V117: Native AArch64 string literals ! materialize addressable static string storage for array-decay, subscript, and unary-address contexts, not only direct pointer rvalues.
V118: Native AArch64 large record-return calls ! when initializing an addressable aggregate local, pass that local slot as the hidden x8 result buffer and leave no scalar materialization path.
V119: Native AArch64 large record-return calls ! when assigning to an addressable aggregate lvalue, pass the lvalue address as the hidden x8 result buffer instead of scalarizing the call result.
V120: Native AArch64 large record returns ! when returning a call result with the same indirect record-return ABI, forward the current hidden result buffer to the nested call.
V121: Native AArch64 global pointer initializers ! resolve optional casts of `&` file-scope compound literals to static compound-literal storage labels.
V122: Native AArch64 call ABI ! pass large by-value record arguments through caller-side temporary copies and spill callee parameters from the received pointer, preserving by-value isolation.
V123: Native AArch64 local array initializers ! initialize arrays of record elements from nested initializer lists and zero-fill omitted aggregate elements.
V124: Native AArch64 call ABI ! pass conditional-expression small record/union arguments by evaluating only the selected branch and loading that branch's ABI fields.
V125: Native AArch64 record returns ! return conditional-expression small record/union values by evaluating only the selected branch and loading that branch's ABI fields.
V126: Native AArch64 global record/union initializers ! preserve nested member designator paths such as `.outer.inner = value` when grouping initializer items for the selected aggregate member.
V127: Native AArch64 large record-return calls ! materialize call expressions into compiler-owned temporary slots when an addressable aggregate value is needed for member access or copy.
V128: Native AArch64 aggregate initialization ! initialize addressable aggregate locals from conditional expressions by evaluating only the selected branch and copying/constructing it into the destination.
V129: Native AArch64 record compound initialization ! recursively initialize designated record/union fields whose initializer is a nested initializer list.
V130: Native AArch64 array expression decay ! emit extern incomplete array identifiers as symbol addresses in rvalue contexts, not scalar loads.
V131: Native AArch64 update expressions ! support prefix/postfix `++`/`--` on file-scope scalar identifiers by storing through their symbol address.
V132: Native AArch64 record-return calls ! materialize small record/union call expressions into compiler-owned temporary slots when member access requires an addressable aggregate value.
V133: Native AArch64 stack frames ! reserve scratch space for indirect record returns that copy an addressable non-compound expression into the hidden result buffer.
V134: Native AArch64 global pointer initializers ! resolve `&global_array[constant].member` as a Mach-O relocation to `symbol+layout_offset`.
V135: Native AArch64 large record returns ! return conditional-expression aggregate values by evaluating only the selected branch and writing it into the hidden result buffer.
V136: Native AArch64 global record initializers ! pack bit-field member designator constants into their ABI storage units and zero-fill omitted bits.
V137: Native AArch64 global pointer initializers ! decay addressable member arrays reached through constant pointer/member expressions into `symbol+layout_offset` relocations.
V138: Native AArch64 block-scope function declarations ! declare callable symbols without allocating stack storage or emitting local initialization code.
V139: Native AArch64 large record-return calls ! expression statements and otherwise discarded results still pass a compiler-owned hidden result buffer.
V140: Native AArch64 global floating initializers ! fold floating constant arithmetic and emit target-sized IEEE bits for static data.
V141: Native AArch64 local arrays ! complete block-scope incomplete char array lengths from string literal initializers before frame layout and initialize stack bytes including the terminator.
V142: Native AArch64 local arrays ! evaluate constant array bounds such as `sizeof(local)` before stack slot allocation.
V143: Native AArch64 bit-field member writes ! compound assignments update only the selected bit range without taking the bit-field address.
V144: Native AArch64 global pointer initializers ! fold constant conditional expressions before resolving selected address relocations.
V145: Native AArch64 array expression decay ! subscript results whose element type is still an array decay to that row address in rvalue contexts.
V146: Native AArch64 atomic builtins ! lower C11/GNU atomic load/store/RMW/CAS/fence operations to native instructions without unresolved `__atomic_*` or `__c11_atomic_*` symbols.
V147: Native AArch64 inline functions ! emit used `static inline` function bodies as local symbols while leaving unused inline bodies un-emitted.
V148: Native AArch64 void handling ! treat qualified `void` call/cast/conditional/return result types as non-materialized void, not scalar register values.
V149: Native AArch64 Darwin variadic calls ! pass variadic record/union arguments using Darwin stack ABI: <=16-byte aggregates copied into stack slots and larger aggregates passed via caller-owned temporary copy pointers.
V150: Native AArch64 bit-field member updates ! lower prefix/postfix `++`/`--` by load/modify/store of the selected bit range while preserving postfix result registers.
V151: Native AArch64 global pointer initializers ! fold casted pointer-plus-integer address constants such as `(T *)((unsigned char *)&global + offsetof(...))` into `symbol+offset` relocations.
V152: Native AArch64 inline functions ! emit any referenced inline function body as a TU-local symbol, including extern inline and function designators in conditionals/global initializers, while keeping unreferenced inline bodies un-emitted.
V153: Native AArch64 compiler builtins ! lower common GCC/Clang builtins used by system/CPython C (`expect`, `unreachable`, `assume_aligned`, `alloca`, bit operations, float constants/classifiers/`fabs`, `flt_rounds`, `frame_address`, `va_copy`, `assert`) without unresolved `__builtin_*` or `_assert` symbols.
V154: Native AArch64 Darwin extern data symbols ! materialize external variable addresses through `@GOTPAGE/@GOTPAGEOFF` and load scalar extern values from that GOT-resolved address; direct `@PAGE/@PAGEOFF` extern data relocations ⊥.
V155: Native AArch64 Darwin extern function designators ! materialize addresses of declared-but-not-defined external functions through `@GOTPAGE/@GOTPAGEOFF`; direct calls still use branch relocations and TU-defined function addresses still use local page relocations.
V156: Native AArch64 call ABI ! when a later argument or indirect callee expression contains a nested call, spill and restore earlier integer/pointer and FP argument registers so the nested call cannot overwrite already evaluated arguments.
V157: Native AArch64 scalar binary expressions ! preserve the evaluated left operand while recursively evaluating the right operand, including arithmetic, comparisons, shifts, and RHS calls.
V158: Native AArch64 local array initialization ! scalar element initializers evaluate their value before recomputing the destination element address, so expression lowering cannot clobber the pending store address.
V159: Native AArch64 stack accesses ! every frame, scratch, spill, and outgoing argument slot whose SP offset exceeds the immediate range must materialize an address in a scratch GPR before load/store; assembler-invalid `[sp, #large]` operands ⊥.
V160: Native AArch64 call ABI ! while evaluating any later argument or indirect callee expression, spill and restore all earlier prepared integer/pointer and FP argument registers; ordinary conditionals, casts, address expressions, and arithmetic may clobber caller-scratch argument registers even without nested calls.
V161: Native AArch64 local scalar compound assignment ! preserve the old lvalue value across RHS evaluation before applying the compound operator; RHS lowering may reuse caller-scratch temporaries such as x9.
V162: Native AArch64 update expressions ! when the update result is requested in the normal lvalue-address scratch register, use a distinct address register so postfix/prefix load-modify-store does not store through the old value.
V163: Native AArch64 aggregate copy/address reloads ! large SP-offset scratch materialization must not clobber a live aggregate source address register such as x12 before the byte copy.
V164: Native AArch64 small record/HFA call-result arguments ! preserve earlier argument registers using planned scratch spills, not dynamic `sp` adjustment, and move overlapping return registers into later argument registers from high to low.
V165: Native AArch64 subscript address scaling ! for non-power-of-two element sizes, the scale scratch register must be distinct from both the base-address register and the index register.
V166: Native AArch64 nested subscript address formation ! an outer subscript index register must remain live while recursively lowering its base expression, so nested subscript levels use distinct index scratch registers.
V167: Native AArch64 string literals ! wide string literals (`L`, `u`, `U`) emit target-width zero-terminated storage and pointer initializers reference that storage; treating wide strings as narrow `__cstring` bytes ⊥.
V168: Native AArch64 nested subscript scaling ! non-power-of-two scale scratch registers must avoid every live outer subscript index register, not just the current base/index pair.
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
V288: LLVM `llc` resolution ! target=llvm object/link paths discover candidates through `XCC_LLC`, `LLVM_CONFIG`, or `PATH` and accept only executables whose `--help` stdout contains LLVM `llc` markers; a single hardcoded path or unverified same-name executable ⊥.
V289: Driver language standard flags ! CC-driver `-std=<mode>` controls preprocessing, parsing, and sema through `FrontendOptions.std`; accepting `-std=c11` while compiling in GNU mode ⊥.
V290: Driver generated-output actions ! `-S`/`-c` with multiple C inputs either derive one default output per input or reject explicit `-o`; overwriting one output with the last generated file ⊥.

## §T TASKS
id|status|task|cites
T1|x|scaffold stdlib-only Python package + `xcc` console script|V1,I.cmd
T2|x|implement frontend pipeline preprocessor→lexer→parser→sema|I.file
T3|x|implement LLVM IR backend through libLLVM-C + `llc`|V9,V288,I.file
T4|x|replace backend modes with target selection defaulting to `llvm`|V13,V14,I.cmd
T5|x|add unit suites for lexer/parser/sema/frontend/codegen/driver|V4,V18,I.cmd
T6|x|delete CPython-specific trial harness and tests|V15,V16,I.file
T7|x|record current CPython frontend/backend status in `CHANGELOG.md`|I.file
T8|x|record CPython build-loop lessons in `LESSONS.md`|I.file
T9|.|add project-agnostic real-build capture/replay design|V16,V17,I.cmd
T10|.|add project-agnostic compile-command replay harness from real build logs|V16,V17,I.cmd
T11|.|add clang-oracle helpers for layout/conversion/codegen regression tests|V5,V6,V7
T12|.|add generic single-file regression workflow docs/examples using minimized C + clang oracle|V4,V5,V9
T13|.|expand ABI/layout tests for structs, unions, bit-fields, anonymous records|V6
T14|.|expand initializer tests for nested aggregate/static-local/global cases|V8
T15|.|expand control-flow IR tests around ternary/logical/switch/goto/labels|V9,V10,V12
T16|.|use real-build integration gate before large changes|V15,V17,V22
T17|.|turn CPython-discovered failures into generic minimized C regression tests|V4,V5,V15
T18|.|verify full target `CC="xcc" ./configure && make` after high-risk codegen/sema changes|§G,V21
T19|x|expand native AArch64 backend from scalar leaf subset to calls/control-flow/memory needed by configure probes|V26,V27,I.cmd
T20|x|make `CC="xcc --target=aarch64-apple-darwin" ./configure` pass without LLVM fallback|V26,V27,I.cmd
T21|x|compile CPython objects with native AArch64 target after deleting stale `.o` files|V21,V26,V27,I.cmd
T22|x|link native AArch64 CPython `python.exe` and run smoke imports on this machine|V26,V28,I.cmd
T23|x|add `x86_64-linux-gnu` target driver, Linux target macros/includes, and initial native SysV assembly backend smoke path|V169,V170,V171,I.cmd
T24|.|expand native x86_64 Linux backend from scalar/control-flow/call subset to CPython configure/build semantics|V169,V171,V182,V183,V184,V185,V186,V187,V188,V189,V190,V191,V192,V193,V194,V195,V196,V197,V198,V199,V200,V201,V202,V203,V204,V205,V206,V207,V208,V209,V210,V211,V212,V213,V214,V215,V216,V217,V218,V219,V220,V221,V222,V223,V224,V225,V226,V227,V228,V229,V230,V231,V232,V233,V234,V235,V236,V237,V238,V239,V240,V241,V242,V243,V244,V245,V246,V247,V248,V249,V250,V251,V252,V253,V254,V255,V256,V257,V274,V275,V276,V277,V278,V279,V280,V281,V282,V283,V284,V285,V286,V287,I.cmd
T25|.|compile and link CPython on gpu02 with `CC="xcc"` and run smoke import|V169,V172,V274,V275,V276,V277,V278,V279,V280,V281,V282,V283,V284,V285,V286,V287,I.cmd

## §B BUGS
id|date|cause|fix
B1|2026-05-26|GNU `void return expr;` skipped operand sema/codegen and lost call typemap|V23
B2|2026-05-26|macro arg collector stopped at block comments/inactive directives inside invocation|V24
B3|2026-05-26|sparse designated incomplete array used item count, truncating CPython function offset table|V25
B4|2026-05-26|native AArch64 rejected empty statement in Autoconf compiler-works probe|V29
B5|2026-05-26|native AArch64 tried to emit unused inline header bodies before user code needed them|V30
B6|2026-05-26|native AArch64 treated `(void)expr` as materialized scalar void in Autoconf undeclared-builtin probe|V31
B7|2026-05-26|native AArch64 rejected `SizeofExpr`, causing configure to mis-detect fundamental types as absent or size 0|V32
B8|2026-05-26|native AArch64 frame collection missed block-local declarations inside configure `if` branches|V33
B9|2026-05-26|native AArch64 passed Darwin variadic `fprintf` args in registers, corrupting configure sizeof output|V34
B10|2026-05-26|native AArch64 rejected `__builtin_offsetof` in configure alignment probes|V35
B11|2026-05-26|native AArch64 could not compile Autoconf float word-order probe and falsely accepted x64 inline asm after stripping GNU asm|V36
B12|2026-05-26|native AArch64 rejected `SwitchStmt` in CPython token dispatch tables|V37
B13|2026-05-26|native AArch64 rejected string literals in global pointer-array initializers such as token name tables|V38
B14|2026-05-26|native AArch64 emitted duplicate storage for an `extern` declaration followed by the real global definition|V39
B15|2026-05-26|native AArch64 rejected record member expressions in CPython parser sources|V40
B16|2026-05-26|native AArch64 rejected assignment to record member lvalues in CPython parser sources|V41
B17|2026-05-26|native AArch64 rejected compound assignment to member and member-array lvalues in CPython parser sources|V42
B18|2026-05-26|native AArch64 rejected pointer dereference lvalues in CPython parser sources|V43
B19|2026-05-26|native AArch64 rejected `WhileStmt` in CPython parser sources|V44
B20|2026-05-26|native AArch64 rejected external global variable reads such as CPython exception objects|V45
B21|2026-05-26|native AArch64 rejected `++`/`--` update expressions in CPython parser sources|V46
B22|2026-05-26|native AArch64 rejected pointer comparisons in CPython parser sources because pointer operands fell through to usual arithmetic conversion|V47
B23|2026-05-26|native AArch64 rejected `ForStmt` in CPython parser sources|V48
B24|2026-05-26|native AArch64 rejected `ConditionalExpr` in CPython parser sources|V49
B25|2026-05-26|native AArch64 rejected local record declarations such as `struct token new_token` because frame slots required scalar type info|V50
B26|2026-05-26|native AArch64 rejected `goto error` cleanup control flow in CPython parser sources|V51
B27|2026-05-26|native AArch64 rejected block-scope `static const char * const[]` declarations in CPython parser sources as unsupported locals|V52
B28|2026-05-26|native AArch64 rejected local pointer-array initializer lists in CPython helper calls|V53
B29|2026-05-26|native AArch64 tried to load a local pointer array aggregate when CPython passed it as a decayed function argument|V54
B30|2026-05-26|native AArch64 tried to load a local homogeneous double record when CPython passed `Py_complex` by value|V55
B31|2026-05-26|native AArch64 rejected CPython calls with more than eight arguments instead of using stack argument slots|V56
B32|2026-05-26|native AArch64 rejected variadic function definitions and `__builtin_va_list` in CPython parser error helpers|V57
B33|2026-05-26|native AArch64 emitted invalid `add #imm` for large CPython record/member offsets|V58
B34|2026-05-26|native AArch64 could not size anonymous records containing enum members because codegen resolved enum specs differently from sema|V59
B35|2026-05-26|native AArch64 rejected `DoWhileStmt` in CPython parser action helpers|V60
B36|2026-05-26|native AArch64 rejected CPython parser lookahead calls that pass `_PyPegen_expect_token` as a function pointer|V61
B37|2026-05-26|native AArch64 keyed local stack slots only by name, so a later block-local `b` reused an earlier unrelated `b` slot and member access used the wrong record type|V62
B38|2026-05-26|native AArch64 accepted only a subset of scalar compound assignment operators and rejected parser capacity growth via `*=`|V63
B39|2026-05-26|native AArch64 rejected file-scope pointer initializers that decay from compound literals instead of emitting anonymous static storage|V64
B40|2026-05-26|native AArch64 treated bit-field members as unaddressable missing fields and rejected reads such as packed `state.kind`|V65
B41|2026-05-26|native AArch64 allowed only identifier callees and rejected generic function-pointer calls such as struct member callbacks|V66
B42|2026-05-26|native AArch64 treated GNU `typeof` as an ordinary type name and could not allocate slots for `typeof(expr)` locals|V67
B43|2026-05-26|native AArch64 rejected function-scope record compound literals used to assign designated scalar fields into an existing aggregate lvalue|V68
B44|2026-05-26|native AArch64 identifier assignment always required a local slot and rejected writes to file-scope function-pointer objects|V69
B45|2026-05-26|native AArch64 re-resolved local TypeSpec for anonymous record typedefs and lost the sema-assigned record identity when function-pointer members were present|V70
B46|2026-05-26|native AArch64 subscript address formation required an lvalue base and rejected pointer-valued casts used as byte-addressed bases|V71
B47|2026-05-26|native AArch64 lowered function declarator ops as unprototyped placeholders, so anonymous records containing function-pointer fields failed structural matching for `offsetof`|V72
B48|2026-05-26|native AArch64 required scalar return types and rejected small record-return helpers such as `PySendResultPair`|V73
B49|2026-05-26|native AArch64 treated file-scope `char[N] = \"...\"` initializers as scalar data and rejected doc string arrays|V74
B50|2026-05-26|native AArch64 rejected identifier initializers for global function-pointer fields instead of emitting symbol relocations|V75
B51|2026-05-26|native AArch64 rejected file-scope record member designators such as type-object tail fields|V76
B52|2026-05-26|native AArch64 rejected positional initialization of anonymous union members inside file-scope records|V77
B53|2026-05-26|native AArch64 loaded member arrays as scalars instead of decaying `record.array` to the element base address|V78
B54|2026-05-26|native AArch64 routed every block-scope `InitList` through the local array initializer and rejected local record initialization|V79
B55|2026-05-26|native AArch64 rejected pointer-returning calls used as subscript bases and let calls during lvalue address formation clobber precomputed index or RHS value registers|V80
B56|2026-05-26|native AArch64 rejected integer-to-double usual arithmetic conversion in bytearray growth comparisons|V81
B57|2026-05-26|native AArch64 treated unary `*` of a function pointer as an ordinary scalar function type instead of an rvalue function designator|V82
B58|2026-05-26|native AArch64 rejected file-scope pointer initializers that take the address of nested global object members|V83
B59|2026-05-26|native AArch64 emitted static local data without the owning function scope, so sibling static local pointer initializers could not resolve|V84
B60|2026-05-26|native AArch64 treated pointer-valued member expressions used as subscript bases as field addresses instead of loaded pointer values|V85
B61|2026-05-26|native AArch64 emitted large frame-record save/restore offsets directly in `stp/ldp`, exceeding AArch64 immediate limits|V86
B62|2026-05-26|native AArch64 implemented `va_start`/`va_end` but rejected `__builtin_va_arg` in variadic CPython formatting helpers|V87
B63|2026-05-26|native AArch64 rejected `array + integer` because binary pointer arithmetic saw the undecayed array type|V88
B64|2026-05-26|native AArch64 rejected unary `*` on array member expressions such as flexible byte storage|V89
B65|2026-05-26|native AArch64 could not take the address of function-scope record compound literals used as return values|V90
B66|2026-05-26|native AArch64 treated `_PyStackRef` union return/argument/member values as unsupported scalars instead of integer-sized ABI values|V91
B67|2026-05-26|native AArch64 rejected global union initializers that use `.member` designators|V92
B68|2026-05-26|native AArch64 rejected comma expressions used as addressable lvalues after assertion side effects|V93
B69|2026-05-26|native AArch64 treated struct assignment through a pointer as scalar store instead of aggregate memory copy|V94
B70|2026-05-26|native AArch64 tried to load aggregate locals used as designated fields inside record compound literals|V95
B71|2026-05-26|native AArch64 did not recognize homogeneous double record call returns such as `Py_complex`|V96
B72|2026-05-26|native AArch64 rejected large `PyStatus` record-returning functions instead of using the x8 indirect result buffer|V97
B73|2026-05-26|native AArch64 tried to load aggregate locals used as initializers for same-type aggregate locals|V98
B74|2026-05-26|native AArch64 tried to take the address of call-returned HFA records instead of forwarding return registers|V99
B75|2026-05-26|native AArch64 used C argument index as FP register index and could not pass HFA call results as later HFA arguments|V55,V100
B76|2026-05-26|native AArch64 spilled HFA function parameters from integer registers instead of FP registers on function entry|V55
B77|2026-05-26|native AArch64 emitted integer `cmp` for floating-point conditions in complex arithmetic|V101
B78|2026-05-26|native AArch64 tried to allocate block-scope incomplete arrays with `[-1]` length instead of initializer-completed length|V102
B79|2026-05-26|native AArch64 rejected global array initializers using enum-valued index designators|V103
B80|2026-05-26|native AArch64 emitted integer `neg` for floating unary minus in floatobject code|V104
B81|2026-05-26|native AArch64 mixed 4-byte float literals into Darwin `__literal8`, producing invalid section size at link|V105
B82|2026-05-26|native AArch64 tried to scalar-load small by-value record arguments such as list sort slices|V106
B83|2026-05-26|native AArch64 emitted oversized immediates for large listsort stack frames and byte local slots|V107
B84|2026-05-26|native AArch64 rejected sema-validated `_Static_assert` declarations in longobject sources|V108
B85|2026-05-26|native AArch64 treated a trailing flexible array member as an unsized record field and rejected `sizeof(struct tag)` in dictobject sources|V109
B86|2026-05-26|native AArch64 emitted both a tentative file-scope definition and the later initialized definition, duplicating memoryobject type symbols|V110
B87|2026-05-26|native AArch64 tried to copy scalar `0` into a nested struct member for brace-elided local aggregate initialization|V111
B88|2026-05-26|native AArch64 collected a nested block local slot type from a later same-name function-scope declaration, so union member access used the wrong active declaration type|V62
B89|2026-05-26|native AArch64 global initializer designator lookup ignored promoted members inside anonymous union/struct fields such as object header refcount flags|V112
B90|2026-05-26|native AArch64 treated a 16-byte by-value record with anonymous union fields as scalar because the small-record ABI path only handled one or two direct fields|V113
B91|2026-05-26|native AArch64 resolved a block-scope tagged record as an unscoped file tag, so Autoconf's `const` probe could not allocate `struct s` locals|V114
B92|2026-05-26|native AArch64 tried to take the address of a call-returned small union used as a later function argument and would clobber earlier argument registers|V115
B93|2026-05-26|native AArch64 assigned to bit-field members by taking their address, which C forbids and the backend cannot materialize|V116
B94|2026-05-26|native AArch64 could emit string literals as pointer rvalues but rejected address formation for string literal arrays used by subscript expressions|V117
B95|2026-05-26|native AArch64 initialized large aggregate locals from calls by trying to scalarize the returned struct instead of passing the destination slot as the hidden x8 result buffer|V118
B96|2026-05-26|native AArch64 assigned large aggregate call results by trying to store scalar return registers instead of passing the destination lvalue address as the hidden x8 result buffer|V119
B97|2026-05-26|native AArch64 returned a large aggregate call result by trying to address a non-materialized call result instead of forwarding the current hidden x8 result buffer|V120
B98|2026-05-26|native AArch64 global pointer initializers handled direct compound literals but rejected casted addresses of file-scope compound literals|V121
B99|2026-05-26|native AArch64 treated large by-value record parameters as scalar arguments instead of passing and spilling an ABI-required temporary copy pointer|V122
B100|2026-05-26|native AArch64 local array initializer assumed scalar elements and rejected arrays whose elements are anonymous records with nested initializer lists|V123
B101|2026-05-26|native AArch64 tried to take the address of conditional small-union call arguments instead of selecting and loading the chosen branch's ABI fields|V124
B102|2026-05-26|native AArch64 returned conditional small-union values by trying to take the address of the conditional expression instead of selecting a branch|V125
B103|2026-05-26|native AArch64 global initializer grouping discarded nested designator paths and treated the final scalar as an initializer for the whole nested aggregate|V126
B104|2026-05-26|native AArch64 member access on large record-return calls tried to use scalar return registers instead of materializing the indirect result into a temporary slot|V127
B105|2026-05-26|native AArch64 aggregate local initialization from a conditional expression tried to take the address of the conditional instead of writing the selected branch into the destination|V128
B106|2026-05-26|native AArch64 rejected nested initializer lists for designated record fields inside local record compound initialization|V129
B107|2026-05-26|native AArch64 treated extern incomplete array identifiers as scalar variables instead of decaying them to their symbol address|V130
B108|2026-05-26|native AArch64 update expressions on file-scope identifiers required a local stack slot and rejected global counters such as `_PyOS_optind++`|V131
B109|2026-05-26|native AArch64 member access on small record-return calls tried to take the address of a non-pointer call result instead of spilling returned ABI fields to a temporary slot|V132
B110|2026-05-26|native AArch64 indirect record returns used scratch while copying ordinary addressable return expressions but frame planning did not reserve scratch space|V133
B111|2026-05-26|native AArch64 global pointer initializers could take addresses of global members but not members reached through constant global array subscripts|V134
B112|2026-05-26|native AArch64 indirect record returns tried to take the address of conditional aggregate return expressions instead of lowering selected branches into the hidden result buffer|V135
B113|2026-05-26|native AArch64 global record initializers rejected bit-field members instead of packing constant field values into their storage unit|V136
B114|2026-05-26|native AArch64 global pointer initializers rejected member-array decay reached through constant pointer member expressions such as `(&runtime.main)->dtoa.preallocated`|V137
B115|2026-05-26|native AArch64 frame planning treated block-scope function declarations as stack locals and tried to allocate storage for function types|V138
B116|2026-05-26|native AArch64 emitted discarded large record-return calls without providing the ABI-required hidden result buffer|V139
B117|2026-05-26|native AArch64 global floating initializers accepted only literal floats and rejected constant floating arithmetic such as `9007199254740992. * 9007199254740992.e-256`|V140
B118|2026-05-26|native AArch64 ignored existing GNU void-return-expression invariant and rejected the return instead of emitting operand side effects|V23
B119|2026-05-26|native AArch64 completed local incomplete arrays from initializer lists but not from string literals, so `char name[] = \"...\"` kept length `[-1]` during frame layout|V141
B120|2026-05-26|native AArch64 local array declarations with constant expression bounds such as `sizeof(marker)` reached frame layout as `[-1]` arrays|V142
B121|2026-05-26|native AArch64 compound assignment to bit-field members used generic address formation and rejected the invalid bit-field address instead of using bit-field load/store|V143
B122|2026-05-26|native AArch64 global pointer initializers rejected constant conditional address expressions instead of folding the condition and emitting the selected relocation|V144
B123|2026-05-26|native AArch64 subscript expressions always scalar-loaded the element and rejected multidimensional array rows such as `const char[4]` instead of decaying them to addresses|V145
B124|2026-05-26|native AArch64 reused `.asciz` escaping for fixed-size `.ascii` char-array data and dropped a significant trailing null byte from each initialized row|V74
B125|2026-05-26|native AArch64 treated C11/GNU atomic builtins as ordinary external calls, causing configure probes to mis-detect libatomic and the final Darwin link to fail on missing `-latomic`|V146
B126|2026-05-26|native AArch64 skipped every inline function body, so calls to used `static inline` header helpers such as atomic wrappers linked as unresolved local functions|V147
B127|2026-05-26|native AArch64 compared call result types to exact `void`, so a typedef-qualified function pointer returning `const void` was incorrectly scalarized|V148
B128|2026-05-26|native AArch64 scalarized variadic aggregate arguments and rejected records such as `mi_memid_t` instead of following Darwin varargs stack layout|V149
B129|2026-05-26|native AArch64 update expressions took bit-field member addresses and postfix lowering could clobber the old-value result register|V150
B130|2026-05-26|native AArch64 global pointer initializers rejected casted byte-address arithmetic around `&global + offsetof(member)` instead of emitting a relocation with addend|V151
B131|2026-05-27|native AArch64 only considered direct calls to static inline functions, so referenced inline function designators and extern inline bodies linked as undefined symbols|V152
B132|2026-05-27|native AArch64 treated common GCC/Clang compiler builtins as ordinary external calls, leaving CPython/system objects with unresolved `__builtin_*` and `_assert` symbols|V153
B133|2026-05-27|native AArch64 lowered float classifiers but missed the Darwin inline math helpers' `__builtin_fabs*` dependencies, leaving classifier wrappers unresolved at link|V153
B134|2026-05-27|native AArch64 emitted referenced header inline bodies with external linkage, so Darwin inline helpers duplicated across translation units|V152
B135|2026-05-27|native AArch64 used direct Mach-O page relocations for external data such as `__stderrp`, producing link fixup errors because imported data has no direct address|V154
B136|2026-05-27|native AArch64 used direct Mach-O page relocations for external function designators such as `malloc` used as a callback, producing link fixup errors|V155
B137|2026-05-27|native AArch64 evaluated `f(a, g())` left-to-right into ABI registers, so `g()` clobbered the already evaluated `a` register and CPython `_freeze_module` crashed in UTF-8 decoding|V156
B138|2026-05-27|native AArch64 evaluated `len > MAX / sizeof(T) - 1` with `len` in x9, then RHS code reused x9, so `_PyMem_RawWcsdup` always took its overflow/no-memory path|V157
B139|2026-05-27|native AArch64 local array initialization kept the destination element address in x11 while evaluating pointer arithmetic initializers, so CPython obmalloc used-pool sentinels were written through the wrong address|V158
B140|2026-05-27|native AArch64 scratch and outgoing-argument spill slots used raw `[sp, #large]` operands in large CPython frames such as `Python/ceval.c`, so Darwin assembler rejected the generated assembly|V159
B141|2026-05-27|native AArch64 preserved earlier call arguments only when a later argument contained a nested call, so `unicode_decode_utf8(s, size, errors ? ... : ..., errors, consumed)` overwrote prepared `s` in x0 while evaluating the conditional third argument and CPython `_freeze_module` crashed in `find_first_nonascii(NULL, 8)`|V160
B142|2026-05-30|native AArch64 local scalar compound assignment kept the old value only in x9 while RHS lowering reused x9, so CPython `_PyObject_VAR_SIZE` computed `nitems + nitems * tp_itemsize`, allocated undersized descriptors, and `_freeze_module` crashed in pymalloc|V161
B143|2026-05-30|native AArch64 postfix update of `(*p_format)++` with the result immediately dereferenced loaded the old pointer into x11 and then stored the incremented pointer through that old value, so CPython `_freeze_module` crashed in `do_mkvalue`|V162
B144|2026-05-30|native AArch64 aggregate assignment in a large stack frame kept the source address in x12, then reloaded the saved destination address using large SP-offset materialization that reused x12, so CPython `list_sort_impl` copied from address `0x1128` and crashed|V163
B145|2026-05-30|native AArch64 saved earlier arguments for call-returned small record arguments by subtracting from `sp`, so nested argument evaluation reloaded locals from shifted offsets; overlapping return-to-argument moves also copied x0→x1→x2/d0→d1→d2 and duplicated the first field|V164
B146|2026-05-30|native AArch64 subscript address formation for non-power-of-two aggregate element sizes reused x12 for the scale constant while x12 held the source base, so CPython `_PyInstructionSequence_InsertInstruction` copied from address `0x84`|V165
B147|2026-05-30|native AArch64 evaluated nested subscripts such as `argv[_PyOS_optind][0]` with the outer index in x10, then recursively lowered the base using x10 for the inner index, so `_bootstrap_python` parsed `./Programs/_freeze_module.py` as an invalid option|V166
B148|2026-05-30|native AArch64 emitted `L""` and other wide string literals as narrow `__cstring` `.asciz` labels, so `_PyOS_GetOpt` initialized `opt_ptr` to the wrong byte string and `_bootstrap_python` reported `Unknown option: -\\0`|V167
B149|2026-05-30|native AArch64 fixed nested subscript index registers but still allowed an inner non-power-of-two scale constant to reuse the outer index register, so CPython `slotdefs_dups[index][i]` computed the wrong slot definition pointer|V168
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
B264|2026-06-04|LLVM target object lowering hardcoded Homebrew `llc` and did not verify that a found same-name executable was LLVM `llc` before compiling IR|V288
B265|2026-06-04|CC-driver `-std=c11` was parsed and forwarded to the delegated tool argv but the frontend always received `std="gnu11"`, so C11 driver invocations accepted GNU-only frontend syntax|V289
B266|2026-06-04|CC-driver `-S`/`-c` computed one output path from the first C input and reused it for every input, so multi-source generated-output commands overwrote earlier outputs instead of rejecting explicit `-o` or deriving per-input defaults|V290
