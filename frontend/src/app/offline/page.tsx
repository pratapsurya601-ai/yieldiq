import type { Metadata } from "next"
import Link from "next/link"

// Offline fallback — served by the service worker (sw.js) when a
// navigation request fails because the device has no connectivity.
// Intentionally a plain server component with zero client JS, zero
// data dependencies: it must render from the SW cache alone.

export const metadata: Metadata = {
  title: "You're offline — YieldIQ",
  description:
    "YieldIQ needs an internet connection for live prices. Reconnect to see real-time valuations.",
  robots: { index: false, follow: false },
}

export default function OfflinePage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 px-4">
      <div className="text-center max-w-md">
        <div className="flex items-center justify-center gap-2 mb-8">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/logo-new.svg"
            alt="YieldIQ"
            className="w-10 h-10 rounded-lg"
          />
          <span className="text-xl font-bold text-gray-900">YieldIQ</span>
        </div>

        <h1 className="text-2xl font-bold text-gray-900 mb-2">
          You&apos;re offline
        </h1>
        <p className="text-sm text-gray-500 mb-8">
          YieldIQ needs an internet connection for live prices. Go back to
          home when you&apos;re online.
        </p>

        <div className="flex items-center justify-center">
          <Link
            href="/"
            className="inline-flex items-center justify-center px-5 py-2.5 min-h-[44px] bg-blue-600 text-white text-sm font-semibold rounded-xl hover:bg-blue-700 active:scale-[0.98] transition"
          >
            Try home page
          </Link>
        </div>
      </div>
    </div>
  )
}
