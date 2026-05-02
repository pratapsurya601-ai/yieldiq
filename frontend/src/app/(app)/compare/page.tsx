"use client"
// /compare — side-by-side peer comparison view (2-5 stocks)
//
// Strategic roadmap #13: analysts pivot stocks side-by-side, not
// sequentially. This page lets the user pick up to 5 tickers and
// renders their key valuation, quality, scenario, and ratio metrics
// in a vertical-metrics x horizontal-stocks table. Best value per row
// is highlighted green; worst red. Auto-suggests sector peers based
// on the first ticker. Mobile responsive (stacks into per-stock cards
// on narrow viewports).
//
// URL contract:
//   /compare?tickers=RELIANCE,TCS,INFY,HDFCBANK
//
// Backwards compat: also accepts the legacy ?stock1=&stock2= shape
// so old links from the previous 2-stock compare page keep working.
//
// Data: parallel useQueries against /api/v1/public/stock-summary/<T>.
// The endpoint is server-cached (Redis) and Next-cached for 5 min, so
// 5 parallel client fetches is cheap. A dedicated batch endpoint is
// deliberately NOT added in P1 — revisit in Q3 if cache miss latency
// becomes painful.

import { useState, useEffect, useRef, useCallback, useMemo, Suspense } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { useQueries, useQuery } from "@tanstack/react-query"
import Link from "next/link"
import api, {
  getStockSummary,
  getPublicPeers,
  type StockSummary,
} from "@/lib/api"
import {
  formatCurrency,
  formatPct,
  formatPercentage,
  cn,
  verdictDisplayLabel,
} from "@/lib/utils"
import { SCORE_COLOR, VERDICT_COLORS } from "@/lib/constants"
import type { Verdict } from "@/types/api"

const MAX_STOCKS = 5
const MIN_STOCKS = 2

interface SearchResult {
  ticker: string
  name: string
}

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

function parseTickersParam(raw: string | null): string[] {
  if (!raw) return []
  return raw
    .split(",")
    .map((t) => t.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, MAX_STOCKS)
}

// Strip exchange suffix for display (.NS / .BO).
function displayTicker(t: string): string {
  return t.replace(/\.(NS|BO)$/i, "")
}

// ---------------------------------------------------------------------------
// Ticker search input — single-select; fires onSelect(ticker) when chosen.
// ---------------------------------------------------------------------------

function AddStockInput({
  onSelect,
  disabled,
  excluded,
}: {
  onSelect: (ticker: string) => void
  disabled: boolean
  excluded: Set<string>
}) {
  const [query, setQuery] = useState("")
  const [suggestions, setSuggestions] = useState<SearchResult[]>([])
  const [open, setOpen] = useState(false)
  const debounceRef = useRef<NodeJS.Timeout | null>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.length < 2) {
      setSuggestions([])
      return
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.get(`/api/v1/search?q=${encodeURIComponent(query)}`)
        const filtered = (res.data.results || []).filter(
          (r: SearchResult) => !excluded.has(r.ticker.toUpperCase()),
        )
        setSuggestions(filtered)
        setOpen(true)
      } catch {
        setSuggestions([])
      }
    }, 200)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query, excluded])

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", onClickOutside)
    return () => document.removeEventListener("mousedown", onClickOutside)
  }, [])

  if (disabled) {
    return (
      <div className="text-xs text-gray-500 italic px-3 py-2 border border-dashed border-gray-200 rounded-xl bg-gray-50">
        Limit reached ({MAX_STOCKS} stocks). Remove one to add another.
      </div>
    )
  }

  return (
    <div ref={wrapperRef} className="relative">
      <svg
        className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500 pointer-events-none"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
      </svg>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => suggestions.length > 0 && setOpen(true)}
        placeholder="Add stock... (e.g. INFY)"
        className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {open && suggestions.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden max-h-64 overflow-y-auto">
          {suggestions.map((s) => (
            <button
              key={s.ticker}
              onClick={() => {
                onSelect(s.ticker.toUpperCase())
                setQuery("")
                setOpen(false)
              }}
              className="w-full text-left px-4 py-3 hover:bg-blue-50 transition flex items-center justify-between border-b border-gray-50 last:border-0"
            >
              <span className="font-medium text-gray-900 text-sm truncate">{s.name}</span>
              <span className="text-xs text-gray-600 font-mono ml-3 shrink-0">
                {displayTicker(s.ticker)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Row helpers — best/worst highlighting
// ---------------------------------------------------------------------------

type Numish = number | null | undefined

function bestWorst(values: Numish[], higherIsBetter = true): { best: number | null; worst: number | null } {
  const finite = values
    .map((v, i) => ({ v, i }))
    .filter((x) => x.v != null && Number.isFinite(x.v as number))
  if (finite.length < 2) return { best: null, worst: null }
  const sorted = [...finite].sort((a, b) =>
    higherIsBetter ? (b.v as number) - (a.v as number) : (a.v as number) - (b.v as number),
  )
  // If best == worst (all values identical), don't highlight.
  if ((sorted[0].v as number) === (sorted[sorted.length - 1].v as number)) {
    return { best: null, worst: null }
  }
  return { best: sorted[0].i, worst: sorted[sorted.length - 1].i }
}

interface RowSpec {
  label: string
  // Per-stock raw value used for ranking (null if not comparable).
  values: Numish[]
  // Per-stock rendered cell.
  rendered: React.ReactNode[]
  higherIsBetter?: boolean
  // Disable highlighting for non-numeric / categorical rows.
  noRank?: boolean
}

function MetricRow({
  spec,
  count,
}: {
  spec: RowSpec
  count: number
}) {
  const { best, worst } = spec.noRank
    ? { best: null, worst: null }
    : bestWorst(spec.values, spec.higherIsBetter ?? true)

  return (
    <div
      className="grid items-center gap-2 px-3 py-2.5 text-sm"
      style={{ gridTemplateColumns: `minmax(8rem, 11rem) repeat(${count}, minmax(0, 1fr))` }}
    >
      <span className="text-gray-600 text-xs font-medium">{spec.label}</span>
      {spec.rendered.map((cell, i) => (
        <span
          key={i}
          className={cn(
            "text-center font-medium px-2 py-1 rounded-md tabular-nums",
            best === i && "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
            worst === i && "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
            best !== i && worst !== i && "text-gray-900",
          )}
        >
          {cell}
        </span>
      ))}
    </div>
  )
}

// Mobile card — same data, stacked per-stock.
function MobileStockCard({
  stock,
  rank,
  rowSpecs,
  index,
}: {
  stock: StockSummary
  rank: { best: Set<string>; worst: Set<string> }
  rowSpecs: RowSpec[]
  index: number
}) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-4 space-y-2">
      <div className="flex items-center justify-between mb-3 pb-3 border-b border-gray-100">
        <Link
          href={`/analysis/${stock.ticker}`}
          className="font-semibold text-gray-900 hover:text-blue-600 truncate"
        >
          {stock.company_name}
        </Link>
        <span className="text-xs font-mono text-gray-600 shrink-0 ml-2">
          {displayTicker(stock.ticker)}
        </span>
      </div>
      <p className="text-xs text-gray-500 -mt-2 mb-2">{stock.sector}</p>
      {rowSpecs.map((row) => {
        const cell = row.rendered[index]
        const label = row.label
        const isBest = rank.best.has(label)
        const isWorst = rank.worst.has(label)
        return (
          <div key={label} className="flex items-center justify-between text-sm py-1">
            <span className="text-xs text-gray-600">{label}</span>
            <span
              className={cn(
                "font-medium tabular-nums px-2 py-0.5 rounded-md",
                isBest && "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
                isWorst && "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
                !isBest && !isWorst && "text-gray-900",
              )}
            >
              {cell}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Verdict + score chips
// ---------------------------------------------------------------------------

function VerdictBadge({ verdict }: { verdict: string }) {
  const v = (verdict || "fairly_valued") as Verdict
  const colors = VERDICT_COLORS[v] || VERDICT_COLORS.fairly_valued
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full font-medium border px-2 py-0.5 text-xs",
        colors.bg,
        colors.text,
        colors.border,
      )}
    >
      {verdictDisplayLabel(v)}
    </span>
  )
}

function ScoreCell({ score, grade }: { score: number; grade: string }) {
  return (
    <span className="inline-flex items-baseline gap-1" style={{ color: SCORE_COLOR(score) }}>
      <span className="font-semibold">{score}</span>
      <span className="text-[10px] uppercase opacity-80">{grade}</span>
    </span>
  )
}

// ---------------------------------------------------------------------------
// Build all the row specs from N stock-summaries.
// ---------------------------------------------------------------------------

function buildRowSpecs(stocks: StockSummary[]): RowSpec[] {
  const n = stocks.length

  // Helpers to map values across the row.
  const map = <T,>(fn: (s: StockSummary) => T): T[] => stocks.map(fn)

  return [
    // ── Valuation block ─────────────────────────────────────────
    {
      label: "CMP",
      values: map((s) => s.current_price),
      rendered: map((s) => formatCurrency(s.current_price, s.currency, s.ticker)),
      noRank: true,
    },
    {
      label: "Fair Value",
      values: map((s) => s.fair_value),
      rendered: map((s) => formatCurrency(s.fair_value, s.currency, s.ticker)),
      noRank: true,
    },
    {
      label: "MoS",
      values: map((s) => s.mos),
      rendered: map((s) => (
        <span className={s.mos >= 0 ? "" : ""}>{formatPct(s.mos)}</span>
      )),
      higherIsBetter: true,
    },
    {
      label: "Verdict",
      values: new Array(n).fill(null),
      rendered: map((s) => <VerdictBadge verdict={s.verdict} />),
      noRank: true,
    },
    {
      label: "YieldIQ Score",
      values: map((s) => s.score),
      rendered: map((s) => <ScoreCell score={s.score} grade={s.grade} />),
      higherIsBetter: true,
    },
    {
      label: "Confidence",
      values: map((s) => s.confidence),
      rendered: map((s) => `${s.confidence}%`),
      higherIsBetter: true,
    },
    // ── Profile / size ──────────────────────────────────────────
    {
      label: "Sector",
      values: new Array(n).fill(null),
      rendered: map((s) => <span className="text-xs">{s.sector || "—"}</span>),
      noRank: true,
    },
    {
      label: "Mcap",
      values: map((s) => s.market_cap),
      rendered: map((s) => formatCurrency(s.market_cap, s.currency, s.ticker)),
      higherIsBetter: true,
    },
    {
      label: "EV/EBITDA",
      values: map((s) => s.ev_ebitda),
      rendered: map((s) =>
        s.ev_ebitda != null && Number.isFinite(s.ev_ebitda) ? `${s.ev_ebitda.toFixed(1)}x` : "—",
      ),
      higherIsBetter: false,
    },
    // ── Quality / returns ───────────────────────────────────────
    {
      label: "ROE",
      values: map((s) => s.roe),
      rendered: map((s) => formatPercentage(s.roe)),
      higherIsBetter: true,
    },
    {
      label: "ROCE",
      values: map((s) => s.roce),
      rendered: map((s) => formatPercentage(s.roce)),
      higherIsBetter: true,
    },
    {
      label: "Debt/Equity",
      values: map((s) => s.de_ratio),
      rendered: map((s) => (s.de_ratio != null ? s.de_ratio.toFixed(2) : "—")),
      higherIsBetter: false,
    },
    {
      label: "Revenue CAGR (3y)",
      values: map((s) => s.revenue_cagr_3y),
      rendered: map((s) => formatPercentage(s.revenue_cagr_3y)),
      higherIsBetter: true,
    },
    {
      label: "Piotroski",
      values: map((s) => s.piotroski),
      rendered: map((s) => `${s.piotroski}/9`),
      higherIsBetter: true,
    },
    {
      label: "Moat",
      values: new Array(n).fill(null),
      rendered: map((s) => <span className="text-xs">{s.moat || "—"}</span>),
      noRank: true,
    },
    {
      label: "WACC",
      values: map((s) => s.wacc),
      rendered: map((s) =>
        s.wacc != null && Number.isFinite(s.wacc) ? `${s.wacc.toFixed(1)}%` : "—",
      ),
      higherIsBetter: false,
    },
    // ── Scenarios ───────────────────────────────────────────────
    {
      label: "Bear case",
      values: map((s) => s.bear_case),
      rendered: map((s) => formatCurrency(s.bear_case, s.currency, s.ticker)),
      noRank: true,
    },
    {
      label: "Base case",
      values: map((s) => s.base_case),
      rendered: map((s) => formatCurrency(s.base_case, s.currency, s.ticker)),
      noRank: true,
    },
    {
      label: "Bull case",
      values: map((s) => s.bull_case),
      rendered: map((s) => formatCurrency(s.bull_case, s.currency, s.ticker)),
      noRank: true,
    },
  ]
}

// Section dividers — break the long table into named groups visually.
const SECTION_BOUNDS: { after: string; label: string }[] = [
  { after: "Confidence", label: "Profile & Quality" },
  { after: "WACC", label: "Scenarios (per-share)" },
]

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

function CompareContent() {
  const router = useRouter()
  const searchParams = useSearchParams()

  // Parse tickers from URL — accept canonical ?tickers= AND legacy ?stock1=&stock2=.
  const initialTickers = useMemo(() => {
    const t = parseTickersParam(searchParams.get("tickers"))
    if (t.length > 0) return t
    const s1 = searchParams.get("stock1")
    const s2 = searchParams.get("stock2")
    return [s1, s2].filter(Boolean).map((x) => x!.toUpperCase()).slice(0, MAX_STOCKS)
  }, [searchParams])

  const [tickers, setTickers] = useState<string[]>(initialTickers)

  // Sync URL whenever the ticker list changes.
  useEffect(() => {
    const qs = tickers.length > 0 ? `?tickers=${tickers.join(",")}` : ""
    router.replace(`/compare${qs}`, { scroll: false })
  }, [tickers, router])

  const addTicker = useCallback((t: string) => {
    setTickers((prev) => {
      const upper = t.toUpperCase()
      if (prev.includes(upper)) return prev
      if (prev.length >= MAX_STOCKS) return prev
      return [...prev, upper]
    })
  }, [])

  const removeTicker = useCallback((t: string) => {
    setTickers((prev) => prev.filter((x) => x !== t))
  }, [])

  // Parallel fetches — useQueries lets us request N tickers at once,
  // each cached independently in the React Query store.
  const summaryQueries = useQueries({
    queries: tickers.map((t) => ({
      queryKey: ["stock-summary", t],
      queryFn: () => getStockSummary(t),
      staleTime: 5 * 60 * 1000,
      retry: 1,
    })),
  })

  const isLoading = summaryQueries.some((q) => q.isLoading)
  const stocks = summaryQueries
    .map((q) => q.data)
    .filter((s): s is StockSummary => !!s)

  // Track which tickers failed to load so we can show a soft warning.
  const failedTickers = tickers.filter(
    (t, i) => !summaryQueries[i].isLoading && !summaryQueries[i].data,
  )

  // Sector-peer suggestions: pull peers of the FIRST ticker once we have
  // at least one stock loaded. Hide ones the user already added.
  const firstTicker = tickers[0]
  const { data: peersData } = useQuery({
    queryKey: ["public-peers", firstTicker],
    queryFn: () => (firstTicker ? getPublicPeers(firstTicker, 6) : Promise.resolve(null)),
    enabled: !!firstTicker,
    staleTime: 60 * 60 * 1000,
  })

  const peerSuggestions = useMemo(() => {
    if (!peersData?.peers) return []
    const have = new Set(tickers.map((t) => t.toUpperCase()))
    return peersData.peers
      .map((p) => ({
        ticker: (p.ticker || p.peer_ticker || "").toUpperCase(),
        name: p.company_name || p.peer_ticker || p.ticker || "",
      }))
      .filter((p) => p.ticker && !have.has(p.ticker))
      .slice(0, 4)
  }, [peersData, tickers])

  // Build the row specs from successfully-loaded stocks (in URL order).
  const orderedStocks = useMemo(() => {
    const map = new Map(stocks.map((s) => [s.ticker.toUpperCase(), s]))
    // The ticker the user typed may not match the canonical (e.g. RELIANCE
    // vs RELIANCE.NS). Try both.
    return tickers
      .map((t) => map.get(t) || map.get(`${t}.NS`) || map.get(`${t}.BO`))
      .filter((s): s is StockSummary => !!s)
  }, [stocks, tickers])

  const rowSpecs = useMemo(
    () => (orderedStocks.length >= 2 ? buildRowSpecs(orderedStocks) : []),
    [orderedStocks],
  )

  // Pre-compute best/worst per row so the mobile cards can highlight too.
  const mobileRanks = useMemo(() => {
    const ranks: { best: Set<string>; worst: Set<string> }[] = orderedStocks.map(
      () => ({ best: new Set<string>(), worst: new Set<string>() }),
    )
    for (const spec of rowSpecs) {
      if (spec.noRank) continue
      const { best, worst } = bestWorst(spec.values, spec.higherIsBetter ?? true)
      if (best != null) ranks[best].best.add(spec.label)
      if (worst != null) ranks[worst].worst.add(spec.label)
    }
    return ranks
  }, [orderedStocks, rowSpecs])

  const enoughStocks = orderedStocks.length >= MIN_STOCKS
  const excludedSet = useMemo(() => new Set(tickers), [tickers])

  return (
    <div className="max-w-2xl md:max-w-5xl lg:max-w-6xl mx-auto px-4 py-6 space-y-5 pb-20">
      <div className="text-center">
        <h1 className="text-lg font-bold text-gray-900 mb-1">Side-by-side Comparison</h1>
        <p className="text-xs text-gray-500">
          Pick {MIN_STOCKS}–{MAX_STOCKS} stocks. Best per metric is green, worst is red.
        </p>
      </div>

      {/* Ticker chips */}
      {tickers.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {tickers.map((t) => (
            <span
              key={t}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 border border-blue-200 rounded-full text-sm font-medium text-blue-800"
            >
              {displayTicker(t)}
              <button
                onClick={() => removeTicker(t)}
                aria-label={`Remove ${displayTicker(t)}`}
                className="text-blue-400 hover:text-blue-700 leading-none"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Add input */}
      <AddStockInput
        onSelect={addTicker}
        disabled={tickers.length >= MAX_STOCKS}
        excluded={excludedSet}
      />

      {/* Sector-peer suggestions */}
      {peerSuggestions.length > 0 && tickers.length < MAX_STOCKS && (
        <div className="bg-amber-50 border border-amber-100 rounded-xl px-3 py-2.5">
          <p className="text-xs text-amber-900 mb-2">
            <span className="font-semibold">Suggested peers</span> for{" "}
            {displayTicker(firstTicker)}
            {peersData?.sector_label ? ` (${peersData.sector_label})` : ""}:
          </p>
          <div className="flex flex-wrap gap-2">
            {peerSuggestions.map((p) => (
              <button
                key={p.ticker}
                onClick={() => addTicker(p.ticker)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white border border-amber-200 rounded-full text-xs font-medium text-amber-900 hover:bg-amber-100 hover:border-amber-300 transition"
              >
                <span>+</span>
                <span>{displayTicker(p.ticker)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {tickers.length > 0 && isLoading && (
        <div className="text-center py-12">
          <div className="inline-block h-6 w-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mb-3" />
          <p className="text-sm text-gray-500">Loading {tickers.length} {tickers.length === 1 ? "stock" : "stocks"}...</p>
        </div>
      )}

      {/* Failed tickers warning */}
      {failedTickers.length > 0 && (
        <div className="text-xs text-rose-700 bg-rose-50 border border-rose-100 rounded-lg px-3 py-2">
          Could not load: {failedTickers.map(displayTicker).join(", ")} (under review or unknown)
        </div>
      )}

      {/* Empty / underfilled prompts */}
      {!isLoading && tickers.length === 0 && (
        <div className="text-center py-12 px-4">
          <h2 className="text-base font-semibold text-gray-900 mb-1">Build a peer group</h2>
          <p className="text-sm text-gray-600 max-w-md mx-auto">
            Search above to add stocks. Try a sector trio like
            {" "}
            <button
              onClick={() => setTickers(["TCS", "INFY", "WIPRO"])}
              className="text-blue-600 hover:underline font-medium"
            >
              TCS / INFY / WIPRO
            </button>
            {" "}or{" "}
            <button
              onClick={() => setTickers(["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK"])}
              className="text-blue-600 hover:underline font-medium"
            >
              private banks
            </button>
            .
          </p>
        </div>
      )}

      {!isLoading && tickers.length === 1 && (
        <div className="text-center py-8 text-sm text-gray-600">
          Add at least one more stock to start comparing.
        </div>
      )}

      {/* Comparison table — desktop / tablet */}
      {enoughStocks && rowSpecs.length > 0 && (
        <>
          <div className="hidden sm:block bg-white rounded-2xl border border-gray-100 overflow-x-auto">
            {/* Header row */}
            <div
              className="grid items-center gap-2 px-3 py-3 border-b border-gray-100 bg-gray-50 sticky top-0 z-10"
              style={{
                gridTemplateColumns: `minmax(8rem, 11rem) repeat(${orderedStocks.length}, minmax(0, 1fr))`,
              }}
            >
              <span className="text-xs font-bold text-gray-600 uppercase tracking-widest">
                Metric
              </span>
              {orderedStocks.map((s) => (
                <div key={s.ticker} className="text-center min-w-0">
                  <Link
                    href={`/analysis/${s.ticker}`}
                    className="text-sm font-semibold text-gray-900 hover:text-blue-600 transition truncate block"
                    title={s.company_name}
                  >
                    {s.company_name}
                  </Link>
                  <p className="text-[11px] text-gray-600 font-mono">
                    {displayTicker(s.ticker)}
                  </p>
                </div>
              ))}
            </div>

            {/* Body rows w/ section headers */}
            <div className="divide-y divide-gray-50">
              {rowSpecs.map((spec, idx) => {
                const sectionAfter = SECTION_BOUNDS.find((b) => b.after === spec.label)
                return (
                  <div key={spec.label}>
                    <MetricRow spec={spec} count={orderedStocks.length} />
                    {sectionAfter && idx < rowSpecs.length - 1 && (
                      <div className="bg-gray-50 px-3 py-1.5 text-[10px] uppercase tracking-widest text-gray-600 font-semibold border-y border-gray-100">
                        {sectionAfter.label}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Mobile — stacked per-stock cards */}
          <div className="sm:hidden space-y-3">
            {orderedStocks.map((stock, i) => (
              <MobileStockCard
                key={stock.ticker}
                stock={stock}
                rank={mobileRanks[i]}
                rowSpecs={rowSpecs}
                index={i}
              />
            ))}
          </div>
        </>
      )}

      <p className="text-xs text-gray-600 text-center leading-relaxed px-4">
        All outputs are model estimates using publicly available data. Not investment advice.
      </p>
    </div>
  )
}

export default function ComparePage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-20 text-gray-600">
          Loading comparison...
        </div>
      }
    >
      <CompareContent />
    </Suspense>
  )
}
