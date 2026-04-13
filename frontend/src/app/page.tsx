"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/store/authStore"
import { useSettingsStore } from "@/store/settingsStore"
import Link from "next/link"
import { useState } from "react"

function MarketingNav() {
  const [mobileOpen, setMobileOpen] = useState(false)
  return (
    <nav className="sticky top-0 z-50 border-b border-white/5 bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B]">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <img src="/logo.jpeg" alt="YieldIQ" className="w-8 h-8 rounded-full" />
          <span className="text-white font-bold text-lg">YieldIQ</span>
        </Link>
        <div className="hidden md:flex items-center gap-8 text-sm">
          <Link href="/features" className="text-gray-400 hover:text-white transition">Features</Link>
          <Link href="/pricing" className="text-gray-400 hover:text-white transition">Pricing</Link>
          <Link href="/auth/signup" className="bg-gradient-to-r from-blue-700 to-cyan-500 text-white font-semibold px-5 py-2 rounded-lg hover:opacity-90 transition">
            Launch App &rarr;
          </Link>
        </div>
        <button onClick={() => setMobileOpen(!mobileOpen)} className="md:hidden text-white">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      </div>
      {mobileOpen && (
        <div className="md:hidden px-4 pb-4 space-y-3">
          <Link href="/features" className="block text-gray-400 hover:text-white text-sm">Features</Link>
          <Link href="/pricing" className="block text-gray-400 hover:text-white text-sm">Pricing</Link>
          <Link href="/auth/signup" className="block bg-gradient-to-r from-blue-700 to-cyan-500 text-white font-semibold px-5 py-2 rounded-lg text-center text-sm">
            Launch App &rarr;
          </Link>
        </div>
      )}
    </nav>
  )
}

function LandingContent() {
  return (
    <div className="bg-white text-gray-900">
      <MarketingNav />

      {/* Hero */}
      <section className="relative overflow-hidden bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B]">
        <div className="absolute top-20 left-1/4 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl" />
        <div className="absolute bottom-10 right-1/4 w-72 h-72 bg-cyan-500/10 rounded-full blur-3xl" />
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-20 md:py-32 text-center relative z-10">
          <p className="text-blue-400 text-xs font-bold tracking-[0.2em] uppercase mb-4">Quantitative Research Platform</p>
          <h1 className="text-4xl md:text-6xl font-black text-white leading-tight mb-6">
            Know What a Stock Is Worth.
            <br />
            <span className="bg-gradient-to-r from-blue-500 to-cyan-400 bg-clip-text text-transparent">Before You Invest.</span>
          </h1>
          <p className="text-gray-400 text-lg md:text-xl max-w-2xl mx-auto mb-10 leading-relaxed">
            YieldIQ gives Indian retail investors institutional-grade DCF valuation &mdash;
            no spreadsheets, no guesswork. Enter a ticker, get a fair value estimate in seconds.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center mb-6">
            <Link
              href="/auth/signup"
              className="bg-gradient-to-r from-blue-700 to-cyan-500 text-white font-bold px-8 py-4 rounded-xl text-lg hover:opacity-90 transition shadow-lg shadow-blue-500/25"
            >
              Start Valuing Stocks &mdash; Free &rarr;
            </Link>
          </div>
          <p className="text-gray-500 text-sm">Works for 6,000+ NSE/BSE stocks.</p>

          {/* Stats */}
          <div className="flex justify-center gap-12 mt-16 flex-wrap">
            <div className="text-center">
              <div className="text-3xl font-black text-white">6,000+</div>
              <div className="text-gray-500 text-xs mt-1">Stocks Covered</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-black text-white">10-Year</div>
              <div className="text-gray-500 text-xs mt-1">DCF Projections</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-black text-white">Free</div>
              <div className="text-gray-500 text-xs mt-1">3 Analyses/Day</div>
            </div>
          </div>
        </div>
      </section>

      {/* Problem */}
      <section className="py-20 bg-gray-50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase text-center mb-3">The Problem</p>
          <h2 className="text-3xl md:text-4xl font-black text-center mb-16 leading-tight">
            Most Indian Investors Act on Tips,
            <br />Not Value.
          </h2>
          <div className="grid md:grid-cols-3 gap-8">
            <div className="bg-white rounded-2xl p-8 shadow-sm border border-gray-100">
              <div className="text-3xl mb-4">&#x1F3B2;</div>
              <h3 className="font-bold text-lg mb-2">Entering at any price</h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                Retail investors chase momentum without knowing if a stock is overvalued or undervalued.
              </p>
            </div>
            <div className="bg-white rounded-2xl p-8 shadow-sm border border-gray-100">
              <div className="text-3xl mb-4">&#x1F4CA;</div>
              <h3 className="font-bold text-lg mb-2">DCF is too complex</h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                Building a discounted cash flow model takes hours and requires finance expertise most people lack.
              </p>
            </div>
            <div className="bg-white rounded-2xl p-8 shadow-sm border border-gray-100">
              <div className="text-3xl mb-4">&#x1F4B0;</div>
              <h3 className="font-bold text-lg mb-2">Tools are expensive</h3>
              <p className="text-gray-500 text-sm leading-relaxed">
                Bloomberg Terminal costs &#8377;20L/year. Screeners give ratios, not valuations. The gap is massive.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="py-20 bg-white">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase text-center mb-3">How It Works</p>
          <h2 className="text-3xl md:text-4xl font-black text-center mb-16">
            Fair Value in Three Steps.
          </h2>
          <div className="grid md:grid-cols-3 gap-8">
            {[
              { step: "1", title: "Enter a Ticker", desc: "Type any NSE/BSE stock ticker \u2014 RELIANCE, TCS, INFY" },
              { step: "2", title: "Automatic DCF Analysis", desc: "YieldIQ pulls financials and runs a DCF model with India-calibrated WACC automatically." },
              { step: "3", title: "Get Fair Value", desc: "See the estimated fair value with adjustable assumptions \u2014 change WACC, growth, terminal rate instantly." },
            ].map((item) => (
              <div key={item.step} className="text-center">
                <div className="w-16 h-16 rounded-2xl bg-gradient-to-r from-blue-700 to-cyan-500 flex items-center justify-center text-white text-2xl font-black mx-auto mb-6">
                  {item.step}
                </div>
                <h3 className="font-bold text-lg mb-2">{item.title}</h3>
                <p className="text-gray-500 text-sm">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="py-20 bg-gray-50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase text-center mb-3">Why YieldIQ</p>
          <h2 className="text-3xl md:text-4xl font-black text-center mb-16">
            Built for Indian Markets. Built for Clarity.
          </h2>
          <div className="grid md:grid-cols-2 gap-6">
            {[
              { icon: "\u{1F1EE}\u{1F1F3}", title: "Indian Market Data", desc: "Covers 6,000+ NSE/BSE stocks with India-specific WACC, risk-free rates calibrated to RBI benchmarks." },
              { icon: "\u{1F393}", title: "No Finance Degree Needed", desc: "Assumptions pre-filled with sensible defaults. Understand the output even if you\u2019ve never built a DCF before." },
              { icon: "\u{1F50D}", title: "Transparent Models", desc: "Every assumption is visible and adjustable. No black box. See exactly how the fair value is calculated." },
              { icon: "\u26A1", title: "Free to Start", desc: "Core valuation is free. No credit card. No signup wall. Start using it in 10 seconds." },
            ].map((f) => (
              <div key={f.title} className="bg-white rounded-2xl p-8 border border-gray-100 hover:border-blue-200 hover:shadow-lg transition">
                <div className="text-2xl mb-3">{f.icon}</div>
                <h3 className="font-bold text-lg mb-2">{f.title}</h3>
                <p className="text-gray-500 text-sm leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* What You Get */}
      <section className="py-20 bg-white">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase text-center mb-3">What You Get</p>
          <h2 className="text-3xl md:text-4xl font-black text-center mb-16">
            Professional Valuation Tools. Zero Complexity.
          </h2>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              { icon: "\u{1F4CA}", title: "Valuation Hero", desc: "Fair value, implied upside/downside, Bear/Base/Bull scenarios \u2014 all at a glance." },
              { icon: "\u2744\uFE0F", title: "Quality Snowflake", desc: "5-axis radar chart scoring Value, Quality, Growth, Health, and Moat." },
              { icon: "\u{1F527}", title: "Interactive DCF", desc: "Adjust WACC, growth rate, terminal value \u2014 see fair value change in real-time." },
              { icon: "\u{1F3AF}", title: "Sensitivity Heatmap", desc: "See how fair value changes across different WACC and growth assumptions." },
              { icon: "\u{1F3DB}\uFE0F", title: "Banking & NBFC Support", desc: "Relative valuation (P/B, P/E vs sector) for stocks where DCF doesn\u2019t apply." },
              { icon: "\u{1F4F1}", title: "Works on Mobile", desc: "Responsive design. Check valuations on the go \u2014 train, chai break, anywhere." },
            ].map((f) => (
              <div key={f.title} className="text-center p-6">
                <div className="text-4xl mb-4">{f.icon}</div>
                <h3 className="font-bold mb-2">{f.title}</h3>
                <p className="text-gray-500 text-sm">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Trust */}
      <section className="py-12 bg-gray-50 border-y border-gray-100">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <p className="text-gray-400 text-sm">
            Data sourced from BSE/NSE filings &nbsp;&bull;&nbsp;
            India-calibrated WACC (RBI benchmarks) &nbsp;&bull;&nbsp;
            100% transparent models &nbsp;&bull;&nbsp;
            SEBI-compliant disclaimers
          </p>
        </div>
      </section>

      {/* CTA */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-20">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h2 className="text-3xl md:text-4xl font-black text-white mb-4">
            Stop Guessing. Start Valuing.
          </h2>
          <p className="text-gray-400 text-lg mb-10 max-w-xl mx-auto">
            Join thousands of Indian investors making smarter decisions with DCF analysis.
          </p>
          <Link
            href="/auth/signup"
            className="bg-gradient-to-r from-blue-700 to-cyan-500 text-white font-bold px-10 py-4 rounded-xl text-lg hover:opacity-90 transition shadow-lg shadow-blue-500/25 inline-block"
          >
            Launch YieldIQ &mdash; It&apos;s Free &rarr;
          </Link>
          <p className="text-gray-500 text-sm mt-6">Works on mobile. No download required.</p>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] border-t border-white/5 py-12">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <div className="flex flex-col md:flex-row justify-between items-start gap-8">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <img src="/logo.jpeg" alt="YieldIQ" className="w-8 h-8 rounded-full" />
                <span className="text-white font-bold text-lg">YieldIQ</span>
              </div>
              <p className="text-gray-500 text-sm max-w-xs">
                Institutional-grade DCF valuation for Indian retail investors.
              </p>
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
                  <Link href="#" className="block text-gray-500 text-sm hover:text-gray-300 transition">Privacy</Link>
                  <Link href="#" className="block text-gray-500 text-sm hover:text-gray-300 transition">Terms</Link>
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
    // If no token, stay on this page — show landing
  }, [token, onboardingComplete, router])

  // If logged in, show loading while redirecting
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

  // Not logged in — show landing page
  return <LandingContent />
}
