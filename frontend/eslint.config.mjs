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
]);

export default eslintConfig;
