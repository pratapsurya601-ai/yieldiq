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

        snap = self._build_snapshot(db_session)
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

    def _build_snapshot(self, db_session) -> dict:
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

        fii_dii = results.get("fii_dii") or {}
        fx = results.get("fx") or {}
        comms = results.get("commodities") or {}
        midcap = results.get("midcap") or {}
        rf = results.get("risk_free")

        return {
            "fii_net_cr":              fii_dii.get("fii_net"),
            "dii_net_cr":              fii_dii.get("dii_net"),
            "fii_date":                fii_dii.get("date"),
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
            cat = (item.get("category") or "").upper()
            try:
                net = float(item.get("netValue", 0) or 0)
            except (TypeError, ValueError):
                net = 0.0
            if cat == "FII":
                out["fii_net"] = round(net, 1)
                out["date"] = item.get("date")
            elif cat == "DII":
                out["dii_net"] = round(net, 1)
                if "date" not in out:
                    out["date"] = item.get("date")
        return out

    def _fetch_fx(self) -> dict:
        """USD/INR via yfinance fast_info."""
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
        """Gold + Silver in USD (per oz)."""
        import yfinance as yf
        out: dict = {}
        for sym, key in (("GC=F", "gold_usd"), ("SI=F", "silver_usd")):
            try:
                fi = yf.Ticker(sym).fast_info
                price = float(getattr(fi, "last_price", 0) or 0)
                out[key] = round(price, 2) if price else None
            except Exception:
                out[key] = None
        return out

    def _fetch_midcap(self) -> dict:
        """Nifty Midcap 150 index."""
        import yfinance as yf
        try:
            fi = yf.Ticker("^NSEMDCP50").fast_info
            price = float(getattr(fi, "last_price", 0) or 0)
            prev = float(getattr(fi, "previous_close", 0) or 0)
            chg = round((price - prev) / prev * 100, 2) if prev else None
            if not price:
                # Fallback symbol
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
        if snapshot.get("risk_free_pct"):
            bullets.append(
                f"10Y G-Sec yield {snapshot['risk_free_pct']:.2f}%."
            )

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

        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()

        if gemini_key:
            try:
                from google import genai as _genai
                client = _genai.Client(api_key=gemini_key)
                resp = client.models.generate_content(
                    model="gemini-2.0-flash", contents=prompt,
                )
                text = (resp.text or "").strip()
                if text:
                    return text
            except Exception as exc:
                err = str(exc).lower()
                if not any(k in err for k in ("quota", "429", "resource_exhausted", "limit")):
                    log.debug("Gemini macro summary failed: %s", exc)
                # fall through to Groq

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
