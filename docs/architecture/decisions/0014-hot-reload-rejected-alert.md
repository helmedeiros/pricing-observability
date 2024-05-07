# 14. Alert on rejected hot-reload (`AdminHotReloadRejected`)

## Status

Accepted — `config/prometheus-rules.yml` gains a sixth alert `AdminHotReloadRejected` in a new `admin-changes` group. Expression: `sum(increase(gateway_requests_total{method="POST",status="400"}[5m])) > 0` for 1 min. Fires when an operator's hot-reload (markup-svc/ADR-0026 Diagnose gate or decision-gateway/ADR-0008 routes-replace) is rejected. Severity `warning`; routes through AlertManager to the webhook sink within the configured `group_wait` (10s).

## Context

markup-svc/ADR-0025 + ADR-0026 made both deploy paths fail-closed for bad rule sets: boot via `--diagnose=on` + `/readyz`, and hot-reload via the Diagnose gate on `POST /admin/reload`. Customers are protected from bad rules either way.

But the operator who POSTed the new rule set doesn't necessarily know the swap was rejected. The 400 response is structured + clear, but operators driving reloads from CI / a deploy pipeline / a curl in a separate terminal might miss it. The platform should page someone fast: the *previous* (working) rules are still serving customers, but the operator almost certainly thinks the *new* config is live. The longer the discrepancy persists, the higher the chance of a confused incident.

A Prometheus alert is the right signal: AlertManager already routes to the webhook sink + the rule shape matches the platform's other operator alerts.

One design question.

### What's the cleanest signal for "/admin POST rejected with 4xx"?

Three candidate metrics:

1. `gateway_requests_total{route="/admin",status="400"}` — most precise (the gateway counts /admin requests by route). Problem: the `route` label is **currently always empty** due to a writer-shadowing bug in the gateway middleware composition. AccessLog's response-writer wrapper "captures" the proxy's `SetMatchedRoute` call without propagating it to the Metrics middleware's wrapper underneath. Tracked as a follow-up fix in decision-gateway.

2. `gateway_requests_total{method="POST",status="400"}` — coarser but works with the current data. Reasoning: in this platform, POST 400 is **almost exclusively** an admin-reload rejection. `/decide` returns 200 on match, 404 on no-match, 5xx on error; `/healthz` / `/readyz` / `/metrics` are GET. So POST 400 is a high-signal proxy for "operator tried to deploy bad config." Possible false positive: a malformed `/decide` request body, but those are rare and operationally interesting in their own right.

3. Log-based alert (Filebeat → ES) on `gateway.access` events with `attrs.path:"/admin/*"` AND `attrs.status:>=400`. Most precise; works regardless of metric-label bugs. But Prometheus doesn't query ES, so this would need a separate Elasticsearch-Watcher rule. Out of scope for the dev posture.

**Pick (2).** Works with the current data; the small noise floor from `/decide` 400s is operationally useful too (they indicate caller bugs). When the route-label bug is fixed, the rule expression can tighten to `route="/admin"` in a one-line follow-up.

## Decision

`config/prometheus-rules.yml`, new group `admin-changes`:

```yaml
- alert: AdminHotReloadRejected
  expr: sum(increase(gateway_requests_total{method="POST",status="400"}[5m])) > 0
  for: 1m
  labels:
    severity: warning
    service: decision-gateway
  annotations:
    summary: "Hot-reload / admin POST rejected — somebody tried to deploy bad config"
    description: |
      {{ $value | printf "%.0f" }} POST 400 response(s) in the last 5m. Most likely
      a markup-svc /admin/reload or /admin/guardrails that failed Diagnose, or a
      decision-gateway /admin/routes with an invalid route table.
      Cross-check in Kibana: msg:"gateway.access" AND attrs.path:"/admin/*" AND attrs.status:>=400
      Re-run GET /admin/diagnose on markup-svc for the issue list.
```

The `for: 1m` requires the condition to hold across two evaluation intervals so single-scrape blips don't page. The `increase[5m] > 0` formulation stays true for ~5 min after any single rejection, so a one-shot rejected reload still pages reliably.

Smoke-tested live: corrupted the rules.csv → POSTed `/admin/reload` 3× → got 400 each time → alert went `pending` → `firing` within `for: 1m` → AlertManager batched within `group_wait: 10s` → webhook delivered to alert-sink → JSON line on stdout. End-to-end < 90 s from rejected reload to operator visibility.

## Consequences

### Closed

- Operators rejected at the Diagnose gate get paged within ~90 s. They no longer wait until customers (or a different alert) surface the discrepancy.
- The alert is high-signal: POST 400 is rare in steady-state operation (the `/decide` 400 path requires a malformed body and is operationally interesting anyway).
- AlertManager-side routing (severity, service labels) matches the rest of the alert set — no new receiver needed.

### Not closed

- The gateway's `route` label is always empty due to the writer-shadowing bug. The alert works because POST 400 is a clean proxy, but the route-label fix would let the expression be more precise. Tracked as a follow-up in decision-gateway.
- The alert doesn't distinguish which `/admin/*` endpoint was hit (reload vs guardrails vs routes). The annotation tells operators all three; they pivot to Kibana to see which.
- `/admin/guardrails` and `/admin/routes` don't yet have Diagnose-style validation gates of their own (markup-svc/ADR-0026's residuals). When they ship the same gate pattern, this alert covers their rejections too without further changes.
- Burn-rate / SLO alerts for admin-rejection error budget. Lands once an SLO commitment exists.
