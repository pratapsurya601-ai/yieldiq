"use client"
// TODO: swap to design tokens

import { useEffect, useRef, useState, useSyncExternalStore } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/store/authStore"
import { useSettingsStore } from "@/store/settingsStore"
import Link from "next/link"
import { ArrowRight, Play, History } from "lucide-react"
import MarketingTopNav from "@/components/marketing/MarketingTopNav"
import HomeSearchBar from "@/components/home/HomeSearchBar"
import TickerAvatar from "@/components/common/TickerAvatar"
import { priceLabel, getLaunchDiscount, tierById } from "@/config/pricing"

/* ── Scroll animation hook ───────────────────────────── */
function useInView(threshold = 0.15) {
  const ref = useRef<HTMLDivElement>(null)
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setInView(true); obs.disconnect() } },
      { threshold }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [threshold])
  return { ref, inView }
}

function FadeIn({ children, delay = 0, className = "" }: {
  children: React.ReactNode; delay?: number; className?: string
}) {
  const { ref, inView } = useInView(0.05)
  return (
    <div
      ref={ref}
      className={`${inView ? "animate-[fade-up_0.6s_ease-out_forwards]" : ""} ${className}`}
      style={{ transitionDelay: `${delay}ms`, animationDelay: `${delay}ms` }}
    >
      {children}
    </div>
  )
}

/* ── Nav now provided by the unified MarketingTopNav component ─────── */

/* ── Demo Card — rotates through real cached analyses ──
   Phase J-copy-1 (2026-05-26): the hardcoded FALLBACK_CARDS used to
   carry concrete prices (RELIANCE ₹2943 etc). When /api/v1/public/
   demo-cards 500s or is slow, first-time visitors saw stale prices
   that diverged from live quotes within weeks — destroying trust on
   the most important first-impression surface. New behaviour: empty
   fallback array means DemoCard returns null until the live endpoint
   answers. The hero copy still works without the card on mobile (it's
   `hidden lg:block` anyway), and on desktop the missing card simply
   reflows the hero to single-column for the < 200ms the fetch takes.
   This is strictly better than showing a wrong number.
*/
type DemoCardData = {
  display_ticker: string
  company_name: string
  sector?: string
  current_price?: number
  fair_value?: number
  mos?: number
  verdict?: string
  score?: number
  grade?: string
  moat?: string
  bear_case?: number
  base_case?: number
  bull_case?: number
}

const FALLBACK_CARDS: DemoCardData[] = []

// Module-level singleton so multiple <DemoCard /> instances (hero +
// how-it-works section) share one network round-trip, and so React
// StrictMode's double-mount doesn't double the fetch count. Without
// this, the landing page hits /api/v1/public/demo-cards 4 times per
// load (2 mounts x 2 instances), audit 2026-05-26 P1.
let _demoCardsPromise: Promise<DemoCardData[] | null> | null = null
function loadDemoCards(): Promise<DemoCardData[] | null> {
  if (_demoCardsPromise) return _demoCardsPromise
  _demoCardsPromise = fetch(`${process.env.NEXT_PUBLIC_API_URL || ""}/api/v1/public/demo-cards`)
    .then(r => r.ok ? r.json() : null)
    .then(data => (data && data.length >= 2 ? data as DemoCardData[] : null))
    .catch(() => null)
  return _demoCardsPromise
}

function DemoCard() {
  const [cards, setCards] = useState<DemoCardData[]>(FALLBACK_CARDS)
  const [idx, setIdx] = useState(0)
  const [fading, setFading] = useState(false)

  useEffect(() => {
    let cancelled = false
    loadDemoCards().then(data => {
      if (!cancelled && data) setCards(data)
    })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (cards.length <= 1) return
    const timer = setInterval(() => {
      setFading(true)
      setTimeout(() => {
        setIdx(prev => (prev + 1) % cards.length)
        setFading(false)
      }, 300)
    }, 5000)
    return () => clearInterval(timer)
  }, [cards.length])

  const c = cards[idx]
  if (!c) return null
  const score = c.score || 0
  const r = 58, circ = 2 * Math.PI * r
  const offset = circ * (1 - score / 100)
  const verdictText = c.verdict === "avoid" ? "high risk" : (c.verdict || "").replace("_", " ")
  const verdictColor = c.verdict === "undervalued" ? "bg-green-500/10 text-green-400"
    : c.verdict === "overvalued" ? "bg-red-500/10 text-red-400"
    : "bg-blue-500/10 text-blue-400"
  const fmt = (n: number | undefined) => n ? n.toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "\u2014"
  const mosSign = (c.mos || 0) >= 0 ? "+" : ""

  // J-copy-2 (audit item 12): outer wrapper centers the card and
  // constrains it to the viewport on mobile (where DemoCard is now
  // rendered in the hero column above the fold). The inner card keeps
  // its 320px target width on lg+ but yields to the column on phones.
  return (
    <div className="relative mx-auto max-w-[320px]" style={{ animation: "float 6s ease-in-out infinite" }}>
      <div className="absolute -inset-6 bg-blue-500/5 rounded-3xl blur-2xl" />
      <div className={`relative bg-[#0F172A] border border-white/10 rounded-2xl p-6 shadow-2xl w-full lg:w-[320px] transition-opacity duration-300 ${fading ? "opacity-0" : "opacity-100"}`}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-white font-bold text-lg">{c.display_ticker}</span>
              <span className="text-[10px] bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded font-medium">NSE</span>
            </div>
            <div className="text-caption text-xs mt-0.5">{c.company_name}</div>
          </div>
          <div className="text-right">
            <div className="text-white font-bold text-lg font-mono">&#8377;{fmt(c.current_price)}</div>
          </div>
        </div>
        <div className="flex items-center gap-4 mb-4">
          <div className="relative w-[130px] h-[130px] flex-shrink-0">
            <svg viewBox="0 0 140 140" className="w-full h-full -rotate-90">
              <circle cx="70" cy="70" r={r} fill="none" stroke="#1E293B" strokeWidth="8" />
              <circle cx="70" cy="70" r={r} fill="none" stroke="url(#ring-grad)" strokeWidth="8"
                strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={offset}
                style={{ transition: "stroke-dashoffset 0.8s ease-out" }} />
              <defs>
                <linearGradient id="ring-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#3B82F6" />
                  <stop offset="100%" stopColor="#06B6D4" />
                </linearGradient>
              </defs>
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-3xl font-black text-white">{score}</span>
              <span className="text-[10px] text-caption font-semibold tracking-wider uppercase">{c.grade || "\u2014"}</span>
            </div>
          </div>
          <div className="space-y-2.5 flex-1">
            <div className={`text-xs font-bold px-3 py-1.5 rounded-full text-center capitalize ${verdictColor}`}>
              {verdictText}
            </div>
            <div>
              <div className="text-caption text-[10px] uppercase tracking-wider">Fair Value</div>
              <div className="text-white font-bold font-mono">&#8377;{fmt(c.fair_value)}</div>
            </div>
            <div>
              <div className="text-caption text-[10px] uppercase tracking-wider">Discount to FV</div>
              <div className={`font-bold font-mono ${(c.mos || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>{mosSign}{(c.mos || 0).toFixed(1)}%</div>
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          {[
            { label: "Bear", val: c.bear_case, color: "bg-red-500/20 text-red-400" },
            { label: "Base", val: c.base_case || c.fair_value, color: "bg-blue-500/20 text-blue-400" },
            { label: "Bull", val: c.bull_case, color: "bg-green-500/20 text-green-400" },
          ].map(s => (
            <div key={s.label} className={`flex-1 rounded-lg px-2 py-1.5 text-center text-[10px] ${s.color}`}>
              <div className="font-medium">{s.label}</div>
              <div className="font-bold font-mono">&#8377;{fmt(s.val)}</div>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-1.5 mt-3 justify-center">
          <span className="w-1.5 h-1.5 bg-green-400 rounded-full" />
          <span className="text-[10px] text-caption">Refreshed each evening</span>
        </div>
      </div>
    </div>
  )
}

/* ── Recently Viewed chip row ─────────────────────────
   Anon-friendly above-the-fold re-engagement hook (audit
   2026-06-07 — AlphaSpread parity P0). Reads identity-only
   from the same `yq:recent-views` localStorage key written by
   AnalysisBody.tsx, so a returning anon visitor sees the
   tickers they previously analysed without any backend round-
   trip. Falls back to a curated set of well-known Indian
   blue-chips for first-time visitors so the row is never
   empty (an empty row would look broken under the search bar).
   Logos resolve via TickerAvatar's existing
   Brandfetch→favicon→monogram chain. */
const RECENTLY_VIEWED_FALLBACK = [
  "RELIANCE.NS",
  "HDFCBANK.NS",
  "TCS.NS",
  "INFY.NS",
  "ITC.NS",
  "TATAMOTORS.NS",
]

// Cached snapshot key — `useSyncExternalStore` requires `getSnapshot`
// to return a stable reference between calls when nothing changed
// (otherwise React will infinite-loop). We re-read localStorage once
// and memoize until a `storage` event tells us another tab wrote.
let _recentsCache: string | null = null
let _recentsValue: { tickers: string[]; isFallback: boolean } = {
  tickers: RECENTLY_VIEWED_FALLBACK,
  isFallback: true,
}

function computeRecentsSnapshot(): { tickers: string[]; isFallback: boolean } {
  if (typeof window === "undefined") {
    return { tickers: RECENTLY_VIEWED_FALLBACK, isFallback: true }
  }
  let raw: string | null = null
  try {
    raw = window.localStorage.getItem("yq:recent-views")
  } catch {
    raw = null
  }
  if (raw === _recentsCache) return _recentsValue
  _recentsCache = raw
  try {
    const parsed = raw ? JSON.parse(raw) : []
    if (Array.isArray(parsed)) {
      const next = parsed
        .filter((e: { ticker?: unknown }) => e && typeof e.ticker === "string")
        .map((e: { ticker: string }) => e.ticker)
        .slice(0, 6)
      if (next.length > 0) {
        _recentsValue = { tickers: next, isFallback: false }
        return _recentsValue
      }
    }
  } catch {
    /* fall through */
  }
  _recentsValue = { tickers: RECENTLY_VIEWED_FALLBACK, isFallback: true }
  return _recentsValue
}

function subscribeRecents(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {}
  const handler = (e: StorageEvent) => {
    if (e.key === "yq:recent-views") onChange()
  }
  window.addEventListener("storage", handler)
  return () => window.removeEventListener("storage", handler)
}

function serverRecentsSnapshot(): { tickers: string[]; isFallback: boolean } {
  return { tickers: RECENTLY_VIEWED_FALLBACK, isFallback: true }
}

function RecentlyViewedChips() {
  // `useSyncExternalStore` is the project's preferred pattern for
  // SSR-safe, lint-clean client-only data (mirrors
  // components/anim/useReducedMotion.ts). SSR + first client paint
  // see the fallback; subsequent renders see the localStorage value
  // if any, all without violating react-hooks/set-state-in-effect.
  const { tickers, isFallback } = useSyncExternalStore(
    subscribeRecents,
    computeRecentsSnapshot,
    serverRecentsSnapshot,
  )

  return (
    <div className="flex flex-wrap items-center gap-2 justify-center lg:justify-start">
      <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
        <History className="w-3.5 h-3.5" />
        {isFallback ? "Popular:" : "Recently viewed:"}
      </span>
      {tickers.map(t => {
        const display = t.replace(/\.(NS|BO)$/i, "")
        return (
          <Link
            key={t}
            href={`/analysis/${display}`}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 transition text-xs font-medium text-gray-200"
          >
            <TickerAvatar ticker={t} size="sm" />
            <span className="font-mono">{display}</span>
          </Link>
        )
      })}
    </div>
  )
}

/* ── Pricing teaser data ──────────────────────────────── */
// Prices are pulled from @/config/pricing so the landing teaser stays
// in sync with the canonical /pricing page and any future config
// changes (incl. the LAUNCH_DISCOUNT toggle) ripple through here too.
type PricingTeaser = {
  id: "free" | "analyst" | "pro"
  name: string
  price: string
  period: string
  tagline: string
  highlight?: boolean
}
// 2026-06-07: tiers flagged `hidden: true` in @/config/pricing are
// filtered out of `visiblePricingPlans` below before render \u2014 Pro is
// hidden for the simplification launch but remains in this array so
// re-enabling is a single config flip. Filter happens at render time
// (not at array-definition time) so the source-of-truth stays in
// pricing.ts.
const pricingPlans: PricingTeaser[] = [
  { id: "free",    name: "Free",    price: "\u20B90",                          period: "/forever", tagline: "5 deep analyses per day. All core features." },
  { id: "analyst", name: "Analyst", price: priceLabel("analyst", "monthly"),   period: "/month",   tagline: "Unlimited analyses, Portfolio Prism, AI summaries.", highlight: true },
  { id: "pro",     name: "Pro",     price: priceLabel("pro", "monthly"),       period: "/month",   tagline: "CSV/PDF export, API access, priority compute." },
]
const visiblePricingPlans: PricingTeaser[] = pricingPlans.filter(
  (p) => !tierById(p.id)?.hidden
)

/* ═════════════════════════════════════════════════════════
   Landing content — 5 sections, ~3500px target
   ═════════════════════════════════════════════════════════ */
function LandingContent() {
  return (
    <div className="bg-bg dark:bg-surface text-ink overflow-x-hidden">
      <MarketingTopNav variant="dark" />

      {/* ── 1. Hero ────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B]">
        <div className="absolute top-10 left-1/4 w-[500px] h-[500px] bg-blue-600/8 rounded-full blur-3xl" />
        <div className="absolute bottom-10 right-1/4 w-[400px] h-[400px] bg-cyan-500/8 rounded-full blur-3xl" />

        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-16 md:py-24 relative z-10">
          <div className="flex flex-col lg:flex-row items-center gap-12 lg:gap-16">
            <div className="flex-1 text-center lg:text-left">
              {/* Headline reshaped 2026-06-07 (AlphaSpread audit P0):
                  question-form framing so the hero reads as "type your
                  ticker, get an answer" rather than a product tagline.
                  SEBI-safe — a question about analytical lookup. */}
              <h1 className="font-display text-4xl md:text-5xl lg:text-6xl font-black text-white leading-[1.1] mb-6 tracking-tight">
                Which Indian stock
                <br />
                do you want to
                {" "}
                <span className="bg-gradient-to-r from-blue-400 via-cyan-300 to-blue-500 bg-clip-text text-transparent">
                  value?
                </span>
              </h1>

              <p className="text-gray-300 text-lg md:text-xl max-w-xl mx-auto lg:mx-0 mb-6 leading-relaxed">
                A transparent DCF for 2,300+ NSE &amp; BSE tickers &mdash; every assumption editable, every number linked to its source filing.
              </p>

              {/* Hero search — primary action above the fold (audit P0).
                  HomeSearchBar uses light surface tokens by design; we
                  wrap it in a white-on-dark frame so the input still
                  pops against the dark gradient hero without forking
                  the component. */}
              <div className="mb-4 max-w-xl mx-auto lg:mx-0">
                <div className="rounded-2xl bg-white/95 dark:bg-surface/95 p-1.5 shadow-xl shadow-blue-500/10 ring-1 ring-white/10">
                  <HomeSearchBar />
                </div>
                <p className="mt-2 text-[11px] text-caption text-center lg:text-left">
                  Press Enter to analyse &middot; no sign-up to browse
                </p>
              </div>

              {/* Recently viewed / popular chips — re-engagement hook. */}
              <div className="mb-6">
                <RecentlyViewedChips />
              </div>

              <div className="flex flex-col sm:flex-row gap-3 justify-center lg:justify-start mb-6">
                <Link href="/discover"
                  className="bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-bold px-6 py-3 rounded-xl text-base hover:opacity-90 hover:-translate-y-0.5 transition-all shadow-lg shadow-blue-500/25 inline-flex items-center justify-center gap-2">
                  Browse all stocks <ArrowRight className="w-4 h-4" />
                </Link>
                <Link href="#how-it-works"
                  className="inline-flex items-center justify-center gap-2 border border-white/10 text-white font-semibold px-5 py-3 rounded-xl text-base hover:bg-white/5 transition">
                  <Play className="w-4 h-4" /> See how it works
                </Link>
              </div>

              {/* Stats strip */}
              <p className="text-caption text-sm">
                <span className="text-white font-semibold">2,300+ NSE &amp; BSE stocks</span>
                <span className="mx-2 text-caption">&middot;</span>
                <span className="text-white font-semibold">Source-linked</span>
                <span className="mx-2 text-caption">&middot;</span>
                <span className="text-white font-semibold">Editable assumptions</span>
              </p>

              <p className="mt-4 text-caption text-xs">
                <Link href="/methodology" className="underline hover:text-gray-300 transition">
                  How the score is computed &rarr;
                </Link>
              </p>
            </div>

            {/* J-copy-2 (audit item 12): DemoCard is now visible on
                mobile as well as desktop. Previously `hidden lg:block`
                hid the most persuasive single element from ~60% of
                Indian retail visitors who land on a phone. The card
                self-rotates and renders compactly on narrow widths. */}
            <div className="flex-shrink-0 w-full lg:w-auto">
              <DemoCard />
            </div>
          </div>
        </div>
      </section>

      {/* ── 2. Here's what you'll see (kept from a4426ce) ── */}
      <section id="how-it-works" className="bg-bg dark:bg-surface py-20 border-b border-gray-100">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <div className="text-center mb-12">
              <div className="inline-flex items-center gap-2 bg-green-50 border border-green-200 rounded-full px-3 py-1 mb-4">
                <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
                <span className="text-[10px] font-bold text-green-700 tracking-[0.2em] uppercase">
                  No sign-up to browse
                </span>
              </div>
              <h2 className="font-display text-3xl sm:text-4xl font-black text-ink mb-3">
                Here&rsquo;s what you&rsquo;ll see
              </h2>
              <p className="text-caption text-base max-w-2xl mx-auto">
                Every Indian stock on YieldIQ is analysed through this same lens &mdash;
                live prices, 3-scenario DCF, quality scores, and plain-English AI
                commentary. This is a real card, rotating through real tickers.
              </p>
              <p className="text-caption text-xs mt-3 max-w-2xl mx-auto">
                Browse and analyse any stock without signing up. A free account
                (5 deep analyses per day) unlocks watchlists, portfolios, and saved screens.
              </p>
            </div>
          </FadeIn>

          <div className="grid lg:grid-cols-2 gap-10 lg:gap-16 items-center">
            <FadeIn>
              <div className="flex justify-center">
                <DemoCard />
              </div>
            </FadeIn>
            <FadeIn>
              <div className="space-y-4">
                {[
                  { num: "01", title: "Fair value from a 3-scenario DCF", body: "Bear / base / bull cases with an explicit weighted average \u2014 no single-point estimate hiding the uncertainty." },
                  { num: "02", title: "Margin of safety vs. today\u2019s price", body: "Color-coded, percent-based. You see immediately whether the stock trades below, near, or well above fair value at the current quote." },
                  { num: "03", title: "YieldIQ score (0\u2013100) + letter grade", body: "Blends valuation, quality, moat, and safety into one number you can compare across sectors." },
                  { num: "04", title: "Moat & Piotroski on every stock", body: "Wide / Narrow / None moat classification plus the 9-point Piotroski F-Score \u2014 no manual digging." },
                  { num: "05", title: "AI summary in plain English", body: "A 2-sentence take on what actually matters for this business, generated fresh from the latest financials." },
                ].map(item => (
                  <div key={item.num} className="flex gap-4">
                    <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center text-white font-black text-xs tracking-wider">
                      {item.num}
                    </div>
                    <div>
                      <h3 className="font-bold text-ink text-base mb-1">{item.title}</h3>
                      <p className="text-caption text-sm leading-relaxed">{item.body}</p>
                    </div>
                  </div>
                ))}
              </div>
            </FadeIn>
          </div>
        </div>
      </section>

      {/* ── 3. Why this is different ────────────────────── */}
      <section className="py-20 bg-bg dark:bg-surface border-b border-gray-100">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <h2 className="font-display text-3xl md:text-4xl font-black text-ink text-center mb-3">
              Why this is different
            </h2>
            <p className="text-caption text-base text-center max-w-2xl mx-auto mb-12">
              Most valuation tools copy US templates and bolt on Indian tickers. YieldIQ is built the other way around.
            </p>
          </FadeIn>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              {
                icon: "\u{1F517}",
                title: "Source-linked",
                body: "Every number clicks through to the filing it came from \u2014 annual report, quarterly filing, or RBI release. No black boxes.",
              },
              {
                icon: "\u270F\uFE0F",
                title: "Assumptions-editable",
                body: "Don\u2019t trust our WACC, growth, or margin inputs? Change them and re-run the DCF yourself. This is a model, not a verdict.",
              },
              {
                icon: "\u{1F4D0}",
                title: "Descriptive-only",
                body: "No registered-advisor trade calls. No tips, no picks. A valuation layer you apply your own judgement to.",
              },
              {
                icon: "\u{1F4CA}",
                title: "Indian risk-free rate",
                body: "WACC is anchored to the 10-year G-Sec, refreshed from RBI data \u2014 not the US treasury. That changes fair value materially.",
              },
              {
                icon: "\u{1F1EE}\u{1F1F3}",
                title: "No borrowed US assumptions",
                body: "Equity-risk premium, terminal growth and tax rates are calibrated to Indian markets, not ported from a Damodaran template.",
              },
              {
                icon: "\u{1F3E6}",
                title: "Sector-specific models",
                body: "Banks and NBFCs use P/B with residual-income logic. FMCG uses stable-growth DCF. One engine per business type \u2014 not one-size-fits-all.",
              },
            ].map((f) => (
              <div key={f.title} className="bg-bg dark:bg-surface rounded-2xl p-6 border border-gray-100">
                <div className="text-2xl mb-3">{f.icon}</div>
                <h3 className="font-bold text-ink text-base mb-2">{f.title}</h3>
                <p className="text-caption text-sm leading-relaxed">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 4. Pricing teaser ───────────────────────────── */}
      <section className="py-16 bg-bg dark:bg-surface border-b border-gray-100">
        <div className="max-w-5xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <h2 className="font-display text-3xl md:text-4xl font-black text-ink text-center mb-8">
              Pricing
            </h2>
          </FadeIn>
          {/* 2026-06-07: grid cols sized to `visiblePricingPlans.length`
              so the layout stays balanced when a tier is hidden. With
              Pro hidden we render 2 cards (Free + Analyst); when Pro
              is re-exposed the grid grows back to 3. Capped at md:cols-3. */}
          <div
            className={
              visiblePricingPlans.length >= 3
                ? "grid md:grid-cols-3 gap-4 max-w-3xl mx-auto"
                : "grid md:grid-cols-2 gap-4 max-w-2xl mx-auto"
            }
          >
            {visiblePricingPlans.map((p) => {
              // Launch-pricing strikethrough + badge applies to the paid
              // monthly tiers (analyst, pro). Returns null for "free".
              const launch = p.id === "free" ? null : getLaunchDiscount(p.id, "monthly")
              return (
              <div
                key={p.name}
                className={`rounded-2xl p-6 border ${p.highlight ? "border-blue-500 ring-1 ring-blue-500/20 bg-white" : "border-gray-100 bg-white"}`}
              >
                <p className="text-sm font-bold text-caption uppercase tracking-wider">
                  {p.name}
                </p>
                {launch && (
                  <div className="flex items-center gap-2 mt-2">
                    <span
                      data-testid={`landing-launch-strikethrough-${p.id}`}
                      className="line-through text-sm font-semibold text-caption"
                    >
                      ₹{launch.originalPrice.toLocaleString("en-IN")}
                    </span>
                    <span
                      data-testid={`landing-launch-badge-${p.id}`}
                      className="bg-orange-100 text-orange-800 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
                    >
                      {launch.percentOff}% off — Launch
                    </span>
                  </div>
                )}
                <p className="mt-2">
                  <span className="font-display text-3xl font-black text-ink font-mono">{p.price}</span>
                  <span className="text-caption text-sm">{p.period}</span>
                </p>
                {launch && (
                  <p
                    data-testid={`landing-launch-savings-${p.id}`}
                    className="text-[11px] font-semibold text-orange-700 mt-1"
                  >
                    Save ₹{launch.savings.toLocaleString("en-IN")}/mo during launch
                  </p>
                )}
                <p className="text-caption text-sm mt-3 leading-relaxed">{p.tagline}</p>
              </div>
              )
            })}
          </div>
          <div className="text-center mt-6">
            <Link href="/pricing" className="text-blue-600 font-semibold text-sm inline-flex items-center gap-1">
              See full comparison <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* ── 5. Final CTA + trust + footer ───────────────── */}
      <section className="relative overflow-hidden bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-20">
        <div className="absolute top-10 left-1/3 w-[400px] h-[400px] bg-blue-600/8 rounded-full blur-3xl" />
        <div className="max-w-4xl mx-auto px-4 text-center relative z-10">
          <h2 className="font-display text-3xl md:text-4xl font-black text-white leading-tight mb-4">
            Start with the stock you own.
            <br />You&rsquo;ll see what we mean.
          </h2>
          <Link
            href="/search"
            className="inline-flex items-center gap-2 bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-bold px-10 py-4 rounded-xl text-lg hover:opacity-90 transition shadow-lg shadow-blue-500/25"
          >
            Analyse your first stock free <ArrowRight className="w-5 h-5" />
          </Link>

          {/* Trust bar */}
          <div className="mt-8 flex items-center justify-center gap-3 flex-wrap text-caption text-xs">
            <span className="text-caption">Data from</span>
            {["NSE", "BSE", "RBI"].map((s, i) => (
              <span key={s} className="inline-flex items-center gap-3">
                {i > 0 && <span className="text-ink">&bull;</span>}
                <span className="font-mono tracking-wider text-caption font-medium">{s}</span>
              </span>
            ))}
          </div>

          {/* SEBI disclaimer — exact text, do not edit */}
          <p className="mt-6 text-caption text-xs max-w-xl mx-auto leading-relaxed">
            YieldIQ is not registered with SEBI as an investment adviser. All outputs are model estimates using publicly available data. Not investment advice.
          </p>

          <p className="mt-6 text-caption text-xs">&copy; 2026 YieldIQ</p>
        </div>
      </section>
    </div>
  )
}

/* ═════════════════════════════════════════════════════════ */
// 2026-06-04 (PR-2): the public-facing root route lives in app/page.tsx
// as a server component now (so it can export `metadata` for the
// canonical URL and SSR-emit landing JSON-LD). This file is the client
// half — auth redirect + interactive landing content — mounted from
// that server page.
export default function LandingClient() {
  const router = useRouter()
  const { token } = useAuthStore()
  const { onboardingComplete } = useSettingsStore()

  useEffect(() => {
    if (token) {
      if (!onboardingComplete) {
        router.replace("/onboarding")
      } else {
        router.replace("/home")
      }
    }
  }, [token, onboardingComplete, router])

  if (token) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="text-2xl font-bold text-ink mb-2">YieldIQ</div>
          <div className="text-sm text-caption">Loading...</div>
        </div>
      </div>
    )
  }

  return <LandingContent />
}
