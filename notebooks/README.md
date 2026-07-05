# Pricing Analytics notebooks

Granular, single-question Jupyter notebooks over the Pricing Decision Platform's Decision Event Stream (markup-decisions + funnel-events buckets). See `docs/architecture/decisions/0021-pricing-analytics-notebooks.md` for the shape record and rationale.

## Getting started

### Locally with a compose stack

```bash
# 1. Bring up the platform + observability (from decision-gateway/):
docker compose up -d
# 2. Drive some traffic (from traffic-gen locally or the compose service):
traffic-gen --session=4 --session-funnel-url=http://localhost:8081 --duration=30s --otel-enabled
# 3. Install notebook deps:
python3 -m venv .venv && source .venv/bin/activate
pip install -r notebooks/requirements.txt
# 4. Open a notebook:
jupyter lab notebooks/analytics/01-data-setup.ipynb
```

### On Google Colab

Each notebook's first cell has a commented Colab bootstrap block. Uncomment, run, and the loader is available:

```python
!pip -q install duckdb pandas matplotlib scipy pyarrow
!mkdir -p /content/lib
!curl -sL https://raw.githubusercontent.com/helmedeiros/pricing-observability/main/notebooks/lib/data_loader.py -o /content/lib/data_loader.py
!touch /content/lib/__init__.py
import sys; sys.path.insert(0, '/content')
```

Colab has no access to the compose-stack MinIO — every notebook falls back to `synthetic` mode automatically when `local_minio` is unavailable, so the whole set runs end-to-end with zero data plumbing. Real-data-on-Colab lands when the snapshot export tool ships (bead `workspaceBRE-57k`).

## The seven Tier-1 notebooks

| # | Notebook | What it answers |
|---|----------|----|
| 01 | [`analytics/01-data-setup.ipynb`](analytics/01-data-setup.ipynb) | Loader modes, schema quick-reference, cross-reference sanity |
| 10 | [`analytics/10-decisions-overview.ipynb`](analytics/10-decisions-overview.ipynb) | Rule fires, markup distribution, per-country slice, latency |
| 11 | [`analytics/11-funnel-overview.ipynb`](analytics/11-funnel-overview.ipynb) | Impressions → clicks → reserves → purchases + timeout split by phase |
| 30 | [`analytics/30-elasticity-baseline.ipynb`](analytics/30-elasticity-baseline.ipynb) | Log-log elasticity coefficient + bootstrap CI |
| 40 | [`analytics/40-segment-conversion.ipynb`](analytics/40-segment-conversion.ipynb) | Per-(tier, country, channel) conversion + Wilson CI, off-baseline signal |
| 50 | [`analytics/50-experiment-lift.ipynb`](analytics/50-experiment-lift.ipynb) | A/B lift + two-proportion z-test + MDE |
| 60 | [`analytics/60-rule-proposal.ipynb`](analytics/60-rule-proposal.ipynb) | Prescriptive: propose new `rules.csv` rows from segment × elasticity |

## Source format

Notebooks are authored as `.py` files in jupytext-percent format (with `# %%` cell markers) and converted to `.ipynb`. Both files are committed:

- Edit `.py`, then run `make notebooks` (or `jupytext --to notebook analytics/*.py`) to regenerate `.ipynb`.
- Colab and browser Jupyter users open `.ipynb` directly.

Rationale: clean code review (`.py` diffs are readable, `.ipynb` JSON isn't) + Colab-native delivery (Colab wants `.ipynb`).

## What's parked (see ADR-0021 Not-closed)

- **Pricing Metrics Aggregator** — the sibling C4 container. A service, not a notebook. Own arc.
- **Snapshot export script** — enables `mode='snapshot'` real-data access from Colab.
- **Tier 2 notebooks** — `02-data-quality`, `12-latency-distribution`, `20-rules-performance`, `31-elasticity-per-segment`.
- **Tier 3 notebooks** — `21-rule-fatigue`, `61-model-feature-engineering`, `62-model-baseline`.
