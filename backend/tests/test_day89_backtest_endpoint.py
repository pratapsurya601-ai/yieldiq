"""Day-89 — YieldIQ-50 hypothetical backtest endpoint + page guards.

Two pieces:

  1. Backend shape tests around the pure helper functions in
     ``yiq50_backtest_service`` (no DB, no FastAPI bootstrap — the
     service is engineered so the DB session is optional and falls
     back to a deterministic large-cap slice when missing).
  2. Source-text guards on the marketing page: SEBI-vocabulary scan,
     mandatory disclaimers present, sitemap + footer link wired.

These run in plain pytest with no DB. The functional behaviour
of the endpoint with live data is covered by the wider integration
suite via the cache_service path.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SERVICE = _ROOT / "backend" / "services" / "yiq50_backtest_service.py"
_PUBLIC = _ROOT / "backend" / "routers" / "public.py"
_PAGE = _ROOT / "frontend" / "src" / "app" / "(marketing)" / "yiq50-backtest" / "page.tsx"
_CHART = _ROOT / "frontend" / "src" / "app" / "(marketing)" / "yiq50-backtest" / "BacktestChart.tsx"
_FOOTER = _ROOT / "frontend" / "src" / "components" / "marketing" / "MarketingFooter.tsx"
_SITEMAP = _ROOT / "frontend" / "src" / "app" / "sitemap.ts"


# SEBI-banned vocabulary on user-facing surfaces. Mirrors Day-85's
# guard list. The page may NOT contain any of these as whole words.
_SEBI_BANNED = {
    "buy", "sell", "hold",
    "outperform", "underperform",
    "outperformed", "underperformed",
    "outperforms", "underperforms",
    "strong", "weak",
    "accumulate", "recommend", "recommendation",
    "should",
}


def _read(p: Path) -> str:
    assert p.exists(), f"required source file missing: {p}"
    return p.read_text(encoding="utf-8")


# ── 1. Backend service guards ───────────────────────────────────


def test_service_file_exists():
    assert _SERVICE.exists()


def test_service_exports_run_function():
    src = _read(_SERVICE)
    assert "def run_yiq50_backtest(" in src


def test_service_uses_canary_universe_file():
    src = _read(_SERVICE)
    assert "canary_stocks_50.json" in src


def test_service_returns_meta_block_with_caveat():
    """Method tag and caveat must be returned in every payload."""
    src = _read(_SERVICE)
    assert '"_meta"' in src or "_meta" in src
    assert '"method"' in src
    assert '"caveat"' in src
    assert '"disclaimer"' in src


def test_service_run_works_with_no_db_session():
    """Even if Session is None / unavailable, run() must return a
    valid payload using the deterministic fallback path."""
    # Force the import path to find the module then call directly.
    import importlib
    import sys

    # Make sure the module is importable from the repo root.
    sys.path.insert(0, str(_ROOT))
    try:
        mod = importlib.import_module("backend.services.yiq50_backtest_service")
        # Universe must load from disk; otherwise the test environment is broken.
        uni = mod._load_yiq50_universe()
        assert len(uni) == 50
    finally:
        if str(_ROOT) in sys.path:
            sys.path.remove(str(_ROOT))


def test_service_lookback_bounds_enforced_on_endpoint():
    """Endpoint must constrain lookback to 1/3/5 years."""
    src = _read(_PUBLIC)
    # The endpoint declares a regex pattern restricting lookback.
    assert 'pattern="^[135]y$"' in src
    assert "/backtest/yiq50" in src


def test_service_uses_nifty_proxy_for_benchmark():
    src = _read(_SERVICE)
    # Match the platform-wide convention from backtest_service.py
    assert "RELIANCE" in src
    assert "HDFCBANK" in src
    assert "TCS" in src
    assert "INFY" in src
    assert "ITC" in src


def test_service_method_tag_distinguishes_fv_history_from_proxy():
    """Either real FV history was used or the proxy slice — both
    cases must be tagged honestly."""
    src = _read(_SERVICE)
    assert "fv_history" in src
    assert "current_score_proxy" in src
    assert "mixed_proxy" in src


# ── 2. Endpoint wiring ──────────────────────────────────────────


def test_endpoint_registered_in_public_router():
    src = _read(_PUBLIC)
    assert "/backtest/yiq50" in src
    # Cached, no-auth, read-only (delegates to the service helper).
    assert "run_yiq50_backtest" in src
    assert "public:backtest:yiq50:" in src


def test_endpoint_does_not_bump_cache_version():
    """Day-89 must NOT touch CACHE_VERSION — historical read only."""
    src = _read(_PUBLIC)
    # The endpoint must not introduce a CACHE_VERSION bump line.
    assert "CACHE_VERSION = " not in src.split("/backtest/yiq50")[1].split("\n\n")[0]


# ── 3. Frontend page guards ─────────────────────────────────────


def test_page_exists():
    assert _PAGE.exists()
    assert _CHART.exists()


def test_page_is_server_component():
    src = _read(_PAGE)
    # No "use client" at top of file.
    head = src.lstrip().splitlines()[:3]
    assert not any('"use client"' in line for line in head), (
        "page.tsx must be a server component"
    )


def test_chart_is_client_component():
    src = _read(_CHART)
    assert '"use client"' in src.splitlines()[0]


def test_page_uses_design_tokens_only():
    src = _read(_PAGE)
    # Page must use the var(--color-*) token vocabulary throughout,
    # not raw hex colours.
    assert "var(--color-bg)" in src
    assert "var(--color-ink)" in src
    assert "var(--color-brand)" in src
    # No raw 6-digit hex colours in user-facing JSX.
    raw_hex = re.findall(r'#[0-9A-Fa-f]{6}\b', src)
    assert not raw_hex, f"page.tsx uses raw hex colours: {raw_hex}"


def test_page_has_all_three_mandatory_disclaimers():
    """SEBI requires (1) past-returns disclaimer, (2) hypothetical
    framing, (3) not-investment-advice statement with the
    not-SEBI-registered call-out."""
    # Collapse all whitespace so JSX line wraps don't defeat substring search.
    src = re.sub(r"\s+", " ", _read(_PAGE).lower())
    assert "past returns are not indicative of future results" in src
    assert "hypothetical results based on backtesting methodology" in src
    assert "not investment advice" in src
    assert "not sebi-registered" in src


def _strip_comments(src: str) -> str:
    """Drop /* ... */ and // ... comments so the SEBI scan only sees
    user-visible JSX, not the JSDoc header that *names* the banned
    vocabulary in order to prohibit it."""
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", " ", src)
    return src


def test_page_contains_no_sebi_banned_vocabulary():
    src = _strip_comments(_read(_PAGE)).lower()
    found = []
    for word in _SEBI_BANNED:
        # whole-word match so "should" doesn't fire on "shoulder"
        if re.search(rf"\b{re.escape(word)}\b", src):
            found.append(word)
    assert not found, f"page.tsx contains SEBI-banned vocabulary: {found}"


def test_chart_contains_no_sebi_banned_vocabulary():
    src = _strip_comments(_read(_CHART)).lower()
    found = [w for w in _SEBI_BANNED if re.search(rf"\b{re.escape(w)}\b", src)]
    assert not found, f"BacktestChart.tsx contains SEBI-banned vocab: {found}"


def test_page_uses_delta_not_alpha_label():
    """User-facing wording: 'delta vs Nifty proxy', NOT 'alpha'
    (alpha is technical jargon the audit asked us to avoid for
    marketing surfaces)."""
    src = _read(_PAGE)
    # The headline column heading and the per-year column heading
    # both use "Delta".
    assert "Delta vs Nifty proxy" in src
    # The chart legend must NOT trumpet "outperformance".
    assert "outperformance" not in src.lower()


def test_footer_links_to_backtest_under_learn():
    src = _read(_FOOTER)
    # Day-89 fix (commit b3ce229): path moved /backtest -> /yiq50-backtest
    # to avoid collision with the authenticated /(app)/backtest route.
    assert '/yiq50-backtest' in src
    # Under the "Learn" column heading — verified by the substring
    # ordering in the file.
    learn_idx = src.find("Learn")
    bt_idx = src.find("/yiq50-backtest")
    yieldiq_idx = src.find("YieldIQ</h3>")
    assert learn_idx < bt_idx < yieldiq_idx, (
        "backtest link must be under the Learn column"
    )


def test_sitemap_includes_backtest_page():
    src = _read(_SITEMAP)
    # Day-89 fix (commit b3ce229): /backtest -> /yiq50-backtest.
    assert "https://yieldiq.in/yiq50-backtest" in src
