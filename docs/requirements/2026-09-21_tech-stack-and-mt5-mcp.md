# Requirement Update — 2026-09-21
Source: project owner (chat). Saved verbatim for traceability.

---

## UPDATE: Candle Intelligence AI — Technology & Library References

Continue developing our independent XAUUSD-only Candle Intelligence AI project according to the existing architecture and blueprint.

Use the following tools and libraries. Review their official documentation and GitHub repositories before implementation.

### Frontend
- Next.js: https://nextjs.org/docs
- TradingView Lightweight Charts: https://github.com/tradingview/lightweight-charts
- shadcn/ui: https://ui.shadcn.com/
- Recharts: https://github.com/recharts/recharts

### Backend & Data Processing
- FastAPI: https://github.com/fastapi/fastapi
- MetaTrader 5 Python API: https://www.mql5.com/en/docs/python_metatrader5
- Polars: https://github.com/pola-rs/polars
- NumPy: https://github.com/numpy/numpy
- SciPy: https://github.com/scipy/scipy

### Database & Historical Storage
- PostgreSQL: https://www.postgresql.org/
- Apache Parquet: https://parquet.apache.org/
- DuckDB: https://github.com/duckdb/duckdb

### Visual Chart Intelligence
- OpenCV: https://github.com/opencv/opencv
- scikit-image: https://github.com/scikit-image/scikit-image
- Plotly: https://github.com/plotly/plotly.py

### Machine Learning & Research
- scikit-learn: https://github.com/scikit-learn/scikit-learn
- LightGBM: https://github.com/microsoft/LightGBM
- Optuna: https://github.com/optuna/optuna
- MLflow: https://github.com/mlflow/mlflow

### Backtesting
- VectorBT: https://github.com/polakowo/vectorbt
- Backtrader: https://github.com/mementum/backtrader

Evaluate these libraries before choosing the final backtesting architecture. Use custom components where required for accurate XAUUSD execution simulation.

### Important Instructions
1. Research existing open-source solutions before building custom functionality.
2. Prefer maintained, reliable libraries with compatible licenses.
3. Reuse existing charting, mathematical analysis, pattern detection, and backtesting tools wherever appropriate.
4. Do not blindly copy repositories or introduce unnecessary dependencies.
5. Build a hybrid Visual Intelligence Engine using numerical OHLC analysis and computer vision.
6. Keep the project strictly XAUUSD-only and independent of Shiibaa.
7. Prioritize historical data accuracy, reproducible experiments, statistical validation, and realistic backtesting.

Before implementation, prepare a final technology selection report identifying which libraries will be used, why they were selected, and which components require custom development.

---

## UPDATE: MT5 MCP Integration

Add MetaTrader 5 MCP support to the independent Candle Intelligence AI project.

Research these repositories:
1. https://github.com/Cloudmeru/MetaTrader-5-MCP-Server
2. https://github.com/amirkhonov/metatrader5-mcp

Official MT5 Python API: https://www.mql5.com/en/docs/python_metatrader5

### Requirements
- Connect the AI research assistant to the local MT5 terminal through MCP.
- Restrict access to XAUUSD market data only.
- Support historical OHLCV, tick data, current prices, spread and symbol information.
- Use the direct MT5 Python API for bulk historical data ingestion into Parquet.
- Keep MCP read-only. Disable all live trading, order modification and account-management operations.
- Never expose MT5 credentials to the frontend or AI-generated reports.
- Verify repository security, maintenance, licensing and compatibility before integration.

First, test the MCP connection with an MT5 demo account and retrieve historical XAUUSD M5 candles.
