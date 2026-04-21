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

from backend.services.logging_utils import hash_email

logger = logging.getLogger(__name__)

# ── SendGrid config ───────────────────────────────────────────

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "hello@yieldiq.in")


def send_alert_email(
    to_email: str,
    ticker: str,
    target_price: float,
    current_price: float,
    direction: str,
) -> bool:
    """Send a price alert email via SendGrid."""
    if not SENDGRID_API_KEY:
        logger.info(f"SendGrid not configured — skipping email for {ticker} to {hash_email(to_email)}")
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        logger.warning("sendgrid package not installed — skipping email")
        return False

    display_ticker = ticker.replace(".NS", "").replace(".BO", "")
    subject = f"YieldIQ Alert: {display_ticker} hit \u20b9{current_price:.0f}"

    # ── Brand constants (mirrored from email_service) ────────
    _HEADER_DARK = "#0F172A"
    _BRAND_PRIMARY = "#2563EB"
    _SITE_URL = "https://yieldiq.in"

    _SEBI_DISCLAIMER = (
        "SEBI Disclaimer: YieldIQ is not a SEBI-registered investment advisor. "
        "All data and analysis are for informational purposes only. "
        "Always consult a qualified financial advisor before making investment decisions."
    )

    html = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0;padding:0;background-color:#F1F5F9;">
      <tr>
        <td align="center" style="padding:24px 16px;">
          <table width="600" cellpadding="0" cellspacing="0" border="0"
                 style="max-width:600px;width:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background-color:#FFFFFF;">

            <!-- ═══ DARK HEADER ═══ -->
            <tr>
              <td style="background-color:{_HEADER_DARK};padding:28px 32px 22px;text-align:center;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td align="center">
                      <span style="display:inline-block;width:40px;height:40px;background-color:{_BRAND_PRIMARY};
                                    color:#FFFFFF;font-size:20px;font-weight:800;line-height:40px;
                                    text-align:center;border-radius:8px;letter-spacing:-1px;">Y</span>
                    </td>
                  </tr>
                  <tr>
                    <td align="center" style="padding-top:12px;">
                      <span style="color:#FFFFFF;font-size:20px;font-weight:700;letter-spacing:4px;text-transform:uppercase;">YIELDIQ ALERT</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- ═══ ALERT HEADLINE ═══ -->
            <tr>
              <td style="padding:32px 32px 0;text-align:center;">
                <span style="font-size:28px;line-height:1;">&#9889;</span>
                <h1 style="margin:8px 0 0;font-size:22px;font-weight:700;color:#0F172A;">{display_ticker} hit your target</h1>
              </td>
            </tr>

            <!-- ═══ PRICE CARD ═══ -->
            <tr>
              <td style="padding:24px 32px 0;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;">
                  <tr>
                    <td style="padding:18px 20px;border-bottom:1px solid #E2E8F0;">
                      <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                          <td style="font-size:13px;color:#64748B;">Target</td>
                          <td style="text-align:right;font-size:16px;font-weight:700;color:#0F172A;">\u20b9{target_price:,.2f} <span style="font-size:12px;font-weight:500;color:#64748B;">({direction})</span></td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:18px 20px;border-bottom:1px solid #E2E8F0;">
                      <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                          <td style="font-size:13px;color:#64748B;">Current Price</td>
                          <td style="text-align:right;font-size:16px;font-weight:700;color:#0F172A;">\u20b9{current_price:,.2f}</td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:14px 20px;text-align:center;">
                      <span style="display:inline-block;background-color:#059669;color:#FFFFFF;font-size:13px;
                                    font-weight:600;padding:4px 14px;border-radius:4px;">&#10003; Triggered</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- ═══ CTA BUTTON ═══ -->
            <tr>
              <td align="center" style="padding:28px 32px 8px;">
                <table cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td align="center" style="background-color:{_BRAND_PRIMARY};border-radius:8px;">
                      <a href="{_SITE_URL}/analysis/{ticker}"
                         style="display:inline-block;padding:14px 36px;color:#FFFFFF;
                                font-size:15px;font-weight:600;text-decoration:none;">
                        View Full Analysis &rarr;
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- ═══ FOOTER ═══ -->
            <tr>
              <td>
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #E5E7EB;margin-top:32px;">
                  <tr>
                    <td style="padding:24px 24px 12px;">
                      <p style="font-size:11px;color:#9CA3AF;line-height:1.5;margin:0;">
                        {_SEBI_DISCLAIMER}
                      </p>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 24px 24px;">
                      <p style="font-size:11px;color:#9CA3AF;margin:0;">
                        &copy; {datetime.now(timezone.utc).year} YieldIQ &middot; yieldiq.in
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

          </table>
        </td>
      </tr>
    </table>
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
        logger.info(f"Alert email sent to {hash_email(to_email)} for {ticker}")
        return True
    except Exception as e:
        logger.error(f"SendGrid email failed for {hash_email(to_email)}: {e}")
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
