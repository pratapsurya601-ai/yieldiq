"""
BSE connectivity test. Runs 4 independent checks and prints a clear
pass/fail + evidence for each one. Write-only diagnostic: does not
touch the DB or any other module.

Run from repo root:
    python -m data_pipeline.xbrl.test_connectivity
or:
    python data_pipeline/xbrl/test_connectivity.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

import requests

TEMP_DIR = Path(__file__).parent / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com",
    "Origin": "https://www.bseindia.com",
}


def _hr(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# ──────────────────────────────────────────────────────────────────
# Test 1 — BseIndiaApi library: ISIN/symbol → scrip code
# ──────────────────────────────────────────────────────────────────
def test_1_bseindiaapi_library() -> None:
    _hr("TEST 1 — BseIndiaApi library: getScripCode('RELIANCE')")
    try:
        from bse import BSE  # type: ignore
    except ImportError as e:
        print(f"FAIL: BseIndiaApi not installed ({e}).")
        print("      Install with: pip install BseIndiaApi")
        return

    try:
        bse = BSE(download_folder=str(TEMP_DIR))
        code = bse.getScripCode("RELIANCE")
        print(f"BSE code for RELIANCE: {code!r}")
        print("Expected: 500325")
        if str(code).strip() == "500325":
            print("PASS")
        else:
            print("MISMATCH — library responded but returned a different code")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        traceback.print_exc()


# ──────────────────────────────────────────────────────────────────
# Test 2 — Financial results via BseIndiaApi
# ──────────────────────────────────────────────────────────────────
def test_2_financial_results() -> None:
    _hr("TEST 2 — BseIndiaApi: quarterly financial results for 500325")
    try:
        from bse import BSE  # type: ignore
    except ImportError as e:
        print(f"SKIP: BseIndiaApi not installed ({e}).")
        return

    bse = BSE(download_folder=str(TEMP_DIR))

    # The library exposes several methods; probe whichever are present
    # and print the first result verbatim so we can see real field names.
    candidate_methods = [
        "getAnnouncements",
        "corporateActions",
        "quarterlyResults",
        "financials",
        "getQuarterlyResults",
        "getFinancialResults",
    ]
    available = [m for m in candidate_methods if hasattr(bse, m)]
    print(f"Available candidate methods on BSE(): {available}")

    # Try announcements filtered to Result category — this is the
    # documented way to reach financial filings in BseIndiaApi.
    try:
        if hasattr(bse, "announcements"):
            data = bse.announcements(scripcode="500325", category="Result")
            print(f"announcements(category='Result') type: {type(data).__name__}")
            print("First record (raw):")
            if isinstance(data, dict):
                tbl = data.get("Table") or data.get("table") or []
                print(json.dumps(tbl[0] if tbl else data, indent=2, default=str)[:1500])
            elif isinstance(data, list):
                print(json.dumps(data[0] if data else [], indent=2, default=str)[:1500])
            else:
                print(repr(data)[:1500])
            print("PASS (response received)")
            return
        else:
            print("Method .announcements() not available on BSE().")
    except Exception as e:
        print(f"announcements() failed: {type(e).__name__}: {e}")

    # Fallback: list every public attribute so we can see what the lib offers
    try:
        public = [a for a in dir(bse) if not a.startswith("_")]
        print(f"Public BSE() members: {public}")
    except Exception as e:
        print(f"Could not introspect BSE(): {e}")

    print("INCONCLUSIVE — no standard financial-results method succeeded")


# ──────────────────────────────────────────────────────────────────
# Test 3 — Direct XBRL XML download
# ──────────────────────────────────────────────────────────────────
def test_3_xbrl_download() -> None:
    _hr("TEST 3 — Download a recent XBRL XML from AttachHis")

    # Step A: find a real XBRL filename from the announcements feed.
    ann_url = (
        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
        "?pageno=1&strCat=Result&strPrevDate=&strScrip=500325&strSearch=P&strToDate=&strType=C"
    )
    # Also try the simpler CorporateAnnouncement endpoint that the legacy
    # code used, because the fancy one changes format often.
    simple_url = (
        "https://api.bseindia.com/BseIndiaAPI/api/CorporateAnnouncement/w"
        "?pageno=1&category=Result&scrip_cd=500325"
    )

    attach = None
    for label, url in [("AnnSubCategoryGetData", ann_url),
                       ("CorporateAnnouncement", simple_url)]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            print(f"[{label}] HTTP {r.status_code}  len(body)={len(r.text)}")
            if r.status_code != 200 or not r.text.strip():
                continue
            try:
                payload = r.json()
            except ValueError:
                print(f"[{label}] body is not JSON; first 200 chars:")
                print(r.text[:200])
                continue
            rows = (
                payload.get("Table")
                or payload.get("table")
                or payload.get("data")
                or []
            ) if isinstance(payload, dict) else []
            print(f"[{label}] rows returned: {len(rows)}")
            # Find the first row with an XML attachment
            for row in rows:
                xml_name = row.get("XBRLATTACHMENTNAME") or row.get("ATTACHMENTNAME") or ""
                if xml_name and xml_name.lower().endswith(".xml"):
                    attach = xml_name
                    print(f"[{label}] first XML attachment: {attach}")
                    break
            if attach:
                break
        except Exception as e:
            print(f"[{label}] request error: {type(e).__name__}: {e}")

    if not attach:
        print("No XML attachment found in announcements feed — cannot download.")
        print("FAIL")
        return

    # Step B: download it
    xml_url = f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{attach}"
    print(f"Downloading: {xml_url}")
    try:
        r = requests.get(xml_url, headers=HEADERS, timeout=30)
        print(f"HTTP {r.status_code}  len(body)={len(r.content)} bytes")
        if r.status_code != 200 or not r.content:
            print("FAIL")
            return
        out = TEMP_DIR / attach
        out.write_bytes(r.content)
        print(f"Saved to: {out}")
        preview = r.content[:500].decode("utf-8", errors="replace")
        print("First 500 chars:")
        print(preview)
        if "<?xml" in preview or "<xbrl" in preview.lower():
            print("PASS (looks like XML/XBRL)")
        else:
            print("WARNING — downloaded but content does not look like XML")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")


# ──────────────────────────────────────────────────────────────────
# Test 4 — Direct Peercomp API call
# ──────────────────────────────────────────────────────────────────
def test_4_peercomp_direct() -> None:
    _hr("TEST 4 — Direct BSE Peercomp API (scripcode=500325, type=QB)")
    url = "https://api.bseindia.com/BseIndiaAPI/api/Peercomp/w?scripcode=500325&type=QB"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        print(f"HTTP {r.status_code}")
        print(f"Content-Type: {r.headers.get('Content-Type')}")
        print(f"len(body)={len(r.text)}")
        print("First 200 chars of response:")
        print(r.text[:200])
        if r.status_code == 200 and r.text.strip():
            print("PASS (got 200 with body)")
        else:
            print("FAIL")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")


def main() -> int:
    print(f"Python: {sys.version.split()[0]}")
    print(f"requests: {requests.__version__}")
    print(f"temp dir: {TEMP_DIR}")
    test_1_bseindiaapi_library()
    test_2_financial_results()
    test_3_xbrl_download()
    test_4_peercomp_direct()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
