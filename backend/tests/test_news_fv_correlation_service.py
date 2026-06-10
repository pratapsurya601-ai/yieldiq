# backend/tests/test_news_fv_correlation_service.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for news_fv_correlation_service.
#
# Pure tests — uses the ``fv_rows`` and ``news_items`` keyword args
# on find_correlated_news() so no DB / yfinance involvement.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from datetime import date as Date

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.news_fv_correlation_service import (
    MIN_DRIVER_SCORE,
    NEWS_WINDOW_DAYS,
    NewsFvCorrelation,
    _alignment_score,
    _composite_relevance,
    _material_deltas,
    _pct_change,
    _recency_score,
    find_correlated_news,
    to_dict,
)


client = TestClient(app)


# ─────────────────────────────────────────────────────────────────
# Helper builders
# ─────────────────────────────────────────────────────────────────

def _fv(date_str: str, fv: float) -> dict:
    return {"date": date_str, "fair_value": fv}


def _news(
    date_str: str,
    headline: str,
    sentiment: float = 0.0,
    importance: str = "medium",
    tier: str = "A",
    url: str = "",
) -> dict:
    return {
        "published_at": f"{date_str}T10:00:00+00:00",
        "headline": headline,
        "sentiment_score": sentiment,
        "sentiment_label": "positive" if sentiment > 0.1 else ("negative" if sentiment < -0.1 else "neutral"),
        "importance": importance,
        "source_quality_tier": tier,
        "source": "Test Wire",
        "url": url or f"https://example.com/{headline[:20].replace(' ', '-')}",
    }


# ─────────────────────────────────────────────────────────────────
# Pure-function tests
# ─────────────────────────────────────────────────────────────────

class TestPureHelpers:
    def test_pct_change_signs(self):
        assert _pct_change(100, 110) == 10.0
        assert _pct_change(100, 90) == -10.0
        assert _pct_change(100, 100) == 0.0

    def test_pct_change_bad_input(self):
        assert _pct_change(0, 100) is None
        assert _pct_change(-1, 100) is None
        assert _pct_change(None, 100) is None
        assert _pct_change("x", 100) is None

    def test_recency_score_decays(self):
        d0 = Date(2026, 6, 10)
        assert _recency_score(d0, d0) == 1.0
        # Halfway through window — score should be ~0.5
        d_half = Date(2026, 6, 10 - NEWS_WINDOW_DAYS // 2)
        score = _recency_score(d_half, d0)
        assert 0.3 < score < 0.7
        # Outside window — zero
        d_far = Date(2026, 5, 1)
        assert _recency_score(d_far, d0) == 0.0

    def test_alignment_positive_with_positive(self):
        # +ve sentiment + +ve FV move → high alignment
        s = _alignment_score(0.5, +5.0)
        assert s > 0.6

    def test_alignment_negative_with_positive_penalised(self):
        # -ve sentiment + +ve FV move → mismatch → low score
        s = _alignment_score(-0.5, +5.0)
        assert s < 0.3

    def test_alignment_neutral_does_not_punish(self):
        # neutral-prior when sentiment missing
        assert _alignment_score(None, +5.0) == 0.3
        assert _alignment_score(0.0, +5.0) == 0.3

    def test_composite_relevance_in_window(self):
        d0 = Date(2026, 6, 10)
        score = _composite_relevance(
            sentiment_score=0.5,
            fv_delta_pct=+5.0,
            news_date=d0,
            fv_date=d0,
            importance="high",
            source_tier="A",
            headline="Strong Q2 earnings beat consensus",
        )
        # Same-day, aligned sentiment, high importance, tier A, topic
        # boost ("earnings", "results") — should be well above floor.
        assert score >= 0.7

    def test_composite_relevance_outside_window_zero(self):
        d_fv = Date(2026, 6, 10)
        d_news = Date(2026, 5, 1)  # > 7 days away
        score = _composite_relevance(
            sentiment_score=1.0,
            fv_delta_pct=+10.0,
            news_date=d_news,
            fv_date=d_fv,
            importance="critical",
            source_tier="A",
            headline="Massive results beat",
        )
        assert score == 0.0


# ─────────────────────────────────────────────────────────────────
# _material_deltas
# ─────────────────────────────────────────────────────────────────

class TestMaterialDeltas:
    def test_no_deltas_when_flat(self):
        rows = [_fv("2026-06-01", 100.0), _fv("2026-06-02", 100.5)]
        assert _material_deltas(rows, threshold_pct=3.0) == []

    def test_picks_up_move_above_threshold(self):
        rows = [
            _fv("2026-06-01", 100.0),
            _fv("2026-06-08", 105.0),  # +5% — material at 3% threshold
            _fv("2026-06-15", 105.5),  # +0.5% — not material
        ]
        deltas = _material_deltas(rows, threshold_pct=3.0)
        assert len(deltas) == 1
        d_after, before, after, pct = deltas[0]
        assert d_after == Date(2026, 6, 8)
        assert before == 100.0
        assert after == 105.0
        assert pct == 5.0

    def test_picks_up_negative_move(self):
        rows = [
            _fv("2026-06-01", 100.0),
            _fv("2026-06-08", 92.0),  # -8%
        ]
        deltas = _material_deltas(rows, threshold_pct=3.0)
        assert len(deltas) == 1
        assert deltas[0][3] == -8.0

    def test_returns_empty_for_single_row(self):
        assert _material_deltas([_fv("2026-06-01", 100.0)], threshold_pct=3.0) == []


# ─────────────────────────────────────────────────────────────────
# find_correlated_news end-to-end (with stubbed inputs)
# ─────────────────────────────────────────────────────────────────

class TestFindCorrelatedNews:
    def test_empty_ticker_returns_empty(self):
        assert find_correlated_news("") == []
        assert find_correlated_news(None) == []  # type: ignore[arg-type]

    def test_returns_empty_when_no_history(self):
        out = find_correlated_news("RELIANCE", fv_rows=[], news_items=[])
        assert out == []

    def test_returns_empty_when_no_material_moves(self):
        rows = [_fv("2026-06-01", 100.0), _fv("2026-06-05", 100.5)]
        out = find_correlated_news("RELIANCE", fv_rows=rows, news_items=[])
        assert out == []

    def test_surface_drivers_for_aligned_news(self):
        rows = [
            _fv("2026-10-05", 100.0),
            _fv("2026-10-12", 105.0),  # +5% on Oct 12
        ]
        news = [
            _news("2026-10-11", "Strong Q2 earnings beat consensus", sentiment=0.8, importance="high"),
            _news("2026-10-10", "Company announces new buyback", sentiment=0.5, importance="high"),
            _news("2026-10-09", "Generic market update", sentiment=0.0, importance="low", tier="C"),
        ]
        out = find_correlated_news(
            "RELIANCE", fv_rows=rows, news_items=news,
        )
        assert len(out) == 1
        c = out[0]
        assert isinstance(c, NewsFvCorrelation)
        assert c.fv_change_date == "2026-10-12"
        assert c.pct_change == 5.0
        assert c.fv_before == 100.0
        assert c.fv_after == 105.0
        # Top driver should be the earnings beat (recent + aligned + high importance + topic boost).
        assert len(c.likely_drivers) >= 1
        top = c.likely_drivers[0]
        assert "earnings" in top["headline"].lower()
        assert top["relevance_score"] >= MIN_DRIVER_SCORE

    def test_empty_drivers_when_only_misaligned_low_quality_news(self):
        # FV rose +5% but only available news is misaligned + outside window
        rows = [
            _fv("2026-10-05", 100.0),
            _fv("2026-10-12", 105.0),
        ]
        news = [
            _news("2026-09-01", "Old unrelated story", sentiment=0.0),  # outside window
        ]
        out = find_correlated_news(
            "RELIANCE", fv_rows=rows, news_items=news,
        )
        assert len(out) == 1
        # Outside-window items get zero recency → no drivers.
        assert out[0].likely_drivers == []

    def test_negative_move_aligned_with_negative_news(self):
        rows = [
            _fv("2026-09-01", 200.0),
            _fv("2026-09-05", 180.0),  # -10%
        ]
        news = [
            _news("2026-09-04", "Profit warning issued by company", sentiment=-0.7, importance="critical"),
            _news("2026-09-03", "Rating downgrade after weak quarterly", sentiment=-0.6, importance="high"),
        ]
        out = find_correlated_news("ABC", fv_rows=rows, news_items=news)
        assert len(out) == 1
        assert out[0].pct_change == -10.0
        assert len(out[0].likely_drivers) >= 1
        # Critical-importance, sentiment-aligned, in-window headline wins.
        top = out[0].likely_drivers[0]
        assert top["importance"] in ("critical", "high")

    def test_correlations_sorted_newest_first(self):
        rows = [
            _fv("2026-06-01", 100.0),
            _fv("2026-06-08", 95.0),    # -5%
            _fv("2026-06-15", 102.0),   # +7.4%
        ]
        out = find_correlated_news("ABC", fv_rows=rows, news_items=[])
        assert len(out) == 2
        # Most recent first.
        assert out[0].fv_change_date == "2026-06-15"
        assert out[1].fv_change_date == "2026-06-08"

    def test_drivers_cap_at_three(self):
        rows = [_fv("2026-06-01", 100.0), _fv("2026-06-05", 110.0)]
        # 5 in-window, all aligned, all high importance.
        news = [
            _news("2026-06-04", f"Earnings beat strong revenue growth #{i}", sentiment=0.8, importance="high")
            for i in range(5)
        ]
        out = find_correlated_news("ABC", fv_rows=rows, news_items=news)
        assert len(out[0].likely_drivers) == 3


# ─────────────────────────────────────────────────────────────────
# to_dict serialiser
# ─────────────────────────────────────────────────────────────────

class TestToDict:
    def test_to_dict_shape(self):
        payload = to_dict([])
        assert payload["correlations"] == []
        assert payload["summary"]["total_material_moves"] == 0
        assert payload["summary"]["moves_with_drivers"] == 0

    def test_to_dict_counts_drivers(self):
        c1 = NewsFvCorrelation(
            fv_change_date="2026-06-08",
            fv_before=100.0, fv_after=105.0, pct_change=5.0,
            likely_drivers=[{"headline": "x"}],
        )
        c2 = NewsFvCorrelation(
            fv_change_date="2026-06-01",
            fv_before=100.0, fv_after=95.0, pct_change=-5.0,
            likely_drivers=[],
        )
        payload = to_dict([c1, c2])
        assert payload["summary"]["total_material_moves"] == 2
        assert payload["summary"]["moves_with_drivers"] == 1


# ─────────────────────────────────────────────────────────────────
# Router contract
# ─────────────────────────────────────────────────────────────────

class TestRouter:
    def test_endpoint_returns_200_for_unknown_ticker(self):
        # No FV history in test DB → empty correlations, never a 500.
        r = client.get("/api/v1/public/news-fv-correlation/UNKNOWN_TICKER_XYZ")
        assert r.status_code == 200
        body = r.json()
        assert body["ticker"] == "UNKNOWN_TICKER_XYZ"
        assert "correlations" in body
        assert "summary" in body
        assert isinstance(body["correlations"], list)

    def test_endpoint_normalises_ticker_case(self):
        r = client.get("/api/v1/public/news-fv-correlation/tcs.ns")
        assert r.status_code == 200
        assert r.json()["ticker"] == "TCS"

    def test_endpoint_rejects_blank_ticker(self):
        # Slash-followed-by-space: FastAPI routes it as the literal " " path
        # which our handler treats as blank → 400.
        r = client.get("/api/v1/public/news-fv-correlation/%20")
        assert r.status_code == 400

    def test_endpoint_threshold_param_validation(self):
        # Below the ge=0.5 floor.
        r = client.get(
            "/api/v1/public/news-fv-correlation/TCS"
            "?fv_change_threshold_pct=0.1"
        )
        assert r.status_code == 422
