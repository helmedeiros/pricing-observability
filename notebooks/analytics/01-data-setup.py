# ---
# jupyter:
#   jupytext:
#     formats: py:percent,ipynb
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.4
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # 01 — Data setup
#
# Foundational notebook. Every other analytics notebook imports
# `lib.data_loader` and calls `load_decisions`, `load_search`,
# `load_booking` — this one walks through the three loading modes and
# shows the shape of each dataset.
#
# **Modes:**
# - `local_minio` — compose stack MinIO via DuckDB `httpfs` (dev only).
# - `synthetic` — deterministic in-notebook generator (works on Colab,
#   no external data needed).
# - `snapshot` — Parquet download from an operator-published URL
#   (stub; landing when an export script exists).
#
# The synthetic generator bakes realistic elasticity into the data
# (higher tier → more clicks, higher price → more walkoffs, treatment
# arm walks off more above €55) so downstream notebooks produce
# sensible outputs even without real events.

# %% [markdown]
# ## Colab bootstrap
#
# Uncomment and run this cell on Google Colab. Skip locally.

# %%
# !pip -q install duckdb pandas matplotlib scipy pyarrow
# !mkdir -p /content/lib
# !curl -sL https://raw.githubusercontent.com/helmedeiros/pricing-observability/main/notebooks/lib/data_loader.py -o /content/lib/data_loader.py
# !touch /content/lib/__init__.py
# import sys; sys.path.insert(0, '/content')

# %% [markdown]
# ## Local bootstrap
#
# Add the notebooks directory to the path so `lib.data_loader`
# imports cleanly. Skip on Colab.

# %%
import os
import sys

_here = os.path.abspath("")
if os.path.basename(_here) == "analytics":
    _here = os.path.dirname(_here)
sys.path.insert(0, _here)

from lib.data_loader import (
    load_decisions,
    load_search,
    load_booking,
    synthetic_dataset,
    MinioConfig,
)

# %% [markdown]
# ## Mode 1: synthetic
#
# Zero external dependencies. Deterministic per `seed`. Runs on Colab
# with nothing configured.

# %%
d_syn, s_syn, b_syn = synthetic_dataset(rows=2000, seed=42)
print(f"decisions: {len(d_syn):>6}  columns: {len(d_syn.columns)}")
print(f"search:    {len(s_syn):>6}  columns: {len(s_syn.columns)}")
print(f"booking:   {len(b_syn):>6}  columns: {len(b_syn.columns)}")

# %%
d_syn.head(3)

# %%
s_syn.head(3)

# %%
b_syn.head(3)

# %% [markdown]
# ## Mode 2: local_minio
#
# Pulls from the compose-stack MinIO via DuckDB's `httpfs` extension.
# Only works when the compose stack is running locally. Skip cells
# below if you're on Colab.

# %%
try:
    d_live = load_decisions(mode="local_minio")
    s_live = load_search(mode="local_minio")
    b_live = load_booking(mode="local_minio")
    print(f"LIVE decisions: {len(d_live):>7}")
    print(f"LIVE search:    {len(s_live):>7}")
    print(f"LIVE booking:   {len(b_live):>7}")
except Exception as e:
    print(f"local_minio unavailable ({e.__class__.__name__}): fall back to synthetic.")

# %% [markdown]
# ## Mode 3: snapshot (stub)
#
# When an operator-run export job publishes Parquet extracts to an
# HTTPS URL, replace the stub with the URL. Colab users unable to
# access MinIO get real data via this path.

# %%
# d = load_decisions(mode="snapshot", url="https://example.internal/decisions.parquet")

# %% [markdown]
# ## Schema quick-reference
#
# Each dataset carries the fields downstream notebooks depend on:

# %%
def _schema(df, name, keys):
    have = [k for k in keys if k in df.columns]
    miss = [k for k in keys if k not in df.columns]
    print(f"{name}: OK={have}  MISSING={miss}")

_schema(d_syn, "decisions", ["decision_id", "rule", "markup_factor", "rc_customer_tier", "rc_country", "rc_amount", "rc_journey_id", "experiment"])
_schema(s_syn, "search", ["decision_id", "journey_id", "search_id", "customer_tier", "country", "price", "position", "experiment", "variant"])
_schema(b_syn, "booking", ["decision_id", "journey_id", "booking_id", "event_type", "price", "phase", "revenue", "experiment", "variant"])

# %% [markdown]
# ## Cross-references
#
# The load-bearing keys per pricing-observability ADR-0020:
#
# - `decision_id` connects `decisions` ⇔ `search` ⇔ `booking`.
# - `journey_id` groups all events in one session.
# - `search_id` groups the N offers shown in one render.

# %%
# Sanity: how many search offers link back to a decision?
matched = s_syn.merge(d_syn[["decision_id"]], on="decision_id", how="inner")
print(f"search offers with matching decision: {len(matched)} / {len(s_syn)}")

# %% [markdown]
# ## What's next
#
# - `10-decisions-overview` — decisions by rule, adapter, hour.
# - `11-funnel-overview` — impressions → clicks → init → reserve → purchase.
# - `30-elasticity-baseline` — overall elasticity + bootstrap CI.
# - `50-experiment-lift` — A/B lift with statistical significance.
# - `60-rule-proposal` — proposed new rules from segment × elasticity.
