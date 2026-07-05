# 21. Pricing Analytics/BI — granular jupytext notebooks with a Colab-compatible data loader

## Status

Accepted — the Pricing Analytics/BI container from the C4 diagram lands as a set of granular, single-question Jupyter notebooks under `notebooks/analytics/`, backed by a shared `lib/data_loader.py` that abstracts over three data-loading modes (local MinIO, synthetic in-notebook generation, and a snapshot-URL stub for a future operator-run export). The Pricing Metrics Aggregator (the other container in the same C4 boundary) is deliberately NOT built here — it is a service, not a notebook, and gets its own arc.

## Context

The Pricing Decision Platform's C4 sketch places two containers inside the Pricing Observability boundary that consume the Decision Event Stream (established by markup-svc ADR-0035/0036 and extended by funnel-sim ADRs 0002/0003):

- **Pricing Analytics/BI** — "Historical analysis: experiment results, route performance, price sensitivity, revenue attribution." Human-driven, hypothesis-first, interactive.
- **Pricing Metrics Aggregator** — "Aggregates Pricing decisions into metrics: margin, margin distribution, attach rate, conversion signals." Continuous / scheduled service, feeds Pricing Monitoring & Alerting downstream.

These have different consumers (a Price Manager persona vs. an on-call rotation), different latency profiles (batch/interactive vs. continuous), and different implementation shapes (notebooks vs. a Go/Python service). This ADR concerns only the Analytics/BI container; the Aggregator is documented as a separate arc in the ROADMAP.

The user's stated needs for Analytics/BI:

1. **Understand experiment results** — A/B lift with confidence intervals + significance tests.
2. **Rules performance** — which rules fire, at what rates, with what downstream conversion.
3. **Price sensitivity** — the elasticity coefficient, per segment, with a bootstrap CI.
4. **Customer segments** — conversion breakdowns per (customer_tier, country, channel, device).
5. **Create and propose new rules/models** — prescriptive analytics, not just descriptive.
6. **Colab-migratable** — every notebook must run in Google Colab with zero local infrastructure.
7. **Granular** — separate notebooks per question, not a monolith.

## Decision

### Layout

```
notebooks/
├── README.md                            # overview + Open-in-Colab badges
├── requirements.txt                     # duckdb, pandas, numpy, matplotlib, scipy, pyarrow
├── lib/
│   ├── __init__.py
│   └── data_loader.py                   # 3 modes, synthetic generator
├── elasticity/
│   └── elasticity.sql                   # pre-existing DuckDB SQL notebook (ADR-0020)
└── analytics/
    ├── 01-data-setup.ipynb              # + .py source
    ├── 10-decisions-overview.ipynb      # + .py source
    ├── 11-funnel-overview.ipynb         # + .py source
    ├── 30-elasticity-baseline.ipynb     # + .py source
    ├── 40-segment-conversion.ipynb      # + .py source
    ├── 50-experiment-lift.ipynb         # + .py source
    └── 60-rule-proposal.ipynb           # + .py source
```

### Naming convention

`NN-topic-subtopic.ipynb` where `NN` groups by concern:

| Range | Concern | Tier |
|-------|---------|------|
| 01-09 | Foundation / setup / data quality | 1-2 |
| 10-19 | Descriptive (decisions, funnel, latency) | 1-2 |
| 20-29 | Rules performance | 2-3 |
| 30-39 | Elasticity | 1-2 |
| 40-49 | Customer segments | 1-2 |
| 50-59 | Experiments / A/B | 1-3 |
| 60-69 | Prescriptive (rule + model proposals) | 1-3 |

Shipped in this ADR (Tier 1): 01, 10, 11, 30, 40, 50, 60. Tiers 2 and 3 are ROADMAP.local.md entries with concrete triggers.

### Source format: jupytext-percent `.py` + generated `.ipynb`

Every notebook is authored as a `.py` file in jupytext-percent format (with `# %%` cell markers) and converted to `.ipynb` via `jupytext --to notebook`. Both files are committed:

- The `.py` file is the review artifact — clean diffs, no JSON noise, no embedded output that gets stale.
- The `.ipynb` file is the deliverable — Colab, VS Code, Jupyter Notebook, JupyterLab all open it directly.

`Makefile` has a `notebooks` target that regenerates every `.ipynb` from its `.py` source so a code review touching a notebook always ends with `make notebooks` and one clean pair of file changes.

### Data loader contract

`lib.data_loader` exposes three loaders: `load_decisions`, `load_search`, `load_booking`. Every loader accepts `mode=`:

- **`local_minio`** (default) — DuckDB `httpfs` extension against the compose-stack MinIO. Zero data prep; loads live events on the operator's laptop. Used in dev and by the arc's per-repo scientific harnesses.
- **`synthetic`** — deterministic `numpy.random.default_rng(seed)` generator that produces coherent decisions + search offers + booking events with cross-referencing `decision_id` / `journey_id` / `search_id`. Baked-in elasticity: higher-tier customers convert more, higher-priced offers convert less, treatment arm walks off more above €55. Runs on Colab with no external data.
- **`snapshot`** — Parquet download from a caller-supplied URL. Stub in this ADR (`raise NotImplementedError` when no URL given); an operator-run export tool lands the real URL in a follow-on arc (`workspaceBRE-57k`).

Every loader returns a `pandas.DataFrame` with a stable column set derived from the ADR-0035 / funnel-sim ADR-0002 / ADR-0003 schemas. `request_context.*` fields on the decisions dataframe are lifted to top-level `rc_*` columns for ergonomic notebook access.

### Colab bootstrap

Every notebook's first cell (commented out for local runs) fetches the loader from GitHub raw and prepends `sys.path`:

```python
# Uncomment on Google Colab:
# !pip -q install duckdb pandas matplotlib scipy pyarrow
# !mkdir -p /content/lib
# !curl -sL https://raw.githubusercontent.com/helmedeiros/pricing-observability/main/notebooks/lib/data_loader.py -o /content/lib/data_loader.py
# !touch /content/lib/__init__.py
# import sys; sys.path.insert(0, '/content')
```

Alternative: `data_loader.colab_bootstrap()` returns the exact snippet as a string so the pattern is discoverable from a Python prompt.

### "Granular" means one question per notebook

Each notebook answers ONE question that a Price Manager might have. Notebooks that couple multiple questions (e.g. "elasticity AND rules AND experiments in one notebook") violate the ADR — split into per-question siblings instead. This drives the Tier 1 count (7 notebooks) and the enumerated Tier 2 (~4) + Tier 3 (~3) additions.

### Notebook end-of-file structure

Every notebook ends with a `## What's next` markdown cell pointing at 2-3 related notebooks. Discovery mesh: any notebook a Price Manager opens tells them what to open next.

## Consequences

### Positive
- One-line-per-analysis workflow: `git pull && jupyter lab notebooks/analytics/60-rule-proposal.ipynb`, no data-plumbing setup.
- Colab compatibility: zero infrastructure for external partners or new team members to test hypotheses.
- Clean code review: the jupytext `.py` sources produce readable diffs; unlike raw `.ipynb` JSON.
- Granularity: adding a new hypothesis-driven notebook is a copy-paste-and-rename of an existing one, not a merge conflict inside a monolith.
- Prescriptive output: the `60-rule-proposal` notebook emits CSV rows that can be pasted into markup-svc's `rules.csv` directly — closes the loop between analysis and action.

### Negative
- Two files per notebook (`.py` + `.ipynb`). `Makefile notebooks` mitigates drift but a reviewer who edits `.ipynb` directly can still cause divergence. Documented in README.
- Coverage bar (`COVER_MIN` in the notebooks Makefile): the notebooks themselves have no unit tests. The data loader is trivially testable but does not have tests in this ADR. Parked.
- Colab bootstrap depends on `raw.githubusercontent.com`. If the repo goes private or the branch moves, every notebook's first cell breaks. Documented in Not-closed.

### Not closed (deferred with explicit triggers)
- **Pricing Metrics Aggregator** — the sibling container in the same C4 boundary. Design lives in `~/Code/workspaceBRE/analytics-arc-plan.local.md`. Build in a follow-on arc when Grafana panels need continuous rolling aggregates fed by a service, not by re-running notebooks on a cron.
- **Snapshot export script** — a CLI (Go or Python) that walks the buckets on a date range, redacts PII fields (product_id / amount per markup-svc ADR-0035's privacy posture), writes Parquet extracts, and publishes to a signed URL. Enables `load_*(mode='snapshot', url=…)`. Trigger: when a Colab partner needs real (non-synthetic) data.
- **Tier 2 notebooks** (`02-data-quality`, `12-latency-distribution`, `20-rules-performance`, `31-elasticity-per-segment`). Bead: `workspaceBRE-lzu`. Trigger: when Price Manager feedback identifies a Tier 1 notebook that would benefit from a companion drill-down.
- **Tier 3 notebooks** (`21-rule-fatigue`, `61-model-feature-engineering`, `62-model-baseline`). Bead: `workspaceBRE-5c9`. Trigger: when the ML challenger flow (model-registry side) is ready for a proposed model to be validated.
- **Data-loader unit tests** — parametrize each mode against a stable expected schema. Trigger: first time the data-loader breaks silently and a notebook produces wrong output without a clear error.
- **Coverage of latency histograms in notebooks** — the raw `duration_ms` field is loaded but there's no `12-latency-distribution` notebook yet. Trigger: first latency incident post-arc.

## References
- pricing-observability ADR-0020 — funnel-events correlation contract that the notebooks depend on.
- markup-svc ADR-0035 — `markup.decision.v1` schema, source for `load_decisions()`.
- markup-svc ADR-0037 — `decision_id` in `/decide` response + `journey_id` in `request_context`, the join keys the notebooks use.
- funnel-sim ADRs 0002, 0003 — `search.v1` and `booking.v1` schemas, source for `load_search()` and `load_booking()`.
- `~/Code/workspaceBRE/learning-loop-plan.local.md` — arc-level design record for the Learning Loop that made these notebooks possible.
- `~/Code/workspaceBRE/analytics-arc-plan.local.md` (to be created in this arc) — arc-level design for the Analytics/BI + Metrics Aggregator arc; enumerates the Metrics Aggregator design that is deferred here.
