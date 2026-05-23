# Manual AR Signals — claude.ai web workflow

This folder is the drop-zone for **manually-curated AR extractions**
that bypass the paid Anthropic API. Files dropped here are bulk-loaded
into the `ar_signals` table by:

```
python scripts/load_manual_ar_signals.py
```

## Why this workflow exists

The full Anthropic-API AR backfill (`scripts/run_ar_intel_backfill.py`)
costs ~$500 for the universe. With ~$98 in API credits, we instead
hand-pick 10–20 high-traffic tickers, paste each AR's text into the
**free** claude.ai web interface, save the JSON response, and bulk-load
via this folder.

## File naming contract

```
<TICKER>_<FY>.json     e.g.  HDFCBANK_2025.json
                              RELIANCE_2024.json
```

- Ticker: uppercase, **no** `.NS` suffix. Same convention as
  `company_annual_reports.ticker`.
- FY: four-digit fiscal-year-end (FY25 → `2025`).

The loader cross-checks `<TICKER>_<FY>` against the JSON's `ticker`
and `fiscal_year` keys; mismatches abort that file.

## JSON shape

Top-level keys (loader will reject the file if any are missing):

```json
{
  "ticker": "HDFCBANK",
  "fiscal_year": 2025,
  "segment_data":               [ ... ],
  "capex_commitments":          [ ... ],
  "related_party_transactions": [ ... ],
  "auditor_flags":              [ ... ],
  "contingent_liabilities":     [ ... ],
  "management_outlook":         "free-text MD&A summary (<= 1500 chars)"
}
```

The six section shapes match `backend/services/ar_intel_service.py`'s
`_SYSTEM_PROMPT`. Empty arrays are valid; `management_outlook` may be
an empty string.

## Extended fields (migration 063, 2026-05-24)

Ten additional **OPTIONAL** top-level JSONB fields land in `ar_signals`
via migration `063_ar_signals_extended_fields.sql`. The loader treats
them as optional — files that omit them simply persist NULL on those
columns, so the existing 21 rows stay valid without backfill.

New extractions (top-200 batch) should fill any subset the AR
actually discloses. All numeric leaves default to `null` when not
disclosed; all arrays default to `[]` when truly empty (not `null`);
`note` fields are free-text 1-line context.

```json
{
  "ticker": "TICKER",
  "fiscal_year": 2025,

  "segment_data":               [ ... ],
  "capex_commitments":          [ ... ],
  "related_party_transactions": [ ... ],
  "auditor_flags":              [ ... ],
  "contingent_liabilities":     [ ... ],
  "management_outlook":         "...",

  "risk_factors": [
    {"category": "regulatory|operational|financial|market|strategic|geopolitical|cyber|climate",
     "description": "...", "mitigation": "..."}
  ],
  "esg_metrics": {
    "scope1_emissions_tco2e": null,
    "scope2_emissions_tco2e": null,
    "scope3_emissions_tco2e": null,
    "water_withdrawal_kl": null,
    "renewable_energy_pct": null,
    "gender_ratio_pct_female_workforce": null,
    "lost_time_injury_frequency_rate": null,
    "csr_spend_cr": null,
    "note": "..."
  },
  "governance": {
    "promoter_pledge_pct": null,
    "promoter_shareholding_pct": null,
    "board_independence_pct": null,
    "auditor_remuneration_cr": null,
    "whistleblower_complaints_count": null,
    "sexual_harassment_complaints_count": null,
    "regulatory_penalties_cr": null,
    "note": "..."
  },
  "workforce_metrics": {
    "total_headcount": null,
    "attrition_pct": null,
    "gender_ratio_pct_female": null,
    "training_hours_per_employee": null,
    "employee_cost_pct_revenue": null,
    "note": "..."
  },
  "customer_concentration": {
    "top_10_customer_pct_revenue": null,
    "geographic_split": [{"region": "...", "pct_revenue": null}],
    "channel_split":    [{"channel": "D2C|B2B|B2C|Export", "pct_revenue": null}],
    "note": "..."
  },
  "operational_kpis": {
    "industry": "banks|it_services|fmcg|auto|pharma|retail|metals|cement|telecom|hotels|infra|chemicals|other",
    "metrics": {
      "capacity_utilisation_pct": null,
      "plants_count": null,
      "stores_count": null,
      "r_and_d_spend_pct_revenue": null,
      "subscriber_count_mn": null,
      "fleet_count": null
    },
    "note": "..."
  },
  "subsidiary_summary": [
    {"name": "...", "country": "...", "revenue_cr": null, "pat_cr": null,
     "networth_cr": null, "ownership_pct": null}
  ],
  "dividend_history": [
    {"fiscal_year": 2025, "interim_dps_rs": null, "final_dps_rs": null,
     "special_dps_rs": null, "total_dps_rs": null, "payout_ratio_pct": null}
  ],
  "capital_actions": [
    {"type": "buyback|bonus|split|qip|rights|preferential|debenture",
     "date": "YYYY-MM-DD", "ratio_or_price": "...", "amount_cr": null}
  ],
  "strategic_priorities": [
    {"priority": "...", "target": "...", "timeline": "FY26|FY26-FY28|long-term"}
  ]
}
```

**Backward-compat:** files that contain only the original 6 sections
keep loading exactly as before — the loader passes NULL into every
extended column. No re-extraction of the existing 21 tickers is
needed.

**Frontend exposure:** none yet. The new fields land in the DB but
no panel surfaces them. A future PR will wire them up after we
measure user interest in the basic AR panel.

## Step-by-step

1. Open the AR PDF (the URL in `company_annual_reports.ar_url`).
2. In claude.ai web, paste the **same system prompt** from
   `_SYSTEM_PROMPT` in `backend/services/ar_intel_service.py`
   (SEBI-compliance rules + JSON schema spec). The exact text is
   reproduced at the bottom of this README — copy from there.
3. Paste the AR text (you can chunk it across multiple messages — ask
   Claude to merge into a single JSON at the end).
4. Take Claude's final JSON, **prepend** the `"ticker"` and
   `"fiscal_year"` keys, save as `<TICKER>_<FY>.json` in this folder.
5. Validate before writing:
   ```
   python scripts/load_manual_ar_signals.py --dry-run --tickers HDFCBANK
   ```
6. If clean, load for real:
   ```
   python scripts/load_manual_ar_signals.py --tickers HDFCBANK
   ```
   Or load every file in this folder:
   ```
   python scripts/load_manual_ar_signals.py
   ```

## SEBI sanitizer behaviour

The loader runs the same `scan_for_banned_vocab` walker the live
extractor uses. Behaviour:

- 0 findings → row goes in as `quality_flag='ok'`.
- 1–5 findings → banned words are swapped for `[redacted]`; row goes
  in as `quality_flag='ok'`.
- > 5 findings → free-text fields are blanked and the row is
  persisted with `quality_flag='sebi_withheld'`. The public reader
  collapses these to `{signals: null, withheld: true}`.

If you see `withheld>0` in the summary, re-prompt Claude with a
reminder of the SEBI-banned vocab list and regenerate.

## DB write metadata

| column          | value                  |
|-----------------|------------------------|
| `model_version` | `claude-ai-web-manual` |
| `prompt_version`| `1`                    |
| `input_tokens`  | `NULL`                 |
| `output_tokens` | `NULL`                 |
| `cost_usd`      | `0`                    |

Idempotency: the UNIQUE on `(annual_report_id, model_version,
prompt_version)` plus `ON CONFLICT … DO UPDATE` means re-running
the loader simply refreshes the row. Safe.

## System prompt to paste into claude.ai

> See the `_SYSTEM_PROMPT` literal in
> `backend/services/ar_intel_service.py`. Copy it verbatim — do not
> paraphrase the SEBI-compliance bullet list. The banned vocab list
> there is the single source of truth.

## Git hygiene

The JSON files in this folder may contain ticker-specific commentary
that we'd rather not commit (it's regeneratable). `.gitignore` for
this folder is left up to the operator — the loader only reads.
