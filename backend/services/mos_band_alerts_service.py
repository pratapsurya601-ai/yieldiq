# backend/services/mos_band_alerts_service.py
# ═══════════════════════════════════════════════════════════════
# MoS-band subscription engine — task #131 retention play.
#
# Distinct from:
#   * alerts_service.py (UserAlert row + hourly evaluator).
#   * band_alert_service.py (sector-percentile band SHIFTS — different
#     surface that fans out to watchlisters on band transitions).
#
# This service powers the "Set alert" CTA on the analysis page where a
# user picks a margin-of-safety percentage threshold + direction
# (positive = notify when MoS rises above; negative = notify when MoS
# falls below). It exists because the existing UserAlert path requires
# kind=mos_above/mos_below with a single threshold and one row per
# (user, ticker, kind) — the band model lets a user stack multiple
# thresholds per ticker, which the retention engine needs.
#
# Storage: JSONL on disk (one row per subscription) keyed by user_id.
# Rationale: no migration, no schema, no Neon hop on the read path,
# trivially backed up via cron. Migrating to Neon later is an
# `INSERT ... SELECT FROM jsonl` operation — see the docstring on
# get_alert_storage_path() for the migration sketch.
#
# Cooldown: 24h after firing on a (user, ticker, threshold, direction)
# tuple. Re-fire is gated on last_fired_at strictly to prevent the
# "every 15 min for hours" failure mode when a ticker hovers near a
# threshold during market hours.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Literal, Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────
COOLDOWN_HOURS = 24
THRESHOLD_MIN = -50.0
THRESHOLD_MAX = 50.0
Direction = Literal["positive", "negative"]
_VALID_DIRECTIONS: frozenset[str] = frozenset({"positive", "negative"})

# Single global write-lock — JSONL append/rewrite is not atomic on
# Windows and the cron + API can race. A process-local lock is enough
# while we run Railway single-replica; multi-replica must move to Neon.
_LOCK = threading.Lock()


# ── Data ───────────────────────────────────────────────────────
@dataclass
class AlertSubscription:
    user_id: str
    ticker: str
    threshold_pct: float
    direction: str  # "positive" | "negative"
    last_fired_at: Optional[datetime] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # ── JSON round-trip helpers ────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "ticker": self.ticker,
            "threshold_pct": float(self.threshold_pct),
            "direction": self.direction,
            "last_fired_at": (
                self.last_fired_at.isoformat()
                if isinstance(self.last_fired_at, datetime)
                else None
            ),
            "created_at": (
                self.created_at.isoformat()
                if isinstance(self.created_at, datetime)
                else self.created_at
            ),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AlertSubscription":
        def _parse_dt(v):
            if not v:
                return None
            if isinstance(v, datetime):
                return v
            try:
                # fromisoformat handles "+00:00" and "Z"-stripped offsets.
                return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            except Exception:
                return None
        created = _parse_dt(d.get("created_at")) or datetime.now(timezone.utc)
        return cls(
            user_id=str(d["user_id"]),
            ticker=str(d["ticker"]).strip().upper(),
            threshold_pct=float(d["threshold_pct"]),
            direction=str(d.get("direction") or "positive"),
            last_fired_at=_parse_dt(d.get("last_fired_at")),
            created_at=created,
        )

    def key(self) -> tuple[str, str, float, str]:
        return (self.user_id, self.ticker, float(self.threshold_pct), self.direction)


# ── Storage path / IO ──────────────────────────────────────────
def get_alert_storage_path() -> str:
    """Path to the JSONL store.

    Env override: ``MOS_BAND_ALERTS_PATH`` — used by tests + the
    cron job so prod and CI never share state. Defaults to a path
    under the user's tmp dir with stable basename so multiple
    instances within one Railway replica see the same file.

    Migration sketch (when we move to Neon):
        INSERT INTO mos_band_alerts (user_id, ticker, threshold_pct,
            direction, last_fired_at, created_at)
        SELECT * FROM jsonb_populate_recordset(...)
        FROM jsonb_array_elements(:payload);
    """
    env = os.environ.get("MOS_BAND_ALERTS_PATH")
    if env:
        return env
    # Default: project-local under data/ so it survives container
    # restarts on Railway's volume mount; tests override via env.
    root = Path(__file__).resolve().parents[2]  # repo root
    return str(root / "data" / "mos_band_alerts.jsonl")


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _read_all() -> list[AlertSubscription]:
    """Read every subscription. Returns [] if the file does not exist."""
    path = get_alert_storage_path()
    if not os.path.exists(path):
        return []
    out: list[AlertSubscription] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(AlertSubscription.from_dict(json.loads(line)))
                except Exception as e:
                    logger.warning("mos_band_alerts: skip malformed row: %s", e)
    except OSError as e:
        logger.warning("mos_band_alerts: read failed at %s: %s", path, e)
    return out


def _write_all(subs: Iterable[AlertSubscription]) -> None:
    path = get_alert_storage_path()
    _ensure_dir(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for s in subs:
            fh.write(json.dumps(s.to_dict(), separators=(",", ":")) + "\n")
    # Best-effort atomic rename. On Windows os.replace is atomic since
    # Python 3.3 for files on the same volume — good enough for our
    # single-replica deployment.
    os.replace(tmp, path)


# ── Validation ─────────────────────────────────────────────────
def _validate(threshold_pct: float, direction: str) -> None:
    """Raise ValueError on bad input. Used by both the public API and the
    POST handler so the same rules apply to both write paths."""
    try:
        thr = float(threshold_pct)
    except (TypeError, ValueError):
        raise ValueError("threshold_pct must be a number")
    if not (THRESHOLD_MIN <= thr <= THRESHOLD_MAX):
        raise ValueError(
            f"threshold_pct must be between {THRESHOLD_MIN:g} and "
            f"{THRESHOLD_MAX:g}"
        )
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(_VALID_DIRECTIONS)}"
        )


# ── Public API ─────────────────────────────────────────────────
def create_subscription(
    user_id: str,
    ticker: str,
    threshold_pct: float,
    direction: str,
) -> AlertSubscription:
    """Create (or return existing) subscription. Idempotent by key."""
    if not user_id:
        raise ValueError("user_id is required")
    if not ticker:
        raise ValueError("ticker is required")
    _validate(threshold_pct, direction)

    sub = AlertSubscription(
        user_id=str(user_id),
        ticker=str(ticker).strip().upper(),
        threshold_pct=float(threshold_pct),
        direction=direction,
    )
    with _LOCK:
        rows = _read_all()
        existing = next((r for r in rows if r.key() == sub.key()), None)
        if existing is not None:
            return existing
        rows.append(sub)
        _write_all(rows)
    return sub


def list_subscriptions_for_user(user_id: str) -> list[AlertSubscription]:
    if not user_id:
        return []
    return [r for r in _read_all() if r.user_id == str(user_id)]


def list_subscriptions_for_ticker(ticker: str) -> list[AlertSubscription]:
    if not ticker:
        return []
    t = str(ticker).strip().upper()
    return [r for r in _read_all() if r.ticker == t]


def delete_subscription(
    user_id: str,
    ticker: str,
    threshold_pct: float,
    direction: str,
) -> bool:
    """Returns True if a row was removed, False otherwise."""
    if not user_id or not ticker:
        return False
    try:
        _validate(threshold_pct, direction)
    except ValueError:
        return False
    target = (str(user_id), str(ticker).strip().upper(),
              float(threshold_pct), direction)
    removed = False
    with _LOCK:
        rows = _read_all()
        kept = [r for r in rows if r.key() != target]
        if len(kept) != len(rows):
            removed = True
            _write_all(kept)
    return removed


def list_distinct_tickers() -> list[str]:
    """Used by the cron — return every ticker that has at least one row."""
    return sorted({r.ticker for r in _read_all()})


# ── Firing logic ───────────────────────────────────────────────
def _condition_met(sub: AlertSubscription, current_mos_pct: float) -> bool:
    """True iff the current MoS meets the subscription's threshold.

    ``positive`` direction: fires when MoS rises ABOVE threshold (stock
    deeply undervalued — user wants to know when the opportunity arrives).
    ``negative`` direction: fires when MoS falls BELOW threshold (stock
    pulled back from premium — user wants to know when their watch is
    no longer overpriced).
    """
    if sub.direction == "positive":
        return current_mos_pct >= sub.threshold_pct
    if sub.direction == "negative":
        return current_mos_pct <= sub.threshold_pct
    return False


def _in_cooldown(last_fired_at: Optional[datetime]) -> bool:
    if last_fired_at is None:
        return False
    now = datetime.now(timezone.utc)
    last = last_fired_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now - last < timedelta(hours=COOLDOWN_HOURS)


def _render_copy(ticker: str, sub: AlertSubscription) -> tuple[str, str]:
    """Render (title, body) for the push notification.

    SEBI vocabulary: informational, no directives. The body describes
    the threshold cross — never tells the user what to do.
    """
    display = ticker.replace(".NS", "").replace(".BO", "").upper()
    title = f"{display} alert"
    if sub.direction == "positive":
        body = (
            f"Margin of safety crossed +{sub.threshold_pct:.0f}% "
            f"(your threshold)"
        )
    else:
        body = (
            f"Margin of safety fell to {sub.threshold_pct:.0f}% "
            f"(your threshold)"
        )
    return title, body


def _send_push_for_user(user_id: str, ticker: str, title: str, body: str) -> bool:
    """Best-effort push. Returns True if at least one endpoint accepted."""
    try:
        from data_pipeline.db import Session as _S
        from backend.services.push_service import send_push
    except Exception as e:
        logger.warning("mos_band_alerts: push_service unavailable: %s", e)
        return False
    if _S is None:
        logger.info("mos_band_alerts: DATABASE not configured — skip push")
        return False
    session = _S()
    try:
        delivered = send_push(
            session,
            user_id=user_id,
            title=title,
            body=body,
            url=f"/analysis/{ticker}",
        )
        return delivered > 0
    except Exception as e:
        logger.warning("mos_band_alerts: send_push failed user=%s ticker=%s: %s",
                       user_id, ticker, e)
        return False
    finally:
        try:
            session.close()
        except Exception:
            pass


def check_and_fire_alerts(
    ticker: str,
    current_mos_pct: float,
) -> list[AlertSubscription]:
    """For every subscription on ``ticker`` whose condition is met AND
    whose cooldown has expired, send a PWA push and stamp
    ``last_fired_at``. Returns the fired subscriptions.

    Never raises — failures are logged and the run continues with the
    next subscription so a single user's misconfigured push endpoint
    can't halt the cron sweep.
    """
    if not ticker:
        return []
    try:
        mos = float(current_mos_pct)
    except (TypeError, ValueError):
        return []
    t = str(ticker).strip().upper()
    now = datetime.now(timezone.utc)

    fired: list[AlertSubscription] = []
    with _LOCK:
        rows = _read_all()
        changed = False
        for sub in rows:
            if sub.ticker != t:
                continue
            if not _condition_met(sub, mos):
                continue
            if _in_cooldown(sub.last_fired_at):
                continue
            title, body = _render_copy(t, sub)
            try:
                _send_push_for_user(sub.user_id, t, title, body)
            except Exception as e:
                logger.warning(
                    "mos_band_alerts: push fan-out failed user=%s: %s",
                    sub.user_id, e,
                )
            sub.last_fired_at = now
            changed = True
            fired.append(sub)
        if changed:
            _write_all(rows)
    return fired
