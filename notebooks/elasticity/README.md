# Elasticity + conversion notebook

DuckDB-native exploratory analysis over the Pricing Decision Platform's two MinIO buckets:

- `markup-decisions/` — every `markup.decision.v1` event emitted by markup-svc (ADR-0035, ADR-0036).
- `funnel-events/search-v1/` and `funnel-events/booking-v1/…` — every `search.v1` and `booking.v1` event emitted by funnel-sim (funnel-sim ADRs 0002, 0003, 0005).

Joins on `decision_id` — the load-bearing key added to markup-svc's `/decide` response by markup-svc ADR-0037 and echoed onto every downstream funnel event by funnel-sim.

## Prerequisites

- The compose stack up (`decision-gateway/docker-compose.yaml -f docker-compose.scientific-override.yaml`).
- MinIO reachable at `localhost:9000` with credentials `minio:minio12345` (the compose defaults).
- Traffic having flowed through the funnel (traffic-gen `--session=N` mode, or manual curls). Freshly-booted stacks with empty buckets yield empty result sets, not an error.
- DuckDB 1.5+ CLI (`brew install duckdb` on macOS; `pip install duckdb` in a venv on Linux).

## Run

```bash
cd notebooks/elasticity
duckdb -init elasticity.sql :memory: ''
```

The script installs `httpfs`, points at MinIO, materializes four views (`offers_shown`, `purchased`, `walked_at_init`, `walked_at_reserve`), and prints the elasticity table plus a journey-level sanity check.

## What it emits

```
┌────────────┬─────────┬─────────────┬───────────┬──────────────────┬───────────
│ experiment │ variant │ impressions │ purchases │ walkoffs_at_init │ … conversion_rate │ price_shock_rate │ payment_friction_rate │ avg_shown_price │ gmv
```

- **impressions** — one row per priced offer that was rendered.
- **purchases** — join to `booking-v1/event_type=booking.purchased/`.
- **walkoffs_at_init** — join to `booking-v1/event_type=booking.timeout/` filtered by `phase=initiated` (the price-shock cohort).
- **walkoffs_at_reserve** — same, filtered by `phase=reserved` (the payment-friction cohort).
- **conversion_rate**, **price_shock_rate**, **payment_friction_rate** — the derived ratios.
- **avg_shown_price** — arithmetic mean over `offers_shown.price`.
- **gmv** — `SUM(revenue)` over the purchased join.

`(none)` rows appear when the markup-svc decision carried no experiment or variant (the default markup-svc rule set does not stamp them). To produce arm-labeled rows, configure markup-svc's router with named experiments (see markup-svc ADR-0011) or drive traffic through model-registry with promoted challenger arms.

## Elasticity math

Once two arms populate, the elasticity coefficient per arm is:

```
elasticity = (Δ conversion / conversion_control) ÷ (Δ avg_price / avg_price_control)
```

One arithmetic step after the query result. Confidence intervals for the lift are a standard proportion-difference test on `purchases / impressions` per arm — z-score and p-value can be materialized as a second view.

## Files

| File | Purpose |
|---|---|
| `elasticity.sql` | The canonical query. Run under `duckdb -init`. |
| `README.md` | This file. |

## Next moves

- **Two-arm setup**: configure markup-svc with `--route=v1:control:rules:…csv --route=v2:treatment:rules:…csv`, run two traffic-gen sessions against the same funnel-sim at different `--session-p-walk-at-init` values, verify `elasticity` shows two rows with the expected direction of lift.
- **Materialize to Parquet**: `COPY (SELECT * FROM elasticity) TO '…parquet' (FORMAT parquet, COMPRESSION zstd);` for archival or downstream consumption.
- **Jupyter surface**: wrap the SQL as an `.ipynb` if a chart layer becomes useful.

See pricing-observability ADR-0020 for the cross-repo integration contract the notebook depends on.
