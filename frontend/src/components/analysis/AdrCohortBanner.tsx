/**
 * AdrCohortBanner — data-sourcing qualification for ADR cross-listed
 * Indian stocks.
 *
 * Sixteen Indian tickers (TCS, INFY, WIPRO, HCLTECH, TECHM, COFORGE,
 * CYIENT, DIVISLAB, KPITTECH, LAURUSLABS, LTIM, MASTEK, MPHASIS, OFSS,
 * PERSISTENT, TATAELXSI) are cross-listed as ADRs on NYSE/NASDAQ. Our
 * upstream financials feed currently resolves these via the ADR record
 * rather than the NSE record. For the four tickers that render a full
 * analysis page today (INFY, WIPRO, HCLTECH, TECHM), the fair value and
 * score shown ARE our latest cached compute — the banner exists to
 * qualify the data-sourcing path so the user knows where the inputs
 * came from, NOT to undermine the values themselves.
 *
 * Banner is paired with a per-ticker TickerAvatar chip in the header
 * for visual consistency with the rest of the analysis surface.
 *
 * Pure presentational, server-renderable. No data fetching.
 */

import TickerAvatar from "@/components/common/TickerAvatar"

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
      className="bg-tone-warn-bg dark:bg-amber-950/30 border border-tone-warn-bd dark:border-amber-900 text-amber-900 dark:text-amber-200 rounded-xl p-4 mb-4 mx-auto max-w-4xl"
    >
      <div className="flex items-start gap-3">
        <div className="flex items-center gap-2 shrink-0">
          <TickerAvatar ticker={bare} size="sm" />
          <span className="font-semibold tabular-nums">{bare}</span>
        </div>
        <div className="flex-1 min-w-0 text-sm leading-relaxed">
          <p>
            <span className="font-bold">Data path:</span> financials for{" "}
            {bare} are currently sourced via the US ADR cross-listing
            (NYSE/NASDAQ). The fair value and score on this page reflect
            the latest cached compute against that data path. A direct
            NSE data path is in active development; values will refresh
            once it lands.{" "}
            <a
              href="/blog/infy-incident-postmortem"
              className="underline font-semibold whitespace-nowrap"
            >
              How our data sourcing works →
            </a>
          </p>
        </div>
      </div>
    </div>
  )
}
