import { redirect } from "next/navigation"

// Alerts live inside the Portfolio page as a tab; /alerts is kept around
// so old bookmarks and shared URLs still resolve.
export default function AlertsRedirect() {
  redirect("/portfolio?tab=alerts")
}
