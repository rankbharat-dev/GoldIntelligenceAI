import pytest
from pydantic import ValidationError

from candle_intel.config import Settings


@pytest.mark.parametrize("symbol", ["XAUUSD", "XAUUSD.m", "XAUUSDm", "XAUUSD_i", "GOLD", "GOLD.pro"])
def test_gold_symbols_accepted(symbol: str) -> None:
    assert Settings(mt5_broker_symbol=symbol, _env_file=None).mt5_broker_symbol == symbol


@pytest.mark.parametrize("symbol", ["EURUSD", "BTCUSD", "XAGUSD", "US30", "XAUEUR", "GOLDEN_GOOSE_1"])
def test_non_gold_symbols_rejected(symbol: str) -> None:
    with pytest.raises(ValidationError):
        Settings(mt5_broker_symbol=symbol, _env_file=None)


def test_redacted_never_contains_password() -> None:
    s = Settings(mt5_login=123, mt5_password="hunter2", mt5_server="Demo", _env_file=None)
    dumped = repr(s.redacted())
    assert "hunter2" not in dumped
    assert "123" not in dumped
    assert "hunter2" not in repr(s)
