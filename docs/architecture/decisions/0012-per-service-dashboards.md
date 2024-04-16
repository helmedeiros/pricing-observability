# 12. Per-service Grafana starter dashboards (decision-gateway + traffic-gen)

## Status

Accepted — `config/dashboards/decision-gateway-overview.json` and `config/dashboards/traffic-gen-overview.json` ship alongside the existing `markup-decide-overview.json`. Operators land on three dashboards in the "Pricing Platform" folder; each surfaces the per-service Prometheus signal added in pricing-observability v0.0.11 (per-service scrape) without requiring PromQL fluency.

## Context

ADR-0011 wired per-service scrapes targeting decision-gateway's `gateway_requests_total` + `gateway_request_duration_seconds` (per ADR-0007 in that repo) and traffic-gen's `trafficgen_requests_total` + `trafficgen_request_duration_seconds` + `trafficgen_target_qps` / `trafficgen_achieved_qps` gauges (per ADR-0006 in that repo). The metrics are queryable in Prometheus but live in PromQL only — operators have to remember the queries. Two starter dashboards close that loop with the same five-panel template the markup-decide-overview dashboard uses.

## Decision

**`decision-gateway-overview`** — five panels:

- RPS by route (timeseries, `sum by(route)`).
- RPS by status (timeseries, `sum by(status)`).
- p50 / p95 / p99 latency (timeseries, histogram_quantile).
- 5xx rate (stat panel, green/yellow/red thresholds at 0.1%/1%).
- 4xx rate (stat panel).

**`traffic-gen-overview`** — four panels:

- Target vs achieved QPS (timeseries, both gauges on one chart).
- Rate by outcome (timeseries, `sum by(outcome)`).
- Outbound latency p50/p95/p99.
- Generator deficit (stat panel showing `target - achieved`, green/yellow/red thresholds at 5/50 reqps).

Both dashboards live under the same Grafana folder (`Pricing Platform`) the markup-decide dashboard does, picked up by the existing `grafana-dashboards.yaml` provider config (`updateIntervalSeconds: 30`).

## Consequences

### Closed

- Operators open Grafana → Pricing Platform folder → see three dashboards: markup-decide, decision-gateway, traffic-gen.
- The traffic-gen target-vs-achieved chart surfaces "the generator is falling behind its profile" live — the single most operationally useful artifact for load investigations.
- The decision-gateway per-route RPS chart isolates which prefixes are bearing traffic without filtering trace lists or grepping access logs.

### Not closed

- A platform-wide dashboard combining all three services on one row each. Lands when an operator's workflow proves it's needed.
- Per-service SLO panels with burn-rate gauges. Blocked on SLO declaration (ADR-deferred until an SLO exists).
- Cross-signal panels (e.g., trace count alongside metrics rate). Possible via the Jaeger datasource; out of scope here.
- Linking dashboards via Grafana data links (click a gateway row to jump to the matching service-tagged log filter in Discover). Possible via Grafana's "Data links" panel option; a future ADR adds it when the operator's investigation pattern proves it.
