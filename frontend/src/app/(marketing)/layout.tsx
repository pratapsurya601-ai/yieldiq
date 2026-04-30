import MarketingTopNav from "@/components/marketing/MarketingTopNav"
import TrustFooter from "@/components/layout/TrustFooter"

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <MarketingTopNav />
      {children}
      <TrustFooter />
    </>
  )
}
