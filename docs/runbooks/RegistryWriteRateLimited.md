# RegistryWriteRateLimited

**Severity:** warning  **Service:** model-registry  **Expression:** `sum(rate(registry_promotions_total{outcome="rate_limited"}[5m])) + sum(rate(registry_rollbacks_total{outcome="rate_limited"}[5m])) > 0.01`

## What this means

ADR-0008's per-env token-bucket limiter (`--write-rate-refill` + `--write-rate-burst`) returned HTTP 429 with `Retry-After` because writes against the env exceeded the configured rate. A single operator hitting 429 once and waiting `Retry-After` does NOT trip this alert (rate < 0.01/s is fine). Sustained ticking means something is retrying without honoring `Retry-After`, or two operators are racing on the same env.

The denied writes never touched the substrate; the data plane is unaffected. The signal is about operator friction and possible thrash.

## First check (5 min)

1. **Identify which surface is being throttled** — split the alert expression in PromQL:
   - `sum(rate(registry_promotions_total{outcome="rate_limited"}[5m]))` — `/promote` throttling
   - `sum(rate(registry_rollbacks_total{outcome="rate_limited"}[5m]))` — `/rollback` throttling
   The split tells you whether the thrash is on promote (uploads going live), rollback (reverting), or both.
2. **Find the env** — `registry_promotions_total{outcome="rate_limited"}` carries an `env` label. The thrashing env is the target of the investigation.
3. **Look at the audit ledger for the env** — `mrctl audit --limit 100` and filter by `target=envs/<env>` (or grep manually). The 429s themselves are NOT recorded in the audit ledger (the handler short-circuits before audit.Record runs), so what you see is the SUCCESSFUL writes around the alert window. The retry pattern is visible in Kibana: `attrs.path:"/promote"` AND `attrs.status:429` shows every retry.

## If confirmed

The investigation is who/what is retrying without backoff:

- **An operator script** — the most common case. Someone wrote a deploy script that retries on 429 immediately rather than honoring `Retry-After`. Locate them via the `operator` field in the access logs around the alert window. Send the standing rule about respecting `Retry-After`.
- **Two operators racing** — both trying to promote different artifacts to the same env. Reconcile via the team channel; one of them needs to wait.
- **CI deploy loop** — a CI pipeline retrying a failed promote in a tight loop. Fix the pipeline to exponential-backoff on 429.
- **The bucket is too tight for normal workflow** — if the team's legitimate operator cadence exceeds the bucket capacity, raise `--write-rate-burst` or shorten `--write-rate-refill`. Document the change in the registry's deployment notes.

## If false-positive

- **Synthetic load test** — a verify-obs harness or scientific run exercising the limiter. The probe in `scripts/verify-registry-observability.sh` intentionally trips the limiter. Confirm via `operator=verify-obs` in the access log.
- **Threshold too tight** — the 0.01/s threshold + 5m window is calibrated to flag thrash, not single-operator backoffs. If the team's workflow legitimately produces sustained 429s without being thrash, raise the threshold.

## Escalation

Warning, not paging. Goal is to investigate within the team's SLA for non-paging alerts. Page only if (a) the throttling is blocking a critical rollback during a customer incident, or (b) the rate climbs past 0.1/s — at that point the limiter is effectively the operational bottleneck and needs urgent retuning or removal for that env.
