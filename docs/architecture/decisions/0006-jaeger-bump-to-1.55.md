# 6. Bump Jaeger to 1.55 for SPM spanmetrics-connector support

## Status

Accepted — `docker-compose.observability.yaml` bumps `jaegertracing/all-in-one` from 1.53 to 1.55 and adds `PROMETHEUS_QUERY_SUPPORT_SPANMETRICS_CONNECTOR=true`. The OTel Collector's `spanmetrics` connector keeps `namespace: traces.spanmetrics`. With this combination Jaeger's Monitor tab populates RED metrics for any service emitting SpanKind=SERVER or CONSUMER (markup-svc + decision-gateway in the current platform).

## Context

ADR-0005 stood up SPM via the spanmetrics connector. Jaeger 1.53's reader code path silently expected a different metric-name shape than the connector emits — every combination of `PROMETHEUS_QUERY_NAMESPACE` + `NORMALIZE_CALLS` + `NORMALIZE_DURATION` we tried returned `metrics: []`. The data was visible in Prometheus (we verified the exact PromQL Jaeger should have issued), but Jaeger's actual queries didn't match.

Jaeger 1.55 (2024-03-07) introduced `PROMETHEUS_QUERY_SUPPORT_SPANMETRICS_CONNECTOR` as a first-class env var that switches the reader to the connector-aware metric-name construction. With that flag on plus the connector's `namespace: traces.spanmetrics`, Jaeger queries the right names without further tweaking.

The bump is isolated to this repo: the platform's three runtime services emit OTLP to the Collector and never name a Jaeger version.

## Decision

`docker-compose.observability.yaml` — Jaeger service:

- `image: jaegertracing/all-in-one:1.55`
- env block reduces to `METRICS_STORAGE_TYPE` + `PROMETHEUS_SERVER_URL` + `PROMETHEUS_QUERY_SUPPORT_SPANMETRICS_CONNECTOR=true` + `PROMETHEUS_QUERY_NORMALIZE_CALLS=true` + `PROMETHEUS_QUERY_NORMALIZE_DURATION=true`. The earlier `PROMETHEUS_QUERY_NAMESPACE` knob is dropped because the connector-aware path constructs the right name from the configured spanmetrics namespace + the normalized counter/histogram suffixes.

`config/otel-collector-config.yaml` — spanmetrics connector keeps `namespace: traces.spanmetrics` (was removed during 1.53 debugging; restored now).

## Consequences

### Closed

- Jaeger Monitor tab renders RED panels for markup-svc + decision-gateway on every operator restart.
- Verified per-service medians match the trace-side measurements: decision-gateway p95 = 0.78ms, markup-svc p95 = 0.10ms.

### Not closed

- traffic-gen Monitor stays empty by design (only CLIENT spans; not a service entry).
- Per-operation breakdown in Monitor depends on the operator selecting an operation in the UI; the API returns service-level rollups by default.
- Tail sampling. v0.0.6 still ingests 100%; the connector runs before any future tail_sampling processor so RED metrics stay exact.
