"use client"
import { useState, useEffect } from "react"
import { useAuthStore } from "@/store/authStore"
import { useSettingsStore } from "@/store/settingsStore"
import { useRouter } from "next/navigation"
import Cookies from "js-cookie"
import api from "@/lib/api"

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
    <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-3">
      <h2 className="text-sm font-semibold text-gray-900">Invite friends, get rewards</h2>
      <p className="text-xs text-gray-500">Share your link. When a friend signs up, you get +5 bonus analyses.</p>
      <div className="flex items-center gap-2">
        <input
          readOnly
          value={referralLink}
          className="flex-1 px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-700 truncate"
        />
        <button
          onClick={handleCopy}
          className="px-4 py-2 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 transition flex-shrink-0"
        >
          {copied ? "Copied!" : "Copy Link"}
        </button>
      </div>
      <div className="flex gap-6 text-center pt-1">
        <div>
          <p className="text-lg font-bold text-gray-900">{stats.referral_count}</p>
          <p className="text-xs text-gray-400">friends invited</p>
        </div>
        <div>
          <p className="text-lg font-bold text-blue-600">{stats.bonus_analyses}</p>
          <p className="text-xs text-gray-400">bonus analyses earned</p>
        </div>
      </div>
    </div>
  )
}

export default function AccountPage() {
  const { email, tier, analysesToday, analysisLimit, logout, setAuth, token, userId } = useAuthStore()
  const { learnMode, proMode, toggleLearnMode, toggleProMode } = useSettingsStore()
  const [upgrading, setUpgrading] = useState(false)
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "err" } | null>(null)
  const router = useRouter()

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
    setUpgrading(true)
    try {
      const { data } = await api.post(`/api/v1/payments/create-order?plan_id=${planId}`)

      // Load Razorpay script if not loaded
      if (!window.Razorpay) {
        await new Promise<void>((resolve) => {
          const script = document.createElement("script")
          script.src = "https://checkout.razorpay.com/v1/checkout.js"
          script.onload = () => resolve()
          document.body.appendChild(script)
        })
      }

      const options = {
        key: data.key_id,
        amount: data.amount,
        currency: data.currency,
        name: "YieldIQ",
        description: data.description,
        order_id: data.order_id,
        prefill: { email: email || "" },
        theme: { color: "#1D4ED8" },
        handler: async (response: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) => {
          // Verify payment on backend
          try {
            const verifyRes = await api.post("/api/v1/payments/verify", null, {
              params: {
                razorpay_order_id: response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
                plan_id: planId,
              },
            })
            if (verifyRes.data.ok) {
              // Update local auth state — no reload needed, Zustand subscribers re-render.
              setAuth(token || "", userId || "", email || "", verifyRes.data.tier, analysesToday, analysisLimit)
              showToast(`Upgraded to ${verifyRes.data.tier.toUpperCase()} \u2014 enjoy!`, "ok")
            }
          } catch {
            showToast("Payment received but verification failed. Email support@yieldiq.in", "err")
          }
        },
      }

      const rzp = new window.Razorpay(options)
      rzp.open()
    } catch {
      showToast("Could not initiate payment. Please try again.", "err")
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
      <h1 className="text-xl font-bold text-gray-900">Account</h1>

      {/* Profile */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-3">
        <div className="flex items-center gap-4">
          {/* YieldIQ logo */}
          <img src="/logo-new.svg" alt="YieldIQ" className="w-14 h-14 rounded-xl flex-shrink-0 shadow-md" />
          <div className="flex-1 min-w-0">
            <p className="font-medium text-gray-900 truncate">{email || "Not signed in"}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 uppercase">{tier}</span>
              <span className="text-xs text-gray-400">
                {analysisLimit >= 999999 ? "Unlimited analyses" : `${analysesToday}/${analysisLimit} analyses today`}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Settings */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-4">
        <h2 className="text-sm font-semibold text-gray-900">Settings</h2>
        <label className="flex items-center justify-between">
          <span className="text-sm text-gray-700">Learn Mode</span>
          <button onClick={toggleLearnMode}
            className={`w-10 h-6 rounded-full transition ${learnMode ? "bg-blue-600" : "bg-gray-200"}`}>
            <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform ${learnMode ? "translate-x-5" : "translate-x-1"}`} />
          </button>
        </label>
        {tier !== "free" && (
          <label className="flex items-center justify-between">
            <span className="text-sm text-gray-700">Pro Mode</span>
            <button onClick={toggleProMode}
              className={`w-10 h-6 rounded-full transition ${proMode ? "bg-blue-600" : "bg-gray-200"}`}>
              <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform ${proMode ? "translate-x-5" : "translate-x-1"}`} />
            </button>
          </label>
        )}
      </div>

      {/* Pricing Cards */}
      {tier === "free" && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">Upgrade your plan</h2>

          {/* Pro */}
          <div className="relative bg-white rounded-2xl border-2 border-blue-200 p-5">
            <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-blue-600 text-white text-[10px] font-bold uppercase tracking-wider px-3 py-1 rounded-full shadow-sm">
              Most Popular
            </span>
            <div className="flex items-center justify-between mb-3 mt-1">
              <div>
                <h3 className="font-bold text-gray-900">Pro</h3>
                <p className="text-xs text-gray-500">For regular investors</p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold text-gray-900">{"\u20b9"}299</p>
                <p className="text-xs text-gray-400">/month</p>
              </div>
            </div>
            <ul className="space-y-1.5 mb-4 text-sm text-gray-600">
              <li>&#10003; Unlimited analyses</li>
              <li>&#10003; Interactive DCF sliders</li>
              <li>&#10003; Sensitivity heatmap</li>
              <li>&#10003; Monte Carlo (1,000 sims)</li>
              <li>&#10003; PDF & Excel export</li>
              <li>&#10003; 50-stock watchlist + 10 alerts</li>
            </ul>
            <button onClick={() => handleUpgrade("pro")} disabled={upgrading}
              className="w-full py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50">
              {upgrading ? "Processing..." : "Upgrade to Pro \u2014 \u20b9299/mo"}
            </button>
          </div>

          {/* Analyst */}
          <div className="bg-gradient-to-br from-gray-900 to-gray-800 rounded-2xl p-5 text-white">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="font-bold">Analyst</h3>
                <p className="text-xs text-gray-400">For serious investors</p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold">{"\u20b9"}799</p>
                <p className="text-xs text-gray-400">/month</p>
              </div>
            </div>
            <ul className="space-y-1.5 mb-4 text-sm text-gray-300">
              <li>&#10003; Everything in Pro</li>
              <li>&#10003; API access (500 calls/day)</li>
              <li>&#10003; Bulk screener</li>
              <li>&#10003; Unlimited watchlist & alerts</li>
              <li>&#10003; Google Sheets sync</li>
              <li>&#10003; Priority support</li>
            </ul>
            <button onClick={() => handleUpgrade("analyst")} disabled={upgrading}
              className="w-full py-3 bg-white text-gray-900 rounded-xl text-sm font-bold hover:bg-gray-100 transition disabled:opacity-50">
              {upgrading ? "Processing..." : "Upgrade to Analyst \u2014 \u20b9799/mo"}
            </button>
          </div>
        </div>
      )}

      {tier !== "free" && (
        <div className="bg-white rounded-2xl border border-gray-100 p-5 text-center">
          <p className="text-sm text-gray-500">Current plan</p>
          <p className="text-lg font-bold text-blue-700 uppercase">{tier}</p>
          <p className="text-xs text-gray-400 mt-1">
            {tier === "pro" || tier === "starter" ? "\u20b9299/month" : tier === "analyst" ? "\u20b9799/month" : ""}
          </p>
        </div>
      )}

      {/* Share & Earn — Referral Section */}
      <ReferralSection />

      <p className="text-[10px] text-gray-400 text-center">
        YieldIQ is not registered with SEBI as an investment adviser. All outputs are model estimates only.
      </p>

      {/* Sign out — less prominent, at the very bottom */}
      <button onClick={handleLogout} className="w-full py-2 text-sm text-gray-400 font-medium hover:text-red-500 transition text-center">
        Sign out
      </button>
    </div>
  )
}
