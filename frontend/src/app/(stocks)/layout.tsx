import MarketingTopNav from "@/components/marketing/MarketingTopNav"
import TrustFooter from "@/components/layout/TrustFooter"
import BackButton from "@/components/layout/BackButton"

export default function StocksLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-white">
      <MarketingTopNav />
      <div className="px-4 sm:px-6 lg:px-8 pt-3 max-w-6xl mx-auto w-full">
        <BackButton fallbackHref="/" />
      </div>
      <main className="flex-1">{children}</main>
      <TrustFooter />
    </div>
  )
}
