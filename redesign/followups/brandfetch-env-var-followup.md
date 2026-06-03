# Brandfetch logo quality — operator config follow-up (one-line)

**Status:** filed 2026-06-03. NOT a PR. NOT a project. **One env var the operator sets whenever they want better logo quality.**
**Priority:** LOW (favicon fallback is adequate at current DAU).

---

## The one line

Set `NEXT_PUBLIC_BRANDFETCH_CLIENT_ID` in the Vercel project environment to your Brandfetch developer client ID. The existing `getLogoUrl()` chain in `frontend/src/lib/logoUrl.ts` will pick it up and switch from favicon fallback to Brandfetch CDN logos automatically. No code change.

## Why this is here, not in a PR

Phase 0 confirmed that the logo infrastructure is fully built — `getLogoUrl()` + `ticker_domains.json` + `marquee_heroes.json` + the new `<TickerAvatar>` chip-wrapper (per Phase 1 primitives). The favicon fallback is what renders today and it's adequate. Brandfetch ships higher-quality, brand-consistent logos but it's a quality-step-up, not a bug fix.

At ~3 DAU, favicon-quality logos are not what's blocking acquisition. Set the env var whenever — a week from now, a month from now, after the content experiment shows traffic and you want every Twitter share to look premium. Until then this is parked.

## Do NOT let this expand

- It is NOT a "logo quality project."
- It is NOT a "switch fallback strategy" task.
- It is one environment variable. Set it. Move on.

If anyone proposes investigating Brandfetch's API limits, comparing logo CDNs, or building a logo-quality dashboard — that is the absorption trap. The 3-DAU rule applies.

## Cross-references

- Phase 0 premise-check P0.6 — logo infrastructure confirmed already built
- `frontend/src/lib/logoUrl.ts` — the chain that consumes the env var
- `frontend/src/data/ticker_domains.json` — the per-ticker domain map (drives the Brandfetch + favicon URLs)
- `frontend/src/data/marquee_heroes.json` — the marquee-50 hand-picked set
