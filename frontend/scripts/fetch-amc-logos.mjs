#!/usr/bin/env node
/**
 * fetch-amc-logos.mjs — bulk-fetch crisp 192px PNG logos from Logo.dev
 * for every fund house in `frontend/src/data/amc_domains.json` and write
 * them to `frontend/public/logos/amc/{slug}.png`, so AmcAvatar can serve
 * retina-sharp brand logos from our own origin instead of low-res
 * (~32-64px) favicons.
 *
 * Sibling of fetch-logos-logodev.mjs — reuses its `runFetch` orchestrator
 * (same Logo.dev public token, the same 200/PNG/>2KB validation that
 * skips 202 placeholders, the same per-attempt manifest). The only
 * difference is the input map and the output dir.
 *
 * Filename slug: the amc_domains.json keys are already the normalized AMC
 * name (lowercase, "Mutual Fund"/"AMC" stripped — see normalizeAmcName in
 * src/lib/logoUrl.ts). We re-key them to a filesystem-safe slug by
 * collapsing every non [a-z0-9] run to "_", which MUST stay in lockstep
 * with `getAmcLogoFilename` in src/lib/logoUrl.ts or the chip 404s and
 * falls through to the favicon stage.
 *
 *   "aditya birla sun life" → aditya_birla_sun_life.png
 *   "360 one"               → 360_one.png
 *
 * Run:  node frontend/scripts/fetch-amc-logos.mjs
 */
import { readFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { runFetch } from "./fetch-logos-logodev.mjs"

const __dirname = dirname(fileURLToPath(import.meta.url))
const FRONTEND_ROOT = resolve(__dirname, "..")
const AMC_PATH = resolve(FRONTEND_ROOT, "src/data/amc_domains.json")
const OUT_DIR = resolve(FRONTEND_ROOT, "public/logos/amc")
const MANIFEST_PATH = resolve(OUT_DIR, "_manifest.json")

/** Keep in lockstep with getAmcLogoFilename in src/lib/logoUrl.ts. */
function amcSlug(key) {
  return key.replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "")
}

const raw = JSON.parse(await readFile(AMC_PATH, "utf8"))
const domains = {}
for (const [key, domain] of Object.entries(raw)) {
  if (key === "_meta" || key === "_META") continue
  domains[amcSlug(key)] = domain
}

console.log(`Fetching ${Object.keys(domains).length} AMC logos from Logo.dev …`)
const { summary } = await runFetch({
  domains,
  outDir: OUT_DIR,
  manifestPath: MANIFEST_PATH,
})
console.log(JSON.stringify(summary, null, 2))
