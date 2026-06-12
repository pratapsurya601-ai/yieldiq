"""BSE quarterly XBRL ingest via Playwright (real-Chrome channel).

Purpose
-------
For the ~96 BSE-only Group A+B legit tickers (SpiceJet, TANFAC, JYOTIRES,
SEKURITIND, ...) NSE does not serve quarterly XBRL because the company
is single-listed on BSE. We therefore have to source the same
``in-bse-fin:`` schema XBRL directly from the BSE corporate filings
page::

    https://www.bseindia.com/corporates/Comp_Resultsnew.aspx?Code=<bse_code>

The XBRL link pattern observed on that page (confirmed during the
investigation for feat/bse-only-xbrl-ingest, May 2026) is::

    /XBRLFILES/FourOneUploadDocument/Main_Ind_As_<code>_<ts>.xml

and the namespace inside the XML is
``xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2020-03-31/in-bse-fin"``
— IDENTICAL to NSE-served XBRL, so the existing parser in
``data_pipeline.sources.nse_quarterly_xbrl.parse_quarter_xml`` consumes
these files directly with no schema branching.

Why Playwright + real Chrome channel
------------------------------------
BSE protects every host (www. + api.) behind Akamai Bot Manager. We
verified all four of the following return 403 / 302→error_Bse for
plain HTTP clients (curl_cffi, requests, even Playwright's bundled
headless Chromium):

    * GET https://www.bseindia.com/
    * GET https://www.bseindia.com/corporates/Comp_Resultsnew.aspx?Code=...
    * GET https://api.bseindia.com/BseIndiaAPI/api/AnnFinancialResultData/w?...
    * GET https://api.bseindia.com/BseIndiaAPI/api/Peercomp/w?...

What works in practice (verified for SpiceJet/500285):

    1. Launch Chromium with ``channel="chrome"`` — uses the locally
       installed real Chrome binary, which Akamai treats as a regular
       human visitor rather than a headless browser.
    2. ``headless=False`` — Akamai's _abck sensor checks for
       ``HeadlessChrome`` substring in the UA and several other
       headless signals. Headed is required.
    3. Warm cookies by visiting the homepage + two stock pages BEFORE
       hitting the filings page. Without warmup the filings page also
       returns 403.

Per-ticker budget: ~10-15s (3 warmup pages × 2.5s + filings page +
parse + 1-N XBRL downloads). 96 tickers serially ≈ 20-25 min.

The ``api.bseindia.com`` endpoint stays blocked even after warmup —
it returns 302→error_Bse with full _abck cookies attached. Don't try
to call it from this module; scrape the XBRL XML URLs out of the
filings page HTML instead.

Dependencies
------------
    pip install playwright playwright-stealth
    playwright install chromium                  # bundled fallback
    # AND: a real Google Chrome installation on the host
    # (Playwright's `channel="chrome"` invokes the system Chrome)

For headless CI: this module will NOT work as-is in GH Actions
``ubuntu-latest`` headless. The headless fallback is left in for
debugging, but the production assumption is local execution on a
workstation with real Chrome (the user runs ingest once, then writes
to Neon).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


BSE_FILINGS_URL_TMPL = (
    "https://www.bseindia.com/corporates/Comp_Resultsnew.aspx?Code={code}"
)
BSE_HOST = "https://www.bseindia.com"

# 2026 migration: the Comp_Resultsnew page is now an Angular SPA whose served
# HTML contains ZERO filing links. The result table is populated by an XHR to
# the api.bseindia.com Corp_FinanceResult_ng endpoint. We call that endpoint
# directly from the warmed browser context (cookies established by the SPA
# page load make it return 200 in-browser).
#
#   GET https://api.bseindia.com/BseIndiaAPI/api/Corp_FinanceResult_ng/w
#       ?SCRIP_CD=<code>&FlagDur=7&HFQ=&ISUBGROUP_CODE=
#
# Response: {"Table":[{ "Scrip_cd":500180, "quarter_code":"MQ2025-2026",
#   "Fld_NatureOfReport":"Standalone",
#   "XMLName":"IFBankingDuplicateUploadDocument/IFBanking_500180_<ts>_IFBanking.html",
#   "Consol_XMLName":"...IFBanking_500180_<ts>_IFBanking.html", ...}, ...]}
#
# ``XMLName`` is the STANDALONE filing (bank NPA fields are standalone-only);
# ``Consol_XMLName`` is the consolidated one. Each is a relative path served
# under /XBRLFILES/ on www.bseindia.com. FlagDur=7 (or empty) returns the full
# multi-year history (~140 rows for HDFCBANK); FlagDur=1 returns nothing.
BSE_FINRESULT_API_TMPL = (
    "https://api.bseindia.com/BseIndiaAPI/api/Corp_FinanceResult_ng/w"
    "?SCRIP_CD={code}&FlagDur={flagdur}&HFQ=&ISUBGROUP_CODE="
)
# FlagDur value that returns the widest history. 7 was confirmed in the
# network capture; empty string ("") returns the same full set.
BSE_FINRESULT_FLAGDUR = "7"

# Absolute-URL prefix for the relative ``XMLName`` path. Confirmed via the
# SPA's own rendered anchors: href="/XBRLFILES/<XMLName>" returns the real
# 2.6 MB inline-XBRL document (status 200). Other prefixes either 404 or
# soft-404 to the Angular shell.
BSE_XBRLFILES_PREFIX = "https://www.bseindia.com/XBRLFILES/"

# Three warmup hops let the Akamai _abck cookie transition to a
# verified state. Removing any of these reverts to 403.
WARMUP_URLS = [
    "https://www.bseindia.com/",
    "https://www.bseindia.com/stock-share-price/reliance-industries-ltd/reliance/500325/",
    "https://www.bseindia.com/markets/equity/EQReports/marketmovers.aspx",
]

# LEGACY: pre-2026 BSE served quarterly Ind-AS XBRL as standalone XML files
# linked directly in the page HTML, e.g.
#   /XBRLFILES/FourOneUploadDocument/Main_Ind_As_500285_2622025161521.xml
# That page is now an Angular SPA with no links, so this regex no longer
# matches anything against live HTML. It is retained only for the
# ``_legacy_list_from_html`` fallback path and for tests that exercise the
# old fixtures.
_XBRL_HREF_RE = re.compile(
    r"""href=['"](/XBRLFILES/[^'"]*?Main_Ind_As_(\d+)_[^'"]+\.xml)['"]""",
    re.IGNORECASE,
)


class BSEXBRLBrowserClient:
    """Playwright-backed session for scraping BSE quarterly XBRL.

    Usage::

        async with BSEXBRLBrowserClient() as cli:
            urls = await cli.list_quarterly_xbrl_urls("500285")
            for u in urls:
                xml_bytes = await cli.download(u)
                ...

    The context manager handles browser lifecycle. Cookie warmup
    happens once per ``__aenter__`` and is reused for every ticker
    in the same session.
    """

    def __init__(self, headless: bool = False, slow_mo: int = 0):
        # Default headless=False: Akamai blocks headless Chromium even
        # with the standard stealth patches. The flag is exposed only
        # so callers can opt into headless mode for non-Akamai testing.
        self.headless = headless
        self.slow_mo = slow_mo
        self._pw = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "BSEXBRLBrowserClient":
        await self.init()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def init(self) -> None:
        from playwright.async_api import async_playwright
        try:
            from playwright_stealth import Stealth  # type: ignore
            _has_stealth = True
        except ImportError:
            _has_stealth = False

        self._pw = await async_playwright().start()

        launch_kwargs: dict[str, Any] = dict(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        # Prefer real Chrome channel (Akamai treats it as a human).
        try:
            self._browser = await self._pw.chromium.launch(
                channel="chrome", **launch_kwargs,
            )
            logger.info("BSE XBRL client: launched real Chrome channel")
        except Exception as exc:
            logger.warning(
                "real-Chrome launch failed (%s); falling back to bundled chromium "
                "— Akamai may still block",
                exc,
            )
            self._browser = await self._pw.chromium.launch(**launch_kwargs)

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
                await Stealth().apply_stealth_async(page)
            except Exception:
                pass

        for url in WARMUP_URLS:
            try:
                resp = await page.goto(
                    url, wait_until="domcontentloaded", timeout=30000,
                )
                logger.debug(
                    "warmup %s -> %s",
                    url, resp.status if resp else "no-resp",
                )
                await page.wait_for_timeout(2500)
            except Exception as exc:
                logger.info("warmup visit failed (%s): %s", url, exc)
        await page.close()
        logger.info("BSE XBRL client ready — Akamai cookies warmed")

    async def list_quarterly_xbrl_urls(
        self, bse_code: str, *, max_filings: int | None = None,
    ) -> list[str]:
        """Return absolute URLs of quarterly result filings for ``bse_code``.

        2026 migration: the Comp_Resultsnew page is now an Angular SPA whose
        served HTML has zero filing links — the result table is fetched by an
        XHR to ``api.bseindia.com/.../Corp_FinanceResult_ng``. We replicate
        that XHR from the warmed browser context (navigating the SPA page
        first establishes the api.bseindia.com cookie so the call returns 200
        in-browser), parse the JSON ``Table``, and build one absolute
        ``/XBRLFILES/<XMLName>`` URL per filing.

        ``XMLName`` is the STANDALONE filing (bank NPA fields are
        standalone-only) and is returned first for each quarter;
        ``Consol_XMLName`` is appended as a fallback only when it differs.
        Order is newest-first (the API returns rows newest-first); duplicate
        URLs across the MQ/MC/DQ quarter-code variants are collapsed. Pass
        ``max_filings`` to cap the count.

        Returns [] on any nav / API failure (logged at INFO) so the caller's
        pre-flight gate trips cleanly.
        """
        if self._context is None:
            raise RuntimeError("client not initialised — call init() first")

        rows: list[dict[str, Any]] = []
        page = await self._context.new_page()

        # Primary path: intercept the SPA's OWN Corp_FinanceResult_ng XHR
        # response. This is far more reliable than replaying the request via
        # ``context.request.get`` -- Akamai's _abck sensor frequently rejects
        # the programmatic replay (returns an empty body / soft-error) even
        # while the in-page XHR succeeds, because the replay is missing the
        # browser-context fetch metadata Akamai fingerprints on.
        captured: dict[str, Any] = {"table": None}

        async def _on_response(resp: Any) -> None:
            if captured["table"] is not None:
                return
            if "Corp_FinanceResult_ng" not in resp.url:
                return
            try:
                data = await resp.json()
                table = data.get("Table") if isinstance(data, dict) else None
                if table:
                    captured["table"] = table
            except Exception:
                pass

        listener = lambda resp: asyncio.create_task(_on_response(resp))  # noqa: E731
        self._context.on("response", listener)
        try:
            target = BSE_FILINGS_URL_TMPL.format(code=bse_code)
            try:
                await page.goto(
                    target, wait_until="domcontentloaded", timeout=45000,
                )
            except Exception as exc:
                logger.info("SPA filings nav fail %s: %s", bse_code, exc)
            # Wait for the SPA to fire its finance-result XHR.
            for _ in range(20):
                if captured["table"] is not None:
                    break
                await page.wait_for_timeout(1500)

            if captured["table"]:
                rows = captured["table"]
            else:
                # Fallback: replicate the XHR ourselves (cookie may now be warm
                # from the SPA's attempt). Short retry loop with SPA reloads.
                api_url = BSE_FINRESULT_API_TMPL.format(
                    code=bse_code, flagdur=BSE_FINRESULT_FLAGDUR,
                )
                for attempt in range(4):
                    try:
                        r = await self._context.request.get(
                            api_url,
                            headers={"Accept": "application/json"},
                            timeout=60000,
                        )
                        raw = await r.body()
                        data = json.loads(raw.decode("utf-8", "replace"))
                        table = (
                            data.get("Table") if isinstance(data, dict) else None
                        )
                        if table:
                            rows = table
                            break
                    except Exception as exc:
                        logger.debug(
                            "finresult api replay attempt %d fail %s: %s",
                            attempt, bse_code, exc,
                        )
                    await page.wait_for_timeout(2500)
                    try:
                        await page.reload(
                            wait_until="domcontentloaded", timeout=30000,
                        )
                    except Exception:
                        pass
        finally:
            try:
                self._context.remove_listener("response", listener)
            except Exception:
                pass
            await page.close()

        if not rows:
            logger.info(
                "finresult api returned no rows for %s (SPA/Akamai)", bse_code,
            )
            return []

        # Step 3: build /XBRLFILES/<XMLName> URLs, standalone first, deduped,
        # newest-first (API order preserved).
        urls: list[str] = []
        seen: set[str] = set()

        def _add(xmlname: str | None) -> None:
            if not xmlname or not isinstance(xmlname, str):
                return
            rel = xmlname.strip().lstrip("/")
            if not rel:
                return
            absolute = BSE_XBRLFILES_PREFIX + rel
            if absolute in seen:
                return
            seen.add(absolute)
            urls.append(absolute)

        # Standalone pass first (preferred -- carries NPA fields), then
        # consolidated as fallback for any quarter without a distinct
        # standalone file.
        for row in rows:
            _add(row.get("XMLName"))
        for row in rows:
            _add(row.get("Consol_XMLName"))

        if max_filings is not None:
            urls = urls[:max_filings]
        return urls

    async def download(self, xbrl_url: str) -> bytes:
        """Download one BSE filing. Returns raw bytes (may be empty on fail).

        Works for both the legacy ``Main_Ind_As_*.xml`` instances and the
        2026 ``IFBanking_*_IFBanking.html`` inline-XBRL documents — both are
        served under ``/XBRLFILES/`` on the same www.bseindia.com host as the
        filings page, so the Akamai cookies established during ``init()``
        warmup are valid for the download too. The IFBanking HTML files run to
        ~2.6 MB, so the read timeout is generous.
        """
        if self._context is None:
            raise RuntimeError("client not initialised — call init() first")
        try:
            r = await self._context.request.get(
                xbrl_url,
                headers={
                    "Referer": "https://www.bseindia.com/corporates/Comp_Resultsnew.aspx",
                    "Accept": "*/*",
                },
                timeout=60000,
            )
        except Exception as exc:
            logger.info("xbrl download error %s: %s", xbrl_url, exc)
            return b""
        if r.status != 200:
            logger.info("xbrl download non-200 %s: %s", xbrl_url, r.status)
            return b""
        try:
            return await r.body()
        except Exception as exc:
            logger.info("xbrl body read error %s: %s", xbrl_url, exc)
            return b""

    async def close(self) -> None:
        try:
            if self._context:
                await self._context.close()
        finally:
            try:
                if self._browser:
                    await self._browser.close()
            finally:
                if self._pw:
                    await self._pw.stop()


# ───────────────────────────────────────────────────────────────────────
# Convenience: fetch + parse for one (bse_code, ticker) pair
# ───────────────────────────────────────────────────────────────────────

async def fetch_and_parse_async(
    bse_code: str,
    ticker: str,
    *,
    client: BSEXBRLBrowserClient | None = None,
    max_filings: int = 22,
    sleep_between: float = 0.4,
) -> list[dict[str, Any]]:
    """Async variant: list + download + parse all quarterly XBRL for one ticker.

    If ``client`` is provided, reuses it (caller manages lifecycle —
    much faster across many tickers). Otherwise spins up a one-shot
    client for this single ticker.
    """
    from data_pipeline.sources.nse_quarterly_xbrl import parse_quarter_xml
    from data_pipeline.sources.nse_xbrl_fundamentals import (
        _extract_contexts,  # noqa: F401  (kept for symmetry / future use)
    )

    owns_client = client is None
    if owns_client:
        client = BSEXBRLBrowserClient()
        await client.init()

    rows: list[dict[str, Any]] = []
    try:
        urls = await client.list_quarterly_xbrl_urls(
            bse_code, max_filings=max_filings,
        )
        logger.info("%s (BSE %s): %d XBRL filings", ticker, bse_code, len(urls))
        for url in urls:
            xml_bytes = await client.download(url)
            if not xml_bytes or len(xml_bytes) < 500:
                continue
            # period_end lives inside the XML; let the parser figure it out.
            period_end = _peek_period_end(xml_bytes)
            if period_end is None:
                continue
            try:
                row = parse_quarter_xml(
                    xml_bytes, ticker, period_end, url, filed_at=None,
                )
            except Exception as exc:
                logger.info(
                    "%s parse fail %s: %s", ticker, url, exc,
                )
                continue
            if row:
                row["segment"] = "equities"
                row["report_period_type"] = "Quarterly"
                row["source"] = "bse"
                rows.append(row)
            await asyncio.sleep(sleep_between)
    finally:
        if owns_client:
            await client.close()
    return rows


def fetch_and_parse(
    bse_code: str,
    ticker: str,
    *,
    max_filings: int = 22,
    sleep_between: float = 0.4,
) -> list[dict[str, Any]]:
    """Sync wrapper for one-off use (scripts, tests).

    For multi-ticker runs prefer using ``BSEXBRLBrowserClient`` directly
    with ``fetch_and_parse_async`` so one browser session amortises across
    many tickers.
    """
    return asyncio.run(
        fetch_and_parse_async(
            bse_code, ticker,
            max_filings=max_filings, sleep_between=sleep_between,
        ),
    )


def _peek_period_end(xml_bytes: bytes):
    """Best-effort: pull the OneD context's endDate from XBRL XML.

    The OneD context is the quarter-duration context (start..end ~90 days)
    and corresponds to the headline reporting period_end. If absent
    (occasionally seen for legacy filings) we fall back to the largest
    endDate present in any context — that one is almost always the
    reporting period_end too.
    """
    from datetime import datetime

    try:
        from lxml import etree
    except ImportError:
        from xml.etree import ElementTree as etree  # type: ignore

    try:
        root = etree.fromstring(xml_bytes)
    except Exception:
        return None

    # Look for context id="OneD" first
    ns = {"xbrli": "http://www.xbrl.org/2003/instance"}
    candidates: list = []
    for ctx in root.iter():
        tag = ctx.tag
        if not isinstance(tag, str) or not tag.endswith("}context"):
            continue
        cid = ctx.get("id", "")
        end_el = None
        for child in ctx.iter():
            ctag = child.tag
            if isinstance(ctag, str) and ctag.endswith("}endDate"):
                end_el = child
                break
        if end_el is None or not (end_el.text or "").strip():
            continue
        try:
            d = datetime.strptime(end_el.text.strip(), "%Y-%m-%d").date()
        except Exception:
            continue
        if cid == "OneD":
            return d
        candidates.append(d)
    if candidates:
        return max(candidates)
    return None
