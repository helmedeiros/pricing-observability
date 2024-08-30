# RegistryCanaryAutoRollback

**Severity:** critical  **Service:** model-registry  **Expression:** `sum(increase(registry_canary_decisions_total{decision="rolled_back"}[5m])) > 0`

## What this means

The ADR-0007 canary supervisor polled Prometheus for `markup_decide_total{outcome="error",env=<env>}` over its configured window (`--canary-window`, default 5m), observed the rate exceed `--canary-threshold` (default 0.01 = 1% error rate), and called the registry's own `RollbackChampion` without an operator in the loop. The data plane just reverted to the previous hash.

The failed candidate is still uploaded — it remains addressable by hash — but it is no longer the active champion. The operator who issued the original `/promote` will receive HTTP 200 on the original call (the rollback happens asynchronously after `/promote` returns), so they may not realise the system reverted.

## First check (5 min)

1. **Find the auto-rollback event** — `mrctl history <env>` shows the most recent transitions. The auto-rollback appears with `kind=champion_rolled_back` and `operator=registry-canary`. Note the `at` timestamp and the `from_hash` (the failed candidate) + `to_hash` (the reverted champion).
2. **Open the trace** — the audit entry carries `trace_id`. Paste it into Jaeger to see the canary supervisor's `registry.canary.observe` span and the subsequent `registry.champion.commit_state` for the rollback.
3. **Check markup-svc errors** — open the model-registry Grafana dashboard, find the `markup_decide_total{outcome="error"}` panel for the affected env. The error rate at the time of the rollback is the signal the supervisor acted on.

## If confirmed

The auto-rollback succeeded; the data plane is safe. The work is forensic:

- **Identify the failing rule** — `mrctl artifact <from_hash>` shows the uploaded bundle including any Rules provenance (ADR-0011). `mrctl diff <to_hash> <from_hash>` highlights what changed. The added or modified rules are the candidates.
- **Reproduce locally** — pull the source bytes via `mrctl artifact <from_hash> source` and run the rule against the request fixtures in the markup-svc repo, or against a Diagnose fixture that mirrors the production decide pattern.
- **Fix and re-promote** — once the failing rule is corrected, upload the new hash and re-promote. The canary supervisor will observe again.
- **Audit trail** — record the incident (failed hash, fix commit, replacement hash) in the team channel so future similar failures can cross-reference.

## If false-positive

The supervisor fires on observed error rate; false positives occur when:

- **Existing baseline error rate exceeds the threshold** — markup-svc was already serving 1.5% errors before the new champion landed, the supervisor attributes those errors to the new champion. Mitigation: bump `--canary-threshold` or move to a relative-rate check (parked).
- **Window too short** — `--canary-window=5m` with a low-traffic env can hit `--canary-min-samples` exactly at the edge, where a transient burst dominates the rate. Mitigation: increase the window for low-traffic envs.
- **Upstream blip during the canary window** — markup-svc was OOMing or the Prometheus query timed out partway through. The supervisor treats query errors as inconclusive (no rollback), so this manifests as missing data, not false rollback. If you see false rollbacks attributable to upstream blips, file a bug.

## Escalation

Critical and pages immediately. Page the **model-registry owner** plus the **operator** who issued the original `/promote` (audit `operator` field on the original promote, not the auto-rollback). Goals:

1. Confirm the rollback was correct (the failing rule is real).
2. Get the corrected rule shipped within the team's SLA for rule-set incidents.
3. If the rollback was false-positive, tune the threshold/window and document the calibration in the canary deployment notes.
