import Navbar from "@/components/layout/Navbar"
import ErrorBoundary from "@/components/ErrorBoundary"
import PWAInstallBanner from "@/components/PWAInstallBanner"

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />
      <main className="flex-1">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
      <PWAInstallBanner />
    </div>
  )
}
