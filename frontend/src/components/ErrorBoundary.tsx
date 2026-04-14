"use client"
import { Component, type ReactNode } from "react"

interface Props { children: ReactNode; fallback?: ReactNode }
interface State { hasError: boolean; error?: Error }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || (
        <div className="flex flex-col items-center justify-center min-h-[60vh] px-4">
          <p className="text-lg font-semibold text-gray-900 mb-2">Something went wrong</p>
          <p className="text-sm text-gray-500 mb-4">An unexpected error occurred.</p>
          <button onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">
            Reload page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
