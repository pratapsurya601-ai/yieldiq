"use client"
// Task #193 — always-visible search on the logged-in home.
// Lightweight wrapper around /tickers.json + Fuse, mirroring the index
// pattern from /search/page.tsx. We deliberately keep the surface tiny:
//  - Single prominent input.
//  - Up to 5 inline suggestions on focus/typing.
//  - Enter on a highlighted suggestion → /analysis/{ticker}.
//  - Enter on free text:
//      * if it normalises to a valid NSE-style ticker → /analysis/{ticker}
//      * else → /search (the dedicated page; richer affordances live there).
// We don't reproduce the full /search UX here — that's by design. The home
// bar exists so users never feel "where do I type a name?", not to replace
// the search page.
import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import Fuse from "fuse.js"
import type { IFuseOptions } from "fuse.js"

interface TickerIndexEntry {
  ticker: string
  display_ticker: string
  company_name: string
  type: string
  keywords?: string[]
}

interface SearchResult {
  ticker: string
  name: string
  displayTicker: string
}

const FUSE_OPTIONS: IFuseOptions<TickerIndexEntry> = {
  keys: [
    { name: "display_ticker", weight: 0.5 },
    { name: "company_name", weight: 0.3 },
    { name: "ticker", weight: 0.15 },
    { name: "keywords", weight: 0.05 },
  ],
  threshold: 0.4,
  ignoreLocation: true,
  minMatchCharLength: 2,
  includeScore: false,
}

// Module-level singleton — shared with /search/page.tsx's identical pattern
// in spirit. Keeping a separate cache here avoids a cross-import dependency
// on a page file (Next.js dislikes that).
let _cached: { fuse: Fuse<TickerIndexEntry> } | null = null
let _loader: Promise<Fuse<TickerIndexEntry> | null> | null = null

async function loadIndex(): Promise<Fuse<TickerIndexEntry> | null> {
  if (_cached) return _cached.fuse
  if (_loader) return _loader
  _loader = (async () => {
    try {
      const res = await fetch("/tickers.json", { cache: "force-cache" })
      if (!res.ok) return null
      const body = (await res.json()) as { tickers?: TickerIndexEntry[] }
      const rows = body.tickers || []
      const fuse = new Fuse(rows, FUSE_OPTIONS)
      _cached = { fuse }
      return fuse
    } catch {
      return null
    } finally {
      _loader = null
    }
  })()
  return _loader
}

function isValidTicker(t: string): boolean {
  return /^[A-Z0-9&\-]{1,20}(\.NS|\.BO)?$/.test(t)
}

export default function HomeSearchBar() {
  const router = useRouter()
  const [query, setQuery] = useState("")
  const [suggestions, setSuggestions] = useState<SearchResult[]>([])
  const [open, setOpen] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState(-1)
  const [ready, setReady] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const listboxId = "home-search-suggestions"

  useEffect(() => {
    loadIndex().then(fuse => {
      if (fuse) setReady(true)
    })
  }, [])

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [])

  const runSearch = useCallback((q: string) => {
    if (q.length < 2 || !_cached) {
      setSuggestions([])
      return
    }
    const hits = _cached.fuse.search(q).slice(0, 5)
    setSuggestions(
      hits.map(h => ({
        ticker: h.item.ticker,
        name: h.item.company_name,
        displayTicker: h.item.display_ticker,
      })),
    )
    setHighlightIdx(-1)
  }, [])

  useEffect(() => {
    if (ready && query.length >= 2) runSearch(query)
  }, [ready, query, runSearch])

  const goToTicker = useCallback(
    (ticker: string) => {
      setOpen(false)
      setQuery("")
      router.push(`/analysis/${ticker}`)
    },
    [router],
  )

  const onSubmit = useCallback(() => {
    const trimmed = query.trim()
    if (!trimmed) return
    // Prefer highlighted suggestion if any
    if (highlightIdx >= 0 && suggestions[highlightIdx]) {
      goToTicker(suggestions[highlightIdx].ticker)
      return
    }
    // Otherwise try first suggestion if it's an obvious match (case-insensitive
    // ticker or display_ticker equality)
    const upper = trimmed.toUpperCase()
    const exact = suggestions.find(
      s =>
        s.displayTicker.toUpperCase() === upper ||
        s.ticker.toUpperCase() === upper ||
        s.ticker.toUpperCase() === `${upper}.NS`,
    )
    if (exact) {
      goToTicker(exact.ticker)
      return
    }
    // Free-form ticker → /analysis if valid format
    let t = upper
    if (!t.includes(".")) t = `${t}.NS`
    if (isValidTicker(t) && suggestions.length === 0) {
      goToTicker(t)
      return
    }
    // Fall through to the dedicated /search page
    setOpen(false)
    router.push(`/search?q=${encodeURIComponent(trimmed)}`)
  }, [query, suggestions, highlightIdx, goToTicker, router])

  return (
    <div ref={wrapRef} className="relative">
      <div className="relative">
        <svg
          className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-caption pointer-events-none"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
          />
        </svg>
        <input
          type="text"
          value={query}
          placeholder="Search any stock, sector, or ticker..."
          aria-label="Search stocks"
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded={open && suggestions.length > 0}
          role="combobox"
          autoComplete="off"
          data-testid="home-search-input"
          onFocus={() => setOpen(true)}
          onChange={e => {
            setQuery(e.target.value)
            setOpen(true)
            runSearch(e.target.value)
          }}
          onKeyDown={e => {
            if (e.key === "ArrowDown" && suggestions.length > 0) {
              e.preventDefault()
              setOpen(true)
              setHighlightIdx(i => Math.min(i + 1, suggestions.length - 1))
            } else if (e.key === "ArrowUp" && suggestions.length > 0) {
              e.preventDefault()
              setHighlightIdx(i => Math.max(i - 1, 0))
            } else if (e.key === "Enter") {
              e.preventDefault()
              onSubmit()
            } else if (e.key === "Escape") {
              setOpen(false)
              setHighlightIdx(-1)
            }
          }}
          className="w-full h-11 pl-11 pr-4 rounded-xl border border-border bg-surface text-sm text-ink placeholder:text-caption focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand transition"
        />
      </div>
      {open && suggestions.length > 0 && (
        <ul
          id={listboxId}
          role="listbox"
          className="absolute left-0 right-0 top-full mt-1 z-40 bg-surface border border-border rounded-xl shadow-lg overflow-hidden max-h-80 overflow-y-auto"
          data-testid="home-search-suggestions"
        >
          {suggestions.map((s, idx) => (
            <li key={s.ticker}>
              <button
                type="button"
                id={`home-search-option-${s.ticker}`}
                role="option"
                aria-selected={idx === highlightIdx}
                onMouseEnter={() => setHighlightIdx(idx)}
                onClick={() => goToTicker(s.ticker)}
                className={`w-full text-left px-4 py-2.5 min-h-[44px] flex items-center justify-between gap-3 transition ${
                  idx === highlightIdx ? "bg-brand/10" : "hover:bg-brand/5"
                }`}
              >
                <span className="flex flex-col min-w-0">
                  <span className="text-sm font-semibold text-ink truncate">
                    {s.displayTicker}
                  </span>
                  <span className="text-xs text-body truncate">{s.name}</span>
                </span>
                <span className="text-caption text-xs" aria-hidden="true">
                  &rsaquo;
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
