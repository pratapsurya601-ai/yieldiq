# backend/services/structured_logging.py
"""
Day-43 (2026-05-20): Structured-logging primitives.

Background
══════════
Backend ``log.info`` usage was sprinkled randomly across services —
each module picked its own field names, message format, and level. As
a result:

  - Ops can't filter Railway logs by ticker / engine / sector
  - p95 latency per engine is impossible to compute from log dumps
  - Cache hit rate trends require manual jq pipelines

This module provides a single canonical entry point that emits ONE
JSON line per event with a fixed schema. Railway captures stdout as
log entries; their query UI parses the JSON fields automatically.

Usage
═════

```python
from backend.services.structured_logging import log_event

log_event(
    "analysis.compute",
    ticker="DELHIVERY.NS",
    engine="story_dcf_after_dcf_collapse",
    cache_hit=False,
    latency_ms=2147,
    sector="Internet Platform",
)
```

emits:

```json
{"ts":"2026-05-20T08:42:18.314Z","level":"INFO","event":"analysis.compute","ticker":"DELHIVERY.NS","engine":"story_dcf_after_dcf_collapse","cache_hit":false,"latency_ms":2147,"sector":"Internet Platform"}
```

Schema
══════
Required:
  ts          ISO-8601 timestamp (UTC)
  level       INFO | WARN | ERROR
  event       dotted event name (analysis.compute, cache.hit, etc.)

Optional (any extra kwargs):
  ticker / engine / cache_hit / latency_ms / sector / request_id /
  user_email_hash / cache_version / error / ...

PII discipline
══════════════
NEVER pass raw user_email. Use ``hash_email(email)`` from
``backend.services.logging_utils`` and pass the result as
``user_email_hash``. The structured logger does NOT redact for you.

Why not python-json-logger / structlog?
════════════════════════════════════════
Both work fine but add ~50KB of dependencies + a configuration step
in main.py. This module is ~80 LoC, has zero deps, and integrates
with the existing ``logging`` stdlib so legacy ``log.info`` calls
keep working alongside it.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, Mapping

# ── Module-level state ─────────────────────────────────────────────

_logger = logging.getLogger("yieldiq.structured")
# Don't propagate to root logger — that would emit the JSON line a
# second time through the human-readable formatter.
_logger.propagate = False

# Standard fields that go FIRST in the output dict, in this order, so
# Railway's log UI shows the most important context at the start.
_STANDARD_FIELDS = (
    "ts", "level", "event",
    "ticker", "engine", "sector",
    "cache_hit", "cache_version", "latency_ms",
    "user_email_hash", "request_id",
    "error",
)


def _ensure_handler() -> None:
    """Add a StreamHandler that emits JSON to stdout, once per process."""
    if _logger.handlers:
        return
    h = logging.StreamHandler(stream=sys.stdout)
    # We emit pre-serialized JSON via _logger.info(json_str), so the
    # formatter just passes the message through unchanged.
    h.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(h)
    _logger.setLevel(logging.INFO)


def _serialise(payload: Mapping[str, Any]) -> str:
    """JSON-encode the payload with stable field ordering."""
    ordered: dict[str, Any] = {}
    # Standard fields first
    for k in _STANDARD_FIELDS:
        if k in payload:
            ordered[k] = payload[k]
    # Then any extras in the order the caller passed them
    for k, v in payload.items():
        if k not in ordered:
            ordered[k] = v
    # ensure_ascii=False so unicode (e.g. ₹ symbol) stays readable
    return json.dumps(ordered, ensure_ascii=False, default=str)


def log_event(event: str, *, level: str = "INFO", **fields: Any) -> None:
    """Emit one structured log line.

    Parameters
    ──────────
    event   Dotted event name (analysis.compute, cache.hit, etc.).
            Convention: <subsystem>.<action> lowercase, no spaces.
    level   INFO | WARN | ERROR. Case-insensitive.
    fields  Any additional context. Common keys: ticker, engine,
            sector, cache_hit, latency_ms, error, user_email_hash.
            Values must be JSON-serialisable; anything else is
            coerced via str(). NEVER pass raw email — use
            backend.services.logging_utils.hash_email() first.

    Defensive — never raises. A logging failure must not break the
    request being logged. Falls back silently if JSON encoding fails.
    """
    try:
        _ensure_handler()
        payload: dict[str, Any] = {
            "ts": _iso_utc_now(),
            "level": (level or "INFO").upper(),
            "event": event,
        }
        # Filter out None values — they clutter the log line
        for k, v in fields.items():
            if v is None:
                continue
            payload[k] = v
        line = _serialise(payload)
        # Use the underlying logger so handlers + propagation work,
        # but the formatter is "%(message)s" so the JSON survives.
        if payload["level"] == "ERROR":
            _logger.error(line)
        elif payload["level"] == "WARN":
            _logger.warning(line)
        else:
            _logger.info(line)
    except Exception:  # noqa: BLE001 — defensive
        # Last-ditch fallback: never break the request being logged.
        # The event simply doesn't get logged this time.
        pass


def _iso_utc_now() -> str:
    """Millisecond-precision UTC ISO-8601 timestamp."""
    t = time.time()
    secs = int(t)
    ms = int((t - secs) * 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(secs)) + f".{ms:03d}Z"


__all__ = ["log_event"]
