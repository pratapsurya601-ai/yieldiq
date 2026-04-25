# backend/services/retention_service.py
# ═══════════════════════════════════════════════════════════════
# D+1 and D+7 retention emails.
#
# Runs from the retention_emails.yml GitHub Actions cron (NOT the
# Railway APScheduler — avoids piling more load onto the single
# Hobby-tier worker). Daily at 08:00 IST.
#
# Queries Supabase auth.users for accounts created exactly N days
# ago, filters out unsubscribed accounts via users_meta, and sends
# a cohort-specific email through the existing SendGrid integration.
#
# Emails:
#   D+1  "Here's how to analyse your first stock"   — activation push
#   D+7  "Stocks worth a second look this week"     — retention push
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from backend.services.email_service import (
    _send_email,
    _email_footer,
    is_user_unsubscribed,
    BRAND_PRIMARY,
    HEADER_DARK,
    SITE_URL,
)

logger = logging.getLogger("yieldiq.retention")


# ── Target cohort lookup ──────────────────────────────────────


def _get_admin_client():
    try:
        from db.supabase_client import get_admin_client
        return get_admin_client()
    except Exception as exc:
        logger.warning("retention: supabase admin client unavailable: %s", exc)
        return None


def get_users_signed_up_on(target_date) -> list[dict]:
    """Return accounts whose ``created_at`` falls on ``target_date`` (UTC).

    Supabase admin.list_users returns at most 50 users per page by
    default; we paginate until we find everyone from the target day.
    In practice most pages will sort newest-first, so we can stop as
    soon as we see a user older than target_date - 1 day.
    """
    client = _get_admin_client()
    if client is None:
        return []

    day_start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    matched: list[dict] = []
    page = 1
    per_page = 100
    while page < 50:  # hard stop: 5,000 users
        try:
            resp = client.auth.admin.list_users(page=page, per_page=per_page)
        except Exception as exc:
            logger.warning("retention: list_users page %d failed: %s", page, exc)
            break
        users = getattr(resp, "users", None) or resp
        if not users:
            break
        all_older = True
        for u in users:
            ts_raw = getattr(u, "created_at", None)
            if not ts_raw:
                continue
            try:
                if isinstance(ts_raw, str):
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                else:
                    ts = ts_raw
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            if ts >= day_start and ts < day_end:
                all_older = False
                matched.append({
                    "email": getattr(u, "email", None),
                    "user_id": str(getattr(u, "id", "")),
                    "created_at": ts.isoformat(),
                })
            elif ts >= day_end:
                all_older = False  # still walking newer rows
            # ts < day_start → keep going; rows may not be sorted
        if all_older:
            break
        if len(users) < per_page:
            break
        page += 1

    return [m for m in matched if m.get("email")]


# ── Templates ──────────────────────────────────────────────────


def _d1_html(email: str) -> str:
    """D+1: activation nudge — 'try your first analysis now'."""
    name = email.split("@")[0].title()
    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;background:#F1F5F9;padding:24px 16px;">
      <div style="max-width:600px;margin:0 auto;background:#FFFFFF;border-radius:8px;overflow:hidden;">
        <div style="background:{HEADER_DARK};padding:28px 32px;text-align:center;">
          <div style="color:#FFFFFF;font-size:20px;font-weight:700;letter-spacing:3px;">YIELDIQ</div>
        </div>
        <div style="padding:32px;">
          <h1 style="margin:0 0 12px;font-size:22px;color:#0F172A;">
            Hi {name}, ready to find your first undervalued stock?
          </h1>
          <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#334155;">
            You signed up yesterday. Here's the 60-second path to your first insight:
          </p>
          <ol style="padding-left:20px;margin:0 0 20px;color:#334155;font-size:15px;line-height:1.7;">
            <li>Open an analysis for a stock you already own or follow</li>
            <li>Look at the <strong>Fair Value</strong> vs. the current price</li>
            <li>If the Margin of Safety is &gt;20% green, it's statistically undervalued by our model</li>
          </ol>
          <p style="margin:0 0 24px;font-size:14px;color:#64748B;">
            Popular starting points: Reliance, TCS, HDFC Bank, Infosys, ITC.
          </p>
          <a href="{SITE_URL}/search"
             style="display:inline-block;padding:12px 24px;background:{BRAND_PRIMARY};color:#FFFFFF;
                    text-decoration:none;border-radius:8px;font-weight:600;font-size:15px;">
            Analyse a stock now &rarr;
          </a>
          <p style="margin:24px 0 0;font-size:13px;color:#94A3B8;line-height:1.5;">
            Free plan: 5 analyses per day. Upgrade to Pro (₹299/mo) for unlimited + interactive DCF sliders.
          </p>
        </div>
        {_email_footer(email)}
      </div>
    </div>
    """


def _d7_html(email: str, top_picks: list[dict]) -> str:
    """D+7: retention — 'here's what's interesting this week'.

    top_picks: list of {ticker, company_name, mos_pct, fair_value, current_price}
    — up to 3 items. If empty, we fall back to a generic 'explore Nifty 50'.
    """
    name = email.split("@")[0].title()

    picks_html = ""
    if top_picks:
        rows = []
        for p in top_picks[:3]:
            tkr_clean = (p.get("ticker") or "").replace(".NS", "").replace(".BO", "")
            name_clean = p.get("company_name") or tkr_clean
            mos = p.get("mos_pct") or 0
            fv = p.get("fair_value") or 0
            cp = p.get("current_price") or 0
            rows.append(f"""
              <tr>
                <td style="padding:14px 16px;border-bottom:1px solid #E5E7EB;">
                  <a href="{SITE_URL}/analysis/{p.get('ticker')}"
                     style="color:{BRAND_PRIMARY};text-decoration:none;font-weight:600;">
                    {name_clean} ({tkr_clean})
                  </a>
                  <div style="font-size:13px;color:#64748B;margin-top:4px;">
                    Fair Value ₹{fv:,.0f} · Price ₹{cp:,.0f} ·
                    <span style="color:#059669;font-weight:600;">+{mos:.0f}% MoS</span>
                  </div>
                </td>
              </tr>
            """)
        picks_html = f"""
          <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 24px;border:1px solid #E5E7EB;border-radius:8px;overflow:hidden;">
            {"".join(rows)}
          </table>
        """
    else:
        picks_html = f"""
          <p style="margin:0 0 20px;font-size:14px;color:#64748B;">
            Browse the YieldIQ 50 on
            <a href="{SITE_URL}/nifty50" style="color:{BRAND_PRIMARY};">/nifty50</a>
            to see what's caught our model's eye this week.
          </p>
        """

    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;background:#F1F5F9;padding:24px 16px;">
      <div style="max-width:600px;margin:0 auto;background:#FFFFFF;border-radius:8px;overflow:hidden;">
        <div style="background:{HEADER_DARK};padding:28px 32px;text-align:center;">
          <div style="color:#FFFFFF;font-size:20px;font-weight:700;letter-spacing:3px;">YIELDIQ</div>
        </div>
        <div style="padding:32px;">
          <h1 style="margin:0 0 12px;font-size:22px;color:#0F172A;">
            {name}, here's what caught our model's eye this week.
          </h1>
          <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:#334155;">
            These are the <strong>3 most undervalued stocks</strong> in our coverage
            universe right now — ranked by Margin of Safety. Each link opens the
            full DCF breakdown.
          </p>
          {picks_html}
          <a href="{SITE_URL}/discover"
             style="display:inline-block;padding:12px 24px;background:{BRAND_PRIMARY};color:#FFFFFF;
                    text-decoration:none;border-radius:8px;font-weight:600;font-size:15px;">
            See more picks &rarr;
          </a>
          <p style="margin:24px 0 0;font-size:13px;color:#94A3B8;line-height:1.5;">
            You'll receive this once — the full weekly newsletter runs every Sunday if you stay subscribed.
          </p>
        </div>
        {_email_footer(email)}
      </div>
    </div>
    """


# ── Data for D+7 picks ────────────────────────────────────────


def _get_top_undervalued(n: int = 3) -> list[dict]:
    """Pull the N most undervalued stocks from the analysis_cache table.
    Sorted by margin_of_safety (desc). Filters out data_limited verdicts
    and anything where mos_pct < 10 (not meaningfully undervalued)."""
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text
    except Exception as exc:
        logger.warning("retention: db imports failed: %s", exc)
        return []

    sess = Session()
    try:
        # PERF (egress): JSONB path extraction - pull the 5 scalars we
        # need instead of the full payload (100KB+ x 250 rows ~= 25MB
        # per call). Same field semantics as the prior dict-walk path.
        rows = sess.execute(text(
            """
            SELECT
              ticker,
              (payload->'valuation'->>'verdict')                 AS verdict,
              (payload->'valuation'->>'margin_of_safety')::float AS mos,
              (payload->'valuation'->>'fair_value')::float       AS fair_value,
              (payload->'valuation'->>'current_price')::float    AS current_price,
              COALESCE(payload->'company'->>'company_name',
                       payload->'company_info'->>'company_name',
                       payload->'company_info'->>'name')         AS company_name
            FROM analysis_cache
            WHERE computed_at > now() - interval '48 hours'
            ORDER BY computed_at DESC
            LIMIT 250
            """
        )).fetchall()
    except Exception as exc:
        logger.warning("retention: analysis_cache query failed: %s", exc)
        sess.close()
        return []
    finally:
        sess.close()

    picks = []
    for r in rows:
        verdict = r[1]
        mos = r[2]
        if verdict in ("data_limited", "unavailable", None):
            continue
        if mos is None or mos < 10:
            continue
        picks.append({
            "ticker": r[0],
            "company_name": r[5] or r[0],
            "mos_pct": float(mos),
            "fair_value": float(r[3] or 0),
            "current_price": float(r[4] or 0),
        })

    picks.sort(key=lambda p: p["mos_pct"], reverse=True)
    return picks[:n]


# ── Batch runners ─────────────────────────────────────────────


def run_retention_batch(day_offset: int) -> dict:
    """Send the cohort email for everyone who signed up exactly ``day_offset``
    days ago. Returns a summary dict.

    day_offset = 1 → D+1 activation
    day_offset = 7 → D+7 retention
    """
    target_date = (datetime.now(timezone.utc) - timedelta(days=day_offset)).date()
    logger.info("retention: running D+%d batch for signup_date=%s", day_offset, target_date)

    users = get_users_signed_up_on(target_date)
    if not users:
        logger.info("retention: no users signed up on %s", target_date)
        return {"day_offset": day_offset, "target_date": str(target_date), "sent": 0, "skipped": 0, "failed": 0}

    top_picks = _get_top_undervalued(3) if day_offset == 7 else []

    sent = 0
    skipped = 0
    failed = 0
    for u in users:
        email = u["email"]
        try:
            if is_user_unsubscribed(email):
                skipped += 1
                continue
            if day_offset == 1:
                html = _d1_html(email)
                subject = "Ready to find your first undervalued stock?"
            elif day_offset == 7:
                html = _d7_html(email, top_picks)
                subject = "3 stocks worth a second look this week"
            else:
                skipped += 1
                continue

            ok = _send_email(email, subject, html)
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as exc:
            logger.warning("retention: send failed for %s: %s", email, exc)
            failed += 1

    logger.info(
        "retention: D+%d batch complete — sent=%d skipped=%d failed=%d",
        day_offset, sent, skipped, failed,
    )
    return {
        "day_offset": day_offset,
        "target_date": str(target_date),
        "matched": len(users),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }


def run_all_retention() -> list[dict]:
    """Entry point for the cron — runs both cohorts."""
    return [run_retention_batch(1), run_retention_batch(7)]
