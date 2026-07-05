"""Data loader for the Pricing Analytics notebooks.

Three modes so every notebook runs anywhere:

    load_decisions(mode='local_minio')  # compose stack MinIO via httpfs
    load_decisions(mode='synthetic')    # in-notebook generation, works on Colab
    load_decisions(mode='snapshot', url='https://...')  # Parquet download (stub)

Every loader returns a pandas DataFrame with a stable column set derived
from the ADR-0035 (markup.decision.v1) and funnel-sim ADR-0002 / ADR-0003
schemas. Notebooks join across the three DataFrames on decision_id,
journey_id, and search_id per pricing-observability ADR-0020.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Literal, Optional

import duckdb
import numpy as np
import pandas as pd

Mode = Literal["local_minio", "synthetic", "snapshot"]


@dataclass
class MinioConfig:
    """Compose-stack MinIO defaults. Override via kwargs when hitting a
    different endpoint."""

    endpoint: str = "localhost:9000"
    access_key: str = "minio"
    secret_key: str = "minio12345"
    use_ssl: bool = False


def _duckdb_with_httpfs(cfg: MinioConfig) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_endpoint = '{cfg.endpoint}';")
    con.execute(f"SET s3_access_key_id = '{cfg.access_key}';")
    con.execute(f"SET s3_secret_access_key = '{cfg.secret_key}';")
    con.execute(f"SET s3_use_ssl = {'true' if cfg.use_ssl else 'false'};")
    con.execute("SET s3_url_style = 'path';")
    return con


# ----------------------------------------------------------------------
# markup.decision.v1
# ----------------------------------------------------------------------

_DECISIONS_GLOB = "s3://markup-decisions/markup-decision-v1/dt=*/hour=*/env=*/instance=*/*.jsonl.gz"


def load_decisions(
    mode: Mode = "local_minio",
    minio: Optional[MinioConfig] = None,
    rows: int = 5000,
    seed: int = 42,
    url: Optional[str] = None,
) -> pd.DataFrame:
    """Load markup.decision.v1 events into a DataFrame."""

    if mode == "local_minio":
        con = _duckdb_with_httpfs(minio or MinioConfig())
        df = con.execute(
            f"SELECT * FROM read_json_auto('{_DECISIONS_GLOB}', hive_partitioning=true, ignore_errors=true)"
        ).df()
        return _normalize_decisions(df)

    if mode == "synthetic":
        return _synthetic_decisions(rows=rows, seed=seed)

    if mode == "snapshot":
        if not url:
            raise ValueError("snapshot mode requires url=...")
        return pd.read_parquet(url)

    raise ValueError(f"unknown mode: {mode}")


def _normalize_decisions(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    # Lift a few request_context fields into top-level columns for ergonomic access.
    if "request_context" in df.columns:
        rc = pd.json_normalize(df["request_context"])
        for col in ("product_id", "category", "customer_tier", "channel", "country",
                    "inventory", "time_window", "amount", "journey_id"):
            if col in rc.columns:
                df[f"rc_{col}"] = rc[col].values
    return df


# ----------------------------------------------------------------------
# search.v1
# ----------------------------------------------------------------------

_SEARCH_GLOB = "s3://funnel-events/search-v1/dt=*/hour=*/env=*/instance=*/*.jsonl.gz"


def load_search(
    mode: Mode = "local_minio",
    minio: Optional[MinioConfig] = None,
    rows: int = 500,
    seed: int = 42,
    url: Optional[str] = None,
) -> pd.DataFrame:
    """Load search.v1 events, offers[] unnested to one row per offer."""

    if mode == "local_minio":
        con = _duckdb_with_httpfs(minio or MinioConfig())
        # Unnest offers[] so each row is (journey_id, search_id, one offer).
        df = con.execute(
            f"""
            WITH raw AS (
                SELECT journey_id, search_id, ts, env, query, UNNEST(offers) AS offer
                FROM read_json_auto('{_SEARCH_GLOB}', hive_partitioning=true, ignore_errors=true)
            )
            SELECT
                journey_id,
                search_id,
                ts,
                env,
                query.customer_tier    AS customer_tier,
                query.country          AS country,
                query.channel          AS channel,
                query.device           AS device,
                query.route            AS route,
                query.departure        AS departure,
                query.passengers       AS passengers,
                offer.offer_id         AS offer_id,
                offer.decision_id      AS decision_id,
                offer.position         AS position,
                offer.price            AS price,
                offer.markup_factor    AS markup_factor,
                offer.experiment       AS experiment,
                offer.variant          AS variant
            FROM raw
            """
        ).df()
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        return df

    if mode == "synthetic":
        return _synthetic_search(rows=rows, seed=seed)

    if mode == "snapshot":
        if not url:
            raise ValueError("snapshot mode requires url=...")
        return pd.read_parquet(url)

    raise ValueError(f"unknown mode: {mode}")


# ----------------------------------------------------------------------
# booking.v1
# ----------------------------------------------------------------------

_BOOKING_GLOB = "s3://funnel-events/booking-v1/dt=*/hour=*/env=*/event_type=*/instance=*/*.jsonl.gz"


def load_booking(
    mode: Mode = "local_minio",
    minio: Optional[MinioConfig] = None,
    rows: int = 500,
    seed: int = 42,
    url: Optional[str] = None,
) -> pd.DataFrame:
    """Load booking.v1 events across all event_type partitions."""

    if mode == "local_minio":
        con = _duckdb_with_httpfs(minio or MinioConfig())
        df = con.execute(
            f"SELECT * FROM read_json_auto('{_BOOKING_GLOB}', hive_partitioning=true, ignore_errors=true)"
        ).df()
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        return df

    if mode == "synthetic":
        return _synthetic_booking(rows=rows, seed=seed)

    if mode == "snapshot":
        if not url:
            raise ValueError("snapshot mode requires url=...")
        return pd.read_parquet(url)

    raise ValueError(f"unknown mode: {mode}")


# ----------------------------------------------------------------------
# Synthetic dataset — realistic-shape data for Colab / no-real-data runs
# ----------------------------------------------------------------------

_TIERS = ["enterprise", "consumer", "gold", "silver"]
_COUNTRIES = ["DE", "FR", "ES", "IT", "BR"]
_CHANNELS = ["web", "mobile", "partner"]
_DEVICES = ["desktop", "mobile", "tablet"]
_ROUTES = ["BR-DE", "FR-DE", "ES-IT", "DE-FR", "IT-DE"]
_RULES = ["enterprise", "br_peak", "default_consumer", "gold_off_peak"]
_EXPERIMENTS = ["", "BR_peak_uplift_v3", "gold_discount_v1"]


def _hex_id(rng: np.random.Generator) -> str:
    return rng.bytes(16).hex()


def synthetic_dataset(rows: int = 5000, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return coherent (decisions, search_offers, booking) with cross-references
    on decision_id / journey_id / search_id.

    Elasticity is baked into the generator: higher-tier customers convert
    more; higher-priced offers convert less; the treatment arm walks off
    at init 5 percentage points more than control at prices above €55.
    """

    rng = np.random.default_rng(seed)

    # Journeys — each yields one search with 3-5 offers.
    n_journeys = max(1, rows // 8)
    journeys = []
    for _ in range(n_journeys):
        tier = rng.choice(_TIERS, p=[0.15, 0.40, 0.30, 0.15])
        country = rng.choice(_COUNTRIES)
        channel = rng.choice(_CHANNELS, p=[0.60, 0.30, 0.10])
        device = rng.choice(_DEVICES, p=[0.55, 0.35, 0.10])
        route = rng.choice(_ROUTES)
        journeys.append({
            "journey_id": _hex_id(rng),
            "customer_tier": str(tier),
            "country": str(country),
            "channel": str(channel),
            "device": str(device),
            "route": str(route),
            "passengers": 1,
            "departure": "2024-09-14",
            "experiment": str(rng.choice(_EXPERIMENTS, p=[0.60, 0.25, 0.15])),
        })

    # Search offers — 3-5 per journey, price gradient by position.
    search_rows = []
    decisions_rows = []
    booking_rows = []

    for j in journeys:
        search_id = _hex_id(rng)
        n_offers = int(rng.integers(3, 6))
        base_price = float(rng.uniform(40, 70))
        # Experiment split control/treatment 50/50.
        variant = "control" if rng.random() < 0.5 else "treatment"

        for pos in range(1, n_offers + 1):
            price = base_price * (1.0 + 0.06 * (pos - 1))
            markup_factor = float(rng.choice([1.02, 1.05, 1.08, 1.15]))
            shown_price = price * markup_factor
            decision_id = _hex_id(rng)
            rule = str(rng.choice(_RULES))

            # Decision event
            decisions_rows.append({
                "decision_id": decision_id,
                "ts": pd.Timestamp("2024-09-14 08:00:00", tz="UTC") + pd.Timedelta(seconds=int(rng.integers(0, 86400))),
                "env": "default",
                "rule": rule,
                "markup_factor": markup_factor,
                "model_version": "v1",
                "engine_adapter": "*inmemory.Engine",
                "experiment": j["experiment"],
                "decide_outcome": "ok",
                "duration_ms": float(rng.exponential(0.5)),
                "rc_customer_tier": j["customer_tier"],
                "rc_country": j["country"],
                "rc_channel": j["channel"],
                "rc_amount": price,
                "rc_journey_id": j["journey_id"],
                "correlation_id": _hex_id(rng),
            })

            search_rows.append({
                "journey_id": j["journey_id"],
                "search_id": search_id,
                "customer_tier": j["customer_tier"],
                "country": j["country"],
                "channel": j["channel"],
                "device": j["device"],
                "route": j["route"],
                "departure": j["departure"],
                "passengers": j["passengers"],
                "offer_id": f"route-{j['route']}-2024-09-14-t{pos}",
                "decision_id": decision_id,
                "position": pos,
                "price": shown_price,
                "markup_factor": markup_factor,
                "experiment": j["experiment"],
                "variant": variant,
            })

        # Pick zero-or-one offer, elasticity baked in.
        offers_this_search = [r for r in search_rows if r["search_id"] == search_id]
        # Base p_click depends on tier
        p_click_base = {"enterprise": 0.35, "gold": 0.28, "silver": 0.20, "consumer": 0.15}[j["customer_tier"]]
        if rng.random() > p_click_base:
            continue  # no click

        # Weighted selection by 1/position, biased by price.
        weights = np.array([(1.0 / r["position"]) * max(0.1, 1.0 - (r["price"] - base_price) / 20)
                             for r in offers_this_search])
        weights = weights / weights.sum()
        picked = offers_this_search[int(rng.choice(len(offers_this_search), p=weights))]

        # Walk-off probabilities: baseline + treatment effect above €55
        walk_at_init_p = 0.20
        walk_at_reserve_p = 0.15
        if variant == "treatment" and picked["price"] > 55:
            walk_at_init_p += 0.15  # meaningful elasticity signal at high price
        if j["customer_tier"] == "consumer":
            walk_at_init_p += 0.10

        booking_id = _hex_id(rng)

        # booking.initiated always fires when they click
        base_booking = {
            "journey_id": j["journey_id"],
            "search_id": search_id,
            "decision_id": picked["decision_id"],
            "offer_id": picked["offer_id"],
            "booking_id": booking_id,
            "price": picked["price"],
            "markup_factor": picked["markup_factor"],
            "currency": "EUR",
            "experiment": j["experiment"],
            "variant": variant,
            "correlation_id": _hex_id(rng),
        }
        booking_rows.append({**base_booking, "event_type": "booking.initiated",
                              "ts": pd.Timestamp("2024-09-14 08:00:00", tz="UTC") + pd.Timedelta(seconds=int(rng.integers(0, 86400)))})

        if rng.random() < walk_at_init_p:
            booking_rows.append({**base_booking, "event_type": "booking.timeout",
                                  "phase": "initiated", "timeout_kind": "customer_abandoned",
                                  "ts": pd.Timestamp("2024-09-14 08:05:00", tz="UTC") + pd.Timedelta(seconds=int(rng.integers(0, 86400)))})
            continue

        booking_rows.append({**base_booking, "event_type": "booking.reserved",
                              "ts": pd.Timestamp("2024-09-14 08:10:00", tz="UTC") + pd.Timedelta(seconds=int(rng.integers(0, 86400)))})

        if rng.random() < walk_at_reserve_p:
            booking_rows.append({**base_booking, "event_type": "booking.timeout",
                                  "phase": "reserved", "timeout_kind": "customer_abandoned",
                                  "ts": pd.Timestamp("2024-09-14 08:15:00", tz="UTC") + pd.Timedelta(seconds=int(rng.integers(0, 86400)))})
            continue

        booking_rows.append({
            **base_booking, "event_type": "booking.purchased",
            "order_id": _hex_id(rng),
            "revenue": picked["price"],
            "ts": pd.Timestamp("2024-09-14 08:20:00", tz="UTC") + pd.Timedelta(seconds=int(rng.integers(0, 86400))),
        })

    decisions = pd.DataFrame(decisions_rows)
    search = pd.DataFrame(search_rows)
    booking = pd.DataFrame(booking_rows)
    return decisions, search, booking


def _synthetic_decisions(rows: int = 5000, seed: int = 42) -> pd.DataFrame:
    d, _, _ = synthetic_dataset(rows=rows, seed=seed)
    return d


def _synthetic_search(rows: int = 5000, seed: int = 42) -> pd.DataFrame:
    _, s, _ = synthetic_dataset(rows=rows, seed=seed)
    return s


def _synthetic_booking(rows: int = 5000, seed: int = 42) -> pd.DataFrame:
    _, _, b = synthetic_dataset(rows=rows, seed=seed)
    return b


# ----------------------------------------------------------------------
# Colab bootstrap
# ----------------------------------------------------------------------

_COLAB_BOOTSTRAP = """
# Run this cell on Google Colab before importing lib.data_loader:
!pip -q install duckdb pandas matplotlib scipy
!mkdir -p /content/lib
!curl -sL https://raw.githubusercontent.com/helmedeiros/pricing-observability/main/notebooks/lib/data_loader.py -o /content/lib/data_loader.py
!touch /content/lib/__init__.py
import sys; sys.path.insert(0, '/content')
"""


def colab_bootstrap() -> str:
    """Return the bootstrap snippet a Colab user pastes into cell 1."""
    return _COLAB_BOOTSTRAP.strip()


__all__ = [
    "MinioConfig",
    "load_decisions",
    "load_search",
    "load_booking",
    "synthetic_dataset",
    "colab_bootstrap",
]
