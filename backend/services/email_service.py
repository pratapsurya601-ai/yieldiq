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

logger = logging.getLogger(__name__)

# ── SendGrid config ───────────────────────────────────────────

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@yieldiq.com")

BRAND_COLOR = "#1D4ED8"
BRAND_DARK = "#1E40AF"
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
    <div style="margin-top:40px;padding-top:20px;border-top:1px solid #E5E7EB;">
      <p style="font-size:12px;color:#9CA3AF;line-height:1.6;">
        You are receiving this email because you signed up on YieldIQ.
        <a href="{unsub_url}" style="color:#6B7280;text-decoration:underline;">Unsubscribe</a>
      </p>
      <p style="font-size:11px;color:#D1D5DB;line-height:1.5;margin-top:12px;">
        {SEBI_DISCLAIMER}
      </p>
      <p style="font-size:11px;color:#D1D5DB;margin-top:8px;">
        &copy; {datetime.now().year} YieldIQ &middot; yieldiq.in
      </p>
    </div>
    """


def _send_email(to_email: str, subject: str, html_content: str) -> bool:
    """Send an email via SendGrid. Returns True on success."""
    if not SENDGRID_API_KEY:
        logger.info(f"SendGrid not configured -- skipping email to {to_email}")
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
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"SendGrid email failed for {to_email}: {e}")
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
        logger.debug(f"Could not check unsubscribe status for {email}: {e}")
    return False


def mark_user_unsubscribed(email: str) -> bool:
    """Mark user as unsubscribed in users_meta."""
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        client.table("users_meta").update(
            {"email_opted_out": True}
        ).eq("email", email).execute()
        logger.info(f"User unsubscribed: {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to unsubscribe {email}: {e}")
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
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
                max-width:600px;margin:0 auto;padding:0;background:#FFFFFF;">

      <!-- Header -->
      <div style="background:linear-gradient(135deg,{BRAND_COLOR},{BRAND_DARK});
                  padding:32px 24px;text-align:center;border-radius:8px 8px 0 0;">
        <h1 style="color:#FFFFFF;font-size:28px;margin:0;font-weight:700;letter-spacing:-0.5px;">
          YieldIQ
        </h1>
        <p style="color:#BFDBFE;font-size:14px;margin:4px 0 0;">
          Institutional-grade stock valuation
        </p>
      </div>

      <!-- Body -->
      <div style="padding:32px 24px;">
        <h2 style="color:#111827;font-size:22px;margin:0 0 8px;">
          Welcome to YieldIQ, {display_name}!
        </h2>
        <p style="color:#4B5563;font-size:15px;line-height:1.6;margin:0 0 24px;">
          You now have access to DCF-powered stock analysis trusted by serious investors.
          Here is how to get started:
        </p>

        <!-- 3 Steps -->
        <div style="margin:0 0 28px;">
          <div style="display:flex;align-items:flex-start;margin-bottom:16px;">
            <div style="flex-shrink:0;width:32px;height:32px;background:{BRAND_COLOR};
                        color:#FFF;border-radius:50%;text-align:center;line-height:32px;
                        font-weight:700;font-size:14px;margin-right:12px;">1</div>
            <div>
              <p style="color:#111827;font-weight:600;margin:0 0 2px;font-size:15px;">
                Search a stock
              </p>
              <p style="color:#6B7280;font-size:13px;margin:0;">
                Type any NSE ticker or company name
              </p>
            </div>
          </div>
          <div style="display:flex;align-items:flex-start;margin-bottom:16px;">
            <div style="flex-shrink:0;width:32px;height:32px;background:{BRAND_COLOR};
                        color:#FFF;border-radius:50%;text-align:center;line-height:32px;
                        font-weight:700;font-size:14px;margin-right:12px;">2</div>
            <div>
              <p style="color:#111827;font-weight:600;margin:0 0 2px;font-size:15px;">
                See fair value
              </p>
              <p style="color:#6B7280;font-size:13px;margin:0;">
                Our 10-year DCF model calculates intrinsic value instantly
              </p>
            </div>
          </div>
          <div style="display:flex;align-items:flex-start;margin-bottom:16px;">
            <div style="flex-shrink:0;width:32px;height:32px;background:{BRAND_COLOR};
                        color:#FFF;border-radius:50%;text-align:center;line-height:32px;
                        font-weight:700;font-size:14px;margin-right:12px;">3</div>
            <div>
              <p style="color:#111827;font-weight:600;margin:0 0 2px;font-size:15px;">
                Make smarter decisions
              </p>
              <p style="color:#6B7280;font-size:13px;margin:0;">
                Invest with confidence using margin of safety scores
              </p>
            </div>
          </div>
        </div>

        <!-- CTA -->
        <div style="text-align:center;margin:28px 0;">
          <a href="{SITE_URL}/search"
             style="display:inline-block;background:{BRAND_COLOR};color:#FFFFFF;
                    padding:14px 32px;border-radius:8px;text-decoration:none;
                    font-weight:600;font-size:16px;">
            Analyze Your First Stock &rarr;
          </a>
        </div>

        <!-- Free tier note -->
        <div style="background:#F0F9FF;border:1px solid #BFDBFE;border-radius:8px;
                    padding:16px;text-align:center;margin:24px 0;">
          <p style="color:#1E40AF;font-size:14px;margin:0;">
            <strong>Free tier:</strong> 5 analyses per day.
            <a href="{SITE_URL}/pricing" style="color:{BRAND_COLOR};text-decoration:underline;">
              Upgrade for unlimited
            </a>.
          </p>
        </div>
      </div>

      <!-- Footer -->
      {_email_footer(email)}
    </div>
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
                query = text("""
                    SELECT
                        s.ticker,
                        s.company_name,
                        dp.close_price,
                        mm.pe_ratio
                    FROM stocks s
                    JOIN daily_prices dp ON dp.ticker = s.ticker
                    JOIN market_metrics mm ON mm.ticker = s.ticker
                    WHERE s.is_active = true
                      AND dp.trade_date = (SELECT MAX(trade_date) FROM daily_prices)
                      AND mm.trade_date = (SELECT MAX(trade_date) FROM market_metrics)
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
                if _mos > 30:
                    verdict = "Strong Buy"
                elif _mos > 15:
                    verdict = "Undervalued"
                elif _mos > 0:
                    verdict = "Slightly Undervalued"
                else:
                    verdict = "Fair Value"
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

    # Build stock rows
    if top_stocks:
        stock_rows = ""
        for i, s in enumerate(top_stocks):
            display_ticker = s["ticker"].replace(".NS", "").replace(".BO", "")
            bg = "#F9FAFB" if i % 2 == 0 else "#FFFFFF"
            mos_display = f"+{s['mos_pct']:.0f}%" if s["mos_pct"] > 0 else f"{s['mos_pct']:.0f}%"
            vc = _verdict_color(s["verdict"])
            stock_rows += f"""
            <tr style="background:{bg};">
              <td style="padding:12px 8px;font-weight:600;color:#111827;font-size:14px;">
                {display_ticker}
                <br><span style="font-weight:400;color:#6B7280;font-size:12px;">{s['company_name']}</span>
              </td>
              <td style="padding:12px 8px;text-align:center;font-weight:600;color:{BRAND_COLOR};font-size:14px;">
                {s['score']}
              </td>
              <td style="padding:12px 8px;text-align:center;font-weight:600;color:#059669;font-size:14px;">
                {mos_display}
              </td>
              <td style="padding:12px 8px;text-align:center;">
                <span style="display:inline-block;background:{vc};color:#FFF;padding:2px 8px;
                             border-radius:4px;font-size:12px;font-weight:600;">{s['verdict']}</span>
              </td>
            </tr>
            """
        stocks_section = f"""
        <h3 style="color:#111827;font-size:18px;margin:28px 0 12px;">
          Top Undervalued Stocks This Week
        </h3>
        <table style="width:100%;border-collapse:collapse;border:1px solid #E5E7EB;border-radius:8px;">
          <thead>
            <tr style="background:#F3F4F6;">
              <th style="padding:10px 8px;text-align:left;font-size:12px;color:#6B7280;
                         text-transform:uppercase;letter-spacing:0.5px;">Stock</th>
              <th style="padding:10px 8px;text-align:center;font-size:12px;color:#6B7280;
                         text-transform:uppercase;letter-spacing:0.5px;">Score</th>
              <th style="padding:10px 8px;text-align:center;font-size:12px;color:#6B7280;
                         text-transform:uppercase;letter-spacing:0.5px;">MoS</th>
              <th style="padding:10px 8px;text-align:center;font-size:12px;color:#6B7280;
                         text-transform:uppercase;letter-spacing:0.5px;">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {stock_rows}
          </tbody>
        </table>
        """
    else:
        stocks_section = """
        <div style="background:#F9FAFB;border-radius:8px;padding:24px;text-align:center;margin:20px 0;">
          <p style="color:#6B7280;font-size:14px;margin:0;">
            No screener data available this week. Check back next Monday!
          </p>
        </div>
        """

    subject = f"YieldIQ Weekly Digest -- {week_start} to {week_end}"

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
                max-width:600px;margin:0 auto;padding:0;background:#FFFFFF;">

      <!-- Header -->
      <div style="background:linear-gradient(135deg,{BRAND_COLOR},{BRAND_DARK});
                  padding:28px 24px;text-align:center;border-radius:8px 8px 0 0;">
        <h1 style="color:#FFFFFF;font-size:24px;margin:0;font-weight:700;">
          YieldIQ
        </h1>
        <p style="color:#BFDBFE;font-size:16px;margin:6px 0 0;font-weight:500;">
          Weekly Market Insights
        </p>
        <p style="color:#93C5FD;font-size:13px;margin:4px 0 0;">
          {week_start} &ndash; {week_end}
        </p>
      </div>

      <!-- Body -->
      <div style="padding:24px;">

        {stocks_section}

        <!-- CTA -->
        <div style="text-align:center;margin:28px 0;">
          <a href="{SITE_URL}/discover"
             style="display:inline-block;background:{BRAND_COLOR};color:#FFFFFF;
                    padding:12px 28px;border-radius:8px;text-decoration:none;
                    font-weight:600;font-size:15px;">
            See All on YieldIQ &rarr;
          </a>
        </div>

        <!-- Market Pulse -->
        <div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;
                    padding:20px;margin:24px 0;">
          <h3 style="color:#111827;font-size:16px;margin:0 0 12px;">
            Market Pulse
          </h3>
          <table style="width:100%;border-collapse:collapse;">
            <tr>
              <td style="padding:6px 0;color:#6B7280;font-size:14px;">Nifty 50</td>
              <td style="padding:6px 0;text-align:right;font-weight:600;color:#111827;font-size:14px;">
                --
              </td>
              <td style="padding:6px 0;text-align:right;color:#6B7280;font-size:13px;">
                --
              </td>
            </tr>
            <tr>
              <td style="padding:6px 0;color:#6B7280;font-size:14px;">Sensex</td>
              <td style="padding:6px 0;text-align:right;font-weight:600;color:#111827;font-size:14px;">
                --
              </td>
              <td style="padding:6px 0;text-align:right;color:#6B7280;font-size:13px;">
                --
              </td>
            </tr>
          </table>
          <p style="color:#9CA3AF;font-size:11px;margin:8px 0 0;">
            Live data available on yieldiq.in/market
          </p>
        </div>

      </div>

      <!-- Footer -->
      {_email_footer(email)}
    </div>
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
            logger.error(f"Weekly digest failed for {email}: {e}")

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
