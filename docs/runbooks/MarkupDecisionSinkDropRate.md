# MarkupDecisionSinkDropRate

**Severity:** warning  **Service:** markup-svc  **Expression:** `sum by (env, reason) (rate(markup_decision_sink_dropped_total[5m])) > 0.01`

The alert payload names the impacted `env` (ADR-0034 env label) and the `reason` (markup-svc ADR-0036). Each reason fires the alert independently so on-call sees a queue-saturation incident separately from an S3-unreachable incident.

## What this means

The ADR-0036 substrate adapter dropped at least one markup.decision.v1 event per 100 seconds over the last 5 minutes. The substrate is the learning-loop's durable feed for downstream Feature Store, ML Training Pipeline, and replay tools. Sustained drops mean those consumers see gaps; a training set built from drop-affected windows is biased toward "decisions that happened when the substrate was healthy."

Two reasons cover the drop space:

- `buffer_full` — the in-memory bounded queue (default 10 000 events) saturated. The producer side could not enqueue; the flush goroutine was not consuming fast enough OR the operator under-sized the queue for the QPS. Most common cause: S3 PUT latency went up.
- `flush_failed` — the bounded exponential-backoff retry (100 ms / 400 ms / 1.6 s) exhausted without a successful PUT. Most common cause: S3 endpoint unreachable, credentials rotated out, bucket-policy regression.

The customer-visible /decide path is unaffected. The sink is non-blocking and a substrate outage never propagates to customer latency.

## First check (5 min)

1. **Open the markup-svc dashboard** — look at `markup_decision_sink_dropped_total{env, reason}` over the last 15 min. A sharp spike points at the trigger time; a gradual climb points at growing QPS outrunning the substrate's flush rate.
2. **Compare against `markup_decision_sink_flushed_total{env}`** — if flushed_total is still ticking, the substrate is alive but slow (saturation). If flushed_total flatlined, the substrate is unreachable.
3. **Open Kibana** — [saved search `runbook: decision sink drops`](http://localhost:5601/app/discover#/view/runbook-decision-sink-drops). The `markup.decision.sink.buffer_full` events fire on burst onset (rate-limited to 1 per 5s window). The `markup.decision.sink.flush_failed` events fire after retry exhaustion. The relative timing tells you whether the queue saturated first (slow S3) or the PUT failed first (unreachable S3).
4. **Check the substrate endpoint** — `docker compose exec minio mc ls local/markup-decisions/ --recursive` (compose) or `aws s3 ls s3://markup-decisions/markup-decision-v1/ --recursive` (real S3). If new batches stopped appearing at a specific timestamp, that's the start of the substrate outage.
5. **Compare against the operator-tunable queue/batch flags** — `markup-svc --decision-sink-queue-size`, `--decision-sink-batch-bytes`, `--decision-sink-batch-window`. If the QPS shifted recently (post-promotion, post-traffic-bump), the queue may be undersized for the new load.

## If confirmed

For `buffer_full` sustained:

- **Substrate is slow but alive.** Raise `--decision-sink-batch-bytes` to flush larger batches less often (one bigger PUT amortises latency), or raise `--decision-sink-queue-size` to ride out the spike. Each is an operator decision tied to acceptable drop rate during a slow-S3 incident.
- **QPS outgrew the substrate sizing.** Recalculate: at N QPS × ~650 B per event × T seconds = expected batch size. Adjust flags accordingly.

For `flush_failed` sustained:

- **S3 endpoint unreachable.** Page the team that owns the endpoint. While unreachable, the sink keeps trying; drops accumulate at the QPS rate. Operators with a hard "no data loss" requirement may want to switch to a disk-spool sink (parked in ADR-0036 as a v2 option).
- **Credentials regression.** Check `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` env or the equivalent `--decision-sink-access-key` / `--decision-sink-secret-key` flags. Rotate if rotated.
- **Bucket policy regression.** Confirm the markup-svc role/user has `s3:PutObject` on the configured bucket and prefix.

## If false-positive

The threshold of `> 0.01 events/s sustained over 5m` is engineered for a multi-thousand-QPS production stream. A genuine false positive would mean the substrate is healthy AND the rate signal is real — this combination is rare. Two cases to consider:

- **Bench / smoke traffic.** A traffic-gen run that drives 10 events/s and the queue is tuned for production scale can produce a brief `buffer_full` spike at the front of the burst before the flush goroutine catches up. The alert's 5m `for:` window swallows that scenario; a single tick at startup is not a real signal.
- **Substrate-side scheduled maintenance.** A planned MinIO / S3 outage with operator awareness should be silenced via the AlertManager `silence` mechanism before the maintenance window. If the silence is missing and the alert fires, the alert is correct; the false-positive is in the operations process.

If neither applies and the substrate is genuinely healthy, check that markup-svc and the alert-evaluation Prometheus instance both see the same env labels — the per-env grouping requires both sides to agree on `env` cardinality.

## Escalation

If the first-check + remediation steps don't resolve in 30 minutes, page the **markup-svc owner** (helmedeiros). Include:

- the dominant `reason` (buffer_full / flush_failed / serialize_failed) from the alert payload,
- `markup_decision_sink_flushed_total{env}` trend over the last hour,
- one or two `markup.decision.sink.flush_failed` log events with the substrate error message,
- current `--decision-sink-batch-bytes` / `--decision-sink-queue-size` flag values,
- substrate-side health: bucket-listing succeeds? credentials still valid?

## Mistakes to avoid

- **Don't disable the sink while incident-triaging.** The metric counter resets only on restart; you lose the "started at" signal.
- **Don't raise the queue without raising the batch budget.** A larger queue with the same flush rate just delays the drop, it doesn't prevent it.
- **Don't treat `flush_failed` as transient.** The bounded retry already swallowed the transient case; if the alert fires, the failure is sustained.

## Why this alert is per-env per-reason

The two reasons distinguish slow-S3 from unreachable-S3 — different remediation paths. The per-env grouping (ADR-0034 follow-through) means a substrate issue affecting only one env doesn't drown on-call in cross-env noise.

## Related runbooks

- [`runbook: decision sink drops`](http://localhost:5601/app/discover#/view/runbook-decision-sink-drops) — Kibana saved search for `markup.decision.sink.*` events.
- `MarkupChallengerEvalTimeoutRate` and `MarkupChallengerLowAgreement` runbooks — shadow-Decider signals that feed the same downstream consumers as the sink stream.
