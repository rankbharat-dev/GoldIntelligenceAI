"""Project settings.

The instrument is fixed at the type level: there is no setting that selects a
different market. The only symbol knob is the *broker's* name for gold, because
brokers spell XAUUSD differently (``XAUUSD``, ``XAUUSD.m``, ``GOLD`` ...).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Final

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CANONICAL_SYMBOL: Final = "XAUUSD"

# Timeframes this project researches (blueprint v1.1 §1). Nothing else is served.
RESEARCH_TIMEFRAMES: Final = ("M1", "M5", "M15", "H1")

# Broker spellings of spot gold vs USD. Anything else is rejected.
_BROKER_GOLD_SYMBOL = re.compile(r"^(XAUUSD|GOLD)([._\-]?[A-Za-z0-9]{0,6})?$")

PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CI_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- MT5 ---------------------------------------------------------------
    mt5_broker_symbol: str = Field(
        default=CANONICAL_SYMBOL,
        description="Broker's symbol name for spot gold, e.g. XAUUSD or XAUUSD.m",
    )
    mt5_terminal_path: Path | None = Field(
        default=None,
        description="terminal64.exe path. Omit to attach to the running terminal.",
    )
    # Optional headless login. Leave unset to attach to the terminal's current
    # session. Use the account's INVESTOR (read-only) password where possible.
    mt5_login: int | None = None
    mt5_password: SecretStr | None = None
    mt5_server: str | None = None
    mt5_timeout_ms: int = 60_000

    # --- MCP guard rails -----------------------------------------------------
    # MCP output caps. The MCP feeds an LLM context window, not a research pipeline.
    mcp_max_bars: int = Field(default=5_000, ge=1, le=50_000)
    mcp_max_ticks: int = Field(default=20_000, ge=1, le=200_000)

    # --- Storage -------------------------------------------------------------
    storage_root: Path = PROJECT_ROOT / "storage"
    postgres_dsn: SecretStr = SecretStr(
        "postgresql+psycopg://candle:candle@localhost:5434/candle_intelligence"
    )

    @field_validator("mt5_broker_symbol")
    @classmethod
    def _gold_only(cls, v: str) -> str:
        if not _BROKER_GOLD_SYMBOL.match(v):
            raise ValueError(
                f"mt5_broker_symbol={v!r} is not a spot-gold symbol. This project is XAUUSD-only."
            )
        return v

    def redacted(self) -> dict[str, object]:
        """Settings safe to print or put in a report — never includes credentials."""
        return {
            "mt5_broker_symbol": self.mt5_broker_symbol,
            "mt5_terminal_path": str(self.mt5_terminal_path) if self.mt5_terminal_path else None,
            "mt5_login_configured": self.mt5_login is not None,
            "mt5_server": self.mt5_server,
            "storage_root": str(self.storage_root),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
