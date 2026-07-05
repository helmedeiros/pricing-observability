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
# # 60 — Rule proposal
#
# Prescriptive analytics: given the segment × conversion table and
# the elasticity coefficient, propose one or more new `markup-svc`
# rules and estimate their impact.
#
# **Proposal criteria** (a segment gets a rule proposal when ALL hold):
#
# 1. Segment has ≥ `MIN_IMPRESSIONS` impressions (statistical mass).
# 2. Conversion is meaningfully below the platform baseline
#    (`ci_high < baseline` — see `40-segment-conversion` for the Wilson CI).
# 3. Estimated elasticity < `ELASTICITY_THRESHOLD` (demand responds
#    to price cuts).
#
# **Output**:
# - Proposed rule as a CSV row that can be pasted into markup-svc's
#   `rules.csv`.
# - Rationale block (segment description + expected lift).
# - Shadow-mode simulation stub (see `Not-closed` at bottom).

# %%
import os
import sys

_here = os.path.abspath("")
if os.path.basename(_here) == "analytics":
    _here = os.path.dirname(_here)
sys.path.insert(0, _here)

import numpy as np
import pandas as pd
from scipy.stats import norm

from lib.data_loader import load_search, load_booking, synthetic_dataset

# %%
MIN_IMPRESSIONS = 30
ELASTICITY_THRESHOLD = -1.0  # elastic → price cut expected to grow revenue
DISCOUNT_STEP = 0.05         # propose 5% discount

# %%
try:
    search = load_search(mode="local_minio")
    booking = load_booking(mode="local_minio")
    if len(search) < 500:
        raise RuntimeError("live data too sparse for proposal math")
    source = "local_minio"
except Exception as e:
    _, search, booking = synthetic_dataset(rows=8000, seed=42)
    source = f"synthetic (live insufficient: {e.__class__.__name__})"

print(f"source={source}  search={len(search):,}  booking={len(booking):,}")

# %% [markdown]
# ## Impressions ⨝ purchases

# %%
purchased = booking[booking["event_type"] == "booking.purchased"][["decision_id"]].drop_duplicates()
purchased["purchased"] = 1
joined = search.merge(purchased, on="decision_id", how="left").fillna({"purchased": 0})
joined["purchased"] = joined["purchased"].astype(int)

baseline = joined["purchased"].mean()
print(f"platform baseline conversion: {baseline * 100:.2f}%")

# %% [markdown]
# ## Segment table with Wilson CI

# %%
def wilson_ci(k: int, n: int, alpha: float = 0.05):
    if n == 0:
        return (float("nan"), float("nan"))
    z = norm.ppf(1 - alpha / 2)
    p = k / n
    denom = 1 + z ** 2 / n
    center = (p + z ** 2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n * n)) / denom
    return (center - half, center + half)

group_cols = [c for c in ["customer_tier", "country", "channel"] if c in joined.columns]

segments = joined.groupby(group_cols).agg(
    impressions=("purchased", "size"),
    purchases=("purchased", "sum"),
    avg_price=("price", "mean"),
).reset_index()
segments = segments[segments["impressions"] >= MIN_IMPRESSIONS].copy()
segments["conversion"] = segments["purchases"] / segments["impressions"]
segments[["ci_low", "ci_high"]] = segments.apply(
    lambda r: pd.Series(wilson_ci(int(r["purchases"]), int(r["impressions"]))),
    axis=1,
)

# %% [markdown]
# ## Per-segment elasticity
#
# Simple log-log fit on price-decile buckets restricted to the
# segment. Requires ≥ 3 populated deciles — segments with narrow
# price distributions fall out here.

# %%
def segment_elasticity(sub: pd.DataFrame) -> float:
    if len(sub) < 30:
        return float("nan")
    sub = sub.copy()
    sub["price_bucket"] = pd.qcut(sub["price"], q=5, labels=False, duplicates="drop")
    d = sub.groupby("price_bucket").agg(
        n=("purchased", "size"),
        purchases=("purchased", "sum"),
        avg_price=("price", "mean"),
    )
    d = d[d["purchases"] > 0]
    if len(d) < 3:
        return float("nan")
    x = np.log(d["avg_price"].to_numpy())
    y = np.log((d["purchases"] / d["n"]).to_numpy())
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)

segments["elasticity"] = segments.apply(
    lambda r: segment_elasticity(
        joined[np.logical_and.reduce([joined[c] == r[c] for c in group_cols])]
    ),
    axis=1,
)
segments["elasticity"] = segments["elasticity"].round(3)
segments["conversion"] = segments["conversion"].round(4)

# %% [markdown]
# ## Candidate segments
#
# Filter by the three criteria above.

# %%
candidates = segments[
    (segments["ci_high"] < baseline)
    & (segments["elasticity"] < ELASTICITY_THRESHOLD)
    & segments["elasticity"].notna()
].copy()

candidates = candidates.sort_values(["elasticity", "conversion"])
candidates[group_cols + ["impressions", "purchases", "conversion", "elasticity", "avg_price"]].round(4)

# %% [markdown]
# ## Expected impact per candidate
#
# Approximate the effect of a `DISCOUNT_STEP` price cut:
#
# - New conversion ≈ current × (1 − elasticity × discount)
#   (log-linear approximation; only reasonable for small discounts).
# - Revenue change ≈ new_conversion / old_conversion × (1 − discount) − 1.

# %%
candidates["proj_conversion"] = candidates["conversion"] * (1 - candidates["elasticity"] * DISCOUNT_STEP)
candidates["proj_revenue_change_pct"] = (
    candidates["proj_conversion"] / candidates["conversion"] * (1 - DISCOUNT_STEP) - 1
) * 100
candidates[group_cols + ["conversion", "elasticity", "proj_conversion", "proj_revenue_change_pct"]].round(4)

# %% [markdown]
# ## Emit as markup-svc rule CSV rows
#
# markup-svc's rule format: `name,condition,factor,priority`. The
# proposed rule sets a factor of `1.00 - DISCOUNT_STEP` (5% discount
# by default) with a low priority so it fires ONLY when no
# higher-priority rule matches — safest rollout posture.

# %%
def to_condition(row) -> str:
    parts = []
    for c in group_cols:
        parts.append(f"{c} == '{row[c]}'")
    return " AND ".join(parts)

def to_rule_name(row) -> str:
    return "proposed_" + "_".join(str(row[c]).lower() for c in group_cols) + f"_disc{int(DISCOUNT_STEP*100)}"

candidates["rule_name"] = candidates.apply(to_rule_name, axis=1)
candidates["condition"] = candidates.apply(to_condition, axis=1)
candidates["factor"] = round(1.0 - DISCOUNT_STEP, 4)
candidates["priority"] = 1  # low priority — falls through if enterprise/br_peak etc. matched

csv_rows = candidates[["rule_name", "condition", "factor", "priority"]].rename(
    columns={"rule_name": "name"}
).to_csv(index=False, quoting=1)

print("=== PROPOSED rules.csv rows ===")
print(csv_rows)

# %% [markdown]
# ## Human-readable rationale

# %%
for _, row in candidates.iterrows():
    seg_desc = " / ".join(f"{c}={row[c]}" for c in group_cols)
    print(f"— Segment: {seg_desc}")
    print(f"  Impressions: {int(row['impressions']):,}  Conversion: {row['conversion']*100:.2f}%  "
          f"(baseline {baseline*100:.2f}%)")
    print(f"  Elasticity: {row['elasticity']:.2f}  (< {ELASTICITY_THRESHOLD}, price-sensitive)")
    print(f"  Proposed: {int(DISCOUNT_STEP*100)}% discount → projected conversion "
          f"{row['proj_conversion']*100:.2f}%, revenue change {row['proj_revenue_change_pct']:+.2f}%")
    print()

# %% [markdown]
# ## Not-closed
#
# - **Shadow-mode simulation stub.** The projected impact above is a
#   log-linear approximation. Real evaluation replays the proposed
#   rule against historic decisions and computes the counter-factual.
#   Requires a bre-go engine binding from Python — parked.
# - **Multi-rule interaction.** A proposal that would fire for a
#   segment already covered by a higher-priority rule effectively
#   does nothing. Need to walk the priority ladder and simulate
#   which rule wins per row.
# - **Guardrail check.** Proposed factor should be validated against
#   markup-svc guardrails before deploy (min factor 0.7, max 1.4 by
#   default per markup-svc guardrails config).
# - **Elasticity confidence.** Segments with a marginally-elastic
#   coefficient (say -0.9 to -1.1) may not be reliably elastic; add
#   a bootstrap CI on the segment coefficient before promoting.
