# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.18] - 2024-05-17

Widen `AdminHotReloadRejected` to 5xx and add per-route latency panels.

### Changed

- `config/prometheus-rules.yml`: `AdminHotReloadRejected` matches `status=~"[45].."` instead of `4..`. Hot-reload returns 500 on CSV parse errors (markup-svc loader path), which the previous expression silently dropped.

### Added

- `config/dashboards/decision-gateway-overview.json`: two new panels — `p99 by route` and `p95 by route` — splitting the existing collapsed-latency panel by route now that the label is correct (decision-gateway v0.0.9 + ADR-0009). Excludes the empty-route `/metrics` self-scrape via `route!=""`.

## [0.0.17] - 2024-05-14

Tighten `AdminHotReloadRejected` now that decision-gateway v0.0.9 fixed the empty-route-label bug.

### Changed

- `config/prometheus-rules.yml`: `AdminHotReloadRejected` expression switches from `gateway_requests_total{method="POST",status="400"}` to `gateway_requests_total{route="/admin",status=~"4.."}`. Filters precisely to the admin path instead of inferring it from method+status, and catches `401` / `403` / `404` / `429` rejections too.

### Operator-visible

Same end-to-end shape as v0.0.16. Corrupted-rules smoke test still fires within ~90 s and delivers via webhook.

## [0.0.16] - 2024-05-07

Alert on rejected hot-reload. markup-svc/ADR-0026 made hot-reload fail closed — bad rules get a 400 with the issue list, the previous (working) rules keep serving. This alert pages the operator within ~90 s of the rejection so the operator-vs-platform discrepancy is caught fast. Closes ADR-0014.

### Added

- `config/prometheus-rules.yml`: new group `admin-changes`, alert `AdminHotReloadRejected`. Expression `sum(increase(gateway_requests_total{method="POST",status="400"}[5m])) > 0` for 1 min. Severity warning, service `decision-gateway`. Annotations point operators at the gateway access log + `/admin/diagnose` for the issue list.

### Operator-visible

Smoke-tested end-to-end: corrupted rules.csv → 3 × POST /admin/reload → 400 each → alert pending → firing in ~70 s → AlertManager batched within group_wait (10 s) → webhook delivered to alert-sink → JSON line on stdout. Total time from rejected reload to operator visibility: < 90 s.

### Pairs with

markup-svc v0.1.16 (ADR-0026 — Diagnose-gated /admin/reload). The alert is the "fast-notify" half of the safety story the gate created.

## [0.0.15] - 2024-04-24

CI fix. v0.0.14 tagged before the ADR-0013 entry was staged into `docs/architecture/decisions/README.md`; `check-adrs` failed on the tag CI. Same pattern as v0.0.12 → v0.0.13. Source contents are identical to v0.0.14.

## [0.0.14] - 2024-04-23

Tail sampling on the OTel Collector. The 2000 QPS perf run identified Jaeger ES as the platform's saturation point (~10k spans/sec → 429s). Tail sampling drops the Jaeger ingest load to ~1k spans/sec while keeping 100% of errors + 100% of slow traces + 10% probabilistic. SPM Monitor + Grafana panels reading spanmetrics stay exact because the spanmetrics connector still sees every span. Closes ADR-0013.

### Changed

- `config/otel-collector-config.yaml`: traces pipeline splits into two. `traces` (100% raw) feeds the spanmetrics connector + debug. `traces/sampled` runs through `tail_sampling` before exporting to Jaeger.
- `processors.tail_sampling` block: 10 s decision_wait, 100k trace buffer, policies = errors + slow-traces (>10 ms) + 10% probabilistic.

### Pairs with

The application stack continues to handle 2000 QPS sustained (see PLAN.md latency table); this release only changes what Jaeger storage sees.

## [0.0.13] - 2024-04-17

CI fix. v0.0.12 tagged before the ADR-0012 entry was staged into `docs/architecture/decisions/README.md`, so `check-adrs` failed on the tag CI. The README index was backfilled in a follow-up commit but the tag stayed pointed at the bad commit. v0.0.13 retags at the fixed commit. Source contents are identical to v0.0.12.

## [0.0.12] - 2024-04-16

Per-service Grafana starter dashboards. Operators land on three dashboards in the Pricing Platform folder; the gateway + traffic-gen panels surface the per-service Prometheus signal from v0.0.11 without PromQL fluency. Closes ADR-0012.

### Added

- `config/dashboards/decision-gateway-overview.json` — five panels: RPS by route, RPS by status, p50/p95/p99 latency, 5xx rate, 4xx rate.
- `config/dashboards/traffic-gen-overview.json` — four panels: target-vs-achieved QPS, rate by outcome, outbound latency, generator deficit (target − achieved).
- ADR-0012.

## [0.0.11] - 2024-04-09

Per-service Prometheus scrape. The single `markup-svc` job (which routed through the gateway at `:8090/metrics`) splits into three jobs targeting each service's own `/metrics` endpoint. Closes ADR-0011.

### Changed

- `config/prometheus.yml`: jobs `markup-svc` (port 8080), `decision-gateway` (port 8090), `traffic-gen` (port 9101). All three carry `service` labels Grafana panels can slice on.

### Pairs with

decision-gateway/docker-compose.yaml change exposing markup-svc's port 8080, enabling `--metrics-enabled` on the gateway, and enabling `--metrics-listen=:9101` on traffic-gen with port 9101 exposed.

## [0.0.10] - 2024-04-02

Kibana `attrs.trace_id` renders as a clickable Jaeger link. Operators click a trace ID value in Discover and the matching Jaeger trace opens in a new tab — one click instead of copy/paste. Closes ADR-0010.

### Added

- `config/kibana-saved-objects.ndjson`: `platform-logs` data view's `fieldFormatMap` adds a `url` formatter for `attrs.trace_id` pointing at `http://localhost:16686/trace/{{value}}`. Cell text stays the bare trace ID; the click opens Jaeger in a new tab.
- `config/kibana-init.sh`: import POST gains retry-with-backoff (up to 20 attempts at 3 s intervals) so a first-boot 503 from the saved-objects API no longer leaves the data view half-provisioned.
- ADR-0010.

## [0.0.9] - 2024-03-26

AlertManager + webhook receiver. The five v0.0.8 alerts now have a destination instead of evaluating into a dead-letter UI. Closes ADR-0009.

### Added

- `alertmanager` (`prom/alertmanager:v0.27.0`) — single route → single receiver delivering all alerts to a webhook.
- `alert-sink` (`python:3.12-alpine`) — ~30-line Python HTTP server that emits one JSON line per alert on stdout (Filebeat picks it up; Kibana queryable as `attrs.msg:"alertmanager.alert"`).
- `config/alertmanager.yml` — route + receiver + grouping (`alertname, service`).
- `config/alert-sink.py` — webhook receiver.
- `config/prometheus.yml` — `alerting.alertmanagers` block pointing at the new container.
- ADR-0009.

### Operator-visible

- AlertManager UI at http://localhost:9093 — fired alert list, silences, inhibitions.
- Alert deliveries visible via `docker compose logs alert-sink`.
- Smoke-tested end-to-end with a synthetic SmokeTest alert posted directly to AlertManager.

## [0.0.8] - 2024-03-19

Five alerting rules wired into Prometheus. Closes the "we built it all but can't get paged" gap. Alerts visible at http://localhost:9090/alerts; AlertManager routing lands in a follow-up. Closes ADR-0008.

### Added

- `config/prometheus-rules.yml`: two groups, five rules.
  - `markup-svc`: `MarkupDecideErrorRateHigh` (warning), `MarkupDecideP99Slow` (warning, p99 > 5 ms for 5 m), `MarkupMetricsScrapeDown` (critical, scrape down 2 m).
  - `platform-spans`: `GatewayRequestErrorRateHigh` (warning), `GatewayRequestP99Slow` (warning, p99 > 5 ms for 10 m).
- `config/prometheus.yml`: new `rule_files:` directive.
- `docker-compose.observability.yaml`: mounts the new rules file.
- ADR-0008.

## [0.0.7] - 2024-03-12

Jaeger System Architecture tab now populates. The graph reads from a `jaeger-dependencies-*` index produced by the `jaeger-spark-dependencies` batch job; without that job the tab shows "No service dependencies found". Closes ADR-0007.

### Added

- `config/spark-deps-loop.sh`: small sh loop that pins `DATE=today` + the storage env then invokes the image entrypoint, sleeping `INTERVAL` (default 120 s) between runs.
- `docker-compose.observability.yaml`: new `spark-dependencies` service (image `ghcr.io/jaegertracing/spark-dependencies/spark-dependencies:latest`) with the loop wrapper as entrypoint.
- ADR-0007 (Accepted).

### Operator-visible

System Architecture renders 5 edges out of the box: traffic-gen → decision-gateway → markup-svc plus two self-edges (each service calling itself within the same trace, which is technically correct).

### Resource footprint

Spark process is ~500 MB RAM at startup, ~10-15 s per run on dev volumes; idle ~85% of the time between 120-s ticks.

## [0.0.6] - 2024-03-08

Jaeger bumped to 1.55 for first-class SPM spanmetrics-connector support. v0.0.5 left the Monitor tab silently empty because Jaeger 1.53's reader expected a metric-name shape the connector doesn't emit. v1.55 added `PROMETHEUS_QUERY_SUPPORT_SPANMETRICS_CONNECTOR=true` which switches to connector-aware name construction. Closes ADR-0006.

### Changed

- `docker-compose.observability.yaml`: `jaegertracing/all-in-one:1.53` → `:1.55`; Jaeger env block reduced (drop `PROMETHEUS_QUERY_NAMESPACE`; add `PROMETHEUS_QUERY_SUPPORT_SPANMETRICS_CONNECTOR=true`).
- `config/otel-collector-config.yaml`: spanmetrics connector keeps `namespace: traces.spanmetrics` (was removed during 1.53 debugging; restored).
- Excess inline comments stripped across the observability configs and the OTel Collector config.

### Operator-visible

Jaeger Monitor tab now populates for markup-svc + decision-gateway. Verified: markup-svc p95 = 96µs at 383 calls/min; decision-gateway p95 = 780µs at 376 calls/min. traffic-gen stays empty by design (only CLIENT spans; not a service entry).

## [0.0.5] - 2023-03-31

Jaeger Service Performance Monitoring. The "Monitor" tab in Jaeger UI moves from the "Get started" placeholder to a working RED-metrics dashboard on every operator restart, automatically, with zero UI clicks. Closes ADR-0005.

### Added

- `config/otel-collector-config.yaml`: `spanmetrics` connector (namespace `traces.spanmetrics` so emitted names match Jaeger's default query namespace, custom histogram buckets `100us, 250us, ..., 5s` covering the platform's measured latency range with useful sub-millisecond resolution, `metrics_flush_interval: 15s` matching Prometheus's scrape cadence) plus a `prometheus` exporter on `0.0.0.0:8889` with `send_timestamps: true` + `const_labels: platform=pricing-decision`. New `metrics` pipeline with the connector as receiver + the prometheus exporter as exporter.
- `config/prometheus.yml`: new scrape job `otel-collector-spanmetrics` targeting `otel-collector:8889/metrics` at 15s.
- `docker-compose.observability.yaml`: Jaeger service env block gains `METRICS_STORAGE_TYPE=prometheus` + `PROMETHEUS_SERVER_URL=http://prometheus:9090` + `PROMETHEUS_QUERY_NORMALIZE_CALLS=true` + `PROMETHEUS_QUERY_NORMALIZE_DURATION=true`.
- ADR-0005 (Accepted): Jaeger SPM via OTel spanmetrics connector. Three design questions answered: connector vs processor vs Jaeger-backend computation (pick connector — in-stream, OTel-canonical, decoupled from any backend); spanmetricsprocessor vs spanmetrics connector (pick connector — future-proof, the processor is removed in newer collector versions); default vs custom histogram buckets (pick custom — the OTel defaults bucket the platform's sub-10ms hot path together).

### Operator-visible

- Jaeger UI Monitor tab (http://localhost:16686/monitor) renders RED panels for any service emitting SpanKind=SERVER or CONSUMER. decision-gateway (`gateway.request`) and traffic-gen (`traffic.request`) light up out of the box. markup-svc shows empty until its outer `markup.decider.decide` span flips to SpanKind=Server (tracked as ADR-0020 in that repo).
- The `traces_spanmetrics_*` metrics are also queryable in Prometheus + Grafana for cross-signal federation or custom alerting.

### Performance impact

OTel Collector: ~100ns per span observe overhead + ~40 KB resident for the spanmetrics state at the platform's ~360-series cardinality. Negligible. Prometheus: one extra ~30 KB scrape every 15s. Jaeger: ~5 PromQL queries per Monitor page render at ~10ms each.

## [0.0.4] - 2023-03-30

Kibana data-view provisioning. Closes the operator-friction loop where every `docker compose down -v` wiped the Kibana saved objects and forced the operator to re-create the `platform-logs-*` data view by hand. Two data views land per compose bring-up: `platform-logs-*` (Filebeat-shipped application logs) + `jaeger-span-*` (Jaeger's span storage in ES). The Kibana `defaultIndex` is set to `platform-logs` so Discover opens directly on the logs view. Closes ADR-0004.

### Added

- `config/kibana-saved-objects.ndjson`: two `index-pattern` saved objects (NDJSON, one per line) describing `platform-logs-*` (time field `@timestamp`) and `jaeger-span-*` (time field `startTimeMillis`). Format follows Kibana's export NDJSON so operators customizing a data view via the UI can export it directly into this file.
- `config/kibana-init.sh`: polls `/api/status` until Kibana reports "available" (up to ~120s for first-boot migration), POSTs the NDJSON via `/api/saved_objects/_import?overwrite=true` (idempotent across restarts), POSTs `defaultIndex=platform-logs` to `/api/kibana/settings`.
- `docker-compose.observability.yaml`: new `kibana-init` one-shot service (image `curlimages/curl:8.5.0`, ~10 MB, `restart: "no"`). Mounts the script + NDJSON; entrypoint is the script. Steady state: container is "exited" — the cookbook calls this out so operators do not mistake it for a failure.
- ADR-0004 (Accepted): Kibana data-view provisioning. One design question answered: init container vs operator-side script (pick init container; matches the rest of the platform's compose-driven posture — Filebeat auto-discovers, OTel Collector auto-receives, Grafana auto-provisions, Kibana now does too).

### Resource footprint

`curlimages/curl:8.5.0` is ~10 MB pulled, ~3 MB resident during execution, zero after exit. Negligible delta to the v0.0.3 stack budget.

## [0.0.3] - 2023-03-29

Metrics phase. Closes the third leg of ADR-0001's logs + traces + metrics triad. Operators now have:

- Per-outcome Decide RPS, p50/p95/p99 latency, error rate + no-match rate at sub-second resolution via Grafana dashboards.
- Three-datasource Grafana setup (Prometheus + Elasticsearch logs + Jaeger) — one browser tab, three views, pivot from metric spike → log lines → trace IDs without leaving the page.
- Operators answer "what's been happening over the last hour" without writing PromQL; the starter dashboard surfaces the most-needed signals from markup-svc/ADR-0019.

Validated against markup-svc v0.1.8 which ships the `/metrics` endpoint per its ADR-0019. Closes ADR-0003.

### Added

- `docker-compose.observability.yaml`: two new services.
  - `prometheus` (image `prom/prometheus:v2.48.1`): binds host port 9090, scrapes via `host.docker.internal:host-gateway` extra-hosts mapping (same pattern the OTel Collector uses for the OTLP receiver). 7-day TSDB retention matches the dev posture; production overrides via a real volume.
  - `grafana` (image `grafana/grafana:10.2.3`): binds host port 3000, anonymous-admin auth so operators do not need credentials in dev; provisioned at startup with three datasources + the starter dashboard.
- `config/prometheus.yml`: scrape config targeting `host.docker.internal:8090/metrics` (through the gateway) with `job_name: markup-svc`, scrape interval 15s, `external_labels: platform=pricing-decision`. decision-gateway + traffic-gen targets land as those repos ship their own `/metrics` endpoints.
- `config/grafana-datasources.yaml`: provisions Prometheus (default), Elasticsearch (logs index `platform-logs-*`), and Jaeger as the three datasources.
- `config/grafana-dashboards.yaml`: dashboard provider config; `updateIntervalSeconds: 30` so dashboard JSON updates in the file hot-reload; `allowUiUpdates: true` so operators can edit in the UI and export back.
- `config/dashboards/markup-decide-overview.json`: starter dashboard with four panels — per-outcome Decide RPS (timeseries), per-adapter Decide RPS (timeseries), latency p50/p95/p99 (timeseries), error rate + no-match rate (stat panels with green/yellow/red thresholds).
- ADR-0003 (Accepted): metrics phase. Three design questions answered: scrape topology — through-gateway vs direct-port (pick through-gateway; matches the platform's hidden-backend posture; ~50µs scrape latency is irrelevant at 15s interval); provisioning files vs UI-driven (pick provisioning files; reproducible from compose, git-reviewable, operators still edit via UI when `allowUiUpdates: true`); starter dashboard scope — minimal vs comprehensive (pick minimal; one dashboard, four panels, all backed by metrics markup-svc actually emits).

### Changed

- ADR-0002 status flipped from Proposed → Accepted in the README index (it was flipped in the ADR file itself in the v0.0.2 release; the index had drifted).

### Resource footprint

Aggregate observability stack jumps from ~4 GB (v0.0.2) to ~4.5 GB (v0.0.3): + Prometheus ~200 MB idle + Grafana ~150 MB idle. Production deployments size up + persist Prometheus's TSDB to a real volume.

## [0.0.2] - 2023-03-21

Second release. Ships the traces phase from ADR-0001 — reordered ahead of metrics because the operator's near-term goal is markup-svc + decision-gateway performance investigation, and traces are the right tool for that question (per-rule + per-decorator latency in a waterfall view, not Prometheus counters). The observability stack gains an OTel Collector container that ingests OTLP gRPC + HTTP and exports to Jaeger; Jaeger writes to the same Elasticsearch instance the v0.0.1 logs phase already stands up. Operators open Jaeger UI on host port 16686, search service `markup-svc`, and see one `markup.decider.decide` span per `/decide` request with the `rule.markup.*` attributes the markup-svc OTel decorator (ADR-0009 in that repo) emits. Validated end-to-end against markup-svc v0.1.5 which bootstraps the OTel SDK in-binary (its ADR-0016) so `--otel-enabled` on the published image produces real exporting spans.

### Added

- `docker-compose.observability.yaml`: two new services. `otel-collector` (image `otel/opentelemetry-collector-contrib:0.92.0`) binds host ports `4317` (OTLP gRPC) and `4318` (OTLP HTTP); platform services on a different Docker network reach it via `host.docker.internal`. `jaeger` (image `jaegertracing/all-in-one:1.53`) binds host port `16686` for the UI; runs with `SPAN_STORAGE_TYPE=elasticsearch` + `ES_SERVER_URLS=http://elasticsearch:9200` + `COLLECTOR_OTLP_ENABLED=true` so spans persist in the existing ES instance and the same `docker compose down -v` wipes logs + traces together for a fresh start.
- `config/otel-collector-config.yaml`: OTLP receiver on `0.0.0.0:4317` (gRPC) + `0.0.0.0:4318` (HTTP); no processors at v0.0.2 (sampling stays at 100% for dev — a `tail_sampling` processor lands when production volume motivates it); two exporters (`otlp` → `jaeger:4317` for the storage path, `debug` for operator-visible drop diagnosis). The Collector config stays minimal — no Zipkin / Jaeger Thrift / Prometheus / Kafka receivers because no consumer asks.
- ADR-0002 (Accepted): traces phase. Reorders ADR-0001's phase plan (traces becomes v0.0.2, metrics moves to v0.0.3). Three design questions answered: OTLP receiver / exporter shape (pick OTLP-to-Jaeger over the legacy Jaeger exporter — both supported by jaeger-all-in-one and OTLP is the OTel-canonical wire shape), Jaeger storage backend (pick `elasticsearch` over `memory` and `cassandra` — single-ES posture from ADR-0001 holds, dev volumes share storage, operators wipe both signals with one volume command), all-in-one vs split deployment (pick all-in-one — same posture markup-svc and the other platform services take, production-grade collector / query / agent split lands when trace volume motivates it).

### Changed

- ADR-0001 phase ordering: v0.0.2 was originally the metrics phase. The repriotization to traces-first is documented inside ADR-0002 (Context section) so the chain stays auditable. Metrics moves to v0.0.3; the phased rollout commitment from ADR-0001 holds.

### Deferred to v0.0.3

- Prometheus + Grafana for metrics. Still blocks on at least one platform service shipping a `/metrics` endpoint; traffic-gen's deferred `/metrics` endpoint is the natural pairing.

### Out of scope for v0.0.2

- decision-gateway gateway-side span emission (one span per inbound request with route + duration_ms + correlation_id attributes). The Collector's OTLP receiver is ready to ingest those spans on day one; the gateway-side ADR lands in the decision-gateway repo.
- traffic-gen root-span emission + traceparent header propagation on outbound POSTs. Same pattern; separate ADR in traffic-gen.
- Cross-service correlation of traces with logs via `attrs.correlation_id` (the platform's `X-Correlation-ID` header) ↔ OTel's `trace_id` / `span_id`. Bridging them is a span-attribute mapping that lands when decision-gateway ships the gateway middleware ADR.
- Sampling configuration. v0.0.2 ingests 100% of spans through the Collector's `processors: []` config. A `tail_sampling` or head-sampler processor lands when production trace volume motivates it.

## [0.0.1] - 2023-03-16

First public release. pricing-observability ships the v0.0.1 logs pipeline for the Pricing Decision Platform: Filebeat + Elasticsearch + Kibana running alongside the existing three-service platform stack, with every platform service's stdout JSON queryable in Kibana by `attrs.correlation_id`. Config-only repo — no Go code, no binary, no Dockerfile to publish. ADR-0001 (Accepted) covers the phased rollout and the Elasticsearch + Kibana vs Loki + Grafana / Jaeger vs Tempo design decisions.

### Added

- `docker-compose.observability.yaml` at the repo root: three services (Elasticsearch 8.11.4 single-node, Kibana 8.11.4 on host port 5601, Filebeat 8.11.4 reading `/var/run/docker.sock` + `/var/lib/docker/containers`). Designed to run alongside `decision-gateway/docker-compose.yaml`; Filebeat reaches the platform via the Docker daemon so the two compose stacks need not share a Docker network. Dev posture: `xpack.security.enabled=false` so curl + Kibana + Filebeat connect without TLS cert provisioning; production gates security at the network layer (same posture markup-svc's `/admin/reload` ADR-0008 takes).
- `config/filebeat.yml`: Docker autodiscover provider tails platform container logs via image-prefix filter on `ghcr.io/helmedeiros/{markup-svc,decision-gateway,traffic-gen}`; `decode_json_fields` processor elevates the application JSON line into top-level Elasticsearch fields (so Kibana queries on `attrs.correlation_id` etc. work without a custom parser); `add_error_key` keeps markup-svc plain-text lines ingestable until the convergence ADR ships. Output is a daily index `platform-logs-YYYY.MM.DD` with 1 shard / 0 replicas (single-node dev posture).
- `docs/cookbook/logs-flowing.md`: operator recipe walking through bringing both stacks up, creating the Kibana index pattern `platform-logs-*`, firing a request with a known `X-Correlation-ID` through the gateway, and watching the line appear in Discover filtered by `attrs.correlation_id`. The ASCII pipeline diagram + "What to check after" curl probes + "Mistakes to avoid" list + the explicit ~2.5 GB RAM resource budget make the recipe self-contained.
- `Makefile` `check-adrs` + `validate-compose` targets and a `make ci-local` that runs both. The compose validator (`docker compose -f <file> config -q`) gracefully skips when docker is not on PATH so minimal CI runners stay usable.
- CI workflow with `tags: ['v*']` from day one (the markup-svc v0.1.2 lesson). No image-publish job because the repo ships configs, not a binary; the upstream `docker.elastic.co/` images are referenced verbatim.
- ADR-0001 (Accepted): observability stack design. Picks Elasticsearch + Kibana over Loki + Grafana for logs (per user preference; the line-JSON shape is what ES's `dynamic_field_mapping` ingests cleanly and Kibana's structured-field filter UI is the right operator tool). Picks Jaeger over Tempo for traces (per user preference; the v0.0.3 Jaeger backend can store spans in the same Elasticsearch that v0.0.1 stands up for logs). Phased rollout (v0.0.1 logs / v0.0.2 metrics / v0.0.3 traces) so each phase ships operator value without waiting for the others' per-repo prerequisites (traffic-gen `/metrics` for v0.0.2; OTel span emission on traffic-gen + decision-gateway for v0.0.3).

### Deferred to v0.0.2

- Prometheus + Grafana for metrics. Blocks on at least one platform service shipping a `/metrics` endpoint; traffic-gen's deferred `/metrics` endpoint is the natural pairing.

### Deferred to v0.0.3

- OTel Collector + Jaeger (with Elasticsearch as Jaeger's storage backend) for traces. Blocks on traffic-gen and decision-gateway emitting OTel spans (per-repo ADRs in those repos).
