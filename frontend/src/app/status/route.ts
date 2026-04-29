// frontend/src/app/status/route.ts
//
// Temporary placeholder for the public status page.
//
// The site footer and /legal/sla page link to https://status.yieldiq.in,
// but DNS for that subdomain has not been wired to Better Stack yet (see
// docs/ops/status_page_setup.md). Until the CNAME lands and a cert is
// issued, /status redirects users to the Better Stack–assigned hostname
// so the footer link is never a dead end.
//
// Once https://status.yieldiq.in resolves with a valid cert, this file
// can be deleted (or the redirect target updated to status.yieldiq.in —
// see step 6 of the runbook).
//
// We intentionally do NOT introduce a new env var for the temporary
// hostname: this file is short-lived and the URL is public.

import { NextResponse } from "next/server"

// 307 keeps the method + signals the redirect is temporary, so search
// engines and clients won't cache status.yieldiq.in → betterstack.com.
const TEMP_STATUS_URL = "https://yieldiq.betterstack.com"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export function GET() {
  return NextResponse.redirect(TEMP_STATUS_URL, 307)
}
