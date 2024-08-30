# MarkupChallengerLowAgreement

**Severity:** warning  **Service:** markup-svc  **Expression:** `(sum(rate(markup_challenger_agreement_total{agree="true"}[5m])) / sum(rate(markup_challenger_agreement_total[5m]))) < 0.95 and (sum(increase(markup_challenger_agreement_total[5m])) > 1000)`

## What this means

The challenger and champion disagreed on the markup factor for more than 5% of SAMPLED /decide calls in the last 5 minutes, with at least 1000 sampled comparisons in the window. The sample-size floor prevents the alert from flapping on quiet envs where a handful of disagreements look catastrophic in ratio.

**Sampling caveat (ADR-0033):** when `--shadow-sample-rate < 1.0` the agreement metric reflects only the sampled fraction of decisions. Cross-reference `markup_challenger_sampled_total{sampled="true"}/(true+false)` to see the effective sample rate. At sample=0.1 a 5% sampled disagreement may correspond to a much smaller or much larger fraction of total /decide depending on where the disagreements concentrate. The team's promote-to-champion gate documented in model-registry ADR-0013 assumes high sample rate during calibration; drop the rate only after the gate has cleared once.

Agreement is defined as champion and challenger producing the same `MarkupFactor` (within `factorEpsilon = 1e-9`) OR both declining (`ErrNoMatch`). Disagreement records the absolute delta in `markup_challenger_factor_delta`.

The customer is paying the champion's factor. The challenger never reaches the response body. So a low agreement rate is forensic, not user-visible.

## First check (5 min)

1. **Open the markup-decide-overview dashboard** — panel 8 (agreement ratio) and panel 10 (factor delta percentiles). Look at the trend: did the ratio drop suddenly (suggesting a specific rule change) or gradually (suggesting a slow distribution drift)?
2. **Compare champion + challenger hashes** — `mrctl state <env>` shows both. `mrctl diff <champion> <challenger>` (registry ADR-0011) lists which rules changed. The added or modified rules are the cause.
3. **Sample a disagreement trace** — [saved search `runbook: shadow disagreements`](http://localhost:5601/app/discover#/view/runbook-shadow-disagreements) lists every /decide where champion and challenger produced different factors. The `attrs.champion_factor` + `attrs.challenger_factor` + `attrs.delta` columns make the disagreement size visible at a glance; `attrs.trace_id` links into Jaeger for the matching trace.

## If confirmed

The challenger is producing meaningfully different decisions:

- **Intentional change** — the operator promoted a challenger with documented rule edits expected to produce different factors (e.g. a 5% uplift on a customer tier). Verify the actual disagreement pattern matches the documented intent: if the challenger fires a different rule than expected, the rule may be wrong even though the operator wanted disagreement. Update the team's shadow-deploy notes and proceed.
- **Regression** — the challenger was supposed to be a drop-in replacement and is producing wrong factors. `mrctl reject --env <env> --reason "shadow agreement <95%"`. The auto-rollback case in ADR-0007 catches champion-side regressions during canary; this is the shadow-side equivalent for catching them before promote.
- **Slow rule-distribution drift** — neither side's rules changed but customer-tier distribution shifted (e.g. seasonal spike in enterprise customers). The agreement ratio is decision-distribution-weighted; a sudden tier shift can drop agreement without any rule change. Cross-check against the customer-tier distribution metric and decide whether the shadow needs re-baselining.

## If false-positive

- **Intentional disagreement during exploration** — the operator is using shadow to evaluate a hypothesis ("what if we charged enterprise customers 10% more"). The disagreement is the answer to their question. Acceptable; document the exploration and silence the alert for the duration via AlertManager UI.
- **Threshold too tight for early shadow runs** — the first 24-48 hours of a new challenger run carry calibration noise as the metric warms up. If the team's shadow protocol intentionally starts disagreement-heavy and converges, the 95% threshold may be too tight. The decision to raise the threshold lives with the team; document the new threshold in the shadow-deploy notes.

## Escalation

Warning, not paging. Goal is to investigate within the team's SLA for non-paging alerts. Page only if (a) the agreement ratio drops below 80% (the challenger is wholesale wrong) or (b) the factor delta p99 exceeds 0.5 (the disagreements are large enough that promoting this challenger would shock customers).
