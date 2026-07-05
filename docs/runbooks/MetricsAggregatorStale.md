# MetricsAggregatorStale

**Severity:** warning  **Service:** pricing-metrics-aggregator  **Expression:** `(time() - max by (env) (pricing_metrics_aggregator_runs_total)) == bool 0` (`for: 15m`)

## What this means

The aggregator's monotonic `runs_total` counter has not advanced for 15 minutes. Either:

- The aggregator process is stuck (unlikely — /healthz would 200 anyway because it serves from the mux goroutine, not the run loop).
- The `up{job="pricing-metrics-aggregator"}` scrape target is DOWN (Prometheus can't reach the /metrics endpoint at all).
- The aggregator's ticker fired but every run has errored for 15m (would also fire `MetricsAggregatorRunFailureRate` — if both are active, treat that one first).

The `pricing_*_last_window` gauges being served on Prometheus are almost certainly stale (they retain the last successful value from before the stall).

## First check (5 min)

1. **Confirm scrape health** — Prometheus UI → Targets → filter `pricing-metrics-aggregator`. `UP` means the counter really isn't advancing; `DOWN` means the /metrics endpoint is unreachable.
2. **Check container state** — `docker compose ps pricing-metrics-aggregator`. Restarting? Exited? Healthy?
3. **Container logs, most recent 100 lines** — `docker compose logs --tail=100 pricing-metrics-aggregator`. Look for either NO `run_ok`/`run_error` lines (loop truly stuck) or repeated `run_error` (which means the other alert should fire too).
4. **Cross-reference `MetricsAggregatorRunFailureRate`** — if active, the loop is running but every run is failing; work that alert instead.

## If confirmed

- **Process stuck.** The run loop is single-goroutine. If it hangs, `docker compose restart pricing-metrics-aggregator` is the fastest remediation. Post-mortem: capture the container's stack trace via `SIGQUIT` before restart (`docker compose kill -s SIGQUIT pricing-metrics-aggregator && docker compose logs ...`). Report the goroutine dump to the aggregator owner.
- **Scrape target DOWN.** Firewall / network / port-mapping issue between Prometheus and the aggregator. Check the compose file's port mapping (`8082:8082`) and any network-namespace shenanigans.
- **Both alerts active** — treat MetricsAggregatorRunFailureRate first; MetricsAggregatorStale is the more permissive cousin.

## If false-positive

The expression `time() - max(counter) == bool 0` reads oddly but is designed for "counter has not advanced since the last scrape". If Prometheus itself is slow (a Prometheus-side incident) the query returns stale data and the alert can misfire. Cross-reference with Prometheus's own health (`up{job="prometheus"}`).

## Escalation

If unresolved in 30 minutes, page the **pricing-metrics-aggregator owner** (helmedeiros). Include the container stack dump (from the SIGQUIT above) and the Prometheus targets page screenshot.
