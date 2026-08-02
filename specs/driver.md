# Driver and Target Selection Contract

## Goal

Each `xcc` invocation selects exactly one visible compilation target and one
CC-style action. Unsupported combinations fail before source compilation.
There is no hidden backend fallback.

## Targets

| Target | Host default | Output owner |
| --- | --- | --- |
| `x86_64-linux-gnu` | x86_64 Linux | [`target-x86_64-linux-gnu.md`](target-x86_64-linux-gnu.md) |
| `llvm` | every other host | [`target-llvm.md`](target-llvm.md) |
| `aarch64-apple-darwin` | explicit | [`target-aarch64-apple-darwin.md`](target-aarch64-apple-darwin.md) |
| `evm` | explicit | [`target-evm.md`](target-evm.md) |

`--target=<name>` overrides the host default. Unknown target names fail before
reading or compiling source input.

## Actions

- `xcc -S source.c -o output` emits the selected target's textual form.
- `xcc -c source.c -o output` emits the selected target's object or bytecode
  form.
- `xcc source.c -o executable` links only when the selected target defines a
  link model.
- `xcc --target=evm --evm-initcode -c source.c` emits EVM deployment
  initcode. The option is invalid for other targets and other actions.
- With multiple C inputs, `-S` and `-c` derive one default output per input or
  reject a shared explicit `-o`; overwriting one output repeatedly is forbidden.

The removed `--backend` and `--no-backend-fallback` interfaces must not be
reintroduced.

## Delegation

The selected target may invoke its documented assembler or linker. Target
preprocessing, lowering, output format, and tool invocations remain visible and
testable. Target code must not branch on CPython or another project's identity.

## Acceptance

Driver tests cover host defaults, explicit targets, unsupported targets,
multi-input output rules, language-mode propagation, EVM initcode restrictions,
and the exact delegated tool family. High-risk changes run the applicable real
build gate with stale outputs removed.
