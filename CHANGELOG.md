# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
