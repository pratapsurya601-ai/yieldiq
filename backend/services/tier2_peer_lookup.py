"""Tier-2 peer lookup helper — bridges DIRECT_PEERS (curated sector
membership) with tier2_peer_metrics (enriched per-ticker data) and
market_metrics (live P/E + P/B + market cap).

Why this exists
───────────────
The DCF-collapse safety net (PR #377) used to call
peer_cap_service.fetch_peer_records_for_ticker(ticker) to build the
peer cohort for Tier 2 fallback. That function returns empty for
several sectors (cement, retail, mid-cap industrials) because the
peer-cap mechanism it was built for has different requirements.
Empty peer list → Tier 2 returns None → safety net fails → broken
DCF FV (INDIACEM ₹0.77 etc.) shipped as `data_limited`.

This helper offers a SECOND source of truth: read the curated peer
list from DIRECT_PEERS for the ticker's sector, then enrich each
peer with the metrics needed by compute_tier2_fair_value. The two
sources can coexist — caller tries peer_cap first, falls through
here when the result is empty / insufficient.

Returns the same PeerRecord shape compute_tier2_fair_value expects:

  {
    "ticker":        str,
    "pe":            Optional[float],   # trailing P/E
    "ev_ebitda":     Optional[float],   # EV / EBITDA TTM
    "roce":          Optional[float],   # percent (27.0 for 27%)
    "piotroski":     Optional[int],     # 0-9 F-score
    "market_cap_cr": Optional[float],   # market cap in crore
  }

The function is conservative — returns [] when the lookup fails for
any reason. Caller treats [] as "no peers available, fall through to
data_limited" exactly like the peer_cap_service path.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("yieldiq.tier2_peer_lookup")


def _norm_sector(s: Optional[str]) -> str:
    return (s or "").strip().lower()


# Map common sector strings to DIRECT_PEERS keys. The DIRECT_PEERS dict
# uses snake_case sector keys (cement, banking, nbfc, ...); incoming
# sector strings from the analysis pipeline are PascalCase / mixed
# ("Cement", "IT Services", "Auto - 4W", etc.). This mapping bridges
# the two without modifying DIRECT_PEERS.
_SECTOR_KEY_MAP: dict[str, str] = {
    # Direct matches to DIRECT_PEERS keys
    "cement": "cement",
    "it services": "it_services",
    "information technology": "it_services",
    "it - software": "it_services",
    "fmcg": "fmcg",
    "consumer staples": "fmcg",
    "pharma": "pharma",
    "pharmaceuticals": "pharma",
    "capital goods": "capital_goods_full",   # Day-6: expanded 11-peer bucket
    "industrials": "capital_goods_full",
    "auto - 4w": "auto_oem",
    "auto - 2w": "auto_oem",
    "auto - oem": "auto_oem",
    "auto oem": "auto_oem",
    "automobile": "auto_oem",
    "oil & gas": "oil_gas",
    "oil gas": "oil_gas",
    "energy": "oil_gas",
    "metals & mining": "metals",
    "metals/mining": "metals",   # slash form (prod label)
    "metals": "metals",
    "steel": "metals",
    "telecom": "telecom",
    "banking": "banking",
    "banks": "banking",
    "nbfc": "nbfc",
    "defence": "defence",
    "defense": "defence",
    "infra": "infra",
    "infrastructure": "infra",
    "chemicals": "chemicals",
    "healthcare": "healthcare",
    "retail": "retail",
    "power": "power",
    "utilities": "power",
    # 2026-05-19 expansion — additional prod sector strings observed
    # in analysis_cache.payload->company->sector. Each mapping anchors
    # to the closest DIRECT_PEERS cohort whose business model best
    # approximates the target's economics.
    "power/utilities": "power",                  # slash form
    "infrastructure/construction": "infra",      # slash form
    "auto components": "auto_oem",
    "auto - components": "auto_oem",
    "auto ancillary": "auto_oem",
    "automotive ancillary": "auto_oem",
    "tyres": "auto_oem",
    "tires": "auto_oem",
    "airlines": "infra",                         # capex-heavy, infra-adjacent
    "logistics": "infra",
    "shipping": "infra",
    "tech hardware/electronics": "capital_goods",  # Indian electronics OEMs
    "tech hardware": "capital_goods",
    "consumer durables": "capital_goods",        # appliances, electronics
    "hospitals": "healthcare",
    "diagnostics": "healthcare",
    # 2026-05-20 (Day-17): hotel + hospitality sector strings. ITCHOTELS
    # was surfacing as sector="Hotels" or "Hospitality" with no peer
    # cohort -> falling through to plain DCF. The economics align with
    # the retail cohort (consumer-facing brand premium, store/property
    # expansion economics, similar EBITDA-margin profile).
    "hospitality": "retail",
    "hotel chains": "retail",
    "hotel": "retail",
    "hotels": "retail",
    "lodging": "retail",
    "real estate": "infra",                      # closest until realty bucket added
    "renewable energy": "power",
    "solar": "power",
    "renewables": "power",
    "engineering & construction": "infra",
    "engineering": "capital_goods",
    "textiles": "retail",
    "apparel": "retail",
    "specialty chemicals": "chemicals",
    "fertilizers": "chemicals",
    "agriculture": "fmcg",                       # food-adjacent
    "media & entertainment": "telecom",          # broadcast / content
    "media": "telecom",

    # Internet platform mappings (2026-05-19 Day-3, with the
    # new DIRECT_PEERS buckets). yfinance returns various labels
    # for Indian platforms — none of which match traditional
    # sector engines. Route them to the new cohort.
    "internet": "internet_platform",
    "internet platform": "internet_platform",
    "e-commerce": "internet_platform",
    "ecommerce": "internet_platform",
    "internet retail": "internet_platform",
    "internet content & information": "internet_platform",
    "online services": "internet_platform",

    # Fintech / online broker mappings
    "fintech": "fintech_broker",
    "online broker": "fintech_broker",
    "capital markets": "fintech_broker",
    "asset management": "fintech_broker",
    "depository": "fintech_broker",
    "exchanges": "fintech_broker",
    "stock exchanges": "fintech_broker",
}


def _resolve_sector_key(sector: Optional[str]) -> Optional[str]:
    """Return the DIRECT_PEERS key for a free-form sector string, or
    None if no mapping. Accepts case-insensitive, optional whitespace."""
    return _SECTOR_KEY_MAP.get(_norm_sector(sector))


def fetch_peers_from_metrics_table(
    ticker: str,
    sector: Optional[str],
    session=None,
) -> list[dict]:
    """Build the peer cohort for ``ticker`` by reading DIRECT_PEERS for
    its sector then enriching each peer from tier2_peer_metrics +
    market_metrics. Excludes ``ticker`` itself from the returned list.

    Returns ``[]`` on any lookup failure — caller treats empty as
    "no peers, fall through to data_limited".
    """
    if not ticker:
        return []

    sector_key = _resolve_sector_key(sector)
    if not sector_key:
        logger.debug(
            "tier2_peer_lookup: no sector→DIRECT_PEERS mapping for %r "
            "(ticker=%s); returning []",
            sector, ticker,
        )
        return []

    try:
        from screener.sector_relative import DIRECT_PEERS
    except Exception as exc:  # noqa: BLE001
        logger.warning("tier2_peer_lookup: DIRECT_PEERS import failed: %s", exc)
        return []

    peers_in_sector: list[str] = list(DIRECT_PEERS.get(sector_key) or [])
    if not peers_in_sector:
        return []

    # Strip the target itself + normalise suffix for set membership.
    def _bare(t: str) -> str:
        return (t or "").replace(".NS", "").replace(".BO", "").upper()

    target_bare = _bare(ticker)
    peers_in_sector = [p for p in peers_in_sector if _bare(p) != target_bare]
    if not peers_in_sector:
        return []

    # Lazy session import. Same pattern as benchmark_reconciliation.
    sess = session
    if sess is None:
        try:
            from backend.services.analysis_cache_service import (
                _get_session as _s,
            )
            sess = _s()
        except Exception as exc:  # noqa: BLE001
            logger.warning("tier2_peer_lookup: no DB session: %s", exc)
            return []
    if sess is None:
        return []

    try:
        from sqlalchemy import text

        # We accept BOTH bare-ticker (TCS) and suffix (TCS.NS) writes
        # on either source; normalise both sides in SQL.
        peer_params = {f"p{i}": p for i, p in enumerate(peers_in_sector)}
        peer_in_clause = ", ".join(f":{k}" for k in peer_params.keys())
        sql = f"""
            WITH wanted AS (
              SELECT UPPER(REPLACE(REPLACE(unnest(ARRAY[{peer_in_clause}]),
                                          '.NS', ''), '.BO', '')) AS bare
            ),
            tpm AS (
              SELECT UPPER(REPLACE(REPLACE(ticker, '.NS', ''), '.BO', ''))
                     AS bare,
                     roce_pct, piotroski, market_cap_cr
              FROM tier2_peer_metrics
            ),
            mm AS (
              SELECT DISTINCT ON (bare)
                     UPPER(REPLACE(REPLACE(ticker, '.NS', ''), '.BO', ''))
                     AS bare,
                     pe_ratio, ev_ebitda
              FROM market_metrics
              WHERE pe_ratio IS NOT NULL OR ev_ebitda IS NOT NULL
              ORDER BY bare, trade_date DESC
            )
            SELECT
              w.bare           AS ticker,
              mm.pe_ratio      AS pe,
              mm.ev_ebitda     AS ev_ebitda,
              tpm.roce_pct     AS roce,
              tpm.piotroski    AS piotroski,
              tpm.market_cap_cr AS market_cap_cr
            FROM wanted w
            LEFT JOIN tpm ON w.bare = tpm.bare
            LEFT JOIN mm  ON w.bare = mm.bare
        """
        rows = sess.execute(text(sql), peer_params).mappings().all()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "tier2_peer_lookup: DB query failed for sector=%s: %s",
            sector_key, exc,
        )
        return []
    finally:
        if session is None:
            try:
                sess.close()
            except Exception:
                pass

    out: list[dict] = []
    for r in rows:
        rec = {
            "ticker":        r.get("ticker"),
            "pe":            _f(r.get("pe")),
            "ev_ebitda":     _f(r.get("ev_ebitda")),
            "roce":          _f(r.get("roce")),
            "piotroski":     _i(r.get("piotroski")),
            "market_cap_cr": _f(r.get("market_cap_cr")),
        }
        # Drop peers with NO usable multiple — they'd fail Tier 2's
        # sanity gate anyway and just dilute the cohort.
        if rec["pe"] is None and rec["ev_ebitda"] is None:
            continue
        out.append(rec)

    logger.info(
        "tier2_peer_lookup: built %d-peer cohort for %s (sector=%s, "
        "sector_key=%s, requested=%d)",
        len(out), ticker, sector, sector_key, len(peers_in_sector),
    )
    return out


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _i(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


__all__ = ["fetch_peers_from_metrics_table"]
