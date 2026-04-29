# backend/services/classification.py
# ═══════════════════════════════════════════════════════════════
# Unified sector / industry classifier.
#
# Single source of truth for "what is this ticker, structurally?".
# Replaces (over time) the patchwork of curated sets in
# backend.services.analysis.constants:
#   - FINANCIAL_COMPANIES
#   - _NBFC_TICKERS / _INSURANCE_TICKERS / _NBFC_INSURANCE_BANKLIKE
#   - INVENTORY_HEAVY_TICKERS
#   - CYCLICAL_TICKERS
#   - TICKER_SECTOR_OVERRIDES
#
# All those continue to work as last-resort fallbacks (see Pillar 4 in
# the foundation PR) but new code MUST go through `classify()`.
#
# Cascade (highest-confidence first):
#   1. NSE official sectoral-index membership (table
#      `nse_sector_constituents` — Pillar 2, lands in a follow-up PR)
#   2. yfinance sector + industry stored on `stocks` (sector, industry)
#   3. Ticker name pattern (e.g. *BANK -> bank, *PHARM/*LAB -> pharma)
#   4. Curated-set fallback (the legacy hand-maintained sets)
#   5. "Unclassified" with data_limited flag
#
# The classifier is pure, side-effect-free, and DB-read-only. It MUST
# NOT mutate the curated sets at runtime. Output `data_quality_score`
# is a 0-1 confidence proxy used by `data_quality.completeness_score`
# (and the YieldIQ 50 gate).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("yieldiq.classification")


# ── Canonical labels ─────────────────────────────────────────────
# These are the labels every other module (sector_benchmarks,
# sector_percentile, hex_service, scoring, surfaces) should agree on.
# They mirror the keys of SECTOR_COHORT_RULES so cohort lookups
# always resolve.
CANONICAL_SECTORS: tuple[str, ...] = (
    "Banks",
    "PSU Bank",
    "Financial Services",   # NBFCs / AMCs / exchanges / insurers etc.
    "Insurance",
    "IT Services",
    "Pharma",
    "FMCG",
    "Auto",
    "Metals",
    "Energy",
    "Realty",
    "Media",
    "Consumer Durables",
    "Chemicals",
    "Cement",
    "Power & Utilities",
    "Telecom",
    "Infrastructure",
    "Textiles",
    "Diversified",
    "Unclassified",
)


# ── Name-pattern rules ──────────────────────────────────────────
# Last-resort lexical fallback when neither NSE nor yfinance has a
# clean answer. Order matters: bank patterns must run before "fin"
# (which would match BAJFINANCE et al as Financial Services).
_NAME_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"BANK$|^BANK|BNK$"), "Banks"),
    (re.compile(r"PHARM|LAB$|LABS$|LIFESCI|HEALTH|BIOC|DRUG"), "Pharma"),
    (re.compile(r"INFOS?Y|TECH|SOFT|INFOTECH|MINDTREE|TCS|WIPRO|HCL"), "IT Services"),
    (re.compile(r"INSUR|LIFE$|GIC|GENINS"), "Insurance"),
    (re.compile(r"FIN$|FINSV|FINANC|FINCORP"), "Financial Services"),
    (re.compile(r"STEEL|METAL|MINING|ALUM|ZINC|COPPER|IRON"), "Metals"),
    (re.compile(r"CEMENT|CEM$"), "Cement"),
    (re.compile(r"OIL$|GAS$|PETRO|REFIN|ENERGY"), "Energy"),
    (re.compile(r"POWER|UTIL|ELECTR|GRID"), "Power & Utilities"),
    (re.compile(r"AUTO|MOTOR|VEHICL"), "Auto"),
    (re.compile(r"REALTY|REALEST|REIT$|HOUSING|BUILD"), "Realty"),
    (re.compile(r"MEDIA|BROADC|CABLE|NEWS"), "Media"),
    (re.compile(r"TELECOM|TELE$|COMMUN"), "Telecom"),
    (re.compile(r"CHEM$|CHEMIC|SPECIAL"), "Chemicals"),
    (re.compile(r"TEXTIL|COTTON|FAB$|YARN"), "Textiles"),
]


# ── yfinance label -> canonical mapping ─────────────────────────
# Mirrors SECTOR_OVERRIDES in analysis/constants.py but produces
# canonical labels (the cohort keys) instead of free-text labels.
_YF_SECTOR_TO_CANONICAL: dict[str, str] = {
    "Technology": "IT Services",
    "Healthcare": "Pharma",
    "Consumer Defensive": "FMCG",
    "Consumer Cyclical": "Auto",          # default; refined by industry
    "Basic Materials": "Metals",
    "Energy": "Energy",
    "Utilities": "Power & Utilities",
    "Real Estate": "Realty",
    "Communication Services": "Media",
    "Financial Services": "Financial Services",  # split via industry
    "Industrials": "Infrastructure",
}


_BANK_INDUSTRY_LIKE = re.compile(r"\bbank", re.IGNORECASE)
_INSURANCE_INDUSTRY_LIKE = re.compile(r"\binsurance", re.IGNORECASE)
_AUTO_INDUSTRY_LIKE = re.compile(r"\bauto|\bvehicle|\bmotorcycl|\btruck", re.IGNORECASE)
_DURABLES_INDUSTRY_LIKE = re.compile(
    r"\bappliance|\bfurnish|\bleisure|\bapparel|\bfootwear|\bluxury", re.IGNORECASE
)
_PHARMA_INDUSTRY_LIKE = re.compile(r"\bdrug|\bpharma|\bbiotech|\bmedical", re.IGNORECASE)
_CEMENT_INDUSTRY_LIKE = re.compile(r"\bcement|\bbuilding material", re.IGNORECASE)


@dataclass
class ClassificationResult:
    """Canonical classification + confidence trail.

    Fields:
      canonical_sector  — one of CANONICAL_SECTORS
      yfinance_sector   — raw yfinance label (for debugging / audits)
      industry          — yfinance industry sub-label (or None)
      is_bank           — True for commercial banks (private + PSU)
      is_nbfc           — True for non-bank lenders / housing finance
      is_insurance      — True for life / general / health insurers
      is_cyclical       — commodity / cycle-bottom-FCF risk
      is_inventory_heavy— retail / apparel / jewellery (negative CFO from WC)
      data_quality_score— 0-1 classifier confidence (input to gate)
      sources_used      — ordered list of cascade sources that voted
    """

    canonical_sector: str
    yfinance_sector: Optional[str] = None
    industry: Optional[str] = None
    is_bank: bool = False
    is_nbfc: bool = False
    is_insurance: bool = False
    is_cyclical: bool = False
    is_inventory_heavy: bool = False
    data_quality_score: float = 0.0
    sources_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "canonical_sector": self.canonical_sector,
            "yfinance_sector": self.yfinance_sector,
            "industry": self.industry,
            "is_bank": self.is_bank,
            "is_nbfc": self.is_nbfc,
            "is_insurance": self.is_insurance,
            "is_cyclical": self.is_cyclical,
            "is_inventory_heavy": self.is_inventory_heavy,
            "data_quality_score": round(self.data_quality_score, 3),
            "sources_used": list(self.sources_used),
        }


def _bare(ticker: str) -> str:
    return (ticker or "").replace(".NS", "").replace(".BO", "").upper().strip()


def _query_nse_sector(ticker_bare: str, db_session) -> Optional[tuple[str, str]]:
    """Look up the ticker in `nse_sector_constituents` (Pillar 2).

    Returns (canonical_sector, nifty_index) or None. Quietly swallows
    UndefinedTable errors so this lands cleanly before the table
    exists — Pillar 2 follow-up PR adds the migration.
    """
    if db_session is None:
        return None
    try:
        from sqlalchemy import text
        row = db_session.execute(
            text(
                "SELECT canonical_sector, nifty_index "
                "FROM nse_sector_constituents "
                "WHERE ticker = :t "
                "ORDER BY fetched_at DESC LIMIT 1"
            ),
            {"t": ticker_bare},
        ).fetchone()
        if row:
            return (str(row[0]), str(row[1]))
    except Exception as exc:
        # Table missing pre-Pillar-2 / connection blip — fall through.
        logger.debug("nse_sector lookup failed for %s: %s", ticker_bare, exc)
    return None


def _query_stocks_row(ticker_bare: str, db_session) -> Optional[tuple[Optional[str], Optional[str]]]:
    """Read (sector, industry) from `stocks`. Tolerates missing row."""
    if db_session is None:
        return None
    try:
        from sqlalchemy import text
        row = db_session.execute(
            text("SELECT sector, industry FROM stocks WHERE ticker = :t LIMIT 1"),
            {"t": ticker_bare},
        ).fetchone()
        if row is None:
            return None
        return (row[0], row[1])
    except Exception as exc:
        logger.debug("stocks row lookup failed for %s: %s", ticker_bare, exc)
        return None


def _classify_from_yfinance(
    yf_sector: Optional[str], industry: Optional[str]
) -> Optional[str]:
    """Translate yfinance (sector, industry) into canonical label.

    The Financial Services and Consumer Cyclical buckets need the
    industry refinement; everything else maps cleanly off sector.
    """
    if not yf_sector:
        return None
    yf = yf_sector.strip()

    if yf == "Financial Services":
        if industry and _BANK_INDUSTRY_LIKE.search(industry):
            return "Banks"
        if industry and _INSURANCE_INDUSTRY_LIKE.search(industry):
            return "Insurance"
        return "Financial Services"

    if yf == "Consumer Cyclical":
        if industry and _AUTO_INDUSTRY_LIKE.search(industry):
            return "Auto"
        if industry and _DURABLES_INDUSTRY_LIKE.search(industry):
            return "Consumer Durables"
        return "Consumer Durables"

    if yf == "Healthcare" and industry and _PHARMA_INDUSTRY_LIKE.search(industry):
        return "Pharma"

    if yf == "Basic Materials" and industry and _CEMENT_INDUSTRY_LIKE.search(industry):
        return "Cement"

    return _YF_SECTOR_TO_CANONICAL.get(yf)


def _classify_from_name(ticker_bare: str) -> Optional[str]:
    for pat, label in _NAME_PATTERNS:
        if pat.search(ticker_bare):
            return label
    return None


def _classify_from_curated_sets(ticker_bare: str) -> Optional[str]:
    """Last-resort lookup against the legacy curated sets.

    DEPRECATED ENTRY POINT — do not extend the sets to add new
    classifications. New cases should be addressed by improving the
    yfinance-row population (Pillar 2) or the name-pattern rules
    above. This branch exists purely so existing data corrections
    don't regress while the foundation rolls out.
    """
    try:
        from backend.services.analysis.constants import (
            _NBFC_TICKERS,
            _INSURANCE_TICKERS,
            FINANCIAL_COMPANIES,
            CYCLICAL_TICKERS,
        )
    except Exception:
        return None
    if ticker_bare in _NBFC_TICKERS:
        return "Financial Services"
    if ticker_bare in _INSURANCE_TICKERS:
        return "Insurance"
    if ticker_bare in (FINANCIAL_COMPANIES - _NBFC_TICKERS - _INSURANCE_TICKERS):
        return "Banks"
    if ticker_bare in CYCLICAL_TICKERS:
        return "Energy"  # most CYCLICAL_TICKERS are oil/metals; coarse but better than Unclassified
    return None


def _is_cyclical(canonical: str, ticker_bare: str) -> bool:
    if canonical in {"Metals", "Energy", "Cement"}:
        return True
    try:
        from backend.services.analysis.constants import CYCLICAL_TICKERS
        if ticker_bare in CYCLICAL_TICKERS:
            return True
    except Exception:
        pass
    return False


def _is_inventory_heavy(canonical: str, ticker_bare: str) -> bool:
    if canonical in {"Consumer Durables", "Realty"}:
        return True
    try:
        from backend.services.analysis.constants import INVENTORY_HEAVY_TICKERS
        if ticker_bare in INVENTORY_HEAVY_TICKERS:
            return True
    except Exception:
        pass
    return False


def classify(ticker: str, db_session=None) -> ClassificationResult:
    """Return the canonical classification for `ticker`.

    `db_session` is optional — pass a `data_pipeline.db.Session()` to
    enable NSE-sector and `stocks` table lookups. Without a session,
    falls back to name patterns + curated sets (lower confidence).
    """
    bare = _bare(ticker)
    sources: list[str] = []
    canonical: Optional[str] = None
    yf_sector: Optional[str] = None
    industry: Optional[str] = None
    confidence: float = 0.0

    # 1. NSE official (Pillar 2 — table may not exist yet)
    nse = _query_nse_sector(bare, db_session) if db_session is not None else None
    if nse is not None:
        canonical = nse[0]
        sources.append("nse_official")
        confidence = max(confidence, 1.0)

    # 2. stocks.sector + stocks.industry (yfinance-derived)
    stocks_row = _query_stocks_row(bare, db_session) if db_session is not None else None
    if stocks_row is not None:
        yf_sector, industry = stocks_row
        if canonical is None:
            yf_canonical = _classify_from_yfinance(yf_sector, industry)
            if yf_canonical:
                canonical = yf_canonical
                sources.append("yfinance")
                # Industry-based refinement is high confidence;
                # sector-only is medium.
                confidence = max(confidence, 0.85 if industry else 0.65)

    # 3. Ticker name pattern
    if canonical is None:
        name_canonical = _classify_from_name(bare)
        if name_canonical:
            canonical = name_canonical
            sources.append("name_pattern")
            confidence = max(confidence, 0.55)

    # 4. Curated-set fallback (legacy)
    if canonical is None:
        curated = _classify_from_curated_sets(bare)
        if curated:
            canonical = curated
            sources.append("curated_set")
            confidence = max(confidence, 0.5)

    # 5. Final fallback
    if canonical is None:
        canonical = "Unclassified"
        sources.append("fallback")
        confidence = 0.1

    is_bank = canonical in {"Banks", "PSU Bank"} or (
        bare.endswith("BANK") and canonical != "Insurance"
    )
    is_nbfc = (
        canonical == "Financial Services"
        and not is_bank
        and not (industry and _INSURANCE_INDUSTRY_LIKE.search(industry or ""))
    )
    is_insurance = canonical == "Insurance"

    return ClassificationResult(
        canonical_sector=canonical,
        yfinance_sector=yf_sector,
        industry=industry,
        is_bank=is_bank,
        is_nbfc=is_nbfc,
        is_insurance=is_insurance,
        is_cyclical=_is_cyclical(canonical, bare),
        is_inventory_heavy=_is_inventory_heavy(canonical, bare),
        data_quality_score=round(confidence, 3),
        sources_used=sources,
    )
