# backend/services/analysis/peer_context.py
"""
Per-metric peer-percentile context for inline comparison sliders.

Manifesto rule 2: every number on the page must show where it sits vs
peer median (and ideally vs its own history). This module produces the
peer half of that promise by reading the same peer rows we already
build for the Peers tab, then summarising each comparable metric down
to ``{value, median, p5, p95}``.

Used by:
  * AnalysisService (extends AnalysisResponse.peer_context — additive,
    no CACHE_VERSION bump).
  * ``<MetricWithContext />`` on the frontend Quality tab, which reads
    the block and renders a 120×14 px slider with the value marker,
    median tick, and (optionally) own-history tick.

Pure function over a list of peer rows — no DB / network here. The
caller (analysis service) supplies rows from ``PeersService``.

Hard rules:
  * Tolerant — if fewer than 3 peer values exist for a metric the entry
    is omitted entirely so the frontend can fall back to a naked value
    instead of rendering a misleading slider over a tiny sample.
  * Field-additive — pre-PR clients ignore the field, no cache bump.
"""
from __future__ import annotations

from typing import Iterable


# Metrics we surface contextually on the analysis page. Order matters
# only for stable output ordering; the frontend keys by name.
_METRIC_KEYS: tuple[str, ...] = (
    "roe_pct",
    "pe_ratio",
    "pb_ratio",
    "ev_ebitda",
    "debt_to_equity",
    "net_margin_pct",
    "fcf_yield_pct",
    "dividend_yield",
)

# Minimum sample size before we'll publish a percentile block. Below
# this the median is noise.
_MIN_SAMPLE = 3


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile on an already-sorted list.

    ``q`` is in [0, 1]. Matches numpy's default ``linear`` method so a
    Python-only impl gives the same answer as the canary universe expects.
    """
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def build_peer_context(
    main_ticker: str,
    peer_rows: Iterable[dict] | None,
) -> dict[str, dict]:
    """Summarise peer rows into ``{metric: {value, median, p5, p95, n}}``.

    ``peer_rows`` is the output of ``PeersService.get_peer_comparison``'s
    ``peers`` field — one dict per ticker (main + peers) with metric
    fields like ``roe_pct``, ``pe_ratio``, etc.

    The returned dict ALSO carries ``value`` (the main ticker's own
    number for that metric) so the frontend only has to read one block
    per metric rather than re-deriving from ``quality`` / ``insights``.

    Returns an empty dict when no usable rows are supplied — caller
    should treat that as "skip the sliders".
    """
    if not peer_rows:
        return {}

    main_row: dict | None = None
    other_rows: list[dict] = []
    main_stripped = (main_ticker or "").upper().replace(".NS", "").replace(".BO", "")
    for row in peer_rows:
        rt = (row.get("ticker") or "").upper().replace(".NS", "").replace(".BO", "")
        if row.get("is_main") or rt == main_stripped:
            main_row = row
        else:
            other_rows.append(row)

    out: dict[str, dict] = {}
    for metric in _METRIC_KEYS:
        peer_vals: list[float] = []
        for row in other_rows:
            v = row.get(metric)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            # Filter NaN / inf
            if fv != fv or fv in (float("inf"), float("-inf")):
                continue
            # PE / PB / EV/EBITDA with non-positive values are noise
            if metric in ("pe_ratio", "pb_ratio", "ev_ebitda") and fv <= 0:
                continue
            peer_vals.append(fv)

        if len(peer_vals) < _MIN_SAMPLE:
            continue

        peer_vals.sort()
        median = _percentile(peer_vals, 0.5)
        p5     = _percentile(peer_vals, 0.05)
        p95    = _percentile(peer_vals, 0.95)

        # Main ticker's own value — may be None even when peer percentiles exist
        own_val: float | None = None
        if main_row is not None and main_row.get(metric) is not None:
            try:
                own_val = float(main_row.get(metric))
                if own_val != own_val or own_val in (float("inf"), float("-inf")):
                    own_val = None
            except (TypeError, ValueError):
                own_val = None

        out[metric] = {
            "value":  round(own_val, 4) if own_val is not None else None,
            "median": round(median, 4),
            "p5":     round(p5, 4),
            "p95":    round(p95, 4),
            "n":      len(peer_vals),
        }

    return out
