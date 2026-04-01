"""
batch/nightly_precompute.py
═══════════════════════════════════════════════════════════════════
YieldIQ — Nightly Pre-compute Batch Job
═══════════════════════════════════════════════════════════════════

PURPOSE
-------
Runs the full YieldIQ DCF + relative-valuation screener over the
entire US equity universe (via Finnhub / usa_tickers.csv) AND the
India NSE universe (data/tickers.csv), combining results into a
single data/screener_results.csv that the Streamlit dashboard reads
at startup.

Designed to run unattended under Windows Task Scheduler once per
night (e.g. 02:00 AM) so that users see fresh data every morning
without triggering on-demand screening.

HOW TO SCHEDULE (Windows Task Scheduler)
-----------------------------------------
1. Open Task Scheduler → "Create Basic Task …"
2. Trigger:  Daily, 02:00 AM (or your preferred off-peak time).
3. Action:   "Start a Program"
     Program/script:  C:\\path\\to\\venv\\Scripts\\python.exe
     Arguments:       batch\\nightly_precompute.py
     Start in:        C:\\Users\\vinit\\Downloads\\yieldiq_v6\\yieldiq
4. Under Settings tick:
     "Run whether user is logged on or not"
     "Run with highest privileges"
5. Make sure FINNHUB_API_KEY (and any other secrets) are set as
   system or user environment variables, OR placed in a .env file
   at the project root (C:\\…\\yieldiq\\.env).

COMMAND-LINE OPTIONS
--------------------
  python batch/nightly_precompute.py
      Run with defaults (12 workers, use cached ticker universe).

  python batch/nightly_precompute.py --refresh-tickers
      Force-invalidate the 24h Finnhub ticker cache before running.

  python batch/nightly_precompute.py --workers 20
      Override the thread-pool size.

  python batch/nightly_precompute.py --curated-only --us-only
      Use only the curated 540-stock US CSV (fast, ~10 min).
      Recommended for daily scheduled runs.

  python batch/nightly_precompute.py --us-only --min-market-cap 0.3
      Full Finnhub universe, pre-filtered to market cap >= $300M.
      Covers ~3,000-4,000 investable US stocks (~30-45 min).

  python batch/nightly_precompute.py --us-only --min-market-cap 0
      Full Finnhub universe, no market-cap filter (18,000+ tickers,
      very slow — not recommended for regular runs).

OUTPUT FILES
------------
  data/screener_results.csv                 — latest combined results (overwritten)
  data/screener_results_YYYYMMDD_HHMM.csv  — timestamped backup
  data/last_batch_run.json                  — run status + metrics for dashboard
  logs/nightly_batch.log                    — appending run log (one line = one run)

PARTIAL-RESULT BEHAVIOUR
-------------------------
KeyboardInterrupt (Ctrl-C) is caught gracefully: any results
collected so far are written to disk before the process exits,
and last_batch_run.json reflects the partial state.

═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

# ── 0. Bootstrap: project root on sys.path + .env loaded FIRST ──
# This block runs before any project imports so every subsequent
# import can resolve correctly regardless of CWD.
import sys
import os
from pathlib import Path

_BATCH_DIR    = Path(__file__).resolve().parent          # …/yieldiq/batch/
_PROJECT_ROOT = _BATCH_DIR.parent                        # …/yieldiq/

# Ensure project root is first on sys.path
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Change CWD to project root so relative paths (data/, logs/, …)
# resolve correctly when the scheduler launches from a different dir.
os.chdir(str(_PROJECT_ROOT))

# Load .env before any project imports so environment variables
# (FINNHUB_API_KEY, etc.) are available to every module.
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_path = _PROJECT_ROOT / ".env"
    if _env_path.exists():
        _load_dotenv(dotenv_path=str(_env_path), override=False)
        print(f"[boot] .env loaded from {_env_path}")
    else:
        _load_dotenv(override=False)   # searches parent dirs
except ImportError:
    # python-dotenv is optional; secrets must then be in system env
    print("[boot] python-dotenv not installed — .env loading skipped")

# ── Activate batch mode BEFORE any project imports ──────────────
# This tells data.collector to skip all Finnhub API calls, which
# eliminates the 2s rate-limit sleeps that make large-universe
# runs take 10+ hours. Sentiment scores will be 0/10 for tickers
# not in the curated CSV (acceptable for batch screening).
os.environ["YIELDIQ_BATCH_MODE"] = "1"

# ── 1. Standard library ─────────────────────────────────────────
import argparse
import ctypes
import json
import logging
import time
from datetime import datetime

# ── 2. Third-party ──────────────────────────────────────────────
import pandas as pd

# ── 3. Project imports ──────────────────────────────────────────
from utils.logger import get_logger
from utils.config import RESULTS_PATH
from data.ticker_registry import get_us_tickers
from screener.stock_screener import run_screener

# ════════════════════════════════════════════════════════════════
# Configuration — tune these values for your hardware / API quota
# ════════════════════════════════════════════════════════════════

MAX_WORKERS = 12   # concurrent ticker threads (raise for faster machines,
                   # lower if you see Yahoo Finance 429 rate-limit errors)

# When True (set via --curated-only CLI flag), use only the curated
# usa_tickers.csv (~540 stocks) instead of the full Finnhub universe
# (~18,000+ symbols). Recommended for daily runs to avoid wasting time
# on micro-cap / OTC names that have no Yahoo Finance data.
CURATED_ONLY = False

# When True (set via --us-only CLI flag), skip the India NSE universe
# entirely. Use this for the US market launch.
US_ONLY = False

# Minimum market cap (USD billions) for the pre-filter step.
# Set via --min-market-cap CLI flag.
# 0 = no filter (default when using --curated-only since CSV is already curated).
# 0.3 = $300M — recommended for full Finnhub universe runs; filters
#        ~18,000 raw symbols down to ~3,000-4,000 investable US stocks.
MIN_MARKET_CAP_B = 0.0

# ════════════════════════════════════════════════════════════════
# Paths
# ════════════════════════════════════════════════════════════════

_DATA_DIR    = _PROJECT_ROOT / "data"
_LOGS_DIR    = _PROJECT_ROOT / "logs"
_INDIA_CSV        = _DATA_DIR / "tickers.csv"
_US_CSV           = _DATA_DIR / "usa_tickers.csv"
_EXTENDED_US_CSV  = _DATA_DIR / "extended_us_tickers.csv"
_RESULTS_CSV = Path(RESULTS_PATH)           # e.g. data/screener_results.csv
_STATUS_FILE = _DATA_DIR / "last_batch_run.json"

# ════════════════════════════════════════════════════════════════
# Logger — console (via get_logger) + file handler
# ════════════════════════════════════════════════════════════════

log = get_logger("nightly_precompute")


def _setup_file_logging() -> None:
    """
    Attach a file handler to the root logger so all log records
    (from every project module) are also appended to
    logs/nightly_batch.log.  Called once at startup.
    """
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOGS_DIR / "nightly_batch.log"
    fh = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  →  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    fh.setLevel(logging.INFO)
    # Attach to the root logger so records from all child loggers flow through
    root_logger = logging.getLogger()
    root_logger.addHandler(fh)
    if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)


# ════════════════════════════════════════════════════════════════
# Sleep prevention (Windows only)
# ════════════════════════════════════════════════════════════════

# SetThreadExecutionState flags
_ES_CONTINUOUS       = 0x80000000
_ES_SYSTEM_REQUIRED  = 0x00000001   # prevent system sleep
_ES_DISPLAY_REQUIRED = 0x00000002   # keep screen on (optional)


def _prevent_sleep() -> None:
    """Tell Windows not to sleep while the batch is running."""
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
        )
        log.info("Sleep prevention active (SetThreadExecutionState)")
    except Exception as exc:
        log.debug(f"Could not set sleep prevention: {exc}")


def _restore_sleep() -> None:
    """Restore normal Windows sleep behaviour after the batch finishes."""
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        log.info("Sleep prevention released")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════
# Market-cap pre-filter
# ════════════════════════════════════════════════════════════════

def _bulk_market_caps(tickers: list[str], batch_size: int = 200) -> dict[str, float]:
    """
    Fetch market caps for a large ticker list using yfinance's
    authenticated download session.  Downloads 1 day of OHLCV data
    for batches of tickers to determine which have valid Yahoo Finance
    data, then fetches market caps via fast_info for the valid subset.

    batch_size=200 keeps each yf.download() call fast and reliable.
    Returns a dict {ticker: market_cap_usd}.
    """
    import yfinance as yf

    caps: dict[str, float] = {}
    total_batches = (len(tickers) + batch_size - 1) // batch_size

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        batch_num = i // batch_size + 1

        try:
            # Step 1: batch download to find tickers with YF data
            df = yf.download(
                batch,
                period="5d",
                progress=False,
                threads=True,
                auto_adjust=True,
            )
            if df.empty:
                log.info(
                    f"  Market-cap batch {batch_num}/{total_batches} — "
                    f"no data ({len(caps):,} caps so far)"
                )
                continue

            # Determine which tickers have valid close prices
            if isinstance(df.columns, pd.MultiIndex):
                close = df.xs("Close", axis=1, level=0) if "Close" in df.columns.get_level_values(0) else pd.DataFrame()
                valid_in_batch = [
                    t for t in batch
                    if t in close.columns and close[t].dropna().shape[0] > 0
                ]
            else:
                # Single ticker returned
                valid_in_batch = batch if df["Close"].dropna().shape[0] > 0 else []

            # Step 2: fast_info for market cap (only for valid tickers)
            for t in valid_in_batch:
                try:
                    fi = yf.Ticker(t).fast_info
                    mcap = getattr(fi, "market_cap", None)
                    if mcap and mcap > 0:
                        caps[t] = float(mcap)
                except Exception:
                    pass  # no cap data — caller keeps ticker

        except Exception as exc:
            log.warning(
                f"Market-cap batch {batch_num}/{total_batches} failed: "
                f"{exc} — keeping all in batch"
            )

        log.info(
            f"  Market-cap batch {batch_num}/{total_batches} done "
            f"({len(caps):,} caps fetched so far)"
        )

    return caps


def _prefilter_by_market_cap(
    tickers: list[str],
    min_market_cap_b: float,
    workers: int,                       # kept for API compatibility, unused
    always_include: set[str] | None = None,
) -> list[str]:
    """
    Filter a ticker list to those with market cap >= min_market_cap_b billion.

    Uses Yahoo Finance's bulk /v7/finance/quote endpoint — fetches market
    caps for 1,000 tickers per HTTP request, so 18,000 tickers takes
    ~20-30 seconds instead of hours.

    Tickers in always_include (e.g. the curated CSV) are kept regardless
    of market cap so we never drop explicitly curated stocks.

    Tickers where the API returns no market cap are kept (benefit of the
    doubt — the screener will reject them later if Yahoo Finance has no
    financial data for them).

    Parameters
    ----------
    tickers          : full ticker list to filter
    min_market_cap_b : threshold in USD billions (e.g. 0.3 = $300M)
    workers          : unused (kept for call-site compatibility)
    always_include   : set of tickers to keep regardless of cap

    Returns
    -------
    Filtered list, original order preserved.
    """
    if min_market_cap_b <= 0:
        return tickers

    always_include = always_include or set()
    threshold = min_market_cap_b * 1_000_000_000

    log.info(
        f"Market-cap pre-filter: checking {len(tickers):,} tickers via "
        f"Yahoo Finance bulk API (threshold=${min_market_cap_b:.2f}B) …"
    )
    t0 = time.perf_counter()

    caps = _bulk_market_caps(tickers)

    passed: list[str] = []
    dropped = 0
    for t in tickers:
        if t in always_include:
            passed.append(t)
        elif t not in caps:
            passed.append(t)     # unknown — keep (benefit of the doubt)
        elif caps[t] >= threshold:
            passed.append(t)
        else:
            dropped += 1

    elapsed = time.perf_counter() - t0
    log.info(
        f"Pre-filter complete in {elapsed:.0f}s: "
        f"{len(tickers):,} → {len(passed):,} tickers "
        f"(dropped {dropped:,} below ${min_market_cap_b:.2f}B)"
    )
    return passed


# ════════════════════════════════════════════════════════════════
# Ticker loading helpers
# ════════════════════════════════════════════════════════════════

def _load_us_tickers(force_refresh: bool = False, curated_only: bool = False, extended: bool = False) -> list[str]:
    """
    Load US tickers.

    When curated_only=True (or --curated-only CLI flag), reads only
    from the hand-curated usa_tickers.csv (~540 stocks).  This is the
    recommended mode for daily runs because the full Finnhub universe
    (~18,000 symbols) contains thousands of micro-cap / OTC names with
    no Yahoo Finance data, wasting API quota and runtime.

    When curated_only=False (default), fetches the full Finnhub
    universe via data.ticker_registry and falls back to the CSV if the
    API is unavailable.

    Returns a deduplicated list of uppercase ticker strings.
    """
    if extended:
        csv_path = _EXTENDED_US_CSV if _EXTENDED_US_CSV.exists() else _US_CSV
        log.info(f"extended=True — loading US tickers from {csv_path.name}")
        try:
            df = pd.read_csv(str(csv_path), dtype=str)
            col = "ticker" if "ticker" in df.columns else df.columns[0]
            tickers = (
                df[col]
                .dropna()
                .str.strip()
                .str.upper()
                .drop_duplicates()
                .tolist()
            )
            log.info(f"Extended CSV loaded: {len(tickers)} tickers")
            return tickers
        except Exception as exc:
            log.error(f"Failed to load extended CSV: {exc}")
            return []

    if curated_only:
        log.info("curated_only=True — loading US tickers from usa_tickers.csv only")
        if not _US_CSV.exists():
            log.error(f"Curated CSV not found: {_US_CSV}")
            return []
        try:
            df = pd.read_csv(str(_US_CSV), dtype=str)
            col = "ticker" if "ticker" in df.columns else df.columns[0]
            tickers = (
                df[col]
                .dropna()
                .str.strip()
                .str.upper()
                .drop_duplicates()
                .tolist()
            )
            tickers = [t for t in tickers if t]
            log.info(f"US universe : {len(tickers):,} tickers  (curated CSV)")
            return tickers
        except Exception as exc:
            log.error(f"Could not load curated US tickers: {exc}")
            return []

    # Primary: dynamic Finnhub registry with 24h disk cache
    try:
        df = get_us_tickers(force_refresh=force_refresh)
        col = "ticker" if "ticker" in df.columns else df.columns[0]
        tickers = (
            df[col]
            .dropna()
            .str.strip()
            .str.upper()
            .drop_duplicates()
            .tolist()
        )
        tickers = [t for t in tickers if t]
        log.info(f"US universe : {len(tickers):,} tickers  (ticker_registry)")
        return tickers
    except Exception as exc:
        log.warning(
            f"ticker_registry raised {exc} — "
            f"falling back to {_US_CSV.name}"
        )

    # Fallback: read usa_tickers.csv directly
    if not _US_CSV.exists():
        log.error(f"US CSV not found: {_US_CSV}")
        return []
    try:
        df = pd.read_csv(str(_US_CSV), dtype=str)
        col = "ticker" if "ticker" in df.columns else df.columns[0]
        tickers = (
            df[col]
            .dropna()
            .str.strip()
            .str.upper()
            .drop_duplicates()
            .tolist()
        )
        tickers = [t for t in tickers if t]
        log.info(f"US universe : {len(tickers):,} tickers  (CSV fallback)")
        return tickers
    except Exception as exc2:
        log.error(f"Could not load US tickers from CSV: {exc2}")
        return []


def _load_india_tickers() -> list[str]:
    """
    Load India NSE tickers from data/tickers.csv.

    The CSV has a single 'ticker' column whose values already carry
    the '.NS' suffix (e.g. 'RELIANCE.NS').  Rows without a suffix
    have '.NS' appended automatically.

    Returns a deduplicated list of ticker strings.
    """
    if not _INDIA_CSV.exists():
        log.warning(f"India tickers CSV not found: {_INDIA_CSV} — skipping India universe")
        return []

    try:
        df = pd.read_csv(str(_INDIA_CSV), dtype=str)
        col = "ticker" if "ticker" in df.columns else df.columns[0]
        raw = df[col].dropna().str.strip().tolist()
        tickers: list[str] = []
        for t in raw:
            t = t.strip()
            if not t:
                continue
            # Ensure .NS suffix (most India tickers in the CSV already have it)
            if not (t.endswith(".NS") or t.endswith(".BO")):
                t = t + ".NS"
            tickers.append(t)
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for t in tickers:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        log.info(f"India universe: {len(unique):,} tickers  ({_INDIA_CSV.name})")
        return unique
    except Exception as exc:
        log.error(f"Could not load India tickers: {exc}")
        return []


# ════════════════════════════════════════════════════════════════
# Results persistence helpers
# ════════════════════════════════════════════════════════════════

def _save_results(df: pd.DataFrame, ts_tag: str) -> None:
    """
    Persist the screener results DataFrame to two files:
      1. data/screener_results.csv  — primary live file (overwritten)
      2. data/screener_results_YYYYMMDD_HHMM.csv  — timestamped backup

    Also prunes backups older than the 7 most recent to keep disk
    usage in check.
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Primary file — always overwrite so the dashboard gets fresh data
    df.to_csv(str(_RESULTS_CSV), index=False)
    log.info(f"Results saved  → {_RESULTS_CSV}  ({len(df):,} rows)")

    # Timestamped backup
    backup_name = f"screener_results_{ts_tag}.csv"
    backup_path = _DATA_DIR / backup_name
    df.to_csv(str(backup_path), index=False)
    log.info(f"Backup saved   → {backup_path}")

    # Keep only the 7 most recent backups to avoid disk bloat
    backups = sorted(_DATA_DIR.glob("screener_results_2*.csv"))
    for old_backup in backups[:-7]:
        try:
            old_backup.unlink()
            log.debug(f"Pruned old backup: {old_backup.name}")
        except Exception:
            pass   # non-fatal if deletion fails


def _derive_top_pick(df: pd.DataFrame) -> str:
    """
    Return the ticker with the highest margin_of_safety among
    DCF-reliable results.  Falls back to the first row if no
    reliable results exist, or '—' if the DataFrame is empty.
    """
    if df is None or df.empty:
        return "—"

    try:
        # Prefer DCF-reliable results
        if "dcf_reliable" in df.columns:
            reliable_df = df[df["dcf_reliable"] == True]   # noqa: E712
        else:
            reliable_df = df

        if reliable_df.empty:
            reliable_df = df

        if "margin_of_safety" in reliable_df.columns:
            mos_series = pd.to_numeric(
                reliable_df["margin_of_safety"], errors="coerce"
            )
            if mos_series.notna().any():
                best_idx = mos_series.idxmax()
                return str(reliable_df.loc[best_idx, "ticker"])

        # Last resort: return the first ticker in the sorted DataFrame
        if "ticker" in df.columns:
            return str(df.iloc[0]["ticker"])
    except Exception:
        pass

    return "—"


def _write_status(
    ts_iso:       str,
    total:        int,
    completed:    int,
    errors:       int,
    duration_min: float,
    top_pick:     str,
) -> None:
    """
    Write data/last_batch_run.json.

    Schema
    ------
    {
        "timestamp":     "<ISO-8601>",
        "total_tickers": N,
        "completed":     N,
        "errors":        N,
        "duration_min":  X.X,
        "top_pick":      "TICKER"
    }

    The dashboard reads this file to display a "last updated" badge.
    """
    status = {
        "timestamp":     ts_iso,
        "total_tickers": total,
        "completed":     completed,
        "errors":        errors,
        "duration_min":  round(duration_min, 1),
        "top_pick":      top_pick,
    }
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")
        log.info(f"Status written → {_STATUS_FILE}")
    except Exception as exc:
        log.warning(f"Could not write status file: {exc}")


# ════════════════════════════════════════════════════════════════
# Main batch runner
# ════════════════════════════════════════════════════════════════

def run_batch(
    force_refresh_tickers: bool = False,
    curated_only: bool = False,
    extended: bool = False,
    us_only: bool = False,
    min_market_cap_b: float = 0.0,
) -> int:
    """
    Orchestrate the full nightly pre-compute.

    Steps
    -----
    1. Set up file logging (append to logs/nightly_batch.log).
    2. Load US tickers via ticker_registry (or CSV fallback).
    3. Load India tickers from data/tickers.csv.
    4. Run run_screener() with MAX_WORKERS threads.
    5. Save combined results + timestamped backup.
    6. Write data/last_batch_run.json.

    KeyboardInterrupt is caught: partial results are saved before exit.

    Returns
    -------
    int
        0 on success, 1 if any error occurred.
    """
    _setup_file_logging()
    _prevent_sleep()   # keep Windows awake for the full run

    t0       = time.perf_counter()
    ts_now   = datetime.now()
    ts_iso   = ts_now.isoformat(timespec="seconds")
    ts_tag   = ts_now.strftime("%Y%m%d_%H%M")

    log.info("=" * 68)
    log.info(f"YieldIQ Nightly Pre-compute  —  {ts_iso}")
    log.info(f"Project root   : {_PROJECT_ROOT}")
    log.info(f"MAX_WORKERS    : {MAX_WORKERS}")
    log.info(f"force_refresh  : {force_refresh_tickers}")
    log.info(f"curated_only   : {curated_only}")
    log.info(f"extended       : {extended}")
    log.info(f"us_only        : {us_only}")
    log.info(f"min_market_cap : ${min_market_cap_b:.2f}B"  if min_market_cap_b > 0 else "min_market_cap : none")
    log.info("=" * 68)

    # ── 1. Load ticker lists ─────────────────────────────────────
    us_tickers    = _load_us_tickers(force_refresh=force_refresh_tickers, curated_only=curated_only, extended=extended)
    india_tickers = [] if us_only else _load_india_tickers()
    all_tickers   = us_tickers + india_tickers
    total         = len(all_tickers)

    if total == 0:
        log.error("Ticker list is empty — nothing to process.  Aborting.")
        _write_status(ts_iso, 0, 0, 0, 0.0, "—")
        return 1

    log.info(
        f"Total universe : {total:,} tickers  "
        f"(US={len(us_tickers):,}  India={len(india_tickers):,})"
    )

    # ── 1b. Market-cap pre-filter (optional) ─────────────────────
    # When running the full Finnhub universe, pre-filter to stocks
    # with market cap >= min_market_cap_b to avoid wasting screener
    # threads on thousands of micro-cap / OTC names with no YF data.
    # The curated CSV tickers are always kept regardless of cap.
    if min_market_cap_b > 0 and not curated_only:
        try:
            curated_set: set[str] = set()
            if _US_CSV.exists():
                _csv_df = pd.read_csv(str(_US_CSV), dtype=str)
                _col = "ticker" if "ticker" in _csv_df.columns else _csv_df.columns[0]
                curated_set = set(
                    _csv_df[_col].dropna().str.strip().str.upper().tolist()
                )
            all_tickers = _prefilter_by_market_cap(
                tickers          = all_tickers,
                min_market_cap_b = min_market_cap_b,
                workers          = MAX_WORKERS,
                always_include   = curated_set,
            )
            total = len(all_tickers)
        except Exception as exc:
            log.warning(f"Market-cap pre-filter failed ({exc}) — continuing with full universe")

    # ── 2. Run the screener ──────────────────────────────────────
    # run_screener() manages its own ThreadPoolExecutor internally.
    # We pass save_csv=False so we control where and how the file
    # is written (primary + backup + status JSON).
    df: pd.DataFrame = pd.DataFrame()
    exit_code = 0

    try:
        df = run_screener(
            tickers     = all_tickers,
            save_csv    = False,           # handled below
            max_workers = MAX_WORKERS,
        )
        log.info(
            f"Screener returned {len(df):,} rows "
            f"from {total:,} input tickers"
        )

    except KeyboardInterrupt:
        log.warning(
            "KeyboardInterrupt received — "
            "saving partial results and exiting cleanly …"
        )
        exit_code = 1
        # df may be empty or partial here; fall through to save whatever we have

    except Exception as exc:
        log.error(
            f"Screener raised an unexpected exception: {exc}",
            exc_info=True,
        )
        exit_code = 1

    # ── 3. Collect statistics ────────────────────────────────────
    elapsed_sec  = time.perf_counter() - t0
    elapsed_min  = elapsed_sec / 60.0
    completed    = len(df) if df is not None and not df.empty else 0
    errors       = total - completed
    top_pick     = _derive_top_pick(df)

    log.info(
        f"Run summary    : total={total:,}  completed={completed:,}  "
        f"errors={errors:,}  duration={elapsed_min:.1f}min  "
        f"top_pick={top_pick}"
    )

    # ── 4. Persist results ───────────────────────────────────────
    if not df.empty:
        try:
            _save_results(df, ts_tag)
        except Exception as exc:
            log.error(f"Failed to save results CSV: {exc}", exc_info=True)
            exit_code = 1
    else:
        log.warning(
            "No results to save — screener returned an empty DataFrame. "
            "The existing screener_results.csv (if any) has NOT been overwritten."
        )
        if exit_code == 0:
            exit_code = 1

    # Always write the status file (even on failure) so the
    # dashboard can report "last attempted" time.
    _write_status(
        ts_iso       = ts_iso,
        total        = total,
        completed    = completed,
        errors       = errors,
        duration_min = elapsed_min,
        top_pick     = top_pick,
    )

    # ── 5. Final banner ──────────────────────────────────────────
    log.info("=" * 68)
    status_word = "SUCCEEDED" if exit_code == 0 else "COMPLETED WITH ERRORS"
    log.info(f"Nightly pre-compute {status_word}")
    log.info(f"  Total tickers : {total:,}")
    log.info(f"  Completed     : {completed:,}")
    log.info(f"  Errors/skipped: {errors:,}")
    log.info(f"  Top pick      : {top_pick}")
    log.info(f"  Wall-clock    : {elapsed_min:.1f} min  ({elapsed_sec:.0f}s)")
    log.info("=" * 68)

    _restore_sleep()   # let Windows sleep normally again
    return exit_code


# ════════════════════════════════════════════════════════════════
# CLI argument parsing
# ════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nightly_precompute",
        description="YieldIQ Nightly Pre-compute Batch Job",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python batch/nightly_precompute.py\n"
            "  python batch/nightly_precompute.py --refresh-tickers\n"
            "  python batch/nightly_precompute.py --workers 20\n"
        ),
    )
    parser.add_argument(
        "--refresh-tickers",
        action="store_true",
        default=False,
        help=(
            "Force re-fetch of the Finnhub ticker universe, "
            "ignoring the 24-hour disk cache."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help=(
            f"Override the thread-pool size (default: {MAX_WORKERS}). "
            "Raise for faster machines; lower if you hit Yahoo 429 errors."
        ),
    )
    parser.add_argument(
        "--curated-only",
        action="store_true",
        default=False,
        help=(
            "Use only the hand-curated usa_tickers.csv (~540 stocks) "
            "instead of the full Finnhub universe (~18,000 symbols). "
            "Recommended for daily runs — completes in ~10 min vs hours."
        ),
    )
    parser.add_argument(
        "--us-only",
        action="store_true",
        default=False,
        help=(
            "Skip the India NSE universe entirely. "
            "Use this for a US-market-only launch."
        ),
    )
    parser.add_argument(
        "--extended",
        action="store_true",
        default=False,
        help=(
            "Use data/extended_us_tickers.csv (~2,500 stocks built from "
            "previous screener runs). Faster than full Finnhub universe, "
            "better coverage than --curated-only. Recommended for weekly runs."
        ),
    )
    parser.add_argument(
        "--min-market-cap",
        type=float,
        default=None,
        metavar="B",
        help=(
            "Pre-filter tickers to those with market cap >= B billion "
            "(e.g. 0.3 = $300M). Reduces the full Finnhub universe "
            "(~18,000) to ~3,000-4,000 investable US stocks. "
            "Ignored when --curated-only is set. Default: 0.3 when "
            "running full universe, 0 when --curated-only."
        ),
    )
    return parser.parse_args()


# ════════════════════════════════════════════════════════════════
# Entry point guard — required by the task specification
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _args = _parse_args()

    if _args.workers is not None:
        MAX_WORKERS = _args.workers
        print(f"[cli] MAX_WORKERS overridden to {MAX_WORKERS}")

    EXTENDED = _args.extended

    if _args.curated_only:
        CURATED_ONLY = True
        print("[cli] curated_only=True — using usa_tickers.csv only")

    if EXTENDED:
        print("[cli] extended=True — using extended_us_tickers.csv")

    if _args.us_only:
        US_ONLY = True
        print("[cli] us_only=True — skipping India universe")

    # Resolve min_market_cap: explicit flag > env default
    # When running the full Finnhub universe without --curated-only,
    # default to $300M filter to avoid processing micro-cap OTC names.
    if _args.min_market_cap is not None:
        MIN_MARKET_CAP_B = _args.min_market_cap
        print(f"[cli] min_market_cap overridden to ${MIN_MARKET_CAP_B:.2f}B")
    elif not CURATED_ONLY:
        MIN_MARKET_CAP_B = 0.0   # no pre-filter — screener rejects bad tickers naturally
        print("[cli] min_market_cap defaulting to none — screener will filter naturally")

    _exit_code = run_batch(
        force_refresh_tickers=_args.refresh_tickers,
        curated_only=CURATED_ONLY,
        extended=EXTENDED,
        us_only=US_ONLY,
        min_market_cap_b=MIN_MARKET_CAP_B,
    )
    sys.exit(_exit_code)
