# 5. Jaeger Service Performance Monitoring via OTel spanmetrics connector

## Status

Accepted — `config/otel-collector-config.yaml` runs the OTel Collector's `spanmetrics` connector (with `namespace: traces.spanmetrics` so the emitted metric names match what Jaeger expects) and a `prometheus` exporter on `:8889/metrics`. `config/prometheus.yml` adds an `otel-collector-spanmetrics` scrape job. `docker-compose.observability.yaml` configures Jaeger with `METRICS_STORAGE_TYPE=prometheus` + `PROMETHEUS_SERVER_URL=http://prometheus:9090` + `PROMETHEUS_QUERY_NORMALIZE_CALLS=true` + `PROMETHEUS_QUERY_NORMALIZE_DURATION=true`. Jaeger's Monitor tab now renders RED metrics (Rate / Errors / Duration) for any service whose spans carry SpanKind=SERVER or CONSUMER — the platform's decision-gateway (server + client spans) and traffic-gen (client spans) light up; markup-svc shows empty until its outer `markup.decider.decide` span flips from Internal to Server (markup-svc/ADR-0020).

## Context

Jaeger 1.30+ ships a "Monitor" tab in the UI that visualizes Rate-Errors-Duration metrics derived from trace data. The "Get started with Service Performance Monitoring" placeholder shows up out of the box; without backing storage it stays empty. Per Jaeger docs, SPM requires a Prometheus-compatible TSDB plus the OTel Collector's spanmetrics connector (or the deprecated `spanmetricsprocessor`) generating the right series.

ADR-0003 (metrics phase) already stood up Prometheus for markup-svc's per-Decide metrics. The OTel Collector from ADR-0002 already receives every span the platform emits. Adding the spanmetrics connector + a Prometheus scrape + the right env vars on Jaeger is wholly mechanical — no new containers, no new data path, no new operator action. The "configure once, automated forever" property matches the rest of the platform's compose-driven posture.

The operator-visible win: the Monitor tab moves from placeholder to a working RED-metrics dashboard inside Jaeger UI. Operators investigating a latency spike on the trace list can pivot to "is this representative of the service's current p95" without leaving the page.

Three design questions.

### 1. Where the span-derived metrics come from: Collector connector vs Jaeger backend vs Prometheus-recording-rule

Three reasonable places to generate the metrics:

- **OTel Collector spanmetrics connector**: spans flow through the Collector regardless (per ADR-0002); the connector observes them as they pass and emits metrics on the side. Pros: in-stream, near-zero latency; the connector is the OTel-canonical pattern; works for any backend (Tempo, Datadog OTLP receiver). Cons: adds Collector memory pressure proportional to label cardinality.
- **Jaeger backend computes metrics**: query the trace store, aggregate. Pros: no separate pipeline. Cons: prohibitively expensive at scale; Jaeger's docs explicitly recommend against; requires an ES query per Monitor page load.
- **Prometheus recording rule on a third-party scrape source**: assumes some other component already emits the metrics. Pros: decouples. Cons: nothing in the current platform emits per-span metrics; would require a new sidecar per service or yet another piece in the pipeline.

**Pick Collector connector.** The Collector is already in the pipeline; the connector adds one in-stream observation per span. Memory cost is bounded by label-cardinality (service_name × span_name × span_kind × status_code = ~5 × 6 × 4 × 3 = ~360 series for the platform); negligible at dev scale, manageable at production scale.

### 2. Spanmetricsprocessor vs spanmetrics connector

OTel ships two implementations that generate the same metric shape:

- **`spanmetricsprocessor`** (deprecated in v0.79, removed in v0.95): runs in a traces pipeline; emits via an internal exporter.
- **`spanmetrics` connector** (v0.79+): the canonical OTel pattern — a connector connects two pipelines (a traces pipeline that feeds in, a metrics pipeline that fans out). Same metric output; cleaner config because the metrics pipeline can export to any metrics-capable sink (Prometheus, OTLP, etc).

**Pick the connector.** Future-proof (the processor is gone in newer collector versions); the connector idiom in the Collector config makes the data flow obvious — `traces` pipeline → `spanmetrics` connector → `metrics` pipeline → `prometheus` exporter.

### 3. Default histogram buckets vs custom buckets

The spanmetrics connector defaults to `0.002, 0.004, 0.006, 0.008, 0.01, 0.05, 0.1, 0.2, 0.4, 0.8, 1, 1.4, 2, 5, 10, 15` seconds. For the platform's measured latency range (100µs–10ms p99 per the ADR-0017 + connection-pool-tuning + multi-arch work), most of those buckets are above the noise floor — Jaeger's Monitor view would show "everything under 50ms" and not distinguish p50 from p99 inside the platform's hot path.

Custom buckets at `100us, 250us, 500us, 1ms, 2ms, 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 5s` cover the platform's actual range with useful resolution below 10ms.

**Pick custom.** The bucket-set divergence vs the OTel default is documented inside the connector config; operators inheriting this config for a non-platform workload should re-tune.

## Decision

`config/otel-collector-config.yaml`:

- New `connectors:` section with `spanmetrics` configured with `namespace: traces.spanmetrics` (so emitted metric names are `traces_spanmetrics_calls_total` and `traces_spanmetrics_duration_milliseconds_*` — matching Jaeger v1.53's default query namespace when `PROMETHEUS_QUERY_NORMALIZE_CALLS=true`), explicit histogram buckets per the design discussion, `metrics_flush_interval: 15s` matching Prometheus's scrape cadence.
- New `prometheus` exporter on `0.0.0.0:8889` with `send_timestamps: true` (so Prometheus samples carry the observe-time timestamp, not the scrape-time timestamp) and `const_labels: platform=pricing-decision` (federation-friendly).
- `service.pipelines` grows: the existing `traces` pipeline gets `spanmetrics` added to its exporters list (the connector implements both exporter and receiver interfaces); new `metrics` pipeline has `spanmetrics` as receiver and `prometheus` as exporter.

`config/prometheus.yml`: new scrape job `otel-collector-spanmetrics` targeting `otel-collector:8889/metrics` at the same 15s interval as the rest.

`docker-compose.observability.yaml` Jaeger service env block:

- `METRICS_STORAGE_TYPE=prometheus`: tells Jaeger to mount the SPM-storage handler against Prometheus.
- `PROMETHEUS_SERVER_URL=http://prometheus:9090`: where to query.
- `PROMETHEUS_QUERY_NORMALIZE_CALLS=true` + `PROMETHEUS_QUERY_NORMALIZE_DURATION=true`: tells Jaeger to use the new-style metric names + label set the connector emits (vs the older `spanmetricsprocessor` shape that used `service` instead of `service_name`).

No new containers. The two new env vars on Jaeger + the one new scrape job + the connector + exporter on the Collector are the entire diff.

## Consequences

### Closed by this ADR

- Jaeger UI's Monitor tab renders the RED metrics view on every operator restart, automatically, for any service emitting SpanKind=SERVER or CONSUMER spans (decision-gateway via `gateway.request`, traffic-gen via `traffic.request`). No operator UI clicks.
- Operators investigating a latency spike on the trace list pivot to "is this representative of the service's current p95" without leaving the Jaeger tab. The Monitor view shows the rolling rate + error + duration per service / per operation.
- The `traces_spanmetrics_*` metrics are also queryable via Prometheus + Grafana for operators who want cross-cluster federation or custom alerting (`alert: HighSpanErrorRate; expr: rate(traces_spanmetrics_calls_total{status_code="STATUS_CODE_ERROR"}[5m]) > 0.1`).

### NOT closed by this ADR

- markup-svc's Monitor tab is empty until its outer `markup.decider.decide` span flips from SpanKind=Internal to SpanKind=Server. That's a markup-svc-side fix tracked as ADR-0020 in that repo. The `markup.guardrails.check` and `markup.engine.evaluate` inner spans correctly stay Internal — they are not service boundaries.
- Spans whose `status_code` is `STATUS_CODE_UNSET` (which is the default when no error is set) appear in the calls metric but the errors metric is zero by construction. Jaeger's Monitor UI distinguishes errors via the `status_code=STATUS_CODE_ERROR` filter; operators want this populated for real error visibility. Spans are correctly marked Error on 5xx via the OTel middleware in each repo (gateway, markup-svc), so when an actual upstream failure happens the errors metric populates. The empty state for the dev posture is normal.
- Tail sampling. The current 100% ingest means the spanmetrics connector observes every span; SPM is exact. When tail sampling lands, the connector should run BEFORE the sampler so SPM stays based on the full span flow (this is the OTel-recommended order; documented in the Collector config when the tail_sampling processor ships).
- The Collector's spanmetrics emits one series per (service_name, span_name, span_kind, status_code) tuple. Under a high-cardinality `span_name` (e.g., if the gateway router were ever changed to use full URL paths as span names), the series count would explode. The current platform's span names are static so cardinality is bounded.

### Performance impact

- **OTel Collector**: per-span overhead = one hashmap lookup on the (service_name, span_name, span_kind, status_code) tuple + one histogram observe + one counter increment. ~100ns per span at sustained 500 QPS = ~50µs/sec CPU. Memory cost: ~360 series × ~14 buckets × 8 bytes = ~40 KB resident for the spanmetrics state. Negligible.
- **Prometheus**: one extra scrape every 15s pulling ~360 series, ~30 KB response body. Negligible.
- **Jaeger**: Monitor tab page load issues ~5 PromQL queries per page render. Prometheus answers in ~10ms each at the dev volume; cost lands on the operator's first page open + every minute on the refresh interval.

### Validation strategy

- `docker compose exec prometheus wget -qO- http://otel-collector:8889/metrics | grep traces_spanmetrics` returns the four series families (calls_total + duration_milliseconds_bucket/count/sum).
- Prometheus targets page (`/targets`) shows `otel-collector-spanmetrics` UP.
- `curl http://localhost:16686/api/metrics/calls?service=decision-gateway&...` returns `groups: > 0` with metric points.
- Open http://localhost:16686/monitor → service: decision-gateway → see RED panels populated. (markup-svc shows empty until ADR-0020 in that repo lands; that's expected.)
