#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <container-name> <command> [args...]"
  exit 2
fi

name="$1"
shift

# Find running containers whose names start with the base name.
mapfile -t matches < <(
  docker ps --format '{{.ID}} {{.Names}}' \
    | awk -v prefix="$name" '$2 ~ ("^" prefix) {print $1}'
)

if [ "${#matches[@]}" -eq 0 ]; then
  echo "No running tox-docker container found for prefix: ${name}" >&2
  exit 1
fi

if [ "${#matches[@]}" -gt 1 ]; then
  echo "Multiple tox-docker containers found for prefix: ${name}" >&2
  docker ps --format '{{.ID}} {{.Names}}' | awk -v prefix="$name" '$2 ~ ("^" prefix) {print $0}' >&2
  exit 1
fi

container_id="${matches[0]}"

docker exec -w /work "$container_id" "$@"
