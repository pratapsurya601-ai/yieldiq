"""Day-40 (2026-05-20): regression guards for JSON-LD + sitemap.

Two HIGH-severity SEO fixes from Day-39 audit:
  1. Zero JSON-LD anywhere → new JsonLd.tsx component emits
     FinancialProduct + BreadcrumbList on /analysis/[ticker]
  2. /analysis/{ticker} missing from dynamic sitemap → added with
     priority 0.9 (canonical surface); revalidate cut from 24h to 1h
"""
from __future__ import annotations
from pathlib import Path


_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
_F = _FRONTEND / "src"
_JSONLD = _F / "app" / "(app)" / "analysis" / "[ticker]" / "JsonLd.tsx"
_PUBLIC_ANALYSIS = _F / "app" / "(app)" / "analysis" / "[ticker]" / "PublicAnalysis.tsx"
_SITEMAP = _F / "app" / "sitemap.ts"
_PUBLIC_SITEMAP_XML = _FRONTEND / "public" / "sitemap.xml"


# ── JsonLd component ─────────────────────────────────────────


def test_jsonld_component_exists():
    assert _JSONLD.exists(), (
        "JsonLd.tsx must exist at "
        "src/app/(app)/analysis/[ticker]/JsonLd.tsx"
    )


def test_jsonld_emits_financial_product_schema():
    src = _JSONLD.read_text(encoding="utf-8")
    assert '"@type": "FinancialProduct"' in src, (
        "FinancialProduct schema missing — required for Google "
        "finance rich results."
    )
    # Provider must be Organization YieldIQ (object-literal syntax in
    # TS source has bare keys — check for the value's surrounding
    # context instead of the quoted-key form)
    assert '"@type": "Organization"' in src
    assert 'name: "YieldIQ"' in src
    # Offers price tied to current_price
    assert '"@type": "Offer"' in src
    assert 'priceCurrency: "INR"' in src


def test_jsonld_emits_breadcrumb_schema():
    src = _JSONLD.read_text(encoding="utf-8")
    assert '"@type": "BreadcrumbList"' in src
    # Exchange → Sector → Stock list items
    assert '"@type": "ListItem"' in src


def test_jsonld_exposes_yieldiq_score_and_verdict():
    """Custom YieldIQ fields should land in additionalProperty so
    they're indexable but don't break the FinancialProduct schema."""
    src = _JSONLD.read_text(encoding="utf-8")
    assert "additionalProperty" in src
    assert "YieldIQ Score" in src
    assert "Margin of Safety" in src
    assert "Fair Value" in src


def test_jsonld_has_test_hooks():
    """data-testid for Day-38 visual-regression inventory."""
    src = _JSONLD.read_text(encoding="utf-8")
    assert 'data-testid="jsonld-financialproduct"' in src
    assert 'data-testid="jsonld-breadcrumb"' in src


def test_public_analysis_renders_jsonld():
    src = _PUBLIC_ANALYSIS.read_text(encoding="utf-8")
    assert 'import JsonLd from "@/app/(app)/analysis/[ticker]/JsonLd"' in src
    assert "<JsonLd" in src
    # Must pass all the required props
    for prop in (
        "ticker={tickerUpper}",
        "currentPrice={price}",
        "fairValue={fair_value}",
        "mosPct={mos_pct}",
        "yieldiqScore={yieldiq_score_100}",
        "verdict={verdictText}",
    ):
        assert prop in src, f"JsonLd missing required prop: {prop}"


# ── Sitemap ──────────────────────────────────────────────────


def test_sitemap_includes_analysis_route():
    src = _SITEMAP.read_text(encoding="utf-8")
    assert "https://yieldiq.in/analysis/${encodeURIComponent(t.ticker)}" in src, (
        "Dynamic sitemap missing /analysis/{ticker}. Google indexes "
        "only what's in the sitemap — without this route the canonical "
        "analysis URL is invisible to search."
    )
    # analysisPages variable defined
    assert "analysisPages: MetadataRoute.Sitemap" in src


def test_sitemap_revalidate_reduced_to_1h():
    """86400 (24h) → 3600 (1h) so new tickers surface in search
    within an hour of being added to the all-tickers endpoint."""
    src = _SITEMAP.read_text(encoding="utf-8")
    assert "revalidate: 3600" in src
    assert "revalidate: 86400" not in src, (
        "Old 24h revalidate still present — Day-40 cut to 1h."
    )


def test_stale_public_sitemap_xml_removed():
    """The hardcoded public/sitemap.xml from 2026-04-25 only listed
    20 tickers and was overriding the dynamic sitemap for some
    crawlers. Must be removed."""
    assert not _PUBLIC_SITEMAP_XML.exists(), (
        "Stale public/sitemap.xml still present — Day-40 removed it "
        "in favour of the dynamic src/app/sitemap.ts route."
    )


def test_sitemap_includes_analysis_in_combined_stockpages():
    """The final concatenation should include all 4 route families."""
    src = _SITEMAP.read_text(encoding="utf-8")
    assert "stockPages = [...fairValuePages, ...analysisPages, ...hexPages, ...prismPages]" in src
