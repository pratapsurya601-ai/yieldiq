"""Final probes — NSE BS/CF endpoints, BSE BS/CF endpoints, NSE history pagination."""
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
time.sleep(3)

print("=" * 60)
print("PROBE A - NSE annual-report / financials endpoints")
print("=" * 60)
nse_urls = [
    "https://www.nseindia.com/api/annual-reports?symbol=RELIANCE&industry=REFINERIES",
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&resultType=Standalone&period=Annual",
    "https://www.nseindia.com/api/quote-equity?symbol=RELIANCE&section=financials",
    "https://www.nseindia.com/api/corp-info?symbol=RELIANCE&corpType=balanceSheet&market=equities",
    "https://www.nseindia.com/api/corp-info?symbol=RELIANCE&corpType=cashFlow&market=equities",
    "https://www.nseindia.com/api/annual-financial-results?symbol=RELIANCE",
    "https://www.nseindia.com/api/fundamentals?symbol=RELIANCE",
]
for url in nse_urls:
    try:
        time.sleep(2)
        resp = session.get(url, timeout=15)
        data = {}
        try:
            data = resp.json()
        except Exception:
            pass
        periods = (
            data.get('resCmpData') or data.get('data') or data.get('results') or []
        )
        print(f"URL: ...{url[30:]}")
        print(f"Status: {resp.status_code} | Periods: {len(periods) if isinstance(periods, list) else 'N/A'} "
              f"| Keys: {list(data.keys())[:8] if data else 'N/A'}")
        if isinstance(periods, list) and periods:
            first = periods[0]
            if isinstance(first, dict):
                print(f"  FIELDS: {list(first.keys())[:15]}")
        elif not isinstance(data, dict) or not data:
            print(f"  Body: {resp.text[:200]}")
        print()
    except Exception as e:
        print(f"ERROR: {e}")

print("=" * 60)
print("PROBE B - BSE balance sheet / cash flow / ratios")
print("=" * 60)
from bse import BSE
bse = BSE(download_folder='./temp/')
bse_urls = [
    "https://api.bseindia.com/BseIndiaAPI/api/BalSheet/w?scripcode=500325&type=C",
    "https://api.bseindia.com/BseIndiaAPI/api/BalSheet/w?scripcode=500325&type=S",
    "https://api.bseindia.com/BseIndiaAPI/api/CashFlow/w?scripcode=500325&type=C",
    "https://api.bseindia.com/BseIndiaAPI/api/CashFlow/w?scripcode=500325&type=S",
    "https://api.bseindia.com/BseIndiaAPI/api/Peercomp/w?scripcode=500325&type=SA",
    "https://api.bseindia.com/BseIndiaAPI/api/Peercomp/w?scripcode=500325&type=CA",
    "https://api.bseindia.com/BseIndiaAPI/api/FinancialStatements/w?scripcode=500325",
    "https://api.bseindia.com/BseIndiaAPI/api/AnnualReportData/w?scripcode=500325",
    "https://api.bseindia.com/BseIndiaAPI/api/CompanyFinancials/w?scripcode=500325",
    "https://api.bseindia.com/BseIndiaAPI/api/Ratios/w?scripcode=500325",
]
for url in bse_urls:
    try:
        time.sleep(1.5)
        resp = bse.session.get(url, timeout=15)
        ct = resp.headers.get('content-type', '')
        is_json = 'json' in ct.lower()
        is_html = 'html' in ct.lower()
        print(f"URL: ...{url[40:]}")
        print(f"Status: {resp.status_code} | JSON: {is_json} | HTML: {is_html} | len={len(resp.text)}")
        if is_json and resp.status_code == 200:
            try:
                data = resp.json()
                s = json.dumps(data, default=str)[:400]
                print(f"  JSON DATA: {s}")
            except Exception as e:
                print(f"  JSON parse error: {e}")
                print(f"  Body: {resp.text[:200]}")
        else:
            print(f"  Body: {resp.text[:200]!r}")
        print()
    except Exception as e:
        print(f"ERROR: {e}")

print("=" * 60)
print("PROBE C - NSE results-comparision pagination / history")
print("=" * 60)
time.sleep(2)
session.get('https://www.nseindia.com', timeout=15)
time.sleep(3)
history_urls = [
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&count=20",
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&years=5",
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&limit=20",
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&from=2019-01-01",
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&page=2",
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE&offset=5",
]
for url in history_urls:
    try:
        time.sleep(2)
        resp = session.get(url, timeout=15)
        print(f"URL: ...{url[url.index('symbol='):]}")
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            try:
                data = resp.json()
                periods = data.get('resCmpData', [])
                print(f"Periods: {len(periods)}")
                if periods:
                    dates = [
                        f"{p.get('re_from_dt','')}..{p.get('re_to_dt','')}"
                        for p in periods
                    ]
                    print(f"  Dates: {dates}")
            except Exception as e:
                print(f"  JSON parse error: {e}")
        else:
            print(f"  Body: {resp.text[:200]}")
        print()
    except Exception as e:
        print(f"ERROR: {e}")
