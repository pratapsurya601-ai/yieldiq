// frontend/src/app/api/revalidate/route.ts
//
// On-demand ISR revalidation endpoint.
//
// The fair-value SEO pages (/stocks/[ticker]/fair-value) are statically
// generated with `next: { revalidate: 300 }`. That gives a 5-minute
// time-based fallback, but we also want the backend to actively kick
// the CDN whenever it writes a fresh analysis to analysis_cache —
// otherwise users who hit a stale page will see numbers that disagree
// with the live API for up to 5 minutes.
//
// Contract:
//   POST /api/revalidate?secret=...   (or x-revalidate-secret header)
//   body: { "path": "/stocks/ITC.NS/fair-value" }   OR  { "tag": "..." }
//
// Returns:
//   200 { revalidated: true,  now: <ms> }
//   401 { revalidated: false, message: "invalid secret" }
//   400 { revalidated: false, message: "path or tag required" }
//   500 { revalidated: false, message: <error> }
//
// Auth: shared secret in REVALIDATE_SECRET. Backend reads the same
// value from its env (REVALIDATE_SECRET) and posts here after a
// successful analysis_cache write. See
// backend/services/analysis_cache_service.py:save_cached.

import { NextRequest, NextResponse } from "next/server"
import { revalidatePath } from "next/cache"
// NOTE: this Next version's revalidateTag requires a cache-profile arg
// (revalidateTag(tag, profile)). We don't use tag-based revalidation
// yet — the backend hook always sends `path` — so we intentionally
// don't import it. Re-add with the 2-arg signature if/when needed.

// Must run on Node, not Edge — revalidatePath/revalidateTag rely on
// the Node-only ISR data cache APIs.
export const runtime = "nodejs"

export async function POST(req: NextRequest) {
  try {
    const expected = process.env.REVALIDATE_SECRET
    if (!expected) {
      // Misconfiguration is treated as auth failure — never silently
      // accept un-secured revalidation in any environment.
      return NextResponse.json(
        { revalidated: false, message: "revalidate secret not configured" },
        { status: 401 },
      )
    }

    const url = new URL(req.url)
    const provided =
      url.searchParams.get("secret") ||
      req.headers.get("x-revalidate-secret") ||
      ""
    if (provided !== expected) {
      return NextResponse.json(
        { revalidated: false, message: "invalid secret" },
        { status: 401 },
      )
    }

    let body: { path?: string } = {}
    try {
      body = await req.json()
    } catch {
      // empty / invalid JSON — fall through to the path check below
    }

    const { path } = body
    if (!path) {
      return NextResponse.json(
        { revalidated: false, message: "path required" },
        { status: 400 },
      )
    }

    revalidatePath(path)

    return NextResponse.json({ revalidated: true, now: Date.now() })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { revalidated: false, message },
      { status: 500 },
    )
  }
}
