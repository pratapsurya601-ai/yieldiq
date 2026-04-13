"use client"
import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/store/authStore"
import { useSettingsStore } from "@/store/settingsStore"

export default function RootPage() {
  const router = useRouter()
  const { token } = useAuthStore()
  const { onboardingComplete } = useSettingsStore()

  useEffect(() => {
    if (!token) {
      router.replace("/auth/login")
    } else if (!onboardingComplete) {
      router.replace("/onboarding")
    } else {
      router.replace("/home")
    }
  }, [token, onboardingComplete, router])

  return (
    <div className="flex flex-col flex-1 items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="text-2xl font-bold text-gray-900 mb-2">YieldIQ</div>
        <div className="text-sm text-gray-500">Loading...</div>
      </div>
    </div>
  );
}
