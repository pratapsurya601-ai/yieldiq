"""
Streamlit UI Integration for YieldIQ API Optimizer
Adds cost monitoring, model routing UI, and batch processing dashboard
Drop this into your dashboard/app.py as a new section
"""

import streamlit as st
import pandas as pd
import json
from datetime import datetime
from api_optimizer import YieldIQOptimizer

# ============================================================
# Initialize optimizer in Streamlit session state
# ============================================================

if "optimizer" not in st.session_state:
    st.session_state.optimizer = YieldIQOptimizer()

optimizer = st.session_state.optimizer


# ============================================================
# SECTION 1: Cost Monitoring Dashboard
# ============================================================

def show_cost_monitor():
    """Display real-time API cost monitoring"""
    st.subheader("💰 API Cost Monitor")
    
    summary = optimizer.get_cost_summary()
    
    if "message" in summary:
        st.info(summary["message"])
        return
    
    # Key metrics in columns
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Cost",
            f"${summary['total_cost']:.4f}",
            f"{summary['total_calls']} calls",
            delta_color="inverse"  # Lower is better
        )
    
    with col2:
        st.metric(
            "Avg Cost/Call",
            f"${summary['avg_cost_per_call']:.6f}",
            "Sonnet base"
        )
    
    with col3:
        st.metric(
            "Cache Hits",
            f"{summary['cache_hits']}",
            f"{summary['cache_writes']} writes"
        )
    
    with col4:
        st.metric(
            "Cache Savings",
            f"${summary['estimated_cache_savings']:.4f}",
            "90% on reads"
        )
    
    # Detailed usage breakdown
    st.markdown("---")
    st.caption("📊 Detailed Usage Breakdown")
    
    if optimizer.usage_log:
        df = pd.DataFrame(optimizer.usage_log)
        
        # Aggregate by operation
        agg_ops = df.groupby("operation").agg({
            "total_cost": "sum",
            "input_tokens": "sum",
            "output_tokens": "sum",
            "cache_read_tokens": "sum"
        }).round(4)
        
        st.dataframe(agg_ops, use_container_width=True)
        
        # Export button
        csv = df.to_csv(index=False)
        st.download_button(
            label="📥 Export Usage Log (CSV)",
            data=csv,
            file_name=f"yieldiq_api_usage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No API calls logged yet")


# ============================================================
# SECTION 2: Stock Analysis with Model Routing
# ============================================================

def show_analysis_router():
    """Interactive stock analysis with automatic model routing"""
    st.subheader("🔍 Stock Analysis (Auto Model Routing)")
    
    col1, col2 = st.columns(2)
    
    with col1:
        ticker = st.text_input("Ticker Symbol", value="AAPL", key="analysis_ticker")
    
    with col2:
        task_type = st.selectbox(
            "Analysis Type",
            [
                "simple_summary",
                "watchlist_alert",
                "portfolio_update",
                "sector_comparison",
                "multi_stock_analysis",
                "deep_valuation"
            ],
            key="analysis_type"
        )
    
    # Context inputs based on task type
    st.caption("📋 Analysis Context")
    
    if task_type == "simple_summary":
        col1, col2 = st.columns(2)
        with col1:
            fair_value = st.number_input("Fair Value", value=250.0, step=1.0)
        with col2:
            price = st.number_input("Current Price", value=228.0, step=1.0)
        context = {"fair_value": fair_value, "price": price}
    
    elif task_type == "watchlist_alert":
        col1, col2 = st.columns(2)
        with col1:
            mos = st.slider("Margin of Safety (%)", -50.0, 50.0, 15.0) / 100
        context = {"mos": mos}
    
    elif task_type == "portfolio_update":
        col1, col2 = st.columns(2)
        with col1:
            portfolio_name = st.text_input("Portfolio Name", value="Main")
        with col2:
            signal = st.selectbox("New Signal", ["Buy", "Hold", "Sell"])
        context = {"portfolio_name": portfolio_name, "signal": signal}
    
    else:
        context = {}
        st.info(f"Analysis type: {task_type}")
    
    # Analyze button
    if st.button("🚀 Analyze & Route to Optimal Model", key="analyze_btn"):
        with st.spinner("Routing to optimal model..."):
            result = optimizer.route_analysis(ticker, task_type, context)
            
            col1, col2 = st.columns([1, 3])
            with col1:
                st.success(f"Model: {result['model_used'].split('-')[1].upper()}")
            with col2:
                st.info(f"This task routed to {result['model_used']} for optimal cost/quality")
            
            st.text_area("Response", result['response'], height=200, disabled=True)


# ============================================================
# SECTION 3: Batch Processing Dashboard
# ============================================================

def show_batch_processor():
    """Queue stocks for batch processing (50% discount)"""
    st.subheader("⚡ Batch Processor (50% Discount)")
    
    st.markdown("""
    **Why batch?** Process multiple stocks at once with 50% off token costs.
    Perfect for overnight sector updates or watchlist processing.
    """)
    
    # Upload CSV template or input manually
    tab1, tab2 = st.tabs(["📤 Upload CSV", "✍️ Input Manually"])
    
    with tab1:
        st.caption("Upload a CSV with columns: ticker, revenue_ttm, ebit_margin, fcf_ltm, current_price, wacc")
        uploaded_file = st.file_uploader("Choose CSV file", type=['csv'], key="batch_csv")
        
        if uploaded_file:
            df = pd.read_csv(uploaded_file)
            st.dataframe(df.head(), use_container_width=True)
            
            if st.button("🎯 Submit Batch", key="submit_batch"):
                stocks = []
                for _, row in df.iterrows():
                    stocks.append({
                        "ticker": row['ticker'],
                        "company_data": {
                            "revenue_ttm": row['revenue_ttm'],
                            "ebit_margin": row['ebit_margin'],
                            "fcf_ltm": row['fcf_ltm'],
                            "current_price": row['current_price'],
                            "shares": row.get('shares', 1),
                            "wacc": row['wacc']
                        }
                    })
                
                batch_id = optimizer.create_batch_analysis(stocks)
                
                st.success(f"✓ Batch submitted: {batch_id}")
                st.info("💡 Results will be ready in ~24 hours at 50% of regular API cost")
                st.code(batch_id, language="text")
    
    with tab2:
        st.caption("Manually add stocks for batch processing")
        
        num_stocks = st.number_input("Number of stocks", min_value=1, max_value=100, value=3)
        
        stocks = []
        cols = st.columns(3)
        
        for i in range(num_stocks):
            with st.expander(f"Stock {i+1}"):
                ticker = st.text_input(f"Ticker {i+1}", value=f"STOCK{i+1}", key=f"ticker_{i}")
                revenue = st.number_input(f"Revenue TTM {i+1}", value=100000.0, key=f"rev_{i}")
                margin = st.slider(f"EBIT Margin {i+1}", 0.0, 1.0, 0.25, key=f"margin_{i}") / 100
                fcf = st.number_input(f"FCF {i+1}", value=25000.0, key=f"fcf_{i}")
                price = st.number_input(f"Current Price {i+1}", value=100.0, key=f"price_{i}")
                wacc = st.slider(f"WACC {i+1}", 0.0, 0.15, 0.08, key=f"wacc_{i}") / 100
                
                stocks.append({
                    "ticker": ticker,
                    "company_data": {
                        "revenue_ttm": revenue,
                        "ebit_margin": margin,
                        "fcf_ltm": fcf,
                        "current_price": price,
                        "shares": 100,
                        "wacc": wacc
                    }
                })
        
        if st.button("🎯 Submit Batch (Manual)", key="submit_batch_manual"):
            batch_id = optimizer.create_batch_analysis(stocks)
            st.success(f"✓ Batch submitted: {batch_id}")
            st.info("💡 Results ready in ~24 hours at 50% off")
    
    # Retrieve batch results
    st.markdown("---")
    st.caption("📋 Check Batch Results")
    
    batch_id_input = st.text_input("Enter Batch ID to check status", key="batch_id_check")
    
    if st.button("Check Status", key="check_status_btn"):
        try:
            results = optimizer.retrieve_batch_results(batch_id_input)
            
            if isinstance(results, dict) and "status" in results:
                st.warning(f"Status: {results['status']}")
                st.info(f"Requests: {results['request_counts']}")
            else:
                st.success(f"✓ Batch complete! {len(results)} results")
                st.json(results[:3])  # Show first 3
        except Exception as e:
            st.error(f"Error retrieving batch: {str(e)}")


# ============================================================
# SECTION 4: Caching Performance
# ============================================================

def show_caching_panel():
    """Display caching effectiveness"""
    st.subheader("⚡ Prompt Caching Performance")
    
    summary = optimizer.get_cost_summary()
    
    if "message" in summary or summary["cache_hits"] == 0:
        st.info("⏳ Caching stats will appear as you use cached analyses")
        return
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Cache Hits", summary["cache_hits"])
    
    with col2:
        st.metric("Cache Writes", summary["cache_writes"])
    
    with col3:
        if summary["cache_hits"] > 0:
            hit_rate = (summary["cache_hits"] / (summary["cache_hits"] + summary["cache_writes"])) * 100
            st.metric("Hit Rate", f"{hit_rate:.1f}%")
    
    st.markdown("---")
    st.caption("💡 How Caching Works")
    st.markdown("""
    - **First call:** System prompt cached at regular rate (25% premium)
    - **Subsequent calls:** Same prompt read at 10% of input cost = 90% savings
    - **Session duration:** Cache persists for 5 minutes of activity
    - **Best for:** Repeated stock analyses, sector dashboards, batch updates
    """)


# ============================================================
# MAIN DASHBOARD LAYOUT
# ============================================================

def show_api_optimizer_dashboard():
    """Main dashboard combining all optimization features"""
    
    st.set_page_config(page_title="YieldIQ API Optimizer", layout="wide")
    
    st.markdown("# 💡 YieldIQ API Cost Optimizer")
    st.markdown("**Reduce Claude API costs by 70-90% with intelligent routing, caching, and batch processing**")
    
    # Main tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "💰 Cost Monitor",
        "🔍 Analyze (Smart Routing)",
        "⚡ Batch Processor",
        "📊 Caching Stats",
        "📚 Documentation"
    ])
    
    with tab1:
        show_cost_monitor()
    
    with tab2:
        show_analysis_router()
    
    with tab3:
        show_batch_processor()
    
    with tab4:
        show_caching_panel()
    
    with tab5:
        st.markdown("""
        ## API Cost Optimization Strategies
        
        ### 1. **Prompt Caching (90% savings)**
        - System prompt cached for 5 minutes
        - Subsequent calls read at 10% of input cost
        - Ideal for repeated stock analyses
        
        ### 2. **Model Routing (3-5x savings)**
        - Haiku for simple tasks (summarization, alerts)
        - Sonnet for complex analysis
        - Automatically selects based on complexity
        
        ### 3. **Batch API (50% savings)**
        - Queue multiple stocks for processing
        - Results ready within 24 hours
        - Perfect for overnight updates
        
        ### 4. **Output Optimization (5x ROI)**
        - Strict token limits on responses
        - JSON format instead of prose
        - Output tokens cost 5x input, so this saves big
        
        ### 5. **Usage Monitoring**
        - Real-time cost tracking per operation
        - CSV export for analysis
        - Identify optimization opportunities
        
        ### Cost Breakdown (Sonnet 4.5)
        | Factor | Cost |
        |--------|------|
        | Input (base) | $3/MTok |
        | Output (base) | $15/MTok |
        | Cached input (read) | $0.30/MTok |
        | Batch discount | -50% |
        
        ### Implementation Tips
        1. Always use caching for system prompts
        2. Route simple analyses to Haiku
        3. Batch process overnight jobs
        4. Set max_tokens to 300-400 max
        5. Monitor usage daily via CSV export
        """)


# ============================================================
# HELPER: Add to existing app.py
# ============================================================

def integrate_into_app():
    """
    Add this to your existing dashboard/app.py:
    
    ```python
    from streamlit_api_optimizer import show_api_optimizer_dashboard
    
    # In your main app
    if st.sidebar.checkbox("Show API Cost Optimizer"):
        show_api_optimizer_dashboard()
    ```
    """
    pass


if __name__ == "__main__":
    show_api_optimizer_dashboard()
