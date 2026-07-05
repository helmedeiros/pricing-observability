# 20. Funnel-events correlation contract — join keys, partition layout, EDA notebook

## Status

Accepted — this ADR indexes the Learning Loop's outcome-half wire contract as it lands in this repo's operational domain. Three sibling repos own the primary contracts (markup-svc ADR-0037 for `decision_id` in `/decide` response + `journey_id` in `request_context`; funnel-sim ADR-0002 / ADR-0003 for the `search.v1` and `booking.v1` schemas; funnel-sim ADR-0005 for the S3 substrate); this ADR pins how observability consumers here — Kibana saved searches, Grafana dashboards, the EDA notebook — join across them.

## Context

markup-svc ADR-0035 landed the `markup.decision.v1` schema and `decision_id` server-side minting. markup-svc ADR-0036 landed the S3 substrate. markup-svc ADR-0037 surfaced `decision_id` on the `/decide` response and accepted `journey_id` in `request_context`. funnel-sim landed as a new service emitting `search.v1` and `booking.v1` events into a sibling `funnel-events` MinIO bucket, referencing the same `decision_id` values on every offer and every booking event so the join is one-hop. traffic-gen landed `--session=N` mode that drives customer journeys through funnel-sim under a caller-minted `journey_id`.

Every plane of observability this repo owns now consumes the correlated stream:

- **Grafana** should show funnel drop-off and conversion-per-arm dashboards.
- **Kibana** saved searches should filter events by `journey_id`, `decision_id`, or `experiment`.
- **Ad-hoc EDA** — a DuckDB notebook that runs directly against MinIO — should compute conversion and elasticity per arm without shipping data to a warehouse.

The three consumers pin implicit expectations on the join semantics. Without an ADR locking them, a future rename of a partition segment or a JSON key silently breaks a saved search or a dashboard query.

## Decision

### The load-bearing join keys

| Key | Scope | Minter | Present on | Purpose |
|-----|-------|--------|------------|---------|
| `journey_id` | Session | Caller (traffic-gen `--session`, later a real BFF / mobile client) | Every event | Session-scoped analytics: group all pricing + funnel events for one visitor's journey. |
| `decision_id` | One priced offer | markup-svc | `markup.decision.v1`, `search.v1.offers[].decision_id`, `booking.v1.decision_id` | Offer-scoped analytics: connect one pricing decision to its downstream outcome. **THE join key.** |
| `search_id` | One search-page render | funnel-sim | `search.v1`, `booking.v1` (when the booking traces to a search) | Groups the N offers shown in one render. Enables shown-but-not-selected analysis. |
| `booking_id` | One reservation attempt | funnel-sim | `booking.v1` (initiated / reserved / purchased / timeout) | Scopes reservation-level events. |
| `order_id` | One successful purchase | funnel-sim | `booking.v1{event_type=booking.purchased}` | Terminal revenue identifier. |

`trace_id` and `correlation_id` are ALSO carried on every event — but they are the wrong scope for analytics joins (one search render = N `/decide` calls = N trace_ids). They stay for observability debugging, not for analytical joins.

### The partition layout consumers depend on

Both buckets are Hive-partitioned so lake-native tools read them natively. Consumers key on these partition segments explicitly (globs, `hive_partitioning=true` in DuckDB read_json_auto, external table definitions in Athena / Snowflake / BigQuery):

```
markup-decisions/
  markup-decision-v1/
    dt=YYYY-MM-DD/hour=HH/env=<env>/instance=<hostname>/
      batch-<RFC3339>-<seq>.jsonl.gz

funnel-events/
  search-v1/
    dt=YYYY-MM-DD/hour=HH/env=<env>/instance=<hostname>/
      batch-<RFC3339>-<seq>.jsonl.gz
  booking-v1/
    dt=YYYY-MM-DD/hour=HH/env=<env>/event_type=booking.initiated/instance=<hostname>/
      batch-<…>.jsonl.gz
    dt=YYYY-MM-DD/hour=HH/env=<env>/event_type=booking.reserved/instance=<hostname>/
      batch-<…>.jsonl.gz
    dt=YYYY-MM-DD/hour=HH/env=<env>/event_type=booking.purchased/instance=<hostname>/
      batch-<…>.jsonl.gz
    dt=YYYY-MM-DD/hour=HH/env=<env>/event_type=booking.timeout/instance=<hostname>/
      batch-<…>.jsonl.gz
```

Consumers filtering `event_type=booking.purchased/` scan ~5% of the booking volume rather than the full set — this is why the booking sink partitions by event_type and the search sink does not (search has one type).

### The JSON stability contract

Both schemas emit empty-string / zero-value fields explicitly rather than omitting them, so DuckDB schema inference and Spark/Snowflake external-table shapes stay stable across batches with sparse arm labels or missing correlation IDs. The one exception is fields that are semantically only present on specific event types (`booking.v1.order_id` on `booking.purchased`; `booking.v1.phase` and `booking.v1.timeout_kind` on `booking.timeout`); those keep `omitempty` and consumers handle them as nullable.

### The EDA notebook this ADR anchors

`notebooks/elasticity/elasticity.sql` runs against a live compose stack:

```
duckdb -init elasticity.sql :memory: ''
```

It materializes four views (`offers_shown`, `purchased`, `walked_at_init`, `walked_at_reserve`), LEFT JOINs from `offers_shown` so unclicked impressions stay in the denominator, and emits per-`(experiment, variant)`:

- `impressions`, `purchases`, `walkoffs_at_init`, `walkoffs_at_reserve`
- `conversion_rate`, `price_shock_rate`, `payment_friction_rate`
- `avg_shown_price`, `gmv`

Elasticity is one arithmetic step downstream of the query result:
```
elasticity = (Δ conversion / conversion_control) ÷ (Δ avg_price / avg_price_control)
```

The notebook is executable end-to-end today: verified against ~90 impressions producing 17 purchases (18.89% conversion) plus 4 price-shock walkoffs and 5 payment-friction walkoffs, all joined on `decision_id`.

## Consequences

### Positive
- Consumers pin one contract, not four. This ADR is the discovery point; the schema ADRs in the three producer repos remain the authoritative sources per field.
- The DuckDB notebook lets an operator answer conversion / elasticity questions without provisioning a warehouse. Same query pattern transfers to Athena or Snowflake by only swapping the S3 endpoint + adding partition projection.
- The load-bearing join is one hop: LEFT JOIN offers_shown to purchased on `decision_id`. Simple to reason about, cheap to run.

### Negative
- Adds a fourth ADR indexing pattern across the arc — an operator learning the platform now reads markup-svc ADR-0037 + funnel-sim ADRs 0002/0003/0005 + this one. The Discovery cost is bounded (each ADR points at the others in its References) but real.
- The notebook is currently only exercised against the local compose stack. Production S3 endpoints have their own authentication + region + endpoint-flip specifics that a future prod-run of the same notebook must translate.
- Two `booking-v1` sink instances would each write to their own `instance=` partition segment; consumers reading `booking-v1/…/*/instance=*/*.jsonl.gz` across two hosts are correct today, but a future multi-region layout may need a `region=` segment. Parked.

### Not closed
- **Materialized-view refresh cadence.** The DuckDB views today re-read the buckets on every query. Production traffic at 1000+ QPS will make this too slow; a scheduled Parquet materialization pattern (Athena `CTAS`, Spark, or plain `duckdb COPY`) is the next step. Deferred.
- **Grafana funnel drop-off dashboard.** A native Prometheus-only dashboard cannot see the correlation because the join is per-event, not per-metric. A Grafana panel backed by the DuckDB view (via a JSON API layer or a scheduled Parquet materialization) is a follow-on.
- **Kibana saved searches.** Filters on `attrs.request_context.journey_id` or `attrs.decision_id` already work; a dedicated set of saved searches naming the Learning Loop join keys is a follow-on documentation task.

## References

- markup-svc ADR-0037 — `decision_id` in `/decide` response; `journey_id` in `request_context`.
- markup-svc ADR-0035, ADR-0036 — `markup.decision.v1` schema + S3 substrate.
- funnel-sim ADR-0002 — `search.v1` contract.
- funnel-sim ADR-0003 — `booking.v1` contract with the terminal-timeout `phase` field.
- funnel-sim ADR-0005 — generic S3 sink instantiated per event type.
- traffic-gen ADR-0009 — `--session=N` session driver.
- `~/Code/workspaceBRE/learning-loop-plan.local.md` — arc-level design record; §Correlation model + §Elasticity.
- `notebooks/elasticity/elasticity.sql` — the canonical DuckDB query this ADR pins.
