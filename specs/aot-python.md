# AOT Python and Strong-Bootstrap Contract

## Goal

XCC compiles a documented CPython-3.11-compatible Python subset from ordinary
`.py` source to native machine code. The same source remains runnable on
CPython. A strong bootstrap is complete only when native Stage 1 builds native
Stage 2 and native Stage 2 builds native Stage 3 from repository source, without
CPython, libpython, a CPython AST, or pre-generated AST/IR as a required input.

## Source Contract

- Accepted syntax is a strict CPython 3.11 subset. Custom syntax, marker
  decorators, AOT pragmas, comment directives, and annotation directives are
  forbidden.
- Width names such as `int32`, `int64`, `uint64`, and `usize` remain ordinary
  Python-visible annotations or aliases with valid CPython behavior.
- Stage 0 may use `ast.parse` through the hosted adapter. Native stages parse
  source with the project-owned lexer, parser, and immutable AST.
- A supported construct is implemented in the AOT binder, lowerer, emitter, or
  runtime. Rewriting compiler source merely to avoid an AOT bug is forbidden.
- A source rewrite outside `src/xcc/aot` requires an explicit subset decision,
  CPython oracle, and native oracle or a documented missing gate.
- Runtime source dependencies are Python-standard-library-only under CPython.
  Native stages have no CPython or libpython dependency.

## Stages and CLI

| Stage | Producer | Parser | Required result |
| --- | --- | --- | --- |
| 0 | CPython | hosted CPython adapter allowed | native Stage 1 |
| 1 | native Stage 1 | project subset parser | native Stage 2 |
| 2 | native Stage 2 | project subset parser | native Stage 3 |
| 3 | native Stage 3 | project subset parser | stability witness |

Hosted builds use `python -m xcc.aot build`; native builds use `xcc-aot build`.
Builds declare `--source-root`, `--entry`, `--output`, and `--parser`. Native
mode accepts only `--parser=subset`; strong-bootstrap builds use `--no-cache`.

The native external-process allowlist is the configured LLVM `llc`, system
assembler, system linker, and platform C runtime. Launching Python or loading a
Python module is forbidden.

## Proof Obligations

- Stage 1 and Stage 2 open and parse the declared repository `.py` source set.
  Deleting cached AST, IR, LLVM, or generated code must not break the build.
- The emitted reachability closure includes the subset lexer/parser, binder,
  lowerer, IR, emitter, runtime boundary, and native CLI.
- Native binaries contain no Python C-API dependency and no unresolved
  Python/libpython symbols.
- Stage 2 and Stage 3 agree on normalized LLVM, exported symbols, source
  manifest, and specified behavior fixtures. Unexplained drift fails the gate.
- Module ordering, manifests, normalized LLVM, diagnostics, and tool logs are
  deterministic.
- A native C compiler smoke and a CPython `configure && make` build are
  secondary integration gates; neither substitutes for the stage proof.

## Python Value and Error Semantics

- Supported operations match CPython-visible value, equality, mutation, alias,
  iteration, exception, and formatting behavior. Pointer identity is not value
  equality.
- Fallible calls carry an explicit status/result/error representation through
  handlers and call boundaries. An unhandled error reaches a nonzero CLI exit;
  it never becomes a successful type-default value.
- Tuple/list/set/dict values use stable owning handles. Growth may replace owned
  backing storage without changing the handle. Mutating operations update the
  receiver in place and preserve alias visibility, including self-extension.
- Heterogeneous scalar unions and opaque objects use an explicit tagged
  boundary. Container receivers are unboxed before structural access and
  opaque results are boxed before crossing the boundary. Raw pointer shape is
  never used as a substitute for a runtime type.
- String, tuple, dict, record, `enumerate`, `reversed`, indexing, and f-string
  paths preserve Python order and conversion behavior.

## Native Memory Contract

- Native compilation has bounded allocation growth and peak memory. Resource
  exhaustion fails with a controlled diagnostic before the host or watchdog is
  starved.
- Compiler-owned allocation phases are inserted only from fixed-point
  allocation, escape, capture, and return-provenance analyses. Unknown,
  fallible, capturing, or opaque paths remain conservative.
- Phases form a validated LIFO region stack. Reset frees only the current
  region; commit transfers its complete segment to its parent; exact promotion
  and capture move only validated reachable graphs without changing payload
  addresses.
- Allocation identity is checked in a bounded exact live index before ownership
  metadata is read. Static or otherwise untracked pointers are treated as
  nonmovable; tracked metadata corruption fails closed.
- Allocation metadata remains bounded at 32 bytes per tracked allocation.
  Allocation, reallocation, free, reset, and commit keep the live index and
  ownership depth consistent.
- Every retained pointer outlives its owner. Container writes apply an ownership
  barrier; weak caches are bounded and invalidated before release, resize, mark
  exit, or address reuse.
- Loop iteration regions are used only when every carried and captured value has
  a precise promotable representation. Opaque loop-carried objects disable
  iteration reset.
- Successful fresh pointer returns preserve only the proven result graph or
  safely transfer the complete region to a parent. Unhandled fallible results
  commit their error graph rather than tracing it incompletely.

## Deterministic and Bounded Emission

- Semantic helper identity uses an explicit structural key over IR types;
  diagnostic `repr()` is never a semantic key.
- Record names retained by long-lived work sets are canonical module-owned
  names.
- Promotion and object helpers are reserved once and emitted through finite
  registry drains. The output must not contain duplicate helper definitions.
- Reachability and LLVM rendering avoid repeated whole-collection copies.
  Already-normalized immutable text is reused, no-op string replacement reuses
  its input, and final LLVM assembly retains only one whole-module output
  buffer.
- Large intermediate render graphs are released before the final LLVM and
  normalized LLVM buffers are assembled.

## Implementation Boundaries

| Area | Path |
| --- | --- |
| Project AST, lexer, parser, CPython adapter | `src/xcc/aot/py_ast.py`, `py_lexer.py`, `py_parser.py`, `cpython_ast_adapter.py` |
| Source manifest and dependency order | `src/xcc/aot/source_contract.py` |
| Native and hosted CLI | `src/xcc/aot/cli.py`, `hosted_cli.py`, `__main__.py` |
| Binding and IR lowering | `src/xcc/aot/binder.py`, `ir.py`, `lower.py` |
| Deterministic LLVM text | `src/xcc/aot/llvm_text.py` |
| Native runtime | `src/xcc/aot/core_runtime.py` |

## Acceptance

Changes run focused hosted and native oracles, stage behavior gates, lint, and
type checks. Memory or reachability changes also run the relevant bounded native
build. A strong-bootstrap claim requires the full Stage 0 → 1 → 2 → 3 chain and
all proof obligations above.
