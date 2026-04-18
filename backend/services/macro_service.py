# backend/services/macro_service.py
"""
Macro snapshot service — FII/DII flows, FX, commodities,
risk-free rate, and an AI-generated market commentary.

All sub-fetches run in parallel with a 15-second cap and degrade
gracefully: any individual failure yields ``None`` for that field
instead of blocking the whole snapshot.

Caching is done through the shared ``CacheService`` singleton:
- ``macro:snapshot`` lives for 4 hours
- ``macro:ai_summary`` lives for 24 hours
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
from datetime import datetime

log = logging.getLogger("yieldiq.macro")


class MacroService:
    """See module docstring."""

    SNAPSHOT_TTL = 4 * 3600
    SUMMARY_TTL = 24 * 3600

    # ── Public API ─────────────────────────────────────────────

    def get_snapshot(self, cache, db_session) -> dict:
        cached = cache.get("macro:snapshot") if cache else None
        if cached is not None:
            return cached

        snap = self._build_snapshot(db_session, cache=cache)
        if cache is not None:
            cache.set("macro:snapshot", snap, ttl=self.SNAPSHOT_TTL)
        return snap

    def get_ai_summary(self, snapshot: dict, cache) -> str | None:
        cached = cache.get("macro:ai_summary") if cache else None
        if cached is not None:
            return cached

        summary = self._generate_summary(snapshot)
        if summary and cache is not None:
            cache.set("macro:ai_summary", summary, ttl=self.SUMMARY_TTL)
        return summary

    # ── Snapshot composition ───────────────────────────────────

    def _build_snapshot(self, db_session, cache=None) -> dict:
        fetchers = {
            "fii_dii":     self._fetch_fii_dii,
            "fx":          self._fetch_fx,
            "commodities": self._fetch_commodities,
            "midcap":      self._fetch_midcap,
            "risk_free":   lambda: self._fetch_risk_free(db_session),
        }
        results: dict = {}

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(fetchers)
        ) as ex:
            futures = {ex.submit(fn): key for key, fn in fetchers.items()}
            try:
                for fut in concurrent.futures.as_completed(futures, timeout=15):
                    key = futures[fut]
                    try:
                        results[key] = fut.result()
                    except Exception as exc:
                        log.debug("macro fetch %s failed: %s", key, exc)
                        results[key] = None
            except concurrent.futures.TimeoutError:
                log.debug("macro overall fetch timed out")

        # ── FII/DII with last-known-good fallback ────────────────
        # If today's fetch succeeded, cache it (7-day TTL) so a
        # future NSE outage still shows yesterday's data instead
        # of "—". If today's fetch failed, pull from that cache.
        fii_dii = results.get("fii_dii") or {}
        fii_stale = False
        if cache is not None:
            if fii_dii.get("fii_net") is not None or fii_dii.get("dii_net") is not None:
                # Fresh data: refresh the last-known-good cache.
                cache.set("macro:fii_dii_last", fii_dii, ttl=7 * 86400)
            else:
                # Live fetch empty — fall back to last-known-good.
                last = cache.get("macro:fii_dii_last")
                if last:
                    fii_dii = last
                    fii_stale = True

        fx = results.get("fx") or {}
        comms = results.get("commodities") or {}
        midcap = results.get("midcap") or {}
        rf = results.get("risk_free")

        return {
            "fii_net_cr":              fii_dii.get("fii_net"),
            "dii_net_cr":              fii_dii.get("dii_net"),
            "fii_date":                fii_dii.get("date"),
            "fii_stale":               fii_stale,
            "usd_inr":                 fx.get("usd_inr"),
            "gold_usd":                comms.get("gold_usd"),
            "silver_usd":              comms.get("silver_usd"),
            "crude_usd":               None,  # Deprecated — replaced by silver
            "risk_free_pct":           rf,
            "nifty_midcap_price":      midcap.get("price"),
            "nifty_midcap_change_pct": midcap.get("change_pct"),
            "last_updated":            datetime.utcnow().isoformat(),
        }

    # ── Individual fetchers ────────────────────────────────────

    def _fetch_fii_dii(self) -> dict:
        """NSE FII/DII flows. Raises on any transport/parse error."""
        try:
            from curl_cffi import requests as cffi
        except ImportError:
            raise RuntimeError("curl_cffi not installed")

        session = cffi.Session(impersonate="chrome")
        # Warm up NSE cookies
        session.get("https://www.nseindia.com", timeout=15)
        resp = session.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"NSE FII status {resp.status_code}")

        data = resp.json()
        out: dict = {}
        for item in data or []:
            cat = (item.get("category") or "").upper().strip()
            try:
                net = float(item.get("netValue", 0) or 0)
            except (TypeError, ValueError):
                net = 0.0
            # NSE returns the category as "FII/FPI" (with slash),
            # not plain "FII" — match on prefix so both forms work.
            if cat.startswith("FII"):
                out["fii_net"] = round(net, 1)
                out["date"] = item.get("date")
            elif cat.startswith("DII"):
                out["dii_net"] = round(net, 1)
                if "date" not in out:
                    out["date"] = item.get("date")
        return out

    def _fetch_fx(self) -> dict:
        """USD/INR — DB first (fx_rates.USDINR), yfinance as fallback."""
        from backend.services import market_data_service as _mds
        row = _mds.get_fx_rate_row("USDINR")
        price = float(row["rate"]) if (row and row.get("rate")) else 0.0
        if price:
            # change_pct is not persisted — best effort via previous row skipped.
            return {
                "usd_inr": round(price, 2),
                "usd_inr_change_pct": None,
            }
        log.warning("_fetch_fx: DB miss on USDINR, falling back to yfinance")
        import yfinance as yf
        fi = yf.Ticker("USDINR=X").fast_info
        price = float(getattr(fi, "last_price", 0) or 0)
        prev = float(getattr(fi, "previous_close", 0) or 0)
        chg = round((price - prev) / prev * 100, 2) if prev else None
        return {
            "usd_inr": round(price, 2) if price else None,
            "usd_inr_change_pct": chg,
        }

    def _fetch_commodities(self) -> dict:
        """Gold + Silver (DB-first, yfinance fallback)."""
        from backend.services import market_data_service as _mds
        out: dict = {}
        for sym, key in (("GC=F", "gold_usd"), ("SI=F", "silver_usd")):
            snap = _mds.get_index_snapshot(sym)
            if snap and snap.get("price"):
                out[key] = round(float(snap["price"]), 2)
                continue
            log.warning("_fetch_commodities: DB miss on %s, falling back to yfinance", sym)
            try:
                import yfinance as yf
                fi = yf.Ticker(sym).fast_info
                price = float(getattr(fi, "last_price", 0) or 0)
                out[key] = round(price, 2) if price else None
            except Exception:
                out[key] = None
        return out

    def _fetch_midcap(self) -> dict:
        """Nifty Midcap (DB-first, yfinance fallback)."""
        from backend.services import market_data_service as _mds
        snap = _mds.get_index_snapshot("^NSEMDCP50")
        if snap and snap.get("price"):
            return {
                "price": round(float(snap["price"]), 2),
                "change_pct": round(float(snap.get("change_pct") or 0), 2)
                               if snap.get("change_pct") is not None else None,
            }
        log.warning("_fetch_midcap: DB miss on ^NSEMDCP50, falling back to yfinance")
        import yfinance as yf
        try:
            fi = yf.Ticker("^NSEMDCP50").fast_info
            price = float(getattr(fi, "last_price", 0) or 0)
            prev = float(getattr(fi, "previous_close", 0) or 0)
            chg = round((price - prev) / prev * 100, 2) if prev else None
            if not price:
                fi = yf.Ticker("^NSMIDCP150").fast_info
                price = float(getattr(fi, "last_price", 0) or 0)
                prev = float(getattr(fi, "previous_close", 0) or 0)
                chg = round((price - prev) / prev * 100, 2) if prev else None
            return {
                "price": round(price, 2) if price else None,
                "change_pct": chg,
            }
        except Exception:
            return {}

    def _fetch_risk_free(self, db_session) -> float | None:
        """Latest 10Y G-Sec yield from the risk_free_rates table."""
        if db_session is None:
            return None
        try:
            from data_pipeline.models import RiskFreeRate
            row = (
                db_session.query(RiskFreeRate)
                .order_by(RiskFreeRate.trade_date.desc())
                .first()
            )
            if row and row.gsec_10yr_yield is not None:
                return round(float(row.gsec_10yr_yield), 2)
        except Exception as exc:
            log.debug("risk_free fetch: %s", exc)
        return None

    # ── AI summary ─────────────────────────────────────────────

    def _generate_summary(self, snapshot: dict) -> str | None:
        """
        2-sentence market commentary. Mirrors the Gemini→Groq
        fallback pattern used by ``dashboard.utils.data_helpers
        .generate_ai_summary`` but with a macro-specific prompt.
        Returns ``None`` if no LLM key is configured or both
        providers error — the UI then hides the summary strip.
        """
        bullets: list[str] = []
        fii = snapshot.get("fii_net_cr")
        dii = snapshot.get("dii_net_cr")
        if fii is not None:
            bullets.append(
                f"FII net {'bought' if fii > 0 else 'sold'} "
                f"₹{abs(fii):,.0f} Cr."
            )
        if dii is not None:
            bullets.append(
                f"DII net {'bought' if dii > 0 else 'sold'} "
                f"₹{abs(dii):,.0f} Cr."
            )
        if snapshot.get("usd_inr"):
            bullets.append(f"USD/INR ₹{snapshot['usd_inr']:.2f}.")
        if snapshot.get("gold_usd"):
            bullets.append(f"Gold ${snapshot['gold_usd']:,.0f}/oz.")
        if snapshot.get("silver_usd"):
            bullets.append(f"Silver ${snapshot['silver_usd']:.1f}/oz.")

        context = " ".join(bullets)
        if not context:
            return None

        prompt = (
            "You are a concise Indian market commentator. Based on the "
            "data below, write EXACTLY 2 sentences of market commentary "
            "for Indian retail investors. Be direct and factual. "
            "Do NOT give investment advice. Do NOT use 'buy' or 'sell'.\n\n"
            f"Data: {context}\n\n"
            "Output: 2 sentences, under 60 words total, no headers, no bullets."
        )

        # Gemini removed 18-Apr-2026 after repeated "API key expired"
        # errors from the google-genai SDK. Groq (llama-3.3-70b) handled
        # the fallback cleanly throughout, so we're making it primary.
        # Keeping GEMINI_API_KEY env var readable so rollback is a one-
        # commit revert rather than also needing env changes.
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()

        if groq_key:
            try:
                from groq import Groq as _Groq
                client = _Groq(api_key=groq_key)
                resp = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=120,
                    temperature=0.3,
                )
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    return text
            except Exception as exc:
                log.debug("Groq macro summary failed: %s", exc)

        return None
