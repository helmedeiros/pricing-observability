# 3. Metrics Phase — Prometheus + Grafana

## Status

Accepted — `docker-compose.observability.yaml` gains a `prometheus` container (v2.48.1) scraping markup-svc's `/metrics` endpoint via `host.docker.internal` + a `grafana` container (v10.2.3) provisioned at startup with Prometheus / Elasticsearch (logs) / Jaeger as datasources plus a starter dashboard rendering the per-outcome Decide RPS, the latency p50/p95/p99 time series, and the error + no-match rate stats. Operators open Grafana on `:3000`, see the "Pricing Platform / markup-svc — Decide overview" dashboard, and answer "what's been happening over the last hour" without writing PromQL. The metrics phase from ADR-0001 ships, completing the logs + traces + metrics triad.

## Context

ADR-0001 scoped the phased rollout: v0.0.1 logs, v0.0.2 metrics, v0.0.3 traces. ADR-0002 reordered v0.0.2 to traces because the operator's bottleneck-investigation question wanted per-request waterfalls first; metrics moved to v0.0.3.

With traces shipping end-to-end (markup-svc/ADR-0017 + decision-gateway/ADR-0002 + traffic-gen/ADR-0004 + multi-arch + the v0.0.5 connection-pool tuning that dropped median request latency from 2030 µs to 720 µs), the obvious next operator question is "is my error rate spiking right now" — which traces cannot answer at a glance. Traces are episodic; metrics are time-series. The two complement: an alert fires on a metric; the operator clicks through to traces from the same window to investigate the specific spans.

markup-svc v0.1.8 (ADR-0019 in that repo) closes the wrapper-main gap that had blocked the metrics phase — its `/metrics` endpoint ships on the canonical published image, no operator-side derivation. With that endpoint live, this ADR is the Prometheus + Grafana wiring that consumes it.

Three design questions.

### 1. Prometheus scrape topology — direct port vs through-gateway

markup-svc's `/metrics` endpoint binds on port 8080 inside the platform compose network. The platform compose does NOT expose port 8080 to the host (it intentionally hides markup-svc behind the gateway). Two scrape topologies:

- **Through the gateway**: Prometheus targets `host.docker.internal:8090/metrics`; the gateway's prefix router forwards `/metrics` to markup-svc:8080/metrics. Pros: matches the gateway-as-front-door story; the gateway can future-decorate the scrape (auth, rate limiting). Cons: adds the gateway hop to every scrape (~50 µs); a gateway outage breaks metrics scraping even when markup-svc is healthy.
- **Expose port 8080 to host**: edit decision-gateway/docker-compose.yaml to publish markup-svc's port 8080; Prometheus targets `host.docker.internal:8080/metrics` directly. Pros: bypasses the gateway entirely. Cons: contradicts the "markup-svc is hidden behind the gateway" posture; operator confusion about why /decide goes through 8090 but /metrics goes through 8080.

**Pick through-gateway** for v0.0.3. The platform's compose stays unchanged (matches the posture); the ~50 µs scrape latency is irrelevant at 15s scrape interval. The gateway adds a `/metrics` route forwarding rule (already implicit via the `/=>http://markup-svc:8080` default route in the platform compose). A future ADR can switch to direct-port if metrics-during-gateway-outage becomes an operational requirement.

### 2. Grafana provisioning vs UI-driven datasource setup

Grafana ships with both: file-based provisioning at startup AND a UI for adding datasources interactively. Two postures:

- **Provisioning files**: datasources + dashboards are described in YAML/JSON files mounted at startup. Pros: reproducible from compose; `docker compose down -v && docker compose up` rebuilds the exact dashboard set; new operators onboarding see the same view as everyone else; the dashboard JSON is in git so PR review covers it. Cons: editing dashboards via the UI requires saving the JSON back to disk (or using Grafana's "save to file" workflow).
- **UI-driven**: operators add datasources + build dashboards via the Grafana UI; the state lives in Grafana's internal SQLite. Pros: fast iteration. Cons: not reproducible from compose; new operators have to either snapshot the dashboard JSON or follow a written walkthrough.

**Pick provisioning files.** The dev posture wins here — the compose stack is reproducible end-to-end, dashboards are in git for review, operator onboarding is "bring up the stack, open Grafana." Editing dashboards via the UI still works (`allowUiUpdates: true` in the provider config); operators promote in-UI changes to git by exporting the dashboard JSON.

### 3. Starter dashboard scope — minimal vs comprehensive

Two starter-dashboard postures:

- **Minimal**: one dashboard, one service, the four most-needed panels (per-outcome RPS, latency percentiles, error rate, no-match rate). Pros: doesn't over-claim; operators see immediately useful signal; the dashboard is a starting point for derived dashboards. Cons: doesn't show off the full Prometheus query language.
- **Comprehensive**: multiple dashboards covering markup-svc + decision-gateway + traffic-gen, with histograms broken down by adapter / model_version / rule, plus correlation panels joining to logs + traces. Pros: shows the platform's full observability surface. Cons: most panels would be empty (decision-gateway + traffic-gen don't expose /metrics yet); operators see "broken" panels and lose trust.

**Pick minimal**. One dashboard, four panels, all backed by metrics that markup-svc actually emits. Operators extend per their needs; the v0.0.3 release ships the simplest thing that works.

## Decision

`config/prometheus.yml`: scrape config targeting `host.docker.internal:8090/metrics` with `job_name: markup-svc`, scrape interval 15s, external_labels `platform: pricing-decision`. Future targets (decision-gateway, traffic-gen) land as those repos ship their own `/metrics` endpoints.

`config/grafana-datasources.yaml`: provisions three datasources at Grafana startup — Prometheus (default), Elasticsearch (logs index `platform-logs-*`), Jaeger. The three-datasource setup means operators on a single Grafana view can pivot from a metric spike to the matching logs window to the matching trace ID without leaving the tab.

`config/grafana-dashboards.yaml`: provider config pointing Grafana at the `dashboards/` directory; `updateIntervalSeconds: 30` so dashboard JSON updates in the file hot-reload; `allowUiUpdates: true` so operators can edit in the UI and export back.

`config/dashboards/markup-decide-overview.json`: starter dashboard with four panels — per-outcome Decide RPS (timeseries), per-adapter Decide RPS (timeseries), latency p50/p95/p99 (timeseries), error rate + no-match rate (stat panels with thresholds).

`docker-compose.observability.yaml`: gains two services. `prometheus` (image `prom/prometheus:v2.48.1`) binds host port 9090, mounts the config + uses `host.docker.internal:host-gateway` extra_hosts mapping so it reaches the platform compose's gateway. 7-day retention matches the dev posture. `grafana` (image `grafana/grafana:10.2.3`) binds host port 3000, mounts the three provisioning configs, uses anonymous-admin auth so operators do not need login credentials in dev.

Aggregate observability stack footprint jumps from ~4 GB (v0.0.2: ES + Kibana + Filebeat + OTel Collector + Jaeger) to ~4.5 GB (v0.0.3: + Prometheus ~200 MB idle + Grafana ~150 MB idle). Production deployments size up + persist Prometheus's TSDB to a real volume.

## Consequences

### Closed by this ADR

- Operator's "what's been happening" question answerable at sub-second resolution: open Grafana → markup-svc overview dashboard → see RPS, latency, error rate over the last 15 min by default.
- Three-datasource Grafana setup: an operator on the markup-svc dashboard sees a latency spike at 14:32, clicks through Elasticsearch datasource to see the logs from that window, clicks through Jaeger to see the spans. Same browser tab, three views, one investigation.
- Pricing-observability ADR-0001's phased rollout is complete: logs (v0.0.1) + traces (v0.0.2) + metrics (v0.0.3). Each phase is independently usable; together they cover the operator's investigation triangle.

### NOT closed by this ADR

- decision-gateway + traffic-gen `/metrics` endpoints. The Prometheus scrape config has a stub for adding them once those repos ship their own metric adapters. Tracked in workspaceBRE/PLAN.md.
- Alerting rules + Alertmanager. Prometheus has no `rule_files` configured yet; an alert on `rate(markup_decide_total{outcome="error"}[5m]) > 0.1` would be the obvious first one. Lands in a follow-up ADR.
- Production-grade Prometheus storage (longer retention, remote_write to Thanos / Cortex / Mimir for HA + multi-cluster federation). Out of scope for dev posture.
- Grafana saved-object backup. Provisioning + git for the dashboard JSON is the dev posture; production deployments add periodic export to a remote backend.
- Kibana URL template for `attrs.trace_id` → Jaeger (the v0.0.3 follow-up the decision-gateway ADR-0003 mentioned). Tracked as a separate small ADR in this repo when Grafana's logs panel proves insufficient for the workflow.
- Custom histogram buckets in markup-svc. The default `prometheus.DefBuckets` (5ms-10s) is wider than markup-svc's typical 10-100 µs Decide latency; the p50/p95/p99 panel reads "all under 5ms" which is correct but less informative than custom finer buckets. markup-svc/ADR-0019 already named this as a follow-up.

### Performance impact

- **Prometheus container**: ~200 MB resident at idle, +50-100 MB per million unique series under steady scrape load. v0.0.3 estimate: ~120 series per scrape × 4 scrapes/min × 60 min × 24 hr × 7 days = ~7M sample writes; well under any production-sized Prometheus.
- **Grafana container**: ~150 MB resident at idle, +50-100 MB per active user. Negligible at dev scale.
- **Scrape network cost**: ~5 KB response body per scrape × 4 scrapes/min × 1 target = ~20 KB/min cross-network bandwidth between observability stack and platform stack. Trivial.
- **markup-svc CPU on scrape**: serializing ~120 series + writing to the response body costs ~100 µs of one goroutine per scrape — well below any sustained request budget.

### Validation strategy

- `docker compose -f docker-compose.observability.yaml config -q` accepts the two new services and the four new volume mounts (the `validate-compose` Makefile target).
- Manual smoke documented in `docs/cookbook/metrics-flowing.md` (a future cookbook file): bring up the platform compose with markup-svc:v0.1.8 + `--metrics-enabled`; bring up the observability compose; open http://localhost:9090/targets and observe markup-svc=UP; open http://localhost:3000 → Dashboards → Pricing Platform → "markup-svc — Decide overview" → see the panels rendering live RPS + latency.
- Cross-signal smoke: induce a latency spike (e.g., briefly stop markup-svc); Grafana's p99 panel jumps; click through to Elasticsearch logs (same window) → see the gateway access lines with 5xx; click through to Jaeger → see the matching trace IDs with the upstream-unreachable error span.
