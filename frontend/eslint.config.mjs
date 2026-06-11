import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  // Day-35 (2026-05-20): ban .toLocaleString in component files so
  // currency / number formatting MUST go through lib/utils.ts. Without
  // this rule, components historically diverged on decimal precision
  // ("₹1,200" vs "₹1200.00") and locale tag ("en-IN" vs "en-US") —
  // fixed point-by-point but kept regressing. The lint rule prevents
  // that regression class entirely.
  //
  // Allowlisted files:
  //   - lib/utils.ts        — defines formatCurrency / formatNumberWithSuffix
  //   - lib/currency.ts     — locale + symbol primitives
  //   - lib/screenerFilters.ts — DSL serialiser; not a formatter
  //   - any *.test.* or *.spec.* file — test fixtures
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: [
      "src/lib/utils.ts",
      "src/lib/currency.ts",
      // 2026-06-11: canonical number-comprehension formatter layer
      // (formatINR / formatCrore / formatPct / formatMultiple /
      // formatCompactCount). Same exemption class as lib/utils.ts —
      // it IS the formatter components must route through.
      "src/lib/formatNumbers.ts",
      "src/**/*.test.{ts,tsx}",
      "src/**/*.spec.{ts,tsx}",
    ],
    rules: {
      "no-restricted-syntax": [
        "warn",
        {
          selector: "CallExpression[callee.property.name='toLocaleString']",
          message:
            "Use formatCurrency / formatNumberWithSuffix / formatPercentage / " +
            "formatRateDecimal from @/lib/utils instead of .toLocaleString(). " +
            "Keeps currency + number formatting consistent across the app.",
        },
      ],
    },
  },
  // ROOT CAUSE #1 (2026-06-10): canonical headline Fair Value invariant.
  //
  // The single source of truth for the user-visible "Fair Value" number
  // is `signals.headlineFairValue` (resolved by useHeroSignals from the
  // backend's `headline_fair_value` field). Every hero, caveat, FAQ,
  // AI Why paragraph, peer table, OG card and JSON-LD surface MUST read
  // it via that resolver.
  //
  // Two surfaces LEGITIMATELY need the DCF-only value and are exempt:
  //   - DcfMultiplesChip     — by definition compares DCF vs Multiples
  //   - ValuationMethodsPanel — breaks out each engine's standalone FV
  //
  // ValuationOutput / scenarios / og-route SSR JSON shapes that mirror
  // backend wire formats are also exempt (those are pass-through reads,
  // not render-path templating).
  //
  // The rule warns on direct member reads of
  //   - signals.fairValue
  //   - x.valuation.fair_value
  // in `src/components/analysis/**` and `src/app/**/analysis/**`.
  // Annotate a deliberate read with the standard ESLint pragma
  // `// eslint-disable-next-line no-restricted-syntax -- headline-fv-allow: <reason>`.
  {
    files: [
      "src/components/analysis/**/*.{ts,tsx}",
      "src/app/**/analysis/**/*.{ts,tsx}",
      "src/app/(marketing)/fair-value/**/*.{ts,tsx}",
      "src/app/api/og/**/*.{ts,tsx}",
    ],
    ignores: [
      // Surfaces that LEGITIMATELY need the DCF-only number.
      "src/components/analysis/DcfMultiplesChip.tsx",
      "src/components/analysis/ValuationMethodsPanel.tsx",
      // The resolver itself defines `fairValue` and `headlineFairValue`.
      "src/lib/useHeroSignals.ts",
      // Tests load fixtures + invariants directly.
      "src/**/*.test.{ts,tsx}",
      "src/**/*.spec.{ts,tsx}",
    ],
    rules: {
      "no-restricted-syntax": [
        "warn",
        {
          selector: "CallExpression[callee.property.name='toLocaleString']",
          message:
            "Use formatCurrency / formatNumberWithSuffix / formatPercentage / " +
            "formatRateDecimal from @/lib/utils instead of .toLocaleString().",
        },
        {
          selector:
            "MemberExpression[object.name='signals'][property.name='fairValue']",
          message:
            "ROOT CAUSE #1 — read `signals.headlineFairValue` (the canonical " +
            "composite-IV-preferred number) instead of `signals.fairValue` " +
            "(DCF-only). Only DcfMultiplesChip and ValuationMethodsPanel may " +
            "read the DCF-only value — those files are eslint-ignored.",
        },
        {
          selector:
            "MemberExpression[property.name='fair_value'][object.type='MemberExpression'][object.property.name='valuation']",
          message:
            "ROOT CAUSE #1 — read `payload.headline_fair_value` (the canonical " +
            "composite-IV-preferred number) or `signals.headlineFairValue` " +
            "from useHeroSignals, NOT `valuation.fair_value` directly. Only " +
            "DcfMultiplesChip and ValuationMethodsPanel may read the DCF-only " +
            "value; those files are eslint-ignored.",
        },
      ],
    },
  },
]);

export default eslintConfig;
