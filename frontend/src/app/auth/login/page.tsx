"use client"
import { useState } from "react"
import { useRouter } from "next/navigation"
import { login } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import Cookies from "js-cookie"
import Link from "next/link"

export default function LoginPage() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const router = useRouter()
  const { setAuth } = useAuthStore()

  const handleLogin = async () => {
    setError("")
    setLoading(true)
    try {
      const res = await login(email, password)
      Cookies.set("yieldiq_token", res.access_token, { expires: 7 })
      setAuth(res.access_token, res.user_id, res.email, res.tier, res.analyses_today, res.analysis_limit)
      // Check if onboarding is complete
      const settings = JSON.parse(localStorage.getItem("yieldiq-settings") || "{}")
      const onboardingDone = settings?.state?.onboardingComplete
      router.push(onboardingDone ? "/home" : "/onboarding")
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Login failed"
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-gray-50">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <img src="/logo.jpeg" alt="YieldIQ" className="w-16 h-16 rounded-full mx-auto mb-3" />
          <h1 className="text-2xl font-bold text-gray-900">YieldIQ</h1>
          <p className="text-sm text-gray-500 mt-1">Know if a stock is undervalued</p>
        </div>

        <div className="bg-white rounded-2xl border border-gray-100 p-6 space-y-4">
          <h2 className="text-lg font-semibold text-gray-900">Sign in</h2>

          {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}

          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="Email" className="w-full px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleLogin()}
            placeholder="Password" className="w-full px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />

          <button onClick={handleLogin} disabled={loading}
            className="w-full py-3 bg-blue-600 text-white rounded-xl text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50">
            {loading ? "Signing in..." : "Sign in"}
          </button>

          <p className="text-center text-sm text-gray-500">
            No account? <Link href="/auth/signup" className="text-blue-600 font-medium hover:underline">Create one</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
