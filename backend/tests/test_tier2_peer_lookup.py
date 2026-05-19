"""Tests for backend.services.tier2_peer_lookup."""
from __future__ import annotations

import pytest

from backend.services.tier2_peer_lookup import (
    _resolve_sector_key,
    fetch_peers_from_metrics_table,
)


# ── _resolve_sector_key — sector string normalisation ─────────────


def test_sector_key_resolves_common_strings():
    assert _resolve_sector_key("Cement") == "cement"
    assert _resolve_sector_key("CEMENT") == "cement"
    assert _resolve_sector_key("  cement  ") == "cement"
    assert _resolve_sector_key("IT Services") == "it_services"
    assert _resolve_sector_key("Information Technology") == "it_services"
    assert _resolve_sector_key("Pharma") == "pharma"
    assert _resolve_sector_key("Pharmaceuticals") == "pharma"
    assert _resolve_sector_key("FMCG") == "fmcg"
    assert _resolve_sector_key("Consumer Staples") == "fmcg"
    assert _resolve_sector_key("Banking") == "banking"
    assert _resolve_sector_key("Banks") == "banking"
    assert _resolve_sector_key("NBFC") == "nbfc"
    assert _resolve_sector_key("Capital Goods") == "capital_goods"


def test_sector_key_resolves_production_observed_strings():
    """Sector strings actually observed in prod analysis_cache
    (2026-05-19 query of payload->company->sector). The 2026-05-19
    expansion added these to broaden under-outlier safety-net
    coverage."""
    # Slash-form variants (Indian-prod convention)
    assert _resolve_sector_key("Metals/Mining") == "metals"
    assert _resolve_sector_key("Power/Utilities") == "power"
    assert _resolve_sector_key("Infrastructure/Construction") == "infra"
    assert _resolve_sector_key("Tech Hardware/Electronics") == "capital_goods"

    # Auto family
    assert _resolve_sector_key("Auto OEM") == "auto_oem"
    assert _resolve_sector_key("Auto Components") == "auto_oem"
    assert _resolve_sector_key("Tyres") == "auto_oem"

    # Industry-specific
    assert _resolve_sector_key("Airlines") == "infra"
    assert _resolve_sector_key("Logistics") == "infra"
    assert _resolve_sector_key("Real Estate") == "infra"
    assert _resolve_sector_key("Hospitals") == "healthcare"
    assert _resolve_sector_key("Consumer Durables") == "capital_goods"
    assert _resolve_sector_key("Renewable Energy") == "power"
    assert _resolve_sector_key("Solar") == "power"
    assert _resolve_sector_key("Textiles") == "retail"
    assert _resolve_sector_key("Specialty Chemicals") == "chemicals"
    assert _resolve_sector_key("Media & Entertainment") == "telecom"


def test_sector_key_returns_none_for_unknown():
    assert _resolve_sector_key("Spaceships") is None
    assert _resolve_sector_key("") is None
    assert _resolve_sector_key(None) is None


# ── fetch_peers_from_metrics_table — failure-mode contract ────────


def test_fetch_peers_empty_ticker_returns_empty():
    assert fetch_peers_from_metrics_table("", "Cement") == []
    assert fetch_peers_from_metrics_table(None, "Cement") == []


def test_fetch_peers_unknown_sector_returns_empty():
    # Unknown sector → no DIRECT_PEERS entry → []
    assert fetch_peers_from_metrics_table("INDIACEM.NS", "Spaceships") == []
    assert fetch_peers_from_metrics_table("INDIACEM.NS", None) == []


def test_fetch_peers_no_session_returns_empty(monkeypatch):
    """When the lazy session import returns None, fetch returns []."""
    import backend.services.tier2_peer_lookup as mod

    # Block the session-getter
    def _no_session():
        return None
    monkeypatch.setattr(
        "backend.services.analysis_cache_service._get_session",
        _no_session,
    )

    out = fetch_peers_from_metrics_table("INDIACEM.NS", "Cement")
    assert out == []


def test_fetch_peers_excludes_self_from_cohort():
    """The target ticker is never in its own peer list — even if it
    appears in DIRECT_PEERS for its sector. Validated against a stub
    session that records the params it was called with."""
    import backend.services.tier2_peer_lookup as mod

    class _StubSess:
        def __init__(self):
            self.last_params: dict | None = None

        def execute(self, _sql, params):
            # Mimic SQLAlchemy result API used by the function.
            class _R:
                def mappings(self_inner):
                    class _M:
                        def all(self_m):
                            return []
                    return _M()
            self.last_params = params
            return _R()

        def close(self):
            pass

    stub = _StubSess()
    fetch_peers_from_metrics_table(
        "INDIACEM.NS", "Cement", session=stub,
    )
    # Whatever peers got bound, INDIACEM must not be among them.
    assert stub.last_params is not None
    bound = {v.upper().replace(".NS", "").replace(".BO", "")
             for v in stub.last_params.values()}
    assert "INDIACEM" not in bound, (
        f"target excluded itself but params still contained: {bound}"
    )
