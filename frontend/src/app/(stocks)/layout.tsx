import Link from "next/link"

export default function StocksLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-white">
      {/* Lightweight header */}
      <header className="sticky top-0 z-50 bg-white border-b border-gray-100">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <img src="/logo-new.svg" alt="YieldIQ" className="w-7 h-7 rounded-lg" />
            <span className="font-bold text-gray-900">YieldIQ</span>
          </Link>
          <div className="flex items-center gap-4">
            <Link href="/nifty50" className="text-sm text-gray-500 hover:text-gray-900 transition hidden sm:block">
              Nifty 50
            </Link>
            <Link
              href="/auth/signup"
              className="bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 transition"
            >
              Start Free &rarr;
            </Link>
          </div>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      {/* CTA footer */}
      <footer className="bg-gray-50 border-t border-gray-100">
        <div className="max-w-4xl mx-auto px-4 py-12 text-center">
          <h2 className="text-2xl font-black text-gray-900 mb-3">
            Want the full interactive analysis?
          </h2>
          <p className="text-gray-500 mb-6">
            Interactive DCF sliders, sensitivity heatmap, Monte Carlo simulation, and more.
          </p>
          <Link
            href="/auth/signup"
            className="inline-block bg-blue-600 text-white font-bold px-8 py-4 rounded-xl text-lg hover:bg-blue-700 transition shadow-lg shadow-blue-500/20"
          >
            Start Valuing Stocks &mdash; Free &rarr;
          </Link>
          <p className="text-[10px] text-gray-400 mt-6">
            Model estimates only &mdash; not investment advice. YieldIQ is not registered with SEBI as an investment adviser.
          </p>
        </div>
        <div className="border-t border-gray-100 py-4">
          <div className="max-w-6xl mx-auto px-4 flex items-center justify-between text-xs text-gray-400">
            <span>&copy; 2026 YieldIQ. Made in India.</span>
            <div className="flex gap-4">
              <Link href="/terms" className="hover:text-gray-600 transition">Terms</Link>
              <Link href="/privacy" className="hover:text-gray-600 transition">Privacy</Link>
            </div>
          </div>
        </div>
      </footer>
    </div>
  )
}
