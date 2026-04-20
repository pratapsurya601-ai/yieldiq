"""BSE Peercomp via Playwright — real-browser fallback after the API
started returning 302→error_Bse.html for programmatic clients in
April 2026.

Strategy
--------
1. Launch headless Chromium with stealth patches (navigator.webdriver,
   chrome runtime, plugins, languages etc.) so Akamai's bot-detection
   can't fingerprint us.
2. Visit https://www.bseindia.com/ to let the Akamai JS challenge solve
   itself and drop valid ``_abck`` / ``bm_sz`` cookies.
3. Re-use the authenticated browser context's request API to hit the
   Peercomp JSON endpoint. Since cookies carry over, the endpoint now
   returns JSON instead of the 302.
4. Parse JSON identically to the original ``bse_xbrl.fetch_historical_financials``.

This module is a drop-in replacement for that function — same return
shape, same downstream ``store_financials`` call site.

Dependencies
------------
    pip install playwright playwright-stealth
    playwright install chromium --with-deps

~200MB Chromium install. Runs fine on GH Actions ``ubuntu-latest``
once you add the ``playwright install`` step to the workflow.

Per-ticker budget: ~3-4s (4 Peercomp endpoints × 0.5-0.8s each, plus
parse). 2,500 tickers single-threaded ≈ 2-2.5 hours. Parallelizable
via matrix sharding.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from data_pipeline.sources.bse_xbrl import (  # reuse existing helpers
    _HIST_ENDPOINTS,
    _parse_cr,
    _parse_float,
    _detect_currency,
    parse_bse_period,
)

logger = logging.getLogger(__name__)


BSE_PEERCOMP_URL_TMPL = (
    "https://api.bseindia.com/BseIndiaAPI/api/Peercomp/w"
    "?scripcode={scrip}&type={stype}&annuallyquarterly={freq}"
)

# URLs to warm cookies + pass Akamai JS challenge
WARMUP_URLS = [
    "https://www.bseindia.com/",
    "https://www.bseindia.com/stock-share-price/reliance-industries-ltd/reliance/500325/",
]


class BSEBrowserClient:
    """Playwright-backed session reusable across many tickers.

    Call ``await init()`` once, then ``await fetch(scrip_code, ticker)``
    for each stock, then ``await close()``.
    """

    def __init__(self, headless: bool = True, slow_mo: int = 0):
        self.headless = headless
        self.slow_mo = slow_mo
        self._pw = None
        self._browser = None
        self._context = None

    async def init(self) -> None:
        from playwright.async_api import async_playwright
        try:
            from playwright_stealth import Stealth  # type: ignore
            _has_stealth = True
        except ImportError:
            _has_stealth = False

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless, slow_mo=self.slow_mo,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
        )

        page = await self._context.new_page()
        if _has_stealth:
            try:
                # playwright-stealth v2+: apply via context or page
                await Stealth().apply_stealth_async(page)
            except Exception:
                pass

        # Warm Akamai cookies by visiting main BSE pages
        for url in WARMUP_URLS:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1500)  # let JS challenge finish
            except Exception as exc:
                logger.info("warmup visit failed (%s): %s", url, exc)
        await page.close()
        logger.info("BSE browser client ready — cookies warmed")

    async def _get_json(self, url: str, retries: int = 2):
        """Hit the JSON endpoint through the browser's request context.
        Returns dict/list or None on failure."""
        import json as _json
        for attempt in range(retries + 1):
            try:
                response = await self._context.request.get(
                    url,
                    headers={
                        "Origin": "https://www.bseindia.com",
                        "Referer": "https://www.bseindia.com/stock-share-price/reliance-industries-ltd/reliance/500325/",
                        "Accept": "application/json, text/plain, */*",
                    },
                    timeout=20000,
                )
                if response.status != 200:
                    logger.debug("HTTP %d on %s", response.status, url)
                    await asyncio.sleep(1.0)
                    continue
                body = await response.text()
                # BSE returns either plain JSON or a JSON wrapped in extra
                # whitespace. Guard against HTML shells (Akamai challenge
                # survived until first GET).
                body_strip = body.strip()
                if not body_strip or body_strip.startswith("<"):
                    logger.debug("non-JSON body on %s (%d bytes)", url, len(body_strip))
                    await asyncio.sleep(1.0)
                    continue
                return _json.loads(body_strip)
            except Exception as exc:
                logger.info("fetch failed (attempt %d) %s: %s", attempt + 1, url, exc)
                await asyncio.sleep(1.5)
        return None

    async def fetch(self, scrip_code: str, ticker: str) -> list[dict[str, Any]]:
        """Fetch 10Y annual + quarterly financials for one ticker.
        Same return shape as bse_xbrl.fetch_historical_financials."""
        raw_data: dict[str, list[dict]] = {}
        for stmt_type, freq, label in _HIST_ENDPOINTS:
            url = BSE_PEERCOMP_URL_TMPL.format(
                scrip=scrip_code, stype=stmt_type, freq=freq,
            )
            payload = await self._get_json(url)
            rows: list[dict] = []
            if isinstance(payload, dict):
                rows = payload.get("Table") or []
            elif isinstance(payload, list):
                rows = payload
            raw_data[label] = rows
            await asyncio.sleep(0.3)  # polite pacing

        return _merge_rows(raw_data, ticker)

    async def close(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()


def _merge_rows(raw_data: dict[str, list[dict]], ticker: str) -> list[dict[str, Any]]:
    """Identical merge logic to the original bse_xbrl.fetch_historical_financials."""
    bs_by_period: dict[date, dict] = {}
    for row in raw_data.get("bs_annual", []):
        period_str = row.get("Year") or row.get("Period") or row.get("year")
        pd_date = parse_bse_period(period_str)
        if pd_date:
            bs_by_period[pd_date] = row

    cf_by_period: dict[date, dict] = {}
    for row in raw_data.get("cf_annual", []):
        period_str = row.get("Year") or row.get("Period") or row.get("year")
        pd_date = parse_bse_period(period_str)
        if pd_date:
            cf_by_period[pd_date] = row

    results: list[dict[str, Any]] = []

    for row in raw_data.get("pl_annual", []):
        period_str = row.get("Year") or row.get("Period") or row.get("year")
        period_end = parse_bse_period(period_str)
        if not period_end:
            continue
        revenue = (_parse_cr(row.get("NetSales")) or _parse_cr(row.get("TotalRevenue"))
                   or _parse_cr(row.get("GrossSales")) or _parse_cr(row.get("Net Sales")))
        pat = (_parse_cr(row.get("PAT")) or _parse_cr(row.get("NetProfit"))
               or _parse_cr(row.get("Net Profit")))
        ebitda = (_parse_cr(row.get("EBITDA")) or _parse_cr(row.get("OperatingProfit"))
                  or _parse_cr(row.get("Operating Profit")))
        eps = (_parse_float(row.get("EPS")) or _parse_float(row.get("DilutedEPS"))
               or _parse_float(row.get("Diluted EPS")) or _parse_float(row.get("BasicEPS")))

        bs = bs_by_period.get(period_end, {})
        total_debt = (_parse_cr(bs.get("TotalDebt")) or _parse_cr(bs.get("Borrowings"))
                      or _parse_cr(bs.get("Total Debt")))
        total_equity = (_parse_cr(bs.get("ShareholdersFunds")) or _parse_cr(bs.get("TotalEquity"))
                        or _parse_cr(bs.get("NetWorth")))
        cash = (_parse_cr(bs.get("CashAndBankBalances")) or _parse_cr(bs.get("Cash")))

        cf = cf_by_period.get(period_end, {})
        cfo = (_parse_cr(cf.get("CashFromOperations")) or _parse_cr(cf.get("OperatingActivities"))
               or _parse_cr(cf.get("CFO")))
        capex = (_parse_cr(cf.get("CapitalExpenditure")) or _parse_cr(cf.get("Capex"))
                 or _parse_cr(cf.get("PurchaseOfFixedAssets")))

        results.append({
            "ticker": ticker, "period_end": period_end, "period_type": "annual",
            "revenue": revenue, "pat": pat, "ebitda": ebitda,
            "cfo": cfo, "capex": capex,
            "total_debt": total_debt, "total_equity": total_equity, "cash": cash,
            "eps_diluted": eps, "source": "BSE_PEERCOMP_BROWSER",
        })

    for row in raw_data.get("pl_quarterly", []):
        period_str = row.get("Year") or row.get("Period") or row.get("year")
        period_end = parse_bse_period(period_str)
        if not period_end:
            continue
        revenue = (_parse_cr(row.get("NetSales")) or _parse_cr(row.get("TotalRevenue")))
        pat = (_parse_cr(row.get("PAT")) or _parse_cr(row.get("NetProfit")))
        ebitda = _parse_cr(row.get("EBITDA")) or _parse_cr(row.get("OperatingProfit"))
        eps = _parse_float(row.get("EPS")) or _parse_float(row.get("DilutedEPS"))
        results.append({
            "ticker": ticker, "period_end": period_end, "period_type": "quarterly",
            "revenue": revenue, "pat": pat, "ebitda": ebitda,
            "cfo": None, "capex": None,
            "total_debt": None, "total_equity": None, "cash": None,
            "eps_diluted": eps, "source": "BSE_PEERCOMP_BROWSER",
        })

    return results
