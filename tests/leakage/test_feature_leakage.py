"""Feature leakage suite (blueprint §7.2) — blocking.

On a synthetic history with the real gold calendar (DST switches, daily break,
weekends, spread spikes):

1. recomputation: features known at T are identical whether computed on the full
   history or on the history known at T (last M15/H1 bar still forming);
2. future perturbation: a different future never changes a feature known at T;
3. availability audit: available_at = bar close ≥ event_time, and M15/H1 context
   closed at or before available_at;
4. the checks are not blind: a set of deliberately leaky features is caught, each by name;
5. the feature-access wrapper never returns a row after the decision time.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from candle_intel.features import leakage
from candle_intel.features.compute import Bars, compute_features
from candle_intel.features.registry import feature_names
from candle_intel.features.store import FeatureStore, LookAheadError

POINT = 0.001

# UTC cut points chosen to hit every awkward boundary.
CUTOFFS = [
    datetime(2025, 2, 20, 14, 37),  # mid M5, mid H1, London/NY overlap
    datetime(2025, 3, 3, 0, 0),  # exactly on a month (regime) and H1 boundary
    datetime(2025, 3, 7, 21, 52),  # Friday, inside the last 3 bars before the 17:00 NY close (EST)
    datetime(2025, 3, 9, 22, 7),  # Sunday reopen, first bars of the week, day of the US DST switch
    datetime(2025, 3, 12, 20, 50),  # inside the rollover window (EDT)
    datetime(2025, 3, 31, 7, 13),  # London open after the UK DST switch
    datetime(2025, 4, 10, 13, 59),  # one minute before an H1 close
]


def pipeline(b: Bars) -> pl.DataFrame:
    return compute_features(b, POINT)


@pytest.fixture(scope="module")
def bars(syn_m1) -> Bars:
    return Bars.from_m1(syn_m1)


@pytest.fixture(scope="module")
def features(bars) -> pl.DataFrame:
    return pipeline(bars)


def test_every_feature_is_exercised(features) -> None:
    """The checks below only mean something if each feature has real values before
    the cut points (warm-ups done, flags firing)."""
    known = features.filter(pl.col("available_at") <= CUTOFFS[-1])
    empty = [c for c in feature_names() if known[c].drop_nulls().n_unique() < 2]
    assert not empty, f"features constant or empty in the synthetic history: {empty}"


def test_recomputation_on_truncated_history(bars) -> None:
    assert leakage.recomputation_check(pipeline, bars, CUTOFFS) == {}


def test_future_perturbation_changes_no_past_feature(bars) -> None:
    assert leakage.perturbation_check(pipeline, bars, CUTOFFS) == {}


def test_perturbation_really_changes_the_future(bars, features) -> None:
    t = CUTOFFS[3]
    other = pipeline(Bars.from_m1(leakage.perturb_after(bars.m1, t)))
    later = lambda f: f.filter(pl.col("available_at") > t + timedelta(hours=2))  # noqa: E731
    assert leakage.diff_columns(later(features), later(other)).get("range_atr", 0) > 0


def test_availability_audit(features) -> None:
    assert leakage.availability_audit(features) == {
        "available_before_event": 0,
        "available_not_bar_close": 0,
        "m15_closes_after_available": 0,
        "h1_closes_after_available": 0,
    }


def test_htf_context_is_the_last_closed_bar(features) -> None:
    by_t = {r["event_time"]: r for r in features.iter_rows(named=True)}
    # 10:55 closes at 11:00 together with the 10:00 H1 bar → that bar is visible.
    assert by_t[datetime(2025, 3, 12, 10, 55)]["h1_close_utc"] == datetime(2025, 3, 12, 11, 0)
    # 10:50 closes at 10:55 → the 10:00 H1 bar is still forming; 09:00 is the latest.
    assert by_t[datetime(2025, 3, 12, 10, 50)]["h1_close_utc"] == datetime(2025, 3, 12, 10, 0)
    assert by_t[datetime(2025, 3, 12, 10, 50)]["m15_close_utc"] == datetime(2025, 3, 12, 10, 45)


# ---------------------------------------------------------------- the checks catch leaks

LEAKS = {
    "leak_next_return": "the next bar's return (shift(-1))",
    "leak_centered_mean": "a centred moving average",
    "leak_global_zscore": "a z-score over the whole history",
    "leak_h1_forming": "H1 close joined on the H1 *open* time (forming bar)",
    "leak_day_high": "the full trading day's high",
}


def leaky_pipeline(b: Bars) -> pl.DataFrame:
    f = pipeline(b)
    close = b.m5.select(event_time="ts_utc", _c="close", _h="high")
    h1 = b.h1.sort("ts_utc").select(_h1_open="ts_utc", leak_h1_forming="close")
    c = pl.col("_c")
    return (
        f.join(close, on="event_time", how="left")
        .sort("event_time")
        .join_asof(h1, left_on="event_time", right_on="_h1_open", strategy="backward")
        .with_columns(
            leak_next_return=c.shift(-1) - c,
            leak_centered_mean=c.rolling_mean(5, center=True),
            leak_global_zscore=(c - c.mean()) / c.std(),
            leak_day_high=pl.col("_h").max().over("trading_day"),
        )
        .drop("_c", "_h", "_h1_open")
    )


def test_recomputation_names_every_leak(bars) -> None:
    found = leakage.recomputation_check(leaky_pipeline, bars, CUTOFFS)
    assert set(found) == set(LEAKS), found


def test_perturbation_names_every_leak(bars) -> None:
    found = leakage.perturbation_check(leaky_pipeline, bars, CUTOFFS)
    assert set(found) == set(LEAKS), found


def test_audit_catches_a_forming_htf_join(features) -> None:
    bad = features.with_columns(h1_close_utc=pl.col("h1_close_utc") + timedelta(hours=1))
    assert leakage.availability_audit(bad)["h1_closes_after_available"] > 0
    early = features.with_columns(available_at=pl.col("event_time"))
    assert leakage.availability_audit(early)["available_not_bar_close"] == early.height


# ---------------------------------------------------------------- access wrapper


def test_store_never_returns_a_future_row(features) -> None:
    store = FeatureStore(features)
    for t in CUTOFFS:
        rows = store.as_of(t)
        assert rows["available_at"].max() <= t
        assert rows.height == features.filter(pl.col("available_at") <= t).height
        latest = store.latest(t)
        assert latest is not None and latest["available_at"] <= t


def test_store_refuses_look_ahead(features) -> None:
    store = FeatureStore(features)
    bar = datetime(2025, 3, 12, 10, 50)
    assert store.bar(bar, decision_time=bar + timedelta(minutes=5))["event_time"] == bar
    with pytest.raises(LookAheadError):
        store.bar(bar, decision_time=bar + timedelta(minutes=4))
    with pytest.raises(KeyError):
        store.bar(datetime(2025, 3, 8, 12, 0), decision_time=datetime(2025, 4, 1))  # Saturday


def test_build_selfcheck_cuts_inside_market_hours() -> None:
    from candle_intel.features.build import selfcheck_cutoffs

    cuts = selfcheck_cutoffs(datetime(2021, 7, 5), datetime(2026, 9, 21, 7, 12))
    assert len(cuts) == 5
    assert all(c.weekday() == 2 and c.minute == 37 for c in cuts)  # Wednesday, mid-bar
    assert cuts == sorted(cuts) and cuts[-1] == datetime(2026, 9, 16, 14, 37)
