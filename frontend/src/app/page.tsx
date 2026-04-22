"use client"
// TODO: swap to design tokens

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/store/authStore"
import { useSettingsStore } from "@/store/settingsStore"
import Link from "next/link"
import { ArrowRight, Play } from "lucide-react"

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

/* ── Nav ─────────────────────────────────────────────── */
function MarketingNav() {
  const [open, setOpen] = useState(false)
  return (
    <nav className="sticky top-0 z-50 bg-[#080E1A]/80 backdrop-blur-xl border-b border-white/5">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <img src="/logo-new.svg" alt="YieldIQ" className="w-8 h-8 rounded-lg" />
          <span className="text-white font-bold text-lg tracking-tight">YieldIQ</span>
        </Link>
        <div className="hidden md:flex items-center gap-8 text-sm">
          <Link href="/features" className="text-gray-400 hover:text-white transition">Features</Link>
          <Link href="/pricing" className="text-gray-400 hover:text-white transition">Pricing</Link>
          <Link href="/auth/login" className="text-gray-400 hover:text-white transition">Sign in</Link>
          <Link href="/auth/signup" className="bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-semibold px-5 py-2 rounded-lg hover:opacity-90 transition shadow-lg shadow-blue-500/20">
            Start Free &rarr;
          </Link>
        </div>
        <button onClick={() => setOpen(!open)} className="md:hidden text-white" aria-label="Menu">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      </div>
      {open && (
        <div className="md:hidden px-4 pb-4 space-y-3 bg-[#080E1A]/95 backdrop-blur-xl">
          <Link href="/features" className="block text-gray-400 text-sm py-1">Features</Link>
          <Link href="/pricing" className="block text-gray-400 text-sm py-1">Pricing</Link>
          <Link href="/auth/login" className="block text-gray-400 text-sm py-1">Sign in</Link>
          <Link href="/auth/signup" className="block bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-semibold px-5 py-2 rounded-lg text-center text-sm">
            Start Free &rarr;
          </Link>
        </div>
      )}
      <div className="h-px bg-gradient-to-r from-transparent via-blue-500/40 to-transparent" />
    </nav>
  )
}

/* ── Demo Card — rotates through real cached analyses ── */
const FALLBACK_CARDS = [
  { display_ticker: "RELIANCE", company_name: "Reliance Industries", sector: "Oil & Gas", current_price: 2943, fair_value: 3480, mos: 18.2, verdict: "undervalued", score: 78, grade: "B", moat: "Wide", bear_case: 2810, base_case: 3480, bull_case: 4120 },
  { display_ticker: "ITC", company_name: "ITC Limited", sector: "FMCG", current_price: 302, fair_value: 458, mos: 51.8, verdict: "undervalued", score: 80, grade: "A", moat: "Wide", bear_case: 380, base_case: 458, bull_case: 540 },
  { display_ticker: "HDFCBANK", company_name: "HDFC Bank", sector: "Banking", current_price: 1642, fair_value: 1890, mos: 15.1, verdict: "undervalued", score: 74, grade: "B", moat: "Wide", bear_case: 1590, base_case: 1890, bull_case: 2180 },
  { display_ticker: "TCS", company_name: "Tata Consultancy", sector: "IT Services", current_price: 3650, fair_value: 3580, mos: -2.0, verdict: "fairly_valued", score: 72, grade: "B", moat: "Wide", bear_case: 2980, base_case: 3580, bull_case: 4200 },
]

function DemoCard() {
  const [cards, setCards] = useState(FALLBACK_CARDS)
  const [idx, setIdx] = useState(0)
  const [fading, setFading] = useState(false)

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL || ""}/api/v1/public/demo-cards`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data && data.length >= 2) setCards(data) })
      .catch(() => {})
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
  const fmt = (n: number) => n ? n.toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "\u2014"
  const mosSign = (c.mos || 0) >= 0 ? "+" : ""

  return (
    <div className="relative" style={{ animation: "float 6s ease-in-out infinite" }}>
      <div className="absolute -inset-6 bg-blue-500/5 rounded-3xl blur-2xl" />
      <div className={`relative bg-[#0F172A] border border-white/10 rounded-2xl p-6 shadow-2xl w-[320px] transition-opacity duration-300 ${fading ? "opacity-0" : "opacity-100"}`}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-white font-bold text-lg">{c.display_ticker}</span>
              <span className="text-[10px] bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded font-medium">NSE</span>
            </div>
            <div className="text-gray-500 text-xs mt-0.5">{c.company_name}</div>
          </div>
          <div className="text-right">
            <div className="text-white font-bold text-lg font-mono">&#8377;{fmt(c.current_price)}</div>
          </div>
        </div>
        <div className="flex items-center gap-5 mb-4">
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
              <span className="text-[10px] text-gray-400 font-semibold tracking-wider uppercase">{c.grade || "\u2014"}</span>
            </div>
          </div>
          <div className="space-y-2.5 flex-1">
            <div className={`text-xs font-bold px-3 py-1.5 rounded-full text-center capitalize ${verdictColor}`}>
              {verdictText}
            </div>
            <div>
              <div className="text-gray-500 text-[10px] uppercase tracking-wider">Fair Value</div>
              <div className="text-white font-bold font-mono">&#8377;{fmt(c.fair_value)}</div>
            </div>
            <div>
              <div className="text-gray-500 text-[10px] uppercase tracking-wider">Margin of Safety</div>
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
          <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
          <span className="text-[10px] text-gray-500">Live data</span>
        </div>
      </div>
    </div>
  )
}

/* ── Pricing teaser data ──────────────────────────────── */
const pricingPlans = [
  { name: "Free",    price: "\u20B90",     period: "/forever", tagline: "3 deep analyses per day. Unlimited Prism snapshots. No card." },
  { name: "Analyst", price: "\u20B9799",   period: "/month",   tagline: "Unlimited analyses, AI narrative, reverse DCF, scenarios.", highlight: true },
  { name: "Pro",     price: "\u20B91,499", period: "/month",   tagline: "CSV/PDF export, alerts, API access, priority compute." },
]

/* ═════════════════════════════════════════════════════════
   Landing content — 5 sections, ~3500px target
   ═════════════════════════════════════════════════════════ */
function LandingContent() {
  return (
    <div className="bg-white text-gray-900 overflow-x-hidden">
      <MarketingNav />

      {/* ── 1. Hero ────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B]">
        <div className="absolute top-10 left-1/4 w-[500px] h-[500px] bg-blue-600/8 rounded-full blur-3xl" />
        <div className="absolute bottom-10 right-1/4 w-[400px] h-[400px] bg-cyan-500/8 rounded-full blur-3xl" />

        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-16 md:py-24 relative z-10">
          <div className="flex flex-col lg:flex-row items-center gap-12 lg:gap-16">
            <div className="flex-1 text-center lg:text-left">
              <h1 className="font-display text-4xl md:text-5xl lg:text-6xl font-black text-white leading-[1.1] mb-6 tracking-tight">
                Know what a stock is worth.
                <br />
                <span className="bg-gradient-to-r from-blue-400 via-cyan-300 to-blue-500 bg-clip-text text-transparent">
                  Before you invest.
                </span>
              </h1>

              <p className="text-gray-400 text-lg md:text-xl max-w-xl mx-auto lg:mx-0 mb-8 leading-relaxed">
                Institutional-grade DCF valuation for Indian retail investors. No spreadsheets, no guesswork &mdash; just a fair-value estimate in seconds.
              </p>

              <div className="flex flex-col sm:flex-row gap-3 justify-center lg:justify-start mb-6">
                <Link href="/search"
                  className="bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-bold px-8 py-4 rounded-xl text-lg hover:opacity-90 hover:-translate-y-0.5 transition-all shadow-lg shadow-blue-500/25 inline-flex items-center justify-center gap-2">
                  Analyse any stock free <ArrowRight className="w-5 h-5" />
                </Link>
                <Link href="#how-it-works"
                  className="inline-flex items-center justify-center gap-2 border border-white/10 text-white font-semibold px-6 py-4 rounded-xl text-lg hover:bg-white/5 transition">
                  <Play className="w-5 h-5" /> See how it works
                </Link>
              </div>

              {/* Stats strip */}
              <p className="text-gray-400 text-sm">
                <span className="text-white font-semibold">2,900 stocks</span>
                <span className="mx-2 text-gray-600">&middot;</span>
                <span className="text-white font-semibold">3 deep analyses/day free</span>
                <span className="mx-2 text-gray-600">&middot;</span>
                <span className="text-white font-semibold">Unlimited Prism</span>
              </p>
            </div>

            <div className="hidden lg:block flex-shrink-0">
              <DemoCard />
            </div>
          </div>
        </div>
      </section>

      {/* ── 2. Here's what you'll see (kept from a4426ce) ── */}
      <section id="how-it-works" className="bg-white py-20 border-b border-gray-100">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <div className="text-center mb-12">
              <div className="inline-flex items-center gap-2 bg-green-50 border border-green-200 rounded-full px-3 py-1 mb-4">
                <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
                <span className="text-[10px] font-bold text-green-700 tracking-[0.2em] uppercase">
                  No sign-up needed
                </span>
              </div>
              <h2 className="font-display text-3xl sm:text-4xl font-black text-gray-900 mb-3">
                Here&rsquo;s what you&rsquo;ll see
              </h2>
              <p className="text-gray-600 text-base max-w-2xl mx-auto">
                Every Indian stock on YieldIQ is analysed through this same lens &mdash;
                live prices, 3-scenario DCF, quality scores, and plain-English AI
                commentary. This is a real card, rotating through real tickers.
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
              <div className="space-y-5">
                {[
                  { num: "01", title: "Fair value from a 3-scenario DCF", body: "Bear / base / bull cases with an explicit weighted average \u2014 no single-point estimate hiding the uncertainty." },
                  { num: "02", title: "Margin of safety vs. today\u2019s price", body: "Color-coded, percent-based. You see immediately whether the stock is cheap, fair, or rich at the current quote." },
                  { num: "03", title: "YieldIQ score (0\u2013100) + letter grade", body: "Blends valuation, quality, moat, and safety into one number you can compare across sectors." },
                  { num: "04", title: "Moat & Piotroski on every stock", body: "Wide / Narrow / None moat classification plus the 9-point Piotroski F-Score \u2014 no manual digging." },
                  { num: "05", title: "AI summary in plain English", body: "A 2-sentence take on what actually matters for this business, generated fresh from the latest financials." },
                ].map(item => (
                  <div key={item.num} className="flex gap-4">
                    <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center text-white font-black text-xs tracking-wider">
                      {item.num}
                    </div>
                    <div>
                      <h3 className="font-bold text-gray-900 text-base mb-1">{item.title}</h3>
                      <p className="text-gray-600 text-sm leading-relaxed">{item.body}</p>
                    </div>
                  </div>
                ))}
              </div>
            </FadeIn>
          </div>
        </div>
      </section>

      {/* ── 3. Why this is different ────────────────────── */}
      <section className="py-20 bg-gray-50 border-b border-gray-100">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <h2 className="font-display text-3xl md:text-4xl font-black text-gray-900 text-center mb-3">
              Why this is different
            </h2>
            <p className="text-gray-500 text-base text-center max-w-2xl mx-auto mb-12">
              Most valuation tools copy US templates and bolt on Indian tickers. YieldIQ is built the other way around.
            </p>
          </FadeIn>
          <div className="grid md:grid-cols-3 gap-6">
            {[
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
              <div key={f.title} className="bg-white rounded-2xl p-6 border border-gray-100">
                <div className="text-2xl mb-3">{f.icon}</div>
                <h3 className="font-bold text-gray-900 text-base mb-2">{f.title}</h3>
                <p className="text-gray-600 text-sm leading-relaxed">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 4. Pricing teaser ───────────────────────────── */}
      <section className="py-16 bg-white border-b border-gray-100">
        <div className="max-w-5xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <h2 className="font-display text-3xl md:text-4xl font-black text-gray-900 text-center mb-10">
              Pricing
            </h2>
          </FadeIn>
          <div className="grid md:grid-cols-3 gap-4">
            {pricingPlans.map((p) => (
              <div
                key={p.name}
                className={`rounded-2xl p-6 border ${p.highlight ? "border-blue-500 ring-1 ring-blue-500/20 bg-white" : "border-gray-100 bg-white"}`}
              >
                <p className="text-sm font-bold text-gray-500 uppercase tracking-wider">
                  {p.name}
                </p>
                <p className="mt-2">
                  <span className="font-display text-3xl font-black text-gray-900 font-mono">{p.price}</span>
                  <span className="text-gray-500 text-sm">{p.period}</span>
                </p>
                <p className="text-gray-600 text-sm mt-3 leading-relaxed">{p.tagline}</p>
              </div>
            ))}
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
          <h2 className="font-display text-3xl md:text-4xl font-black text-white leading-tight mb-5">
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
          <div className="mt-10 flex items-center justify-center gap-3 flex-wrap text-gray-400 text-xs">
            <span className="text-gray-500">Data from</span>
            {["NSE", "BSE", "RBI", "yfinance"].map((s, i) => (
              <span key={s} className="inline-flex items-center gap-3">
                {i > 0 && <span className="text-gray-700">&bull;</span>}
                <span className="font-mono tracking-wider text-gray-400 font-medium">{s}</span>
              </span>
            ))}
          </div>

          {/* SEBI disclaimer — exact text, do not edit */}
          <p className="mt-6 text-gray-500 text-xs max-w-xl mx-auto leading-relaxed">
            YieldIQ is not registered with SEBI as an investment adviser. All outputs are model estimates using publicly available data. Not investment advice.
          </p>

          <p className="mt-6 text-gray-600 text-xs">&copy; 2026 YieldIQ</p>
        </div>
      </section>
    </div>
  )
}

/* ═════════════════════════════════════════════════════════ */
export default function RootPage() {
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
          <div className="text-2xl font-bold text-gray-900 mb-2">YieldIQ</div>
          <div className="text-sm text-gray-500">Loading...</div>
        </div>
      </div>
    )
  }

  return <LandingContent />
}
