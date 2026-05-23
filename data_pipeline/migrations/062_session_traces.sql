-- 062_session_traces.sql
-- Phase J — observation harness.
--
-- Append-only event log for auth'd session traces. Powers the launch-
-- week debugging surface: when a user reports a confusing UX, we can
-- replay the sequence of pages they visited and buttons they clicked
-- (NO PII, NO form contents — only event types and minimal metadata).
--
-- Captured by `frontend/src/lib/useSessionTrace.ts`, batched every
-- 30s up to 100 events per session, POSTed to
-- /api/v1/internal/session-trace. Read back via /admin/session-traces.
--
-- Anonymous visitors are not traced (the hook short-circuits, and the
-- backend POST requires a valid session JWT).

-- user_id is TEXT (matches existing alerts, push_subscriptions, band_alerts
-- conventions — JWT.sub is a Supabase UUID string, not a numeric id).
-- The Phase J spec called for BIGINT; deviating to keep schema consistent
-- with the rest of the auth surface. See PR description.
CREATE TABLE IF NOT EXISTS session_traces (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_session_traces_user_created
    ON session_traces (user_id, created_at DESC);
