#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <glibc|musl>"
  exit 2
fi

case "$1" in
  glibc)
    docker build -f docker/Dockerfile.glibc -t xcc-glibc .
    ;;
  musl)
    docker build -f docker/Dockerfile.musl -t xcc-musl .
    ;;
  *)
    echo "Unknown target: $1"
    exit 2
    ;;
 esac
