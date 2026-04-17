# backend/validators/ground_truth.py
# ═══════════════════════════════════════════════════════════════
# 20-stock canary ground truth.
#
# Ranges are from recent public filings (Screener / BSE / NSE).
# Update quarterly. Any live-API value outside these ranges is a
# flag — either a data bug or a real regime change worth reviewing.
#
# Conventions (match ValuationOutput / QualityOutput shape):
#   wacc           -> decimal (0.09, 0.12)
#   roe            -> percent (22.0, 28.0)
#   de_ratio       -> ratio   (0.0, 0.6)
#   market_cap_cr  -> crores  (350_000, 500_000)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations


CANARY_STOCKS: dict[str, dict[str, tuple[float, float]]] = {
    "RELIANCE": {
        "roe":           (6.5, 14.0),
        "de_ratio":      (0.20, 0.60),
        "wacc":          (0.09, 0.13),
        "market_cap_cr": (1_400_000, 2_200_000),
    },
    "TCS": {
        "roe":           (40.0, 55.0),
        "de_ratio":      (0.00, 0.10),
        "wacc":          (0.09, 0.13),
        "market_cap_cr": (900_000, 1_600_000),
    },
    "HCLTECH": {
        "roe":           (20.0, 30.0),
        "de_ratio":      (0.00, 0.20),
        "wacc":          (0.09, 0.13),
        "market_cap_cr": (300_000, 500_000),
    },
    "INFY": {
        "roe":           (25.0, 40.0),
        "de_ratio":      (0.00, 0.15),
        "wacc":          (0.09, 0.13),
        "market_cap_cr": (500_000, 800_000),
    },
    "HDFCBANK": {
        "roe":           (13.0, 20.0),
        "de_ratio":      (5.00, 10.0),   # bank leverage is high by nature
        "wacc":          (0.09, 0.14),
        "market_cap_cr": (900_000, 1_500_000),
    },
    "ITC": {
        "roe":           (22.0, 32.0),
        "de_ratio":      (0.00, 0.10),
        "wacc":          (0.09, 0.12),
        "market_cap_cr": (400_000, 650_000),
    },
    "ASIANPAINT": {
        "roe":           (20.0, 32.0),
        "de_ratio":      (0.00, 0.30),
        "wacc":          (0.09, 0.13),
        "market_cap_cr": (180_000, 350_000),
    },
    "NESTLEIND": {
        "roe":           (55.0, 95.0),
        "de_ratio":      (0.00, 0.40),
        "wacc":          (0.08, 0.12),
        "market_cap_cr": (150_000, 300_000),
    },
    "HINDUNILVR": {
        "roe":           (18.0, 35.0),
        "de_ratio":      (0.00, 0.30),
        "wacc":          (0.08, 0.12),
        "market_cap_cr": (450_000, 750_000),
    },
    "SBIN": {
        "roe":           (12.0, 20.0),
        "de_ratio":      (8.00, 15.0),   # bank
        "wacc":          (0.09, 0.14),
        "market_cap_cr": (500_000, 900_000),
    },
    "LT": {
        "roe":           (12.0, 22.0),
        "de_ratio":      (0.30, 1.20),
        "wacc":          (0.10, 0.13),
        "market_cap_cr": (350_000, 550_000),
    },
    "MARUTI": {
        "roe":           (12.0, 22.0),
        "de_ratio":      (0.00, 0.20),
        "wacc":          (0.10, 0.13),
        "market_cap_cr": (300_000, 500_000),
    },
    "SUNPHARMA": {
        "roe":           (12.0, 22.0),
        "de_ratio":      (0.00, 0.30),
        "wacc":          (0.09, 0.12),
        "market_cap_cr": (300_000, 500_000),
    },
    "BAJFINANCE": {
        "roe":           (15.0, 25.0),
        "de_ratio":      (3.00, 7.00),   # NBFC
        "wacc":          (0.10, 0.14),
        "market_cap_cr": (400_000, 700_000),
    },
    "KOTAKBANK": {
        "roe":           (11.0, 17.0),
        "de_ratio":      (4.50, 9.00),   # bank
        "wacc":          (0.09, 0.13),
        "market_cap_cr": (300_000, 500_000),
    },
    "AXISBANK": {
        "roe":           (10.0, 18.0),
        "de_ratio":      (7.00, 12.0),   # bank
        "wacc":          (0.09, 0.13),
        "market_cap_cr": (300_000, 500_000),
    },
    "WIPRO": {
        "roe":           (12.0, 22.0),
        "de_ratio":      (0.00, 0.30),
        "wacc":          (0.09, 0.13),
        "market_cap_cr": (200_000, 350_000),
    },
    "ULTRACEMCO": {
        "roe":           (10.0, 18.0),
        "de_ratio":      (0.10, 0.50),
        "wacc":          (0.10, 0.13),
        "market_cap_cr": (200_000, 400_000),
    },
    "TITAN": {
        "roe":           (20.0, 35.0),
        "de_ratio":      (0.20, 1.00),
        "wacc":          (0.10, 0.13),
        "market_cap_cr": (200_000, 400_000),
    },
    "POWERGRID": {
        "roe":           (14.0, 22.0),
        "de_ratio":      (1.50, 3.00),   # utility
        "wacc":          (0.09, 0.12),
        "market_cap_cr": (200_000, 350_000),
    },
}


def run_canary(db_values: dict) -> list[str]:
    """
    db_values: dict mapping symbol -> record dict with the CANARY fields.
                Accepted field aliases handled internally.
    Returns list of violation messages. Empty == clean.
    """
    violations: list[str] = []
    for sym, expected in CANARY_STOCKS.items():
        actual = db_values.get(sym)
        if not actual:
            # Also accept ticker with .NS suffix
            actual = db_values.get(f"{sym}.NS")
        if not actual:
            violations.append(f"{sym}: missing from provided records")
            continue
        for field, (lo, hi) in expected.items():
            v = _resolve(actual, field)
            if v is None:
                violations.append(f"{sym}.{field}: None")
                continue
            if v < lo or v > hi:
                violations.append(
                    f"{sym}.{field}={v:g} outside canary range [{lo}, {hi}]"
                )
    return violations


def _resolve(record: dict, field: str):
    """Look up a field by name with a few known aliases."""
    if field in record:
        return _num(record[field])
    aliases = {
        "de_ratio":      ("debt_to_equity",),
        "market_cap_cr": ("mcap_cr", "market_cap_crore"),
    }
    for alias in aliases.get(field, ()):
        if alias in record:
            return _num(record[alias])
    # market_cap_cr can be derived from market_cap (raw INR)
    if field == "market_cap_cr" and "market_cap" in record:
        raw = _num(record["market_cap"])
        if raw is not None:
            return raw / 1e7
    return None


def _num(v):
    if v is None:
        return None
    try:
        x = float(v)
        if x != x:
            return None
        return x
    except (TypeError, ValueError):
        return None
