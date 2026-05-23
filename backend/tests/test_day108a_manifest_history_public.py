"""Day-108a (2026-05-23): per-ticker manifest history public endpoint.

Locks the contract for
``GET /api/v1/public/manifest-history/{ticker}``:

  * Wildcard ("*") entries surface for every ticker.
  * Scoped entries (e.g. metals cohort, IT services cohort) only
    surface for the tickers in scope, bare-ticker matched so the
    .NS / .BO suffix is irrelevant.
  * Field-scoped entries surface their ``fields_affected`` list.
  * Ordering is newest-first by ``applied_at``.
  * Unknown tickers return 200 with an empty list (not 404) so the
    UI can render a stable empty state.
  * NTPC.NS surfaces the Day-94 init wildcard plus the
    Day-95 metals cohort is NOT in scope for NTPC.
  * HDFCBANK.NS surfaces only the wildcard entries (no
    banking-specific scoped entries in MANIFEST today).

Task #123 update (2026-05-23): the anon response no longer carries
the raw ``version_id`` (an internal cadence handle leaking onto a
public, SEO-facing surface). Membership assertions that previously
matched on ``version_id`` now match on the engine-stable
``fields_affected`` projection plus the ``applied_at`` timestamp,
which are both derived from the same MANIFEST entries but are not
internal-vocabulary. The "auth-vs-anon shape" contract proper is
exercised in ``test_phase_g_public_manifest_sanitization.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers import public as public_router  # noqa: E402
from backend.services.cache_invalidation_manifest import MANIFEST  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(public_router.router)
    return TestClient(app)


def _get(client: TestClient, ticker: str) -> dict:
    r = client.get(f"/api/v1/public/manifest-history/{ticker}")
    assert r.status_code == 200, r.text
    return r.json()


def _applied_at_for(version_id: str) -> str:
    """Look up a MANIFEST entry's applied_at ISO string by version_id.

    Used as a stable membership probe on the anon response — the anon
    shape strips ``version_id`` (Task #123) but ``applied_at`` survives
    and is unique per entry in the live MANIFEST.
    """
    for entry in MANIFEST:
        if entry.get("version_id") == version_id:
            applied = entry.get("applied_at")
            return applied.isoformat() if applied else ""
    raise AssertionError(f"unknown manifest version_id {version_id!r}")


def _applied_ats(body: dict) -> set[str]:
    return {e.get("applied_at") for e in body.get("entries", []) if e.get("applied_at")}


def test_ntpc_surfaces_day94_init_wildcard(client: TestClient) -> None:
    """NTPC.NS is not in any scoped cohort, but the init wildcard
    entry (scope='*') applies to every ticker."""
    body = _get(client, "NTPC.NS")
    assert body["ticker"] == "NTPC.NS"
    ats = _applied_ats(body)
    assert _applied_at_for("v_init_2026_05_22") in ats
    # NTPC is NOT in the metals cohort or any sector cohort, so
    # the scoped entries must NOT appear.
    assert _applied_at_for("v_day95_metals_sector_pins") not in ats
    assert _applied_at_for("v_day107a_it_services_cohort_2026_05_23") not in ats


def test_hdfcbank_surfaces_only_wildcard_entries(client: TestClient) -> None:
    """HDFCBANK has no banking-specific manifest entry today, so it
    only sees the wildcard entries (init, de_ratio null-safety,
    asset_turnover units, CAGR panel)."""
    body = _get(client, "HDFCBANK.NS")
    ats = _applied_ats(body)
    # Must include the init anchor + at least one wildcard scope.
    assert _applied_at_for("v_init_2026_05_22") in ats
    assert _applied_at_for("v_day103c_cagr_panel_2026_05_22") in ats
    # Must NOT include any non-wildcard cohort entry that doesn't
    # cover HDFCBANK. (HDFCBANK IS in the v_day109a banking cohort
    # added 2026-05-23 — that entry IS expected to surface.)
    forbidden = {
        _applied_at_for("v_day95_metals_sector_pins"),
        _applied_at_for("v_day107a_it_services_cohort_2026_05_23"),
        _applied_at_for("v_day107b_fmcg_cohort_2026_05_23"),
        _applied_at_for("v_day107c_auto_cohort_2026_05_23"),
        _applied_at_for("v_day107d_capital_goods_cohort_2026_05_23"),
    }
    assert forbidden.isdisjoint(ats)


def test_unknown_ticker_returns_200_with_wildcards(client: TestClient) -> None:
    """Unknown tickers don't 404 — wildcard entries still apply to
    *any* ticker string, so we expect a non-empty list. The point
    of the test is that the endpoint never raises."""
    body = _get(client, "ZZZNONEXISTENT.NS")
    assert body["ticker"] == "ZZZNONEXISTENT.NS"
    # Wildcards apply to every string, including unknown ones.
    assert isinstance(body["entries"], list)
    assert any(
        e["fields_affected"] == ["*"]
        for e in body["entries"]
    )


def test_entries_ordered_newest_first(client: TestClient) -> None:
    body = _get(client, "TCS.NS")  # in the IT services cohort
    entries = body["entries"]
    assert len(entries) >= 2
    isos = [e["applied_at"] for e in entries if e["applied_at"]]
    assert isos == sorted(isos, reverse=True)


def test_tcs_surfaces_it_services_cohort(client: TestClient) -> None:
    """TCS is in the IT services cohort — that scoped entry must
    appear, in addition to the wildcards."""
    body = _get(client, "TCS.NS")
    ats = _applied_ats(body)
    assert _applied_at_for("v_day107a_it_services_cohort_2026_05_23") in ats
    assert _applied_at_for("v_init_2026_05_22") in ats
    # NOT in metals.
    assert _applied_at_for("v_day95_metals_sector_pins") not in ats


def test_field_scoped_entry_surfaces_fields_affected(
    client: TestClient,
) -> None:
    """The CAGR-panel entry has fields=['compounded_growth']. That
    list must round-trip as fields_affected, matched by stable
    applied_at (Task #123 anon shape strips version_id)."""
    body = _get(client, "RELIANCE.NS")
    target_at = _applied_at_for("v_day103c_cagr_panel_2026_05_22")
    cagr = next(
        (e for e in body["entries"] if e.get("applied_at") == target_at),
        None,
    )
    assert cagr is not None
    assert cagr["fields_affected"] == ["compounded_growth"]


def test_metals_ticker_surfaces_metals_cohort(client: TestClient) -> None:
    """HINDZINC is in the metals cohort — verifies the bare-ticker
    matcher works for tickers without an exchange suffix."""
    body = _get(client, "HINDZINC")
    ats = _applied_ats(body)
    assert _applied_at_for("v_day95_metals_sector_pins") in ats


def test_bare_ticker_matches_exchange_suffix(client: TestClient) -> None:
    """TCS and TCS.NS and TCS.BO must all return the same entries —
    the matcher strips exchange suffix before comparing. Compared by
    applied_at since the anon shape no longer carries version_id."""
    a = _get(client, "TCS")
    b = _get(client, "TCS.NS")
    c = _get(client, "TCS.BO")
    assert _applied_ats(a) == _applied_ats(b) == _applied_ats(c)


def test_cache_control_header_set(client: TestClient) -> None:
    r = client.get("/api/v1/public/manifest-history/NTPC.NS")
    assert r.status_code == 200
    cc = r.headers.get("Cache-Control", "")
    assert "s-maxage=3600" in cc
    assert "stale-while-revalidate" in cc
