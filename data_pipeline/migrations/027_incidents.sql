-- 027_incidents.sql
-- ═══════════════════════════════════════════════════════════════
-- Public incident log for the /status page and the recent-incident
-- banner on every page.
--
-- Backs the new `GET /api/v1/public/incidents` endpoint and the
-- transparency surface: when something user-visible breaks (Vercel
-- 402, stale fair-value cache, auth flap, etc.) we log it here so
-- visitors arriving after the fact can see "yes, this was broken,
-- here's what happened, here's what we did".
--
-- Sector-isolated. No analysis math touches this table.
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    severity TEXT NOT NULL CHECK (severity IN ('major', 'minor', 'partial')),
    surface TEXT NOT NULL CHECK (surface IN ('frontend', 'backend', 'data_pipeline', 'auth', 'payments')),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    resolution TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_incidents_started_at
    ON incidents(started_at DESC);

COMMENT ON TABLE incidents IS
    'Public-facing incident log. Backs /api/v1/public/incidents and the dismissible recent-incident banner. Surface = which layer broke; severity = blast-radius shorthand.';

-- ── Seed: the two known recent incidents (idempotent) ─────────────
-- Guarded by a uniqueness check on (started_at, title) so re-running
-- the migration is safe even though the table has no UNIQUE constraint.
INSERT INTO incidents (started_at, ended_at, severity, surface, title, description, resolution)
SELECT * FROM (VALUES
    (
        TIMESTAMPTZ '2026-05-02 16:00:00+00',
        TIMESTAMPTZ '2026-05-02 21:00:00+00',
        'major', 'frontend',
        'yieldiq.in returned HTTP 402 — Vercel plan limit hit',
        'All marketing and app pages returned 402 Payment Required for ~5 hours after Reddit launch traffic exceeded the free Vercel tier.',
        'Vercel plan upgraded to Pro. Service restored. Plan now sized for sustained launch traffic.'
    ),
    (
        TIMESTAMPTZ '2026-05-02 08:00:00+00',
        TIMESTAMPTZ '2026-05-02 14:00:00+00',
        'minor', 'data_pipeline',
        'Stale fair-value cache for ~294 mid-cap tickers',
        'Tickers including FOSECOIND showed inflated CAGR (55%) due to NSE_XBRL_SYNTH and NSE_XBRL rows both stored as period_type=annual.',
        'Data UPDATE reclassified 422 rows to annual_synth. Writer patched in commit f65d64e. Affected tickers will refresh on next nightly snapshot.'
    )
) AS seed(started_at, ended_at, severity, surface, title, description, resolution)
WHERE NOT EXISTS (
    SELECT 1 FROM incidents i
    WHERE i.started_at = seed.started_at
      AND i.title = seed.title
);
