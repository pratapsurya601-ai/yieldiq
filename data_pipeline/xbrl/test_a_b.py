"""Run TEST A and TEST B verbatim as specified."""
import json
import os
os.makedirs("./temp/", exist_ok=True)

print("=" * 70)
print("TEST A")
print("=" * 70)
from bse import BSE
bse = BSE(download_folder='./temp/')
result = bse.resultsSnapshot('500325')
print("TYPE:", type(result))
print(json.dumps(result, indent=2, default=str))

print()
print("=" * 70)
print("TEST B")
print("=" * 70)
from datetime import datetime, timedelta
today = datetime.now()
three_years_ago = today - timedelta(days=1095)

bse2 = BSE(download_folder='./temp/')
result2 = bse2.announcements(
    scripcode='500325',
    category='Result',
    from_date=three_years_ago.strftime('%Y%m%d'),
    to_date=today.strftime('%Y%m%d')
)
print(f"Total filings: {len(result2)}")
for r in result2:
    print(r.get('DT_TM',''), '|',
          r.get('NEWSSUB','')[:60], '|',
          r.get('XML_NAME',''), '|',
          r.get('ATTACHMENTNAME',''))
