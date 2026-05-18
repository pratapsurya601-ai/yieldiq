-- 014_seed_cement_mergers.sql
-- 2026-05-18 — db/ mirror of
-- data_pipeline/migrations/043_seed_cement_mergers.sql.
--
-- See that file for the canonical comments; this file exists solely
-- to keep the dual migration trees in lockstep per the convention
-- established by 010/012/025/041/042.

INSERT INTO corporate_actions (
    ticker, ex_date, action_type, multiplier,
    source_url, source_doc, notes,
    data_source, data_quality_rank
) VALUES
    ('ULTRACEMCO', DATE '2024-09-01', 'MATERIAL_ACQUISITION', 1.07,
     'https://www.bseindia.com/corporates/anndet_new.aspx?newsid=ultracemco-kesoram',
     'Stock-exchange filing — Kesoram cement business slump-sale / scheme of arrangement close',
     'Kesoram Cement (Sedam + Basantnagar, ~10.75 MTPA) absorbed by UltraTech; integration capex compresses post-merger latest_fcf and pollutes the trailing 5y revenue CAGR window.',
     'curated', 10),

    ('ULTRACEMCO', DATE '2024-12-01', 'MATERIAL_ACQUISITION', 1.09,
     'https://www.bseindia.com/corporates/anndet_new.aspx?newsid=ultracemco-indiacements',
     'Stock-exchange filing — India Cements acquisition close',
     'India Cements (~14 MTPA) absorbed by UltraTech; second material acquisition in FY25.',
     'curated', 10),

    ('AMBUJACEM', DATE '2022-09-01', 'REVERSE_MERGER', 1.00,
     'https://www.bseindia.com/corporates/anndet_new.aspx?newsid=ambujacem-adani',
     'Stock-exchange filing — Adani Group acquires Holcim stake; change of control of Ambuja Cements',
     'Adani Group takeover of Ambuja Cements (Holcim divestment); pre-2022 history belongs to a different operating regime.',
     'curated', 10),

    ('ACC', DATE '2022-09-01', 'REVERSE_MERGER', 1.00,
     'https://www.bseindia.com/corporates/anndet_new.aspx?newsid=acc-adani',
     'Stock-exchange filing — Adani Group acquires Holcim stake; change of control of ACC',
     'Adani Group takeover of ACC (Holcim divestment); same transaction as AMBUJACEM.',
     'curated', 10)
ON CONFLICT (ticker, ex_date, action_type) DO NOTHING;
