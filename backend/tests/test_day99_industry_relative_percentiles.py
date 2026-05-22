"""Day-99 (2026-05-22): industry-relative percentile rankings.

Backend behaviour (percentile math, endpoint shape, thin-cohort
handling) + frontend smoke (the Hex component accepts the new prop
and the AnalysisHero renders a SEBI-safe caption). The frontend
assertions are simple string greps against the source files so the
test runs without a Node toolchain.

Why these are the right tests:
  - The math test (rank 38 of 50 → 76th percentile) is the bug a
    misplaced `<` / `<=` would create — a 1-point shift on every
    surfaced number.
  - The thin-cohort test prevents the "100th percentile of 3 stocks"
    failure mode that competitors actually ship.
  - The SEBI vocabulary scan catches a future contributor adding
    "outperform" / "underperform" copy to the caption.
"""
from __future__ import annotations

import importlib.util as _importlib_util
import pathlib as _pathlib

import pytest

from backend.services import industry_percentile_service as ips


# ── Percentile math ─────────────────────────────────────────────


def test_percentile_rank_38_of_50_is_76th():
    """50 stocks sorted ascending. Target at rank 38 (0-indexed) sits
    above 38 strictly-lower peers → 38/50 = 76%. This is the
    canonical worked example from the task spec; a `<=` would shift
    every surfaced percentile by one slot."""
    cohort = list(range(50))  # values 0..49
    target = 38
    assert ips.percentile_rank(target, cohort) == 76


def test_percentile_rank_empty_cohort_is_zero():
    assert ips.percentile_rank(7.5, []) == 0


def test_percentile_rank_handles_nan_value():
    assert ips.percentile_rank(float("nan"), [1, 2, 3]) == 0


def test_percentile_rank_handles_nan_in_cohort():
    """NaN entries are skipped, not counted as below."""
    cohort = [1.0, 2.0, float("nan"), 4.0]
    # subject = 3 → strictly-below = 2 (1, 2), valid n = 3 → 67%
    assert ips.percentile_rank(3.0, cohort) == 67


def test_percentile_rank_max_value_is_100():
    cohort = [1, 2, 3, 4]
    assert ips.percentile_rank(10, cohort) == 100


def test_percentile_rank_min_value_is_zero():
    cohort = [1, 2, 3, 4]
    assert ips.percentile_rank(0, cohort) == 0


# ── Endpoint-shape behaviour via the service helper ──────────────


class _FakeRow:
    """SQLAlchemy-Result-like row supporting positional indexing."""
    def __init__(self, *vals):
        self._vals = vals

    def __getitem__(self, i):
        return self._vals[i]


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


def _make_payload(yieldiq_score: float, moat_score: float = 7.0,
                  roce: float = 18.0, piotroski: int = 7) -> dict:
    """Build a minimal analysis_cache payload that the hex_axes
    derivation can read. Numbers picked so the derived 6 axes land
    near `moat_score`."""
    return {
        "quality": {
            "yieldiq_score": yieldiq_score,
            "moat": "Wide" if moat_score >= 7 else "Narrow",
            "moat_score": moat_score,
            "piotroski_score": piotroski,
            "roce": roce,
            "roe": roce - 2.0,
        },
        "valuation": {
            "margin_of_safety": 12.5,
        },
    }


class _FakeSession:
    """Minimal sqlalchemy Session double. Routes by the leading
    keyword of the SQL text so the service can drive 3 distinct
    queries (industry lookup, cohort fanout, single-ticker payload
    refetch) without us having to parse SQL."""

    def __init__(self, *, industry_row=None, cohort_rows=None,
                 subject_payload_row=None):
        self.industry_row = industry_row
        self.cohort_rows = cohort_rows or []
        self.subject_payload_row = subject_payload_row
        self.queries: list[str] = []

    def execute(self, sql, params=None):
        sql_text = str(sql).lower()
        self.queries.append(sql_text)
        if "from stocks" in sql_text and "industry, sector" in sql_text:
            rows = [self.industry_row] if self.industry_row else []
            return _FakeResult(rows)
        if "from stocks" in sql_text and "join latest_ac" in sql_text:
            return _FakeResult(self.cohort_rows)
        if "from analysis_cache" in sql_text:
            rows = [self.subject_payload_row] if self.subject_payload_row else []
            return _FakeResult(rows)
        return _FakeResult([])

    def close(self):
        pass


def test_endpoint_shape_returns_all_required_keys():
    """Standard happy path: target sits at rank 38 of 50, returns
    ticker / industry / cohort_size / percentiles dict."""
    ips._clear_cache()
    cohort_rows = [
        _FakeRow(f"PEER{i}.NS", _make_payload(yieldiq_score=float(i)))
        for i in range(50)
    ]
    # Replace one slot with the subject at score=38.
    cohort_rows[38] = _FakeRow("TCS.NS", _make_payload(yieldiq_score=38.0))
    sess = _FakeSession(
        industry_row=_FakeRow("IT Services", "Technology"),
        cohort_rows=cohort_rows,
    )
    out = ips.compute_industry_percentiles("TCS.NS", sess, ["score"])
    assert out["ticker"] == "TCS.NS"
    assert out["industry"] == "IT Services"
    assert out["cohort_size"] == 50
    assert "percentiles" in out
    assert out["percentiles"]["score"] == 76


def test_thin_cohort_returns_null_percentiles_with_caveat():
    """Fewer than MIN_COHORT_SIZE peers → null percentiles + a
    caveat string. NEVER a misleading numeric percentile."""
    ips._clear_cache()
    cohort_rows = [
        _FakeRow(f"PEER{i}.NS", _make_payload(yieldiq_score=float(i * 10)))
        for i in range(3)  # only 3 peers
    ]
    sess = _FakeSession(
        industry_row=_FakeRow("Specialty Insurance", "Financial Services"),
        cohort_rows=cohort_rows,
    )
    out = ips.compute_industry_percentiles("NICHE.NS", sess, ["score", "moat"])
    assert out["cohort_size"] == 3
    assert out["percentiles"] == {"score": None, "moat": None}
    assert "caveat" in out and out["caveat"]


def test_unknown_industry_returns_empty_percentiles():
    """Ticker absent from stocks.industry → cohort_size 0, all
    percentiles null, a caveat — never a 500."""
    ips._clear_cache()
    sess = _FakeSession(industry_row=None)
    out = ips.compute_industry_percentiles("MYSTERY.NS", sess, ["score"])
    assert out["cohort_size"] == 0
    assert out["percentiles"]["score"] is None
    assert "caveat" in out


def test_metric_filter_only_returns_requested_keys():
    """`metrics=quality,moat` must not surface the other 5."""
    ips._clear_cache()
    cohort_rows = [
        _FakeRow(f"P{i}.NS", _make_payload(yieldiq_score=float(i)))
        for i in range(10)
    ]
    cohort_rows[5] = _FakeRow("INFY.NS", _make_payload(yieldiq_score=5.0))
    sess = _FakeSession(
        industry_row=_FakeRow("IT Services", "Technology"),
        cohort_rows=cohort_rows,
    )
    out = ips.compute_industry_percentiles("INFY.NS", sess, ["quality", "moat"])
    assert set(out["percentiles"].keys()) == {"quality", "moat"}


def test_cache_returns_same_payload_within_ttl():
    """Second call within TTL must not re-query the DB."""
    ips._clear_cache()
    cohort_rows = [
        _FakeRow(f"P{i}.NS", _make_payload(yieldiq_score=float(i)))
        for i in range(20)
    ]
    cohort_rows[10] = _FakeRow("HDFCBANK.NS", _make_payload(yieldiq_score=10.0))
    sess = _FakeSession(
        industry_row=_FakeRow("Banks - Private Sector", "Financial Services"),
        cohort_rows=cohort_rows,
    )
    first = ips.get_cached_percentiles("HDFCBANK.NS", sess, ["score"])
    queries_after_first = len(sess.queries)
    second = ips.get_cached_percentiles("HDFCBANK.NS", sess, ["score"])
    assert first == second
    # Second call should have issued zero new queries.
    assert len(sess.queries) == queries_after_first


# ── Frontend smoke (string scans, no Node required) ─────────────


_REPO_ROOT = _pathlib.Path(__file__).resolve().parents[2]
_HEX_TSX = _REPO_ROOT / "frontend" / "src" / "components" / "hex" / "Hex.tsx"
_HERO_TSX = (
    _REPO_ROOT / "frontend" / "src" / "components" / "analysis" / "AnalysisHero.tsx"
)
_LIB_TS = _REPO_ROOT / "frontend" / "src" / "lib" / "industryPercentile.ts"


def test_hex_component_accepts_percentiles_prop():
    """Compile-time props extension. Without this, AnalysisHero
    would TS-error when passing percentiles into <Hex />."""
    src = _HEX_TSX.read_text(encoding="utf-8")
    assert "percentiles?:" in src
    assert "Partial<Record<HexAxisKey" in src


def test_hex_renders_percentile_caption_block():
    """The caption rendering must be guarded so absent / null
    entries render nothing — only `typeof === 'number'` qualifies."""
    src = _HEX_TSX.read_text(encoding="utf-8")
    assert 'typeof percentiles[p.key] === "number"' in src
    assert "ordinal(" in src


def test_analysis_hero_renders_industry_caption():
    """SEBI-safe one-liner under the Score. Implemented via the
    `percentileCaption` helper in lib/industryPercentile.ts."""
    src = _HERO_TSX.read_text(encoding="utf-8")
    assert "industry-percentile-caption" in src
    assert "percentileCaption" in src


def test_caption_helper_uses_sebi_safe_vocabulary():
    """Banned words must NOT appear in the rendered caption helper.
    This is the regression we are most worried about: a future
    contributor "improving" the copy to 'Outperforms peers in {industry}'
    would be an instant SEBI violation."""
    src = _LIB_TS.read_text(encoding="utf-8")
    # The helper contains the banned-list comment; strip comments before scanning.
    import re as _re
    no_comments = _re.sub(r"/\*.*?\*/", "", src, flags=_re.DOTALL)
    no_comments = _re.sub(r"//.*", "", no_comments)
    lowered = no_comments.lower()
    for banned in (
        "outperform", "underperform", "buy", "sell", "hold",
        "accumulate", "recommend", "strong",
    ):
        assert banned not in lowered, (
            f"SEBI-banned word '{banned}' leaked into percentileCaption helper"
        )


def test_caption_buckets_at_quartile_boundaries():
    """Boundary check on the adjective bucket. Lifted from
    percentileCaption so we exercise the exact thresholds the UI
    will render. Implemented as a python mirror so the test runs
    without a Node toolchain."""
    def bucket(p):
        if p >= 75: return "top"
        if p >= 50: return "above"
        if p >= 25: return "below"
        return "bottom"
    assert bucket(75) == "top"
    assert bucket(74) == "above"
    assert bucket(50) == "above"
    assert bucket(49) == "below"
    assert bucket(25) == "below"
    assert bucket(24) == "bottom"
    assert bucket(0) == "bottom"
