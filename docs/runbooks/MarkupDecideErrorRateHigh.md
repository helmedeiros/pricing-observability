# MarkupDecideErrorRateHigh

**Severity:** warning  **Service:** markup-svc  **Expression:** `sum(rate(markup_decide_total{outcome="error"}[5m])) > 0.1`

## What this means

The markup-svc Decide path is returning `outcome=error` faster than 0.1/s averaged over the last 5 min. /decide answers `500` to the caller (decision-gateway, which then surfaces 500 upstream). Customer-visible: any caller routing through this engine is seeing failures.

## First check (5 min)

1. **Gateway 5xx panel** — open `decision-gateway — overview` in Grafana, check the `5xx rate (5m)` stat. Confirms whether the engine error is reaching the customer or being absorbed.
2. **Recent error logs in Kibana** — [open saved search `runbook: markup-svc 5xx access`](http://localhost:5601/app/discover#/view/runbook-markup-svc-5xx). Look at `attrs.error` + `attrs.engine_adapter` on the most recent entries.
3. **Jaeger** — open Service Performance Monitoring for `markup-svc`, filter `span_kind=SERVER` + `status_code=STATUS_CODE_ERROR`. Click into one to see which span ended in error and what the parent gateway.request span looked like.
4. **Rule set health** — `curl http://markup-svc:8080/admin/diagnose` (or run it via the gateway: `curl http://decision-gateway:8090/admin/diagnose`). If healthy=false, the loaded rules have known issues that may be producing engine errors.

## If confirmed

- **Recently rolled config?** Roll back. Find the last good rule set tag in git (`git log -- compose-fixtures/rules.csv` on decision-gateway) and restore. Then `POST /admin/reload`.
- **Engine adapter pressure** (rule-set has grown, p99 also climbing) — switch to the indexed adapter if not already on it (markup-svc `--adapter=indexed`). Recreate the markup-svc container.
- **Guardrails veto storm** — Kibana `attrs.error:*guardrail*`. A new guardrail with too-tight bounds is rejecting every Decide. Either widen the guardrail or roll it back.
- **Upstream timeout** — gateway pool pressure or backend overload. Check the `decision-gateway — overview` Latency p99 panel; if both error rate and p99 are climbing, the problem is upstream of markup-svc.

## If false-positive

- **Just-rolled deploy** — the 5 min window catches the rollover blip. If error rate dropped below 0.1/s in the last minute, this is post-deploy churn; let it auto-resolve.
- **Synthetic chaos test** — traffic-gen `error` profile is running. Confirm with `docker compose logs traffic-gen --tail 20`.

## Escalation

If first-check + remediation don't resolve in 15 min, page the **markup-svc owner** (helmedeiros). Include the time window, the dominant `attrs.error` string from Kibana, and the rule set tag currently loaded.
