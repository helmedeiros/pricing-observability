#!/usr/bin/env bash
set -euo pipefail

cd "${1:-.}"
DOCKER="${DOCKER:-docker}"

for f in docker-compose*.yaml; do
  [ -e "$f" ] || continue
  if command -v "$DOCKER" >/dev/null 2>&1; then
    echo "validate-compose: $f"
    "$DOCKER" compose -f "$f" config -q || exit 1
  else
    echo "validate-compose: docker not on PATH -- skipping $f"
  fi
done
