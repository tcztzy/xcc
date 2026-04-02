# Apple Silicon Target

## Scope

- macOS on Apple silicon is the primary native development platform today.
- The native macOS architecture name for Apple silicon is `arm64`, commonly shipped alongside `x86_64` in universal binaries.

## Instruction set and execution state

Arm defines the Armv8-A application profile with two execution states: AArch64 (64-bit) and AArch32 (32-bit). The AArch64 execution state uses the A64 instruction set and 64-bit registers.

For XCC, the Apple silicon backend targets AArch64/A64. AArch32 is not part of the compiler roadmap.

## Endianness

Apple silicon and Intel Macs use little-endian data format, so no byte-order conversion is required for host ABI interoperability on macOS.

## Object format and linking

macOS uses Mach-O for object files and executables. XCC currently emits AArch64 assembly and relies on the platform `clang` toolchain to assemble and link Mach-O outputs. Native Mach-O object emission remains active implementation work.

## Linux/ELF targets

Linux/ELF remains part of the compiler target set. Current Docker workflows are used to build and validate that path while native ELF support is implemented.

## References

- https://developer.apple.com/documentation/xcode/porting_your_macos_apps_to_apple_silicon/
- https://www.arm.com/architecture/cpu/a-profile
- https://developer.apple.com/library/archive/documentation/Performance/Conceptual/CodeFootprint/Articles/MachOOverview.html
