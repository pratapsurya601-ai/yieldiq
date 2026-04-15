"""
Option 2: ticker x category matrix via `bse` library.
Option 3: session warmup then direct Peercomp call.

Prints everything; no DB writes, no YieldIQ file edits.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests
from bse import BSE  # type: ignore

TEMP = Path(__file__).parent / "temp"
TEMP.mkdir(exist_ok=True)


def hr(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


# ──────────────────────────────────────────────────────────────────
# Option 2 — ticker x category matrix
# ──────────────────────────────────────────────────────────────────
def option_2():
    hr("OPTION 2 — ticker x category matrix")
    from datetime import datetime, timedelta

    bse = BSE(download_folder=str(TEMP))
    tickers = [
        ("500325", "RELIANCE"),
        ("532540", "TCS"),
        ("500209", "INFY"),
        ("500875", "ITC"),
    ]
    # library uses strCat="-1" sentinel for "all"; we also try variants
    categories = [
        "Result",
        "Results",
        "Financial Results",
        "Board Meeting",
        "",          # empty
        None,        # omit (library default = "-1")
    ]

    # BSE announcements only cover ~recent window — open a 365-day range
    to_d = datetime.now()
    from_d = to_d - timedelta(days=365)

    found = None
    for scrip, name in tickers:
        for cat in categories:
            try:
                kwargs = dict(scripcode=scrip, from_date=from_d, to_date=to_d)
                if cat is not None:
                    kwargs["category"] = cat
                data = bse.announcements(**kwargs)
                rows = data.get("Table", []) if isinstance(data, dict) else []
                total = (data.get("Table1") or [{}])[0].get("ROWCNT", "?") if isinstance(data, dict) else "?"
                print(f"{name:8s} | cat={cat!r:25s} | rows={len(rows):3d} | ROWCNT={total}")
                if rows and not found:
                    found = (name, scrip, cat, rows)
            except Exception as e:
                print(f"{name:8s} | cat={cat!r:25s} | ERROR {type(e).__name__}: {e}")
            if found:
                break
        if found:
            break

    if not found:
        print("\nNo combination returned rows in the last 365 days. "
              "Will try resultsSnapshot() instead (the library's financial-results method).")
        try:
            snap = bse.resultsSnapshot("500325")
            print("resultsSnapshot(500325) =")
            print(json.dumps(snap, indent=2, default=str)[:3000])
        except Exception as e:
            print(f"resultsSnapshot failed: {type(e).__name__}: {e}")
        return

    name, scrip, cat, rows = found
    print(f"\nFIRST HIT -> {name} / category={cat!r} / {len(rows)} rows")
    print("Field names (keys) of first row:")
    print(list(rows[0].keys()))
    print("\nFirst row JSON (truncated):")
    print(json.dumps(rows[0], indent=2, default=str)[:2000])

    # also show any attachment-looking fields across the first 3 rows
    print("\nAttachment-like fields across first 3 rows:")
    for i, r in enumerate(rows[:3]):
        atts = {k: v for k, v in r.items()
                if isinstance(v, str) and (v.lower().endswith(".xml") or v.lower().endswith(".pdf")
                                          or "XBRL" in k.upper() or "ATTACH" in k.upper())}
        print(f"  row {i}: {atts}")


# ──────────────────────────────────────────────────────────────────
# Option 3 — session warmup, then Peercomp directly
# ──────────────────────────────────────────────────────────────────
def option_3():
    hr("OPTION 3 — session warmup + direct Peercomp call")

    s = requests.Session()
    warmup_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-IN,en;q=0.9",
    }
    print("Step 1: GET https://www.bseindia.com (warmup)")
    r1 = s.get("https://www.bseindia.com", headers=warmup_headers, timeout=15)
    print(f"  HTTP {r1.status_code}  len(body)={len(r1.text)}")

    print("\nStep 2: cookies after warmup:")
    for c in s.cookies:
        print(f"  {c.name} = {c.value[:60]}{'...' if len(c.value) > 60 else ''}  (domain={c.domain})")
    if not len(s.cookies):
        print("  (no cookies set)")

    print("\nStep 3: Peercomp with warmed session")
    api_headers = {
        "User-Agent": warmup_headers["User-Agent"],
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.bseindia.com/",
        "Origin": "https://www.bseindia.com",
        "Accept-Language": "en-IN,en;q=0.9",
    }
    url = "https://api.bseindia.com/BseIndiaAPI/api/Peercomp/w?scripcode=500325&type=QB"
    r2 = s.get(url, headers=api_headers, timeout=20)
    ct = r2.headers.get("Content-Type", "")
    print(f"  HTTP {r2.status_code}  Content-Type={ct}  len(body)={len(r2.text)}")
    print("  First 300 chars:")
    print(r2.text[:300])
    is_json = "json" in ct.lower() or r2.text.lstrip().startswith(("{", "["))
    print(f"  Is JSON? {is_json}")

    # Bonus: also try the Peercomp endpoints the legacy file used (type=P/B/C with freq)
    print("\nStep 3b: same session against legacy Peercomp variants")
    for t, f in [("P", "A"), ("B", "A"), ("C", "A"), ("P", "Q")]:
        u = f"https://api.bseindia.com/BseIndiaAPI/api/Peercomp/w?scripcode=500325&type={t}&annuallyquarterly={f}"
        r = s.get(u, headers=api_headers, timeout=20)
        ctt = r.headers.get("Content-Type", "")
        isj = "json" in ctt.lower() or r.text.lstrip().startswith(("{", "["))
        print(f"  type={t} freq={f}  HTTP {r.status_code}  CT={ctt}  JSON={isj}  len={len(r.text)}")
        if isj:
            try:
                payload = r.json()
                tbl = payload.get("Table", []) if isinstance(payload, dict) else []
                print(f"    rows={len(tbl)}")
                if tbl:
                    print(f"    first row keys: {list(tbl[0].keys())}")
            except Exception as e:
                print(f"    json parse failed: {e}")


def main():
    option_2()
    option_3()
    print("\nDone.")


if __name__ == "__main__":
    main()
