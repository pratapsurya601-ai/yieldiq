"""Unit tests for data_pipeline.sources.amfi_ter.

No network — every test runs against a CAPTURED fixture mirroring the
shape of the AMFI populate-te-rdata-revised payload (rows captured live
2026-06-15, FY 2026-2027, Month 06-2026, MF_ID 64 PPFAS / 45 Mirae,
with numbers lightly trimmed for a compact fixture).

Surfaces under test:
    1. _parse_pct        — string percent "1.6400" -> 1.64, "0.0000" -> 0.0
    2. latest_per_scheme — day-granular rows collapse to max TER_Date / NSDL
    3. normalize_base_name — strips plan/option, "&"/"and", IDCW, hyphens
    4. match_ter_rows    — one TER base row fans out to MANY funds plan rows
                           and is AMC-scoped to avoid cross-AMC collisions
"""
from __future__ import annotations

import pytest

from data_pipeline.sources.amfi_ter import (
    _parse_pct,
    latest_per_scheme,
    match_ter_rows,
    normalize_amc,
    normalize_base_name,
)


# ── Captured TER-feed fixture (shape-accurate, network-free) ─────────

# One scheme (Parag Parikh Flexi Cap) appears on THREE disclosure days so
# the collapse has something to dedupe; the max-TER_Date row (06-14) must
# win. A second scheme (Mirae Large Cap) and an ETF round out the set.
TER_FIXTURE: list[dict] = [
    # Parag Parikh Flexi Cap — three days, ascending then we keep 06-14.
    {
        "NSDLSchemeCode": "PPFA/O/E/FCF/13/04/0001",
        "Scheme_Name": "Parag Parikh Flexi Cap Fund",
        "SchemeCat_Desc": "Equity Scheme - Flexi Cap Fund",
        "TER_Date": "2026-06-01T00:00:00.000Z",
        "D_TER": "0.6900", "R_TER": "1.2800",
        "MF_ID": 64, "Month": "06-2026",
    },
    {
        "NSDLSchemeCode": "PPFA/O/E/FCF/13/04/0001",
        "Scheme_Name": "Parag Parikh Flexi Cap Fund",
        "SchemeCat_Desc": "Equity Scheme - Flexi Cap Fund",
        "TER_Date": "2026-06-14T00:00:00.000Z",  # newest — must win
        "D_TER": "0.6200", "R_TER": "1.2100",
        "MF_ID": 64, "Month": "06-2026",
    },
    {
        "NSDLSchemeCode": "PPFA/O/E/FCF/13/04/0001",
        "Scheme_Name": "Parag Parikh Flexi Cap Fund",
        "SchemeCat_Desc": "Equity Scheme - Flexi Cap Fund",
        "TER_Date": "2026-06-07T00:00:00.000Z",
        "D_TER": "0.6200", "R_TER": "1.2100",
        "MF_ID": 64, "Month": "06-2026",
    },
    # Mirae Large Cap — single day, zero-TER edge ("0.0000" must parse 0.0
    # is exercised in the parse test; here a normal pair).
    {
        "NSDLSchemeCode": "MIRA/O/E/LCF/08/02/0001",
        "Scheme_Name": "Mirae Asset Large Cap Fund",
        "SchemeCat_Desc": "Equity Scheme - Large Cap Fund",
        "TER_Date": "2026-06-14T00:00:00.000Z",
        "D_TER": "0.5700", "R_TER": "1.5400",
        "MF_ID": 45, "Month": "06-2026",
    },
    # An ETF — the kind of row that typically has NO matching funds plan
    # rows (no Direct/Regular split), i.e. an expected reconciliation miss.
    {
        "NSDLSchemeCode": "MIRA/O/O/EET/24/12/0078",
        "Scheme_Name": "Mirae Asset BSE 200 Equal Weight ETF",
        "SchemeCat_Desc": "Other Scheme - Other ETFs",
        "TER_Date": "2026-06-14T00:00:00.000Z",
        "D_TER": "0.1500", "R_TER": "0.1500",
        "MF_ID": 45, "Month": "06-2026",
    },
]

# Minimal funds-table fixture: PPFAS Flexi Cap exists as FOUR per-plan
# rows (Direct/Regular × Growth/IDCW); Mirae Large Cap as two. A
# DIFFERENT-AMC "Large Cap Fund" is included to prove AMC-scoping stops a
# cross-AMC base-name collision. The ETF has no funds rows (it never gets
# the plan/option fan-out), so it stays unmatched.
FUNDS_FIXTURE: list[dict] = [
    {"scheme_code": "PP01", "amc": "Parag Parikh Mutual Fund",
     "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"},
    {"scheme_code": "PP02", "amc": "Parag Parikh Mutual Fund",
     "scheme_name": "Parag Parikh Flexi Cap Fund - Regular Plan - Growth"},
    {"scheme_code": "PP03", "amc": "Parag Parikh Mutual Fund",
     "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan (IDCW)"},
    {"scheme_code": "PP04", "amc": "Parag Parikh Mutual Fund",
     "scheme_name": "Parag Parikh Flexi Cap Fund - Regular Plan - IDCW Reinvestment"},
    {"scheme_code": "MI01", "amc": "Mirae Asset Mutual Fund",
     "scheme_name": "Mirae Asset Large Cap Fund - Direct Plan - Growth"},
    {"scheme_code": "MI02", "amc": "Mirae Asset Mutual Fund",
     "scheme_name": "Mirae Asset Large Cap Fund Regular Growth"},
    # SAME base name, DIFFERENT AMC — must NOT receive Mirae's TER.
    {"scheme_code": "XX01", "amc": "Some Other Mutual Fund",
     "scheme_name": "Mirae Asset Large Cap Fund - Direct Plan - Growth"},
]

# MF_ID -> AMC label, as the committed map provides it.
MF_ID_AMC = {
    "64": "Parag Parikh Mutual Fund",
    "45": "Mirae Asset Mutual Fund",
}


# ── _parse_pct ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.6400", 1.64),   # stays in PERCENT, no /100
        ("2.4400", 2.44),
        ("0.6200", 0.62),
        ("0.0000", 0.0),    # legitimate zero TER
        ("", None),
        ("N.A.", None),
        (None, None),
        ("-1.0", None),     # negative is never a legitimate TER
    ],
)
def test_parse_pct(raw, expected) -> None:
    got = _parse_pct(raw)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_parse_pct_stays_in_percent_not_fraction() -> None:
    # Guards the UNITS DECISION: a "1.6400" must surface as 1.64 (renders
    # "1.64%" via the frontend fmtPct), NOT 0.0164.
    assert _parse_pct("1.6400") == pytest.approx(1.64)


# ── latest_per_scheme collapse ───────────────────────────────────────


def test_latest_per_scheme_keeps_max_ter_date() -> None:
    out = latest_per_scheme(TER_FIXTURE)
    # 5 fixture rows over 3 distinct NSDL codes -> 3 collapsed rows.
    by_code = {r["NSDLSchemeCode"]: r for r in out}
    assert len(out) == 3
    flexi = by_code["PPFA/O/E/FCF/13/04/0001"]
    # The 06-14 row (D_TER 0.62) must win over 06-01 (0.69) and 06-07.
    assert flexi["TER_Date"].startswith("2026-06-14")
    assert flexi["D_TER"] == "0.6200"
    assert flexi["R_TER"] == "1.2100"


def test_latest_per_scheme_drops_unusable_rows() -> None:
    rows = [
        {"NSDLSchemeCode": "", "Scheme_Name": "x", "TER_Date": "2026-06-14T00:00:00Z"},
        {"NSDLSchemeCode": "A/1", "Scheme_Name": "y", "TER_Date": ""},
        {"NSDLSchemeCode": "A/2", "Scheme_Name": "z",
         "TER_Date": "2026-06-10T00:00:00.000Z", "D_TER": "1.0", "R_TER": "2.0"},
    ]
    out = latest_per_scheme(rows)
    # Blank code and unparseable date are dropped; only A/2 survives.
    assert [r["NSDLSchemeCode"] for r in out] == ["A/2"]


# ── normalize_base_name / normalize_amc ──────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Parag Parikh Flexi Cap Fund", "parag parikh flexi cap fund"),
        ("Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
         "parag parikh flexi cap fund"),
        ("Parag Parikh Flexi Cap Fund - Regular Plan (IDCW)",
         "parag parikh flexi cap fund"),
        ("Mirae Asset Large Cap Fund Regular Growth",
         "mirae asset large cap fund"),
        ("SBI Magnum Multicap Fund - Direct - IDCW Reinvestment",
         "sbi magnum multicap fund"),
        # Intra-word hyphen preserved; separator hyphens dropped.
        ("HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth",
         "hdfc mid-cap opportunities fund"),
        # "&" and "and" collapse to the same key.
        ("ICICI Prudential Bluechip Fund & Co - Direct Plan - IDCW",
         "icici prudential bluechip fund and co"),
        ("ICICI Prudential Bluechip Fund and Co",
         "icici prudential bluechip fund and co"),
        ("", ""),
    ],
)
def test_normalize_base_name(name, expected) -> None:
    assert normalize_base_name(name) == expected


def test_normalize_base_name_and_vs_ampersand_equal() -> None:
    assert (
        normalize_base_name("Foo & Bar Fund - Direct - Growth")
        == normalize_base_name("Foo and Bar Fund - Regular - Growth")
    )


def test_normalize_amc_strips_house_suffix_and_ampersand() -> None:
    assert normalize_amc("Mirae Asset Mutual Fund") == "mirae asset"
    assert normalize_amc("Mirae Asset Mutual Fund Ltd") == "mirae asset"
    assert (
        normalize_amc("ICICI Prudential AMC")
        == normalize_amc("ICICI Prudential Mutual Fund")
    )


# ── match_ter_rows one-to-many fan-out + AMC scoping ─────────────────


def test_match_fans_out_to_all_plans_of_a_scheme() -> None:
    collapsed = latest_per_scheme(TER_FIXTURE)
    params, recon = match_ter_rows(collapsed, FUNDS_FIXTURE, MF_ID_AMC)

    by_code = {p["scheme_code"]: p for p in params}
    # PPFAS Flexi Cap base -> all 4 plan rows, EACH carrying BOTH TERs.
    for sc in ("PP01", "PP02", "PP03", "PP04"):
        assert sc in by_code
        assert by_code[sc]["ter_direct"] == pytest.approx(0.62)
        assert by_code[sc]["ter_regular"] == pytest.approx(1.21)
    # Mirae Large Cap base -> its 2 in-AMC plan rows.
    assert by_code["MI01"]["ter_direct"] == pytest.approx(0.57)
    assert by_code["MI02"]["ter_regular"] == pytest.approx(1.54)


def test_match_amc_scoping_blocks_cross_amc_collision() -> None:
    collapsed = latest_per_scheme(TER_FIXTURE)
    params, recon = match_ter_rows(collapsed, FUNDS_FIXTURE, MF_ID_AMC)
    by_code = {p["scheme_code"] for p in params}
    # XX01 has the SAME base name as the Mirae fund but a different AMC,
    # so Mirae's TER must NOT bleed onto it.
    assert "XX01" not in by_code


def test_match_etf_is_unmatched_and_reported() -> None:
    collapsed = latest_per_scheme(TER_FIXTURE)
    params, recon = match_ter_rows(collapsed, FUNDS_FIXTURE, MF_ID_AMC)
    # 3 collapsed TER rows: Flexi Cap (matched), Large Cap (matched), ETF
    # (no funds plan rows -> unmatched).
    assert recon.ter_rows_total == 3
    assert recon.ter_rows_matched == 2
    assert recon.ter_rows_unmatched == 1
    # 4 PPFAS plan rows + 2 Mirae plan rows = 6 upsert params.
    assert recon.funds_rows_updated == 6
    assert len(params) == 6
    # The ETF base name appears in the unmatched sample list.
    assert any("ETF" in s for s in recon.unmatched_samples)


def test_match_unmatched_when_mf_id_missing_from_amc_map() -> None:
    # A TER row whose MF_ID is absent from the AMC map has empty AMC scope
    # and therefore matches nothing (fails safe, not cross-AMC).
    collapsed = latest_per_scheme(TER_FIXTURE)
    params, recon = match_ter_rows(collapsed, FUNDS_FIXTURE, {})  # empty map
    assert recon.ter_rows_matched == 0
    assert recon.funds_rows_updated == 0
