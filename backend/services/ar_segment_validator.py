# backend/services/ar_segment_validator.py
# ═══════════════════════════════════════════════════════════════
# Annual-Report segment-data unit-consistency validator
# (ROOT CAUSE #9 — 2026-06-11).
#
# ar_intel_service extracts segment_data rows from annual-report
# PDFs via Anthropic. The LLM occasionally produces unit-inconsistent
# rows: most commonly it reads a "% of total" column or a sub-segment
# expressed in lakhs as if it were in crore. The HDFCBANK FY25
# extraction is the reference case:
#
#   * Treasury                     Revenue 62,227 Cr / EBIT 4,605 Cr   plausible
#   * Retail Banking — Digital     Revenue     8.59 Cr / EBIT  0.04 Cr   IMPLAUSIBLE
#   * Retail Banking — Non-Digital Revenue 2,83,426 Cr / EBIT 27,309 Cr plausible
#
# An ₹8.59 Cr revenue line ($1M USD) for HDFCBANK's digital arm is
# not a real disclosed segment — it is almost certainly a sub-rail
# % share misread as absolute crore.
#
# This module is a PURE function over a segment_data list (no DB,
# no LLM). It computes a per-row plausibility verdict and stamps
# each row with ``unit_validated: bool`` and ``validation_reason:
# str`` so downstream consumers (the AR signals router + the
# frontend panel) can filter the bad rows out without losing the
# row itself — we preserve quarantined entries as evidence.
#
# Contract:
#   validate_segment_rows(rows, *, total_revenue_cr=None) ->
#       list[dict]
#
# Every returned dict is a shallow copy of the input with two
# additional keys: ``unit_validated`` and ``validation_reason``.
# Existing keys are NEVER mutated. The order of the rows is
# preserved.
#
# Rules (initial, conservative — quarantine when in doubt):
#
#   R1. revenue_share_implausible
#       Row revenue, when expressed as a share of total reported
#       revenue across all rows, is < 0.1 % or > 110 %. The lower
#       bound catches the % column / lakhs-as-cr misread; the
#       upper bound catches "row already contains the total" type
#       errors.
#
#   R2. ebit_margin_implausible
#       EBIT margin (ebit_cr / revenue_cr) is outside [-50, +90] %.
#       Banks legitimately run 30-45 % operating margin; +90 %
#       implies a row where EBIT > revenue (unit mismatch); -50 %
#       implies a segment so loss-making it is almost certainly a
#       mis-attributed cost rail.
#
#   R3. unit_mismatch_cluster
#       If a single row's revenue is < 1 % of the median row
#       revenue in its sibling cluster, AND the EBIT margin
#       computed from the row is suspicious (rule R2 fires OR
#       within a tighter [-30, +85] band but the absolute EBIT is
#       < 1 % of median EBIT), the row is flagged. This catches
#       the case where one segment slipped from Cr to Lakh while
#       its siblings stayed in Cr.
#
# The validator does NOT consult an LLM for re-extraction — that
# is the caller's responsibility (the ar_intel_service batch
# orchestrator can decide to re-run with explicit unit prompts on
# flagged rows). The validator's job is to mark the rows so the
# frontend can hide them and the backend can record the count for
# observability.
#
# Idempotent: re-running validate_segment_rows on an already-
# validated list yields byte-identical output (modulo the same
# stamps). Tests rely on this.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import statistics
from typing import Any

logger = logging.getLogger("yieldiq.ar_segment_validator")

# Bounds — exposed as module constants so tests and the audit
# script can import them.
REVENUE_SHARE_MIN_PCT = 0.1
REVENUE_SHARE_MAX_PCT = 110.0
EBIT_MARGIN_MIN_PCT = -50.0
EBIT_MARGIN_MAX_PCT = 90.0
EBIT_MARGIN_TIGHT_MIN_PCT = -30.0
EBIT_MARGIN_TIGHT_MAX_PCT = 85.0
CLUSTER_REVENUE_RATIO_MIN = 0.01  # 1 % of median
CLUSTER_EBIT_RATIO_MIN = 0.01

# Public stamps written onto each row.
VALIDATED_KEY = "unit_validated"
REASON_KEY = "validation_reason"


def _coerce_float(v: Any) -> float | None:
    """Return v as float, or None if it cannot be parsed.

    Accepts numbers and number-like strings; strips Indian-style
    thousand separators so "2,83,426" parses as 283_426.
    """
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        # bool is a subclass of int; reject explicitly.
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f != f:  # NaN
            return None
        return f
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace(" ", "")
        if not s:
            return None
        # Tolerate trailing units the LLM sometimes leaks ("12.3 Cr").
        for suffix in (" cr", " crore", " crores", " cr.", " lakh", " mn", " million", "%"):
            if s.lower().endswith(suffix):
                s = s[: -len(suffix)].rstrip()
        try:
            return float(s)
        except (TypeError, ValueError):
            return None
    return None


def _row_revenue(row: dict) -> float | None:
    return _coerce_float(row.get("revenue_cr"))


def _row_ebit(row: dict) -> float | None:
    return _coerce_float(row.get("ebit_cr"))


def _median_ignoring_none(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None and v > 0]
    if not clean:
        return None
    try:
        return float(statistics.median(clean))
    except statistics.StatisticsError:
        return None


def _compute_total_revenue(rows: list[dict]) -> float | None:
    """Sum revenue across all rows, ignoring None / non-numeric.

    Used as the denominator for the revenue-share rule when the
    caller does not pass an externally-anchored ``total_revenue_cr``
    (e.g. the AR's income-statement-level total).
    """
    total = 0.0
    count = 0
    for r in rows:
        v = _row_revenue(r)
        if v is None or v <= 0:
            continue
        total += v
        count += 1
    if count == 0 or total <= 0:
        return None
    return total


def _classify_row(
    row: dict,
    *,
    total_revenue: float | None,
    median_revenue: float | None,
    median_ebit: float | None,
) -> tuple[bool, str]:
    """Return (ok, reason) for one row.

    `ok=True` means the row passed all rules. `reason` is empty
    when ok is True. When ok is False, reason is a short
    machine-readable string of the form
    "<rule>: <human-readable detail>".
    """
    rev = _row_revenue(row)
    ebit = _row_ebit(row)

    # Rows with no usable revenue at all aren't useful for the
    # share rule. Don't quarantine just for being empty — the
    # extractor sometimes legitimately writes {"segment": "Other",
    # "revenue_cr": null} when a sub-rail isn't disclosed. We
    # only quarantine when the row CLAIMS a number that is then
    # implausible.
    if rev is None:
        return True, ""

    # Rule R1 — revenue share.
    if total_revenue is not None and total_revenue > 0:
        share_pct = (rev / total_revenue) * 100.0
        if share_pct < REVENUE_SHARE_MIN_PCT:
            return (
                False,
                f"revenue_share_implausible: row revenue {rev:.2f} Cr is "
                f"{share_pct:.3f}% of total {total_revenue:.0f} Cr "
                f"(< {REVENUE_SHARE_MIN_PCT}% floor)",
            )
        if share_pct > REVENUE_SHARE_MAX_PCT:
            return (
                False,
                f"revenue_share_implausible: row revenue {rev:.2f} Cr is "
                f"{share_pct:.1f}% of total {total_revenue:.0f} Cr "
                f"(> {REVENUE_SHARE_MAX_PCT}% ceiling)",
            )

    # Rule R2 — EBIT margin.
    if ebit is not None and rev > 0:
        margin_pct = (ebit / rev) * 100.0
        if margin_pct < EBIT_MARGIN_MIN_PCT or margin_pct > EBIT_MARGIN_MAX_PCT:
            return (
                False,
                f"ebit_margin_implausible: ebit {ebit:.2f}/rev {rev:.2f} "
                f"= {margin_pct:.1f}% margin (outside "
                f"[{EBIT_MARGIN_MIN_PCT},{EBIT_MARGIN_MAX_PCT}])",
            )

    # Rule R3 — cluster outlier (catches unit drift relative to
    # sibling rows). Only fires when we have a usable median and
    # the row is suspiciously small relative to it.
    if median_revenue is not None and median_revenue > 0:
        rev_ratio = rev / median_revenue
        if rev_ratio < CLUSTER_REVENUE_RATIO_MIN:
            # Either margin is loosely-bad OR absolute EBIT is
            # cluster-outlier-small. Either condition implies the
            # row's units don't match its siblings.
            ebit_outlier = False
            if ebit is not None and median_ebit is not None and median_ebit > 0:
                if abs(ebit) / median_ebit < CLUSTER_EBIT_RATIO_MIN:
                    ebit_outlier = True
            margin_loose_bad = False
            if ebit is not None and rev > 0:
                margin_pct = (ebit / rev) * 100.0
                if (
                    margin_pct < EBIT_MARGIN_TIGHT_MIN_PCT
                    or margin_pct > EBIT_MARGIN_TIGHT_MAX_PCT
                ):
                    margin_loose_bad = True
            if ebit_outlier or margin_loose_bad:
                return (
                    False,
                    f"unit_mismatch_cluster: row revenue {rev:.2f} Cr is "
                    f"{rev_ratio * 100:.2f}% of cluster median "
                    f"{median_revenue:.0f} Cr "
                    f"(< {CLUSTER_REVENUE_RATIO_MIN * 100}%); "
                    f"likely Cr/Lakh or %-of-total misread",
                )

    return True, ""


def validate_segment_rows(
    rows: list[dict],
    *,
    total_revenue_cr: float | None = None,
) -> list[dict]:
    """Stamp each row with ``unit_validated`` and ``validation_reason``.

    Pure function — no I/O, no LLM, no exceptions on bad input.
    Non-dict items in ``rows`` are skipped (logged at DEBUG).

    Args:
        rows: list of segment dicts from ar_signals.segment_data.
        total_revenue_cr: optional externally-anchored total revenue
            (e.g. the AR's income-statement total). When None, the
            validator computes a denominator from the rows
            themselves. Pass an external anchor when you trust it
            more than the row-sum.

    Returns:
        list[dict]: each row is a shallow copy with ``unit_validated:
            bool`` and ``validation_reason: str`` stamps appended.
            Already-stamped rows are revalidated (idempotent).
    """
    if not isinstance(rows, list):
        return []

    clean_rows: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            logger.debug("validate_segment_rows: skipped non-dict entry %r", r)
            continue
        clean_rows.append(r)
    if not clean_rows:
        return []

    total_revenue = (
        float(total_revenue_cr)
        if total_revenue_cr is not None and total_revenue_cr > 0
        else _compute_total_revenue(clean_rows)
    )
    median_revenue = _median_ignoring_none(
        [_row_revenue(r) for r in clean_rows]
    )
    median_ebit = _median_ignoring_none(
        [
            abs(v) if v is not None else None
            for v in (_row_ebit(r) for r in clean_rows)
        ]
    )

    out: list[dict] = []
    for r in clean_rows:
        ok, reason = _classify_row(
            r,
            total_revenue=total_revenue,
            median_revenue=median_revenue,
            median_ebit=median_ebit,
        )
        stamped = dict(r)
        # Remove any previous stamps to keep the function
        # idempotent — re-running over an already-stamped list
        # must yield the same result regardless of prior state.
        stamped.pop(VALIDATED_KEY, None)
        stamped.pop(REASON_KEY, None)
        stamped[VALIDATED_KEY] = bool(ok)
        stamped[REASON_KEY] = reason
        out.append(stamped)

    return out


def count_flagged(rows: list[dict]) -> int:
    """Convenience helper for tests / audits.

    Returns the number of rows where ``unit_validated`` is False.
    Safe on un-stamped lists (returns 0 — un-stamped rows are
    treated as validated, matching the panel's default).
    """
    n = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get(VALIDATED_KEY) is False:
            n += 1
    return n
