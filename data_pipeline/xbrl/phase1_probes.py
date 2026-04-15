"""Phase 1 probes — find where BSE actually serves XBRL for a filing."""
import re
from bse import BSE

bse = BSE(download_folder='./temp/')

news_id = "065b7abc-81f7-4472-8e29-2e83cff76daa"
xml_name = "ANN_500325_065B7ABC-81F7-4472-8E29-2E83CFF76DAA"
scrip_code = "500325"

print("=" * 60)
print("PROBE 1 - AnnGetAttachment endpoint")
print("=" * 60)
urls1 = [
    f"https://api.bseindia.com/BseIndiaAPI/api/AnnGetAttachment/w?NewsID={news_id}",
    f"https://api.bseindia.com/BseIndiaAPI/api/AnnGetAttachment/w?NewsID={xml_name}",
]
for url in urls1:
    r = bse.session.get(url, timeout=15)
    print(f"URL: {url[:80]}")
    print(f"Status: {r.status_code} | CT: {r.headers.get('content-type','')}")
    print(f"Body: {r.text[:300]}")
    print("---")

print("=" * 60)
print("PROBE 2 - DispXBRLData endpoints")
print("=" * 60)
urls2 = [
    f"https://api.bseindia.com/BseIndiaAPI/api/DispXBRLDataByNewsid/w?newsid={news_id}",
    f"https://api.bseindia.com/BseIndiaAPI/api/DispXBRLDataByNewsid/w?newsid={xml_name}",
    f"https://api.bseindia.com/BseIndiaAPI/api/DispXBRLData/w?scripcode={scrip_code}&newsid={news_id}",
]
for url in urls2:
    r = bse.session.get(url, timeout=15)
    print(f"URL: {url[:80]}")
    print(f"Status: {r.status_code} | CT: {r.headers.get('content-type','')}")
    print(f"Body: {r.text[:300]}")
    print("---")

print("=" * 60)
print("PROBE 3 - AnnSubCategoryGetData with more fields")
print("=" * 60)
url3 = (
    f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    f"?strCat=Result&strPrevDate=20260101&strScrip={scrip_code}"
    f"&strSearch=P&strToDate=20260120&strType=C&subcategory=-1"
)
r = bse.session.get(url3, timeout=15)
print(f"Status: {r.status_code} | CT: {r.headers.get('content-type','')}")
try:
    data = r.json()
    tbl = data.get('Table') or []
    print(f"Rows in Table: {len(tbl)}")
    if tbl:
        first = tbl[0]
        print("ALL KEYS IN FIRST ROW:")
        for k, v in first.items():
            print(f"  {k}: {str(v)[:80]}")
except Exception as e:
    print(f"JSON parse failed: {e}")
    print(f"Body: {r.text[:300]}")

print("=" * 60)
print("PROBE 4 - BSE company results page scrape")
print("=" * 60)
qtr_url = (
    "https://www.bseindia.com/corporates/results.aspx"
    "?Code=500325&Company=Reliance-Industries-Ltd&qtr=128.00&RType="
)
r = bse.session.get(qtr_url, timeout=15)
print(f"Status: {r.status_code} | CT: {r.headers.get('content-type','')} | len={len(r.text)}")
xbrl_patterns = [
    r'\.xml',
    r'XBRL',
    r'xbrl',
    r'AttachHis/([^"\'<>]+\.xml)',
    r'corpfiling/([^"\'<>]+)',
]
for pattern in xbrl_patterns:
    matches = re.findall(pattern, r.text)
    if matches:
        print(f"Pattern {pattern!r} found {len(matches)} match(es), first 5: {matches[:5]}")
    else:
        print(f"Pattern {pattern!r} - no matches")

print("=" * 60)
print("PROBE 5 - Dispxbrlfiling / DispXBRLData paths")
print("=" * 60)
xbrl_paths = [
    f"https://www.bseindia.com/xml-data/corpfiling/Dispxbrlfiling/{scrip_code}/",
    f"https://www.bseindia.com/Corpfiling/DispXBRLData.aspx?newsid={news_id}",
    f"https://www.bseindia.com/corporates/DispXBRLData.aspx?newsid={news_id}",
]
for url in xbrl_paths:
    r = bse.session.get(url, timeout=15)
    print(f"URL: {url}")
    print(f"Status: {r.status_code} | CT: {r.headers.get('content-type','')} | len={len(r.text)}")
    print(f"Body first 200: {r.text[:200]!r}")
    print("---")
