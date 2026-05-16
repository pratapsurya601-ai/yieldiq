"""Fetch the NIFTY SME EMERGE constituent list and cache to a file.

Output:
    data_pipeline/data/nse_sme_tickers.txt  (one ticker per line, sorted)

The cached file is consumed by:
    scripts/backfill_nse_quarterly_xbrl.py --batch sme_all --segment sme

Re-run periodically (monthly is enough) to pick up new SME listings.
The list is small (~500 names) and cheap to refresh.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_pipeline.sources.nse_xbrl_fundamentals import _get_session  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("fetch_sme")

SME_INDEX_URL = (
    "https://www.nseindia.com/api/equity-stockIndices"
    "?index=NIFTY%20SME%20EMERGE"
)
OUT_PATH = ROOT / "data_pipeline" / "data" / "nse_sme_tickers.txt"


def main() -> int:
    session = _get_session()
    r = session.get(SME_INDEX_URL, timeout=30, headers={"Accept": "application/json"})
    if r.status_code != 200:
        log.error("NSE returned HTTP %d", r.status_code)
        return 1
    try:
        data = r.json()
    except Exception as exc:
        log.error("JSON decode failed: %s", exc)
        return 1
    raw = data.get("data") or []
    # The first row is the index meta-entry ("NIFTY SME EMERGE"), skip it.
    syms = sorted({
        d.get("symbol") for d in raw
        if d.get("symbol") and d.get("symbol") != "NIFTY SME EMERGE"
    })
    if not syms:
        log.error("no symbols returned (NSE returned %d rows)", len(raw))
        return 1
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(syms) + "\n", encoding="utf-8")
    log.info("wrote %d SME tickers to %s", len(syms), OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
