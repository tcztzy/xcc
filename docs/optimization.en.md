# Optimization: Making Code Run Faster

Optimization is one of the most complex parts of a compiler. The five projects span the full spectrum — from TCC's zero optimization to GCC's hundreds of passes.

## Optimization Levels

### Frontend Optimizations (Language-Aware)

These optimizations leverage C/C++ language semantics above the IR level:

| Optimization | Description | Who Does It |
|-------------|-------------|-------------|
| Constant folding | `3 + 4` → `7` | All |
| Type narrowing | Unnecessary `int` → `short` | GCC, Clang, CCC (narrow pass) |
| NRVO | Named Return Value Optimization | Clang, GCC |
| Virtual function devirtualization | `obj->vf()` → direct call | Clang (requires LTO) |

### IR Optimizations (Architecture-Agnostic)

This is the main optimization battlefield. All IR-capable projects focus here.

#### Dead Code Elimination (DCE)

Remove code that can never execute:

```c
int x = 42;
return 0;
// After: return 0;  // x's assignment eliminated
```

#### Constant Folding & Propagation

```c
int x = 3;
int y = x + 4;    // y = 7 (propagate x=3, fold 3+4)
int z = y * 2;    // z = 14 (propagate y=7, fold 7*2)
```

#### Common Subexpression Elimination (CSE / GVN)

```c
// Before
int a = b + c;
int d = b + c;    // b + c recomputed
// After
int a = b + c;
int d = a;        // reuse a
```

GVN (Global Value Numbering) is a stronger version of CSE — each computation gets a "value number", identical numbers can be reused.

#### Inlining

```c
// Before
static int add(int a, int b) { return a + b; }
int x = add(3, 4);   // call add
// After
int x = 3 + 4;       // body inserted, call overhead gone
```

#### Loop Invariant Code Motion (LICM)

```c
// Before
for (int i = 0; i < n; i++) {
    x = a * b;       // a*b independent of loop variable
    arr[i] = x + i;
}
// After
x = a * b;           // hoisted out, computed once
for (int i = 0; i < n; i++) {
    arr[i] = x + i;
}
```

#### Strength Reduction

Replace expensive operations with cheaper ones:

```c
x * 2  → x << 1       // multiply → shift
x / 8  → x >> 3       // divide → shift (unsigned only)
x * 7  → (x << 3) - x // multiply → shift + subtract
```

## Optimization Lineups

### GCC — 300+ Optimization Passes

GCC has the most massive optimization system, running ~250 passes on GIMPLE (SSA) and ~50 on RTL.

Key pass groups:
```
IPA (Inter-Procedural Analysis)
├── inline (inline decisions)
├── pure-const (pure/const function analysis)
└── cp (constant propagation to call args)

GIMPLE (SSA)
├── ccp (Conditional Constant Propagation)
├── dce (Dead Code Elimination)
├── dom (Dominator Optimization: jump threading + redundancy + const prop)
├── gvn (Global Value Numbering)
├── lim (Loop Invariant Motion)
├── ivopts (Induction Variable Optimization)
├── sra (Scalar Replacement of Aggregates)
└── ... 200+ more

RTL
├── combine (Instruction combination: multiple → one)
├── cse (Common Subexpression Elimination)
├── fwprop (Forward propagation: reg → immediate)
├── sched (Instruction scheduling)
└── peephole2 (Peephole optimization)
```

### Clang/LLVM — Modular Pass Pipeline

LLVM's passes are organized into PassManager pipelines:

```
-O0: No optimization (but mem2reg always runs for IR validity)
-O1: ~50 passes (lightweight, balanced compile time)
-O2: ~150 passes (standard optimization)
-O3: ~170 passes (aggressive: more inlining + vectorization + loop unrolling)
-Os: ~140 passes (code size biased)
-Oz: ~150 passes (minimize code size)
```

Core passes:
```
InstCombine (instruction combination/simplification) — runs 4-6 times
GVN (Global Value Numbering)
LICM (Loop Invariant Code Motion)
Inline (bottom-up inlining with cost model)
SLP Vectorizer (Superword Level Parallelism)
Loop Vectorizer
SimplifyCFG (Control Flow Graph simplification)
Jump Threading
Correlated Value Propagation
```

### CCC — 15 Passes, Lean Design

CCC doesn't have LLVM/GCC's 200+ passes. Its 15 passes cover enough to compile large real-world C projects (PostgreSQL, FFmpeg, Linux kernel):

```
Phase 0: Inline stage
  ┌──────────────────────────────────────────────┐
  │ inline → mem2reg → constant_fold → copy_prop │
  │   → simplify → constant_fold → copy_prop     │
  │   → resolve_asm                              │
  └──────────────────────────────────────────────┘

Main Loop (dirty-tracked, up to 3 rounds):
  ┌──────────────────────────────────────────────┐
  │ cfg_simplify → copy_prop → div_by_const      │
  │   → narrow → simplify → constant_fold        │
  │   → gvn → licm → iv_strength_reduce          │
  │   → if_convert → copy_prop → dce             │
  │   → cfg_simplify → ipcp                      │
  └──────────────────────────────────────────────┘

Cleanup:
  ┌──────────────────────────────────────────────┐
  │ dead_statics → phi elimination               │
  └──────────────────────────────────────────────┘
```

**Dirty tracking**: each pass returns whether it actually modified anything. If a pass did nothing, downstream passes can be skipped. This means 15 passes typically need only 1-2 rounds for most code.

### TCC — Local Peephole

TCC does no IR-level optimization (there is no IR), only local peephole during code generation:

```c
// Within the same expression:
int x = 3 + 4 * 5;  // → emit constant 23 directly
int y = a * 8;      // → sal eax, 3   (shift instead of multiply)
int z = a / 2;      // → sar eax, 1   (positive only)
```

### XCC — Delegating to LLVM

XCC implements zero optimization passes. All optimization is done by LLVM toolchain (`llc`)'s built-in pass pipeline. XCC-generated LLVM IR is the input to LLVM's optimization.

```
XCC generates → LLVM IR → llc (O0/O1/O2/O3) → machine code
```

### XCC Frontend Throughput Optimization

XCC still needs to optimize the compiler implementation itself. The
2026-06-17 profiling loop used `Python/getcompiler.c` from a configured CPython
tree as the representative real-project workload. cProfile showed repeated
preprocessor tokenization as the main avoidable cost: `lex_pp` accounted for
17.296 s cumulative time in the baseline profile.

The accepted changes were:

- lazily materialize `FrontendResult.pp_tokens`, so ordinary compile paths do
  not re-lex the preprocessed source unless a caller requests preprocessor
  tokens;
- add a cheap identifier scan before full macro tokenization, while preserving
  the existing token-rendered spacing behavior once non-predefined macros are
  present.

On the CPython `Python/getcompiler.c` profile, cProfile total time dropped from
49.608 s to 17.690 s, and `lex_pp` cumulative time dropped from 17.296 s to
3.521 s. A parser punctuation-check micro-optimization was tried and reverted
because it did not give a reliable CPython-scale win. The lesson is that
compiler throughput work needs the same discipline as generated-code
optimization: profile first, change one thing, and reject changes that only
look faster in isolation.

The 2026-06-18 validation tightened the measurement and integration rules.
When comparing XCC against GCC or Clang for frontend throughput, XCC is measured
through the mypyc-precompiled import tree, not the pure-Python tree. Rebuilt
`bench-mypyc` on CPython `Objects/listobject.c` measured 4.608, 4.592, and
4.510 seconds, while the same configured CPython file passed syntax-only checks
under Homebrew GCC 15.3.0 at 0.187, 0.176, and 0.181 seconds and Homebrew Clang
22.1.7 at 0.140, 0.118, and 0.140 seconds. These are frontend/syntax timings,
not full object-code throughput timings.

Integration validation also moved from partial object-file smoke tests to a
fresh full CPython build. A clean out-of-tree
`CC=/Users/tcztzy/GitHub/xcc/.venv/bin/xcc ./configure && make -j1`, with
`XCC_LLC=/opt/homebrew/opt/llvm/bin/llc`, completed successfully and checked
116 modules with 0 failed imports. The full build found two issues the earlier
three-file smoke missed: OpenSSL macros passing `const char **` through
`void *`, and CPython's GNU `__extension__ __alignof__(expr)` under C11. The
recurring root cause was insufficient coverage of real-project GNU/system-header
compatibility edges; the fix was to minimize each case against GCC/Clang and
then rerun the full build from a clean directory.

---

## Key Optimization Techniques

### 1. Pass Ordering

Optimization isn't arbitrary stacking — order matters critically.

```
Counter-example: DCE before inline → inlined dead code waits until next DCE round
Correct:
  inline → mem2reg → DCE → GVN
  (inlining exposes more context, mem2reg makes it SSA,
   DCE eliminates inline redundancy, GVN does value analysis on full information)
```

CCC's pass ordering is carefully tuned: after inline, immediately run mem2reg + constant_fold + copy_prop to exploit the newly exposed information.

### 2. Fixpoint Iteration

One optimization may create opportunities for another. The classic approach is **iteration to fixpoint**:

```
while changed:
    run_all_passes()
```

LLVM's strategy: core passes (InstCombine) run 4-6 times scattered through the pipeline, rather than unlimited iteration.

CCC uses **bounded iteration** (max 3 rounds) + **dirty tracking**, balancing effectiveness and compilation time.

### 3. Cost Model

Inlining and loop unrolling can't be done blindly — code bloat hurts I-cache hit rate.

LLVM's inline cost model considers:
- Callee size (in IR instruction count)
- Argument constantness (inlining constant args gives higher payoff)
- Call frequency (only hot paths worth inlining)
- Current function size (prevent excessive bloat of the caller)

---

## Pass Type Summary

| Pass Type | What It Does | Examples |
|-----------|-------------|----------|
| Analysis | Produces results without modifying IR | Alias analysis, dominator tree, loop detection |
| Transform | Modifies IR | Inlining, DCE, LICM |
| Canonicalize | Normalizes IR for subsequent passes | mem2reg (alloca→SSA), SimplifyCFG |

---

Next: [Backend & Code Generation](backend.md) — no matter how well IR is optimized, it must eventually become machine code the CPU can execute.
