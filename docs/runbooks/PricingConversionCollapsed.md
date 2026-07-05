# PricingConversionCollapsed

**Severity:** warning  **Service:** pricing-metrics-aggregator  **Expression:** conversion in the last 15m is < 50% of the 4h moving average AND the 4h average is > 2% (guards cold-start).

## What this means

The proportion `pricing_purchases_last_window / pricing_impressions_last_window` collapsed. Half its 4h baseline is a sharp drop; the 4h baseline must be non-trivial (> 2%) so a fresh-boot 0/0 or a synthetic-empty compose stack doesn't fire spuriously.

The customer is either:
- Not clicking to book at all (rule regression? guardrails vetoing every price? experiment arm winning too hard on price?), or
- Clicking, initiating, then walking (cross-reference `pricing_walkoffs_at_init_last_window`).

This is BUSINESS-IMPACT — customers who would have booked are not booking. Whether the ROOT CAUSE is upstream (search-svc broken?), pricing (rule regression?), or downstream (payment-svc broken?), the alert is doing its job by paging on the SYMPTOM. Diagnose from there.

## First check (5 min)

1. **Open the Pricing Metrics Grafana dashboard.** Compare conversion, impressions, and purchases panels over the last 4h. Did impressions drop (upstream traffic loss)? Did purchases drop but impressions stayed flat (something between rule + purchase failed)?
2. **Cross-reference `MarkupDecideErrorRateHigh`.** If ALSO firing, the pricing decision itself is failing — customers see errors instead of prices. Work that alert first.
3. **Cross-reference `PricingWalkoffAtInitSpike`.** If ALSO firing, customers see prices, click, then walk. Price-shock cohort. This says elasticity moved (a rule promoted a factor that broke the price band).
4. **Cross-reference `Gateway*` alerts.** If active, the customer-visible path has a broken hop.
5. **Cross-reference `MetricsAggregatorRunFailureRate`.** If active, the conversion number itself may be stale, not the customer behavior.
6. **Recent promotions.** `mrctl audit --tail=20` for any rule promotions in the last 4h. If a promotion happened just before the drop, revert first + investigate second (`mrctl rollback`).

## If confirmed

- **Rule regression.** `mrctl rollback --env=<env>` to the previous champion. Confirm conversion recovers within the next 4h evaluation window. Post-mortem on the rule change.
- **Guardrails veto storm.** `markup_guardrails_veto_total` from Prometheus. If elevated, a rule is producing factors outside the guardrail band and every decision is vetoed to fallback. Same remediation as rule regression.
- **Upstream traffic loss.** If `pricing_impressions_last_window` dropped in lock-step, the drop is not a pricing issue — funnel-sim (or real search-svc) isn't rendering pages. Escalate to the upstream service owner.
- **Payment-svc regression.** If `pricing_walkoffs_at_reserve_last_window` spiked simultaneously, customers reach reserve but payment fails. Escalate to funnel-sim owner (or real payment-svc owner if that swap has happened).

## If false-positive

- **Fresh compose stack in dev.** The `> 2%` guard on the 4h baseline should prevent this. If it fires anyway, the guard's `+ 0.001` denominator is masking a real signal — check the raw numbers directly.
- **Experiment arm win.** A treatment arm that legitimately drops conversion (say, testing higher-priced offers to measure price elasticity ON PURPOSE) will fire this. In that case: (a) silence the alert for the duration of the experiment, (b) tag the silence with the experiment_id, (c) document in the experiment plan that the alert is expected.
- **Multi-env aggregator.** The alert groups by `env`. If a dev env with different baseline is scraped alongside prod, both env instances evaluate independently.

## Escalation

Business-impact alert. If unresolved in 15 minutes, page:
1. The **pricing owner** first (revenue-affecting).
2. If rule-related, the **model-registry owner** for a rollback.
3. If upstream, whoever owns the impacted service (funnel-sim owner today; real search-svc / booking-svc owner in the future).
