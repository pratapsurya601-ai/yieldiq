-- Migration 063: ar_signals -- 10 extended JSONB fields for comprehensive AR panel.
--
-- WHY
-- ---
-- Migration 060 stood up ar_signals with 6 extraction sections (segment_data,
-- capex_commitments, related_party_transactions, auditor_flags,
-- contingent_liabilities, management_outlook). For the next manual-AR batch
-- (top-200 tickers via the free claude.ai web workflow, see
-- manual_ar_signals/README.md) we want a richer extraction template covering
-- risk factors, ESG, governance, workforce, customer concentration,
-- industry-specific operational KPIs, subsidiary roll-ups, dividend history,
-- capital actions, and strategic priorities.
--
-- All 10 new columns are NULLABLE JSONB so the existing 21 loaded rows stay
-- valid without backfill. The loader (scripts/load_manual_ar_signals.py)
-- treats the new keys as optional and passes NULL when the source JSON omits
-- them. No frontend surfaces these fields yet -- that's a separate follow-up
-- gated on user interest in the basic AR panel.
--
-- Forward-only, additive, no DROP. Safe to run on production with traffic.

BEGIN;

ALTER TABLE ar_signals
  ADD COLUMN IF NOT EXISTS risk_factors            JSONB,
  ADD COLUMN IF NOT EXISTS esg_metrics             JSONB,
  ADD COLUMN IF NOT EXISTS governance              JSONB,
  ADD COLUMN IF NOT EXISTS workforce_metrics       JSONB,
  ADD COLUMN IF NOT EXISTS customer_concentration  JSONB,
  ADD COLUMN IF NOT EXISTS operational_kpis        JSONB,
  ADD COLUMN IF NOT EXISTS subsidiary_summary      JSONB,
  ADD COLUMN IF NOT EXISTS dividend_history        JSONB,
  ADD COLUMN IF NOT EXISTS capital_actions         JSONB,
  ADD COLUMN IF NOT EXISTS strategic_priorities    JSONB;

COMMENT ON COLUMN ar_signals.risk_factors IS
  'Optional JSONB array of {category, description, mitigation} risk items.';
COMMENT ON COLUMN ar_signals.esg_metrics IS
  'Optional JSONB object with scope1/2/3 emissions, water, renewable %, etc.';
COMMENT ON COLUMN ar_signals.governance IS
  'Optional JSONB object with promoter pledge/shareholding, board independence, complaints, penalties.';
COMMENT ON COLUMN ar_signals.workforce_metrics IS
  'Optional JSONB object with headcount, attrition, gender ratio, training hours.';
COMMENT ON COLUMN ar_signals.customer_concentration IS
  'Optional JSONB object with top-10 customer %, geographic split, channel split.';
COMMENT ON COLUMN ar_signals.operational_kpis IS
  'Optional JSONB object with industry tag + industry-specific metrics map.';
COMMENT ON COLUMN ar_signals.subsidiary_summary IS
  'Optional JSONB array of subsidiary roll-up rows {name, country, revenue_cr, pat_cr, ...}.';
COMMENT ON COLUMN ar_signals.dividend_history IS
  'Optional JSONB array of per-FY dividend rows {fiscal_year, interim_dps_rs, final_dps_rs, ...}.';
COMMENT ON COLUMN ar_signals.capital_actions IS
  'Optional JSONB array of corporate actions {type, date, ratio_or_price, amount_cr}.';
COMMENT ON COLUMN ar_signals.strategic_priorities IS
  'Optional JSONB array of {priority, target, timeline} strategy bullets.';

COMMIT;
