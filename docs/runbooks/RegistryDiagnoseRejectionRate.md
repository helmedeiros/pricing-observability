# RegistryDiagnoseRejectionRate

**Severity:** warning  **Service:** model-registry  **Expression:** `sum(rate(registry_promotions_total{outcome="diagnose_rejected"}[5m])) > 0.01`

## What this means

ADR-0006's pre-promote Diagnose gate short-circuited `/promote` with HTTP 422 because markup-svc's `/admin/reload` returned `healthy: false` for the candidate rule set. The counter `registry_promotions_total{outcome="diagnose_rejected"}` ticked. Sustained ticking above 0.01/s over 5 min means more than 3 rejections in the window — not a one-off typo, but a pattern.

The candidate rule set never reached the data plane; the previous champion is still live. No customer impact yet.

## First check (5 min)

1. **Find the rejected promotes** — `mrctl audit --limit 50` and grep for `action=promote` entries close to the alert window. The rejected ones do not carry the standard success annotations; the audit Action is `promote_rejected`.
2. **Identify the artifact + issue kinds** — for each rejected promote, the audit entry carries the `artifact_hash`. `mrctl artifact <hash>` shows who uploaded it. The 422 response body (logged at `registry.promote.rejected` in Kibana) carries `diagnose.errors[].kind` — typically `duplicate_name`, `invalid_factor`, `empty_condition`, `empty_rule_set`. The kind tells you the failure mode.
3. **Find the operator pattern** — if all rejections come from the same `operator` field, it is a single sender (often an automation). If they span multiple operators, it is more likely an upstream rule-authoring pipeline emitting broken rules.

## If confirmed

The work is upstream of the registry: the authoring pipeline is producing rules that fail Diagnose. The registry's job here is forensic and gate-keeping.

- **Identify the upstream pipeline** — the audit operator + artifact metadata (created_by, source_commit_sha) point at which authoring process emitted the bad rule. A CI pipeline, a rule-edit tool, or an operator running `mrctl upload` by hand.
- **Stop the source** — pause the authoring pipeline (or the operator's script) until the pattern is understood. This prevents continued upload of bad rules that pile up in the staged pool and create operator confusion.
- **Diagnose locally** — pull the failing source via `mrctl artifact <hash> source` and re-run `markup-svc Diagnose` (or a Go test that calls `load.Diagnose`) to confirm the issue kinds match the audit log.
- **Fix and document** — the authoring pipeline's check should fire BEFORE upload, not at registry promote time. Diagnose-on-author is the systemic fix.

## If false-positive

- **Test-from-production sweep** — an SRE deliberately exercising the Diagnose gate as part of a verify-obs run. Acceptable but the verify-obs harness should be the source. Check Kibana for the `verify-obs` operator string on the rejected entries.
- **Threshold too tight** — the 0.01/s default was calibrated against the v0.0.4 baseline. If the team's normal authoring cadence exceeds this (e.g., bulk-uploading dozens of rule sets per hour as exploration), raise the threshold and document the new baseline.

## Escalation

Warning, not paging. Goal is to investigate within the team's SLA for non-paging alerts. Page only if (a) the rejections coincide with customer-visible issues (the previous champion is also failing in some way), or (b) the sustained rate keeps climbing past 0.05/s — at that point the authoring pipeline is actively broken.
