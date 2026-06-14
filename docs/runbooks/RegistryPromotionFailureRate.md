# RegistryPromotionFailureRate

**Severity:** warning  **Service:** model-registry  **Expression:** `sum(rate(registry_promotions_total{outcome=~"failed|partial"}[5m])) > 0.02`

## What this means

model-registry's `/promote` endpoint is hitting `failed` (all instances rejected the rolling push) or `partial` (some did but the state committed per ADR-0005) faster than 1 promotion every 50 s sustained over 5 min. Sustained partial is the same operator action as failed: a sick markup-svc instance needs to be checked.

## First check (5 min)

1. **Which outcome is dominating** — `sum by (outcome) (rate(registry_promotions_total{outcome=~"failed|partial"}[5m]))`. `failed` means every instance rejected; `partial` means some did and the env-state still moved.
2. **Per-env breakdown** — `sum by (env, outcome) (rate(registry_promotions_total{outcome=~"failed|partial"}[5m]))`. If only one env is firing, the deployer's instance list for that env is sick. If all envs are firing, the new rule set itself is unhealthy.
3. **Deploy span errors** — Jaeger: search service=`model-registry` with tag `otel.status_code=ERROR`. The `registry.deploy.push_to_instance` span carries `instance.url` so you see which markup-svc instance rejected. `registry.deploy.readyz` carries `readyz.polls` so you see whether the push reached but the readiness probe timed out.
4. **markup-svc end** — for each failing instance URL, `curl http://<url>/healthz` and `curl http://<url>/admin/diagnose`. If `/admin/diagnose` says `healthy: false`, the new rule set was rejected by markup-svc's diagnose layer.

## If confirmed

- **All instances reject (`failed` dominates)** — the new rule set is broken. Roll back via `mrctl rollback --env <env> --reason "RegistryPromotionFailureRate"`. The previous champion is restored.
- **One instance rejects (`partial` dominates)** — the new rule set is fine; one markup-svc is unhealthy. Check the instance's logs in Kibana: `service:"markup-svc" AND host:"<failing instance>"`. Replace or restart the instance.
- **Readyz timeout** — the `registry.deploy.readyz` span's `readyz.polls` attribute shows whether the probe ever got a 200. If polls > 50 the instance accepted the reload but is taking too long to ready. Check rule-set size; the indexed adapter may be needed.

## If false-positive

- **Synthetic chaos test** — someone is intentionally exercising the rejection path with a known-bad rule set.
- **Deploy-time bounce** — a single bad bounce of one markup-svc instance during a routine deploy. Acceptable if `registry_promotions_total{outcome=ok}` resumes after a minute.

## Escalation

If first-check + remediation don't resolve in 15 min, page **model-registry + markup-svc** owners. Include the env, the dominant outcome, the failing instance URL(s), and a sample trace_id from a failed promote.
