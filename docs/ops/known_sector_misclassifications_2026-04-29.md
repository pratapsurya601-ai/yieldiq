# Known Sector Misclassifications — 2026-04-29

Tickers where yfinance returns a misleading top-level sector label that
does not match the canonical line of business. Tracked here so we
remember to (a) keep them in the unified bank-like classifier
(`backend/services/analysis/constants.py::_NBFC_INSURANCE_BANKLIKE`)
and (b) revisit a permanent data fix on the `stocks` table once the
yfinance label stabilises.

A direct `UPDATE stocks SET sector='Financial Services',
industry='Banks - Regional' WHERE ticker IN (...)` is intentionally NOT
applied here — it would mask the root cause (yfinance bad data) and
the next backfill would silently overwrite our manual values. The
classifier-side fix in `is_bank_like` is the safer mitigation: it
treats ticker membership as the authoritative signal, regardless of
what yfinance returns this week.

## Tickers

| Ticker | yfinance.sector (observed) | Canonical sector | Industry / Notes |
| --- | --- | --- | --- |
| CAPITALSFB.NS | Chemicals (!) | Financial Services | Banks - Regional. Capital Small Finance Bank, listed Jan 2024. Pre-fix: ran FCF-DCF, FV=999 vs price=257, MoS +289%, YieldIQ 89/A+ contradicting hex composite ~5/10. |
| ESAFSFB.NS | (varies, occasionally Industrials) | Financial Services | Banks - Regional. Listed Nov 2023. |
| UJJIVANSFB.NS | Financial Services | Financial Services | Banks - Regional. Already classified correctly via sector but kept on the explicit list as defence. |
| EQUITASBNK.NS | Financial Services | Financial Services | Banks - Regional. |
| AUBANK.NS | Financial Services | Financial Services | Banks - Regional. Was also in FINANCIAL_COMPANIES via INDUSINDBK-tier list pre-fix? Verified now via the unified set. |
| SURYODAY.NS | (occasionally Industrials) | Financial Services | Banks - Regional. SFB. |
| FINOPB.NS | (varies) | Financial Services | Banks - Regional. SFB. |
| JANASURF.NS | (varies) | Financial Services | Banks - Regional. SFB. |
| UTKARSHBNK.NS | (varies) | Financial Services | Banks - Regional. SFB. |

## Verification protocol

When a new SFB or NBFC IPO is observed serving a nonsense sector via
yfinance:

1. Add the ticker to `_NBFC_INSURANCE_BANKLIKE` in
   `backend/services/analysis/constants.py`.
2. Append a row to the table above with the date observed and the bad
   yfinance label.
3. Bump `CACHE_VERSION` so v(N-1) cached payloads (which still reflect
   the old DCF-path classification) are invalidated.
4. Verify post-deploy that `valuation.fair_value_source` for the new
   ticker contains `p_bv` or `peer_cap` (not the default DCF source)
   and that `valuation.margin_of_safety` is within ±30% on a fairly
   priced bank.

The unified `is_bank_like(ticker, sector, industry)` helper accepts
all three signals so a yfinance industry label of `Banks - Regional`
will catch new tickers automatically even before they make it onto
this list. The explicit ticker set is a belt-and-braces fallback for
the common case where yfinance returns "Chemicals" or similar
nonsense.
