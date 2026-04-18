import Navbar from "@/components/layout/Navbar"
import DesktopNav from "@/components/layout/DesktopNav"
import ErrorBoundary from "@/components/ErrorBoundary"
import PWAInstallBanner from "@/components/PWAInstallBanner"

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <DesktopNav />
      <Navbar />
      <main className="flex-1">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
      <PWAInstallBanner />
    </div>
  )
}
