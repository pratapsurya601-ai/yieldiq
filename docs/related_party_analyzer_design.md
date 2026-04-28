# Related-party transactions (RPT) analyzer — design

Status: **scaffolding landed, Phase-1 PDF parsing + Phase-2 LLM extraction not yet implemented.**

## Why this matters

Indian listed-company governance lives or dies on related-party transactions. SEBI Listing Obligations and Disclosure Requirements (LODR) Reg 23 and Section 188 of the Companies Act 2013 require companies to disclose every material contract with promoters, directors, KMPs, and their entities — including loans, royalty payments, asset sales, leases, and "consultancy" arrangements. Western data platforms ignore this almost completely because (a) the disclosures live in unstructured PDF annual reports, not XBRL, and (b) the regulatory framing is unfamiliar. YieldIQ's edge is to be excellent here: surface the disclosures, run a curated red-flag rule set on top, and present the result on the analysis page next to fundamentals and Pulse.

## Data sources

| Source | URL pattern | Notes |
| --- | --- | --- |
| BSE annual reports | `https://www.bseindia.com/xml-data/corpfiling/AttachLive/{guid}.pdf` (PDF), `https://www.bseindia.com/corporates/ann.html?scrip={bse_code}` (index) | Primary. Most ARs available within ~30d of AGM. |
| NSE annual reports | `https://www.nseindia.com/api/annual-reports?index=equities&symbol={NSE_SYMBOL}` (JSON), `https://www.nseindia.com/companies-listing/corporate-filings-annual-reports` (browse) | Fallback when BSE 404s. Same PDFs in many cases. |
| SEBI portal | `https://www.sebi.gov.in/sebi_data/...` | Cross-check for the largest issuers; not used as primary. |

The disclosures we care about live in:
- **Form AOC-2** (Companies Act Sec 188) — material contracts/arrangements with related parties. Includes the arms-length declaration.
- **MGT-9** (extract of annual return) — named related-party listing.
- **Notes to the financial statements** — actual transaction values for the year (the AOC-2 schedule is sometimes summary-only).

## Schema (`migration 017`)

`related_party_transactions` stores one row per (party, txn_type, amount). Rationale per column:

| Column | Why |
| --- | --- |
| `ticker`, `fiscal_year` | Hot index for the analysis-page query. |
| `source_filing` | `AOC-2` / `MGT-9` / `AnnualReport` / `NoteN`. Audit + replay. |
| `related_party_name` | Verbatim from the disclosure. We do *not* normalise names at ingest — Phase-3 will dedupe via embedding similarity once we have enough corpus. |
| `related_party_type` | `subsidiary` / `associate` / `kmp` / `promoter_entity` / `director_entity` / `relative_kmp` / `other`. Maps onto AS-18 / Ind-AS-24 / SEBI LODR Reg 23 categories. The split between `promoter_entity` and `director_entity` matters because different red-flag thresholds apply. |
| `txn_type` | `loan_given` / `loan_taken` / `sale_goods` / `purchase_goods` / `rendering_service` / `receiving_service` / `royalty` / `rent` / `guarantee` / `asset_sale` / `asset_purchase` / `investment` / `other`. Granular enough to drive the rule set without exploding the enum. |
| `amount_inr` | NUMERIC(15,2). Always rupees, NOT crore — the LLM prompt converts. |
| `is_arms_length` | Declared in AOC-2; nullable because not all sources disclose it. |
| `llm_confidence` (0–1) + `human_reviewed` | Confidence < 0.85 should *not* auto-publish; it queues for human review. The bar is intentionally high — surfacing a wrong RPT on a public analysis page is reputationally expensive. |
| `UNIQUE(ticker, fiscal_year, related_party_name, txn_type, amount_inr)` | Dedup key for re-extraction idempotency. |

## Red-flag rule set

| Code | Rule | Threshold | Rationale |
| --- | --- | --- | --- |
| `RPT_LOAN_TO_PROMOTER` | Sum of `loan_given` to promoter / director / KMP / relative-KMP entities | > 5% of net worth | SEBI LODR Reg 23(1)(a) materiality. |
| `RPT_ROYALTY_HEAVY` | Sum of `royalty` to related parties | > 2% of revenue | Historical heuristic — royalty is a favoured value-extraction vehicle; 2% is the line where governance-watchers start asking questions. |
| `RPT_ASSET_SALE_BELOW_BOOK` | Any `asset_sale` priced < 80% of book value | per row | 20% discount-to-book floor. Below that, there should be a documented bid process. |
| `RPT_VAGUE_CONSULTANCY` | `rendering_service` / `receiving_service` rows whose description matches "consult" / "advisory" / "professional fee" but does NOT disclose scope or rate | >= 1 row | Recurring opaque consultancy fees are a classic value leak. |
| `RPT_BALANCE_SPIKE` | Total RPT amount > 50% above prior-year total | YoY | Sudden balance jumps without a corporate-action explanation are worth a flag. |

Thresholds are intentionally conservative. Once we have the top-500 backfill (Phase-4), we'll calibrate against base rates.

## LLM extraction architecture

```
AR PDF (BSE/NSE)
   |
   v
section identifier  --regex on per-page text-->  (page_start, page_end)
   |                       (PyMuPDF / pdfplumber)
   v
LLM extractor      --structured JSON output-->   List[RPTRow]
   |               (Groq Llama-3.1-70B  OR
   |                Gemini Pro 1.5+ multimodal)
   v
confidence gate    --0.85 cutoff-->
   |   >=0.85: auto-publish
   |   <0.85:  human-review queue
   v
UPSERT into related_party_transactions
```

The exact prompts live in `backend/services/related_party_service.py`
as `LLM_SYSTEM_PROMPT` and `LLM_USER_PROMPT_TEMPLATE` — they are the
canonical reference for Phase-2 work.

## Open implementation questions

1. **Section-finding regex aggression.** AOC-2 is sometimes a standalone schedule, sometimes embedded inside "Notes to Financial Statements". How aggressive should the regex be? Too tight = missed disclosures; too loose = LLM extraction cost balloons. Probably needs a two-pass approach — strict first, fallback to "any page mentioning 'related part'" if zero matches.
2. **LLM cost/throughput at scale.** ~3000 tickers × 2 reports/year × ~20 extracted pages each = ~120k extractions/year. Groq is cheap and fast (Llama-3.1-70B at ~$0.59/M tokens) but text-only and less accurate on tables. Gemini Pro 1.5 is multimodal (handles scanned-PDF tables) but ~10× the cost. Tentative plan: Groq for first pass; queue Gemini for the rows the confidence gate rejected.
3. **Refresh cadence.** Once per year post-AGM-results-filing? Or rolling, whenever a new AR drops? I lean towards rolling — top-100 tickers checked weekly, top-500 monthly, rest on AGM-month trigger.
4. **Frontend integration.** Two options: (a) analysis-page sidebar with "5 red flags found" count → expandable list; (b) separate `/governance/{ticker}` page. (a) is cheaper and surfaces governance to every analysis-page visitor; (b) lets the data breathe. I'd ship (a) first, promote to (b) once we have enough rule coverage to fill a page.
5. **Confidence thresholds.** Auto-publish if LLM confidence > 0.85, else queue for human review. Is 0.85 the right line? It's a placeholder until we calibrate against a hand-labelled set on the top-50 ARs.

## Frontend integration sketch

- Pulse axis (existing) + new **Governance** red-flag chip on the analysis hero ("3 governance flags").
- Click the chip → drawer listing each `Flag.title` with severity colour + supporting rows (linked back to `source_pdf_url` + `source_page`).
- Long-tail detail goes on `/governance/{ticker}` (Phase 3).

## Follow-up phases

| Phase | Scope | Status |
| --- | --- | --- |
| 0 — Scaffolding | Schema, service, ingest stub, fixture, tests, docs | **DONE (this PR)** |
| 1 — Real PDF parser | PyMuPDF/pdfplumber section finder + page-range bounds | next |
| 2 — LLM integration | Groq first pass, Gemini fallback, JSON-schema validation, confidence gate | after Phase 1 |
| 3 — Red-flag UI | Hero chip + analysis-page drawer | parallel with Phase 2 |
| 4 — Backfill | Top-500 tickers, last 5 fiscal years, human-review queue | post Phase 2 |
| 5 — Alerts | Notify watchlist users when a new RPT disclosure (BSE corporate-filings feed) lands | last |
