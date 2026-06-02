#!/usr/bin/env python3
"""
backfill_fair_value_history.py
═══════════════════════════════════════════════════════════════

Phase 1 — operator-run, one-shot backfill of provenance-tagged
historical fair-value points into ``fair_value_history``.

Sources (in priority order):
  1. SNAPSHOT — ``scripts/snapshots/snapshot_20260423_135549_ae518d0f9328.json``
     Each ticker becomes one row with provenance='snapshot',
     date=2026-04-23, model_version='snapshot_ae518d0',
     manifest_id=NULL.

  2. GOLDEN — ``scripts/dcf_golden.json``
     Inserted only if the most-recent commit for the file is a
     production-API refresh (commit message contains the canonical
     phrase 'refresh golden snapshot baseline' or similar). If
     production-faithfulness cannot be confirmed, the rows are
     DROPPED and a warning is logged.
     provenance='golden', model_version=<commit SHA>, manifest_id=NULL.

  3. EXISTING ROWS — already tagged provenance='live' by the
     migration's column default. No action.

Idempotent via ON CONFLICT on (ticker, date, provenance). Operator-
run only (NOT a cron). Use ``--dry-run`` to preview without writing.

Usage
─────
    python scripts/backfill_fair_value_history.py [--dry-run]

Exit codes
──────────
    0  success (or dry-run completed)
    1  DB unavailable
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import date as _Date
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=os.environ.get("BACKFILL_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("backfill_fv_history")


SNAPSHOT_FILE = _REPO_ROOT / "scripts" / "snapshots" / (
    "snapshot_20260423_135549_ae518d0f9328.json"
)
GOLDEN_FILE = _REPO_ROOT / "scripts" / "dcf_golden.json"

# Phrases in the golden file's most-recent commit that confirm the
# rows came from a production-API refresh (not a hand-edit or a
# synthetic test fixture). Keep narrow — false positives here ship
# untrusted FV points into the production history series.
_GOLDEN_REFRESH_MARKERS = (
    "refresh golden snapshot baseline",
    "refresh golden baseline",
    "production-api refresh",
)


# ── Helpers ──────────────────────────────────────────────────────
def _bare(ticker: str) -> str:
    return ticker.replace(".NS", "").replace(".BO", "").strip().upper()


def _load_snapshot_rows() -> list[dict]:
    """Parse the snapshot file into insert-ready rows."""
    if not SNAPSHOT_FILE.exists():
        log.warning("snapshot file missing: %s", SNAPSHOT_FILE)
        return []
    try:
        payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("snapshot parse failed: %s", exc)
        return []

    snapshot_at = payload.get("snapshot_at") or ""
    # snapshot_at looks like "2026-04-23T08:25:49.747443+00:00"
    try:
        as_of = _Date.fromisoformat(snapshot_at[:10])
    except Exception:
        log.error("cannot parse snapshot_at date: %r", snapshot_at)
        return []

    sha = (payload.get("commit_sha") or "")[:7] or "unknown"
    model_version = f"snapshot_{sha}"

    rows: list[dict] = []
    state = payload.get("state") or {}
    for ticker, body in state.items():
        pub = (body or {}).get("public") or {}
        fv = pub.get("fair_value")
        if fv is None:
            continue
        try:
            fv_f = float(fv)
        except (TypeError, ValueError):
            continue
        if fv_f <= 0:
            continue
        bear = pub.get("bear_case")
        bull = pub.get("bull_case")
        rows.append({
            "ticker": _bare(ticker),
            "date": as_of,
            "fair_value": round(fv_f, 4),
            "bear_iv": round(float(bear), 4) if bear else None,
            "bull_iv": round(float(bull), 4) if bull else None,
            "scenario_weights": None,
            "model_version": model_version,
            "provenance": "snapshot",
            "manifest_id": None,
        })
    return rows


def _golden_is_production_faithful() -> tuple[bool, str]:
    """Inspect the most-recent commit touching the golden file.

    Returns (is_faithful, commit_sha). When False, the second element
    holds the commit subject (for logging context).
    """
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%H%n%s", str(GOLDEN_FILE)],
            cwd=str(_REPO_ROOT),
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8", errors="replace").strip().splitlines()
    except Exception as exc:
        log.warning("git log on golden failed: %s", exc)
        return (False, "unknown")
    if len(out) < 2:
        return (False, "unknown")
    sha, subject = out[0], out[1]
    subject_l = subject.lower()
    for marker in _GOLDEN_REFRESH_MARKERS:
        if marker in subject_l:
            return (True, sha)
    return (False, subject)


def _load_golden_rows() -> list[dict]:
    if not GOLDEN_FILE.exists():
        log.warning("golden file missing: %s", GOLDEN_FILE)
        return []
    faithful, sha_or_subject = _golden_is_production_faithful()
    if not faithful:
        log.warning(
            "golden rows DROPPED — most-recent commit does not match a "
            "production-API refresh marker. Context: %s",
            sha_or_subject,
        )
        return []
    try:
        payload = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("golden parse failed: %s", exc)
        return []

    captured_at = payload.get("captured_at") or ""
    try:
        as_of = _Date.fromisoformat(captured_at[:10])
    except Exception:
        log.error("cannot parse golden captured_at: %r", captured_at)
        return []

    model_version = sha_or_subject[:12] if sha_or_subject else "golden"
    rows: list[dict] = []
    tickers = payload.get("tickers") or {}
    for ticker, body in tickers.items():
        fv = (body or {}).get("fair_value")
        if fv is None:
            continue
        try:
            fv_f = float(fv)
        except (TypeError, ValueError):
            continue
        if fv_f <= 0:
            continue
        rows.append({
            "ticker": _bare(ticker),
            "date": as_of,
            "fair_value": round(fv_f, 4),
            "bear_iv": None,
            "bull_iv": None,
            "scenario_weights": None,
            "model_version": model_version,
            "provenance": "golden",
            "manifest_id": None,
        })
    return rows


# ── DB write ─────────────────────────────────────────────────────
def _upsert(rows: Iterable[dict], dry_run: bool) -> int:
    rows = list(rows)
    if not rows:
        return 0
    if dry_run:
        return len(rows)

    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        log.error("cannot import data_pipeline.db: %s", exc)
        return 0
    if Session is None:
        return 0
    from sqlalchemy import text

    sess = Session()
    written = 0
    sql = text(
        """
        INSERT INTO fair_value_history (
            ticker, date, fair_value, price, mos_pct,
            bear_iv, bull_iv, scenario_weights,
            model_version, provenance, manifest_id,
            written_at, updated_at
        )
        VALUES (
            :ticker, :date, :fair_value, 0, 0,
            :bear_iv, :bull_iv, CAST(:scenario_weights AS jsonb),
            :model_version, :provenance, :manifest_id,
            now(), now()
        )
        ON CONFLICT (ticker, date, provenance) DO UPDATE SET
            fair_value       = EXCLUDED.fair_value,
            bear_iv          = EXCLUDED.bear_iv,
            bull_iv          = EXCLUDED.bull_iv,
            scenario_weights = EXCLUDED.scenario_weights,
            model_version    = EXCLUDED.model_version,
            manifest_id      = EXCLUDED.manifest_id,
            written_at       = now()
        """
    )
    try:
        for r in rows:
            params = dict(r)
            if params.get("scenario_weights") is not None and not isinstance(
                params["scenario_weights"], str
            ):
                params["scenario_weights"] = json.dumps(params["scenario_weights"])
            try:
                sess.execute(sql, params)
                written += 1
            except Exception as exc:
                log.warning(
                    "upsert failed for %s @ %s (%s): %s",
                    r.get("ticker"), r.get("date"), r.get("provenance"), exc,
                )
                try:
                    sess.rollback()
                except Exception:
                    pass
        sess.commit()
    finally:
        try:
            sess.close()
        except Exception:
            pass
    return written


# ── Main ─────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 1 backfill for fair_value_history. Operator-run, "
            "one-shot, idempotent."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be inserted without writing.",
    )
    args = parser.parse_args()

    snapshot_rows = _load_snapshot_rows()
    golden_rows = _load_golden_rows()

    log.info("Snapshot rows ready:  %d", len(snapshot_rows))
    log.info("Golden   rows ready:  %d", len(golden_rows))

    if args.dry_run:
        # Show a head sample so operator can sanity check.
        for sample in (snapshot_rows[:3] + golden_rows[:3]):
            log.info("  sample: %s", sample)
        log.info(
            "DRY RUN — no rows written. "
            "Existing 'live' rows untouched (auto-tagged via column default)."
        )
        return 0

    snapshot_written = _upsert(snapshot_rows, dry_run=False)
    golden_written = _upsert(golden_rows, dry_run=False)
    dropped = (
        (len(snapshot_rows) - snapshot_written)
        + (len(golden_rows) - golden_written)
    )
    log.info(
        "DONE — snapshot=%d golden=%d dropped=%d (existing live rows untouched)",
        snapshot_written, golden_written, dropped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
