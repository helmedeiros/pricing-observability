# See all platform logs flowing through Kibana

## Problem

You want every log line emitted by markup-svc, decision-gateway, and traffic-gen to land in Elasticsearch and be queryable in Kibana — sliced by `attrs.correlation_id` so you can pull a single request's lifecycle across all three services with one query.

## Recipe

Clone the four platform repos so the compose files are reachable:

```sh
git clone https://github.com/helmedeiros/markup-svc.git
git clone https://github.com/helmedeiros/traffic-gen.git
git clone https://github.com/helmedeiros/decision-gateway.git
git clone https://github.com/helmedeiros/pricing-observability.git
```

Bring up the platform stack (markup-svc + decision-gateway + traffic-gen) first:

```sh
cd decision-gateway
docker compose up -d
```

Verify all three containers are running:

```sh
docker compose ps
# NAME                          STATUS
# decision-gateway-markup-svc-1     Up
# decision-gateway-decision-gateway-1  Up
# decision-gateway-traffic-gen-1    Up
```

Bring up the observability stack alongside it:

```sh
cd ../pricing-observability
docker compose -f docker-compose.observability.yaml up -d
```

Wait for Elasticsearch to come up healthy (the Kibana container will block on this via the healthcheck):

```sh
until curl -fs http://localhost:9200/_cluster/health | grep -E '"status":"(green|yellow)"' > /dev/null; do sleep 1; done
echo "Elasticsearch ready"
```

Open Kibana in a browser at <http://localhost:5601>. On first launch Kibana asks how you want to ingest data — pick "Add data manually" or skip the welcome screen.

Create the index pattern:

1. Sidebar → **Stack Management** → **Index Patterns** (or **Data Views** depending on Kibana version).
2. Click **Create index pattern**.
3. Name pattern: `platform-logs-*`.
4. Timestamp field: `@timestamp`.
5. Save.

Send a request through the gateway with a known correlation ID so you have something to query for:

```sh
curl -i -X POST \
  -H "X-Correlation-ID: smoke-1" \
  -H "Content-Type: application/json" \
  -d '{"customer_tier":"enterprise"}' \
  http://localhost:8090/decide
```

Within ~10 seconds, the line appears in Kibana. In the **Discover** view, paste this filter:

```
attrs.correlation_id : "smoke-1"
```

You should see one or more documents (typically one from decision-gateway's `gateway.access` event; markup-svc still emits plain-text logs that land under `message` rather than `attrs.*` until the markup-svc convergence ADR ships).

Run traffic-gen for a few seconds to generate volume:

```sh
cd ../decision-gateway
docker compose exec decision-gateway sh -c "echo 'gateway is up; traffic-gen container will keep pushing'"
# traffic-gen is already running per the platform compose's default
# command (exp:10->500@5m). Wait 30 seconds and the platform-logs-*
# index gains hundreds of documents.
```

Back in Kibana:

```
attrs.route : "/decide" and attrs.status : 200
```

shows every successful decide-routed request. Add columns for `attrs.duration_ms`, `attrs.correlation_id`, `attrs.path` to see the per-request shape.

## What's happening

```
markup-svc container stdout    ─┐
decision-gateway container stdout ─┤
traffic-gen container stdout   ─┘
        │
        │ Docker captures stdout into /var/lib/docker/containers/<id>/<id>-json.log
        ▼
┌──────────────────────────┐
│       Filebeat           │ docker.autodiscover provider tails the platform
│  (one container,         │ container log files; image-prefix filter drops
│   mounts docker.sock +   │ any other Docker containers on the daemon.
│   /var/lib/docker/...)   │ decode_json_fields elevates {time,level,msg,attrs}
└──────────────┬───────────┘ into top-level ES fields.
               │
               │ Bulk index requests
               ▼
┌──────────────────────────┐
│     Elasticsearch        │ Single-node, dynamic field mapping; one daily
│   (platform-logs-*)      │ index. attrs.correlation_id becomes a keyword
└──────────────┬───────────┘ field queryable by exact match.
               │
               │ Kibana query
               ▼
┌──────────────────────────┐
│         Kibana           │ Discover view: filter by attrs.correlation_id,
│  (http://localhost:5601) │ add columns, save searches, build dashboards.
└──────────────────────────┘
```

Each platform service writes one JSON object per log event to its stdout. Docker captures stdout into a container-scoped JSON file on the host. Filebeat (single container on the host's Docker daemon) tails those files, applies the `decode_json_fields` processor to elevate the application JSON into top-level ES fields, and bulk-indexes them.

The `attrs.correlation_id` lift is what makes the cross-service join work: the gateway's CorrelationID middleware mints a UUID v4 when the inbound request lacks one, propagates it on the outbound request to markup-svc, and emits it on the `gateway.access` event. traffic-gen does not set `X-Correlation-ID` today (a candidate v0.0.3 feature) so every traffic-gen-driven request gets a gateway-minted UUID; the cookbook query above works on either.

## What to check after

- `curl http://localhost:9200/_cluster/health` returns a JSON document with `"status":"green"` or `"yellow"` (yellow is fine for single-node since replica shards are unallocated).
- `curl http://localhost:9200/_cat/indices?v` lists at least one index matching `platform-logs-*` with a non-zero `docs.count`.
- `curl http://localhost:9200/platform-logs-*/_search?size=1&pretty | jq '.hits.hits[0]._source'` returns a document with top-level `time`, `level`, `msg`, `attrs` (or for markup-svc plain-text lines, a `message` field with the raw text and an `error.message` annotation from `add_error_key`).
- Kibana Discover view shows documents accumulating in near-real-time as you fire requests at the gateway.
- A `attrs.correlation_id : "<some-uuid>"` query returns the matching document(s) within a few seconds of the request.
- `docker logs decision-gateway-filebeat-1 2>&1 | tail -30` shows Filebeat's own logs — useful when ES is unreachable; Filebeat retries with backoff and surfaces the connection error.

## Mistakes to avoid

- **Trying to query plain-text markup-svc lines under `attrs.*`**: markup-svc still emits plain text. Those lines land under `message`, not `attrs`. Until the markup-svc convergence ADR converts to the same JSON shape decision-gateway and traffic-gen already use, structured-field filtering on markup-svc logs is limited.
- **Running the observability compose before the platform compose**: Filebeat starts before any platform container exists; its autodiscover provider sees no matching containers and the platform-logs-* index stays empty until you start the platform too. Order doesn't matter logically — Filebeat retries — but operator confusion is real. Bring the platform up first.
- **Tearing down `docker-compose.observability.yaml` with `down -v`**: that wipes the Elasticsearch volume so all ingested logs are lost. Use `down` (no `-v`) for a clean stop that preserves the index.
- **Hitting `https://localhost:5601`**: Kibana ships HTTP in this dev posture (no TLS). Use `http://`.
- **Trying to add `xpack.security.enabled=true` without `ELASTIC_PASSWORD`**: ES requires the password set when security is on; the compose runs with security OFF for dev so curl + Kibana + Filebeat connect anonymously. A production deployment turns security back on and provisions the password via the env var.

## Resource budget

The observability stack adds ~2.5 GB RAM + ~1 CPU core to the dev machine under steady-state load:

- Elasticsearch JVM heap (`-Xms1g -Xmx1g`): 1 GB.
- Elasticsearch off-heap (Lucene buffers, segment cache): ~512 MB at steady state.
- Kibana: ~512 MB.
- Filebeat: ~50-100 MB.

On an 8 GB dev laptop running the platform stack (~500 MB) + observability stack (~2.5 GB) + the IDE / browser / docker-desktop itself, the budget is tight. The compose file documents this in its header comment; tune `ES_JAVA_OPTS=-Xms512m -Xmx512m` to halve ES's heap if you only care about smoke-level traffic.

## Relevant ADRs and config files

- pricing-observability [ADR-0001](../architecture/decisions/0001-observability-stack.md) — phased rollout, ES + Kibana choice over Loki + Grafana, Jaeger choice over Tempo, NOT-closed list.
- `docker-compose.observability.yaml` at the repo root — service definitions (ES + Kibana + Filebeat).
- `config/filebeat.yml` — autodiscover provider + `decode_json_fields` processor + ES output.
- decision-gateway ADR-0001 — the gateway emits the `gateway.access` JSON events this recipe queries.
- traffic-gen ADR-0001 — the load shaper that drives platform traffic.
- markup-svc ADR-0009 — OTel span decorator (relevant for v0.0.3 traces phase; not active in v0.0.1).
- markup-svc plain-text → JSON convergence ADR — pending; the cookbook footnote on plain-text lines references this gap.
