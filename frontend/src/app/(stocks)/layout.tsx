import MarketingTopNav from "@/components/marketing/MarketingTopNav"
import TrustFooter from "@/components/layout/TrustFooter"

export default function StocksLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-white">
      <MarketingTopNav />
      <main className="flex-1">{children}</main>
      <TrustFooter />
    </div>
  )
}
