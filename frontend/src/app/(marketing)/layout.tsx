import TrustFooter from "@/components/layout/TrustFooter"

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <TrustFooter />
    </>
  )
}
