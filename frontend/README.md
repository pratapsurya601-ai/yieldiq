# YieldIQ frontend

## Local development

Install dependencies and start Next.js:

```bash
npm ci
npm run dev
```

The frontend uses `NEXT_PUBLIC_API_URL` to reach the FastAPI backend. See
`.env.local.example` for local configuration.

## Cloudflare Workers deployment

The app uses the OpenNext Cloudflare adapter. Preview the Cloudflare runtime
locally with:

```bash
npm run preview:cloudflare
```

Production deployment is a manual GitHub Actions workflow. Before running it,
configure these repository Actions variables and secrets:

- Variables: `NEXT_PUBLIC_API_URL` (defaults to `https://api.yieldiq.in`),
  `NEXT_PUBLIC_GA4_ID`, and `NEXT_PUBLIC_SENTRY_DSN`.
- Secrets: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and optionally
  `SENTRY_AUTH_TOKEN` for source-map uploads.
- Create the R2 bucket `yieldiq-next-cache` before deploying; it stores the
  Next.js incremental cache. R2 has monthly free allowances, with charges if
  usage exceeds them.

The Cloudflare token needs permission to deploy Workers. The workflow deploys
to a `workers.dev` address; attach the production domain only after checking
the deployment. The FastAPI service remains on Railway. Image optimization is
disabled to avoid requiring a paid Cloudflare Images binding.

Keep the Vercel deployment available during the migration. Switch the DNS for
`yieldiq.in` only after the Cloudflare deployment passes the production smoke
checks.
