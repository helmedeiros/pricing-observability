# RegistryStateDriftDetected

**Severity:** critical  **Service:** model-registry  **Expression:** `sum(increase(registry_state_drift_total[5m])) > 0`

## What this means

A `/rollback` call read its preview hash (the champion immediately before the current one) at time T0, started its rolling push at T1, then committed the state at T2 — and the committed hash diverged from the preview. A concurrent `/promote` landed between T0 and T2, advancing the champion pointer between the preview and the commit.

The data plane is currently serving `committed_hash`. The operator who issued the rollback thinks it is serving `preview_hash`. They are looking at the wrong rule set.

This is a critical / should-never-happen invariant under normal operation. fsstate's `SetMaxOpenConns(1)` serialises writes at the SQLite level; the only way drift happens is if two operators issue a `/promote` and a `/rollback` in the same window without coordination.

## First check (5 min)

1. **Find the drifted rollback** — Kibana: `msg:"registry.rollback.race_detected"` over the last 15 min. The event carries `preview_hash`, `committed_hash`, `operator`, and `trace_id`. **Open the trace_id in Jaeger immediately**.
2. **Identify the racing promote** — Kibana for the same time window: `msg:"registry.access" AND attrs.path:"/promote"`. Find the `/promote` whose trace started before the rollback's trace ended.
3. **What is currently serving** — `curl http://decision-gateway:8090/admin/diagnose` to see the active rule set in markup-svc. Cross-reference against `committed_hash` from step 1.

## If confirmed

This is operator coordination failure, not a registry bug, but the registry is the only place this can be reconciled.

- **Decide which hash should be live**. Talk to the operator who issued each call. If the rollback's intent was to revert a known-bad champion, the right state is `preview_hash`. If the promote's intent was to advance to a new known-good champion, the right state is `committed_hash`.
- **Reconcile** — if the desired hash is `preview_hash` (the rollback's intent), re-issue the rollback: `mrctl rollback --env <env> --reason "RegistryStateDriftDetected reconciliation"`. Then verify with `mrctl state <env>` and a fresh `/admin/diagnose`.
- **Audit trail** — record the reconciliation in the team channel with the trace_ids of both the racing promote and the racing rollback so the on-call can audit later.

## If false-positive

There is no false-positive case for this alert. It fires only when fsstate's race-detection code path runs, which only happens when the preview/commit hashes actually diverge.

## Escalation

This is a critical alert and pages immediately. Page **model-registry owner** + the **on-call operators** who issued the two racing calls. The escalation has two goals:
1. Reconcile the divergence within 30 min (data plane is serving an unintended rule set).
2. Identify whether the team needs a coordination layer (a registry-side lock per env, a chat-driven mutex, or an ADR-0007-class auth gate that serializes operator actions).
