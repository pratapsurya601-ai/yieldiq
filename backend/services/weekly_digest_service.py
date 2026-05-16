"""backend/services/weekly_digest_service.py

Weekly digest content generator.

Produces a personalized {subject, html, text} payload per user. Two
branches:

  (a) User has >= 1 watchlist item:
        - Show weekly price + Below/Above Fair Value status for each
          watchlist ticker. Caps at 8 rows so the email stays scannable.

  (b) User has 0 watchlist items (the activation-crisis cohort —
      0/5 organic signups came back after first session):
        - Show "Stocks moving this week": top 5 NSE/BSE tickers whose
          fundamental score improved the most week-over-week, from the
          YieldIQ-50 canary universe (`scripts/canary_stocks_50.json`).
          We use the canary set rather than the full universe because
          (1) it is curated quality-first, (2) we already snapshot it
          nightly so week-over-week deltas are cheap to compute, and
          (3) it sidesteps the Apr-27 incident where the digest pulled
          random US OTC tickers from a stale screener CSV.

This module ONLY generates content. The actual SendGrid call and the
unsubscribe / idempotency checks live in `email_service.py` and
`scripts/send_weekly_digest.py`. Keeping content pure makes it easy
to unit-test without mocking SendGrid.

SEBI compliance:
  - No recommendation verbs ("buy/sell/strong/weak/should").
  - "Below Fair Value" / "Above Fair Value" labels only.
  - "Movers this week" wording (factual), never "Top Picks".
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Hard caps so the email stays scannable and the SendGrid payload small.
WATCHLIST_MAX_ROWS = 8
MOVERS_MAX_ROWS = 5

SITE_URL = os.environ.get("SITE_URL", "https://yieldiq.in")
BRAND_PRIMARY = "#2563EB"
HEADER_DARK = "#0F172A"


@dataclass
class DigestRow:
    """One stock row, ready for the email template."""
    ticker: str           # display ticker, no .NS/.BO suffix
    company_name: str
    price: Optional[float]
    fv_label: str         # "Below Fair Value" | "Above Fair Value" | "Around Fair Value" | "—"
    score: Optional[int]  # 0-100, may be None
    note: str             # small caption, e.g. "+4 score WoW" or "Added 12 Mar"


@dataclass
class Digest:
    subject: str
    html: str
    text: str


# ───────────────────────────────────────────────────────────────
# DB access helpers (safe-fail; digest is best-effort, never raises)
# ───────────────────────────────────────────────────────────────

def _pipeline_session():
    """Return a data_pipeline SQLAlchemy session or None."""
    try:
        from data_pipeline.db import Session
        if Session is None:
            return None
        return Session()
    except Exception as exc:
        logger.debug("weekly_digest_service: pipeline session unavailable: %s", exc)
        return None


def _supabase_client():
    """Return Supabase admin client or None."""
    try:
        from db.supabase_client import get_admin_client
        return get_admin_client()
    except Exception as exc:
        logger.debug("weekly_digest_service: supabase client unavailable: %s", exc)
        return None


def _fv_label_from_mos(mos_pct: Optional[float]) -> str:
    """Map a margin-of-safety % into a SEBI-safe descriptive label.

    > +10%  -> Below Fair Value   (price is below FV, MoS positive)
    -10..10 -> Around Fair Value
    < -10%  -> Above Fair Value   (price is above FV)
    None    -> —
    """
    if mos_pct is None:
        return "—"
    if mos_pct >= 10:
        return "Below Fair Value"
    if mos_pct <= -10:
        return "Above Fair Value"
    return "Around Fair Value"


def _get_user_watchlist(client, user_email: str) -> list[str]:
    """Return the user's watchlist tickers (Supabase `watchlist` table)."""
    if client is None or not user_email:
        return []
    try:
        result = (
            client.table("watchlist")
            .select("ticker")
            .eq("user_email", user_email)
            .execute()
        )
        return [r["ticker"] for r in (result.data or []) if r.get("ticker")]
    except Exception as exc:
        logger.debug("weekly_digest_service: watchlist read failed for %s: %s",
                     user_email, exc)
        return []


def _fetch_watchlist_rows(tickers: list[str]) -> list[DigestRow]:
    """For each watchlist ticker, fetch latest price + FV label."""
    if not tickers:
        return []
    sess = _pipeline_session()
    if sess is None:
        # Best-effort: return name-only rows so the user still sees their list.
        return [
            DigestRow(
                ticker=t.replace(".NS", "").replace(".BO", ""),
                company_name=t.replace(".NS", "").replace(".BO", ""),
                price=None,
                fv_label="—",
                score=None,
                note="",
            )
            for t in tickers[:WATCHLIST_MAX_ROWS]
        ]

    rows: list[DigestRow] = []
    try:
        from sqlalchemy import text
        # FIX-5-ENFORCED: NSE/BSE only — defensive even though watchlist
        # should already be limited to .NS/.BO.
        nsebse = [t for t in tickers if t.endswith(".NS") or t.endswith(".BO")]
        if not nsebse:
            return []
        q = text(
            """
            WITH dp AS (
                SELECT DISTINCT ON (ticker) ticker, close_price, trade_date
                FROM daily_prices
                WHERE ticker = ANY(:tickers)
                ORDER BY ticker, trade_date DESC
            )
            SELECT s.ticker,
                   COALESCE(s.company_name, s.ticker) AS company_name,
                   dp.close_price
            FROM stocks s
            LEFT JOIN dp ON dp.ticker = s.ticker
            WHERE s.ticker = ANY(:tickers)
            """
        )
        result = sess.execute(q, {"tickers": nsebse}).fetchall()
        by_ticker = {r[0]: r for r in result}
        for t in nsebse[:WATCHLIST_MAX_ROWS]:
            r = by_ticker.get(t)
            if r is None:
                continue
            price = float(r[2]) if r[2] is not None else None

            # FV label: try the analysis_cache JSON payload.
            mos_pct = _read_mos_from_cache(sess, t)
            rows.append(
                DigestRow(
                    ticker=t.replace(".NS", "").replace(".BO", ""),
                    company_name=r[1] or t,
                    price=price,
                    fv_label=_fv_label_from_mos(mos_pct),
                    score=None,
                    note="",
                )
            )
    except Exception as exc:
        logger.warning("weekly_digest_service: watchlist fetch failed: %s", exc)
    finally:
        try:
            sess.close()
        except Exception:
            pass
    return rows


def _read_mos_from_cache(sess, ticker: str) -> Optional[float]:
    """Pull margin_of_safety (%) from the latest analysis_cache row.

    Returns None on any failure or stale cache (> 14 days old) — we'd
    rather show "—" than a misleading label.
    """
    try:
        from sqlalchemy import text
        row = sess.execute(
            text(
                """
                SELECT payload
                FROM analysis_cache
                WHERE ticker = :t
                  AND computed_at > now() - interval '14 days'
                ORDER BY computed_at DESC
                LIMIT 1
                """
            ),
            {"t": ticker},
        ).fetchone()
        if not row:
            return None
        payload = row[0]
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            import json
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return None
        # Common payload keys — check the top-level and the dcf block.
        for key in ("margin_of_safety", "mos_pct", "mos"):
            v = payload.get(key)
            if isinstance(v, (int, float)):
                return float(v)
        dcf = payload.get("dcf") or {}
        for key in ("margin_of_safety", "mos_pct", "mos"):
            v = dcf.get(key)
            if isinstance(v, (int, float)):
                return float(v)
    except Exception:
        return None
    return None


def _fetch_movers_rows() -> list[DigestRow]:
    """Stocks moving this week — fundamental_score WoW improvement.

    Universe: YieldIQ canary 50 (curated, NSE/BSE only).
    Filter:   value_score > 0 AND mos > 0  (FIX-3 from the Apr-27 incident).
    Ordering: largest week-over-week score improvement first.
    """
    sess = _pipeline_session()
    if sess is None:
        return []
    rows: list[DigestRow] = []
    try:
        from sqlalchemy import text
        # Universe: canary stocks JSON file lives in scripts/.
        import json
        import pathlib
        canary_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "canary_stocks_50.json"
        if not canary_path.exists():
            return []
        canary = json.loads(canary_path.read_text(encoding="utf-8"))
        tickers = [t for t in canary if isinstance(t, str)
                   and (t.endswith(".NS") or t.endswith(".BO"))]
        if not tickers:
            return []

        # The fundamental_score_history table is the canonical WoW source.
        # Fall back to a current-snapshot ordering if history is empty.
        q = text(
            """
            WITH now_row AS (
                SELECT DISTINCT ON (ticker) ticker, fundamental_score, margin_of_safety
                FROM market_metrics
                WHERE ticker = ANY(:tickers)
                  AND market_cap_cr IS NOT NULL AND market_cap_cr > 0
                  AND fundamental_score IS NOT NULL
                ORDER BY ticker, trade_date DESC
            ),
            wk_row AS (
                SELECT DISTINCT ON (ticker) ticker, fundamental_score
                FROM market_metrics
                WHERE ticker = ANY(:tickers)
                  AND trade_date <= now() - interval '7 days'
                  AND fundamental_score IS NOT NULL
                ORDER BY ticker, trade_date DESC
            ),
            dp AS (
                SELECT DISTINCT ON (ticker) ticker, close_price
                FROM daily_prices
                WHERE ticker = ANY(:tickers)
                ORDER BY ticker, trade_date DESC
            )
            SELECT s.ticker,
                   COALESCE(s.company_name, s.ticker),
                   dp.close_price,
                   n.fundamental_score,
                   COALESCE(n.fundamental_score - w.fundamental_score, 0) AS delta,
                   n.margin_of_safety
            FROM stocks s
            JOIN now_row n ON n.ticker = s.ticker
            LEFT JOIN wk_row w ON w.ticker = s.ticker
            LEFT JOIN dp ON dp.ticker = s.ticker
            WHERE n.margin_of_safety IS NOT NULL
              AND n.margin_of_safety > 0
              AND n.fundamental_score > 0
            ORDER BY delta DESC NULLS LAST, n.fundamental_score DESC
            LIMIT :lim
            """
        )
        result = sess.execute(q, {"tickers": tickers, "lim": MOVERS_MAX_ROWS}).fetchall()
        for r in result:
            t = r[0]
            delta = float(r[4]) if r[4] is not None else 0.0
            note = ""
            if delta > 0:
                note = f"+{delta:.0f} score WoW"
            elif delta < 0:
                note = f"{delta:.0f} score WoW"
            mos_pct = float(r[5]) if r[5] is not None else None
            rows.append(
                DigestRow(
                    ticker=t.replace(".NS", "").replace(".BO", ""),
                    company_name=r[1] or t,
                    price=float(r[2]) if r[2] is not None else None,
                    fv_label=_fv_label_from_mos(mos_pct),
                    score=int(r[3]) if r[3] is not None else None,
                    note=note,
                )
            )
    except Exception as exc:
        logger.warning("weekly_digest_service: movers fetch failed: %s", exc)
    finally:
        try:
            sess.close()
        except Exception:
            pass
    return rows


# ───────────────────────────────────────────────────────────────
# Rendering
# ───────────────────────────────────────────────────────────────

def _render_row_html(row: DigestRow, idx: int, last: bool) -> str:
    border = "" if last else "border-bottom:1px solid #E2E8F0;"
    price_str = f"Rs {row.price:,.2f}" if row.price is not None else "—"
    score_str = f"Score {row.score}" if row.score is not None else ""
    extra = f" &middot; {row.note}" if row.note else ""
    return f"""
        <tr>
          <td style="padding:14px 18px;{border}">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td width="32" valign="top">
                  <span style="display:inline-block;width:26px;height:26px;background-color:{HEADER_DARK};
                                color:#FFFFFF;font-size:12px;font-weight:700;line-height:26px;
                                text-align:center;border-radius:6px;">{idx}</span>
                </td>
                <td valign="top" style="padding-left:12px;">
                  <span style="font-size:15px;font-weight:700;color:#0F172A;">{row.ticker}</span>
                  <span style="color:#94A3B8;font-size:13px;">&nbsp;{row.company_name}</span>
                  <br>
                  <span style="font-size:13px;color:#475569;">{price_str}</span>
                  <span style="color:#CBD5E1;">&nbsp;&middot;&nbsp;</span>
                  <span style="font-size:13px;color:#475569;">{row.fv_label}</span>
                  <span style="font-size:12px;color:#94A3B8;">{(' &middot; ' + score_str) if score_str else ''}{extra}</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>
    """


def _render_text(rows: list[DigestRow], heading: str, week_label: str,
                 cta_url: str, cta_label: str, footer_email: str) -> str:
    """Plain-text version. Some clients (and ML spam filters) prefer one."""
    lines = [
        "YieldIQ Weekly Digest",
        week_label,
        "",
        heading,
        "",
    ]
    if not rows:
        lines.append("No data this week. We'll be back next Thursday.")
    else:
        for i, r in enumerate(rows, start=1):
            price = f"Rs {r.price:,.2f}" if r.price is not None else "—"
            extras = []
            if r.score is not None:
                extras.append(f"Score {r.score}")
            if r.note:
                extras.append(r.note)
            tail = (" | " + " | ".join(extras)) if extras else ""
            lines.append(f"  {i}. {r.ticker} — {r.company_name}")
            lines.append(f"     {price} | {r.fv_label}{tail}")
    lines += [
        "",
        f"{cta_label}: {cta_url}",
        "",
        "Unsubscribe from weekly digests in your account settings:",
        f"{SITE_URL}/account",
        "",
        "SEBI Disclaimer: YieldIQ is not a SEBI-registered investment advisor. "
        "All data is for informational purposes only and does not constitute "
        "investment advice. Past performance does not guarantee future results.",
    ]
    return "\n".join(lines)


def _render_html(rows: list[DigestRow], heading: str, intro: str,
                 week_label: str, cta_url: str, cta_label: str,
                 email_for_footer: str) -> str:
    from backend.services.email_service import _email_footer  # local import: avoid cycle

    if rows:
        body_rows = "".join(
            _render_row_html(r, i + 1, i == len(rows) - 1)
            for i, r in enumerate(rows)
        )
    else:
        body_rows = """
            <tr><td style="padding:24px;text-align:center;color:#64748B;font-size:14px;">
              No data this week. We'll be back next Thursday.
            </td></tr>
        """

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0;padding:0;background-color:#F1F5F9;">
      <tr>
        <td align="center" style="padding:24px 16px;">
          <table width="600" cellpadding="0" cellspacing="0" border="0"
                 style="max-width:600px;width:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background-color:#FFFFFF;">
            <tr>
              <td style="background-color:{HEADER_DARK};padding:28px 32px 22px;text-align:center;">
                <span style="color:#FFFFFF;font-size:18px;font-weight:700;letter-spacing:4px;text-transform:uppercase;">YIELDIQ WEEKLY</span>
                <div style="color:#94A3B8;font-size:12px;margin-top:6px;">{week_label}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:28px 32px 0;">
                <h1 style="margin:0 0 6px;font-size:20px;font-weight:700;color:#0F172A;">{heading}</h1>
                <p style="margin:0 0 18px;font-size:14px;color:#64748B;line-height:1.6;">{intro}</p>
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;">
                  {body_rows}
                </table>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:24px 32px 8px;">
                <table cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td align="center" style="background-color:{BRAND_PRIMARY};border-radius:8px;">
                      <a href="{cta_url}" style="display:inline-block;padding:12px 30px;color:#FFFFFF;
                              font-size:14px;font-weight:600;text-decoration:none;">{cta_label} &rarr;</a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr><td>{_email_footer(email_for_footer)}</td></tr>
          </table>
        </td>
      </tr>
    </table>
    """


# ───────────────────────────────────────────────────────────────
# Public entry point
# ───────────────────────────────────────────────────────────────

def generate_digest(user_email: str) -> Digest:
    """Build a personalized digest for one user. Never raises."""
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).strftime("%b %d")
    week_end = now.strftime("%b %d, %Y")
    week_label = f"{week_start} – {week_end}"

    client = _supabase_client()
    tickers = _get_user_watchlist(client, user_email)

    if tickers:
        rows = _fetch_watchlist_rows(tickers)
        heading = "Your watchlist this week"
        intro = (
            "Latest closing prices and Fair-Value status for the stocks "
            "you are tracking. Labels are descriptive, not recommendations."
        )
        cta_url = f"{SITE_URL}/account"
        cta_label = "Open your watchlist"
        subject = f"Your watchlist update — {week_end}"
    else:
        rows = _fetch_movers_rows()
        heading = "Stocks moving this week"
        intro = (
            "From the YieldIQ-50 quality universe, ranked by week-over-week "
            "fundamental score change. Add any of these to your watchlist "
            "to get them in next week's digest."
        )
        cta_url = f"{SITE_URL}/discover"
        cta_label = "Explore YieldIQ-50"
        subject = f"Stocks moving this week — {week_end}"

    html = _render_html(rows, heading, intro, week_label, cta_url, cta_label, user_email)
    text = _render_text(rows, heading, week_label, cta_url, cta_label, user_email)
    return Digest(subject=subject, html=html, text=text)
