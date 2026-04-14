// analytics.ts — track specific user actions in YieldIQ
declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void
  }
}

export function trackEvent(
  eventName: string,
  params?: Record<string, string | number | boolean>
) {
  if (typeof window === "undefined") return
  if (window.gtag) {
    window.gtag("event", eventName, params)
  }
}

export function trackStockAnalysed(ticker: string, verdict: string, score: number) {
  trackEvent("stock_analysed", { ticker, verdict, score })
}

export function trackSectionViewed(section: string, ticker: string) {
  trackEvent("section_viewed", { section, ticker })
}

export function trackExportUsed(format: string, ticker: string) {
  trackEvent("export_used", { format, ticker })
}

export function trackSearchUsed(query: string) {
  trackEvent("search_used", { query })
}

export function trackUpgradeClicked(plan: string, source: string) {
  trackEvent("upgrade_clicked", { plan, source })
}

export function trackSignupCompleted(source: string) {
  trackEvent("signup_completed", { source })
}
