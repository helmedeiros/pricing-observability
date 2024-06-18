# 18. Sample 100% of `/admin*` traces

## Status

Accepted — `config/otel-collector-config.yaml` `tail_sampling.policies` gains an `admin-paths` policy (`type: string_attribute`, `key: http.url`, `values: [".*/admin.*"]`, `enabled_regex_matching: true`) sitting before the existing `probabilistic-10pct` fallback. Any trace where at least one span tags `http.url` containing `/admin` is kept by the sampled pipeline and persisted to Elasticsearch. Errors + slow traces (>10ms) policies remain unchanged.

## Context

ADR-0007 in traffic-gen wired an admin-path background mix so the gateway dashboard's per-route panels stop rendering NaN. Each admin POST is observed via the same OTel-instrumented HTTP client as the `/decide` poster, so trace context propagation is identical: the InstrumentedTransport opens a `traffic.request` span and injects W3C `traceparent`. Live verification (audit performed during platform-trace work):

| Path | URL | Services in trace | Span count |
|---|---|---|---|
| /decide | `http://decision-gateway:8090/decide` | traffic-gen, decision-gateway, markup-svc | 5 |
| /admin/reload | `http://decision-gateway:8090/admin/reload` | traffic-gen, decision-gateway | 3 |

Propagation worked — `gateway.request` and `gateway.proxy.upstream` spans landed on the same trace as the originating `traffic.request`. But two findings emerged:

1. **markup-svc admin handlers don't open OTel spans.** The trace ends at the gateway's `gateway.proxy.upstream` because markup-svc's `/admin/reload` handler is uninstrumented. Tracked separately as a markup-svc roadmap item; out of scope for this ADR.

2. **Admin traces were almost never sampled.** Initial Jaeger queries (limit=200, ordered by recent first) returned 0 admin traces in a 5-min window. Cause: admin POSTs are fast (sub-millisecond on a clean reload) and non-error, so they fall into the existing `probabilistic-10pct` policy. At 2 admin POSTs/min, the expected yield is ~12 admin traces/hour — but they get drowned by the /decide traffic (~500 QPS = 150k traces / 5 min) in the default Jaeger query ordering. Even direct tag-search struggled to surface enough samples to make the SPM view of `/admin` traffic meaningful.

This ADR addresses (2). (1) is for markup-svc.

### Approach

The OTel Collector contrib's `tail_sampling` processor supports a `string_attribute` policy that matches on span attribute key + value with optional regex. Adding a policy before `probabilistic-10pct` guarantees admin-bearing traces are kept regardless of latency or status.

The regex `.*/admin.*` matches any URL containing `/admin` — covers `/admin/reload`, `/admin/diagnose`, `/admin/routes`, `/admin/guardrails`. Substring match would also work; regex form is uniform with how future operator URLs might be expressed.

Considered and rejected: separate policy per endpoint (`/admin/reload`, `/admin/routes`, etc.). Over-specified — the operator-visibility goal is "all admin-path traces always reach Jaeger," and adding new admin endpoints would silently bypass the policy until someone remembered to update the list.

## Decision

`config/otel-collector-config.yaml`:

```yaml
processors:
  tail_sampling:
    decision_wait: 10s
    num_traces: 100000
    expected_new_traces_per_sec: 5000
    policies:
      - name: errors
        type: status_code
        status_code: { status_codes: [ERROR] }
      - name: slow-traces
        type: latency
        latency: { threshold_ms: 10 }
      - name: admin-paths
        type: string_attribute
        string_attribute:
          key: http.url
          values: [".*/admin.*"]
          enabled_regex_matching: true
      - name: probabilistic-10pct
        type: probabilistic
        probabilistic: { sampling_percentage: 10 }
```

Policy ordering matters operationally (every policy gets evaluated; trace is kept if any matches), but placing `admin-paths` before `probabilistic-10pct` keeps the config readable as a triage sequence (errors → slow → admin → fallback).

## Consequences

### Closed

- Admin-path traces are 100% sampled. Operators investigating `/admin/reload` or `/admin/diagnose` behaviour can find traces without retrying queries or extending the window. Verified live: a 5-min window post-policy returned 31 admin traces via tag search.
- `AdminHotReloadRejected` runbook's Jaeger deep-link (`http://localhost:16686/search?service=decision-gateway&tags={"otel.status_code":"ERROR"}`) now reliably shows admin failures even on the rare-rejection path, because the trace is always kept.
- Future admin endpoints (`/admin/guardrails`, `/admin/routes`, anything matching `*/admin*`) inherit the policy without a config change.

### Not closed

- markup-svc admin handlers (`/admin/reload`, `/admin/diagnose`, `/admin/guardrails`) don't open OTel spans, so the markup-svc service is missing from admin trace waterfalls. The trace ends at the gateway's `gateway.proxy.upstream` child span. Closing this requires markup-svc work (`internal/httpapi` to wrap admin handlers with a tracer span the same way `/decide` does). Tracked as a markup-svc roadmap item.
- Storage cost. Admin traces are rare (~2/min in steady state), so the additional load on Elasticsearch is well under 1% of the sampled-pipeline volume. If a future workflow drives admin traffic to >100 QPS, the policy can switch to a probabilistic sub-sample. No action needed today.
- Operator-emitted admin POSTs (a human running `curl /admin/reload` via kubectl exec, not the synthetic traffic-gen path) only land in Jaeger if the client either propagates trace-context or opens a span. Out of scope; operators wanting to trace their own admin actions can set `traceparent` manually or use the OTel HTTP wrapper.

### Performance impact

- One extra `string_attribute` policy evaluation per buffered trace. The tail_sampling processor evaluates all policies in sequence; this adds a regex match against `http.url` per trace. At ~5000 traces/s expected (config setting), this is sub-microsecond per trace.
- Memory: tail_sampling buffer (`num_traces: 100000`) is unchanged; admin traces are short-lived and small, so the steady-state buffer occupancy stays similar.
