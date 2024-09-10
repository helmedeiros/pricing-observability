# MarkupChallengerEvalTimeoutRate

**Severity:** warning  **Service:** markup-svc  **Expression:** `sum by (env) (rate(markup_challenger_eval_timeout_total[5m])) / (sum by (env) (rate(markup_challenger_agreement_total[5m])) + sum by (env) (rate(markup_challenger_eval_timeout_total[5m]))) > 0.01`

The alert payload names the impacted `env` (ADR-0034 in markup-svc adds env labels to all `markup_challenger_*` series, so the alert fires per env independently rather than aggregating across a multi-env scrape).

## What this means

The challenger Decider missed its evaluation deadline (default 10 ms, set via `httpapi.DefaultShadowTimeout`) on more than 1% of SAMPLED /decide calls in the last 5 minutes. Timeouts are not counted as disagreement — they are missing signal — so the agreement metric degrades by however many comparisons silently dropped.

**Sampling caveat (ADR-0033):** when `--shadow-sample-rate < 1.0` the timeout rate is measured over the sampled fraction. The absolute timeout count is lower than at sample=1.0, but the rate-as-fraction is the meaningful signal — a slow challenger times out at the same proportion regardless of sample rate. The `markup_challenger_decide_duration_seconds` histogram (ADR-0033) lets you see the latency distribution directly; a p99 climbing toward 10 ms predicts this alert before it fires.

The customer-visible response path is unaffected: the champion answered synchronously and the challenger ran in a detached goroutine. The alert is about the shadow signal's quality, not the customer's experience.

## First check (5 min)

1. **Confirm the challenger is loaded** — `curl http://markup-svc:8080/admin/diagnose` (or check `mrctl state <env>` for the registry-side challenger hash). If no challenger is loaded, the timeout counter should be flat — investigate why it is ticking.
2. **Open the markup-decide-overview dashboard** — panels 7 and 9 show the timeout rate over time. Look for the start time: did the rate climb after a specific `mrctl promote --role challenger`?
3. **Compare champion + challenger latency** — `histogram_quantile(0.99, sum by(le)(rate(markup_decide_duration_seconds_bucket[5m])))` is the champion path. The challenger ran on the same machine; a champion p99 well under 10 ms means the challenger Decider is the slow one.
4. **Check Jaeger** — `markup.challenger.evaluate` span. The span's duration tells you what the challenger Decider's actual cost looks like. Compare against the deadline.
5. **Open Kibana** — [saved search `runbook: shadow eval timeout`](http://localhost:5601/app/discover#/view/runbook-shadow-eval-timeout) lists every event where the shadow goroutine missed its deadline. The `attrs.trace_id` column links into Jaeger for the matching trace.

## If confirmed

The challenger Decider is too slow for the deadline:

- **Reject the challenger** if the slowness is structural (e.g. a rule set with thousands of rules using a non-indexed engine). `mrctl reject --env <env> --reason "shadow eval timeout > 1%"`. The auto-rollback case in ADR-0007 covers the champion side; this is the shadow-side equivalent: dropped because it cannot run.
- **Tune the deadline** if the slowness is bounded but exceeds the default 10 ms. The deadline is `httpapi.DefaultShadowTimeout`; today it is a constant. A `--shadow-timeout` flag is parked in the ADR-0032 follow-up list. Until that flag ships, operators must rebuild markup-svc with a larger constant.
- **Investigate the engine** if the challenger uses a different adapter than the champion. The indexed engine is roughly an order of magnitude faster than firstmatch on large rule sets; a shadow that switched adapters between champion and challenger is the most common cause of timeout spikes.

## If false-positive

- **Synthetic load spike** — verify-obs or scientific harness running at high QPS pushes the steady-state agreement counter way up; transient timeouts during the spike are amplified relative to the baseline. The alert's 5-min window dampens this, but a sustained synthetic run can still trip it.
- **Champion contention** — a champion under load can starve the goroutine pool, making the challenger appear slow even when its own work is fast. Look at goroutine count and runtime scheduler metrics; if both deciders are starved, the alert is symptom, not cause.

## Escalation

Warning, not paging. Goal is to investigate within the team's SLA for non-paging alerts. Page only if (a) the timeout rate keeps climbing past 5% — at that point the shadow signal is mostly useless and the operator should reject the challenger immediately — or (b) the customer-visible champion p99 also climbs in the same window, suggesting CPU saturation.
