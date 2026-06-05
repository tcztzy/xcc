# Darwin AArch64 Target Spec

## §G GOAL
The `aarch64-apple-darwin` target emits native Darwin AArch64 assembly and can
compile/link CPython to a `python.exe` that starts and runs smoke imports on
this machine.

## §C CONSTRAINTS
- `--target=aarch64-apple-darwin` selects this target explicitly.
- Object and executable paths use direct native assembly, not LLVM IR or `llc`.
- Assembly and relocation rules follow Darwin AArch64/Mach-O conventions.
- Backend fixes generalize to C semantics, ABI, driver compatibility, or
  diagnostics; CPython file/path identity branches are forbidden.

## §I INTERFACES
- cmd: `xcc --target=aarch64-apple-darwin -c source.c -o source.o` → native
  Darwin AArch64 assembly + assembler object.
- cmd: `xcc --target=aarch64-apple-darwin source.c -o exe` → native Darwin
  AArch64 executable; no LLVM IR/`llc`.
- cmd: `CC="xcc --target=aarch64-apple-darwin" ./configure && make` in CPython
  tree → native AArch64 integration gate.
- file: `src/xcc/aarch64_asm.py` → native Darwin AArch64 backend.

## §V INVARIANTS
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

## §T TASKS
id|status|task|cites
T19|x|expand native AArch64 backend from scalar leaf subset to calls/control-flow/memory needed by configure probes|V26,V27,I.cmd
T20|x|make `CC="xcc --target=aarch64-apple-darwin" ./configure` pass without LLVM fallback|V26,V27,I.cmd
T21|x|compile CPython objects with native AArch64 target after deleting stale `.o` files|V21,V26,V27,I.cmd
T22|x|link native AArch64 CPython `python.exe` and run smoke imports on this machine|V26,V28,I.cmd

## §B BUGS
id|date|cause|fix
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
