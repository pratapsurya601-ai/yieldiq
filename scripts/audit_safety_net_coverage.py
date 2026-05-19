"""One-shot audit: which under-outliers will the safety-net peer
lookup successfully cover?

Run while the patched code is checked out but BEFORE deploy. Confirms
the sector mappings + cohort sizes are sufficient for each sample
under-outlier to receive a Tier 2 fallback FV.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.tier2_peer_lookup import fetch_peers_from_metrics_table


SAMPLE = [
    ("INDIACEM.NS",   "Cement"),
    ("PAYTM.NS",      "NBFC"),
    ("WESTLIFE.NS",   "Retail"),
    ("AEGISVOPAK.NS", "Capital Goods"),
    ("PINELABS.NS",   "NBFC"),
    ("BHEL.NS",       "Defence"),
    ("MAZDOCK.NS",    "Defence"),
    ("GRSE.NS",       "Defence"),
    ("FIVESTAR.NS",   "NBFC"),
    ("ITCHOTELS.NS",  "Retail"),
    ("EMMVEE.NS",     "Power"),
    ("ATHERENERG.NS", "Auto OEM"),
    ("BIOCON.NS",     "Pharma"),
    ("AMBUJACEM.NS",  "Cement"),
    ("TATACHEM.NS",   "Chemicals"),
    ("TVSMOTOR.NS",   "Auto OEM"),
    ("ADANIPORTS.NS", "Infra"),
    ("JSWSTEEL.NS",   "Metals/Mining"),
    ("NTPCGREEN.NS",  "Power"),
    ("OBEROIRLTY.NS", "Real Estate"),
    ("DELHIVERY.NS",  "Logistics"),
    ("DMART.NS",      "Retail"),
    ("INDIGO.NS",     "Airlines"),
    ("DIXON.NS",      "Tech Hardware/Electronics"),
    ("HAVELLS.NS",    "Consumer Durables"),
]


def main() -> int:
    print(f"{'Ticker':<16} {'Sector':<28} {'Peers':<6} {'Status'}")
    print("-" * 70)
    covered = 0
    for ticker, sector in SAMPLE:
        try:
            peers = fetch_peers_from_metrics_table(ticker, sector)
            n = len(peers)
        except Exception as exc:
            n = -1
            print(f"  ERROR on {ticker}: {exc}")
            continue
        # MIN_BUCKET_SIZE lowered to 3 on 2026-05-19 to broaden coverage
        status = "OK" if n >= 3 else f"INSUFFICIENT ({n}<3)"
        if n >= 3:
            covered += 1
        print(f"{ticker:<16} {sector:<28} {n:<6} {status}")
    print()
    print(f"Coverage: {covered}/{len(SAMPLE)} "
          f"({covered * 100 // len(SAMPLE)}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
