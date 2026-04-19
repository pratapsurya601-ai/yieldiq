# Canary Diff Report

Commit: `bcda9636ce88`
Timestamp: 2026-04-19T08:32:37.436467+00:00

Stocks checked: **50**
Fetch failures: **49**
Total violations: **251**

## Gate totals
- **single_source_of_truth**: FAIL (52)
- **mos_math_consistency**: FAIL (50)
- **scenario_dispersion**: FAIL (49)
- **canary_bounds**: FAIL (50)
- **forbidden_values**: FAIL (50)

## Violations
### RELIANCE
- gate 1:
  - RELIANCE: fetch failed (HTTP 503)
- gate 2:
  - RELIANCE: fetch failed (HTTP 503)
- gate 3:
  - RELIANCE: fetch failed (HTTP 503)
- gate 4:
  - RELIANCE: fetch failed (HTTP 503)
- gate 5:
  - RELIANCE: fetch failed (HTTP 503)

### TCS
- gate 1:
  - TCS.bear_case: public=1899.93 authed={'iv': 1899.9250825231452, 'wacc': 0.113, 'growth': 0.013644261772478766, 'term_g': 0.03, 'mos_pct': -26.4022822962175}
  - TCS.base_case: public=3479.4 authed={'iv': 3479.4, 'wacc': 0.098, 'growth': 0.0736, 'term_g': 0.04, 'mos_pct': 34.8}
  - TCS.bull_case: public=4031.9 authed={'iv': 4031.8970035787297, 'wacc': 0.083, 'growth': 0.13364426177247876, 'term_g': 0.05, 'mos_pct': 56.18427284829478}
- gate 2:
  - TCS: mos=34.8000 but (fv-cmp)/cmp=0.3478
- gate 4:
  - TCS.wacc=0.098 outside [0.1, 0.14]
- gate 5:
  - TCS: |mos|=34.8 > 1.50

### HDFCBANK
- gate 1:
  - HDFCBANK: fetch failed (HTTP 503)
- gate 2:
  - HDFCBANK: fetch failed (HTTP 503)
- gate 3:
  - HDFCBANK: fetch failed (HTTP 503)
- gate 4:
  - HDFCBANK: fetch failed (HTTP 503)
- gate 5:
  - HDFCBANK: fetch failed (HTTP 503)

### INFY
- gate 1:
  - INFY: fetch failed (HTTP 503)
- gate 2:
  - INFY: fetch failed (HTTP 503)
- gate 3:
  - INFY: fetch failed (HTTP 503)
- gate 4:
  - INFY: fetch failed (HTTP 503)
- gate 5:
  - INFY: fetch failed (HTTP 503)

### ITC
- gate 1:
  - ITC: fetch failed (HTTP 503)
- gate 2:
  - ITC: fetch failed (HTTP 503)
- gate 3:
  - ITC: fetch failed (HTTP 503)
- gate 4:
  - ITC: fetch failed (HTTP 503)
- gate 5:
  - ITC: fetch failed (HTTP 503)

### HCLTECH
- gate 1:
  - HCLTECH: fetch failed (HTTP 503)
- gate 2:
  - HCLTECH: fetch failed (HTTP 503)
- gate 3:
  - HCLTECH: fetch failed (HTTP 503)
- gate 4:
  - HCLTECH: fetch failed (HTTP 503)
- gate 5:
  - HCLTECH: fetch failed (HTTP 503)

### ICICIBANK
- gate 1:
  - ICICIBANK: fetch failed (HTTP 503)
- gate 2:
  - ICICIBANK: fetch failed (HTTP 503)
- gate 3:
  - ICICIBANK: fetch failed (HTTP 503)
- gate 4:
  - ICICIBANK: fetch failed (HTTP 503)
- gate 5:
  - ICICIBANK: fetch failed (HTTP 503)

### BHARTIARTL
- gate 1:
  - BHARTIARTL: fetch failed (HTTP 503)
- gate 2:
  - BHARTIARTL: fetch failed (HTTP 503)
- gate 3:
  - BHARTIARTL: fetch failed (HTTP 503)
- gate 4:
  - BHARTIARTL: fetch failed (HTTP 503)
- gate 5:
  - BHARTIARTL: fetch failed (HTTP 503)

### SBIN
- gate 1:
  - SBIN: fetch failed (HTTP 503)
- gate 2:
  - SBIN: fetch failed (HTTP 503)
- gate 3:
  - SBIN: fetch failed (HTTP 503)
- gate 4:
  - SBIN: fetch failed (HTTP 503)
- gate 5:
  - SBIN: fetch failed (HTTP 503)

### LT
- gate 1:
  - LT: fetch failed (HTTP 503)
- gate 2:
  - LT: fetch failed (HTTP 503)
- gate 3:
  - LT: fetch failed (HTTP 503)
- gate 4:
  - LT: fetch failed (HTTP 503)
- gate 5:
  - LT: fetch failed (HTTP 503)

### BAJFINANCE
- gate 1:
  - BAJFINANCE: fetch failed (HTTP 503)
- gate 2:
  - BAJFINANCE: fetch failed (HTTP 503)
- gate 3:
  - BAJFINANCE: fetch failed (HTTP 503)
- gate 4:
  - BAJFINANCE: fetch failed (HTTP 503)
- gate 5:
  - BAJFINANCE: fetch failed (HTTP 503)

### KOTAKBANK
- gate 1:
  - KOTAKBANK: fetch failed (HTTP 503)
- gate 2:
  - KOTAKBANK: fetch failed (HTTP 503)
- gate 3:
  - KOTAKBANK: fetch failed (HTTP 503)
- gate 4:
  - KOTAKBANK: fetch failed (HTTP 503)
- gate 5:
  - KOTAKBANK: fetch failed (HTTP 503)

### AXISBANK
- gate 1:
  - AXISBANK: fetch failed (HTTP 503)
- gate 2:
  - AXISBANK: fetch failed (HTTP 503)
- gate 3:
  - AXISBANK: fetch failed (HTTP 503)
- gate 4:
  - AXISBANK: fetch failed (HTTP 503)
- gate 5:
  - AXISBANK: fetch failed (HTTP 503)

### MARUTI
- gate 1:
  - MARUTI: fetch failed (HTTP 503)
- gate 2:
  - MARUTI: fetch failed (HTTP 503)
- gate 3:
  - MARUTI: fetch failed (HTTP 503)
- gate 4:
  - MARUTI: fetch failed (HTTP 503)
- gate 5:
  - MARUTI: fetch failed (HTTP 503)

### WIPRO
- gate 1:
  - WIPRO: fetch failed (HTTP 503)
- gate 2:
  - WIPRO: fetch failed (HTTP 503)
- gate 3:
  - WIPRO: fetch failed (HTTP 503)
- gate 4:
  - WIPRO: fetch failed (HTTP 503)
- gate 5:
  - WIPRO: fetch failed (HTTP 503)

### SUNPHARMA
- gate 1:
  - SUNPHARMA: fetch failed (HTTP 503)
- gate 2:
  - SUNPHARMA: fetch failed (HTTP 503)
- gate 3:
  - SUNPHARMA: fetch failed (HTTP 503)
- gate 4:
  - SUNPHARMA: fetch failed (HTTP 503)
- gate 5:
  - SUNPHARMA: fetch failed (HTTP 503)

### TITAN
- gate 1:
  - TITAN: fetch failed (HTTP 503)
- gate 2:
  - TITAN: fetch failed (HTTP 503)
- gate 3:
  - TITAN: fetch failed (HTTP 503)
- gate 4:
  - TITAN: fetch failed (HTTP 503)
- gate 5:
  - TITAN: fetch failed (HTTP 503)

### ULTRACEMCO
- gate 1:
  - ULTRACEMCO: fetch failed (HTTP 503)
- gate 2:
  - ULTRACEMCO: fetch failed (HTTP 503)
- gate 3:
  - ULTRACEMCO: fetch failed (HTTP 503)
- gate 4:
  - ULTRACEMCO: fetch failed (HTTP 503)
- gate 5:
  - ULTRACEMCO: fetch failed (HTTP 503)

### POWERGRID
- gate 1:
  - POWERGRID: fetch failed (HTTP 503)
- gate 2:
  - POWERGRID: fetch failed (HTTP 503)
- gate 3:
  - POWERGRID: fetch failed (HTTP 503)
- gate 4:
  - POWERGRID: fetch failed (HTTP 503)
- gate 5:
  - POWERGRID: fetch failed (HTTP 503)

### HINDUNILVR
- gate 1:
  - HINDUNILVR: fetch failed (HTTP 503)
- gate 2:
  - HINDUNILVR: fetch failed (HTTP 503)
- gate 3:
  - HINDUNILVR: fetch failed (HTTP 503)
- gate 4:
  - HINDUNILVR: fetch failed (HTTP 503)
- gate 5:
  - HINDUNILVR: fetch failed (HTTP 503)

### DRREDDY
- gate 1:
  - DRREDDY: fetch failed (HTTP 503)
- gate 2:
  - DRREDDY: fetch failed (HTTP 503)
- gate 3:
  - DRREDDY: fetch failed (HTTP 503)
- gate 4:
  - DRREDDY: fetch failed (HTTP 503)
- gate 5:
  - DRREDDY: fetch failed (HTTP 503)

### ONGC
- gate 1:
  - ONGC: fetch failed (HTTP 503)
- gate 2:
  - ONGC: fetch failed (HTTP 503)
- gate 3:
  - ONGC: fetch failed (HTTP 503)
- gate 4:
  - ONGC: fetch failed (HTTP 503)
- gate 5:
  - ONGC: fetch failed (HTTP 503)

### NTPC
- gate 1:
  - NTPC: fetch failed (HTTP 503)
- gate 2:
  - NTPC: fetch failed (HTTP 503)
- gate 3:
  - NTPC: fetch failed (HTTP 503)
- gate 4:
  - NTPC: fetch failed (HTTP 503)
- gate 5:
  - NTPC: fetch failed (HTTP 503)

### TATAMOTORS
- gate 1:
  - TATAMOTORS: fetch failed (HTTP 503)
- gate 2:
  - TATAMOTORS: fetch failed (HTTP 503)
- gate 3:
  - TATAMOTORS: fetch failed (HTTP 503)
- gate 4:
  - TATAMOTORS: fetch failed (HTTP 503)
- gate 5:
  - TATAMOTORS: fetch failed (HTTP 503)

### M&M
- gate 1:
  - M&M: fetch failed (HTTP 503)
- gate 2:
  - M&M: fetch failed (HTTP 503)
- gate 3:
  - M&M: fetch failed (HTTP 503)
- gate 4:
  - M&M: fetch failed (HTTP 503)
- gate 5:
  - M&M: fetch failed (HTTP 503)

### HEROMOTOCO
- gate 1:
  - HEROMOTOCO: fetch failed (HTTP 503)
- gate 2:
  - HEROMOTOCO: fetch failed (HTTP 503)
- gate 3:
  - HEROMOTOCO: fetch failed (HTTP 503)
- gate 4:
  - HEROMOTOCO: fetch failed (HTTP 503)
- gate 5:
  - HEROMOTOCO: fetch failed (HTTP 503)

### DIVISLAB
- gate 1:
  - DIVISLAB: fetch failed (HTTP 503)
- gate 2:
  - DIVISLAB: fetch failed (HTTP 503)
- gate 3:
  - DIVISLAB: fetch failed (HTTP 503)
- gate 4:
  - DIVISLAB: fetch failed (HTTP 503)
- gate 5:
  - DIVISLAB: fetch failed (HTTP 503)

### COALINDIA
- gate 1:
  - COALINDIA: fetch failed (HTTP 503)
- gate 2:
  - COALINDIA: fetch failed (HTTP 503)
- gate 3:
  - COALINDIA: fetch failed (HTTP 503)
- gate 4:
  - COALINDIA: fetch failed (HTTP 503)
- gate 5:
  - COALINDIA: fetch failed (HTTP 503)

### TATASTEEL
- gate 1:
  - TATASTEEL: fetch failed (HTTP 503)
- gate 2:
  - TATASTEEL: fetch failed (HTTP 503)
- gate 3:
  - TATASTEEL: fetch failed (HTTP 503)
- gate 4:
  - TATASTEEL: fetch failed (HTTP 503)
- gate 5:
  - TATASTEEL: fetch failed (HTTP 503)

### JSWSTEEL
- gate 1:
  - JSWSTEEL: fetch failed (HTTP 503)
- gate 2:
  - JSWSTEEL: fetch failed (HTTP 503)
- gate 3:
  - JSWSTEEL: fetch failed (HTTP 503)
- gate 4:
  - JSWSTEEL: fetch failed (HTTP 503)
- gate 5:
  - JSWSTEEL: fetch failed (HTTP 503)

### ADANIPORTS
- gate 1:
  - ADANIPORTS: fetch failed (HTTP 503)
- gate 2:
  - ADANIPORTS: fetch failed (HTTP 503)
- gate 3:
  - ADANIPORTS: fetch failed (HTTP 503)
- gate 4:
  - ADANIPORTS: fetch failed (HTTP 503)
- gate 5:
  - ADANIPORTS: fetch failed (HTTP 503)

### BAJAJ-AUTO
- gate 1:
  - BAJAJ-AUTO: fetch failed (HTTP 503)
- gate 2:
  - BAJAJ-AUTO: fetch failed (HTTP 503)
- gate 3:
  - BAJAJ-AUTO: fetch failed (HTTP 503)
- gate 4:
  - BAJAJ-AUTO: fetch failed (HTTP 503)
- gate 5:
  - BAJAJ-AUTO: fetch failed (HTTP 503)

### ASIANPAINT
- gate 1:
  - ASIANPAINT: fetch failed (HTTP 503)
- gate 2:
  - ASIANPAINT: fetch failed (HTTP 503)
- gate 3:
  - ASIANPAINT: fetch failed (HTTP 503)
- gate 4:
  - ASIANPAINT: fetch failed (HTTP 503)
- gate 5:
  - ASIANPAINT: fetch failed (HTTP 503)

### NESTLEIND
- gate 1:
  - NESTLEIND: fetch failed (HTTP 503)
- gate 2:
  - NESTLEIND: fetch failed (HTTP 503)
- gate 3:
  - NESTLEIND: fetch failed (HTTP 503)
- gate 4:
  - NESTLEIND: fetch failed (HTTP 503)
- gate 5:
  - NESTLEIND: fetch failed (HTTP 503)

### BRITANNIA
- gate 1:
  - BRITANNIA: fetch failed (HTTP 503)
- gate 2:
  - BRITANNIA: fetch failed (HTTP 503)
- gate 3:
  - BRITANNIA: fetch failed (HTTP 503)
- gate 4:
  - BRITANNIA: fetch failed (HTTP 503)
- gate 5:
  - BRITANNIA: fetch failed (HTTP 503)

### DABUR
- gate 1:
  - DABUR: fetch failed (HTTP 503)
- gate 2:
  - DABUR: fetch failed (HTTP 503)
- gate 3:
  - DABUR: fetch failed (HTTP 503)
- gate 4:
  - DABUR: fetch failed (HTTP 503)
- gate 5:
  - DABUR: fetch failed (HTTP 503)

### GODREJCP
- gate 1:
  - GODREJCP: fetch failed (HTTP 503)
- gate 2:
  - GODREJCP: fetch failed (HTTP 503)
- gate 3:
  - GODREJCP: fetch failed (HTTP 503)
- gate 4:
  - GODREJCP: fetch failed (HTTP 503)
- gate 5:
  - GODREJCP: fetch failed (HTTP 503)

### PIDILITIND
- gate 1:
  - PIDILITIND: fetch failed (HTTP 503)
- gate 2:
  - PIDILITIND: fetch failed (HTTP 503)
- gate 3:
  - PIDILITIND: fetch failed (HTTP 503)
- gate 4:
  - PIDILITIND: fetch failed (HTTP 503)
- gate 5:
  - PIDILITIND: fetch failed (HTTP 503)

### TECHM
- gate 1:
  - TECHM: fetch failed (HTTP 503)
- gate 2:
  - TECHM: fetch failed (HTTP 503)
- gate 3:
  - TECHM: fetch failed (HTTP 503)
- gate 4:
  - TECHM: fetch failed (HTTP 503)
- gate 5:
  - TECHM: fetch failed (HTTP 503)

### GRASIM
- gate 1:
  - GRASIM: fetch failed (HTTP 503)
- gate 2:
  - GRASIM: fetch failed (HTTP 503)
- gate 3:
  - GRASIM: fetch failed (HTTP 503)
- gate 4:
  - GRASIM: fetch failed (HTTP 503)
- gate 5:
  - GRASIM: fetch failed (HTTP 503)

### CIPLA
- gate 1:
  - CIPLA: fetch failed (HTTP 503)
- gate 2:
  - CIPLA: fetch failed (HTTP 503)
- gate 3:
  - CIPLA: fetch failed (HTTP 503)
- gate 4:
  - CIPLA: fetch failed (HTTP 503)
- gate 5:
  - CIPLA: fetch failed (HTTP 503)

### EICHERMOT
- gate 1:
  - EICHERMOT: fetch failed (HTTP 503)
- gate 2:
  - EICHERMOT: fetch failed (HTTP 503)
- gate 3:
  - EICHERMOT: fetch failed (HTTP 503)
- gate 4:
  - EICHERMOT: fetch failed (HTTP 503)
- gate 5:
  - EICHERMOT: fetch failed (HTTP 503)

### TATACONSUM
- gate 1:
  - TATACONSUM: fetch failed (HTTP 503)
- gate 2:
  - TATACONSUM: fetch failed (HTTP 503)
- gate 3:
  - TATACONSUM: fetch failed (HTTP 503)
- gate 4:
  - TATACONSUM: fetch failed (HTTP 503)
- gate 5:
  - TATACONSUM: fetch failed (HTTP 503)

### BPCL
- gate 1:
  - BPCL: fetch failed (HTTP 503)
- gate 2:
  - BPCL: fetch failed (HTTP 503)
- gate 3:
  - BPCL: fetch failed (HTTP 503)
- gate 4:
  - BPCL: fetch failed (HTTP 503)
- gate 5:
  - BPCL: fetch failed (HTTP 503)

### IOC
- gate 1:
  - IOC: fetch failed (HTTP 503)
- gate 2:
  - IOC: fetch failed (HTTP 503)
- gate 3:
  - IOC: fetch failed (HTTP 503)
- gate 4:
  - IOC: fetch failed (HTTP 503)
- gate 5:
  - IOC: fetch failed (HTTP 503)

### HINDALCO
- gate 1:
  - HINDALCO: fetch failed (HTTP 503)
- gate 2:
  - HINDALCO: fetch failed (HTTP 503)
- gate 3:
  - HINDALCO: fetch failed (HTTP 503)
- gate 4:
  - HINDALCO: fetch failed (HTTP 503)
- gate 5:
  - HINDALCO: fetch failed (HTTP 503)

### SHREECEM
- gate 1:
  - SHREECEM: fetch failed (HTTP 503)
- gate 2:
  - SHREECEM: fetch failed (HTTP 503)
- gate 3:
  - SHREECEM: fetch failed (HTTP 503)
- gate 4:
  - SHREECEM: fetch failed (HTTP 503)
- gate 5:
  - SHREECEM: fetch failed (HTTP 503)

### HDFCLIFE
- gate 1:
  - HDFCLIFE: fetch failed (HTTP 503)
- gate 2:
  - HDFCLIFE: fetch failed (HTTP 503)
- gate 3:
  - HDFCLIFE: fetch failed (HTTP 503)
- gate 4:
  - HDFCLIFE: fetch failed (HTTP 503)
- gate 5:
  - HDFCLIFE: fetch failed (HTTP 503)

### SBILIFE
- gate 1:
  - SBILIFE: fetch failed (HTTP 503)
- gate 2:
  - SBILIFE: fetch failed (HTTP 503)
- gate 3:
  - SBILIFE: fetch failed (HTTP 503)
- gate 4:
  - SBILIFE: fetch failed (HTTP 503)
- gate 5:
  - SBILIFE: fetch failed (HTTP 503)

### ICICIPRULI
- gate 1:
  - ICICIPRULI: fetch failed (HTTP 503)
- gate 2:
  - ICICIPRULI: fetch failed (HTTP 503)
- gate 3:
  - ICICIPRULI: fetch failed (HTTP 503)
- gate 4:
  - ICICIPRULI: fetch failed (HTTP 503)
- gate 5:
  - ICICIPRULI: fetch failed (HTTP 503)

---
STATUS: FAIL