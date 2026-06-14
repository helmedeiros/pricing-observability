# RegistryDeployFailureRate

**Severity:** warning  **Service:** model-registry  **Expression:** `sum(rate(registry_deploys_total{outcome="failed"}[5m])) > 0.05`

## What this means

The per-instance deploy counter is incrementing `outcome=failed` faster than 1 every 20 s averaged over 5 min. This is the *instance-level* counter — every single instance the rolling deployer tried to push to and got rejected. Distinct from `RegistryPromotionFailureRate`, which fires only when the failure rate is high enough to also fail the promotion.

A single sick markup-svc instance failing every push trips this alert quickly without necessarily tripping the promotion-level one. That's the point: catch a quietly-misbehaving instance before it contaminates a future promotion.

## First check (5 min)

1. **Per-instance breakdown** — Jaeger: filter `service=model-registry` + tag `otel.status_code=ERROR` over the firing window. `registry.deploy.push_to_instance` spans carry `instance.url`. Look for a single URL that dominates the failures.
2. **`/healthz` on the suspect instance** — `curl <instance.url>/healthz`. If non-200, the instance is down.
3. **markup-svc logs for the suspect** — Kibana: `service:"markup-svc" AND host:"<URL>"` over the last 15 min. Look for repeated `admin.reload.failed` or `decide.error` events.
4. **`registry.audit.write_failed`** — Kibana: `msg:"registry.audit.write_failed" AND attrs.action:"promote"` over the firing window. If present, the audit gap may correlate with the deploy failures (operator action recorded as half-done).

## If confirmed

- **Single instance failing** — drain that instance from the deployer's instance list (edit the static-config JSON or replace the instance). Forward-fix: a kubernetes operator would notice and replace; today an operator manually replaces.
- **All instances failing** — the new rule set is broken. This usually also trips `RegistryPromotionFailureRate`; if not, only a fraction of pushes got far enough to fail. Roll back the most recent champion.
- **`/admin/reload` 5xx-ing** — body-based reload is broken in the running markup-svc binary. Check the markup-svc binary version on the failing instance; ADR-0030 reload may not be enabled if it's an old build.

## If false-positive

- **Synthetic chaos / rolling restart** — someone is intentionally bouncing markup-svc instances. Confirm with deploy operators.
- **Partial-deploy backlog** — registered `partial` outcomes are surfacing as `failed` per-instance ticks (the partial-deploy span is one instance that succeeded + one that failed; both record their `outcome` separately). This is the expected shape; if the promotion-level alert is NOT firing the registry's state machine is fine.

## Escalation

If a single instance fails consistently for 30 min, page the **infrastructure owner**. If many instances fail, page **markup-svc + model-registry** owners and consider a stack-wide pause via `mrctl rollback`.
