"use client"
import { Component, type ErrorInfo, type ReactNode } from "react"

interface Props {
  children: ReactNode
  fallback?: ReactNode
  /**
   * Optional human-readable tag used to identify which boundary caught
   * the error in console output. Helpful when the homepage wraps each
   * rail individually — without this, every crash logs the same generic
   * "Something went wrong" with no way to tell which rail died.
   */
  label?: string
}
interface State { hasError: boolean; error?: Error }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    const tag = this.props.label ? `[ErrorBoundary:${this.props.label}]` : "[ErrorBoundary]"
    // Tag the line so it's grep-able in a noisy console — pairs with
    // the per-rail labels on the homepage.
    console.error(`${tag} caught error`, error, info?.componentStack)
    // SENTRY-HOOK: when @sentry/nextjs is wired in, replace the
    // console.error above with `Sentry.captureException(error, {
    //   tags: { boundary: this.props.label ?? "unknown" },
    //   extra: { componentStack: info?.componentStack },
    // })`. Intentionally not adding the dep here.
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
