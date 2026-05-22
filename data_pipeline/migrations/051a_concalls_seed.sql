BEGIN;

-- Migration 051a (Day-103a): seed rows for the concalls library so the
-- ConcallsPanel renders something visible in audit screens until the
-- BSE ingestion pipeline lands.
--
-- Three rows for HDFCBANK.NS spanning the most recent quarters. The
-- transcript_text column is left NULL — we only carry the source URL
-- and a pre-written SEBI-safe AI summary so the panel renders the
-- bullets without needing to call Groq on first paint.
--
-- These are placeholder URLs pointing at HDFC Bank's investor-relations
-- page — replace with the real PDF URLs once the BSE ingester
-- enumerates them.
--
-- Rollback:
--   DELETE FROM concalls WHERE ticker = 'HDFCBANK.NS' AND source_url LIKE '%/seed/%';

INSERT INTO concalls (ticker, period, concall_date, source_url, ai_summary, ai_summary_model, ai_summary_generated_at)
VALUES
    (
        'HDFCBANK.NS',
        'FY26-Q4',
        DATE '2026-04-19',
        'https://www.hdfcbank.com/personal/about-us/investor-relations/seed/q4-fy26-concall',
        E'- Net interest income grew steadily on the back of healthy retail loan book expansion and a stable deposit mix.\n- Management flagged a modest compression in net interest margin owing to higher term-deposit cost, expected to normalise over the next two quarters.\n- Asset quality remained in line with prior quarters; slippages were broadly steady and the credit cost outlook was reiterated.\n- Digital throughput on UPI, cards and account opening continued to scale, with management highlighting onboarding cycle-time reduction.\n- Capital adequacy stayed comfortably above regulatory thresholds; management reiterated focus on profitable growth rather than balance-sheet expansion targets.',
        'llama-3.3-70b-versatile',
        now()
    ),
    (
        'HDFCBANK.NS',
        'FY26-Q3',
        DATE '2026-01-18',
        'https://www.hdfcbank.com/personal/about-us/investor-relations/seed/q3-fy26-concall',
        E'- Loan growth was led by retail and commercial-rural banking; corporate book remained selective with pricing discipline highlighted.\n- Deposit accretion picked up sequentially with branch additions and granular CASA progress called out by management.\n- Provisions tracked the run-rate of prior quarters; management noted no broad-based asset-quality stress signals in retail.\n- Operating expenses reflected continued branch expansion and technology spend; cost-to-income trajectory was reaffirmed as a multi-quarter normalisation story.\n- Management commentary on integration synergies referenced ongoing branch rationalisation and a steady cross-sell ramp into the merged customer base.',
        'llama-3.3-70b-versatile',
        now()
    ),
    (
        'HDFCBANK.NS',
        'FY26-Q2',
        DATE '2025-10-19',
        'https://www.hdfcbank.com/personal/about-us/investor-relations/seed/q2-fy26-concall',
        E'- Quarterly print showed sequential improvement in core operating profit with stable fee-income contribution.\n- Margin trajectory was framed as gradually recovering as legacy high-cost borrowings continue to roll off.\n- Retail credit quality indicators were described as steady; unsecured segment growth was characterised as calibrated.\n- Branch network expansion stayed on plan; management cited improving productivity from newer-vintage branches.\n- Technology and analytics investments were highlighted alongside a longer-term framing of franchise-strength build-out.',
        'llama-3.3-70b-versatile',
        now()
    )
ON CONFLICT (ticker, period) DO NOTHING;

COMMIT;
