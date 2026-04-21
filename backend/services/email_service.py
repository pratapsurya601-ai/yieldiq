# backend/services/email_service.py
# ═══════════════════════════════════════════════════════════════
# Centralized email service using SendGrid.
# Welcome emails on signup + weekly digest with top undervalued stocks.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import os
import logging
import hashlib
import time
from datetime import datetime, timedelta, timezone

from backend.services.logging_utils import hash_email

logger = logging.getLogger(__name__)

# ── SendGrid config ───────────────────────────────────────────

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "hello@yieldiq.in")

BRAND_PRIMARY = "#2563EB"
BRAND_ACCENT = "#06B6D4"
HEADER_DARK = "#0F172A"
HEADER_LIGHT = "#1E293B"
SITE_URL = "https://yieldiq.in"

SEBI_DISCLAIMER = (
    "SEBI Disclaimer: YieldIQ is not a SEBI-registered investment advisor. "
    "All data, analysis, and scores are for informational purposes only and do not "
    "constitute investment advice or recommendations. Past performance does not "
    "guarantee future results. Always consult a qualified financial advisor before "
    "making investment decisions. Investments in securities are subject to market risks. "
    "Read all scheme-related documents carefully."
)


def _get_unsubscribe_url(email: str) -> str:
    """Generate unsubscribe URL with a simple hash token."""
    secret = os.environ.get("JWT_SECRET", "yieldiq-unsub-salt")
    token = hashlib.sha256(f"{email}:{secret}".encode()).hexdigest()[:16]
    return f"{SITE_URL}/api/v1/email/unsubscribe?email={email}&token={token}"


def verify_unsubscribe_token(email: str, token: str) -> bool:
    """Verify the unsubscribe token matches."""
    secret = os.environ.get("JWT_SECRET", "yieldiq-unsub-salt")
    expected = hashlib.sha256(f"{email}:{secret}".encode()).hexdigest()[:16]
    return token == expected


def _email_footer(email: str) -> str:
    """Common footer for all emails: unsubscribe + SEBI disclaimer."""
    unsub_url = _get_unsubscribe_url(email)
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #E5E7EB;margin-top:32px;">
      <tr>
        <td style="padding:24px 24px 12px;">
          <p style="font-size:12px;color:#9CA3AF;line-height:1.6;margin:0;">
            You are receiving this email because you signed up on YieldIQ.
            <a href="{unsub_url}" style="color:#6B7280;text-decoration:underline;">Unsubscribe</a>
          </p>
        </td>
      </tr>
      <tr>
        <td style="padding:0 24px;">
          <p style="font-size:11px;color:#9CA3AF;line-height:1.5;margin:0;">
            {SEBI_DISCLAIMER}
          </p>
        </td>
      </tr>
      <tr>
        <td style="padding:12px 24px 24px;">
          <p style="font-size:11px;color:#9CA3AF;margin:0;">
            &copy; {datetime.now().year} YieldIQ &middot; yieldiq.in
          </p>
        </td>
      </tr>
    </table>
    """


def _send_email(to_email: str, subject: str, html_content: str) -> bool:
    """Send an email via SendGrid. Returns True on success."""
    if not SENDGRID_API_KEY:
        logger.info(f"SendGrid not configured -- skipping email to {hash_email(to_email)}")
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        logger.warning("sendgrid package not installed -- skipping email")
        return False

    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        html_content=html_content,
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
        logger.info(f"Email sent to {hash_email(to_email)}: {subject}")
        return True
    except Exception as e:
        logger.error(f"SendGrid email failed for {hash_email(to_email)}: {e}")
        return False


def is_user_unsubscribed(email: str) -> bool:
    """Check if user has opted out of emails."""
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        result = (
            client.table("users_meta")
            .select("email_opted_out")
            .eq("email", email)
            .maybe_single()
            .execute()
        )
        if result.data:
            return bool(result.data.get("email_opted_out", False))
    except Exception as e:
        logger.debug(f"Could not check unsubscribe status for {hash_email(email)}: {e}")
    return False


def mark_user_unsubscribed(email: str) -> bool:
    """Mark user as unsubscribed in users_meta."""
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        client.table("users_meta").update(
            {"email_opted_out": True}
        ).eq("email", email).execute()
        logger.info(f"User unsubscribed: {hash_email(email)}")
        return True
    except Exception as e:
        logger.error(f"Failed to unsubscribe {hash_email(email)}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# WELCOME EMAIL
# ═══════════════════════════════════════════════════════════════

def send_welcome_email(email: str, name: str = "") -> bool:
    """Send branded welcome email on signup. Safe to call in background thread."""
    if is_user_unsubscribed(email):
        return False

    display_name = name or email.split("@")[0].title()
    subject = f"Welcome to YieldIQ, {display_name}!"

    html = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0;padding:0;background-color:#F1F5F9;">
      <tr>
        <td align="center" style="padding:24px 16px;">
          <table width="600" cellpadding="0" cellspacing="0" border="0"
                 style="max-width:600px;width:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background-color:#FFFFFF;">

            <!-- ═══ DARK HEADER ═══ -->
            <tr>
              <td style="background-color:{HEADER_DARK};padding:36px 32px 28px;text-align:center;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td align="center">
                      <span style="display:inline-block;width:44px;height:44px;background-color:{BRAND_PRIMARY};
                                    color:#FFFFFF;font-size:22px;font-weight:800;line-height:44px;
                                    text-align:center;border-radius:10px;letter-spacing:-1px;">Y</span>
                    </td>
                  </tr>
                  <tr>
                    <td align="center" style="padding-top:14px;">
                      <span style="color:#FFFFFF;font-size:22px;font-weight:700;letter-spacing:4px;text-transform:uppercase;">YIELDIQ</span>
                    </td>
                  </tr>
                  <tr>
                    <td align="center" style="padding-top:6px;">
                      <span style="color:#94A3B8;font-size:13px;letter-spacing:0.5px;">Institutional-grade DCF valuation</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- ═══ GREETING ═══ -->
            <tr>
              <td style="padding:36px 32px 0;">
                <h1 style="margin:0 0 6px;font-size:24px;font-weight:700;color:#0F172A;">Welcome, {display_name}</h1>
                <p style="margin:0;font-size:16px;color:#64748B;line-height:1.5;">You're in. Here's your edge.</p>
              </td>
            </tr>

            <!-- ═══ 3 STEPS ═══ -->
            <tr>
              <td style="padding:28px 32px 0;">
                <!-- Step 1 -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:12px;">
                  <tr>
                    <td style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:16px 18px;">
                      <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                          <td width="36" valign="top">
                            <span style="font-size:18px;line-height:1;">&#128269;</span>
                          </td>
                          <td valign="top" style="padding-left:4px;">
                            <span style="font-size:12px;font-weight:600;color:#94A3B8;text-transform:uppercase;letter-spacing:1px;">Step 1</span>
                            <p style="margin:4px 0 0;font-size:15px;font-weight:600;color:#0F172A;">Search any NSE/BSE stock</p>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                </table>

                <!-- Step 2 -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:12px;">
                  <tr>
                    <td style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:16px 18px;">
                      <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                          <td width="36" valign="top">
                            <span style="font-size:18px;line-height:1;">&#128202;</span>
                          </td>
                          <td valign="top" style="padding-left:4px;">
                            <span style="font-size:12px;font-weight:600;color:#94A3B8;text-transform:uppercase;letter-spacing:1px;">Step 2</span>
                            <p style="margin:4px 0 0;font-size:15px;font-weight:600;color:#0F172A;">Get instant DCF fair value</p>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                </table>

                <!-- Step 3 -->
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:12px;">
                  <tr>
                    <td style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:16px 18px;">
                      <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                          <td width="36" valign="top">
                            <span style="font-size:18px;line-height:1;">&#127919;</span>
                          </td>
                          <td valign="top" style="padding-left:4px;">
                            <span style="font-size:12px;font-weight:600;color:#94A3B8;text-transform:uppercase;letter-spacing:1px;">Step 3</span>
                            <p style="margin:4px 0 0;font-size:15px;font-weight:600;color:#0F172A;">Know before you invest</p>
                          </td>
                        </tr>
                      </table>
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
                    <td align="center" style="background-color:{BRAND_PRIMARY};border-radius:8px;">
                      <a href="{SITE_URL}/search"
                         style="display:inline-block;padding:14px 36px;color:#FFFFFF;
                                font-size:16px;font-weight:600;text-decoration:none;
                                letter-spacing:0.3px;">
                        Analyze Your First Stock &rarr;
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- ═══ WHAT YOU GET ═══ -->
            <tr>
              <td style="padding:28px 32px 0;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;">
                  <tr>
                    <td style="padding:20px 22px 8px;">
                      <span style="font-size:13px;font-weight:700;color:#64748B;text-transform:uppercase;letter-spacing:1px;">What you get</span>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 22px 6px;">
                      <p style="margin:0;font-size:14px;color:#334155;line-height:2;">
                        &#10003;&nbsp; 15 valuation engines<br>
                        &#10003;&nbsp; 2,900+ NSE/BSE stocks covered<br>
                        &#10003;&nbsp; Bear / Base / Bull scenarios<br>
                        &#10003;&nbsp; Free &mdash; 5 analyses per day
                      </p>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:4px 22px 18px;">
                      <a href="{SITE_URL}/pricing" style="font-size:13px;color:{BRAND_PRIMARY};text-decoration:underline;">
                        Upgrade for unlimited &rarr;
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- ═══ FOOTER ═══ -->
            <tr>
              <td>
                {_email_footer(email)}
              </td>
            </tr>

          </table>
        </td>
      </tr>
    </table>
    """

    return _send_email(email, subject, html)


# ═══════════════════════════════════════════════════════════════
# WEEKLY DIGEST EMAIL
# ═══════════════════════════════════════════════════════════════

def _get_top_undervalued_stocks(limit: int = 5) -> list[dict]:
    """
    Query the data pipeline database for stocks with highest margin of safety.
    Falls back to screener CSV if DB unavailable.
    Returns list of dicts: ticker, company_name, score, mos_pct, verdict.
    """
    # Try Aiven PostgreSQL via data_pipeline
    try:
        from data_pipeline.db import Session
        if Session is not None:
            from sqlalchemy import text
            db = Session()
            try:
                # DISTINCT ON dedupes cross-listing rows in market_metrics
                # AND in daily_prices (same ticker, NSE+BSE -> two rows
                # even on the same trade_date). See design note in
                # backend/routers/screener.py.
                query = text("""
                    WITH mm_dedup AS (
                        SELECT DISTINCT ON (ticker) ticker, pe_ratio
                        FROM market_metrics
                        ORDER BY ticker, trade_date DESC
                    ),
                    dp_dedup AS (
                        SELECT DISTINCT ON (ticker) ticker, close_price
                        FROM daily_prices
                        ORDER BY ticker, trade_date DESC
                    )
                    SELECT
                        s.ticker,
                        s.company_name,
                        dp.close_price,
                        mm.pe_ratio
                    FROM stocks s
                    JOIN dp_dedup dp ON dp.ticker = s.ticker
                    JOIN mm_dedup mm ON mm.ticker = s.ticker
                    WHERE s.is_active = true
                    ORDER BY mm.pe_ratio ASC NULLS LAST
                    LIMIT :lim
                """)
                rows = db.execute(query, {"lim": limit}).fetchall()
                if rows:
                    results = []
                    for row in rows:
                        results.append({
                            "ticker": row[0],
                            "company_name": row[1] or row[0],
                            "score": 75,  # placeholder until full scoring in DB
                            "mos_pct": 0,
                            "verdict": "Undervalued",
                        })
                    return results
            finally:
                db.close()
    except Exception as e:
        logger.debug(f"DB query for top stocks failed: {e}")

    # Fallback: screener CSV
    try:
        import pandas as pd
        from pathlib import Path
        csv_path = Path(__file__).resolve().parent.parent.parent / "data" / "screener_results.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score")), None)
            mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct")), None)
            ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), df.columns[0])
            name_col = next((c for c in df.columns if "name" in c.lower()), None)

            if mos_col:
                df = df.sort_values(mos_col, ascending=False)
            elif score_col:
                df = df.sort_values(score_col, ascending=False)

            results = []
            for _, row in df.head(limit).iterrows():
                _mos = float(row.get(mos_col, 0)) if mos_col else 0
                _score = int(row.get(score_col, 0)) if score_col else 0
                # SEBI-safe verdicts: descriptive, model-relative, never imperative.
                if _mos > 30:
                    verdict = "Deeply Undervalued (vs model)"
                elif _mos > 15:
                    verdict = "Undervalued (vs model)"
                elif _mos > 0:
                    verdict = "Slightly Undervalued (vs model)"
                else:
                    verdict = "Fair Value (vs model)"
                results.append({
                    "ticker": str(row.get(ticker_col, "")),
                    "company_name": str(row.get(name_col, row.get(ticker_col, ""))) if name_col else str(row.get(ticker_col, "")),
                    "score": _score,
                    "mos_pct": _mos,
                    "verdict": verdict,
                })
            return results
    except Exception as e:
        logger.debug(f"CSV fallback for top stocks failed: {e}")

    return []


def _verdict_color(verdict: str) -> str:
    """Return a color hex for the verdict badge."""
    v = verdict.lower()
    if "strong" in v:
        return "#059669"
    if "undervalued" in v:
        return "#10B981"
    if "fair" in v:
        return "#F59E0B"
    return "#6B7280"


def send_weekly_digest(email: str) -> bool:
    """Send weekly market digest email. Safe to call in background thread."""
    if is_user_unsubscribed(email):
        return False

    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).strftime("%b %d")
    week_end = now.strftime("%b %d, %Y")

    top_stocks = _get_top_undervalued_stocks(limit=5)

    # Build stock cards
    if top_stocks:
        stock_cards = ""
        for i, s in enumerate(top_stocks):
            display_ticker = s["ticker"].replace(".NS", "").replace(".BO", "")
            mos_display = f"+{s['mos_pct']:.0f}%" if s["mos_pct"] > 0 else f"{s['mos_pct']:.0f}%"
            vc = _verdict_color(s["verdict"])
            border_bottom = "border-bottom:1px solid #E2E8F0;" if i < len(top_stocks) - 1 else ""
            stock_cards += f"""
            <tr>
              <td style="padding:16px 18px;{border_bottom}">
                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td width="32" valign="top">
                      <span style="display:inline-block;width:28px;height:28px;background-color:{HEADER_DARK};
                                    color:#FFFFFF;font-size:13px;font-weight:700;line-height:28px;
                                    text-align:center;border-radius:6px;">#{i+1}</span>
                    </td>
                    <td valign="top" style="padding-left:12px;">
                      <span style="font-size:15px;font-weight:700;color:#0F172A;">{display_ticker}</span>
                      <span style="display:inline-block;background-color:{vc};color:#FFFFFF;font-size:11px;
                                    font-weight:600;padding:1px 8px;border-radius:4px;margin-left:8px;
                                    vertical-align:middle;">{s['verdict'].upper()}</span>
                      <br>
                      <span style="font-size:13px;color:#64748B;">Score {s['score']}</span>
                      <span style="color:#CBD5E1;">&nbsp;&middot;&nbsp;</span>
                      <span style="font-size:13px;font-weight:600;color:#059669;">{mos_display} MoS</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """
        stocks_section = f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;">
          <tr>
            <td style="padding:16px 18px 8px;">
              <span style="font-size:18px;font-weight:700;color:#0F172A;">Top Opportunities This Week</span>
            </td>
          </tr>
          {stock_cards}
        </table>
        """
    else:
        stocks_section = """
        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;">
          <tr>
            <td style="padding:24px;text-align:center;">
              <p style="color:#64748B;font-size:14px;margin:0;">
                No screener data available this week. Check back next Monday!
              </p>
            </td>
          </tr>
        </table>
        """

    subject = f"YieldIQ Weekly Digest -- {week_start} to {week_end}"

    html = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0;padding:0;background-color:#F1F5F9;">
      <tr>
        <td align="center" style="padding:24px 16px;">
          <table width="600" cellpadding="0" cellspacing="0" border="0"
                 style="max-width:600px;width:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background-color:#FFFFFF;">

            <!-- ═══ DARK HEADER ═══ -->
            <tr>
              <td style="background-color:{HEADER_DARK};padding:32px 32px 24px;text-align:center;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td align="center">
                      <span style="display:inline-block;width:40px;height:40px;background-color:{BRAND_PRIMARY};
                                    color:#FFFFFF;font-size:20px;font-weight:800;line-height:40px;
                                    text-align:center;border-radius:8px;letter-spacing:-1px;">Y</span>
                    </td>
                  </tr>
                  <tr>
                    <td align="center" style="padding-top:12px;">
                      <span style="color:#FFFFFF;font-size:20px;font-weight:700;letter-spacing:4px;text-transform:uppercase;">YIELDIQ WEEKLY</span>
                    </td>
                  </tr>
                  <tr>
                    <td align="center" style="padding-top:6px;">
                      <span style="color:#94A3B8;font-size:13px;">{week_start} &ndash; {week_end}</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- ═══ STOCK CARDS ═══ -->
            <tr>
              <td style="padding:28px 32px 0;">
                {stocks_section}
              </td>
            </tr>

            <!-- ═══ CTA BUTTON ═══ -->
            <tr>
              <td align="center" style="padding:28px 32px 8px;">
                <table cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td align="center" style="background-color:{BRAND_PRIMARY};border-radius:8px;">
                      <a href="{SITE_URL}/discover"
                         style="display:inline-block;padding:14px 36px;color:#FFFFFF;
                                font-size:15px;font-weight:600;text-decoration:none;">
                        Explore All Stocks &rarr;
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- ═══ QUICK STATS ═══ -->
            <tr>
              <td style="padding:24px 32px 0;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;">
                  <tr>
                    <td style="padding:16px 18px 8px;">
                      <span style="font-size:13px;font-weight:700;color:#64748B;text-transform:uppercase;letter-spacing:1px;">Quick Stats</span>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:0 18px;">
                      <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                          <td style="padding:6px 0;font-size:14px;color:#64748B;">Nifty 50</td>
                          <td style="padding:6px 0;text-align:right;font-weight:600;color:#0F172A;font-size:14px;">&mdash;</td>
                        </tr>
                        <tr>
                          <td style="padding:6px 0;font-size:14px;color:#64748B;">Sensex</td>
                          <td style="padding:6px 0;text-align:right;font-weight:600;color:#0F172A;font-size:14px;">&mdash;</td>
                        </tr>
                        <tr>
                          <td style="padding:6px 0;font-size:14px;color:#64748B;">Stocks analyzed</td>
                          <td style="padding:6px 0;text-align:right;font-weight:600;color:#0F172A;font-size:14px;">2,900+</td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:8px 18px 16px;">
                      <span style="font-size:11px;color:#94A3B8;">Live data available at yieldiq.in/market</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- ═══ FOOTER ═══ -->
            <tr>
              <td>
                {_email_footer(email)}
              </td>
            </tr>

          </table>
        </td>
      </tr>
    </table>
    """

    return _send_email(email, subject, html)


# ═══════════════════════════════════════════════════════════════
# WEEKLY DIGEST BATCH SENDER (called by scheduler)
# ═══════════════════════════════════════════════════════════════

## ── Strategic email limits (100/day SendGrid free tier) ──────
# Budget: ~20 welcome + ~50 digest + ~30 alerts = 100/day max
DAILY_DIGEST_LIMIT = 50   # Max digest emails per Monday
DAILY_WELCOME_LIMIT = 20  # Max welcome emails per day


def send_weekly_digests_to_all() -> int:
    """
    Send weekly digest to subscribed, active users only.
    Limited to DAILY_DIGEST_LIMIT to stay within SendGrid free tier.
    Prioritizes paid users first, then most recently active free users.
    """
    emails = _get_digest_recipients()
    if not emails:
        logger.info("No eligible users for weekly digest")
        return 0

    # Cap at limit
    if len(emails) > DAILY_DIGEST_LIMIT:
        logger.info(f"Capping digest from {len(emails)} to {DAILY_DIGEST_LIMIT} recipients")
        emails = emails[:DAILY_DIGEST_LIMIT]

    sent = 0
    for email in emails:
        try:
            if send_weekly_digest(email):
                sent += 1
            time.sleep(1)  # Rate limit: 1/sec for SendGrid
        except Exception as e:
            logger.error(f"Weekly digest failed for {hash_email(email)}: {e}")

    logger.info(f"Weekly digest: {sent}/{len(emails)} sent (limit: {DAILY_DIGEST_LIMIT})")
    return sent


def _get_digest_recipients() -> list[str]:
    """
    Get digest-eligible emails, ordered by priority:
    1. Paid users (starter/pro) — always get digest
    2. Active free users (signed up within last 30 days)
    Excludes opted-out users.
    """
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()

        # Get paid users first (highest priority)
        paid = (
            client.table("users_meta")
            .select("email, tier")
            .or_("email_opted_out.is.null,email_opted_out.eq.false")
            .in_("tier", ["starter", "pro"])
            .execute()
        )
        paid_emails = [r["email"] for r in (paid.data or []) if r.get("email")]

        # Then get active free users (recent signups)
        free = (
            client.table("users_meta")
            .select("email")
            .or_("email_opted_out.is.null,email_opted_out.eq.false")
            .eq("tier", "free")
            .order("created_at", desc=True)
            .limit(DAILY_DIGEST_LIMIT)
            .execute()
        )
        free_emails = [r["email"] for r in (free.data or []) if r.get("email")]

        # Paid first, then free — deduplicated
        seen = set()
        ordered = []
        for e in paid_emails + free_emails:
            if e not in seen:
                seen.add(e)
                ordered.append(e)

        return ordered

    except Exception as e:
        logger.warning(f"Failed to get digest recipients: {e}")

    # Fallback: try auth admin list
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        users_response = client.auth.admin.list_users()
        if users_response:
            return [u.email for u in users_response if u.email][:DAILY_DIGEST_LIMIT]
    except Exception:
        pass

    return []
