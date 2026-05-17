import MarketingTopNav from "@/components/marketing/MarketingTopNav"
import Navbar from "@/components/layout/Navbar"
import ErrorBoundary from "@/components/ErrorBoundary"
import PWAInstallBanner from "@/components/PWAInstallBanner"
import BackButton from "@/components/layout/BackButton"
import EmailVerifyBanner from "@/components/EmailVerifyBanner"

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Soft email-verify nudge — hidden when logged-out or verified.
          Mounted above all in-app pages so users see the prompt on
          home / analysis / portfolio / account / etc., but not on the
          marketing tree. */}
      <EmailVerifyBanner />
      {/* Desktop: unified top nav (same items as marketing/stocks) */}
      <div className="hidden md:block">
        <MarketingTopNav />
      </div>
      {/* Mobile: bottom-tab nav for the workspace */}
      <Navbar />
      <div className="px-4 sm:px-6 lg:px-8 pt-3 max-w-6xl mx-auto w-full">
        <BackButton fallbackHref="/home" />
      </div>
      <main className="flex-1">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
      <PWAInstallBanner />
    </div>
  )
}
