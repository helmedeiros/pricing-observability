#!/usr/bin/env bash
set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/validate-compose.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0

BASE='services:
  prometheus:
    image: prom/prometheus:v2.53.0
    volumes:
      - ./a.yml:/etc/prometheus/prometheus.yml:ro'

GOOD_OVERRIDE='services:
  prometheus:
    volumes: !override
      - ./b.yml:/etc/prometheus/prometheus.yml:ro'

site() {
  local dir="$WORK/$1"
  mkdir -p "$dir"
  shift
  while [ $# -gt 0 ]; do
    printf '%s\n' "$2" > "$dir/$1"
    shift 2
  done
  echo "$dir"
}

expect() {
  local name="$1" want="$2" dir="$3" pattern="${4:-}"
  shift 4 2>/dev/null || shift 3
  local out code
  out="$(env "$@" bash "$SCRIPT" "$dir" 2>&1)"
  code=$?
  local ok=1
  if [ "$want" = 0 ] && [ "$code" -ne 0 ]; then ok=0; fi
  if [ "$want" = 1 ] && [ "$code" -eq 0 ]; then ok=0; fi
  if [ -n "$pattern" ] && ! grep -q -- "$pattern" <<<"$out"; then ok=0; fi
  if [ "$ok" = 1 ]; then
    pass=$((pass + 1))
    echo "PASS $name"
  else
    fail=$((fail + 1))
    echo "FAIL $name (exit $code, want $([ "$want" = 0 ] && echo 0 || echo non-zero)${pattern:+, output matching '$pattern'})"
    sed 's/^/    /' <<<"$out"
  fi
}

expect "valid base file passes" 0 \
  "$(site base-ok docker-compose.observability.yaml "$BASE")" ""

expect "invalid base file fails" 1 \
  "$(site base-bad docker-compose.observability.yaml "$BASE
    not_a_compose_key: true")" ""

expect "valid override passes when layered on the base" 0 \
  "$(site override-ok docker-compose.observability.yaml "$BASE" \
    docker-compose.scientific-override.yaml "$GOOD_OVERRIDE")" "docker-compose.observability.yaml + docker-compose.scientific-override.yaml"

expect "override with an unknown key fails" 1 \
  "$(site override-bad-key docker-compose.observability.yaml "$BASE" \
    docker-compose.scientific-override.yaml "$GOOD_OVERRIDE
    not_a_compose_key: true")" ""

expect "override adding a service with no image fails" 1 \
  "$(site override-new-service docker-compose.observability.yaml "$BASE" \
    docker-compose.scientific-override.yaml "services:
  grafana:
    ports: [\"3000:3000\"]")" ""

expect "override without a base file fails" 1 \
  "$(site override-no-base docker-compose.scientific-override.yaml "$GOOD_OVERRIDE")" "docker-compose.observability.yaml"

expect "missing docker in CI fails" 1 \
  "$(site no-docker-ci docker-compose.observability.yaml "$BASE")" "docker" \
  DOCKER=definitely-not-docker CI=true

expect "missing docker outside CI skips with a notice" 0 \
  "$(site no-docker-local docker-compose.observability.yaml "$BASE")" "skipping" \
  DOCKER=definitely-not-docker CI=

echo "validate-compose tests: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
