import Link from "next/link"

export default function NotFound() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 px-4">
      <div className="text-center max-w-md">
        <div className="flex items-center justify-center gap-2 mb-8">
          <img src="/logo-new.svg" alt="YieldIQ" className="w-10 h-10 rounded-lg" />
          <span className="text-xl font-bold text-gray-900">YieldIQ</span>
        </div>

        <h1 className="text-6xl font-black text-gray-200 mb-4">404</h1>
        <h2 className="text-xl font-bold text-gray-900 mb-2">Page not found</h2>
        <p className="text-sm text-gray-500 mb-8">
          The page you&apos;re looking for doesn&apos;t exist or has been moved.
        </p>

        <div className="flex items-center justify-center gap-3">
          <Link
            href="/home"
            className="inline-flex items-center justify-center px-5 py-2.5 min-h-[44px] bg-blue-600 text-white text-sm font-semibold rounded-xl hover:bg-blue-700 active:scale-[0.98] transition"
          >
            Go Home
          </Link>
          <Link
            href="/search"
            className="inline-flex items-center justify-center px-5 py-2.5 min-h-[44px] bg-white text-gray-700 text-sm font-semibold rounded-xl border border-gray-200 hover:bg-gray-50 active:scale-[0.98] transition"
          >
            Search Stocks
          </Link>
        </div>
      </div>
    </div>
  )
}
