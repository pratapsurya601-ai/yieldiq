# Currency mis-tag audit — 2026-05-18

## TL;DR

yfinance has flipped `financialCurrency` back to **INR** for the same
~18 IT-services and pharma tickers we previously repatriated. New rows
are now landing in INR while older rows still carry `currency='USD'` in
the `financials` table — a mixed-magnitude long tail that silently
breaks revenue-per-share, DCF, and any peer ratio that aggregates
across periods.

`scripts/audit_currency_mistags.py` is a **read-only** auditor. This
doc explains how to run it, what its output means, and the
operator-side decision matrix for repatriation.

## Background — prior fixes

| PR | Tickers | Fix |
|----|---------|-----|
| v50 | MPHASIS, COFORGE, PERSISTENT, KPITTECH | IT-services USD → INR repatriation |
| v75 | (4 IT-services, re-confirm) | Read-path conversion guard |
| v90 | ~14 pharma tickers (DRREDDY, SUNPHARMA, DIVISLAB, CIPLA, LUPIN, AUROPHARMA, BIOCON, TORNTPHARM, GLENMARK, IPCALAB, GRANULES, LAURUSLABS, PFIZER, PIIND…) | Pharma USD → INR repatriation |

All three PRs assumed yfinance's `financialCurrency` was authoritative.
It is not. The 2026-05-18 DRREDDY ticket showed yfinance now reports
`financialCurrency='INR'` for the same ticker it used to report as
USD. Older USD-magnitude rows in our table are therefore being mixed
with newer INR-magnitude rows tagged INR.

## What the audit script does

`scripts/audit_currency_mistags.py`:

1. Reads every row in `financials` where `currency='USD'`.
2. For each unique ticker, probes `yf.Ticker(t + '.NS').info` for:
   - `financialCurrency` (today's truth)
   - `country` (should be `"India"` for the mis-tag class)
   - `quoteType` (must not be `"ADR"` — true ADRs legitimately report
     in USD)
3. For each row, computes revenue-per-share. If the stored row is
   tagged USD but per-share revenue exceeds **$50 USD/share**, flags
   `magnitude_says_inr` — that magnitude is only plausible if the
   stored value is actually INR being mis-read as USD.
4. Writes a JSON report to `scripts/snapshots/currency_mistag_audit_<utc-ts>.json`.

**It writes nothing to the database. There is no `--apply` flag. Do
not add one in this PR.**

## How to run

```bash
# Local DRY-RUN with full yfinance probes
export DATABASE_URL="postgresql://...neon..."
python scripts/audit_currency_mistags.py

# Skip yfinance (DB-only, fast, for CI)
python scripts/audit_currency_mistags.py --no-yfinance

# Investigate a single ticker
python scripts/audit_currency_mistags.py --tickers DRREDDY
```

Sample shape: see `scripts/snapshots/currency_mistag_audit_SAMPLE.json`.

## Flags emitted

| Flag | Meaning |
|------|---------|
| `yfinance_says_inr` | yfinance currently reports `financialCurrency='INR'` for this ticker — our stored USD tag is stale. |
| `country_india` | yfinance country is India and quoteType is not ADR — issuer should be filing in INR. |
| `magnitude_says_inr(rps=N)` | Stored revenue / shares > $50/share — magnitude implies INR mis-tagged as USD. |

A ticker should be considered for repatriation when **at least two**
of the three flags fire. `magnitude_says_inr` alone is the strongest
signal because it is independent of yfinance's current mood.

## Estimated suspect count

Based on prior PRs (v50, v75, v90) and the DRREDDY ticket: expect
**~18 tickers** flagged (4 IT-services + ~14 pharma). If the audit
returns substantially more, that indicates the mis-tagging has spread
beyond the known set and a wider re-ingest is warranted.

## Decision matrix (operator side)

After running the audit, for each flagged ticker:

| Condition | Action |
|-----------|--------|
| 3/3 flags fire AND ticker was in v50/v75/v90 | Repatriate USD → INR (high confidence). |
| 2/3 flags fire, `quoteType='ADR'` | **Skip.** Legitimate ADR — keep USD. |
| 2/3 flags fire, country='India', no ADR | Repatriate. |
| Only `yfinance_says_inr` fires (magnitude is plausibly USD) | Manual review — could be a genuine USD reporter that happens to look INR-scale. |
| Only `magnitude_says_inr` fires, yfinance still says USD | Manual review — possible XBRL-side mis-tag distinct from the yfinance class. |

## Why this script does NOT auto-fix

Three reasons we learned the hard way:

1. **yfinance's `financialCurrency` is not authoritative.** It flipped
   once (USD → INR → USD → INR over a year). An auto-repair loop driven
   by that field would oscillate.
2. **ADR rows must stay USD.** A naive `UPDATE financials SET
   currency='INR' WHERE …` would corrupt any legitimate ADR row that
   happens to share a sector with the mis-tagged set.
3. **Repatriation changes magnitude by 80–90×.** Cache invalidation,
   canary-diff (per `CLAUDE.md` rule 1), and snapshot-before-bump
   (rule 2) all apply. Wrapping that into an audit script would violate
   the discipline that exists for a reason.

The follow-up PR (out of scope here) should:

1. Take the audit JSON as input.
2. Require explicit `--tickers` allowlist + `--apply` to mutate rows.
3. Bump `CACHE_VERSION` with a before/after snapshot.
4. Pass `canary_diff.py` 5/5 before merge.

## Files

- `scripts/audit_currency_mistags.py` — the auditor (read-only).
- `scripts/snapshots/currency_mistag_audit_SAMPLE.json` — illustrative
  output shape; real runs land in the same directory with a UTC
  timestamp.
- `docs/audit/currency-mistag-audit-2026-05-18.md` — this doc.
