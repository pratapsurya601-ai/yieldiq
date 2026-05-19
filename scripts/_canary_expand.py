"""Day-15: Expand canary_universe_180.json from 189 to ~339 tickers
toward NIFTY 500 coverage. Idempotent — re-running does not duplicate.

Inputs are hardcoded below from the parallel-agent research run.
Format matches the existing JSON conventions:
  - `buckets[bucket]` = list of bare-NSE ticker strings
  - `stocks[]` = list of {symbol, sector, bucket, mcap_tier, canary_bounds}
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent / "canary_universe_180.json"

NEW_TICKERS: list[dict] = [
    # ── top100_diversified (56) ──
    {"symbol":"ETERNAL","sector":"Consumer Cyclical","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":None,"debt_to_equity":[0,0.5],"wacc":[0.11,0.15],"market_cap_cr":[110000,330000],"revenue_cagr_3y":[0.15,0.60]}},
    {"symbol":"BSE","sector":"Capital Markets","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.20,0.40],"debt_to_equity":[0,0.1],"wacc":[0.10,0.14],"market_cap_cr":[80000,240000],"revenue_cagr_3y":[0.20,0.60]}},
    {"symbol":"ICICIAMC","sector":"Asset Management","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.30,0.80],"debt_to_equity":[0,0.2],"wacc":[0.10,0.13],"market_cap_cr":[80000,240000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"SOLARINDS","sector":"Specialty Chemicals","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.20,0.35],"debt_to_equity":[0.1,0.5],"wacc":[0.11,0.14],"market_cap_cr":[80000,240000],"revenue_cagr_3y":[0.20,0.50]}},
    {"symbol":"JIOFIN","sector":"NBFC","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":None,"debt_to_equity":[0,1.5],"wacc":[0.10,0.13],"market_cap_cr":[75000,230000],"revenue_cagr_3y":None}},
    {"symbol":"PFC","sector":"NBFC - Power","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.22],"debt_to_equity":[6,10],"wacc":[0.08,0.11],"market_cap_cr":[75000,220000],"revenue_cagr_3y":[0.08,0.20]}},
    {"symbol":"POWERINDIA","sector":"Capital Goods","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.18],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[70000,220000],"revenue_cagr_3y":[0.15,0.45]}},
    {"symbol":"TATACAP","sector":"NBFC","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.16],"debt_to_equity":[4,7],"wacc":[0.10,0.13],"market_cap_cr":[65000,195000],"revenue_cagr_3y":[0.15,0.30]}},
    {"symbol":"IRFC","sector":"NBFC - Infra","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.16],"debt_to_equity":[7,10],"wacc":[0.07,0.10],"market_cap_cr":[65000,195000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"INDUSTOWER","sector":"Telecom Services","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.25],"debt_to_equity":[0.3,1.0],"wacc":[0.10,0.13],"market_cap_cr":[55000,170000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"GVT&D","sector":"Capital Goods","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.35],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[55000,170000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"HDFCAMC","sector":"Asset Management","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.25,0.40],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[55000,175000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"UNITDSPR","sector":"FMCG - Alcohol","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.30],"debt_to_equity":[0,0.2],"wacc":[0.10,0.13],"market_cap_cr":[48000,145000],"revenue_cagr_3y":[0.05,0.15]}},
    {"symbol":"INDHOTEL","sector":"Hotels","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.22],"debt_to_equity":[0.1,0.5],"wacc":[0.10,0.13],"market_cap_cr":[45000,140000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"RECLTD","sector":"NBFC - Power","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.22],"debt_to_equity":[5,8],"wacc":[0.08,0.11],"market_cap_cr":[45000,140000],"revenue_cagr_3y":[0.08,0.20]}},
    {"symbol":"MCX","sector":"Capital Markets","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.40],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[42000,130000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"BHARTIHEXA","sector":"Telecom Services","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.30],"debt_to_equity":[0.5,1.5],"wacc":[0.10,0.13],"market_cap_cr":[38000,120000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"LTF","sector":"NBFC","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.15],"debt_to_equity":[3.5,5],"wacc":[0.10,0.13],"market_cap_cr":[35000,105000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"NAM-INDIA","sector":"Asset Management","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.25,0.40],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[35000,105000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"BAJAJHFL","sector":"Mortgage Finance","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.18],"debt_to_equity":[3.5,6],"wacc":[0.09,0.12],"market_cap_cr":[35000,105000],"revenue_cagr_3y":[0.15,0.35]}},
    {"symbol":"GICRE","sector":"Insurance","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.18],"debt_to_equity":None,"wacc":[0.09,0.12],"market_cap_cr":[34000,105000],"revenue_cagr_3y":None}},
    {"symbol":"SBICARD","sector":"NBFC - Cards","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.22],"debt_to_equity":[2.5,4],"wacc":[0.10,0.13],"market_cap_cr":[30000,90000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"HDBFS","sector":"NBFC","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.18],"debt_to_equity":[3.5,6],"wacc":[0.10,0.13],"market_cap_cr":[28000,85000],"revenue_cagr_3y":[0.15,0.30]}},
    {"symbol":"MFSL","sector":"Insurance Holding","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.05,0.15],"debt_to_equity":[0.1,0.5],"wacc":[0.10,0.13],"market_cap_cr":[27000,85000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"SUNDARMFIN","sector":"NBFC","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.18],"debt_to_equity":[3,5],"wacc":[0.09,0.12],"market_cap_cr":[25000,75000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"MOTILALOFS","sector":"Capital Markets","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.30],"debt_to_equity":[0.5,2],"wacc":[0.11,0.14],"market_cap_cr":[25000,75000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"PATANJALI","sector":"FMCG","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.18],"debt_to_equity":[0,0.3],"wacc":[0.10,0.13],"market_cap_cr":[25000,75000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"M&MFIN","sector":"NBFC","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.16],"debt_to_equity":[3.5,5.5],"wacc":[0.10,0.13],"market_cap_cr":[22000,67000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"360ONE","sector":"Asset Management","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.25],"debt_to_equity":[0.5,2.5],"wacc":[0.11,0.14],"market_cap_cr":[22000,67000],"revenue_cagr_3y":[0.15,0.35]}},
    {"symbol":"RADICO","sector":"FMCG - Alcohol","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.22],"debt_to_equity":[0.1,0.4],"wacc":[0.10,0.13],"market_cap_cr":[23000,70000],"revenue_cagr_3y":[0.10,0.20]}},
    {"symbol":"PIRAMALFIN","sector":"NBFC","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.04,0.12],"debt_to_equity":[2,4],"wacc":[0.10,0.13],"market_cap_cr":[21000,64000],"revenue_cagr_3y":None}},
    {"symbol":"HUDCO","sector":"NBFC - Housing","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.18],"debt_to_equity":[5,8],"wacc":[0.08,0.11],"market_cap_cr":[21000,62000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"AIIL","sector":"Capital Markets","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.40],"debt_to_equity":[0,0.5],"wacc":[0.11,0.14],"market_cap_cr":[21000,65000],"revenue_cagr_3y":None}},
    {"symbol":"GODFRYPHLP","sector":"FMCG - Tobacco","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.28],"debt_to_equity":[0,0.2],"wacc":[0.10,0.13],"market_cap_cr":[19000,57000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"GODREJIND","sector":"Conglomerate","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.06,0.15],"debt_to_equity":[2,5],"wacc":[0.10,0.13],"market_cap_cr":[19000,57000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"UBL","sector":"FMCG - Alcohol","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.18],"debt_to_equity":[0.1,0.5],"wacc":[0.10,0.13],"market_cap_cr":[18000,55000],"revenue_cagr_3y":[0.05,0.15]}},
    {"symbol":"POONAWALLA","sector":"NBFC","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.04,0.15],"debt_to_equity":[3,6],"wacc":[0.10,0.13],"market_cap_cr":[18000,55000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"IREDA","sector":"NBFC - Renewables","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.20],"debt_to_equity":[5,8],"wacc":[0.08,0.11],"market_cap_cr":[18000,55000],"revenue_cagr_3y":[0.15,0.35]}},
    {"symbol":"TATAINVEST","sector":"Holding Co","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.01,0.08],"debt_to_equity":[0,0.1],"wacc":[0.09,0.12],"market_cap_cr":[17000,52000],"revenue_cagr_3y":None}},
    {"symbol":"LICHSGFIN","sector":"Mortgage Finance","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.18],"debt_to_equity":[6,9],"wacc":[0.08,0.11],"market_cap_cr":[15000,46000],"revenue_cagr_3y":[0.05,0.15]}},
    {"symbol":"ABSLAMC","sector":"Asset Management","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.20,0.32],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[15000,45000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"ANANDRATHI","sector":"Capital Markets","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.30,0.50],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[15000,45000],"revenue_cagr_3y":[0.20,0.40]}},
    {"symbol":"STARHEALTH","sector":"Insurance","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.05,0.18],"debt_to_equity":None,"wacc":[0.10,0.13],"market_cap_cr":[15000,45000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"HEXT","sector":"IT Services","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.18,0.30],"debt_to_equity":[0,0.2],"wacc":[0.10,0.13],"market_cap_cr":[15000,45000],"revenue_cagr_3y":[0.10,0.20]}},
    {"symbol":"GODIGIT","sector":"Insurance","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.05,0.18],"debt_to_equity":None,"wacc":[0.10,0.13],"market_cap_cr":[14000,43000],"revenue_cagr_3y":[0.20,0.45]}},
    {"symbol":"ANGELONE","sector":"Capital Markets","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.40],"debt_to_equity":[0.5,2],"wacc":[0.11,0.14],"market_cap_cr":[14000,42000],"revenue_cagr_3y":[0.20,0.50]}},
    {"symbol":"PNBHOUSING","sector":"Mortgage Finance","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.15],"debt_to_equity":[2.5,4.5],"wacc":[0.09,0.12],"market_cap_cr":[14000,42000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"NIACL","sector":"Insurance","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.02,0.10],"debt_to_equity":None,"wacc":[0.09,0.12],"market_cap_cr":[13000,41000],"revenue_cagr_3y":None}},
    {"symbol":"NUVAMA","sector":"Asset Management","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.20,0.35],"debt_to_equity":[1,3],"wacc":[0.11,0.14],"market_cap_cr":[13000,40000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"AWL","sector":"FMCG - Foods","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.06,0.15],"debt_to_equity":[0.3,1.0],"wacc":[0.10,0.13],"market_cap_cr":[13000,39000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"CRISIL","sector":"Financial Data","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.22,0.35],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[15000,45000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"CDSL","sector":"Capital Markets","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.20,0.32],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[12000,37000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"CAMS","sector":"IT Services","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.30,0.45],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[10000,29000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"SUNTV","sector":"Media","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[10000,32000],"revenue_cagr_3y":[-0.05,0.10]}},
    {"symbol":"CREDITACC","sector":"NBFC - MFI","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.05,0.20],"debt_to_equity":[2.5,4.5],"wacc":[0.10,0.13],"market_cap_cr":[10000,32000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"IIFL","sector":"NBFC","bucket":"top100_diversified","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.18],"debt_to_equity":[4,6],"wacc":[0.10,0.13],"market_cap_cr":[9000,30000],"revenue_cagr_3y":[0.05,0.25]}},

    # ── banks (7) ──
    {"symbol":"INDIANB","sector":"PSU Bank","bucket":"banks","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.20],"debt_to_equity":[0.3,0.9],"wacc":[0.10,0.14],"market_cap_cr":[55000,165000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"YESBANK","sector":"Private Bank","bucket":"banks","mcap_tier":"large","canary_bounds":{"roe":[0.03,0.12],"debt_to_equity":[1.0,1.5],"wacc":[0.11,0.15],"market_cap_cr":[34000,105000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"MAHABANK","sector":"PSU Bank","bucket":"banks","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.25],"debt_to_equity":[0.8,1.3],"wacc":[0.10,0.14],"market_cap_cr":[30000,90000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"UCOBANK","sector":"PSU Bank","bucket":"banks","mcap_tier":"large","canary_bounds":{"roe":[0.06,0.14],"debt_to_equity":[0.5,1.0],"wacc":[0.10,0.14],"market_cap_cr":[15000,47000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"KARURVYSYA","sector":"Private Bank","bucket":"banks","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.20],"debt_to_equity":[0.1,0.3],"wacc":[0.11,0.14],"market_cap_cr":[14000,44000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"PSB","sector":"PSU Bank","bucket":"banks","mcap_tier":"mid","canary_bounds":{"roe":[0.05,0.14],"debt_to_equity":[0.8,1.3],"wacc":[0.10,0.14],"market_cap_cr":[8000,26000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"CHOLAHLDNG","sector":"Bank Holding","bucket":"banks","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.22],"debt_to_equity":[10,18],"wacc":[0.10,0.14],"market_cap_cr":[15000,47000],"revenue_cagr_3y":[0.15,0.35]}},

    # ── psu_utilities (30) ──
    {"symbol":"ADANIENSOL","sector":"Power Transmission","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.07,0.15],"debt_to_equity":[1.5,2.5],"wacc":[0.09,0.12],"market_cap_cr":[78000,235000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"TATAPOWER","sector":"Power Utility","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.15],"debt_to_equity":[1.3,2.3],"wacc":[0.09,0.12],"market_cap_cr":[65000,195000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"CGPOWER","sector":"Capital Goods","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.25],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[66000,200000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"ENRIN","sector":"Capital Goods","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.30],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[55000,165000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"HINDPETRO","sector":"Oil Marketing","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.20],"debt_to_equity":[1.0,2.0],"wacc":[0.10,0.13],"market_cap_cr":[39000,117000],"revenue_cagr_3y":None}},
    {"symbol":"NHPC","sector":"Power Utility","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.06,0.12],"debt_to_equity":[0.8,1.4],"wacc":[0.08,0.11],"market_cap_cr":[38000,115000],"revenue_cagr_3y":[0.00,0.10]}},
    {"symbol":"TORNTPOWER","sector":"Power Utility","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.20],"debt_to_equity":[0.3,0.8],"wacc":[0.09,0.12],"market_cap_cr":[37000,110000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"SUZLON","sector":"Renewables","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.40],"debt_to_equity":[0.05,0.3],"wacc":[0.12,0.15],"market_cap_cr":[37000,110000],"revenue_cagr_3y":[0.20,0.60]}},
    {"symbol":"NTPCGREEN","sector":"Renewables","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.01,0.10],"debt_to_equity":[0.8,1.5],"wacc":[0.08,0.11],"market_cap_cr":[45000,135000],"revenue_cagr_3y":[0.20,0.80]}},
    {"symbol":"JSWENERGY","sector":"Power Utility","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.05,0.13],"debt_to_equity":[1.3,2.3],"wacc":[0.09,0.12],"market_cap_cr":[45000,135000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"ATGL","sector":"City Gas","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0.3,0.8],"wacc":[0.10,0.13],"market_cap_cr":[33000,100000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"NATIONALUM","sector":"Metals (PSU)","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.35],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[37000,110000],"revenue_cagr_3y":None}},
    {"symbol":"BDL","sector":"Defence","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[24000,73000],"revenue_cagr_3y":[0.10,0.40]}},
    {"symbol":"THERMAX","sector":"Capital Goods","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.18],"debt_to_equity":[0.2,0.6],"wacc":[0.11,0.14],"market_cap_cr":[25000,76000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"NLCINDIA","sector":"Power Utility","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.18],"debt_to_equity":[0.9,1.5],"wacc":[0.08,0.11],"market_cap_cr":[24000,73000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"HINDCOPPER","sector":"Metals (PSU)","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.25],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[27000,83000],"revenue_cagr_3y":None}},
    {"symbol":"PETRONET","sector":"Gas Utility","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.25],"debt_to_equity":[0,0.3],"wacc":[0.10,0.13],"market_cap_cr":[20000,60000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"SJVN","sector":"Power Utility","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.04,0.12],"debt_to_equity":[1.3,2.3],"wacc":[0.08,0.11],"market_cap_cr":[15000,45000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"GUJGASLTD","sector":"City Gas","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.22],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[12000,38000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"IGL","sector":"City Gas","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.25],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[10000,32000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"NBCC","sector":"Construction (PSU)","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.30],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[12000,38000],"revenue_cagr_3y":[0.05,0.25]}},
    {"symbol":"MRPL","sector":"Oil Refining (PSU)","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.22],"debt_to_equity":[0.8,1.5],"wacc":[0.10,0.13],"market_cap_cr":[13000,40000],"revenue_cagr_3y":None}},
    {"symbol":"CESC","sector":"Power Utility","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.16],"debt_to_equity":[1.2,2.2],"wacc":[0.09,0.12],"market_cap_cr":[12000,36000],"revenue_cagr_3y":[0.05,0.15]}},
    {"symbol":"AEGISLOG","sector":"Oil & Gas Logistics","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0.5,1.3],"wacc":[0.10,0.13],"market_cap_cr":[12000,36000],"revenue_cagr_3y":[0.05,0.25]}},
    {"symbol":"IRB","sector":"Infra - Roads","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.25],"debt_to_equity":[0.7,1.5],"wacc":[0.10,0.13],"market_cap_cr":[12000,37000],"revenue_cagr_3y":[0.05,0.25]}},
    {"symbol":"FACT","sector":"Fertilizer (PSU)","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":None,"debt_to_equity":[0.8,1.8],"wacc":[0.11,0.14],"market_cap_cr":[28000,86000],"revenue_cagr_3y":None}},
    {"symbol":"GMDCLTD","sector":"Mining (PSU)","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.18],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[10000,32000],"revenue_cagr_3y":None}},
    {"symbol":"CASTROLIND","sector":"Oil Marketing","bucket":"psu_utilities","mcap_tier":"large","canary_bounds":{"roe":[0.40,0.65],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[9000,27000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"KIRLOSENG","sector":"Capital Goods","bucket":"psu_utilities","mcap_tier":"mid","canary_bounds":{"roe":[0.12,0.22],"debt_to_equity":[0.5,2.3],"wacc":[0.11,0.14],"market_cap_cr":[12000,38000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"KPIL","sector":"Construction","bucket":"psu_utilities","mcap_tier":"mid","canary_bounds":{"roe":[0.06,0.15],"debt_to_equity":[0.4,1.0],"wacc":[0.11,0.14],"market_cap_cr":[10000,32000],"revenue_cagr_3y":[0.10,0.30]}},

    # ── cyclicals (36) ──
    {"symbol":"HINDZINC","sector":"Metals","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.30,0.80],"debt_to_equity":[0.2,0.7],"wacc":[0.11,0.14],"market_cap_cr":[135000,400000],"revenue_cagr_3y":None}},
    {"symbol":"HYUNDAI","sector":"Auto","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.25,0.45],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[74000,220000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"POLYCAB","sector":"Cap Goods - Cables","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.18,0.28],"debt_to_equity":[0.1,0.5],"wacc":[0.11,0.14],"market_cap_cr":[69000,205000],"revenue_cagr_3y":[0.15,0.30]}},
    {"symbol":"LLOYDSME","sector":"Metals","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.40],"debt_to_equity":[1.0,2.0],"wacc":[0.12,0.15],"market_cap_cr":[48000,145000],"revenue_cagr_3y":[0.20,0.60]}},
    {"symbol":"LODHA","sector":"Realty","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0.3,0.8],"wacc":[0.11,0.14],"market_cap_cr":[42000,128000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"SRF","sector":"Chemicals","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0.3,0.6],"wacc":[0.11,0.14],"market_cap_cr":[40000,120000],"revenue_cagr_3y":[0.05,0.25]}},
    {"symbol":"UNOMINDA","sector":"Auto Parts","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.22],"debt_to_equity":[0.3,0.7],"wacc":[0.11,0.14],"market_cap_cr":[32000,97000],"revenue_cagr_3y":[0.15,0.35]}},
    {"symbol":"SCHAEFFLER","sector":"Auto Parts","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.25],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[31000,95000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"LINDEINDIA","sector":"Industrial Gases","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.18],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[31000,95000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"COROMANDEL","sector":"Fertilizer","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.22],"debt_to_equity":[0.3,0.8],"wacc":[0.11,0.14],"market_cap_cr":[27000,82000],"revenue_cagr_3y":None}},
    {"symbol":"APARINDS","sector":"Cap Goods - Cables","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.28],"debt_to_equity":[0.05,0.3],"wacc":[0.11,0.14],"market_cap_cr":[25000,76000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"TIINDIA","sector":"Auto - Tubes","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0.3,0.8],"wacc":[0.11,0.14],"market_cap_cr":[27000,83000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"PIIND","sector":"Agrochem","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.22],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[23000,71000],"revenue_cagr_3y":[0.05,0.25]}},
    {"symbol":"SUPREMEIND","sector":"Building Materials","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.25],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[22000,67000],"revenue_cagr_3y":[0.05,0.25]}},
    {"symbol":"KEI","sector":"Cap Goods - Cables","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.22],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[24000,74000],"revenue_cagr_3y":[0.15,0.35]}},
    {"symbol":"ASTRAL","sector":"Building Materials","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.22],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[20000,63000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"KALYANKJIL","sector":"Retail - Jewellery","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.22],"debt_to_equity":[0.6,1.5],"wacc":[0.11,0.14],"market_cap_cr":[18000,55000],"revenue_cagr_3y":[0.15,0.45]}},
    {"symbol":"AIAENG","sector":"Cap Goods","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.22],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[18000,54000],"revenue_cagr_3y":[0.00,0.20]}},
    {"symbol":"NAVINFLUOR","sector":"Specialty Chem","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.25],"debt_to_equity":[0.2,0.6],"wacc":[0.11,0.14],"market_cap_cr":[18000,54000],"revenue_cagr_3y":[0.05,0.30]}},
    {"symbol":"ENDURANCE","sector":"Auto Parts","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.20],"debt_to_equity":[0.1,0.4],"wacc":[0.11,0.14],"market_cap_cr":[18000,54000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"SONACOMS","sector":"Auto Parts","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.22],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[18000,54000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"3MINDIA","sector":"Diversified","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.20,0.35],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[18000,53000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"WELCORP","sector":"Steel Pipes","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.35],"debt_to_equity":[0,0.3],"wacc":[0.12,0.15],"market_cap_cr":[17000,52000],"revenue_cagr_3y":None}},
    {"symbol":"EXIDEIND","sector":"Auto Parts","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.05,0.13],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[15000,45000],"revenue_cagr_3y":[0.00,0.15]}},
    {"symbol":"JSWINFRA","sector":"Ports","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.20],"debt_to_equity":[0.3,0.8],"wacc":[0.10,0.13],"market_cap_cr":[28000,84000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"METROBRAND","sector":"Retail - Footwear","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.28],"debt_to_equity":[0.5,1.0],"wacc":[0.11,0.14],"market_cap_cr":[14000,42000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"TVSHLTD","sector":"Auto Holding","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.18,0.30],"debt_to_equity":[5,9],"wacc":[0.11,0.14],"market_cap_cr":[14000,42000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"ZFCVINDIA","sector":"Auto Parts","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.20],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[14000,42000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"FORCEMOT","sector":"Auto","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.18,0.35],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[13000,40000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"MSUMI","sector":"Auto Parts","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.22,0.38],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[13000,40000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"TIMKEN","sector":"Bearings","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.22],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[13000,40000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"GESHIP","sector":"Shipping","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.12,0.25],"debt_to_equity":[0.1,0.5],"wacc":[0.11,0.14],"market_cap_cr":[11000,33000],"revenue_cagr_3y":None}},
    {"symbol":"HONAUT","sector":"Automation","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0,0.1],"wacc":[0.11,0.14],"market_cap_cr":[13000,40000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"ANANTRAJ","sector":"Realty","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.18],"debt_to_equity":[0,0.3],"wacc":[0.11,0.14],"market_cap_cr":[9000,27000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"BRIGADE","sector":"Realty","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.18],"debt_to_equity":[0.5,1.3],"wacc":[0.11,0.14],"market_cap_cr":[8000,26000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"KAJARIACER","sector":"Ceramics","bucket":"cyclicals","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[8000,26000],"revenue_cagr_3y":[0.05,0.20]}},

    # ── pharma (21) ──
    {"symbol":"FORTIS","sector":"Hospitals","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.07,0.15],"debt_to_equity":[0.1,0.5],"wacc":[0.10,0.13],"market_cap_cr":[36000,110000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"ANTHEM","sector":"Biotechnology","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.25],"debt_to_equity":[0,0.2],"wacc":[0.11,0.14],"market_cap_cr":[22000,66000],"revenue_cagr_3y":[0.15,0.30]}},
    {"symbol":"AJANTPHARM","sector":"Pharma","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.18,0.28],"debt_to_equity":[0,0.2],"wacc":[0.10,0.13],"market_cap_cr":[20000,60000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"ASTERDM","sector":"Hospitals","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.30],"debt_to_equity":[0.3,0.9],"wacc":[0.10,0.13],"market_cap_cr":[19000,58000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"NH","sector":"Hospitals","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.28],"debt_to_equity":[0.3,1.0],"wacc":[0.10,0.13],"market_cap_cr":[19000,56000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"JBCHEPHARM","sector":"Pharma","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.25],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[17000,52000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"MEDANTA","sector":"Hospitals","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0.1,0.4],"wacc":[0.10,0.13],"market_cap_cr":[17000,50000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"EMCURE","sector":"Pharma","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.25],"debt_to_equity":[0.2,0.6],"wacc":[0.10,0.13],"market_cap_cr":[16000,49000],"revenue_cagr_3y":[0.10,0.25]}},
    {"symbol":"GLAND","sector":"Pharma","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.05,0.15],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[15000,46000],"revenue_cagr_3y":[-0.05,0.15]}},
    {"symbol":"KIMS","sector":"Hospitals","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.25],"debt_to_equity":[0.5,1.5],"wacc":[0.10,0.13],"market_cap_cr":[15000,46000],"revenue_cagr_3y":[0.15,0.30]}},
    {"symbol":"LALPATHLAB","sector":"Diagnostics","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.18,0.28],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[13000,40000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"IKS","sector":"Healthcare IT","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.20,0.35],"debt_to_equity":[0.2,0.7],"wacc":[0.10,0.13],"market_cap_cr":[13000,40000],"revenue_cagr_3y":[0.15,0.40]}},
    {"symbol":"WOCKPHARMA","sector":"Pharma","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":None,"debt_to_equity":[0.3,0.8],"wacc":[0.11,0.14],"market_cap_cr":[12000,38000],"revenue_cagr_3y":[0.00,0.20]}},
    {"symbol":"NATCOPHARM","sector":"Pharma","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.15,0.32],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[10000,32000],"revenue_cagr_3y":None}},
    {"symbol":"NEULANDLAB","sector":"Pharma","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.13,0.25],"debt_to_equity":[0.05,0.2],"wacc":[0.11,0.14],"market_cap_cr":[10000,32000],"revenue_cagr_3y":[0.10,0.30]}},
    {"symbol":"ASTRAZEN","sector":"Pharma","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.22],"debt_to_equity":[0,0.1],"wacc":[0.10,0.13],"market_cap_cr":[10000,32000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"SAILIFE","sector":"CRO","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.05,0.15],"debt_to_equity":[0.1,0.4],"wacc":[0.10,0.13],"market_cap_cr":[11000,35000],"revenue_cagr_3y":[0.15,0.30]}},
    {"symbol":"SAGILITY","sector":"Healthcare BPM","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.05,0.15],"debt_to_equity":[0.1,0.4],"wacc":[0.10,0.13],"market_cap_cr":[10000,30000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"SYNGENE","sector":"CRO","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.18],"debt_to_equity":[0.05,0.3],"wacc":[0.10,0.13],"market_cap_cr":[9000,28000],"revenue_cagr_3y":[0.05,0.20]}},
    {"symbol":"GRANULES","sector":"Pharma","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.08,0.20],"debt_to_equity":[0.1,0.5],"wacc":[0.11,0.14],"market_cap_cr":[9000,28000],"revenue_cagr_3y":[0.00,0.20]}},
    {"symbol":"ERIS","sector":"Pharma","bucket":"pharma","mcap_tier":"large","canary_bounds":{"roe":[0.10,0.20],"debt_to_equity":[0.5,1.2],"wacc":[0.10,0.13],"market_cap_cr":[9000,29000],"revenue_cagr_3y":[0.10,0.25]}},
]


def main() -> int:
    d = json.loads(PATH.read_text(encoding="utf-8"))

    # ── Pre-fix: Day-7 added 5 platform tickers with bucket='platform'
    # but the buckets dict never had a 'platform' key. Result: orphan
    # entries that the canary_diff harness silently couldn't validate
    # (missing roe / debt_to_equity / wacc fields too). Backfill:
    #
    #   (a) Add 'platform' to buckets meta description
    #   (b) Ensure buckets['platform'] list exists
    #   (c) Backfill the 5 entries' canary_bounds with full field set
    if "platform" not in d.get("buckets", {}):
        d["buckets"]["platform"] = []
    if "platform" not in d["_meta"].get("buckets", {}):
        d["_meta"].setdefault("buckets", {})["platform"] = (
            "Internet-platform + fintech-broker cohort (story-DCF eligible). "
            "Confidence is hard-capped at 50 — see StoryDcfBadge."
        )
    _PLATFORM_BACKFILL = {
        "MEESHO":     {"roe": None, "debt_to_equity": [0, 0.3], "wacc": [0.13, 0.16]},
        "SWIGGY":     {"roe": None, "debt_to_equity": [0, 0.3], "wacc": [0.13, 0.16]},
        "NUVAMA":     {"roe": [0.20, 0.35], "debt_to_equity": [1, 3], "wacc": [0.12, 0.14]},
        "GROWW":      {"roe": [0.10, 0.40], "debt_to_equity": [0.3, 1.5], "wacc": [0.12, 0.15]},
        "ANGELONE":   {"roe": [0.15, 0.40], "debt_to_equity": [0.5, 2], "wacc": [0.11, 0.14]},
        "MOTILALOFS": {"roe": [0.15, 0.30], "debt_to_equity": [0.5, 2], "wacc": [0.11, 0.14]},
        "360ONE":     {"roe": [0.12, 0.25], "debt_to_equity": [0.5, 2.5], "wacc": [0.11, 0.14]},
        "CDSL":       {"roe": [0.20, 0.32], "debt_to_equity": [0, 0.1], "wacc": [0.11, 0.14]},
        "MCX":        {"roe": [0.15, 0.40], "debt_to_equity": [0, 0.1], "wacc": [0.11, 0.14]},
    }
    for s in d["stocks"]:
        if s["symbol"] in _PLATFORM_BACKFILL:
            s["canary_bounds"].update(_PLATFORM_BACKFILL[s["symbol"]])
            if s["symbol"] not in d["buckets"]["platform"]:
                d["buckets"]["platform"].append(s["symbol"])

    existing_symbols = {s["symbol"] for s in d.get("stocks", [])}

    added = 0
    skipped = 0
    for new in NEW_TICKERS:
        sym = new["symbol"]
        bucket = new["bucket"]
        if sym in existing_symbols:
            skipped += 1
            continue
        if bucket not in d["buckets"]:
            print(f"WARN: bucket '{bucket}' not in existing buckets — skipping {sym}")
            continue
        # Existing buckets are LISTS of bare-symbol STRINGS — not objects
        if sym not in d["buckets"][bucket]:
            d["buckets"][bucket].append(sym)
        d["stocks"].append(new)
        existing_symbols.add(sym)
        added += 1

    # Update meta
    d["_meta"]["version"] = 3
    d["_meta"]["universe_version"] = f"v3_{len(d['stocks'])}"
    d["_meta"]["as_of"] = "2026-05-19"
    d["_meta"]["description"] = (
        f"{len(d['stocks'])}-stock canary universe (v3). Expanded from v2 (189) toward "
        "NIFTY 500 footprint (~339 tickers). Buckets retained: top100_diversified, "
        "banks, psu_utilities, cyclicals, pharma. New entries sourced from Day-15 "
        "merge-gate expansion against live stocks/market_metrics tables, capped to "
        "market_cap_cr >= 5,000 and excluding loss-makers + shadow tickers."
    )

    # Write back with consistent indent
    PATH.write_text(
        json.dumps(d, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",  # explicit LF; we cleaned the BOM earlier
    )
    bucket_sizes = {k: len(v) for k, v in d["buckets"].items()}
    print(f"OK: added {added} tickers, skipped {skipped} (duplicates)")
    print(f"Final universe: {len(d['stocks'])} stocks across {len(d['buckets'])} buckets")
    print(f"Bucket sizes: {bucket_sizes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
