# backend/tests/test_warm_path_estimator_coverage.py
# ═══════════════════════════════════════════════════════════════
# v_composite_warm_path_estimator_fix_2026_06_11
#
# Covers the three warm-path estimator-coverage fixes:
#   1. Bank residual income is self-sufficient on cached payloads —
#      a dict payload WITHOUT computation_inputs but WITH the bank
#      KPI fields on quality (nim / casa / cost_to_income / roe /
#      book_value_per_share) routes to the deepened engine.
#   2. Peer multiples compute from explicit market_metrics fallbacks
#      when the payload lacks quality.pe_ratio / pb_ratio (which the
#      canonical response model never carried), and the cohort
#      median resolver sources pe/pb from market_metrics.
#   3. Reason strings rendered on the composition panel are
#      sentences, not machine slugs / raw field names — and the
#      genuinely-data-missing bank case keeps an honest reason.
# Plus regressions: non-bank routing unchanged; payload slots still
# win over the market_metrics fallback.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import pytest

from backend.routers.analysis import (
    _humanize_three_stage_reason,
    _inject_sector_specific_dict,
    _inject_three_stage_dict,
    _merge_bank_deepened_inputs,
    _resolve_sector_primary_fv,
)
from backend.services.multiples_fv import compute_multiples_fv

# Bound at import time, BEFORE the autouse `_no_db` fixture patches the
# module attribute — lets the bare-keying regression test exercise the
# real implementation.
from backend.services.market_multiples import _fetch_rows as _real_fetch_rows


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

def _warm_bank_payload(*, with_nim: bool = True) -> dict:
    """HDFCBANK-shaped WARM-PATH payload: no computation_inputs at
    all (cached tier payloads never carry the bank_deepened block),
    bank KPI data on the quality block as the canonical model
    surfaces it (percent units)."""
    quality: dict = {
        "is_bank": True,
        "roe": 17.5,                     # percent (QualityOutput.roe)
        "casa": 46.0,                    # percent (QualityOutput.casa)
        "cost_to_income": 40.0,          # percent
        "book_value_per_share": 600.0,
    }
    if with_nim:
        quality["nim"] = 4.1             # percent (QualityOutput.nim)
    return {
        "ticker": "HDFCBANK",
        "company": {"ticker": "HDFCBANK", "sector": "Banking"},
        "quality": quality,
        "valuation": {
            "fair_value": 1141.82,
            "discount_rate": 0.125,
            "wacc": 0.125,
            "terminal_growth": 0.10,
            "current_price": 1500.0,
            "base_case": 1141.82,
            "bull_case": 1450.0,
            "bear_case": 850.0,
        },
        "insights": {
            "dividend": {
                "dividend_rate_per_share": 19.5,
                "consecutive_years": 8,
                "payout_ratio_pct": 26.0,
            },
        },
        # NO computation_inputs — the warm-path defining property.
    }


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Keep every test hermetic — no bank-KPI DB row, no
    market_metrics rows unless a test patches them in."""
    monkeypatch.setattr(
        "backend.routers.analysis._fetch_bank_kpi_row", lambda t: None,
    )
    from backend.services import market_multiples
    monkeypatch.setattr(
        market_multiples, "_fetch_rows",
        lambda tickers: {t: {"pe": None, "pb": None} for t in tickers},
    )
    market_multiples._reset_cache_for_tests()
    yield
    market_multiples._reset_cache_for_tests()


# ─────────────────────────────────────────────────────────────────
# 1. Bank residual income — warm-path self-sufficiency
# ─────────────────────────────────────────────────────────────────

class TestBankResidualIncomeWarmPath:
    def test_routes_without_computation_inputs_when_quality_has_nim(self):
        payload = _warm_bank_payload(with_nim=True)
        fv, label = _resolve_sector_primary_fv(
            ticker="HDFCBANK", sector="Banking", payload=payload,
        )
        assert fv is not None and fv > 0
        assert label == "bank_residual_income_deepened"

    def test_inject_writes_sector_specific_fields(self):
        payload = _warm_bank_payload(with_nim=True)
        _inject_sector_specific_dict(payload)
        assert payload["sector_specific_fv"] is not None
        assert payload["sector_specific_fv"] > 0
        assert payload["sector_specific_label"] == (
            "bank_residual_income_deepened"
        )
        assert payload["sector_specific_reason"] is None

    def test_genuinely_missing_nim_returns_none_with_honest_reason(self):
        payload = _warm_bank_payload(with_nim=False)
        fv, label = _resolve_sector_primary_fv(
            ticker="HDFCBANK", sector="Banking", payload=payload,
        )
        assert fv is None
        assert label is None
        reason = payload.get("sector_specific_reason") or ""
        assert "net interest margin" in reason.lower()
        # SEBI-safe + jargon-free: no raw slugs, no advisory verbs.
        assert "_" not in reason
        assert "nim_pct" not in reason

    def test_inject_stamps_honest_reason_despite_preseeded_none(self):
        # Regression: `_inject_sector_specific_dict` pre-seeds
        # `sector_specific_reason` with None as a defensive default
        # BEFORE the resolver runs. A setdefault inside the resolver
        # therefore no-ops on every warm dict path and the user saw a
        # silent dash (reason=None) instead of the honest sentence —
        # verified live on the cached HDFCBANK payload, where NIM is
        # genuinely absent from every source. The reason write must
        # survive the pre-seeded key.
        payload = _warm_bank_payload(with_nim=False)
        _inject_sector_specific_dict(payload)
        assert payload["sector_specific_fv"] is None
        reason = payload.get("sector_specific_reason") or ""
        assert "net interest margin" in reason.lower()

    def test_snapshot_block_still_wins_when_present(self):
        # Forward-compat: an explicit computation_inputs.bank_deepened
        # block keeps precedence over the quality-derived fallbacks.
        payload = _warm_bank_payload(with_nim=True)
        payload["computation_inputs"] = {
            "bank_deepened": {
                "nim_pct": 0.041,
                "book_value_per_share": 600.0,
                "roe_pct": 0.175,
                "cost_of_equity": 0.125,
                "sustainable_growth": 0.10,
                "payout_ratio": 0.26,
            },
        }
        fv, label = _resolve_sector_primary_fv(
            ticker="HDFCBANK", sector="Banking", payload=payload,
        )
        assert fv is not None and fv > 0
        assert label == "bank_residual_income_deepened"

    def test_merge_converts_percent_units_to_decimals(self):
        payload = _warm_bank_payload(with_nim=True)
        merged = _merge_bank_deepened_inputs(
            "HDFCBANK", {}, payload["quality"], payload["valuation"],
            payload["insights"],
        )
        assert merged["nim_pct"] == pytest.approx(0.041)
        assert merged["casa_mix_pct"] == pytest.approx(0.46)
        assert merged["cost_to_income_pct"] == pytest.approx(0.40)
        assert merged["roe_pct"] == pytest.approx(0.175)
        assert merged["payout_ratio"] == pytest.approx(0.26)
        assert merged["book_value_per_share"] == pytest.approx(600.0)

    def test_db_kpi_row_fills_gaps(self, monkeypatch):
        monkeypatch.setattr(
            "backend.routers.analysis._fetch_bank_kpi_row",
            lambda t: {
                "casa_pct": 38.0,
                "pcr_pct": 72.5,
                "gnpa_pct": 1.2,
                "cost_to_income_pct": 40.1,
            },
        )
        payload = _warm_bank_payload(with_nim=True)
        # Remove the payload casa / cost-to-income so the DB fills.
        payload["quality"].pop("casa")
        payload["quality"].pop("cost_to_income")
        merged = _merge_bank_deepened_inputs(
            "HDFCBANK", {}, payload["quality"], payload["valuation"],
            payload["insights"],
        )
        assert merged["casa_mix_pct"] == pytest.approx(0.38)
        assert merged["provision_coverage_pct"] == pytest.approx(0.725)
        assert merged["gnpa_pct"] == pytest.approx(0.012)
        assert merged["cost_to_income_pct"] == pytest.approx(0.401)

    def test_non_bank_routing_unchanged(self):
        # RELIANCE-shaped industrial: must NOT pick up the bank label
        # and must not stamp a bank reason.
        payload = {
            "ticker": "RELIANCE",
            "company": {"ticker": "RELIANCE", "sector": "Energy"},
            "quality": {"is_bank": False, "roe": 9.0},
            "valuation": {
                "fair_value": 2900.0,
                "current_price": 2800.0,
                "wacc": 0.105,
                "terminal_growth": 0.04,
            },
            "insights": {},
        }
        fv, label = _resolve_sector_primary_fv(
            ticker="RELIANCE", sector="Energy", payload=payload,
        )
        assert label != "bank_residual_income_deepened"
        assert payload.get("sector_specific_reason") is None


# ─────────────────────────────────────────────────────────────────
# 2. Peer multiples — market_metrics fallback + cohort medians
# ─────────────────────────────────────────────────────────────────

class TestMultiplesFvFallback:
    def test_explicit_ticker_pb_fallback_used_when_payload_lacks_slots(self):
        payload = {
            "quality": {},  # canonical model never carried pe/pb slots
            "valuation": {"current_price": 750.0},
        }
        fv, method = compute_multiples_fv(
            payload, {"pe": None, "pb": 1.8}, ticker_pe=None, ticker_pb=2.0,
        )
        assert method == "pb"
        assert fv == pytest.approx(750.0 * (1.8 / 2.0), abs=0.01)

    def test_payload_slots_win_over_fallback(self):
        payload = {
            "quality": {"pe_ratio": 20.0},
            "valuation": {"current_price": 100.0},
        }
        fv, method = compute_multiples_fv(
            payload, {"pe": 25.0, "pb": None}, ticker_pe=10.0,
        )
        assert method == "pe"
        # Uses payload PE 20, not fallback 10.
        assert fv == pytest.approx(100.0 * (25.0 / 20.0), abs=0.01)

    def test_no_inputs_still_returns_none(self):
        payload = {"quality": {}, "valuation": {"current_price": 100.0}}
        fv, method = compute_multiples_fv(payload, {"pe": None, "pb": None})
        assert fv is None and method is None

    def test_fetch_rows_queries_bare_and_keys_canonical(self, monkeypatch):
        # Regression: `market_metrics.ticker` stores BARE symbols
        # (HDFCBANK), while callers and the TTL cache key canonical
        # suffixed symbols (HDFCBANK.NS). Querying the table with
        # suffixed symbols silently matches ZERO rows — verified live:
        # every PE/PB lookup returned None despite the table carrying
        # pe 16.7 / pb 1.96 for HDFCBANK. The SQL params must be bare
        # and the result must come back keyed canonical.
        from backend.services import market_multiples

        captured: dict = {}

        class _FakeResult:
            def fetchall(self):
                # DB rows key BARE tickers, like the real table.
                return [("HDFCBANK", 16.7, 1.96)]

        class _FakeSession:
            def execute(self, _sql, params):
                captured.update(params)
                return _FakeResult()

            def close(self):
                pass

        monkeypatch.setattr(
            market_multiples, "_get_session", lambda: _FakeSession(),
        )
        out = _real_fetch_rows(["HDFCBANK.NS"])
        assert captured["tickers"] == ["HDFCBANK"]      # bare to the DB
        assert out["HDFCBANK.NS"]["pe"] == pytest.approx(16.7)
        assert out["HDFCBANK.NS"]["pb"] == pytest.approx(1.96)

    def test_cohort_medians_come_from_market_metrics(self, monkeypatch):
        from backend.services import sector_medians_for_ticker as smt
        from backend.services import market_multiples

        # 12-bank cohort — market_metrics carries pb for each member.
        def _fake_fetch(tickers):
            return {t: {"pe": 17.0, "pb": 2.0} for t in tickers}

        monkeypatch.setattr(market_multiples, "_fetch_rows", _fake_fetch)
        market_multiples._reset_cache_for_tests()
        # Cached payloads exist but (faithfully) carry no quality pe/pb.
        monkeypatch.setattr(
            "backend.services.analysis_cache_service.get_cached_latest",
            lambda symbol: {"quality": {"roe": 12.0}},
        )
        smt._reset_cache_for_tests()
        medians = smt.get_sector_medians_for_ticker("HDFCBANK")
        assert medians["pe"] == pytest.approx(17.0)
        assert medians["pb"] == pytest.approx(2.0)
        assert medians["roe"] == pytest.approx(12.0)
        smt._reset_cache_for_tests()

    def test_banks_cohort_query_matches_nse_style_rows(self):
        # The Banks cohort SQL must accept canonical_sector variants
        # AND NSE-style raw sectors without the industry filter.
        from backend.services.sector_percentile import _build_cohort_query
        sql, params = _build_cohort_query("Banks")
        assert "canonicals" in params
        assert "Private Bank" in params["canonicals"]
        assert "sectors_unambiguous" in params
        assert "Bank" in params["sectors_unambiguous"]
        # industry filter only guards the ambiguous Financial Services
        # branch — the unambiguous branch must not reference it.
        assert "sectors_unambiguous" in sql
        assert "industry ILIKE" in sql

    def test_bank_singular_sector_canonicalizes(self):
        from backend.services.sector_percentile import _canonical_sector
        assert _canonical_sector("Bank") == "Banks"
        assert _canonical_sector("Private Banks") == "Banks"
        assert _canonical_sector("Banking") == "Banks"


# ─────────────────────────────────────────────────────────────────
# 3. Reason humanization (backend source)
# ─────────────────────────────────────────────────────────────────

class TestReasonHumanization:
    def test_three_stage_bank_copy(self):
        out = _humanize_three_stage_reason(
            "base_year_fcf_non_positive", is_bank=True,
        )
        assert "Banks" in out
        assert "free cash flow" in out
        assert "base_year_fcf_non_positive" not in out

    def test_three_stage_non_bank_copy(self):
        out = _humanize_three_stage_reason(
            "base_year_fcf_non_positive", is_bank=False,
        )
        assert "free cash flow" in out.lower()
        assert "_" not in out

    def test_three_stage_inject_writes_humanized_reason_for_bank(self):
        payload = _warm_bank_payload(with_nim=True)
        _inject_three_stage_dict(payload)
        assert payload["three_stage_fv"] is None
        reason = payload["three_stage_reason"]
        assert "base_year_fcf_non_positive" not in reason
        assert "free cash flow" in reason.lower()

    def test_ddm_low_payout_reason_drops_raw_field_name(self):
        from backend.services.dividend_discount_model_service import (
            is_ddm_applicable,
        )
        applicable, reason = is_ddm_applicable(
            ticker="HDFCBANK",
            sector="Banking",
            payout_ratio=0.26,
            dividend_streak_years=8,
        )
        assert applicable is False
        assert "payout_ratio" not in reason
        assert "26%" in reason
        assert "30%" in reason
        assert "payout" in reason.lower()
