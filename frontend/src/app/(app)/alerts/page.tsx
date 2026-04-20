import AlertsEmpty from "@/components/empty-states/AlertsEmpty"

// Alerts also live inside the Portfolio page as a tab. Visiting /alerts
// directly shows the empty state so users landing on old bookmarks still
// get a useful entry point.
export default function AlertsPage() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <AlertsEmpty />
    </div>
  )
}
