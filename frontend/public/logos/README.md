# Self-hosted NSE ticker logos

This folder holds the 253 retina-sharp 192×192 PNG logos for the curated
NSE universe in `frontend/src/data/ticker_domains.json` (261 entries; 8
domains hit a Logo.dev placeholder or oversized-image guard and remain
on the runtime fallback chain).

## Source

[Logo.dev](https://logo.dev) free tier, fetched via the public token
embedded in `frontend/scripts/fetch-logos-logodev.mjs`. Public tokens
are domain-restricted by design (same model as a Stripe publishable
key) and are safe to commit.

Endpoint:

```
GET https://img.logo.dev/{domain}?token={pk_…}&size=192&format=png
```

Validation rules (in `fetch-logos-logodev.mjs`):

- HTTP 200 (HTTP 202 = Logo.dev placeholder, skipped — the runtime
  Google s2/favicons fallback in `TickerAvatar.tsx` is a better
  long-tail option than an initials placeholder).
- `content-type` starts with `image/png`.
- Body size > 2 KB (defends against 1×1 transparent stubs).

## License & attribution

Per Logo.dev's free-tier terms, the logos are used here under
**nominative fair use** for identification of the company being
analysed. Attribution is rendered in the site footer
(`TrustFooter.tsx`):

> Company names and logos are trademarks of their respective owners
> and are used for identification purposes only. Logo data from logo.dev.

Do not relicense, repackage, or redistribute these PNGs as a separate
asset bundle.

## Refresh procedure

To regenerate the corpus (e.g. after `ticker_domains.json` is amended,
or to pick up updated Logo.dev coverage for tickers that previously
landed on a placeholder):

```bash
node frontend/scripts/fetch-logos-logodev.mjs
```

The script:

1. Iterates `frontend/src/data/ticker_domains.json` (skipping `_meta`).
2. Sanitises the ticker key to a filesystem-safe form:
   `&` → `_AND_`, `-` → `_`. (E.g. `M&M` → `M_AND_M.png`.)
3. Saves each accepted PNG to `frontend/public/logos/{TICKER}.png`.
4. Maintains `_manifest.json` documenting every fetch attempt
   (success, placeholder, or fail with reason).

Rate-limited to 5 req/s; full corpus refresh takes ~52s.

## Manifest

`_manifest.json` is the source of truth for what was fetched, when,
and which entries fell back. Inspect it with:

```bash
jq '._meta.summary' frontend/public/logos/_manifest.json
```

Last refresh summary (2026-06-09):

- saved (real PNG): 253
- placeholder (HTTP 202): 3
- too small (<2 KB): 5
- total bytes: ~4.5 MB

## Runtime resolution

The avatar component
(`frontend/src/components/common/TickerAvatar.tsx`) tries the
self-hosted PNG first via `getSelfHostedLogoUrl(ticker)` in
`frontend/src/lib/logoUrl.ts`. On 404 the `<img onError>` cascade
advances through Google s2/favicons → DuckDuckGo icons → sector-coloured
letter mark. The server-side OG image renderer
(`frontend/src/app/api/og/_lib/companyLogo.ts`) follows the same order.

Keep the three filename-sanitisation sites in lockstep:

- `frontend/scripts/fetch-logos-logodev.mjs` → `tickerToFsSafe`
- `frontend/src/lib/logoUrl.ts` → `tickerToLogoFilename`
- `frontend/src/app/api/og/_lib/companyLogo.ts` → `tickerToLogoFilename`
