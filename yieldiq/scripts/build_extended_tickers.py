"""
Build data/extended_us_tickers.csv from screener_results.csv.
Combines all successfully screened tickers with the curated usa_tickers.csv.
Run from project root: python scripts/build_extended_tickers.py
"""
import pandas as pd
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --- sector mapping: screener format → usa_tickers format ---
SECTOR_MAP = {
    "US Technology":            "Technology",
    "US Industrials":           "Industrials",
    "US General":               "General",
    "US Pharma / Biotech":      "Healthcare",
    "US Energy":                "Energy",
    "US Banks & Financials":    "Financials",
    "US Telecom":               "Communication Services",
    "US Communication":         "Communication Services",
    "US Consumer Discretionary":"Consumer Discretionary",
    "US Consumer Staples":      "Consumer Staples",
    "US Materials":             "Materials",
    "US REITs":                 "Real Estate",
    "US Utilities":             "Utilities",
    "US IT Services":                        "Technology",
    "US IT Services / Enterprise Software":  "Technology",
    "US Healthcare":                         "Healthcare",
    "US Healthcare Services":                "Healthcare",
    "US Financials":                         "Financials",
    "General":                               "General",
}

def map_sector(s: str) -> str:
    if not isinstance(s, str):
        return "General"
    return SECTOR_MAP.get(s.strip(), s.strip())

# --- load curated list ---
curated_path = os.path.join(ROOT, "data", "usa_tickers.csv")
curated = pd.read_csv(curated_path)
curated["ticker"] = curated["ticker"].str.strip().str.upper()
print(f"Curated tickers : {len(curated)}")

# --- load all screener result files ---
result_files = [
    os.path.join(ROOT, "data", f)
    for f in os.listdir(os.path.join(ROOT, "data"))
    if f.startswith("screener_results") and f.endswith(".csv")
    and "extended" not in f
]
result_files.sort()
print(f"Result files    : {result_files}")

dfs = []
for fp in result_files:
    try:
        df = pd.read_csv(fp, usecols=["ticker", "sector"])
        dfs.append(df)
    except Exception as e:
        print(f"  skipping {fp}: {e}")

if not dfs:
    print("No screener result files found — nothing to build.")
    sys.exit(1)

results = pd.concat(dfs, ignore_index=True)
results["ticker"] = results["ticker"].str.strip().str.upper()
results = results.drop_duplicates(subset="ticker")
print(f"Screened tickers: {len(results)}")

# --- filter out obvious OTC junk ---
# Keep only tickers that look like real US exchange tickers:
# 1-5 uppercase letters, or CLASS-share format like BRK-B
import re
valid_pattern = re.compile(r'^[A-Z]{1,5}$|^[A-Z]{1,4}-[A-Z]$')
results = results[results["ticker"].apply(lambda t: bool(valid_pattern.match(str(t))))]
print(f"After OTC filter: {len(results)}")

# --- build extended list ---
# Start with curated (has proper names)
curated_set = set(curated["ticker"])

# New tickers from screener not in curated
new_tickers = results[~results["ticker"].isin(curated_set)].copy()
new_tickers["name"]   = new_tickers["ticker"]          # use ticker as name placeholder
new_tickers["sector"] = new_tickers["sector"].apply(map_sector)
new_tickers = new_tickers[["ticker", "name", "sector"]]

extended = pd.concat([curated, new_tickers], ignore_index=True)
extended = extended.drop_duplicates(subset="ticker")
extended = extended.sort_values("ticker").reset_index(drop=True)

# --- save ---
out_path = os.path.join(ROOT, "data", "extended_us_tickers.csv")
extended.to_csv(out_path, index=False)
print(f"\n✅ Saved {len(extended)} tickers → {out_path}")
print(f"   Curated       : {len(curated)}")
print(f"   New from scan : {len(extended) - len(curated)}")

# sector breakdown
print("\nSector breakdown:")
print(extended["sector"].value_counts().to_string())
