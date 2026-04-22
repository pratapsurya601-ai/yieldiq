"""
yf_circuit.py — process-wide circuit breaker for yfinance calls.

Why this exists
---------------
yfinance is a scraping library, not a supported API. When Yahoo rate-limits
or regresses (a fairly routine occurrence), calls start returning 429,
empty responses, "Invalid Crumb" errors, or plain timeouts. The collector
already retries with backoff, but with a 4-attempt retry schedule the
worst-case wait per ticker is ~25s. Under a real outage, every cold-compute
request in the pipeline pays that cost before falling back to FMP/Finnhub.

This module adds a module-level circuit that trips after N consecutive
failures and stays open for a cooldown window — during which every call
site can fast-fail without hitting the network. Once the cooldown elapses,
the next call probes yfinance again. If it succeeds, the circuit closes
and normal operation resumes. If it fails, the cooldown extends.

Integration shape
-----------------
Call sites do three things:

    from data.yf_circuit import check_or_raise, record_success, record_failure, DataUnavailableError

    try:
        check_or_raise()                 # raises DataUnavailableError if open
        result = yf.Ticker(...).info     # or .history, .financials, etc.
        record_success()                 # resets failure counter on clean hit
    except DataUnavailableError:
        raise                            # already typed; propagate to caller
    except Exception as e:
        record_failure(e)                # increments; may open circuit
        raise

For callers that prefer a boolean return contract (like collector.py's
`_load_yf`), `is_open()` is the non-raising probe and returns True when
the circuit is currently tripped.

Threading
---------
State is mutated under a module-level lock. All public helpers are safe
to call from multiple threads (FastAPI thread-pool workers, Railway worker
batch jobs). The cooldown timer is wall-clock based — not monotonic —
because we tolerate small clock drift and want the cooldown to survive
restarts in a predictable way when logged.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)

# ── Tunables (env-overridable so ops can adjust without a redeploy) ──

FAILURES_TO_OPEN = int(os.getenv("YF_CIRCUIT_FAILURES_TO_OPEN", "5"))
"""Consecutive rate-limit/network failures before the circuit trips."""

COOLDOWN_SECONDS = int(os.getenv("YF_CIRCUIT_COOLDOWN_SECONDS", "300"))
"""How long the circuit stays open once tripped. 5 min is a good default:
long enough for Yahoo rate-limits to decay, short enough that a transient
blip doesn't block a whole batch job."""


class DataUnavailableError(RuntimeError):
    """Raised when yfinance is circuit-broken or repeatedly failing.

    Callers should treat this as "data temporarily unavailable" — render
    the ticker as Under Review in the UI, skip it in batch jobs, or fall
    through to the FMP/Finnhub secondary source. Do not retry the same
    call in the same request cycle; the whole point of the circuit is to
    save that wasted latency.
    """


# ── State ─────────────────────────────────────────────────────────────

_lock = threading.Lock()
_consecutive_failures: int = 0
_open_until: float = 0.0  # unix epoch seconds; 0 means circuit is closed


# ── Classifier ────────────────────────────────────────────────────────

_RATE_LIMIT_HINTS = (
    "429",
    "rate limit",
    "too many requests",
    "forbidden",
    "invalid crumb",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "connection",
    "read operation",
)


def is_rate_limit_error(exc: BaseException) -> bool:
    """Return True if `exc` looks like a yfinance/Yahoo transport failure.

    Matches on the canonical rate-limit / crumb / timeout / connection
    signatures we've observed in production. False positives here are
    cheap (they just count toward the circuit counter); false negatives
    are the real cost (circuit never trips during a real outage), so the
    match list leans generous.
    """
    msg = str(exc).lower()
    return any(hint in msg for hint in _RATE_LIMIT_HINTS)


# ── Public API ────────────────────────────────────────────────────────

def is_open() -> bool:
    """Non-raising probe. True if the circuit is currently tripped."""
    with _lock:
        return time.time() < _open_until


def check_or_raise() -> None:
    """Raise DataUnavailableError if the circuit is currently open.

    Call this at the top of any hot-path code that's about to hit
    yfinance. Keeps the network call itself unchanged — we just skip
    it when we already know it'll fail.
    """
    with _lock:
        now = time.time()
        if now < _open_until:
            remaining = int(_open_until - now)
            raise DataUnavailableError(
                f"yfinance circuit open for {remaining}s more "
                f"(after {_consecutive_failures} consecutive failures)"
            )


def record_success() -> None:
    """Called after a yfinance call returns clean data. Resets the
    failure counter and closes the circuit if it was open."""
    global _consecutive_failures, _open_until
    with _lock:
        if _consecutive_failures > 0 or _open_until > 0:
            log.info(
                "yf_circuit: success after %d failures — closing circuit",
                _consecutive_failures,
            )
        _consecutive_failures = 0
        _open_until = 0.0


def record_failure(exc: BaseException | None = None) -> None:
    """Called after a yfinance call errors. Increments the failure
    counter; if the threshold is crossed, opens the circuit for
    COOLDOWN_SECONDS.

    `exc` is optional — passing it lets us log the classifier verdict
    and tune the rules over time. Non-rate-limit errors (e.g. an
    assertion in our own code) still count toward the failure total at
    half-weight, on the theory that persistent mis-parsing of yfinance
    responses is also a signal to back off.
    """
    global _consecutive_failures, _open_until
    is_rl = bool(exc) and is_rate_limit_error(exc)
    weight = 1 if is_rl else 1  # keep both weights at 1 for now; easy to tune
    with _lock:
        _consecutive_failures += weight
        if _consecutive_failures >= FAILURES_TO_OPEN and _open_until < time.time():
            _open_until = time.time() + COOLDOWN_SECONDS
            log.warning(
                "yf_circuit: OPENING for %ds after %d consecutive failures (last: %s)",
                COOLDOWN_SECONDS,
                _consecutive_failures,
                type(exc).__name__ if exc else "unknown",
            )


def circuit_status() -> dict[str, Any]:
    """Snapshot for /health or admin endpoints. Safe to call frequently."""
    with _lock:
        now = time.time()
        open_now = now < _open_until
        return {
            "open": open_now,
            "seconds_remaining": int(max(0, _open_until - now)),
            "consecutive_failures": _consecutive_failures,
            "failures_to_open": FAILURES_TO_OPEN,
            "cooldown_seconds": COOLDOWN_SECONDS,
        }


def reset_for_tests() -> None:
    """Test-only: reset circuit state. Do NOT call from application code."""
    global _consecutive_failures, _open_until
    with _lock:
        _consecutive_failures = 0
        _open_until = 0.0
