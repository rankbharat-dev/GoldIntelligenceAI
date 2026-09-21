"""Market structure from OHLC geometry (blueprint §13) — causal by construction.

Build order of §13, each stage on the one before:

    swing points → support / resistance → trendlines → channels → ranges
    → breakout / retest / failed breakout → liquidity sweeps

**Timing.** A swing high at bar ``i`` needs ``K`` bars on its right to be recognised
(its high must not be exceeded by them). It is therefore *confirmed* at the close of
bar ``i + K`` — that confirmation time is its ``available_at``. Every structure value
on a row uses only swings confirmed on that row or earlier, and levels / lines are
re-drawn only when a new swing is confirmed, with the ATR known at that moment. So a
structure value never depends on a later bar; the leakage suite (recomputation on
truncated history, future perturbation) checks this like every other feature.

**Units.** Prices are bid prices; distances are in ATR(14) of the previous M5 bars
(the same normaliser as the feature store), row positions are bar indices of the
series passed in (consecutive M5 bars; weekend gaps are just the next bar).

Every detection is also returned as an object with exact bar times and prices
(:func:`detect`), so the chart overlays and the features come from the same code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import numpy as np
import polars as pl
from numpy.lib.stride_tricks import sliding_window_view

STRUCTURE_VERSION = "structure/1"

K = 5  # swing confirmation: bars on each side (25 minutes on M5)
K_H1 = 3  # swing confirmation on H1
LEVEL_LOOKBACK = 1152  # bars of swings that form S/R levels (~4 trading days of M5)
LEVEL_MAX_SWINGS = 60
LEVEL_TOL_ATR = 0.35  # swings closer than this (in ATR) form one level
LEVEL_MIN_TOUCHES = 2
LINE_MAX_SPAN = 576  # anchors of a trendline at most this many bars apart (~2 days)
LINE_MAX_AGE = 576  # a trendline expires this many bars after its second anchor
LINE_TOL_ATR = 0.3  # a swing within this distance of a line touches it
LINE_TOUCH_LOOKBACK = 6  # swings checked for extra touches when a line is drawn
BREAK_MEMORY = 48  # bars_since_break_* is null beyond this
RETEST_BARS = 24
RETEST_TOL_ATR = 0.25
FAIL_BARS = 12

CONFIG = {
    "structure_version": STRUCTURE_VERSION,
    "swing_k": K,
    "swing_k_h1": K_H1,
    "level_lookback_bars": LEVEL_LOOKBACK,
    "level_max_swings": LEVEL_MAX_SWINGS,
    "level_tol_atr": LEVEL_TOL_ATR,
    "level_min_touches": LEVEL_MIN_TOUCHES,
    "line_max_span_bars": LINE_MAX_SPAN,
    "line_max_age_bars": LINE_MAX_AGE,
    "line_tol_atr": LINE_TOL_ATR,
    "break_memory_bars": BREAK_MEMORY,
    "retest_bars": RETEST_BARS,
    "retest_tol_atr": RETEST_TOL_ATR,
    "fail_bars": FAIL_BARS,
}

# Output columns of structure_features(), in registry order.
COLUMNS = (
    "sw_hi_dist_atr",
    "sw_lo_dist_atr",
    "sw_hi_age",
    "sw_lo_age",
    "sw_trend",
    "rng_width_atr",
    "rng_pos",
    "sw_break_up",
    "sw_break_down",
    "bars_since_break_up",
    "bars_since_break_down",
    "retest_up",
    "retest_down",
    "failed_break_up",
    "failed_break_down",
    "sweep_high",
    "sweep_low",
    "sweep_depth_atr",
    "sr_above_dist_atr",
    "sr_above_touches",
    "sr_below_dist_atr",
    "sr_below_touches",
    "sr_above_high_dist_atr",
    "sr_below_low_dist_atr",
    "tl_up_dist_atr",
    "tl_up_slope_atr",
    "tl_up_touches",
    "tl_up_break",
    "tl_dn_dist_atr",
    "tl_dn_slope_atr",
    "tl_dn_touches",
    "tl_dn_break",
    "ch_up_pos",
    "ch_dn_pos",
    "ch_width_atr",
)
H1_COLUMNS = ("h1_sw_trend", "h1_sw_hi_dist_atr", "h1_sw_lo_dist_atr")


# ---------------------------------------------------------------- swings


@dataclass(frozen=True)
class Swings:
    """Confirmed swing points of one kind, in confirmation order."""

    bar: np.ndarray  # pivot bar index
    price: np.ndarray
    confirm: np.ndarray  # row at whose close the pivot becomes known (= bar + k)

    def last_at(self, rows: np.ndarray) -> np.ndarray:
        """Index into this table of the last swing confirmed at or before each row (-1: none)."""
        return np.searchsorted(self.confirm, rows, side="right") - 1


def pivots(high: np.ndarray, low: np.ndarray, k: int) -> tuple[Swings, Swings]:
    """Swing highs / lows: strictly above (below) the ``k`` bars before, and not
    exceeded by the ``k`` bars after. Ties on the right keep the earlier bar."""
    n = len(high)
    if n < 2 * k + 1:
        empty = np.zeros(0, dtype=np.int64)
        return Swings(empty, np.zeros(0), empty), Swings(empty, np.zeros(0), empty)
    wh = sliding_window_view(high, 2 * k + 1)
    wl = sliding_window_view(low, 2 * k + 1)
    is_h = (wh[:, k] > wh[:, :k].max(axis=1)) & (wh[:, k] >= wh[:, k + 1 :].max(axis=1))
    is_l = (wl[:, k] < wl[:, :k].min(axis=1)) & (wl[:, k] <= wl[:, k + 1 :].min(axis=1))
    ih = np.flatnonzero(is_h) + k
    il = np.flatnonzero(is_l) + k
    return (
        Swings(ih.astype(np.int64), high[ih].astype(np.float64), (ih + k).astype(np.int64)),
        Swings(il.astype(np.int64), low[il].astype(np.float64), (il + k).astype(np.int64)),
    )


def _take(a: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """``a[idx]`` with NaN where ``idx < 0``."""
    out = np.full(len(idx), np.nan)
    ok = idx >= 0
    out[ok] = a[idx[ok]]
    return out


def _safe_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where((b > 0) & np.isfinite(b), a / np.where(b > 0, b, 1.0), np.nan)


# ---------------------------------------------------------------- support / resistance


def _cluster(prices: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray]:
    """Prices → (level price = cluster mean, touches), sorted. Walking up the sorted
    prices, a cluster takes every price within ``tol`` of its lowest one, so a level is
    never wider than ``tol`` (no chaining of a whole trend into one "level")."""
    p = np.sort(prices)
    starts = []
    i = 0
    while i < len(p):
        starts.append(i)
        i = int(np.searchsorted(p, p[i] + tol, side="right"))
    st = np.asarray(starts)
    counts = np.diff(np.concatenate([st, [len(p)]]))
    return np.add.reduceat(p, st) / counts, counts


@dataclass
class _Levels:
    rows: list[int] = field(default_factory=list)  # event row
    levels: list[np.ndarray] = field(default_factory=list)  # sorted level prices (touches ≥ min)
    touches: list[np.ndarray] = field(default_factory=list)


def support_resistance(sh: Swings, sl: Swings, atr: np.ndarray, n: int) -> _Levels:
    """Levels re-drawn at every swing confirmation from the swings of the last
    ``LEVEL_LOOKBACK`` bars, clustered with the ATR of that row."""
    bars = np.concatenate([sh.bar, sl.bar])
    prices = np.concatenate([sh.price, sl.price])
    conf = np.concatenate([sh.confirm, sl.confirm])
    # confirm = bar + k for every swing, so confirmation order is also bar order
    order = np.argsort(conf, kind="stable")
    bars, prices, conf = bars[order], prices[order], conf[order]
    out = _Levels()
    for j in np.unique(conf):
        if j >= n:
            continue
        hi = np.searchsorted(conf, j, side="right")
        lo = max(np.searchsorted(bars, j - LEVEL_LOOKBACK, side="left"), hi - LEVEL_MAX_SWINGS)
        p = prices[lo:hi]
        a = atr[j]
        if len(p) < LEVEL_MIN_TOUCHES or not np.isfinite(a) or a <= 0:
            lv, tc = np.zeros(0), np.zeros(0, dtype=np.int64)
        else:
            lv, tc = _cluster(p, LEVEL_TOL_ATR * a)
            ok = tc >= LEVEL_MIN_TOUCHES
            lv, tc = lv[ok], tc[ok]
        out.rows.append(int(j))
        out.levels.append(lv)
        out.touches.append(tc)
    return out


def _level_features(lv: _Levels, close, high, low, atr, n) -> dict[str, np.ndarray]:
    f = {
        k: np.full(n, np.nan)
        for k in (
            "sr_above_dist_atr",
            "sr_above_touches",
            "sr_below_dist_atr",
            "sr_below_touches",
            "sr_above_high_dist_atr",
            "sr_below_low_dist_atr",
        )
    }
    ends = [*lv.rows[1:], n]
    for j, end, levels, touches in zip(lv.rows, ends, lv.levels, lv.touches, strict=True):
        if not len(levels):
            continue
        r = np.arange(j, end)
        c = close[r]
        idx = np.searchsorted(levels, c, side="right")
        up, dn = idx < len(levels), idx > 0
        a = atr[r]
        above = np.where(up, levels[np.minimum(idx, len(levels) - 1)], np.nan)
        below = np.where(dn, levels[np.maximum(idx - 1, 0)], np.nan)
        f["sr_above_dist_atr"][r] = _safe_div(above - c, a)
        f["sr_below_dist_atr"][r] = _safe_div(c - below, a)
        f["sr_above_touches"][r] = np.where(up, touches[np.minimum(idx, len(levels) - 1)], np.nan)
        f["sr_below_touches"][r] = np.where(dn, touches[np.maximum(idx - 1, 0)], np.nan)
        f["sr_above_high_dist_atr"][r] = _safe_div(above - high[r], a)
        f["sr_below_low_dist_atr"][r] = _safe_div(low[r] - below, a)
    return f


# ---------------------------------------------------------------- trendlines / channels


@dataclass(frozen=True)
class Line:
    kind: str  # "up" (through rising swing lows) or "down" (through falling swing highs)
    bar1: int
    price1: float
    bar2: int
    price2: float
    formed: int  # row whose close confirmed the second anchor
    touches: int
    channel_offset: float | None  # parallel line distance (price), None if no opposite swing
    end: int  # last row the line is active (inclusive)
    broken: int | None  # row whose close crossed the line

    @property
    def slope(self) -> float:
        return (self.price2 - self.price1) / (self.bar2 - self.bar1)

    def value(self, rows: np.ndarray | int) -> np.ndarray | float:
        return self.price1 + self.slope * (np.asarray(rows) - self.bar1)


def trendlines(
    anchors: Swings, opposite: Swings, close: np.ndarray, atr: np.ndarray, kind: str, n: int
) -> list[Line]:
    """At each confirmation of a swing of ``anchors`` a line through the last two is
    drawn if they rise (``up``) / fall (``down``). It stays active until the next
    confirmation, a close through it, or ``LINE_MAX_AGE`` bars after its second anchor."""
    sign = 1.0 if kind == "up" else -1.0
    lines: list[Line] = []
    m = len(anchors.bar)
    for e in range(1, m):
        j = int(anchors.confirm[e])
        if j >= n:
            break
        b1, p1, b2, p2 = int(anchors.bar[e - 1]), anchors.price[e - 1], int(anchors.bar[e]), anchors.price[e]
        if sign * (p2 - p1) <= 0 or b2 - b1 > LINE_MAX_SPAN:
            continue
        a = atr[j]
        if not np.isfinite(a) or a <= 0:
            continue
        slope = (p2 - p1) / (b2 - b1)
        # extra touches: earlier swings of the same kind lying on the line
        lo = max(0, e - LINE_TOUCH_LOOKBACK)
        prev_b, prev_p = anchors.bar[lo : e + 1], anchors.price[lo : e + 1]
        on_line = np.abs(prev_p - (p1 + slope * (prev_b - b1))) <= LINE_TOL_ATR * a
        touches = int(on_line[prev_b >= b1 - LINE_MAX_SPAN].sum())
        # channel: the farthest opposite swing between the first anchor and now
        o_lo = np.searchsorted(opposite.bar, b1, side="left")
        o_hi = np.searchsorted(opposite.confirm, j, side="right")
        offset = None
        if o_hi > o_lo:
            ob, op = opposite.bar[o_lo:o_hi], opposite.price[o_lo:o_hi]
            d = sign * (op - (p1 + slope * (ob - b1)))
            if d.max() > 0:
                offset = float(d.max())
        nxt = int(anchors.confirm[e + 1]) - 1 if e + 1 < m else n - 1
        end = min(nxt, b2 + LINE_MAX_AGE, n - 1)
        rows = np.arange(j, end + 1)
        crossed = sign * (close[rows] - (p1 + slope * (rows - b1))) < 0
        if crossed[0]:
            continue  # already through the line when it could first be drawn
        broken = None
        hit = np.flatnonzero(crossed)
        if len(hit):
            broken = int(rows[hit[0]])
            end = broken
        lines.append(Line(kind, b1, float(p1), b2, float(p2), j, touches, offset, end, broken))
    return lines


def _line_features(lines: list[Line], close, atr, n, kind: str) -> dict[str, np.ndarray]:
    dist = np.full(n, np.nan)
    slope = np.full(n, np.nan)
    touches = np.full(n, np.nan)
    brk = np.zeros(n, dtype=bool)
    pos = np.full(n, np.nan)
    width = np.full(n, np.nan)
    sign = 1.0 if kind == "up" else -1.0
    for ln in lines:
        rows = np.arange(ln.formed, ln.end + 1)
        if ln.broken is not None:
            brk[ln.broken] = True  # the line ends on the bar that closes through it
        v = ln.value(rows)
        a = atr[rows]
        dist[rows] = _safe_div(close[rows] - v, a)
        slope[rows] = _safe_div(np.full(len(rows), ln.slope * 12), a)  # ATR per hour of M5 bars
        touches[rows] = ln.touches
        if ln.channel_offset:
            # 0 = channel floor, 1 = channel roof, for both kinds
            inside = sign * (close[rows] - v) / ln.channel_offset
            pos[rows] = inside if kind == "up" else 1.0 - inside
            width[rows] = _safe_div(np.full(len(rows), ln.channel_offset), a)
    return {
        f"tl_{kind}_dist_atr": dist,
        f"tl_{kind}_slope_atr": slope,
        f"tl_{kind}_touches": touches,
        f"tl_{kind}_break": brk,
        f"ch_{kind}_pos": pos,
        f"_ch_{kind}_width": width,
    }


# ---------------------------------------------------------------- breaks, retests, sweeps


def _events_after(event_rows: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """Index of the last event strictly before each row (-1: none)."""
    return np.searchsorted(event_rows, rows, side="left") - 1


def _first_in_group(flag: np.ndarray, group: np.ndarray) -> np.ndarray:
    """``flag`` only on its first True row per group value."""
    out = np.zeros(len(flag), dtype=bool)
    idx = np.flatnonzero(flag)
    if len(idx):
        _, first = np.unique(group[idx], return_index=True)
        out[idx[first]] = True
    return out


def _breaks(level: np.ndarray, close, low_or_high, atr, direction: int) -> dict[str, np.ndarray]:
    """Break of the last swing level in ``direction`` (+1 up through a high, −1 down
    through a low), then retest (price comes back to the level and holds) or failure
    (closes back through it)."""
    n = len(close)
    rows = np.arange(n)
    prev_close = np.concatenate([[np.nan], close[:-1]])
    with np.errstate(invalid="ignore"):
        brk = (direction * (close - level) > 0) & ~(direction * (prev_close - level) > 0) & np.isfinite(level)
    brk[0] = False
    ev = np.flatnonzero(brk)
    ev_level = level[ev]
    last = np.searchsorted(ev, rows, side="right") - 1  # break at or before the row
    since = np.where(last >= 0, rows - _take(ev.astype(np.float64), last), np.nan)
    since = np.where(since <= BREAK_MEMORY, since, np.nan)
    prior = _events_after(ev, rows)  # break strictly before the row
    lvl = _take(ev_level, prior)
    age = rows - _take(ev.astype(np.float64), prior)
    with np.errstate(invalid="ignore"):
        tol = RETEST_TOL_ATR * atr
        if direction > 0:
            retest = (age <= RETEST_BARS) & (low_or_high <= lvl + tol) & (close > lvl)
            fail = (age <= FAIL_BARS) & (close < lvl)
        else:
            retest = (age <= RETEST_BARS) & (low_or_high >= lvl - tol) & (close < lvl)
            fail = (age <= FAIL_BARS) & (close > lvl)
    retest &= np.isfinite(lvl)
    fail = _first_in_group(fail & np.isfinite(lvl), prior)
    return {"break": brk, "since": since, "retest": retest, "fail": fail}


# ---------------------------------------------------------------- assembly


@dataclass
class Structure:
    """Everything detected on one series: per-row features and the objects behind them."""

    features: dict[str, np.ndarray]
    swings_high: Swings
    swings_low: Swings
    levels: _Levels
    lines: list[Line]


def analyse(
    open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, atr: np.ndarray
) -> Structure:
    """Structure of an OHLC series. ``atr`` (price units) must be known at each bar's
    close (e.g. ATR of the previous bars); NaN during warm-up."""
    n = len(close)
    rows = np.arange(n)
    sh, sl = pivots(high, low, K)
    ih, il = sh.last_at(rows), sl.last_at(rows)
    last_hi, prev_hi = _take(sh.price, ih), _take(sh.price, ih - 1)
    last_lo, prev_lo = _take(sl.price, il), _take(sl.price, il - 1)
    prev_hi[ih < 1] = np.nan
    prev_lo[il < 1] = np.nan

    f: dict[str, np.ndarray] = {}
    f["sw_hi_dist_atr"] = _safe_div(close - last_hi, atr)
    f["sw_lo_dist_atr"] = _safe_div(close - last_lo, atr)
    f["sw_hi_age"] = np.where(ih >= 0, rows - _take(sh.bar.astype(np.float64), ih), np.nan)
    f["sw_lo_age"] = np.where(il >= 0, rows - _take(sl.bar.astype(np.float64), il), np.nan)
    with np.errstate(invalid="ignore"):
        up = (last_hi > prev_hi) & (last_lo > prev_lo)
        down = (last_hi < prev_hi) & (last_lo < prev_lo)
    known = np.isfinite(prev_hi) & np.isfinite(prev_lo)
    f["sw_trend"] = np.where(known, np.where(up, 1.0, np.where(down, -1.0, 0.0)), np.nan)
    width = last_hi - last_lo
    f["rng_width_atr"] = _safe_div(width, atr)
    f["rng_pos"] = _safe_div(close - last_lo, width)

    bu = _breaks(last_hi, close, low, atr, +1)
    bd = _breaks(last_lo, close, high, atr, -1)
    f["sw_break_up"], f["sw_break_down"] = bu["break"], bd["break"]
    f["bars_since_break_up"], f["bars_since_break_down"] = bu["since"], bd["since"]
    f["retest_up"], f["retest_down"] = bu["retest"], bd["retest"]
    f["failed_break_up"], f["failed_break_down"] = bu["fail"], bd["fail"]

    # Liquidity sweep: the wick takes out the last swing, the close comes back inside.
    with np.errstate(invalid="ignore"):
        sweep_h = (high > last_hi) & (close < last_hi)
        sweep_l = (low < last_lo) & (close > last_lo)
    f["sweep_high"], f["sweep_low"] = sweep_h, sweep_l
    depth = np.where(sweep_h, high - last_hi, np.where(sweep_l, last_lo - low, np.nan))
    f["sweep_depth_atr"] = _safe_div(depth, atr)

    levels = support_resistance(sh, sl, atr, n)
    f |= _level_features(levels, close, high, low, atr, n)

    up_lines = trendlines(sl, sh, close, atr, "up", n)
    dn_lines = trendlines(sh, sl, close, atr, "down", n)
    lf = _line_features(up_lines, close, atr, n, "up") | _line_features(dn_lines, close, atr, n, "down")
    wu, wd = lf.pop("_ch_up_width"), lf.pop("_ch_down_width")
    f |= {k.replace("_down_", "_dn_"): v for k, v in lf.items()}
    f["ch_width_atr"] = np.where(np.isfinite(wu), wu, wd)

    for v in f.values():
        if v.dtype == np.float64:
            v[~np.isfinite(v)] = np.nan
    return Structure(f, sh, sl, levels, sorted(up_lines + dn_lines, key=lambda x: x.formed))


def structure_features(m5: pl.DataFrame, atr_col: str = "_atr") -> pl.DataFrame:
    """Per-row structure columns for a frame sorted by ``event_time`` with OHLC and
    ``atr_col`` (price units). Returns ``event_time`` + :data:`COLUMNS`."""
    ohlc = (m5[c].to_numpy().astype(np.float64) for c in ("open", "high", "low", "close"))
    s = analyse(*ohlc, _atr(m5, atr_col))
    cols: dict[str, Any] = {"event_time": m5["event_time"]}
    for c in COLUMNS:
        v = s.features[c]
        if v.dtype == bool:
            cols[c] = pl.Series(c, v, dtype=pl.Boolean)
        elif c == "sw_trend":
            cols[c] = pl.Series(c, v).fill_nan(None).cast(pl.Int8)
        elif c.endswith(("_age", "_touches")) or c.startswith("bars_since"):
            cols[c] = pl.Series(c, v).fill_nan(None).cast(pl.Int32)
        else:
            cols[c] = pl.Series(c, v, dtype=pl.Float64)
    return pl.DataFrame(cols).with_columns(pl.col(pl.Float64).fill_nan(None))


def _atr(df: pl.DataFrame, col: str) -> np.ndarray:
    return df[col].cast(pl.Float64).fill_null(float("nan")).to_numpy()


def h1_structure(h1: pl.DataFrame) -> pl.DataFrame:
    """H1 swing state per closed H1 bar (confirmation K_H1 bars later), keyed by the
    bar's close time. Joined to M5 rows as-of that close, like other H1 context."""
    h1 = h1.sort("ts_utc")
    high, low = h1["high"].to_numpy().astype(np.float64), h1["low"].to_numpy().astype(np.float64)
    rows = np.arange(len(h1))
    sh, sl = pivots(high, low, K_H1)
    ih, il = sh.last_at(rows), sl.last_at(rows)
    last_hi, last_lo = _take(sh.price, ih), _take(sl.price, il)
    prev_hi, prev_lo = _take(sh.price, ih - 1), _take(sl.price, il - 1)
    prev_hi[ih < 1] = np.nan
    prev_lo[il < 1] = np.nan
    with np.errstate(invalid="ignore"):
        trend = np.where(
            np.isfinite(prev_hi) & np.isfinite(prev_lo),
            np.where(
                (last_hi > prev_hi) & (last_lo > prev_lo),
                1.0,
                np.where((last_hi < prev_hi) & (last_lo < prev_lo), -1.0, 0.0),
            ),
            np.nan,
        )
    return pl.DataFrame(
        {
            "_h1s_close_utc": h1["ts_utc"] + timedelta(hours=1),
            "h1_sw_trend": pl.Series(trend).fill_nan(None).cast(pl.Int8),
            "_h1_sw_hi": pl.Series(last_hi).fill_nan(None),
            "_h1_sw_lo": pl.Series(last_lo).fill_nan(None),
        }
    )


# ---------------------------------------------------------------- detections (chart overlays)


def detect(m5: pl.DataFrame, atr_col: str = "_atr", start_row: int = 0) -> dict[str, Any]:
    """Exact coordinates of every detection whose anchor lies at or after ``start_row``:
    swings, current S/R levels, trendlines (+ channels), sweeps, breaks, retests and
    failed breakouts. Times are bar opens (UTC epoch seconds); ``known_at`` is the close
    of the row at which the detection became available."""
    t = m5["event_time"].dt.epoch("s").to_numpy()
    o, h, low, c = (m5[x].to_numpy().astype(np.float64) for x in ("open", "high", "low", "close"))
    atr = _atr(m5, atr_col)
    s = analyse(o, h, low, c, atr)
    n = len(c)
    step = 300

    def ts(i: int) -> int:
        return int(t[i])

    swings = []
    for kind, sw in (("high", s.swings_high), ("low", s.swings_low)):
        for b, p, cf in zip(sw.bar, sw.price, sw.confirm, strict=True):
            if b >= start_row and cf < n:
                swings.append(
                    {"kind": kind, "time": ts(b), "price": round(float(p), 3), "known_at": ts(cf) + step}
                )
    swings.sort(key=lambda x: x["time"])

    levels = []
    if s.levels.rows:
        j = s.levels.rows[-1]
        a = atr[j]
        all_p = np.concatenate([s.swings_high.price, s.swings_low.price])
        all_b = np.concatenate([s.swings_high.bar, s.swings_low.bar])
        all_c = np.concatenate([s.swings_high.confirm, s.swings_low.confirm])
        for lv, tc in zip(s.levels.levels[-1], s.levels.touches[-1], strict=True):
            near = (np.abs(all_p - lv) <= LEVEL_TOL_ATR * a) & (all_c <= j) & (all_b >= j - LEVEL_LOOKBACK)
            bars = np.sort(all_b[near])
            levels.append(
                {
                    "price": round(float(lv), 3),
                    "touches": int(tc),
                    "band": round(float(LEVEL_TOL_ATR * a / 2), 3),
                    "first_time": ts(int(bars[0])) if len(bars) else None,
                    "last_time": ts(int(bars[-1])) if len(bars) else None,
                    "known_at": ts(j) + step,
                }
            )

    lines = []
    for ln in s.lines:
        if ln.end < start_row:
            continue
        lines.append(
            {
                "kind": ln.kind,
                "p1": {"time": ts(ln.bar1), "price": round(ln.price1, 3)},
                "p2": {"time": ts(ln.bar2), "price": round(ln.price2, 3)},
                "end": {"time": ts(ln.end), "price": round(float(ln.value(ln.end)), 3)},
                "known_at": ts(ln.formed) + step,
                "touches": ln.touches,
                "broken_at": ts(ln.broken) if ln.broken is not None else None,
                "channel_offset": None if ln.channel_offset is None else round(ln.channel_offset, 3),
            }
        )

    f = s.features
    events = []
    for key, label in (
        ("sweep_high", "sweep_high"),
        ("sweep_low", "sweep_low"),
        ("sw_break_up", "break_up"),
        ("sw_break_down", "break_down"),
        ("retest_up", "retest_up"),
        ("retest_down", "retest_down"),
        ("failed_break_up", "failed_up"),
        ("failed_break_down", "failed_down"),
    ):
        idx = np.flatnonzero(f[key])
        if key.startswith("retest_"):  # on the chart: only the first retest after each break
            brk = np.flatnonzero(f["sw_break_up" if key.endswith("up") else "sw_break_down"])
            owner = np.searchsorted(brk, idx, side="right") - 1
            _, first = np.unique(owner, return_index=True)
            idx = idx[first]
        for i in idx:
            if i >= start_row:
                events.append({"kind": label, "time": ts(int(i)), "price": round(float(c[i]), 3)})
    events.sort(key=lambda x: x["time"])
    return {
        "structure_version": STRUCTURE_VERSION,
        "config": CONFIG,
        "swings": swings,
        "levels": levels,
        "lines": lines,
        "events": events,
    }
