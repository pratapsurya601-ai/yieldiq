"""Force-warm the analysis_cache for the 24 named Day-14-19 fixes
by hitting the public stock-summary endpoint, which triggers a fresh
compute under CACHE_VERSION 121 on cache_version mismatch.

Each request is one HTTP call; the API handles compute + cache-write.
We wait briefly between requests to avoid rate-limit / worker pressure.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request

TICKERS = [
    # Day-16 hospital
    "MAXHEALTH", "FORTIS", "MEDANTA", "KIMS", "APOLLOHOSP",
    "NH", "ASTERDM", "RAINBOW", "VIJAYA", "AGARWALEYE",
    # Day-17 recent-IPO
    "ITCHOTELS", "ABLBL", "FIVESTAR", "AADHARHFC", "CANHLIFE",
    # Day-18 logistics
    "DELHIVERY", "MAHLOG", "ALLCARGO",
    # Day-19 CDMO
    "DIVISLAB", "SYNGENE", "COHANCE", "ANTHEM", "SAGILITY", "IKS",
]


def warm(ticker: str) -> tuple[int, str]:
    url = f"https://api.yieldiq.in/api/v1/public/stock-summary/{ticker}.NS"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "yieldiq-force-warm/day20"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.getcode(), "ok"
    except urllib.error.HTTPError as e:
        return e.code, f"http_{e.code}"
    except urllib.error.URLError as e:
        return 0, f"url_err: {e.reason}"
    except Exception as e:  # noqa: BLE001
        return 0, f"err: {e.__class__.__name__}"


def main() -> int:
    print(f"force-warming {len(TICKERS)} tickers via public stock-summary")
    print(f"{'ticker':<12} {'status':<8} {'note':<24} {'elapsed':>8}")
    print("-" * 56)
    ok = 0
    for t in TICKERS:
        t0 = time.time()
        code, note = warm(t)
        elapsed = time.time() - t0
        if code == 200:
            ok += 1
        print(f"{t:<12} {code:<8} {note:<24} {elapsed:>7.1f}s")
        time.sleep(0.5)  # gentle pacing
    print()
    print(f"DONE: {ok}/{len(TICKERS)} warmed successfully")
    print("Now run:  py scripts/impact_check_day14_19.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
