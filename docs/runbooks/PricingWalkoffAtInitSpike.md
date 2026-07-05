# PricingWalkoffAtInitSpike

**Severity:** info  **Service:** pricing-metrics-aggregator  **Expression:** `pricing_walkoffs_at_init_last_window / pricing_impressions_last_window > 0.20` for 15m.

## What this means

The price-shock cohort — customers who click a priced offer, initiate a booking, then walk away before providing personal information — exceeded 20% of impressions sustained. Interpretation depends on WHICH cohort's rate moved:

- `pricing_walkoffs_at_init_last_window` spike, `pricing_walkoffs_at_reserve_last_window` stable → **price signal**. Customers see the price after commit and don't accept it. Elasticity moved on us; a rule pushed factor higher than the market accepts.
- BOTH spike → **upstream signal**. Either search-svc / funnel-sim / booking-svc is broken (all customers reaching init flow onward see the same downstream issue), or a real payment-svc changed timeouts.

This is **info-severity** — not a page. On-call should look at it, but 20% walk-at-init is elevated, not catastrophic. `PricingConversionCollapsed` is the higher-severity partner alert.

## First check (5 min)

1. **Grafana Pricing Metrics dashboard.** Are walkoff-at-init AND walkoff-at-reserve BOTH spiked, or just init? See the "What this means" split above.
2. **Impressions trend.** Did impressions drop? If yes, denominator is smaller so the ratio spikes without absolute walkoff growth. Not necessarily a real signal.
3. **Recent factor promotions.** `mrctl audit --tail=20`. A promotion that pushed markup factors higher would produce this signal.
4. **Compare against baseline.** `avg_over_time(pricing_walkoffs_at_init_last_window / pricing_impressions_last_window [4h])` — if the recent value is 20% and the baseline is 15%, this is elevated but not extraordinary; if the baseline was 5%, this is a real signal.

## If confirmed

- **Price-shock cohort real.** No immediate action — this is informational. Book a follow-up:
  1. Analytics team runs `notebooks/analytics/30-elasticity-baseline.ipynb` on the last 4h data. If the elasticity coefficient moved (< -1.5 vs baseline -1.0), the market's price sensitivity really changed.
  2. If elasticity is stable but walkoff-at-init still spiked, the customer-visible price band changed. Diff the rules.csv against the last known-good.
- **Upstream signal.** Escalate to the upstream owner. Cross-reference `Gateway*` and `funnel-sim`-side alerts.

## If false-positive

- **Synthetic-load traffic pattern.** `traffic-gen --session=N --session-p-walk-at-init=X` explicitly injects a walkoff rate; if the operator ran a session at `--session-p-walk-at-init=0.25`, this alert will fire correctly. Silence for the duration of the traffic run.
- **Low impressions.** With N < 100 in a 5m window, ratio noise dominates. The alert's `for: 15m` window helps but doesn't eliminate the case fully. Cross-check the absolute impression count.

## Escalation

Info-severity — no page. Slack notification only. If sustained > 4h without a known cause (traffic-gen, expected experiment behavior), open a ticket to the pricing team for deeper investigation.
