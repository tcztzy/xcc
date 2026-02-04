# Linux/ELF Target

## Scope

Linux/ELF is a secondary target used to validate glibc and musl compatibility and to keep the toolchain aligned with CPython's Linux build expectations.

## Linker

The initial ELF linker is mold.

## C library targets

- glibc for mainstream GNU/Linux environments.
- musl for lightweight and static friendly environments.

## Build environment

Linux/ELF builds are executed in Docker containers on macOS hosts to keep the toolchain isolated and reproducible.

## Docker workflow

Images are defined in `docker/Dockerfile.glibc` and `docker/Dockerfile.musl`.

Example commands:

- Build glibc image: `./scripts/docker-build.sh glibc`
- Build musl image: `./scripts/docker-build.sh musl`
- Open a shell in the image: `./scripts/docker-shell.sh glibc` or `./scripts/docker-shell.sh musl`
- Run a command directly (glibc): `./scripts/docker-run.sh glibc <command> [args...]`
- Run a command directly (musl): `./scripts/docker-run.sh musl <command> [args...]`
- Run unit tests via tox-docker (glibc): `tox -e docker_glibc`
- Run unit tests via tox-docker (musl): `tox -e docker_musl`

Note: The Dockerfiles assume `mold` is available in the base distribution repositories. If it is missing, install it from upstream or build it from source and update the images.

## References

- https://github.com/rui314/mold/blob/main/docs/mold.md
- https://sourceware.org/glibc/manual/latest/pdf/libc.pdf
- https://musl.libc.org/doc/1.1.24/manual.txt
- https://docs.docker.com/get-started/
