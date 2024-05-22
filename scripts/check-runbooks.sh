#!/usr/bin/env bash
# Verify runbook hygiene:
#   1. Every alert in prometheus-rules.yml has a runbook_url annotation.
#   2. Every runbook_url resolves to docs/runbooks/<AlertName>.md.
#   3. Every docs/runbooks/<AlertName>.md matches an alert in the rules.
#   4. Every runbook has the five required ## sections.
set -euo pipefail

RULES="config/prometheus-rules.yml"
RB_DIR="docs/runbooks"
REQUIRED_SECTIONS=(
  "## What this means"
  "## First check"
  "## If confirmed"
  "## If false-positive"
  "## Escalation"
)

fail=0

alerts="$(awk '/^      - alert:/ { gsub(/^.*alert: */, ""); print }' "$RULES")"

for a in $alerts; do
  rb_line="$(awk -v a="$a" '
    /^      - alert: / { in_alert = ($0 ~ a"$") }
    in_alert && /runbook_url:/ { print; exit }
  ' "$RULES")"
  if [ -z "$rb_line" ]; then
    echo "alert has no runbook_url: $a" >&2
    fail=1
    continue
  fi
  expected="$RB_DIR/$a.md"
  if ! echo "$rb_line" | grep -q "docs/runbooks/$a.md"; then
    echo "alert $a runbook_url does not point at $expected" >&2
    fail=1
  fi
  if [ ! -f "$expected" ]; then
    echo "alert $a runbook file missing: $expected" >&2
    fail=1
  fi
done

for f in "$RB_DIR"/*.md; do
  base="$(basename "$f" .md)"
  if ! echo "$alerts" | grep -qx "$base"; then
    echo "orphan runbook (no matching alert): $f" >&2
    fail=1
  fi
  for section in "${REQUIRED_SECTIONS[@]}"; do
    if ! grep -q "^$section" "$f"; then
      echo "$f missing section: $section" >&2
      fail=1
    fi
  done
done

if [ "$fail" -ne 0 ]; then
  exit 1
fi

count="$(echo "$alerts" | wc -l | tr -d ' ')"
echo "runbooks in sync ($count alerts, all with runbook_url and a 5-section runbook)"
