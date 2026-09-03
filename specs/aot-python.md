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
- Chained assignment to local names evaluates its right-hand side once and
  binds that value to every target in source order.
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
- AOT-V1: Caller-supplied or derived payload identity is checked in a bounded
  exact live index before an adjacent prefix is interpreted as its allocation
  header. An internal header loaded directly from the private allocation head
  may skip a separate lookup, but its exact-index membership and allocation tag
  must be validated before header metadata can direct a pointer write. Static
  or otherwise untracked pointers are nonmovable; missing exact membership or
  an invalid allocation tag fails closed.
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
- AOT-V2: A validation process constructs each identical full-bootstrap
  source/configuration artifact at most once. Structural assertions reuse the
  immutable lowered module and LLVM text, native behavior fixtures reuse one
  executable per configuration, and the native behavior matrix runs outside
  Python line tracing while hosted build orchestration remains coverage-visible.
- AOT-V3: Every module selected by the bootstrap source manifest is accepted by
  the project-owned Python-subset parser before lowering. A refactor of
  bootstrap-reachable compiler code must not introduce syntax outside that
  subset.
- AOT-V4: The first `append` to an unannotated empty list establishes its
  homogeneous element type from the appended expression, including unary
  numeric expressions.
- AOT-V5: Every function reachable from the native compiler entry lowers using
  implemented subset operations; hosted execution alone is not admission to
  the bootstrap closure.
- AOT-V6: The complete lowered compiler closure renders to LLVM with concrete
  scalar operation types, and `llc` accepts that LLVM.
- AOT-V7: Constructing a dataclass through its generated initializer invokes a
  reachable zero-argument `__post_init__` exactly once after field
  initialization; a class with an explicit `__init__` does not gain an
  implicit post-init call.
- AOT-V8: Replacing an element in a tuple-backed container preserves the
  container element representation, including the runtime tag required by a
  heterogeneous scalar/record union.
- AOT-V9: `list(iterable)` returns a fresh tuple-backed container whose later
  mutation cannot change the input, while preserving the input element layout.
- AOT-V10: A value-producing `or` between `T | None` and `T` returns a `T`
  value even when `T` is itself a multi-member union; it must not collapse to
  `None` or lose the selected operand.
- AOT-V11: Constructing a dataclass that extends an exception initializes its
  declared fields from the generated initializer before it is raised, so a
  caught payload and its custom `__str__` observe the supplied values.
- AOT-V12: String slicing clamps explicit positive and negative bounds to the
  source length before copying, matching Python without reading outside the
  source allocation.
- AOT-V13: The native no-callback preprocessor resolves dynamic predefined
  macros at their expansion site, including inside function-like macro
  arguments; their placeholder table entries are never emitted as source.
- AOT-V14: Equality between a heterogeneous tuple slot represented by the
  tagged-object ABI and a concrete scalar compares Python values, not the
  tagged allocation address. This includes compiler type-operation tuples such
  as `("arr", -1)` used to infer incomplete compound-literal array bounds.
- AOT-V15: Integer shifts at or beyond the native word width never inherit the
  target CPU's masked shift count. Their representable low word follows Python
  arithmetic, while constant integer expressions retain enough width for their
  exact value. This includes bounds checks and full-width mask expressions used
  by the compiler's 64-bit bit-field updates.

## Performance Contract

- A claim of at least 1.3x native AOT throughput compares compilers built from
  the same final source, changing only the declared native optimization mode.
  It uses the same production translation unit and flags, at least one warm-up,
  five alternating measured runs, and the median wall time.
- Every compared object must be byte-identical. The optimized compiler must
  also pass the complete native behavior matrix, Stage 0 → 1 → 2 → 3 strong
  bootstrap, and an unmodified CPython `configure && make` integration build;
  a faster compiler with changed output or behavior does not satisfy the gate.

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
