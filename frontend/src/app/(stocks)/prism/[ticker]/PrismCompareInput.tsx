"use client"

import { useRouter } from "next/navigation"
import { useState } from "react"

interface PrismCompareInputProps {
  base: string
}

export default function PrismCompareInput({ base }: PrismCompareInputProps) {
  const router = useRouter()
  const [value, setValue] = useState("")

  const go = () => {
    const other = value.trim().toUpperCase().replace(/\.(NS|BO)$/i, "")
    if (!other) return
    router.push(`/prism/compare/${base}-vs-${other}`)
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        go()
      }}
      className="flex flex-col sm:flex-row gap-3"
    >
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Enter ticker e.g. TCS"
        className="flex-1 border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        autoCapitalize="characters"
      />
      <button
        type="submit"
        className="bg-blue-600 text-white text-sm font-semibold px-5 py-2.5 rounded-xl hover:bg-blue-500 transition"
      >
        Compare
      </button>
    </form>
  )
}
