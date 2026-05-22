# Sentry verification — pre-launch (2026-05-22, Day-101)

10-line checklist. Run this once after a fresh deploy to confirm Sentry is
catching backend AND client errors, with source maps mapped, before any
real user clicks "Subscribe — ₹99".

## Backend

1. Log in as admin (`pratapsurya601@gmail.com` or `suryasbss601@gmail.com`).
2. `curl -H "Authorization: Bearer $ADMIN_JWT" https://api.yieldiq.in/api/v1/admin/sentry-probe`
   → expect HTTP 500 (endpoint raises by design).
3. Open Sentry → filter `error.type:_SentryProbeError` → confirm one new
   event within 30s, with a Python stack trace pointing at
   `backend/routers/admin.py:sentry_probe`.

## Client

4. Visit `https://yieldiq.in/admin` (must be logged in as admin).
5. Click **Trigger client error** (under "Sentry readiness probes").
6. Open Sentry → filter `error.type:SentryClientProbeError` → confirm one
   new event within 30s.
7. Confirm the stack trace shows the ORIGINAL `.tsx` file path
   (`frontend/src/app/(app)/admin/page.tsx`), not a minified
   `chunks/page-abc123.js` line. If you see the minified path, source-map
   upload failed on the Vercel build — re-deploy with
   `SENTRY_AUTH_TOKEN` set in Vercel env.

## PII scrub check

8. In either event, click "Show all" on the request data → confirm no
   user email, no JWT, no Razorpay key fragments. `send_default_pii=False`
   in `backend/main.py` + `_scrub_event` should keep these out.

## Sign-off

9. If steps 3, 6, and 7 all pass: tick the checklist in the Day-101 PR and
   flip the "Subscribe — ₹99" CTA live. If any step fails, do NOT flip the
   toggle — file a P0 against this runbook and fix Sentry wiring first.
10. Re-run this runbook after every Sentry SDK upgrade or any change to
    `backend/main.py` Sentry init block / `frontend/sentry.*.config.ts`.
