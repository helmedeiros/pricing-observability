# 11. Model Registry alerting rules + exemplar storage

## Status

Accepted — `config/prometheus-rules.yml` ships a new `model-registry` group with four alerts wired against the lifecycle counters model-registry v0.0.4+ exposes. `config/prometheus.yml` gains a `model-registry` scrape target. The Prometheus container command now carries `--enable-feature=exemplar-storage` so the `registry_deploy_duration_seconds` `trace_id` exemplars survive into the query API and Grafana panels can drill from a slow-bucket bar to the matching Jaeger waterfall.

## Context

model-registry v0.0.4 shipped the operator-facing write surface (`/upload`, `/promote`, `/rollback`) wired through Reader/Writer contracts on envstate + audit, a rolling per-instance deployer, and SQLite backings. The hardening pass that followed instrumented every code path with lifecycle metric counters (`registry_uploads_total`, `registry_promotions_total{env, role, outcome}`, `registry_rollbacks_total{env, outcome}`, `registry_deploys_total{outcome}`, `registry_deploy_duration_seconds`, `registry_state_drift_total{env}`) and lifecycle traces (`registry.deploy.push_to_instance`, `registry.deploy.readyz`, `registry.champion.commit_state`, `registry.audit.record`). The histogram carries `trace_id` exemplars under the OpenMetrics exposition.

What was missing: no alert fires on any of those counters. An operator watching Grafana eventually sees a spike; an operator who is not watching misses it. The registry side has zero pageable signals.

This ADR closes that loop with four alerts targeted at the operationally meaningful failure modes the v0.0.4 surface exposes.

## Decision

Four alerts in a new `model-registry` group plus the Prometheus exemplar-storage feature flag.

### Alerts

**`RegistryUploadFailureRate`** — `sum(rate(registry_uploads_total{outcome!="ok"}[5m])) > 0.05` for 5 min. Warning. Fires when more than 1 upload failure every 20 s sustained over 5 min. Surfaces malformed multipart bodies, oversize payloads, and substrate-write failures. Distinct from a one-off operator typo because of the 5-min window.

**`RegistryPromotionFailureRate`** — `sum(rate(registry_promotions_total{outcome=~"failed|partial"}[5m])) > 0.02` for 5 min. Warning. Fires when promotion attempts hit `failed` (all instances failed the rolling push) or `partial` (some instances failed) at sustained rate. Partial-deploy commits state per ADR-0005 — the bar is "this is normal-rare, but a sustained rate means a sick instance the operator must attend to".

**`RegistryDeployFailureRate`** — `sum(rate(registry_deploys_total{outcome="failed"}[5m])) > 0.05` for 5 min. Warning. Fires on per-instance push failures (the `registry.deploy.push_to_instance` span ended in error). This is the *instance-level* counter — a single sick markup-svc instance failing every push trips this alert. The promotion-level alert above trips only when the failure rate is high enough to also fail the promotion.

**`RegistryStateDriftDetected`** — `sum(increase(registry_state_drift_total[5m])) > 0` for 0 min. **Critical**. Fires the moment ANY state drift is observed: a `/rollback` preview hash diverged from the committed hash because a concurrent `/promote` landed between the preview and the commit. This is a should-never-happen invariant. Operators must reconcile via a follow-up rollback before any further promote lands.

### Scrape config

A `model-registry` job in `prometheus.yml` scraping `host.docker.internal:8090/metrics` at 15 s. Same posture as the existing `decision-gateway` job — the registry runs on the host's compose network and Prometheus reaches it via `host.docker.internal`.

### Exemplar storage

Prometheus's exemplar storage is disabled by default; without it exemplars survive only the current scrape and Grafana cannot drill from a histogram bar to a trace. The container command gains `--enable-feature=exemplar-storage`. The dev-default exemplar capacity (100,000 entries) is sufficient at the registry's operator-class throughput (admin-class endpoints, not per-request).

### Runbooks

Each alert ships a runbook under `docs/runbooks/` keyed by alert name. Same shape as the v0.0.3 markup-svc runbooks: what this means → first check → if confirmed → if false-positive → escalation. The Kibana queries cite the lifecycle JSON log events (`registry.audit.write_failed`, `registry.rollback.race_detected`) the registry emits, all of which carry `trace_id` for the Jaeger hop.

## Consequences

### Closed

- Four alerts page operators on the registry failure modes that v0.0.4 introduces. State drift is critical because it represents a should-never-happen invariant; the other three are warning because they catch sustained regressions, not single bad requests.
- The `--enable-feature=exemplar-storage` flag lets Grafana panels drill from a slow `registry_deploy_duration_seconds` bucket to the Jaeger trace via the `trace_id` exemplar — the missing link between the metrics surface and the tracing surface.
- Prometheus scrapes `model-registry:8090/metrics` at 15 s so all of `registry_http_*` + the lifecycle counters land in the existing dashboards.

### Not closed

- AlertManager routing for the registry-severity alerts (lands in ADR-0009 sibling for the registry job). Today the alerts fire into Prometheus's internal state at http://localhost:9090/alerts but do not page anyone outside the UI. The existing alertmanager.yml's `severity: critical` route will pick up `RegistryStateDriftDetected` once the registry job is referenced there.
- Live-stack observability E2E that asserts the alerts actually trip (injects a synthetic failure rate, polls Prometheus's `/api/v1/alerts` endpoint, asserts the right alert moves to `firing`). Parked as the next chunk per the model-registry session plan.
- Per-env partitioning of the upload + deploy alerts. `RegistryPromotionFailureRate` is sum-without-`env`; a future cut once multi-env routing exists can split per-env so an alert page identifies which env is sick.
- Burn-rate / SLO alerts on the lifecycle surface. The first cut uses simple thresholds matching the markup-svc + decision-gateway shape; SLO alerts land once an SLO is declared for the registry.
