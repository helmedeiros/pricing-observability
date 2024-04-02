#!/bin/sh
# Kibana data-view + saved-object provisioning. Polls /api/status until
# "available", then POSTs the bundled NDJSON to the import API with
# retry-and-backoff (the saved-objects API can still 503 after status
# reports green during first boot). See ADR-0004 + ADR-0010.

set -eu

KIBANA_URL="${KIBANA_URL:-http://kibana:5601}"
NDJSON="${NDJSON:-/etc/kibana-init/saved-objects.ndjson}"

echo "kibana-init: waiting for Kibana at $KIBANA_URL ..."
i=0
until curl -fs "$KIBANA_URL/api/status" 2>/dev/null | grep -q '"level":"available"'; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "kibana-init: Kibana did not become available within ~120s; giving up." >&2
    exit 1
  fi
  sleep 2
done
echo "kibana-init: Kibana is available, importing saved objects ..."

i=0
while true; do
  http_code=$(curl -sS -o /tmp/import-result.json -w "%{http_code}" \
    -X POST "$KIBANA_URL/api/saved_objects/_import?overwrite=true" \
    -H "kbn-xsrf: true" \
    --form file=@"$NDJSON" || echo 000)
  case "$http_code" in
    2*)
      cat /tmp/import-result.json
      echo
      break
      ;;
    *)
      i=$((i + 1))
      if [ "$i" -gt 20 ]; then
        echo "kibana-init: import failed after 20 retries (last http=$http_code)" >&2
        cat /tmp/import-result.json >&2 || true
        exit 1
      fi
      echo "kibana-init: import http=$http_code, retry $i/20 in 3s ..." >&2
      sleep 3
      ;;
  esac
done

curl -fsS \
  -X POST "$KIBANA_URL/api/kibana/settings/defaultIndex" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -d '{"value":"platform-logs"}' \
  > /dev/null

echo "kibana-init: done."
