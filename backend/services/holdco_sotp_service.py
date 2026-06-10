# backend/services/holdco_sotp_service.py
"""Holdco Sum-of-the-Parts (SOTP) Service — T1.4 Phase A (2026-06-10).

Standalone valuation service for Indian holding companies (BAJAJHLDNG,
TATAINVEST, PILANIINVS, etc.). DCF-on-the-holdco is meaningless for
pure pass-through vehicles whose only cash flows are dividends from
listed subsidiaries — the right framework is to sum the attributable
value of each underlying stake, apply a holdco discount, then add/
subtract the holdco's own balance-sheet net cash.

  SOTP_value = Σ_i (stake_pct × underlying_market_cap × (1 - discount))
              + holdco_net_cash
              - holdco_debt

The holdco discount captures three real-world frictions:

  - Illiquidity — holdco shares trade thin vs. the underlying floats.
  - Tax leakage — dividends from sub to holdco then sub to investor
    are taxed twice in many regimes.
  - Governance overhead — separate boards, audits, management costs
    that erode realized pass-through value.

Per-sector discount defaults reflect the empirical Indian-market
range (20% for clean financial holdcos, 25-30% for conglomerates,
30%+ for opaque media holdcos). These are tunable parameters, not
fixed constants — production calibration should refine them against
realized NAV-to-discount-rate trading bands.

Phase A is intentionally narrow:

  - Service module + dataclasses + ``compute_sotp``.
  - No wiring into composite_iv_service.py (Phase B).
  - No live market-cap fetcher (production needs a Yahoo/NSE adapter).
  - The data_provider callable injection pattern lets tests pass
    canned market caps without any DB / cache / network. The seed
    file ``backend/data/holdco_underlyings.json`` carries the
    per-holdco stake structure; production wiring will inject a
    provider that resolves underlying tickers to live market caps.

Phase B (separate PR) will:

  - Route holdco tickers through compute_sotp in composite_iv_service.py
    instead of the current DCF-only fallback.
  - Surface a per-component SOTP breakdown on the analysis page.
  - Update CACHE_VERSION / manifest accordingly.

Design notes
------------
- Never raises. Bad / missing data on a single underlying degrades
  to a skipped component plus a sanity warning — not an exception.
  The aggregate value continues to be computed against the components
  that resolved cleanly.
- The holdco discount is APPLIED PER COMPONENT (not to the aggregate)
  so per-component records can show both pre- and post-discount
  attributable value. This matches how analysts present a SOTP
  table: each row shows the discount working on that line.
- Unlisted underlyings (set ``is_listed=False``) are skipped from
  the aggregate in Phase A and surface a warning explaining that
  book value / last funding round is the right fallback. Phase B
  may add that fallback once book-value plumbing exists.
- Plain dataclasses + ``to_dict`` helper for JSON-safe serialization
  so the Phase B router can return the result directly via FastAPI
  without an additional Pydantic conversion layer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Callable, Iterable, Optional

logger = logging.getLogger("yieldiq.holdco_sotp")


# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

# Default holdco discount when no sector tuning applies. 25% is the
# middle of the empirical 20-30% Indian-market range and matches how
# sell-side analyst SOTP notes typically frame "plain" holdco NAV.
DEFAULT_HOLDCO_DISCOUNT_PCT = 25.0

# Sector-tuned discount defaults. Keys are the bare ticker; rationale
# captured in get_sector_holdco_discount's docstring. Tickers absent
# from this map fall through to DEFAULT_HOLDCO_DISCOUNT_PCT.
_SECTOR_DISCOUNT_OVERRIDES: dict[str, float] = {
    # Pure financial holdcos — clean pass-through to listed subs,
    # minimal overhead, well-understood underlyings. Tighter band.
    "BAJAJHLDNG": 22.0,
    "MAHSCOOTER": 22.0,
    # Tata Investment Corporation — financial holdco but with a
    # wider underlying basket (TCS, TATAMOTORS, TATASTEEL, TITAN,
    # TATAPOWER, etc.) and Tata Sons overhead. Mid-band.
    "TATAINVEST": 28.0,
    # Conglomerate / diversified-asset holdcos — wider mix of
    # unlisted assets, harder to value precisely. Wider band.
    "GRASIM": 30.0,
    "PILANIINVS": 30.0,
    "KAMAHOLD": 30.0,
    "SUMMITSEC": 30.0,
    "WILLIAMAGR": 30.0,
    "MCLEODRUSS": 30.0,
    "GAYAHWS": 30.0,
    "MOIL": 30.0,
    # Media holdcos — opaque underlying value (content libraries,
    # broadcasting licenses), historically distressed governance.
    "NDTV": 35.0,
    "NETWORK18": 35.0,
}


# ─────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────


@dataclass
class UnderlyingHolding:
    """A single line item in a holdco's SOTP table.

    Fields:
      ticker: underlying NSE ticker (bare symbol, no .NS suffix).
      stake_pct: holdco's ownership stake in the underlying, 0-100.
                 e.g. 33.4 means the holdco owns 33.4% of the underlying.
      underlying_market_cap_inr_cr: the underlying's full market cap
                 in INR Crores. The attributable value to the holdco
                 is (stake_pct/100) × this. None for unlisted /
                 unresolvable underlyings; surfaces a warning.
      is_listed: True for NSE/BSE-listed underlyings; False for
                 private / unlisted (skipped from aggregate in
                 Phase A; book-value fallback is Phase B work).
    """
    ticker: str
    stake_pct: float
    underlying_market_cap_inr_cr: Optional[float] = None
    is_listed: bool = True


@dataclass
class HoldcoSOTPInputs:
    """Inputs to compute_sotp for a single holdco.

    Fields:
      holdco_ticker: the holdco's bare NSE ticker (e.g. BAJAJHLDNG).
      underlyings: list of UnderlyingHolding rows.
      holdco_net_cash_inr_cr: positive = net cash on holdco BS;
                              negative = net debt. Added to the
                              aggregate after discount.
      holdco_shares_outstanding: holdco shares outstanding in CRORES
                              (not raw millions / units). Used to
                              derive per-share value. 0 = unknown;
                              per_share returns None.
      holdco_discount_pct: 0-100; default 25%. Used when
                           sector_holdco_discount_override is None.
      sector_holdco_discount_override: explicit override that beats
                           both holdco_discount_pct AND the sector
                           default. Use this when the caller has a
                           more authoritative number (e.g. recent
                           analyst median) than the seed default.
    """
    holdco_ticker: str
    underlyings: list[UnderlyingHolding]
    holdco_net_cash_inr_cr: float = 0.0
    holdco_shares_outstanding: float = 0.0
    holdco_discount_pct: float = DEFAULT_HOLDCO_DISCOUNT_PCT
    sector_holdco_discount_override: Optional[float] = None


@dataclass
class HoldcoSOTPResult:
    """Output of compute_sotp.

    Fields:
      sotp_value_inr_cr: aggregate SOTP value in INR Crores AFTER
                         discount and after net-cash adjustment.
                         None when no underlying resolved.
      sotp_per_share: aggregate divided by shares outstanding × 1cr,
                      i.e. value in INR per share. None when shares
                      outstanding is 0 / unknown.
      components: per-underlying audit trail with fields:
                  - ticker
                  - stake_pct
                  - underlying_market_cap_inr_cr
                  - attributable_value_inr_cr  (pre-discount)
                  - post_discount_value_inr_cr (after holdco discount)
                  - is_listed
                  - skipped_reason             (None when included)
      holdco_discount_applied_pct: the effective discount used (0-100).
      holdco_net_cash_applied: the net-cash delta added.
      method: "sotp_pure" — all underlyings listed + resolved
              "sotp_with_unlisted_fallback" — some unlisted skipped
              "unavailable" — nothing resolved; sotp_value None
      sanity_warnings: human-readable strings explaining any quirk
                       (missing mcaps, distress, zero shares, etc).
    """
    sotp_value_inr_cr: Optional[float]
    sotp_per_share: Optional[float]
    components: list[dict]
    holdco_discount_applied_pct: float
    holdco_net_cash_applied: float
    method: str
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────────────


def get_sector_holdco_discount(holdco_ticker: str) -> float:
    """Return the sector-tuned holdco discount default (0-100).

    Buckets:

      - Pure financial holdcos (BAJAJHLDNG, MAHSCOOTER): 22%
        — clean pass-through to listed subs, minimal overhead.
      - Mid-band financial holdcos (TATAINVEST): 28%
        — wider underlying basket, Tata Sons overhead.
      - Conglomerate / diversified-asset holdcos (GRASIM,
        PILANIINVS, KAMAHOLD, SUMMITSEC, WILLIAMAGR, MCLEODRUSS,
        GAYAHWS, MOIL): 30%
        — wider mix of unlisted assets, harder to value precisely.
      - Media holdcos (NDTV, NETWORK18): 35%
        — opaque underlying value, historical governance issues.
      - Default (any ticker not in the override map): 25%
        — the empirical middle of the Indian-market band.

    Returns DEFAULT_HOLDCO_DISCOUNT_PCT when the ticker isn't in
    the override map (covers tickers that pass is_holdco_sotp_applicable
    but lack a per-sector default).
    """
    if not isinstance(holdco_ticker, str):
        return DEFAULT_HOLDCO_DISCOUNT_PCT
    clean = holdco_ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    return _SECTOR_DISCOUNT_OVERRIDES.get(clean, DEFAULT_HOLDCO_DISCOUNT_PCT)


def is_holdco_sotp_applicable(
    ticker: str,
    holding_companies_set: Iterable[str],
) -> tuple[bool, str]:
    """Decide whether SOTP applies to ``ticker``.

    Returns (True, "ticker classified as holdco") when ``ticker`` is
    in ``holding_companies_set``. Otherwise returns (False, reason).
    ``holding_companies_set`` is typically the
    HOLDING_COMPANIES frozenset/set from
    ``backend.services.analysis.constants``; the parameter is typed
    as ``Iterable[str]`` to accept either set/frozenset/list without
    forcing the caller to convert.

    Defensive against None / non-string ticker input.
    """
    if not isinstance(ticker, str) or not ticker.strip():
        return False, "ticker missing or non-string"
    clean = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    try:
        membership = clean in holding_companies_set
    except TypeError:
        return False, "holding_companies_set is not iterable"
    if membership:
        return True, "ticker classified as holdco"
    return False, (
        f"{clean} is not in HOLDING_COMPANIES — SOTP only applies to "
        "pure holding companies; operating-company tickers should use "
        "DCF + peer multiples via the standard composite IV path"
    )


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────


def _safe_float(value) -> Optional[float]:
    """Coerce ``value`` to a finite float. Returns None on failure /
    NaN / infinity. NaN propagates poison through aggregates, so we
    reject it at the boundary."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _resolve_discount(inputs: HoldcoSOTPInputs) -> float:
    """Resolve the effective holdco discount.

    Precedence:
      1. ``sector_holdco_discount_override`` (when set + valid)
      2. ``holdco_discount_pct`` from inputs (when not the default sentinel)
      3. ``get_sector_holdco_discount(ticker)`` (sector lookup)

    The intent is that callers who explicitly set holdco_discount_pct
    to a non-default value get THEIR override; callers who left it
    at the default DEFAULT_HOLDCO_DISCOUNT_PCT get the sector tune;
    callers who passed sector_holdco_discount_override get that
    regardless. Returns a value clamped to [0, 100].
    """
    raw: Optional[float]
    if inputs.sector_holdco_discount_override is not None:
        raw = _safe_float(inputs.sector_holdco_discount_override)
    elif (
        inputs.holdco_discount_pct is not None
        and _safe_float(inputs.holdco_discount_pct) is not None
        and float(inputs.holdco_discount_pct) != DEFAULT_HOLDCO_DISCOUNT_PCT
    ):
        raw = _safe_float(inputs.holdco_discount_pct)
    else:
        # Caller left at the sentinel default — defer to sector tune.
        raw = get_sector_holdco_discount(inputs.holdco_ticker)

    if raw is None:
        raw = DEFAULT_HOLDCO_DISCOUNT_PCT
    # Clamp to [0, 100] — a negative discount is a premium (nonsensical
    # for holdcos as a category); >100% would yield negative attributable
    # value (also nonsensical).
    if raw < 0:
        return 0.0
    if raw > 100:
        return 100.0
    return float(raw)


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


def compute_sotp(inputs: HoldcoSOTPInputs) -> HoldcoSOTPResult:
    """Compute the SOTP valuation for a holdco.

    Sums attributable value across listed underlyings, applies the
    resolved holdco discount per component, adds holdco net cash
    (subtracts net debt), and divides by shares outstanding for
    per-share value.

    Defensive contract:
      - Never raises. Bad rows are skipped with a warning.
      - Returns a HoldcoSOTPResult with method="unavailable" and
        sotp_value_inr_cr=None when nothing resolved.
      - Unlisted underlyings (is_listed=False) are skipped from the
        aggregate and surface a warning.
      - holdco_shares_outstanding=0 produces sotp_per_share=None
        plus a warning, but aggregate is still computed.
      - Negative SOTP (when net debt > aggregate attributable value)
        is allowed — it's a real signal of distress, surfaced as a
        warning rather than masked.
    """
    warnings: list[str] = []

    # ── Discount resolution ───────────────────────────────────────
    discount_pct = _resolve_discount(inputs)
    discount_fraction = discount_pct / 100.0

    # ── Net cash adjustment ───────────────────────────────────────
    net_cash = _safe_float(inputs.holdco_net_cash_inr_cr)
    if net_cash is None:
        net_cash = 0.0
        warnings.append(
            "holdco_net_cash_inr_cr was non-numeric or NaN — treated as 0; "
            "balance-sheet adjustment skipped"
        )

    # ── Walk underlyings ──────────────────────────────────────────
    components: list[dict] = []
    aggregate_post_discount = 0.0
    listed_resolved = 0
    listed_total = 0
    unlisted_skipped = 0
    underlyings = list(inputs.underlyings or [])

    for u in underlyings:
        if not isinstance(u, UnderlyingHolding):
            warnings.append(
                "skipped a row that wasn't an UnderlyingHolding instance"
            )
            continue

        # Build a base component record so the audit trail captures
        # every input row, included or skipped.
        base = {
            "ticker": str(u.ticker) if u.ticker is not None else "",
            "stake_pct": _safe_float(u.stake_pct),
            "underlying_market_cap_inr_cr": _safe_float(u.underlying_market_cap_inr_cr),
            "attributable_value_inr_cr": None,
            "post_discount_value_inr_cr": None,
            "is_listed": bool(u.is_listed),
            "skipped_reason": None,
        }

        # Unlisted — Phase A skip + warning.
        if not u.is_listed:
            unlisted_skipped += 1
            base["skipped_reason"] = (
                "Unlisted underlying not valued in Phase A — needs book "
                "value or last funding fallback"
            )
            warnings.append(
                f"underlying {base['ticker']!r}: unlisted — skipped from "
                "aggregate (Phase A doesn't fallback to book value yet)"
            )
            components.append(base)
            continue

        listed_total += 1

        stake = base["stake_pct"]
        mcap = base["underlying_market_cap_inr_cr"]

        if stake is None or stake <= 0:
            base["skipped_reason"] = "stake_pct missing or non-positive"
            warnings.append(
                f"underlying {base['ticker']!r}: stake_pct missing or "
                "non-positive — skipped from aggregate"
            )
            components.append(base)
            continue

        if mcap is None or mcap <= 0:
            base["skipped_reason"] = (
                "underlying market cap missing — needs live data_provider "
                "or fallback to book value (NOT IMPLEMENTED Phase A)"
            )
            warnings.append(
                f"underlying {base['ticker']!r}: market cap missing — "
                "fallback to book value (NOT IMPLEMENTED Phase A)"
            )
            components.append(base)
            continue

        # Defensive: stakes > 100% are a data error. Cap and warn —
        # don't silently inflate the SOTP.
        if stake > 100:
            warnings.append(
                f"underlying {base['ticker']!r}: stake_pct={stake} > 100 — "
                "capped to 100"
            )
            stake = 100.0

        attributable = (stake / 100.0) * mcap
        post_discount = attributable * (1.0 - discount_fraction)

        base["attributable_value_inr_cr"] = attributable
        base["post_discount_value_inr_cr"] = post_discount
        components.append(base)
        aggregate_post_discount += post_discount
        listed_resolved += 1

    # ── Method classification ─────────────────────────────────────
    if listed_resolved == 0:
        method = "unavailable"
    elif unlisted_skipped > 0 or listed_resolved < listed_total:
        method = "sotp_with_unlisted_fallback"
    else:
        method = "sotp_pure"

    # ── Aggregate ─────────────────────────────────────────────────
    if listed_resolved == 0:
        sotp_value: Optional[float] = None
        sotp_per_share: Optional[float] = None
        if not underlyings:
            warnings.append(
                "no underlyings supplied — SOTP requires at least one "
                "listed stake row"
            )
        else:
            warnings.append(
                "no listed underlying resolved a market cap — SOTP "
                "unavailable; provide a data_provider that returns live "
                "market caps or seed the inputs directly"
            )
    else:
        sotp_value = aggregate_post_discount + net_cash
        if sotp_value < 0:
            warnings.append(
                f"computed SOTP is negative ({sotp_value:.1f} Cr) — net "
                "debt exceeds attributable underlying value; the holdco "
                "may be in distress or carrying obligations the listed-"
                "sub stakes alone cannot cover"
            )

        shares = _safe_float(inputs.holdco_shares_outstanding)
        if shares is None or shares <= 0:
            sotp_per_share = None
            warnings.append(
                "holdco_shares_outstanding is 0 or missing — per-share "
                "value not derived; aggregate value still returned"
            )
        else:
            # shares are in CRORES; sotp_value is in CRORES.
            # value/share = (Cr) / (cr_shares) = INR/share directly.
            sotp_per_share = sotp_value / shares

    return HoldcoSOTPResult(
        sotp_value_inr_cr=sotp_value,
        sotp_per_share=sotp_per_share,
        components=components,
        holdco_discount_applied_pct=discount_pct,
        holdco_net_cash_applied=net_cash,
        method=method,
        sanity_warnings=warnings,
    )


def to_dict(result: HoldcoSOTPResult) -> dict:
    """JSON-safe serialization of a HoldcoSOTPResult.

    Components are already dicts (built that way during compute_sotp)
    so this is a thin asdict-equivalent that round-trips through
    ``json.dumps`` without a custom encoder.
    """
    return {
        "sotp_value_inr_cr": result.sotp_value_inr_cr,
        "sotp_per_share": result.sotp_per_share,
        "components": list(result.components),
        "holdco_discount_applied_pct": result.holdco_discount_applied_pct,
        "holdco_net_cash_applied": result.holdco_net_cash_applied,
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings),
    }


# ─────────────────────────────────────────────────────────────────
# data_provider injection hook (Phase B will use this)
# ─────────────────────────────────────────────────────────────────


def resolve_market_caps(
    underlyings: list[UnderlyingHolding],
    data_provider: Optional[Callable[[str], Optional[float]]] = None,
) -> list[UnderlyingHolding]:
    """Return a NEW list of UnderlyingHolding rows with market caps
    populated via ``data_provider``.

    Phase A doesn't ship a default provider — production wiring (Phase
    B) will inject one that resolves bare NSE tickers to live market
    caps in INR Crores. Phase A tests pass canned providers (e.g.
    a dict-lookup lambda) without instantiating any DB / cache layer.

    Defensive: if data_provider is None or raises on any row, that
    row's market cap stays at whatever the input row had (typically
    None, which compute_sotp will then surface as a sanity warning).
    """
    if data_provider is None:
        # Round-trip the inputs unchanged — caller already populated
        # the market caps, or they'll come through as None and the
        # warning fires downstream.
        return list(underlyings or [])
    resolved: list[UnderlyingHolding] = []
    for u in underlyings or []:
        if not isinstance(u, UnderlyingHolding):
            continue
        if not u.is_listed:
            resolved.append(u)
            continue
        if u.underlying_market_cap_inr_cr is not None:
            # Already populated — preserve.
            resolved.append(u)
            continue
        try:
            mcap = data_provider(u.ticker)
        except Exception as exc:
            logger.warning(
                "holdco_sotp: data_provider raised for %s: %s",
                u.ticker, exc,
            )
            mcap = None
        resolved.append(UnderlyingHolding(
            ticker=u.ticker,
            stake_pct=u.stake_pct,
            underlying_market_cap_inr_cr=_safe_float(mcap),
            is_listed=u.is_listed,
        ))
    return resolved
