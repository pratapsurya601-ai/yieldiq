# Formula Audit 2026-04-19

## margin_of_safety

Computations (want: exactly 1):
  - backend/routers/portfolio.py:159  _do_import()  [mos]
  - backend/routers/screener.py:71  _query_stocks_from_db()  [mos]   ⚠ DUPLICATE
  - backend/services/analysis_service.py:1589  _get_full_analysis_inner()  [mos_pct]   ⚠ DUPLICATE
  - backend/services/analysis_service.py:1791  _get_full_analysis_inner()  [mos_pct]   ⚠ DUPLICATE
  - backend/services/analysis_service.py:2298  _get_full_analysis_inner()  [mos_pct]   ⚠ DUPLICATE
  - backend/services/analysis_service.py:2300  _get_full_analysis_inner()  [mos_pct]   ⚠ DUPLICATE
  - backend/services/financial_valuation_service.py:285  _compute_pbv_path()  [mos_pct]   ⚠ DUPLICATE
  - backend/services/financial_valuation_service.py:325  _compute_pe_path()  [mos_pct]   ⚠ DUPLICATE
  - backend/services/hex_history_service.py:465  _compute_value_axis()  [mos_pct]   ⚠ DUPLICATE
  - backend/services/hex_history_service.py:615  _compute_snapshot()  [mos_pct]   ⚠ DUPLICATE
  - backend/services/hex_service.py:367  _axis_value_general()  [mos_pct]   ⚠ DUPLICATE
  - backend/services/portfolio_service.py:218  get_holdings_with_live_data()  [mos_pct]   ⚠ DUPLICATE
  - backend/services/prism_service.py:556  _build_prism()  [mos_pct]   ⚠ DUPLICATE

Passthroughs (count: 50):
  - backend/models/requests.py:23  AddHoldingRequest()  [mos_pct]
  - backend/models/responses.py:27  ValuationOutput()  [margin_of_safety]
  - backend/models/responses.py:154  ReverseDCFScenario()  [mos]
  - backend/models/responses.py:182  ScenarioCase()  [mos_pct]
  - backend/models/responses.py:233  ScreenerStock()  [margin_of_safety]
  - backend/models/responses.py:268  HoldingResponse()  [mos_pct]
  - backend/routers/analysis.py:246  get_analysis()  [margin_of_safety]
  - backend/routers/analysis.py:638  _load_screener_csv()  [margin_of_safety]
  - backend/routers/analysis.py:659  _load_cached_analyses()  [margin_of_safety]
  - backend/routers/analysis.py:737  get_yieldiq50()  [margin_of_safety]
  - backend/routers/analysis.py:757  get_yieldiq50()  [margin_of_safety]
  - backend/routers/analysis.py:790  get_top_pick()  [mos]
  - backend/routers/portfolio.py:43  get_holdings()  [mos_pct]
  - backend/routers/portfolio.py:79  add_holding()  [mos_pct]
  - backend/routers/portfolio.py:168  _do_import()  [mos]
  - backend/routers/portfolio.py:176  _do_import()  [mos]
  - backend/routers/portfolio.py:179  _do_import()  [mos_pct]
  - backend/routers/public.py:76  _extract_analysis_summary()  [mos]
  - backend/routers/public.py:606  _flatten()  [mos]
  - backend/routers/screener.py:73  _query_stocks_from_db()  [margin_of_safety]
  - backend/routers/screener.py:155  _query_preset_from_db()  [mos]
  - backend/routers/screener.py:183  _query_preset_from_db()  [mos]
  - backend/routers/screener.py:207  _query_preset_from_db()  [margin_of_safety]
  - backend/services/analysis_service.py:1207  _get_full_analysis_inner()  [margin_of_safety]
  - backend/services/analysis_service.py:1248  _get_full_analysis_inner()  [margin_of_safety]
  - backend/services/analysis_service.py:1798  _get_full_analysis_inner()  [mos_pct]
  - backend/services/analysis_service.py:1819  _sc()  [mos_pct]
  - backend/services/analysis_service.py:1983  _get_full_analysis_inner()  [mos]
  - backend/services/analysis_service.py:2210  _get_full_analysis_inner()  [margin_of_safety]
  - backend/services/analysis_service.py:2299  _get_full_analysis_inner()  [mos_pct]
  - backend/services/financial_valuation_service.py:293  _compute_pbv_path()  [margin_of_safety]
  - backend/services/financial_valuation_service.py:331  _compute_pe_path()  [margin_of_safety]
  - backend/services/hex_service.py:361  _axis_value_general()  [mos_pct]
  - backend/services/hex_service.py:369  _axis_value_general()  [mos_pct]
  - backend/services/hex_service.py:408  _axis_value_bank()  [mos_pct]
  - backend/services/peers_service.py:195  _cached_score()  [mos_pct]
  - backend/services/peers_service.py:262  _build_row()  [mos_pct]
  - backend/services/portfolio_service.py:212  get_holdings_with_live_data()  [mos_pct]
  - backend/services/prism_narration_service.py:125  _groq_narration()  [mos]
  - backend/services/prism_narration_service.py:289  _templated_narration()  [mos]
  - backend/services/prism_service.py:186  _score_history_12m()  [mos]
  - backend/services/prism_service.py:284  _compute_sector_rank_table()  [mos]
  - backend/services/prism_service.py:545  _build_prism()  [mos_pct]
  - backend/services/prism_service.py:558  _build_prism()  [mos_pct]
  - backend/services/prism_service.py:569  _build_prism()  [mos_pct]
  - backend/services/prism_service.py:571  _build_prism()  [mos_pct]
  - backend/services/prism_service.py:619  _build_prism()  [mos_pct]
  - backend/services/retention_service.py:164  _d7_html()  [mos]
  - backend/services/retention_service.py:272  _get_top_undervalued()  [mos]
  - backend/validators/consistency.py:33  check_consistency()  [mos]

STATUS: ⚠ 13 computations found — violates single-source rule

## fair_value

Computations (want: exactly 1):
  - (none found)

Passthroughs (count: 29):
  - backend/models/responses.py:25  ValuationOutput()  [fair_value]
  - backend/models/responses.py:231  ScreenerStock()  [fair_value]
  - backend/routers/analysis.py:245  get_analysis()  [fair_value]
  - backend/routers/public.py:76  _extract_analysis_summary()  [fair_value]
  - backend/routers/public.py:606  _flatten()  [fair_value]
  - backend/services/analysis_service.py:1207  _get_full_analysis_inner()  [fair_value]
  - backend/services/analysis_service.py:1248  _get_full_analysis_inner()  [fair_value]
  - backend/services/analysis_service.py:1983  _get_full_analysis_inner()  [fv]
  - backend/services/analysis_service.py:2210  _get_full_analysis_inner()  [fair_value]
  - backend/services/financial_valuation_service.py:293  _compute_pbv_path()  [fair_value]
  - backend/services/financial_valuation_service.py:331  _compute_pe_path()  [fair_value]
  - backend/services/hex_history_service.py:476  _fetch_current_fv_and_revenue()  [fv]
  - backend/services/hex_history_service.py:495  _fetch_current_fv_and_revenue()  [fv]
  - backend/services/hex_history_service.py:497  _fetch_current_fv_and_revenue()  [fv]
  - backend/services/hex_service.py:359  _axis_value_general()  [fv]
  - backend/services/peers_service.py:195  _cached_score()  [fair_value]
  - backend/services/peers_service.py:262  _build_row()  [fair_value]
  - backend/services/portfolio_service.py:209  get_holdings_with_live_data()  [fair_value]
  - backend/services/portfolio_service.py:214  get_holdings_with_live_data()  [fair_value]
  - backend/services/prism_narration_service.py:127  _groq_narration()  [fv]
  - backend/services/prism_narration_service.py:291  _templated_narration()  [fv]
  - backend/services/prism_service.py:544  _build_prism()  [fair_value]
  - backend/services/prism_service.py:565  _build_prism()  [fair_value]
  - backend/services/prism_service.py:567  _build_prism()  [fair_value]
  - backend/services/prism_service.py:619  _build_prism()  [fair_value]
  - backend/services/retention_service.py:165  _d7_html()  [fv]
  - backend/services/validators.py:98  validate_analysis()  [fv]
  - backend/services/validators.py:141  validate_analysis()  [fv]
  - backend/validators/consistency.py:31  check_consistency()  [fv]

STATUS: ℹ no computation found (passthrough-only — verify upstream)

## bear_case

Computations (want: exactly 1):
  - (none found)

Passthroughs (count: 5):
  - backend/models/responses.py:29  ValuationOutput()  [bear_case]
  - backend/routers/public.py:76  _extract_analysis_summary()  [bear_case]
  - backend/services/analysis_service.py:2210  _get_full_analysis_inner()  [bear_case]
  - backend/services/financial_valuation_service.py:293  _compute_pbv_path()  [bear_case]
  - backend/services/financial_valuation_service.py:331  _compute_pe_path()  [bear_case]

STATUS: ℹ no computation found (passthrough-only — verify upstream)

## base_case

Computations (want: exactly 1):
  - (none found)

Passthroughs (count: 5):
  - backend/models/responses.py:30  ValuationOutput()  [base_case]
  - backend/routers/public.py:76  _extract_analysis_summary()  [base_case]
  - backend/services/analysis_service.py:2210  _get_full_analysis_inner()  [base_case]
  - backend/services/financial_valuation_service.py:293  _compute_pbv_path()  [base_case]
  - backend/services/financial_valuation_service.py:331  _compute_pe_path()  [base_case]

STATUS: ℹ no computation found (passthrough-only — verify upstream)

## bull_case

Computations (want: exactly 1):
  - (none found)

Passthroughs (count: 5):
  - backend/models/responses.py:31  ValuationOutput()  [bull_case]
  - backend/routers/public.py:76  _extract_analysis_summary()  [bull_case]
  - backend/services/analysis_service.py:2210  _get_full_analysis_inner()  [bull_case]
  - backend/services/financial_valuation_service.py:293  _compute_pbv_path()  [bull_case]
  - backend/services/financial_valuation_service.py:331  _compute_pe_path()  [bull_case]

STATUS: ℹ no computation found (passthrough-only — verify upstream)

## roce

Computations (want: exactly 1):
  - backend/services/hex_history_service.py:308  _compute_quality_axis()  [roce]

Passthroughs (count: 5):
  - backend/models/responses.py:69  QualityOutput()  [roce]
  - backend/routers/public.py:76  _extract_analysis_summary()  [roce]
  - backend/services/analysis_service.py:2247  _get_full_analysis_inner()  [roce]
  - backend/services/hex_service.py:466  _axis_quality()  [roce]
  - backend/validators/consistency.py:37  check_consistency()  [roce]

STATUS: ✓ single source

## ev_ebitda

Computations (want: exactly 1):
  - (none found)

Passthroughs (count: 10):
  - backend/models/responses.py:144  InsightCards()  [ev_ebitda]
  - backend/routers/public.py:76  _extract_analysis_summary()  [ev_ebitda]
  - backend/routers/public.py:601  _flatten()  [ev_ebitda]
  - backend/routers/public.py:603  _flatten()  [ev_ebitda]
  - backend/routers/public.py:605  _flatten()  [ev_ebitda]
  - backend/routers/public.py:606  _flatten()  [ev_ebitda]
  - backend/services/analysis_service.py:2279  _get_full_analysis_inner()  [ev_ebitda]
  - backend/services/local_data_service.py:376  assemble_local()  [ev_to_ebitda]
  - backend/services/peers_service.py:225  _build_row()  [ev_ebitda]
  - backend/services/peers_service.py:262  _build_row()  [ev_ebitda]

STATUS: ℹ no computation found (passthrough-only — verify upstream)

## revenue_cagr_3y

Computations (want: exactly 1):
  - backend/services/financials_service.py:408  _compute_summary()  [revenue_cagr_3y]

Passthroughs (count: 6):
  - backend/models/responses.py:77  QualityOutput()  [revenue_cagr_3y]
  - backend/routers/public.py:76  _extract_analysis_summary()  [revenue_cagr_3y]
  - backend/services/analysis_service.py:2247  _get_full_analysis_inner()  [revenue_cagr_3y]
  - backend/services/financials_service.py:399  _compute_summary()  [revenue_cagr_3y]
  - backend/services/financials_service.py:412  _compute_summary()  [revenue_cagr_3y]
  - backend/services/financials_service.py:421  _compute_summary()  [revenue_cagr_3y]

STATUS: ✓ single source

## revenue_cagr_5y

Computations (want: exactly 1):
  - (none found)

Passthroughs (count: 3):
  - backend/models/responses.py:78  QualityOutput()  [revenue_cagr_5y]
  - backend/routers/public.py:76  _extract_analysis_summary()  [revenue_cagr_5y]
  - backend/services/analysis_service.py:2247  _get_full_analysis_inner()  [revenue_cagr_5y]

STATUS: ℹ no computation found (passthrough-only — verify upstream)

## roe

Computations (want: exactly 1):
  - backend/routers/public.py:974  get_dupont_analysis()  [roe]
  - backend/services/analysis_service.py:229  _compute_roe_fallback()  [roe]   ⚠ DUPLICATE
  - backend/services/analysis_service.py:2247  _get_full_analysis_inner()  [roe]   ⚠ DUPLICATE

Passthroughs (count: 13):
  - backend/models/responses.py:66  QualityOutput()  [roe]
  - backend/routers/public.py:76  _extract_analysis_summary()  [roe]
  - backend/routers/public.py:606  _flatten()  [roe]
  - backend/services/analysis_service.py:675  _add_flags()  [roe]
  - backend/services/financial_valuation_service.py:377  compute_financial_fair_value()  [roe]
  - backend/services/financials_service.py:126  _Row()  [roe]
  - backend/services/hex_service.py:467  _axis_quality()  [roe]
  - backend/services/local_data_service.py:166  assemble_local()  [roe]
  - backend/services/local_data_service.py:204  assemble_local()  [roe]
  - backend/services/local_data_service.py:376  assemble_local()  [roe]
  - backend/services/peers_service.py:237  _build_row()  [roe]
  - backend/services/validators.py:126  validate_analysis()  [roe]
  - backend/validators/consistency.py:38  check_consistency()  [roe]

STATUS: ⚠ 3 computations found — violates single-source rule

## debt_to_equity

Computations (want: exactly 1):
  - backend/services/financials_service.py:239  _fetch_from_db()  [debt_to_equity]

Passthroughs (count: 10):
  - backend/models/responses.py:67  QualityOutput()  [de_ratio]
  - backend/routers/public.py:76  _extract_analysis_summary()  [de_ratio]
  - backend/routers/public.py:606  _flatten()  [de_ratio]
  - backend/services/analysis_service.py:2247  _get_full_analysis_inner()  [de_ratio]
  - backend/services/financials_service.py:127  _Row()  [debt_to_equity]
  - backend/services/financials_service.py:361  _build_year()  [debt_to_equity]
  - backend/services/local_data_service.py:167  assemble_local()  [de_ratio]
  - backend/services/local_data_service.py:205  assemble_local()  [de_ratio]
  - backend/services/local_data_service.py:376  assemble_local()  [de_ratio]
  - backend/services/peers_service.py:262  _build_row()  [debt_to_equity]

STATUS: ✓ single source

---

SUMMARY:
FAIL  — 2 keys violate single-source rule:
  - margin_of_safety (13 computations)
  - roe (3 computations)
