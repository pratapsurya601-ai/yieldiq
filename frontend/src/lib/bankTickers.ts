// bankTickers.ts -- frontend mirror of the canonical commercial-bank
// universe defined in backend/services/analysis/sector_overrides.py
// as _PURE_BANK_TICKERS_FOR_DE (38 tickers).
//
// Kept in sync MANUALLY for now; the only consumer is BankKpiPanel's
// pre-fetch gate on /analysis/[ticker], and the backend endpoint
// returns is_bank:false for any ticker that's not in this set, so a
// drift just means an unnecessary network call (the panel still
// hides itself based on the response). When the cohort changes,
// update both files in the same PR.

const PURE_BANK_TICKERS = new Set<string>([
  // Tier-1 private
  "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK",
  // Tier-2 private / regional
  "FEDERALBNK", "IDFCFIRSTB", "AUBANK", "BANDHANBNK", "RBLBANK",
  // PSU
  "SBIN", "PNB", "BANKBARODA", "CANBK", "BANKINDIA", "IOB",
  "UCOBANK", "CENTRALBK", "INDIANB", "MAHABANK", "IDBI", "UNIONBANK",
  // Older private + small-finance
  "YESBANK", "KARURVYSYA", "CUB", "DCBBANK", "SOUTHBANK", "TMB",
  "CAPITALSFB", "ESAFSFB", "EQUITASBNK", "UJJIVANSFB", "SURYODAY",
  "FINOPB", "JANASURF", "UTKARSHBNK", "FINCABK", "SFBAJM",
])

function bareTicker(ticker: string | null | undefined): string {
  if (!ticker) return ""
  let bare = ticker.toUpperCase().trim()
  for (const suffix of [".NS", ".BO", ".BSE", ".NSE"]) {
    if (bare.endsWith(suffix)) {
      bare = bare.slice(0, -suffix.length)
      break
    }
  }
  return bare
}

export function isPureBank(ticker: string | null | undefined): boolean {
  return PURE_BANK_TICKERS.has(bareTicker(ticker))
}

export const PURE_BANK_TICKERS_FOR_DE = PURE_BANK_TICKERS
