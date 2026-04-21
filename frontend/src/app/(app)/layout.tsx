import Navbar from "@/components/layout/Navbar"
import DesktopNav from "@/components/layout/DesktopNav"
import ErrorBoundary from "@/components/ErrorBoundary"
import PWAInstallBanner from "@/components/PWAInstallBanner"
import BackButton from "@/components/layout/BackButton"

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <DesktopNav />
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
