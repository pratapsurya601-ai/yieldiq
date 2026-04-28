# YieldIQ Service Level Agreement (SLA)

**Version:** 1.0
**Effective date:** 2026-04-27
**Applies to:** all paying YieldIQ tiers (Pro, and any successor paid plans).
**Free tier:** best-effort, no SLA.

---

## 1. Uptime commitment

YieldIQ commits to **99.5% monthly uptime** for the paying tier across:

- The web app at `https://yieldiq.in`
- The public API at `https://api.yieldiq.in`

99.5% allows up to **~3 hours 36 minutes** of unplanned downtime per
calendar month. Live status is published at
[`status.yieldiq.in`](https://status.yieldiq.in).

## 2. What counts as downtime

A minute counts as down if **two consecutive checks** from Better Stack
fail against any of these monitors:

- Marketing home (`/`)
- API health (`/api/v1/health`)
- Public stock summary (`/api/v1/public/stock-summary/RELIANCE.NS`)
- All tickers (`/api/v1/public/all-tickers`)

Slow responses (under 30s) are not counted as downtime, but persistent
slowness (P95 > 5s for > 1 hour) is treated as a P2 incident.

## 3. Maintenance windows

Planned maintenance is **excluded** from the SLA calculation. Windows:

- **Sundays, 03:00–05:00 IST** (weekly, as needed)
- Announced on the status page at least **24 hours** in advance.

Emergency maintenance for security patches may be performed outside
this window with as much notice as practical; this is also excluded.

## 4. Service credits

If we miss the 99.5% target in a calendar month, paying customers
receive a credit on their next invoice:

| Breach in a rolling 12-month window | Credit                  |
|-------------------------------------|-------------------------|
| 1st                                 | 10% of monthly fee      |
| 2nd                                 | 20% of monthly fee      |
| 3rd                                 | 40% of monthly fee      |
| 4th and beyond                      | 100% of monthly fee     |

Credits are applied automatically — no need to file a claim. The credit
is the sole and exclusive remedy for any SLA breach.

## 5. Out of scope

The SLA does **not** cover downtime caused by:

- **Third-party providers** (Vercel, Railway, Neon, Cloudflare, payment
  gateways). We report these on the status page, but cannot refund for
  them.
- **Force majeure** (natural disasters, internet backbone failures,
  state-level censorship).
- **User-side issues**: unstable internet, outdated browsers, ad
  blockers that strip cookies / scripts, browser extensions that break
  the app.
- **Beta or "experimental" features** clearly marked as such in the
  product.
- **Free-tier traffic** — we will keep the free tier running on a
  best-effort basis.

## 6. Your responsibilities

To be eligible for SLA credit:

- Your account must be in good standing (payments current).
- The breach must be visible on `status.yieldiq.in` history.
- You access YieldIQ via a modern browser (Chrome / Edge / Safari /
  Firefox, last 2 major versions).

## 7. Reporting an outage

1. Check `status.yieldiq.in` first — if it's red, we already know.
2. If status is green but you're seeing problems, email
   **hello@yieldiq.in** with: URL, ticker, screenshot, browser, time.
3. We'll respond per the [incident severity matrix](status_page_setup.md#severity-levels).

## 8. Changes to this SLA

We may update this SLA. Material changes (lowering the uptime target,
shrinking credits, expanding exclusions) will be communicated by email
to active paying customers at least **30 days** before they take
effect. The current version is always at `https://yieldiq.in/legal/sla`.

---

**Contact:** hello@yieldiq.in
**Effective:** 2026-04-27
**Version:** 1.0
