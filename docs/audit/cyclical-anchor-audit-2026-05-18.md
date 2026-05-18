# Cyclical-Trough Anchor Audit — 2026-05-18

**Scope**: verify PR #69-#70 (`CYCLICAL_TROUGH_ANCHOR`) is firing correctly
post-`CACHE_VERSION = 114`. Investigation only — no code changes.

**Files inspected**
- `backend/services/analysis/service.py` (anchor gate at L1696-L1726, propagation L2507-L2531)
- `backend/services/analysis/constants.py` (`CYCLICAL_TICKERS` L250, `CYCLICAL_SECTORS` L279, `is_cyclical()` L710)
- Prod endpoint `https://api.yieldiq.in/api/v1/public/stock-summary/{ticker}.NS`

---

## 1. Anchor logic (current, v114)

Gate (service.py L1696):

```
if is_cyclical(ticker, _resolved_sector_for_cycle)
   and price > 0
   and iv < 0.2 * price:
    _pre_anchor_iv = iv
    iv = round(price * 0.95, 2)               # base
    _trough_anchor_bear_iv = round(price * 0.85, 2)
    _trough_anchor_bull_iv = round(price * 1.10, 2)
    _trough_anchor_fired = True
```

Propagation (L2507) overrides scenario engine's bear/bull with anchored
0.85x / 1.10x band when the anchor fires.

Cyclical universe is union of:
- `CYCLICAL_TICKERS` (Steel / Metals / Oil&Gas / Cement / Coal /
  Sugar / Fertilisers / Shipping / RELIANCE)
- `CYCLICAL_SECTORS = {"Metals & Mining", "Oil & Gas", "Steel"}`

Sector-engine routing in Step 6 short-circuits *before* the anchor for:
- REITs (`is_reit_ticker` → data_limited)
- Regulated utilities (rate-base path)
- Banks (P/B path, `is_financial`)
- Recent IPOs (sector-relative)

So a ticker that is *both* in `CYCLICAL_TICKERS` AND now routes through a
sector engine cannot reach the anchor gate — by construction the anchor
only sees DCF residue. No double-routing collision detected.

---

## 2. Live prod state (2026-05-18, v114)

| Ticker      | Sector         | CMP    | FV     | uncapped_fv | bear   | bull   | src          | verdict        | anchor? |
|-------------|----------------|--------|--------|-------------|--------|--------|--------------|----------------|---------|
| TATASTEEL   | Metals/Mining  | 209.71 | 168.15 | **199.22**  | 134.52 | 230.68 | peer_capped  | overvalued     | FIRED   |
| JSWSTEEL    | Metals/Mining  | 1287.4 | 753.07 | **1223.03** | 602.46 | 1416.14| peer_capped  | data_limited   | FIRED   |
| HINDALCO    | Metals/Mining  | 1053.1 | 320.05 | —           | 108.03 | 542.88 | dcf          | overvalued     | no (ratio=0.30) |
| COALINDIA   | Oil & Gas*     | 465.30 | 621.24 | —           | 351.25 | 882.68 | dcf          | undervalued    | no      |
| ONGC        | Oil & Gas      | 297.20 | 176.70 | —           | 51.89  | 328.33 | dcf          | overvalued     | no (ratio=0.59) |
| SAIL        | Metals/Mining  | 190.57 | 181.04 | —           | 144.83 | 217.25 | dcf          | fairly_valued  | no      |
| JINDALSTEL  | General/Div.   | 1231.8 | 1310.64| —           | 1047.03| 1572.77| dcf          | fairly_valued  | no      |
| NMDC        | Metals/Mining  | 90.14  | 79.20  | —           | 45.71  | 108.22 | dcf          | fairly_valued  | no      |
| VEDL        | Metals/Mining  | 327.00 | 521.82 | —           | 272.20 | 777.64 | dcf          | undervalued    | no      |
| BPCL        | Oil & Gas      | 280.80 | 202.74 | —           | 101.76 | 344.77 | dcf          | overvalued     | no (ratio=0.72) |
| IOC         | Oil & Gas      | 131.81 | 49.36  | —           | **1.59** | 117.87 | dcf        | data_limited   | no (ratio=0.37) |
| HPCL        | —              | —      | —      | —           | —      | —      | **503**      | under_review   | n/a     |

*COALINDIA shows sector=`Oil & Gas` in the response — that's the
SECTOR_OVERRIDES coalescing of Coal under O&G for display. Ticker
membership in `CYCLICAL_TICKERS` carries the anchor either way.

---

## 3. Per-ticker diagnosis

### Anchor-fired group (working as designed)
- **TATASTEEL** — DCF residue produced iv well under 0.2*price; anchor
  set uncapped_fv=199.22 (0.95*209.71). Peer-cap then trimmed FV to
  168.15 (1.5 × peer-median P/E ₹112.10). Bear=134.52, Bull=230.68 are
  the anchored 0.85/1.10 band — *but* base case is no longer the
  anchor's 0.95 (it's the peer-capped 0.80*price). **Anchor + peer-cap
  collision** (see §4 finding A).
- **JSWSTEEL** — same pattern. Uncapped=1223 (≈0.95*1287). Peer-cap
  cuts to 753 (0.58*price). Verdict shows `data_limited`. Same
  collision as TATASTEEL.

### Anchor-eligible but not fired (correctly)
- **HINDALCO** ratio 0.30 > 0.20: anchor stays off. FV 320 looks low
  relative to CMP 1053, but engine produced a non-trivial iv — that's
  a *valuation gap*, not a trough miss. ⚠ See §4 finding B.
- **ONGC** ratio 0.59, **BPCL** ratio 0.72 — both healthy DCFs by the
  anchor's definition. Verdicts (overvalued) reflect cycle-peak crude.
- **IOC** ratio 0.37 — above threshold so anchor doesn't fire, but
  **bear=₹1.59 is broken**. Engine produced a near-zero bear that
  `_enforce_scenario_order` accepted. The anchor was designed to
  rescue exactly this kind of degenerate scenario output. See §4
  finding C.

### Healthy DCF (no anchor needed)
- COALINDIA, SAIL, JINDALSTEL, NMDC, VEDL — bear/base/bull bands are
  sensible. No regression.

### Broken upstream
- **HPCL.NS** returns 503 `cache_miss_recompute_failed`. Unrelated to
  anchor — investigate ingest. (Note: HINDPETRO.NS, the older alias,
  returns successfully with sector=Oil&Gas, FV=569.80, CMP=358.90.)

---

## 4. Regressions detected post-v114

### Finding A — anchor + peer-cap collision (TATASTEEL, JSWSTEEL)
**Severity**: medium. Anchor fires (L1696) → iv = 0.95*price. Then peer-cap
block (L2191) runs unconditionally and trims iv down to peer-median
× 1.5, overwriting the anchored base. Result: base case is no longer
inside the [0.85, 1.10] band the anchor propagated to bear/bull —
TATASTEEL displays bear=134.52, base=168.15, bull=230.68, which is an
inconsistent story (base is the peer cap, bear/bull are the anchor).

The anchor's purpose is to say *"cycle-bottom DCF is unreliable, pin
to current price."* Peer-capping on top reintroduces a different,
weaker form of cycle-bottom signal (peer P/E during a sector trough is
also depressed). The TATASTEEL audit trail (`peer_cap_details.median_pe
= 29.07`) shows the peer set itself is metals — capping a metals
anchor against a metals-median P/E during a metals trough defeats the
anchor.

**Recommended fix**: skip peer-cap when `_trough_anchor_fired` is true.
One-line guard at L2191.

### Finding B — HINDALCO falls into the "0.2-0.5" twilight zone
**Severity**: low / observational. iv/price = 0.30 — above the 0.2 anchor
threshold but well below the 0.5 fair-value band. The anchor's
threshold was tuned for "iv ≈ 0 from equity_value short-circuit"
(deep trough). With normalized-FCF (PR #68) doing its job, deep-zero
cases are rarer; the new failure mode is "iv = real but absurdly low
because trough-FCF × debt drag still produces ~0.3*price."

**Recommended fix**: consider raising the threshold from `0.2 * price`
to `0.35 * price` for super-cyclicals (`_CAPEX_SUPER_CYCLICAL_TICKERS`).
Needs canary-diff before merge; the 0.35 threshold would also catch
IOC (finding C). Probably also catches BPCL (ratio 0.72 — would NOT
catch BPCL at 0.35).

### Finding C — IOC bear=₹1.59
**Severity**: medium (cosmetic but undermines the page). Anchor doesn't
fire (ratio 0.37 > 0.20). Bear scenario from the DCF engine is ₹1.59,
which `_enforce_scenario_order` accepts (1.59 ≤ 49.36 ≤ 117.87 is
"ordered"). Frontend shows a bear case of essentially ₹0 — the exact
display pathology PR #168 was built to prevent.

**Recommended fix**: same as Finding B (lift threshold), OR add a
*secondary* bear-floor guard: if `bear_iv < 0.10 * price` AND
`is_cyclical(ticker)`, clamp bear to `0.85 * price` independent of
whether the base-anchor fired. This is a narrower intervention than
B.

### Finding D — `_CYCLICAL_SECTORS` taxonomy drift
**Severity**: documentation-only. There are now *three* cyclical-sector
sets in the codebase, none of which agree:
- `constants.py::CYCLICAL_SECTORS = {Metals & Mining, Oil & Gas, Steel}`
- `analytical_notes.py::_CYCLICAL_SECTORS = {fmcg, cement, auto, chemicals}`
- `confidence_service.py::_CYCLICAL_SECTORS = frozenset({...})`

These serve different purposes (anchor gating vs note generation vs
confidence-band derate) but the shared name invites cargo-culting.
The `analytical_notes` set includes `cement` — the same `cement` that
was *removed* from anchor gating in April. Whether by design or not is
not obvious from a single grep.

**Recommended fix**: rename to disambiguate (`_CYCLICAL_NOTE_SECTORS`,
`_CYCLICAL_CONFIDENCE_SECTORS`). Pure rename, no behaviour change.

---

## 5. In good shape

- COALINDIA, SAIL, JINDALSTEL, NMDC, VEDL, HINDPETRO — bands are
  consistent, no anchor needed.
- Anchor *gate* is still correctly excluding REITs / utilities / banks
  / recent IPOs (sector engines short-circuit upstream of L1696).
- Anchor *propagation* to bear/bull (L2507) works — verified on
  TATASTEEL/JSWSTEEL where bear/bull are the anchored band.

## 6. Recommended next steps

1. **Highest priority**: design doc for Finding A (anchor + peer-cap
   collision). Single-line skip-when-anchor-fired guard. Write
   `docs/design/cyclical-anchor-peercap-skip.md` and ship behind
   canary-diff.
2. **Medium**: design doc for Finding C (bear-floor secondary guard for
   IOC-type cases).
3. **Low / no-rush**: rename `_CYCLICAL_SECTORS` constants to
   disambiguate (Finding D).
4. **Unrelated**: investigate HPCL.NS 503 (cache_miss_recompute_failed).
   Separate from anchor work.

## Hard rules respected
- Investigation only; no code touched.
- This document committed on a docs-only branch.
- DO NOT merge until reviewed.
