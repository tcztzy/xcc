#!/usr/bin/env bash
set -euo pipefail

# Run clang fixture operations inside x86_64 Docker container.
# Matches CI (Linux x86_64) environment locally.
#
# Usage:
#   scripts/docker-clang-suite.sh              # sync + run clang suite
#   scripts/docker-clang-suite.sh --rebuild    # regenerate full baseline (long!)
#   scripts/docker-clang-suite.sh --check      # check fixtures against archive

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="xcc-glibc"
MODE="${1:-test}"

cd "$ROOT"

# Build image if needed
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building Docker image: $IMAGE"
  docker build -t "$IMAGE" -f docker/Dockerfile.glibc .
fi

sync_cmd="uv run python scripts/sync_clang_fixtures.py"
suite_cmd="XCC_RUN_CLANG_SUITE=1 uv run python -m unittest -v tests.test_clang_suite"

case "$MODE" in
  --rebuild)
    echo "Regenerating full baseline on x86_64..."
    inner="uv sync --dev && $sync_cmd --rebuild-full-suite-baseline"
    ;;
  --check)
    echo "Checking fixtures on x86_64..."
    inner="uv sync --dev && $sync_cmd --check"
    ;;
  test|--test)
    echo "Running clang suite on x86_64..."
    inner="uv sync --dev && $sync_cmd && $suite_cmd"
    ;;
  *)
    echo "Usage: $0 [--test|--rebuild|--check]"
    exit 1
    ;;
esac

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" \
  "$IMAGE" \
  bash -c "
    set -euo pipefail
    export VIRTUAL_ENV=/opt/venv
    export PATH=\"/opt/venv/bin:\$PATH\"
    cd /work
    $inner
  "
