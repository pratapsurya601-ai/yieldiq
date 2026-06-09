#!/usr/bin/env node
/**
 * fetch-logos-logodev.mjs — bulk-fetch crisp 192px PNG logos from
 * Logo.dev for every entry in `frontend/src/data/ticker_domains.json`
 * and write them to `frontend/public/logos/{TICKER}.png` so the avatar
 * chips can be served retina-sharp from our own origin instead of the
 * 64-128px Google s2/favicons fallback.
 *
 * Public token is embedded by design — Logo.dev's free tier issues
 * domain-restricted public keys (the same pattern as a Stripe publishable
 * key). Safe to commit; user has accepted the model.
 *
 * Validation rules per response:
 *   - HTTP 200 (we skip 202 — Logo.dev returns 202 with a generated
 *     initials placeholder when it doesn't have the real logo; that's
 *     worse than our existing Google favicon fallback so we'd rather
 *     punt and let the runtime cascade in TickerAvatar handle it).
 *   - content-type starts with `image/png`.
 *   - body size > 2KB (defends against an edge case where the CDN
 *     returns a 1×1 transparent stub at 200).
 *
 * Filename sanitisation matches `TickerAvatar.tsx` so the runtime
 * lookup is a direct hashmap hit:
 *   `&` → `_AND_`, `-` → `_`. Nothing else is transformed.
 *
 * Maintains `frontend/public/logos/_manifest.json`:
 *   { TICKER: { domain, source_url, bytes, fetched_at, hash, status } }
 * Every attempt is recorded — success, placeholder, or fail — so the
 * READme can describe the corpus and re-runs can detect drift.
 *
 * Rate-limit: 200ms between requests (5 req/sec). 261 entries → ~52s.
 * Retry once on transient HTTP 000 / 5xx with a 500ms backoff.
 */
import { createHash } from "node:crypto"
import { mkdir, readFile, writeFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const FRONTEND_ROOT = resolve(__dirname, "..")

const DOMAINS_PATH = resolve(
  FRONTEND_ROOT,
  "src/data/ticker_domains.json",
)
const OUT_DIR = resolve(FRONTEND_ROOT, "public/logos")
const MANIFEST_PATH = resolve(OUT_DIR, "_manifest.json")

// Public, domain-restricted Logo.dev token. User-provided.
const LOGO_DEV_TOKEN = "pk_SNFK_ZzwSiq032W9M6TmJg"
const SIZE_PX = 192
const MIN_BYTES = 2048
const RATE_LIMIT_MS = 200
const RETRY_BACKOFF_MS = 500

/**
 * Build the filesystem-safe ticker for the on-disk PNG name.
 *
 * Keep this in lockstep with the runtime resolver in
 * `frontend/src/lib/logoUrl.ts` (`getSelfHostedLogoUrl`) — both sides
 * MUST apply identical transformations or the chip will 404 and fall
 * through to the Google favicon stage even when the file exists.
 */
export function tickerToFsSafe(ticker) {
  return ticker.replace(/&/g, "_AND_").replace(/-/g, "_")
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

function buildLogoDevUrl(domain) {
  return `https://img.logo.dev/${encodeURIComponent(domain)}?token=${LOGO_DEV_TOKEN}&size=${SIZE_PX}&format=png`
}

/**
 * Fetch one logo. Returns a result object — never throws.
 *
 * Result shape:
 *   { ok: true,  status: "saved",       bytes, hash, contentType }
 *   { ok: false, status: "placeholder", httpStatus }
 *   { ok: false, status: "too_small",   bytes }
 *   { ok: false, status: "bad_type",    contentType }
 *   { ok: false, status: "http_error",  httpStatus }
 *   { ok: false, status: "network",     message }
 */
export async function fetchOne(domain, { fetchImpl = fetch } = {}) {
  const url = buildLogoDevUrl(domain)
  let lastErr = null

  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetchImpl(url, {
        headers: {
          "User-Agent": "YieldIQ-LogoFetcher/1.0 (+https://yieldiq.in)",
        },
      })

      // Logo.dev returns 202 with a generated placeholder when it
      // doesn't have the real logo. Skip — Google favicon is a better
      // long-tail fallback.
      if (res.status === 202) {
        return { ok: false, status: "placeholder", httpStatus: 202 }
      }

      if (res.status >= 500 || res.status === 0) {
        lastErr = { ok: false, status: "http_error", httpStatus: res.status }
        await sleep(RETRY_BACKOFF_MS)
        continue
      }

      if (!res.ok) {
        return { ok: false, status: "http_error", httpStatus: res.status }
      }

      const contentType = res.headers.get("content-type") || ""
      if (!contentType.toLowerCase().startsWith("image/png")) {
        return { ok: false, status: "bad_type", contentType }
      }

      const buf = Buffer.from(await res.arrayBuffer())
      if (buf.byteLength < MIN_BYTES) {
        return { ok: false, status: "too_small", bytes: buf.byteLength }
      }

      const hash = createHash("sha256").update(buf).digest("hex").slice(0, 16)
      return {
        ok: true,
        status: "saved",
        bytes: buf.byteLength,
        hash,
        contentType,
        url,
        buf,
      }
    } catch (err) {
      lastErr = {
        ok: false,
        status: "network",
        message: err?.message ?? String(err),
      }
      await sleep(RETRY_BACKOFF_MS)
    }
  }

  return lastErr ?? { ok: false, status: "network", message: "unknown" }
}

/**
 * Pure orchestrator — accepts an injected `fetchImpl` and `writeFile`
 * so the unit test can run without touching the network or disk. The
 * real CLI entrypoint at the bottom of the file wires the real fetch
 * and fs writers.
 */
export async function runFetch({
  domains,
  fetchImpl = fetch,
  writeFileImpl = writeFile,
  mkdirImpl = mkdir,
  outDir = OUT_DIR,
  manifestPath = MANIFEST_PATH,
  rateLimitMs = RATE_LIMIT_MS,
  logger = console,
} = {}) {
  await mkdirImpl(outDir, { recursive: true })

  const manifest = {}
  const summary = {
    total: 0,
    saved: 0,
    placeholder: 0,
    too_small: 0,
    bad_type: 0,
    http_error: 0,
    network: 0,
    total_bytes: 0,
  }

  const entries = Object.entries(domains).filter(
    ([k]) => k !== "_meta" && k !== "_META",
  )

  for (let i = 0; i < entries.length; i++) {
    const [ticker, domain] = entries[i]
    summary.total++

    if (typeof domain !== "string" || !domain.trim()) {
      manifest[ticker] = {
        domain: null,
        status: "no_domain",
        fetched_at: new Date().toISOString(),
      }
      continue
    }

    const result = await fetchOne(domain, { fetchImpl })

    if (result.ok) {
      const fsSafe = tickerToFsSafe(ticker)
      const filePath = resolve(outDir, `${fsSafe}.png`)
      await writeFileImpl(filePath, result.buf)
      summary.saved++
      summary.total_bytes += result.bytes
      manifest[ticker] = {
        domain,
        source_url: result.url,
        bytes: result.bytes,
        hash: result.hash,
        fetched_at: new Date().toISOString(),
        status: "saved",
        filename: `${fsSafe}.png`,
      }
      logger.log(
        `  [${i + 1}/${entries.length}] OK   ${ticker.padEnd(14)} ${domain.padEnd(28)} ${result.bytes}B`,
      )
    } else {
      summary[result.status] = (summary[result.status] ?? 0) + 1
      manifest[ticker] = {
        domain,
        fetched_at: new Date().toISOString(),
        status: result.status,
        ...("httpStatus" in result ? { http_status: result.httpStatus } : {}),
        ...("bytes" in result ? { bytes: result.bytes } : {}),
        ...("contentType" in result
          ? { content_type: result.contentType }
          : {}),
        ...("message" in result ? { error: result.message } : {}),
      }
      logger.log(
        `  [${i + 1}/${entries.length}] SKIP ${ticker.padEnd(14)} ${domain.padEnd(28)} ${result.status}`,
      )
    }

    if (i < entries.length - 1 && rateLimitMs > 0) {
      await sleep(rateLimitMs)
    }
  }

  await writeFileImpl(
    manifestPath,
    JSON.stringify(
      {
        _meta: {
          source: "logo.dev (free tier, public token)",
          token_prefix: LOGO_DEV_TOKEN.slice(0, 6) + "…",
          size_px: SIZE_PX,
          format: "png",
          fetched_at: new Date().toISOString(),
          summary,
        },
        logos: manifest,
      },
      null,
      2,
    ),
  )

  return { manifest, summary }
}

function printSummary(summary, logger = console) {
  const fail =
    summary.http_error +
    summary.network +
    summary.bad_type +
    summary.too_small
  logger.log("")
  logger.log("─".repeat(60))
  logger.log("Logo.dev fetch summary")
  logger.log("─".repeat(60))
  logger.log(`  total processed   : ${summary.total}`)
  logger.log(`  saved (real PNG)  : ${summary.saved}`)
  logger.log(`  placeholder (202) : ${summary.placeholder}`)
  logger.log(`  fail (skipped)    : ${fail}`)
  logger.log(`    - http_error    : ${summary.http_error}`)
  logger.log(`    - network       : ${summary.network}`)
  logger.log(`    - bad_type      : ${summary.bad_type}`)
  logger.log(`    - too_small     : ${summary.too_small}`)
  logger.log(
    `  total bytes saved : ${summary.total_bytes} (${(summary.total_bytes / 1024).toFixed(1)} KB)`,
  )
  logger.log("─".repeat(60))
}

// CLI entrypoint — only executes when called directly, not when
// imported by the test harness.
const isMain =
  process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))

if (isMain) {
  const raw = await readFile(DOMAINS_PATH, "utf8")
  const domains = JSON.parse(raw)
  console.log(
    `Fetching ${Object.keys(domains).filter((k) => k !== "_meta").length - (domains._META ? 1 : 0)} logos from Logo.dev …`,
  )
  const { summary } = await runFetch({ domains })
  printSummary(summary)
}
