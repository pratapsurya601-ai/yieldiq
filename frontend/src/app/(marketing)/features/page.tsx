"use client"

import Link from "next/link"
// Nav is now provided by (marketing)/layout.tsx via the unified MarketingTopNav
// — see commit "feat(nav): unify navbar across marketing/app/stock pages".

const detailedFeatures = [
  {
    tag: "Core Engine",
    title: "Automated DCF Valuation",
    desc: "Enter a ticker and get a complete discounted cash flow valuation in seconds. YieldIQ pulls revenue, margins, capex, and growth rates from actual filings \u2014 then projects free cash flows and discounts them to present value.",
    bullets: [
      "10-year FCF projections",
      "India-calibrated WACC (RBI benchmarks)",
      "Terminal value with Gordon Growth Model",
    ],
    visual: { icon: "\u{1F4CA}", line1: "Fair Value: \u20B92,450", line2: "+18% Implied Upside", note: "Model output \u00B7 Not investment advice" },
    reversed: false,
  },
  {
    tag: "Quality Analysis",
    title: "Prism Score (6 pillars)",
    desc: "A single 0\u2013100 score blended from six pillars \u2014 Pulse, Quality, Moat, Safety, Growth, Value. Each pillar is computed from audited fundamentals with sector-aware percentile bands, so comparisons are like-for-like.",
    bullets: [
      "Bank-aware Piotroski (4-signal scaled to /9)",
      "Economic moat classification (Wide / Narrow / None)",
      "Sector-percentile valuation bands",
    ],
    visual: { icon: "\u{1F537}", line1: "Prism: 72/100 \u2014 B+", line2: "Moat 88 | Safety 81 | Quality 74", note: null },
    reversed: true,
  },
  {
    tag: "Interactive",
    title: "Live DCF Engine",
    desc: "Disagree with the growth rate? Change it. Want to stress-test with a higher discount rate? Go ahead. Three sliders \u2014 WACC, Terminal Growth, Growth Adjustment \u2014 update the fair value instantly.",
    bullets: [
      "Real-time fair value recalculation",
      "Sensitivity heatmap",
      "Bear / Base / Bull scenarios",
    ],
    visual: { icon: "\u{1F527}", line1: "Adjusted: \u20B92,890", line2: "+32% vs Base Case", note: "WACC: 9.5% | Growth: 12% | Terminal: 3%" },
    reversed: false,
  },
  {
    tag: "Banks & NBFCs",
    title: "Relative Valuation for Financials",
    desc: "Banks, NBFCs, and insurance companies don\u2019t fit DCF models. YieldIQ automatically detects these and shows P/E, P/B, and ROE compared to sector medians \u2014 the right way to value financial stocks.",
    bullets: [
      "25+ Indian banks detected",
      "NBFC-specific P/B benchmarks",
      "Insurance sector medians",
    ],
    visual: { icon: "\u{1F3DB}\uFE0F", line1: "P/E: 14.2x | P/B: 2.1x | ROE: 16.8%", line2: "Discount to Sector Median", note: null },
    reversed: true,
  },
]

const featureGrid = [
  { icon: "\u{1F4CA}", title: "DCF Engine", desc: "Automated 10-year discounted cash flow model with India-calibrated WACC and terminal value." },
  { icon: "\u{1F3AF}", title: "Piotroski F-Score", desc: "9-factor scoring system that measures financial health based on profitability, leverage, and efficiency." },
  { icon: "\u{1F6E1}\uFE0F", title: "Moat Analysis", desc: "Quantitative assessment of competitive advantages \u2014 pricing power, switching costs, network effects." },
  { icon: "\u{1F504}", title: "Reverse DCF", desc: "Solve for the growth rate the market is pricing in today — then judge whether that’s realistic given the company’s history and sector." },
  { icon: "\u{1F4C8}", title: "Bear / Base / Bull Scenarios", desc: "Sector-aware DCF with three explicit scenarios and a weighted fair value — no single-point estimate hiding the uncertainty." },
  { icon: "\u{1F50D}", title: "Screener", desc: "Filter 2,300+ NSE & BSE stocks by valuation, Prism score, moat, sector, and more." },
  { icon: "\u{1FA7A}", title: "Portfolio Health", desc: "Upload your portfolio and see aggregate health, diversification, and valuation metrics." },
  { icon: "\u2728", title: "AI Summary", desc: "LLM-powered plain-English summary of the valuation, risks, and key drivers for any stock." },
]

export default function FeaturesPage() {
  return (
    <div className="bg-white text-gray-900">
      {/* Hero */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-20">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h1 className="text-4xl md:text-5xl font-black text-white mb-4">
            Everything You Need to
            <br />
            <span className="bg-gradient-to-r from-blue-500 to-cyan-400 bg-clip-text text-transparent">Value Indian Stocks.</span>
          </h1>
          <p className="text-gray-400 text-lg">No spreadsheets. No terminal subscriptions. Just clear, data-driven fair value estimates.</p>
        </div>
      </section>

      {/* Detailed Features */}
      <section className="py-20">
        <div className="max-w-5xl mx-auto px-4 space-y-20">
          {detailedFeatures.map((f) => (
            <div key={f.title} className="grid md:grid-cols-2 gap-12 items-center">
              <div className={f.reversed ? "order-2 md:order-2" : ""}>
                <div className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase mb-3">{f.tag}</div>
                <h2 className="text-3xl font-black mb-4">{f.title}</h2>
                <p className="text-gray-500 leading-relaxed mb-4">{f.desc}</p>
                <ul className="space-y-2 text-sm text-gray-600">
                  {f.bullets.map((b) => (
                    <li key={b} className="flex gap-2">
                      <span className="text-blue-500">{"\u2713"}</span>
                      {b}
                    </li>
                  ))}
                </ul>
              </div>
              <div className={`bg-gray-50 rounded-2xl p-8 text-center ${f.reversed ? "order-1 md:order-1" : ""}`}>
                <div className="text-6xl mb-4">{f.visual.icon}</div>
                <div className="text-2xl font-black">{f.visual.line1}</div>
                <div className="text-green-600 font-bold mt-1">{f.visual.line2}</div>
                {f.visual.note && <div className="text-gray-400 text-xs mt-2">{f.visual.note}</div>}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Feature Grid */}
      <section className="py-20 bg-gray-50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6">
          <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase text-center mb-3">All Features</p>
          <h2 className="text-3xl md:text-4xl font-black text-center mb-16">
            The Complete Toolkit
          </h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            {featureGrid.map((f) => (
              <div key={f.title} className="bg-white rounded-2xl p-6 border border-gray-100 hover:border-blue-200 hover:shadow-lg transition">
                <div className="text-3xl mb-3">{f.icon}</div>
                <h3 className="font-bold text-lg mb-2">{f.title}</h3>
                <p className="text-gray-500 text-sm leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-20">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h2 className="text-3xl font-black text-white mb-4">Ready to See What Your Stocks Are Really Worth?</h2>
          <p className="text-gray-400 mb-8">Start with any NSE/BSE ticker. Free.</p>
          <Link
            href="/auth/signup"
            className="bg-gradient-to-r from-blue-700 to-cyan-500 text-white font-bold px-10 py-4 rounded-xl text-lg hover:opacity-90 transition shadow-lg shadow-blue-500/25 inline-block"
          >
            Open YieldIQ &rarr;
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] border-t border-white/5 py-8">
        <div className="max-w-6xl mx-auto px-4 flex flex-col md:flex-row justify-between items-center gap-4">
          <div className="flex items-center gap-2">
            <img src="/logo-new.svg" alt="YieldIQ" className="w-6 h-6 rounded-md" />
            <span className="text-gray-400 text-sm">&copy; 2026 YieldIQ. Made in India.</span>
          </div>
          <div className="flex gap-6 text-gray-500 text-xs">
            <Link href="/" className="hover:text-gray-300">Home</Link>
            <Link href="/pricing" className="hover:text-gray-300">Pricing</Link>
          </div>
          <p className="text-gray-600 text-xs">
            Model output only &mdash; not investment advice. YieldIQ is not registered with SEBI as an investment adviser.
          </p>
        </div>
      </footer>
    </div>
  )
}
