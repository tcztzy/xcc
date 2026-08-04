# AOT native profiling, debugging, and phase timing

XCC's AOT compiler can be built in three modes. The default mode preserves the
existing deterministic, path-independent LLVM text. `debug=True` and
`profile=True` are explicit opt-ins that both add source-level LLVM debug
metadata and native stack-unwind support while retaining the production
optimization level.

For example, this builds a native compiler intended for profiling:

```sh
uv run python -c 'from pathlib import Path; from xcc.aot.bootstrap import build_native_bootstrap; build_native_bootstrap(Path.cwd(), Path("build/aot/xcc-profile"), llc="/opt/homebrew/opt/llvm/bin/llc", profile=True)'
```

Use `debug=True` instead for a debug-labelled build. The hosted and native AOT
builder CLIs also accept `--debug` and `--profile`. Both modes emit:

- one `DIFile` and `DICompileUnit` per source file;
- a `DISubprogram` for every emitted function;
- `DILocation` attachments for function entries and source statements;
- `uwtable` on all emitted definitions; and
- LLVM `llc` options `--frame-pointer=all`, `--emit-dwarf-unwind=always`, and
  `--dwarf-version=4`.

The default mode emits none of this metadata and passes none of those extra
options, so absolute source paths do not enter ordinary bootstrap products.
XCC does not run `dsymutil` automatically: an adjacent dSYM is useful for
distribution or archival, but it is not needed for Mach-O object DWARF,
`sample`, or `atos` validation and would add another nonessential tool to the
build pipeline.

## macOS native tools

Inspect the object and unwind information directly:

```sh
/usr/bin/dwarfdump --debug-info --debug-line build/aot/xcc-profile.o
/opt/homebrew/opt/llvm/bin/llvm-dwarfdump --eh-frame build/aot/xcc-profile.o
/opt/homebrew/opt/llvm/bin/llvm-objdump --disassemble build/aot/xcc-profile
```

The disassembly should contain a real ARM64 frame record such as `stp x29,
x30` followed by `add x29, sp, ...`; the FDE should switch its CFA to `W29`.
Mach-O may use compact unwind as well as DWARF at runtime. Do not force a
`.debug_frame` section: `--emit-dwarf-unwind=always` produces the runtime
`.eh_frame` records needed by stack walkers.

Profile a real native compiler process with `sample`:

```sh
build/aot/xcc-profile -c input.c -o input.o &
profile_pid=$!
/usr/bin/sample "$profile_pid" 10 1 -file build/aot/xcc-profile.sample.txt
wait "$profile_pid"
```

Resolve an address from the report using the report's load address:

```sh
/usr/bin/atos -o build/aot/xcc-profile -arch arm64 \
  -l 0x1004b0000 0x1004b660c
```

For Instruments, the equivalent command-line entry point is:

```sh
xcrun xctrace record --template 'Time Profiler' --launch -- \
  build/aot/xcc-profile -c input.c -o input.o
```

`sample` is the automated acceptance path because it produces a stable text
report. `xctrace` may require an interactive Instruments installation and its
post-processing/export can be unavailable on headless or overloaded hosts.

## Linux `perf`

The same profile/debug build contract is platform-neutral LLVM IR plus
`llc`'s target-specific frame-pointer and DWARF unwind lowering. On Linux,
validate and profile the native ELF binary with:

```sh
readelf --sections build/aot/xcc-profile.o | grep -E 'debug_info|debug_line|eh_frame'
llvm-dwarfdump --eh-frame build/aot/xcc-profile.o
objdump -d build/aot/xcc-profile | less
perf record -g --call-graph fp -- build/aot/xcc-profile -c input.c -o input.o
perf report --stdio
```

`perf record -g --call-graph dwarf,16384` is also supported when DWARF stack
walking is preferred. The macOS test gate cross-lowers the debug IR to
`x86_64-unknown-linux-gnu` and checks ELF `.debug_info`, `.debug_line`,
`.eh_frame`, FDEs, and an `RBP` frame-pointer prologue. That proves the emitted
object contract, but macOS cannot execute Linux `perf`; the two `perf` commands
above remain the Linux runtime acceptance boundary.

## Native phase timing JSON

The native AOT C compiler accepts an optional output path in either form:

```sh
build/aot/xcc-profile -c input.c -o input.o --timing-json timing.json
build/aot/xcc-profile -c input.c -o input.o --timing-json=timing.json
```

The stable `xcc.compile-timing.v1` schema is compact JSON with these fixed
fields:

```json
{
  "schema": "xcc.compile-timing.v1",
  "clock": "monotonic",
  "unit": "nanoseconds",
  "success": true,
  "failed_stage": null,
  "total_ns": 10773396958,
  "phases": {
    "preprocessing": {"duration_ns": 7024246708, "status": "ok"},
    "parser": {"duration_ns": 1154264042, "status": "ok"},
    "sema": {"duration_ns": 1002779417, "status": "ok"},
    "codegen": {"duration_ns": 1037710500, "status": "ok"},
    "llc": {"duration_ns": 554350083, "status": "ok"}
  }
}
```

Timing uses a monotonic nanosecond clock. With no timing option, neither the
clock nor the timed frontend path is called. A preprocessing, parser, sema,
codegen, or `llc` failure writes `success: false`, names `failed_stage`, marks
that phase `error`, and marks later phases `not_run`. An empty, duplicate, or
link-only timing option is rejected. Failure to write the LLVM or requested
timing file makes the compile fail; when the timing destination itself is
unwritable, no JSON can be produced there by definition.

## Python profiling boundary

There are two distinct profiling surfaces:

- When XCC frontend/compiler semantics execute as Python under CPython,
  `profile` and `cProfile` remain valid. A hosted call through `compile_source`
  and `generate_llvm_ir` exposes ordinary entries such as
  `preprocess_source`, `parse`, and `analyze` to `cProfile`.
- Once that compiler has been AOT-lowered into a native executable, its hot
  functions are native machine-code symbols. Use `sample`, Instruments, or
  Linux `perf` for those hotspots.

The native runtime deliberately does not synthesize Python call/return events
for `cProfile`. Doing so would measure an emulated event stream rather than the
native work being optimized.

## Measured cost

The final builds were measured sequentially on macOS ARM64 while compiling the
unmodified CPython `Objects/listobject.c` with its real core include paths.
Every default, profile, debug, and timing-on run produced the same object
SHA-256, `227c5fd9aae42918677546b6404a39045e4f0d82ca13b8d71683b873c9fbcde8`.

| mode | three wall-clock runs (s) | median (s) | executable | AOT object |
| --- | --- | ---: | ---: | ---: |
| default | 10.40, 10.81, 11.19 | 10.81 | 903,096 B | 1,464,040 B |
| profile | 10.31, 12.42, 12.43 | 12.42 | 1,039,560 B | 1,726,208 B |
| debug | 10.42, 10.60, 12.99 | 10.60 | 1,039,560 B | 1,726,208 B |
| profile + timing JSON | 10.38, 10.84, 19.99 | 10.84 | unchanged | unchanged |

Another CPython configure was active on the same host, so the wall results
show substantial scheduling noise; in particular, a negative apparent median
"overhead" must not be interpreted as a speedup. The less scheduler-sensitive
same-round hardware counters measured 63.285 billion retired instructions for
default, 67.727 billion for profile (+7.02%), 67.907 billion for debug (+7.30%),
and 67.835 billion for profile plus timing (+0.16% over profile). Debug/profile
increase the executable by 15.11% and the AOT object by 17.91%; timing adds no
binary size because its code is already present in that profiled compiler and
is reached only by the opt-in argument.
