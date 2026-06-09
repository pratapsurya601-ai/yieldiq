#!/usr/bin/env python3
"""
fetch_sector_heroes.py — download contextual hero photos per sector.

Hand-curated Unsplash photo IDs, one per sector slug, downloaded as
1600x600 WebP into ``frontend/public/hero-sectors/{slug}.webp``.

Unsplash License: free for commercial + non-commercial use without
attribution. Crediting photographers is appreciated, so per-photo
credit lives in ``frontend/public/hero-sectors/CREDITS.md``.

Run from repo root:
    python scripts/fetch_sector_heroes.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

# Hand-picked photo IDs. Each communicates the sector's "vibe" — what a
# user expects to see when they think of an HDFC Bank office, a TCS
# campus, an ITC kitchen, etc. Selection criteria:
#   - Workplace / lifestyle / infrastructure photography, NOT a logo
#   - Wide composition that crops cleanly to 1600x600 letterbox
#   - Subdued color so dark text overlays read well at the bottom
#
# Tuple is (slug, unsplash_photo_id, photographer_name, photographer_handle).
# Photographer fields drive the CREDITS.md generation below.
SECTOR_PHOTOS: list[tuple[str, str, str, str]] = [
    # Banking & Financials — corporate office tower glass / lobby
    ("banking", "photo-1450101499163-c8848c66ca85", "Etienne Martin", "etiennemartin"),
    # NBFC / asset management — financial dashboard / trading screens
    ("nbfc", "photo-1611974789855-9c2a0a7236a3", "Jakub Żerdzicki", "jakubzerdzicki"),
    # Insurance — umbrella / shelter / professional handshake
    ("insurance", "photo-1450101499163-c8848c66ca85", "Etienne Martin", "etiennemartin"),
    # IT services — modern open workspace with monitors
    ("it_services", "photo-1497366216548-37526070297c", "Copernico", "copernicowork"),
    # FMCG — grocery shelf / kitchen / consumer goods
    ("fmcg", "photo-1542838132-92c53300491e", "nrd", "nrd"),
    # Auto — highway at golden hour
    ("auto", "photo-1492144534655-ae79c964c9d7", "Robin Vet", "rvet"),
    # Pharma — laboratory / scientist hands / clean room
    ("pharma", "photo-1576091160399-112ba8d25d1d", "National Cancer Institute", "nci"),
    # Energy / Oil & Gas — refinery / oil rig at golden hour
    ("energy_oil_gas", "photo-1503694978374-8a2fa686963a", "Robin Sommer", "rommer"),
    # Power / utilities — transmission tower / power lines
    ("power_utilities", "photo-1473341304170-971dccb5ac1e", "Matthew Henry", "matthewhenry"),
    # Metals & Mining — quarry / mine / heavy equipment
    ("metals_mining", "photo-1581094271901-8022df4466f9", "Dominik Vanyi", "dominikvanyi"),
    # Cement / construction — construction site / crane / scaffolding
    ("cement_construction", "photo-1503387762-592deb58ef4e", "Scott Blake", "sunburned_surveyor"),
    # Industrials / Capital goods — factory floor / robotics / machinery
    ("industrials_capgoods", "photo-1565043666747-69f6646db940", "Lenny Kuhne", "lennykuhne"),
    # Telecom — telecom tower / network / antennas
    ("telecom", "photo-1494522855154-9297ac14b55f", "Frantzou Fleurine", "frantzou"),
    # Realty / REITs — modern building / skyline / commercial property
    ("realestate_reits", "photo-1486406146926-c627a92ad1ab", "Sean Pollock", "seanpollock"),
    # Consumer retail — mall / shop / retail interior
    ("consumer_retail", "photo-1481437156560-3205f6a55735", "Heidi Fin", "heidifin"),
    # Agri / chemicals — field / agriculture / harvest
    ("agri_chemicals", "photo-1500382017468-9049fed747ef", "Federico Respini", "federicorespini"),
    # Media / entertainment — film studio / camera / broadcast
    ("media_entertainment", "photo-1485846234645-a62644f84728", "Jakob Owens", "jakobowens1"),
    # Default — generic city / financial district skyline
    ("default", "photo-1444723121867-7a241cacace9", "Sean Pollock", "seanpollock"),
]

# Unsplash CDN base. The image-ID URLs return a WebP when you ask for
# `fm=webp`; sizing is server-side via `w`/`h`/`fit=crop`.
CDN = "https://images.unsplash.com/{photo_id}?w=1600&h=600&fit=crop&q=70&fm=webp"

OUT_DIR = Path(__file__).resolve().parents[1] / "frontend" / "public" / "hero-sectors"


def download(slug: str, photo_id: str) -> int:
    url = CDN.format(photo_id=photo_id)
    out = OUT_DIR / f"{slug}.webp"
    req = Request(url, headers={"User-Agent": "yieldiq-asset-fetch/1.0"})
    with urlopen(req, timeout=30) as resp:
        data = resp.read()
    out.write_bytes(data)
    return len(data)


def write_credits() -> None:
    lines = [
        "# Hero sector photo credits",
        "",
        "All photos sourced from [Unsplash](https://unsplash.com), used under the",
        "[Unsplash License](https://unsplash.com/license) (free for commercial",
        "and non-commercial use; attribution appreciated but not required).",
        "",
        "| Sector | Photographer | Unsplash |",
        "|---|---|---|",
    ]
    for slug, photo_id, name, handle in SECTOR_PHOTOS:
        lines.append(
            f"| `{slug}` | {name} | "
            f"[@{handle}](https://unsplash.com/@{handle}) / "
            f"[photo](https://unsplash.com/photos/{photo_id}) |"
        )
    (OUT_DIR / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    total_bytes = 0
    for slug, photo_id, *_ in SECTOR_PHOTOS:
        try:
            n = download(slug, photo_id)
            total_bytes += n
            print(f"  ok  {slug:24s} {n // 1024:5d} KB")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{slug}: {exc}")
            print(f"  FAIL {slug:24s} {exc}", file=sys.stderr)
        time.sleep(0.2)
    write_credits()
    print(f"\nTotal: {total_bytes // 1024} KB across {len(SECTOR_PHOTOS)} sectors")
    if failures:
        print("\nFailures:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    # Emit a machine-readable manifest the component can read at build
    # time if we ever want to auto-generate the sector → image map.
    manifest = {
        slug: {"photo_id": pid, "photographer": name, "handle": handle}
        for slug, pid, name, handle in SECTOR_PHOTOS
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
