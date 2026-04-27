"""
Utility modules for YieldIQ dashboard.

Heavy-dep modules are NOT imported here so this package can be safely
imported from slim environments (e.g. the hex_history backfill
GitHub Actions runner, which has no streamlit/plotly installed).
Import them directly from their submodule:

    from utils.data_helpers import ...   # streamlit + collectors
    from utils.chart_layouts import ...  # streamlit (KL, CL, apply_koyfin, style_fig, T)
"""

from .formatting import fmt, fmts, sig_human, mos_insight, plain_kpi_label
from .scoring import compute_yieldiq_score

__all__ = [
    'fmt', 'fmts', 'sig_human', 'mos_insight', 'plain_kpi_label',
    'compute_yieldiq_score',
]
