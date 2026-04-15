"""NSE XBRL / financials archive probe."""
import os
import time
import requests

os.makedirs('data_pipeline/xbrl/temp', exist_ok=True)

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.nseindia.com',
    'Accept-Language': 'en-IN,en;q=0.9',
})

print("Warming up NSE session...")
warmup = session.get('https://www.nseindia.com', timeout=15)
print(f"Warmup: {warmup.status_code} | Cookies: {dict(session.cookies)}")
time.sleep(2)

print("\n" + "=" * 60)
print("PROBE 1 - NSE financial-results APIs for RELIANCE")
print("=" * 60)
urls_to_try = [
    "https://www.nseindia.com/api/results-comparision?index=equities&symbol=RELIANCE",
    "https://www.nseindia.com/api/corp-info?symbol=RELIANCE&corpType=financialResults&market=equities",
    "https://nsearchives.nseindia.com/corporate/xbrl/RELIANCE_standalone_Q3_2025.xml",
    "https://www.nseindia.com/api/quote-equity?symbol=RELIANCE&section=financials",
]
for url in urls_to_try:
    try:
        time.sleep(2)
        resp = session.get(url, timeout=15)
        ct = resp.headers.get('content-type', '')
        print(f"\nURL: {url[:80]}")
        print(f"Status: {resp.status_code} | CT: {ct}")
        is_json = 'json' in ct.lower()
        is_xml = 'xml' in ct.lower() or resp.text[:10].strip().startswith('<?xml')
        print(f"JSON: {is_json} | XML: {is_xml}")
        print(f"Body: {resp.text[:400]}")
    except Exception as e:
        print(f"ERROR: {e}")

print("\n" + "=" * 60)
print("PROBE 2 - NSE XBRL direct archive paths")
print("=" * 60)
xbrl_patterns = [
    "https://nsearchives.nseindia.com/corporate/xbrl/",
    "https://archives.nseindia.com/corporate/xbrl/",
    "https://www.nseindia.com/corporates/xbrl/",
]
for url in xbrl_patterns:
    try:
        resp = session.get(url, timeout=10)
        print(f"URL: {url}")
        print(f"Status: {resp.status_code} | Size: {len(resp.content)}")
        print(f"Body: {resp.text[:200]}")
        print("---")
    except Exception as e:
        print(f"ERROR: {e}")

print("\n" + "=" * 60)
print("PROBE 3 - NSE financials endpoint")
print("=" * 60)
time.sleep(2)
fin_url = ("https://www.nseindia.com/api/financials?symbol=RELIANCE"
           "&fin_type=Quarterly&series=EQ")
try:
    resp = session.get(fin_url, timeout=15)
    ct = resp.headers.get('content-type', '')
    print(f"Status: {resp.status_code} | CT: {ct}")
    print(f"Body: {resp.text[:1000]}")
    if 'json' in ct.lower():
        import json
        data = resp.json()
        print("JSON KEYS:",
              list(data.keys()) if isinstance(data, dict) else type(data))
except Exception as e:
    print(f"ERROR: {e}")

print("\n" + "=" * 60)
print("PROBE 4 - NSE quote-equity?section=financials")
print("=" * 60)
time.sleep(2)
quote_urls = [
    "https://www.nseindia.com/api/quote-equity?symbol=RELIANCE&section=financials",
    "https://www.nseindia.com/api/quote-equity?symbol=TCS&section=financials",
]
for url in quote_urls:
    try:
        resp = session.get(url, timeout=15)
        ct = resp.headers.get('content-type', '')
        print(f"\nURL: {url[:80]}")
        print(f"Status: {resp.status_code} | CT: {ct}")
        print(f"Body: {resp.text[:800]}")
    except Exception as e:
        print(f"ERROR: {e}")
