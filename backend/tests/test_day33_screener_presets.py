"""Day-33 (2026-05-20): regression guards for the screener preset
expansion from 4 → 9 presets. Day-27 audit found the 4 existing ones
are well-named but limited; users with a sector thesis had no anchor.

Each new preset must use ONLY backend-allowed fields per
SCREENER_FIELD_MAP in routers/public.py: pe_ratio, pb_ratio,
ev_ebitda, roe, roce, de_ratio, market_cap_cr (alias mcap), mos,
score, sector.

Source-text grep over .ts files.
"""
from __future__ import annotations
import re
from pathlib import Path


_F = Path(__file__).resolve().parents[2] / "frontend" / "src"
_PRESETS = _F / "lib" / "screenerFilters.ts"
_SCREENER_PAGE = _F / "app" / "(app)" / "screener" / "page.tsx"
_PUBLIC_ROUTER = Path(__file__).resolve().parents[2] / "backend" / "routers" / "public.py"


# Mirror of SCREENER_FIELD_MAP keys in routers/public.py
ALLOWED_FIELDS = {
    "pe_ratio", "pb_ratio", "ev_ebitda",
    "roe", "roce", "de_ratio",
    "market_cap_cr", "mcap",
    "mos", "score",
    "sector",
}

EXPECTED_PRESET_KEYS = {
    # Pre-Day-33 (kept)
    "cheap_quality", "high_quality", "deep_value", "smallcap_value",
    # Day-33 additions
    "psu_power_bargains", "pharma_quality", "bargain_largecaps",
    "tech_leaders", "conservative_value",
}


def test_preset_count_expanded_to_nine():
    src = _PRESETS.read_text(encoding="utf-8")
    # Count preset entries by their `key:` declarations
    keys = re.findall(r'^\s*key:\s*"([a-z_]+)"', src, re.MULTILINE)
    assert len(keys) == 9, (
        f"Expected 9 presets after Day-33 expansion, found {len(keys)}: {keys}"
    )


def test_preset_keys_match_expected_set():
    src = _PRESETS.read_text(encoding="utf-8")
    keys = set(re.findall(r'^\s*key:\s*"([a-z_]+)"', src, re.MULTILINE))
    missing = EXPECTED_PRESET_KEYS - keys
    extra = keys - EXPECTED_PRESET_KEYS
    assert not missing, f"Missing presets: {sorted(missing)}"
    assert not extra, f"Unexpected presets: {sorted(extra)}"


def test_all_preset_fields_are_backend_allowed():
    """Every field in every preset's filters must be in
    SCREENER_FIELD_MAP. If this fails the preset will produce a 400
    Bad Request from /screener/query."""
    src = _PRESETS.read_text(encoding="utf-8")
    # Extract every `field: "<name>"` occurrence inside the preset list
    fields_used = re.findall(r'field:\s*"([a-z_]+)"', src)
    bad = [f for f in fields_used if f not in ALLOWED_FIELDS]
    assert not bad, (
        f"Presets reference unknown fields: {sorted(set(bad))}. "
        f"Backend SCREENER_FIELD_MAP allows: {sorted(ALLOWED_FIELDS)}"
    )


def test_sector_presets_use_known_sector_values():
    """sector= filters should match the sector strings the backend
    actually carries. Pin a small allowlist of curated values that
    are known to be in the stocks table."""
    src = _PRESETS.read_text(encoding="utf-8")
    # Find every `field: "sector", op: ..., value: "..."` triple
    sector_pat = re.compile(
        r'\{\s*field:\s*"sector",\s*op:\s*"=",\s*value:\s*"([^"]+)"\s*\}'
    )
    sector_values = sector_pat.findall(src)
    # The audit confirmed these sector strings exist in the live stocks table
    known_sectors = {
        "Utilities", "Pharma", "Technology", "Bank", "Banking",
        "Auto", "FMCG", "Internet Platform", "Industrials",
        "Consumer Cyclical", "Basic Materials", "Energy",
        "Financial Services", "Real Estate", "Communication Services",
        "Consumer Defensive", "Metal", "Retail",
    }
    bad = [v for v in sector_values if v not in known_sectors]
    assert not bad, (
        f"Preset sector values not in known set: {bad}. Add to the known "
        f"list above OR change the preset to use a known sector."
    )


def test_screener_empty_state_uses_3col_grid_for_9_presets():
    """The grid was sm:grid-cols-2; with 9 presets 3-across on lg
    reads better than 5 rows of 2."""
    src = _SCREENER_PAGE.read_text(encoding="utf-8")
    assert "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" in src


def test_screener_field_map_unchanged():
    """Defensive: backend SCREENER_FIELD_MAP membership must include
    every field our presets use. If the backend drops one, presets break."""
    src = _PUBLIC_ROUTER.read_text(encoding="utf-8")
    # Read the SCREENER_FIELD_MAP block
    m = re.search(r"SCREENER_FIELD_MAP:\s*dict\[str,\s*str\]\s*=\s*\{(.*?)\}", src, re.DOTALL)
    assert m, "SCREENER_FIELD_MAP not found in routers/public.py"
    keys_in_backend = set(re.findall(r'"([a-z_]+)":', m.group(1)))
    fields_used = set(re.findall(r'field:\s*"([a-z_]+)"', _PRESETS.read_text(encoding="utf-8")))
    missing_backend = fields_used - keys_in_backend
    assert not missing_backend, (
        f"Presets reference fields that backend's SCREENER_FIELD_MAP "
        f"doesn't expose: {sorted(missing_backend)}. Add to backend "
        f"map first."
    )
