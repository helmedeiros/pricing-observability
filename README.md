# pricing-observability

Observability stack for the [Pricing Decision Platform](https://github.com/helmedeiros/markup-svc). Configs and docker-compose only — no Go code. Ships in phases per ADR-0001:

- **v0.0.1** — logs: Filebeat + Elasticsearch + Kibana. One operator command on top of the existing three-service platform stack; Kibana queries logs from all three services filterable by `attrs.correlation_id`.
- **v0.0.2** (deferred) — metrics: Prometheus + Grafana, once at least one platform service ships a `/metrics` endpoint.
- **v0.0.3** (deferred) — traces: OTel Collector + Jaeger (with Elasticsearch as Jaeger's storage backend), once traffic-gen and decision-gateway adopt OTel spans.

## Status

Pre-release. The day-one scaffold + ADR-0001 (Proposed) describe the phased rollout and the Elasticsearch / Kibana / Jaeger choices (over Loki / Tempo). The compose file + Filebeat config + cookbook recipe land in subsequent commits of the same release window.

## Companion repos

- [markup-svc](https://github.com/helmedeiros/markup-svc) — the decision engine (currently plain-text logs; conversion to JSON is a parallel ADR).
- [traffic-gen](https://github.com/helmedeiros/traffic-gen) — the load shaper (emits JSON via `internal/jsonlog`).
- [decision-gateway](https://github.com/helmedeiros/decision-gateway) — the HTTP front door (emits JSON via `internal/middleware.AccessLog`).

## Standing rules

Inherited from the three companion repos:

- ADR for every architectural change (Status / Context / Decision / Consequences).
- `make ci-local` passes before every commit (this repo runs `check-adrs` + `validate-compose`).
- Conventional Commits (`type(scope): subject`).
- Annotated tags on every release.

## Building

```sh
make ci-local        # the same checks CI runs
```

No Go code; the gate is YAML validation + ADR hygiene only.

## License

MIT, matching the rest of the Pricing Decision Platform repos.
