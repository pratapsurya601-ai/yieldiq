/**
 * AdrCohortBanner — transparency notice for ADR cross-listed Indian stocks.
 *
 * Why this exists: 16 Indian tickers that are cross-listed as ADRs in the
 * US (TCS, INFY, WIPRO, HCLTECH, TECHM, COFORGE, CYIENT, DIVISLAB,
 * KPITTECH, LAURUSLABS, LTIM, MASTEK, MPHASIS, OFSS, PERSISTENT,
 * TATAELXSI) hit a known yfinance.info upstream defect — the ADR record
 * shadows the NSE record and core financials come back partial or zero.
 * The downstream effect on the YieldIQ analysis page is a silent
 * "Data Limited" verdict with no explanation. The INFY post-mortem
 * (2026-04-29) confirmed this is a class-level issue, not a one-off.
 *
 * Until the direct NSE data path lands (ETA Q2 2026), we surface the
 * status explicitly so users typing "INFY" don't infer the model is
 * simply broken.
 *
 * Pure presentational, server-renderable. No data fetching.
 */

const ADR_AFFECTED_TICKERS = new Set<string>([
  "TCS",
  "INFY",
  "HCLTECH",
  "WIPRO",
  "TECHM",
  "COFORGE",
  "CYIENT",
  "DIVISLAB",
  "KPITTECH",
  "LAURUSLABS",
  "LTIM",
  "MASTEK",
  "MPHASIS",
  "OFSS",
  "PERSISTENT",
  "TATAELXSI",
])

export function isAdrAffected(ticker: string): boolean {
  const bare = ticker.toUpperCase().replace(".NS", "").replace(".BO", "")
  return ADR_AFFECTED_TICKERS.has(bare)
}

export default function AdrCohortBanner({ ticker }: { ticker: string }) {
  const bare = ticker.toUpperCase().replace(".NS", "").replace(".BO", "")
  if (!ADR_AFFECTED_TICKERS.has(bare)) return null

  return (
    <div
      role="status"
      className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900 text-amber-900 dark:text-amber-200 rounded-xl p-4 mb-4 mx-auto max-w-4xl"
    >
      <div className="flex items-start gap-3">
        <span className="text-lg" aria-hidden="true">ⓘ</span>
        <div className="flex-1 min-w-0 text-sm leading-relaxed">
          <p>
            <strong>Data Limited:</strong> {bare} is on our ADR cross-listed
            cohort where upstream financial data has known quality issues.
            We&apos;re working on a direct NSE data path. Fair value and score
            may be conservative until fix ETA Q2 2026.{" "}
            <a
              href="/blog/infy-incident-postmortem"
              className="underline font-semibold whitespace-nowrap"
            >
              Why this happens →
            </a>
          </p>
        </div>
      </div>
    </div>
  )
}
