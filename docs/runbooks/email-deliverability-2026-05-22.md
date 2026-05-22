# Email Deliverability Runbook — 2026-05-22

Day-101b audit of yieldiq.in / yieldiq.com email-sending state. Documents
current DNS records, gaps to close before scaling email volume, and the
smoke-test workflow.

## Background — which domain actually sends?

`backend/services/email_service.py` line 25:

```
FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "hello@yieldiq.com")
```

So every transactional email — welcome, upgrade confirmation, student
verification result, weekly digest, band alert — is sent FROM
`hello@yieldiq.com`. The Railway env var `SENDGRID_FROM_EMAIL` can
override, but in prod today the From header is `.com`.

Receiving mail servers authenticate on the **From-header domain**. That
means `yieldiq.com` is the domain whose SPF / DKIM / DMARC matters for
deliverability. `yieldiq.in` is the brand / web domain; it does not
appear in any outgoing SMTP envelope today.

Implication: the SendGrid CNAMEs on `yieldiq.in` are not currently doing
anything useful for inbox delivery — they were set up on the wrong
domain.

## Email surfaces enumerated

From `grep -rn "sendgrid|email_service|send_email" backend/`:

| Type | Function | Trigger | Tag |
| --- | --- | --- | --- |
| Welcome | `send_welcome_email` | Signup webhook | `welcome` |
| Upgrade confirmation | `send_upgrade_confirmation_email` | `/verify-subscription` after Razorpay flip | (none today) |
| Student decision | `send_student_application_email` | Admin approve/reject | (none today) |
| Weekly digest | `send_weekly_digest` | GH Actions cron Thursdays | `weekly_digest` |
| Band alert | `alerts_service.send_alert_email` | Band-cross detector | `band_alert` |
| Password reset | Supabase auth (not SendGrid) | Auth flow | — |
| Newsletter | `newsletter_service.send_issue` | Manual admin trigger | `newsletter` |
| Retention re-engagement | `retention_service.send_winback` | 14-day inactive cron | `winback` |
| Unsubscribe confirm | `routers/email.py` | User clicks unsub link | — |

Password reset goes through Supabase auth (separate sender). Everything
else flows through `email_service._send_email -> SendGrid API`.

## DNS state — 2026-05-22

Lookups via `nslookup` against the upstream resolver. Nameservers:
`yieldiq.in` = GoDaddy (`ns57.domaincontrol.com`), `yieldiq.com` =
Azure DNS (`ns1-33.azure-dns.com`).

### yieldiq.in (brand / web)

| Record | State | Value |
| --- | --- | --- |
| MX | absent | (no MX served — domain does not receive mail) |
| SPF (TXT v=spf1) | **MISSING** | (only Google site-verification TXT present) |
| DKIM `s1._domainkey` CNAME | present | `s1.domainkey.u97623216.wl217.sendgrid.net` |
| DKIM `s2._domainkey` CNAME | present | `s2.domainkey.u97623216.wl217.sendgrid.net` |
| DMARC `_dmarc` TXT | present | `v=DMARC1; p=quarantine; adkim=r; aspf=r; rua=mailto:dmarc_rua@onsecureserver.net;` |

### yieldiq.com (actual From-domain — the one that matters)

| Record | State | Value |
| --- | --- | --- |
| MX | absent | — |
| SPF | **MISSING** | — |
| DKIM `s1._domainkey` CNAME | **MISSING** | NXDOMAIN |
| DKIM `s2._domainkey` CNAME | **MISSING** | NXDOMAIN |
| DMARC | present | `v=DMARC1; p=reject; pct=100; rua=mailto:rua@dmarc.microsoft; ruf=mailto:ruf@dmarc.microsoft; fo=1` |

`yieldiq.com` has DMARC at **p=reject** with no SPF and no DKIM. This is
the worst possible combination: any unauthenticated message from
`@yieldiq.com` (which is every message we send today, because we have no
SPF/DKIM on this domain) **fails DMARC and is silently dropped by every
major receiver** (Gmail, Outlook, Yahoo). The `rua=mailto:rua@dmarc.microsoft`
target is also malformed — `dmarc.microsoft` is not a valid hostname,
so aggregate reports are not being delivered either.

## Gap summary (action items)

Two domains, ranked by urgency.

### P0 — yieldiq.com (every prod email is failing DMARC today)

The current state is "DMARC reject + no auth" — this is functionally an
outage. Pick ONE of two paths:

**Option A (recommended, smallest change): switch the From header to
`hello@yieldiq.in` and use the existing `.in` DKIM.** One Railway env
var flip:

```
SENDGRID_FROM_EMAIL=hello@yieldiq.in
```

Then add the missing SPF on `.in` (see P1 below). Total time: 15 min.
This route uses the SendGrid DKIM CNAMEs already in DNS on `.in`.

**Option B (if `.com` From is brand-required): authenticate `.com`.**
Add these records on `yieldiq.com` (Azure DNS):

```
Type    Name                        Value
TXT     yieldiq.com                 v=spf1 include:sendgrid.net ~all
CNAME   s1._domainkey               s1.domainkey.u<SUBUSER>.wl217.sendgrid.net
CNAME   s2._domainkey               s2.domainkey.u<SUBUSER>.wl217.sendgrid.net
CNAME   em<NNNN>                    u<SUBUSER>.wl217.sendgrid.net
```

The `<SUBUSER>` and `<NNNN>` values come from SendGrid → Settings →
Sender Authentication → "Authenticate Your Domain" → enter `yieldiq.com`.
SendGrid then prints the three CNAMEs to paste into Azure DNS.

Also fix the DMARC `rua=` target — `mailto:rua@dmarc.microsoft` is
malformed. Replace with a real mailbox you can read, e.g.
`mailto:dmarc@yieldiq.in`. Until SPF + DKIM are passing, lower the
DMARC policy to `p=none` so aggregate reports flow in without bouncing
legitimate mail:

```
v=DMARC1; p=none; pct=100; rua=mailto:dmarc@yieldiq.in; fo=1
```

Once a week of reports shows SPF + DKIM passing at >99%, raise back to
`p=quarantine` then `p=reject`.

### P1 — yieldiq.in (cheap hygiene win)

Add SPF on `.in` so future `@yieldiq.in` sends authenticate:

```
Type    Name           Value
TXT     yieldiq.in     v=spf1 include:sendgrid.net ~all
```

The DKIM CNAMEs are already present and correct. DMARC is present and
sensible at `p=quarantine`. Once SPF is added, `.in` is fully aligned.

### P2 — operational

- Add `tags=["upgrade_confirmation"]` and `tags=["student_decision"]`
  to `send_upgrade_confirmation_email` and `send_student_application_email`
  so SendGrid dashboard analytics segment by surface (today they ship
  with no category).
- Set up a SendGrid Event Webhook to log bounces / spam complaints to
  the `email_send_log` table that already exists for idempotency.
- Move the unverified `rua` mailbox to one a human checks weekly.

## Smoke test

`scripts/email_smoke.py` sends one of each transactional template to a
recipient you control. Run it AFTER making any DNS change to verify
the new authentication path.

```
SENDGRID_API_KEY=... \
SENDGRID_FROM_EMAIL=hello@yieldiq.in \
python scripts/email_smoke.py --to you@gmail.com
```

The script prints SendGrid response status for each send. **Then open
each message in Gmail → triple-dot menu → "Show original"** and verify:

- `SPF: PASS` with the domain matching the From-domain
- `DKIM: PASS` with the domain matching the From-domain
- `DMARC: PASS`

If any of the three are `FAIL` or `NEUTRAL`, the DNS change has not
propagated or the domain in the From header does not match the
authenticated domain. Wait 10 min (TTL = 600s on `.in`, 300s on `.com`)
and retry.

## SendGrid monitoring

- Activity feed: https://app.sendgrid.com/email_activity
- Sender Authentication: https://app.sendgrid.com/settings/sender_auth
- Bounces: https://app.sendgrid.com/suppressions/bounces
- Spam reports: https://app.sendgrid.com/suppressions/spam_reports
- Stats by category: https://app.sendgrid.com/statistics/category

Healthy thresholds for a transactional sender at our volume (<200/day):

- Bounce rate < 2%
- Spam-report rate < 0.08% (Gmail's published threshold)
- Block rate < 0.5%

If any threshold is breached, pause the relevant category in
`email_service.py` and investigate before resuming.

## Owner / next review

Founder. Re-audit after each of:

1. The `.com` SPF/DKIM change (or the `.in` From-domain switch).
2. First weekly digest send post-fix.
3. First 100 welcome emails sent post-fix.
