"""Static enforcement of the MT5 boundary (blueprint v1.1 §3.1, §7.2).

1. Only candle_intel/ingest/mt5_session.py may import MetaTrader5.
2. No source file may reference MT5 trading, order, position or deal-history functions.
3. account_info may appear only inside mt5_session (demo/real + trading-permitted check).
4. Research modules may not import the ingestion layer or the MCP server — research
   reads Parquet snapshots only.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = [ROOT / "src", ROOT / "services", ROOT / "scripts"]
MT5_GATEWAY = ROOT / "src" / "candle_intel" / "ingest" / "mt5_session.py"

FORBIDDEN_MT5_ATTRS = {
    "order_send", "order_check", "order_calc_margin", "order_calc_profit",
    "orders_get", "orders_total", "positions_get", "positions_total",
    "history_orders_get", "history_orders_total", "history_deals_get",
    "history_deals_total",
}
# mt5.login() switches accounts. "login" is also a legitimate initialize() keyword,
# so it is forbidden as an attribute access only.
FORBIDDEN_ATTR_ONLY = {"login"}

# Packages under candle_intel that are research code and must stay offline.
RESEARCH_PACKAGES = {
    "data", "costs", "features", "structure", "patterns", "labeling",
    "statistics", "backtest", "ml", "viewer", "vision",
}


def _python_files() -> list[Path]:
    return [p for d in SOURCE_DIRS if d.exists() for p in d.rglob("*.py")]


def _imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_only_gateway_imports_metatrader5() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in _python_files()
        if p != MT5_GATEWAY
        and any(m.split(".")[0] == "MetaTrader5" for m in _imports(ast.parse(p.read_text("utf-8"))))
    ]
    assert not offenders, f"MetaTrader5 imported outside the gateway: {offenders}"


def test_no_trading_surface_referenced() -> None:
    hits = []
    for p in _python_files():
        for node in ast.walk(ast.parse(p.read_text("utf-8"))):
            name = None
            if isinstance(node, ast.Attribute):
                name = node.attr if node.attr in FORBIDDEN_MT5_ATTRS | FORBIDDEN_ATTR_ONLY else None
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                name = node.value if node.value in FORBIDDEN_MT5_ATTRS else None
            if name:
                hits.append(f"{p.relative_to(ROOT)}:{node.lineno} {name}")
    assert not hits, f"Trading/account surface referenced: {hits}"


def test_account_info_confined_to_gateway() -> None:
    hits = [
        str(p.relative_to(ROOT))
        for p in _python_files()
        if p != MT5_GATEWAY
        and any(
            isinstance(n, ast.Attribute) and n.attr == "account_info"
            for n in ast.walk(ast.parse(p.read_text("utf-8")))
        )
    ]
    assert not hits, f"account_info used outside gateway: {hits}"


def test_research_code_cannot_reach_live_data() -> None:
    offenders = []
    for pkg in RESEARCH_PACKAGES:
        pkg_dir = ROOT / "src" / "candle_intel" / pkg
        for p in pkg_dir.rglob("*.py"):
            for mod in _imports(ast.parse(p.read_text("utf-8"))):
                if mod.startswith(("candle_intel.ingest", "ci_mt5_mcp", "MetaTrader5")):
                    offenders.append(f"{p.relative_to(ROOT)} -> {mod}")
    assert not offenders, f"Research code imports a live-data layer: {offenders}"
