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

/** Fired when the user lands on the marketing /pricing page. Also captures
 *  billing cadence (monthly/annual) + whether they're logged in so we can
 *  split the funnel between cold traffic and existing users. */
export function trackPricingViewed(
  loggedIn: boolean,
  tier: string,
) {
  trackEvent("pricing_viewed", { logged_in: loggedIn, tier })
}

/** Fired when the user toggles billing between monthly and annual. Useful
 *  for seeing whether the savings badge actually drives annual clicks. */
export function trackBillingToggled(billing: "monthly" | "annual") {
  trackEvent("billing_toggled", { billing })
}

/** Fired when the Razorpay checkout modal opens (user committed to attempt
 *  payment). Between upgrade_clicked and this, we lose some share to
 *  script-load failures. */
export function trackCheckoutOpened(plan: string, billing: string) {
  trackEvent("checkout_opened", { plan, billing })
}

/** Fired when the backend verifies a successful Razorpay payment. This is
 *  the money event — Google Ads + Meta can optimise on it. */
export function trackSubscriptionStarted(plan: string, billing: string) {
  trackEvent("subscription_started", { plan, billing })
}

/** Fired when the payment flow errors (user-cancel vs. script failure vs.
 *  backend verify failure). Tag the reason so we can triage. */
export function trackCheckoutFailed(
  plan: string,
  reason: "script_load" | "init" | "verify" | "cancelled",
) {
  trackEvent("checkout_failed", { plan, reason })
}
