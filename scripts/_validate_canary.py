import json
from pathlib import Path

d = json.load(open(Path(__file__).parent / "canary_universe_180.json", encoding="utf-8"))
print("parsed OK")
print("total:", len(d["stocks"]))

required = {"roe", "debt_to_equity", "wacc", "market_cap_cr", "revenue_cagr_3y"}
bad = []
for s in d["stocks"]:
    if "canary_bounds" not in s:
        bad.append(f"{s['symbol']}: no canary_bounds")
        continue
    missing = required - set(s["canary_bounds"].keys())
    if missing:
        bad.append(f"{s['symbol']}: missing {missing}")
print("validation errors:", len(bad))
for x in bad[:5]:
    print(" ", x)

all_syms = {s["symbol"] for s in d["stocks"]}
for bname, bsyms in d["buckets"].items():
    orphan = [s for s in bsyms if s not in all_syms]
    if orphan:
        print(f"bucket {bname} has orphans: {orphan[:5]}")

# Also check inverse: every stock's bucket field must point to a real bucket
bad_bucket = [s["symbol"] for s in d["stocks"] if s.get("bucket") not in d["buckets"]]
print("stocks with bad bucket field:", bad_bucket[:5])
