import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import { getStockSummary } from "@/lib/api"
import DCFSensitivityHeatmap from "@/components/analysis/DCFSensitivityHeatmap"

interface RouteParams {
  params: Promise<{ ticker: string }>
}

export async function generateMetadata({ params }: RouteParams): Promise<Metadata> {
  const { ticker } = await params
  const display = ticker.toUpperCase()
  return {
    title: `${display} DCF Sensitivity Heatmap | YieldIQ`,
    description: `Interactive WACC × terminal-growth heatmap for ${display}. See how the DCF fair value moves with the two key assumptions.`,
    robots: { index: false, follow: true },
  }
}

export default async function SensitivityPage({ params }: RouteParams) {
  const { ticker } = await params
  const display = ticker.toUpperCase()
  const summary = await getStockSummary(ticker)
  if (!summary) notFound()

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 sm:py-12">
      <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
        <Link href="/" className="hover:text-gray-600">Home</Link>
        <span>/</span>
        <Link href={`/stocks/${display}/fair-value`} className="hover:text-gray-600">
          {display} Fair Value
        </Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">Sensitivity</span>
      </nav>

      <header className="mb-6">
        <h1 className="text-2xl sm:text-3xl font-black" style={{ color: "var(--color-ink, #0F172A)" }}>
          {summary.company_name} — DCF Sensitivity
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Pivot the two assumptions that drive the bulk of DCF output: cost of
          capital (WACC) and terminal growth (TG). Cells are coloured by margin
          of safety vs. the live current price.
        </p>
      </header>

      <DCFSensitivityHeatmap ticker={display} summary={summary} />

      <div className="mt-6 text-xs text-gray-400">
        <Link href={`/stocks/${display}/fair-value`} className="hover:text-gray-600">
          ← Back to {display} fair-value page
        </Link>
      </div>
    </div>
  )
}
