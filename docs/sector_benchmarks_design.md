# Sector Benchmarks — Design Note

**Status:** Implemented, sample data only. Real per-sector numbers populate once `model_predictions_history` accumulates ≥1 quarter of sector-tagged predictions.
**Owner:** Performance Retrospective (Task 12, A+ refinement).
**Code:**
- `backend/services/sector_benchmarks.py` — mapping
- `backend/services/retrospective_service.py` — `summarize_for_period(..., benchmark='auto')`
- `backend/routers/public.py` — `/api/v1/public/retrospective?benchmark=auto`
- `frontend/src/app/(marketing)/methodology/performance/page.tsx` — sector table
- `tests/test_sector_benchmarks.py`

---

## Why sector-relative > absolute

Saying *"our IT picks beat Nifty 500 by 4%"* is meaningless if Nifty IT outperformed Nifty 500 by 8% over the same window. The IT picks would have **lagged** their natural benchmark and we'd be implicitly claiming alpha that doesn't exist.

Saying *"our cement picks beat Nifty 500 by 1%"* sounds weak — until you learn Nifty Cement was down 6%. Then it's a 7% sector-relative win.

The only honest comparison for a sector-concentrated pick is the sector index. This is standard practice in equity research; we were short-cutting it because the platform launched with one benchmark.

A model picking IT stocks should be benchmarked against Nifty IT, not Nifty 500. Cement vs Nifty Cement. Sector-relative is the honest comparison.

## Mapping

| Canonical sector | Yahoo ticker | Index | Rationale |
|---|---|---|---|
| IT Services | `^CNXIT` | Nifty IT | Direct fit; covers TCS/INFY/WIPRO/HCL/TECHM. |
| Banks | `^NSEBANK` | Nifty Bank | Private + PSU mix; broadest bank exposure. |
| Pharma | `^CNXPHARMA` | Nifty Pharma | Covers Sun/Cipla/Dr.Reddy/Divis/Lupin. |
| FMCG | `^CNXFMCG` | Nifty FMCG | HUL/ITC/Nestle/Britannia. |
| Auto | `^CNXAUTO` | Nifty Auto | OEMs + ancillaries; tightest available index. |
| Metals | `^CNXMETAL` | Nifty Metal | Tata Steel / JSW / Hindalco / Vedl. |
| Energy | `^CNXENERGY` | Nifty Energy | RIL / NTPC / Power Grid; oil + power blended. |
| Realty | `^CNXREALTY` | Nifty Realty | Small index but only listed alternative. |
| Media | `^CNXMEDIA` | Nifty Media | Thin index, low n — flag in UI when n<5. |
| PSU Bank | `^CNXPSUBANK` | Nifty PSU Bank | Distinct from `^NSEBANK`; separate beta profile. |
| Financial Services | `^CNXFIN` | Nifty Financial Services | NBFCs, AMCs, insurance, holdcos. |
| Consumer Durables | `^CNXCONSUM` | Nifty Consumer Durables | Best fit for white-goods / paints. |
| _default_ | `NIFTY500.NS` | Nifty 500 | Fallback for unmapped/conglomerate stocks. |

Aliases (`SECTOR_ALIASES` in code) cover variants like `"Information Technology"`, `"Oil & Gas"`, `"NBFC"`, `"Insurance"` — they all route to the canonical key above.

## Aggregate semantics under `benchmark=auto`

When `benchmark=auto`, the headline fields (`outperform_rate`, `benchmark.return_pct`) become **sector-weighted aggregates**, not single-benchmark numbers:

- `outperform_rate` = `Σ (predictions that beat their own sector benchmark) / Σ predictions` across all sectors with a resolvable benchmark.
- `benchmark.return_pct` = n-weighted mean of per-sector benchmark returns. `ticker` is set to `"auto"` so consumers can disambiguate.

This is what makes the headline number honest: it's no longer "47 picks vs Nifty 500", it's "47 picks vs the right benchmark for each pick".

`benchmark=nifty500` preserves the legacy single-benchmark behaviour byte-for-byte (verified by `test_nifty500_mode_shape_unchanged`). This is the backward-compat contract for any caller still pointing at the old shape.

## Open questions

1. **Conglomerate stocks** (RELIANCE, ITC, ADANIENT). RELIANCE is officially "Energy" in NSE's classification but is increasingly retail/telecom by revenue. ITC is "FMCG" but with a hotels/paperboards tail. Three options:
   - **Stay nominal** (current): trust the `stocks.sector` label even when revenue mix has drifted. Simple, slightly stale.
   - **Revenue-weighted custom benchmark**: blend Nifty Energy + Nifty Consumer for RELIANCE per the segment split. Honest but expensive — needs annual recompute.
   - **Bucket as `Conglomerate` → fallback to Nifty 500**: explicit "we don't know which sector to compare against".
   *Decision:* Stay nominal for v1. Revisit once we have ≥4 quarters of data and can measure how much it matters.

2. **Banks vs NBFCs vs Insurance.** The map currently routes:
   - Public/private banks → `^NSEBANK`
   - PSU banks → `^CNXPSUBANK` (distinct beta)
   - NBFCs / insurers / AMCs → `^CNXFIN` (Nifty Financial Services)
   This is one boundary the sector strings *must* be tagged correctly upstream. If `Bajaj Finance` is labelled `Banks`, it ends up vs Nifty Bank — which is wrong (NBFC, not bank). Coverage runbook should add a check.

3. **Index availability gaps.** No native Nifty Cement / Nifty Chemicals / Nifty Defence indices exist on Yahoo. These fall through to NIFTY 500. When index providers list these (NSE has signalled both), add them to `SECTOR_BENCHMARK_MAP`.

4. **Survivorship bias in the benchmarks themselves.** The Nifty IT index reconstitutes; a stock that drops out post-prediction inflates the index return. We accept this — the same is true of the broad benchmark and is the SEBI-acceptable convention.

## Future

- **Factor benchmarks**: small-cap picks vs Nifty Smallcap 100 (not Nifty 500), value picks vs a value-weighted index, growth picks vs Nifty 500 Growth. Adds a second axis (factor-relative), independent of sector.
- **Custom blends**: the conglomerate problem is best solved by bespoke per-stock benchmarks (segment-revenue-weighted). Expensive; revisit only if conglomerate calls drive the headline materially.
- **Time-varying benchmarks**: if a stock changes sector mid-period, the prediction's benchmark should be the sector at the time of prediction, not at outcome. The mapping is static today; resolve at write-time, not summarise-time, when this becomes material.
