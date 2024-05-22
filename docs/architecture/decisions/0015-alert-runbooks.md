# 15. Per-alert runbooks via `runbook_url` annotation

## Status

Accepted — every alert in `config/prometheus-rules.yml` carries a `runbook_url` annotation pointing at `docs/runbooks/<alertname>.md` in this repo. Each runbook follows a fixed five-section shape (What this means / First check / If confirmed / If false-positive / Escalation) so an operator paged at 3 am gets the same shape of answer regardless of which alert fired. `scripts/check-runbooks.sh` (wired into `make ci-local`) verifies the link round-trips: every alert's `runbook_url` resolves to a file that exists and every runbook file matches an alert in the rules file.

## Context

The route-label arc (ADR-0009 in decision-gateway, ADR-0014 here, plus the v0.0.17 / v0.0.18 refinements) brought the alert *expressions* up to operational quality — they fire on the right requests and catch both 4xx and 5xx rejections. The next bottleneck moved to the human side: when `AdminHotReloadRejected` lands in a paging channel, the annotation summary says "somebody tried to deploy bad config" and the description points at Kibana + `/admin/diagnose`, but there's no triage script. The on-call has to derive the next move from prose every time. Same for `MarkupDecideP99Slow` ("Investigate adapter, rule-set size, or upstream pressure") — three possibilities, no decision tree.

Two ways to close that gap:

### 1. Inline the runbook in the alert description

Expand `annotations.description` to a multi-paragraph triage tree. Templated values render in-place via the existing `{{ $value }}` substitution.

Pros: zero extra files, ships with the alert.
Cons: AlertManager payloads get unwieldy; the alert-sink + webhook + paging providers all repeat the prose; updating a runbook means re-deploying Prometheus; the description is YAML-quoted markdown, which fights the operator's eyes.

### 2. `runbook_url` annotation pointing at a file in the repo

Standard Prometheus convention. PagerDuty / Slack receivers render it as a clickable link; our `alert-sink` carries it as a JSON field. Runbooks live in `docs/runbooks/<alertname>.md`, version-controlled alongside the alert that points at them, reviewable via PR, renderable in GitHub.

Pros: separation of concerns (alert defines *when*, runbook defines *what to do*); markdown not YAML; PR review on the actual triage tree; updating a runbook is a doc change, not a Prometheus reload.
Cons: one extra file per alert; an alert without a runbook is a possible drift mode. The CI gate closes that.

**Pick `runbook_url`.** Standard convention, separates concerns, the drift risk is gateable.

## Decision

Every alert in `config/prometheus-rules.yml` gains:

```yaml
annotations:
  runbook_url: "https://github.com/helmedeiros/pricing-observability/blob/main/docs/runbooks/<alertname>.md"
  ...
```

The slug matches the alert name exactly (e.g., `MarkupDecideErrorRateHigh.md`).

Each runbook follows a fixed shape:

```markdown
# <AlertName>

**Severity:** <warning|critical>  **Service:** <service-label>  **Expression:** <PromQL>

## What this means
One paragraph: what triggered the alert and what it implies about user-visible impact.

## First check (5 min)
Three to five commands / dashboard links / Kibana queries that confirm or deny.

## If confirmed
Step-by-step remediation. Concrete commands when possible.

## If false-positive
What patterns mean "no real fault" — flapping during deploys, scrape gaps, expected post-reload churn.

## Escalation
Who to page if first-check + remediation don't resolve in 15 min.
```

`scripts/check-runbooks.sh` (added to `make ci-local`) asserts:

1. Every alert has a `runbook_url` annotation whose path resolves to a file under `docs/runbooks/`.
2. Every file under `docs/runbooks/` matches an alert name in the rules file (no orphans).
3. Every runbook has the five required `## ` sections.

## Consequences

### Closed

- 3 am triage starts from a deterministic script, not from re-reading the alert description. The five-section shape gives the on-call a known place to look for "what does this mean" vs "what do I do."
- Updating a runbook is a doc PR, not a Prometheus rules reload. Operators outside the platform team can contribute the "if false-positive" section as they discover patterns.
- Future alerts inherit the convention via the CI gate: a new alert without a runbook breaks `make ci-local`.

### Not closed

- Runbooks are markdown, not executable. An operator still copy-pastes commands. A future ADR could ship the highest-traffic runbooks as `make runbook-<alertname>` targets, but only after the first few runbooks prove out which steps are mechanical.
- The five-section shape is enforced structurally, not semantically. A runbook with empty "If false-positive" content passes the gate. PR review catches that; not the script's job.
- No history of past firings per alert. The runbook is static; "what did we do last time this fired" lives in chat archives + commit log of the runbook itself. Out of scope.

### Performance impact

None. `runbook_url` is a string annotation; AlertManager payloads grow by ~120 bytes per alert.
