# backend/services/newsletter_service.py
# ═══════════════════════════════════════════════════════════════
# Weekly newsletter — Sunday 8am IST
# Richer content than weekly digest: top 5 undervalued, top 3
# overvalued, market sentiment, AI analysis, CTA.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.services.cache_service import cache
from backend.services.email_service import (
    _send_email, _email_footer, is_user_unsubscribed,
    BRAND_PRIMARY, BRAND_ACCENT, HEADER_DARK, SITE_URL, SEBI_DISCLAIMER,
)

logger = logging.getLogger("yieldiq.newsletter")


def get_top_undervalued(limit: int = 5) -> list[dict]:
    """Top N undervalued stocks from cache by score * mos ranking."""
    candidates = []
    for key in list(cache._store.keys()):
        if not key.startswith("analysis:") or ".NS" not in key:
            continue
        val = cache.get(key)
        if val and hasattr(val, "valuation") and val.valuation.verdict == "undervalued":
            candidates.append({
                "ticker": val.ticker.replace(".NS", "").replace(".BO", ""),
                "company_name": val.company.company_name,
                "sector": val.company.sector,
                "score": val.quality.yieldiq_score,
                "mos": val.valuation.margin_of_safety,
                "fair_value": val.valuation.fair_value,
                "price": val.valuation.current_price,
                "moat": val.quality.moat,
            })
    candidates.sort(key=lambda x: x["score"] * max(x["mos"], 0), reverse=True)
    return candidates[:limit]


def get_top_overvalued(limit: int = 3) -> list[dict]:
    """Top N overvalued stocks from cache."""
    candidates = []
    for key in list(cache._store.keys()):
        if not key.startswith("analysis:") or ".NS" not in key:
            continue
        val = cache.get(key)
        if val and hasattr(val, "valuation") and val.valuation.verdict in ("overvalued", "avoid"):
            candidates.append({
                "ticker": val.ticker.replace(".NS", "").replace(".BO", ""),
                "company_name": val.company.company_name,
                "score": val.quality.yieldiq_score,
                "mos": val.valuation.margin_of_safety,
                "price": val.valuation.current_price,
                "fair_value": val.valuation.fair_value,
            })
    candidates.sort(key=lambda x: x["mos"])
    return candidates[:limit]


def get_market_sentiment() -> dict:
    """Aggregate verdict counts from cache."""
    verdicts = {"undervalued": 0, "fairly_valued": 0, "overvalued": 0, "avoid": 0}
    total = 0
    for key in list(cache._store.keys()):
        if key.startswith("analysis:") and ".NS" in key:
            val = cache.get(key)
            if val and hasattr(val, "valuation"):
                v = val.valuation.verdict
                if v in verdicts:
                    verdicts[v] += 1
                    total += 1
    return {"verdicts": verdicts, "total": total}


def _fmt_inr(n: float) -> str:
    try:
        return f"\u20B9{n:,.0f}"
    except Exception:
        return "\u2014"


def _mos_color(mos: float) -> str:
    return "#10B981" if mos >= 0 else "#EF4444"


def build_newsletter_html(email: str) -> str:
    """Build the full newsletter HTML."""
    undervalued = get_top_undervalued(5)
    overvalued = get_top_overvalued(3)
    sentiment = get_market_sentiment()

    now = datetime.now(timezone.utc)
    week_label = now.strftime("%B %d, %Y")

    # Stock rows for undervalued
    uv_rows = ""
    for i, s in enumerate(undervalued):
        bg = "#F0FDF4" if i % 2 == 0 else "#FFFFFF"
        uv_rows += f"""
        <tr style="background:{bg};">
          <td style="padding:10px 16px;font-weight:700;color:#111827;">{s['ticker']}</td>
          <td style="padding:10px 16px;color:#6B7280;font-size:13px;">{s['company_name'][:25]}</td>
          <td style="padding:10px 16px;font-family:monospace;text-align:right;">{_fmt_inr(s['price'])}</td>
          <td style="padding:10px 16px;font-family:monospace;text-align:right;">{_fmt_inr(s['fair_value'])}</td>
          <td style="padding:10px 16px;font-family:monospace;text-align:right;color:{_mos_color(s['mos'])};font-weight:700;">+{s['mos']:.1f}%</td>
          <td style="padding:10px 16px;text-align:center;font-weight:700;">{s['score']}</td>
        </tr>"""

    # Overvalued rows
    ov_rows = ""
    for i, s in enumerate(overvalued):
        bg = "#FEF2F2" if i % 2 == 0 else "#FFFFFF"
        ov_rows += f"""
        <tr style="background:{bg};">
          <td style="padding:10px 16px;font-weight:700;color:#111827;">{s['ticker']}</td>
          <td style="padding:10px 16px;color:#6B7280;font-size:13px;">{s['company_name'][:25]}</td>
          <td style="padding:10px 16px;font-family:monospace;text-align:right;">{_fmt_inr(s['price'])}</td>
          <td style="padding:10px 16px;font-family:monospace;text-align:right;">{_fmt_inr(s['fair_value'])}</td>
          <td style="padding:10px 16px;font-family:monospace;text-align:right;color:#EF4444;font-weight:700;">{s['mos']:.1f}%</td>
        </tr>"""

    # Sentiment bar
    total = sentiment["total"] or 1
    uv_pct = round(sentiment["verdicts"]["undervalued"] / total * 100)
    fv_pct = round(sentiment["verdicts"]["fairly_valued"] / total * 100)
    ov_pct = 100 - uv_pct - fv_pct

    html = f"""
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="margin:0;padding:0;background:#F9FAFB;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;margin:0 auto;">
        <!-- Header -->
        <tr><td style="background:linear-gradient(135deg,{HEADER_DARK},{BRAND_PRIMARY});padding:32px 24px;text-align:center;">
          <h1 style="color:white;font-size:28px;margin:0 0 8px;">YieldIQ Weekly</h1>
          <p style="color:#93C5FD;font-size:14px;margin:0;">Week of {week_label}</p>
        </td></tr>

        <!-- Market Sentiment -->
        <tr><td style="padding:24px;">
          <h2 style="font-size:18px;color:#111827;margin:0 0 12px;">Market Sentiment</h2>
          <p style="font-size:14px;color:#6B7280;margin:0 0 12px;">
            Of {sentiment['total']} stocks analysed: {sentiment['verdicts']['undervalued']} undervalued,
            {sentiment['verdicts']['fairly_valued']} fairly valued, {sentiment['verdicts']['overvalued'] + sentiment['verdicts']['avoid']} overvalued.
          </p>
          <div style="display:flex;height:24px;border-radius:12px;overflow:hidden;background:#E5E7EB;">
            <div style="width:{uv_pct}%;background:#10B981;"></div>
            <div style="width:{fv_pct}%;background:#3B82F6;"></div>
            <div style="width:{ov_pct}%;background:#EF4444;"></div>
          </div>
          <div style="display:flex;gap:16px;margin-top:8px;font-size:12px;color:#6B7280;">
            <span style="color:#10B981;">&#9632; {uv_pct}% undervalued</span>
            <span style="color:#3B82F6;">&#9632; {fv_pct}% fair</span>
            <span style="color:#EF4444;">&#9632; {ov_pct}% overvalued</span>
          </div>
        </td></tr>

        <!-- Top 5 Undervalued -->
        <tr><td style="padding:0 24px 24px;">
          <h2 style="font-size:18px;color:#111827;margin:0 0 12px;">Top 5 Undervalued Stocks</h2>
          <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #E5E7EB;border-radius:8px;overflow:hidden;font-size:13px;">
            <tr style="background:#F3F4F6;">
              <th style="padding:10px 16px;text-align:left;font-weight:600;color:#6B7280;">Ticker</th>
              <th style="padding:10px 16px;text-align:left;font-weight:600;color:#6B7280;">Company</th>
              <th style="padding:10px 16px;text-align:right;font-weight:600;color:#6B7280;">Price</th>
              <th style="padding:10px 16px;text-align:right;font-weight:600;color:#6B7280;">Fair Value</th>
              <th style="padding:10px 16px;text-align:right;font-weight:600;color:#6B7280;">MoS%</th>
              <th style="padding:10px 16px;text-align:center;font-weight:600;color:#6B7280;">Score</th>
            </tr>
            {uv_rows if uv_rows else '<tr><td colspan="6" style="padding:20px;text-align:center;color:#9CA3AF;">Cache warming — check back soon</td></tr>'}
          </table>
        </td></tr>

        <!-- Top 3 Overvalued -->
        <tr><td style="padding:0 24px 24px;">
          <h2 style="font-size:18px;color:#111827;margin:0 0 12px;">Most Overvalued (Caution)</h2>
          <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #E5E7EB;border-radius:8px;overflow:hidden;font-size:13px;">
            <tr style="background:#F3F4F6;">
              <th style="padding:10px 16px;text-align:left;font-weight:600;color:#6B7280;">Ticker</th>
              <th style="padding:10px 16px;text-align:left;font-weight:600;color:#6B7280;">Company</th>
              <th style="padding:10px 16px;text-align:right;font-weight:600;color:#6B7280;">Price</th>
              <th style="padding:10px 16px;text-align:right;font-weight:600;color:#6B7280;">Fair Value</th>
              <th style="padding:10px 16px;text-align:right;font-weight:600;color:#6B7280;">MoS%</th>
            </tr>
            {ov_rows if ov_rows else '<tr><td colspan="5" style="padding:20px;text-align:center;color:#9CA3AF;">No overvalued stocks found this week</td></tr>'}
          </table>
        </td></tr>

        <!-- CTA -->
        <tr><td style="padding:0 24px 24px;text-align:center;">
          <a href="{SITE_URL}/nifty50" style="display:inline-block;background:{BRAND_PRIMARY};color:white;font-weight:700;padding:14px 32px;border-radius:12px;text-decoration:none;font-size:16px;">
            View Full Nifty 50 Dashboard &rarr;
          </a>
        </td></tr>

        <!-- Footer -->
        {_email_footer(email)}
      </table>
    </body></html>
    """
    return html


def send_newsletter(email: str) -> bool:
    """Send weekly newsletter to a single user."""
    if is_user_unsubscribed(email):
        return False
    html = build_newsletter_html(email)
    now = datetime.now(timezone.utc)
    subject = f"YieldIQ Weekly: Top Undervalued Stocks \u2014 {now.strftime('%b %d, %Y')}"
    return _send_email(email, subject, html)


def send_newsletter_to_all() -> int:
    """Send newsletter to all subscribed users. Returns count sent."""
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        if not client:
            logger.warning("Supabase not available for newsletter")
            return 0
        result = (
            client.table("users_meta")
            .select("email")
            .neq("email_opted_out", True)
            .execute()
        )
        emails = [r["email"] for r in (result.data or []) if r.get("email")]
    except Exception as e:
        logger.error(f"Failed to fetch newsletter recipients: {e}")
        return 0

    count = 0
    for email in emails:
        try:
            if send_newsletter(email):
                count += 1
        except Exception as e:
            logger.warning(f"Newsletter failed for {email}: {e}")

    logger.info(f"Newsletter complete: {count}/{len(emails)} sent")
    return count
