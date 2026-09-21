from datetime import UTC, datetime

import pytest

from candle_intel.ingest.mt5_session import to_epoch_seconds

EPOCH_2026 = 1_767_225_600  # 2026-01-01T00:00:00 encoded as MT5 does (wall time as UTC)


def test_naive_wall_time_is_encoded_independent_of_machine_timezone() -> None:
    # Regression: the MetaTrader5 package reads naive datetimes as machine-local time,
    # which shifted range queries by 5.5 h on an IST machine.
    assert to_epoch_seconds(datetime(2026, 1, 1)) == EPOCH_2026


def test_aware_datetime_is_rejected_as_ambiguous() -> None:
    with pytest.raises(ValueError):
        to_epoch_seconds(datetime(2026, 1, 1, tzinfo=UTC))
