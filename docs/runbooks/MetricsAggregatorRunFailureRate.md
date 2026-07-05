# MetricsAggregatorRunFailureRate

**Severity:** warning  **Service:** pricing-metrics-aggregator  **Expression:** `sum by (env) (rate(pricing_metrics_aggregator_runs_total{outcome="error"}[15m])) > 0`

## What this means

One or more aggregation runs failed in the last 15 minutes and the pattern has held for 10 minutes straight. The aggregator's `pricing_*_last_window` gauges have not been refreshed from the failing windows — Prometheus is still returning the *last successful* value, not the current bucket state. Grafana panels look "stable" but are lying about how recent the underlying data is.

The customer-visible pricing path is unaffected. This is an observability incident, not a serving incident.

## First check (5 min)

1. **Open the container logs** — `docker compose logs -f pricing-metrics-aggregator | grep run_error`. The `error` field on the JSON event names the ingest side that failed: `search: …` or `booking: …`. That tells you which prefix is the problem.
2. **Compare `runs_total{outcome="ok"}` vs `runs_total{outcome="error"}`** in Prometheus. Ratio > 50% error means the aggregator can't reach MinIO at all; low error ratio with sustained > 0 means a specific batch is malformed or a specific object timed out.
3. **Test the ingest surface directly** — `docker compose exec pricing-metrics-aggregator wget -qO- http://minio:9000/minio/health/live`. A 200 here rules out network partition; a non-200 confirms it.
4. **Check `pricing_metrics_aggregator_run_duration_seconds_bucket`** — if p95 crept above the `--interval`, the aggregator is falling behind (each run overlaps the next). Not necessarily a run failure but often a leading indicator.
5. **List the buckets from a shell inside the aggregator container** — `mc alias set local http://minio:9000 minio minio12345 && mc ls local/funnel-events --recursive`. If the prefix walk works from inside the container but the aggregator logs still say `error`, the problem is at the ingest reader (bad batch, gzip corruption); if the shell walk also fails, it's the underlying storage.

## If confirmed

- **MinIO unreachable** — check the compose `minio` service health. `docker compose ps` should show `(healthy)`. Restart minio if it's flapping; open pricing-observability's MinIO runbook.
- **Credentials regression** — `--event-source-access-key` / `--event-source-secret-key` do not match the MinIO deployment. Verify the compose env vars; rotate if the MinIO password was changed.
- **Bucket layout regression** — the aggregator walks `dt=/hour=/env=` Hive prefixes. If a producer (markup-svc s3sink or funnel-sim s3sink) changed its key layout without a matching aggregator change, the walk sees no objects and no error — but a schema regression could produce malformed batches. Cross-reference the last release of markup-svc + funnel-sim.
- **Bad batch** — the ingest reader skips a bad row silently today (pyc-0.0.1 known-gap; `bad_rows_total` is a parked follow-on per aggregator ROADMAP). If the whole batch is malformed (gzip corruption), the object read fails and the whole window errors. Delete the bad object from MinIO to unblock the next run; document the drop.

## If false-positive

- **Cold-start after a rolling deploy** — the aggregator boot sequence runs an immediate first pass before the ticker; if MinIO is not yet healthy at that moment, the boot pass errors and the counter starts at 1. Wait one more `--interval` and the counter should not advance. If it stays at 1, this is not a false positive — it's a boot-time incident that self-resolved.
- **Empty bucket** — a fresh compose stack with no traffic yet returns zero events for the window; the aggregator's `run_ok` path fires with all-zero gauges and no error. This alert should NOT fire on empty buckets — if it does, the ingest reader is misinterpreting empty-prefix as an error. Cross-reference with the reader tests.

## Escalation

If the first-check + remediation steps don't resolve in 30 minutes, page the **pricing-metrics-aggregator owner** (helmedeiros). Include:
- The relevant `run_error` log lines from container logs.
- The output of `docker compose exec pricing-metrics-aggregator wget -qO- http://minio:9000/minio/health/live`.
- The Prometheus query output for `pricing_metrics_aggregator_runs_total`.
