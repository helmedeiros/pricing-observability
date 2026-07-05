# 22. Pricing Monitoring & Alerting for the metrics aggregator surface

## Status

Accepted — the Pricing Monitoring & Alerting container from the C4 diagram lands as a Prometheus scrape target + four AlertManager rules + one Grafana dashboard consuming the pricing-metrics-aggregator's gauges. Ships alongside pricing-metrics-aggregator ADR-0002 (labeled gauges) so the arm and segment views in Grafana can consume the `_labeled` surface as soon as the operator opts labels in.

## Context

pricing-metrics-aggregator ADR-0001 landed the always-on Prometheus surface for the joined signal between markup-decisions and funnel-events (impressions, purchases, walkoffs, GMV, conversion rate). ADR-0002 extended it with per-arm and per-segment `_labeled` gauges under a bounded cardinality cap.

The remaining container in the Pricing Observability boundary — Pricing Monitoring & Alerting — has infrastructure (Prometheus, AlertManager, Grafana, existing rules for markup-svc / decision-gateway / model-registry) but no rules or panels that consume the aggregator's gauges. Grafana users querying `pricing_conversion_rate_last_window` see the metric because Prometheus scrapes it, but there's no curated dashboard and no alert on business-impact anomalies (conversion collapse, walkoff spike). Alerting on the aggregator's own health (run failures, staleness) is also missing — a broken aggregator today produces a silent staleness across every downstream consumer.

This ADR closes both gaps.

## Decision

### Scrape target

`config/prometheus.yml` gains a scrape job for `pricing-metrics-aggregator` at `host.docker.internal:8082` — matches the aggregator's compose port publish and the host.docker.internal bridge convention used for markup-svc, decision-gateway, model-registry.

### AlertManager rules — new group `pricing-metrics-aggregator`

Four rules land in `config/prometheus-rules.yml`. Two are aggregator-health (the observability surface), two are business-impact (the pricing surface).

| Alert | Severity | Signal |
|---|---|---|
| `MetricsAggregatorRunFailureRate` | warning | `sum by (env) (rate(pricing_metrics_aggregator_runs_total{outcome="error"}[15m])) > 0` for 10m — one or more failed runs sustained. Gauges retain last-known-good but no longer reflect current bucket state. |
| `MetricsAggregatorStale` | warning | `runs_total` counter has not advanced for 15m. Either the loop is stuck or the scrape target is down. |
| `PricingConversionCollapsed` | warning | Last-15m conversion is < 50% of the 4h moving average AND the 4h average is > 2%. The `> 2%` guard prevents cold-start / synthetic-empty compose stacks from firing spuriously. Business-impact. |
| `PricingWalkoffAtInitSpike` | info | `pricing_walkoffs_at_init_last_window / pricing_impressions_last_window > 0.20` for 15m. The price-shock cohort. Non-paging; Slack-only. |

Each ships a 5-section runbook (What this means / First check / If confirmed / If false-positive / Escalation) at `docs/runbooks/<AlertName>.md` per ADR-0015 convention. Each runbook links to Grafana panels for cross-reference and lists the co-firing alerts to consult first.

### Grafana dashboard

New dashboard `config/dashboards/pricing-metrics-overview.json` with 12 panels in three tiers:

- **Top row (stats)**: current-window conversion rate, GMV, impressions, purchases as single-value stat cards.
- **Middle rows (time series, env-total)**: impressions vs purchases, walkoff phases side-by-side, conversion rate, GMV.
- **Labeled surface panels**: per-arm conversion (needs `--include-labels=variant`), per-segment impressions (needs `--include-labels=customer_tier,country`). Panel descriptions document the dependency so an operator seeing empty panels knows what to enable.
- **Meta-observability**: aggregation run rate by outcome, run-duration percentiles (p50 / p95 / p99).

### The label surface's Grafana story

The labeled panels use `label!=""` filters (e.g. `pricing_conversion_rate_last_window_labeled{variant!=""}`) so:

- When the operator has NOT opted labels in, the metric doesn't exist → panel shows "no data" without confusion.
- When the operator HAS opted variant in but customer_tier + country are not, the customer_tier panel silently filters to nothing while the variant panel shows real series — self-documenting.

### Alert rule design principles

- **Cold-start guard** on business-impact rules. `PricingConversionCollapsed` requires the 4h baseline to be > 2% because a stack with an empty MinIO bucket produces conversion=0 which "collapses vs" any past positive value. This is a real ADR call — the alternative (fire the alert on cold-start) trained operators to ignore it.
- **`for:` clauses on every rule**. Nothing fires on a single tick. Every alert requires 10-15 minutes of sustained state. Reduces noise; slightly delays real fires; accepted trade-off.
- **Business-impact alerts cross-reference their operational cousins**. `PricingConversionCollapsed`'s runbook says "check MarkupDecideErrorRateHigh first — if firing, work that alert." Prevents on-call from investigating the SYMPTOM when a partner alert already identifies the ROOT cause.

## Consequences

### Positive
- **The Pricing Monitoring & Alerting C4 container is now materially wired.** Prometheus scrapes, AlertManager fires, Grafana renders, runbooks route on-call. Every plane of the observability chain runs end-to-end for the aggregator's signals.
- **Aggregator health is observable.** Two of the four alerts are aggregator-self alerts (failure rate + staleness). A broken aggregator no longer silently masks the pricing signal.
- **Business anomalies are pageable.** Conversion collapse — the highest-impact signal a pricing platform can produce — has a rule + runbook + Grafana cross-reference.
- **Panel authors have a starting dashboard.** `pricing-metrics-overview.json` is a curated view; operators wanting per-arm or per-country deep-dives clone and customize.

### Negative
- **Four rules add to the on-call cognitive load.** Mitigated by the runbook's cross-reference sections and the info-severity for the walkoff signal (Slack-only, no page).
- **`PricingConversionCollapsed` is a proportion-of-proportion alert.** These can be tricky to reason about mid-incident. The runbook explicitly walks through the arithmetic + cross-refs.
- **The labeled panels are dependent on operator flag config.** An operator running the aggregator without `--include-labels` sees empty labeled panels. Documented in panel descriptions, but a fresh eye may still be confused. Trigger for a follow-on: a panel-help annotation embedded in Grafana itself.

### Not closed
- **Kibana saved searches for the aggregator's structured logs**. `pricing-metrics-aggregator.run_error` events are indexed but no saved search links directly from the runbooks. Follow the ADR-0016 convention when the aggregator's log volume grows enough to warrant it.
- **Cardinality-limit alert.** If the operator opts labels in and the `_other_` bucket carries >20% of the impressions, real signal is being folded into `_other_`. A `pricing_metrics_aggregator_other_share` gauge + an alert on it would surface that.
- **Multi-env aggregation.** The rules group by `env`. If a multi-env deployment scrapes multiple aggregators, alerts fire per-env correctly. Silences per env are the operator's responsibility.
- **Long-window comparisons.** The `4h` baseline in `PricingConversionCollapsed` is a compromise (long enough to smooth noise, short enough to catch same-day drift). A `24h` or `7d` variant may be added when the platform runs long enough to accumulate the history.

## References
- pricing-metrics-aggregator ADR-0001 — role framing; this ADR is the "when this repo is ready to be a first-class dashboard + on-call surface" trigger it named.
- pricing-metrics-aggregator ADR-0002 — labeled surface Grafana panels 9 + 10 consume.
- pricing-observability ADR-0008 — Prometheus alerting rules (first cut) — the pattern this ADR follows.
- pricing-observability ADR-0015 — per-alert runbooks via `runbook_url` annotation.
- pricing-observability ADR-0016 — runbook saved searches in Kibana (parked here as a follow-on).
