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
# # 50 — Experiment lift
#
# A/B analysis for one experiment. Groups impressions by variant,
# computes:
#
# - **Conversion per arm** (Wilson CI).
# - **Absolute and relative lift** vs the control arm.
# - **Two-proportion z-test** for the arm vs control comparison.
# - **Minimum detectable effect** given the observed sample size.
#
# `experiment` and `variant` are stamped on every `search.v1` +
# `booking.v1` event per funnel-sim ADR-0002 / ADR-0003, so this is
# a single-table window function per event stream — no re-join to the
# decision event needed for arm-level analysis.

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
try:
    search = load_search(mode="local_minio")
    booking = load_booking(mode="local_minio")
    if search["experiment"].fillna("").eq("").all():
        # No arm labels in live data → synthetic (which does bake arms in).
        raise RuntimeError("no experiment labels in live data")
    source = "local_minio"
except Exception as e:
    _, search, booking = synthetic_dataset(rows=8000, seed=42)
    source = f"synthetic (live insufficient: {e.__class__.__name__})"

print(f"source={source}  search={len(search):,}  booking={len(booking):,}")

# %% [markdown]
# ## Experiments present in the data

# %%
exp_counts = (search.assign(experiment=search["experiment"].fillna("").replace("", "(none)"))
              .groupby("experiment").size().rename("impressions"))
exp_counts

# %% [markdown]
# ## Pick an experiment
#
# Drop `(none)` — that's baseline traffic without an arm assignment.
# Change `EXPERIMENT` to any label from the table above.

# %%
non_none = [x for x in exp_counts.index if x != "(none)"]
EXPERIMENT = non_none[0] if non_none else None
print(f"analyzing: {EXPERIMENT}")

# %% [markdown]
# ## Impressions + purchases per arm

# %%
purchased = booking[booking["event_type"] == "booking.purchased"][["decision_id"]].drop_duplicates()
purchased["purchased"] = 1

exp_search = search[search["experiment"] == EXPERIMENT].copy() if EXPERIMENT else search.iloc[0:0]
joined = exp_search.merge(purchased, on="decision_id", how="left").fillna({"purchased": 0})
joined["purchased"] = joined["purchased"].astype(int)

arms = joined.groupby("variant").agg(
    impressions=("purchased", "size"),
    purchases=("purchased", "sum"),
    avg_price=("price", "mean"),
).round(4)
arms["conversion"] = (arms["purchases"] / arms["impressions"]).round(4)
arms

# %% [markdown]
# ## Wilson CIs per arm

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

arms[["ci_low", "ci_high"]] = arms.apply(
    lambda r: pd.Series(wilson_ci(int(r["purchases"]), int(r["impressions"]))),
    axis=1,
).round(4)
arms

# %% [markdown]
# ## Lift vs control
#
# Convention: variant named `"control"` is the baseline. If your
# convention differs, set `CONTROL_NAME` to the right label.

# %%
CONTROL_NAME = "control"

if CONTROL_NAME in arms.index:
    control_p = arms.loc[CONTROL_NAME, "conversion"]
    lift = arms.copy()
    lift["absolute_lift"] = (lift["conversion"] - control_p).round(4)
    lift["relative_lift_pct"] = ((lift["conversion"] / control_p - 1) * 100).round(2)
    lift
else:
    print(f"no arm named {CONTROL_NAME!r}; adjust CONTROL_NAME and rerun")
    lift = arms

# %% [markdown]
# ## Two-proportion z-test
#
# For every non-control arm vs control:
#
# $$ z = \frac{\hat{p}_A - \hat{p}_B}{\sqrt{\hat{p}(1-\hat{p})(1/n_A + 1/n_B)}} $$
# where $\hat{p}$ is the pooled rate.

# %%
def two_prop_ztest(k_a: int, n_a: int, k_b: int, n_b: int):
    p_a = k_a / n_a
    p_b = k_b / n_b
    p_pool = (k_a + k_b) / (n_a + n_b)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        return float("nan"), float("nan")
    z = (p_a - p_b) / se
    p_value = 2 * (1 - norm.cdf(abs(z)))
    return z, p_value

if CONTROL_NAME in arms.index and len(arms) > 1:
    k_c, n_c = int(arms.loc[CONTROL_NAME, "purchases"]), int(arms.loc[CONTROL_NAME, "impressions"])
    tests = []
    for arm in arms.index:
        if arm == CONTROL_NAME:
            continue
        k_a, n_a = int(arms.loc[arm, "purchases"]), int(arms.loc[arm, "impressions"])
        z, p = two_prop_ztest(k_a, n_a, k_c, n_c)
        tests.append({"arm": arm, "z": round(z, 3), "p_value": round(p, 4),
                      "significant_at_005": p < 0.05})
    pd.DataFrame(tests)

# %% [markdown]
# ## Minimum detectable effect (MDE)
#
# Given the sample sizes you already have, what's the smallest true
# lift you could reliably detect at 80% power / 5% significance?

# %%
def mde(n_control: int, baseline_rate: float, alpha: float = 0.05, power: float = 0.80) -> float:
    z_alpha = norm.ppf(1 - alpha / 2)
    z_beta = norm.ppf(power)
    var = baseline_rate * (1 - baseline_rate)
    # simplistic: symmetric n per arm; MDE as absolute proportion
    return (z_alpha + z_beta) * np.sqrt(2 * var / n_control)

if CONTROL_NAME in arms.index:
    n_c = int(arms.loc[CONTROL_NAME, "impressions"])
    p_c = float(arms.loc[CONTROL_NAME, "conversion"])
    print(f"MDE at 80% power: {mde(n_c, p_c) * 100:.2f} percentage points")
    print(f"(control p={p_c*100:.2f}%, n={n_c:,})")

# %% [markdown]
# ## Conversion bar plot with CIs

# %%
if len(arms):
    fig, ax = plt.subplots(figsize=(8, 3))
    xs = range(len(arms))
    ax.bar(xs, arms["conversion"])
    ax.errorbar(xs, arms["conversion"],
                yerr=[arms["conversion"] - arms["ci_low"], arms["ci_high"] - arms["conversion"]],
                fmt="none", color="black", capsize=5)
    ax.set_xticks(xs)
    ax.set_xticklabels(arms.index)
    ax.set_ylabel("conversion rate")
    ax.set_title(f"{EXPERIMENT} — conversion per arm (95% CI) — {source}")
    plt.tight_layout()
    plt.show()

# %% [markdown]
# ## What's next
#
# - `53-experiment-drilldown` (Tier 3) — lift per segment inside one
#   experiment, so a null aggregate lift can be decomposed into
#   segments-that-moved and segments-that-didn't.
# - `60-rule-proposal` — take a winning arm's rule and propose it as
#   the new baseline.
