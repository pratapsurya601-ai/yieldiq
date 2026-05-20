# YieldIQ Week-5 Monetization Funnel Audit (Day 46)

**Date**: 2026-05-20
**Scope**: Free → Paid conversion journey (signup → quota wall → /pricing → Razorpay → tier flip → activation)
**Method**: Static code audit + cross-reference live endpoints
**Deliverable**: Ranked friction list seeding Days 47-50

---

## TL;DR

The infrastructure is **solid** — Razorpay subscriptions, signature verification, webhook idempotency, tier model, pricing page are all production-quality. The friction is **post-purchase experience**.

| Stage | Status | Priority |
|---|---|---|
| Tier model + quotas | ✅ HEALTHY | — |
| Pricing page | ✅ EXCELLENT | — |
| Checkout flow (Razorpay) | ✅ EXCELLENT | — |
| Webhook reliability | ✅ EXCELLENT | — |
| **Upgrade prompts** | ⚠ MODERATE | P3 |
| **Onboarding email post-checkout** | ❌ CRITICAL GAP | **P1** |
| **Activation event in-app** | ⚠ WEAK SIGNAL | **P2** |

---

## Day 47: P1 — Post-checkout confirmation email + activation modal

### P1 — `/verify-subscription` doesn't send a confirmation email
Paid users complete Razorpay checkout, tier flips in DB, JWT refreshes — but they receive **zero email** acknowledging the upgrade. Cold activation.

**Fix**: call `send_upgrade_confirmation_email(user_email, tier)` inside `/verify-subscription` after the tier update succeeds. Tier-specific copy:
- **Analyst (₹799/mo)**: "Portfolio Prism unlocked. Import a broker account to see your holdings valued."
- **Pro (₹1,499/mo)**: "CSV/PDF export + API key unlocked. Generate your first API key at /account/api."

### P2 — No in-app activation modal post-upgrade
User lands on `/account` after Razorpay redirect with no celebration, no next-step guidance.

**Fix**: append `?just_upgraded={tier}` to the success redirect. Frontend renders a modal with:
- 3 feature callouts for the new tier
- Primary action button (broker import / API key / export demo)
- "Dismiss" button (and stores `dismissed_upgrade_modal_{tier}` in localStorage so the modal doesn't re-fire on every visit)

---

## Day 48: P3 + P4 — Upgrade prompts polish

### P3 — Analysis quota 429 has no clickable upgrade link
Free user hits 5-analysis cap. API returns 429 with text `"Daily analysis limit reached (5/5). Upgrade for more."` — no link in the response. Frontend renders the text and the user has to MANUALLY navigate to `/pricing`.

**Fix**: extend the 429 response detail to:
```json
{
  "error": "quota_exceeded",
  "message": "Daily analysis limit reached (5/5)",
  "limit": 5,
  "used": 5,
  "upgrade_link": "/pricing?ref=quota_wall"
}
```

Frontend intercepts errors with `code === "quota_exceeded"` and renders the existing `TierCapUpsell` (currently only fires for broker / compare caps) with a clickable upgrade CTA.

### P4 — Quota warning fires late (at remaining=1)
Today the home-page warning shows when `remaining <= 1`. By then the user is one click away from the wall — no runway to consider upgrading.

**Fix**: fire the warning at `remaining <= 3`. Soft nudge first, hard wall second.

---

## Day 49: Trial / student-tier friction

### Student verification is manual
Student/CA tier flow today:
1. User signs up
2. User emails `hello@yieldiq.in` with proof
3. Ops manually flips tier in Supabase
4. No automated approval email back to user

**Fix**: add `/api/v1/billing/student-verify` endpoint that accepts an image upload (college ID / CA enrolment letter), stores it in Supabase Storage, and surfaces in `/admin/student-applications` for ops to approve with one click. Auto-emails the user on approval/rejection.

---

## Day 50: Webhook resilience spot-check

Webhook handling is already excellent — signature verification, two-layer idempotency, defensive Supabase writes, recognised event coverage (`subscription.activated/.charged/.halted/.cancelled/.completed`).

**Day 50 scope**: add a `webhook_events_dashboard` view inside `/admin/health-stats` so ops can see:
- Webhook events received in the last 24h, by type
- Failed event count + last failure reason
- Dedupe ratio (how many duplicate Razorpay retries got short-circuited)

This is observability, not new functionality. Lock in the existing resilience by making it visible.

---

## Sprint mechanics

4 PRs (Days 47, 48, 49, 50). Each carries:
- The fix
- Regression-guard tests (Python source-text where possible)
- No CACHE_VERSION bump
- sector-scope: `<none — monetization>`

After Day 50: instrument a Mixpanel/Posthog funnel ($signup → first_analysis → quota_hit → pricing_view → checkout_started → subscription_active → first_paid_analysis) to MEASURE the impact, since YieldIQ doesn't currently have a product analytics layer.
