# backend/services/alert_service.py
# ═══════════════════════════════════════════════════════════════
# Price alert checking + SendGrid email notifications.
# Called by the scheduler (every few hours) and manual /alerts/check.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import os
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── SendGrid config ───────────────────────────────────────────

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@yieldiq.com")


def send_alert_email(
    to_email: str,
    ticker: str,
    target_price: float,
    current_price: float,
    direction: str,
) -> bool:
    """Send a price alert email via SendGrid."""
    if not SENDGRID_API_KEY:
        logger.info(f"SendGrid not configured — skipping email for {ticker} to {to_email}")
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        logger.warning("sendgrid package not installed — skipping email")
        return False

    display_ticker = ticker.replace(".NS", "").replace(".BO", "")
    subject = f"YieldIQ Alert: {display_ticker} hit \u20b9{current_price:.0f}"
    html = f"""
    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px;">
      <h2 style="color:#1D4ED8;">YieldIQ Price Alert</h2>
      <p><strong>{display_ticker}</strong> has crossed your target price.</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;">
        <tr><td style="padding:8px;color:#6B7280;">Target:</td><td style="padding:8px;font-weight:bold;">\u20b9{target_price:.2f} ({direction})</td></tr>
        <tr><td style="padding:8px;color:#6B7280;">Current:</td><td style="padding:8px;font-weight:bold;">\u20b9{current_price:.2f}</td></tr>
      </table>
      <a href="https://yieldiq.in/analysis/{ticker}" style="display:inline-block;background:#1D4ED8;color:white;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600;">View Analysis</a>
      <p style="margin-top:24px;font-size:12px;color:#9CA3AF;">Model estimate only. Not investment advice.</p>
    </div>
    """

    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        html_content=html,
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
        logger.info(f"Alert email sent to {to_email} for {ticker}")
        return True
    except Exception as e:
        logger.error(f"SendGrid email failed for {to_email}: {e}")
        return False


# ── Price fetching ────────────────────────────────────────────

def _fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Return {ticker: last_price} using yfinance fast_info."""
    prices: dict[str, float] = {}
    try:
        import yfinance as yf
        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).fast_info
                price = float(getattr(info, "last_price", 0) or 0)
                if price > 0:
                    prices[ticker] = price
            except Exception:
                pass
    except ImportError:
        logger.warning("yfinance not installed")
    return prices


def _should_fire(alert_type: str, current: float, target: float) -> bool:
    """Return True if the alert condition is met."""
    if alert_type == "above":
        return current >= target
    if alert_type in ("below", "iv_reached"):
        return current <= target
    return False


# ── Main alert checking function ──────────────────────────────

def check_and_trigger_alerts(user_email: Optional[str] = None) -> list[dict]:
    """
    Check all active (non-triggered) alerts against current prices.
    If triggered: mark as triggered in Supabase, send email via SendGrid.

    Args:
        user_email: If provided, only check alerts for this user.
                    If None, check ALL active alerts (used by scheduler).

    Returns list of triggered alert dicts.
    """
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
    except Exception:
        client = None

    if not client:
        logger.info("Supabase not available — falling back to SQLite alert check")
        return _check_sqlite_alerts(user_email)

    try:
        # Fetch active alerts
        query = client.table("price_alerts").select("*").eq("is_active", True)
        if user_email:
            query = query.eq("user_email", user_email)
        result = query.execute()
        alerts = result.data or []

        if not alerts:
            return []

        # Batch-fetch prices
        tickers = list({a["ticker"] for a in alerts})
        prices = _fetch_prices(tickers)
        now = datetime.now(timezone.utc).isoformat()
        triggered = []

        for alert in alerts:
            current_price = prices.get(alert["ticker"], 0.0)
            if current_price <= 0:
                continue

            if _should_fire(alert["alert_type"], current_price, alert["target_price"]):
                # Mark as triggered in Supabase
                try:
                    client.table("price_alerts").update({
                        "is_active": False,
                        "triggered_at": now,
                    }).eq("id", alert["id"]).execute()
                except Exception as e:
                    logger.error(f"Failed to update alert {alert['id']}: {e}")
                    continue

                # Send email notification
                send_alert_email(
                    to_email=alert["user_email"],
                    ticker=alert["ticker"],
                    target_price=alert["target_price"],
                    current_price=current_price,
                    direction=alert["alert_type"],
                )

                triggered.append({
                    "id": alert["id"],
                    "ticker": alert["ticker"],
                    "alert_type": alert["alert_type"],
                    "target_price": alert["target_price"],
                    "current_price": current_price,
                    "triggered_at": now,
                    "user_email": alert["user_email"],
                })

        logger.info(f"Alert check complete: {len(triggered)} triggered out of {len(alerts)} active")
        return triggered

    except Exception as e:
        logger.error(f"Alert check failed: {e}")
        return []


def _check_sqlite_alerts(user_email: Optional[str] = None) -> list[dict]:
    """Fallback: check alerts using SQLite dashboard/alerts.py."""
    try:
        from alerts import check_alerts_for_all_users, check_alerts
        if user_email:
            from alerts import _get_user_id
            uid = _get_user_id(user_email)
            if uid:
                return check_alerts(uid)
            return []
        else:
            result = check_alerts_for_all_users()
            return []  # SQLite version doesn't return triggered details
    except Exception:
        return []


# ── Scheduler entry point ─────────────────────────────────────

def run_alert_check():
    """Entry point for the APScheduler job. Checks all users' alerts."""
    logger.info("Running scheduled alert check...")
    triggered = check_and_trigger_alerts(user_email=None)
    logger.info(f"Scheduled alert check done: {len(triggered)} alerts triggered")
    return triggered
