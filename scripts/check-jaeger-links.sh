#!/usr/bin/env bash
# Verify Jaeger deep-link hygiene in runbooks:
#   1. Every localhost:16686 URL uses a path we recognize (/monitor or /search).
#   2. Every URL carries a service= query parameter so the operator lands on
#      a service-scoped view, not the empty service picker.
#   3. The service= value matches one of the known platform services.
set -euo pipefail

RB_DIR="docs/runbooks"
KNOWN_SERVICES="markup-svc decision-gateway traffic-gen model-registry"
KNOWN_PATHS="/monitor /search"

fail=0
total=0

while IFS= read -r url; do
  total=$((total + 1))
  path="$(echo "$url" | sed -E 's|^http://localhost:16686([^?]*)\?.*|\1|')"
  if ! echo " $KNOWN_PATHS " | grep -q " $path "; then
    echo "unknown Jaeger path: $url (path=$path)" >&2
    fail=1
    continue
  fi
  if ! echo "$url" | grep -q 'service='; then
    echo "Jaeger link missing service= param: $url" >&2
    fail=1
    continue
  fi
  svc="$(echo "$url" | sed -E 's|.*[?&]service=([^&]+).*|\1|')"
  if ! echo " $KNOWN_SERVICES " | grep -q " $svc "; then
    echo "Jaeger link references unknown service: $svc ($url)" >&2
    fail=1
  fi
done < <(grep -h -E -o 'http://localhost:16686[^)]*' "$RB_DIR"/*.md | sort -u)

if [ "$fail" -ne 0 ]; then
  exit 1
fi

if [ "$total" -eq 0 ]; then
  echo "no Jaeger deep-links found in runbooks; check-jaeger-links is a no-op" >&2
  exit 0
fi

echo "Jaeger links in sync ($total unique deep-links, all service-scoped to a known service)"
