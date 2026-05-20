"""Day-41 + Day-42 (2026-05-20): combined SEO polish.

Day-41: canonical URL on /analysis/[ticker]; Breadcrumb links
Day-42: robots.txt explicit Allow + Crawl-delay; og:image:type
"""
from __future__ import annotations
from pathlib import Path


_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
_LAYOUT = _FRONTEND / "src" / "app" / "(app)" / "analysis" / "[ticker]" / "layout.tsx"
_BREADCRUMB = _FRONTEND / "src" / "components" / "analysis" / "Breadcrumb.tsx"
_ROBOTS = _FRONTEND / "public" / "robots.txt"


# ── Day-41: canonical ───────────────────────────────────────


def test_layout_emits_canonical_url():
    src = _LAYOUT.read_text(encoding="utf-8")
    assert "alternates: {" in src
    assert "canonical: `https://yieldiq.in/analysis/${ticker}`" in src, (
        "Canonical URL missing from layout metadata. Without this, "
        "Google indexes URL variants (?utm_source=...) as duplicates."
    )


# ── Day-41: Breadcrumb internal links ───────────────────────


def test_breadcrumb_imports_next_link():
    src = _BREADCRUMB.read_text(encoding="utf-8")
    assert 'import Link from "next/link"' in src, (
        "Breadcrumb must import Next Link so exchange/sector/cap "
        "pills are server-rendered crawlable <a> tags."
    )


def test_breadcrumb_exchange_links_to_stocks_facet():
    src = _BREADCRUMB.read_text(encoding="utf-8")
    assert "/stocks?exchange=${exchange.toLowerCase()}" in src


def test_breadcrumb_sector_links_to_stocks_facet():
    src = _BREADCRUMB.read_text(encoding="utf-8")
    assert "/stocks?sector=${encodeURIComponent(sector)}" in src


def test_breadcrumb_cap_bucket_links_to_stocks_facet():
    src = _BREADCRUMB.read_text(encoding="utf-8")
    assert "/stocks?cap=" in src


def test_breadcrumb_index_links_for_nifty_variants():
    src = _BREADCRUMB.read_text(encoding="utf-8")
    # indexHref() helper maps NIFTY 50 / BANK / IT to landing pages
    assert "indexHref" in src or "indexHref(" in src
    assert "/nifty50" in src
    assert "/nifty-bank" in src
    assert "/nifty-it" in src


def test_breadcrumb_has_testid_for_visual_regression():
    src = _BREADCRUMB.read_text(encoding="utf-8")
    assert 'data-testid="breadcrumb-classification"' in src


# ── Day-42: og:image:type ───────────────────────────────────


def test_layout_emits_og_image_type():
    src = _LAYOUT.read_text(encoding="utf-8")
    assert 'type: "image/png"' in src, (
        "og:image:type missing — older scrapers (LinkedIn, WhatsApp) "
        "need this hint to render the preview correctly."
    )


# ── Day-42: robots.txt ───────────────────────────────────────


def test_robots_allows_stock_seo_routes():
    src = _ROBOTS.read_text(encoding="utf-8")
    # All 3 SEO-eligible stock surfaces explicitly allowed
    assert "Allow: /stocks/" in src
    assert "Allow: /prism/" in src
    assert "Allow: /hex/" in src
    # Plus blog + compare
    assert "Allow: /blog/" in src
    assert "Allow: /compare/" in src


def test_robots_has_crawl_delay_for_non_google_bots():
    src = _ROBOTS.read_text(encoding="utf-8")
    assert "Crawl-delay: 1" in src, (
        "Crawl-delay missing — non-Google bots (Bing, Yandex) have "
        "historically hammered the backend."
    )


def test_robots_has_googlebot_specific_block_without_crawl_delay():
    """Google ignores Crawl-delay but warns about it in Search Console.
    Repeating Allow/Disallow under User-agent: Googlebot WITHOUT the
    Crawl-delay directive silences the warning."""
    src = _ROBOTS.read_text(encoding="utf-8")
    gbot_idx = src.find("User-agent: Googlebot")
    assert gbot_idx > 0, "User-agent: Googlebot block missing"
    gbot_block = src[gbot_idx:]
    assert "Crawl-delay" not in gbot_block, (
        "Googlebot block should NOT carry Crawl-delay."
    )


def test_robots_sitemap_reference_unchanged():
    src = _ROBOTS.read_text(encoding="utf-8")
    assert "Sitemap: https://yieldiq.in/sitemap.xml" in src
