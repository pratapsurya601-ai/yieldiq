# test_finnhub.py
# ═══════════════════════════════════════════════════════════════
# Run this from your yieldiq folder to verify Finnhub is working
# Command: python test_finnhub.py
# ═══════════════════════════════════════════════════════════════

import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("  YieldIQ — Finnhub Integration Test")
print("=" * 60)

# ── Test 1: API Key loaded ────────────────────────────────────
print("\n[1] Checking API key...")
try:
    import pathlib
    env_path = pathlib.Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "FINNHUB_API_KEY" in line and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k.strip(), v)

    key = os.environ.get("FINNHUB_API_KEY", "")
    if key and len(key) > 5:
        print(f"    ✓ API key loaded: {key[:4]}{'*' * (len(key)-4)}")
    else:
        print("    ✗ API key NOT found — check your .env file")
        print("      Expected: FINNHUB_API_KEY=your_key_here")
        sys.exit(1)
except Exception as e:
    print(f"    ✗ Error: {e}")
    sys.exit(1)

# ── Test 2: Raw Finnhub API call ──────────────────────────────
print("\n[2] Testing Finnhub API connection...")
import requests

TICKER = "AAPL"
BASE   = "https://finnhub.io/api/v1"

try:
    r = requests.get(f"{BASE}/quote",
                     params={"symbol": TICKER, "token": key},
                     timeout=8)
    if r.status_code == 200:
        data = r.json()
        price = data.get("c", 0)
        change = data.get("dp", 0)
        if price > 0:
            print(f"    ✓ Finnhub API live — {TICKER}: ${price:.2f} ({change:+.2f}%)")
        else:
            print(f"    ✗ Got response but price=0 — check key validity")
            print(f"      Response: {data}")
    elif r.status_code == 401:
        print("    ✗ HTTP 401 — Invalid API key")
    elif r.status_code == 429:
        print("    ✗ HTTP 429 — Rate limited (too many calls)")
    else:
        print(f"    ✗ HTTP {r.status_code}: {r.text[:100]}")
        sys.exit(1)
except requests.exceptions.Timeout:
    print("    ✗ Timeout — check internet connection")
    sys.exit(1)
except Exception as e:
    print(f"    ✗ Connection error: {e}")
    sys.exit(1)

# ── Test 3: Price target data ─────────────────────────────────
print("\n[3] Testing analyst price targets...")
try:
    r = requests.get(f"{BASE}/stock/price-target",
                     params={"symbol": TICKER, "token": key}, timeout=8)
    data = r.json()
    mean = data.get("targetMean", 0)
    count= data.get("numberOfAnalysts", 0)
    if mean > 0:
        print(f"    ✓ Price targets — Mean: ${mean:.2f} | Analysts: {count}")
    else:
        print(f"    ⚠ No price target data for {TICKER} (may be free tier limit)")
except Exception as e:
    print(f"    ✗ Error: {e}")

# ── Test 4: Earnings data ─────────────────────────────────────
print("\n[4] Testing earnings surprise history...")
try:
    r = requests.get(f"{BASE}/stock/earnings",
                     params={"symbol": TICKER, "limit": 4, "token": key}, timeout=8)
    data = r.json()
    if data and isinstance(data, list) and len(data) > 0:
        q = data[0]
        print(f"    ✓ Earnings data — Last quarter: "
              f"Actual ${q.get('actual',0):.2f} vs "
              f"Est ${q.get('estimate',0):.2f} "
              f"({q.get('surprisePercent',0):+.1f}%)")
    else:
        print(f"    ⚠ No earnings data returned")
except Exception as e:
    print(f"    ✗ Error: {e}")

# ── Test 5: Recommendation trend ─────────────────────────────
print("\n[5] Testing analyst recommendations...")
try:
    r = requests.get(f"{BASE}/stock/recommendation",
                     params={"symbol": TICKER, "token": key}, timeout=8)
    data = r.json()
    if data and isinstance(data, list) and len(data) > 0:
        latest = data[0]
        buy   = latest.get("buy", 0) + latest.get("strongBuy", 0)
        hold  = latest.get("hold", 0)
        sell  = latest.get("sell", 0) + latest.get("strongSell", 0)
        print(f"    ✓ Recommendations — Buy: {buy} | Hold: {hold} | Sell: {sell}")
    else:
        print(f"    ⚠ No recommendation data")
except Exception as e:
    print(f"    ✗ Error: {e}")

# ── Test 6: Company news ──────────────────────────────────────
print("\n[6] Testing company news feed...")
try:
    from datetime import datetime, timedelta
    today   = datetime.today().strftime("%Y-%m-%d")
    week_ago= (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
    r = requests.get(f"{BASE}/company-news",
                     params={"symbol": TICKER, "from": week_ago,
                             "to": today, "token": key}, timeout=8)
    data = r.json()
    if data and isinstance(data, list) and len(data) > 0:
        print(f"    ✓ News — {len(data)} headlines in last 7 days")
        print(f"      Latest: {data[0].get('headline','')[:60]}...")
    else:
        print(f"    ⚠ No news (may be weekend or quiet period)")
except Exception as e:
    print(f"    ✗ Error: {e}")

# ── Test 7: Full collector integration ────────────────────────
print("\n[7] Testing full StockDataCollector with Finnhub...")
try:
    from data.collector import StockDataCollector, FINNHUB_KEY
    print(f"    Finnhub key in collector: {'✓ yes' if FINNHUB_KEY else '✗ no'}")

    start = time.time()
    collector = StockDataCollector(TICKER)
    raw = collector.get_all()
    elapsed = time.time() - start

    if raw:
        print(f"    ✓ get_all() succeeded in {elapsed:.1f}s")
        print(f"      Price:        ${raw.get('price', 0):.2f}")
        print(f"      Company:      {raw.get('company_name', 'N/A')}")
        print(f"      Change:       {raw.get('price_change_pct', 0):+.2f}%")
        print(f"      Day High:     ${raw.get('day_high', 0):.2f}")
        print(f"      Day Low:      ${raw.get('day_low', 0):.2f}")
        print(f"      Sector:       {raw.get('sector_name', 'N/A')}")

        tgt = raw.get("finnhub_price_target", {})
        if tgt:
            print(f"      Price Target: ${tgt.get('mean', 0):.2f} mean "
                  f"({tgt.get('count', 0)} analysts)")
        else:
            print(f"      Price Target: not available")

        earnings = raw.get("finnhub_earnings", [])
        print(f"      Earnings:     {len(earnings)} quarters available")

        news = raw.get("news", [])
        print(f"      News:         {len(news)} headlines")

        income = raw.get("income_df", None)
        if income is not None and not income.empty:
            print(f"      Income stmt:  {len(income)} years of data ✓")
        else:
            print(f"      Income stmt:  empty (yfinance issue)")

        cf = raw.get("cf_df", None)
        if cf is not None and not cf.empty:
            print(f"      Cash flows:   {len(cf)} years of data ✓")
        else:
            print(f"      Cash flows:   empty (yfinance issue)")

    else:
        print(f"    ✗ get_all() returned None")

except Exception as e:
    import traceback
    print(f"    ✗ Error: {e}")
    traceback.print_exc()

# ── Summary ───────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  Test complete.")
print("  If all checks show ✓, Finnhub is fully integrated.")
print("  ⚠ warnings are OK — they mean the data exists but")
print("  is empty for this specific ticker/time.")
print("=" * 60)
