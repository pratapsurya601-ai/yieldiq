"""Phase 0 — fixed Test B: pass datetime objects directly."""
from bse import BSE
from datetime import datetime, timedelta

bse = BSE(download_folder='./temp/')
today = datetime.now()
three_years_ago = today - timedelta(days=1095)

result = bse.announcements(
    scripcode='500325',
    category='Result',
    from_date=three_years_ago,
    to_date=today,
)
print(f"Total filings: {len(result)}")
print(f"Keys in response: {list(result.keys()) if isinstance(result, dict) else 'N/A'}")
rows = result.get("Table", []) if isinstance(result, dict) else []
rowcnt = (result.get("Table1") or [{}])[0].get("ROWCNT", "?") if isinstance(result, dict) else "?"
print(f"ROWCNT reported by BSE: {rowcnt}")
print(f"Rows on page 1: {len(rows)}")
print()
for r in rows:
    print(r.get('DT_TM','')[:10], '|',
          r.get('NEWSSUB','')[:50], '|',
          'XML:', r.get('XML_NAME','NO_XML'), '|',
          'PDF:', r.get('ATTACHMENTNAME','NO_PDF'))
