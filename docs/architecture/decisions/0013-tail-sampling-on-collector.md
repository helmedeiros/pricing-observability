# 13. Tail sampling on the OTel Collector

## Status

Accepted — the OTel Collector splits the traces pipeline into two: a raw 100% pipeline that feeds the `spanmetrics` connector + the debug exporter, and a sampled pipeline that runs `tail_sampling` before the OTLP exporter to Jaeger. Policies: 100% of spans with `STATUS_CODE_ERROR`, 100% of traces with latency > 10 ms, 10% probabilistic for everything else. `decision_wait: 10s` buffers spans long enough to see most of the trace before deciding. SPM Monitor stays exact (spanmetrics sees every span); Jaeger search shows a tractable subset.

## Context

The 2000 QPS perf run (PLAN.md, "Sustained-load run") confirmed the application stack handles 2000 QPS sustained without errors and with 3-5× CPU headroom. The saturation point was the observability storage tier: at 2000 QPS × ~5 spans/trace = ~10k spans/sec, Elasticsearch returned 429 on Jaeger queries. The Jaeger UI became unusable during the experiment.

Three remediation options were considered:

1. **Scale Elasticsearch up** — more shards, more nodes. Production option; out of scope for a single-node dev compose.
2. **Drop spans at the receiver** — `probabilistic_sampler` processor at the receiver side. Simple but loses error visibility (10% of errors visible at 10% sample rate).
3. **Tail sampling** — buffer spans for a configurable window, then decide per-trace based on policies (always keep errors, always keep slow traces, probabilistic otherwise). Strictly better than head sampling: errors are not undersampled; slow traces (the operator's primary investigation target) are not undersampled.

Pick tail sampling.

One subtlety: spanmetrics-derived metrics (the calls + duration histograms Jaeger Monitor + Grafana panels read) must stay exact for the per-service RED metrics to remain accurate. If tail sampling runs upstream of spanmetrics, the metrics inherit the sampling bias. The Collector lets the same OTLP receiver feed multiple pipelines, so the fix is structural: one pipeline runs spans into spanmetrics with no processor; a second pipeline runs the same spans through tail_sampling before exporting to Jaeger.

## Decision

`config/otel-collector-config.yaml` — two `traces`-shape pipelines share the `otlp` receiver:

```yaml
service:
  pipelines:
    traces:                                 # 100% to spanmetrics + debug
      receivers: [otlp]
      exporters: [spanmetrics, debug]
    traces/sampled:                         # sampled to Jaeger
      receivers: [otlp]
      processors: [tail_sampling]
      exporters: [otlp]
    metrics:
      receivers: [spanmetrics]
      exporters: [prometheus]
```

`processors.tail_sampling`:

- `decision_wait: 10s` — buffer span arrivals for 10 s before deciding what to do with a trace. Long enough that most spans of a trace are already buffered (the platform's deepest trace is the 5-span `traffic.request → ... → markup.engine.evaluate`, which completes in under 5 ms wall-clock; 10 s is generous).
- `num_traces: 100000` — max traces in memory. At 2000 QPS × 10 s decision_wait = 20k traces in-flight, well under the cap.
- `expected_new_traces_per_sec: 5000` — sizing hint for the processor's internal data structures. Picked above the measured 2000 QPS to leave headroom.
- Three policies, evaluated in order:
  - `errors` — `status_code: ERROR`. Keep every error trace.
  - `slow-traces` — `latency.threshold_ms: 10`. 10 ms is above the platform's measured p99 (1.65 ms gateway / 50 µs engine at 2000 QPS); anything past 10 ms is an anomaly worth investigating.
  - `probabilistic-10pct` — 10% of everything else.

The expected post-sampling load on Jaeger ES at sustained 2000 QPS: ~10% × 10k spans/sec = ~1000 spans/sec. Well under the saturation point measured during the perf run.

## Consequences

### Closed

- Jaeger UI stays responsive under sustained 2000 QPS. The trace list shows the 10% probabilistic sample + every error + every slow trace.
- SPM Monitor + Grafana panels reading spanmetrics stay exact. Per-service RED metrics show the full 2000 QPS rate, not the sampled rate.
- Operators investigating slow traces in Jaeger see them whether they fall in the 10% sample or not (the slow-traces policy guarantees retention).
- Error investigation is similarly complete: STATUS_CODE_ERROR spans are always kept.

### Not closed

- Per-service sampling rates. Currently 10% applies platform-wide. A per-service rate (e.g., 100% on markup-svc admin endpoints, 1% on /healthz probes) would need additional `and` policy combinators. Lands when an operator workflow proves it.
- Operator-tunable sampling rate at runtime. The current config is file-driven; a `tail_sampling` policy change requires a Collector restart. The Collector supports config-reload signals but the wiring is out of scope today.
- Adaptive sampling (e.g., scale back to 1% under load, 100% during incidents). Lands as a follow-up if the static-rate baseline proves insufficient.
- Memory cost of the `decision_wait` buffer. At 2000 QPS × 10 s × ~5 spans × ~1 KB/span ≈ ~100 MB. The Collector container's measured idle was ~80 MB; expect ~200 MB under load. Within the dev-stack budget.
- Storage compression. ES still writes ~1k spans/sec; with default mappings each span document is ~2 KB; at 1k spans/sec the daily index grows ~170 MB/day. Production deployments add ILM policies; out of scope here.

### Performance impact

- **Per-span Collector cost**: spans now fan out to two pipelines instead of one. Each pipeline runs in its own goroutine; the receiver hands off via channel. Cost: ~50 ns per span × 2k spans/sec = ~100 µs/sec CPU on the Collector. Negligible.
- **Per-trace tail_sampling cost**: the 10 s buffer + policy evaluation. The processor batches by trace; per-trace decision is ~1 µs. At 2000 traces/sec = ~2 ms/sec CPU. Negligible.
- **Memory**: ~200 MB resident at sustained load, up from ~80 MB.
- **Jaeger ES write load**: drops from ~10k spans/sec to ~1k spans/sec. The 429 saturation observed in the perf run goes away.
