"""Market-structure regression tests (blueprint §13 exit: detections map to exact
coordinates). Hand-built geometry with known answers, brute-force references for
every rule, and a direct causality check (a prefix of the series gives the same
structure values as the full series)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest

from candle_intel.structure import geometry as g

T0 = datetime(2025, 3, 3, 8, 0)


def piecewise(points: list[tuple[int, float]]) -> np.ndarray:
    xs, ys = zip(*points, strict=True)
    return np.interp(np.arange(xs[-1] + 1), xs, ys)


def frame(low: np.ndarray, high: np.ndarray | None = None, close: np.ndarray | None = None) -> pl.DataFrame:
    high = low + 1.0 if high is None else high
    close = low + 0.5 if close is None else close
    n = len(low)
    return pl.DataFrame(
        {
            "event_time": [T0 + timedelta(minutes=5 * i) for i in range(n)],
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": high,
            "low": low,
            "close": close,
            "_atr": np.ones(n),
        }
    ).with_columns(pl.col("event_time").cast(pl.Datetime("us")))


def epoch(i: int) -> int:
    return int((T0 + timedelta(minutes=5 * i) - datetime(1970, 1, 1)).total_seconds())


# A V at bar 10 (low 90), a peak at bar 20 (high 100), a higher V at bar 30 (low 95), then up.
LOW = piecewise([(0, 100), (10, 90), (20, 99), (30, 95), (45, 105), (60, 108)])


def test_pivot_exact_and_tie_rule() -> None:
    high = np.array([1, 2, 3, 4, 5, 10, 10, 4, 3, 2, 1, 0, 0, 0, 0, 0], dtype=float)
    sh, _ = g.pivots(high, high - 1, 5)
    assert sh.bar.tolist() == [5]  # the second 10 is not strictly above its left side
    assert sh.price.tolist() == [10.0]
    assert sh.confirm.tolist() == [10]  # known only at the close of bar 5 + K


def test_swing_known_only_after_confirmation() -> None:
    s = g.analyse(*(frame(LOW)[c].to_numpy() for c in ("open", "high", "low", "close")), np.ones(len(LOW)))
    lo_bars = s.swings_low.bar.tolist()
    assert lo_bars[:2] == [10, 30]
    assert s.swings_low.price[:2].tolist() == [90.0, 95.0]
    d = s.features["sw_lo_dist_atr"]
    # bar 14: the low at 10 is not confirmed yet (needs bars 11..15)
    assert np.isnan(d[14]) and d[15] == pytest.approx(LOW[15] + 0.5 - 90.0)
    # the higher low at 30 replaces it at its confirmation (row 35), not before
    assert d[34] == pytest.approx(LOW[34] + 0.5 - 90.0)
    assert d[35] == pytest.approx(LOW[35] + 0.5 - 95.0)
    assert np.isnan(s.features["sw_trend"][35])  # one swing high so far → trend not known yet


def test_trendline_and_channel_coordinates() -> None:
    f = frame(LOW)
    s = g.analyse(*(f[c].to_numpy() for c in ("open", "high", "low", "close")), np.ones(len(LOW)))
    up = [ln for ln in s.lines if ln.kind == "up"]
    assert up and (up[0].bar1, up[0].price1, up[0].bar2, up[0].price2) == (10, 90.0, 30, 95.0)
    assert up[0].formed == 35 and up[0].slope == pytest.approx(0.25)
    # the parallel goes through the swing high at bar 20 (high 100): line there = 92.5
    assert up[0].channel_offset == pytest.approx(7.5)
    close40 = LOW[40] + 0.5
    line40 = 90 + 0.25 * 30
    assert s.features["tl_up_dist_atr"][40] == pytest.approx(close40 - line40)
    assert s.features["ch_up_pos"][40] == pytest.approx((close40 - line40) / 7.5)
    assert s.features["tl_up_touches"][40] == 2
    assert np.isnan(s.features["tl_up_dist_atr"][34])  # not drawable before row 35

    d = g.detect(f)
    ln = next(x for x in d["lines"] if x["kind"] == "up")
    assert ln["p1"] == {"time": epoch(10), "price": 90.0}
    assert ln["p2"] == {"time": epoch(30), "price": 95.0}
    assert ln["known_at"] == epoch(35) + 300
    lows = [x for x in d["swings"] if x["kind"] == "low"]
    assert lows[0] == {"kind": "low", "time": epoch(10), "price": 90.0, "known_at": epoch(15) + 300}


def test_trendline_break_ends_the_line() -> None:
    low = LOW.copy()
    low[50:] = low[50:] - 12  # collapse through the line at bar 50
    s = g.analyse(*(frame(low)[c].to_numpy() for c in ("open", "high", "low", "close")), np.ones(len(low)))
    brk = np.flatnonzero(s.features["tl_up_break"])
    assert brk.tolist() == [50]
    assert s.features["tl_up_dist_atr"][50] < 0
    assert np.isnan(s.features["tl_up_dist_atr"][51])


def _brute_last(swings: g.Swings, j: int) -> float:
    known = [p for p, c in zip(swings.price, swings.confirm, strict=True) if c <= j]
    return known[-1] if known else np.nan


@pytest.fixture(scope="module")
def walk() -> pl.DataFrame:
    rng = np.random.default_rng(3)
    close = 2000 + np.cumsum(rng.normal(0, 1, 3000))
    opn = np.concatenate([[2000.0], close[:-1]])
    high = np.maximum(opn, close) + np.abs(rng.normal(0, 0.6, 3000))
    low = np.minimum(opn, close) - np.abs(rng.normal(0, 0.6, 3000))
    return pl.DataFrame(
        {
            "event_time": [T0 + timedelta(minutes=5 * i) for i in range(3000)],
            "open": opn,
            "high": high,
            "low": low,
            "close": close,
            "_atr": np.full(3000, 1.4),
        }
    ).with_columns(pl.col("event_time").cast(pl.Datetime("us")))


def _analyse(df: pl.DataFrame) -> g.Structure:
    return g.analyse(*(df[c].to_numpy() for c in ("open", "high", "low", "close")), df["_atr"].to_numpy())


def test_pivots_match_brute_force(walk) -> None:
    h, lo = walk["high"].to_numpy(), walk["low"].to_numpy()
    sh, sl = g.pivots(h, lo, g.K)
    k = g.K
    ref_h = [
        i for i in range(k, len(h) - k) if h[i] > h[i - k : i].max() and h[i] >= h[i + 1 : i + k + 1].max()
    ]
    ref_l = [
        i
        for i in range(k, len(lo) - k)
        if lo[i] < lo[i - k : i].min() and lo[i] <= lo[i + 1 : i + k + 1].min()
    ]
    assert sh.bar.tolist() == ref_h and sl.bar.tolist() == ref_l


def test_sweeps_and_breaks_match_brute_force(walk) -> None:
    s = _analyse(walk)
    h, lo, c = (walk[x].to_numpy() for x in ("high", "low", "close"))
    for j in range(20, 3000, 7):
        last_hi, last_lo = _brute_last(s.swings_high, j), _brute_last(s.swings_low, j)
        assert s.features["sweep_high"][j] == bool(h[j] > last_hi and c[j] < last_hi)
        assert s.features["sweep_low"][j] == bool(lo[j] < last_lo and c[j] > last_lo)
        assert s.features["sw_break_up"][j] == bool(c[j] > last_hi and not c[j - 1] > last_hi)
    # every failed breakout closes back below a level broken at most FAIL_BARS earlier
    bu = np.flatnonzero(s.features["sw_break_up"])
    for j in np.flatnonzero(s.features["failed_break_up"]):
        b = bu[bu < j][-1]
        assert j - b <= g.FAIL_BARS
        assert c[j] < _brute_last(s.swings_high, b)


def test_levels_are_clusters_of_confirmed_swings(walk) -> None:
    s = _analyse(walk)
    j = s.levels.rows[-1]
    swings = [
        p
        for sw in (s.swings_high, s.swings_low)
        for b, p, cf in zip(sw.bar, sw.price, sw.confirm, strict=True)
        if cf <= j and b >= j - g.LEVEL_LOOKBACK
    ]
    for lv, tc in zip(s.levels.levels[-1], s.levels.touches[-1], strict=True):
        near = [p for p in swings if abs(p - lv) <= g.LEVEL_TOL_ATR * 1.4]
        assert tc >= g.LEVEL_MIN_TOUCHES and len(near) >= tc
    lv, tc = g._cluster(np.array([10.0, 10.2, 10.3, 11.0, 13.0, 13.1]), 0.35)
    assert tc.tolist() == [3, 1, 2]
    assert lv[0] == pytest.approx((10.0 + 10.2 + 10.3) / 3)


@pytest.mark.parametrize("cut", [400, 1111, 2047, 2999])
def test_prefix_gives_identical_structure(walk, cut) -> None:
    """Causality: every structure value on row < cut is the same whether the series
    ends at ``cut`` or continues — no value can depend on a later bar."""
    full = g.structure_features(walk)
    part = g.structure_features(walk.head(cut))
    a, b = full.head(cut), part
    for col in g.COLUMNS:
        x, y = a[col], b[col]
        same = (x.is_null() & y.is_null()) | (x == y).fill_null(False)
        if x.dtype == pl.Float64:
            same = same | ((x - y).abs() < 1e-9).fill_null(False)
        assert bool(same.all()), f"{col} changed when later bars were removed (cut {cut})"
