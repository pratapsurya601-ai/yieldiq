# dashboard/tabs/search_tab.py
# Search tab — delegates to stock_analysis
from __future__ import annotations


def render_search():
    """Render the Search/Analysis tab — main stock analysis."""
    from tabs.stock_analysis import render as _render_stock_analysis
    _render_stock_analysis()
