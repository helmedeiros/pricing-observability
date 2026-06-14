# RegistryUploadFailureRate

**Severity:** warning  **Service:** model-registry  **Expression:** `sum(rate(registry_uploads_total{outcome!="ok"}[5m])) > 0.05`

## What this means

model-registry's `/upload` endpoint is rejecting or failing more than 1 upload every 20 s averaged over the last 5 min. Operators trying to push a new rule set are seeing 400/413/500 responses. The current champion is unaffected — the failure is on the way in, before the substrate Put.

## First check (5 min)

1. **Which outcome is dominating** — open Grafana and query `sum by (outcome) (rate(registry_uploads_total{outcome!="ok"}[5m]))`. Outcomes:
   - `invalid` — malformed multipart body (truncated boundary, missing `source` part, wrong Content-Type).
   - `too_large` — payload exceeded the 16 MB ceiling (`DefaultMaxUploadBytes`).
   - `substrate_error` — fsstore Put failed (disk full, WAL corruption, permission).
2. **Operator's trace** — Kibana: `msg:"registry.access" AND attrs.path:"/upload" AND attrs.status:>=400`. The `attrs.trace_id` field is a clickable Jaeger link (per ADR-0010); cross-reference with [recent error spans on model-registry](http://localhost:16686/search?service=model-registry&tags=%7B%22otel.status_code%22%3A%22ERROR%22%7D&lookback=15m&limit=20). The trace shows whether multipart parse, readUploadParts, or substrate Put errored.
3. **Audit-failure check** — Kibana: `msg:"registry.audit.write_failed"`. If present alongside the 4xx/5xx burst, the substrate write may be racing with audit ledger writes; check `registry_state_drift_total` rate too.

## If confirmed

- **`invalid` dominates** — most likely a misbehaving mrctl CLI or a stuck proxy truncating bodies. Check the inbound `User-Agent` header in the Kibana entries.
- **`too_large` dominates** — operator is trying to push a larger artifact than the 16 MB ceiling allows. Either compress or split the rule set, or bump `DefaultMaxUploadBytes` (requires a release).
- **`substrate_error` dominates** — disk pressure or fsstore corruption. `df -h` on the registry host, then `sqlite3 metadata.db "PRAGMA integrity_check;"`. If integrity_check fails, restore from the last good backup and re-run the failed uploads.

## If false-positive

- **Operator-driven smoke test** — someone is intentionally testing the rejection paths. Confirm with the on-call operator.
- **Just-rolled deploy** — the 5 min window catches deploy-time churn if the registry container restarted mid-upload. Acceptable for a single bounce.

## Escalation

If first-check + remediation don't resolve in 15 min, page the **model-registry owner** (helmedeiros). Include the dominant outcome label, the 5-min rate, and a sample `trace_id` from Kibana.
