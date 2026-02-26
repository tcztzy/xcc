# Back End

## IR design

- Use an explicit control flow graph with typed values.
- Keep lowering passes small and fully testable.
- Track provenance from AST to IR for better diagnostics.

## Code generation

- Emit objects compatible with the target platform ABI.
- Prefer deterministic register allocation and instruction selection.
- Implement a stable calling convention layer per target.

## Object emission and linking

- Emit standard object files for the platform (ELF, Mach-O, or COFF).
- For macOS targets, emit Mach-O objects and link with the system linker.
- For ELF targets, link with mold as the initial supported linker.
- Linux/ELF builds are executed in Docker to isolate the toolchain.

## Debuggability

- Emit optional debug information behind a flag.
- Provide line mapping for diagnostics and profiling.
