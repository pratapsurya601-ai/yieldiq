import type { Metadata } from "next"

import DemoClient from "./DemoClient"

// Throwaway design preview of the v3 analysis-page redesign
// (docs/ANALYSIS_PAGE_TARGET_ARCHITECTURE.md §7 + docs/redesign_mockups/).
// Mock data only — never indexed, never linked from the app, not in the
// sitemap. Server shell so the robots metadata applies; all
// interactivity lives in the client tree below.
export const metadata: Metadata = {
  title: "Analysis redesign preview",
  robots: { index: false, follow: false },
}

export default function AnalysisRedesignPreviewPage() {
  return <DemoClient />
}
