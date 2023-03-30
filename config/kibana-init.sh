#!/bin/sh
# Kibana data-view provisioning entrypoint. Waits for Kibana's
# /api/status to report "available" then imports the bundled
# saved-objects NDJSON (overwrite=true makes it idempotent on
# every compose restart). See ADR-0004.
#
# Runs in a kibana-init service that exits after the import; the
# canonical compose declares it as restart: "no" so it stays out
# of the way once it has done its one job.

set -eu

KIBANA_URL="${KIBANA_URL:-http://kibana:5601}"
NDJSON="${NDJSON:-/etc/kibana-init/saved-objects.ndjson}"

echo "kibana-init: waiting for Kibana at $KIBANA_URL ..."
# Poll up to ~120s. Kibana's first-boot migration takes 30-60s on
# a fresh ES; subsequent restarts are 5-10s.
i=0
until curl -fs "$KIBANA_URL/api/status" 2>/dev/null | grep -q '"level":"available"'; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "kibana-init: Kibana did not become available within ~120s; giving up." >&2
    exit 1
  fi
  sleep 2
done
echo "kibana-init: Kibana is available, importing data views ..."

# Import via the saved-objects API. The X-XSRF token + the
# kbn-xsrf header are both required by Kibana for non-GET API
# calls. overwrite=true makes the call idempotent across
# compose restarts.
curl -fsS \
  -X POST "$KIBANA_URL/api/saved_objects/_import?overwrite=true" \
  -H "kbn-xsrf: true" \
  --form file=@"$NDJSON" \
  | tee /tmp/import-result.json

# Set the default index pattern to platform-logs so Discover opens
# directly on the logs view instead of the empty selector.
curl -fsS \
  -X POST "$KIBANA_URL/api/kibana/settings/defaultIndex" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -d '{"value":"platform-logs"}' \
  > /dev/null

echo "kibana-init: done."
