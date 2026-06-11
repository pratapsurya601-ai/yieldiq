// Demo-local color constants mirroring the locked mockup hexes
// (docs/redesign_mockups/README.md "approved ramp stops").
//
// NOTE: in the real build these map onto the token palette in
// globals.css (one chart-theme module, zero raw hexes). They are kept
// verbatim here so this throwaway preview stays pixel-faithful to the
// founder-approved mockups. Neutrals (ink / caption / border / surface)
// already use the live tokens via CSS variables.
export const DEMO_COLORS = {
  teal: "#1D9E75",
  tealDark: "#0F6E56",
  tealDeep: "#085041",
  tealLight: "#5DCAA5",
  tealFaint: "#9FE1CB",
  blue: "#378ADD",
  blueDark: "#185FA5",
  blueDeep: "#0C447C",
  blueLight: "#85B7EB",
  blueFaint: "#B5D4F4",
  purple: "#7F77DD",
  purpleDark: "#534AB7",
  purpleLight: "#AFA9EC",
  coral: "#D85A30",
  coralDark: "#993C1D",
  coralDeep: "#712B13",
  coralLight: "#F0997B",
  amber: "#EF9F27",
  amberDark: "#854F0B",
  olive: "#639922",
  gray: "#888780",
  grayLight: "#B4B2A9",
  pink: "#D4537E",
} as const

/** Live theme tokens, for SVG attributes that can't take Tailwind classes. */
export const TOKENS = {
  ink: "var(--color-ink)",
  body: "var(--color-body)",
  caption: "var(--color-caption)",
  border: "var(--color-border)",
  surface: "var(--color-surface)",
  raised: "var(--color-raised)",
  success: "var(--color-success)",
  warning: "var(--color-warning)",
} as const
