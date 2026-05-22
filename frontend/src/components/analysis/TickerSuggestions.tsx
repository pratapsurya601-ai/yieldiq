"use client"
/**
 * Day-106 — "Did you mean?" suggestions block.
 *
 * Rendered inside the not-found (404) branch of /analysis/[ticker]. When the
 * user lands on a delisted/typo ticker (e.g. "HDFC" after the 2023 merger
 * into HDFCBANK), we extract the typed query from the URL, hit the existing
 * public /api/v1/search endpoint, and offer 1-click recovery to the right
 * symbol. If the suggest call returns nothing we render nothing — the
 * caller's "Search again" CTA stays as the fallback.
 *
 * Suggestions are cached by query for 5 minutes; they don't change
 * minute-to-minute and the backend list is static.
 */
import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import api from "@/lib/api"

interface SuggestResult {
  ticker: string
  name: string
  type: string
}

interface SuggestResponse {
  query: string
  results: SuggestResult[]
}

/**
 * Strip exchange suffixes and normalise to a search query. We mirror what
 * backend search_tickers expects: lowercase, trimmed, no suffix.
 */
export function tickerToSuggestQuery(ticker: string): string {
  return ticker
    .replace(/\.NS$/i, "")
    .replace(/\.BO$/i, "")
    .replace(/\.BSE$/i, "")
    .trim()
    .toLowerCase()
}

interface Props {
  /** The (failed) ticker from the URL, e.g. "HDFC" or "HDFC.NS". */
  ticker: string
}

export default function TickerSuggestions({ ticker }: Props) {
  const q = tickerToSuggestQuery(ticker)

  const { data } = useQuery<SuggestResponse>({
    queryKey: ["ticker-suggest", q],
    // search_tickers itself short-circuits queries < 2 chars to [],
    // so we mirror that on the client to skip a needless round-trip.
    enabled: q.length >= 2,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    retry: false,
    queryFn: async () => {
      const res = await api.get<SuggestResponse>("/api/v1/search", {
        params: { q, limit: 5 },
      })
      return res.data
    },
  })

  const results = data?.results ?? []
  if (results.length === 0) return null

  return (
    <div className="mt-2 mb-6 text-left" data-testid="ticker-suggestions">
      <p className="text-xs font-semibold uppercase tracking-wider text-caption mb-2 text-center">
        Did you mean?
      </p>
      <ul className="space-y-2">
        {results.map((r) => {
          const display = r.ticker.replace(".NS", "").replace(".BO", "")
          return (
            <li key={r.ticker}>
              <Link
                href={`/analysis/${r.ticker}`}
                className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface px-4 py-3 min-h-[44px] hover:border-brand hover:bg-brand/5 active:scale-[0.99] transition"
                data-testid={`suggest-${r.ticker}`}
              >
                <span className="flex flex-col text-left">
                  <span className="text-sm font-semibold text-ink">{display}</span>
                  <span className="text-xs text-body">{r.name}</span>
                </span>
                <span className="text-body" aria-hidden="true">
                  &rsaquo;
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
