#!/usr/bin/env bash
# Live-stack observability verification for model-registry v0.0.4+.
#
# Per ADR-0019, the registry emits a lifecycle metric set + child spans
# + trace-correlated logs. Unit tests prove the data SHAPES are right.
# This script proves the data actually FLOWS end-to-end through the
# pricing-observability stack:
#
#   model-registry → OTel Collector → Jaeger (traces + spans render)
#   model-registry → Prometheus (counters tick + exemplars persist)
#   model-registry → Filebeat → Elasticsearch → Kibana (logs carry trace_id)
#
# What it does:
#   1. Boots a fresh model-registry binary on the host, OTel pointing at
#      the observability collector, metrics on :8091 (the port
#      config/prometheus.yml scrapes).
#   2. Drives a mrctl upload → promote → rollback round-trip against
#      a running markup-svc.
#   3. Polls each backend's HTTP API:
#        Jaeger    /api/traces?service=model-registry
#        Prom      /api/v1/query?query=registry_promotions_total
#        Prom      /api/v1/query_exemplars (exemplar storage proof)
#        ES        /<index>/_search (trace_id presence proof)
#   4. Reports PASS / FAIL per assertion.
#
# Prerequisites:
#   - docker compose -f docker-compose.observability.yaml up -d
#       (Jaeger 16686, Prom 9090, Grafana 3000, ES 9200, Kibana 5601,
#        Filebeat, OTel Collector 4317)
#   - markup-svc reachable at MARKUP_SVC_URL (default http://localhost:8080)
#   - model-registry repo built locally; REGISTRY_BIN points at the binary
#     or pass the path as the first arg.
#
# Usage:
#   ./scripts/verify-registry-observability.sh \
#       [/abs/path/to/model-registry] \
#       [--keep-running]   # leave the registry up after success
#
# Exit codes:
#   0  every assertion passed
#   1  one or more assertions failed
#   2  precondition missing (stack not up, registry binary not found)

set -euo pipefail

REGISTRY_BIN="${REGISTRY_BIN:-${1:-}}"
REGISTRY_PORT="${REGISTRY_PORT:-8091}"
REGISTRY_URL="http://localhost:${REGISTRY_PORT}"
MARKUP_SVC_URL="${MARKUP_SVC_URL:-http://localhost:8080}"
COLLECTOR_URL="${COLLECTOR_URL:-localhost:4317}"
JAEGER_URL="${JAEGER_URL:-http://localhost:16686}"
PROM_URL="${PROM_URL:-http://localhost:9090}"
ES_URL="${ES_URL:-http://localhost:9200}"
ES_INDEX="${ES_INDEX:-platform-logs-*}"
KEEP_RUNNING=false

for arg in "$@"; do
  case "$arg" in
    --keep-running) KEEP_RUNNING=true ;;
  esac
done

fail=0
pass=0
note() { printf '  • %s\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; pass=$((pass+1)); }
bad()  { printf '  \033[31m✘\033[0m %s\n' "$*" >&2; fail=$((fail+1)); }

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing tool: $1"; exit 2; }
}

require curl
require jq

# --- 0. Preconditions ----------------------------------------------------

echo "==> preconditions"

# REGISTRY_BIN is only required when this script is responsible for
# booting the registry. When VERIFY_ES_IN_COMPOSE=1, the operator has
# already started the registry via docker compose and we drive an
# already-running endpoint.
if [ "${VERIFY_ES_IN_COMPOSE:-0}" != "1" ]; then
  if [ -z "$REGISTRY_BIN" ] || [ ! -x "$REGISTRY_BIN" ]; then
    echo "set REGISTRY_BIN to an executable model-registry binary (got: '$REGISTRY_BIN')" >&2
    exit 2
  fi
fi

for svc in "$JAEGER_URL" "$PROM_URL" "$ES_URL" "$MARKUP_SVC_URL"; do
  if ! curl -fsS -o /dev/null -m 2 "$svc/" 2>/dev/null && \
     ! curl -fsS -o /dev/null -m 2 "$svc/healthz" 2>/dev/null && \
     ! curl -fsS -o /dev/null -m 2 "$svc/api/services" 2>/dev/null && \
     ! curl -fsS -o /dev/null -m 2 "$svc/-/healthy" 2>/dev/null && \
     ! curl -fsS -o /dev/null -m 2 "$svc/_cluster/health" 2>/dev/null; then
    bad "service not reachable: $svc"
  else
    ok "service reachable: $svc"
  fi
done
[ "$fail" -eq 0 ] || { echo "preconditions failed"; exit 2; }

# --- 1. Boot model-registry on the host ----------------------------------

echo "==> boot model-registry on :${REGISTRY_PORT}"

if [ "${VERIFY_ES_IN_COMPOSE:-0}" = "1" ]; then
  # Compose-managed registry already running; just confirm reachable.
  if curl -fsS -o /dev/null -m 2 "$REGISTRY_URL/healthz"; then
    ok "registry /healthz reachable at $REGISTRY_URL (compose-managed)"
  else
    bad "VERIFY_ES_IN_COMPOSE=1 but $REGISTRY_URL/healthz is not reachable — bring it up first"
    exit 2
  fi
  trap 'rm -rf "${DATA_DIR:-/dev/null}" 2>/dev/null || true' EXIT INT TERM
else
  DATA_DIR="$(mktemp -d -t mr-obs-e2e.XXXXXX)"
  INSTANCES_CFG="${DATA_DIR}/instances.json"
  # Point the production env at the running markup-svc so POST /promote
  # can rolling-push to it. Without --instances-config the registry
  # disables the /promote + /rollback routes at boot and returns 404.
  cat >"$INSTANCES_CFG" <<EOF
{"production": ["${MARKUP_SVC_URL}"]}
EOF

  trap 'cleanup' EXIT INT TERM
  cleanup() {
    if [ "$KEEP_RUNNING" = false ] && [ -n "${REG_PID:-}" ] && kill -0 "$REG_PID" 2>/dev/null; then
      kill "$REG_PID" 2>/dev/null || true
      wait "$REG_PID" 2>/dev/null || true
    fi
    rm -rf "$DATA_DIR" 2>/dev/null || true
  }

  REG_LOG="$(mktemp -t mr-obs-e2e.log.XXXXXX)"
  REGISTRY_OTEL_EXPORTER=otlp \
  REGISTRY_OTEL_ENDPOINT="$COLLECTOR_URL" \
  REGISTRY_ADDR=":${REGISTRY_PORT}" \
  REGISTRY_STORE_BACKEND=fs \
  REGISTRY_STORE_ROOT="$DATA_DIR" \
  REGISTRY_INSTANCES_CONFIG="$INSTANCES_CFG" \
  OTEL_SERVICE_NAME=model-registry \
    "$REGISTRY_BIN" >"$REG_LOG" 2>&1 &
  REG_PID=$!

  note "registry pid=$REG_PID; logs at $REG_LOG"

  # Wait for /healthz to come up.
  for i in $(seq 1 50); do
    if curl -fsS -o /dev/null -m 1 "$REGISTRY_URL/healthz"; then
      ok "registry /healthz ready"
      break
    fi
    sleep 0.1
    [ "$i" -lt 50 ] || { bad "registry never came up"; exit 1; }
  done
fi

# --- 2. Drive the round-trip ---------------------------------------------

echo "==> drive round-trip via raw HTTP (no mrctl dependency)"

CSV='name,condition,factor,priority
verify_obs,customer_tier == '"'"'enterprise'"'"',1.23,99
'

# upload
BOUNDARY="MR$(date +%s%N)"
UPLOAD_BODY="$(mktemp -t mr-upload.XXXXXX)"
{
  printf -- "--%s\r\n" "$BOUNDARY"
  printf 'Content-Disposition: form-data; name="source"; filename="rules.csv"\r\n'
  printf 'Content-Type: text/csv\r\n\r\n'
  printf '%s\r\n' "$CSV"
  printf -- "--%s--\r\n" "$BOUNDARY"
} >"$UPLOAD_BODY"

HASH="$(curl -fsS -X POST "$REGISTRY_URL/upload" \
  -H "Content-Type: multipart/form-data; boundary=$BOUNDARY" \
  --data-binary @"$UPLOAD_BODY" | jq -r .hash)"
rm -f "$UPLOAD_BODY"
[ -n "$HASH" ] && [ "$HASH" != "null" ] || { bad "upload returned no hash"; exit 1; }
ok "upload → hash=$HASH"

# promote
curl -fsS -X POST "$REGISTRY_URL/promote" -H 'Content-Type: application/json' \
  -d "$(jq -n --arg h "$HASH" '{hash:$h, env:"production", role:"champion", operator:"verify-obs", reason:"obs e2e"}')" \
  >/dev/null || { bad "promote failed"; exit 1; }
ok "promote → committed"

# rollback (will fail with no_history since only one champion has been
# promoted; that's fine, we already exercised commit_state + deploy spans
# on the promote).
ROLLBACK_STATUS="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$REGISTRY_URL/rollback" \
  -H 'Content-Type: application/json' \
  -d '{"env":"production","operator":"verify-obs","reason":"obs e2e"}')"
note "rollback → HTTP $ROLLBACK_STATUS (400 no_history expected on a single-champion env)"

# Give the OTel exporter + Prom scrape one full window to flush.
note "waiting 18s for collector flush + prom scrape"
sleep 18

# --- 3. Jaeger: trace renders with lifecycle spans -----------------------

echo "==> jaeger /api/traces?service=model-registry"

TRACES_JSON="$(curl -fsS "$JAEGER_URL/api/traces?service=model-registry&lookback=2m&limit=20")"
TRACE_COUNT="$(echo "$TRACES_JSON" | jq '.data | length')"
[ "$TRACE_COUNT" -gt 0 ] && ok "Jaeger sees model-registry traces (count=$TRACE_COUNT)" || bad "Jaeger has zero traces for service=model-registry"

if [ "$TRACE_COUNT" -gt 0 ]; then
  for span in \
      "registry.deploy.push_to_instance" \
      "registry.deploy.readyz" \
      "registry.champion.commit_state" \
      "registry.audit.record"; do
    found="$(echo "$TRACES_JSON" | jq --arg n "$span" '[.data[].spans[] | select(.operationName == $n)] | length')"
    if [ "$found" -gt 0 ]; then
      ok "Jaeger span present: $span ($found)"
    else
      bad "Jaeger span missing: $span"
    fi
  done
  # Cross-service: assert markup-svc spans appear in the same traces.
  # Jaeger's trace JSON shape: spans[].processID references the trace's
  # processes{processID: {serviceName, ...}} map. We resolve span →
  # processID → serviceName to walk the cross-service graph.
  cross="$(echo "$TRACES_JSON" | jq '
    [ .data[]
      | . as $t
      | select(
          .spans
          | any(
              $t.processes[.processID].serviceName == "markup-svc"
            )
        )
    ] | length')"
  if [ "$cross" -gt 0 ]; then
    ok "Jaeger trace nests markup-svc as a downstream service ($cross trace(s))"
  else
    bad "no Jaeger trace contains a markup-svc span — traceparent propagation broken"
  fi
fi

# --- 4. Prometheus: counters ticked + exemplars stored -------------------

echo "==> prometheus /api/v1/query"

PROM_PROMOTE="$(curl -fsS "$PROM_URL/api/v1/query" --data-urlencode 'query=sum(registry_promotions_total{outcome="ok"})')"
PROM_PROMOTE_VAL="$(echo "$PROM_PROMOTE" | jq -r '.data.result[0].value[1] // "0"')"
if [ "$(echo "$PROM_PROMOTE_VAL > 0" | bc -l 2>/dev/null || echo 0)" = "1" ]; then
  ok "Prometheus registry_promotions_total{outcome=ok} = $PROM_PROMOTE_VAL"
else
  bad "registry_promotions_total{outcome=ok} did not tick (val=$PROM_PROMOTE_VAL) — scrape config or counter wiring broken"
fi

PROM_UP="$(curl -fsS "$PROM_URL/api/v1/query" --data-urlencode 'query=up{job="model-registry"}')"
PROM_UP_VAL="$(echo "$PROM_UP" | jq -r '.data.result[0].value[1] // "0"')"
[ "$PROM_UP_VAL" = "1" ] && ok "Prometheus scrape target up{job=model-registry} = 1" || bad "Prometheus cannot scrape model-registry (up=$PROM_UP_VAL)"

echo "==> prometheus /api/v1/query_exemplars"

EXEMPLARS="$(curl -fsS "$PROM_URL/api/v1/query_exemplars?query=registry_deploy_duration_seconds_bucket&start=$(date -u -v-3M +%FT%TZ 2>/dev/null || date -u -d '-3 minutes' +%FT%TZ)&end=$(date -u +%FT%TZ)")"
EX_COUNT="$(echo "$EXEMPLARS" | jq '[.data[].exemplars[]] | length')"
if [ "$EX_COUNT" -gt 0 ]; then
  EX_TRACE="$(echo "$EXEMPLARS" | jq -r '.data[0].exemplars[0].labels.trace_id // ""')"
  if [ -n "$EX_TRACE" ]; then
    ok "Prometheus exemplar carries trace_id=$EX_TRACE"
  else
    bad "exemplar present but trace_id label missing"
  fi
else
  bad "no exemplars stored for registry_deploy_duration_seconds_bucket — --enable-feature=exemplar-storage missing?"
fi

# --- 5. Elasticsearch: trace_id flows through logs pipeline --------------

echo "==> elasticsearch _search"

# Filebeat tails /var/lib/docker/containers/*.log inside its container,
# so it can only index containers. This verification script runs the
# registry as a host process for self-containment, which means
# Filebeat will never see its stdout. Detect that case and emit a
# clear SKIP rather than a confusing FAIL.
#
# To actually verify ES indexing, bring the registry up via docker
# compose (decision-gateway/docker-compose.yaml now includes a
# model-registry service) and re-run with VERIFY_ES_IN_COMPOSE=1.
if [ "${VERIFY_ES_IN_COMPOSE:-0}" != "1" ]; then
  note "SKIP — registry runs as a host process; Filebeat only tails container logs."
  note "      Bring the registry up via 'docker compose up -d model-registry' in"
  note "      decision-gateway/, then run this script with VERIFY_ES_IN_COMPOSE=1."
else
  # Filebeat → ES indexing delay can be a couple of seconds beyond the
  # 18s sleep above; one final wait.
  sleep 5
  # decode_json_fields lifts the application JSON line into top-level
  # ES fields, so msg + attrs.* are at the document root. match_phrase
  # on `message` is the most portable filter because some Filebeat
  # versions don't index `msg` as a keyword.
  ES_QUERY='{
    "size": 1,
    "query": {
      "bool": {
        "filter": [
          { "match_phrase": { "message": "registry.access" } },
          { "exists": { "field": "attrs.trace_id" } }
        ]
      }
    },
    "sort": [{"@timestamp": "desc"}]
  }'
  ES_HIT="$(curl -fsS -H 'Content-Type: application/json' -X POST "$ES_URL/$ES_INDEX/_search" -d "$ES_QUERY")"
  ES_TOTAL="$(echo "$ES_HIT" | jq -r '.hits.total.value // 0')"
  if [ "$ES_TOTAL" -gt 0 ]; then
    ES_TRACE="$(echo "$ES_HIT" | jq -r '.hits.hits[0]._source.attrs.trace_id')"
    ok "Elasticsearch indexed registry.access with attrs.trace_id=$ES_TRACE"
  else
    bad "no registry.access events with attrs.trace_id in ES index $ES_INDEX (Filebeat pipeline broken or trace not minted in time)"
  fi
fi

# --- summary -------------------------------------------------------------

echo
echo "==> summary: $pass passed, $fail failed"
[ "$fail" -eq 0 ] && exit 0 || exit 1
