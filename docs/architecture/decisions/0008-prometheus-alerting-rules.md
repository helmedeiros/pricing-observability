# 8. Prometheus alerting rules (first cut)

## Status

Accepted — `config/prometheus-rules.yml` ships five alerts wired via `rule_files` in `prometheus.yml`. Two groups: `markup-svc` (decide error rate, p99 latency, scrape-target down) and `platform-spans` (gateway error rate + p99 from the spanmetrics connector). Alerts fire into Prometheus's internal state machine and are visible at http://localhost:9090/alerts. No external notification routing in this release; AlertManager + Slack/email lands when the stack runs alongside something that needs to be paged.

## Context

The observability surface produces RED metrics + per-service histograms + per-Decide counts + per-span call/duration metrics. None of it triggers anything. An operator watching Grafana sees a spike eventually; an operator NOT watching Grafana misses it entirely. Codifying a small alert set closes the "we built it all but can't get paged" loop.

The first cut targets the two services that drive operator decisions: markup-svc (engine error rate and latency) and decision-gateway (server-span error rate and latency from the spanmetrics view). traffic-gen stays outside SPM by design (it's the client; no inbound work).

## Decision

Five alerts. Each carries `severity` (warning or critical) + `service` labels for routing later, and an annotations block with one-line summary + investigation pointer.

**markup-svc group:**

- `MarkupDecideErrorRateHigh` — `sum(rate(markup_decide_total{outcome="error"}[5m])) > 0.1`. Warning. Fires on more than 1 engine error / 10s sustained over 5 min.
- `MarkupDecideP99Slow` — `histogram_quantile(0.99, sum by(le) (rate(markup_decide_duration_seconds_bucket[5m]))) > 0.005`. Warning. Engine p99 > 5 ms for 5 min (typical work is 10–100 µs; 5 ms is a 50–500× regression).
- `MarkupMetricsScrapeDown` — `up{job="markup-svc"} == 0` for 2 min. Critical. Operations alert.

**platform-spans group (from spanmetrics):**

- `GatewayRequestErrorRateHigh` — server-kind error spans rate > 0.1/s for 5 min.
- `GatewayRequestP99Slow` — server-kind p99 latency > 5 ms for 10 min (10-min window because gateway latency is noisier than engine work).

Rule evaluation runs at the default 15 s interval. The `for:` durations are sized so transient spikes (single bad request, brief network blip) do not page; sustained problems do.

The Prometheus config gets `rule_files: [/etc/prometheus/prometheus-rules.yml]` and the compose mounts the new file alongside `prometheus.yml`.

## Consequences

### Closed

- Five baseline alerts fire on the symptoms an operator most often hits: engine errors, engine slowdown, scrape failure, gateway errors, gateway slowdown.
- Alert state visible at http://localhost:9090/alerts; fired alerts cross-referenced with Jaeger traces (filter trace list by service + time window of the firing window) and Kibana logs (filter by `attrs.trace_id:*` and the firing window).
- The labels `severity` + `service` are in place for AlertManager routing when it ships.

### Not closed

- AlertManager + external notification routing (Slack, email, PagerDuty). The current setup evaluates rules but does not send anything outside Prometheus. Lands when this stack runs in an environment where the operator is not watching the UI.
- Burn-rate / SLO alerts. The first cut uses simple thresholds; the next cut once an SLO is declared can layer in 2h/24h burn-rate rules.
- Per-rule alerting (one alert per markup rule by name). Adding `by (rule)` to the error-rate alert would surface which rule is failing; current shape stays service-level for noise control.
- traffic-gen alerts. By design — traffic-gen is the load source, not a service.
- Recording rules for high-cardinality histogram precomputes. Once SLO-driven dashboards land, precomputed rate vectors cut Grafana panel load.
