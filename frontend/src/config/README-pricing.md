# Pricing config

To change displayed prices: edit `pricing.ts`, commit, deploy. The pricing
page (`/pricing`), the home quota banner (`/home`), and the tax-report
paywalls (`/portfolio/tax-report`) all read from here.

To wire the Razorpay payment flow: set the `RAZORPAY_PLAN_ID_*` env vars in
Railway (per `backend/routers/payments.py`). Create the plans in the
Razorpay dashboard first to get the IDs. The plan-ID env vars are read by
the backend only — the frontend never touches them.

This config controls DISPLAY only. The frontend does not read Razorpay plan
IDs — the backend mints subscriptions using the env vars when the frontend
calls `/api/v1/payments/create-subscription`.

Setting a variant's `priceInr` to `null` makes it render as "Coming soon" —
useful for tiers in transition between price revisions.
