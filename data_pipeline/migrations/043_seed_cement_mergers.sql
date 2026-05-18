-- 043_seed_cement_mergers.sql
-- 2026-05-18 — Phase-B extension of the structural-break CAGR overlay
-- to cement sector tickers. Builds on the framework introduced by
-- 041_corporate_actions_structural.sql (structural action_types) and
-- 042_seed_structural_mergers.sql (initial bank seed rows).
--
-- Background: per docs/design/cement-dcf-fix.md, four of the top seven
-- cement tickers (SHREECEM, DALBHARAT, JKCEMENT, RAMCOCEM) are within
-- the ±30% consensus band and need no intervention. Three are broken,
-- all post-M&A integrators whose trailing CAGR window straddles two
-- entity regimes — the same shape as HDFCBANK in 042.
--
--   * ULTRACEMCO ate Kesoram Cement (FY24/25 close, ~Sep-2024) and is
--     in the process of absorbing India Cements (close ~Dec-2024 per
--     UltraTech's investor announcements). Both events depress
--     post-merger latest_fcf while inflating reported revenue.
--   * AMBUJACEM was taken over by the Adani Group in September 2022
--     (Holcim divestment). Pre-takeover history belongs to a different
--     operating regime.
--   * ACC was acquired alongside AMBUJACEM in the same Adani / Holcim
--     transaction (close September 2022).
--
-- Once these rows land, corporate_actions_service.has_structural_break
-- returns True for the affected tickers and the existing truncation
-- gate from PR #324 (with PR #328's .NS/.BO strip fix) automatically
-- shortens the CAGR window — no engine change required.
--
-- Idempotent: ON CONFLICT DO NOTHING against the natural-key index
-- uq_corporate_actions_natural_key (ticker, ex_date, action_type)
-- introduced in 025_corporate_actions_quality_rank.sql.
--
-- Dual-path convention: mirrored at
-- db/migrations/014_seed_cement_mergers.sql.
--
-- Apply with:
--   python scripts/apply_migration.py \
--       data_pipeline/migrations/043_seed_cement_mergers.sql
--
-- Post-merge ops:
--   * Operator must apply this migration via the Neon SQL editor (or
--     scripts/apply_migration.py against the production DSN).
--   * Bust cached analysis rows for ULTRACEMCO / AMBUJACEM / ACC so the
--     next request recomputes through the truncation gate.

INSERT INTO corporate_actions (
    ticker, ex_date, action_type, multiplier,
    source_url, source_doc, notes,
    data_source, data_quality_rank
) VALUES
    -- ULTRACEMCO — Kesoram Cement acquisition close. Kesoram's cement
    -- assets (Sedam + Basantnagar, ~10.75 MTPA) folded into UltraTech
    -- per the September-2024 scheme of arrangement effective date.
    -- Treated as MATERIAL_ACQUISITION (capacity lift ~7% of UltraTech's
    -- ~150 MTPA base) so the truncation gate triggers without claiming
    -- a full reverse-merger shape.
    ('ULTRACEMCO', DATE '2024-09-01', 'MATERIAL_ACQUISITION', 1.07,
     'https://www.bseindia.com/corporates/anndet_new.aspx?newsid=ultracemco-kesoram',
     'Stock-exchange filing — Kesoram cement business slump-sale / scheme of arrangement close',
     'Kesoram Cement (Sedam + Basantnagar, ~10.75 MTPA) absorbed by UltraTech; integration capex compresses post-merger latest_fcf and pollutes the trailing 5y revenue CAGR window.',
     'curated', 10),

    -- ULTRACEMCO — India Cements acquisition close. India Cements
    -- (~14 MTPA) acquired in December 2024 per UltraTech's investor
    -- announcement; second material capacity addition inside a single
    -- fiscal year. Same MATERIAL_ACQUISITION classification.
    ('ULTRACEMCO', DATE '2024-12-01', 'MATERIAL_ACQUISITION', 1.09,
     'https://www.bseindia.com/corporates/anndet_new.aspx?newsid=ultracemco-indiacements',
     'Stock-exchange filing — India Cements acquisition close',
     'India Cements (~14 MTPA) absorbed by UltraTech; second material acquisition in FY25 — combined with Kesoram, lifts installed capacity by ~16% and re-anchors revenue base.',
     'curated', 10),

    -- AMBUJACEM — Adani / Holcim transaction close (September 2022).
    -- Operationally a change-of-control of the listed entity rather
    -- than a legal merger, but the regime shift (governance, capex
    -- strategy, leverage profile) is the same scale as a reverse
    -- merger and the trailing CAGR window must be truncated to the
    -- post-Adani years only.
    ('AMBUJACEM', DATE '2022-09-01', 'REVERSE_MERGER', 1.00,
     'https://www.bseindia.com/corporates/anndet_new.aspx?newsid=ambujacem-adani',
     'Stock-exchange filing — Adani Group acquires Holcim stake; change of control of Ambuja Cements',
     'Adani Group takeover of Ambuja Cements (Holcim divestment); pre-2022 history belongs to a different operating regime. Bundled with ACC under the same transaction.',
     'curated', 10),

    -- ACC — same Adani / Holcim transaction. Holcim sold its stake
    -- in both Ambuja and ACC together; both listed entities changed
    -- control on the same effective date. Seeded separately because
    -- ACC's standalone financials and CAGR computation are independent
    -- of AMBUJA's.
    ('ACC', DATE '2022-09-01', 'REVERSE_MERGER', 1.00,
     'https://www.bseindia.com/corporates/anndet_new.aspx?newsid=acc-adani',
     'Stock-exchange filing — Adani Group acquires Holcim stake; change of control of ACC',
     'Adani Group takeover of ACC (Holcim divestment); same transaction as AMBUJACEM. Pre-2022 ACC history reflects Holcim-era operating regime.',
     'curated', 10)
ON CONFLICT (ticker, ex_date, action_type) DO NOTHING;
