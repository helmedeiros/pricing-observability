#!/usr/bin/env bash
# Verify saved-search round-trip:
#   1. Every discover view link in a runbook resolves to a saved-object id
#      present in config/kibana-saved-objects.ndjson.
#   2. Every saved object of type "search" in the NDJSON is referenced by
#      at least one runbook (no orphans).
set -euo pipefail

NDJSON="config/kibana-saved-objects.ndjson"
RB_DIR="docs/runbooks"

fail=0

ids_in_ndjson="$(awk -F'"' '/"type": ?"search"/ {
  for (i=1; i<=NF; i++) if ($i == "id") { print $(i+2); next }
}' "$NDJSON" | sort -u)"

ids_in_runbooks="$(grep -h -o 'discover#/view/[a-zA-Z0-9_-]*' "$RB_DIR"/*.md \
  | sed 's|discover#/view/||' | sort -u)"

for id in $ids_in_runbooks; do
  if ! echo "$ids_in_ndjson" | grep -qx "$id"; then
    echo "runbook references unknown saved-search id: $id" >&2
    fail=1
  fi
done

for id in $ids_in_ndjson; do
  if ! echo "$ids_in_runbooks" | grep -qx "$id"; then
    echo "orphan saved search (no runbook links to it): $id" >&2
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  exit 1
fi

count="$(echo "$ids_in_ndjson" | wc -l | tr -d ' ')"
echo "saved-searches in sync ($count search objects, all linked from runbooks)"
