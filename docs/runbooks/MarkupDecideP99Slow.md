# MarkupDecideP99Slow

**Severity:** warning  **Service:** markup-svc  **Expression:** `histogram_quantile(0.99, sum by(le) (rate(markup_decide_duration_seconds_bucket[5m]))) > 0.005`

## What this means

99th-percentile markup-svc Decide latency exceeded 5 ms over the last 5 min. Customer-visible: 1% of pricing decisions are at least 5x the typical engine cost; the gateway p99 alert (`GatewayRequestP99Slow`) will likely follow if this persists.

## First check (5 min)

1. **Confirm in the dashboard** — open `markup-svc — overview` in Grafana, check the `Decide latency — p50 / p95 / p99` panel. Confirm the p99 line is actually above 5 ms (the alert fires on the smoothed series; the live panel shows the spikes).
2. **Rule set size** — `curl http://markup-svc:8080/admin/diagnose | jq '.rule_count'` (or the gateway-proxied version). If rule_count grew significantly since the last steady state, indexing pressure is the prime suspect.
3. **Adapter check** — `docker compose ps markup-svc` + inspect the `--adapter=` flag. `inmemory` is O(N) per Decide; if N > 100, p99 climbing is expected.
4. **Jaeger span breakdown** — open SPM for `markup-svc`, look at recent traces, identify which child span is slowest (`markup.decide.evaluate`, `guardrails.check`, etc.).

## If confirmed

- **Adapter swap** — switch markup-svc from `--adapter=inmemory` to `--adapter=indexed` (or `priority`). Recreate the container (compose `up -d --force-recreate markup-svc`). Run `--diagnose=on` will catch any non-indexable conditions during boot.
- **Rule-set trim** — review the loaded rules CSV. Remove or consolidate rules that haven't matched in the recent decision log (`msg:"markup-server.access" AND attrs.no_match:true`).
- **Guardrails latency** — if `guardrails.check` span dominates, the guardrails set has grown. Check `/admin/guardrails` and prune.
- **Upstream pressure** — if p99 is climbing AND gateway pool latency is climbing AND error rate is fine, the problem is below markup-svc (Elasticsearch, OTel Collector backpressure, etc.).

## If false-positive

- **Cold-cache window** — first 60 s after `--force-recreate` shows elevated p99 while the adapter warms. Wait for the `for: 5m` clock to reset post-warmup.
- **Synthetic burst test** — traffic-gen `burst` profile is running and exceeding the steady-state QPS budget. Confirm `docker compose logs traffic-gen --tail 20`.

## Escalation

If first-check + remediation don't resolve in 15 min, page **markup-svc owner** (helmedeiros). Include the dominant slow-span name from Jaeger, the current `--adapter` flag, and rule_count.
