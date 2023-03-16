# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.1] - 2023-03-16

First public release. pricing-observability ships the v0.0.1 logs pipeline for the Pricing Decision Platform: Filebeat + Elasticsearch + Kibana running alongside the existing three-service platform stack, with every platform service's stdout JSON queryable in Kibana by `attrs.correlation_id`. Config-only repo — no Go code, no binary, no Dockerfile to publish. ADR-0001 (Accepted) covers the phased rollout and the Elasticsearch + Kibana vs Loki + Grafana / Jaeger vs Tempo design decisions.

### Added

- `docker-compose.observability.yaml` at the repo root: three services (Elasticsearch 8.11.4 single-node, Kibana 8.11.4 on host port 5601, Filebeat 8.11.4 reading `/var/run/docker.sock` + `/var/lib/docker/containers`). Designed to run alongside `decision-gateway/docker-compose.yaml`; Filebeat reaches the platform via the Docker daemon so the two compose stacks need not share a Docker network. Dev posture: `xpack.security.enabled=false` so curl + Kibana + Filebeat connect without TLS cert provisioning; production gates security at the network layer (same posture markup-svc's `/admin/reload` ADR-0008 takes).
- `config/filebeat.yml`: Docker autodiscover provider tails platform container logs via image-prefix filter on `ghcr.io/helmedeiros/{markup-svc,decision-gateway,traffic-gen}`; `decode_json_fields` processor elevates the application JSON line into top-level Elasticsearch fields (so Kibana queries on `attrs.correlation_id` etc. work without a custom parser); `add_error_key` keeps markup-svc plain-text lines ingestable until the convergence ADR ships. Output is a daily index `platform-logs-YYYY.MM.DD` with 1 shard / 0 replicas (single-node dev posture).
- `docs/cookbook/logs-flowing.md`: operator recipe walking through bringing both stacks up, creating the Kibana index pattern `platform-logs-*`, firing a request with a known `X-Correlation-ID` through the gateway, and watching the line appear in Discover filtered by `attrs.correlation_id`. The ASCII pipeline diagram + "What to check after" curl probes + "Mistakes to avoid" list + the explicit ~2.5 GB RAM resource budget make the recipe self-contained.
- `Makefile` `check-adrs` + `validate-compose` targets and a `make ci-local` that runs both. The compose validator (`docker compose -f <file> config -q`) gracefully skips when docker is not on PATH so minimal CI runners stay usable.
- CI workflow with `tags: ['v*']` from day one (the markup-svc v0.1.2 lesson). No image-publish job because the repo ships configs, not a binary; the upstream `docker.elastic.co/` images are referenced verbatim.
- ADR-0001 (Accepted): observability stack design. Picks Elasticsearch + Kibana over Loki + Grafana for logs (per user preference; the line-JSON shape is what ES's `dynamic_field_mapping` ingests cleanly and Kibana's structured-field filter UI is the right operator tool). Picks Jaeger over Tempo for traces (per user preference; the v0.0.3 Jaeger backend can store spans in the same Elasticsearch that v0.0.1 stands up for logs). Phased rollout (v0.0.1 logs / v0.0.2 metrics / v0.0.3 traces) so each phase ships operator value without waiting for the others' per-repo prerequisites (traffic-gen `/metrics` for v0.0.2; OTel span emission on traffic-gen + decision-gateway for v0.0.3).

### Deferred to v0.0.2

- Prometheus + Grafana for metrics. Blocks on at least one platform service shipping a `/metrics` endpoint; traffic-gen's deferred `/metrics` endpoint is the natural pairing.

### Deferred to v0.0.3

- OTel Collector + Jaeger (with Elasticsearch as Jaeger's storage backend) for traces. Blocks on traffic-gen and decision-gateway emitting OTel spans (per-repo ADRs in those repos).
