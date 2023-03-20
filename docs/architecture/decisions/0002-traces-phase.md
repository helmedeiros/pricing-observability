# 2. Traces Phase — OTel Collector + Jaeger with Elasticsearch storage

## Status

Proposed — proposes the v0.0.2 traces phase from ADR-0001: an OTel Collector container ingests OTLP spans from platform services and exports them to Jaeger, which writes to the existing Elasticsearch instance the v0.0.1 logs phase already stands up. Operators access traces via Jaeger UI on host port 16686. v0.0.2 ships even though only markup-svc emits spans today — `markup-svc/ADR-0009` shipped the OTel span decorator and the binary accepts `--otel-enabled`; per-request spans land in Jaeger as soon as the compose sets the flag + OTLP exporter env vars. decision-gateway and traffic-gen span emission stays as separate per-repo ADRs in those repos.

## Context

ADR-0001 named v0.0.2 as the metrics phase and v0.0.3 as the traces phase. The original ordering was metrics-first because none of the three platform services shipped `/metrics` endpoints at the time — Prometheus would scrape nothing useful. But the user's stated near-term goal is **performance investigation of markup-svc and decision-gateway**, and traces are the right tool for that:

- markup-svc already emits per-`Decide` spans via the OTel decorator (ADR-0009 in markup-svc). The exporter side is missing — the compose does not set `--otel-enabled` + `OTEL_EXPORTER_OTLP_ENDPOINT` today, so the spans drop on the floor.
- Per-rule + per-decorator latency is the question operators actually have when they want to find the bottleneck. Metrics give counts and histograms; traces give the per-request waterfall that shows whether the swap.Decider lock pair or the indexed engine's evaluation is dominant at a given QPS.

So the v0.0.x ordering swaps: traces become v0.0.2; metrics moves to v0.0.3 (and lands once at least one platform service ships `/metrics`). The phased rollout commitment from ADR-0001 holds; the order is repriotized for the user's investigation need.

Three design questions.

### 1. OTel Collector receiver / exporter shape

The platform services emit spans via OTel SDK. The Collector receives via OTLP (gRPC and/or HTTP) and exports somewhere. Two candidate exporter targets:

- **OTLP exporter to Jaeger directly**. Jaeger 1.35+ accepts OTLP natively on port 4317 (gRPC) / 4318 (HTTP). Collector exports OTLP → Jaeger; Jaeger writes to ES backend.
- **Jaeger exporter (legacy)**. Collector exports in Jaeger's native format. Less standard; OTLP is the future.

**Pick OTLP-to-Jaeger.** Both supported by jaeger-all-in-one; OTLP is the OTel-canonical wire shape.

Receivers ship `otlp` only — no Zipkin / Jaeger Thrift / Prometheus / Kafka in v0.0.2 because no consumer asks. The Collector config stays minimal.

### 2. Jaeger storage — Elasticsearch backend vs in-memory

Jaeger all-in-one supports several storage backends via `SPAN_STORAGE_TYPE`:

- **`memory`**: spans live in process memory. Pro: zero setup, fast. Con: gone on container restart, no historical analysis.
- **`elasticsearch`**: spans persist in the ES the logs phase already stands up. Pro: traces + logs share one storage backend (operational elegance the ADR-0001 status sentence already hinted at). Con: one more index pattern to manage; jaeger writes JSON docs with its own schema, not the platform's `attrs` shape.
- **`cassandra`**: standard production Jaeger storage. Pro: write-throughput. Con: another container; overkill for v0.0.x dev posture.

**Pick `elasticsearch`.** The single-ES posture from ADR-0001 carries through; operators do one `docker volume rm` to wipe both logs and traces on a fresh start; the existing ES JVM heap covers both workloads at dev volume.

### 3. jaeger-all-in-one vs split collector/query/agent

Jaeger ships as one binary (`jaeger-all-in-one`) with collector + query + agent + UI bundled, or as separate containers. For production deployments where the trace-ingest throughput is the bottleneck, splitting is mandatory. For the v0.0.x dev posture, all-in-one is one container instead of three.

**Pick all-in-one.** Same posture markup-svc takes (one binary, one container) and the same posture the platform's other compose services take. A production-grade split lands when a real consumer's trace volume motivates it.

## Decision

`docker-compose.observability.yaml` gains two services:

```yaml
otel-collector:
  image: otel/opentelemetry-collector-contrib:0.92.0
  command: ["--config=/etc/otel-collector-config.yaml"]
  volumes:
    - ./config/otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro
  ports:
    - "4317:4317"   # OTLP gRPC receiver (platform services send here)
    - "4318:4318"   # OTLP HTTP receiver (alternative for browsers / curl)

jaeger:
  image: jaegertracing/all-in-one:1.53
  depends_on:
    elasticsearch:
      condition: service_healthy
  environment:
    - SPAN_STORAGE_TYPE=elasticsearch
    - ES_SERVER_URLS=http://elasticsearch:9200
    - COLLECTOR_OTLP_ENABLED=true
  ports:
    - "16686:16686"  # Jaeger UI
```

`config/otel-collector-config.yaml` configures one receiver (OTLP gRPC + HTTP), no processors at v0.0.2 (sampling stays at 100% for dev), and one exporter (OTLP to `jaeger:4317`).

`decision-gateway/docker-compose.yaml` gets a follow-up commit (in the decision-gateway repo) wiring the markup-svc service with `--otel-enabled` + `OTEL_SERVICE_NAME=markup-svc` + `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`. Since the decision-gateway repo's compose is the canonical platform stack, the env-var wiring lands there.

`docs/cookbook/traces-flowing.md` walks operators through bringing both stacks up, hitting the gateway with `/decide` requests, and opening Jaeger UI to see per-request waterfalls grouped by `markup.decider.decide` span name.

## Consequences

### Closed by this ADR

- Traces from markup-svc land in Jaeger UI within seconds of the request. Per-rule + per-decorator latency is visible in the waterfall; operators answer "where does this 5xx come from" or "which decorator is dominant at 1000 QPS" without grepping logs.
- Logs (Filebeat → ES) and traces (Collector → Jaeger → ES) share one Elasticsearch instance. One `docker compose -f docker-compose.observability.yaml down -v` wipes both for a fresh start.
- OTLP receiver is open on `:4317` (gRPC) and `:4318` (HTTP) for any future platform service that wants to emit spans. decision-gateway and traffic-gen span emission lands as separate per-repo ADRs; the Collector accepts them as-is when they ship.

### NOT closed by this ADR

- decision-gateway span emission. The gateway-side spans (one per inbound request, with route + duration_ms + correlation_id as span attributes) are a substantial enough piece that they belong in their own ADR inside the decision-gateway repo. The Collector's OTLP receiver is ready to ingest them on day one when that work ships.
- traffic-gen span emission (root spans + traceparent propagation on outbound POSTs). Same pattern; separate ADR in traffic-gen.
- Sampling. v0.0.2 ingests 100% of spans. A `tail_sampling` processor in the Collector config lands when production trace volume motivates it.
- Cross-service correlation joining traces with logs via `attrs.correlation_id`. The current platform's `X-Correlation-ID` header and OTel's `trace_id` / `span_id` are different identifiers. Bridging them is a span-attribute mapping (set `correlation_id` as a span attribute when the gateway middleware ships) — punted to the decision-gateway span ADR.
- Production storage tuning (ES index lifecycle for jaeger-span-* indices, replica counts, refresh interval). v0.0.2 uses Jaeger's defaults; production deployments override via the jaeger ES backend env vars.

### Performance impact

The platform's request path gains:

- **markup-svc** (via the existing OTel decorator): one span per `Decide` call. The decorator wraps the engine and writes one finished span per call. Per ADR-0009 in markup-svc, the cost is ~50–100 ns per span when the exporter is configured. With the OTLP exporter active, the gRPC client batches and sends async — no per-request blocking.
- **OTel Collector**: ingests, batches, exports. The Collector container itself uses ~200 MB RAM at idle, ~500 MB under steady-state load. CPU usage is single-digit-percent per 1k spans/sec on the dev posture.
- **Jaeger all-in-one**: ~300 MB RAM idle, ~1 GB under steady-state load with ES backend.

Aggregate observability budget jumps from ~2.5 GB (v0.0.1) to ~4 GB (v0.0.2) on the dev machine. The cookbook recipe documents this; operators on tighter budgets tune `ES_JAVA_OPTS=-Xms512m -Xmx512m` and skip the OTel Collector when they only need logs.

### Validation strategy

- `validate-compose` passes: `docker compose -f docker-compose.observability.yaml config -q` accepts the two new services and the volume mount for `otel-collector-config.yaml`.
- Manual smoke documented in `docs/cookbook/traces-flowing.md`:
  - Bring up the platform stack (decision-gateway compose) with `--otel-enabled` + OTLP env vars wired on markup-svc.
  - Bring up the observability stack (this repo's compose).
  - Send 5 `/decide` requests through the gateway.
  - Open Jaeger UI at `http://localhost:16686`, search for service `markup-svc`, observe one trace per request with a `markup.decider.decide` span carrying `rule.markup.adapter` / `rule.markup.rule` / `rule.markup.factor` attributes per ADR-0009 in markup-svc.
- The recipe is validated against a real run before commit.
