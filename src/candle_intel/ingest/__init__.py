"""The only package permitted to import ``MetaTrader5``.

Everything downstream reads immutable Parquet snapshots. See blueprint §3.1 and
tests/leakage/test_mt5_boundary.py, which enforces this.
"""
