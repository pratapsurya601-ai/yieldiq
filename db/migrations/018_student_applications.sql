-- Day-49 (2026-05-20): student / CA articleship tier-verification.
--
-- Backs /api/v1/billing/student-verify (user submits ID) and the
-- /api/v1/admin/student-applications/* review queue. Each row
-- references a private object in the "student-ids" storage bucket
-- (must be created separately in the Supabase dashboard, since
-- bucket creation is not portable across SQL dialects).
--
-- status lifecycle:
--   pending → approved   (admin clicks Approve)
--   pending → rejected   (admin clicks Reject + provides reason)
--
-- Indexes:
--   - status              → fast queue queries
--   - user_id, created_at → "show me my latest submission" path
--
-- RLS is intentionally OFF on this table — all access goes through
-- the backend service-role client, never directly from the
-- browser. The bucket itself is private and read access is via
-- short-lived signed URLs minted server-side.

CREATE TABLE IF NOT EXISTS student_applications (
    id              UUID PRIMARY KEY,
    user_id         UUID NOT NULL,
    email           TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    institution     TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    storage_path    TEXT NOT NULL,
    rejection_reason TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     TEXT
);

CREATE INDEX IF NOT EXISTS idx_student_apps_status
    ON student_applications (status);

CREATE INDEX IF NOT EXISTS idx_student_apps_user_created
    ON student_applications (user_id, created_at DESC);

-- Convenience comment block describing the bucket setup that must
-- happen in the Supabase dashboard (or via the storage REST API)
-- BEFORE the endpoint is hit:
--
--   Bucket name : student-ids
--   Public      : false
--   Allowed MIME types : image/jpeg, image/png, image/webp, application/pdf
--   File size limit    : 5 MB
--
-- The backend service role can read/write freely; no other role
-- should be granted access.
