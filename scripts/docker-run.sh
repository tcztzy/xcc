#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <glibc|musl> <command> [args...]"
  exit 2
fi

case "$1" in
  glibc)
    image="xcc-glibc"
    ;;
  musl)
    image="xcc-musl"
    ;;
  *)
    echo "Unknown target: $1"
    exit 2
    ;;
 esac

shift

docker run --rm -v "${PWD}":/work -w /work "$image" "$@"
