# dashboard/ui/components/analysis_loader.py
# ═══════════════════════════════════════════════════════════════
# Replaces generic spinners with meaningful loading copy
# that makes the model feel thorough, not instant and cheap.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st
import time

LOADING_STEPS = [
    (0.10, "Fetching financial data..."),
    (0.25, "Validating data quality..."),
    (0.40, "Running DCF model..."),
    (0.55, "Checking 9 quality signals..."),
    (0.70, "Running 1,000 Monte Carlo scenarios..."),
    (0.85, "Calculating YieldIQ Score..."),
    (0.95, "Preparing your analysis..."),
    (1.00, "Analysis complete"),
]


def run_with_loader(analysis_func, *args, **kwargs):
    """
    Wraps an analysis function with the sequential loading display.
    Shows each step with a progress bar advancing through LOADING_STEPS.

    Usage:
        result = run_with_loader(get_full_analysis, ticker)
    """
    progress_bar = st.progress(0)
    status_text = st.empty()

    # Show first few steps immediately (they're fast)
    for progress, message in LOADING_STEPS[:-2]:
        status_text.html(
            f'<div style="font-size:13px;color:#64748B;font-weight:500;'
            f'padding:4px 0;">{message}</div>'
        )
        progress_bar.progress(progress)
        time.sleep(0.15)

    # Run the actual analysis
    result = analysis_func(*args, **kwargs)

    # Complete the progress
    for progress, message in LOADING_STEPS[-2:]:
        status_text.html(
            f'<div style="font-size:13px;color:#185FA5;font-weight:600;'
            f'padding:4px 0;">{message}</div>'
        )
        progress_bar.progress(progress)
        time.sleep(0.2)

    # Clean up loader
    time.sleep(0.3)
    progress_bar.empty()
    status_text.empty()

    return result
