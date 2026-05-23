"""bse_bank_xbrl.py — Bank-specific XBRL schedule fetcher.

Phase I-ingest-a (Block II). Standalone module so the generic
``bse_xbrl.py`` (which fetches BSE Stockquote / Peercomp generic
financial statements) is not perturbed.

What this module owns
---------------------
A narrow surface dedicated to extracting the six XBRL-reachable
bank operational KPIs identified by the Phase I-audit:

    gnpa_pct, nnpa_pct, pcr_pct           (BSE quarterly XBRL Schedule XVIII -- Asset Classification)
    casa_pct                              (BSE quarterly XBRL Schedule V    -- Deposits)
    cost_to_income_pct                    (BSE quarterly XBRL Form A / Sch B; derivable from operating_expense / (interest_earned + non_interest_income))
    credit_deposit_pct                    (BSE quarterly XBRL Sch V + VII   -- Advances / Deposits)

Branches / ATMs / customer-base are NOT XBRL-disclosed and are
handled by ``scripts/extract_bank_ops_from_ar.py`` (I-ingest-b),
not by this module.

Why this is structured as a provider with a default no-op
---------------------------------------------------------
The Phase I-audit explicitly flagged that the per-bank quarterly
XBRL Schedule URLs are not enumerated in ``company_filings``
today and that the bank-specific RBI / NSE XBRL element-tag map
has not been authored (see
``docs/diagnostics/phase-i-bank-kpi-coverage-2026-05-26.md``,
verdict RESCOPE).

Rather than ship a fabricated XBRL parser that hallucinates tag
names and silently writes nulls (or worse, wrong values), this
module provides:

    1. A clean public surface (``fetch_bank_kpis_for_quarter``)
       that the ingest CLI calls.
    2. A pluggable provider (``register_provider`` / ``_PROVIDER``)
       so an operator / dev can wire a real BSE XBRL parser
       without touching the CLI or persistence layer.
    3. A reference ``ParsedBankKpiRow`` dataclass + percent / decimal
       normaliser that any future provider must produce.
    4. A documented set of tag-name candidates per KPI (the
       ``_KPI_TAG_CANDIDATES`` map) so the future parser has a
       starting point and the audit trail stays in-tree.

The default provider returns ``None`` for every (ticker, quarter)
pair. The CLI therefore writes zero rows by default -- which is
honest. The pre-flight gate in the CLI will report this as
"provider not configured" rather than silently passing.

Wiring a real provider
----------------------
A dev who has authored the BSE XBRL schedule parser can install
it without modifying this file:

    from data_pipeline.sources import bse_bank_xbrl
    bse_bank_xbrl.register_provider(my_provider)

where ``my_provider(ticker: str, n_quarters: int) -> list[ParsedBankKpiRow]``
returns one row per quarter (oldest -> newest).

Discipline
----------
* Read-only against external APIs; the only side-effects are
  network calls (when a real provider is wired) and the
  caller's DB UPSERT into ``bank_operational_kpis``.
* No score / DCF code touched.
* Percent columns are stored as percentages (0.0 - 100.0) per
  the migration-061 contract; the normaliser ``_as_percent``
  multiplies decimals < 1 by 100 with a logged warning so a
  provider that returns 0.024 for GNPA does not write 0.024%.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

logger = logging.getLogger("yieldiq.bse_bank_xbrl")


# ---------- KPI tag candidates (for future provider authors) -----------------

# Best-effort starting point for an XBRL element-tag mapping. The
# Indian bank XBRL taxonomy (NSE / BSE submission via the RBI
# Schedules V / VII / XVIII) does not have a single canonical
# namespace exposed publicly, and tag names diverge across filers
# and quarters. The provider author should iterate the live XBRL
# for HDFCBANK / SBIN / AXISBANK (the audit-prescribed pre-flight
# trio) and harvest the actual element tags before extending this
# list.
_KPI_TAG_CANDIDATES: dict[str, tuple[str, ...]] = {
    "gnpa_pct": (
        "GrossNonPerformingAssetsRatio",
        "GrossNPARatio",
        "GrossNPAtoGrossAdvancesRatio",
        "in-rbi:GrossNPARatio",
    ),
    "nnpa_pct": (
        "NetNonPerformingAssetsRatio",
        "NetNPARatio",
        "NetNPAtoNetAdvancesRatio",
        "in-rbi:NetNPARatio",
    ),
    "pcr_pct": (
        "ProvisionCoverageRatio",
        "PCR",
        "in-rbi:ProvisionCoverageRatio",
    ),
    "casa_pct": (
        "CASARatio",
        "CurrentAndSavingsAccountRatio",
        "in-rbi:CASARatio",
    ),
    "cost_to_income_pct": (
        "CostToIncomeRatio",
        "OperatingExpensesToTotalIncomeRatio",
        "in-rbi:CostToIncomeRatio",
    ),
    "credit_deposit_pct": (
        "CreditDepositRatio",
        "CDRatio",
        "in-rbi:CreditDepositRatio",
    ),
}

# Which of the six fields a row must populate to count as "useful"
# for the pre-flight gate. The audit (sec. 5) requires >=4 of 6
# fields on >=2 of the 3 pre-flight tickers; this constant is the
# numerator of that check.
XBRL_KPI_FIELDS: tuple[str, ...] = tuple(_KPI_TAG_CANDIDATES.keys())


@dataclass
class ParsedBankKpiRow:
    """One row's worth of bank KPIs parsed from XBRL.

    All percent fields are PERCENTAGES (0.0-100.0) per the
    migration-061 contract -- callers must NOT pre-multiply.
    A field that's absent from the source filing stays ``None``;
    every-field-None rows are dropped by the caller.
    """
    ticker: str
    period_end: date
    period_type: str = "quarterly"

    gnpa_pct: Optional[float] = None
    nnpa_pct: Optional[float] = None
    pcr_pct: Optional[float] = None
    casa_pct: Optional[float] = None
    cost_to_income_pct: Optional[float] = None
    credit_deposit_pct: Optional[float] = None

    source: str = "bse_xbrl"
    source_url: Optional[str] = None
    raw_tag_hits: dict[str, str] = field(default_factory=dict)

    def populated_field_count(self) -> int:
        """Number of XBRL_KPI_FIELDS that are non-None on this row."""
        return sum(1 for f in XBRL_KPI_FIELDS if getattr(self, f) is not None)

    def is_useful(self) -> bool:
        """At least one populated field -- otherwise the caller
        should drop the row rather than UPSERT all-NULL values.
        """
        return self.populated_field_count() > 0


# ---------- percent / decimal normaliser ------------------------------------

def as_percent(value: object, *, field_name: str = "",
               ticker: str = "") -> Optional[float]:
    """Coerce a raw XBRL numeric to a percentage in [0.0, 100.0].

    Bank XBRL filings inconsistently report ratios as either a
    percentage ("2.45" for 2.45%) or a decimal ("0.0245" for the
    same). The migration-061 contract is PERCENTAGES; this
    function applies a 1.0-pivot heuristic with a warning trail:

      * None / non-numeric -> None
      * 0 <= v < 1         -> v * 100 (logged as a decimal->percent coercion)
      * 1 <= v <= 100      -> v unchanged
      * v > 100            -> dropped with a warning (almost
                              certainly a unit-scale mismatch,
                              e.g. raw rupees vs. crores -- the
                              same guard the generic financials
                              path applies to ROE).
      * v < 0              -> dropped with a warning.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None

    if f != f:  # NaN
        return None
    if f < 0:
        logger.warning(
            "bse_bank_xbrl.as_percent: dropping negative %s=%s for %s",
            field_name or "ratio", f, ticker or "?",
        )
        return None
    if f > 100:
        logger.warning(
            "bse_bank_xbrl.as_percent: dropping out-of-range %s=%s for %s "
            "(>100 -- likely unit mismatch)",
            field_name or "ratio", f, ticker or "?",
        )
        return None
    if f < 1.0:
        # Treat as decimal-encoded percent (0.0245 -> 2.45).
        coerced = f * 100.0
        logger.debug(
            "bse_bank_xbrl.as_percent: coerced decimal %s=%s -> %s%% for %s",
            field_name or "ratio", f, coerced, ticker or "?",
        )
        return round(coerced, 3)
    return round(f, 3)


# ---------- pluggable provider -----------------------------------------------

# Provider signature: (ticker, n_quarters) -> list[ParsedBankKpiRow].
# Default implementation returns an empty list -- see module
# docstring for the rationale.
ProviderFn = Callable[[str, int], list[ParsedBankKpiRow]]


def _default_provider(ticker: str, n_quarters: int) -> list[ParsedBankKpiRow]:
    """Default no-op provider.

    Logs once per ticker (DEBUG) and returns []. The CLI surfaces
    a clear "provider not configured" pre-flight failure when this
    is the active provider -- there is no silent path that writes
    zero rows without the operator noticing.
    """
    logger.debug(
        "bse_bank_xbrl: default no-op provider invoked for %s (n_quarters=%d)"
        " -- no real BSE XBRL schedule parser is wired. Register one via"
        " register_provider() to populate gnpa/nnpa/pcr/casa/cost-to-income"
        "/credit-deposit.",
        ticker, n_quarters,
    )
    return []


_PROVIDER: ProviderFn = _default_provider


def register_provider(provider: ProviderFn) -> None:
    """Install a real BSE XBRL schedule provider.

    See the module docstring for the contract. The CLI calls
    ``fetch_bank_kpis_for_quarter`` which dispatches to whichever
    provider is registered.
    """
    if not callable(provider):
        raise TypeError("provider must be callable")
    global _PROVIDER
    _PROVIDER = provider
    logger.info(
        "bse_bank_xbrl: registered provider %s.%s",
        getattr(provider, "__module__", "?"),
        getattr(provider, "__name__", "?"),
    )


def is_default_provider() -> bool:
    """True iff the no-op default provider is still active."""
    return _PROVIDER is _default_provider


def fetch_bank_kpis_for_quarter(
    ticker: str, n_quarters: int = 20,
) -> list[ParsedBankKpiRow]:
    """Public entrypoint. Returns up to ``n_quarters`` rows for
    ``ticker``, oldest -> newest, via the registered provider.

    The default provider returns []; the CLI pre-flight will
    fail-fast on that case so the operator knows the parser has
    not been wired yet.
    """
    if not ticker or not isinstance(ticker, str):
        raise ValueError("ticker must be a non-empty string")
    if not isinstance(n_quarters, int) or n_quarters <= 0:
        raise ValueError("n_quarters must be a positive int")
    return list(_PROVIDER(ticker, n_quarters))
