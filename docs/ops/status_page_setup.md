# Status Page Setup — Better Stack (Ops Runbook)

This runbook walks through standing up the public YieldIQ status page at
`https://status.yieldiq.in` using **Better Stack** (formerly Better Uptime).
The free tier is sufficient: 10 monitors, 1 status page, 3-minute check
intervals.

This file lives under `docs/ops/` because it is the authoritative ops
runbook. The earlier draft at `docs/status_page_setup.md` is kept as a
pointer to here.

> **Why this runbook exists.** The site footer + `/legal/sla` page already
> link to `https://status.yieldiq.in`, but DNS for that subdomain is not
> yet configured. Until DNS lands, `frontend/src/app/status/route.ts`
> redirects to the temporary Better Stack hostname.

---

## 0. Pre-flight

You will need:

- Cloudflare DNS access for `yieldiq.in` (to add the CNAME).
- The `hello@yieldiq.in` mailbox (for sign-up + alert delivery).
- 15–20 minutes for sign-up + monitor creation, plus ~5–10 min for DNS
  propagation and cert issuance.

Do **not** create or commit any new env vars for this work. The status
page is fully external; nothing in our stack reads from it.

---

## 1. Sign up for Better Stack

1. Go to <https://betterstack.com/uptime>.
2. Sign up with `hello@yieldiq.in`. Verify the email.
3. Skip team invites — single-operator is fine for now.
4. Pick the **Free** plan.

Save the workspace URL Better Stack assigns you (e.g.
`https://uptime.betterstack.com/team/<id>/`) — you'll need it in step 4.

---

## 2. Create the four monitors

Add the following four HTTP monitors. All use `GET`, default timeout
(30s), 3-minute check interval, alert after **1 failure**.

| # | Name                           | URL                                                                                       | Expected status |
|---|--------------------------------|-------------------------------------------------------------------------------------------|-----------------|
| 1 | API health                     | `https://api.yieldiq.in/health`                                                           | 200             |
| 2 | Public — all tickers           | `https://api.yieldiq.in/api/v1/public/all-tickers`                                        | 200             |
| 3 | Public — retrospective Q4FY26  | `https://api.yieldiq.in/api/v1/public/retrospective?period=Q4FY26&window=30`              | 200             |
| 4 | Marketing home                 | `https://yieldiq.in/`                                                                     | 200             |

For each monitor:

- Enable **SSL expiry** alert (warn 14 days before cert expiry).
- Set **expected response time**: warn at 5 000 ms, alert at 15 000 ms.
- Notification channel: **email → `hello@yieldiq.in`**.
- Leave Slack/PagerDuty disabled until those channels exist.

> The retrospective endpoint takes a query string. Better Stack accepts
> the full URL with `?period=…&window=…` — paste it verbatim in the
> "URL" field.

---

## 3. Configure email alerts

1. **Integrations → Email** → confirm `hello@yieldiq.in` is the only
   recipient.
2. **Notification policies** → use the default *Email immediately* policy
   for all four monitors.
3. Send a **test alert** from the UI and confirm it lands in the
   `hello@yieldiq.in` inbox.

When a second on-call human or a Slack workspace exists, return here and
add them as additional recipients.

---

## 4. Create the status page

1. **Status pages → New page** → name `YieldIQ Status`.
2. Add the four monitors above. Group them as:
   - **Web** — Marketing home
   - **API** — API health, Public — all tickers, Public — retrospective Q4FY26
3. Set **timezone** to `Asia/Kolkata`.
4. Upload `/logo-new.svg` from `frontend/public/` as the page logo.
5. Set **Support URL** → `https://yieldiq.in/about`.
6. Set **Contact email** → `hello@yieldiq.in`.
7. Enable **subscriber notifications** (email opt-in for end-users).
8. **Save.**

Better Stack will publish the page at a temporary hostname like
`https://yieldiq.betterstack.com` (or `…betteruptime.com`). Note that
hostname — it's also the redirect target in step 6.

---

## 5. DNS — point `status.yieldiq.in` at Better Stack

In Better Stack: **Status page → Settings → Custom domain → Add domain**
→ `status.yieldiq.in`. The UI will show a target hostname to CNAME to
(usually `<workspace>.betteruptime.com` or similar).

In Cloudflare DNS for `yieldiq.in`:

```
Type:   CNAME
Name:   status
Target: <value-from-better-stack>     (e.g. yieldiq.betteruptime.com)
Proxy:  DNS only (grey cloud)         — Better Stack issues its own cert
TTL:    Auto
```

**Important:** keep the proxy off (grey cloud). Cloudflare's orange-cloud
proxy will break Better Stack's Let's Encrypt cert issuance.

Verification + cert issuance is automatic and usually takes 5–10 min.
You can re-trigger verification from the Better Stack UI if it stalls.

---

## 6. Remove the temporary redirect

While DNS is propagating, the app routes `/status` →
`https://yieldiq.betterstack.com` via
`frontend/src/app/status/route.ts`. Once `https://status.yieldiq.in`
resolves and serves a valid cert:

1. Delete `frontend/src/app/status/route.ts` (or change the redirect
   target to `https://status.yieldiq.in` — either is fine; the footer
   already points users straight at `status.yieldiq.in`, so the
   `/status` route is purely a fallback).
2. Confirm the footer "Status" link in `frontend/src/components/
   layout/TrustFooter.tsx` still points at `https://status.yieldiq.in`.
3. Confirm the SLA page (`frontend/src/app/legal/sla/page.tsx`) links
   resolve.

---

## 7. Incident response

(Carried over verbatim from `docs/status_page_setup.md`.)

### Severity levels

| Sev | Definition                                                  | Target response                  |
|-----|-------------------------------------------------------------|----------------------------------|
| P0  | Site fully down, data loss, security breach                 | 15 min ack, 1 h fix or workaround |
| P1  | Major feature broken (analysis, portfolio, payments)        | 1 h ack, 4 h fix                 |
| P2  | Minor degradation (slow response, single-ticker glitch)     | 1 business day                   |

### Process

1. Better Stack pages → operator acknowledges within target.
2. Operator opens an **incident** on the status page (Investigating →
   Identified → Monitoring → Resolved).
3. Post-incident: 1-paragraph postmortem in
   `docs/ops/postmortems/YYYY-MM-DD-slug.md` within 48 h for any P0/P1.
4. If the breach exceeds the SLA threshold (`docs/sla.md`), credits are
   issued on the next billing cycle.

### Maintenance windows

Sundays 03:00–05:00 IST. Pre-announce on the status page at least 24 h
ahead. Time inside the window does **not** count against the SLA.

---

## 8. Verification checklist

Before closing the setup task:

- [ ] All four monitors show **green** for 1 hour.
- [ ] `https://status.yieldiq.in` resolves and shows the dashboard.
- [ ] SSL cert on `status.yieldiq.in` is valid (Let's Encrypt via
      Better Stack).
- [ ] Test alert fires and lands in `hello@yieldiq.in`.
- [ ] Footer "Status" link in production lands on the status page.
- [ ] `/status` redirect works (redirects to either the temp hostname or
      `status.yieldiq.in`, depending on DNS state).
- [ ] `/legal/sla` page renders without console errors.

---

## What the operator must do manually

This whole runbook is manual — Claude cannot sign up for Better Stack on
your behalf. The end-state requires:

1. A Better Stack account on `hello@yieldiq.in` (free tier).
2. The four monitors above, with email alerts enabled.
3. A status page named `YieldIQ Status` bound to those four monitors.
4. A Cloudflare CNAME `status` → Better Stack's hostname.
5. Cert issuance verified, then deletion (or retargeting) of the
   `/status` redirect route.

Until step 4 lands, the redirect at `/status` keeps the footer link
working by sending users to the temporary Better Stack hostname.
