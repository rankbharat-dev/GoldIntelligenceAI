"""Feature values checked by hand against the bars they come from."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl
import pytest

from candle_intel.features.compute import Bars, compute_features
from candle_intel.features.registry import FEATURES, META_COLUMNS, feature_names

POINT = 0.001


@pytest.fixture(scope="module")
def bars(syn_m1) -> Bars:
    return Bars.from_m1(syn_m1)


@pytest.fixture(scope="module")
def feats(bars) -> pl.DataFrame:
    return compute_features(bars, POINT, research_start=datetime(2025, 2, 10))


def row(feats: pl.DataFrame, t: datetime) -> dict:
    return feats.filter(pl.col("event_time") == t).row(0, named=True)


def test_columns_match_the_registry(feats) -> None:
    assert feats.columns == [*META_COLUMNS, *feature_names()]
    assert all(f.description and f.group and f.unit for f in FEATURES)


def test_candle_anatomy_by_hand(bars, feats) -> None:
    t = datetime(2025, 3, 12, 14, 35)
    m5 = bars.m5.sort("ts_utc")
    i = m5["ts_utc"].to_list().index(t)
    o, h, lo, c = (m5[k][i] for k in ("open", "high", "low", "close"))
    prev_close = m5["close"][i - 1]
    # ATR(14) of the 14 bars *before* this one
    trs = [
        max(
            m5["high"][j] - m5["low"][j],
            abs(m5["high"][j] - m5["close"][j - 1]),
            abs(m5["low"][j] - m5["close"][j - 1]),
        )
        for j in range(i - 14, i)
    ]
    atr = sum(trs) / 14
    r = row(feats, t)
    assert r["available_at"] == t + timedelta(minutes=5)
    assert r["atr_pts"] == pytest.approx(atr / POINT)
    assert r["range_pts"] == pytest.approx((h - lo) / POINT)
    assert r["close_loc"] == pytest.approx((c - lo) / (h - lo))
    assert r["body_frac"] == pytest.approx(abs(c - o) / (h - lo))
    assert r["upper_wick_frac"] + r["lower_wick_frac"] + r["body_frac"] == pytest.approx(1.0)
    assert r["body_atr"] == pytest.approx((c - o) / atr)
    assert r["ret_atr"] == pytest.approx((c - prev_close) / atr)
    assert r["dir"] == (1 if c > o else -1 if c < o else 0)


def test_sequence_features_agree_with_bars(bars, feats) -> None:
    m5 = bars.m5.sort("ts_utc")
    f = feats.sort("event_time")
    hi, lo = m5["high"].to_list(), m5["low"].to_list()
    dirs = f["dir"].to_list()
    for i in range(3000, 3400):
        r = f.row(i, named=True)
        assert r["inside_bar"] == (hi[i] <= hi[i - 1] and lo[i] >= lo[i - 1])
        assert r["outside_bar"] == (hi[i] > hi[i - 1] and lo[i] < lo[i - 1])
        k = 1
        while dirs[i - k] == dirs[i]:
            k += 1
        assert r["streak"] == k * dirs[i]
        assert r["up_count_5"] == sum(d == 1 for d in dirs[i - 4 : i + 1])
        sym = {1: "U", -1: "D", 0: "-"}
        assert r["dirs_3"] == "".join(sym[d] for d in dirs[i - 2 : i + 1])


@pytest.mark.parametrize(
    ("t", "session", "since_ny", "since_london"),
    [
        # Before the US DST switch (EST, UTC−5): 13:00 UTC = 08:00 NY, 13:00 London (GMT)
        (datetime(2025, 3, 7, 13, 0), "london_ny_overlap", 0, 300),
        (datetime(2025, 3, 7, 12, 30), "london", 1410, 270),
        # After it (EDT, UTC−4): 12:30 UTC = 08:30 NY → overlap
        (datetime(2025, 3, 10, 12, 30), "london_ny_overlap", 30, 270),
        # After the UK switch (BST, UTC+1): 07:00 UTC = 08:00 London
        (datetime(2025, 3, 31, 7, 0), "london", 1140, 0),  # 03:00 NY
        (datetime(2025, 3, 31, 3, 0), "asian", 900, 1200),  # 23:00 NY, 04:00 London, 12:00 Tokyo
        # 22:30 UTC = 18:30 EDT, 22:30 London, 07:30 Tokyo: nobody's session
        (datetime(2025, 3, 12, 22, 30), "off", 630, 870),
    ],
)
def test_sessions_are_dst_aware(feats, t, session, since_ny, since_london) -> None:
    r = row(feats, t)
    assert r["session"] == session
    assert r["min_since_ny_open"] == since_ny
    assert r["min_since_london_open"] == since_london


def test_trading_day_rolls_at_17_new_york(feats) -> None:
    # Wednesday 2025-03-12: 20:55 UTC = 16:55 EDT (Wednesday's day); 22:00 UTC = 18:00 → Thursday
    assert row(feats, datetime(2025, 3, 12, 20, 55))["trading_day"] == date(2025, 3, 12)
    assert row(feats, datetime(2025, 3, 12, 22, 0))["trading_day"] == date(2025, 3, 13)


def test_hygiene_flags(feats) -> None:
    week_open = datetime(2025, 3, 9, 22, 0)  # Sunday 18:00 EDT
    for k in range(3):
        r = row(feats, week_open + timedelta(minutes=5 * k))
        assert r["hyg_week_first3"] and r["hyg_no_entry"]
        assert r["bars_since_week_open"] == k
    assert row(feats, week_open)["hyg_weekend_gap"]
    assert not row(feats, week_open + timedelta(minutes=15))["hyg_week_first3"]
    # Friday close 17:00 EST = 22:00 UTC: 21:45, 21:50, 21:55 are the last 3
    assert [row(feats, datetime(2025, 3, 7, 21, m))["hyg_week_last3"] for m in (40, 45, 50, 55)] == [
        False,
        True,
        True,
        True,
    ]
    # Rollover window 16:45–18:30 NY
    assert row(feats, datetime(2025, 3, 12, 20, 45))["hyg_rollover"]  # 16:45 EDT
    assert not row(feats, datetime(2025, 3, 12, 20, 40))["hyg_rollover"]
    assert row(feats, datetime(2025, 3, 12, 22, 25))["hyg_rollover"]  # 18:25 EDT
    assert not row(feats, datetime(2025, 3, 12, 22, 30))["hyg_rollover"]


def test_abnormal_spread_fires_on_spikes(syn_m1, bars, feats) -> None:
    tier_change = syn_m1["ts_utc"][syn_m1.height // 2]  # synthetic tier 60 → 90 pts
    m5_spread = bars.m5.select(event_time="ts_utc", mx="spread_points_max", mn="spread_points_min")
    f = feats.join(m5_spread, on="event_time")
    calm = f.filter(pl.col("event_time").is_between(datetime(2025, 3, 1), tier_change - timedelta(hours=1)))
    assert 0 < calm["hyg_abnormal_spread"].mean() < 0.05
    # Before the tier change, every flagged bar contains a spike (the synthetic spikes are 6×).
    spiky = calm.filter("hyg_abnormal_spread")
    assert (spiky["mx"] >= 3 * spiky["mn"].clip(lower_bound=60)).all()


def test_abnormal_spread_after_a_tier_jump_is_temporary(syn_m1, feats) -> None:
    """A new, higher spread tier is abnormal until the trailing ~5-day median has
    caught up — in real time nobody knows yet that the new tier will last."""
    tier_change = syn_m1["ts_utc"][syn_m1.height // 2]
    share = lambda d0, d1: feats.filter(  # noqa: E731
        pl.col("event_time").is_between(tier_change + timedelta(days=d0), tier_change + timedelta(days=d1))
    )["hyg_abnormal_spread"].mean()
    assert share(0, 1) > 0.9
    assert share(7, 14) < 0.05


def test_previous_day_levels(bars, feats) -> None:
    m5 = bars.m5.with_columns(
        td=(
            pl.col("ts_utc").dt.replace_time_zone("UTC").dt.convert_time_zone("America/New_York")
            + timedelta(hours=7)
        ).dt.date()
    )
    prev = m5.filter(pl.col("td") == date(2025, 3, 12))
    r = row(feats, datetime(2025, 3, 13, 14, 0))
    atr = r["atr_pts"] * POINT
    c = m5.filter(pl.col("ts_utc") == datetime(2025, 3, 13, 14, 0))["close"][0]
    assert r["dist_prev_high_atr"] == pytest.approx((c - prev["high"].max()) / atr)
    assert r["dist_prev_low_atr"] == pytest.approx((c - prev["low"].min()) / atr)


def test_regime_is_causal_monthly_terciles(feats) -> None:
    march = feats.filter(pl.col("event_time").dt.month() == 3)
    shares = march["vol_regime"].value_counts(normalize=True)
    assert set(shares["vol_regime"].to_list()) == {"low", "mid", "high"}
    # February has fewer than 10 trading days of history before it → unknown
    assert feats.filter(pl.col("event_time").dt.month() == 2)["vol_regime"].null_count() > 0
