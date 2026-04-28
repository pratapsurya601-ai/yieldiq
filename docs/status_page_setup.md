# Status Page Setup — Better Stack

This runbook walks through setting up the public YieldIQ status page at
`status.yieldiq.in` using **Better Stack** (formerly Better Uptime). Free tier
is sufficient: 10 monitors, 1 status page, 3-minute check intervals.

## 1. Sign up

1. Go to <https://betterstack.com/uptime> and create an account using
   `ops@yieldiq.in` (or `hello@yieldiq.in` if no ops alias).
2. Skip the team-invite flow for now — single-operator is fine.
3. Pick the **free** plan; you can upgrade later if you outgrow it.

## 2. Create monitors

Add the following five HTTP monitors. All use `GET`, default timeout (30s),
3-minute interval, alert after 1 failure.

| # | Name                       | URL                                                                  | Expected status |
|---|----------------------------|----------------------------------------------------------------------|-----------------|
| 1 | Marketing home             | `https://yieldiq.in/`                                                | 200             |
| 2 | API health                 | `https://api.yieldiq.in/api/v1/health`                               | 200             |
| 3 | Public stock summary       | `https://api.yieldiq.in/api/v1/public/stock-summary/RELIANCE.NS`     | 200             |
| 4 | All tickers                | `https://api.yieldiq.in/api/v1/public/all-tickers`                   | 200             |
| 5 | Demo cards                 | `https://api.yieldiq.in/api/v1/public/demo-cards`                    | 200             |

For each monitor:
- Enable **SSL expiry** alert (warn 14 days before expiry).
- Set **expected response time** to 5000ms (warn) and 15000ms (alert).
- Notification channel: email + (optional) Slack webhook.

## 3. Create the status page

1. **Status pages → New page** → name `YieldIQ Status`.
2. Add the five monitors above grouped as:
   - **Web** — Marketing home
   - **API** — API health, Public stock summary, All tickers, Demo cards
3. Set **timezone** to `Asia/Kolkata`.
4. Set **logo** to `/logo-new.svg` from the YieldIQ public assets (upload).
5. Set **Support URL** to `https://yieldiq.in/about` and **Contact email** to
   `hello@yieldiq.in`.
6. Enable **subscriber notifications** (email).
7. Save.

## 4. DNS — point status.yieldiq.in at Better Stack

Better Stack will give you a target hostname like
`yieldiq.betteruptime.com`. In Cloudflare DNS for `yieldiq.in`:

```
Type:   CNAME
Name:   status
Target: yieldiq.betteruptime.com   (use the exact value from Better Stack)
Proxy:  DNS only (grey cloud) — Better Stack issues its own cert
TTL:    Auto
```

Then in Better Stack: **Status page → Domain → Add custom domain** →
`status.yieldiq.in`. Verification + cert issuance is automatic, ~5 min.

## 5. Wire into the YieldIQ footer

Already done in this PR — `TrustFooter.tsx` now has a **Status** link
pointing at `https://status.yieldiq.in` and an **SLA** link pointing at
`/legal/sla`.

## 6. Incident response runbook

### Severity levels

| Sev | Definition                                                            | Target response  |
|-----|-----------------------------------------------------------------------|------------------|
| P0  | Site fully down, data loss, security breach                           | 15 min ack, 1 h fix or workaround |
| P1  | Major feature broken (analysis page, portfolio, payments)             | 1 h ack, 4 h fix |
| P2  | Minor degradation (slow response, single-ticker glitch)               | 1 business day   |

### Who responds

Single-operator phase: **Vinit**. Better Stack alerts route to email +
phone. Escalation is manual until a second on-call is added.

### Process

1. Better Stack pages → operator acknowledges within target.
2. Operator opens an **incident** on the status page (Investigating →
   Identified → Monitoring → Resolved).
3. Post-incident: write a 1-paragraph postmortem in
   `docs/ops/postmortems/YYYY-MM-DD-slug.md` within 48 h for any P0/P1.
4. If the breach exceeds the SLA threshold (see `docs/sla.md`), credits
   are issued automatically on the next billing cycle.

### Maintenance windows

Sundays 03:00–05:00 IST. Pre-announce on the status page at least 24 h
ahead. Time inside the window does **not** count against the SLA.

## 7. Verification checklist

- [ ] All five monitors show **green** for 1 hour.
- [ ] `https://status.yieldiq.in` resolves and shows the dashboard.
- [ ] SSL cert on `status.yieldiq.in` is valid (Let's Encrypt via Better Stack).
- [ ] Test alert fired and received via email.
- [ ] Footer link in production lands on the status page.
- [ ] `/legal/sla` page renders.
