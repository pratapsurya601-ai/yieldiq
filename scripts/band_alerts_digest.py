#!/usr/bin/env python
# scripts/band_alerts_digest.py
# ═══════════════════════════════════════════════════════════════
# Daily band-shift digest. Entry point for the GH Actions workflow
# .github/workflows/band_alerts_daily_digest.yml.
#
# Reads `band_alerts` rows from the last 24h with delivered_email = FALSE,
# groups them by user_id (which is an email address — see
# backend/routers/alerts._user_id), and emails each user a summary via
# the existing SendGrid path in backend.services.email_service._send_email.
#
# Usage:
#   python scripts/band_alerts_digest.py            # live
#   python scripts/band_alerts_digest.py --dry-run  # log-only
#
# Env (same secrets as alerts_evaluator):
#   DATABASE_URL        — required
#   SENDGRID_API_KEY    — required for live mode
#   SENDGRID_FROM_EMAIL — optional override
#
# Exit codes:
#   0  — success (including "nothing to do")
#   1  — fatal (bad env, DB unreachable, etc.)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_DASHBOARD = _ROOT / "dashboard"
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except Exception:
    pass


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _render_html(email: str, shifts: list[dict]) -> str:
    """Render a minimal HTML body for the digest. Uses the same brand
    palette as backend/services/email_service so it visually matches
    the existing welcome / weekly-digest emails."""
    rows = []
    for s in shifts:
        ticker = (s.get("ticker") or "").upper()
        from_label = s.get("from_label") or s.get("from_band") or ""
        to_label = s.get("to_label") or s.get("to_band") or ""
        link = f"https://yieldiq.in/analyze/{ticker}"
        rows.append(
            f"<tr>"
            f"<td style='padding:8px 12px;font-weight:600;color:#0F172A;'>"
            f"<a href='{link}' style='color:#2563EB;text-decoration:none;'>{ticker}</a>"
            f"</td>"
            f"<td style='padding:8px 12px;color:#475569;'>{from_label}</td>"
            f"<td style='padding:8px 12px;color:#475569;'>&rarr;</td>"
            f"<td style='padding:8px 12px;color:#0F172A;font-weight:500;'>{to_label}</td>"
            f"</tr>"
        )
    rows_html = "\n".join(rows) if rows else (
        "<tr><td colspan='4' style='padding:16px;color:#94A3B8;'>"
        "No shifts in the last 24h.</td></tr>"
    )

    return f"""
    <html><body style='margin:0;padding:24px;background:#F8FAFC;
        font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'>
      <div style='max-width:560px;margin:0 auto;background:#FFFFFF;
          border-radius:12px;border:1px solid #E2E8F0;overflow:hidden;'>
        <div style='background:#0F172A;padding:20px 24px;'>
          <h1 style='margin:0;color:#FFFFFF;font-size:18px;'>
            YieldIQ &middot; Band-shift digest
          </h1>
        </div>
        <div style='padding:20px 24px;'>
          <p style='margin:0 0 12px;color:#0F172A;font-size:14px;'>
            The following stocks on your watchlist crossed a sector-percentile
            valuation band in the last 24 hours.
          </p>
          <table cellpadding='0' cellspacing='0' border='0' width='100%'
              style='margin-top:8px;border-collapse:collapse;font-size:14px;'>
            {rows_html}
          </table>
          <p style='margin:24px 0 0;color:#64748B;font-size:12px;'>
            Sector-percentile bands are computed from peer cohorts of
            10+ tickers in the same sector. A shift means this stock's
            relative valuation versus its peers changed meaningfully.
          </p>
        </div>
        <div style='padding:12px 24px;border-top:1px solid #E2E8F0;
            color:#94A3B8;font-size:11px;'>
          You're receiving this because you have stocks on your YieldIQ
          watchlist. Mute these alerts in Settings.
        </div>
      </div>
    </body></html>
    """


def main() -> int:
    parser = argparse.ArgumentParser(description="YieldIQ band-shift digest")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log what would be sent; don't email or stamp DB.")
    args = parser.parse_args()
    _setup_logging()
    log = logging.getLogger("band_digest")

    if not os.environ.get("DATABASE_URL"):
        log.error("DATABASE_URL is not set — aborting.")
        return 1

    try:
        from backend.services import band_alert_service as bas
    except Exception as exc:
        log.exception("Could not import band_alert_service: %s", exc)
        return 1

    grouped = bas.list_pending_email_digest(hours=24)
    if not grouped:
        log.info("No pending band-shift alerts in the last 24h. Nothing to send.")
        return 0

    log.info("Pending digests: users=%d total_alerts=%d",
             len(grouped), sum(len(v) for v in grouped.values()))

    if args.dry_run:
        for uid, shifts in grouped.items():
            log.info("DRY-RUN would email user=%s shifts=%d", uid, len(shifts))
            for s in shifts:
                log.info("  %s: %s -> %s", s["ticker"], s["from_band"], s["to_band"])
        return 0

    try:
        from backend.services.email_service import _send_email, is_user_unsubscribed
    except Exception as exc:
        log.exception("Could not import email_service: %s", exc)
        return 1

    sent_alert_ids: list[int] = []
    sent_users = 0
    for uid, shifts in grouped.items():
        # uid is the email address — see backend.routers.alerts._user_id
        # fallback ordering. Skip if the user has opted out of email.
        if not isinstance(uid, str) or "@" not in uid:
            log.info("Skipping non-email user_id=%s (push-only or pre-migration)", uid)
            continue
        try:
            if is_user_unsubscribed(uid):
                log.info("Skipping unsubscribed user=%s", uid)
                continue
        except Exception:
            pass

        subject = (
            f"YieldIQ digest: {len(shifts)} band shift"
            f"{'s' if len(shifts) != 1 else ''} on your watchlist"
        )
        html = _render_html(uid, shifts)
        ok = False
        try:
            ok = _send_email(uid, subject, html)
        except Exception:
            log.exception("Send failed for user=%s", uid)
            ok = False
        if ok:
            sent_users += 1
            sent_alert_ids.extend(s["id"] for s in shifts)

    if sent_alert_ids:
        marked = bas.mark_emails_delivered(sent_alert_ids)
        log.info("Stamped delivered_email=TRUE on %d rows", marked)

    log.info("Digest complete. users_emailed=%d alerts_marked=%d",
             sent_users, len(sent_alert_ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
