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
# # 40 — Segment conversion
#
# Per-segment conversion rate with Wilson score confidence intervals.
# Segments = every (customer_tier, country, channel) tuple with at
# least `MIN_IMPRESSIONS` observations.
#
# Wilson interval (not the naive Normal) — small counts (< 30) or
# extreme rates (near 0 or 1) break the Normal approximation. Wilson
# is well-behaved across the whole [0, 1] range.

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
from scipy.stats import norm

from lib.data_loader import load_search, load_booking, synthetic_dataset

# %%
MIN_IMPRESSIONS = 30

try:
    search = load_search(mode="local_minio")
    booking = load_booking(mode="local_minio")
    if len(search) < 300:
        raise RuntimeError("too few live rows")
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

# %% [markdown]
# ## Wilson score CI
#
# $$\hat{p} \pm z \sqrt{\frac{\hat{p}(1-\hat{p})}{n} + \frac{z^2}{4n^2}}$$
# then divide by $(1 + z^2/n)$ for the correct-form Wilson.

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

# %% [markdown]
# ## Per-segment breakdown
#
# (customer_tier, country, channel) buckets. Segments with fewer than
# `MIN_IMPRESSIONS` are omitted — CIs would be too wide to be useful.

# %%
group_cols = ["customer_tier", "country", "channel"]
have_cols = [c for c in group_cols if c in joined.columns]

segments = joined.groupby(have_cols).agg(
    impressions=("purchased", "size"),
    purchases=("purchased", "sum"),
).reset_index()
segments = segments[segments["impressions"] >= MIN_IMPRESSIONS].copy()
segments["conversion"] = segments["purchases"] / segments["impressions"]
segments[["ci_low", "ci_high"]] = segments.apply(
    lambda r: pd.Series(wilson_ci(int(r["purchases"]), int(r["impressions"]))),
    axis=1,
)
segments["ci_width"] = segments["ci_high"] - segments["ci_low"]
segments = segments.sort_values("conversion", ascending=False).round(4)
segments

# %% [markdown]
# ## Segments sorted by conversion (top 10)

# %%
top10 = segments.head(10).copy()
if len(top10):
    labels = top10.apply(lambda r: " | ".join(str(r[c]) for c in have_cols), axis=1)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.errorbar(top10["conversion"], range(len(top10)),
                xerr=[top10["conversion"] - top10["ci_low"], top10["ci_high"] - top10["conversion"]],
                fmt="o", capsize=3)
    ax.set_yticks(range(len(top10)))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("conversion rate (95% CI)")
    ax.set_title(f"top-10 segments — {source}")
    plt.tight_layout()
    plt.show()

# %% [markdown]
# ## Baseline vs segment
#
# For a segment to be "meaningfully different", the CI must not
# overlap the platform-wide conversion baseline. Segments whose CI
# lies fully above / below the baseline are the ones worth investigating.

# %%
baseline = joined["purchased"].mean()
print(f"platform baseline conversion: {baseline * 100:.2f}%")

if len(segments):
    segments["above_baseline"] = segments["ci_low"] > baseline
    segments["below_baseline"] = segments["ci_high"] < baseline
    signal = segments[segments["above_baseline"] | segments["below_baseline"]]
    print(f"segments with CI clearly off baseline: {len(signal)} / {len(segments)}")
    signal[have_cols + ["impressions", "purchases", "conversion", "ci_low", "ci_high"]].round(4)

# %% [markdown]
# ## What's next
#
# - `31-elasticity-per-segment` — pair each segment with its own
#   elasticity coefficient to see where the demand curve is steepest.
# - `60-rule-proposal` — for segments significantly below baseline,
#   propose a discount rule; for those above, propose a premium.
