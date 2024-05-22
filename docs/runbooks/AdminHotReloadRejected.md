# AdminHotReloadRejected

**Severity:** warning  **Service:** decision-gateway  **Expression:** `sum(increase(gateway_requests_total{route="/admin",status=~"[45].."}[5m])) > 0`

## What this means

A POST to a gateway `/admin/*` endpoint was rejected with a 4xx or 5xx in the last 5 min. The operator's intent was clear (somebody posted a new config); the platform refused (Diagnose veto, parse error, validation failure). Customer-visible: nothing yet — the previously-loaded rules / routes / guardrails are still serving — but the operator almost certainly thinks the new config is live. **The gap between "operator thinks deployed" and "platform is still serving the old" is the danger window this alert closes.**

## First check (5 min)

1. **Find the rejected request** — Kibana: `service:"decision-gateway" AND msg:"gateway.access" AND attrs.path:"/admin/*" AND attrs.status:>=400`. Look at `attrs.correlation_id`, `attrs.status`, `attrs.path`.
2. **Read the rejection reason** — same correlation_id in the markup-svc logs: `service:"markup-svc" AND attrs.correlation_id:"<id>"`. The error string says exactly which rule failed Diagnose or which parser stage broke.
3. **Confirm the live config** — `curl http://markup-svc:8080/admin/diagnose` returns the *currently-loaded* (good) rule set's diagnosis. Should be `healthy:true`. If healthy:false, somehow a broken set IS live; escalate.
4. **Identify the operator** — chat / commit-log / change-ticket history. Whoever was deploying needs to know their config did NOT land.

## If confirmed

- **Tell the operator first.** They think their config is live. They are likely already moving on. The window to course-correct is short.
- **If the operator intended the rejected payload** — they need to fix the config and re-post. The rejection body has the issue list. Pair them with the markup-svc owner if they're stuck on a Diagnose error they don't recognize.
- **If the operator intended something else and the payload was wrong** — they sent the wrong file / wrong endpoint. Help them post the correct payload.
- **Routes-replace failure** (path was `/admin/routes`) — `curl http://decision-gateway:8090/admin/routes` to confirm the table did NOT update. Operator re-posts with the corrected table.

## If false-positive

- **CI smoke test** — pipelines that intentionally post a broken config to verify the gate fires. Confirm with the CI run history; these are expected and should clear within one alert window.
- **Penetration / fuzz tooling** — security scanner POSTing garbage to `/admin/*` paths. The 4xx is correct behavior; the alert is doing what it should. Either silence the source or accept the false-positives during scans.

## Escalation

If the rejected payload is from production change-management (not CI / fuzz), and the operator can't be located within 15 min, page the **decision-gateway owner** (helmedeiros) AND the **markup-svc owner** (same). The customer-impact clock starts when the operator deploys something downstream of this on the assumption it landed.
