-- 003_users_meta_email_opted_out.sql
--
-- Adds the email_opted_out flag to users_meta. The newsletter and
-- weekly-pick services already gate on this column
-- (backend/services/newsletter_service.py:228, 290 and
-- backend/services/email_service.py:124, 142, 630, 640) but Supabase
-- prod doesn't have it yet — every newsletter send was failing with
-- `column users_meta.email_opted_out does not exist (42703)`.
--
-- NULL = treated as not opted out (default mailing-allowed). This
-- matches the existing OR clause pattern in the queries:
--   .or_("email_opted_out.is.null,email_opted_out.eq.false")
--
-- Apply via Supabase SQL editor (or `supabase db push`).

ALTER TABLE users_meta
    ADD COLUMN IF NOT EXISTS email_opted_out BOOLEAN DEFAULT false;
