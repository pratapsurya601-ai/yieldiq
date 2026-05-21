"""Day-78 (2026-05-22): corporate-actions feed-health block in
/admin/health-stats and matching thresholds in /admin/health-alerts.

Context — the 2026-05-20 outlier audit found Reliance's "last dividend
Aug 2025" (9+ months stale). The `corporate_actions` table is fed by
the NSE bhavcopy + per-symbol ingest jobs; if they silently stop for
a ticker (network, rate limit, format change), the Day-67 yfinance
fallback in dividend_service.py papers over the gap on the read path
but raises no alert. This block makes the gap observable.

Source-text guards only — no DB, no FastAPI client. Verifies the new
block is wired correctly into admin.py and the matching alert
thresholds exist.
"""
from __future__ import annotations
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_ADMIN = _ROOT / "backend" / "routers" / "admin.py"


# ── /admin/health-stats corp_actions block ────────────────────


def test_admin_py_exists():
    assert _ADMIN.exists(), "backend/routers/admin.py missing"


def test_health_stats_exposes_corp_actions_block():
    src = _ADMIN.read_text(encoding="utf-8")
    # Block is returned alongside the existing webhook block.
    assert '"corp_actions": corp_actions_block,' in src, (
        "corp_actions block must be added to the get_health_stats "
        "response dict (next to the Day-50 webhook block)."
    )


def test_corp_actions_block_has_all_five_fields():
    src = _ADMIN.read_text(encoding="utf-8")
    for field in (
        '"total_rows"',
        '"tickers_covered_24h"',
        '"tickers_covered_7d"',
        '"oldest_freshly_updated_pct"',
        '"feed_last_write_at"',
    ):
        assert field in src, (
            f"corp_actions block must expose {field} — required by "
            "the Day-78 contract."
        )


def test_corp_actions_block_queries_corporate_actions_table():
    src = _ADMIN.read_text(encoding="utf-8")
    # Aggregate-only queries — must reference the table and use the
    # cheap MAX / COUNT DISTINCT / COUNT FILTER pattern, not a full
    # row scan.
    assert "FROM corporate_actions" in src
    assert "COUNT(DISTINCT ticker)" in src
    assert "MAX(ex_date)" in src
    # 6-month coverage-decay window (the Reliance pattern).
    assert "INTERVAL '6 months'" in src


def test_corp_actions_block_is_failure_safe():
    src = _ADMIN.read_text(encoding="utf-8")
    # Block must be wrapped in try/except with a log.warning fallback
    # so a missing table or transient DB hiccup never 500s the
    # endpoint (mirrors the Day-50 webhook pattern).
    assert "health-stats corp_actions block failed (non-fatal)" in src, (
        "corp_actions block must log a non-fatal warning on failure "
        "rather than propagating the exception."
    )
    assert "corp_actions_block: dict = {" in src, (
        "corp_actions_block must be pre-initialised before the try "
        "so the response always has the key, even on failure."
    )


# ── /admin/health-alerts thresholds ───────────────────────────


def test_health_alerts_check_feed_last_write_at():
    src = _ADMIN.read_text(encoding="utf-8")
    # 48h threshold → ALERT
    assert '"alert", "corp_actions.feed_last_write_at"' in src
    assert "Corp-actions ingestion appears stopped" in src
    # Threshold value present in the _add call.
    assert "last_write, 48," in src


def test_health_alerts_check_coverage_decay():
    src = _ADMIN.read_text(encoding="utf-8")
    # 30% threshold → WARN
    assert '"warn", "corp_actions.oldest_freshly_updated_pct"' in src
    assert "Coverage decay in corp-actions feed" in src
    assert "stale_pct, 0.30," in src


def test_health_alerts_doc_header_lists_new_thresholds():
    src = _ADMIN.read_text(encoding="utf-8")
    # The doc-comment block above /admin/health-alerts should record
    # the Day-78 additions so future readers know what fires when.
    assert "corp_actions.feed_last_write_at" in src
    assert "corp_actions.oldest_freshly_updated_pct" in src
