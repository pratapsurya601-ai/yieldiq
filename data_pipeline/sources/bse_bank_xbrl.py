"""bse_bank_xbrl.py -- Bank-specific XBRL schedule fetcher + parser.

Phase I-ingest-a (Block II) shipped the provider-pattern scaffold.
Phase I-ingest-a (Block III) -- this revision -- replaces the no-op
default with a real BSE quarterly XBRL parser that extracts the six
bank operational KPIs from the in-bse-fin / in-capmkt taxonomies
observed in production filings (HDFCBANK Q2/Q3 FY25, Q4 FY26
integrated filing).

What this module owns
---------------------
A narrow surface dedicated to extracting the six XBRL-reachable
bank operational KPIs identified by the Phase I-audit:

    gnpa_pct, nnpa_pct                    (PercentageOfGrossNpa /
                                           PercentageOfNpa -- decimal
                                           encoded as 0.0136 = 1.36%)
    pcr_pct                               (DERIVED:
                                           (GrossNPA - NetNPA) / GrossNPA
                                           -- the specific-provision PCR
                                           formula; the SEBI bank XBRL
                                           schema does NOT carry a filed
                                           ProvisionCoverageRatio tag.)
    cost_to_income_pct                    (DERIVED:
                                           OperatingExpenses /
                                           (InterestEarned - InterestExpended
                                            + OtherIncome) * 100)
    credit_deposit_pct                    (DERIVED: Advances / Deposits * 100;
                                           uses the OneI instant context.)
    casa_pct                              (NOT DISCLOSED in BSE quarterly
                                           XBRL -- the schema reports only
                                           aggregate Deposits, not the
                                           current/savings breakdown. Always
                                           returns None. Operators wanting
                                           CASA must source it from
                                           AR-Anthropic (Phase I-ingest-b)
                                           or quarterly investor presentations.)

Branches / ATMs / customer-base are NOT XBRL-disclosed and are
handled by ``scripts/extract_bank_ops_from_ar.py`` (I-ingest-b),
not by this module.

Element-tag survey (2026-05, against backend/tests/fixtures/bank_xbrl/
+ tests/fixtures/xbrl/hdfcbank_*.xml)
-----------------------------------------------------------
Both the legacy 2019-09 schema (`in-bse-fin`) and the 2026-01
SEBI Integrated Filing schema (`in-capmkt`, namespace URI containing
`IntegratedFinance_Banking`) use IDENTICAL element local names for
the six base facts the parser needs:

    PercentageOfGrossNpa, PercentageOfNpa            (period: OneD)
    GrossNonPerformingAssets, NonPerformingAssets    (period: OneD,
                                                      absolute, scale=Crores)
    Advances, Deposits                               (period: OneI -- instant)
    InterestEarned, InterestExpended, OtherIncome    (period: OneD)
    OperatingExpenses                                (period: OneD)

Because the local names match across schemas, the parser is namespace-
agnostic (matches by ``etree.QName(el).localname``). No schema branch
is needed.

NPA fields are reported in the STANDALONE filing only. Consolidated
filings (NatureOfReportStandaloneConsolidated = "Consolidated") carry
zeros for NPA-related fields per RBI convention -- ratios are an
unconsolidated, parent-bank metric. The provider therefore prefers
standalone XBRL when both are available for the same quarter.

Wiring a real provider
----------------------
The module auto-registers ``bse_xbrl_v1`` (a network-backed provider
that uses ``data_pipeline.sources.bse_quarterly_xbrl.BSEXBRLBrowserClient``
to fetch filings from BSE). Operators can override with their own
provider:

    from data_pipeline.sources import bse_bank_xbrl
    bse_bank_xbrl.register_provider(my_provider)

The reset helper ``reset_to_default_provider()`` exists for tests.

Discipline
----------
* Read-only against external APIs; the only side-effects are
  network calls and the caller's DB UPSERT.
* No score / DCF code touched.
* Percent columns are stored as percentages (0.0 - 100.0) per
  the migration-061 contract; ``as_percent`` multiplies decimals
  < 1 by 100 with a logged warning so a provider that returns
  0.024 for GNPA does not write 0.024%.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Optional

logger = logging.getLogger("yieldiq.bse_bank_xbrl")


# ---------- KPI tag candidates (historical reference) -----------------------
#
# The names below are the *observed* element local names in BSE quarterly
# XBRL filings (HDFCBANK Q2/Q3 FY25 + Q4 FY26 integrated). The parser
# uses ``_TAG_MAP`` below for the actual extraction; this candidate map
# is preserved as audit-trail documentation for future schema drift.
_KPI_TAG_CANDIDATES: dict[str, tuple[str, ...]] = {
    "gnpa_pct": (
        "PercentageOfGrossNpa",  # observed (decimal encoded)
        "GrossNonPerformingAssetsRatio",
        "GrossNPARatio",
    ),
    "nnpa_pct": (
        "PercentageOfNpa",  # observed (decimal encoded)
        "NetNonPerformingAssetsRatio",
        "NetNPARatio",
    ),
    "pcr_pct": (
        # NOT directly filed; derived from GrossNPA / NetNPA absolutes.
        "ProvisionCoverageRatio",
        "PCR",
    ),
    "casa_pct": (
        # NOT in BSE quarterly XBRL -- aggregate Deposits only.
        "CASARatio",
        "CurrentAndSavingsAccountRatio",
    ),
    "cost_to_income_pct": (
        # Derived from OperatingExpenses / (NII + OtherIncome).
        "CostToIncomeRatio",
        "OperatingExpensesToTotalIncomeRatio",
    ),
    "credit_deposit_pct": (
        # Derived from Advances / Deposits.
        "CreditDepositRatio",
        "CDRatio",
    ),
}

# Concrete element-name map the parser actually walks. Local-name match;
# namespace-agnostic across in-bse-fin (legacy 2019-09) and in-capmkt
# (SEBI Integrated 2026-01).
_TAG_MAP: dict[str, str] = {
    "gnpa_decimal": "PercentageOfGrossNpa",
    "nnpa_decimal": "PercentageOfNpa",
    "gross_npa_abs": "GrossNonPerformingAssets",
    "net_npa_abs": "NonPerformingAssets",
    "advances": "Advances",
    "deposits": "Deposits",
    "interest_earned": "InterestEarned",
    "interest_expended": "InterestExpended",
    "other_income": "OtherIncome",
    "operating_expenses": "OperatingExpenses",
}

# Which of the six fields a row must populate to count as "useful"
# for the pre-flight gate.
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


# ---------- low-level XBRL extraction ---------------------------------------

def _localname(qname: str) -> str:
    """Return XML local name from a ``{ns}name`` QName string."""
    if "}" in qname:
        return qname.split("}", 1)[1]
    return qname


def _pick_period_context(contexts: dict, prefer_duration: bool = True) -> tuple[str | None, date | None]:
    """Pick the quarter context: prefer the shortest duration context
    (OneD = ~90 days) over multi-quarter / annual ones.

    Returns (context_id, period_end_date).
    """
    best_id = None
    best_end: date | None = None
    best_days = 10**9
    for cid, info in contexts.items():
        start = info.get("start")
        end = info.get("end")
        if not (start and end):
            continue
        try:
            sd = datetime.strptime(start, "%Y-%m-%d").date()
            ed = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            continue
        days = (ed - sd).days
        # Quarter is ~90d; reject annual (300+) and weird buckets.
        if not (60 <= days <= 120):
            continue
        # Prefer the latest end-date when there are duplicates.
        if best_end is None or ed > best_end or (ed == best_end and days < best_days):
            best_id = cid
            best_end = ed
            best_days = days
    return best_id, best_end


def _pick_instant_context(contexts: dict, target_end: date | None) -> str | None:
    """Pick the instant context whose date matches ``target_end`` (or
    is closest -- BSE bank XBRL typically files the balance-sheet
    instant on the same day as the quarter-end).
    """
    best_id = None
    best_delta = 10**9
    for cid, info in contexts.items():
        inst = info.get("instant")
        if not inst:
            continue
        try:
            d = datetime.strptime(inst, "%Y-%m-%d").date()
        except ValueError:
            continue
        if target_end is None:
            return cid
        delta = abs((d - target_end).days)
        if delta < best_delta:
            best_delta = delta
            best_id = cid
    return best_id


def _fact(facts: dict, tag: str, context: str | None) -> float | None:
    """Look up one numeric fact by local-name + contextRef."""
    rows = facts.get(tag) or []
    if context:
        for v, c in rows:
            if c == context:
                return v
    # Fallback: any context, prefer non-zero.
    for v, _c in rows:
        if v != 0:
            return v
    return rows[0][0] if rows else None


def _detect_consolidated(xbrl_bytes: bytes) -> bool | None:
    """Read ``NatureOfReportStandaloneConsolidated`` if present.

    Returns True for Consolidated, False for Standalone, None if absent.
    """
    try:
        from lxml import etree
    except ImportError:
        from xml.etree import ElementTree as etree  # type: ignore
    try:
        root = etree.fromstring(xbrl_bytes)
    except Exception:
        return None
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        # Plain XBRL XML: tag local name IS the element name.
        # iXBRL: tag is <ix:nonNumeric name='in-capmkt:NatureOf...'>, so the
        # element name lives in the ``name`` attribute instead.
        ln = _localname(el.tag)
        name_attr = el.get("name") or ""
        name_local = name_attr.split(":", 1)[1] if ":" in name_attr else name_attr
        if (
            ln == "NatureOfReportStandaloneConsolidated"
            or name_local == "NatureOfReportStandaloneConsolidated"
        ):
            txt = "".join(el.itertext()).strip().lower()
            if "consolid" in txt:
                return True
            if "standalone" in txt:
                return False
    return None


# ---------- inline-XBRL (iXBRL) fact extraction -----------------------------
#
# Since 2026 the BSE SEBI Integrated Filing serves bank quarterly results as
# inline XBRL (iXBRL) wrapped in an HTML document
# (``IFBanking_<code>_<ts>_IFBanking.html``), NOT as a standalone
# ``Main_Ind_As_*.xml`` instance. The numeric facts are carried in
# ``<ix:nonFraction>`` / ``<ix:nonNumeric>`` tags whose ``name=`` attribute is
# the same element local name the old XML path used::
#
#     <ix:nonFraction name='in-capmkt:PercentageOfGrossNpa' contextRef='OneD'
#                     unitRef='pure' scale='-2' decimals='INF'>1.15</ix:nonFraction>
#     <ix:nonFraction name='in-capmkt:GrossNonPerformingAssets' contextRef='OneD'
#                     unitRef='INR' scale='7' format='ixt3:numdotdecimalin'
#                     >34,061.19</ix:nonFraction>
#
# The ``<xbrli:context>`` definitions are present verbatim, so the existing
# ``_extract_contexts`` (local-name match on ``context``/``startDate``/...)
# already resolves OneD (the quarter duration) and OneI (the balance-sheet
# instant) with no changes.
#
# Two transforms the iXBRL extractor MUST apply that the plain-XML
# ``_extract_facts`` does not:
#   * ``scale`` -- multiply the text value by 10**scale (e.g. scale='-2' turns
#     1.15 into 0.0115; scale='7' turns 34,061.19 crore-units into the absolute
#     rupee figure). All six KPIs are ratios whose common scale cancels, but we
#     apply it for correctness so downstream consumers get true magnitudes.
#   * ``sign`` -- an ``ix:nonFraction sign='-'`` is a negated value.
# Thousands separators (Indian grouping, e.g. ``31,05,250.48``) are stripped.

def _ixbrl_sniff(xbrl_bytes: bytes) -> bool:
    """Cheap content sniff: is this an inline-XBRL (iXBRL) document?

    Detects iXBRL by the inline-XBRL namespace declaration, which always
    lives in the document head (the root ``<html xmlns:ix=".../inlineXBRL">``
    element). We deliberately do NOT scan for the first ``<ix:nonFraction>``
    tag: in the BSE IFBanking documents the head + style block runs to
    ~580 KB before the first fact appears, so a fixed head window would
    miss it. Returns False for plain XBRL XML so the legacy
    ``Main_Ind_As_*.xml`` path stays intact.
    """
    head = xbrl_bytes[:65_536].lower()
    return b"inlinexbrl" in head or b"xmlns:ix" in head


def _extract_ixbrl_facts(
    xbrl_bytes: bytes,
) -> dict[str, list[tuple[float, str]]]:
    """Return {localname: [(scaled_value, contextRef), ...]} from iXBRL.

    Walks every ``ix:nonFraction`` element, reads its ``name`` attribute
    (``ns:LocalName`` -> ``LocalName``), applies ``scale`` and ``sign``, strips
    thousands separators, and keys the resulting numeric fact by the element
    local name -- producing exactly the same shape ``_extract_facts`` returns
    for plain XBRL XML, so the rest of ``parse_bank_xbrl`` is format-agnostic.

    ``ix:nonNumeric`` tags carry text (auditor names, nature-of-report, ...);
    they are not numeric facts and are skipped here -- but the
    ``NatureOfReportStandaloneConsolidated`` flag is read separately by
    ``_detect_consolidated`` (which also handles iXBRL, see below).
    """
    try:
        from lxml import etree
    except ImportError:  # pragma: no cover -- lxml is a hard dep in prod
        from xml.etree import ElementTree as etree  # type: ignore

    try:
        root = etree.fromstring(xbrl_bytes)
    except Exception as exc:
        logger.debug("ixbrl parse fail: %s", exc)
        return {}

    facts: dict[str, list[tuple[float, str]]] = {}
    for el in root.iter():
        tag = el.tag
        if not isinstance(tag, str):
            continue
        if _localname(tag) != "nonFraction":
            continue
        name = el.get("name") or ""
        if not name:
            continue
        local = name.split(":", 1)[1] if ":" in name else name

        # Concatenate text (iXBRL facts may wrap inner spans for formatting).
        raw = "".join(el.itertext()).strip()
        if not raw:
            continue
        s = raw.replace(",", "").replace(" ", "").strip()
        if not s or s.upper() in ("NIL", "NA", "-", "--"):
            continue
        try:
            val = float(s)
        except (TypeError, ValueError):
            continue

        scale = el.get("scale")
        if scale:
            try:
                val *= 10.0 ** int(scale)
            except (TypeError, ValueError):
                pass
        sign = (el.get("sign") or "").strip()
        if sign == "-":
            val = -val

        ctx = el.get("contextRef") or ""
        facts.setdefault(local, []).append((val, ctx))
    return facts


# ---------- the parser ------------------------------------------------------

def parse_bank_xbrl(
    xbrl_bytes: bytes,
    *,
    ticker: str = "",
) -> dict[str, Any]:
    """Parse one BSE quarterly bank XBRL into the 6 ratio dict.

    Returns a dict with keys::

        gnpa_pct, nnpa_pct, pcr_pct, casa_pct,
        cost_to_income_pct, credit_deposit_pct,
        period_end (date | None),
        consolidated (bool | None),
        raw_tag_hits (dict[str, str])

    Missing / underivable fields are ``None``. Returns a dict with
    all-None ratio fields (but period_end may still be populated) on
    a malformed XBRL -- never raises.
    """
    out: dict[str, Any] = {
        "gnpa_pct": None,
        "nnpa_pct": None,
        "pcr_pct": None,
        "casa_pct": None,  # never derivable from BSE quarterly XBRL
        "cost_to_income_pct": None,
        "credit_deposit_pct": None,
        "period_end": None,
        "consolidated": None,
        "raw_tag_hits": {},
    }
    if not xbrl_bytes or len(xbrl_bytes) < 100:
        return out

    try:
        from data_pipeline.sources.nse_xbrl_fundamentals import (
            _extract_contexts, _extract_facts,
        )
    except Exception as exc:  # pragma: no cover -- import-time only
        logger.warning("parse_bank_xbrl: extract helpers unavailable: %s", exc)
        return out

    is_ixbrl = _ixbrl_sniff(xbrl_bytes)
    try:
        # Contexts (<xbrli:context>) are present verbatim in both the legacy
        # plain-XBRL XML and the 2026 iXBRL HTML, so the same extractor works
        # for either. Facts differ: iXBRL carries them in <ix:nonFraction>
        # name= attributes with a scale, so it needs a dedicated extractor.
        contexts = _extract_contexts(xbrl_bytes)
        if is_ixbrl:
            facts = _extract_ixbrl_facts(xbrl_bytes)
        else:
            facts = _extract_facts(xbrl_bytes)
    except Exception as exc:
        logger.info(
            "parse_bank_xbrl: malformed XBRL for %s: %s",
            ticker or "?", exc,
        )
        return out

    if not facts:
        # No numeric facts at all -- malformed or wrong file type.
        return out

    duration_ctx, period_end = _pick_period_context(contexts)
    instant_ctx = _pick_instant_context(contexts, period_end)
    out["period_end"] = period_end
    out["consolidated"] = _detect_consolidated(xbrl_bytes)

    # ---- direct ratios (decimal-encoded in source) ----
    gnpa_raw = _fact(facts, _TAG_MAP["gnpa_decimal"], duration_ctx)
    nnpa_raw = _fact(facts, _TAG_MAP["nnpa_decimal"], duration_ctx)
    out["gnpa_pct"] = as_percent(gnpa_raw, field_name="gnpa_pct", ticker=ticker)
    out["nnpa_pct"] = as_percent(nnpa_raw, field_name="nnpa_pct", ticker=ticker)
    if gnpa_raw is not None:
        out["raw_tag_hits"]["gnpa_pct"] = _TAG_MAP["gnpa_decimal"]
    if nnpa_raw is not None:
        out["raw_tag_hits"]["nnpa_pct"] = _TAG_MAP["nnpa_decimal"]

    # ---- PCR (derived) ----
    # Specific-provision PCR = (GrossNPA - NetNPA) / GrossNPA * 100.
    # Only meaningful when both absolutes are positive (standalone
    # filings only -- consolidated bank XBRL files zeros per RBI
    # disclosure convention).
    gross_npa = _fact(facts, _TAG_MAP["gross_npa_abs"], duration_ctx)
    net_npa = _fact(facts, _TAG_MAP["net_npa_abs"], duration_ctx)
    if (
        gross_npa is not None and net_npa is not None
        and gross_npa > 0 and net_npa >= 0 and net_npa <= gross_npa
    ):
        pcr_raw = (gross_npa - net_npa) / gross_npa * 100.0
        out["pcr_pct"] = round(pcr_raw, 3)
        out["raw_tag_hits"]["pcr_pct"] = (
            f"DERIVED({_TAG_MAP['gross_npa_abs']}-"
            f"{_TAG_MAP['net_npa_abs']})/{_TAG_MAP['gross_npa_abs']}"
        )

    # ---- credit-deposit ratio (derived from instant context) ----
    advances = _fact(facts, _TAG_MAP["advances"], instant_ctx)
    deposits = _fact(facts, _TAG_MAP["deposits"], instant_ctx)
    if (
        advances is not None and deposits is not None
        and deposits > 0 and advances >= 0
    ):
        cd_raw = advances / deposits * 100.0
        # CD ratio for a bank is typically 60-110%; >150% means
        # something is wrong (probably a context mix-up between
        # FourD and OneI).
        if 0 < cd_raw <= 150:
            out["credit_deposit_pct"] = round(cd_raw, 3)
            out["raw_tag_hits"]["credit_deposit_pct"] = (
                f"DERIVED({_TAG_MAP['advances']}/{_TAG_MAP['deposits']})"
            )

    # ---- cost-to-income ratio (derived) ----
    # CIR = OperatingExpenses / (InterestEarned - InterestExpended + OtherIncome)
    int_earned = _fact(facts, _TAG_MAP["interest_earned"], duration_ctx)
    int_exp = _fact(facts, _TAG_MAP["interest_expended"], duration_ctx)
    other_inc = _fact(facts, _TAG_MAP["other_income"], duration_ctx)
    op_exp = _fact(facts, _TAG_MAP["operating_expenses"], duration_ctx)
    if (
        int_earned is not None and int_exp is not None
        and other_inc is not None and op_exp is not None
    ):
        nii = int_earned - int_exp
        total_inc = nii + other_inc
        if total_inc > 0 and op_exp > 0:
            cir_raw = op_exp / total_inc * 100.0
            # Bank CIR is typically 35-65%; >100% would mean the bank
            # is losing money before provisions -- not impossible (PSU
            # bank crisis quarters) but we cap at 100 per as_percent
            # contract.
            if 0 < cir_raw <= 100:
                out["cost_to_income_pct"] = round(cir_raw, 3)
                out["raw_tag_hits"]["cost_to_income_pct"] = (
                    f"DERIVED({_TAG_MAP['operating_expenses']}/"
                    f"(NII+{_TAG_MAP['other_income']}))"
                )

    # CASA is not in BSE quarterly XBRL; always None. Documented.
    return out


# ---------- pluggable provider -----------------------------------------------

# Provider signature: (ticker, n_quarters) -> list[ParsedBankKpiRow].
# Default implementation returns an empty list -- see module
# docstring for the rationale.
ProviderFn = Callable[[str, int], list[ParsedBankKpiRow]]


def _default_provider(ticker: str, n_quarters: int) -> list[ParsedBankKpiRow]:
    """Default no-op provider.

    Logs once per ticker (DEBUG) and returns []. The CLI surfaces
    a clear "provider not configured" pre-flight failure when this
    is the active provider. Operators install the real provider via
    ``register_provider(bse_xbrl_v1_provider)`` (the module-level
    convenience callable below) or by passing the parser to their
    own fetcher.
    """
    logger.debug(
        "bse_bank_xbrl: default no-op provider invoked for %s (n_quarters=%d)"
        " -- call register_provider(bse_xbrl_v1_provider) to enable the real"
        " BSE quarterly XBRL parser.",
        ticker, n_quarters,
    )
    return []


_PROVIDER: ProviderFn = _default_provider
_PROVIDER_NAME: str = "default-noop"


def register_provider(provider: ProviderFn, name: str = "custom") -> None:
    """Install a real BSE XBRL schedule provider.

    See the module docstring for the contract. The CLI calls
    ``fetch_bank_kpis_for_quarter`` which dispatches to whichever
    provider is registered.

    Backward compatibility: callers may pass either
    ``register_provider(fn)`` (legacy 1-arg form used by Phase
    I-ingest-a tests) or ``register_provider(fn, name="...")``.
    """
    if not callable(provider):
        raise TypeError("provider must be callable")
    global _PROVIDER, _PROVIDER_NAME
    _PROVIDER = provider
    _PROVIDER_NAME = name
    logger.info(
        "bse_bank_xbrl: registered provider name=%s impl=%s.%s",
        name,
        getattr(provider, "__module__", "?"),
        getattr(provider, "__name__", "?"),
    )


def reset_to_default_provider() -> None:
    """Restore the no-op default provider (test helper)."""
    global _PROVIDER, _PROVIDER_NAME
    _PROVIDER = _default_provider
    _PROVIDER_NAME = "default-noop"


def is_default_provider() -> bool:
    """True iff the no-op default provider is still active."""
    return _PROVIDER is _default_provider


def active_provider_name() -> str:
    """Diagnostic accessor for the registered provider's name."""
    return _PROVIDER_NAME


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


# ---------- bse_xbrl_v1: real network-backed provider ----------------------
#
# This provider walks the BSE corporate-filings page for ``ticker``,
# downloads each Main_Ind_As_<code>_*.xml, runs ``parse_bank_xbrl`` on
# the bytes, and returns one ParsedBankKpiRow per (quarter, standalone-
# preferred) filing.
#
# Coverage gaps to be aware of (Phase I v1):
#   * Requires real-Chrome Playwright channel (Akamai bot wall). On
#     a CI runner without a desktop Chrome install, the fetch fails
#     and the provider returns [] for that ticker. The CLI pre-flight
#     surfaces this cleanly.
#   * CASA is never populated (schema gap; documented above).
#   * Consolidated filings carry zeros for NPA fields -- the provider
#     prefers standalone (one per quarter) and falls back to
#     consolidated only if no standalone exists for the same period.
#   * Some PSU banks (notably IDBI legacy filings pre-FY22) use older
#     in-bse-fin schema variants that omit the OneI instant context;
#     credit-deposit ratio will be None on those filings. Per the
#     "stop conditions" rule we ship v1 with this gap documented and
#     punt the v2 coverage push to a later PR.
# -----------------------------------------------------------------------

# Ticker -> BSE numeric code for the 38-bank PURE_BANK_TICKERS_FOR_DE
# universe. Lazy-loaded from backend/services on first call.
_BSE_CODE_CACHE: dict[str, str] = {}


def _bse_code_for(ticker: str) -> str | None:
    """Best-effort BSE numeric code lookup for ``ticker``.

    Consults the project's ``bse_securities_master`` (if present) and
    a hard-coded fallback table for the 38 PURE_BANK_TICKERS_FOR_DE
    cohort so that pre-flight works even before the master is loaded.
    """
    t = ticker.upper().strip()
    if t in _BSE_CODE_CACHE:
        return _BSE_CODE_CACHE[t] or None

    # Hard-coded fallback for the canonical bank universe -- sourced
    # from BSE's listed-equity page, verified May 2026.
    # BSE numeric codes for the PURE_BANK_TICKERS_FOR_DE cohort, verified
    # against BSE listed-equity pages May 2026. Some recent SFB / micro-
    # finance listings carry placeholder codes pending master-table load;
    # those are flagged with a comment.
    _FALLBACK: dict[str, str] = {
        "AUBANK":       "540611",
        "AXISBANK":     "532215",
        "BANDHANBNK":   "541153",
        "BANKBARODA":   "532134",
        "BANKINDIA":    "532149",
        "CANBK":        "532483",
        "CAPITALSFB":   "543556",
        "CENTRALBK":    "532885",
        "CUB":          "532210",
        "DCBBANK":      "532772",
        "EQUITASBNK":   "543243",
        "ESAFSFB":      "544020",
        "FEDERALBNK":   "500469",
        "FINCABK":      "543386",  # Fincare → resolved via master if drift
        "FINOPB":       "543386",
        "HDFCBANK":     "500180",
        "ICICIBANK":    "532174",
        "IDBI":         "500116",
        "IDFCFIRSTB":   "539437",
        "INDIANB":      "532814",
        "INDUSINDBK":   "532187",
        "IOB":          "532388",
        "JANASURF":     "544308",  # Jana SFB
        "KARURVYSYA":   "590003",
        "KOTAKBANK":    "500247",
        "MAHABANK":     "532525",
        "PNB":          "532461",
        "RBLBANK":      "540065",
        "SBIN":         "500112",
        "SFBAJM":       "543279",  # Suryoday-class SFB; verify via master
        "SOUTHBANK":    "532218",
        "SURYODAY":     "543279",
        "TMB":          "543596",
        "UCOBANK":      "532505",
        "UJJIVANSFB":   "542904",
        "UNIONBANK":    "532477",
        "UTKARSHBNK":   "543942",
        "YESBANK":      "532648",
    }
    code = _FALLBACK.get(t)
    if code:
        _BSE_CODE_CACHE[t] = code
        return code

    # Try the project securities master.
    try:
        from data_pipeline.sources import bse_securities_master as bsm
        lookup = getattr(bsm, "get_bse_code", None)
        if callable(lookup):
            c = lookup(t)
            if c:
                _BSE_CODE_CACHE[t] = str(c)
                return str(c)
    except Exception:
        pass

    return None


def bse_xbrl_v1_provider(ticker: str, n_quarters: int) -> list[ParsedBankKpiRow]:
    """Real network-backed provider: fetch BSE quarterly XBRL filings
    for ``ticker`` and parse the first ``n_quarters`` into
    ParsedBankKpiRow.

    Returns [] on any network / Playwright failure (logged at INFO)
    so the CLI pre-flight gate trips cleanly rather than crashing the
    operator's run.
    """
    if not ticker:
        return []
    bse_code = _bse_code_for(ticker)
    if not bse_code:
        logger.info(
            "bse_xbrl_v1: no BSE code for %s -- cannot fetch XBRL", ticker,
        )
        return []
    try:
        from data_pipeline.sources.bse_quarterly_xbrl import (
            BSEXBRLBrowserClient,
        )
    except Exception as exc:
        logger.info(
            "bse_xbrl_v1: bse_quarterly_xbrl unavailable (%s) -- returning []",
            exc,
        )
        return []

    # Run the async fetch synchronously. Each filing is independent;
    # we serialise to keep Akamai happy.
    import asyncio

    async def _run() -> list[ParsedBankKpiRow]:
        rows_by_period: dict[date, ParsedBankKpiRow] = {}
        client = BSEXBRLBrowserClient()
        await client.init()
        try:
            urls = await client.list_quarterly_xbrl_urls(
                bse_code, max_filings=max(n_quarters * 2, 8),
            )
            for url in urls:
                xml_bytes = await client.download(url)
                if not xml_bytes or len(xml_bytes) < 500:
                    continue
                try:
                    parsed = parse_bank_xbrl(xml_bytes, ticker=ticker)
                except Exception as exc:
                    logger.info(
                        "bse_xbrl_v1: parse fail %s %s: %s",
                        ticker, url, exc,
                    )
                    continue
                pe = parsed.get("period_end")
                if pe is None:
                    continue
                row = ParsedBankKpiRow(
                    ticker=ticker,
                    period_end=pe,
                    gnpa_pct=parsed["gnpa_pct"],
                    nnpa_pct=parsed["nnpa_pct"],
                    pcr_pct=parsed["pcr_pct"],
                    casa_pct=parsed["casa_pct"],
                    cost_to_income_pct=parsed["cost_to_income_pct"],
                    credit_deposit_pct=parsed["credit_deposit_pct"],
                    source="bse_xbrl",
                    source_url=url,
                    raw_tag_hits=parsed["raw_tag_hits"],
                )
                # Prefer standalone over consolidated for the same
                # period (NPA fields are zeroed in consolidated filings).
                existing = rows_by_period.get(pe)
                if existing is None or (
                    row.populated_field_count()
                    > existing.populated_field_count()
                ):
                    rows_by_period[pe] = row
                if len(rows_by_period) >= n_quarters:
                    break
        finally:
            await client.close()
        # Oldest -> newest per the public contract.
        return [rows_by_period[k] for k in sorted(rows_by_period.keys())]

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.info("bse_xbrl_v1: fetch failed for %s: %s", ticker, exc)
        return []


# ---------- auto-register the real provider at import ----------------------
#
# Operators / tests can disable auto-registration by setting the env
# var ``BSE_BANK_XBRL_NO_AUTOREGISTER=1`` before importing. With auto-
# registration on, ``is_default_provider()`` returns False after import
# and the CLI pre-flight runs against the real network-backed fetcher.
import os as _os
if not _os.environ.get("BSE_BANK_XBRL_NO_AUTOREGISTER"):
    try:
        register_provider(bse_xbrl_v1_provider, name="bse_xbrl_v1")
    except Exception as _exc:  # pragma: no cover -- defensive
        logger.warning(
            "bse_bank_xbrl: auto-register failed (%s); default no-op provider"
            " remains active.",
            _exc,
        )
