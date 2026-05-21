"""Tax-loss harvesting calculator (Day-90).

Pure-Python tax math: takes a list of holdings with (ticker, qty,
avg_cost, current_price, acquired_on), classifies each into the
ST/LT bucket per Indian capital-gains rules (FY 2025-26+), identifies
unrealized-loss positions as harvesting CANDIDATES, and estimates the
tax that would be saved if the loss were realized in the current FY.

NOT investment advice. This is a calculator. The frontend frames it
as a tax-estimation tool — see SEBI lexicon rules in the page copy.

Indian capital-gains rules baked in:
  - STCG on listed equity (held < 12 months) taxed at 20% (post-FY24-25
    Budget hike from 15%).
  - LTCG on listed equity (held >= 12 months) taxed at 12.5% (up from
    10%), with a Rs 1,25,000 per-FY exemption.
  - Loss offsets:
      STCL  -> can offset BOTH STCG and LTCG gains
      LTCL  -> can offset ONLY LTCG gains
  - Unused capital losses carry forward 8 assessment years (not
    modelled here; surfaced as caveat in the UI).
  - India has NO wash-sale rule — same-day repurchase is permitted.

Boundary discipline:
  Holding period is computed in WHOLE CALENDAR MONTHS using the
  acquired_on date vs the "as-of" date (today by default). A position
  acquired exactly 12 months ago is LONG-TERM (>= 12mo). One day
  short = SHORT-TERM. This boundary is tested explicitly because an
  off-by-one-day bug here would directly cost users money.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import Optional, Iterable

# Tax constants — kept LOCAL so this module is self-contained and easy
# to unit-test. The realized-gains tax_service.py uses identical
# constants; if either changes, update both (small surface, intentional
# duplication so an isolated test failure pinpoints which path broke).
STCG_RATE = 0.20            # 20% on STCG (listed equity, with STT)
LTCG_RATE = 0.125           # 12.5% on LTCG above exemption
LTCG_EXEMPTION_RS = 125_000  # Rs 1.25L per FY (all LTCG combined)
LT_HOLDING_MONTHS = 12      # >= 12 calendar months = long-term


@dataclass
class TLHSuggestion:
    ticker: str
    qty: float
    avg_cost: float
    current_price: float
    unrealized_loss: float        # always > 0 for a candidate
    holding_period_months: int    # whole months, floor
    tax_bucket: str               # "ST" or "LT"
    estimated_tax_saved: float    # >= 0
    rationale: str

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_date(value) -> Optional[date]:
    """Coerce ISO strings / datetimes / dates to date. Returns None if
    we can't parse — caller treats unknown buy date as ineligible."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    # Try ISO date / ISO datetime / RFC3339 with Z suffix.
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:len(fmt) + 6 if "%f" in fmt else len(s)], fmt).date()
        except ValueError:
            continue
    # Last resort: fromisoformat handles tz-aware ISO with offset.
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        return None


def months_held(acquired_on: date, as_of: date) -> int:
    """Whole calendar months between acquired_on and as_of (floor).

    A position bought on 2024-01-15 and evaluated on 2025-01-15 has
    been held exactly 12 months -> LT. Same position evaluated on
    2025-01-14 has 11 months -> ST. This matches CBDT's "held for more
    than 12 months" wording (interpreted as >= 12 calendar months
    inclusive of acquisition-day anniversary).
    """
    if as_of < acquired_on:
        return 0
    months = (as_of.year - acquired_on.year) * 12 + (as_of.month - acquired_on.month)
    # If the day-of-month hasn't reached the acquisition day, we're
    # still inside the previous month.
    if as_of.day < acquired_on.day:
        months -= 1
    return max(0, months)


def classify_bucket(acquired_on: Optional[date], as_of: date) -> str:
    """Return "LT" if held >= 12 calendar months, else "ST".

    If acquired_on is unknown, defaults to "ST" — the conservative
    bucket (higher tax rate -> higher estimated saving on a loss). The
    UI surfaces the missing-date caveat per-row.
    """
    if acquired_on is None:
        return "ST"
    return "LT" if months_held(acquired_on, as_of) >= LT_HOLDING_MONTHS else "ST"


def fy_for_date(d: date) -> str:
    """Indian financial year label, e.g. 2026-04-05 -> 'FY26-27'.

    FY runs 1-Apr through 31-Mar. A date in Jan-Mar belongs to the FY
    that STARTED the previous April.
    """
    start_year = d.year if d.month >= 4 else d.year - 1
    end_year = (start_year + 1) % 100
    return f"FY{start_year % 100:02d}-{end_year:02d}"


def _bucket_rate(bucket: str) -> float:
    return STCG_RATE if bucket == "ST" else LTCG_RATE


def compute_suggestions(
    holdings: Iterable[dict],
    realized_stcg_this_fy: float = 0.0,
    realized_ltcg_this_fy: float = 0.0,
    as_of: Optional[date] = None,
) -> dict:
    """Build TLH suggestions for the given portfolio.

    Args:
      holdings: iterable of dicts with at least:
          ticker (str), qty (float), avg_cost (float),
          current_price (float), acquired_on (date / ISO str / None)
      realized_stcg_this_fy: net realized STCG gains booked YTD in this
          FY. Default 0 (we have no trade history yet — documented
          caveat). Positive = net gain to offset; negative = already
          in loss.
      realized_ltcg_this_fy: same, for LTCG.
      as_of: evaluation date. Default = today (UTC date).

    Returns:
      {
        "as_of": "2026-05-22",
        "fy": "FY26-27",
        "suggestions": [TLHSuggestion.to_dict(), ...],   # ranked desc
        "totals": {
            "candidate_count": int,
            "gross_unrealized_loss": float,
            "estimated_tax_saved": float,
        },
        "context": {
            "realized_stcg_this_fy": float,
            "realized_ltcg_this_fy": float,
            "ltcg_exemption_rs": LTCG_EXEMPTION_RS,
            "stcg_rate_pct": 20.0,
            "ltcg_rate_pct": 12.5,
            "caveats": [str, ...],
        }
      }
    """
    as_of = as_of or datetime.utcnow().date()
    fy = fy_for_date(as_of)

    # Remaining gain that a fresh loss could offset, by bucket.
    # STCL can offset STCG + LTCG; LTCL can only offset LTCG.
    # Start with the user's stated realized FY position, then deduct
    # as we "apply" each candidate suggestion in rank order.
    remaining_stcg = max(0.0, float(realized_stcg_this_fy or 0.0))
    remaining_ltcg = max(0.0, float(realized_ltcg_this_fy or 0.0))

    # LTCG above the Rs 1.25L exemption is the only LTCG actually
    # TAXED — so the offsetting benefit is capped at the taxable slice.
    # If the user's net LTCG is below the exemption, a fresh LTCL has
    # zero immediate cash benefit (but does carry forward 8 AYs).
    taxable_ltcg_remaining = max(0.0, remaining_ltcg - LTCG_EXEMPTION_RS)

    raw_candidates: list[dict] = []
    caveats: list[str] = []
    missing_date_count = 0

    for h in holdings:
        ticker = (h.get("ticker") or "").strip()
        if not ticker:
            continue
        try:
            qty = float(h.get("qty") or h.get("quantity") or 0)
            avg_cost = float(h.get("avg_cost") or h.get("entry_price") or 0)
            current_price = float(h.get("current_price") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0 or avg_cost <= 0 or current_price <= 0:
            # Can't compute P&L without all three. Skip silently — the
            # holdings table already surfaces missing data elsewhere.
            continue

        unrealized = (current_price - avg_cost) * qty
        if unrealized >= 0:
            # Not a harvesting candidate. The calculator only surfaces
            # positions where realizing the position would create a
            # deductible loss.
            continue

        loss = -unrealized  # positive number

        acquired = _parse_date(h.get("acquired_on") or h.get("saved_at"))
        if acquired is None:
            missing_date_count += 1
        bucket = classify_bucket(acquired, as_of)
        months = months_held(acquired, as_of) if acquired else 0

        raw_candidates.append({
            "ticker": ticker,
            "qty": qty,
            "avg_cost": round(avg_cost, 2),
            "current_price": round(current_price, 2),
            "unrealized_loss": round(loss, 2),
            "holding_period_months": months,
            "tax_bucket": bucket,
            # Pre-rank tax-saved estimate uses the bucket's marginal
            # rate against full loss; we'll refine to the offset-capped
            # value once we sort and consume the FY-gain budget.
            "raw_tax_saved": loss * _bucket_rate(bucket),
            "acquired_known": acquired is not None,
        })

    # Rank by gross potential first (raw_tax_saved DESC). Then walk in
    # order, consuming the FY-gain budget. ST losses are scarcer (offset
    # both buckets, higher rate) so giving them rank priority by raw
    # saving naturally surfaces the highest-value candidates.
    raw_candidates.sort(key=lambda c: c["raw_tax_saved"], reverse=True)

    suggestions: list[dict] = []
    gross_loss = 0.0
    total_saved = 0.0

    for c in raw_candidates:
        loss = c["unrealized_loss"]
        bucket = c["tax_bucket"]
        gross_loss += loss

        # Compute the OFFSET-CAPPED tax saving. A loss only saves tax
        # to the extent the user has matching gains to offset; surplus
        # carries forward (modelled as zero immediate saving but
        # documented in the rationale).
        if bucket == "ST":
            # STCL offsets STCG first (same-bucket, higher rate ->
            # better ROI), then spills into taxable LTCG.
            offset_st = min(loss, remaining_stcg)
            spill = loss - offset_st
            offset_lt = min(spill, taxable_ltcg_remaining)
            remaining_stcg -= offset_st
            taxable_ltcg_remaining -= offset_lt
            remaining_ltcg = max(0.0, remaining_ltcg - offset_lt)
            saved = offset_st * STCG_RATE + offset_lt * LTCG_RATE
            carry = loss - offset_st - offset_lt
            rationale = _rationale_st(offset_st, offset_lt, carry, fy)
        else:
            # LTCL offsets only LTCG, and only the TAXABLE slice (above
            # the Rs 1.25L exemption) yields cash savings this FY.
            offset_lt = min(loss, taxable_ltcg_remaining)
            taxable_ltcg_remaining -= offset_lt
            remaining_ltcg = max(0.0, remaining_ltcg - offset_lt)
            saved = offset_lt * LTCG_RATE
            carry = loss - offset_lt
            rationale = _rationale_lt(offset_lt, carry, fy)

        total_saved += saved
        suggestions.append({
            "ticker": c["ticker"],
            "qty": c["qty"],
            "avg_cost": c["avg_cost"],
            "current_price": c["current_price"],
            "unrealized_loss": c["unrealized_loss"],
            "holding_period_months": c["holding_period_months"],
            "tax_bucket": bucket,
            "estimated_tax_saved": round(saved, 2),
            "rationale": rationale,
            "acquired_known": c["acquired_known"],
        })

    # Re-rank final list by estimated_tax_saved DESC so the highest-
    # immediate-benefit suggestions float to the top. Ties broken by
    # gross loss (larger loss = larger carry-forward, still useful).
    suggestions.sort(
        key=lambda s: (s["estimated_tax_saved"], s["unrealized_loss"]),
        reverse=True,
    )

    if missing_date_count > 0:
        caveats.append(
            f"{missing_date_count} holding(s) had no acquisition date "
            "available; treated as short-term (conservative). Edit the "
            "holding to set an acquisition date for accurate bucketing."
        )
    if realized_stcg_this_fy == 0 and realized_ltcg_this_fy == 0:
        caveats.append(
            f"No realized gains supplied for {fy}; tax-saved estimates "
            "assume any harvested loss will be carried forward (8 AYs) "
            "unless you book offsetting gains this FY."
        )

    return {
        "as_of": as_of.isoformat(),
        "fy": fy,
        "suggestions": suggestions,
        "totals": {
            "candidate_count": len(suggestions),
            "gross_unrealized_loss": round(gross_loss, 2),
            "estimated_tax_saved": round(total_saved, 2),
        },
        "context": {
            "realized_stcg_this_fy": round(float(realized_stcg_this_fy or 0.0), 2),
            "realized_ltcg_this_fy": round(float(realized_ltcg_this_fy or 0.0), 2),
            "ltcg_exemption_rs": LTCG_EXEMPTION_RS,
            "stcg_rate_pct": STCG_RATE * 100,
            "ltcg_rate_pct": LTCG_RATE * 100,
            "caveats": caveats,
        },
    }


def _rationale_st(offset_st: float, offset_lt: float, carry: float, fy: str) -> str:
    """SEBI-clean rationale string for a short-term loss candidate.

    Uses calculator language only — "could offset", "estimated",
    "candidate for harvesting" — never "buy", "sell", "should",
    "recommend"."""
    parts: list[str] = []
    if offset_st > 0:
        parts.append(f"could offset ₹{_fmt(offset_st)} of {fy} STCG at 20%")
    if offset_lt > 0:
        parts.append(f"spills to offset ₹{_fmt(offset_lt)} of {fy} LTCG at 12.5%")
    if carry > 0:
        parts.append(f"₹{_fmt(carry)} carries forward (8 AYs)")
    if not parts:
        return (
            f"Short-term loss candidate for {fy}; no current-year gains "
            "to offset, full amount would carry forward 8 AYs."
        )
    return "Short-term loss candidate: " + "; ".join(parts) + "."


def _rationale_lt(offset_lt: float, carry: float, fy: str) -> str:
    parts: list[str] = []
    if offset_lt > 0:
        parts.append(
            f"could offset ₹{_fmt(offset_lt)} of taxable {fy} LTCG at 12.5%"
        )
    if carry > 0:
        parts.append(f"₹{_fmt(carry)} carries forward (8 AYs)")
    if not parts:
        return (
            f"Long-term loss candidate for {fy}; LTCG is within the "
            f"₹1.25L exemption so no immediate cash saving — full "
            "amount carries forward 8 AYs."
        )
    return "Long-term loss candidate: " + "; ".join(parts) + "."


def _fmt(n: float) -> str:
    """Integer-rupees, Indian thousands grouping. Kept tiny on purpose
    — the frontend re-formats; the server string is only for the
    rationale field."""
    n = int(round(n))
    s = str(abs(n))
    if len(s) <= 3:
        grouped = s
    else:
        # Indian grouping: last 3, then groups of 2.
        head, tail = s[:-3], s[-3:]
        chunks = []
        while len(head) > 2:
            chunks.append(head[-2:])
            head = head[:-2]
        if head:
            chunks.append(head)
        grouped = ",".join(reversed(chunks)) + "," + tail
    return ("-" if n < 0 else "") + grouped
