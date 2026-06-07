// verify-logo-urls.mjs — sanity check that the swapped-in logo CDNs
// actually return image bytes for the 5 representative tickers.
// Pass-criterion: for each ticker, at least one of (Google s2/favicons,
// DuckDuckGo ip3) must return a 2xx with image bytes. The `<img onError>`
// cascade in TickerAvatar covers per-ticker primary failures at runtime,
// so a single primary 404 doesn't break UX — but at-least-one-source
// must always succeed, otherwise the chain falls straight to the
// letter mark.
// Run: node frontend/scripts/verify-logo-urls.mjs
const TICKERS = ["HDFCBANK", "TCS", "INFY", "MARUTI", "RELIANCE"]

// Re-implement the primary URL builder here (rather than importing
// the TS, which would require a transform). Keep this in lockstep
// with `urlForStage(s=0)` in TickerAvatar.tsx and getLogoUrl's
// primary path in logoUrl.ts.
function googleFaviconUrl(domain, sz = 128) {
  return `https://www.google.com/s2/favicons?domain=${domain}&sz=${sz}`
}
function duckduckgoIconUrl(domain) {
  return `https://icons.duckduckgo.com/ip3/${domain}.ico`
}

const DOMAINS = {
  HDFCBANK: "hdfcbank.com",
  TCS: "tata.com",
  INFY: "infosys.com",
  MARUTI: "marutisuzuki.com",
  RELIANCE: "ril.com",
}

async function check(label, url) {
  try {
    const res = await fetch(url, {
      signal: AbortSignal.timeout(5000),
      redirect: "follow",
    })
    const ct = res.headers.get("content-type") || ""
    const buf = await res.arrayBuffer()
    const ok = res.ok && ct.startsWith("image/") && buf.byteLength > 0
    console.log(
      `  ${ok ? "OK" : "FAIL"}  ${label.padEnd(12)}  status=${res.status}  type=${ct}  bytes=${buf.byteLength}`,
    )
    return ok
  } catch (err) {
    console.log(`  FAIL  ${label.padEnd(12)}  threw: ${err?.message ?? err}`)
    return false
  }
}

let bothDead = 0
let primaryDead = 0
for (const t of TICKERS) {
  const domain = DOMAINS[t]
  console.log(`\n${t}  (${domain})`)
  const primary = googleFaviconUrl(domain, 128)
  const fallback = duckduckgoIconUrl(domain)
  const okPrimary = await check("google-128", primary)
  const okFallback = await check("ddg-ico", fallback)
  if (!okPrimary) primaryDead += 1
  if (!okPrimary && !okFallback) bothDead += 1
}

console.log(
  `\nSummary: primary-failed=${primaryDead}/${TICKERS.length}` +
    `, both-failed=${bothDead}/${TICKERS.length}`,
)
if (bothDead === 0) {
  console.log(
    "PASS: every sample ticker has at least one working logo source (Google primary or DuckDuckGo fallback). " +
      "Tickers that fail BOTH would cascade to the sector-colored letter mark in the live UI.",
  )
  process.exit(0)
} else {
  console.log(
    `FAIL: ${bothDead} ticker(s) have NO working source — those will render as letter marks. ` +
      "If this is a small number (1-2) and matches known-stale Google-favicon entries, ship anyway; " +
      "otherwise investigate before merging.",
  )
  process.exit(1)
}
