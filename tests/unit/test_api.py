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
