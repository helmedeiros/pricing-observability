# 4. Kibana data-view provisioning via kibana-init container

## Status

Accepted — `docker-compose.observability.yaml` gains a `kibana-init` one-shot service (image `curlimages/curl:8.5.0`, `restart: "no"`) that polls Kibana's `/api/status` until "available" then POSTs `config/kibana-saved-objects.ndjson` to `/api/saved_objects/_import?overwrite=true`. Two data views land per operator restart: `platform-logs-*` (time field `@timestamp` — the Filebeat-shipped application logs) and `jaeger-span-*` (time field `startTimeMillis` — Jaeger's span storage in Elasticsearch). The init also sets the Kibana `defaultIndex` to `platform-logs` so Discover opens directly on the logs view instead of the empty data-view selector.

## Context

Operators bringing up the observability stack repeatedly hit the same friction: Kibana boots, Discover demands a data view, the operator manually types `platform-logs-*`, picks `@timestamp`, saves. Every `docker compose down -v` wipes the saved object and the dance starts again. Grafana solved this for itself via file-based provisioning at startup (per ADR-0003); Kibana 8.x does NOT have an equivalent YAML provisioning mechanism for saved objects — its `xpack.fleet.packages` config is for Fleet integrations only, not for arbitrary saved-objects.

The reproducible-from-compose dev posture is non-negotiable. The fix is an init container that calls Kibana's saved-objects import API once per stack bring-up.

One design question.

### init container vs operator-side script

Two options to run the import:

- **Init container in compose**: a small image (curl + the NDJSON file) starts when Kibana starts, waits for `/api/status` to report "available", POSTs the import, exits. Pros: zero operator action; reproducible from compose; idempotent on every restart (`overwrite=true`); the bundled NDJSON lives in the same repo as the rest of the observability configs. Cons: adds one more container to the compose; that container is "always exited" in the steady state which can look odd at first.
- **Operator-side shell script**: a `scripts/init-kibana.sh` the cookbook tells operators to run once after the stack is up. Pros: no extra container; explicit operator action. Cons: not reproducible — the operator has to remember the script; `docker compose down -v` requires re-running it; new operators have to read the cookbook before they can use Discover.

**Pick init container.** The operator-experience win matches the rest of the platform's compose-driven posture (Filebeat auto-discovers; OTel Collector auto-receives; Grafana auto-provisions). The "always exited" container is a normal sight in production compose-stack patterns (sidecar / init-style services); the cookbook calls it out so operators do not mistake it for a failure.

## Decision

`config/kibana-saved-objects.ndjson`: two `index-pattern` saved objects in NDJSON form (one per line) describing `platform-logs-*` and `jaeger-span-*` with their respective time-field names. The format follows Kibana's export NDJSON shape so an operator who customizes a data view via the UI can export it directly into this file.

`config/kibana-init.sh`: a `#!/bin/sh` script that:

1. Polls `KIBANA_URL/api/status` until the response contains `"level":"available"`. Maximum wait ~120s (covers Kibana's first-boot migration which is 30-60s on a fresh ES).
2. POSTs the bundled NDJSON to `KIBANA_URL/api/saved_objects/_import?overwrite=true` via curl multipart-form. `overwrite=true` makes the call idempotent across compose restarts; the operator's UI edits survive the next restart only if they re-export to the file.
3. POSTs `defaultIndex=platform-logs` to `/api/kibana/settings` so Discover opens on the logs view.
4. Exits.

`docker-compose.observability.yaml` gains the `kibana-init` service: image `curlimages/curl:8.5.0` (alpine + curl, ~10 MB), `restart: "no"`, `depends_on: kibana`, mounts the script + NDJSON files, entrypoint is `/bin/sh /etc/kibana-init/kibana-init.sh`. The dependency is "depends_on: kibana" (not the healthcheck-conditional variant) because Kibana's compose-level healthcheck is not configured today; the script's `/api/status` poll IS the healthcheck.

## Consequences

### Closed by this ADR

- Kibana opens to a usable Discover view on every operator restart with zero manual setup. `attrs.correlation_id` and `attrs.trace_id` queries from the `gateway.access` log lines work immediately.
- The `jaeger-span-*` data view gives operators a Kibana-side view of spans (separate from Jaeger's UI). Useful for ad-hoc span queries that don't fit Jaeger's trace-list model — e.g., `aggregate by tag rule.markup.adapter` across all recent spans.
- Operators customizing a data view via the Kibana UI can export it back into the bundled NDJSON file; the next compose restart is reproducible from git.

### NOT closed by this ADR

- Kibana saved searches, visualizations, dashboards. The current scope is data views only — saved searches + dashboards would land in the same NDJSON file as additional saved-object lines. The pattern scales; the first dashboard motivates adding it.
- Kibana URL templates that link `attrs.trace_id` to Jaeger UI. Tracked separately; the URL-template saved object is a `url` type, NOT an `index-pattern`, so it goes into the same NDJSON file alongside data views.
- Authentication on the saved-objects import. v0.0.x runs Kibana with `xpack.security.enabled=false`; production deployments authenticate the import with an API key passed via the init script's env. Out of scope for dev.
- A Kibana-side version of the Grafana starter dashboard. Grafana is the canonical metrics+logs+traces dashboard; Kibana's Discover + Lens visualizations stay for ad-hoc log exploration. Not duplicating the dashboard.

### Resource footprint

The `curlimages/curl:8.5.0` image is ~10 MB pulled, ~3 MB resident during execution, zero after exit. Negligible. The init runs once per compose `up`; subsequent restarts re-run it (idempotent with `overwrite=true`).

### Validation strategy

- After `docker compose -f docker-compose.observability.yaml up -d`: the `kibana-init` container starts, runs, exits with code 0 within ~60s of Kibana being available. `docker compose logs kibana-init` shows `successCount: 2` from the import API.
- Curl-side: `curl http://localhost:5601/api/saved_objects/_find?type=index-pattern -H 'kbn-xsrf: true'` returns both data views. `curl http://localhost:5601/api/kibana/settings` returns `defaultIndex: platform-logs`.
- Operator-side: opening http://localhost:5601/app/discover lands on the `platform-logs-*` view with the time picker showing recent log lines; switching the data-view selector at the top reveals `jaeger-span-*` as the second option.
