"""Cost model (blueprint §6): tick weighting, cells and fallback, scenarios,
slippage / commission / swap, validation, and an end-to-end build on synthetic
storage whose true spreads are known."""

import hashlib
import json
from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest

from candle_intel.config import Settings
from candle_intel.costs import build, execution, spread, ticks, validate, volatility

SPEC = {
    "point": 0.001,
    "trade_contract_size": 100.0,
    "swap_mode": 1,
    "swap_long": -549.3,
    "swap_short": 0.0,
    "swap_rollover3days": 3,  # MT5: Wednesday
}


def _weekly(offset: float, start: datetime, weeks: int) -> pl.DataFrame:
    days = [start + timedelta(weeks=i) for i in range(weeks + 1)]
    return pl.DataFrame(
        {
            "iso_year": [d.isocalendar().year for d in days],
            "iso_week": [d.isocalendar().week for d in days],
            "offset_hours": [offset] * len(days),
        }
    ).with_columns(pl.col("iso_year").cast(pl.Int32), pl.col("iso_week").cast(pl.Int8))


# ---------------------------------------------------------------- ticks


def test_quotes_are_time_weighted_capped_and_converted_to_utc() -> None:
    t0 = datetime(2026, 3, 2, 10, 0, 0)  # server time, broker at UTC+2
    tk = pl.DataFrame(
        {
            "ts_server": [
                t0,
                t0 + timedelta(seconds=10),
                t0 + timedelta(seconds=12),
                t0 + timedelta(seconds=300),
            ],
            "bid": [4000.101, 4000.101, 4000.101, 4000.101],
            "ask": [4000.191, 4000.251, 4000.191, 4000.191],  # 90, 150, 90, 90 points (float noise)
        }
    ).with_columns(pl.col("ts_server").cast(pl.Datetime("ms")))
    hist, rejected = ticks.histogram(tk, _weekly(2.0, t0, 1), SPEC["point"])
    assert rejected == {"nonpositive": 0, "no_clock": 0}
    m = ticks.minutes(hist)
    first = m.row(0, named=True)
    assert first["ts_utc"] == datetime(2026, 3, 2, 8, 0)
    # 90 for 10 s, 150 for 2 s, then 90 for 288 s capped to 60 s.
    assert first["seconds"] == pytest.approx(72.0)
    assert first["spread_twmean"] == pytest.approx((90 * 70 + 150 * 2) / 72)
    assert (first["spread_min"], first["spread_max"]) == (90, 150)


def test_weighted_quantiles_are_exact() -> None:
    df = pl.DataFrame({"v": [10, 20, 30], "seconds": [300.0, 180.0, 120.0]})
    q = spread.weighted_quantiles(df, (), "v").row(0, named=True)
    assert (q["p25"], q["p50"], q["p90"], q["p99"]) == (10, 10, 30, 30)
    assert q["mean"] == pytest.approx(17.0)
    assert q["minutes"] == pytest.approx(10.0)


# ---------------------------------------------------------------- cells


def _khist() -> pl.DataFrame:
    """Hour 10 Monday is rich; hour 11 Monday has 10 s of quotes (too sparse)."""
    rows = []
    for vb, sp in (("low", 50), ("mid", 60), ("high", 70)):
        rows.append((10, 1, vb, sp, 3600.0 * 2))
    rows.append((11, 1, "mid", 500, 10.0))
    rows.append((11, 2, "mid", 80, 3600.0 * 2))
    return pl.DataFrame(
        rows, schema=["hour_utc", "dow", "vol_bucket", "spread_points", "seconds"], orient="row"
    ).with_columns(pl.col("hour_utc").cast(pl.Int8), pl.col("dow").cast(pl.Int8), ratio=pl.lit(1.0))


def test_lookup_uses_the_finest_cell_with_enough_quoted_time() -> None:
    table = spread.cells(_khist(), "abs", "t")
    keys = pl.DataFrame(
        {"hour_utc": [10, 11, 5], "dow": [1, 1, 3], "vol_bucket": ["high", "mid", "low"]}
    ).with_columns(pl.col("hour_utc").cast(pl.Int8), pl.col("dow").cast(pl.Int8))
    got = spread.lookup(keys, table).sort("hour_utc")
    # hour 5: nothing at hour level → global cell
    assert got["cell_level"].to_list() == [3, 0, 2]
    assert got["p50"].to_list()[1] == 70  # exact cell
    assert got["p50"].to_list()[2] == 80  # hour 11 pooled over weekdays: the 10 s outlier is diluted


def test_lookup_survives_an_empty_global_cell() -> None:
    table = spread.cells(_khist(), "abs", "t").with_columns(minutes=pl.lit(0.0))
    keys = pl.DataFrame({"hour_utc": [10], "dow": [1], "vol_bucket": ["low"]}).with_columns(
        pl.col("hour_utc").cast(pl.Int8), pl.col("dow").cast(pl.Int8)
    )
    got = spread.lookup(keys, table)
    assert got.height == 1 and got["p50"][0] is None


# ---------------------------------------------------------------- volatility


def test_volatility_is_known_at_the_bar_open() -> None:
    n = 400
    rng = np.random.default_rng(1)
    close = 2000 + np.cumsum(rng.normal(0, 1, n))
    m5 = pl.DataFrame(
        {
            "ts_utc": [datetime(2026, 1, 5) + timedelta(minutes=5 * i) for i in range(n)],
            "high": close + 1,
            "low": close - 1,
            "close": close,
        }
    )
    base = volatility.m5_volatility(m5, 0.001)
    shocked = volatility.m5_volatility(
        m5.with_columns(
            pl.when(pl.int_range(pl.len()) == n - 1).then(9999.0).otherwise(pl.col("high")).alias("high")
        ),
        0.001,
    )
    assert base["atr_points"][-1] == shocked["atr_points"][-1]  # the bar's own range is not used
    assert base["atr_points"][-2] == pytest.approx(2000.0, rel=0.5)


# ---------------------------------------------------------------- execution


def test_rollovers_follow_new_york_17h_across_dst_and_weekends() -> None:
    # Summer: 17:00 NY = 21:00 UTC. Mon 20:00 → Tue 23:00 UTC crosses Mon and Tue.
    assert len(execution.rollovers(datetime(2026, 7, 6, 20), datetime(2026, 7, 7, 23))) == 2
    # Winter: 17:00 NY = 22:00 UTC. Mon 21:30 → Mon 23:00 crosses Monday's rollover.
    assert len(execution.rollovers(datetime(2026, 1, 12, 21, 30), datetime(2026, 1, 12, 23))) == 1
    # ...but Mon 21:30 → Mon 21:55 does not (it would in summer).
    assert execution.rollovers(datetime(2026, 1, 12, 21, 30), datetime(2026, 1, 12, 21, 55)) == []
    # Friday → Monday: only Friday's rollover; the weekend is paid on Wednesday.
    assert len(execution.rollovers(datetime(2026, 7, 10, 20), datetime(2026, 7, 13, 20))) == 1


def test_swap_charges_triple_on_wednesday_and_only_the_quoted_side() -> None:
    wed_to_thu = (datetime(2026, 7, 8, 20), datetime(2026, 7, 9, 20))
    assert execution.swap_nights(*wed_to_thu, SPEC) == 3
    assert execution.swap_usd("long", 1.0, *wed_to_thu, SPEC) == pytest.approx(3 * 54.93)
    assert execution.swap_usd("short", 1.0, *wed_to_thu, SPEC) == 0.0
    assert execution.swap_usd("long", 1.0, datetime(2026, 7, 6, 10), datetime(2026, 7, 6, 12), SPEC) == 0.0
    with pytest.raises(NotImplementedError):
        execution.swap_usd("long", 1.0, *wed_to_thu, SPEC | {"swap_mode": 2})


def test_slippage_is_adverse_ordered_and_widened_in_windows() -> None:
    atr = 5000.0
    s = execution.SCENARIOS
    for order in ("market", "stop"):
        o, b, p = (execution.slippage_points(order, atr, s[k]) for k in ("optimistic", "base", "pessimistic"))
        assert 0 <= o <= b <= p
    for sc in s.values():
        assert execution.slippage_points("stop", atr, sc) >= execution.slippage_points("market", atr, sc)
        assert execution.slippage_points("stop", atr, sc, in_window=True) >= execution.slippage_points(
            "stop", atr, sc
        )
        assert execution.slippage_points("limit", atr, sc) == 0.0
    assert execution.slippage_points("stop", atr, s["base"], in_window=True) == pytest.approx(
        2 * (10 + 0.02 * atr)
    )


def test_pessimistic_commission_is_conservative_until_confirmed() -> None:
    s = execution.SCENARIOS
    unconfirmed = execution.Commission()
    assert unconfirmed.usd(2.0, s["base"]) == 0.0
    assert unconfirmed.usd(2.0, s["pessimistic"]) == 14.0
    confirmed = execution.Commission(per_lot_round_turn_usd=0.0, confirmed=True)
    assert confirmed.usd(2.0, s["pessimistic"]) == 0.0


def test_validation_metrics_on_a_perfect_prediction() -> None:
    df = pl.DataFrame(
        {"spread_twmean": [90.0, 100.0], "p50": [90.0, 100.0], "p90": [90.0, 100.0], "p99": [95.0, 120.0]}
    )
    m = validate.metrics(df)
    assert m["relative_bias_p50"] == 0 and m["coverage_p90"] == 1 and m["mae_p50"] == 0


# ---------------------------------------------------------------- end to end


RAW = "xauusd_test_20260301T000000Z"
DERIVED = "xauusd_test_d20260301T000000Z"
T0 = datetime(2026, 1, 4, 22, 0)  # Sunday open, broker clock = UTC
TICK_FROM = datetime(2026, 1, 12)  # ticks cover the last two weeks only


def _level(ts: datetime) -> int:
    return 40 if ts < datetime(2026, 1, 18) else 90  # a broker tier change inside the tick window


def _synthetic_storage(root) -> None:
    rng = np.random.default_rng(3)
    ts, t = [], T0
    while t < T0 + timedelta(weeks=3):
        if t.weekday() < 5 or (t.weekday() == 6 and t.hour >= 22):
            if not (t.weekday() == 4 and t.hour >= 21):
                ts.append(t)
        t += timedelta(minutes=1)
    n = len(ts)
    close = 4000 + np.cumsum(rng.normal(0, 0.5, n))
    spread_pts = [(_level(x) if i % 997 else 0) for i, x in enumerate(ts)]  # a few broken snapshots
    m1 = pl.DataFrame(
        {
            "ts_utc": ts,
            "ts_server": ts,
            "open": close,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "spread_points": spread_pts,
        }
    ).with_columns(pl.col("spread_points").cast(pl.Int32))
    m5 = m1.group_by_dynamic("ts_utc", every="5m").agg(
        pl.col("high").max(), pl.col("low").min(), pl.col("close").last()
    )

    raw_dir = root / "raw" / "xauusd" / RAW
    (raw_dir / "ticks").mkdir(parents=True)
    chunks = []
    tick_minutes = m1.filter(pl.col("ts_utc") >= TICK_FROM)["ts_utc"].to_list()
    by_day: dict = {}
    for mt in tick_minutes:
        lvl = _level(mt)
        for s, mult in ((0, 1), (20, 2 if mt.minute % 10 == 0 else 1), (40, 1)):
            by_day.setdefault(mt.date(), []).append(
                (mt + timedelta(seconds=s), 4000.0, 4000.0 + lvl * mult * 0.001)
            )
    for d, rows in sorted(by_day.items()):
        f = raw_dir / "ticks" / f"{d}.parquet"
        pl.DataFrame(rows, schema=["ts_server", "bid", "ask"], orient="row").with_columns(
            pl.col("ts_server").cast(pl.Datetime("ms"))
        ).write_parquet(f)
        chunks.append(
            {
                "day": str(d),
                "file": f.name,
                "rows": len(rows),
                "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
            }
        )
    (raw_dir / "manifest.json").write_text(
        json.dumps({"raw_version": RAW, "tick_chunks": chunks}), encoding="utf-8"
    )

    out = root / "derived" / "xauusd" / DERIVED
    out.mkdir(parents=True)
    m1.write_parquet(out / "M1.parquet")
    m5.write_parquet(out / "M5.parquet")
    _weekly(0.0, T0, 3).write_parquet(out / "clock_weekly.parquet")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": DERIVED,
                "raw_version": RAW,
                "raw_manifest_sha256": hashlib.sha256((raw_dir / "manifest.json").read_bytes()).hexdigest(),
                "broker": "Test Broker",
                "broker_server": "Test-Server",
                "price_side": "bid",
                "research_window_utc": [str(T0), str(ts[-1])],
                "symbol_spec": SPEC,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("storage")
    _synthetic_storage(root)
    mp = pytest.MonkeyPatch()
    settings = Settings(storage_root=root, _env_file=None)
    mp.setattr(build, "get_settings", lambda: settings)
    mp.setattr(build, "_register", lambda doc: None)  # never write test rows to the real database
    mp.setattr(spread, "CURRENT_DAYS", 5)  # "current" = the last week, all on the new tier
    out = build.build(root / "derived" / "xauusd" / DERIVED)
    yield root, out
    mp.undo()


def test_build_writes_a_hashed_versioned_model(built) -> None:
    _, out = built
    doc = json.loads((out / "cost_model.json").read_text(encoding="utf-8"))
    for name, meta in doc["files"].items():
        path = out / (f"{name}.json" if name == "validation" else f"{name}.parquet")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == meta["sha256"]
    assert doc["dataset_id"] == DERIVED and doc["config_hash"]
    assert build.cost_models(out.parents[1]) == [out]


def test_every_bar_is_priced_with_ordered_scenarios(built) -> None:
    root, out = built
    m1 = pl.read_parquet(root / "derived" / "xauusd" / DERIVED / "M1.parquet")
    c = pl.read_parquet(out / "M1_costs.parquet")
    assert c.height == m1.height
    scen = c.select("spread_optimistic", "spread_base", "spread_pessimistic")
    assert scen.null_count().sum_horizontal().item() == 0
    assert (c["spread_optimistic"] <= c["spread_base"]).all()
    assert (c["spread_base"] <= c["spread_pessimistic"]).all()
    assert (c["spread_pessimistic"] >= c["spread_current_p90"]).all()


def test_measured_where_ticks_exist_modeled_elsewhere(built) -> None:
    _, out = built
    c = pl.read_parquet(out / "M1_costs.parquet")
    measured = c.filter(pl.col("spread_source") == "measured")
    assert measured["ts_utc"].min() >= TICK_FROM
    assert c.filter(pl.col("ts_utc") < TICK_FROM)["spread_source"].unique().to_list() == ["modeled"]
    assert (measured["spread_base"] == measured["spread_obs"]).all()
    # Minutes with a 2× spike for 20 of 60 s: time-weighted mean = level × 4/3.
    spiky = measured.filter((pl.col("ts_utc").dt.minute() % 10 == 0) & ~pl.col("level_imputed"))
    assert spiky["spread_obs"].to_list() == pytest.approx((spiky["spread_level"] * 4 / 3).to_list())


def test_modeled_history_follows_the_bar_level_not_todays_tier(built) -> None:
    _, out = built
    c = pl.read_parquet(out / "M1_costs.parquet")
    early = c.filter((pl.col("ts_utc") < TICK_FROM) & ~pl.col("level_imputed"))
    assert early["spread_level"].unique().to_list() == [40]
    assert early["spread_base"].max() <= 40 * 2  # scaled from 40, not from today's 90
    # ...but the promotion gate charges at least the recent tier.
    assert early["spread_pessimistic"].min() >= 90
    imputed = c.filter(pl.col("level_imputed"))
    assert imputed.height > 0 and (imputed["spread_level"] > 0).all()


def test_m5_costs_are_the_entry_minute(built) -> None:
    _, out = built
    m1 = pl.read_parquet(out / "M1_costs.parquet")
    m5 = pl.read_parquet(out / "M5_costs.parquet")
    j = m5.join(m1, on="ts_utc", suffix="_m1")
    assert j.height == m5.height
    assert (j["spread_base"] == j["spread_base_m1"]).all()


def test_validation_report_scores_both_models(built) -> None:
    _, out = built
    v = json.loads((out / "validation.json").read_text(encoding="utf-8"))
    assert set(v["models"]) == {"level_x_ratio", "abs_cells"}
    assert v["holdout_minutes"] > 0
    a = v["models"]["level_x_ratio"]
    assert abs(a["relative_bias_p50"]) < 0.15 and a["coverage_p90"] >= 0.85


def test_api_serves_costs_heatmap_and_levels(built, monkeypatch) -> None:
    from ci_api import main
    from fastapi.testclient import TestClient

    root, out = built
    settings = Settings(storage_root=root, _env_file=None)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._manifest.cache_clear()
    client = TestClient(main.app)

    s = client.get(f"/api/costs/{DERIVED}").json()
    assert s["cost_model_id"] == out.name and s["validation"]["chosen_model"] == "level_x_ratio"
    assert set(s["execution"]["scenarios"]) == {"optimistic", "base", "pessimistic"}

    h = client.get("/api/costs/latest/heatmap", params={"stat": "p90", "window": "current"}).json()
    assert len(h["values"]) == 7 and all(len(r) == 24 for r in h["values"])
    monday_10 = h["values"][0][10]
    assert monday_10 is not None and monday_10 >= 90
    assert h["values"][5][10] is None  # Saturday: market closed, no cell

    r = client.get("/api/costs/latest/heatmap", params={"basis": "ratio", "vol": "high"}).json()
    assert r["unit"] == "x minute minimum"
    assert (
        client.get("/api/costs/latest/heatmap", params={"basis": "ratio", "window": "current"}).status_code
        == 422
    )
    assert client.get("/api/costs/latest/heatmap", params={"stat": "p75"}).status_code == 422
    assert client.get("/api/costs/..%2F..%2Fraw").status_code == 404

    lv = client.get("/api/costs/latest/levels").json()
    assert len(lv["time"]) == len(lv["level_median"]) == len(lv["measured_mean"])
    assert lv["measured_mean"][0] is None and lv["measured_mean"][-1] is not None
