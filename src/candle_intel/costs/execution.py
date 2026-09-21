"""Execution costs beyond the spread: slippage, commission, swap (blueprint §6).

All price-like quantities are in **points** (the symbol's ``point``, 0.001 USD on
XAUUSD) unless a name says ``usd``. Money per lot follows the frozen symbol spec:
``usd = points × point × contract_size × lots``.

Slippage parameters are *assumptions* — a demo account produces no fills to
calibrate against. They are deliberately explicit, versioned with the cost model,
and to be re-fitted from simulated-vs-live fills in paper trading (Phase 9).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")

OrderType = Literal["market", "stop", "limit"]
Side = Literal["long", "short"]
ScenarioName = Literal["optimistic", "base", "pessimistic"]


@dataclass(frozen=True)
class Slippage:
    fixed_points: float
    atr_frac: float  # share of M5 ATR(14) known at the order time

    def points(self, atr_points: float) -> float:
        return self.fixed_points + self.atr_frac * max(atr_points, 0.0)


@dataclass(frozen=True)
class Scenario:
    name: ScenarioName
    spread_column: str  # column of the bar cost tables
    market: Slippage  # market orders: fixed + volatility-proportional
    stop: Slippage  # stop orders: always adverse
    window_multiplier: float  # stop slippage multiplier inside rollover / news windows
    use_unconfirmed_commission: bool  # charge the conservative commission until A4 is confirmed


SCENARIOS: dict[ScenarioName, Scenario] = {
    "optimistic": Scenario(
        "optimistic", "spread_optimistic", Slippage(0.0, 0.0), Slippage(0.0, 0.005), 1.0, False
    ),
    "base": Scenario("base", "spread_base", Slippage(5.0, 0.01), Slippage(10.0, 0.02), 2.0, False),
    "pessimistic": Scenario(
        "pessimistic", "spread_pessimistic", Slippage(15.0, 0.03), Slippage(30.0, 0.05), 3.0, True
    ),
}


@dataclass(frozen=True)
class Commission:
    per_lot_round_turn_usd: float = 0.0
    confirmed: bool = False  # Appendix A4: commission for this account type not yet confirmed
    unconfirmed_pessimistic_usd: float = 7.0  # typical raw-spread-account charge, used until confirmed

    def usd(self, lots: float, scenario: Scenario) -> float:
        rate = self.per_lot_round_turn_usd
        if scenario.use_unconfirmed_commission and not self.confirmed:
            rate = max(rate, self.unconfirmed_pessimistic_usd)
        return rate * lots


def slippage_points(
    order: OrderType, atr_points: float, scenario: Scenario, in_window: bool = False
) -> float:
    """Adverse slippage of one fill, in points (always ≥ 0: it is a cost).

    ``in_window`` = inside the rollover window (bar column ``in_rollover_window``)
    or a news window; it widens stop slippage only. Limit orders fill at their price.
    """
    if order == "limit":
        return 0.0
    if order == "market":
        return scenario.market.points(atr_points)
    mult = scenario.window_multiplier if in_window else 1.0
    return scenario.stop.points(atr_points) * mult


def points_to_usd(points: float, lots: float, spec: dict[str, Any]) -> float:
    return points * spec["point"] * spec["trade_contract_size"] * lots


# ---------------------------------------------------------------- swap

_MT5_WEEKDAY_TO_ISO = {0: 7, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}  # MT5: 0 = Sunday


def rollovers(entry_utc: datetime, exit_utc: datetime) -> list[date]:
    """New York dates whose 17:00 NY rollover falls in (entry, exit]. Weekdays only:
    gold does not roll on Saturday or Sunday (the weekend is charged on the
    triple-swap day instead). Naive datetimes are UTC."""
    if exit_utc <= entry_utc:
        return []
    start = _aware(entry_utc).astimezone(NEW_YORK)
    end = _aware(exit_utc).astimezone(NEW_YORK)
    out, d = [], start.date()
    while d <= end.date():
        roll = datetime(d.year, d.month, d.day, 17, tzinfo=NEW_YORK)
        if d.isoweekday() <= 5 and start < roll <= end:
            out.append(d)
        d += timedelta(days=1)
    return out


def swap_nights(entry_utc: datetime, exit_utc: datetime, spec: dict[str, Any]) -> int:
    """Charged nights, counting the broker's triple-swap weekday three times."""
    triple = _MT5_WEEKDAY_TO_ISO[int(spec["swap_rollover3days"])]
    return sum(3 if d.isoweekday() == triple else 1 for d in rollovers(entry_utc, exit_utc))


def swap_usd(side: Side, lots: float, entry_utc: datetime, exit_utc: datetime, spec: dict[str, Any]) -> float:
    """Swap as a cost in USD (positive = you pay). The broker quotes swap as a
    credit (negative = charge), so the sign is flipped here."""
    mode = int(spec["swap_mode"])
    if mode == 0:  # SYMBOL_SWAP_MODE_DISABLED
        return 0.0
    if mode != 1:  # only SYMBOL_SWAP_MODE_POINTS is implemented; fail loudly on anything else
        raise NotImplementedError(f"swap_mode {mode} not supported yet")
    rate_points = spec["swap_long"] if side == "long" else spec["swap_short"]
    nights = swap_nights(entry_utc, exit_utc, spec)
    return -points_to_usd(rate_points, lots, spec) * nights


def describe(commission: Commission, spec: dict[str, Any]) -> dict[str, Any]:
    """Serialisable description stored with the cost model."""
    return {
        "units": "points (1 point = symbol point); usd = points * point * contract_size * lots",
        "scenarios": {k: asdict(v) for k, v in SCENARIOS.items()},
        "commission": asdict(commission),
        "swap": {
            "mode": spec["swap_mode"],
            "long_points_per_night": spec["swap_long"],
            "short_points_per_night": spec["swap_short"],
            "long_usd_per_lot_night": -points_to_usd(spec["swap_long"], 1.0, spec),
            "short_usd_per_lot_night": -points_to_usd(spec["swap_short"], 1.0, spec),
            "triple_day_mt5": spec["swap_rollover3days"],
            "rollover": "17:00 America/New_York, Mon–Fri",
        },
        "slippage_basis": "M5 ATR(14) known at order time (bar column atr_points)",
        "slippage_status": "assumed — no fills available on a demo account; refit in Phase 9",
    }


def _aware(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC_TZ) if ts.tzinfo is None else ts
