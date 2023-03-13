# 1. Observability Stack for the Pricing Decision Platform

## Status

Proposed — proposes a phased observability stack shipped as a separate `pricing-observability` repo: v0.0.1 wires Filebeat + Elasticsearch + Kibana to ingest the structured JSON stdout that markup-svc, traffic-gen, and decision-gateway already emit (markup-svc plain text gets a follow-up to convert); v0.0.2 adds Prometheus + Grafana for metrics once at least one service ships a `/metrics` endpoint; v0.0.3 adds an OTel Collector + Jaeger (with Elasticsearch as Jaeger's storage backend) for traces once traffic-gen and decision-gateway adopt OTel spans. v0.0.1 is the minimum viable: one operator command brings the stack up next to the existing three-service platform, and Kibana shows logs from all three services filterable by `attrs.correlation_id` so a single request's lifecycle is queryable end-to-end.

## Context

The platform has three services running: markup-svc emits plain-text logs to stdout (and has the OTel span decorator from ADR-0009 + the metrics-port decorator from ADR-0010 as opt-in library code); decision-gateway emits one JSON line per request via `gateway.access` + a `gateway.boot` event; traffic-gen emits `traffic-gen.boot` + `traffic-gen.done` JSON events. Each service ships logs to its own container stdout; nothing today gathers them centrally.

Operators driving the platform under load (the docker-compose stack from decision-gateway/cookbook with `exp:10->500@5m`) cannot today answer:

- "Show me every log line for request `corr-xyz` across all three services."
- "What's the per-route latency at the gateway over the last five minutes?" (this needs Grafana, not just docker logs.)
- "Show me the spans for the slow `/decide` request that returned 5xx at 14:32." (this needs traces, which markup-svc can emit but nobody collects yet.)

Three design questions.

### 1. Logs backend — Elasticsearch + Kibana vs Loki + Grafana

The user explicitly named **Elasticsearch** and **Jaeger** as the backends they want to see. Both options carry honest tradeoffs:

- **Elasticsearch + Kibana** (the user's preference):
  - Pro: operator-familiar, mature, every JSON field becomes a queryable mapping; Kibana's UI excels at structured-field filtering (`attrs.correlation_id : "corr-xyz"`); same ES instance can store Jaeger spans, removing one moving piece for v0.0.3.
  - Con: heavier resource footprint than Loki (a single-node ES container needs ~2 GB RAM in compose); index mapping management is non-trivial as schema evolves; license shifted to SSPL in 2021 (still permissive enough for OSS use but not the OSI-approved Apache 2 Loki is on).
- **Loki + Grafana**:
  - Pro: lightweight (no full-text index on log content; queries via line-grep + label-index); Apache 2 license; pairs naturally with Grafana for unified metrics + logs UIs.
  - Con: Loki's query model (LogQL) is line-oriented and less ergonomic for structured-field queries than Kibana's Lucene; the platform already emits one JSON object per line which is the case where Loki's "logs as labeled streams" model is least leveraged.

**Pick Elasticsearch + Kibana** for v0.0.1 per the user's preference. The JSON-per-line shape the platform emits is exactly what ES's `dynamic_field_mapping` ingests cleanly. Kibana's structured-field filter UI is the right tool for the correlation-ID slice. The bigger resource footprint is a development-machine cost, not a production cost the platform is sized for yet.

### 2. Traces backend — Jaeger vs Grafana Tempo

The user named Jaeger. Either works:

- **Jaeger** (the user's preference):
  - Pro: standalone, has its own UI without needing Grafana, OSS Apache 2, mature; storage backends include in-memory (dev), Cassandra, **Elasticsearch** (reuses the v0.0.1 ES we already ship), Kafka.
  - Con: separate UI from logs (operators switch between Kibana and Jaeger UI) — mitigated by Kibana having a Jaeger integration plugin (out of scope for v0.0.3 first commit; can land as a polish).
- **Tempo**:
  - Pro: designed for object-storage (S3 / GCS / Azure Blob / local FS); pairs natively with Grafana so traces and metrics share one UI.
  - Con: requires Grafana for any UI at all; no standalone trace explorer.

**Pick Jaeger** for v0.0.3 per the user's preference. The Elasticsearch-backend story is operationally elegant: one ES instance stores both logs (Filebeat → ES) and traces (Jaeger → ES). Grafana stays in the picture for v0.0.2 metrics; trace exploration goes through Jaeger UI.

### 3. Phased rollout vs single big-bang

A single commit shipping the full Filebeat + ES + Kibana + Prometheus + Grafana + OTel Collector + Jaeger stack would be one fat ADR + ~10 config files + a 200-line compose. The operator value of "everything at once" is real, but:

- Two of the three services (traffic-gen, decision-gateway) don't emit OTel spans yet, so the trace pipe ingests only markup-svc traces day-one. That's barely better than no traces; the cross-service trace join (the headline value) waits for traffic-gen and decision-gateway ADRs.
- Two of the three services don't ship a `/metrics` endpoint yet. Prometheus would scrape nothing useful for them.
- Logs work today for all three (modulo the markup-svc plain-text gap). One commit shipping logs gets immediate operator value across the whole platform.

**Pick phased.** v0.0.1 = logs only. v0.0.2 = metrics once at least one service has `/metrics` (traffic-gen v0.0.3 is the natural pairing). v0.0.3 = traces once traffic-gen + decision-gateway emit spans. Each phase has a separate ADR (this one + ADR-0002 + ADR-0003) so the design freedom for each phase stays unconstrained by today's commitments.

## Decision

`pricing-observability` is a config-only repo: docker-compose files plus the per-component config files (Filebeat, OTel Collector, Prometheus, Grafana). No Go code; no go.mod; the CI gate is `make ci-local` running `check-adrs` + `validate-compose` (the latter `docker compose -f <file> config -q` to surface YAML / schema / unknown-key errors).

v0.0.1 ships:

- `docker-compose.observability.yaml` adding three services to the existing three-service platform stack: `elasticsearch` (single-node, ~2 GB RAM, in-memory or local-volume storage), `kibana` (UI on host port 5601), `filebeat` (one container reading the Docker daemon's container-log directory via a bind mount, parsing the Docker-format JSON wrapper, extracting the inner application JSON, indexing into ES with the application's `time / level / msg / attrs.*` fields as first-class ES mappings).
- `config/filebeat.yml` configures the Docker input + the ES output + the processor pipeline that extracts the inner JSON message.
- `docs/cookbook/logs-flowing.md` walks operators through `docker compose -f docker-compose.observability.yaml up`, opening Kibana, creating the index pattern, and writing the `attrs.correlation_id : "..."` query that pulls every log line for a single request across all three services.

v0.0.2 and v0.0.3 stay deferred per the phased-rollout decision.

A separate convergence ADR (probably in the markup-svc repo) is needed to flip markup-svc's stdout from plain text to the same `{time, level, msg, attrs}` JSON shape decision-gateway and traffic-gen already use. Filebeat ingests markup-svc's current plain text fine, but Kibana's structured-field filtering only works after the conversion. The cookbook recipe documents this gap and points at the convergence ADR.

## Consequences

### Closed by this ADR

- The "logs flowing" question the user asked has a concrete answer: ship Filebeat + ES + Kibana as v0.0.1 of a new fourth repo; the operator-facing flow is one extra `docker compose -f` command on top of the existing platform stack.
- The phased rollout commits the platform to operator-value-each-phase rather than a fat single-release that ships incomplete pipes for two of the three signal types.
- The Jaeger + Elasticsearch backend choice locks in the user's preference and gives Jaeger a natural storage backend (the ES we already ship) when v0.0.3 lands.

### NOT closed by this ADR

- Metrics pipeline (Prometheus + Grafana). Deferred to v0.0.2 ADR-0002.
- Traces pipeline (OTel Collector + Jaeger). Deferred to v0.0.3 ADR-0003.
- OTel span emission from traffic-gen + decision-gateway. Each is a per-repo ADR landing before v0.0.3 of this repo.
- markup-svc plain-text → JSON log conversion. Separate ADR in the markup-svc repo; pricing-observability v0.0.1 ingests the current plain-text fine but the structured-filter value waits for the conversion.
- Kubernetes manifests (DaemonSet for Filebeat, StatefulSet for ES). v0.0.1 ships docker-compose only; the k8s pattern is its own ADR once a real deployment target appears.
- Authentication on Kibana / Jaeger UIs. v0.0.1 binds to localhost only; operators gate via NetworkPolicy or a reverse-proxy auth layer at deploy time. Same posture markup-svc's `/admin/reload` ADR-0008 takes.
- Retention policies + index lifecycle management. v0.0.1 stores logs indefinitely in the dev volume; a real deployment configures ILM. ADR-defer until a real consumer has a retention requirement.
- Sampling. Default is "ingest every line"; sampling lands when log volume materially exceeds the dev-machine budget.

### Performance impact

The platform's per-request cost is unchanged by this repo — Filebeat tails container stdout out-of-band from the request path. The dev-machine resource footprint of running the observability stack alongside the platform is ~2.5 GB RAM (ES dominates) + ~1 CPU core under steady-state load. Operators running on an 8 GB / 4-core developer laptop will notice; the cookbook recipe documents the budget and suggests `ELASTIC_PASSWORD=` + `xpack.security.enabled=false` for the dev-machine compose (production gates security via the network layer).

A scientific harness for the observability pipeline is out of scope. The pipeline's right-or-wrong is measured by "can the operator find correlation-ID X in Kibana", not by ns/op.

### Validation strategy

- `validate-compose` in `make ci-local`: `docker compose -f docker-compose.observability.yaml config -q` catches YAML / schema / unknown-key errors at every push and PR.
- A manual end-to-end smoke per ADR-0012 of markup-svc (the scientific-harness ADR's spiritual cousin): bring the full platform stack up (decision-gateway compose) + the observability stack up (this repo's compose), drive a request through the gateway with a known correlation ID, and assert the line appears in Kibana within 30s when queried by that ID. Document the smoke in the cookbook recipe.
- A `cookbook/logs-flowing.md` cookbook recipe walks operators through the smoke; the recipe is validated against a real run before commit (the same posture every cookbook recipe in the other three repos uses).
- Filebeat's own `--strict.perms=false` + verbose logging surface its own ingestion errors; the cookbook documents how to read Filebeat logs when ES is unreachable.
