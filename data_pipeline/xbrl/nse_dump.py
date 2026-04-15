"""Full dump of NSE results-comparision JSON for 4 tickers + BS/CF probing."""
import json
import time
import requests

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.nseindia.com',
    'Accept-Language': 'en-IN,en;q=0.9',
    'X-Requested-With': 'XMLHttpRequest',
})

session.get('https://www.nseindia.com', timeout=15)
time.sleep(2)

tickers = ['RELIANCE', 'TCS', 'HDFCBANK', 'ITC']

for ticker in tickers:
    print(f"\n{'='*60}")
    print(f"FULL DUMP: {ticker}")
    print('='*60)
    url = f"https://www.nseindia.com/api/results-comparision?index=equities&symbol={ticker}"
    try:
        time.sleep(3)
        resp = session.get(url, timeout=20)
        print(f"Status: {resp.status_code}")
        if resp.status_code != 200:
            print(f"FAILED: {resp.text[:200]}")
            continue
        data = resp.json()
        periods = data.get('resCmpData', [])
        print(f"Total periods returned: {len(periods)}")
        if not periods:
            print("NO DATA")
            continue
        print(f"\nALL KEYS in first period record:")
        first = periods[0]
        for key, val in first.items():
            print(f"  {key}: {str(val)[:80]}")
        print(f"\nPeriod date range:")
        for p in periods:
            print(f"  {p.get('re_from_dt',''):12s} to "
                  f"{p.get('re_to_dt',''):12s} | "
                  f"type={p.get('re_res_type','')} | "
                  f"created={p.get('re_create_dt','')}")
        save_path = f"data_pipeline/xbrl/temp/{ticker}_nse_full.json"
        with open(save_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\nSaved full JSON to {save_path}")
    except Exception as e:
        print(f"ERROR: {e}")

print("\n" + "="*60)
print("CHECKING FOR BALANCE SHEET + CASH FLOW")
print("="*60)

time.sleep(2)
session.get('https://www.nseindia.com', timeout=15)
time.sleep(2)

bs_cf_urls = [
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&type=balanceSheet",
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&type=cashFlow",
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&fin_type=balanceSheet",
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&fin_type=Annual",
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&res_type=Annual",
]

for url in bs_cf_urls:
    try:
        time.sleep(2)
        resp = session.get(url, timeout=15)
        try:
            data = resp.json() if resp.status_code == 200 else {}
        except Exception:
            data = {}
        periods = data.get('resCmpData', [])
        print(f"\nURL: ...{url[url.index('symbol='):]}")
        print(f"Status: {resp.status_code} | Periods: {len(periods)}")
        if periods:
            print(f"Keys: {list(periods[0].keys())[:10]}")
    except Exception as e:
        print(f"ERROR: {e}")
