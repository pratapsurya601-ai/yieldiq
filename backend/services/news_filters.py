# backend/services/news_filters.py
# ═══════════════════════════════════════════════════════════════
# News filtering, source ranking, topic tagging
#
# Three layers applied to raw news items (yfinance / BSE / etc.)
# before they reach the UI:
#
#   1. Ticker-exact filter  — item headline+summary must mention
#      the exact ticker symbol OR an alias of the canonical
#      company name (from data/company_name_aliases.json).
#      Substring matches against generic words ("CMS", "HDFC")
#      that bleed across companies are blocked.
#
#   2. Source quality tier  — each item is tagged Tier 1..4.
#      Tier 4 is dropped unless its topic survives a whitelist
#      (earnings | deal | governance). Tier 1/2 sort first,
#      then Tier 3, then surviving Tier 4.
#
#   3. Topic classifier     — light keyword tagger:
#      earnings | deal | governance | regulatory |
#      analyst-update | general.  Drives the noise filter and
#      the UI chip.
#
# Pure functions, no I/O beyond loading the aliases JSON once.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Iterable, Optional
from urllib.parse import urlparse

logger = logging.getLogger("yieldiq.news.filters")

# ── Aliases ────────────────────────────────────────────────────

_ALIAS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "company_name_aliases.json",
)


@lru_cache(maxsize=1)
def _load_aliases() -> dict[str, list[str]]:
    try:
        with open(_ALIAS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {k.upper(): list(v) for k, v in raw.items() if not k.startswith("_") and isinstance(v, list)}
    except Exception as e:
        logger.warning(f"news_filters: failed to load aliases ({_ALIAS_PATH}): {e}")
        return {}


def get_aliases(ticker: str) -> list[str]:
    """Return canonical aliases for a ticker (NSE symbol, no suffix)."""
    clean = (ticker or "").upper().replace(".NS", "").replace(".BO", "")
    aliases = list(_load_aliases().get(clean, []))
    if clean and clean not in aliases:
        aliases.append(clean)
    return aliases


# ── 1. Ticker-exact filter ─────────────────────────────────────

# Words that often produce false-positive substring matches across
# unrelated Indian listings (e.g. "HDFC" hitting "HDFC Bank" items
# on an HDFCLIFE page). Required if no other alias matches.
_AMBIGUOUS_PREFIXES = {"HDFC", "ICICI", "TATA", "BAJAJ", "ADANI", "GODREJ", "MAHINDRA", "JINDAL", "BIRLA"}


def _word_pattern(token: str) -> re.Pattern:
    """Compile a case-insensitive whole-word regex for token."""
    # Escape; treat ampersand/quote as boundaries naturally.
    pat = re.escape(token.strip())
    # \b doesn't work cleanly with leading/trailing non-word chars
    # (e.g. "Dr."). Use lookarounds on word chars.
    return re.compile(rf"(?<!\w){pat}(?!\w)", re.IGNORECASE)


@lru_cache(maxsize=2048)
def _compiled_aliases(ticker: str) -> tuple[re.Pattern, ...]:
    return tuple(_word_pattern(a) for a in get_aliases(ticker) if a and len(a) >= 2)


def matches_ticker(item: dict, ticker: str) -> bool:
    """
    True iff the item's headline OR summary mentions the ticker
    symbol or a canonical alias as a whole word (case-insensitive).

    For ambiguous corporate-family prefixes (HDFC / TATA / BAJAJ /
    ADANI / ...) a bare prefix match is NOT enough — a longer
    alias (e.g. "HDFC Bank") must hit.
    """
    if not ticker:
        return True  # aggregate feed: no per-ticker gate
    haystack = " ".join(
        str(item.get(k, "") or "") for k in ("headline", "summary", "company_name")
    )
    if not haystack.strip():
        return False

    clean = ticker.upper().replace(".NS", "").replace(".BO", "")
    patterns = _compiled_aliases(clean)
    if not patterns:
        # No alias data — fall back to whole-word ticker match.
        return bool(_word_pattern(clean).search(haystack))

    # If the symbol itself is an ambiguous prefix (e.g. "HDFC"
    # standalone would never be a real ticker, but "TATA" might),
    # require a non-prefix alias hit.
    ambiguous_only = clean in _AMBIGUOUS_PREFIXES
    for pat in patterns:
        token = pat.pattern
        if ambiguous_only and token.strip("\\b\\W").upper() in _AMBIGUOUS_PREFIXES:
            continue
        if pat.search(haystack):
            return True
    return False


# ── 2. Source quality tier ─────────────────────────────────────

_TIER_1 = {
    "reuters", "bloomberg", "moneycontrol", "livemint", "mint",
    "et markets", "economic times", "the economic times",
    "businessline", "the hindu businessline", "hindu businessline",
    "business standard", "bs", "financial express",
}
_TIER_2 = {
    "ndtv profit", "ndtv", "cnbc tv18", "cnbctv18", "cnbc-tv18",
    "outlook business", "outlook", "the hindu", "zee business",
    "bqprime", "bq prime",
}
_TIER_3 = {
    "simply wall st", "simply wall street", "gurufocus", "seeking alpha",
    "zacks", "motley fool", "the motley fool", "investorplace",
    "yahoo finance", "yahoo", "investing.com",
}
# Tier 4 (noise): regulatory boilerplate, recognised by topic
# tag rather than source name — see classify_topic below.

# Domain hints when the source string is missing/generic.
_DOMAIN_TIER = {
    "reuters.com": 1, "bloomberg.com": 1, "moneycontrol.com": 1,
    "livemint.com": 1, "economictimes.indiatimes.com": 1,
    "thehindubusinessline.com": 1, "business-standard.com": 1,
    "financialexpress.com": 1,
    "ndtvprofit.com": 2, "cnbctv18.com": 2, "outlookbusiness.com": 2,
    "thehindu.com": 2, "zeebiz.com": 2,
    "simplywall.st": 3, "gurufocus.com": 3, "seekingalpha.com": 3,
    "zacks.com": 3, "fool.com": 3, "investorplace.com": 3,
    "finance.yahoo.com": 3, "yahoo.com": 3, "investing.com": 3,
}


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url or "").netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def source_tier(item: dict) -> int:
    """Return 1 (best) .. 4 (noise) for a news item."""
    src = (item.get("source") or "").strip().lower()
    if src:
        if src in _TIER_1 or any(s in src for s in _TIER_1):
            return 1
        if src in _TIER_2 or any(s in src for s in _TIER_2):
            return 2
        if src in _TIER_3 or any(s in src for s in _TIER_3):
            return 3
    dom = _domain_of(item.get("url", ""))
    if dom in _DOMAIN_TIER:
        return _DOMAIN_TIER[dom]
    # BSE / NSE filings — quality depends on topic, default Tier 2.
    if src in {"bse", "nse"}:
        return 2
    return 3  # unknown source — middle ground, not noise


# ── 3. Topic classifier ────────────────────────────────────────

_TOPIC_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    ("earnings", [
        re.compile(r"\b(q[1-4]|quarterly|annual)\s+(results?|earnings?|numbers)\b", re.I),
        re.compile(r"\bearnings?\s+(call|report|preview|release|beat|miss)\b", re.I),
        re.compile(r"\b(net\s+profit|revenue|ebitda|topline|bottom\s*line)\b", re.I),
        re.compile(r"\b(profit|loss)\s+(rises?|falls?|grows?|jumps?|declines?)", re.I),
    ]),
    ("deal", [
        re.compile(r"\b(acquisition|acquires?|acquired|merger|merges?|demerger)\b", re.I),
        re.compile(r"\b(open\s+offer|buy(\s|-)?back|stake\s+sale|divest|spin(\s|-)?off)\b", re.I),
        re.compile(r"\b(jv|joint\s+venture|partnership|tie(\s|-)?up)\b", re.I),
        re.compile(r"\b(order\s+win|contract\s+(win|award)|bags?\s+order)\b", re.I),
    ]),
    ("governance", [
        re.compile(r"\b(board\s+meeting|appoint(s|ed|ment)|resign(s|ed|ation)|ceo|cfo|md|chairman)\b", re.I),
        re.compile(r"\b(dividend|bonus|stock\s+split|rights\s+issue|qip|preferential\s+issue)\b", re.I),
        re.compile(r"\b(agm|egm|postal\s+ballot)\b", re.I),
    ]),
    ("analyst-update", [
        re.compile(r"\b(brokerage|target\s+price|upgrade[ds]?|downgrade[ds]?|rating\s+(cut|raised|change))\b", re.I),
        re.compile(r"\b(buy|sell|hold|overweight|underweight|outperform|underperform)\s+(rating|call)\b", re.I),
    ]),
    ("regulatory", [
        re.compile(r"\b(sebi|rbi|cci|nclt|cbi|ed)\b.*\b(notice|order|action|probe|raid|approval)\b", re.I),
        re.compile(r"\b(insolvency|nclt\s+(order|petition)|moratorium|delisting)\b", re.I),
        re.compile(r"\b(scrip\s+code|listing\s+(approval|change)|compliance)\b", re.I),
    ]),
]

# Pure boilerplate that adds zero investor value (Tier 4 even if
# source is good).
_BOILERPLATE = [
    re.compile(r"\bnewspaper\s+advertisement\b", re.I),
    re.compile(r"\be(\s|-)?voting\b", re.I),
    re.compile(r"\bannual\s+secretarial\s+compliance\s+report\b", re.I),
    re.compile(r"\bsecretarial\s+compliance\s+report\b", re.I),
    re.compile(r"\bform\s+8-?k\b", re.I),  # US filing, irrelevant for IN stocks
    re.compile(r"\bregulation\s+30\b.*\bdisclosure\b", re.I),
    re.compile(r"\bcompliance\s+certificate\b", re.I),
    re.compile(r"\bintimation\s+(under|of)\s+regulation\b", re.I),
    re.compile(r"\b(book\s+closure|record\s+date)\s+intimation\b", re.I),
    re.compile(r"\bcopy\s+of\s+newspaper\b", re.I),
]


def classify_topic(item: dict) -> str:
    text = f"{item.get('headline','')} {item.get('summary','')}"
    if not text.strip():
        return "general"
    for tag, patterns in _TOPIC_PATTERNS:
        for pat in patterns:
            if pat.search(text):
                return tag
    return "general"


def is_boilerplate(item: dict) -> bool:
    text = f"{item.get('headline','')} {item.get('summary','')}"
    if not text.strip():
        return False
    return any(p.search(text) for p in _BOILERPLATE)


# ── Composite filter ──────────────────────────────────────────

# Topics worth keeping even if surfaced via a Tier 4 source.
_KEEP_TIER4_TOPICS = {"earnings", "deal", "governance"}


def annotate(item: dict, ticker: Optional[str] = None) -> dict:
    """Attach tier + topic fields. Pure (returns a new dict)."""
    out = dict(item)
    out["tier"] = source_tier(item)
    out["topic"] = classify_topic(item)
    return out


def filter_and_rank(
    items: Iterable[dict],
    ticker: Optional[str] = None,
    *,
    drop_boilerplate: bool = True,
) -> list[dict]:
    """
    Apply ticker-exact gate + tier ranking + boilerplate drop.
    Returns items sorted by (tier asc, published_at desc).
    """
    kept: list[dict] = []
    for raw in items or []:
        if drop_boilerplate and is_boilerplate(raw):
            continue
        if ticker and not matches_ticker(raw, ticker):
            continue
        ann = annotate(raw, ticker)
        if ann["tier"] >= 4 and ann["topic"] not in _KEEP_TIER4_TOPICS:
            continue
        kept.append(ann)

    def _key(it: dict):
        return (it.get("tier", 3), -_pub_epoch(it))

    kept.sort(key=_key)
    return kept


def _pub_epoch(item: dict) -> float:
    from datetime import datetime, timezone
    raw = item.get("published_at") or ""
    if not isinstance(raw, str) or not raw:
        return 0.0
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0
