"""Read-only scanner for the financials-table reconciliation diagnosis.

For each ticker in canary_universe_180.json:
  1. GET /api/v1/analysis/{t}/financials?years=10 → new `company_financials` shape
  2. GET /api/v1/coverage/{t}                      → old `financials` row count (annual_history.value)

Per ticker, capture:
  - new_n: number of annual rows in company_financials
  - new_fys: list of FY strings present
  - new_dup_fys: FYs that appear more than once
  - new_missing_fys: gaps inside the FY sequence (e.g. FY22, FY24 present but FY23 absent)
  - new_revenue_yoy_spikes: list of (fy_pair, yoy_pct) where |yoy| > 50%
  - new_period_end_anomalies: rows where period_end month != Mar/Dec (fiscal-stub)
  - new_currency, new_currency_mix: from row[].currency if exposed
  - old_n: row count in old financials table (from coverage rubric)
  - div_gap: old_n - new_n

Writes _financials_scan.csv beside this script.
"""
from __future__ import annotations
import csv
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

BASE = "https://api.yieldiq.in/api/v1"
HERE = Path(__file__).parent
UNIVERSE = Path(__file__).parent.parent.parent / "scripts" / "canary_universe_180.json"
OUT_CSV = HERE / "_financials_scan.csv"
THROTTLE_S = 0.10

YOY_SPIKE = 0.50  # |yoy| > 50% flagged


def http_json(url: str, timeout: float = 20.0) -> tuple[int, dict | None]:
    req = urllib.request.Request(url, headers={"User-Agent": "fin-recon-scan/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def fy_for(period_end_iso: str) -> int | None:
    try:
        y, m, _ = period_end_iso.split("-")
        y_i = int(y); m_i = int(m)
        return y_i + 1 if m_i >= 4 else y_i
    except Exception:
        return None


def analyse_new(payload: dict | None) -> dict:
    out = {
        "new_n": 0,
        "new_fys": "",
        "new_dup_fys": "",
        "new_missing_fys": "",
        "new_yoy_spikes": "",
        "new_period_end_anomalies": "",
        "new_min_rev": "",
        "new_max_rev": "",
    }
    if not payload:
        return out
    inc = payload.get("income") or []
    if not isinstance(inc, list):
        return out
    out["new_n"] = len(inc)
    rows = []
    for r in inc:
        pe = r.get("period_end") or ""
        fy = fy_for(pe) if pe else None
        rev = r.get("revenue")
        rows.append((fy, pe, rev))
    fys = [f for f, _, _ in rows if f is not None]
    out["new_fys"] = "|".join(f"FY{f}" for f in fys)
    # duplicates
    seen = {}
    for f in fys:
        seen[f] = seen.get(f, 0) + 1
    dups = [f"FY{f}" for f, n in seen.items() if n > 1]
    out["new_dup_fys"] = "|".join(sorted(dups))
    # gaps
    if fys:
        lo, hi = min(fys), max(fys)
        expected = set(range(lo, hi + 1))
        present = set(fys)
        missing = sorted(expected - present)
        out["new_missing_fys"] = "|".join(f"FY{f}" for f in missing)
    # yoy spikes
    # sort newest→oldest by period_end iso desc; rows already are
    revs_by_fy: dict[int, float] = {}
    for fy, pe, rev in rows:
        if fy is None or rev is None:
            continue
        # If duplicate FY, take the larger one (some duplicates have one small stub)
        prev = revs_by_fy.get(fy)
        try:
            r = float(rev)
        except Exception:
            continue
        if prev is None or abs(r) > abs(prev):
            revs_by_fy[fy] = r
    sorted_fys = sorted(revs_by_fy.keys())
    spikes = []
    for i in range(1, len(sorted_fys)):
        a, b = sorted_fys[i - 1], sorted_fys[i]
        if b - a != 1:
            continue
        prev_v = revs_by_fy[a]
        cur_v = revs_by_fy[b]
        if prev_v == 0 or prev_v is None:
            continue
        yoy = (cur_v - prev_v) / abs(prev_v)
        if abs(yoy) > YOY_SPIKE:
            spikes.append(f"FY{a}->FY{b}:{yoy*100:+.0f}%")
    out["new_yoy_spikes"] = "|".join(spikes)
    # period_end anomalies: month not in {3, 12} (most NSE companies end Mar; some Dec)
    anomalies = []
    for fy, pe, _ in rows:
        try:
            mo = int(pe.split("-")[1])
            if mo not in (3, 12, 6, 9):  # treat Mar/Jun/Sep/Dec as normal
                anomalies.append(f"FY{fy}:{pe}")
        except Exception:
            pass
    out["new_period_end_anomalies"] = "|".join(anomalies)
    if revs_by_fy:
        out["new_min_rev"] = f"{min(revs_by_fy.values()):.1f}"
        out["new_max_rev"] = f"{max(revs_by_fy.values()):.1f}"
    return out


def analyse_coverage(payload: dict | None) -> dict:
    out = {"old_n": "", "cov_tier": "", "validator_warnings": ""}
    if not payload:
        return out
    out["cov_tier"] = payload.get("tier") or ""
    for r in payload.get("rubric") or []:
        if r.get("key") == "annual_history":
            v = r.get("value")
            out["old_n"] = str(v) if v is not None else ""
        if r.get("key") == "validator_warnings":
            out["validator_warnings"] = str(r.get("value") or "")
    return out


def main() -> int:
    with UNIVERSE.open("r", encoding="utf-8") as f:
        uni = json.load(f)
    stocks = uni.get("stocks") or []
    if not stocks:
        print("no stocks in universe", file=sys.stderr)
        return 2

    fields = [
        "symbol", "bucket", "sector",
        "new_n", "old_n", "div_gap",
        "new_fys", "new_dup_fys", "new_missing_fys",
        "new_yoy_spikes", "new_period_end_anomalies",
        "new_min_rev", "new_max_rev",
        "cov_tier", "validator_warnings",
        "fin_http", "cov_http",
        "flagged_corruption", "flagged_divergence",
    ]
    rows_out = []
    n = len(stocks)
    t0 = time.time()
    for i, s in enumerate(stocks, 1):
        sym = s.get("symbol") or ""
        if not sym:
            continue
        sector = s.get("sector") or ""
        bucket = s.get("bucket") or ""
        ts = f"{sym}.NS"

        fin_code, fin = http_json(f"{BASE}/analysis/{ts}/financials?years=10")
        time.sleep(THROTTLE_S)
        cov_code, cov = http_json(f"{BASE}/coverage/{ts}")
        time.sleep(THROTTLE_S)

        a = analyse_new(fin)
        c = analyse_coverage(cov)

        try:
            div_gap = int(c["old_n"]) - int(a["new_n"]) if c["old_n"] else ""
        except Exception:
            div_gap = ""

        flagged_corruption = []
        if a["new_dup_fys"]:
            flagged_corruption.append("dup")
        if a["new_missing_fys"]:
            flagged_corruption.append("gap")
        if a["new_yoy_spikes"]:
            flagged_corruption.append("yoy_spike")
        if a["new_period_end_anomalies"]:
            flagged_corruption.append("period_anom")
        flagged_divergence = ""
        if isinstance(div_gap, int) and abs(div_gap) >= 3:
            flagged_divergence = f"gap{div_gap:+d}"

        rows_out.append({
            "symbol": sym, "bucket": bucket, "sector": sector,
            "new_n": a["new_n"], "old_n": c["old_n"], "div_gap": div_gap,
            "new_fys": a["new_fys"], "new_dup_fys": a["new_dup_fys"],
            "new_missing_fys": a["new_missing_fys"],
            "new_yoy_spikes": a["new_yoy_spikes"],
            "new_period_end_anomalies": a["new_period_end_anomalies"],
            "new_min_rev": a["new_min_rev"], "new_max_rev": a["new_max_rev"],
            "cov_tier": c["cov_tier"], "validator_warnings": c["validator_warnings"],
            "fin_http": fin_code, "cov_http": cov_code,
            "flagged_corruption": "|".join(flagged_corruption),
            "flagged_divergence": flagged_divergence,
        })
        if i % 25 == 0 or i == n:
            dt = time.time() - t0
            print(f"[{i}/{n}] {sym} fin={fin_code} cov={cov_code} elapsed={dt:.0f}s", flush=True)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)
    print(f"wrote {OUT_CSV} ({len(rows_out)} rows)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
