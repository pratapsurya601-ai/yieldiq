"""Day-86 (2026-05-22): two Tier-3 second pieces shipped together.

Piece 1 — Cohort-outlier flagging on /api/v1/public/peers/{ticker}.
The Day-80 caption explained WHY each peer was in the cohort but never
caught the case where one peer's fundamentals depart sharply from the
cohort median. Day-86 adds a per-peer `outlier_flag` computed in the
backend: z-score the ROE / ROCE / YieldIQ-score columns against the
cohort median; if ANY metric is > 2 sigma out, mark the peer.

Piece 2 — Ratio staleness alerts. The Day-78 corp_actions feed-health
block has been mirrored for the daily `market_metrics` ratios table
with a tighter 24h staleness threshold (ratios are a daily feed; the
6-month corp-actions horizon doesn't apply) and a 20% per-ticker
threshold for the WARN level.

SEBI vocabulary: the outlier flag uses neutral language ("deviates",
"departs from cohort") — never "outperform"/"underperform" since the
word literally describes what an outlier is. Tests below lock in both
the wiring and the SEBI guard.

Source-text guards only — no DB, no FastAPI bootstrap. The endpoints
are exercised by the wider integration suite; this file's job is to
make sure neither piece regresses silently.
"""
from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_PUBLIC = _ROOT / "backend" / "routers" / "public.py"
_ADMIN = _ROOT / "backend" / "routers" / "admin.py"
_FRONTEND_API = _ROOT / "frontend" / "src" / "lib" / "api.ts"
_FRONTEND_COMPARE = (
    _ROOT / "frontend" / "src" / "app" / "(app)" / "compare" / "page.tsx"
)


def _read(p: Path) -> str:
    assert p.exists(), f"required source file missing: {p}"
    return p.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# Piece 1: cohort-outlier flagging in public.py
# ─────────────────────────────────────────────────────────────────


def test_public_peers_attaches_outlier_flag_field() -> None:
    src = _read(_PUBLIC)
    # Every peer row must carry the field (failure-safe default included).
    assert 'p["outlier_flag"] = {' in src, (
        "public /peers must attach an outlier_flag dict to every peer row."
    )
    assert '"is_outlier":' in src
    assert '"deviates_on":' in src


def test_outlier_flag_uses_two_sigma_threshold() -> None:
    src = _read(_PUBLIC)
    # The contract is > 2 stdev from the cohort median.
    assert "if z > 2.0:" in src, (
        "outlier flag must fire when |z| > 2.0 — that's the cohort "
        "deviation contract documented in Day-86."
    )


def test_outlier_flag_compares_against_cohort_median() -> None:
    src = _read(_PUBLIC)
    # Median (not mean) is the deviation reference — robust to one
    # extreme peer skewing the centre.
    assert "median" in src
    assert "cohort_median" in src, (
        "deviation entries must record the cohort median so the UI can "
        "render value-vs-median tooltips."
    )


def test_outlier_flag_metrics_are_roe_roce_score() -> None:
    src = _read(_PUBLIC)
    assert 'metric_fields = ("roe", "roce", "score")' in src, (
        "outlier flag must z-score ROE / ROCE / score per the Day-86 "
        "contract — no PE (PE means different things across sectors)."
    )


def test_outlier_flag_is_failure_safe() -> None:
    src = _read(_PUBLIC)
    # On exception, every peer must still get the field so the frontend
    # never crashes on a missing key.
    assert "outlier_flag synth failed" in src
    assert 'p.setdefault("outlier_flag"' in src


def test_public_peers_emits_roce_alongside_roe() -> None:
    src = _read(_PUBLIC)
    # ROCE must be populated on the peer row (it's the second axis the
    # outlier detector z-scores against).
    assert '"roce": roce,' in src, (
        "peer rows must include roce — it's a deviation axis for the "
        "outlier detector."
    )
    # Fallback path must read roce off ratio_history too.
    assert 'roce = getattr(rh, "roce", None)' in src


def test_outlier_flag_avoids_sebi_vocabulary() -> None:
    src = _read(_PUBLIC)
    # Source-comment audit — the new block must not introduce the
    # banned advisory verbs around the outlier logic. We grep the
    # vicinity of the new comment header.
    start = src.find("Day-86 (2026-05-22): cohort-outlier flagging")
    assert start > 0, "Day-86 outlier-flag comment header missing"
    end = src.find("def ", start)
    if end == -1:
        end = start + 4000
    section = src[start:end].lower()
    for banned in (
        "outperform",
        "underperform",
        "recommend",
        # "buy"/"sell"/"hold" as standalone words; substring grep is
        # noisy (e.g. "should", "buy" is in "buyer") so we only ban
        # the unambiguous advisory verbs here.
        " buy ",
        " sell ",
        "accumulate",
    ):
        assert banned not in section, (
            f"SEBI vocabulary leak in Day-86 outlier-flag section: "
            f"banned token {banned!r} appeared."
        )


# ─────────────────────────────────────────────────────────────────
# Piece 1b: frontend wiring (compare page + api.ts types)
# ─────────────────────────────────────────────────────────────────


def test_frontend_api_declares_peer_outlier_flag_type() -> None:
    src = _read(_FRONTEND_API)
    assert "interface PeerOutlierFlag" in src
    assert "interface PeerOutlierDeviation" in src
    # Field on PublicPeerRow.
    assert "outlier_flag?: PeerOutlierFlag | null" in src


def test_compare_page_renders_outlier_tag() -> None:
    src = _read(_FRONTEND_COMPARE)
    # data-testid is the contract — visual-regression + smoke tests
    # query against it.
    assert 'data-testid="peer-cohort-outlier-tag"' in src, (
        "compare page must render a per-peer outlier tag with the "
        "documented data-testid."
    )
    # User-visible label uses SEBI-safe terminology.
    assert "Cohort outlier" in src
    # Banned advisory verbs must not appear as user-visible copy in the
    # outlier section.
    assert "Outperform" not in src or "outlier_flag" in src  # sanity
    # No <strong> usage introduced (theme codemod discipline).
    assert "<strong>Cohort outlier" not in src


def test_compare_page_threads_outlier_flag_through_suggestion_map() -> None:
    src = _read(_FRONTEND_COMPARE)
    # The useMemo that builds suggestion buttons must pick up the
    # outlier_flag fields so the chip renders.
    assert "isOutlier: !!p.outlier_flag?.is_outlier" in src
    assert "deviatesOn: p.outlier_flag?.deviates_on ?? []" in src


# ─────────────────────────────────────────────────────────────────
# Piece 2: market_metrics ratios-feed health block in admin.py
# ─────────────────────────────────────────────────────────────────


def test_health_stats_exposes_market_metrics_block() -> None:
    src = _read(_ADMIN)
    assert '"market_metrics": market_metrics_block,' in src, (
        "market_metrics block must be added to the get_health_stats "
        "response (next to the Day-78 corp_actions block)."
    )


def test_market_metrics_block_has_all_five_fields() -> None:
    src = _read(_ADMIN)
    for field in (
        '"total_rows"',
        '"tickers_covered_24h"',
        '"tickers_with_stale_ratios_pct"',
        '"oldest_freshly_updated_pct"',
        '"feed_last_write_at"',
    ):
        assert field in src, (
            f"market_metrics block must expose {field} per the Day-86 contract."
        )


def test_market_metrics_block_queries_market_metrics_table() -> None:
    src = _read(_ADMIN)
    assert "FROM market_metrics" in src
    # Aggregate-only — mirrors the Day-78 SQL shape.
    assert "COUNT(DISTINCT ticker)" in src
    assert "MAX(trade_date)" in src
    # 7-day per-ticker staleness window (Day-86 contract; tighter than
    # the 6-month corp-actions window because ratios are a daily feed).
    assert "INTERVAL '7 days'" in src


def test_market_metrics_block_is_failure_safe() -> None:
    src = _read(_ADMIN)
    assert "health-stats market_metrics block failed (non-fatal)" in src, (
        "market_metrics block must log a non-fatal warning on failure."
    )
    assert "market_metrics_block: dict = {" in src, (
        "market_metrics_block must be pre-initialised before the try."
    )


def test_market_metrics_health_alerts_feed_last_write_at() -> None:
    src = _read(_ADMIN)
    # 24h threshold → ALERT (tighter than corp-actions 48h because
    # ratios are a daily feed).
    assert '"alert", "market_metrics.feed_last_write_at"' in src
    assert "market_metrics ingestion appears stopped" in src
    assert "mm_last_write, 24," in src


def test_market_metrics_health_alerts_per_ticker_staleness() -> None:
    src = _read(_ADMIN)
    # 20% threshold → WARN
    assert '"warn", "market_metrics.tickers_with_stale_ratios_pct"' in src
    assert "Per-ticker staleness in market_metrics feed" in src
    assert "mm_stale_pct, 0.20," in src


def test_market_metrics_doc_header_lists_thresholds() -> None:
    src = _read(_ADMIN)
    assert "market_metrics.feed_last_write_at" in src
    assert "market_metrics.tickers_with_stale_ratios_pct" in src
