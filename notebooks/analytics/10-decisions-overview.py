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
# # 10 — Decisions overview
#
# Descriptive view of the `markup.decision.v1` stream. What rules are
# firing, how often, on what shapes. No joins yet — this is the
# pricing-side descriptive slice before we correlate with outcomes.

# %%
import os
import sys

_here = os.path.abspath("")
if os.path.basename(_here) == "analytics":
    _here = os.path.dirname(_here)
sys.path.insert(0, _here)

import matplotlib.pyplot as plt
import pandas as pd

from lib.data_loader import load_decisions, synthetic_dataset

# %% [markdown]
# ## Load
#
# Try MinIO; fall back to synthetic so this notebook always runs.

# %%
try:
    df = load_decisions(mode="local_minio")
    source = "local_minio"
except Exception:
    df, _, _ = synthetic_dataset(rows=3000, seed=42)
    source = "synthetic"

print(f"source={source}  rows={len(df):,}")

# %% [markdown]
# ## Filter to `ok` outcomes
#
# `no_match` / `error` / `canceled` / `deadline_exceeded` are separate
# operational concerns and skew the descriptive stats.

# %%
if "decide_outcome" in df.columns:
    ok = df[df["decide_outcome"] == "ok"].copy()
else:
    ok = df.copy()
print(f"ok rows: {len(ok):,}")

# %% [markdown]
# ## Rule fire counts

# %%
rule_counts = ok["rule"].value_counts().to_frame("fires")
rule_counts["share"] = (rule_counts["fires"] / rule_counts["fires"].sum()).round(4)
rule_counts

# %%
ax = rule_counts["fires"].plot(kind="barh", figsize=(8, 3))
ax.set_xlabel("fires")
ax.set_title("rule fires (ok outcomes)")
plt.tight_layout()
plt.show()

# %% [markdown]
# ## Markup factor distribution

# %%
ok["markup_factor"].describe().round(4)

# %%
ax = ok["markup_factor"].plot(kind="hist", bins=20, figsize=(8, 3))
ax.set_xlabel("markup_factor")
ax.set_title("markup factor distribution")
plt.tight_layout()
plt.show()

# %% [markdown]
# ## Per-rule markup factor

# %%
per_rule = ok.groupby("rule")["markup_factor"].describe().round(4)
per_rule

# %% [markdown]
# ## Latency distribution (`duration_ms`)
#
# The wall-clock p50 / p95 / p99 of the `/decide` handler envelope
# (matches `markup_decide_duration_seconds` histogram in Prometheus).

# %%
if "duration_ms" in ok.columns:
    q = ok["duration_ms"].quantile([0.5, 0.95, 0.99]).round(3)
    print(q.to_string())
    ax = ok["duration_ms"].clip(upper=ok["duration_ms"].quantile(0.99)).plot(kind="hist", bins=40, figsize=(8, 3))
    ax.set_xlabel("duration_ms (clipped at p99)")
    ax.set_title("decide handler wall-clock")
    plt.tight_layout()
    plt.show()

# %% [markdown]
# ## Experiment breakdown
#
# What fraction of decisions carried an experiment label. Empty
# experiment == baseline; populated == arm assignment from
# markup-svc's router.

# %%
if "experiment" in ok.columns:
    exp = ok["experiment"].fillna("(none)").replace("", "(none)").value_counts().to_frame("fires")
    exp["share"] = (exp["fires"] / exp["fires"].sum()).round(4)
    exp

# %% [markdown]
# ## Per-country slice

# %%
if "rc_country" in ok.columns:
    by_country = ok.groupby("rc_country").agg(
        fires=("decision_id", "count"),
        avg_markup=("markup_factor", "mean"),
    ).round(4).sort_values("fires", ascending=False)
    by_country

# %% [markdown]
# ## What's next
#
# - `11-funnel-overview` — connect these decisions to the search /
#   booking events to see conversion per rule.
# - `20-rules-performance` — same view but joined against outcomes.
