#!/usr/bin/env node
/**
 * Build or refresh `frontend/public/tickers.json` — the slim index used
 * by the client-side fuzzy search in `src/app/(app)/search/page.tsx`.
 *
 * Why not run this from `next build`?
 *   The Railway backend may not be reachable from a CI build runner, and
 *   we don't want a transient outage to break the marketing site deploy.
 *   So this is a MANUAL script: run it when the ticker universe changes,
 *   commit the updated JSON. The file itself is the source of truth for
 *   the frontend; the backend endpoint is just a convenient refresh tap.
 *
 * Usage:
 *   # Hit a local dev backend
 *   node scripts/build_ticker_index.mjs
 *
 *   # Hit a specific base URL
 *   API_BASE=https://api.yieldiq.in node scripts/build_ticker_index.mjs
 *
 * Behaviour:
 *   - On success, overwrites `public/tickers.json`.
 *   - On network failure, prints a warning and exits 0 without touching
 *     the existing JSON. This keeps CI/local dev from breaking if the
 *     backend is down.
 */
import { writeFile } from "node:fs/promises"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT_PATH = join(__dirname, "..", "public", "tickers.json")
const API_BASE = process.env.API_BASE || "http://localhost:8000"
const URL = `${API_BASE.replace(/\/$/, "")}/api/v1/public/tickers-index`

async function main() {
  console.log(`[tickers-index] fetching ${URL}`)
  let res
  try {
    res = await fetch(URL, { headers: { Accept: "application/json" } })
  } catch (err) {
    console.warn(`[tickers-index] fetch failed — keeping existing JSON. Error: ${err.message}`)
    return
  }
  if (!res.ok) {
    console.warn(`[tickers-index] HTTP ${res.status} — keeping existing JSON.`)
    return
  }
  const body = await res.json()
  if (!body || !Array.isArray(body.tickers)) {
    console.warn(`[tickers-index] unexpected response shape — keeping existing JSON.`)
    return
  }
  const payload = JSON.stringify(
    {
      version: body.version ?? 1,
      generated_at: body.generated_at ?? new Date().toISOString(),
      count: body.tickers.length,
      tickers: body.tickers,
    },
    null,
    0,
  )
  await writeFile(OUT_PATH, payload, "utf-8")
  console.log(`[tickers-index] wrote ${body.tickers.length} rows → ${OUT_PATH}`)
}

main().catch((err) => {
  console.error(`[tickers-index] fatal:`, err)
  process.exit(1)
})
