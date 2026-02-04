# Requirements

## Language and standard

- Baseline: C11 core language and standard library semantics, without relying on optional C11 features.
- Public C API compatibility with C99 and C++ where CPython requires it.
- Avoid compiler specific extensions and keep warning free builds.

## CPython build prerequisites

- A C11 compiler is required to build CPython.
- CPython expects IEEE 754 floating point semantics with NaN support.
- Thread support is required for the core runtime.

## Platform support policy

- Target platforms should align with CPython tiered support policy.
- Initial support must be explicitly declared and tested for each tier and OS/toolchain combination.

## Initial target platform

- First target: macOS on Apple silicon (`arm64`).
- Universal binaries on macOS commonly include `arm64` and `x86_64` slices; native `arm64` is the priority for early milestones.
- Apple silicon uses little-endian byte order on macOS.

## Linker and C library targets

- Linker: mold for ELF targets.
- Standard C library targets: glibc and musl.

## Build environments

- Primary development host: macOS on Apple silicon.
- Linux/ELF builds are executed in Docker containers.

## Runtime constraints

- No third party runtime dependencies (stdlib only).
- Runs on CPython and PyPy, Python 3.11 and later.

## References

- CPython build requirements and configuration guide (Python docs).
- PEP 7: C language standards and compiler constraints for CPython.
- PEP 11: CPython platform support tiers.
