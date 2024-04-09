# 11. Per-service Prometheus scrape: markup-svc / decision-gateway / traffic-gen

## Status

Accepted — `config/prometheus.yml` splits the single `markup-svc` job (which routed through the gateway at `:8090/metrics`) into three per-service jobs targeting `host.docker.internal:8080` / `:8090` / `:9101`. The matching change in `decision-gateway/docker-compose.yaml` exposes markup-svc's port 8080, enables `--metrics-enabled` on the gateway (so `/metrics` serves gateway-side metrics instead of forwarding to markup-svc), and enables `--metrics-listen=:9101` on traffic-gen with port 9101 exposed.

## Context

ADR-0003 wired the metrics phase with a single `markup-svc` scrape job pointing at `host.docker.internal:8090/metrics` — through the decision-gateway, which forwarded `/metrics` to markup-svc via a `--route=/metrics=>markup-svc` rule. This worked because only markup-svc emitted Prometheus exposition.

Since then both decision-gateway (v0.0.7 per its ADR-0007) and traffic-gen (v0.0.5 per its ADR-0006) ship their own `/metrics` endpoints. Three obstacles to scraping them via the existing routing:

1. The gateway's mux registers `/metrics` exactly when `--metrics-enabled` is set, which takes precedence over the `/` catch-all that proxies to markup-svc. So enabling gateway metrics breaks the existing markup-svc scrape path.
2. The gateway's `httputil.ReverseProxy` does not rewrite paths, so a route like `/markup-metrics=>http://markup-svc:8080/metrics` would forward `/markup-metrics` literally and 404.
3. traffic-gen does not sit behind the gateway; it's a client. There's no proxying path.

The cleanest fix is the obvious one: expose each service on a distinct host port and give Prometheus three scrape jobs. The "hide markup-svc behind the gateway" posture is preserved for application traffic (`/decide`, `/admin`) — only `/metrics` becomes a parallel direct path.

## Decision

`config/prometheus.yml` — three scrape jobs replace the previous one:

```yaml
- job_name: markup-svc
  static_configs: [{ targets: ["host.docker.internal:8080"], labels: { service: markup-svc } }]

- job_name: decision-gateway
  static_configs: [{ targets: ["host.docker.internal:8090"], labels: { service: decision-gateway } }]

- job_name: traffic-gen
  static_configs: [{ targets: ["host.docker.internal:9101"], labels: { service: traffic-gen } }]
```

All three jobs share the same 15 s scrape interval and the existing `external_labels: platform=pricing-decision`.

`decision-gateway/docker-compose.yaml` (separate commit in that repo) carries the matching platform-side changes: expose `ports: ["8080:8080"]` on markup-svc, drop the `/metrics` route, enable `--metrics-enabled` on the gateway, enable `--metrics-listen=:9101` + expose 9101 on traffic-gen.

## Consequences

### Closed

- Each service's own `/metrics` exposition is queryable in Prometheus. PromQL like `sum by(service)(rate(markup_decide_total[1m]))` and `gateway_requests_total{route="/decide"}` and `trafficgen_achieved_qps` all work.
- Grafana panels that key on the `service` label (which we added as a per-job label, not via re-labeling) slice cleanly: `{service="decision-gateway"}` vs `{service="markup-svc"}`.
- Adding a fourth runtime service later requires one new scrape job + one new exposed port; the pattern scales.

### Not closed

- Service discovery. All three targets are static_configs. A future ADR moves to DNS-based or file-based SD when the platform runs more than one replica per service.
- Cross-stack network sharing. Today both compose stacks reach each other via `host.docker.internal`. A future composition (single compose, shared network) drops the hostname dance.
- Scrape-time TLS. v0.0.x runs plaintext per the dev posture. Production adds `https://` + cert provisioning.
- Removing the markup-svc `ports: ["8080:8080"]` exposure when production deployments have markup-svc on a cluster-internal network. The dev compose exposes it for the scrape; production scrapes use cluster DNS without exposing to the host.
