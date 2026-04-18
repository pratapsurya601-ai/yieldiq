BEGIN;

-- Generic key/value cache for slow, uncacheable-by-CDN endpoints
-- (authenticated, tier-varying responses). Survives Railway redeploys
-- so the in-memory cache doesn't always start cold.
--
-- Consumers:
--   /api/v1/analysis/{ticker}/financials
--   /api/v1/analysis/{ticker}/fv-history
--   (add more as slow endpoints are discovered via Sentry)
--
-- Key convention:
--   "{endpoint}:{ticker}:{params-encoded-deterministically}"
-- Example:
--   "financials:TCS.NS:annual:5"
--   "fv-history:TCS.NS:3"
CREATE TABLE IF NOT EXISTS endpoint_cache (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '24 hours'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fast "expire all stale rows" sweep. Run by a cron if the table grows.
CREATE INDEX IF NOT EXISTS idx_endpoint_cache_expires_at
    ON endpoint_cache (expires_at);

COMMIT;
