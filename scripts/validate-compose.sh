#!/usr/bin/env bash
set -euo pipefail

cd "${1:-.}"
DOCKER="${DOCKER:-docker}"
BASE="${COMPOSE_BASE:-docker-compose.observability.yaml}"

if ! command -v "$DOCKER" >/dev/null 2>&1; then
  for f in docker-compose*.yaml; do
    [ -e "$f" ] && echo "validate-compose: docker not on PATH -- skipping $f"
  done
  exit 0
fi

for f in docker-compose*.yaml; do
  [ -e "$f" ] || continue
  case "$f" in
    *override*)
      if [ ! -e "$BASE" ]; then
        echo "validate-compose: $f is an override but $BASE is missing" >&2
        exit 1
      fi
      echo "validate-compose: $BASE + $f"
      "$DOCKER" compose -f "$BASE" -f "$f" config -q || exit 1
      ;;
    *)
      echo "validate-compose: $f"
      "$DOCKER" compose -f "$f" config -q || exit 1
      ;;
  esac
done
