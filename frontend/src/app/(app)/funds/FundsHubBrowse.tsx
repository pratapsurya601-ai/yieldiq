/**
 * FundsHubBrowse — the rich DEFAULT (no q / no category) /funds hub.
 *
 * Server component. Composes the redesigned browse experience that
 * renders with real content on first paint, so the bare /funds landing
 * is never an empty "search to browse" prompt:
 *
 *   1. CategoryMosaic     — the true category census as an animated tile
 *                           grid (centerpiece), linking to ?category=.
 *   2. AmcRail            — fund houses ordered by sample count, linking
 *                           to ?q=<amc>.
 *   3. RiskometerSpectrum — descriptive six-band risk strip (self-hides
 *                           when the sample carries no riskometer data).
 *   4. A first look       — a sample card grid (FundCard) so the user
 *                           sees real schemes immediately.
 *
 * All facets are derived here (pure, synchronous) from one sample list
 * call + the categories census already fetched by the page; nothing
 * here mutates searchParams, so the page stays static-ISR.
 *
 * SEBI: descriptive only. Sample order is the endpoint's alphabetical
 * order — not a ranked "pick". No advisory vocab.
 */
import { fetchFundListSSR } from "@/lib/api"
import { RevealStagger } from "@/components/motion"
import type { FundRiskometerLevel } from "@/types/api"

import FundCard, { type FundCardItem } from "./FundCard"
import CategoryMosaic, { type MosaicCategory } from "./CategoryMosaic"
import AmcRail, { type AmcFacet } from "./AmcRail"
import RiskometerSpectrum, { type RiskBucket } from "./RiskometerSpectrum"
import { RISKOMETER_ORDER } from "@/lib/fund-riskometer"

const SAMPLE_SIZE = 48
const MAX_AMCS = 14

export default async function FundsHubBrowse({
  categories,
}: {
  categories: MosaicCategory[]
}) {
  // One additional call: a sample of the universe (alphabetical) so the
  // hub shows real cards + can derive AMC / riskometer facets. Errors
  // degrade to an empty sample (handled by the no-empty fallbacks).
  const { funds } = await fetchFundListSSR(SAMPLE_SIZE)
  const sample = funds as FundCardItem[]

  // AMC facet — count-based factual sort, top houses first.
  const amcMap = new Map<string, number>()
  for (const f of sample) amcMap.set(f.amc, (amcMap.get(f.amc) ?? 0) + 1)
  const amcs: AmcFacet[] = [...amcMap]
    .map(([amc, count]) => ({ amc, count }))
    .sort((a, b) => b.count - a.count || a.amc.localeCompare(b.amc))
    .slice(0, MAX_AMCS)

  // Riskometer buckets — six ordered bands; spectrum self-hides on zero.
  const riskBuckets: RiskBucket[] = RISKOMETER_ORDER.map(
    (level: FundRiskometerLevel) => ({
      level,
      count: sample.filter((f) => f.riskometer_level === level).length,
    }),
  )

  return (
    <div className="space-y-12 md:space-y-16">
      <CategoryMosaic categories={categories} />

      <AmcRail amcs={amcs} />

      <RiskometerSpectrum buckets={riskBuckets} />

      {sample.length > 0 ? (
        <section className="space-y-3">
          <div className="space-y-1">
            <p className="text-[11px] font-semibold uppercase leading-4 tracking-[0.06em] text-caption">
              A first look
            </p>
            <h2 className="text-[22px] font-semibold leading-7 tracking-tight text-ink">
              Schemes A–Z
            </h2>
          </div>
          {/*
            threshold={0} is load-bearing — this grid is many rows tall,
            so RevealStagger's default 0.15 in-view threshold never fits
            in the viewport and every card would stay opacity-0 on load
            (memory #939). With 0 it reveals as the grid's top edge
            enters view.
          */}
          <RevealStagger
            className="grid items-stretch gap-3 sm:grid-cols-2 lg:grid-cols-3"
            staggerMs={15}
            threshold={0}
          >
            {sample.map((f) => (
              <FundCard key={f.scheme_code} fund={f} />
            ))}
          </RevealStagger>
        </section>
      ) : null}
    </div>
  )
}
