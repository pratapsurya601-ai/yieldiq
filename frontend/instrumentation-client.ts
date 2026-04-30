import * as Sentry from "@sentry/nextjs"

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_VERCEL_ENV || "development",
  release: process.env.NEXT_PUBLIC_BUILD_ID || process.env.VERCEL_GIT_COMMIT_SHA,

  // Conservative sampling for paid-tier cost control
  tracesSampleRate: 0.1,           // 10% of requests
  replaysSessionSampleRate: 0,     // session replay OFF (expensive)
  replaysOnErrorSampleRate: 1.0,   // 100% on errors only

  // Suppress known browser noise
  ignoreErrors: [
    "ResizeObserver loop limit exceeded",
    "ResizeObserver loop completed with undelivered notifications",
    "Non-Error promise rejection captured",
    "Hydration failed",  // Next.js hydration warnings, separately tracked
  ],

  // Don't capture if no DSN configured (local dev without sentry)
  enabled: !!process.env.NEXT_PUBLIC_SENTRY_DSN,
})
