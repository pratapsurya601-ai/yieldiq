"""One-shot fetcher: live integrated-filing XBRLs for 3 insurance issuers.

Drops the freshest financial XBRL to tests/fixtures/xbrl/ for each of
HDFCLIFE (life), SBILIFE (life), ICICIGI (general). Used to extend
INSURANCE_QUARTERLY_TAGS with the full insurance schema discovered live.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_pipeline.sources.nse_quarterly_xbrl import (  # noqa: E402
    _fetch_integrated_filings,
    _legacy_fetch_filings_index,
)
from data_pipeline.sources.nse_xbrl_fundamentals import _get_session  # noqa: E402

OUT_DIR = ROOT / "tests" / "fixtures" / "xbrl"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("HDFCLIFE", "hdfclife_integrated_q4_fy26.xml"),
    ("SBILIFE",  "sbilife_integrated_q4_fy26.xml"),
    ("ICICIGI",  "icicigi_integrated_q4_fy26.xml"),
]


def fetch_one(symbol: str, out_name: str, session) -> dict:
    """Try integrated endpoint on all three indices, then legacy fallback."""
    report = {"symbol": symbol, "out": out_name}
    rows: list[dict] = []
    for idx in ("equities", "insurance"):
        try:
            r = _fetch_integrated_filings(symbol, index=idx, session=session)
        except Exception as exc:
            r = []
            report.setdefault("errs", []).append(f"integrated {idx}: {exc}")
        if r:
            rows = r
            report["source"] = f"integrated/{idx}"
            break
    if not rows:
        for idx in ("equities", "insurance"):
            try:
                r = _legacy_fetch_filings_index(symbol, idx, session=session)
            except Exception as exc:
                r = []
                report.setdefault("errs", []).append(f"legacy {idx}: {exc}")
            if r:
                rows = r
                report["source"] = f"legacy/{idx}"
                break
    if not rows:
        report["error"] = "no filings"
        return report

    # Pick freshest by toDate / periodEnd / qe_Date
    def _key(f):
        return f.get("toDate") or f.get("periodEnd") or f.get("qe_Date") or ""
    rows.sort(key=_key, reverse=True)
    chosen = rows[0]
    url = chosen.get("xbrl")
    report["xbrl_url"] = url
    report["period_end"] = _key(chosen)
    if not url or not str(url).startswith("http"):
        report["error"] = "no xbrl url"
        return report
    try:
        rr = session.get(url, timeout=30)
    except Exception as exc:
        report["error"] = f"download fail: {exc}"
        return report
    if rr.status_code != 200 or len(rr.content) < 500:
        report["error"] = f"http {rr.status_code} len={len(rr.content)}"
        return report
    out_path = OUT_DIR / out_name
    out_path.write_bytes(rr.content)
    report["bytes"] = len(rr.content)
    report["saved"] = str(out_path)
    return report


def main() -> int:
    session = _get_session()
    for symbol, out_name in TARGETS:
        rep = fetch_one(symbol, out_name, session)
        print(f"[{symbol}] {rep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
