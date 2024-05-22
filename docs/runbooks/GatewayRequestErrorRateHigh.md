# GatewayRequestErrorRateHigh

**Severity:** warning  **Service:** decision-gateway  **Expression:** `sum(rate(traces_spanmetrics_calls_total{service_name="decision-gateway",span_kind="SPAN_KIND_SERVER",status_code="STATUS_CODE_ERROR"}[5m])) > 0.1`

## What this means

The decision-gateway server-span error rate exceeded 0.1/s over the last 5 min, measured from the spanmetrics connector (so this is a *trace-derived* signal, not the raw `gateway_requests_total` counter). Customer-visible: pricing requests through the gateway are erroring out. Almost always one of: upstream (markup-svc) is failing, the route table is misconfigured, or the gateway hit a panic/timeout.

## First check (5 min)

1. **Cross-correlate with markup-svc** — open the `MarkupDecideErrorRateHigh` panel. If both are firing together, the root cause is in markup-svc; follow its runbook first.
2. **Gateway access logs** — Kibana: `service:"decision-gateway" AND msg:"gateway.access" AND attrs.status:>=500`. Look at the `attrs.route` distribution. Is it concentrated on one route or spread?
3. **Jaeger** — open SPM for `decision-gateway`, filter `span_kind=SERVER` + `status_code=STATUS_CODE_ERROR`. Click into a failing trace; inspect the `gateway.proxy.upstream` child span for the actual error.
4. **Routes table** — `curl http://decision-gateway:8090/admin/routes`. Confirm the routes resolve to live backends.

## If confirmed

- **Upstream failure** — markup-svc is the proximate cause. Switch to that runbook.
- **Route misconfig** — `/admin/routes` shows a backend URL that no longer exists or has bad DNS. Restore via `POST /admin/routes` with the last-known-good table.
- **Pool exhaustion** — `attrs.error` strings cluster on "context deadline exceeded". Upstream is slow enough that the gateway's `--backend-timeout=5s` is biting. Either widen the timeout (only as a band-aid) or address the upstream slowness.
- **Panic in the gateway** — `docker compose logs decision-gateway --tail 30` shows a Go panic stack. Recreate the container (`up -d --force-recreate decision-gateway`) and capture the stack for the owner.

## If false-positive

- **traffic-gen `error` profile** is intentionally generating malformed requests to exercise the error path. Confirm `docker compose logs traffic-gen --tail 20`.
- **Just-rolled markup-svc** — first 30 s after restart, gateway upstream calls fail. The `for: 5m` window mostly filters this; if the alert clears within ~5 min and stays clear, this was rollover.

## Escalation

If first-check + remediation don't resolve in 15 min, page the **decision-gateway owner** (helmedeiros). Include the dominant `attrs.error` string, the affected `attrs.route` distribution, and the upstream service that the failing `gateway.proxy.upstream` spans point at.
