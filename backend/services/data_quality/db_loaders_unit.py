"""DB loader for the unit_integrity validator (2026-06-13).

Kept in its own module (same convention as db_loaders_a2.py) so the
cross-field unit/currency loader is reviewable in isolation. Same rules
as the rest of the framework:

- optional ``conn_factory`` for tests; production opens psycopg2 from
  ``$DATABASE_URL`` and returns None when it's unset (orchestrator skip).
- the loader only fetches + classifies into the (pure) ``TickerAnomaly``
  dataclass; all threshold/severity *policy* lives in the validator
  module and ``checks.py``.
- parameterised queries throughout; the only interpolated tokens are
  literal column names from validator source code, never caller input.

Data model
----------
We work off the latest ANNUAL period per ticker:
- ``ratio_history`` (period_type='annual') gives the computed ratios
  already in unit-free form: asset_turnover, de_ratio, net_margin,
  market_cap_cr.
- ``financials`` (period_type='annual') gives the raw revenue,
  free_cash_flow and the per-row ``currency`` flag.
These are joined on ticker; ``stocks.canonical_sector`` supplies the
sector for sector-aware asset_turnover banding.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Optional

from .db_loaders import _open_connection, _scalar

logger = logging.getLogger("yieldiq.data_quality.db_loaders_unit")


def load_unit_integrity_sample(
    conn_factory: Optional[Callable[[], Any]] = None,
) -> Optional[Any]:
    from .validators.unit_integrity import (
        FCF_OVER_MCAP_FAIL,
        FCF_OVER_MCAP_WARN,
        KNOWN_GOOD_ASSET_TURNOVER,
        NET_MARGIN_BAND,
        REVENUE_OVER_MCAP_FAIL,
        REVENUE_OVER_MCAP_WARN,
        TickerAnomaly,
        UnitIntegritySample,
        classify_asset_turnover,
    )

    with _open_connection(conn_factory) as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            row_count = int(_scalar(cur, "SELECT COUNT(*) FROM ratio_history WHERE period_type='annual'") or 0)
            prior_row_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM ratio_history "
                "WHERE period_type='annual' AND period_end <= (CURRENT_DATE - INTERVAL '90 days')",
            ) or 0)
            last_update: Optional[datetime] = _scalar(
                cur, "SELECT MAX(computed_at) FROM ratio_history WHERE period_type='annual'",
            )

            # ── Latest-annual ratio_history per ticker, with sector. ──
            # One pass pulls everything the cross-field checks need.
            cur.execute(
                """
                WITH rh AS (
                    SELECT DISTINCT ON (ticker)
                           ticker, asset_turnover, de_ratio, net_margin, market_cap_cr
                      FROM ratio_history
                     WHERE period_type='annual'
                     ORDER BY ticker, period_end DESC
                ),
                fn AS (
                    SELECT DISTINCT ON (ticker)
                           ticker, revenue, free_cash_flow, currency
                      FROM financials
                     WHERE period_type='annual'
                     ORDER BY ticker, period_end DESC
                )
                SELECT rh.ticker,
                       s.canonical_sector,
                       rh.asset_turnover,
                       rh.de_ratio,
                       rh.net_margin,
                       rh.market_cap_cr,
                       fn.revenue,
                       fn.free_cash_flow,
                       fn.currency
                  FROM rh
                  LEFT JOIN fn ON fn.ticker = rh.ticker
                  LEFT JOIN stocks s ON s.ticker = rh.ticker
                """
            )
            rows = cur.fetchall()

            # Classify in Python (pure logic, mirrored by the tests).
            asset_turnover_anomalies: list[TickerAnomaly] = []
            net_margin_anomalies: list[TickerAnomaly] = []
            rev_mcap_anomalies: list[TickerAnomaly] = []
            fcf_mcap_anomalies: list[TickerAnomaly] = []

            asset_turnover_total = 0
            net_margin_total = 0
            rev_mcap_total = 0
            fcf_mcap_total = 0

            de_total = 0
            de_zero_count = 0
            de_zero_by_sector: dict[str, list[int]] = {}

            nm_warn = (NET_MARGIN_BAND[0], NET_MARGIN_BAND[1])
            nm_fail = (NET_MARGIN_BAND[2], NET_MARGIN_BAND[3])

            for (
                ticker, sector, asset_turnover, de_ratio, net_margin,
                market_cap_cr, revenue, free_cash_flow, currency,
            ) in rows:
                at = None if asset_turnover is None else float(asset_turnover)
                de = None if de_ratio is None else float(de_ratio)
                nm = None if net_margin is None else float(net_margin)
                mcap = None if market_cap_cr is None else float(market_cap_cr)
                rev = None if revenue is None else float(revenue)
                fcf = None if free_cash_flow is None else float(free_cash_flow)
                sec = sector or None

                # asset_turnover (sector-aware)
                if at is not None:
                    asset_turnover_total += 1
                    a = classify_asset_turnover(ticker, sec, at)
                    if a is not None:
                        asset_turnover_anomalies.append(a)

                # net_margin band
                if nm is not None:
                    net_margin_total += 1
                    if nm < nm_fail[0] or nm > nm_fail[1]:
                        net_margin_anomalies.append(
                            TickerAnomaly(ticker, "net_margin", nm, nm_fail, "fail", sec)
                        )
                    elif nm < nm_warn[0] or nm > nm_warn[1]:
                        net_margin_anomalies.append(
                            TickerAnomaly(ticker, "net_margin", nm, nm_warn, "warn", sec)
                        )

                # de_ratio == 0 cohort (INR-relevant; only count rows that
                # actually have a de_ratio value so the denominator is the
                # cohort that *could* be zero, not the whole universe).
                if de is not None:
                    de_total += 1
                    if de == 0.0:
                        de_zero_count += 1
                    bucket = de_zero_by_sector.setdefault(sec or "Unknown", [0, 0])
                    bucket[1] += 1
                    if de == 0.0:
                        bucket[0] += 1

                # revenue >> market cap (only meaningful for INR rows;
                # USD rows are caught by the currency check and would
                # false-positive here since revenue is in USD).
                if (
                    mcap is not None and mcap > 0
                    and rev is not None and rev > 0
                    and (currency is None or currency == "INR")
                ):
                    rev_mcap_total += 1
                    ratio = rev / mcap
                    if ratio >= REVENUE_OVER_MCAP_FAIL:
                        rev_mcap_anomalies.append(
                            TickerAnomaly(
                                ticker, "revenue/market_cap", ratio,
                                (0.0, REVENUE_OVER_MCAP_FAIL), "fail", sec,
                            )
                        )
                    elif ratio >= REVENUE_OVER_MCAP_WARN:
                        rev_mcap_anomalies.append(
                            TickerAnomaly(
                                ticker, "revenue/market_cap", ratio,
                                (0.0, REVENUE_OVER_MCAP_WARN), "warn", sec,
                            )
                        )

                # fcf >> market cap (DCF-overshoot signature)
                if (
                    mcap is not None and mcap > 0
                    and fcf is not None and fcf > 0
                    and (currency is None or currency == "INR")
                ):
                    fcf_mcap_total += 1
                    ratio = fcf / mcap
                    if ratio >= FCF_OVER_MCAP_FAIL:
                        fcf_mcap_anomalies.append(
                            TickerAnomaly(
                                ticker, "free_cash_flow/market_cap", ratio,
                                (0.0, FCF_OVER_MCAP_FAIL), "fail", sec,
                            )
                        )
                    elif ratio >= FCF_OVER_MCAP_WARN:
                        fcf_mcap_anomalies.append(
                            TickerAnomaly(
                                ticker, "free_cash_flow/market_cap", ratio,
                                (0.0, FCF_OVER_MCAP_WARN), "warn", sec,
                            )
                        )

            de_zero_by_sector_t = {
                k: (v[0], v[1]) for k, v in de_zero_by_sector.items()
            }

            # ── Currency double-convert guard. ──
            # Latest annual financials row per ticker; count non-INR.
            cur.execute(
                """
                WITH fn AS (
                    SELECT DISTINCT ON (ticker) ticker, currency
                      FROM financials
                     WHERE period_type='annual'
                     ORDER BY ticker, period_end DESC
                )
                SELECT ticker, currency FROM fn
                """
            )
            cur_rows = cur.fetchall()
            currency_total = len(cur_rows)
            non_inr = [t for (t, c) in cur_rows if c is not None and c != "INR"]
            non_inr_count = len(non_inr)

            # ── Known-good asset_turnover values. ──
            known_good_asset_turnover: dict[str, Optional[float]] = {}
            for ticker in KNOWN_GOOD_ASSET_TURNOVER:
                v = _scalar(
                    cur,
                    "SELECT asset_turnover FROM ratio_history "
                    "WHERE ticker = %s AND period_type='annual' "
                    "ORDER BY period_end DESC LIMIT 1",
                    (ticker,),
                )
                known_good_asset_turnover[ticker] = None if v is None else float(v)

        return UnitIntegritySample(
            row_count=row_count,
            prior_row_count=prior_row_count,
            last_update=last_update,
            asset_turnover_total=asset_turnover_total,
            asset_turnover_anomalies=asset_turnover_anomalies,
            de_total=de_total,
            de_zero_count=de_zero_count,
            de_zero_by_sector=de_zero_by_sector_t,
            net_margin_total=net_margin_total,
            net_margin_anomalies=net_margin_anomalies,
            rev_mcap_total=rev_mcap_total,
            rev_mcap_anomalies=rev_mcap_anomalies,
            fcf_mcap_total=fcf_mcap_total,
            fcf_mcap_anomalies=fcf_mcap_anomalies,
            currency_total=currency_total,
            non_inr_count=non_inr_count,
            non_inr_tickers=sorted(non_inr),
            known_good_asset_turnover=known_good_asset_turnover,
        )


__all__ = ["load_unit_integrity_sample"]
