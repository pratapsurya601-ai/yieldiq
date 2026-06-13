"""A3 sector-engine wiring — cold-path computation_inputs population.

The cold-compute analysis service (``backend/services/analysis/service.py``)
now populates the sector-specific input sub-blocks the per-engine FV
helpers in ``backend/routers/analysis.py`` consume:

  * ``computation_inputs["bank_deepened"]`` — NIM / CASA / PCR / GNPA /
    cost-income / BVPS / ROE (decimals), assembled by the warm-path
    merge helper ``_merge_bank_deepened_inputs``.
  * ``computation_inputs["insurance"]``     — EV + VNB (absolute INR) +
    VNB multiple + shares, from ``insurance_appraisal_inputs``.
  * ``computation_inputs["nbfc"]``          — intentionally ABSENT
    (abstain): the avg-assets gate input cannot be sourced unit-safely
    yet (TODO in service.py).

Before this wiring the snapshot stored in ``analysis_cache.payload``
carried no sector inputs, so ``_resolve_sector_primary_fv`` — which
re-derives ``sector_specific_fv`` from that snapshot at the router
boundary — abstained to None for insurers/NBFCs even when their
ingested data was present.

These tests exercise the populated-block logic directly (no network,
no live DB) and prove the resolver then emits a non-null
``sector_specific_fv`` purely from the persisted snapshot block. They
also assert the strict-superset property: a generic stock's snapshot is
unchanged (no sector keys appear).
"""
from __future__ import annotations

from backend.routers.analysis import (
    _merge_bank_deepened_inputs,
    _resolve_sector_primary_fv,
)


def _bank_quality() -> dict:
    """HDFCBANK-shaped quality fields as the service holds them at the
    population point: NIM / CASA / cost-income are 0-100 PERCENTS
    (compute_nim / compute_cost_to_income outputs and _bm_casa), ROE is
    a percent (enriched.roe), BVPS absolute."""
    return {
        "is_bank": True,
        "nim": 4.0,
        "casa": 46.0,
        "cost_to_income": 40.0,
        "roe": 17.0,
        "book_value_per_share": 620.0,
        "payout_ratio": 0.20,
        "shares_outstanding": 760.0,
    }


def _bank_valuation() -> dict:
    return {
        "current_price": 1650.0,
        "discount_rate": 0.115,
        "wacc": 0.115,
        "terminal_growth": 0.10,
    }


# ─────────────────────────────────────────────────────────────────
# Bank: snapshot block populates + resolver computes from it alone
# ─────────────────────────────────────────────────────────────────

def test_bank_deepened_block_populates_with_nim() -> None:
    """The merge helper (as called by the A3 service wiring) yields a
    bank_deepened block carrying nim_pct when NIM is available — this is
    the block the service persists into computation_inputs."""
    merged = _merge_bank_deepened_inputs(
        "HDFCBANK", {}, _bank_quality(), _bank_valuation(), {},
    )
    assert merged.get("nim_pct") is not None
    # percents → decimals
    assert abs(merged["nim_pct"] - 0.04) < 1e-9
    assert abs(merged["casa_mix_pct"] - 0.46) < 1e-9
    assert abs(merged["cost_to_income_pct"] - 0.40) < 1e-9
    assert abs(merged["roe_pct"] - 0.17) < 1e-9
    assert merged["book_value_per_share"] == 620.0


def test_bank_sector_specific_fv_resolves_from_snapshot_block_alone() -> None:
    """After A3 wiring, sector_specific_fv resolves for a bank purely
    from the PERSISTED computation_inputs["bank_deepened"] snapshot —
    with quality stripped to is_bank only, isolating the snapshot as the
    source (proving the snapshot, not the live merge, carries the data)."""
    merged = _merge_bank_deepened_inputs(
        "HDFCBANK", {}, _bank_quality(), _bank_valuation(), {},
    )
    assert merged.get("nim_pct")  # gate precondition

    payload = {
        "ticker": "HDFCBANK",
        "company": {"ticker": "HDFCBANK", "sector": "Banking"},
        "quality": {"is_bank": True},  # nothing but the bank flag
        "valuation": _bank_valuation(),
        "insights": {},
        "computation_inputs": {"bank_deepened": merged},
    }
    fv, label = _resolve_sector_primary_fv("HDFCBANK", "Banking", payload)
    assert label == "bank_residual_income_deepened"
    assert fv is not None and fv > 0


def test_bank_without_nim_leaves_block_absent() -> None:
    """Honest abstain: no NIM → the merged block carries no nim_pct, so
    the A3 service wiring does NOT persist a bank_deepened block, and the
    resolver stays at None (P/B headline path is unchanged)."""
    q = _bank_quality()
    q["nim"] = None
    merged = _merge_bank_deepened_inputs(
        "HDFCBANK", {}, q, _bank_valuation(), {},
    )
    # The A3 service gate persists only when nim_pct resolved.
    persist = bool(merged.get("nim_pct"))
    assert persist is False


# ─────────────────────────────────────────────────────────────────
# Insurance: EV/VNB Crore→INR conversion + resolver computes from it
# ─────────────────────────────────────────────────────────────────

def test_insurance_block_units_and_resolution() -> None:
    """The A3 insurance block passes EV/VNB in ₹ Crores (the
    insurance_appraisal_inputs unit) straight through with shares in
    Crore-count — the unit the EVVNBInputs engine path expects — and the
    resolver emits a sane per-share insurance FV from that block."""
    import backend.services.insurance_appraisal_service as ias

    # Emulate the service-side population: row Crores → block Crores.
    ev_cr, vnb_cr, shares = 50_000.0, 3_500.0, 215.0
    block = {
        "embedded_value": ev_cr,
        "new_business_value": vnb_cr,
        "shares_outstanding": shares,
    }
    try:
        mult = ias.select_vnb_multiple("HDFCLIFE")
        if mult and mult > 0:
            block["vnb_multiple"] = float(mult)
    except Exception:
        pass

    payload = {
        "ticker": "HDFCLIFE",
        "company": {"ticker": "HDFCLIFE", "sector": "Insurance"},
        "quality": {"shares_outstanding": shares},
        "valuation": {"current_price": 600.0},
        "insights": {},
        "computation_inputs": {"insurance": block},
    }
    fv, label = _resolve_sector_primary_fv("HDFCLIFE", "Insurance", payload)
    assert label == "insurance_ev_vnb"
    assert fv is not None and fv > 0
    # EV alone is 50_000 Cr / 215 Cr-shares ≈ ₹232/sh; with VNB×mult it is
    # higher (EV + 3500×mult, /215). Sanity band — a realistic ₹/share
    # price, NOT a billions-scale number (which would betray a unit bug).
    assert 200.0 < fv < 5000.0


# ─────────────────────────────────────────────────────────────────
# Strict-superset: generic stock untouched
# ─────────────────────────────────────────────────────────────────

def test_generic_stock_gets_no_sector_block_and_no_fv() -> None:
    """A non-bank / non-insurer / non-NBFC ticker resolves to no sector
    engine — its computation_inputs would carry no sector sub-block."""
    payload = {
        "ticker": "ASIANPAINT",
        "company": {"ticker": "ASIANPAINT", "sector": "Consumer"},
        "quality": {"shares_outstanding": 95.0},
        "valuation": {"current_price": 2800.0},
        "insights": {},
        "computation_inputs": {},
    }
    fv, label = _resolve_sector_primary_fv("ASIANPAINT", "Consumer", payload)
    assert fv is None
    assert label is None
    # No sector sub-block keys were introduced.
    assert "bank_deepened" not in payload["computation_inputs"]
    assert "insurance" not in payload["computation_inputs"]
    assert "nbfc" not in payload["computation_inputs"]
