"""Phase 0 — download one RELIANCE PDF via bse.session and inspect tables."""
import os
from datetime import datetime, timedelta
from bse import BSE

os.makedirs("data_pipeline/xbrl/temp", exist_ok=True)

bse = BSE(download_folder="./temp/")
today = datetime.now()
three_years_ago = today - timedelta(days=1095)

result = bse.announcements(
    scripcode="500325",
    category="Result",
    from_date=three_years_ago,
    to_date=today,
)
filings = result["Table"]
print(f"Found {len(filings)} filings")

latest = filings[0]
pdf_name = latest["ATTACHMENTNAME"]
period = latest.get("NEWSSUB", "")[:80]
print(f"Downloading: {period}")
print(f"PDF: {pdf_name}")

url = f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{pdf_name}"
resp = bse.session.get(url, timeout=30)
print(f"Status: {resp.status_code}")
print(f"Size: {len(resp.content)} bytes")

if resp.status_code == 200:
    path = "data_pipeline/xbrl/temp/reliance_latest.pdf"
    with open(path, "wb") as f:
        f.write(resp.content)
    print(f"Saved to {path}")

    import pdfplumber

    with pdfplumber.open(path) as pdf:
        print(f"Pages: {len(pdf.pages)}")
        for i, page in enumerate(pdf.pages[:3]):
            print(f"\n=== PAGE {i+1} ===")
            tables = page.extract_tables()
            print(f"Tables found: {len(tables)}")
            for j, table in enumerate(tables):
                cols = len(table[0]) if table else 0
                print(f"  Table {j+1}: {len(table)} rows x {cols} cols")
                for row in table[:5]:
                    # Truncate each cell for readable printing
                    trunc = [
                        (c[:50] if isinstance(c, str) else c) for c in row
                    ]
                    print(f"    {trunc}")
