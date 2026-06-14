BEGIN;

-- web_vitals_events (2026-06-14): real-user Core Web Vitals (RUM).
--
-- Lab traces (Chrome DevTools) only measure one machine. This table
-- stores field metrics beaconed from real visitors' browsers
-- (frontend WebVitalsBeacon.tsx -> POST /api/v1/telemetry/web-vital)
-- so /admin/web-vitals can report p75 across actual devices + networks
-- — the number that actually reflects user experience. CrUX has no data
-- for this domain yet (traffic too low), so this is our own RUM.
--
-- Privacy (mirrors pwa_telemetry_events / migration 050):
--   * `metric` is whitelisted upstream (LCP/CLS/INP/TTFB/FCP) by the
--     Pydantic Literal on the router.
--   * `path` is the route TEMPLATE (e.g. /analysis/[ticker]), with the
--     dynamic segment collapsed client-side — never a per-user URL, no
--     query string, no IDs.
--   * `conn_type` / `device` are coarse buckets (4g/3g/wifi, mobile/
--     desktop) — not fingerprintable.
--   * `ip_hash` = sha256(SALT_PWA_TELEMETRY || remote_ip) for dedup
--     only; raw IPs are never stored.
--
-- Additive migration — no existing flow touched.
--
-- Rollback:
--   DROP TABLE IF EXISTS web_vitals_events;

CREATE TABLE IF NOT EXISTS web_vitals_events (
    id          SERIAL PRIMARY KEY,
    metric      TEXT NOT NULL,            -- LCP | CLS | INP | TTFB | FCP
    value       DOUBLE PRECISION NOT NULL, -- ms (CLS is unitless, stored as-is)
    rating      TEXT,                      -- good | needs-improvement | poor
    path        TEXT,                      -- route template, sanitized
    nav_type    TEXT,                      -- navigate | reload | back_forward | restore
    conn_type   TEXT,                      -- 4g | 3g | 2g | slow-2g | wifi | unknown
    device      TEXT,                      -- mobile | desktop
    ip_hash     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_web_vitals_metric_created
    ON web_vitals_events (metric, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_web_vitals_path_created
    ON web_vitals_events (path, created_at DESC);

COMMIT;
