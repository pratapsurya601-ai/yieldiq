"""Corporate-actions ticker alias resolver.

Single source of truth for demerged / renamed / delisted NSE listings.
Consulted by the ingest pipeline BEFORE hitting Yahoo/NSE, and by the
analysis router at read time so requests for retired symbols return a
structured redirect instead of an empty state.

Design goals
------------
- O(1) dict lookup; config is cached after first load.
- Cheap for the common case: an active ticker never touches the alias
  file at all (resolve_for_fetch returns the default .NS-suffixed
  Fetch result via the fast path).
- Config-driven. No hardcoded tickers in this module.
- Degrades safely: if the YAML is missing or malformed, every ticker
  is treated as `active` and the pipeline behaves as before.

The YAML lives at (searched in order):
    config/ticker_aliases.yaml
    data_pipeline/config/ticker_aliases.yaml
See that file for the schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional, Union
import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status literal — kept in sync with the schema in ticker_aliases.yaml.
# ---------------------------------------------------------------------------
AliasStatus = Literal[
    "active",
    "renamed",
    "nickname",
    "demerged",
    "demerged_pending",
    "delisted",
]

_VALID_STATUSES = {
    "active", "renamed", "nickname",
    "demerged", "demerged_pending", "delisted",
}

# Statuses that represent a real corporate action (i.e. should trigger
# the redirect gate in backend/routers/analysis.py). `nickname` is
# explicitly NOT in this set — it is purely a routing rewrite.
CORPORATE_ACTION_STATUSES = frozenset({"demerged", "demerged_pending", "delisted"})


# ---------------------------------------------------------------------------
# Resolve-result ADT
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Fetch:
    """Pipeline should fetch this Yahoo symbol (and attribute to `ticker`)."""
    symbol: str
    ticker: str


@dataclass(frozen=True)
class Skip:
    """Pipeline should skip this ticker silently. Reason is logged at INFO."""
    reason: str
    ticker: str


@dataclass(frozen=True)
class Redirect:
    """Pipeline should iterate each successor; read path should redirect."""
    ticker: str
    successors: list["Successor"]
    effective_date: Optional[str] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class Successor:
    ticker: str
    share_ratio: float = 1.0
    fetch_symbol: Optional[str] = None


ResolveResult = Union[Fetch, Skip, Redirect]


# ---------------------------------------------------------------------------
# Config loading (cached)
# ---------------------------------------------------------------------------
_CONFIG_SEARCH_PATHS = (
    "config/ticker_aliases.yaml",
    "data_pipeline/config/ticker_aliases.yaml",
)


def _project_root() -> Path:
    # data_pipeline/ticker_aliases.py -> parents[1] is repo root
    return Path(__file__).resolve().parents[1]


def _config_path() -> Optional[Path]:
    override = os.environ.get("YIELDIQ_TICKER_ALIASES_PATH")
    if override:
        p = Path(override)
        return p if p.exists() else None
    root = _project_root()
    for rel in _CONFIG_SEARCH_PATHS:
        p = root / rel
        if p.exists():
            return p
    return None


@lru_cache(maxsize=1)
def load_aliases() -> dict:
    """Load and cache the alias config.

    Returns an empty dict if the file is missing or unparseable — the
    system degrades to "everything is active" in that case.
    """
    path = _config_path()
    if path is None:
        logger.info("ticker_aliases: no config file found; all tickers treated as active")
        return {}
    try:
        import yaml  # lazy import — yaml isn't needed for active-only paths
    except ImportError:
        logger.warning("ticker_aliases: PyYAML not installed; treating all tickers as active")
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:  # malformed YAML, permission, etc.
        logger.error("ticker_aliases: failed to parse %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.error("ticker_aliases: config root is not a mapping in %s", path)
        return {}
    # Normalize keys to uppercase so lookups are case-insensitive on the
    # input side. Validate status at load time so bad config fails loudly
    # in tests rather than silently at runtime.
    normalized: dict[str, dict] = {}
    for raw_key, entry in data.items():
        key = str(raw_key).upper().strip()
        if not isinstance(entry, dict):
            logger.error("ticker_aliases: entry %s is not a mapping; skipping", key)
            continue
        status = entry.get("status", "active")
        if status not in _VALID_STATUSES:
            logger.error(
                "ticker_aliases: entry %s has invalid status %r; skipping", key, status
            )
            continue
        normalized[key] = entry
    return normalized


def _clear_cache() -> None:
    """Test hook — invalidate the cached config."""
    load_aliases.cache_clear()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_status(ticker: str) -> AliasStatus:
    """Return the alias status for a ticker. Default is 'active'."""
    if not ticker:
        return "active"
    entry = load_aliases().get(ticker.upper().strip())
    if not entry:
        return "active"
    return entry.get("status", "active")  # type: ignore[return-value]


def resolve_nickname(ticker: str) -> Optional[str]:
    """Return the canonical ticker for a `nickname` entry, else None.

    Read-path helper used by `backend/routers/analysis.py` to rewrite
    colloquial requests (e.g. `/analysis/HUL`) to the canonical ticker
    (`HINDUNILVR`) before any cache lookup or compute. Returns None for
    every status except `nickname` so the caller falls through unchanged.
    """
    if not ticker:
        return None
    entry = load_aliases().get(ticker.upper().strip())
    if not entry or entry.get("status") != "nickname":
        return None
    canonical = str(entry.get("canonical", "")).upper().strip()
    return canonical or None


def _default_fetch_symbol(ticker: str) -> str:
    """Mirror data_pipeline.xbrl.tickers.get_yf_symbol's default rule.

    We keep this local so ticker_aliases stays importable without a
    circular dep on the ingest package (which imports yfinance).
    """
    # Hard-coded specials matching tickers.get_yf_symbol.
    specials = {
        "M&M": "M&M.NS",
        "BAJAJ-AUTO": "BAJAJ-AUTO.NS",
        "MCDOWELL-N": "MCDOWELL-N.NS",
    }
    return specials.get(ticker, f"{ticker}.NS")


def resolve_for_fetch(ticker: str) -> ResolveResult:
    """Resolve a ticker to a fetch / skip / redirect instruction.

    Fast path: unknown ticker (not in alias file) -> Fetch(<ticker>.NS).
    No YAML parsing beyond the one-time cached load.
    """
    if not ticker:
        return Skip(reason="empty_ticker", ticker=ticker or "")
    key = ticker.upper().strip()
    aliases = load_aliases()
    entry = aliases.get(key)

    if not entry:
        return Fetch(symbol=_default_fetch_symbol(key), ticker=key)

    status = entry.get("status", "active")

    if status == "active":
        fetch_symbol = entry.get("fetch_symbol") or _default_fetch_symbol(key)
        return Fetch(symbol=fetch_symbol, ticker=key)

    if status == "renamed":
        fetch_symbol = entry.get("fetch_symbol") or _default_fetch_symbol(key)
        return Fetch(symbol=fetch_symbol, ticker=key)

    if status == "nickname":
        # Colloquial alias — rewrite to the canonical ticker entirely.
        # The returned `ticker` is the CANONICAL one (not the nickname),
        # so downstream cache keys / response payloads / analytics events
        # all attribute against the real entity. Request for "HUL"
        # produces a response keyed on "HINDUNILVR".
        canonical = str(entry.get("canonical", "")).upper().strip()
        if not canonical:
            # Misconfigured entry — degrade to fast path so we don't
            # 500 a user request because of a YAML typo.
            logger.error(
                "ticker_aliases: nickname %s missing `canonical:`; falling back to default fetch",
                key,
            )
            return Fetch(symbol=_default_fetch_symbol(key), ticker=key)
        # If the canonical itself has a YAML entry (e.g. another rename),
        # honour its fetch_symbol; cap recursion at 1 hop for simplicity.
        canonical_entry = aliases.get(canonical)
        if canonical_entry and canonical_entry.get("status") == "renamed":
            fetch_symbol = canonical_entry.get("fetch_symbol") or _default_fetch_symbol(canonical)
        else:
            fetch_symbol = _default_fetch_symbol(canonical)
        return Fetch(symbol=fetch_symbol, ticker=canonical)

    if status == "delisted":
        return Skip(reason="delisted", ticker=key)

    if status == "demerged_pending":
        return Skip(reason="demerged_pending", ticker=key)

    if status == "demerged":
        raw_successors = entry.get("successors") or []
        successors = [
            Successor(
                ticker=str(s.get("ticker", "")).upper().strip(),
                share_ratio=float(s.get("share_ratio", 1.0)),
                fetch_symbol=s.get("fetch_symbol"),
            )
            for s in raw_successors
            if s and s.get("ticker")
        ]
        # If config lists no fetchable successors, treat as pending so
        # the pipeline skips cleanly rather than iterating no-ops.
        if not any(s.fetch_symbol for s in successors):
            return Skip(reason="demerged_no_fetch_symbols", ticker=key)
        eff = entry.get("effective_date")
        if eff is not None and not isinstance(eff, str):
            eff = eff.isoformat()
        return Redirect(
            ticker=key,
            successors=successors,
            effective_date=eff,
            note=entry.get("note"),
        )

    # Unknown status — defensive default.
    return Fetch(symbol=_default_fetch_symbol(key), ticker=key)


def get_successors_payload(ticker: str) -> Optional[dict]:
    """Shape the read-path payload for demerged/delisted tickers.

    Returns None for active/renamed tickers. The analysis router uses
    this to emit a structured redirect response without breaking the
    existing AnalysisResponse shape (see backend/routers/analysis.py).
    """
    key = ticker.upper().strip() if ticker else ""
    entry = load_aliases().get(key)
    if not entry:
        return None
    status = entry.get("status", "active")
    # `nickname` is a routing-only alias, not a corp action — never emit
    # a redirect payload for it. Treat it identically to `active`.
    if status in ("active", "renamed", "nickname"):
        return None
    successors = [
        {
            "ticker": str(s.get("ticker", "")).upper().strip(),
            "share_ratio": float(s.get("share_ratio", 1.0)),
            "fetch_symbol": s.get("fetch_symbol"),
        }
        for s in (entry.get("successors") or [])
        if s and s.get("ticker")
    ]
    # YAML's safe_load converts YYYY-MM-DD into datetime.date; coerce
    # to ISO-format string so the router payload is JSON-serializable.
    eff = entry.get("effective_date")
    if eff is not None and not isinstance(eff, str):
        eff = eff.isoformat()
    return {
        "status": status,
        "ticker": key,
        "successors": successors,
        "effective_date": eff,
        "note": entry.get("note"),
    }
