# 7. Periodic jaeger-spark-dependencies job for the Service Graph

## Status

Accepted — `docker-compose.observability.yaml` adds a `spark-dependencies` service running `ghcr.io/jaegertracing/spark-dependencies/spark-dependencies:latest` with a small loop wrapper that invokes the image entrypoint every 120 s against today's `jaeger-span-*` index. Output lands in `jaeger-dependencies-YYYY-MM-DD`. Jaeger's "System Architecture" tab queries that index and renders the service-call graph.

## Context

Jaeger's dependency graph is not computed from live spans. The Jaeger UI's `System Architecture` tab reads from `jaeger-dependencies-*` indices in Elasticsearch (when `SPAN_STORAGE_TYPE=elasticsearch`), which are produced by the `jaeger-spark-dependencies` batch job. Without that job, the tab shows "No service dependencies found" — which is what the operator observed.

The Spark job reads one day's spans, aggregates parent-child service relationships, writes one document per (parent, child) pair to the `jaeger-dependencies-YYYY-MM-DD` index. Default mode processes yesterday; for dev we want today so the graph stays fresh while traffic-gen is running.

## Decision

Two files:

- `config/spark-deps-loop.sh`: a small `/bin/sh` loop that exports `DATE=$(date -u +%Y-%m-%d)` + `STORAGE=elasticsearch` + `ES_NODES=http://elasticsearch:9200` + `MAIN_CLASS=io.jaegertracing.spark.dependencies.elasticsearch.ElasticsearchDependenciesJob` then runs `/entrypoint.sh`. Sleeps `INTERVAL` (120 s) between runs.
- `docker-compose.observability.yaml`: new `spark-dependencies` service. Mounts the script + overrides the image entrypoint with `["/bin/sh", "/etc/spark-deps/spark-deps-loop.sh"]`.

## Consequences

### Closed

- `System Architecture` populates with the expected service edges: traffic-gen → decision-gateway → markup-svc. Self-edges per service (decision-gateway → decision-gateway, markup-svc → markup-svc) are also present because intra-service parent-child span pairs count as same-service traffic in the Spark aggregator.
- The graph updates every 2 minutes; new services emitting spans appear automatically.

### Not closed

- The Spark job is a Java/Spark process — ~500 MB RAM at startup, ~10-15 s per run on dev volumes. At 120 s interval, the container is idle ~85% of the time. Production deployments typically schedule it as a daily k8s CronJob instead of a sidecar loop.
- Self-edges (a service calling itself within the same trace) are correct but visually noisy. A `--exclude` flag on the Spark job would suppress them; not configured today.
- Older `jaeger-dependencies-*` indices are not retention-managed by this ADR. ES's default keeps them indefinitely; production deployments add an ILM policy.
