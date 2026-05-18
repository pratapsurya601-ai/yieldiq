"""Tier 2 vs custom-engine head-to-head reconciliation harness.

Layer B Week-2 analytics tool. Once Layer A reconciliation data is
flowing (consensus_estimates populated by the daily 05:00 IST refresh),
this script compares — for each canary ticker —

    delta_current = |current_fv - consensus_median| / consensus_median
    delta_tier2   = |tier2_fv   - consensus_median| / consensus_median

and labels a winner:

    "tier2_wins"     : Tier 2 is at least THRESHOLD_PCT closer to consensus
    "current_wins"   : current engine is at least THRESHOLD_PCT closer
    "tie"            : within THRESHOLD_PCT of each other
    "no_consensus"   : consensus row missing or below analyst floor

Per-engine aggregation rolls up wins/losses bucketed by the current
engine's ``valuation_method`` (dcf, pharma_rd_adjusted,
fmcg_brand_overlay, ...). Engines where Tier 2 wins a strong majority
of the head-to-head are surfaced as deprecation candidates for the
Week-5 cleanup pass.

This script is read-only and analytics-only:

  * No CACHE_VERSION bump — does not enter the cache key.
  * Does not flip TIER2_ENABLED — that's an operator decision after
    reviewing the output of this script across several reconciliation
    runs.
  * Does not write to the DB; output goes to stdout / a JSON file.

Usage::

    python scripts/tier2_head_to_head.py \\
        --universe canary \\
        --threshold-pct 5 \\
        --min-analysts 3 \\
        --output tier2_head_to_head.json

    # offline (no DB) — used by tests + CI smoke:
    python scripts/tier2_head_to_head.py --self-test
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("tier2_head_to_head")


# ── Tunables (CLI-overridable) ──────────────────────────────────────

# Default "must be at least this much closer" pp gap for a clear win.
DEFAULT_THRESHOLD_PCT = 5.0

# Default analyst-coverage floor mirrors the Benchmark Reconciliation
# Framework (Layer A) so the two layers agree on "consensus available".
DEFAULT_MIN_ANALYSTS = 3

# An engine becomes a Week-5 deprecation candidate when Tier 2 wins
# this fraction (or more) of the head-to-head AND there are at least
# MIN_ENGINE_SAMPLES decisive matchups (excluding ties and
# no_consensus). The 60% / 10-sample floor is conservative — anything
# below is statistical noise on a 180-stock universe.
DEPRECATION_WIN_RATE = 0.60
MIN_ENGINE_SAMPLES = 10


# ── Pure helpers (DB-free; covered by tests) ────────────────────────


def _safe_pos_float(x: Any) -> Optional[float]:
    """Coerce to float, returning None for None / NaN / non-positive."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    if v <= 0:
        return None
    return v


def label_winner(
    current_fv: Optional[float],
    tier2_fv: Optional[float],
    consensus_fv: Optional[float],
    analyst_count: Optional[int],
    *,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    min_analysts: int = DEFAULT_MIN_ANALYSTS,
) -> dict:
    """Return the head-to-head verdict for a single ticker.

    Shape::

        {
          "winner":         "tier2_wins"|"current_wins"|"tie"|"no_consensus",
          "delta_current":  float|None,   # |cur-cons|/cons, 0..inf
          "delta_tier2":    float|None,
          "delta_gap_pp":   float|None,   # (delta_current - delta_tier2) * 100
          "reason":         str,          # human one-liner for logs
        }

    Threshold is in *percentage points* (5 → 0.05 fraction gap). The
    sign convention is "tier2 wins if delta_tier2 is THRESHOLD lower
    than delta_current".
    """
    cur = _safe_pos_float(current_fv)
    t2 = _safe_pos_float(tier2_fv)
    cons = _safe_pos_float(consensus_fv)

    if cons is None or (analyst_count is not None and analyst_count < min_analysts):
        return {
            "winner": "no_consensus",
            "delta_current": None,
            "delta_tier2": None,
            "delta_gap_pp": None,
            "reason": (
                "consensus missing"
                if cons is None
                else f"analyst_count {analyst_count} < floor {min_analysts}"
            ),
        }

    delta_cur = abs(cur - cons) / cons if cur is not None else None
    delta_t2 = abs(t2 - cons) / cons if t2 is not None else None

    # If either FV is missing, the comparison degenerates. Surface
    # which side is dark; the harness reports this under aggregate
    # counters but the per-ticker winner is "tie" only when both
    # sides exist and are within threshold.
    if delta_cur is None and delta_t2 is None:
        return {
            "winner": "no_consensus",
            "delta_current": None,
            "delta_tier2": None,
            "delta_gap_pp": None,
            "reason": "neither current_fv nor tier2_fv available",
        }
    if delta_cur is None:
        return {
            "winner": "tier2_wins",
            "delta_current": None,
            "delta_tier2": delta_t2,
            "delta_gap_pp": None,
            "reason": "current_fv unavailable; Tier 2 wins by default",
        }
    if delta_t2 is None:
        return {
            "winner": "current_wins",
            "delta_current": delta_cur,
            "delta_tier2": None,
            "delta_gap_pp": None,
            "reason": "tier2_fv unavailable (data_limited); current wins by default",
        }

    gap_pp = (delta_cur - delta_t2) * 100.0  # +ve → tier2 closer
    threshold_frac_pp = float(threshold_pct)
    if gap_pp > threshold_frac_pp:
        winner = "tier2_wins"
        reason = (
            f"tier2 closer by {gap_pp:.1f}pp "
            f"(cur={delta_cur * 100:.1f}%, t2={delta_t2 * 100:.1f}%)"
        )
    elif gap_pp < -threshold_frac_pp:
        winner = "current_wins"
        reason = (
            f"current closer by {-gap_pp:.1f}pp "
            f"(cur={delta_cur * 100:.1f}%, t2={delta_t2 * 100:.1f}%)"
        )
    else:
        winner = "tie"
        reason = (
            f"within {threshold_pct:.0f}pp "
            f"(cur={delta_cur * 100:.1f}%, t2={delta_t2 * 100:.1f}%)"
        )
    return {
        "winner": winner,
        "delta_current": delta_cur,
        "delta_tier2": delta_t2,
        "delta_gap_pp": gap_pp,
        "reason": reason,
    }


def aggregate_by_engine(results: Iterable[dict]) -> dict[str, dict[str, int]]:
    """Roll per-ticker results up by the *current* engine's
    valuation_method. Each engine bucket gets four counters:

        tier2_wins, current_wins, ties, no_consensus

    Tickers whose current engine is unknown bucket under "unknown".
    """
    summary: dict[str, dict[str, int]] = {}
    for r in results:
        engine = (r.get("current_engine") or "unknown").strip() or "unknown"
        bucket = summary.setdefault(
            engine,
            {"tier2_wins": 0, "current_wins": 0, "ties": 0, "no_consensus": 0},
        )
        w = r.get("winner")
        if w == "tier2_wins":
            bucket["tier2_wins"] += 1
        elif w == "current_wins":
            bucket["current_wins"] += 1
        elif w == "tie":
            bucket["ties"] += 1
        else:
            bucket["no_consensus"] += 1
    return summary


def deprecation_recommendations(
    engine_summary: dict[str, dict[str, int]],
    *,
    win_rate: float = DEPRECATION_WIN_RATE,
    min_samples: int = MIN_ENGINE_SAMPLES,
) -> list[str]:
    """Return human-readable recommendations for engines where Tier 2
    wins ``win_rate`` or more of decisive matchups (excluding ties and
    no_consensus), provided there are at least ``min_samples`` decisive
    matchups in the bucket.

    The "dcf" generic engine is always reported but never marked as a
    deprecation candidate — it's the fallback when no custom engine
    exists, so deprecating it has no meaning.
    """
    out: list[str] = []
    for engine, c in sorted(engine_summary.items()):
        if engine == "dcf":
            continue
        decisive = c["tier2_wins"] + c["current_wins"]
        if decisive < min_samples:
            continue
        wr = c["tier2_wins"] / decisive
        if wr >= win_rate:
            out.append(
                f"{engine}: Tier 2 wins {wr * 100:.0f}% "
                f"({c['tier2_wins']}/{decisive}) — recommend deprecation in Week 5"
            )
    return out


# ── Self-test (no DB) ───────────────────────────────────────────────


def _selftest() -> int:
    """Offline correctness check used by tests + CI smoke."""
    print("=== tier2_head_to_head self-test ===")

    # Scenario 1: Tier 2 is 10pp closer to consensus
    v = label_winner(
        current_fv=80, tier2_fv=98, consensus_fv=100, analyst_count=10,
        threshold_pct=5,
    )
    assert v["winner"] == "tier2_wins", v
    print(f"  scenario 1 (tier2 wins): {v['reason']}")

    # Scenario 2: current is 10pp closer
    v = label_winner(
        current_fv=98, tier2_fv=80, consensus_fv=100, analyst_count=10,
        threshold_pct=5,
    )
    assert v["winner"] == "current_wins", v
    print(f"  scenario 2 (current wins): {v['reason']}")

    # Scenario 3: tie within threshold
    v = label_winner(
        current_fv=97, tier2_fv=100, consensus_fv=100, analyst_count=10,
        threshold_pct=5,
    )
    assert v["winner"] == "tie", v
    print(f"  scenario 3 (tie): {v['reason']}")

    # Scenario 4: missing consensus
    v = label_winner(
        current_fv=100, tier2_fv=110, consensus_fv=None, analyst_count=10,
    )
    assert v["winner"] == "no_consensus", v
    print(f"  scenario 4 (no consensus): {v['reason']}")

    # Scenario 5: analyst floor not met
    v = label_winner(
        current_fv=100, tier2_fv=110, consensus_fv=120, analyst_count=2,
        min_analysts=3,
    )
    assert v["winner"] == "no_consensus", v
    print(f"  scenario 5 (analyst floor): {v['reason']}")

    # Aggregation rolls up correctly
    rows = [
        {"current_engine": "pharma_rd_adjusted", "winner": "tier2_wins"},
        {"current_engine": "pharma_rd_adjusted", "winner": "tier2_wins"},
        {"current_engine": "pharma_rd_adjusted", "winner": "current_wins"},
        {"current_engine": "dcf", "winner": "tie"},
        {"current_engine": "dcf", "winner": "no_consensus"},
    ]
    agg = aggregate_by_engine(rows)
    assert agg["pharma_rd_adjusted"] == {
        "tier2_wins": 2, "current_wins": 1, "ties": 0, "no_consensus": 0,
    }, agg
    assert agg["dcf"] == {
        "tier2_wins": 0, "current_wins": 0, "ties": 1, "no_consensus": 1,
    }, agg
    print("  aggregate_by_engine: OK")

    # Recs filter min_samples and the 60% threshold
    summary = {
        "pharma_rd_adjusted": {
            "tier2_wins": 18, "current_wins": 6, "ties": 2, "no_consensus": 0,
        },
        "fmcg_brand_overlay": {
            "tier2_wins": 2, "current_wins": 1, "ties": 0, "no_consensus": 0,
        },  # below min_samples
        "dcf": {  # always excluded
            "tier2_wins": 200, "current_wins": 50, "ties": 0, "no_consensus": 0,
        },
    }
    recs = deprecation_recommendations(summary)
    assert any("pharma_rd_adjusted" in r for r in recs), recs
    assert not any("fmcg_brand_overlay" in r for r in recs), recs
    assert not any("dcf" in r for r in recs), recs
    print(f"  deprecation_recommendations: OK ({len(recs)} recs)")

    print("=== self-test PASSED ===")
    return 0


# ── Universe loader ─────────────────────────────────────────────────


def load_canary_symbols(path: Path) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [s["symbol"] for s in data.get("stocks", [])]


# ── Live-mode loaders (DB-backed; thin shells around SQL) ───────────


def _load_current_rows(session, symbols: Optional[list[str]]) -> dict[str, dict]:
    """Read most-recent analysis_cache row per ticker (optionally
    restricted to ``symbols``). Returns
    ``{ticker: {"current_fv": float|None, "current_engine": str|None,
                "sector": str|None}}``.
    """
    from sqlalchemy import text

    if symbols:
        sql = text("""
            SELECT DISTINCT ON (ticker)
                ticker,
                (payload->'valuation'->>'fair_value')::float           AS current_fv,
                COALESCE(
                    payload->'valuation'->>'valuation_method',
                    payload->'valuation'->>'method',
                    'dcf'
                )                                                       AS current_engine,
                payload->>'sector'                                      AS sector
            FROM analysis_cache
            WHERE ticker = ANY(:tickers)
            ORDER BY ticker, computed_at DESC
        """)
        rows = session.execute(sql, {"tickers": symbols}).mappings().all()
    else:
        sql = text("""
            SELECT DISTINCT ON (ticker)
                ticker,
                (payload->'valuation'->>'fair_value')::float           AS current_fv,
                COALESCE(
                    payload->'valuation'->>'valuation_method',
                    payload->'valuation'->>'method',
                    'dcf'
                )                                                       AS current_engine,
                payload->>'sector'                                      AS sector
            FROM analysis_cache
            ORDER BY ticker, computed_at DESC
        """)
        rows = session.execute(sql).mappings().all()
    return {
        r["ticker"]: {
            "current_fv": r["current_fv"],
            "current_engine": r["current_engine"],
            "sector": r["sector"],
        }
        for r in rows
    }


def _load_consensus_rows(session, tickers: list[str]) -> dict[str, dict]:
    """Read latest consensus per ticker via the view. Returns
    ``{ticker: {"consensus_fv": float|None, "analyst_count": int|None}}``.
    """
    from sqlalchemy import text

    rows = session.execute(text("""
        SELECT ticker,
               target_median::float AS consensus_fv,
               analyst_count
        FROM latest_consensus_per_ticker
        WHERE ticker = ANY(:tickers)
    """), {"tickers": tickers}).mappings().all()
    return {
        r["ticker"]: {
            "consensus_fv": r["consensus_fv"],
            "analyst_count": r["analyst_count"],
        }
        for r in rows
    }


def _compute_tier2_for_ticker(ticker: str, sector: Optional[str]) -> Optional[dict]:
    """Best-effort Tier 2 computation for a single ticker.

    Tier 2 needs a populated ``financials`` dict and a peer list. The
    full computation lives behind the analysis service plumbing and
    is expensive to bootstrap here. For the head-to-head harness we
    re-use the analysis service's standalone ``compute_tier2_for_ticker``
    helper if it exists; otherwise the caller surfaces None as
    data_limited and the per-ticker winner becomes "current_wins"
    by default (which is correct — we can't dethrone an engine we
    can't beat).

    Returns ``{"fair_value": float, ...}`` or ``None``.
    """
    try:
        # Optional helper — wired up in service.py when Tier 2 lands
        # in the routing tree (Week 1 PR 1 added the service module
        # itself; the wiring + helper land in a follow-up).
        from backend.services.analysis.service import (  # type: ignore[attr-defined]
            compute_tier2_for_ticker as _helper,
        )
        return _helper(ticker, sector=sector)
    except Exception as exc:  # pragma: no cover — service-shape dependent
        logger.debug(
            "tier2 helper not available for %s (sector=%s): %s",
            ticker, sector, exc,
        )
        return None


def _run_live(
    *,
    universe: str,
    threshold_pct: float,
    min_analysts: int,
) -> dict:
    """DB-backed run. Returns the full output dict written to JSON."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL not set; required for live mode")

    canary_path = Path(__file__).parent / "canary_universe_180.json"
    if universe == "canary":
        symbols = load_canary_symbols(canary_path)
    elif universe == "all":
        symbols = None  # signal "no filter"
    else:
        raise SystemExit(f"unknown universe: {universe}")

    engine = create_engine(db_url, future=True)
    Sess = sessionmaker(bind=engine, future=True)
    sess = Sess()
    try:
        current = _load_current_rows(sess, symbols)
        tickers = list(current.keys()) if symbols is None else symbols
        consensus = _load_consensus_rows(sess, tickers)
    finally:
        sess.close()

    per_ticker: list[dict] = []
    for tk in sorted(current.keys() if symbols is None else symbols):
        cur = current.get(tk, {})
        cons = consensus.get(tk, {})
        t2 = _compute_tier2_for_ticker(tk, cur.get("sector"))
        t2_fv = (t2 or {}).get("fair_value")
        verdict = label_winner(
            current_fv=cur.get("current_fv"),
            tier2_fv=t2_fv,
            consensus_fv=cons.get("consensus_fv"),
            analyst_count=cons.get("analyst_count"),
            threshold_pct=threshold_pct,
            min_analysts=min_analysts,
        )
        per_ticker.append({
            "ticker": tk,
            "sector": cur.get("sector"),
            "current_engine": cur.get("current_engine") or "unknown",
            "current_fv": cur.get("current_fv"),
            "tier2_fv": t2_fv,
            "consensus_fv": cons.get("consensus_fv"),
            "analyst_count": cons.get("analyst_count"),
            **verdict,
        })

    engine_summary = aggregate_by_engine(per_ticker)
    recs = deprecation_recommendations(engine_summary)
    return {
        "_meta": {
            "universe": universe,
            "threshold_pct": threshold_pct,
            "min_analysts": min_analysts,
            "ticker_count": len(per_ticker),
        },
        "engine_summary": engine_summary,
        "deprecation_recommendations": recs,
        "per_ticker": per_ticker,
    }


# ── CLI ─────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--threshold-pct", type=float, default=DEFAULT_THRESHOLD_PCT,
        help="Declare Tier 2 winner if it's >N pp closer to consensus (default 5).",
    )
    p.add_argument(
        "--universe", choices=["canary", "all"], default="canary",
        help="Scope: canary_universe_180 or all analysis_cache rows.",
    )
    p.add_argument(
        "--min-analysts", type=int, default=DEFAULT_MIN_ANALYSTS,
        help="Require N analyst coverage for consensus (default 3).",
    )
    p.add_argument(
        "--output", type=str, default=None,
        help="Write the full JSON report here (otherwise stdout).",
    )
    p.add_argument(
        "--self-test", action="store_true",
        help="Offline correctness check; no DB required.",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    if args.self_test:
        return _selftest()

    report = _run_live(
        universe=args.universe,
        threshold_pct=args.threshold_pct,
        min_analysts=args.min_analysts,
    )
    blob = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(blob, encoding="utf-8")
        logger.info("wrote %s", args.output)
    else:
        print(blob)
    return 0


if __name__ == "__main__":
    sys.exit(main())
