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
# # 30 — Elasticity baseline
#
# Overall price elasticity of demand from the impressions and
# purchases in the funnel-events bucket. Two estimators land here:
#
# 1. **Segmented ratio elasticity** — bucket by price decile, compute
#    conversion per bucket, fit a log-log line and read the slope.
# 2. **Bootstrap confidence interval** — resample impressions with
#    replacement to bound the coefficient's uncertainty.
#
# Follow-on `31-elasticity-per-segment` runs the same pipeline per
# customer_tier / country / channel.

# %%
import os
import sys

_here = os.path.abspath("")
if os.path.basename(_here) == "analytics":
    _here = os.path.dirname(_here)
sys.path.insert(0, _here)

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from lib.data_loader import load_search, load_booking, synthetic_dataset

# %%
try:
    search = load_search(mode="local_minio")
    booking = load_booking(mode="local_minio")
    source = "local_minio"
    if len(search) < 300:
        raise RuntimeError("not enough live data for a stable estimate")
except Exception as e:
    _, search, booking = synthetic_dataset(rows=5000, seed=42)
    source = f"synthetic (live insufficient: {e.__class__.__name__})"

print(f"source={source}  search={len(search):,}  booking={len(booking):,}")

# %% [markdown]
# ## Impressions ⨝ purchases
#
# LEFT JOIN so unclicked impressions stay in the denominator.

# %%
purchased = booking[booking["event_type"] == "booking.purchased"][["decision_id"]].drop_duplicates()
purchased["purchased"] = 1
joined = search.merge(purchased, on="decision_id", how="left").fillna({"purchased": 0})
joined["purchased"] = joined["purchased"].astype(int)
print(f"impressions: {len(joined):,}   purchases: {int(joined['purchased'].sum()):,}   "
      f"conversion: {joined['purchased'].mean() * 100:.2f}%")

# %% [markdown]
# ## Price-decile view
#
# 10 buckets by shown price, one conversion rate per bucket.

# %%
joined["price_decile"] = pd.qcut(joined["price"], q=10, labels=False, duplicates="drop")
decile = joined.groupby("price_decile").agg(
    n=("purchased", "size"),
    purchases=("purchased", "sum"),
    avg_price=("price", "mean"),
).round(4)
decile["conversion"] = (decile["purchases"] / decile["n"]).round(4)
decile

# %%
fig, ax = plt.subplots(figsize=(8, 3))
ax.plot(decile["avg_price"], decile["conversion"], marker="o")
ax.set_xlabel("avg price per decile (€)")
ax.set_ylabel("conversion rate")
ax.set_title(f"conversion vs price — {source}")
plt.tight_layout()
plt.show()

# %% [markdown]
# ## Log-log elasticity
#
# `log(conversion) = intercept + elasticity * log(price)`. The slope
# is the price elasticity of demand. Only decile rows with at least
# one purchase are used (log(0) is undefined).

# %%
valid = decile[decile["conversion"] > 0].copy()
x = np.log(valid["avg_price"].to_numpy())
y = np.log(valid["conversion"].to_numpy())
slope, intercept = np.polyfit(x, y, 1)
print(f"elasticity coefficient (point estimate): {slope:.3f}")
print(f"intercept: {intercept:.3f}")

# %% [markdown]
# ## Bootstrap CI on the coefficient
#
# Resample the impressions table with replacement; recompute the
# decile pipeline; collect the slope. 500 iterations is enough for
# a reasonable CI on the point estimate; increase to 2000 for tighter
# bounds in production analysis.

# %%
rng = np.random.default_rng(42)
n_boot = 500
slopes = []
n = len(joined)

for _ in range(n_boot):
    idx = rng.integers(0, n, size=n)
    sample = joined.iloc[idx]
    try:
        sample["price_decile"] = pd.qcut(sample["price"], q=10, labels=False, duplicates="drop")
        d = sample.groupby("price_decile").agg(
            purchases=("purchased", "sum"),
            n=("purchased", "size"),
            avg_price=("price", "mean"),
        )
        d = d[d["purchases"] > 0]
        if len(d) < 3:
            continue
        s, _ = np.polyfit(np.log(d["avg_price"]), np.log(d["purchases"] / d["n"]), 1)
        slopes.append(s)
    except Exception:
        continue

slopes_arr = np.array(slopes)
lo, hi = np.percentile(slopes_arr, [2.5, 97.5])
print(f"bootstrap 95% CI on elasticity: [{lo:.3f}, {hi:.3f}]  (n_boot={len(slopes)})")

# %%
fig, ax = plt.subplots(figsize=(8, 3))
ax.hist(slopes_arr, bins=30)
ax.axvline(slope, color="red", label=f"point estimate {slope:.3f}")
ax.axvline(lo, color="orange", linestyle=":", label=f"CI [{lo:.3f}, {hi:.3f}]")
ax.axvline(hi, color="orange", linestyle=":")
ax.set_xlabel("elasticity coefficient")
ax.set_title("bootstrap distribution of the elasticity coefficient")
ax.legend()
plt.tight_layout()
plt.show()

# %% [markdown]
# ## Interpretation
#
# - **Elasticity < -1**: demand is elastic — a 1% price increase
#   drops demand by more than 1%. Cutting price grows revenue.
# - **Elasticity ~ -1**: unit elastic — revenue-maximizing point.
# - **Elasticity > -1** (closer to zero): inelastic — price increase
#   grows revenue.
#
# If the CI crosses zero, the estimate is not statistically
# distinguishable from "no relationship between price and demand"
# at this sample size — gather more data before acting on the number.

# %% [markdown]
# ## What's next
#
# - `31-elasticity-per-segment` — the same pipeline broken down by
#   customer_tier / country / channel to find where the demand curve
#   is steepest.
# - `60-rule-proposal` — combine segment × elasticity to propose
#   segment-specific pricing rules.
