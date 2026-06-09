# backend/tests/test_holdco_classification_propagation.py
# ═══════════════════════════════════════════════════════════════
# Holdco classification propagation tests
# (fix/holdco-classification-single-source-of-truth, 2026-06-09)
#
# Verifies that the `is_holding_company` / HOLDING_COMPANIES single
# source of truth propagates into every downstream consumer that
# previously emitted bank-template or operating-company copy on
# BAJAJHLDNG and other pure holding companies:
#
#   * is_bank_like()                  → returns False for holdcos
#   * Honest Card invalidating list   → holdco-NAV triggers, not bank
#   * Worry Index Solvency driver     → no "bank ROA" copy on holdcos
#   * Prism `assign_verdict`          → Under Review when is_holdco=True
#   * ELI15 deterministic bullets     → SOTP framing, not "FV Rs 0"
#   * holdco_underlyings.json         → every key is in HOLDING_COMPANIES
#
# Anchor ticker is BAJAJHLDNG (the symptom reproducer in the task).
# HDFCBANK + RELIANCE are the negative-control non-holdcos that must
# NOT trip any new branch.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import pathlib

import pytest

from backend.services.analysis.constants import (
    HOLDING_COMPANIES,
    is_bank_like,
    is_holding_company,
)


class TestIsBankLikeHoldcoPrecedence:
    """The bank classifier must never claim a curated holdco."""

    @pytest.mark.parametrize(
        "ticker",
        [
            "BAJAJHLDNG",
            "BAJAJHLDNG.NS",
            "TATAINVEST",
            "MAHSCOOTER",
            "PILANIINVS",
            "KAMAHOLD",
        ],
    )
    def test_holdco_is_not_bank_like(self, ticker):
        # The pre-fix bug: BAJAJHLDNG sat in _NBFC_INSURANCE_BANKLIKE,
        # so `is_bank_like` returned True even though it's a pure
        # holding company. The QualityOutput.is_bank flag then propagated
        # bank-template copy into the Honest Card + Worry Index.
        assert is_bank_like(ticker) is False
        # Even with "Financial Services" sector hint, the holdco branch
        # wins.
        assert (
            is_bank_like(ticker, sector="Financial Services") is False
        )

    def test_hdfcbank_still_is_bank_like(self):
        # Negative control: a real bank stays classified as a bank.
        assert is_bank_like("HDFCBANK") is True
        assert is_bank_like("HDFCBANK.NS") is True

    def test_reliance_still_not_bank_like(self):
        # Negative control: a non-bank, non-holdco operating company.
        assert is_bank_like("RELIANCE", sector="Energy") is False


class TestHonestCardHoldcoBranch:
    """Honest Card 'would change our verdict' uses holdco template."""

    def _build(self, ticker="BAJAJHLDNG", is_holdco=True):
        from backend.services.analysis.honest_card_generator import (
            generate_honest_card,
        )
        company = {"ticker": ticker, "sector": "Financial Services"}
        quality = {
            "is_holdco": is_holdco,
            "is_bank": False,
            # Bank-template fields that the pre-fix code would have
            # used to produce the bank trigger list. Setting them
            # here confirms the holdco branch wins regardless.
            "roa": 11.31,
        }
        valuation = {
            "fair_value": None,
            "data_limited": True,
            "verdict": "data_limited",
        }
        return generate_honest_card(
            company=company,
            quality=quality,
            valuation=valuation,
        )

    def test_holdco_invalidating_conditions_no_bank_template(self):
        card = self._build()
        joined = " | ".join(card.invalidating_conditions).lower()
        # The pre-fix bug surfaced both of these:
        assert "loan / advances" not in joined
        assert "gross npa" not in joined
        # And the holdco branch should mention NAV / discount framing.
        assert "nav" in joined or "discount" in joined

    def test_hdfcbank_keeps_bank_invalidating_conditions(self):
        # Negative control — a real bank still gets the bank triggers.
        from backend.services.analysis.honest_card_generator import (
            generate_honest_card,
        )
        card = generate_honest_card(
            company={"ticker": "HDFCBANK", "sector": "Financial Services"},
            quality={"is_holdco": False, "is_bank": True, "roa": 1.8},
            valuation={"fair_value": 1500.0, "verdict": "undervalued"},
        )
        joined = " | ".join(card.invalidating_conditions).lower()
        # Bank trigger list must still fire for actual banks — protects
        # against an over-correction that empties the bank branch.
        assert "loan / advances" in joined or "gross npa" in joined


class TestWorryIndexHoldcoSolvency:
    """Worry Index Solvency driver must drop the 'bank ROA' line."""

    def test_holdco_solvency_does_not_render_bank_roa(self):
        from backend.services.analysis.worry_index import compute_worry_index
        quality = {
            "is_holdco": True,
            "is_bank": False,
            # If we naively read `roa` we'd emit "bank ROA 11.31%" —
            # that's the exact symptom in the BAJAJHLDNG repro.
            "roa": 11.31,
            "de_ratio": 0.05,
            "current_ratio": 5.2,
        }
        wi = compute_worry_index(quality=quality)
        contribs = wi.contributors
        solvency = next(c for c in contribs if c["component"] == "solvency")
        detail = (solvency["detail"] or "").lower()
        # Bank ROA copy must NOT appear.
        assert "bank roa" not in detail
        # Holdco framing should explain WHY solvency math is skipped.
        assert "holdco" in detail or "nav" in detail


class TestPrismAssignVerdictHoldcoGate:
    """assign_verdict must force Under Review for holdcos regardless of MoS."""

    def test_holdco_gate_overrides_mos_band(self):
        from backend.services.prism_service import assign_verdict
        # 6-axis hex with real scores so the null-pillar gate does NOT
        # fire — only the holdco gate should.
        hex_payload = {
            "axes": {
                "value":   {"score": 6.6},
                "quality": {"score": 7.0},
                "moat":    {"score": 5.5},
                "safety":  {"score": 6.0},
                "growth":  {"score": 5.0},
                "pulse":   {"score": 5.5},
            }
        }
        band, label, _composite, reason = assign_verdict(
            hex_payload, mos_pct=-35.0, is_holdco=True
        )
        # Without the holdco gate this would land at "expensive" /
        # "Notably above fair value" — the exact symptom on
        # BAJAJHLDNG.
        assert band == "data_limited"
        assert label == "Under Review"
        assert reason is not None
        # Reason must reference holding-company / SOTP framing for
        # the SEBI-safe explainer surface.
        assert (
            "holding" in (reason or "").lower()
            or "sotp" in (reason or "").lower()
        )

    def test_non_holdco_band_unchanged(self):
        from backend.services.prism_service import assign_verdict
        hex_payload = {
            "axes": {
                k: {"score": 6.0}
                for k in ("value", "quality", "moat", "safety", "growth", "pulse")
            }
        }
        band, label, _composite, _reason = assign_verdict(
            hex_payload, mos_pct=30.0, is_holdco=False
        )
        # Non-holdcos: MoS 30% → "Below fair value region".
        assert band in ("undervalued", "deepValue")


class TestELI15HoldcoBullet:
    """ELI15 deterministic b1 must mention SOTP / underlyings for holdcos."""

    def test_holdco_b1_names_underlying_constituents(self):
        from backend.services.eli15_thesis_service import (
            ThesisContext,
            deterministic_template_bullets,
        )
        ctx = ThesisContext(
            ticker="BAJAJHLDNG",
            company_name="Bajaj Holdings",
            sector="Financial Services",
            verdict="data_limited",
            verdict_display="insufficient data",
            current_price=15000.0,
            fair_value=None,
            mos_pct=None,
            is_holdco=True,
            holdco_underlyings=("BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV"),
        )
        bullets = deterministic_template_bullets(ctx)
        assert len(bullets) == 3
        b1_lower = bullets[0].lower()
        # The b1 must name the SOTP framing, NOT "model fair value
        # reference is Rs 0" (the pre-fix symptom).
        assert "rs 0" not in b1_lower
        assert "holding company" in b1_lower or "sum-of-parts" in b1_lower
        # Underlying constituent names must be present so the user
        # can click through to the actual value drivers.
        assert "bajaj-auto" in b1_lower

    def test_holdco_b1_empty_underlyings_still_clean(self):
        # NDTV is a holdco with no curated underlying tickers — must
        # still emit a SOTP-framed b1 without erroring.
        from backend.services.eli15_thesis_service import (
            ThesisContext,
            deterministic_template_bullets,
        )
        ctx = ThesisContext(
            ticker="NDTV",
            company_name="NDTV",
            sector="Communication Services",
            verdict="data_limited",
            verdict_display="insufficient data",
            current_price=200.0,
            fair_value=None,
            mos_pct=None,
            is_holdco=True,
            holdco_underlyings=(),
        )
        b1 = deterministic_template_bullets(ctx)[0]
        assert "rs 0" not in b1.lower()
        assert "holding company" in b1.lower()


class TestHoldcoUnderlyingsJSONShape:
    """holdco_underlyings.json invariants — keys must be in HOLDING_COMPANIES."""

    def test_every_key_is_a_curated_holdco(self):
        path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "data" / "holdco_underlyings.json"
        )
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # _meta is the only allowed non-ticker key.
        keys = [k for k in data.keys() if k != "_meta"]
        # Otherwise the holdco branch in peers_service /
        # eli15_thesis_service would emit a constituent list for
        # a ticker that is NOT classified as a holdco by the rest
        # of the system — a silent drift bug.
        for k in keys:
            assert k in HOLDING_COMPANIES, (
                f"{k} is in holdco_underlyings.json but NOT in "
                f"HOLDING_COMPANIES — single source of truth violated"
            )

    def test_underlyings_are_strings(self):
        path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "data" / "holdco_underlyings.json"
        )
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for k, v in data.items():
            if k == "_meta":
                continue
            assert isinstance(v, list)
            for sym in v:
                assert isinstance(sym, str)
                assert sym.upper() == sym  # uppercased NSE symbols


class TestHoldingCompaniesSeedListContents:
    """Regression guard against accidental holdco-seed removals."""

    def test_seed_list_contains_user_reported_tickers(self):
        # Tickers the task brief enumerated as "likely affected":
        # BAJAJHLDNG, MAHSCOOTER, TATAINVEST.
        for ticker in (
            "BAJAJHLDNG", "MAHSCOOTER", "TATAINVEST",
            "PILANIINVS", "KAMAHOLD", "MCLEODRUSS",
        ):
            assert is_holding_company(ticker), (
                f"{ticker} must be classified as a holding company "
                f"so the propagation guard fires"
            )
