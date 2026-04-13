"use client"
import { useState } from "react"
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

export default function AccountPage() {
  const { email, tier, analysesToday, analysisLimit, logout, setAuth, token, userId } = useAuthStore()
  const { learnMode, proMode, toggleLearnMode, toggleProMode } = useSettingsStore()
  const [upgrading, setUpgrading] = useState(false)
  const router = useRouter()

  const handleLogout = () => {
    Cookies.remove("yieldiq_token")
    logout()
    router.push("/auth/login")
  }

  const handleUpgrade = async (planId: "starter" | "pro") => {
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
              // Update local auth state
              setAuth(token || "", userId || "", email || "", verifyRes.data.tier, analysesToday, analysisLimit)
              alert(`Upgraded to ${verifyRes.data.tier.toUpperCase()}!`)
              window.location.reload()
            }
          } catch {
            alert("Payment received but verification failed. Contact support.")
          }
        },
      }

      const rzp = new window.Razorpay(options)
      rzp.open()
    } catch {
      alert("Could not initiate payment. Please try again.")
    } finally {
      setUpgrading(false)
    }
  }

  return (
    <div className="max-w-md mx-auto px-4 py-8 space-y-6">
      <h1 className="text-xl font-bold text-gray-900">Account</h1>

      {/* Profile */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-3">
        <p className="text-sm text-gray-500">Email</p>
        <p className="font-medium text-gray-900">{email || "Not signed in"}</p>
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 uppercase">{tier}</span>
          <span className="text-xs text-gray-400">{analysesToday}/{analysisLimit} analyses today</span>
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

          {/* Starter */}
          <div className="bg-white rounded-2xl border-2 border-blue-200 p-5">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="font-bold text-gray-900">Starter</h3>
                <p className="text-xs text-gray-500">For regular investors</p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold text-gray-900">{"\u20b9"}499</p>
                <p className="text-xs text-gray-400">/month</p>
              </div>
            </div>
            <ul className="space-y-1.5 mb-4 text-sm text-gray-600">
              <li>&#10003; 50 analyses per day</li>
              <li>&#10003; Bear/Base/Bull scenarios</li>
              <li>&#10003; Stock screener</li>
              <li>&#10003; PDF reports</li>
              <li>&#10003; Portfolio tracking</li>
            </ul>
            <button onClick={() => handleUpgrade("starter")} disabled={upgrading}
              className="w-full py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50">
              {upgrading ? "Processing..." : "Upgrade to Starter"}
            </button>
          </div>

          {/* Pro */}
          <div className="bg-gradient-to-br from-gray-900 to-gray-800 rounded-2xl p-5 text-white">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="font-bold">Pro</h3>
                <p className="text-xs text-gray-400">For serious investors</p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold">{"\u20b9"}1,999</p>
                <p className="text-xs text-gray-400">/month</p>
              </div>
            </div>
            <ul className="space-y-1.5 mb-4 text-sm text-gray-300">
              <li>&#10003; Everything in Starter</li>
              <li>&#10003; Unlimited analyses</li>
              <li>&#10003; Monte Carlo (1000 sims)</li>
              <li>&#10003; Sensitivity analysis</li>
              <li>&#10003; Excel DCF model</li>
              <li>&#10003; AI analyst chat</li>
            </ul>
            <button onClick={() => handleUpgrade("pro")} disabled={upgrading}
              className="w-full py-3 bg-white text-gray-900 rounded-xl text-sm font-bold hover:bg-gray-100 transition disabled:opacity-50">
              {upgrading ? "Processing..." : "Upgrade to Pro"}
            </button>
          </div>
        </div>
      )}

      {tier !== "free" && (
        <div className="bg-white rounded-2xl border border-gray-100 p-5 text-center">
          <p className="text-sm text-gray-500">Current plan</p>
          <p className="text-lg font-bold text-blue-700 uppercase">{tier}</p>
          <p className="text-xs text-gray-400 mt-1">
            {tier === "starter" ? "₹499/month" : "₹1,999/month"}
          </p>
        </div>
      )}

      <button onClick={handleLogout} className="w-full py-3 text-sm text-red-600 font-medium bg-red-50 rounded-xl hover:bg-red-100 transition">
        Sign out
      </button>

      <p className="text-[10px] text-gray-400 text-center">
        YieldIQ is not registered with SEBI as an investment adviser. All outputs are model estimates only.
      </p>
    </div>
  )
}
