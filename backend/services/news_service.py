# backend/services/news_service.py
# ═══════════════════════════════════════════════════════════════
# News & corporate filings — per-ticker and aggregated feed
#
# Sources:
#   1. yfinance Ticker.news — recent news articles per stock
#   2. BSE Corporate Announcements API — official filings (best-effort)
#   3. NSE Corporate Actions — splits, bonuses, dividends
#
# Importance scoring uses keywords to rank filings:
#   CRITICAL: results, qualified opinion, auditor change, fraud
#   HIGH:     dividend, split, bonus, board meeting
#   MEDIUM:   conference, investor presentation, press release
#   LOW:      everything else
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("yieldiq.news")


# ── Importance scoring ─────────────────────────────────────────

IMPORTANCE_KEYWORDS = {
    "critical": [
        r"\bresults?\b", r"\bquarterly\b", r"\bqualified opinion\b",
        r"\bauditor\b.*\b(change|resign)", r"\bfraud\b", r"\binvestigation\b",
        r"\bsebi\b.*\b(notice|action)", r"\bdelist\b", r"\binsolvency\b",
        r"\bnpa\b", r"\bdefault\b", r"\bratings? downgrade",
    ],
    "high": [
        r"\bdividend\b", r"\bbonus\b", r"\bsplit\b", r"\brights issue\b",
        r"\bbuyback\b", r"\bboard meeting\b", r"\bagm\b", r"\begm\b",
        r"\bacquisition\b", r"\bmerger\b", r"\bdemerger\b",
        r"\bopen offer\b", r"\bpreferential issue\b", r"\bqip\b",
        r"\bnew\s+plant\b", r"\bcapacity expansion\b",
    ],
    "medium": [
        r"\bconference\b", r"\binvestor (meet|presentation|conference)",
        r"\bpress release\b", r"\banalyst meet\b", r"\bcredit rating\b",
        r"\bappointment\b", r"\bresignation\b",
    ],
}


def score_importance(headline: str) -> str:
    """Return importance: critical, high, medium, or low."""
    if not headline:
        return "low"
    text = headline.lower()
    for level in ("critical", "high", "medium"):
        for pattern in IMPORTANCE_KEYWORDS[level]:
            if re.search(pattern, text):
                return level
    return "low"


def importance_color(level: str) -> str:
    return {
        "critical": "#DC2626",
        "high": "#F59E0B",
        "medium": "#3B82F6",
        "low": "#9CA3AF",
    }.get(level, "#9CA3AF")


# ── Source 1: yfinance news ────────────────────────────────────

def fetch_yfinance_news(ticker: str, limit: int = 15) -> list[dict]:
    """
    Fetch recent news articles for a ticker from yfinance.
    Returns normalized list of news dicts.
    """
    try:
        import yfinance as yf
        # Suppress yfinance log noise
        import logging as _yf_log
        _yf_log.getLogger("yfinance").setLevel(_yf_log.CRITICAL)

        if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
            ticker = f"{ticker}.NS"

        t = yf.Ticker(ticker)
        raw_news = t.news or []

        results = []
        for item in raw_news[:limit]:
            content = item.get("content") or item
            title = content.get("title") or item.get("title") or ""
            if not title:
                continue
            pub_date = (
                content.get("pubDate")
                or content.get("displayTime")
                or item.get("providerPublishTime")
            )
            # Normalize date to ISO string
            if isinstance(pub_date, (int, float)):
                try:
                    pub_date = datetime.fromtimestamp(int(pub_date), tz=timezone.utc).isoformat()
                except Exception:
                    pub_date = None

            url = (
                content.get("canonicalUrl", {}).get("url")
                if isinstance(content.get("canonicalUrl"), dict)
                else content.get("canonicalUrl")
            )
            if not url:
                url = content.get("clickThroughUrl", {}).get("url") if isinstance(content.get("clickThroughUrl"), dict) else None
            if not url:
                url = item.get("link", "")

            provider_obj = content.get("provider") or {}
            provider = provider_obj.get("displayName") if isinstance(provider_obj, dict) else (
                item.get("publisher") or "Yahoo Finance"
            )

            summary = content.get("summary") or content.get("description") or ""

            results.append({
                "headline": title,
                "summary": summary[:500] if summary else "",
                "source": provider or "Yahoo Finance",
                "url": url,
                "published_at": pub_date or "",
                "importance": score_importance(title),
                "importance_color": importance_color(score_importance(title)),
                "category": "news",
            })
        return results
    except Exception as e:
        logger.warning(f"fetch_yfinance_news failed for {ticker}: {e}")
        return []


# ── Source 2: BSE corporate announcements ──────────────────────

def fetch_bse_filings(ticker: Optional[str] = None, days: int = 14, limit: int = 30) -> list[dict]:
    """
    Fetch corporate announcements from BSE.

    If ticker provided, filters to that scrip. Otherwise returns
    all recent announcements (best effort).

    BSE API requires Chrome impersonation; uses curl_cffi.
    """
    try:
        from curl_cffi import requests
    except ImportError:
        return []

    # BSE date format: YYYYMMDD
    today = datetime.now(timezone.utc).date()
    from_date = (today - timedelta(days=days)).strftime("%Y%m%d")
    to_date = today.strftime("%Y%m%d")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bseindia.com/corporates/ann.html",
        "Accept": "application/json",
    }

    # Try to look up scrip code if ticker provided
    scrip_code = ""
    if ticker:
        scrip_code = _resolve_bse_scrip_code(ticker) or ""

    url = (
        f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
        f"?pageno=1&strCat=-1&strPrevDate={from_date}"
        f"&strScrip={scrip_code}&strSearch=P&strToDate={to_date}"
        f"&strType=C&subcategory=-1"
    )

    try:
        r = requests.get(url, headers=headers, impersonate="chrome", timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        rows = data.get("Table", []) or []
    except Exception as e:
        logger.warning(f"BSE fetch failed: {e}")
        return []

    results = []
    for row in rows[:limit]:
        headline = row.get("HEADLINE", "") or row.get("NEWSSUB", "") or ""
        if not headline:
            continue
        results.append({
            "headline": headline,
            "summary": row.get("MORE", "")[:500] if row.get("MORE") else "",
            "source": "BSE",
            "ticker": row.get("SCRIP_CD", ""),
            "company_name": row.get("SLONGNAME", ""),
            "url": _bse_attachment_url(row),
            "published_at": row.get("NEWS_DT", "") or row.get("DT_TM", ""),
            "category": row.get("CATEGORYNAME", "") or "filing",
            "importance": score_importance(headline),
            "importance_color": importance_color(score_importance(headline)),
        })
    return results


_BSE_SCRIP_MAP = {
    # Common ones — full lookup table loaded lazily if needed
    "RELIANCE": "500325", "TCS": "532540", "HDFCBANK": "500180",
    "INFY": "500209", "ITC": "500875", "SBIN": "500112",
    "ICICIBANK": "532174", "BAJFINANCE": "500034", "MARUTI": "532500",
    "TITAN": "500114", "WIPRO": "507685", "AXISBANK": "532215",
    "KOTAKBANK": "500247", "LT": "500510", "SUNPHARMA": "524715",
    "HCLTECH": "532281", "NESTLEIND": "500790", "ASIANPAINT": "500820",
    "ULTRACEMCO": "532538", "ADANIENT": "512599", "POWERGRID": "532898",
    "NTPC": "532555", "ONGC": "500312", "COALINDIA": "533278",
    "BHARTIARTL": "532454", "HINDUNILVR": "500696", "TATASTEEL": "500470",
    "BRITANNIA": "500825", "HEROMOTOCO": "500182", "BAJAJ-AUTO": "532977",
    "HINDZINC": "500188", "JINDALSTEL": "532286", "MANKIND": "543904",
    "VEDL": "500295", "RCF": "524230",
}


def _resolve_bse_scrip_code(ticker: str) -> Optional[str]:
    """Look up BSE numeric scrip code for a ticker symbol."""
    clean = ticker.replace(".NS", "").replace(".BO", "").upper()
    return _BSE_SCRIP_MAP.get(clean)


def _bse_attachment_url(row: dict) -> str:
    """Build BSE attachment URL from row (PDF link to filing)."""
    attach = row.get("ATTACHMENTNAME", "")
    if attach:
        return f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attach}"
    return ""


# ── Combined: fetch all news + filings for a ticker ────────────

def fetch_all_news_for_ticker(ticker: str, days: int = 14) -> list[dict]:
    """
    Combine yfinance news + BSE filings for a single ticker.
    Sorted by published_at descending. Deduplicated by URL.
    """
    yf = fetch_yfinance_news(ticker, limit=15)
    bse = fetch_bse_filings(ticker=ticker, days=days, limit=15)

    seen_urls = set()
    combined = []
    for item in (bse + yf):  # BSE first (more important)
        u = item.get("url", "")
        if u and u in seen_urls:
            continue
        if u:
            seen_urls.add(u)
        combined.append(item)

    # Sort by published_at descending (recent first)
    def _sort_key(it):
        d = it.get("published_at", "")
        return d if isinstance(d, str) else ""
    combined.sort(key=_sort_key, reverse=True)
    return combined


# ── AI summary of a filing/news headline ───────────────────────

def summarize_filings(items: list[dict], max_items: int = 5) -> Optional[str]:
    """
    Use AI to generate a 2-3 sentence summary of the most important
    filings/news. Returns None if AI unavailable.
    """
    if not items:
        return None
    top = sorted(
        items,
        key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.get("importance", "low"), 3),
    )[:max_items]
    bullet_list = "\n".join(
        f"- [{x.get('importance', 'low').upper()}] {x.get('headline', '')[:200]}"
        for x in top
    )

    prompt = (
        "Summarize the most important news for an Indian retail investor in 2-3 plain English sentences. "
        "Focus on what matters financially. Do NOT recommend buying or selling. Do not use bullet points.\n\n"
        f"Recent news:\n{bullet_list}\n\nSummary:"
    )

    # Try Gemini first, then Groq
    import os
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()

    if gemini_key:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            r = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
            )
            text = (r.text or "").strip()
            if text:
                return text[:600]
        except Exception as e:
            logger.warning(f"Gemini summary failed: {e}")

    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            comp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.3,
            )
            text = comp.choices[0].message.content.strip()
            if text:
                return text[:600]
        except Exception as e:
            logger.warning(f"Groq summary failed: {e}")

    return None
