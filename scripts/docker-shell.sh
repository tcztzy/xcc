#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <glibc|musl>"
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

docker run --rm -it -v "${PWD}":/work -w /work "$image" /bin/sh
