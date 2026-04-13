"use client"
import { useAuthStore } from "@/store/authStore"
import { useSettingsStore } from "@/store/settingsStore"
import { useRouter } from "next/navigation"
import Cookies from "js-cookie"

export default function AccountPage() {
  const { email, tier, analysesToday, analysisLimit, logout } = useAuthStore()
  const { learnMode, proMode, toggleLearnMode, toggleProMode } = useSettingsStore()
  const router = useRouter()

  const handleLogout = () => {
    Cookies.remove("yieldiq_token")
    logout()
    router.push("/auth/login")
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

      {/* Upgrade */}
      {tier === "free" && (
        <div className="bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-5 text-white">
          <h2 className="font-bold mb-1">Upgrade to Starter</h2>
          <p className="text-sm text-blue-100 mb-3">50 analyses/day, scenarios, screener, PDF reports</p>
          <p className="text-2xl font-bold">{"\u20b9"}499<span className="text-sm font-normal text-blue-200">/month</span></p>
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
