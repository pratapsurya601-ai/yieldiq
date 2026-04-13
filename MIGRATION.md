# YieldIQ — Streamlit to Next.js Migration

## Phase 1 (Current) — Backend API live
- FastAPI at api.yieldiq.in
- Streamlit at yieldiq.in (unchanged)
- Next.js in development

## Phase 2 — Frontend deployed
- Next.js at yieldiq.in
- FastAPI at api.yieldiq.in
- Streamlit at legacy.yieldiq.in (kept alive)

## Phase 3 — Full cutover
- Next.js at yieldiq.in (primary)
- legacy.yieldiq.in deprecated
- Streamlit service removed from Railway

## Feature parity checklist before Phase 3
- [ ] All 15 valuation engines accessible via Next.js
- [ ] Authentication working (login/signup/tiers)
- [ ] Portfolio + watchlist + alerts working
- [ ] PDF/Excel export working
- [ ] AI summary working
- [ ] Screener working with all presets
- [ ] Razorpay payment integration
- [ ] Mobile responsive (tested on real device)
- [ ] Performance: analysis loads < 3 seconds
- [ ] Learn Mode tooltips working
- [ ] Pro Mode gate working
- [ ] Notification system working

## Cost comparison
| Service | Streamlit (current) | Next.js + FastAPI |
|---------|-------------------|-------------------|
| Railway | ~$10/mo           | ~$10/mo (FastAPI) |
| Vercel  | N/A               | $0 (free tier)    |
| Total   | ~$10/mo           | ~$10/mo           |
