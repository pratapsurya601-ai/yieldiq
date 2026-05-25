"use client"
import { useEffect, useRef, useState } from "react"

/**
 * Fires `true` the first time the element enters the viewport, then
 * disconnects the observer. Used by every animation primitive so
 * animations only run once on first reveal, never on subsequent
 * scrolls.
 *
 * If IntersectionObserver is unavailable (very old browsers, or SSR
 * pre-hydration), the effect schedules an `inView=true` flip via the
 * observer callback path — content is never hidden because the
 * primitives all check this hook and render their final state.
 */
export function useInViewOnce<T extends Element>(
  threshold: number = 0.15,
  rootMargin: string = "0px",
): { ref: React.RefObject<T | null>; inView: boolean } {
  const ref = useRef<T | null>(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    if (inView) return
    const node = ref.current
    if (!node) return

    // Fallback for environments without IntersectionObserver: queue a
    // microtask that flips inView. Done as a callback (not a direct
    // setState in the effect body) so the React 19 hooks lint rule is
    // satisfied — and so the flip is consistent with the IO callback
    // path.
    if (typeof IntersectionObserver === "undefined") {
      const id = setTimeout(() => setInView(true), 0)
      return () => clearTimeout(id)
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setInView(true)
            observer.disconnect()
            break
          }
        }
      },
      { threshold, rootMargin },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [threshold, rootMargin, inView])

  return { ref, inView }
}
