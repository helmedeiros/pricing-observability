# 9. AlertManager + webhook receiver

## Status

Accepted — `docker-compose.observability.yaml` adds two services: `alertmanager` (`prom/alertmanager:v0.27.0`) and `alert-sink` (a ~30-line Python HTTP receiver). Prometheus's `alerting.alertmanagers` block targets AlertManager; AlertManager's single default route delivers every alert to `http://alert-sink:9000/alerts` via the standard webhook receiver. The sink logs each delivery as one JSON line on stdout, so `docker compose logs alert-sink` is the operator's view of fired/resolved alerts.

## Context

ADR-0008 wired five Prometheus alerting rules into the `rule_files` directive. The rules evaluate, fired alerts show up at `/alerts`, but nothing leaves Prometheus — no Slack, no email, no webhook. Operators not watching the UI miss every event. AlertManager is the canonical Prometheus piece for receiver routing, deduplication, and silencing; it ships as a separate container and is the natural fit.

The dev-posture choice is the receiver. Real notification channels (Slack, PagerDuty, email/SMTP) require credentials + corporate plumbing. For the dev compose we want the round-trip to work end-to-end and visible without external dependencies. A tiny webhook sink that logs incoming AlertManager POSTs to stdout closes the loop without requiring any external account.

## Decision

`config/alertmanager.yml`: one route → one receiver (`default`) → one `webhook_configs` block pointing at `http://alert-sink:9000/alerts` with `send_resolved: true`. `group_by: [alertname, service]` so AlertManager batches the natural alert keys. `group_wait: 10s` + `group_interval: 5m` + `repeat_interval: 1h` keep the storm shape sane during dev iteration.

`config/alert-sink.py`: a single-file Python HTTP server listening on `:9000`. For each POST it parses the AlertManager JSON body and emits one line per alert with `{msg=alertmanager.alert, status, alertname, severity, service, summary, starts_at, ends_at}` — the same JSON shape Filebeat already understands, so `docker logs` AND Kibana both surface it.

`config/prometheus.yml`: `alerting.alertmanagers` block points at `alertmanager:9093`.

`docker-compose.observability.yaml`: `alertmanager` mounts the config + binds `9093`; `alert-sink` uses `python:3.12-alpine` + mounts the script + binds `9100:9000` for direct probing.

## Consequences

### Closed

- Alerts now have a destination. The operator's "we have all the signals but can't get paged" gap closes for dev. Production deployments swap `webhook_configs` for a `slack_configs` / `email_configs` / `pagerduty_configs` block in the same AlertManager config.
- Cross-signal symmetry: alert events land in the same stdout-driven log pipeline as `gateway.access` / `markup-server.access`, so Filebeat → Kibana sees them under `attrs.msg:"alertmanager.alert"` filtering.
- Smoke-tested via a synthetic alert POSTed directly to AlertManager: the alert flowed through batching → webhook → sink and landed on stdout within the configured `group_wait`.

### Not closed

- Silences / inhibitions UI workflows. AlertManager's UI (port 9093) supports them; no automation around them yet.
- Real notification channels. The dev receiver is intentionally a stdout sink. Operators wire production channels by swapping the `webhook_configs` block.
- Multi-tenant routing. The dev config has one route + one receiver; production fan-outs per `severity` or `service` land when there is more than one consumer.
- High availability for AlertManager. The compose runs a single instance; production deployments cluster three.
