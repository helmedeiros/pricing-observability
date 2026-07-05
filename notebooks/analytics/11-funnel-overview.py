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
# # 11 — Funnel overview
#
# End-to-end drop-off through the customer journey:
#
# ```
# impressions → clicks (booking.initiated)
#             → reservations (booking.reserved)
#             → purchases (booking.purchased)
#
# with terminal timeouts branching off at each post-init phase.
# ```
#
# Uses the correlation contract from pricing-observability ADR-0020:
# `search.v1.offers[].decision_id` → `booking.v1.decision_id`.

# %%
import os
import sys

_here = os.path.abspath("")
if os.path.basename(_here) == "analytics":
    _here = os.path.dirname(_here)
sys.path.insert(0, _here)

import matplotlib.pyplot as plt
import pandas as pd

from lib.data_loader import load_search, load_booking, synthetic_dataset

# %%
try:
    search = load_search(mode="local_minio")
    booking = load_booking(mode="local_minio")
    source = "local_minio"
    if len(search) < 50 or len(booking) < 50:
        raise RuntimeError("not enough live data")
except Exception as e:
    _, search, booking = synthetic_dataset(rows=3000, seed=42)
    source = f"synthetic (live insufficient: {e.__class__.__name__})"

print(f"source={source}  search={len(search):,}  booking={len(booking):,}")

# %% [markdown]
# ## Funnel counters
#
# Impressions = one per offer shown. Clicks / reserves / purchases /
# timeouts join back on `decision_id`.

# %%
impressions = len(search)
by_type = booking.groupby("event_type").size().to_dict() if "event_type" in booking.columns else {}
clicks    = by_type.get("booking.initiated", 0)
reserves  = by_type.get("booking.reserved", 0)
purchases = by_type.get("booking.purchased", 0)
timeouts  = by_type.get("booking.timeout", 0)

pd.DataFrame({
    "stage":  ["impressions", "clicks", "reserves", "purchases", "timeouts"],
    "count":  [impressions, clicks, reserves, purchases, timeouts],
}).set_index("stage")

# %% [markdown]
# ## Drop-off rates

# %%
def pct(n, d):
    return round(100.0 * n / d, 2) if d else float("nan")

drop = pd.DataFrame({
    "transition": [
        "impressions → clicks",
        "clicks → reserves",
        "reserves → purchases",
    ],
    "kept_pct": [pct(clicks, impressions), pct(reserves, clicks), pct(purchases, reserves)],
    "dropped_pct": [pct(impressions - clicks, impressions),
                    pct(clicks - reserves, clicks),
                    pct(reserves - purchases, reserves)],
})
drop

# %% [markdown]
# ## Timeout split by phase
#
# `phase=initiated` = price-shock cohort (walked before providing
# info). `phase=reserved` = payment-friction cohort. Different
# analytical meaning per funnel-sim ADR-0003.

# %%
if "phase" in booking.columns:
    timeouts_df = booking[booking["event_type"] == "booking.timeout"]
    phase_split = timeouts_df["phase"].value_counts().to_frame("timeouts")
    phase_split["share"] = (phase_split["timeouts"] / phase_split["timeouts"].sum()).round(4)
    phase_split
else:
    print("no phase column — booking.timeout events not present")

# %% [markdown]
# ## Funnel plot

# %%
stages = ["impressions", "clicks", "reserves", "purchases"]
counts = [impressions, clicks, reserves, purchases]
fig, ax = plt.subplots(figsize=(8, 3))
ax.barh(stages[::-1], counts[::-1])
ax.set_xlabel("count")
ax.set_title(f"funnel — {source}")
for i, c in enumerate(counts[::-1]):
    ax.text(c, i, f" {c}", va="center")
plt.tight_layout()
plt.show()

# %% [markdown]
# ## Per-segment funnel (customer_tier)

# %%
if "customer_tier" in search.columns and "decision_id" in booking.columns:
    imp = search.groupby("customer_tier").size().rename("impressions")
    pur = (booking[booking["event_type"] == "booking.purchased"]
             .merge(search[["decision_id", "customer_tier"]].drop_duplicates(), on="decision_id", how="inner")
             .groupby("customer_tier").size().rename("purchases"))
    seg = pd.concat([imp, pur], axis=1).fillna(0).astype(int)
    seg["conversion_pct"] = (100.0 * seg["purchases"] / seg["impressions"]).round(2)
    seg.sort_values("conversion_pct", ascending=False)

# %% [markdown]
# ## Per-segment funnel (country)

# %%
if "country" in search.columns:
    imp = search.groupby("country").size().rename("impressions")
    pur = (booking[booking["event_type"] == "booking.purchased"]
             .merge(search[["decision_id", "country"]].drop_duplicates(), on="decision_id", how="inner")
             .groupby("country").size().rename("purchases"))
    seg_c = pd.concat([imp, pur], axis=1).fillna(0).astype(int)
    seg_c["conversion_pct"] = (100.0 * seg_c["purchases"] / seg_c["impressions"]).round(2)
    seg_c.sort_values("conversion_pct", ascending=False)

# %% [markdown]
# ## What's next
#
# - `30-elasticity-baseline` — the elasticity coefficient from these
#   impressions and purchases.
# - `40-segment-conversion` — same segment views with statistical
#   significance / confidence intervals.
# - `50-experiment-lift` — per-arm funnel with lift and p-value.
