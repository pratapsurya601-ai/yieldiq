"use client"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useAuthStore } from "@/store/authStore"
import {
  CountUp,
  ChartDrawIn,
  FadeStagger,
  RevealOnScroll,
} from "@/components/anim"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  ResponsiveContainer,
  CartesianGrid,
  Tooltip,
} from "recharts"

// Match the admin gate used elsewhere (src/app/(app)/admin/page.tsx).
const ADMIN_EMAILS = ["pratapsurya601@gmail.com", "suryasbss601@gmail.com"]

const SAMPLE_SERIES = [
  { name: "FY20", value: 412 },
  { name: "FY21", value: 489 },
  { name: "FY22", value: 567 },
  { name: "FY23", value: 612 },
  { name: "FY24", value: 701 },
  { name: "FY25", value: 786 },
]

function Section({
  title,
  children,
  caption,
}: {
  title: string
  caption?: string
  children: React.ReactNode
}) {
  return (
    <RevealOnScroll className="border border-gray-100 rounded-2xl p-6 bg-bg dark:bg-surface">
      <h2 className="text-sm font-bold uppercase tracking-tight text-ink mb-1">
        {title}
      </h2>
      {caption && (
        <p className="text-xs italic text-caption mb-4 max-w-prose">{caption}</p>
      )}
      {children}
    </RevealOnScroll>
  )
}

export default function AnimDemoPage() {
  const { email } = useAuthStore()
  const router = useRouter()
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    // Subscribe to Zustand persist hydration. The initial-check branch
    // schedules a microtask so setHydrated runs in a callback, not
    // synchronously in the effect body (react-hooks/set-state-in-effect).
    if (useAuthStore.persist.hasHydrated()) {
      const id = setTimeout(() => setHydrated(true), 0)
      return () => clearTimeout(id)
    }
    const unsub = useAuthStore.persist.onFinishHydration(() => setHydrated(true))
    return unsub
  }, [])

  useEffect(() => {
    if (!hydrated) return
    if (!email || !ADMIN_EMAILS.includes(email)) {
      router.push("/home")
    }
  }, [hydrated, email, router])

  if (!hydrated) return null
  if (!email || !ADMIN_EMAILS.includes(email)) return null

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6 pb-32">
      <div>
        <h1 className="text-xl font-bold text-ink">Animation primitives demo</h1>
        <p className="text-sm text-caption">
          Visual QA for the primitives library. Scroll slowly to see each
          one trigger on viewport entry.
        </p>
      </div>

      <Section
        title="CountUp"
        caption="Numbers count up from 0 once, when scrolled into view."
      >
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-xs text-caption">Fair value</p>
            <p className="text-2xl font-bold tabular-nums text-ink">
              <CountUp to={1131} prefix="₹" />
            </p>
          </div>
          <div>
            <p className="text-xs text-caption">Discount</p>
            <p className="text-2xl font-bold tabular-nums text-ink">
              <CountUp to={43.7} decimals={1} suffix="%" />
            </p>
          </div>
          <div>
            <p className="text-xs text-caption">Score</p>
            <p className="text-2xl font-bold tabular-nums text-ink">
              <CountUp to={50} suffix=" / 100" />
            </p>
          </div>
        </div>
      </Section>

      <Section
        title="ChartDrawIn"
        caption="Recharts line draws in left-to-right on first viewport entry."
      >
        <ChartDrawIn animationDuration={1100}>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={SAMPLE_SERIES}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#0d9488"
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartDrawIn>
      </Section>

      <Section
        title="FadeStagger"
        caption="List children fade + slide in, one after the other."
      >
        <FadeStagger
          staggerMs={120}
          direction="up"
          className="grid grid-cols-1 sm:grid-cols-2 gap-3"
        >
          {SAMPLE_SERIES.map((row) => (
            <div
              key={row.name}
              className="rounded-xl border border-gray-100 p-4"
            >
              <p className="text-xs text-caption">{row.name}</p>
              <p className="text-lg font-bold tabular-nums text-ink">
                <CountUp to={row.value} prefix="₹" />
              </p>
            </div>
          ))}
        </FadeStagger>
      </Section>

      <Section
        title="RevealOnScroll"
        caption="Each section above is wrapped in RevealOnScroll — that is the primitive driving the entrance you just saw."
      >
        <p className="text-sm text-ink">
          This whole page is a sequence of <code>&lt;RevealOnScroll&gt;</code>{" "}
          panels. The headline below is one more, with a 200ms delay.
        </p>
        <RevealOnScroll delay={200} className="mt-4">
          <p className="text-base font-medium text-ink">
            Animations are storytelling, not decoration. The page reveals
            itself as you scroll.
          </p>
        </RevealOnScroll>
      </Section>

      <Section
        title="useScrollSnap()"
        caption="Hook returns class names + ref for snap-to-section scrolling on a container. Not visually demoed inline (would conflict with page scroll) — used by the analysis page wrapper."
      >
        <pre className="text-xs bg-gray-50 dark:bg-gray-900 rounded-lg p-3 overflow-x-auto">
          {`const { ref, containerClassName, itemClassName } = useScrollSnap("mandatory")`}
        </pre>
      </Section>
    </div>
  )
}
