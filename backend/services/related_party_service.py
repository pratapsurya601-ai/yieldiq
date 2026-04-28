"""
related_party_service.py — Related-party transactions (RPT) analyzer.

SCAFFOLDING ONLY. This module lays the foundation for YieldIQ's Indian
governance differentiator: surfacing AOC-2 / MGT-9 / Notes-to-accounts
related-party disclosures and applying a curated red-flag rule set on
top of them.

Out of scope for THIS module (deliberately stubbed):
  * Live PDF parsing (PyMuPDF / pdfplumber).
  * Live LLM extraction calls (Groq / Gemini).
  * Frontend integration (analysis page sidebar / governance chip).

In scope here:
  * Pydantic-style row + flag dataclasses.
  * SQL access against the migration-017 table.
  * Summary aggregation (totals by txn_type, large-txn callouts,
    intra-promoter callouts, non-arms-length count).
  * Red-flag rule set (see detect_red_flags) — thresholds derived from
    SEBI LODR Reg 23 ("material" RPT thresholds) and the Companies Act.

The DB layer is injected as a callable that returns
``list[dict[str, Any]]`` rows, so tests can drive the service from a
fixture without spinning up Postgres. See tests/test_related_party_service.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger("yieldiq.governance.rpt")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

# Allowed enum values — kept as constants so callers (LLM extractor, ingest
# script, tests) can validate without re-deriving.
PARTY_TYPES = (
    "subsidiary",
    "associate",
    "kmp",
    "promoter_entity",
    "director_entity",
    "relative_kmp",
    "other",
)

TXN_TYPES = (
    "loan_given",
    "loan_taken",
    "sale_goods",
    "purchase_goods",
    "rendering_service",
    "receiving_service",
    "royalty",
    "rent",
    "guarantee",
    "asset_sale",
    "asset_purchase",
    "investment",
    "other",
)

SOURCE_FILINGS = ("AOC-2", "MGT-9", "AnnualReport", "NoteN")

# Promoter-side party types — used by both summarise() and detect_red_flags().
_PROMOTER_SIDE_TYPES = {"promoter_entity", "director_entity", "kmp", "relative_kmp"}


@dataclass
class RPTRow:
    """One row from related_party_transactions."""

    ticker: str
    fiscal_year: int
    source_filing: str
    related_party_name: str
    related_party_type: Optional[str]
    txn_type: str
    amount_inr: Optional[float]
    is_arms_length: Optional[bool]
    description: Optional[str] = None
    source_pdf_url: Optional[str] = None
    source_page: Optional[int] = None
    llm_extracted: bool = True
    llm_confidence: Optional[float] = None
    human_reviewed: bool = False
    id: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RPTRow":
        kept = {k: d.get(k) for k in cls.__dataclass_fields__.keys()}
        return cls(**kept)  # type: ignore[arg-type]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Flag:
    """One governance red-flag. Keep this minimal — frontend renders the
    code + severity + description directly; supporting_rows lets users
    drill into the underlying transactions."""

    code: str                # machine-stable id, e.g. "RPT_LOAN_TO_PROMOTER"
    severity: str            # "info" | "warn" | "high"
    title: str               # human-readable headline
    description: str         # one-line rationale with numbers
    supporting_rows: List[int] = field(default_factory=list)  # RPTRow.id values

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# DB access — injectable so tests can run without Postgres.
# ---------------------------------------------------------------------------

# A FetcherFn takes (ticker, fiscal_year) and returns raw row dicts.
# In production this is wired to SQLAlchemy. In tests, an in-memory
# fixture provides the same shape.
FetcherFn = Callable[[str, int], List[Dict[str, Any]]]


def _default_fetcher(ticker: str, fiscal_year: int) -> List[Dict[str, Any]]:  # pragma: no cover
    """Default DB fetcher — used in production. Tests inject their own.

    Imported lazily so this module stays usable in environments without
    the SQLAlchemy engine wired up (e.g. unit tests, scripts).
    """
    try:
        from sqlalchemy import text
        from db.engine import get_engine  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "related_party_service: default DB fetcher unavailable; "
            "inject a fetcher in tests."
        ) from exc

    sql = text(
        """
        SELECT id, ticker, fiscal_year, source_filing, related_party_name,
               related_party_type, txn_type, amount_inr, is_arms_length,
               description, source_pdf_url, source_page, llm_extracted,
               llm_confidence, human_reviewed
          FROM related_party_transactions
         WHERE ticker = :t AND fiscal_year = :y
         ORDER BY amount_inr DESC NULLS LAST, related_party_name ASC
        """
    )
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"t": ticker, "y": fiscal_year}).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_rpts_for_year(
    ticker: str,
    fiscal_year: int,
    *,
    fetcher: Optional[FetcherFn] = None,
) -> List[RPTRow]:
    """Return all RPT rows for (ticker, fiscal_year).

    Pass ``fetcher`` in tests to inject fixture data; production callers
    omit it and the service uses the default Postgres fetcher.
    """
    fn = fetcher or _default_fetcher
    raw = fn(ticker.upper(), int(fiscal_year))
    return [RPTRow.from_dict(r) for r in raw]


def summarize_rpts(
    ticker: str,
    fiscal_year: int,
    *,
    fetcher: Optional[FetcherFn] = None,
    revenue_inr: Optional[float] = None,
) -> Dict[str, Any]:
    """Aggregate RPTs for one fiscal year.

    Returns a dict with:
      total_count            -- number of disclosed RPT rows
      totals_by_txn_type     -- { txn_type: sum(amount_inr) }
      non_arms_length_count  -- count where is_arms_length is False
      large_transactions     -- rows where amount_inr > 1% of revenue_inr
                                (only populated if revenue_inr is given)
      intra_promoter_rows    -- rows with promoter / director / KMP
                                / relative_kmp counterparty
      total_amount_inr       -- sum of all (non-NULL) amounts
    """
    rows = get_rpts_for_year(ticker, fiscal_year, fetcher=fetcher)

    totals_by_txn: Dict[str, float] = {}
    total_amount = 0.0
    non_arms = 0
    intra_promoter: List[Dict[str, Any]] = []
    large_txns: List[Dict[str, Any]] = []

    threshold_amt = (revenue_inr or 0.0) * 0.01  # SEBI "material" floor heuristic

    for r in rows:
        amt = r.amount_inr or 0.0
        total_amount += amt
        totals_by_txn[r.txn_type] = totals_by_txn.get(r.txn_type, 0.0) + amt
        if r.is_arms_length is False:
            non_arms += 1
        if r.related_party_type in _PROMOTER_SIDE_TYPES:
            intra_promoter.append(r.to_dict())
        if revenue_inr and amt > threshold_amt:
            large_txns.append(r.to_dict())

    return {
        "ticker": ticker.upper(),
        "fiscal_year": int(fiscal_year),
        "total_count": len(rows),
        "total_amount_inr": total_amount,
        "totals_by_txn_type": totals_by_txn,
        "non_arms_length_count": non_arms,
        "large_transactions": large_txns,
        "intra_promoter_rows": intra_promoter,
    }


# ---------------------------------------------------------------------------
# Red-flag rule set
# ---------------------------------------------------------------------------
#
# Thresholds — picked to align with SEBI / Companies-Act materiality and
# with what an experienced governance analyst would flag by hand. Each
# rule is conservative; tighten in code review once we have backtest data
# across the top-500 backfill (Phase 4).
#
#   (a) loans to promoter entities   > 5% of net worth
#       -> SEBI LODR Reg 23(1)(a) "material" related-party threshold.
#   (b) royalty payments              > 2% of revenue
#       -> historical heuristic; royalties have been the favoured
#          value-extraction vehicle in multiple Indian governance cases.
#   (c) asset sales to related parties below 80% of book value
#       -> 20% discount-to-book floor; below that, ask why.
#   (d) recurring "consultancy fees" without clear scope
#       -> heuristic on description: contains "consult" / "advisory"
#          AND scope/rate disclosure missing.
#   (e) net related-party balance growing > 50% YoY
#       -> stub here; needs prior-year fetch in detect_red_flags caller.

@dataclass
class RedFlagContext:
    """Optional financial context the rules need."""
    net_worth_inr: Optional[float] = None
    revenue_inr: Optional[float] = None
    book_value_lookup: Dict[str, float] = field(default_factory=dict)
    prior_year_total_inr: Optional[float] = None  # supports rule (e)


def detect_red_flags(
    ticker: str,
    fiscal_year: int,
    *,
    fetcher: Optional[FetcherFn] = None,
    context: Optional[RedFlagContext] = None,
) -> List[Flag]:
    """Apply the curated red-flag rule set to one (ticker, fiscal_year).

    ``context`` carries the numerator/denominator inputs the rules need
    (net worth, revenue, prior-year RPT total). Without context, the
    rules that need a denominator silently skip — they do NOT fire.
    """
    ctx = context or RedFlagContext()
    rows = get_rpts_for_year(ticker, fiscal_year, fetcher=fetcher)
    flags: List[Flag] = []

    # (a) Loans given to promoter-side entities > 5% of net worth.
    if ctx.net_worth_inr and ctx.net_worth_inr > 0:
        promoter_loans = [
            r for r in rows
            if r.txn_type == "loan_given"
            and r.related_party_type in _PROMOTER_SIDE_TYPES
            and (r.amount_inr or 0) > 0
        ]
        loan_total = sum((r.amount_inr or 0) for r in promoter_loans)
        if loan_total > 0.05 * ctx.net_worth_inr:
            pct = 100.0 * loan_total / ctx.net_worth_inr
            flags.append(Flag(
                code="RPT_LOAN_TO_PROMOTER",
                severity="high",
                title="Large loans to promoter entities",
                description=(
                    f"Loans given to promoter/director/KMP entities total "
                    f"INR {loan_total:,.0f} ({pct:.1f}% of net worth; "
                    f"SEBI material threshold = 5%)."
                ),
                supporting_rows=[r.id for r in promoter_loans if r.id is not None],
            ))

    # (b) Royalty payments > 2% of revenue.
    if ctx.revenue_inr and ctx.revenue_inr > 0:
        royalties = [r for r in rows if r.txn_type == "royalty" and (r.amount_inr or 0) > 0]
        roy_total = sum((r.amount_inr or 0) for r in royalties)
        if roy_total > 0.02 * ctx.revenue_inr:
            pct = 100.0 * roy_total / ctx.revenue_inr
            flags.append(Flag(
                code="RPT_ROYALTY_HEAVY",
                severity="warn",
                title="Royalty payments above 2% of revenue",
                description=(
                    f"Royalty / brand-license payments to related parties "
                    f"total INR {roy_total:,.0f} ({pct:.1f}% of revenue)."
                ),
                supporting_rows=[r.id for r in royalties if r.id is not None],
            ))

    # (c) Asset sales to related parties below 80% of book value.
    if ctx.book_value_lookup:
        cheap_sales = []
        for r in rows:
            if r.txn_type != "asset_sale" or not r.amount_inr:
                continue
            bv = ctx.book_value_lookup.get(r.related_party_name)
            if bv and r.amount_inr < 0.80 * bv:
                cheap_sales.append((r, bv))
        if cheap_sales:
            ids = [r.id for r, _ in cheap_sales if r.id is not None]
            flags.append(Flag(
                code="RPT_ASSET_SALE_BELOW_BOOK",
                severity="high",
                title="Asset sale to related party below book value",
                description=(
                    f"{len(cheap_sales)} asset-sale transaction(s) to "
                    "related parties priced below 80% of book value."
                ),
                supporting_rows=ids,
            ))

    # (d) Recurring consultancy / advisory fees without clear scope.
    # Use word-boundary matching to avoid false-positives like "strategic"
    # containing the substring "rate" — that bit us during fixture testing.
    import re as _re

    def _has_word(text: str, words: Sequence[str]) -> bool:
        for w in words:
            pat = r"\b" + _re.escape(w) + r"\b"
            if _re.search(pat, text):
                return True
        return False

    consult_keywords = ("consult", "consultancy", "advisory", "professional fee")
    consult_rows = [
        r for r in rows
        if r.txn_type in ("rendering_service", "receiving_service", "other")
        and r.description
        and any(k in r.description.lower() for k in consult_keywords)  # substring OK here
    ]
    scope_keywords = ("scope", "rate", "per hour", "lump sum", "deliverable", "sow")
    vague_consult = [
        r for r in consult_rows
        if r.description and not _has_word(r.description.lower(), scope_keywords)
    ]
    if len(vague_consult) >= 1:
        flags.append(Flag(
            code="RPT_VAGUE_CONSULTANCY",
            severity="warn",
            title="Consultancy fees without disclosed scope",
            description=(
                f"{len(vague_consult)} consultancy/advisory fee row(s) lack "
                "a disclosed scope or rate basis."
            ),
            supporting_rows=[r.id for r in vague_consult if r.id is not None],
        ))

    # (e) Net related-party balance growing > 50% YoY.
    if ctx.prior_year_total_inr and ctx.prior_year_total_inr > 0:
        current_total = sum((r.amount_inr or 0) for r in rows)
        growth = (current_total - ctx.prior_year_total_inr) / ctx.prior_year_total_inr
        if growth > 0.50:
            flags.append(Flag(
                code="RPT_BALANCE_SPIKE",
                severity="warn",
                title="Related-party balance up >50% YoY",
                description=(
                    f"Total RPT amount INR {current_total:,.0f} vs prior-year "
                    f"INR {ctx.prior_year_total_inr:,.0f} ({growth*100:.0f}% YoY)."
                ),
                supporting_rows=[],
            ))

    return flags


# ---------------------------------------------------------------------------
# LLM extraction stub
# ---------------------------------------------------------------------------

# Prompt template — kept here as the canonical reference. The Phase-2
# integration will load this string, render with the page-range, and
# call Groq / Gemini Pro with structured-output (JSON-schema) mode.
LLM_SYSTEM_PROMPT = (
    "You are an SEBI-compliance analyst specialising in Indian listed-"
    "company governance. You read scanned annual-report pages and extract "
    "related-party transactions exactly as disclosed, without inference. "
    "If a value is ambiguous, return is_arms_length=null and llm_confidence "
    "below 0.85 so a human reviewer is queued."
)

LLM_USER_PROMPT_TEMPLATE = (
    "Ticker: {ticker}\n"
    "Fiscal year: {fiscal_year}\n"
    "Source: AOC-2 schedule (or MGT-9 / Notes-to-Accounts) on pages "
    "{page_start}-{page_end} of the attached annual-report PDF.\n\n"
    "Extract every related-party transaction as a JSON array. Each item:\n"
    "  related_party_name: string (verbatim)\n"
    "  related_party_type: one of {party_types}\n"
    "  txn_type: one of {txn_types}\n"
    "  amount_inr: number (rupees, NOT crore — convert if disclosed in crore)\n"
    "  is_arms_length: boolean | null\n"
    "  description: short verbatim quote from the disclosure\n"
    "  source_page: int\n"
    "  llm_confidence: float in [0,1]\n"
    "Return ONLY the JSON array. No prose."
)


def extract_rpts_from_pdf_with_llm(
    pdf_url: str,
    ticker: str,
    *,
    fiscal_year: Optional[int] = None,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> List[RPTRow]:
    """STUB. Phase-2 work.

    Wiring plan:
      1. Download PDF (use scripts/ingest_annual_reports.py helpers).
      2. Locate AOC-2 / MGT-9 / Notes section page-range via header regex.
      3. Render the pages to a multi-modal LLM (Gemini Pro 1.5+ for vision,
         Groq Llama-3.1-70B for text-only fast path).
      4. Validate the JSON response against the RPTRow schema.
      5. Apply confidence threshold (>=0.85 -> auto-publish, otherwise
         queue for human review).

    See LLM_SYSTEM_PROMPT and LLM_USER_PROMPT_TEMPLATE for the exact
    prompt that will be sent.
    """
    raise NotImplementedError(
        "LLM RPT extraction is Phase 2 — see "
        "docs/related_party_analyzer_design.md for the rollout plan."
    )


__all__ = [
    "PARTY_TYPES",
    "TXN_TYPES",
    "SOURCE_FILINGS",
    "RPTRow",
    "Flag",
    "RedFlagContext",
    "FetcherFn",
    "get_rpts_for_year",
    "summarize_rpts",
    "detect_red_flags",
    "extract_rpts_from_pdf_with_llm",
    "LLM_SYSTEM_PROMPT",
    "LLM_USER_PROMPT_TEMPLATE",
]
