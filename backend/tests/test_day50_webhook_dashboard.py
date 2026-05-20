"""Day-50 (2026-05-20): webhook events dashboard inside /admin/health-stats.

Source-text regression guards covering:
  - Migration 019 creates webhook_event_log with the right CHECK
    constraint and indexes
  - payments.py defines _log_webhook_attempt and calls it from the
    signature-failure, parse-failure, duplicate, and accepted paths
  - admin.py /health-stats response includes a "webhook" block with
    by_type_24h, processed/duplicate/failed counts, dedupe_ratio_24h,
    and last_failure_reason
  - admin.py /health-alerts raises a webhook.failed_count_24h breach
    at >5 (warn) and >20 (alert)
"""
from __future__ import annotations
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _ROOT / "db" / "migrations" / "019_webhook_event_log.sql"
_PAYMENTS = _ROOT / "backend" / "routers" / "payments.py"
_ADMIN = _ROOT / "backend" / "routers" / "admin.py"


# ── Migration ────────────────────────────────────────────────


def test_migration_019_file_exists():
    assert _MIGRATION.exists(), "019_webhook_event_log.sql missing"


def test_migration_defines_table_with_status_check():
    src = _MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS webhook_event_log" in src
    assert "CHECK (status IN ('processed', 'duplicate', 'failed'))" in src
    assert "idx_webhook_event_log_received_at" in src
    assert "idx_webhook_event_log_status_received" in src
    assert "ENABLE ROW LEVEL SECURITY" in src


# ── Logging helper + instrumentation in webhook handler ─────


def test_log_webhook_attempt_helper_defined():
    src = _PAYMENTS.read_text(encoding="utf-8")
    assert "def _log_webhook_attempt(" in src
    # Inserts into webhook_event_log table
    assert 'client_sb.table("webhook_event_log").insert' in src
    # Failure non-fatal — wrapped in try/except
    assert "log_exc" in src


def test_webhook_handler_logs_signature_failure():
    src = _PAYMENTS.read_text(encoding="utf-8")
    # The signature-verification except block must call the logger
    assert 'error=f"signature:' in src


def test_webhook_handler_logs_parse_failure():
    src = _PAYMENTS.read_text(encoding="utf-8")
    assert 'error=f"parse:' in src


def test_webhook_handler_logs_duplicate_and_processed():
    src = _PAYMENTS.read_text(encoding="utf-8")
    assert 'status="duplicate"' in src
    assert 'status="processed"' in src


# ── /admin/health-stats webhook block ────────────────────────


def test_health_stats_returns_webhook_block():
    src = _ADMIN.read_text(encoding="utf-8")
    # Block keys
    assert '"by_type_24h"' in src
    assert '"processed_count_24h"' in src
    assert '"duplicate_count_24h"' in src
    assert '"failed_count_24h"' in src
    assert '"dedupe_ratio_24h"' in src
    assert '"last_failure_reason"' in src
    # And the response carries it under "webhook"
    assert '"webhook": webhook_block' in src


def test_health_stats_queries_webhook_event_log_24h():
    src = _ADMIN.read_text(encoding="utf-8")
    assert 'sb.table("webhook_event_log")' in src
    assert "timedelta(hours=24)" in src
    # Pulls newest first so first failed row = last failure
    assert 'order("received_at", desc=True)' in src


def test_health_stats_webhook_block_is_failure_safe():
    src = _ADMIN.read_text(encoding="utf-8")
    # Pre-migration / missing table must NOT 500 the endpoint
    assert "health-stats webhook block failed (non-fatal)" in src


# ── /admin/health-alerts webhook thresholds ──────────────────


def test_health_alerts_warns_at_5_failures():
    src = _ADMIN.read_text(encoding="utf-8")
    assert 'webhook.failed_count_24h' in src
    # warn threshold
    assert "wh_failed > 5" in src
    # alert threshold
    assert "wh_failed > 20" in src
