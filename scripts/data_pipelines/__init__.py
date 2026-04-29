"""Unified completeness backfill pipeline.

Reads `reports/download_requirements_<date>.json` produced by the audit
agent and dispatches per-field backfill workers (yfinance primary,
Finnhub/FMP/NSE indices fallback). Pure data-pipeline ops — never
touches scoring math.

See `run_completeness_backfill.py` for the entry point and CLI.
"""
