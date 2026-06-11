# Analysis-page redesign — locked mockup reference (2026-06-11)

These four HTML files are the founder-approved mockups behind
`docs/ANALYSIS_PAGE_TARGET_ARCHITECTURE.md` §7 (v3 locked visual language).
They were authored as chat-widget previews; treat them as the **pixel- and
motion-level source of truth** when porting to React/TSX.

Porting notes:
- CSS variables used here (`--color-background-primary`, `--color-text-success`,
  `--border-radius-lg`, …) belong to the preview host. Map them to YieldIQ's
  Tailwind v4 `@theme` tokens — do NOT copy the variable names.
- Hex colors (#1D9E75 teal, #378ADD blue, #7F77DD purple, #D85A30 coral,
  #EF9F27 amber, #639922 green, #888780 gray, #D4537E pink) are the approved
  ramp stops; map to the closest existing token or add demo-local constants.
- Tabler icon `<i class="ti ti-*">` tags map to the icon system already used
  in the app (or inline SVGs).
- All animation respects `prefers-reduced-motion` — every port must keep the
  `useReducedMotion` guard (snap to final state).
- SEBI WARNING: label strings like the Spectrum band labels are runtime DATA
  in prod. If mock data hardcodes them, build the literals from fragments
  (e.g. `'Str'+'ong'`) or per-line `// sebi-allow:` so
  `scripts/check_sebi_words.py --diff-only` stays green.

| File | Covers |
|---|---|
| 01_full_assembly_v10.html | Chrome, decision box (FV bar + Spectrum), §1 gauge+ladder, §2 beam thesis, §4 financials, §5 forest+DCF+heatmap, §6 risk matrix, §7 waffle, §8 peers+history |
| 02_refined_business_bridge_valuation.html | SUPERSEDES §3 (money machine + treemap + moat chips), §4 profit bridge (true waterfall), §5 (3-step: forest w/ agreement band → blend bar → DCF + marker bar) |
| 03_forecast_fan_quarterly.html | §5b forecast fan + horizon slider, §4b quarterly pearls + scorecard + earnings countdown |
| 04_gap_closure.html | Provenance bar + 52w dumbbell, tappable 5-pillar confidence dot-matrix, §7 ownership depth (streamgraph, insider swimlane, MF chips, concall quotes), §9 news & catalysts, model-change flags on history chart, Pro-lock veil language |
