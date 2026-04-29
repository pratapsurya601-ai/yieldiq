"""Shared helpers for the completeness backfill pipeline.

Throttling, retries, structured per-ticker logging, checkpoint I/O,
DB connection helpers, and the BackfillReport dataclass.

Design goals:
  * Idempotent — every UPSERT helper here is keyed on a natural key
    (ticker / ticker+period_end / ticker+trade_date).
  * Resumable — checkpoint JSON written every 50 tickers; re-run skips
    already-completed work.
  * Forensic — each ticker x field result emitted as a JSON line.
  * Boring — no scoring math, no CACHE_VERSION, no backend deps.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger("data_pipeline.backfill")


# --------------------------------------------------------------------------- #
# Reports / checkpoints
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "reports"
CHECKPOINT_DIR = REPORTS_DIR / "_backfill_checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class BackfillReport:
    field: str
    attempted: int = 0
    succeeded: int = 0
    skipped: int = 0          # source returned no data — not an error
    errored: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    top_errors: dict[str, int] = field(default_factory=dict)

    def record(self, status: str, source: str = "", err: str = "") -> None:
        self.attempted += 1
        if status == "ok":
            self.succeeded += 1
            if source:
                self.by_source[source] = self.by_source.get(source, 0) + 1
        elif status == "skip":
            self.skipped += 1
        else:
            self.errored += 1
            if err:
                key = err[:80]
                self.top_errors[key] = self.top_errors.get(key, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Structured logging — one JSON line per ticker x field result
# --------------------------------------------------------------------------- #
_LOG_LOCK = threading.Lock()
_LOG_PATH: Path | None = None


def init_jsonl_log(run_id: str) -> Path:
    global _LOG_PATH
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _LOG_PATH = REPORTS_DIR / f"backfill_log_{run_id}.jsonl"
    _LOG_PATH.touch()
    return _LOG_PATH


def log_event(**kwargs: Any) -> None:
    """Append one structured line to the run's JSONL log. Thread-safe."""
    if _LOG_PATH is None:
        return
    payload = {"ts": datetime.now(timezone.utc).isoformat(), **kwargs}
    line = json.dumps(payload, default=str)
    with _LOG_LOCK:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


# --------------------------------------------------------------------------- #
# Checkpoint
# --------------------------------------------------------------------------- #
def checkpoint_path(field_name: str) -> Path:
    return CHECKPOINT_DIR / f"{field_name}.json"


def load_checkpoint(field_name: str) -> set[str]:
    p = checkpoint_path(field_name)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text(encoding="utf-8")).get("done", []))
    except Exception:
        return set()


def save_checkpoint(field_name: str, done: set[str]) -> None:
    p = checkpoint_path(field_name)
    p.write_text(
        json.dumps({"done": sorted(done), "updated": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# Throttle + retries
# --------------------------------------------------------------------------- #
RETRY_BACKOFFS = (5, 15, 60)   # seconds between attempts on 429/transient
PER_TICKER_TIMEOUT_S = 30


class TimeoutError_(Exception):
    pass


def _timeout_alarm(seconds: int):
    """Cross-platform-ish per-call timeout via threading.

    signal.alarm is POSIX-only; CI runs on Linux but devs on Windows.
    A daemon Timer that flips a flag is portable but cannot interrupt
    blocking sockets. yfinance / requests respect their own timeouts,
    so we use this as a soft watchdog only.
    """
    cancelled = {"v": False}

    def _trip():
        cancelled["v"] = True
    t = threading.Timer(seconds, _trip)
    t.daemon = True
    return t, cancelled


def with_retries(fn: Callable[[], Any], *, label: str) -> tuple[Any, str | None]:
    """Run fn() with 5s/15s/60s backoff. Returns (result, error_str_or_None)."""
    last_err = None
    for i, wait in enumerate((0,) + RETRY_BACKOFFS):
        if wait:
            time.sleep(wait)
        try:
            return fn(), None
        except Exception as e:  # broad — yfinance throws many shapes
            msg = str(e)[:200]
            last_err = msg
            transient = any(k in msg.lower() for k in ("429", "timeout", "temporar", "connection"))
            if not transient:
                logger.debug("%s non-transient error, abort retries: %s", label, msg)
                return None, msg
            logger.warning("%s transient error (attempt %d): %s", label, i + 1, msg)
    return None, last_err


# --------------------------------------------------------------------------- #
# DB
# --------------------------------------------------------------------------- #
def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL env var is required (Neon connection string).")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def make_session():
    """Return a SQLAlchemy session bound to the Neon URL.

    Each fetch_* worker takes a session via dependency injection so we
    can swap in a mock during tests.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    eng = create_engine(get_database_url(), pool_pre_ping=True, pool_size=5, max_overflow=5)
    return sessionmaker(bind=eng)()


# --------------------------------------------------------------------------- #
# Ticker normalisation
# --------------------------------------------------------------------------- #
def bare(ticker: str) -> str:
    """Strip yfinance suffix (.NS / .BO) — DB stores bare ticker."""
    return ticker.upper().split(".")[0]


def yf_symbol(ticker: str) -> str:
    """Default to .NS — most YieldIQ universe is NSE-listed."""
    t = ticker.upper()
    if "." in t:
        return t
    return f"{t}.NS"


# --------------------------------------------------------------------------- #
# Graceful shutdown
# --------------------------------------------------------------------------- #
SHUTDOWN = threading.Event()


def install_signal_handlers() -> None:
    def _handler(signum, frame):  # noqa: ARG001
        logger.warning("signal %s received — finishing in-flight tickers and stopping", signum)
        SHUTDOWN.set()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _handler)
        except (ValueError, AttributeError):
            # Not on main thread or unsupported — best effort.
            pass


# --------------------------------------------------------------------------- #
# Worker harness — drives a single fetch_* module across a ticker list
# --------------------------------------------------------------------------- #
def drive_workers(
    field_name: str,
    tickers: list[str],
    fetch_one: Callable[[str], dict],
    *,
    workers: int = 5,
    sleep_s: float = 0.4,
    dry_run: bool = False,
) -> BackfillReport:
    """Generic harness: iterate tickers, run fetch_one(ticker), record results.

    fetch_one(ticker) MUST return a dict with at least:
      {"status": "ok"|"skip"|"error", "source": "yfinance"|..., "error": str}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    report = BackfillReport(field=field_name)
    done = load_checkpoint(field_name)
    todo = [t for t in tickers if t not in done]
    logger.info(
        "[%s] %d total / %d already done / %d todo (workers=%d, dry_run=%s)",
        field_name, len(tickers), len(done), len(todo), workers, dry_run,
    )
    if dry_run:
        for t in todo[:20]:
            log_event(field=field_name, ticker=t, status="dry_run")
        report.attempted = len(todo)
        report.skipped = len(todo)
        return report

    processed_since_ckpt = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_run_one, fetch_one, t, sleep_s): t for t in todo}
        for fut in as_completed(futures):
            if SHUTDOWN.is_set():
                break
            t = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"status": "error", "source": "", "error": str(e)[:200]}
            status = res.get("status", "error")
            report.record(status, res.get("source", ""), res.get("error", ""))
            log_event(field=field_name, ticker=t, **res)
            done.add(t)
            processed_since_ckpt += 1
            if processed_since_ckpt >= 50:
                save_checkpoint(field_name, done)
                processed_since_ckpt = 0
                logger.info(
                    "[%s] checkpoint @ done=%d ok=%d skip=%d err=%d",
                    field_name, len(done), report.succeeded, report.skipped, report.errored,
                )

    save_checkpoint(field_name, done)
    return report


def _run_one(fn: Callable[[str], dict], ticker: str, sleep_s: float) -> dict:
    """Wrap fetch_one with throttle + soft timeout."""
    timer, cancelled = _timeout_alarm(PER_TICKER_TIMEOUT_S)
    timer.start()
    try:
        time.sleep(sleep_s)   # baseline politeness
        res = fn(ticker)
        if cancelled["v"]:
            return {"status": "error", "source": "", "error": "per-ticker timeout >30s"}
        return res
    finally:
        timer.cancel()


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
def now_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
