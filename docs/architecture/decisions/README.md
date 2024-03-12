# Architecture Decision Records

Each file in this folder captures one architecture decision made on the pricing-observability codebase, following the standard ADR shape (Status / Context / Decision / Consequences).

New decisions get the next number and a short kebab-case slug:

```
NNNN-short-decision-name.md
```

`scripts/check-adrs.sh` (wired into `make ci-local`) verifies that:

1. Every ADR file is indexed in this README.
2. Every README link points at a file that exists.
3. Every ADR file has a `## Status` line with one of: `Proposed`, `Accepted`, `Superseded by ADR-NNNN`, `Deprecated`.
4. Every ADR file has the four standard sections: `## Status`, `## Context`, `## Decision`, `## Consequences`.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-observability-stack.md) | Observability stack for the Pricing Decision Platform | ✅ Accepted |
| [0002](0002-traces-phase.md) | Traces phase — OTel Collector + Jaeger with Elasticsearch storage | ✅ Accepted |
| [0003](0003-metrics-phase.md) | Metrics phase — Prometheus + Grafana | ✅ Accepted |
| [0004](0004-kibana-data-view-provisioning.md) | Kibana data-view provisioning via kibana-init container | ✅ Accepted |
| [0005](0005-jaeger-spm-spanmetrics-connector.md) | Jaeger Service Performance Monitoring via OTel spanmetrics connector | ✅ Accepted |
| [0006](0006-jaeger-bump-to-1.55.md) | Bump Jaeger to 1.55 for SPM spanmetrics-connector support | ✅ Accepted |
| [0007](0007-spark-dependencies-job.md) | Periodic jaeger-spark-dependencies job for the Service Graph | ✅ Accepted |
