# GatewayRequestP99Slow

**Severity:** warning  **Service:** decision-gateway  **Expression:** `histogram_quantile(0.99, sum by(le) (rate(traces_spanmetrics_duration_milliseconds_bucket{service_name="decision-gateway",span_kind="SPAN_KIND_SERVER"}[5m]))) > 5`

## What this means

99th-percentile gateway server-span latency exceeded 5 ms over the last 5 min, on the trace-derived spanmetrics signal. Customer-visible: 1% of pricing requests took 5x+ the typical gateway cost. Upstream (markup-svc) is the most common root cause, followed by pool pressure on the gateway-to-markup-svc connection, followed by gateway-internal middleware overhead (Tracing batch flushes, MetricsSink contention).

## First check (5 min)

1. **Dashboard cross-check** — open `decision-gateway — overview` Grafana dashboard. Compare:
   - `Latency — p50 / p95 / p99` (overall) — is the spike on p99 only or also on p95?
   - `p99 by route` — is one route dominating? (`/decide` vs `/admin`)
2. **Cross-correlate with markup-svc** — open `MarkupDecideP99Slow` state. If both fire, the engine is the proximate cause; follow its runbook.
3. **Jaeger Monitor (SPM)** — gateway service, look at the slow traces (top of the latency chart). Inspect `gateway.proxy.upstream` span vs the parent `gateway.request` span — the delta is gateway-internal time.
4. **h2c flag check** — `docker compose ps decision-gateway --format '{{.Command}}'` should NOT include `--upstream-h2c` (per ADR-0006 it's measured worse than HTTP/1.1 pool-tuned on a Docker bridge). If somebody re-enabled it, that's the regression.

## If confirmed

- **markup-svc is slow** — switch to `MarkupDecideP99Slow` runbook.
- **Pool pressure** — gateway-internal time (parent - upstream span) is small, but upstream span is highly variable. Check `MaxIdleConnsPerHost` and `IdleConnTimeout` per ADR-0005; if the gateway was restarted with defaults, pool is undersized.
- **Tracing batch flush** — gateway-internal time has periodic spikes every ~5 s (OTel Collector batch interval). Drop the trace sampling ratio (`OTEL_TRACES_SAMPLER` env) or move to tail sampling per ADR-0013.
- **h2c re-enabled** — drop the `--upstream-h2c` flag from the gateway command, recreate. ADR-0006 documents why.

## If false-positive

- **Burst profile in traffic-gen** — synthetic peak above steady-state QPS. Confirm with traffic-gen logs.
- **Cold start window** — first ~60 s after gateway recreate; the HTTP/1.1 pool is empty and every request opens a fresh TCP connection. The `for: 10m` clock filters this.
- **Jaeger 429 backpressure** — if the OTel Collector is being rate-limited by Jaeger/ES, gateway span exports queue up; the spanmetrics signal degrades but real customer latency is fine. Cross-check with the raw `gateway_request_duration_seconds` counter.

## Escalation

If first-check + remediation don't resolve in 15 min, page the **decision-gateway owner** (helmedeiros). Include the dominant route from `p99 by route`, the gateway-internal vs upstream-span split from a slow trace, and current `--upstream-h2c` flag state.
