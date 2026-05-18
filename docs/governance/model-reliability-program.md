# Model Reliability Program — Governance Doc

**Status:** Living document
**Owner:** YieldIQ architecture
**Created:** 2026-05-18
**Last revised:** 2026-05-18
**Cache version at creation:** v102
**Revision cadence:** Quarterly (next: 2026-08-18) or on any phase-status change

---

## Status emoji legend

| Emoji | Meaning |
|---|---|
| ✅ | Shipped, validated, in production |
| 🟡 | In-flight or partial (works for some tickers, not all) |
| ⏸️ | Deferred — design exists or is justified but not built |
| ❌ | Deprecated — built then disabled, or rejected on review |
| 🚧 | Active construction (PR open or behind feature flag) |
| 🚩 | Flag-only / advisory (no FV math change) |
| 📋 | Design doc only, no code |

---

## 0. TL;DR

YieldIQ has a **5-phase Model Reliability Program** that exists to make the model's outputs honestly defensible to a retail Indian investor.

- **Phase 1 — Truth Universe** 🟡 expanding 50 → 180 canary tickers (Layer A reconciliation expansion in flight).
- **Phase 2 — Sector Engines** 🟡 6 sectors ✅ keep, 3 🟡 partial, 1 ❌ deprecated, 2 ⏸️ deferred on data blockers.
- **Phase 3 — Confidence Gating (Layer C)** ✅ shipped via PRs #340, #342 — `data_quality`, `model_confidence`, `valuation_stability` scores now drive an "Under Review" verdict instead of fake-precise FVs.
- **Phase 4 — Anomaly Detection** 🟡 6 of 7 rules live (PR #327); FCF-CAGR rule pending.
- **Phase 5 — Benchmark Reconciliation (Layer A)** ✅ shipped via PR #341 — daily outlier dashboard + admin endpoint.

This doc is the contract YieldIQ keeps with itself about how it ships, deprecates, and gates a model.

---

## 1. Mission statement

> **YieldIQ ships the most-credible transparent-DCF fair values for Indian retail investors. Where our model is unreliable, we say so honestly — via "Under Review" verdicts and caveats — not by faking precision.**

Three things this implies, in order of importance:

1. **Credibility beats coverage.** A 180-ticker universe we can defend > a 3,000-ticker universe we cannot. Coverage expands only as reliability is proven on the canary.
2. **Transparency beats accuracy.** Our DCF is auditable to the cash-flow line. We will not adopt opaque ML scoring or "secret-sauce" overlays that the user cannot follow.
3. **Honest abstention beats false precision.** If `data_quality < 0.5` or `model_confidence < 0.4`, we surface **Under Review** rather than a number — and we log it on the reconciliation dashboard so we can fix it.

What this mission rejects:

- "Bloomberg Terminal for India" framing — that is marketing, not a model.
- Broker-sync / portfolio-import features — out of scope; not a research product.
- SE Asia expansion — India only for the foreseeable future.
- Any UX that hides the methodology behind the number.

---

## 2. The 5-Phase Roadmap

Each phase is independently shippable and has its own acceptance metric. Phases are roughly sequential but interlock — Phase 5 (Layer A reconciliation) is the **scoreboard** that Phase 2 deprecation decisions are gated on.

### Phase 1 — Truth Universe 🟡 (canary expansion in-flight)

**Goal:** ground the entire program in a curated, growable canary of stocks whose "correct FV" is defensible against analyst consensus, exchange disclosures, and our own snapshots.

**Status:**

- ✅ 50-stock canary live (`scripts/canary_stocks_50.json`) since Phase 0.
- 🚧 Expansion 50 → 180 in flight via `canary-universe-180` PR (lands alongside Layer A reconciliation expansion).
- ⏸️ 180 → 500 target deferred to Phase 5 follow-up once reconciliation data confirms outlier stability.

**Why 180 and not 500 from day 1:** every ticker added to the canary creates ongoing snapshot + diff cost. 180 covers Nifty 100, Nifty Next 50, plus 30 curated edge cases (REITs, ETFs, holdcos, defense PSUs, regulated utilities). We add the next 320 only when reconciliation tells us *which* 320 are worth the cost.

**Acceptance metric:** 180 canary tickers each with:

1. Last 4 daily snapshots in `analysis_cache.computation_inputs`.
2. A consensus delta (`|delta_pct|`) from Layer A reconciliation.
3. A confidence triplet (`data_quality`, `model_confidence`, `valuation_stability`) from Layer C.

**Current value:** 50 of 180 (28%). Jumps to ~120 of 180 (67%) when `canary-universe-180` lands.

### Phase 2 — Sector Engines 🟡 (8 of 12 categories at terminal state)

**Goal:** preserve sector engines **only** where the math is structurally different. Deprecate or never-build the rest.

**Per-engine status table:**

| Sector | Status | Engine / treatment | Anchoring design doc |
|---|---|---|---|
| Banks / NBFCs | ✅ | P/B × peer-band engine | `docs/design/bank-equity-source-fix.md` |
| Regulated Utilities | ✅ | Rate-base (PR #318) | `docs/design/regulated-utility-dcf-fix.md` |
| REITs | ✅ | Skip-DCF + DPU yield (PR #335) | `docs/design/reit-valuation-fix.md` |
| ETFs | ✅ | Skip-DCF + NAV (PR #325) | (no doc; skip is trivial) |
| Holdcos | ✅ | Skip-DCF + NAV discount caveat | (pre-v95) |
| Defense PSU | ✅ 🚩 | Advisory flag only (PR #333) | `docs/design/defense-psu-dcf-fix.md` |
| Pharma | 🟡 | R&D-adjusted FCF (PRs #320, #330) — Tier 1 stable subset works, MANKIND / AJANTPHARM still off | `docs/design/pharma-dcf-fix.md` |
| Cement | 🟡 | M&A truncation + classifier (PRs #324, #331) — 4 of 7 in band; W5 reconciliation decides keep/deprecate | `docs/design/cement-dcf-fix.md` |
| FMCG | 🟡 | Brand-premium overlay (PR #336) — partial, deprecation planned; only ROIC-bump survives into Tier 1 | `docs/design/fmcg-dcf-fix.md` |
| Capital Goods | ❌ | 7y-WC FCF engine (PR #337) — **disabled on contact**; code deletion scheduled W5 | `docs/design/capital-goods-dcf-fix.md` |
| Insurance | ⏸️ 📋 | EV + VNB design doc only; data sourcing blocker (IRDAI EV disclosures not yet auto-ingested) | `docs/design/insurance-dcf-fix.md` |
| Realty Developers | ⏸️ 📋 | Design doc only; land-bank curation cadence is the blocker | `docs/design/realty-developers-dcf-fix.md` |

**Acceptance metric:** every sector in the table at one of {✅, ⏸️, ❌}. 🟡 is a transitional state and must resolve at W5 reconciliation (see §6 Decision Log).

**Current value:** 8 of 12 at terminal state (67%). Pharma + Cement + FMCG await W5 reconciliation. Capital Goods is terminal-deprecated but code not yet deleted.

### Phase 3 — Confidence Gating (Layer C) ✅ (shipped)

**Goal:** every public FV is accompanied by three machine-readable scores; below a threshold, the verdict flips to **Under Review** and the FV is not shown.

**Status:** shipped via PRs #340 (scoring) and #342 (verdict gating).

**Scores:**

- **`data_quality`** ∈ [0, 1] — completeness + freshness of the input series (FCF history, sector tag, EPS/EBITDA, net debt).
- **`model_confidence`** ∈ [0, 1] — agreement among multiple internal valuation candidates (DCF base, DCF stressed, cohort-multiple, reverse-DCF cross-check).
- **`valuation_stability`** ∈ [0, 1] — variance of FV over the trailing 14-day snapshot window.

**Verdict gating:**

```
if data_quality < 0.5 OR model_confidence < 0.4 OR valuation_stability < 0.3:
    verdict = "Under Review"
    public_fv = null   # we hide the number; the methodology is still shown
else:
    verdict = standard {Buy, Hold, Sell} mapping from FV vs CMP
```

**Acceptance metric:** every canary ticker has a confidence triplet stored daily; the dashboard counts Under-Review verdicts per sector. Goal: < 15% Under-Review for Tier 1, < 35% for Tier 2.

**Current value:** triplet live on 100% of canary tickers (PR #342 backfilled). Under-Review rate stabilising at ~22% across canary — within target.

### Phase 4 — Anomaly Detection 🟡 (6 of 7 rules)

**Goal:** before any FV is published, run it through a battery of anomaly rules that catch the obvious bugs (DRREDDY-class XBRL unit blow-ups, MANKIND-dragged-by-generics, peers-bigger-than-the-stock).

**Status:** PR #327 shipped 6 of 7 rules. FCF-CAGR rule deferred to Phase 4.1.

**Rules live (PR #327):**

1. **`fv_vs_cmp_extreme`** — |FV − CMP| / CMP > 200% triggers manual review.
2. **`fv_vs_book_extreme`** — FV > 5 × book value triggers cap to 5× (SCHAEFFLER-class).
3. **`cohort_isolation`** — ticker FV diverges from sector-bucket median by > 3 σ.
4. **`negative_terminal_value`** — DCF terminal leg < 0 forces fall-through to Tier 2.
5. **`stale_inputs`** — any computation input older than 90 days flags `data_quality` drop.
6. **`unit_mismatch_guard`** — defensive cap against XBRL-unit blow-ups (DRREDDY-class; root cause not found, see §7).

**Rule pending (Phase 4.1):**

7. **`fcf_cagr_outlier`** — 5y FCF CAGR outside [−25%, +60%] triggers Tier-2 fall-through. Design exists; not implemented.

**Acceptance metric:** all 7 rules live + nightly job logs per-rule trigger counts. Trigger-count regression > 50% week-over-week is itself an anomaly.

**Current value:** 6 of 7 rules (86%). Rule #7 in backlog.

### Phase 5 — Benchmark Reconciliation (Layer A) ✅ (shipped)

**Goal:** every FV gets compared against analyst-consensus median (where available) and our own historic snapshot. The delta is logged. Outliers go to a daily admin dashboard. **This is the scoreboard that Phase 2 deprecation decisions are gated on.**

**Status:** shipped via PR #341.

**What shipped:**

- `consensus_estimates` table (PR #334) — nightly refresh from broker aggregator.
- Reconciliation gate inside `service.py` (PR #341) — populates `|delta_pct|` on every public FV.
- Admin endpoint `/admin/reconciliation/outliers` — top 50 outliers per sector.
- Post-deploy canary checkpoint — reconciliation delta diff must be < 5pp on average across canary, else deploy is rolled back.

**Acceptance metric:**

1. Reconciliation framework live ✅
2. Daily outlier dashboard populated ✅
3. Canary coverage expanding 50 → 180 with consensus deltas (in-flight with Phase 1)
4. Outlier count (|delta| > 30%) drops by ≥30% across Layer-B migration window (measured at W5 vs W0).

**Current value:** items 1 and 2 ✅; item 3 at 50/180 (28%); item 4 baseline being established this week.

---

## 3. Architecture overview — Layer B (Tier 1/2/3)

The architectural backbone of the program is the **Layer B two-tier valuation system** described in `docs/design/valuation-architecture-simplification.md`. This doc summarises status per Tier; the full design lives in the linked file.

### 3.1 Tier 1 — Generic FCF-DCF, curated universe ~150 tickers 🚧

**What it does:** the existing generic transparent DCF, but only routed to ~150 large-caps with clean 5y financials.

**Status:** curated list (`backend/services/analysis/tier1_universe.py`) scheduled to land W2 of the Layer B migration. Today the generic DCF still touches ~2,500 tickers; the Layer B work funnels it down.

**Eligibility (full spec in valuation-architecture-simplification.md §2.1):**

- Market cap ≥ ₹25,000 Cr or in Nifty 100.
- 5 consecutive years of positive FCF.
- Revenue CAGR 5y in `[−5%, +30%]`.
- Net debt / EBITDA ≤ 3.5 (financial sector exempt).
- No structure-breaking corporate action in trailing 24 months.
- NOT in any Tier 3 sector.

**Acceptance metric:** ≥80% of Tier 1 tickers within ±20% of consensus median.

### 3.2 Tier 2 — Quality-weighted sector cohort multiples ~1,500 tickers 🚧

**What it does:** for each ticker, find peers in same sector AND same quality bucket (Premium / Core / Tail, defined by ROCE + Piotroski + market cap). Use bucket-median P/E × ticker EPS and bucket-median EV/EBITDA × ticker EBITDA. Weight 60/40.

**Status:** service to be implemented W1 of Layer B migration. Feature-flagged off in prod until W2 canary acceptance.

**Why bucketing matters:** today's sector medians drag franchise tickers down to commodity-peer levels (MANKIND vs generics, NESTLE vs PATANJALI). Bucketing benchmarks like-against-like.

**Acceptance metric:** ≥70% of Tier 2 tickers within ±30% of consensus median.

### 3.3 Tier 3 — Skip with caveat ~300 tickers ✅

**What it does:** for structurally-different sectors (banks, insurance, REIT, ETF, holdco, regulated utility, defense flag) and for ineligible tickers (sub-3y history, microcap with no analyst coverage, loss-making, sanity-guard failures), route to the appropriate skip path or sector engine.

**Status:** ✅ for the bespoke-but-skip-shaped engines (banks, regulated utility, REITs, ETFs, holdcos, defense flag). ⏸️ for insurance design only. Skip-on-eligibility-failure category will gain explicit routing when the Tier 2 service lands.

**Acceptance metric:** < 350 non-trivial tickers in Tier 3 (excluding ETFs, REITs, holdcos which together account for ~200). Measured at Layer B W6.

### 3.4 Routing tree (target)

```
ticker → sector_resolve()
  ├─ is_etf            → Tier 3 (skip, show NAV)           ✅
  ├─ is_reit           → Tier 3 (skip, show DPU yield)     ✅
  ├─ is_holdco         → Tier 3 (skip, show NAV discount)  ✅
  ├─ is_financial      → Banks P/B engine                  ✅
  ├─ is_regulated_utility → Rate-base engine               ✅
  ├─ in TIER1_UNIVERSE → Tier 1 generic DCF                🚧
  ├─ tier2_eligible    → Tier 2 quality-bucketed cohort    🚧
  └─ default           → Tier 3 (data-limited caveat)      🚧
```

The cement / pharma / FMCG / cap-goods sector branches sit *between* the regulated-utility and Tier 1 branches today. They are being deprecated into Tier 2 via the W3–W5 Layer B migration.

---

## 4. Discipline rules

These are the non-negotiable shipping rules. The first three exist in `CLAUDE.md` already and were re-confirmed today. The last three are **new** — added based on lessons from today's session.

### Existing rules (`CLAUDE.md`, 2026-04-19)

1. **Never ship without canary-diff.** `python scripts/canary_diff.py` must exit 0 BEFORE merging any PR that touches `backend/services/`, `backend/routers/`, `backend/validators/`, `backend/models/`, or `scripts/canary_stocks_50.json`. The GitHub Actions canary workflow enforces this.

2. **Never bump CACHE_VERSION without snapshot.** Run `python scripts/snapshot_50_stocks.py` BEFORE the bump. Run `python scripts/canary_diff.py --diff-against latest` AFTER. Any FV change > 15% on any of the 50 must be explained in the PR description.

3. **Never declare a bug "fixed" off a single Chrome MCP test.** The fix is fixed when:
   - canary-diff passes 5/5 gates on all 50 (180 once Phase 1 lands)
   - 7 consecutive nightly canary runs are clean
   - The fix is reproducible from snapshotted `computation_inputs`

### New rules (lessons from 2026-05-18 session)

4. **Never use `git checkout --theirs` on multi-merge files.** Earlier today a merge resolution on `service.py` used `--theirs` and silently dropped the regulated-utility branch landed in PR #318. Multi-merge files (`service.py`, `constants.py`, `analysis_cache.py`) require manual conflict resolution. If the conflict touches a routing branch, the merge MUST be reviewed by a second pair of eyes or paired with a routing-counter telemetry check before push.

5. **Sector engines without reconciliation gating are unsafe to ship.** Until Layer A reconciliation gives a head-to-head consensus delta, a new sector engine is an opinion, not a fix. Capital Goods PR #337 burned three weeks because we shipped on local unit tests + canary 5/5; reconciliation later showed it pulled FVs *down* across the cohort, not towards consensus. **No new sector engine PR is merged without a `docs/reconciliation/<sector>-tier2-vs-engine.md` win-rate report.**

6. **Local unit tests are insufficient acceptance for behaviour changes.** Pre-merge acceptance requires an end-to-end probe (admin `/diagnose/ticker/<symbol>` or equivalent staging hit) on at least 3 affected tickers, with screenshots attached to the PR. Unit tests pass on mocks; the real bugs (XBRL units, sector tag mismatches, peer-bucket sizes < 4) only surface end-to-end.

---

## 5. Decision log

Chronological, with the reasoning. Append-only; do not edit prior entries except to note follow-up.

### 2026-05-18

**D1 — PR #318 regulated-utility engine kept.**
- Decision: keep the rate-base engine as a permanent Tier 3 path.
- Reasoning: the math is *structurally* different. POWERGRID, NTPC, TATAPOWER (regulated leg) earn an allowed return on rate-base set by CERC tariff orders. There is no FCF / EPS / EBITDA reformulation that recovers this — the economic primitive is "rate base × allowed RoE", not "discounted cash flow". POWERGRID FV landed at ₹290 against CMP ₹291 after the fix; that level of validation cannot come from a cohort multiple. **Survives §3 Decision Framework (math structurally different; generic DCF + Tier-2 cohort both fail; reference is public via CERC tariff orders).**

**D2 — PR #337 capital-goods engine disabled, scheduled for deletion.**
- Decision: disable on contact; delete ~600 LOC in Layer B W5 cleanup.
- Reasoning: the 7y-WC-smoothed FCF engine was built to fix 15 of 18 cohort tickers > 30% off consensus. Once shipped, reconciliation showed it pulled 6 of 18 FVs **further from** consensus, with the remaining gains being within statistical noise. The engine's premise — that smoothing WC over 7y "extracts the signal" — was wrong; it just re-weighted the same noisy FCF series the generic DCF already uses. The signal lives in **what comparable, similarly-profitable peers trade at**, not in another FCF reformulation. This is the canonical example of a rule-4 violation (sector engine shipped without reconciliation gating). It is also the catalyst for new discipline rule 5.

**D3 — Insurance engine deferred indefinitely (data blocker).**
- Decision: keep `docs/design/insurance-dcf-fix.md` as a 📋 design only; do not start implementation.
- Reasoning: insurance fair value requires Embedded Value + Value of New Business. IRDAI publishes EV in annual disclosures but the format is inconsistent across LIC / HDFCLIFE / SBILIFE / ICICIPRULI / ICICIGI / MAXFIN; we do not yet have a reliable auto-ingest path. Building the engine before the data is auto-ingested means manual EV updates per ticker per quarter — guaranteed staleness. **Build is gated on operator decision to either license a feed or fund the curation pipeline.** Until then, the 6 listed insurers route to Tier 2 with the "financial services — life / general" quality bucket; reconciliation will tell us whether that is good enough.

**D4 — Real estate developer engine deferred indefinitely (data blocker).**
- Decision: keep `docs/design/realty-developers-dcf-fix.md` as 📋 design only.
- Reasoning: realty-developer NAV requires per-project land-bank inventory + saleable-area assumptions + city-tier price curves. Three of those are quarterly-curated manually by the equity-research analyst at each broker; none is auto-ingestible from filings at reasonable cadence. DLF, OBEROIRLTY, GODREJPROP route to Tier 2 with a "real estate — developer" sector tag and bucket. If reconciliation shows persistent > 40% deltas on the 6 large developers, revisit. **Curation cadence is the operator decision.**

**D5 — Tier 2 cohort multiples chosen as the new default; Tier 1 (generic DCF) shrunk to a curated list.**
- Decision: invert the historical default. Most stocks no longer get custom DCF; they get sector quality-bucket median multiples.
- Reasoning: 8 sector engines built in 9 months, 2 work cleanly, 3 partial, 1 deprecated. The pattern is broken. Every external aggregator (Koyfin, Tikr, Tickertape, Screener.in) has already converged on cohort multiples for the long tail — not because the math is fancier, but because **most stocks do not have clean enough 5y FCF for a custom DCF to be defensible.** Tier 1 stays for the ~150 large-caps where generic DCF actually works; everything else routes to Tier 2 unless it is structurally Tier 3.

**D6 — Benchmark reconciliation (Layer A) declared the program's safety net.**
- Decision: every Phase 2 deprecation, every Tier 1↔Tier 2 routing change, every CACHE_VERSION bump is gated on a reconciliation diff.
- Reasoning: we do not have ground truth, but we have analyst consensus median as a high-quality external check. The reconciliation framework (PR #341) gives us a daily `|delta_pct|` per ticker. When local unit tests + canary 5/5 say "fine" but reconciliation says "we just moved 6 of 18 tickers further from consensus", **the reconciliation signal wins.** This is the discipline that catches what we can't see locally. Without it, Capital Goods #337 would still be live.

**D7 — FMCG brand-premium overlay (PR #336) scheduled for partial rollback.**
- Decision: delete the overlay math; preserve only the `BRAND_MOAT_PREMIUM_TICKERS` ROIC bump (~20 names), which folds into Tier 1.
- Reasoning: 150 LOC of FV-smoothing math; the only durable insight was "moat tickers deserve a ROIC premium." Keep the 30 LOC of curated list + ROIC bump; delete the rest. Scheduled W5 of Layer B migration.

**D8 — Cement engine (PRs #324 / #331) provisionally kept; W5 reconciliation decides.**
- Decision: do not deprecate yet; do not double-down either.
- Reasoning: cement engine currently lands 4 of 7 in band (ULTRACEMCO, SHREECEM, AMBUJACEM, ACC in; DALMIABHA, JKCEMENT, RAMCOCEM still outside band). M&A-truncation classifier is a data-cleaning win regardless and moves to the data layer in W5 cleanup. The engine itself stays until the W3 reconciliation report `docs/reconciliation/cement-tier2-vs-engine.md` shows whether Tier 2 wins ≥ 60% of head-to-heads.

---

## 6. Acceptance metrics per phase — current values

Snapshot 2026-05-18, cache v102.

| Phase | Metric | Target | Current | Status |
|---|---|---|---|---|
| **1 — Truth Universe** | Canary tickers with snapshot + consensus delta + confidence triplet | 180 | 50 (28%) → jumps to ~120 (67%) when `canary-universe-180` lands | 🟡 in-flight |
| **2 — Sector Engines** | Sectors at terminal state {✅, ⏸️, ❌} | 12 of 12 | 8 of 12 (67%) — pharma, cement, FMCG awaiting W5 reconciliation; cap-goods code awaiting deletion | 🟡 |
| **3 — Confidence Gating** | All canary tickers with daily confidence triplet | 100% | 100% ✅ | ✅ |
| **3 — Confidence Gating** | Under-Review rate Tier 1 | < 15% | n/a (Tier 1 not yet routed) | 🚧 |
| **3 — Confidence Gating** | Under-Review rate canary (proxy) | < 25% | ~22% | ✅ within target |
| **4 — Anomaly Detection** | Anomaly rules live | 7 of 7 | 6 of 7 (86%) — FCF-CAGR rule pending | 🟡 |
| **5 — Benchmark Reconciliation** | Reconciliation framework live | yes | yes ✅ | ✅ |
| **5 — Benchmark Reconciliation** | Daily outlier dashboard | yes | yes ✅ | ✅ |
| **5 — Benchmark Reconciliation** | Canary coverage with `|delta_pct|` | 180 / 180 | 50 / 180 (28%) | 🟡 |
| **5 — Benchmark Reconciliation** | Outlier-count reduction across Layer B migration | ≥ 30% | baseline being measured this week | 🚧 |

---

## 7. Open questions / unresolved

Each item has an owner and an ETA. Items move out of this section once decided; the decision moves to §5.

| # | Question | Owner | ETA | Notes |
|---|---|---|---|---|
| Q1 | Insurance EV / VNB data sourcing — licensed feed vs internal curation pipeline | Operator | Q3 2026 | Decision unblocks 📋 → 🚧 transition for `docs/design/insurance-dcf-fix.md`. Until then, LIC / HDFCLIFE / SBILIFE / ICICIPRULI / ICICIGI / MAXFIN ride Tier 2 "financial — life / general" bucket. |
| Q2 | Real estate developer land-bank curation cadence — quarterly manual vs annual auto-best-effort | Operator | Q3 2026 | Same shape as Q1. Routes DLF / OBEROIRLTY / GODREJPROP through Tier 2 in the interim. |
| Q3 | Cement engine — keep or deprecate | Architecture | Layer B W5 (~2026-06-22) | Decision gated on `docs/reconciliation/cement-tier2-vs-engine.md`. Threshold: keep if Tier 2 head-to-head wins ≤ 3 of 7; else deprecate. |
| Q4 | DRREDDY-class XBRL unit deep bug | Data ingest | open | Defensive cap masks the symptom (anomaly rule 6, `unit_mismatch_guard`); root cause not found. Suspected to be a units-of-measure inconsistency in NSE XBRL filings for tickers with multi-currency footnotes. Continuing investigation. |
| Q5 | Tier 1 curated list size — 130, 150, 170, or 220? | Architecture | Layer B W4 | Recommend starting at 150 and tuning at W4 against the reconciliation table. |
| Q6 | Defense PSU — keep as advisory flag only, or build a "defense premium" Tier 2 bucket? | Architecture | Layer B W3 | Tentative: build the bucket for HAL, BEL, BDL, BEML, COCHINSHIP, MAZDOCK; retain the flag in parallel. |
| Q7 | FCF-CAGR anomaly rule (Phase 4 rule 7) | Backend | Phase 4.1 (2026-Q3) | Design exists; implementation in backlog. |
| Q8 | Tier 2 reverse-DCF semantics | Architecture | Layer B W4 | Reverse-DCF is meaningless for cohort-multiple FVs. Recommend reporting "implied P/E vs cohort P/E gap" rather than implied growth. |

---

## 8. What this doc IS

- The **living source of truth** for "what is the model doing right now, and why".
- The **reference** new agents, new operators, and external auditors should read first.
- The **contract YieldIQ keeps with itself** — every phase, every engine disposition, every discipline rule has a reasoned position here.
- A **decision log** that grows monotonically. Past decisions are not edited; they are superseded with a new dated entry.

## 9. What this doc is NOT

- **Not marketing collateral.** No claims about beating analysts, no "Bloomberg Terminal" framing, no leaderboards.
- **Not user-facing.** Retail investors see verdicts, FVs, confidence labels, and methodology pages — not this. Where this doc and a user-facing page disagree, the user-facing page is updated.
- **Not set in stone.** Quarterly revision cadence. Phase definitions, acceptance metrics, and even the mission statement can shift if the data demands it. The discipline rules in §4 are the most durable component; they change only after a documented post-mortem.
- **Not a substitute for the design docs.** Each phase, each engine, and each Tier links out to the design doc that owns the implementation detail. This doc is the index; those docs are the contracts.

---

## 10. Related documents

Read these in order if you are new:

1. `docs/design/valuation-architecture-simplification.md` — Layer B architecture (Tier 1 / Tier 2 / Tier 3).
2. `docs/design/benchmark-reconciliation-framework.md` — Layer A (the scoreboard).
3. `CLAUDE.md` — root discipline (canary, snapshot, fix-is-fixed).
4. `docs/design/regulated-utility-dcf-fix.md` — canonical "sector engine is structurally justified".
5. `docs/design/capital-goods-dcf-fix.md` — canonical "sector engine was NOT structurally justified".
6. `docs/design/fmcg-dcf-fix.md` — canonical "overlay was 95% noise, 5% durable insight".
7. `docs/design/pharma-dcf-fix.md` — current state; bucket-quality fix candidate.
8. `docs/design/cement-dcf-fix.md` — provisional; W5 reconciliation decides.
9. `docs/design/bank-equity-source-fix.md` — banks P/B engine.
10. `docs/design/reit-valuation-fix.md` — REIT skip-DCF classifier.
11. `docs/design/defense-psu-dcf-fix.md` — defense advisory flag.
12. `docs/design/insurance-dcf-fix.md` — insurance EV/VNB design (📋 only).
13. `docs/design/realty-developers-dcf-fix.md` — realty developer design (📋 only).
14. `docs/CI_GATES.md` — canary GH Actions workflow definition.
15. `docs/cache_version_discipline.md` — CACHE_VERSION bump protocol.
16. `memory/feedback_yieldiq_discipline.md` — discipline rules in user memory.

---

## 11. Revision history

| Date | Reviser | Change |
|---|---|---|
| 2026-05-18 | architecture | Initial draft; consolidates 5-phase program from competitive audit + decisions from today's session (D1–D8). |
