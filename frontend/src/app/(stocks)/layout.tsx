import MarketingTopNav from "@/components/marketing/MarketingTopNav"
import MarketingFooter from "@/components/marketing/MarketingFooter"

export default function StocksLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-white">
      <MarketingTopNav />
      <main className="flex-1">{children}</main>
      <MarketingFooter />
    </div>
  )
}
