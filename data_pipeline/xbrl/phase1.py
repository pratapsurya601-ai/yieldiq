"""Phase 1 — try to download XBRL XML for the first RELIANCE filing.

Note: the library exposes its Session as `bse.session` (no underscore),
not `bse._session` as written in the spec. Using `bse.session`.
"""
import os
from bse import BSE

os.makedirs("temp", exist_ok=True)
bse = BSE(download_folder="./temp/")

xml_name = "ANN_500325_065B7ABC-81F7-4472-8E29-2E83CFF76DAA"

urls_to_try = [
    f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{xml_name}.xml",
    f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{xml_name.lower()}.xml",
    f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{xml_name}.zip",
]

saved = False
for url in urls_to_try:
    try:
        resp = bse.session.get(url, timeout=30)
        content_type = resp.headers.get("content-type", "")
        first_100 = resp.text[:100] if resp.text else ""
        is_html = (
            "html" in content_type.lower()
            or "<!doctype" in first_100.lower()
        )
        is_xml = "xml" in content_type.lower() or (
            "<?xml" in first_100
            or (first_100.strip().startswith("<") and not is_html)
        )

        print(f"URL: {url}")
        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {content_type}")
        print(f"Content-Length (bytes): {len(resp.content)}")
        print(f"Is HTML: {is_html}")
        print(f"Is XML: {is_xml}")
        print(f"First 200 chars: {resp.text[:200]!r}")
        print("---")

        if resp.status_code == 200 and is_xml:
            with open("temp/test_reliance.xml", "w", encoding="utf-8") as f:
                f.write(resp.text)
            print("SAVED to temp/test_reliance.xml")
            saved = True
            break
        elif resp.status_code == 200 and content_type.startswith("application"):
            with open("temp/test_reliance.zip", "wb") as f:
                f.write(resp.content)
            print("SAVED as zip to temp/test_reliance.zip")
            saved = True
            break
    except Exception as e:
        print(f"ERROR: {e}")

print("\nSession check - trying PDF URL:")
pdf_name = "38a2f910-438f-4fc0-8abc-c6cd5933b5ac.pdf"
pdf_url = f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{pdf_name}"
resp = bse.session.get(pdf_url, timeout=30)
print(f"PDF Status: {resp.status_code}")
print(f"PDF Content-Type: {resp.headers.get('content-type','')}")
print(f"PDF size: {len(resp.content)} bytes")
print(f"PDF first 8 bytes: {resp.content[:8]!r}")

print(f"\nXML saved? {saved}")
