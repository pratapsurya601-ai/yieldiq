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


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(public_router.router)
    return TestClient(app)


def _get(client: TestClient, ticker: str) -> dict:
    r = client.get(f"/api/v1/public/manifest-history/{ticker}")
    assert r.status_code == 200, r.text
    return r.json()


def test_ntpc_surfaces_day94_init_wildcard(client: TestClient) -> None:
    """NTPC.NS is not in any scoped cohort, but the Day-94 init
    entry (scope='*') applies to every ticker."""
    body = _get(client, "NTPC.NS")
    assert body["ticker"] == "NTPC.NS"
    vids = [e["version_id"] for e in body["entries"]]
    assert "v_init_2026_05_22" in vids
    # NTPC is NOT in the metals cohort or any sector cohort, so
    # the scoped entries must NOT appear.
    assert "v_day95_metals_sector_pins" not in vids
    assert "v_day107a_it_services_cohort_2026_05_23" not in vids


def test_hdfcbank_surfaces_only_wildcard_entries(client: TestClient) -> None:
    """HDFCBANK has no banking-specific manifest entry today, so it
    only sees the wildcard entries (init, de_ratio null-safety,
    asset_turnover units, CAGR panel)."""
    body = _get(client, "HDFCBANK.NS")
    vids = [e["version_id"] for e in body["entries"]]
    # Must include the init anchor + at least one wildcard scope.
    assert "v_init_2026_05_22" in vids
    assert "v_day103c_cagr_panel_2026_05_22" in vids
    # Must NOT include any scoped cohort entry.
    forbidden = {
        "v_day95_metals_sector_pins",
        "v_day107a_it_services_cohort_2026_05_23",
        "v_day107b_fmcg_cohort_2026_05_23",
        "v_day107c_auto_cohort_2026_05_23",
        "v_day107d_capital_goods_cohort_2026_05_23",
    }
    assert forbidden.isdisjoint(set(vids))


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
    """TCS is in the Day-107a IT services cohort — that scoped entry
    must appear, in addition to the wildcards."""
    body = _get(client, "TCS.NS")
    vids = [e["version_id"] for e in body["entries"]]
    assert "v_day107a_it_services_cohort_2026_05_23" in vids
    assert "v_init_2026_05_22" in vids
    # NOT in metals.
    assert "v_day95_metals_sector_pins" not in vids


def test_field_scoped_entry_surfaces_fields_affected(
    client: TestClient,
) -> None:
    """The Day-103c CAGR entry has fields=['compounded_growth'].
    That list must round-trip as fields_affected."""
    body = _get(client, "RELIANCE.NS")
    cagr = next(
        (e for e in body["entries"]
         if e["version_id"] == "v_day103c_cagr_panel_2026_05_22"),
        None,
    )
    assert cagr is not None
    assert cagr["fields_affected"] == ["compounded_growth"]


def test_metals_ticker_surfaces_metals_cohort(client: TestClient) -> None:
    """HINDZINC is in the Day-95 metals cohort — verifies the bare-
    ticker matcher works for tickers without an exchange suffix."""
    body = _get(client, "HINDZINC")
    vids = [e["version_id"] for e in body["entries"]]
    assert "v_day95_metals_sector_pins" in vids


def test_bare_ticker_matches_exchange_suffix(client: TestClient) -> None:
    """TCS and TCS.NS and TCS.BO must all return the same entries —
    the matcher strips exchange suffix before comparing."""
    a = _get(client, "TCS")
    b = _get(client, "TCS.NS")
    c = _get(client, "TCS.BO")
    vids_a = {e["version_id"] for e in a["entries"]}
    vids_b = {e["version_id"] for e in b["entries"]}
    vids_c = {e["version_id"] for e in c["entries"]}
    assert vids_a == vids_b == vids_c


def test_cache_control_header_set(client: TestClient) -> None:
    r = client.get("/api/v1/public/manifest-history/NTPC.NS")
    assert r.status_code == 200
    cc = r.headers.get("Cache-Control", "")
    assert "s-maxage=3600" in cc
    assert "stale-while-revalidate" in cc
