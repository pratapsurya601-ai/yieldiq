"use client"
import { useState, useEffect, useRef, Suspense } from "react"
import { useAuthStore } from "@/store/authStore"
import { useSettingsStore } from "@/store/settingsStore"
import { useRouter, useSearchParams } from "next/navigation"
import Cookies from "js-cookie"
import api from "@/lib/api"
import ThemeToggle from "@/components/layout/ThemeToggle"
import {
  trackUpgradeClicked,
  trackCheckoutOpened,
  trackSubscriptionStarted,
  trackCheckoutFailed,
} from "@/lib/analytics"

declare global {
  interface Window {
    Razorpay: new (options: Record<string, unknown>) => { open: () => void }
  }
}

function ReferralSection() {
  const [referralCode, setReferralCode] = useState("")
  const [referralLink, setReferralLink] = useState("")
  const [stats, setStats] = useState({ referral_count: 0, bonus_analyses: 0 })
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api.get("/api/v1/referral/code").then((r) => {
      setReferralCode(r.data.referral_code)
      setReferralLink(r.data.referral_link)
    }).catch(() => {})
    api.get("/api/v1/referral/stats").then((r) => {
      setStats({ referral_count: r.data.referral_count, bonus_analyses: r.data.bonus_analyses })
    }).catch(() => {})
  }, [])

  const handleCopy = () => {
    if (referralLink) {
      navigator.clipboard.writeText(referralLink)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  if (!referralCode) return null

  return (
    <div className="bg-bg dark:bg-surface rounded-2xl border border-border p-5 space-y-3">
      <h2 className="text-sm font-semibold text-ink">Invite friends, get rewards</h2>
      <p className="text-xs text-caption">Share your link. When a friend signs up, you get +5 bonus analyses.</p>
      <div className="flex items-center gap-2">
        <input
          readOnly
          value={referralLink}
          className="flex-1 px-3 py-2 bg-surface border border-border rounded-lg text-xs text-body truncate"
        />
        <button
          onClick={handleCopy}
          className="px-4 py-2 min-h-[40px] bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 active:scale-[0.97] transition flex-shrink-0"
        >
          {copied ? "Copied!" : "Copy Link"}
        </button>
      </div>
      <div className="flex gap-6 text-center pt-1">
        <div>
          <p className="text-lg font-bold text-ink">{stats.referral_count}</p>
          <p className="text-xs text-caption">friends invited</p>
        </div>
        <div>
          <p className="text-lg font-bold text-brand">{stats.bonus_analyses}</p>
          <p className="text-xs text-caption">bonus analyses earned</p>
        </div>
      </div>
    </div>
  )
}

export default function AccountPage() {
  return (
    <Suspense fallback={<div className="max-w-md md:max-w-2xl mx-auto px-4 py-8" />}>
      <AccountInner />
    </Suspense>
  )
}

function AccountInner() {
  const { email, tier, analysesToday, analysisLimit, logout, setAuth, token, userId } = useAuthStore()
  const { learnMode, proMode, toggleLearnMode, toggleProMode } = useSettingsStore()
  const [upgrading, setUpgrading] = useState(false)
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "err" } | null>(null)
  const router = useRouter()
  const searchParams = useSearchParams()
  const upgradeHint = searchParams.get("upgrade") as "pro" | "analyst" | null
  const upgradeSectionRef = useRef<HTMLDivElement>(null)

  // If the user came from the pricing page with ?upgrade=pro|analyst,
  // jump them to the upgrade cards so they don't have to hunt.
  useEffect(() => {
    if (upgradeHint && upgradeSectionRef.current) {
      upgradeSectionRef.current.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [upgradeHint])

  const showToast = (msg: string, tone: "ok" | "err" = "ok") => {
    setToast({ msg, tone })
    setTimeout(() => setToast(null), 4000)
  }

  const handleLogout = () => {
    Cookies.remove("yieldiq_token")
    logout()
    router.push("/auth/login")
  }

  const handleUpgrade = async (planId: "pro" | "analyst") => {
    // GA4: upgrade_clicked — entry point of the paid funnel. Source
    // differentiates pricing-driven vs. account-page clicks so we can
    // see which surface converts better.
    const hintedBilling = (searchParams.get("billing") === "annual" ? "annual" : "monthly") as "monthly" | "annual"
    trackUpgradeClicked(planId, `account:${hintedBilling}`)
    setUpgrading(true)
    try {
      // 2026-04-21: switched from one-time Orders API (/create-order)
      // to Razorpay Subscriptions API (/create-subscription) so monthly
      // and annual plans actually auto-renew instead of being single
      // charges. The ₹99 PAYG path still uses /create-order — this
      // handler only triggers for analyst/pro subscriptions.
      const { data } = await api.post(
        `/api/v1/payments/create-subscription?plan_id=${planId}&billing=${hintedBilling}`
      )

      // Load Razorpay script if not loaded
      if (!window.Razorpay) {
        try {
          await new Promise<void>((resolve, reject) => {
            const script = document.createElement("script")
            script.src = "https://checkout.razorpay.com/v1/checkout.js"
            script.onload = () => resolve()
            script.onerror = () => reject(new Error("script_load_failed"))
            document.body.appendChild(script)
          })
        } catch {
          trackCheckoutFailed(planId, "script_load")
          throw new Error("Razorpay script failed to load")
        }
      }

      // GA4: checkout_opened — user committed to attempt payment.
      trackCheckoutOpened(planId, hintedBilling)

      const options = {
        key: data.key_id,
        // For subscriptions we pass subscription_id (not order_id).
        // Razorpay checkout handles the first charge + schedules
        // the renewals off this subscription_id.
        subscription_id: data.subscription_id,
        name: "YieldIQ",
        description: data.description,
        prefill: { email: email || "" },
        theme: { color: "#1D4ED8" },
        modal: {
          // GA4: user dismissed the checkout modal without paying
          ondismiss: () => trackCheckoutFailed(planId, "cancelled"),
        },
        handler: async (response: {
          razorpay_subscription_id: string
          razorpay_payment_id: string
          razorpay_signature: string
        }) => {
          // Verify subscription signature on backend and flip tier.
          try {
            const verifyRes = await api.post("/api/v1/payments/verify-subscription", null, {
              params: {
                razorpay_subscription_id: response.razorpay_subscription_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
                plan_id: planId,
              },
            })
            if (verifyRes.data.ok) {
              // GA4: the money event. Fired after backend verification so
              // we never count a charge that failed signature validation.
              trackSubscriptionStarted(planId, hintedBilling)
              // Update local auth state — no reload needed, Zustand subscribers re-render.
              setAuth(token || "", userId || "", email || "", verifyRes.data.tier, analysesToday, analysisLimit)
              showToast(`Subscribed to ${verifyRes.data.tier.toUpperCase()} \u2014 enjoy!`, "ok")
            } else {
              trackCheckoutFailed(planId, "verify")
            }
          } catch {
            trackCheckoutFailed(planId, "verify")
            showToast("Payment received but verification failed. Email support@yieldiq.in", "err")
          }
        },
      }

      const rzp = new window.Razorpay(options)
      rzp.open()
    } catch (err) {
      // Distinguishes init failure (create-subscription 4xx/5xx,
      // SDK init) from the script-load case we already tagged above.
      // 503 from backend = Razorpay plan ID env var not set yet; show
      // a specific message so ops can tell the user exactly why.
      const msg = (err as Error)?.message || ""
      const axErr = err as {
        response?: { status?: number; data?: { detail?: string } }
      }
      const status = axErr?.response?.status
      const backendDetail = axErr?.response?.data?.detail
      if (!msg.includes("Razorpay script failed")) {
        trackCheckoutFailed(planId, "init")
      }
      if (status === 503) {
        showToast("Plan not live yet — email support@yieldiq.in to get early access.", "err")
      } else if (backendDetail) {
        // Backend-provided detail carries the real Razorpay error
        // (e.g. "Subscription init failed: BadRequestError: The ID
        // provided is invalid or could not be found"). Surface it so
        // ops can self-diagnose without Railway log access.
        showToast(backendDetail, "err")
      } else {
        showToast("Could not initiate payment. Please try again.", "err")
      }
    } finally {
      setUpgrading(false)
    }
  }

  return (
    <div className="max-w-md md:max-w-2xl mx-auto px-4 py-8 space-y-6 pb-20">
      {toast && (
        <div
          className={`fixed bottom-20 md:top-20 md:bottom-auto left-1/2 -translate-x-1/2 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg z-50 max-w-sm text-center ${
            toast.tone === "err" ? "bg-red-600" : "bg-gray-900"
          }`}
          role="status"
        >
          {toast.msg}
        </div>
      )}
      <h1 className="text-xl font-bold text-ink">Account</h1>

      {/* Profile */}
      <div className="bg-bg dark:bg-surface rounded-2xl border border-border p-5 space-y-3">
        <div className="flex items-center gap-4">
          {/* YieldIQ logo */}
          <img src="/logo-new.svg" alt="YieldIQ" className="w-14 h-14 rounded-xl flex-shrink-0 shadow-md" />
          <div className="flex-1 min-w-0">
            <p className="font-medium text-ink truncate">{email || "Not signed in"}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 uppercase">{tier}</span>
              <span className="text-xs text-body">
                {analysisLimit >= 999999 ? "Unlimited analyses" : `${analysesToday}/${analysisLimit} analyses today`}
              </span>
            </div>
          </div>
        </div>
        {/* Display-name editor link (PR #72). Sub-route /account/profile
            handles the input + 3-edit lifetime cap. */}
        <a
          href="/account/profile"
          className="flex items-center justify-between rounded-xl border border-border px-3 py-3 hover:bg-surface dark:hover:bg-bg transition"
        >
          <div className="flex flex-col">
            <span className="text-sm font-medium text-ink">Display name</span>
            <span className="text-xs text-caption">How we greet you across the app</span>
          </div>
          <span className="text-sm text-caption" aria-hidden>›</span>
        </a>
      </div>

      {/* Settings */}
      <div className="bg-bg dark:bg-surface rounded-2xl border border-border p-5 space-y-4">
        <h2 className="text-sm font-semibold text-ink">Settings</h2>
        <div className="flex items-center justify-between">
          <span className="text-sm text-body">Theme</span>
          <ThemeToggle />
        </div>
        <label className="flex items-center justify-between">
          <span className="text-sm text-body">Learn Mode</span>
          <button onClick={toggleLearnMode}
            className={`w-10 h-6 rounded-full transition ${learnMode ? "bg-blue-600" : "bg-gray-200 dark:bg-gray-700"}`}>
            <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform ${learnMode ? "translate-x-5" : "translate-x-1"}`} />
          </button>
        </label>
        {tier !== "free" && (
          <label className="flex items-center justify-between">
            <span className="text-sm text-body">Pro Mode</span>
            <button onClick={toggleProMode}
              className={`w-10 h-6 rounded-full transition ${proMode ? "bg-blue-600" : "bg-gray-200 dark:bg-gray-700"}`}>
              <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform ${proMode ? "translate-x-5" : "translate-x-1"}`} />
            </button>
          </label>
        )}
      </div>

      {/* Pricing Cards */}
      {tier === "free" && (
        <div ref={upgradeSectionRef} className="space-y-3 scroll-mt-20">
          <h2 className="text-sm font-semibold text-ink">Upgrade your plan</h2>

          {/* Analyst — sweet-spot tier, most users start here */}
          <div className={`relative bg-bg dark:bg-surface rounded-2xl border-2 p-5 transition ${upgradeHint === "analyst" ? "border-blue-500 ring-4 ring-blue-100 dark:ring-blue-900/40" : "border-blue-200 dark:border-blue-900"}`}>
            <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-blue-600 text-white text-[10px] font-bold uppercase tracking-wider px-3 py-1 rounded-full shadow-sm">
              Most Popular
            </span>
            <div className="flex items-center justify-between mb-3 mt-1">
              <div>
                <h3 className="font-bold text-ink">Analyst</h3>
                <p className="text-xs text-caption">For serious DIY investors</p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold text-ink">{"\u20b9"}799</p>
                <p className="text-xs text-body">/month</p>
              </div>
            </div>
            <ul className="space-y-1.5 mb-4 text-sm text-body">
              <li>&#10003; Unlimited analyses</li>
              <li>&#10003; Portfolio Prism + Health score</li>
              <li>&#10003; Multi-account portfolios (5 brokers)</li>
              <li>&#10003; AI summaries + Concall AI</li>
              <li>&#10003; Time Machine + Tax Report</li>
              <li>&#10003; Compare up to 3 stocks</li>
            </ul>
            <button onClick={() => handleUpgrade("analyst")} disabled={upgrading}
              className="w-full py-3 min-h-[44px] bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700 active:scale-[0.98] transition disabled:opacity-50 disabled:active:scale-100">
              {upgrading ? "Processing..." : "Upgrade to Analyst \u2014 \u20b9799/mo"}
            </button>
          </div>

          {/* Pro — power user tier with exports + API */}
          {/* dark-mode-allow: card is intentionally always-dark (premium "midnight"
              treatment) so the from-gray-900/to-gray-800 + text-gray-300/400 stays
              fixed in both modes. */}
          <div className={`bg-gradient-to-br from-gray-900 to-gray-800 rounded-2xl p-5 text-white transition ${upgradeHint === "pro" ? "ring-4 ring-blue-400" : ""}`}>
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="font-bold">Pro</h3>
                <p className="text-xs text-gray-400">For bloggers, advisors, power users</p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold">{"\u20b9"}1,499</p>
                <p className="text-xs text-gray-400">/month</p>
              </div>
            </div>
            <ul className="space-y-1.5 mb-4 text-sm text-gray-300">
              <li>&#10003; Everything in Analyst</li>
              <li>&#10003; CSV + PDF export</li>
              <li>&#10003; API access (100 req/day)</li>
              <li>&#10003; 10 broker accounts</li>
              <li>&#10003; Save + share custom screens</li>
              <li>&#10003; Priority compute + earnings-day digest</li>
            </ul>
            <button onClick={() => handleUpgrade("pro")} disabled={upgrading}
              className="w-full py-3 min-h-[44px] bg-white text-gray-900 rounded-xl text-sm font-bold hover:bg-gray-100 active:scale-[0.98] transition disabled:opacity-50 disabled:active:scale-100">
              {upgrading ? "Processing..." : "Upgrade to Pro \u2014 \u20b91,499/mo"}
            </button>
          </div>
        </div>
      )}

      {tier !== "free" && (
        <div className="bg-bg dark:bg-surface rounded-2xl border border-border p-5 text-center">
          <p className="text-sm text-caption">Current plan</p>
          <p className="text-lg font-bold text-blue-700 dark:text-blue-300 uppercase">{tier}</p>
          <p className="text-xs text-body mt-1">
            {tier === "analyst" ? "\u20b9799/month" : tier === "pro" ? "\u20b91,499/month" : ""}
          </p>
        </div>
      )}

      {/* Share & Earn — Referral Section */}
      <ReferralSection />

      <p className="text-xs text-body text-center">
        YieldIQ is not registered with SEBI as an investment adviser. All outputs are model estimates only.
      </p>

      {/* Sign out — less prominent, at the very bottom */}
      <button onClick={handleLogout} className="w-full py-2 text-sm text-body font-medium hover:text-red-500 transition text-center">
        Sign out
      </button>
    </div>
  )
}
