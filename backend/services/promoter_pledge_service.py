"""promoter_pledge_service.py — promoter share-pledge tracking.

Indian governance signal: when a promoter group pledges shares as
collateral for personal/group loans, it's a leading indicator of
distress. Sharp jumps in pledged_pct historically precede price
collapses (RCOM, Zee, Future Retail, Anil Ambani group, etc.).

Data sources
------------
BSE — https://www.bseindia.com/corporates/sastpledge.aspx
    HTML page; filtered by scrip code (we already store
    ``stocks.bse_code``). One disclosure per row, dated. Uses the
    cookie-priming + Mozilla UA pattern proven in
    ``bse_shareholding_service.py`` / ``sebi_sast_service.py``.

NSE — https://www.nseindia.com/api/corporates-pledgedata?index=equities
    JSON API behind a cookie-gated front page. Prime the session by
    visiting ``https://www.nseindia.com/`` and the filings landing
    page first, then re-use the cookie jar for the API call. NSE
    returns ALL recent disclosures across symbols in one payload —
    batch, don't loop.

Schema lives in ``data_pipeline/migrations/016_promoter_pledges.sql``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("yieldiq.governance.pledge")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


# ── Constants ─────────────────────────────────────────────────

PLEDGE_JUMP_THRESHOLD_PP = 5.0  # SEBI material-disclosure threshold

_BSE_PLEDGE_URL = "https://www.bseindia.com/corporates/sastpledge.aspx"
_BSE_HOME = "https://www.bseindia.com/"

_NSE_PLEDGE_API = (
    "https://www.nseindia.com/api/corporates-pledgedata?index=equities"
)
_NSE_HOME = "https://www.nseindia.com/"
_NSE_PLEDGE_LANDING = (
    "https://www.nseindia.com/companies-listing/corporate-filings-pledged-data"
)

_HEADERS_BSE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Connection": "keep-alive",
}

_HEADERS_NSE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _NSE_PLEDGE_LANDING,
    "Connection": "keep-alive",
}


# ── Data class ────────────────────────────────────────────────


@dataclass(frozen=True)
class PledgeRow:
    """One snapshot of promoter pledge state for a single ticker."""

    ticker: str
    as_of_date: date
    promoter_group_pct: Optional[float]
    pledged_pct: Optional[float]
    pledged_shares: Optional[int]
    source_url: Optional[str]

    def to_dict(self) -> dict:
        d = asdict(self)
        # Serialize date for JSON / DB-driver friendliness.
        d["as_of_date"] = self.as_of_date.isoformat() if isinstance(
            self.as_of_date, date
        ) else self.as_of_date
        return d


# ── DB helpers ────────────────────────────────────────────────


def _get_raw_cursor():
    """Return (conn, cursor) from the shared pipeline engine, or (None, None)."""
    try:
        from data_pipeline.db import engine
    except Exception as exc:  # pragma: no cover
        logger.warning("promoter_pledge_service: pipeline engine import failed: %s", exc)
        return None, None
    if engine is None:
        return None, None
    conn = engine.raw_connection()
    cur = conn.cursor()
    return conn, cur


def _row_to_pledge(row: tuple) -> PledgeRow:
    ticker, as_of, prom_pct, pl_pct, pl_shares, source_url = row
    return PledgeRow(
        ticker=ticker,
        as_of_date=as_of,
        promoter_group_pct=float(prom_pct) if prom_pct is not None else None,
        pledged_pct=float(pl_pct) if pl_pct is not None else None,
        pledged_shares=int(pl_shares) if pl_shares is not None else None,
        source_url=source_url,
    )


# ── Public read API ───────────────────────────────────────────


def get_latest_pledge(ticker: str) -> Optional[PledgeRow]:
    """Return the most recent pledge snapshot for ``ticker``, or None."""
    conn, cur = _get_raw_cursor()
    if cur is None:
        return None
    try:
        cur.execute(
            """
            SELECT ticker, as_of_date, promoter_group_pct,
                   pledged_pct, pledged_shares, source_url
              FROM promoter_pledges
             WHERE ticker = %s
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            (ticker,),
        )
        row = cur.fetchone()
        return _row_to_pledge(row) if row else None
    finally:
        cur.close()
        conn.close()


def get_pledge_history(ticker: str, months: int = 24) -> List[PledgeRow]:
    """Return pledge snapshots for ``ticker`` over the last ``months`` months,
    oldest first (suitable for sparkline)."""
    conn, cur = _get_raw_cursor()
    if cur is None:
        return []
    try:
        cutoff = date.today() - timedelta(days=int(months) * 31)
        cur.execute(
            """
            SELECT ticker, as_of_date, promoter_group_pct,
                   pledged_pct, pledged_shares, source_url
              FROM promoter_pledges
             WHERE ticker = %s
               AND as_of_date >= %s
             ORDER BY as_of_date ASC
            """,
            (ticker, cutoff),
        )
        return [_row_to_pledge(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def compute_pledge_change_pp(
    ticker: str, lookback_days: int = 90
) -> Optional[float]:
    """Return percentage-point change in pledged_pct vs ``lookback_days`` ago.

    A positive value means the promoter group has *increased* pledging
    over the window — that's the bad direction.
    """
    conn, cur = _get_raw_cursor()
    if cur is None:
        return None
    try:
        cur.execute(
            """
            SELECT as_of_date, pledged_pct
              FROM promoter_pledges
             WHERE ticker = %s
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            (ticker,),
        )
        latest = cur.fetchone()
        if not latest or latest[1] is None:
            return None
        latest_date, latest_pct = latest

        cutoff = latest_date - timedelta(days=lookback_days)
        cur.execute(
            """
            SELECT as_of_date, pledged_pct
              FROM promoter_pledges
             WHERE ticker = %s
               AND as_of_date <= %s
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            (ticker, cutoff),
        )
        prior = cur.fetchone()
        if not prior or prior[1] is None:
            return None
        return float(latest_pct) - float(prior[1])
    finally:
        cur.close()
        conn.close()


# ── Parsing helpers ───────────────────────────────────────────


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _parse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _bse_code_for(ticker: str) -> Optional[str]:
    """Look up the BSE scrip code for a ticker via the ``stocks`` table."""
    conn, cur = _get_raw_cursor()
    if cur is None:
        return None
    try:
        cur.execute(
            "SELECT bse_code FROM stocks WHERE ticker = %s LIMIT 1",
            (ticker,),
        )
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0]).strip()
    except Exception as exc:
        logger.info("bse_code lookup failed for %s: %s", ticker, exc)
    finally:
        try:
            cur.close()
        finally:
            conn.close()
    return None


# ── Real scrapers ─────────────────────────────────────────────


def _parse_bse_pledge_html(html: str, ticker: str, source_url: str) -> List[PledgeRow]:
    """Parse the BSE sastpledge.aspx response into PledgeRow records.

    The page renders disclosures in a table. Column layout (typical):
        Filing Date | Promoter Name | Pledged Shares | % of Promoter |
        % of Total Capital | PDF link
    Tables on BSE pages are notoriously brittle — we extract by header
    name where possible, fall back to positional parsing.
    """
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:
        logger.warning("BeautifulSoup unavailable: %s", exc)
        return []

    soup = BeautifulSoup(html, "html.parser")
    rows: List[PledgeRow] = []

    # The disclosure table id varies; search broadly for any table whose
    # header row mentions both "pledge" and "%".
    for table in soup.find_all("table"):
        header_text = (table.find("tr").get_text(" ", strip=True).lower()
                       if table.find("tr") else "")
        if "pledge" not in header_text and "encumber" not in header_text:
            continue

        headers = [
            th.get_text(" ", strip=True).lower()
            for th in table.find("tr").find_all(["th", "td"])
        ]

        def _col(name_substr: str) -> Optional[int]:
            for i, h in enumerate(headers):
                if name_substr in h:
                    return i
            return None

        idx_date = _col("date")
        idx_pledged_shares = _col("pledged shares")
        if idx_pledged_shares is None:
            idx_pledged_shares = _col("encumbered")
        idx_pct_promoter = _col("% of promoter") or _col("% of holding")
        idx_pct_total = _col("% of total") or _col("% of paid")

        for tr in table.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            cells = [td.get_text(" ", strip=True) for td in tds]
            as_of = _parse_date(cells[idx_date]) if idx_date is not None else None
            if as_of is None:
                # Try first column as date heuristically.
                as_of = _parse_date(cells[0])
            if as_of is None:
                continue

            pledged_pct = (
                _to_float(cells[idx_pct_promoter])
                if idx_pct_promoter is not None and idx_pct_promoter < len(cells)
                else None
            )
            pledged_shares = (
                _to_int(cells[idx_pledged_shares])
                if idx_pledged_shares is not None and idx_pledged_shares < len(cells)
                else None
            )
            promoter_group_pct = (
                _to_float(cells[idx_pct_total])
                if idx_pct_total is not None and idx_pct_total < len(cells)
                else None
            )

            rows.append(PledgeRow(
                ticker=ticker,
                as_of_date=as_of,
                promoter_group_pct=promoter_group_pct,
                pledged_pct=pledged_pct,
                pledged_shares=pledged_shares,
                source_url=source_url,
            ))

    # De-duplicate by (ticker, as_of_date), keep first occurrence.
    seen: set = set()
    deduped: List[PledgeRow] = []
    for r in rows:
        key = (r.ticker, r.as_of_date)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def fetch_from_bse(ticker: str, *, _http_get=None) -> List[PledgeRow]:
    """Fetch pledge disclosures from BSE for a single ticker.

    Source: https://www.bseindia.com/corporates/sastpledge.aspx?scripcode={code}

    ``_http_get`` is a test seam: pass a callable ``(url, headers, timeout) -> (status, text)``
    to bypass the network. Returns [] on any error (never raises) so the
    cron loop can continue across tickers.
    """
    code = _bse_code_for(ticker)
    if not code:
        logger.info("BSE pledge: no bse_code for %s — skipping", ticker)
        return []

    url = f"{_BSE_PLEDGE_URL}?scripcode={code}"

    if _http_get is not None:
        try:
            status, text = _http_get(url, _HEADERS_BSE, 30)
        except Exception as exc:
            logger.info("BSE pledge test-seam failed for %s: %s", ticker, exc)
            return []
        if status != 200 or not text:
            return []
        return _parse_bse_pledge_html(text, ticker, url)

    try:
        import requests
    except Exception as exc:
        logger.warning("BSE pledge: requests unavailable: %s", exc)
        return []

    session = requests.Session()
    try:
        session.get(_BSE_HOME, headers=_HEADERS_BSE, timeout=15)
    except Exception as exc:
        logger.info("BSE pledge: cookie prime failed: %s", exc)

    for attempt in range(2):
        try:
            resp = session.get(url, headers=_HEADERS_BSE, timeout=30)
            if resp.status_code == 200 and resp.text:
                return _parse_bse_pledge_html(resp.text, ticker, url)
            if resp.status_code in (403, 429, 503) or 500 <= resp.status_code < 600:
                time.sleep(2.0 * (attempt + 1))
                continue
            logger.info("BSE pledge HTTP %s for %s", resp.status_code, ticker)
            return []
        except Exception as exc:
            logger.info("BSE pledge attempt %d failed for %s: %s", attempt + 1, ticker, exc)
            time.sleep(2.0 * (attempt + 1))
    return []


def _parse_nse_pledge_payload(payload: Any) -> Dict[str, List[PledgeRow]]:
    """Group NSE pledge disclosures by symbol → list[PledgeRow]."""
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("DATA") or payload.get("rows") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    by_sym: Dict[str, List[PledgeRow]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = (r.get("symbol") or r.get("SYMBOL") or "").strip().upper()
        if not sym:
            continue
        as_of = _parse_date(
            r.get("date")
            or r.get("dt")
            or r.get("disclosureDate")
            or r.get("creationDate")
            or r.get("filingDate")
        )
        if as_of is None:
            continue
        pledged_pct = _to_float(
            r.get("personPledgedHoldingPct")
            or r.get("pledgedPct")
            or r.get("perHolding")
            or r.get("pledgedSharesAsPercentTotalShareholding")
        )
        pledged_shares = _to_int(
            r.get("totalPledgedShares")
            or r.get("noOfShares")
            or r.get("pledgedShares")
        )
        promoter_group_pct = _to_float(
            r.get("promoterHoldingPct")
            or r.get("promoterTotalSharePct")
        )
        source_url = (
            r.get("attchmntFile")
            or r.get("attachmentUrl")
            or "https://www.nseindia.com/companies-listing/corporate-filings-pledged-data"
        )

        by_sym.setdefault(sym, []).append(PledgeRow(
            ticker=sym,
            as_of_date=as_of,
            promoter_group_pct=promoter_group_pct,
            pledged_pct=pledged_pct,
            pledged_shares=pledged_shares,
            source_url=source_url,
        ))
    return by_sym


def fetch_from_nse_bulk(*, _http_get=None) -> Dict[str, List[PledgeRow]]:
    """Single-call batch fetch of all recent NSE pledge disclosures.

    Returns ``{symbol_upper: [PledgeRow, ...]}``. NSE returns one large
    payload with all symbols in the recent window — fetch once, group,
    persist many.
    """
    if _http_get is not None:
        try:
            status, text = _http_get(_NSE_PLEDGE_API, _HEADERS_NSE, 30)
        except Exception as exc:
            logger.info("NSE pledge test-seam failed: %s", exc)
            return {}
        if status != 200 or not text:
            return {}
        import json as _json
        try:
            return _parse_nse_pledge_payload(_json.loads(text))
        except Exception as exc:
            logger.info("NSE pledge JSON parse failed: %s", exc)
            return {}

    try:
        import requests
    except Exception as exc:
        logger.warning("NSE pledge: requests unavailable: %s", exc)
        return {}

    session = requests.Session()
    try:
        session.get(_NSE_HOME, headers=_HEADERS_NSE, timeout=15)
        session.get(_NSE_PLEDGE_LANDING, headers=_HEADERS_NSE, timeout=15)
    except Exception as exc:
        logger.info("NSE pledge: cookie prime failed: %s", exc)

    for attempt in range(2):
        try:
            resp = session.get(_NSE_PLEDGE_API, headers=_HEADERS_NSE, timeout=30)
            if resp.status_code == 200:
                try:
                    return _parse_nse_pledge_payload(resp.json())
                except ValueError:
                    logger.info("NSE pledge: non-JSON body len=%d",
                                len(resp.content or b""))
                    return {}
            if resp.status_code in (403, 429, 503) or 500 <= resp.status_code < 600:
                time.sleep(2.0 * (attempt + 1))
                continue
            logger.info("NSE pledge HTTP %s", resp.status_code)
            return {}
        except Exception as exc:
            logger.info("NSE pledge attempt %d failed: %s", attempt + 1, exc)
            time.sleep(2.0 * (attempt + 1))
    return {}


def fetch_from_nse(ticker: str) -> List[PledgeRow]:
    """Convenience wrapper: pull NSE bulk payload, return rows for one ticker.

    The cron loop should prefer ``fetch_from_nse_bulk`` directly to avoid
    re-fetching the bulk payload N times. This wrapper exists for ad-hoc
    use and parity with ``fetch_from_bse``.
    """
    by_sym = fetch_from_nse_bulk()
    return by_sym.get(ticker.upper(), [])


# ── Alert pipeline ────────────────────────────────────────────


def detect_pledge_jumps(
    *, lookback_days: int = 90, threshold_pp: float = PLEDGE_JUMP_THRESHOLD_PP
) -> List[dict]:
    """For every watchlist ticker × user, queue an ``alert_fired`` notification
    when promoter pledge jumped > ``threshold_pp`` pp over ``lookback_days``.

    Returns a list of ``{user_id, ticker, change_pp, latest_pct, prior_pct,
    notification_id}`` summaries. Idempotency is provided by an existence
    check against the most recent matching ``alert_fired`` notification —
    we won't re-fire on the same change within 7 days.
    """
    summaries: List[dict] = []
    conn, cur = _get_raw_cursor()
    if cur is None:
        logger.info("detect_pledge_jumps: DB unavailable")
        return summaries
    try:
        # Distinct (user_id, ticker) pairs across all watchlists.
        try:
            cur.execute(
                "SELECT DISTINCT user_id, ticker FROM watchlist_items"
            )
            pairs = cur.fetchall()
        except Exception as exc:
            logger.info("detect_pledge_jumps: watchlist read failed: %s", exc)
            pairs = []
    finally:
        cur.close()
        conn.close()

    if not pairs:
        return summaries

    try:
        from backend.services.notifications_service import (
            create_notification,
            can_receive,
        )
    except Exception as exc:
        logger.warning("detect_pledge_jumps: notifications import failed: %s", exc)
        return summaries

    for user_id, ticker in pairs:
        try:
            change = compute_pledge_change_pp(ticker, lookback_days=lookback_days)
        except Exception as exc:
            logger.info("compute_pledge_change_pp failed for %s: %s", ticker, exc)
            continue
        if change is None or change <= threshold_pp:
            continue

        latest = get_latest_pledge(ticker)
        if not latest:
            continue
        prior_pct = (latest.pledged_pct or 0.0) - change

        # Idempotency: skip if we've already fired alert for this user/ticker
        # in the last 7 days at the same approximate magnitude.
        if _recently_fired(user_id, ticker, change):
            continue

        try:
            if not can_receive("free", "alert_fired"):
                # Should always be true for "alert_fired" but guard anyway.
                continue
        except Exception:
            pass

        title = f"Pledge alert: {ticker}"
        body = (
            f"Promoter pledge in {ticker} jumped "
            f"{prior_pct:.1f}% → {latest.pledged_pct:.1f}% "
            f"({latest.as_of_date.isoformat()})"
        )
        try:
            nid = create_notification(
                user_id=user_id,
                type="alert_fired",
                title=title,
                body=body,
                link=f"/analysis/{ticker}",
                metadata={
                    "kind": "promoter_pledge_jump",
                    "ticker": ticker,
                    "change_pp": round(float(change), 3),
                    "latest_pct": float(latest.pledged_pct),
                    "prior_pct": round(float(prior_pct), 3),
                    "as_of_date": latest.as_of_date.isoformat(),
                    "lookback_days": int(lookback_days),
                },
            )
        except Exception as exc:
            logger.warning("pledge alert insert failed for %s/%s: %s",
                           user_id, ticker, exc)
            continue

        summaries.append({
            "user_id": user_id,
            "ticker": ticker,
            "change_pp": round(float(change), 3),
            "latest_pct": float(latest.pledged_pct),
            "prior_pct": round(float(prior_pct), 3),
            "notification_id": nid,
        })
    logger.info("detect_pledge_jumps: queued %d alert(s)", len(summaries))
    return summaries


def _recently_fired(user_id: str, ticker: str, change_pp: float) -> bool:
    """Return True if a pledge-jump alert for this user+ticker was queued in
    the last 7 days. Cheap idempotency guard so re-running the cron after
    a rerun-on-failure doesn't double-notify users."""
    conn, cur = _get_raw_cursor()
    if cur is None:
        return False
    try:
        cur.execute(
            """
            SELECT 1 FROM notifications
             WHERE user_id = %s
               AND type = 'alert_fired'
               AND created_at > NOW() - INTERVAL '7 days'
               AND metadata->>'kind' = 'promoter_pledge_jump'
               AND metadata->>'ticker' = %s
             LIMIT 1
            """,
            (user_id, ticker),
        )
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        try:
            cur.close()
        finally:
            conn.close()
