#!/usr/bin/env python3
"""
_backfill_manifest_titles.py — one-shot script to inject ``title_public``
into every entry of cache_invalidation_manifest.MANIFEST that is
missing one.

Approach
========
1. Load the manifest dict-by-dict using the live MANIFEST list (so we
   can apply our `_humanise_title_public` helper consistently).
2. For each entry without a usable ``title_public``, derive one from
   the rationale, validate against the banned-pattern guard, and
   merge in a per-version_id override map for the worst offenders the
   auto-deriver can't handle cleanly.
3. Rewrite the manifest source file in place: for every dict literal
   whose ``"version_id": "..."`` line matches one we're patching, we
   inject a ``"title_public": "..."`` line immediately ABOVE the
   ``"applied_at":`` line. The dict shape stays consistent; existing
   comments + scope + rationale survive unchanged.

The script is idempotent: running it twice is a no-op (entries that
already carry a title_public are skipped).

Usage
=====
    python scripts/_backfill_manifest_titles.py            # apply in-place
    python scripts/_backfill_manifest_titles.py --dry-run  # print plan only
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MANIFEST_PATH = ROOT / "backend" / "services" / "cache_invalidation_manifest.py"


# ─────────────────────────────────────────────────────────────────
# Hand-authored title_public overrides for the worst-offender entries.
# These are the ones surfaced verbatim on yieldiq.in/analysis/HDFCBANK
# History tab on 2026-06-10:
#   "T4.5 + T4.6 + T4.7 + T4.8 + T4.10 — five accounting normalizations…"
#   "T4.2 + T4.3 + T4.4 + T4.9 — four accounting normalizations…"
#   "T3.1 — bank residual-income engine deepened with NIM decomposition…"
#   "v_t6_2_ai_chat_phase_a_2026_06_10"
#   "Verdict gate now reads composite_intrinsic_value when present…"
#
# Plus a sweep of other roadmap-tier-coded entries that the auto-deriver
# can't pretty up enough.
# ─────────────────────────────────────────────────────────────────
OVERRIDES: dict[str, str] = {
    # The four explicitly-listed leaks from the brief.
    "v_t4_normalizations_part_2_2026_06_10": (
        "Five accounting normalizations added (minority interest, working "
        "capital, effective tax rate, pension, FX translation)"
    ),
    "v_t4_normalizations_batch_2026_06_10": (
        "Four accounting normalizations added (leases, R&D, excess cash, "
        "litigation provisions)"
    ),
    "v_t3_1_bank_residual_income_deepened_2026_06_10": (
        "Bank residual-income engine deepened — NIM decomposition, CASA "
        "sensitivity, provision coverage, DuPont ROE"
    ),
    "v_phase_c_2_verdict_gate_composite_consumption_2026_06_10": (
        "Verdict now consumes the Composite Intrinsic Value (with fair-value "
        "fallback)"
    ),
    "v_t6_2_ai_chat_phase_a_2026_06_10": (
        "Multi-turn AI chat panel on the analysis page"
    ),
    # Engine-roadmap T-tier entries — pretty-print each.
    "v_t1_1_composite_intrinsic_value_2026_06_09": (
        "Composite Intrinsic Value — weighted blend of DCF, multiples, and "
        "Wall-St consensus"
    ),
    "v_t1_3_sector_wacc_tg_calibrated_2026_06_10": (
        "Sector-calibrated WACC and Terminal Growth tables (Damodaran India "
        "2026 anchored)"
    ),
    "v_t1_4_holdco_sotp_phase_a_2026_06_10": (
        "Holdco sum-of-the-parts valuation service (sector-tuned holdco "
        "discounts)"
    ),
    "v_t1_5a_analyst_calibration_service_2026_06_09": (
        "Analyst calibration service — YieldIQ versus Wall-Street price-"
        "target deviation report"
    ),
    "v_t1_6_confidence_composite_agreement_2026_06_10": (
        "Confidence pillar added: agreement between fair-value estimators"
    ),
    "v_t2_1_ddm_phase_a_2026_06_10": (
        "Dividend Discount Model standalone service (Gordon, two-stage, "
        "H-model)"
    ),
    "v_t2_2_epv_phase_a_2026_06_10": (
        "Earnings Power Value standalone service (Greenwald framework)"
    ),
    "v_t2_3_replacement_value_phase_a_2026_06_10": (
        "Replacement Value standalone service (Graham / Tobin Q framework)"
    ),
    "v_t2_4_probability_weighted_fv_phase_a_2026_06_10": (
        "Probability-weighted fair value service (three- or four-scenario "
        "weighting)"
    ),
    "v_t2_5_three_stage_dcf_phase_a_2026_06_10": (
        "Three-stage growth DCF standalone service (explicit high-growth, "
        "linear fade, terminal)"
    ),
    "v_t2_6_apv_phase_a_2026_06_10": (
        "Adjusted Present Value (APV) standalone valuation service"
    ),
    "v_t2_8_liquidation_value_phase_a_2026_06_10": (
        "Liquidation Value standalone service (Graham framework, downside "
        "floor)"
    ),
    "v_t3_2_nbfc_roa_phase_a_2026_06_10": (
        "NBFC ROA-tree (DuPont) standalone valuation service for non-bank "
        "financials"
    ),
    "v_t3_3_insurance_ev_vnb_2026_06_10": (
        "Embedded Value + Value of New Business appraisal added for life "
        "insurers"
    ),
    "v_t3_4_re_developer_phase_a_2026_06_10": (
        "Real-estate developer valuation framework (land bank, forward "
        "sales, rental perpetuity)"
    ),
    "v_t3_5_pharma_pipeline_phase_a_2026_06_10": (
        "Pharma pipeline risk-adjusted NPV standalone service"
    ),
    "v_t3_6_it_services_overlay_phase_a_2026_06_10": (
        "IT services overlay — adjusts fair value for client / vertical / "
        "geography concentration"
    ),
    "v_t3_7_auto_oem_cycle_phase_a_2026_06_10": (
        "Auto OEM mid-cycle normalization service (sqrt of peak × trough)"
    ),
    "v_t3_7_oil_gas_phase_a_2026_06_10": (
        "Oil & gas reserves valuation service (upstream NPV, downstream "
        "EV/EBITDA, city-gas volume)"
    ),
    "v_t3_8_cement_utilization_phase_a_2026_06_10": (
        "Cement capacity-utilization × EBITDA-per-tonne valuation framework"
    ),
    "v_t3_9_steel_cost_curve_phase_a_2026_06_10": (
        "Steel cost-curve quartile + integration premium valuation framework"
    ),
    "v_t3_11_telecom_arpu_phase_a_2026_06_10": (
        "Telecom ARPU-driven valuation service (5-year subscriber × ARPU DCF)"
    ),
    "v_t3_12_utilities_maintenance_phase_a_2026_06_10": (
        "Utilities maintenance-capex intensity overlay for regulated "
        "utilities"
    ),
    "v_t3_13_consumer_durables_wc_phase_a_2026_06_10": (
        "Consumer durables working-capital normalization framework"
    ),
    "v_t3_14_media_subscriber_ltv_phase_a_2026_06_10": (
        "Media subscriber lifetime-value valuation framework"
    ),
    "v_t3_15_logistics_freight_phase_a_2026_06_10": (
        "Logistics freight valuation framework (six freight-mode segments)"
    ),
    "v_t4_1_sbc_dilution_phase_a_2026_06_10": (
        "Stock-based-compensation dilution adjustment as an additive "
        "financials field"
    ),
    "v_t5_3_derived_insights_2026_06_10": (
        "Derived insights surfaced — earnings momentum, growth quality, "
        "valuation stability"
    ),
    "v_t5_7_monthly_accuracy_report_2026_06_10": (
        "Monthly accuracy report cron — 30-day-forward direction accuracy "
        "and magnitude error per sector"
    ),
    "v_phase_b_estimator_surfacing_2026_06_10": (
        "Five standalone valuation estimators (DDM, EPV, three-stage DCF, "
        "liquidation, probability-weighted) surfaced in the analysis "
        "response"
    ),
    "v_phase_b_sector_routing_mega_2026_06_10": (
        "Mega-wiring — 14 sector engines now route their tickers through "
        "the composite intrinsic-value service"
    ),
    "v_data_limited_gate_tighten_2026_05_24": (
        "Tightened the data-limited verdict gate — requires missing "
        "scenarios in addition to low confidence; stops zeroing fair value "
        "in the edge case"
    ),
    "v_sector_heatmap_2026_06_10": (
        "Sector heatmap added — sector cohort as a tile grid sized by market "
        "cap, coloured by margin of safety"
    ),
    "v_concall_sentence_sentiment_2026_06_10": (
        "Concall sentence-level sentiment — per-sentence polarity, topic "
        "clustering, management-tone shift"
    ),
    "v_news_fv_correlation_2026_06_10": (
        "News-to-fair-value correlation panel — links material fair-value "
        "moves to news headlines within ±7 days"
    ),
    "v_implied_assumptions_extension_2026_06_10": (
        "Implied-assumptions panel — what does the market expect at the "
        "current price?"
    ),
    "v_forward_earnings_calendar_fv_impact_2026_06_10": (
        "Forward earnings calendar with per-5%-beat fair-value impact "
        "preview"
    ),
    "v_cross_engine_consensus_signal_2026_06_10": (
        "Cross-engine consensus signal — when N estimators agree on "
        "direction vs price, mark as high conviction"
    ),
}


def _import_helpers():
    try:
        from backend.services.cache_invalidation_manifest import (  # noqa: WPS433
            MANIFEST,
            _humanise_title_public,
            _matches_banned_title_pattern,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[backfill] failed to import manifest module: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)
    return MANIFEST, _humanise_title_public, _matches_banned_title_pattern


def _derive_title(
    entry: dict,
    humanise,
    matcher,
) -> str:
    """Compute the title_public for a single entry.

    Precedence:
        1. OVERRIDES[version_id] if present.
        2. humanise(rationale).
        3. Fall through to "Model updated." if both fail the guard.
    """
    vid = entry.get("version_id") or ""
    if vid in OVERRIDES:
        return OVERRIDES[vid]
    rationale = entry.get("rationale") or ""
    candidate = humanise(rationale)
    if matcher(candidate) is None:
        return candidate
    # Fall back to "Model updated." — operator will hand-edit later.
    return "Model updated."


def _build_insertion_map() -> dict[str, str]:
    """Walk MANIFEST and build {version_id: title_public}."""
    manifest, humanise, matcher = _import_helpers()
    out: dict[str, str] = {}
    for entry in manifest:
        vid = (entry or {}).get("version_id")
        if not vid:
            continue
        existing = (entry or {}).get("title_public")
        if isinstance(existing, str) and existing.strip():
            continue
        out[vid] = _derive_title(entry, humanise, matcher)
    return out


def _escape_for_python_str(s: str) -> str:
    """Escape s so it can be embedded in a Python double-quoted string."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _patch_source(plan: dict[str, str], dry_run: bool) -> int:
    """Inject the title_public line above the applied_at line for each
    entry in `plan`. Returns the number of entries patched."""
    src = MANIFEST_PATH.read_text(encoding="utf-8")
    lines = src.splitlines()
    out: list[str] = []
    i = 0
    patched = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # Look for a `"version_id": "VID",` line and check if we have
        # a plan entry for VID. If so, scan forward to the next
        # `"applied_at":` line and insert the title_public line above
        # it (preserving the leading whitespace of the applied_at line).
        m = re.match(r'^(\s*)"version_id":\s*"([^"]+)"\s*,?\s*$', line)
        if m and m.group(2) in plan:
            vid = m.group(2)
            title = plan[vid]
            indent = m.group(1)
            out.append(line)
            j = i + 1
            while j < n:
                next_line = lines[j]
                if re.match(r'^\s*"applied_at"\s*:', next_line):
                    out.append(
                        f'{indent}"title_public": '
                        f'"{_escape_for_python_str(title)}",'
                    )
                    out.append(next_line)
                    patched += 1
                    i = j + 1
                    break
                out.append(next_line)
                j += 1
            else:
                # No applied_at found before EOF — bail by appending
                # remaining content untouched.
                i = j
            continue
        out.append(line)
        i += 1
    new_src = "\n".join(out)
    if src.endswith("\n") and not new_src.endswith("\n"):
        new_src += "\n"
    if not dry_run:
        MANIFEST_PATH.write_text(new_src, encoding="utf-8")
    return patched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without modifying the file.",
    )
    args = parser.parse_args(argv)

    plan = _build_insertion_map()
    if not plan:
        print("[backfill] no entries to patch — all manifest entries already carry a title_public.")
        return 0
    print(f"[backfill] planning to inject title_public for {len(plan)} entries:")
    for vid, title in plan.items():
        print(f"  {vid}\n    -> {title}")
    if args.dry_run:
        print("[backfill] dry-run, no file changes written.")
        return 0
    patched = _patch_source(plan, dry_run=False)
    print(f"[backfill] patched {patched} entries in {MANIFEST_PATH}")
    if patched != len(plan):
        print(
            f"[backfill] WARNING: planned={len(plan)} but patched={patched}. "
            "Some entries may not match the expected source pattern.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
