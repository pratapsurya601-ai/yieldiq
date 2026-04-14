"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/store/authStore"
import { useSettingsStore } from "@/store/settingsStore"
import Link from "next/link"
import {
  Search, Shuffle, LineChart, Banknote, ChevronDown,
  ArrowRight, Shield, BarChart3, Target, Layers,
  Zap, TrendingUp, Play,
} from "lucide-react"

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

/* ── Animated counter ────────────────────────────────── */
function AnimatedCounter({ target, suffix = "" }: { target: number; suffix?: string }) {
  const [count, setCount] = useState(0)
  const { ref, inView } = useInView(0.05)
  useEffect(() => {
    if (!inView) return
    const duration = 1500
    const start = performance.now()
    const step = (now: number) => {
      const t = Math.min((now - start) / duration, 1)
      const ease = 1 - Math.pow(1 - t, 3)
      setCount(Math.floor(ease * target))
      if (t < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }, [inView, target])
  return (
    <div ref={ref} className="inline-block min-w-[2ch]">
      {count.toLocaleString("en-IN")}{suffix}
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
        <button onClick={() => setOpen(!open)} className="md:hidden text-white">
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

/* ── Mock Analysis Card (Hero) ───────────────────────── */
function MockAnalysisCard() {
  const score = 78
  const r = 58, circ = 2 * Math.PI * r
  const offset = circ * (1 - score / 100)
  return (
    <div className="relative" style={{ animation: "float 6s ease-in-out infinite" }}>
      <div className="absolute -inset-6 bg-blue-500/5 rounded-3xl blur-2xl" />
      <div className="relative bg-[#0F172A] border border-white/10 rounded-2xl p-6 shadow-2xl w-[320px]">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-white font-bold text-lg">RELIANCE</span>
              <span className="text-[10px] bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded font-medium">NSE</span>
            </div>
            <div className="text-gray-500 text-xs mt-0.5">Reliance Industries Ltd</div>
          </div>
          <div className="text-right">
            <div className="text-white font-bold text-lg font-mono">&#8377;2,943</div>
            <div className="text-green-400 text-xs">+1.2%</div>
          </div>
        </div>
        {/* Conviction Ring */}
        <div className="flex items-center gap-5 mb-4">
          <div className="relative w-[130px] h-[130px] flex-shrink-0">
            <svg viewBox="0 0 140 140" className="w-full h-full -rotate-90">
              <circle cx="70" cy="70" r={r} fill="none" stroke="#1E293B" strokeWidth="8" />
              <circle cx="70" cy="70" r={r} fill="none" stroke="url(#ring-grad)" strokeWidth="8"
                strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={offset} />
              <defs>
                <linearGradient id="ring-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#3B82F6" />
                  <stop offset="100%" stopColor="#06B6D4" />
                </linearGradient>
              </defs>
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-3xl font-black text-white">{score}</span>
              <span className="text-[10px] text-gray-400 font-semibold tracking-wider uppercase">Good</span>
            </div>
          </div>
          <div className="space-y-2.5 flex-1">
            <div className="bg-green-500/10 text-green-400 text-xs font-bold px-3 py-1.5 rounded-full text-center">
              Undervalued
            </div>
            <div>
              <div className="text-gray-500 text-[10px] uppercase tracking-wider">Fair Value</div>
              <div className="text-white font-bold font-mono">&#8377;3,480</div>
            </div>
            <div>
              <div className="text-gray-500 text-[10px] uppercase tracking-wider">Margin of Safety</div>
              <div className="text-blue-400 font-bold font-mono">+18.2%</div>
            </div>
          </div>
        </div>
        {/* Scenarios */}
        <div className="flex gap-2">
          {[
            { label: "Bear", val: "2,810", color: "bg-red-500/20 text-red-400" },
            { label: "Base", val: "3,480", color: "bg-blue-500/20 text-blue-400" },
            { label: "Bull", val: "4,120", color: "bg-green-500/20 text-green-400" },
          ].map(s => (
            <div key={s.label} className={`flex-1 rounded-lg px-2 py-1.5 text-center text-[10px] ${s.color}`}>
              <div className="font-medium">{s.label}</div>
              <div className="font-bold font-mono">&#8377;{s.val}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ── Radar chart (Quality Snowflake) ─────────────────── */
function MockRadarChart() {
  const axes = ["Value", "Quality", "Growth", "Health", "Moat"]
  const scores = [0.85, 0.72, 0.65, 0.9, 0.6]
  const cx = 100, cy = 100, R = 70
  const angleStep = (2 * Math.PI) / 5
  const getPoint = (i: number, r: number) => {
    const a = -Math.PI / 2 + i * angleStep
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)]
  }
  const outerPts = axes.map((_, i) => getPoint(i, R).join(",")).join(" ")
  const scorePts = scores.map((s, i) => getPoint(i, R * s).join(",")).join(" ")

  return (
    <div className="relative">
      <div className="absolute -inset-4 bg-cyan-500/5 rounded-3xl blur-xl" />
      <div className="relative bg-[#0F172A] border border-white/10 rounded-2xl p-6 shadow-2xl">
        <div className="text-white font-bold text-sm mb-3">Quality Snowflake</div>
        <svg viewBox="0 0 200 200" className="w-48 h-48 mx-auto">
          {/* Grid lines */}
          {[0.33, 0.66, 1].map(scale => (
            <polygon key={scale} points={axes.map((_, i) => getPoint(i, R * scale).join(",")).join(" ")}
              fill="none" stroke="#1E293B" strokeWidth="1" />
          ))}
          {/* Axis lines */}
          {axes.map((_, i) => {
            const [x, y] = getPoint(i, R)
            return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#1E293B" strokeWidth="1" />
          })}
          {/* Score polygon */}
          <polygon points={scorePts} fill="rgba(59,130,246,0.15)" stroke="#3B82F6" strokeWidth="2" />
          {/* Score dots */}
          {scores.map((s, i) => {
            const [x, y] = getPoint(i, R * s)
            return <circle key={i} cx={x} cy={y} r="3" fill="#3B82F6" />
          })}
          {/* Labels */}
          {axes.map((label, i) => {
            const [x, y] = getPoint(i, R + 18)
            return <text key={label} x={x} y={y} textAnchor="middle" dominantBaseline="middle"
              className="fill-gray-400 text-[9px] font-medium">{label}</text>
          })}
        </svg>
      </div>
    </div>
  )
}

/* ── Heatmap mockup ──────────────────────────────────── */
function MockHeatmap() {
  const waccs = ["8%", "10%", "12%", "14%", "16%"]
  const growths = ["5%", "8%", "10%", "12%", "15%"]
  const data = [
    [4200, 3890, 3610, 3370, 3150],
    [3950, 3650, 3390, 3160, 2960],
    [3720, 3430, 3180, 2970, 2780],
    [3510, 3230, 2990, 2790, 2610],
    [3320, 3050, 2820, 2630, 2460],
  ]
  const getColor = (v: number) => {
    if (v >= 3600) return "bg-green-500/30 text-green-300"
    if (v >= 3200) return "bg-green-500/15 text-green-400"
    if (v >= 2900) return "bg-blue-500/15 text-blue-300"
    if (v >= 2700) return "bg-amber-500/15 text-amber-300"
    return "bg-red-500/15 text-red-300"
  }
  return (
    <div className="relative">
      <div className="absolute -inset-4 bg-blue-500/5 rounded-3xl blur-xl" />
      <div className="relative bg-[#0F172A] border border-white/10 rounded-2xl p-5 shadow-2xl">
        <div className="text-white font-bold text-sm mb-1">Sensitivity Heatmap</div>
        <div className="text-gray-500 text-[10px] mb-3">Fair value at different WACC &times; Growth</div>
        <div className="overflow-x-auto">
          <table className="text-[10px]">
            <thead>
              <tr>
                <th className="text-gray-500 pr-1 text-left">WACC\Growth</th>
                {growths.map(g => <th key={g} className="text-gray-400 px-1 font-medium text-center">{g}</th>)}
              </tr>
            </thead>
            <tbody>
              {waccs.map((w, i) => (
                <tr key={w}>
                  <td className="text-gray-400 pr-1 font-medium">{w}</td>
                  {data[i].map((v, j) => (
                    <td key={j} className="p-0.5">
                      <div className={`w-11 h-8 rounded flex items-center justify-center font-mono font-bold ${getColor(v)}`}>
                        {(v / 1000).toFixed(1)}k
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

/* ── Scrolling ticker data ───────────────────────────── */
const TICKER_DATA = [
  { name: "RELIANCE", price: "2,943", change: 1.2 },
  { name: "TCS", price: "3,890", change: -0.8 },
  { name: "HDFCBANK", price: "1,642", change: 0.5 },
  { name: "INFY", price: "1,580", change: -1.3 },
  { name: "ITC", price: "438", change: 2.1 },
  { name: "SBIN", price: "782", change: 0.9 },
  { name: "BAJFINANCE", price: "8,240", change: -0.4 },
  { name: "TATAMOTORS", price: "648", change: 1.7 },
  { name: "SUNPHARMA", price: "1,820", change: 0.3 },
  { name: "MARUTI", price: "12,450", change: -0.6 },
  { name: "TITAN", price: "3,210", change: 1.1 },
  { name: "WIPRO", price: "452", change: -1.8 },
  { name: "AXISBANK", price: "1,128", change: 0.7 },
  { name: "KOTAKBANK", price: "1,892", change: -0.2 },
  { name: "LT", price: "3,640", change: 0.4 },
]

/* ── Animated line chart (draws on scroll) ───────────── */
function AnimatedChart() {
  const { ref, inView } = useInView(0.1)
  const points = [
    40, 42, 38, 45, 50, 48, 55, 52, 58, 62, 56, 60, 65, 63, 70,
    68, 72, 75, 71, 78, 82, 80, 85, 88, 84, 90, 87, 92, 95, 93,
  ]
  const w = 320, h = 120, pad = 8
  const xStep = (w - pad * 2) / (points.length - 1)
  const minY = Math.min(...points), maxY = Math.max(...points)
  const scaleY = (v: number) => h - pad - ((v - minY) / (maxY - minY)) * (h - pad * 2)
  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${pad + i * xStep} ${scaleY(p)}`).join(" ")
  const areaD = pathD + ` L ${pad + (points.length - 1) * xStep} ${h - pad} L ${pad} ${h - pad} Z`
  // Calculate approximate path length for stroke-dasharray
  const pathLen = points.reduce((sum, p, i) => {
    if (i === 0) return 0
    const dx = xStep
    const dy = scaleY(p) - scaleY(points[i - 1])
    return sum + Math.sqrt(dx * dx + dy * dy)
  }, 0)

  return (
    <div ref={ref} className="relative">
      <div className="absolute -inset-4 bg-green-500/5 rounded-3xl blur-xl" />
      <div className="relative bg-[#0F172A] border border-white/10 rounded-2xl p-5 shadow-2xl">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-white font-bold text-sm">RELIANCE.NS</div>
            <div className="text-gray-500 text-[10px]">5-Year Price History</div>
          </div>
          <div className="text-right">
            <div className="text-green-400 font-mono font-bold text-sm">+142%</div>
            <div className="text-gray-500 text-[10px]">5Y Return</div>
          </div>
        </div>
        <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-auto">
          {/* Grid lines */}
          {[0.25, 0.5, 0.75].map(pct => (
            <line key={pct} x1={pad} y1={pad + pct * (h - pad * 2)} x2={w - pad} y2={pad + pct * (h - pad * 2)}
              stroke="#1E293B" strokeWidth="1" />
          ))}
          {/* Area fill — use className for reliable CSS transition */}
          <path d={areaD} fill="url(#chart-area-grad)"
            className={`transition-opacity duration-1000 delay-500 ${inView ? "opacity-30" : "opacity-0"}`} />
          {/* Line — use calculated path length for accurate draw animation */}
          <path d={pathD} fill="none" stroke="url(#chart-line-grad)" strokeWidth="2.5" strokeLinecap="round"
            strokeDasharray={pathLen} strokeDashoffset={inView ? 0 : pathLen}
            style={{ transition: "stroke-dashoffset 2s ease" }} />
          {/* Current price dot */}
          <circle cx={pad + (points.length - 1) * xStep} cy={scaleY(points[points.length - 1])}
            r="4" fill="#10B981"
            className={`transition-opacity duration-300 delay-[2000ms] ${inView ? "opacity-100" : "opacity-0"}`} />
          <defs>
            <linearGradient id="chart-line-grad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#3B82F6" />
              <stop offset="100%" stopColor="#10B981" />
            </linearGradient>
            <linearGradient id="chart-area-grad" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#10B981" />
              <stop offset="100%" stopColor="transparent" />
            </linearGradient>
          </defs>
        </svg>
        {/* Price axis */}
        <div className="flex justify-between text-[9px] text-gray-600 font-mono mt-1 px-1">
          <span>2021</span><span>2022</span><span>2023</span><span>2024</span><span>2025</span><span>2026</span>
        </div>
      </div>
    </div>
  )
}

/* ── Animated bar chart (revenue growth) ─────────────── */
function AnimatedBars() {
  const { ref, inView } = useInView(0.1)
  const bars = [
    { year: "FY21", val: 65, color: "from-blue-500 to-blue-400" },
    { year: "FY22", val: 78, color: "from-blue-500 to-cyan-400" },
    { year: "FY23", val: 85, color: "from-blue-500 to-cyan-400" },
    { year: "FY24", val: 92, color: "from-cyan-500 to-green-400" },
    { year: "FY25", val: 100, color: "from-green-500 to-emerald-400" },
  ]
  return (
    <div ref={ref} className="relative">
      <div className="absolute -inset-4 bg-blue-500/5 rounded-3xl blur-xl" />
      <div className="relative bg-[#0F172A] border border-white/10 rounded-2xl p-5 shadow-2xl">
        <div className="text-white font-bold text-sm mb-1">Revenue Growth</div>
        <div className="text-gray-500 text-[10px] mb-4">RELIANCE — 5-year trend (&#8377; Cr)</div>
        <div className="flex items-end gap-3 h-28">
          {bars.map((b, i) => (
            <div key={b.year} className="flex-1 flex flex-col items-center gap-1">
              <div className="w-full relative" style={{ height: `${b.val}%` }}>
                <div
                  className={`absolute bottom-0 w-full rounded-t-md bg-gradient-to-t ${b.color}`}
                  style={{
                    height: inView ? "100%" : "0%",
                    transition: `height 0.8s ease ${i * 0.15}s`,
                  }}
                />
              </div>
              <span className="text-[9px] text-gray-500 font-mono">{b.year}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ── Interactive WACC slider demo ────────────────────── */
function InteractiveWACCDemo() {
  const [wacc, setWacc] = useState(12)
  const baseFV = 3480
  // Simple inverse relationship: lower WACC = higher fair value
  const fairValue = Math.round(baseFV * (12 / wacc))
  const mos = Math.round((fairValue / 2943 - 1) * 100)

  return (
    <div className="relative">
      <div className="absolute -inset-4 bg-purple-500/5 rounded-3xl blur-xl" />
      <div className="relative bg-[#0F172A] border border-white/10 rounded-2xl p-5 shadow-2xl">
        <div className="text-white font-bold text-sm mb-1">Interactive DCF</div>
        <div className="text-gray-500 text-[10px] mb-4">Drag to see fair value change in real-time</div>

        {/* WACC Slider */}
        <div className="mb-4">
          <div className="flex justify-between text-[10px] mb-1.5">
            <span className="text-gray-400">WACC (Discount Rate)</span>
            <span className="text-cyan-400 font-mono font-bold">{wacc.toFixed(1)}%</span>
          </div>
          <input type="range" min={8} max={18} step={0.5} value={wacc}
            onChange={e => setWacc(parseFloat(e.target.value))}
            className="w-full h-1.5 rounded-full appearance-none cursor-pointer
              bg-gradient-to-r from-green-500 via-cyan-500 to-red-500
              [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4
              [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:shadow-lg
              [&::-webkit-slider-thumb]:shadow-cyan-500/30" />
          <div className="flex justify-between text-[9px] text-gray-600 mt-1">
            <span>8%</span><span>13%</span><span>18%</span>
          </div>
        </div>

        {/* Result */}
        <div className="bg-white/5 rounded-xl p-3 flex items-center justify-between">
          <div>
            <div className="text-gray-500 text-[10px]">Fair Value</div>
            <div className="text-white font-black text-xl font-mono">&#8377;{fairValue.toLocaleString("en-IN")}</div>
          </div>
          <div className="text-right">
            <div className="text-gray-500 text-[10px]">Margin of Safety</div>
            <div className={`font-bold text-lg font-mono ${mos >= 0 ? "text-green-400" : "text-red-400"}`}>
              {mos >= 0 ? "+" : ""}{mos}%
            </div>
          </div>
        </div>
        <div className="text-center mt-2">
          <span className={`text-[10px] font-bold px-3 py-1 rounded-full ${
            mos >= 15 ? "bg-green-500/20 text-green-400" :
            mos >= 0 ? "bg-blue-500/20 text-blue-400" :
            "bg-red-500/20 text-red-400"
          }`}>
            {mos >= 15 ? "Undervalued" : mos >= 0 ? "Fair Value" : "Overvalued"}
          </span>
        </div>
      </div>
    </div>
  )
}

/* ── FAQ Accordion ───────────────────────────────────── */
const faqs = [
  { q: "What is DCF valuation?", a: "Discounted Cash Flow (DCF) estimates a stock's intrinsic value by projecting future free cash flows and discounting them back to present value. It tells you what a stock is actually worth based on fundamentals, not market sentiment." },
  { q: "How accurate is the fair value estimate?", a: "DCF is a model, not a prediction. The output depends on assumptions (growth rate, WACC, terminal value). YieldIQ shows you all assumptions transparently so you can judge the quality of the estimate yourself." },
  { q: "Which stocks are covered?", a: "All NSE and BSE listed equities \u2014 over 2,900 stocks including large caps, mid caps, and small caps. We support banking/NBFC stocks with relative valuation models." },
  { q: "Is this investment advice?", a: "No. YieldIQ is a quantitative research tool. All outputs are model-generated estimates for educational purposes. We are not registered with SEBI as an investment adviser." },
  { q: "Do I need a finance background?", a: "No. All assumptions are pre-filled with sensible defaults. The interface explains every metric in plain language. If you\u2019ve never built a DCF before, you can still understand the output." },
  { q: "Can I cancel anytime?", a: "Yes. No lock-in. Cancel from your account settings. Full refund within 7 days if you\u2019re not satisfied." },
]

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-b border-gray-100">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between py-5 text-left">
        <span className="font-semibold text-gray-900 pr-4">{q}</span>
        <ChevronDown className={`w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-300 ${open ? "rotate-180" : ""}`} />
      </button>
      <div className={`overflow-hidden transition-all duration-300 ${open ? "max-h-60 pb-5" : "max-h-0"}`}>
        <p className="text-gray-500 text-sm leading-relaxed">{a}</p>
      </div>
    </div>
  )
}


/* ── Pricing data ────────────────────────────────────── */
const pricingPlans = [
  {
    name: "Free", price: "\u20B90", period: "/forever",
    features: ["5 analyses per day", "NSE/BSE large caps", "Basic DCF valuation"],
    cta: "Get Started Free", highlighted: false,
  },
  {
    name: "Starter", price: "\u20B9499", period: "/month",
    features: ["50 analyses per day", "All 6,000+ stocks", "Interactive DCF + heatmap"],
    cta: "Start 7-Day Free Trial", highlighted: true,
  },
  {
    name: "Pro", price: "\u20B91,999", period: "/month",
    features: ["Unlimited analyses", "Monte Carlo + API", "AI summary + bulk screener"],
    cta: "Get Pro Access", highlighted: false,
  },
]

/* ═════════════════════════════════════════════════════════
   Main Landing Page
   ═════════════════════════════════════════════════════════ */
function LandingContent() {
  return (
    <div className="bg-white text-gray-900 overflow-x-hidden">
      <MarketingNav />

      {/* ── Hero ──────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B]">
        {/* Animated background orbs */}
        <div className="absolute top-10 left-1/4 w-[500px] h-[500px] bg-blue-600/8 rounded-full blur-3xl" style={{ animation: "shimmer-drift 8s ease-in-out infinite" }} />
        <div className="absolute bottom-10 right-1/4 w-[400px] h-[400px] bg-cyan-500/8 rounded-full blur-3xl" style={{ animation: "shimmer-drift 10s ease-in-out infinite 2s" }} />
        <div className="absolute top-1/2 left-1/2 w-[300px] h-[300px] bg-indigo-500/5 rounded-full blur-3xl" style={{ animation: "shimmer-drift 12s ease-in-out infinite 4s" }} />

        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-16 md:py-24 relative z-10">
          <div className="flex flex-col lg:flex-row items-center gap-12 lg:gap-16">
            {/* Left — text */}
            <div className="flex-1 text-center lg:text-left">
              <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-blue-500/20 bg-blue-500/10 text-blue-400 text-xs font-medium mb-6">
                <span className="w-2 h-2 bg-green-400 rounded-full" style={{ animation: "pulse-glow 2s ease-in-out infinite" }} />
                Live &mdash; 2,900+ stocks analyzed
              </div>

              <h1 className="text-4xl md:text-5xl lg:text-6xl font-black text-white leading-[1.1] mb-6 tracking-tight">
                Know What a Stock
                <br />Is Worth.{" "}
                <span className="bg-gradient-to-r from-blue-400 via-cyan-300 to-blue-500 bg-clip-text text-transparent bg-[length:200%] animate-[gradient-shift_3s_ease_infinite]">
                  Before You Decide.
                </span>
              </h1>

              <p className="text-gray-400 text-lg md:text-xl max-w-xl mx-auto lg:mx-0 mb-8 leading-relaxed">
                Institutional-grade DCF valuation for Indian retail investors.
                No spreadsheets, no guesswork. Enter a ticker, get fair value in seconds.
              </p>

              <div className="flex flex-col sm:flex-row gap-3 justify-center lg:justify-start mb-6">
                <Link href="/auth/signup"
                  className="bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-bold px-8 py-4 rounded-xl text-lg hover:opacity-90 hover:shadow-xl hover:shadow-blue-500/25 hover:-translate-y-0.5 transition-all shadow-lg shadow-blue-500/20">
                  Start Valuing Stocks &mdash; Free &rarr;
                </Link>
                <Link href="#how-it-works"
                  className="flex items-center justify-center gap-2 border border-white/10 text-white font-semibold px-6 py-4 rounded-xl text-lg hover:bg-white/5 transition">
                  <Play className="w-5 h-5" /> How it works
                </Link>
              </div>

              {/* Real stats instead of fake avatars */}
              <div className="flex items-center gap-6 justify-center lg:justify-start text-sm text-gray-400">
                <span><span className="text-white font-semibold">&#8377;0</span> forever for core features</span>
                <span className="text-gray-600">&bull;</span>
                <span>No credit card required</span>
              </div>
            </div>

            {/* Right — floating analysis card */}
            <div className="hidden lg:block flex-shrink-0">
              <MockAnalysisCard />
            </div>
          </div>

          {/* Stats */}
          <div className="flex justify-center lg:justify-start gap-12 mt-16 flex-wrap">
            {[
              { value: 2934, suffix: "+", label: "Stocks Analyzed" },
              { value: 15, suffix: "", label: "Valuation Engines" },
              { value: 10, suffix: "-Year", label: "DCF Projections" },
            ].map(s => (
              <div key={s.label} className="text-center">
                <div className="text-3xl font-black text-white">
                  <AnimatedCounter target={s.value} suffix={s.suffix} />
                </div>
                <div className="text-gray-500 text-xs mt-1">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Scrolling Stock Ticker ────────────────────── */}
      <section className="bg-[#0B1120] border-y border-white/5 py-2.5 overflow-hidden">
        <div className="flex whitespace-nowrap" style={{ animation: "ticker-scroll 40s linear infinite" }}>
          {[...TICKER_DATA, ...TICKER_DATA].map((t, i) => (
            <div key={`${t.name}-${i}`} className="inline-flex items-center gap-2 px-5 text-xs">
              <span className="text-gray-400 font-semibold">{t.name}</span>
              <span className="text-white font-mono font-bold">&#8377;{t.price}</span>
              <span className={`font-mono font-bold ${t.change >= 0 ? "text-green-400" : "text-red-400"}`}>
                {t.change >= 0 ? "+" : ""}{t.change}%
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* ── Trust Bar ─────────────────────────────────── */}
      <section className="bg-gray-50 border-b border-gray-100 py-4">
        <div className="max-w-6xl mx-auto px-4 flex items-center justify-center gap-4 flex-wrap text-gray-400 text-sm">
          <span className="text-gray-500 font-medium">Data sourced from</span>
          {["NSE", "BSE", "RBI", "yfinance"].map((s, i) => (
            <span key={s}>
              {i > 0 && <span className="mr-4 text-gray-300">&bull;</span>}
              <span className="font-mono tracking-wider text-gray-400 font-medium">{s}</span>
            </span>
          ))}
        </div>
      </section>

      {/* ── Problem ───────────────────────────────────── */}
      <section className="py-20 bg-white">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase text-center mb-3">The Problem</p>
            <h2 className="text-3xl md:text-4xl font-black text-center mb-16 leading-tight">
              Most Indian Investors Act on Tips,<br />Not Value.
            </h2>
          </FadeIn>
          <div className="grid md:grid-cols-3 gap-8">
            {[
              { Icon: Shuffle, title: "Entering at any price", desc: "Retail investors chase momentum without knowing if a stock is overvalued or undervalued.", color: "text-red-500 bg-red-50", border: "border-l-red-300" },
              { Icon: LineChart, title: "DCF is too complex", desc: "Building a discounted cash flow model takes hours and requires finance expertise most people lack.", color: "text-amber-500 bg-amber-50", border: "border-l-amber-300" },
              { Icon: Banknote, title: "Tools are expensive", desc: "Bloomberg Terminal costs \u20B920L/year. Screeners give ratios, not valuations. The gap is massive.", color: "text-blue-500 bg-blue-50", border: "border-l-blue-300" },
            ].map((card, i) => (
              <FadeIn key={card.title} delay={i * 100}>
                <div className={`bg-white rounded-2xl p-8 shadow-sm border border-gray-100 border-l-4 ${card.border} hover:shadow-lg transition`}>
                  <div className={`w-12 h-12 rounded-xl ${card.color} flex items-center justify-center mb-4`}>
                    <card.Icon className="w-6 h-6" />
                  </div>
                  <h3 className="font-bold text-lg mb-2">{card.title}</h3>
                  <p className="text-gray-500 text-sm leading-relaxed">{card.desc}</p>
                </div>
              </FadeIn>
            ))}
          </div>
        </div>
      </section>

      {/* ── How It Works ──────────────────────────────── */}
      <section id="how-it-works" className="py-20 bg-gray-50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase text-center mb-3">How It Works</p>
            <h2 className="text-3xl md:text-4xl font-black text-center mb-16">Fair Value in Three Steps.</h2>
          </FadeIn>
          <div className="grid md:grid-cols-3 gap-8 relative">
            {/* Connector line */}
            <div className="hidden md:block absolute top-8 left-[calc(16.67%+24px)] right-[calc(16.67%+24px)] h-0.5 border-t-2 border-dashed border-blue-200" />
            {[
              { step: "1", title: "Enter a Ticker", desc: "Type any NSE/BSE stock \u2014 RELIANCE, TCS, INFY, or any of 2,900+ stocks.", Icon: Search },
              { step: "2", title: "Automatic DCF Analysis", desc: "YieldIQ pulls financials and runs 15 valuation engines with India-calibrated WACC automatically.", Icon: BarChart3 },
              { step: "3", title: "Get Fair Value", desc: "See fair value, conviction score, scenarios \u2014 adjust WACC, growth, terminal rate instantly.", Icon: Target },
            ].map((item, i) => (
              <FadeIn key={item.step} delay={i * 150}>
                <div className="text-center relative z-10">
                  <div className="w-16 h-16 rounded-full border-2 border-blue-500 flex items-center justify-center text-blue-600 text-2xl font-black mx-auto mb-6 bg-gray-50">
                    {item.step}
                  </div>
                  <h3 className="font-bold text-lg mb-2">{item.title}</h3>
                  <p className="text-gray-500 text-sm leading-relaxed max-w-xs mx-auto">{item.desc}</p>
                </div>
              </FadeIn>
            ))}
          </div>
        </div>
      </section>

      {/* ── Product Showcase ──────────────────────────── */}
      <section className="py-20 bg-white">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase text-center mb-3">What You Get</p>
            <h2 className="text-3xl md:text-4xl font-black text-center mb-16">See the Product in Action.</h2>
          </FadeIn>

          {/* Showcase 1: Valuation */}
          <FadeIn>
            <div className="flex flex-col lg:flex-row items-center gap-12 mb-20">
              <div className="flex-1">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 text-blue-600 text-xs font-bold mb-4">
                  <Layers className="w-3.5 h-3.5" /> Core Engine
                </div>
                <h3 className="text-2xl font-black mb-3">Instant DCF Valuation</h3>
                <p className="text-gray-500 leading-relaxed mb-4">
                  Enter any ticker and get an institutional-grade DCF analysis in seconds. See fair value,
                  conviction score, margin of safety, and Bear/Base/Bull scenarios.
                </p>
                <ul className="space-y-2">
                  {["Conviction ring with 0-100 scoring", "Undervalued/Overvalued verdict", "3 scenario analysis (Bear/Base/Bull)"].map(f => (
                    <li key={f} className="flex items-center gap-2 text-sm text-gray-600">
                      <div className="w-1.5 h-1.5 rounded-full bg-blue-500" /> {f}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="flex-shrink-0 hidden md:block">
                <MockAnalysisCard />
              </div>
            </div>
          </FadeIn>

          {/* Showcase 2: Animated Charts + Data */}
          <FadeIn>
            <div className="flex flex-col lg:flex-row-reverse items-center gap-12 mb-20">
              <div className="flex-1">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-green-50 text-green-600 text-xs font-bold mb-4">
                  <TrendingUp className="w-3.5 h-3.5" /> Historical Data
                </div>
                <h3 className="text-2xl font-black mb-3">5 Years of Financial Data</h3>
                <p className="text-gray-500 leading-relaxed mb-4">
                  Price history, revenue trends, cash flow growth — all visualized instantly.
                  Powered by 1M+ data points from NSE Bhavcopy, BSE filings, and RBI benchmarks.
                </p>
                <ul className="space-y-2">
                  {["Self-drawing price charts on scroll", "Revenue & FCF growth bars", "1M+ price records across 2,900+ stocks"].map(f => (
                    <li key={f} className="flex items-center gap-2 text-sm text-gray-600">
                      <div className="w-1.5 h-1.5 rounded-full bg-green-500" /> {f}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="flex-shrink-0 hidden md:flex flex-col gap-4">
                <AnimatedChart />
                <AnimatedBars />
              </div>
            </div>
          </FadeIn>

          {/* Showcase 3: Interactive DCF */}
          <FadeIn>
            <div className="flex flex-col lg:flex-row items-center gap-12">
              <div className="flex-1">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-50 text-purple-600 text-xs font-bold mb-4">
                  <Target className="w-3.5 h-3.5" /> Try It Now
                </div>
                <h3 className="text-2xl font-black mb-3">Interactive DCF Engine</h3>
                <p className="text-gray-500 leading-relaxed mb-4">
                  Drag the WACC slider and watch the fair value change in real-time.
                  No black box — every assumption is visible and adjustable.
                  <span className="font-semibold text-gray-700"> Try it right here.</span>
                </p>
                <ul className="space-y-2">
                  {["Real-time fair value recalculation", "WACC, growth rate, terminal value sliders", "Instant Undervalued/Overvalued verdict"].map(f => (
                    <li key={f} className="flex items-center gap-2 text-sm text-gray-600">
                      <div className="w-1.5 h-1.5 rounded-full bg-purple-500" /> {f}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="flex-shrink-0 hidden md:block">
                <InteractiveWACCDemo />
              </div>
            </div>
          </FadeIn>
        </div>
      </section>

      {/* ── Live Demo CTA ─────────────────────────────── */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-16">
        <div className="max-w-3xl mx-auto px-4 text-center">
          <FadeIn>
            <h2 className="text-2xl md:text-3xl font-black text-white mb-3">See it in action</h2>
            <p className="text-gray-400 mb-8">Try a free analysis on any stock</p>
            <div className="bg-white/5 border border-white/10 rounded-xl px-4 py-3 flex items-center gap-3 max-w-md mx-auto mb-6">
              <Search className="w-5 h-5 text-gray-500 flex-shrink-0" />
              <span className="text-gray-500 text-sm flex-1 text-left">Try RELIANCE, TCS, or INFY...</span>
              <Link href="/analysis/RELIANCE.NS" className="bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-semibold px-4 py-1.5 rounded-lg text-sm hover:opacity-90 transition">
                Analyze
              </Link>
            </div>
            <div className="flex gap-3 justify-center flex-wrap">
              {["RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC"].map(t => (
                <Link key={t} href={`/analysis/${t}.NS`}
                  className="border border-white/10 text-white/80 px-4 py-1.5 rounded-full text-sm hover:bg-white/10 transition font-mono">
                  {t}
                </Link>
              ))}
            </div>
          </FadeIn>
        </div>
      </section>

      {/* comparison section removed per user request */}

      {/* ── Pricing Preview ───────────────────────────── */}
      <section className="py-20 bg-gray-50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase text-center mb-3">Pricing</p>
            <h2 className="text-3xl md:text-4xl font-black text-center mb-4">Simple, Transparent Pricing.</h2>
            <p className="text-gray-500 text-center mb-16">Start free. Upgrade when you need more power.</p>
          </FadeIn>
          <div className="grid md:grid-cols-3 gap-6 max-w-4xl mx-auto">
            {pricingPlans.map((plan, i) => (
              <FadeIn key={plan.name} delay={i * 100}>
                <div className={plan.highlighted
                  ? "bg-gradient-to-br from-blue-600 to-cyan-500 p-px rounded-2xl shadow-xl shadow-blue-500/20"
                  : ""
                }>
                  <div className={`rounded-2xl p-6 h-full ${plan.highlighted ? "bg-white" : "bg-white border border-gray-200"}`}>
                    <div className="text-sm font-bold uppercase tracking-wider text-gray-500 mb-2">{plan.name}</div>
                    <div className="flex items-baseline gap-1 mb-1">
                      <span className="text-4xl font-black text-gray-900">{plan.price}</span>
                      <span className="text-gray-400 text-sm">{plan.period}</span>
                    </div>
                    <ul className="space-y-2 my-6">
                      {plan.features.map(f => (
                        <li key={f} className="flex items-center gap-2 text-sm text-gray-600">
                          <Zap className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" /> {f}
                        </li>
                      ))}
                    </ul>
                    <Link href="/auth/signup"
                      className={`block w-full text-center py-3 rounded-xl font-semibold text-sm transition ${
                        plan.highlighted
                          ? "bg-gradient-to-r from-blue-600 to-cyan-500 text-white hover:opacity-90"
                          : "border border-gray-200 text-gray-700 hover:bg-gray-50"
                      }`}>
                      {plan.cta} &rarr;
                    </Link>
                  </div>
                </div>
              </FadeIn>
            ))}
          </div>
          <p className="text-center mt-8">
            <Link href="/pricing" className="text-blue-600 text-sm font-semibold hover:underline">
              See full comparison &rarr;
            </Link>
          </p>
        </div>
      </section>

      {/* ── FAQ ───────────────────────────────────────── */}
      <section className="py-20 bg-white">
        <div className="max-w-3xl mx-auto px-4 sm:px-6">
          <FadeIn>
            <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase text-center mb-3">FAQ</p>
            <h2 className="text-3xl md:text-4xl font-black text-center mb-12">Frequently Asked Questions</h2>
          </FadeIn>
          <FadeIn>
            <div>
              {faqs.map(f => <FAQItem key={f.q} q={f.q} a={f.a} />)}
            </div>
          </FadeIn>
        </div>
      </section>

      {/* ── Final CTA ─────────────────────────────────── */}
      <section className="relative overflow-hidden bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-24">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-blue-600/5 rounded-full blur-3xl" />
        <div className="max-w-4xl mx-auto px-4 text-center relative z-10">
          <FadeIn>
            <h2 className="text-4xl md:text-5xl font-black text-white mb-4">
              Stop Guessing. Start Valuing.
            </h2>
            <p className="text-gray-400 text-lg mb-4 max-w-xl mx-auto">
              Join 2,900+ Indian investors making smarter decisions with DCF analysis.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center mt-8">
              <Link href="/auth/signup"
                className="bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-bold px-10 py-4 rounded-xl text-lg hover:opacity-90 hover:shadow-xl hover:shadow-blue-500/30 hover:-translate-y-0.5 transition-all shadow-lg shadow-blue-500/20 inline-block">
                Launch YieldIQ &mdash; It&apos;s Free &rarr;
              </Link>
              <Link href="/analysis/RELIANCE.NS"
                className="flex items-center justify-center gap-2 border border-white/10 text-white font-semibold px-8 py-4 rounded-xl text-lg hover:bg-white/5 transition">
                See a live analysis &rarr;
              </Link>
            </div>
            <p className="text-gray-500 text-sm mt-6">Works on mobile. No download required. No credit card.</p>
          </FadeIn>
        </div>
      </section>

      {/* ── Footer ────────────────────────────────────── */}
      <footer className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] border-t border-white/5 py-12">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <div className="flex flex-col md:flex-row justify-between items-start gap-8">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <img src="/logo-new.svg" alt="YieldIQ" className="w-8 h-8 rounded-lg" />
                <span className="text-white font-bold text-lg">YieldIQ</span>
              </div>
              <p className="text-gray-500 text-sm max-w-xs mb-4">
                Institutional-grade DCF valuation for Indian retail investors.
              </p>
              {/* Social links */}
              <div className="flex gap-3">
                <a href="https://twitter.com/yieldiq" target="_blank" rel="noopener noreferrer"
                  className="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                </a>
                <a href="https://linkedin.com/company/yieldiq" target="_blank" rel="noopener noreferrer"
                  className="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
                </a>
              </div>
            </div>
            <div className="flex gap-16 flex-wrap">
              <div>
                <h4 className="text-gray-300 font-semibold text-sm mb-3">Product</h4>
                <div className="space-y-2">
                  <Link href="/features" className="block text-gray-500 text-sm hover:text-gray-300 transition">Features</Link>
                  <Link href="/pricing" className="block text-gray-500 text-sm hover:text-gray-300 transition">Pricing</Link>
                </div>
              </div>
              <div>
                <h4 className="text-gray-300 font-semibold text-sm mb-3">Company</h4>
                <div className="space-y-2">
                  <a href="mailto:hello@yieldiq.in" className="block text-gray-500 text-sm hover:text-gray-300 transition">Contact</a>
                </div>
              </div>
              <div>
                <h4 className="text-gray-300 font-semibold text-sm mb-3">Legal</h4>
                <div className="space-y-2">
                  <Link href="/privacy" className="block text-gray-500 text-sm hover:text-gray-300 transition">Privacy</Link>
                  <Link href="/terms" className="block text-gray-500 text-sm hover:text-gray-300 transition">Terms</Link>
                </div>
              </div>
            </div>
          </div>
          <div className="border-t border-white/5 mt-10 pt-6 flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-gray-600 text-xs">&copy; 2026 YieldIQ. Made in India.</p>
            <p className="text-gray-600 text-xs">
              Model output only &mdash; not investment advice. YieldIQ is not registered with SEBI as an investment adviser.
            </p>
          </div>
        </div>
      </footer>
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
