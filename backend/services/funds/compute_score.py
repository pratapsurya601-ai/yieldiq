# backend/services/funds/compute_score.py
# YieldIQ Fund Score — rule-based composite, 0..100.
#
# Inputs (per scheme, all optional — missing fields contribute 0 to that
# component but do NOT zero the whole score):
#   * rolling_3y_mean          (higher is better; weighted vs peers)
#   * sharpe_3y                (higher is better; weighted vs peers)
#   * max_dd_3y                (less negative is better; weighted vs peers)
#   * ter_direct or ter_regular (lower is better; weighted vs peers)
#   * manager_tenure_years     (acts as a floor: <1y caps the score at 60,
#                               1-3y caps at 80, otherwise no cap)
#
# Peer set is the SEBI category (e.g. all "Large Cap" schemes). We rank
# each input within the peer set to derive a 0..100 percentile, then
# combine with the weights below.
#
# Weights (sum to 100):
#   rolling_3y_mean    : 30
#   sharpe_3y          : 25
#   max_dd_3y          : 20
#   ter (direct first) : 15
#   tenure floor       : 10
#
# NO LLM. Pure rules. The breakdown is persisted as separate component
# columns on fund_returns_cache so the analysis page can render the
# rationale without re-computing.
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


# Public weights — exposed so the Phase 3 breakdown card can label them.
WEIGHTS = {
    "rolling": 30,
    "sharpe": 25,
    "drawdown": 20,
    "ter": 15,
    "tenure": 10,
}

# Tenure floor: applied as a cap on the FINAL composite, not the
# component. Reasoning: a manager change is a known disruption to a
# fund's track record; we cap the headline score until the new manager
# accumulates a meaningful track record. Floor values are caps, not
# offsets — a score below the cap stays at its computed value.
TENURE_CAPS = (
    (1.0, 60),   # < 1 year on the desk
    (3.0, 80),   # 1-3 years on the desk
)


@dataclass
class ScoreInputs:
    rolling_3y_mean: Optional[float]
    sharpe_3y: Optional[float]
    max_dd_3y: Optional[float]
    ter: Optional[float]
    manager_tenure_years: Optional[float]


@dataclass
class ScoreResult:
    score: Optional[int]
    component_rolling: int
    component_sharpe: int
    component_drawdown: int
    component_ter: int
    component_tenure: int
    notes: list[str]


def _percentile_rank(value: Optional[float], peers: Sequence[float], higher_better: bool) -> Optional[float]:
    """Return percentile rank in [0, 1] of ``value`` within ``peers``.

    ``peers`` may include the scheme itself; we still rank it among the
    full set. Returns None when there are fewer than 5 non-null peers.
    """
    if value is None:
        return None
    arr = np.array([p for p in peers if p is not None], dtype=float)
    if arr.size < 5:
        return None
    if higher_better:
        rank = float(np.sum(arr <= value)) / float(arr.size)
    else:
        rank = float(np.sum(arr >= value)) / float(arr.size)
    return max(0.0, min(1.0, rank))


def _apply_tenure_cap(raw_score: int, tenure_years: Optional[float]) -> tuple[int, int]:
    """Return (capped_score, tenure_component_0_to_100).

    Tenure component is the FLOOR-mapped value used for the breakdown
    card: 100 if no cap fires, otherwise the cap value.
    """
    if tenure_years is None:
        # Unknown tenure is treated neutrally — no cap applied, but the
        # tenure component is reported at 50 so the breakdown card shows
        # "tenure unknown" honestly.
        return raw_score, 50
    for threshold, cap in TENURE_CAPS:
        if tenure_years < threshold:
            return min(raw_score, cap), cap
    return raw_score, 100


def compute_score_for_scheme(
    inputs: ScoreInputs,
    peer_rolling_3y: Sequence[Optional[float]],
    peer_sharpe_3y: Sequence[Optional[float]],
    peer_max_dd_3y: Sequence[Optional[float]],
    peer_ter: Sequence[Optional[float]],
) -> ScoreResult:
    """Compute the YieldIQ Fund Score using peer-set percentile ranks.

    Each peer sequence is the same-category set of values for that
    metric (the scheme's own value is expected to be present in the
    sequence so the percentile is computed against the full peer cohort).

    Returns a ScoreResult with None ``score`` when too few peer rows
    were available to rank ANY of the four metrics — that means the
    category is too small and the page falls back to category medians
    instead of a composite.
    """
    notes: list[str] = []

    pct_rolling = _percentile_rank(inputs.rolling_3y_mean, peer_rolling_3y, higher_better=True)
    pct_sharpe = _percentile_rank(inputs.sharpe_3y, peer_sharpe_3y, higher_better=True)
    pct_dd = _percentile_rank(inputs.max_dd_3y, peer_max_dd_3y, higher_better=True)  # less-negative ranks higher
    pct_ter = _percentile_rank(inputs.ter, peer_ter, higher_better=False)

    # Component sub-scores (0..100). Missing percentile -> 0 contribution
    # but we record the gap in notes for the breakdown card.
    def _comp(pct: Optional[float], name: str) -> int:
        if pct is None:
            notes.append(f"{name} percentile unavailable (peer set too small or value null)")
            return 0
        return int(round(pct * 100.0))

    c_rolling = _comp(pct_rolling, "rolling")
    c_sharpe = _comp(pct_sharpe, "sharpe")
    c_dd = _comp(pct_dd, "drawdown")
    c_ter = _comp(pct_ter, "ter")

    if pct_rolling is None and pct_sharpe is None and pct_dd is None and pct_ter is None:
        notes.append("all peer percentiles unavailable — score withheld")
        return ScoreResult(
            score=None,
            component_rolling=c_rolling, component_sharpe=c_sharpe,
            component_drawdown=c_dd, component_ter=c_ter,
            component_tenure=0,
            notes=notes,
        )

    # Weighted average of the four percentile components. Tenure rides
    # on top as a cap.
    weighted = (
        c_rolling * WEIGHTS["rolling"]
        + c_sharpe * WEIGHTS["sharpe"]
        + c_dd * WEIGHTS["drawdown"]
        + c_ter * WEIGHTS["ter"]
    ) / (WEIGHTS["rolling"] + WEIGHTS["sharpe"] + WEIGHTS["drawdown"] + WEIGHTS["ter"])
    raw = int(round(weighted))
    raw = max(0, min(100, raw))

    capped, c_tenure = _apply_tenure_cap(raw, inputs.manager_tenure_years)
    if capped < raw:
        notes.append(f"tenure cap fired (raw={raw}, capped={capped})")

    return ScoreResult(
        score=capped,
        component_rolling=c_rolling,
        component_sharpe=c_sharpe,
        component_drawdown=c_dd,
        component_ter=c_ter,
        component_tenure=c_tenure,
        notes=notes,
    )
