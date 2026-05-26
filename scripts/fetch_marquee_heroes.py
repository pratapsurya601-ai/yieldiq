"""
fetch_marquee_heroes.py — download Wikipedia infobox photos for the top
50 most-traded NSE stocks and emit a manifest that the analysis hero
component can consume.

Why: Option C from the marquee-heroes spec — give the 50 most-traded
NSE names a hand-curated hero photo (landmark / product / building),
while the lower ~250 keep the existing logo-only Option A treatment.

What this does:
  1. Walks `MARQUEE_50` (ticker -> wikipedia article title) below.
  2. Hits the Wikipedia REST summary endpoint for each article and
     pulls `originalimage.source` (and the credit/license info we can
     scrape from the file metadata API).
  3. Downloads each image, re-encodes to JPEG ~800x450 at quality 85
     (ratchet to 75 if any file exceeds 150KB), saves to
     `frontend/public/hero/<TICKER>.jpg`.
  4. Writes `frontend/src/data/marquee_heroes.json` mapping ticker ->
     {src, credit, source_url}.

This script is run ONCE during PR prep. The build does not run it. No
runtime Wikipedia fetches — everything is committed as a static asset.
"""

from __future__ import annotations

import concurrent.futures as cf
import io
import json
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

import requests
from PIL import Image

# Force line-buffered stdout so progress is visible when launched in the
# background by a harness.
sys.stdout.reconfigure(line_buffering=True)

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_HERO_DIR = REPO_ROOT / "frontend" / "public" / "hero"
MANIFEST_PATH = REPO_ROOT / "frontend" / "src" / "data" / "marquee_heroes.json"

UA = "YieldIQ-MarqueeHeroFetcher/1.0 (https://yieldiq.in; contact: ops@yieldiq.in)"
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
FILE_META_URL = (
    "https://en.wikipedia.org/w/api.php?action=query&prop=imageinfo"
    "&iiprop=extmetadata|url&format=json&titles={file_title}"
)
PAGE_IMAGES_URL = (
    "https://en.wikipedia.org/w/api.php?action=query&prop=images"
    "&imlimit=40&format=json&titles={title}"
)
IMAGE_RESOLVE_URL = (
    "https://en.wikipedia.org/w/api.php?action=query&prop=imageinfo"
    "&iiprop=url&format=json&titles={file_title}"
)

# Substrings we don't want to pick up as a hero (logos, flags, charts).
_BLOCKLIST = (
    "logo",
    "flag",
    "increase",
    "decrease",
    "emblem",
    "symbol",
    "wikim",
    "edit-icon",
    "commons-logo",
    "question_book",
)
_IMG_EXT_OK = (".jpg", ".jpeg", ".png")


def pick_fallback_image(article_title: str) -> Optional[str]:
    """When REST summary returns no image, scrape the article's full
    images list and pick the first plausible non-logo JPG/PNG. Returns
    a resolved upload.wikimedia.org URL, or None.
    """
    try:
        r = requests.get(
            PAGE_IMAGES_URL.format(title=article_title),
            headers={"User-Agent": UA},
            timeout=(5, 15),
        )
        if r.status_code != 200:
            return None
        data = r.json()
        pages = (data.get("query") or {}).get("pages") or {}
        for _pid, page in pages.items():
            for img in page.get("images", []) or []:
                title = img.get("title") or ""
                lower = title.lower()
                if not any(lower.endswith(ext) for ext in _IMG_EXT_OK):
                    continue
                if any(b in lower for b in _BLOCKLIST):
                    continue
                # Resolve the file title to a real upload URL.
                rr = requests.get(
                    IMAGE_RESOLVE_URL.format(file_title=quote(title, safe=":")),
                    headers={"User-Agent": UA},
                    timeout=(5, 15),
                )
                if rr.status_code != 200:
                    continue
                rd = rr.json()
                for _ipid, ipage in (rd.get("query") or {}).get("pages", {}).items():
                    infos = ipage.get("imageinfo") or []
                    if infos and infos[0].get("url"):
                        return infos[0]["url"]
    except requests.RequestException as exc:
        print(f"  ! fallback images error: {exc}")
    return None

# Ticker -> Wikipedia article title. Hand-curated. If a stock's article
# doesn't have a usable infobox photo (e.g. it's a CEO portrait), we
# still try — the downloader will warn and we'll skip it in the manifest.
MARQUEE_50: list[tuple[str, str]] = [
    ("RELIANCE", "Reliance_Industries"),
    ("TCS", "Tata_Consultancy_Services"),
    ("HDFCBANK", "HDFC_Bank"),
    ("INFY", "Infosys"),
    ("ICICIBANK", "ICICI_Bank"),
    ("BHARTIARTL", "Bharti_Airtel"),
    ("ITC", "ITC_Limited"),
    ("SBIN", "State_Bank_of_India"),
    ("LT", "Larsen_%26_Toubro"),
    ("AXISBANK", "Axis_Bank"),
    ("KOTAKBANK", "Kotak_Mahindra_Bank"),
    ("HINDUNILVR", "Hindustan_Unilever"),
    ("BAJFINANCE", "Bajaj_Finance"),
    ("ASIANPAINT", "Asian_Paints"),
    ("MARUTI", "Maruti_Suzuki"),
    ("M&M", "Mahindra_%26_Mahindra"),
    ("SUNPHARMA", "Sun_Pharmaceutical"),
    ("TITAN", "Titan_Company"),
    ("ULTRACEMCO", "UltraTech_Cement"),
    ("WIPRO", "Wipro"),
    ("NESTLEIND", "Nestl%C3%A9_India"),
    ("TATAMOTORS", "Tata_Motors"),
    ("TATASTEEL", "Tata_Steel"),
    ("NTPC", "NTPC_Limited"),
    ("POWERGRID", "Power_Grid_Corporation_of_India"),
    ("ONGC", "Oil_and_Natural_Gas_Corporation"),
    ("COALINDIA", "Coal_India"),
    ("JSWSTEEL", "JSW_Steel"),
    ("ADANIENT", "Adani_Enterprises"),
    ("ADANIPORTS", "Adani_Ports_%26_SEZ"),
    ("HCLTECH", "HCLTech"),
    ("TECHM", "Tech_Mahindra"),
    ("BAJAJFINSV", "Bajaj_Finserv"),
    ("GRASIM", "Grasim_Industries"),
    ("INDUSINDBK", "IndusInd_Bank"),
    ("BPCL", "Bharat_Petroleum"),
    ("IOC", "Indian_Oil_Corporation"),
    ("HINDALCO", "Hindalco_Industries"),
    ("EICHERMOT", "Eicher_Motors"),
    ("DIVISLAB", "Divi%27s_Laboratories"),
    ("DRREDDY", "Dr._Reddy%27s_Laboratories"),
    ("CIPLA", "Cipla"),
    ("BRITANNIA", "Britannia_Industries"),
    ("DABUR", "Dabur"),
    ("HEROMOTOCO", "Hero_MotoCorp"),
    ("BAJAJ-AUTO", "Bajaj_Auto"),
    ("APOLLOHOSP", "Apollo_Hospitals"),
    ("TATACONSUM", "Tata_Consumer_Products"),
    ("PIDILITIND", "Pidilite_Industries"),
    ("SHREECEM", "Shree_Cement"),
]


def fetch_summary(article_title: str) -> Optional[dict]:
    url = SUMMARY_URL.format(title=article_title)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=(5, 15))
    except requests.RequestException as exc:
        print(f"  ! summary network error {article_title}: {exc}")
        return None
    if r.status_code != 200:
        print(f"  ! summary {r.status_code} {article_title}")
        return None
    return r.json()


def fetch_file_credit(file_url: str) -> tuple[str, str]:
    """Return (credit_string, source_url) for a Wikipedia/Commons image URL.

    file_url looks like
    https://upload.wikimedia.org/wikipedia/commons/.../Foo_Bar.jpg
    We derive the canonical "File:Foo_Bar.jpg" title and call the API
    for its imageinfo->extmetadata so we can pull Artist + LicenseShortName.
    """
    fname = unquote(file_url.rsplit("/", 1)[-1])
    file_title = f"File:{fname}"
    url = FILE_META_URL.format(file_title=quote(file_title, safe=":"))
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=(5, 10))
        if r.status_code != 200:
            return ("Wikipedia", f"https://commons.wikimedia.org/wiki/{quote(file_title)}")
        data = r.json()
        pages = (data.get("query") or {}).get("pages") or {}
        for _pid, page in pages.items():
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            meta = infos[0].get("extmetadata") or {}
            artist_raw = (meta.get("Artist") or {}).get("value") or ""
            license_name = (meta.get("LicenseShortName") or {}).get("value") or "CC"
            descr_url = infos[0].get("descriptionurl") or (
                f"https://commons.wikimedia.org/wiki/{quote(file_title)}"
            )
            # Strip HTML tags from artist (often wrapped in <a>...</a>).
            import re as _re
            artist = _re.sub(r"<[^>]+>", "", artist_raw).strip() or "Wikipedia"
            credit = f"Wikipedia / {artist} / {license_name}"
            return (credit, descr_url)
    except Exception as exc:  # noqa: BLE001
        print(f"    ! file_credit error: {exc}")
    return ("Wikipedia (CC-BY-SA)", f"https://commons.wikimedia.org/wiki/{quote(file_title)}")


def download_image(image_url: str) -> Optional[bytes]:
    try:
        r = requests.get(image_url, headers={"User-Agent": UA}, timeout=(5, 25))
    except requests.RequestException as exc:
        print(f"    ! image network error: {exc}")
        return None
    if r.status_code != 200:
        print(f"    ! image {r.status_code}")
        return None
    return r.content


def reencode(raw: bytes, target_path: Path) -> int:
    """Re-encode `raw` to ~800x450 JPEG. Returns final file size in bytes."""
    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = bg
    else:
        img = img.convert("RGB")
    # Cover-fit to 800x450 (crop centred).
    target_w, target_h = 800, 450
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    tgt_ratio = target_w / target_h
    if src_ratio > tgt_ratio:
        # too wide — scale by height then crop sides.
        new_h = target_h
        new_w = int(round(src_ratio * new_h))
    else:
        new_w = target_w
        new_h = int(round(new_w / src_ratio))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    target_path.parent.mkdir(parents=True, exist_ok=True)
    for quality in (85, 80, 75, 70):
        img.save(target_path, "JPEG", quality=quality, optimize=True, progressive=True)
        sz = target_path.stat().st_size
        if sz <= 150 * 1024:
            return sz
    return target_path.stat().st_size


def process_one(ticker: str, article: str) -> tuple[str, Optional[dict], Optional[str]]:
    """Worker for a single ticker.

    Returns (ticker, manifest_entry_or_None, skip_reason_or_None).
    """
    print(f"[{ticker}] start  ({article})")
    summary = fetch_summary(article)
    original: Optional[str] = None
    if summary:
        original = (summary.get("originalimage") or {}).get("source")
        if not original:
            original = (summary.get("thumbnail") or {}).get("source")
    if not original:
        # Fallback: scrape the article's images list for the first
        # plausible non-logo JPG/PNG. Catches articles where the REST
        # summary endpoint only knows the (SVG) logo (e.g. Axis Bank,
        # Maruti Suzuki, Tata Motors, Eicher Motors, ...).
        print(f"[{ticker}] summary has no image — falling back to page images")
        original = pick_fallback_image(article)
    if not original:
        print(f"[{ticker}] ! no image found")
        return (ticker, None, "no image found")

    raw = download_image(original)
    if not raw:
        return (ticker, None, "download failed")

    target = PUBLIC_HERO_DIR / f"{ticker}.jpg"
    try:
        sz = reencode(raw, target)
    except Exception as exc:  # noqa: BLE001
        print(f"[{ticker}] ! reencode failed: {exc}")
        return (ticker, None, f"reencode: {exc}")

    credit, source_url = fetch_file_credit(original)
    entry = {
        "src": f"/hero/{ticker}.jpg",
        "credit": credit,
        "source_url": source_url,
    }
    print(f"[{ticker}] ok {sz/1024:.1f} KB — {credit}")
    return (ticker, entry, None)


def main() -> int:
    PUBLIC_HERO_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    skipped: list[tuple[str, str]] = []

    # 8-way parallelism keeps us well under Wikipedia's API limits while
    # cutting wall-clock from ~5min serial to ~45s. Order of completion
    # is non-deterministic but the final manifest is re-ordered to match
    # the MARQUEE_50 list for stable diffs.
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(process_one, t, a) for t, a in MARQUEE_50]
        for fut in cf.as_completed(futures):
            ticker, entry, reason = fut.result()
            if entry:
                manifest[ticker] = entry
            else:
                skipped.append((ticker, reason or "unknown"))

    ordered_manifest = {t: manifest[t] for t, _ in MARQUEE_50 if t in manifest}

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w", encoding="utf-8") as fh:
        json.dump(
            {"_meta": {
                "description": "Top-50 NSE marquee tickers -> hand-curated hero image (Wikipedia infobox). Generated by scripts/fetch_marquee_heroes.py. Lower 200 fall through to logo-only hero.",
                "generated_count": len(ordered_manifest),
                "skipped": [{"ticker": t, "reason": r} for t, r in skipped],
            }, **ordered_manifest},
            fh,
            indent=2,
            ensure_ascii=False,
        )
        fh.write("\n")

    print()
    print(f"DONE  manifest={len(manifest)}  skipped={len(skipped)}")
    if skipped:
        for t, r in skipped:
            print(f"  - {t}: {r}")

    if len(skipped) > 15:
        print("WARN: >15 skips — manifest still written, but worth a look.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
