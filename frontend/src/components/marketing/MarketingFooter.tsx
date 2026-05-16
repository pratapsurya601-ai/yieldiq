import Link from "next/link"

export default function MarketingFooter() {
  return (
    <footer className="bg-[#0F172A] text-gray-300 border-t border-white/5 mt-16">
      <div className="max-w-6xl mx-auto px-4 py-12">
        {/* Top row — link grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-8 mb-10">
          {/* Discover */}
          <div>
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">Discover</h3>
            <ul className="space-y-2 text-sm">
              <li><Link href="/nifty50" className="hover:text-white transition">Nifty 50 Dashboard</Link></li>
              <li><Link href="/nifty-bank" className="hover:text-white transition">Nifty Bank</Link></li>
              <li><Link href="/nifty-it" className="hover:text-white transition">Nifty IT</Link></li>
              <li><Link href="/earnings-calendar" className="hover:text-white transition">Earnings Calendar</Link></li>
              <li><Link href="/news" className="hover:text-white transition">News &amp; Filings</Link></li>
            </ul>
          </div>

          {/* Screens */}
          <div>
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">Filters</h3>
            <ul className="space-y-2 text-sm">
              <li><Link href="/screens/high-roce" className="hover:text-white transition">High ROCE</Link></li>
              <li><Link href="/screens/low-pe-quality" className="hover:text-white transition">Low P/E + Quality</Link></li>
              <li><Link href="/screens/wide-moat" className="hover:text-white transition">Wide Moat</Link></li>
              <li><Link href="/screens/debt-free" className="hover:text-white transition">Debt-Free</Link></li>
              <li><Link href="/screens/high-piotroski" className="hover:text-white transition">High Piotroski</Link></li>
            </ul>
          </div>

          {/* Learn */}
          <div>
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">Learn</h3>
            <ul className="space-y-2 text-sm">
              <li><Link href="/blog" className="hover:text-white transition">Blog</Link></li>
              <li><Link href="/blog/what-is-dcf-valuation" className="hover:text-white transition">What is DCF?</Link></li>
              <li><Link href="/blog/piotroski-f-score-explained" className="hover:text-white transition">Piotroski F-Score</Link></li>
              <li><Link href="/blog/margin-of-safety-explained" className="hover:text-white transition">Margin of Safety</Link></li>
              <li><Link href="/how-it-works" className="hover:text-white transition">How YieldIQ works</Link></li>
              <li><Link href="/blog/stcg-ltcg-tax-fy-2025-26" className="hover:text-white transition">Capital Gains Tax</Link></li>
            </ul>
          </div>

          {/* Company */}
          <div>
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">YieldIQ</h3>
            <ul className="space-y-2 text-sm">
              <li><Link href="/features" className="hover:text-white transition">Features</Link></li>
              <li><Link href="/pricing" className="hover:text-white transition">Pricing</Link></li>
              <li><Link href="/auth/signup" className="hover:text-white transition">Get Started</Link></li>
              <li><Link href="/home" className="hover:text-white transition">App Home</Link></li>
              <li><Link href="/portfolio" className="hover:text-white transition">My Portfolio</Link></li>
            </ul>
          </div>
        </div>

        {/* Bottom row */}
        <div className="border-t border-white/5 pt-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-gray-500">
          <div className="flex items-center gap-2">
            <img src="/logo-new.svg" alt="YieldIQ" className="w-5 h-5 rounded" />
            <span>&copy; 2026 YieldIQ &middot; Made in India</span>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/terms" className="hover:text-gray-300 transition">Terms</Link>
            <Link href="/privacy" className="hover:text-gray-300 transition">Privacy</Link>
            <Link href="/methodology" className="hover:text-gray-300 transition">Methodology</Link>
            <Link href="/errata" className="hover:text-gray-300 transition">Errata</Link>
            <Link href="/status" className="hover:text-gray-300 transition">Status</Link>
          </div>
          <p className="text-[10px] text-gray-600 max-w-md text-center sm:text-right">
            Model output only &mdash; not investment advice. YieldIQ is not registered with SEBI as an investment adviser.
          </p>
        </div>
      </div>
    </footer>
  )
}
