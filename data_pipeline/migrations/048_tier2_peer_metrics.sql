-- ═══════════════════════════════════════════════════════════════
-- 048_tier2_peer_metrics.sql
--
-- Tier 2 cohort engine (see backend/services/tier2_cohort_valuation_service.py)
-- buckets peers into Premium / Core / Tail based on:
--     ROCE_pct, Piotroski F-score, market_cap_cr
--
-- Today the in-flight peer builder in service.py
-- (_build_tier2_peers_from_sector_relative) cannot populate these
-- fields, so every peer lands in Tail and quality bucketing is a
-- no-op (MANKIND benchmarks against generic-exporter median instead
-- of the franchise-pharma median).
--
-- This table caches the three inputs (plus a precomputed bucket) for
-- every curated peer in screener.sector_relative.DIRECT_PEERS. The
-- enrichment script `scripts/enrich_tier2_peer_metrics.py` is the
-- sole writer; the Tier 2 service is the sole reader.
--
-- Additive — no CACHE_VERSION bump. Missing rows fall back to Tail
-- (current behaviour) so the read-only consumer change is a
-- no-regression rollout under TIER2_ENABLED=false.
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS tier2_peer_metrics (
    ticker          TEXT PRIMARY KEY,
    roce_pct        NUMERIC,
    piotroski       INT,
    market_cap_cr   NUMERIC,
    quality_bucket  TEXT,  -- 'premium' | 'core' | 'tail' precomputed
    refreshed_at    TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tier2_peer_metrics_bucket
    ON tier2_peer_metrics (quality_bucket);
