"""Unit tests for backend.services.funds.compute_score.

The score is a rule-based composite of peer-percentile sub-scores. We
verify:
    * Score is always in [0, 100] for any combination of inputs.
    * A scheme at the top of every peer metric scores near 100.
    * A scheme at the bottom scores near 0.
    * Tenure cap fires correctly.
    * Insufficient peer cohort returns score=None.
"""
from __future__ import annotations

import pytest

from backend.services.funds.compute_score import (
    ScoreInputs,
    compute_score_for_scheme,
    WEIGHTS,
    TENURE_CAPS,
)


def _peers(n: int, base: float, step: float) -> list[float]:
    return [base + step * i for i in range(n)]


def test_top_of_category_scores_high():
    n = 20
    rolling = _peers(n, 0.05, 0.005)   # 5..14.5 percent
    sharpe = _peers(n, 0.2, 0.05)
    drawdown = _peers(n, -0.40, 0.015)  # -40 .. -11.5 percent
    ter = _peers(n, 0.5, 0.05)
    # Scheme has the BEST value for each metric.
    inp = ScoreInputs(
        rolling_3y_mean=max(rolling),
        sharpe_3y=max(sharpe),
        max_dd_3y=max(drawdown),       # least-negative drawdown wins
        ter=min(ter),                  # lowest TER wins
        manager_tenure_years=5.0,      # past every tenure cap
    )
    res = compute_score_for_scheme(
        inp,
        peer_rolling_3y=rolling + [inp.rolling_3y_mean],
        peer_sharpe_3y=sharpe + [inp.sharpe_3y],
        peer_max_dd_3y=drawdown + [inp.max_dd_3y],
        peer_ter=ter + [inp.ter],
    )
    assert res.score is not None
    assert 0 <= res.score <= 100
    assert res.score >= 90
    assert res.component_tenure == 100


def test_bottom_of_category_scores_low():
    n = 20
    rolling = _peers(n, 0.05, 0.005)
    sharpe = _peers(n, 0.2, 0.05)
    drawdown = _peers(n, -0.40, 0.015)
    ter = _peers(n, 0.5, 0.05)
    inp = ScoreInputs(
        rolling_3y_mean=min(rolling),
        sharpe_3y=min(sharpe),
        max_dd_3y=min(drawdown),
        ter=max(ter),
        manager_tenure_years=10.0,
    )
    res = compute_score_for_scheme(
        inp,
        peer_rolling_3y=rolling + [inp.rolling_3y_mean],
        peer_sharpe_3y=sharpe + [inp.sharpe_3y],
        peer_max_dd_3y=drawdown + [inp.max_dd_3y],
        peer_ter=ter + [inp.ter],
    )
    assert res.score is not None
    assert 0 <= res.score <= 100
    assert res.score <= 15


def test_tenure_cap_short_tenure():
    n = 20
    rolling = _peers(n, 0.05, 0.005)
    sharpe = _peers(n, 0.2, 0.05)
    drawdown = _peers(n, -0.40, 0.015)
    ter = _peers(n, 0.5, 0.05)
    inp = ScoreInputs(
        rolling_3y_mean=max(rolling),
        sharpe_3y=max(sharpe),
        max_dd_3y=max(drawdown),
        ter=min(ter),
        manager_tenure_years=0.5,   # < 1y → cap at 60
    )
    res = compute_score_for_scheme(
        inp,
        peer_rolling_3y=rolling + [inp.rolling_3y_mean],
        peer_sharpe_3y=sharpe + [inp.sharpe_3y],
        peer_max_dd_3y=drawdown + [inp.max_dd_3y],
        peer_ter=ter + [inp.ter],
    )
    assert res.score is not None
    assert res.score <= TENURE_CAPS[0][1]
    assert res.component_tenure == TENURE_CAPS[0][1]


def test_score_in_bounds_for_random_inputs():
    # Property: any input combo yields a score in [0, 100] or None.
    import random
    rng = random.Random(2026)
    n = 12
    for _ in range(40):
        rolling = [rng.uniform(0.0, 0.20) for _ in range(n)]
        sharpe = [rng.uniform(-0.5, 1.5) for _ in range(n)]
        drawdown = [rng.uniform(-0.60, -0.05) for _ in range(n)]
        ter = [rng.uniform(0.30, 2.0) for _ in range(n)]
        inp = ScoreInputs(
            rolling_3y_mean=rng.choice(rolling),
            sharpe_3y=rng.choice(sharpe),
            max_dd_3y=rng.choice(drawdown),
            ter=rng.choice(ter),
            manager_tenure_years=rng.uniform(0.0, 12.0),
        )
        res = compute_score_for_scheme(
            inp, rolling, sharpe, drawdown, ter,
        )
        if res.score is not None:
            assert 0 <= res.score <= 100


def test_empty_peer_set_returns_none_score():
    inp = ScoreInputs(
        rolling_3y_mean=0.12, sharpe_3y=0.5, max_dd_3y=-0.20, ter=0.8,
        manager_tenure_years=4.0,
    )
    res = compute_score_for_scheme(inp, [], [], [], [])
    # All four peer cohorts empty -> all percentiles None -> score withheld.
    assert res.score is None
    assert any("withheld" in n for n in res.notes)


def test_weights_sum_to_total():
    assert sum(WEIGHTS.values()) == 100
