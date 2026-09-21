import json
from datetime import datetime, timedelta

import polars as pl
import pytest
from ci_api import main
from fastapi.testclient import TestClient

from candle_intel.config import Settings

DATASET = "xauusd_test_d20260101T000000Z"


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "derived" / "xauusd" / DATASET
    root.mkdir(parents=True)
    t0 = datetime(2026, 1, 5)
    m5 = pl.DataFrame(
        {
            "ts_utc": [t0 + timedelta(minutes=5 * i) for i in range(10)],
            "open": [float(i) for i in range(10)],
            "high": [i + 1.0 for i in range(10)],
            "low": [i - 1.0 for i in range(10)],
            "close": [i + 0.5 for i in range(10)],
            "tick_volume": list(range(10)),
            "m1_bars": [5] * 9 + [3],  # the last bar is incomplete
        }
    ).with_columns(pl.col("ts_utc").cast(pl.Datetime("us")), pl.col("m1_bars").cast(pl.Int16))
    m5.write_parquet(root / "M5.parquet")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": DATASET,
                "broker": "B",
                "broker_server": "S",
                "research_window_utc": ["a", "b"],
                "built_utc": "x",
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(storage_root=tmp_path, _env_file=None)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    main._manifest.cache_clear()
    return TestClient(main.app)


def test_latest_page_is_oldest_first_and_flags_incomplete(client) -> None:
    r = client.get("/api/candles", params={"tf": "M5", "limit": 4}).json()
    assert r["dataset_id"] == DATASET
    assert r["open"] == [6.0, 7.0, 8.0, 9.0]
    assert r["time"] == sorted(r["time"])
    assert r["incomplete"] == [False, False, False, True]
    assert r["has_more"] is True


def test_before_pages_backwards_without_overlap(client) -> None:
    first = client.get("/api/candles", params={"tf": "M5", "limit": 4}).json()
    older = client.get("/api/candles", params={"tf": "M5", "limit": 4, "before": first["time"][0]}).json()
    assert older["open"] == [2.0, 3.0, 4.0, 5.0]
    oldest = client.get("/api/candles", params={"tf": "M5", "limit": 4, "before": older["time"][0]}).json()
    assert oldest["open"] == [0.0, 1.0]
    assert oldest["has_more"] is False


def test_rejects_unknown_timeframe_and_dataset(client) -> None:
    assert client.get("/api/candles", params={"tf": "D1"}).status_code == 422
    assert client.get("/api/candles", params={"dataset": "nope"}).status_code == 404
    assert client.get("/api/candles", params={"dataset": "../../raw"}).status_code == 404
    assert client.get("/api/datasets/..%2F..%2Fraw/summary").status_code == 404
    assert client.get("/api/candles", params={"limit": 999999}).status_code == 422


# ---------------------------------------------------------------- features (Phase 3)


@pytest.fixture
def feature_client(client, tmp_path):
    fs = tmp_path / "derived" / "xauusd" / DATASET / "features" / "s_f20260101T000000Z"
    fs.mkdir(parents=True)
    t0 = datetime(2026, 1, 5)
    ev = [t0 + timedelta(minutes=5 * i) for i in range(24)]  # 2 hours of M5
    pl.DataFrame(
        {
            "event_time": ev,
            "available_at": [t + timedelta(minutes=5) for t in ev],
            "ts_server": ev,
            "trading_day": [t0.date()] * 24,
            "m15_close_utc": [t0] * 24,
            "h1_close_utc": [t0] * 24,
            "in_research_window": [True] * 24,
            "range_atr": [float(i) for i in range(23)] + [float("nan")],
            "session": ["london"] * 24,
        }
    ).with_columns(
        pl.col("event_time", "available_at", "ts_server", "m15_close_utc", "h1_close_utc").cast(
            pl.Datetime("us")
        )
    ).write_parquet(fs / "features_M5.parquet")
    (fs / "feature_set.json").write_text(
        json.dumps(
            {
                k: k
                for k in (
                    "feature_set_id feature_version dataset_id companion_cost_model_id row_semantics "
                    "built_utc code_version config_hash groups schema leakage_selfcheck summary files"
                ).split()
            }
        ),
        encoding="utf-8",
    )
    return client


def epoch(t: datetime) -> int:
    return int((t - datetime(1970, 1, 1)).total_seconds())


def test_feature_bar_maps_every_timeframe_to_its_m5_bar(feature_client) -> None:
    t0 = datetime(2026, 1, 5)
    r = feature_client.get(
        f"/api/features/{DATASET}/bar", params={"time": epoch(t0 + timedelta(minutes=10))}
    ).json()
    assert r["values"]["range_atr"] == 2.0 and r["mapped"] is False
    assert r["meta"]["available_at"] == epoch(t0 + timedelta(minutes=15))
    # M1 minute 12 → the M5 bar opening at 10
    r = feature_client.get(
        f"/api/features/{DATASET}/bar", params={"time": epoch(t0 + timedelta(minutes=12)), "tf": "M1"}
    ).json()
    assert r["meta"]["event_time"] == epoch(t0 + timedelta(minutes=10)) and r["mapped"] is True
    # H1 bar at 00:00 → its last M5 bar, 00:55
    r = feature_client.get(f"/api/features/{DATASET}/bar", params={"time": epoch(t0), "tf": "H1"}).json()
    assert r["meta"]["event_time"] == epoch(t0 + timedelta(minutes=55))
    # NaN is served as null; no cost model → costs is null
    r = feature_client.get(
        f"/api/features/{DATASET}/bar", params={"time": epoch(t0 + timedelta(minutes=115))}
    ).json()
    assert r["values"]["range_atr"] is None and r["costs"] is None


def test_feature_endpoints_reject_bad_input(feature_client) -> None:
    assert feature_client.get(f"/api/features/{DATASET}").json()["feature_set_id"] == "feature_set_id"
    assert feature_client.get(f"/api/features/{DATASET}/bar", params={"time": 0}).status_code == 404
    assert feature_client.get("/api/features/../bar", params={"time": 0}).status_code == 404
    assert (
        feature_client.get(f"/api/features/{DATASET}/bar", params={"time": 0, "tf": "D1"}).status_code == 422
    )


def test_features_404_without_a_feature_set(client) -> None:
    assert client.get(f"/api/features/{DATASET}").status_code == 404
