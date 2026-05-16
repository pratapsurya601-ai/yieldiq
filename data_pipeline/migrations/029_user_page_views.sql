-- 027_user_page_views.sql
-- Append-only per-user page-view telemetry for activation analysis.
--
-- Motivation (2026-05-16): 5/5 organic signups in 16 days produced 0
-- watchlist/portfolio writes. The only existing post-signup telemetry
-- is watchlist+portfolio inserts, so we literally cannot tell if a
-- user looked at 50 stocks or 0. This table records signed-in views
-- of key analysis pages so the admin user-activity endpoint can
-- answer "did user X view any analysis page after signup?".
--
-- Constraints:
--   * Append-only, no joins on read path
--   * 30-day rolling retention via scripts/prune_page_views.py (daily cron)
--   * Anonymous users are NEVER inserted (would explode the table)
--   * Inserts are fire-and-forget via FastAPI BackgroundTasks
CREATE TABLE IF NOT EXISTS user_page_views (
  id BIGSERIAL PRIMARY KEY,
  user_email TEXT NOT NULL,
  page_kind TEXT NOT NULL CHECK (page_kind IN (
    'analysis','compare','portfolio_analyze','discover',
    'watchlist','pulse','sector','methodology','other'
  )),
  ticker TEXT,  -- nullable, populated for analysis/compare
  path TEXT NOT NULL,  -- e.g. /analysis/INFY
  viewed_at TIMESTAMPTZ DEFAULT now(),
  user_agent TEXT,
  referrer TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_page_views_user_email_viewed
  ON user_page_views(user_email, viewed_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_page_views_viewed_at
  ON user_page_views(viewed_at DESC);

COMMENT ON TABLE user_page_views IS
  'Append-only signed-in user page views. 30-day retention via scripts/prune_page_views.py daily cron.';
