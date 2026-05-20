"""Day-43 (2026-05-20): structured-logging primitives.

Verifies the log_event() helper emits valid JSON with the canonical
field order, handles missing fields gracefully, and never raises.
"""
from __future__ import annotations
import io
import json
import logging
import re

from backend.services.structured_logging import log_event


def _capture() -> tuple[io.StringIO, logging.Handler]:
    """Swap the structured logger's handler with a StringIO sink."""
    buf = io.StringIO()
    log = logging.getLogger("yieldiq.structured")
    # Strip existing handlers so we get a clean buffer
    for h in list(log.handlers):
        log.removeHandler(h)
    h = logging.StreamHandler(stream=buf)
    h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    return buf, h


def _drain(buf: io.StringIO) -> list[dict]:
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def test_log_event_emits_json_line():
    buf, _ = _capture()
    log_event("analysis.compute", ticker="DELHIVERY.NS", engine="dcf")
    out = _drain(buf)
    assert len(out) == 1
    entry = out[0]
    assert entry["event"] == "analysis.compute"
    assert entry["ticker"] == "DELHIVERY.NS"
    assert entry["engine"] == "dcf"
    assert entry["level"] == "INFO"


def test_log_event_timestamp_iso_8601_with_ms():
    buf, _ = _capture()
    log_event("test.event")
    entry = _drain(buf)[0]
    # 2026-05-20T08:42:18.314Z
    pat = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
    assert pat.match(entry["ts"]), f"Bad timestamp format: {entry['ts']}"


def test_log_event_canonical_field_order():
    """Standard fields appear in fixed order so Railway's log UI shows
    most-important context first."""
    buf, _ = _capture()
    log_event(
        "analysis.compute",
        engine="dcf",
        ticker="TCS.NS",
        latency_ms=2100,
        sector="Technology",
        cache_hit=False,
    )
    raw = buf.getvalue().splitlines()[0]
    # ts should appear before event; event before ticker;
    # ticker before engine; cache_hit before latency_ms
    idx_ts = raw.index('"ts"')
    idx_event = raw.index('"event"')
    idx_ticker = raw.index('"ticker"')
    idx_engine = raw.index('"engine"')
    idx_cache = raw.index('"cache_hit"')
    idx_latency = raw.index('"latency_ms"')
    assert idx_ts < idx_event < idx_ticker < idx_engine < idx_cache < idx_latency, (
        "Canonical field order violated."
    )


def test_log_event_drops_none_values():
    """None values are noisy in logs. Filtered out before emit."""
    buf, _ = _capture()
    log_event("test", ticker="X", engine=None, sector="Y", cache_hit=None)
    entry = _drain(buf)[0]
    assert "engine" not in entry
    assert "cache_hit" not in entry
    assert entry["ticker"] == "X"
    assert entry["sector"] == "Y"


def test_log_event_level_warn_and_error():
    buf, _ = _capture()
    log_event("data.gap", level="WARN", ticker="X")
    log_event("compute.fail", level="ERROR", ticker="Y", error="something broke")
    entries = _drain(buf)
    assert entries[0]["level"] == "WARN"
    assert entries[1]["level"] == "ERROR"
    assert entries[1]["error"] == "something broke"


def test_log_event_never_raises_on_bad_input():
    """Defensive: a logging failure must NEVER break the request."""
    # An object that can't be JSON-serialised AND can't be str()'d
    # cleanly. log_event must swallow + emit nothing.
    class BadValue:
        def __str__(self):
            raise RuntimeError("can't stringify")
    buf, _ = _capture()
    # Should not raise
    log_event("test.bad", ticker=BadValue())
    # And shouldn't crash the next legitimate emit
    log_event("test.good", ticker="OK")
    entries = _drain(buf)
    # Either both got dropped (full defensive), or the second one
    # made it through. Critical: no exception bubbled up.
    assert all(isinstance(e, dict) for e in entries)


def test_log_event_unicode_safe():
    """Don't lose the rupee symbol or other non-ASCII chars."""
    buf, _ = _capture()
    log_event("price.update", ticker="X", display="₹1,234.56")
    entry = _drain(buf)[0]
    assert entry["display"] == "₹1,234.56"


def test_log_event_extra_fields_preserved_after_standard_ones():
    buf, _ = _capture()
    log_event("custom", ticker="X", custom_field_a=1, custom_field_b=2)
    entry = _drain(buf)[0]
    assert entry["custom_field_a"] == 1
    assert entry["custom_field_b"] == 2
