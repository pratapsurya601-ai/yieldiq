// @ts-nocheck
/**
 * Tests for ValueBandChip.
 *
 * NOTE: this repo does not yet have a test runner installed. The file
 * is written against vitest + @testing-library/react conventions so it
 * runs unmodified once those deps are added. The `@ts-nocheck` above
 * keeps `tsc --noEmit` and `next build` green until those deps land.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import {
  ValueBandChip,
  type ValueBand,
} from "@/components/hex/ValueBandChip"

const BANDS: { band: ValueBand; label: string }[] = [
  { band: "strong_discount", label: "Strong discount" },
  { band: "below_peers", label: "Below peers" },
  { band: "in_range", label: "In range" },
  { band: "above_peers", label: "Above peers" },
  { band: "notably_overvalued", label: "Notably overvalued" },
  { band: "data_limited", label: "Data limited" },
]

describe("ValueBandChip", () => {
  for (const { band, label } of BANDS) {
    it(`renders the ${band} band with its label`, () => {
      render(<ValueBandChip band={band} label={label} percentile={50} />)
      const chip = screen.getByTestId("value-band-chip")
      expect(chip).toHaveAttribute("data-band", band)

      const labelEl = screen.getByTestId("value-band-chip-label")
      if (band === "data_limited") {
        expect(labelEl.textContent).toBe("—")
      } else {
        expect(labelEl.textContent).toBe(label)
      }
    })
  }

  it("renders an em-dash and no percentile for data_limited", () => {
    render(
      <ValueBandChip
        band="data_limited"
        label="Data limited"
        percentile={42}
      />,
    )
    expect(screen.getByTestId("value-band-chip-label").textContent).toBe("—")
    expect(screen.queryByTestId("value-band-chip-percentile")).toBeNull()
  })

  it("renders the percentile suffix for non-data_limited bands", () => {
    render(
      <ValueBandChip band="in_range" label="In range" percentile={52} />,
    )
    expect(
      screen.getByTestId("value-band-chip-percentile").textContent,
    ).toBe("52th")
  })

  it("omits percentile when not provided", () => {
    render(<ValueBandChip band="in_range" label="In range" />)
    expect(screen.queryByTestId("value-band-chip-percentile")).toBeNull()
  })
})
