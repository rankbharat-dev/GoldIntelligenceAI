"""Phase 9: account cost profiles. A Raw Spread account's ticks (here: a quarter of the
demo's spread, with zero-spread quotes) calibrate a Raw profile over the whole bar
history and pass the Phase 2 acceptance test; before such ticks exist, a provisional
Raw profile charges the demo spread (upper bound) + the owner's commission; runs
record their profile, and promotion waits for the calibrated Raw profile."""

import hashlib
import json
from datetime import timedelta

import polars as pl
import pytest

from candle_intel.config import Settings
from candle_intel.costs import build, execution, profiles, spread
from candle_intel.research import checklist
from tests.unit.test_costs import DERIVED, RAW, TICK_FROM, _level, _synthetic_storage

RAW2 = "xauusd_test-raw_20260302T000000Z"
RAW_SHARE = 0.25


def _raw_account_ticks(root) -> None:
    """A second raw archive: same minutes, a Raw account quoting 25 % of the demo's spread,
    0.0 for the first 10 s of every 5th minute."""
    m1 = pl.read_parquet(root / "derived" / "xauusd" / DERIVED / "M1.parquet")
    d = root / "raw" / "xauusd" / RAW2
    (d / "ticks").mkdir(parents=True)
    by_day: dict = {}
    for mt in m1.filter(pl.col("ts_utc") >= TICK_FROM)["ts_utc"].to_list():
        raw_pts = round(_level(mt) * RAW_SHARE)
        rows = [(mt, 4000.0, 4000.0 + (0 if mt.minute % 5 == 0 else raw_pts) * 0.001)]
        rows.append((mt + timedelta(seconds=10), 4000.0, 4000.0 + raw_pts * 0.001))
        by_day.setdefault(mt.date(), []).extend(rows)
    chunks = []
    for day, rows in sorted(by_day.items()):
        f = d / "ticks" / f"{day}.parquet"
        pl.DataFrame(rows, schema=["ts_server", "bid", "ask"], orient="row").with_columns(
            pl.col("ts_server").cast(pl.Datetime("ms"))
        ).write_parquet(f)
        chunks.append({"day": str(day), "file": f.name, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
    session = {"server_offset_hours": 0.0, "account_label": "raw", "broker_server": "Test-Server"}
    (d / "manifest.json").write_text(
        json.dumps({"raw_version": RAW2, "session": session, "tick_chunks": chunks})
    )
    # the demo archive needs a session block too (older test storage has none)
    own = root / "raw" / "xauusd" / RAW / "manifest.json"
    m = json.loads(own.read_text())
    m["session"] = {"server_offset_hours": 0.0, "account_label": "standard"}
    own.write_text(json.dumps(m))
    man = root / "derived" / "xauusd" / DERIVED / "manifest.json"
    dm = json.loads(man.read_text())
    dm["raw_manifest_sha256"] = hashlib.sha256(own.read_bytes()).hexdigest()
    man.write_text(json.dumps(dm))


@pytest.fixture(scope="module")
def storage(tmp_path_factory):
    root = tmp_path_factory.mktemp("storage")
    _synthetic_storage(root)
    _raw_account_ticks(root)
    mp = pytest.MonkeyPatch()
    settings = Settings(storage_root=root, _env_file=None)
    mp.setattr(build, "get_settings", lambda: settings)
    mp.setattr(profiles, "get_settings", lambda: settings)
    mp.setattr(build, "_register", lambda doc: None)
    mp.setattr(spread, "CURRENT_DAYS", 5)
    ds = root / "derived" / "xauusd" / DERIVED
    demo = build.build(ds)
    provisional = profiles.build_provisional_raw(ds, 10.0)
    c = execution.Commission(per_lot_round_turn_usd=10.0, confirmed=True)
    raw = build.build(ds, c, "raw", RAW2)
    yield ds, demo, provisional, raw
    mp.undo()


def _doc(p):
    return json.loads((p / "cost_model.json").read_text(encoding="utf-8"))


def test_raw_profile_is_calibrated_and_validated(storage) -> None:
    _, demo, _, raw = storage
    d = _doc(raw)
    assert d["profile"] == "raw" and d["status"] == "validated" and d["tick_source_raw_version"] == RAW2
    assert d["validation"]["passed"]
    assert d["tick_window"]["ticks_rejected"]["nonpositive"] == 0  # zero spreads are real on Raw
    assert d["execution"]["commission"]["per_lot_round_turn_usd"] == 10.0
    rc = pl.read_parquet(raw / "M1_costs.parquet")
    dc = pl.read_parquet(demo / "M1_costs.parquet")
    # pre-tick history is priced from the demo bars' level × the Raw ratio (~25 %)
    early = rc.filter((pl.col("ts_utc") < TICK_FROM) & ~pl.col("level_imputed"))
    ratio = (early["spread_base"] / early["spread_level"]).median()
    assert 0.15 <= ratio <= 0.3
    j = rc.join(dc, on="ts_utc", suffix="_demo")
    assert (j["spread_base"] <= j["spread_base_demo"]).all()
    assert (rc["spread_optimistic"] <= rc["spread_base"]).all()
    assert (rc["spread_base"] <= rc["spread_pessimistic"]).all()


def test_provisional_raw_is_an_upper_bound_with_the_owner_commission(storage) -> None:
    _, demo, prov, _ = storage
    d = _doc(prov)
    assert (d["profile"], d["status"]) == ("raw", "provisional")
    assert "upper bound" in d["spread_basis"]
    assert pl.read_parquet(prov / "M1_costs.parquet").equals(pl.read_parquet(demo / "M1_costs.parquet"))
    c = execution.Commission(**d["execution"]["commission"])
    for s in execution.SCENARIOS.values():
        assert c.usd(1.0, s) == 10.0  # a stated account term: every scenario pays it


def test_newest_prefers_validated_and_listing(storage) -> None:
    ds, demo, prov, raw = storage
    assert profiles.newest(ds, "raw") == raw  # validated beats the (older) provisional
    assert profiles.newest(ds) == demo
    rows = {r["profile"]: r for r in profiles.listing(ds)}
    assert rows["raw"]["status"] == "validated" and rows["demo_trial7"]["status"] == "validated"
    assert profiles.active() == "demo_trial7"
    profiles.set_active("raw", ds)
    assert profiles.active() == "raw"
    with pytest.raises(ValueError):
        profiles.set_active("nope", ds)
    profiles.set_active("demo_trial7", ds)


def test_checklist_waits_for_the_calibrated_raw_profile() -> None:
    def doc(prof, status):
        m = {"n": 2000, "expectancy_r": 0.2, "profit_factor": 1.5, "max_dd_r": 5, "max_dd_pct": 0.05}
        ab = m | {"stability": {"year": {"score": 0.8}, "session": {"score": 0.8}}, "ambiguity_rate": 0.01}
        return (
            {"results": {"pessimistic": m}},
            {"results": {"pessimistic": m}},
            {
                "results": {"pessimistic": ab},
                "deflated_sharpe": {"deflated_excess": 0.1, "n_trials": 3},
                "lineage": {"cost_profile": prof, "cost_profile_status": status},
            },
        )

    demo = checklist.evaluate(*doc("demo_trial7", "validated"), None, 0)
    item = next(i for i in demo["items"] if i["key"] == "cost_profile")
    assert item["passed"] is None and not demo["ready_to_unseal"] and demo["passes_pre_holdout"]
    prov = checklist.evaluate(*doc("raw", "provisional"), None, 0)
    assert not prov["ready_to_unseal"]
    raw = checklist.evaluate(*doc("raw", "validated"), None, 0)
    assert next(i for i in raw["items"] if i["key"] == "cost_profile")["passed"] is True
    assert raw["ready_to_unseal"]
