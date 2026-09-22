"""Classic indicators (features/4) against plain step-by-step reference formulas."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import polars as pl
import pytest

from candle_intel.features.compute import Bars, compute_features


@pytest.fixture(scope="module")
def f(syn_m1) -> pl.DataFrame:
    out = compute_features(Bars.from_m1(syn_m1), 0.001, research_start=datetime(2025, 2, 10))
    m5 = Bars.from_m1(syn_m1).m5.sort("ts_utc").rename({"ts_utc": "event_time"})
    return out.join(m5.select("event_time", "open", "high", "low", "close", "tick_volume"), on="event_time")


def ema(x: np.ndarray, n: int, alpha: float | None = None) -> np.ndarray:
    a = alpha or 2 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def test_bollinger_50_2_1(f) -> None:
    c = f["close"].to_numpy()
    i = 500
    w = c[i - 49 : i + 1]
    mid, sd = w.mean(), w.std()
    up, lo = mid + 2.1 * sd, mid - 2.1 * sd
    assert f["bb_pctb"][i] == pytest.approx((c[i] - lo) / (up - lo), rel=1e-6)
    assert f["bb_close_above_upper"][i] == (c[i] > up)
    assert f["bb_pctb"][:49].null_count() == 49  # no band before 50 bars


def test_ema_rsi_macd(f) -> None:
    c = f["close"].to_numpy()
    atr = (f["close"] - f["open"]).to_numpy() / f["body_atr"].to_numpy()  # recover the ATR used
    i = 900
    assert f["ema21_dist_atr"][i] == pytest.approx((c[i] - ema(c, 21)[i]) / atr[i], rel=1e-6)
    d = np.diff(c, prepend=np.nan)
    d[0] = 0.0
    g = ema(np.clip(d, 0, None), 14, 1 / 14)
    lo = ema(np.clip(-d, 0, None), 14, 1 / 14)
    assert f["rsi14"][i] == pytest.approx(100 - 100 / (1 + g[i] / lo[i]), rel=1e-4)
    macd = ema(c, 12) - ema(c, 26)
    assert f["macd_hist_atr"][i] == pytest.approx((macd[i] - ema(macd, 9)[i]) / atr[i], rel=1e-4)
    assert set(f["ema9_21_cross"].drop_nulls().unique()) <= {-1, 0, 1}
    assert 0 <= f["adx14"].drop_nulls().min() and f["adx14"].drop_nulls().max() <= 100


def test_vwap_resets_each_trading_day(f) -> None:
    day = f.filter(pl.col("trading_day") == f["trading_day"][2000])
    tp = (day["high"] + day["low"] + day["close"]) / 3
    v = day["tick_volume"].cast(pl.Float64)
    vwap = (tp * v).cum_sum() / v.cum_sum()
    atr = (day["close"] - day["open"]) / day["body_atr"]
    expect = ((day["close"] - vwap) / atr).to_numpy()
    got = day["vwap_dist_atr"].to_numpy()
    ok = np.isfinite(expect) & np.isfinite(got)
    assert ok.sum() > 100 and np.allclose(got[ok], expect[ok], rtol=1e-6)
