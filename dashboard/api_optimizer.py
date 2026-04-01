"""
YieldIQ API Cost Optimizer
Implements: Prompt caching, Model routing, Batch API, Output optimization, Usage tracking
"""

import json
import csv
import os
from datetime import datetime
from typing import Optional, Dict, Any, List
import anthropic

class YieldIQOptimizer:
    """Central hub for all Claude API cost optimizations"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.usage_log = []
        self.cache_hits = 0
        self.cache_writes = 0
        
        # Ensure logs directory exists
        os.makedirs("api_logs", exist_ok=True)
    
    # ============================================================
    # 1. PROMPT CACHING - 90% savings on repeated context
    # ============================================================
    
    def get_dcf_system_prompt(self) -> str:
        """
        Core DCF analysis system prompt - large and reusable
        This gets cached so subsequent calls reuse it at 10% cost
        """
        return """You are an expert financial analyst specializing in DCF (Discounted Cash Flow) valuation.

CORE CONCEPTS:
- WACC (Weighted Average Cost of Capital): Discount rate reflecting risk
- Free Cash Flow (FCF): Cash available to all investors after reinvestment
- Terminal Value: Value beyond explicit forecast period
- Margin of Safety (MoS): (Fair Value - Current Price) / Fair Value * 100

DCF VALUATION FORMULA:
Fair Value = Σ(FCF_t / (1 + WACC)^t) + Terminal Value / (1 + WACC)^n

ANALYSIS FRAMEWORK:
1. Historical Analysis: Revenue, EBIT margin, FCF conversion trends
2. Growth Assumptions: Revenue growth, margin expansion (3-5 year explicit)
3. Terminal Growth: Long-term sustainable growth rate (2-3%)
4. Valuation: DCF intrinsic value with sensitivity analysis
5. Investment Thesis: Margin of Safety and key drivers

OUTPUT FORMAT (JSON):
{
  "ticker": "string",
  "fair_value": number,
  "margin_of_safety_pct": number,
  "rating": "Undervalued|Fair|Overvalued",
  "key_drivers": ["string"],
  "risks": ["string"]
}

Be concise, data-driven, and highlight key assumptions."""
    
    def analyze_stock_with_cache(self, ticker: str, company_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a stock with prompt caching enabled.
        First call writes cache (premium rate), subsequent calls read at 10% cost.
        Perfect for batch processing multiple stocks.
        """
        system_prompt = self.get_dcf_system_prompt()
        
        # Format company data concisely
        context = f"""
COMPANY DATA FOR {ticker}:
Revenue (TTM): ${company_data.get('revenue_ttm', 0):,.0f}M
EBIT Margin: {company_data.get('ebit_margin', 0):.1%}
FCF (LTM): ${company_data.get('fcf_ltm', 0):,.0f}M
Current Price: ${company_data.get('current_price', 0):.2f}
Shares Outstanding: {company_data.get('shares', 0):.1f}M
Beta: {company_data.get('beta', 0):.2f}
WACC: {company_data.get('wacc', 0):.1%}
"""
        
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,  # OPTIMIZATION: Strict output limit
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}  # Cache for 5 minutes
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze {ticker} for DCF valuation. {context}\nProvide JSON output only."
                }
            ]
        )
        
        # Track cache performance
        self._track_cache_usage(response)
        self._log_usage(response, ticker, "analyze_stock_with_cache")
        
        # Parse JSON response
        try:
            text = response.content[0].text
            # Extract JSON from response
            json_str = text[text.find('{'):text.rfind('}')+1]
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return {"error": "Failed to parse response", "raw": response.content[0].text}
    
    # ============================================================
    # 2. MODEL ROUTING - 3-5x savings for simple tasks
    # ============================================================
    
    def route_analysis(self, ticker: str, task_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route analysis to appropriate model based on complexity.
        Haiku for simple tasks (3x cheaper), Sonnet for complex analysis.
        """
        complexity_score = self._estimate_complexity(task_type, context)
        
        if complexity_score <= 3:  # Simple tasks
            model = "claude-haiku-4-5-20241022"
            max_tokens = 200
        elif complexity_score <= 6:  # Medium complexity
            model = "claude-sonnet-4-20250514"
            max_tokens = 400
        else:  # Complex analysis
            model = "claude-sonnet-4-20250514"
            max_tokens = 600
        
        prompt = self._build_analysis_prompt(ticker, task_type, context)
        
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        
        self._log_usage(response, ticker, f"route_analysis_{task_type}", model)
        return {"model_used": model, "response": response.content[0].text}
    
    def _estimate_complexity(self, task_type: str, context: Dict[str, Any]) -> int:
        """Score task complexity 1-10"""
        scores = {
            "simple_summary": 1,
            "watchlist_alert": 2,
            "portfolio_update": 3,
            "sector_comparison": 5,
            "multi_stock_analysis": 7,
            "deep_valuation": 9
        }
        return scores.get(task_type, 5)
    
    def _build_analysis_prompt(self, ticker: str, task_type: str, context: Dict[str, Any]) -> str:
        """Build concise prompt based on task type"""
        prompts = {
            "simple_summary": f"One-line DCF summary for {ticker}: Fair value ${context.get('fair_value', 0):.2f}, Current ${context.get('price', 0):.2f}",
            "watchlist_alert": f"Alert: {ticker} signal change. MoS {context.get('mos', 0):.1%}. Action?",
            "portfolio_update": f"Portfolio rebalance for {context.get('portfolio_name', 'Main')}. New signal: {context.get('signal', 'Hold')}",
        }
        return prompts.get(task_type, "Analyze " + ticker)
    
    # ============================================================
    # 3. BATCH API - 50% savings for non-urgent processing
    # ============================================================
    
    def create_batch_analysis(self, stocks: List[Dict[str, Any]]) -> str:
        """
        Queue multiple stock analyses for batch processing.
        50% discount on all tokens. Results ready within 24 hours.
        Perfect for overnight sector updates or watchlist processing.
        
        Args:
            stocks: List of dicts with 'ticker' and 'company_data' keys
        
        Returns:
            batch_id: Use to retrieve results later
        """
        requests = []
        
        for stock in stocks:
            ticker = stock['ticker']
            company_data = stock['company_data']
            
            # Build minimal but complete request
            context = f"""Ticker: {ticker}
Revenue: ${company_data.get('revenue_ttm', 0):.0f}M
EBIT Margin: {company_data.get('ebit_margin', 0):.1%}
FCF: ${company_data.get('fcf_ltm', 0):.0f}M
Price: ${company_data.get('current_price', 0):.2f}
WACC: {company_data.get('wacc', 0):.1%}"""
            
            requests.append({
                "custom_id": f"batch-{ticker}-{datetime.now().timestamp()}",
                "params": {
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 250,
                    "system": [
                        {
                            "type": "text",
                            "text": self.get_dcf_system_prompt()
                        }
                    ],
                    "messages": [
                        {
                            "role": "user",
                            "content": f"DCF analysis for {ticker}:\n{context}\nJSON format only."
                        }
                    ]
                }
            })
        
        batch = self.client.batches.create(requests=requests)
        print(f"✓ Batch created: {batch.id}")
        print(f"  Processing {len(stocks)} stocks")
        print(f"  Expected cost: 50% of regular API calls")
        print(f"  Results available in ~24 hours")
        
        return batch.id
    
    def retrieve_batch_results(self, batch_id: str) -> List[Dict[str, Any]]:
        """Retrieve completed batch results"""
        batch = self.client.batches.retrieve(batch_id)
        
        if batch.processing_status == "in_progress":
            return {"status": "in_progress", "request_counts": batch.request_counts}
        
        results = []
        for result in self.client.batches.results(batch_id):
            try:
                results.append(json.loads(result.message.content[0].text))
            except (json.JSONDecodeError, AttributeError):
                results.append({"error": "Failed to parse", "raw": str(result)})
        
        return results
    
    # ============================================================
    # 4. OUTPUT OPTIMIZATION - 5x ROI on token savings
    # ============================================================
    
    def create_summary_with_strict_limits(self, ticker: str, analysis_data: Dict[str, Any]) -> str:
        """
        Generate analysis summary with strict output limits.
        Output tokens cost 5x input tokens, so this optimization is high-ROI.
        
        Limits:
        - Max 3 lines for summary
        - JSON format (more compact than prose)
        - Explicit stop sequences
        """
        prompt = f"""For {ticker}, provide a 3-line investment summary.
Format: JSON with 'summary', 'action', 'confidence' keys.
Analysis context: {json.dumps(analysis_data, default=str)}
No explanation. JSON only."""
        
        response = self.client.messages.create(
            model="claude-haiku-4-5-20241022",  # Cheaper model for this task
            max_tokens=150,  # STRICT OUTPUT LIMIT
            messages=[{"role": "user", "content": prompt}]
        )
        
        self._log_usage(response, ticker, "create_summary_with_strict_limits")
        
        try:
            return json.loads(response.content[0].text)
        except json.JSONDecodeError:
            return {"summary": response.content[0].text}
    
    # ============================================================
    # 5. USAGE TRACKING & MONITORING
    # ============================================================
    
    def _track_cache_usage(self, response: Any) -> None:
        """Track cache hit/write statistics"""
        usage = response.usage
        if hasattr(usage, 'cache_creation_input_tokens') and usage.cache_creation_input_tokens > 0:
            self.cache_writes += 1
        if hasattr(usage, 'cache_read_input_tokens') and usage.cache_read_input_tokens > 0:
            self.cache_hits += 1
    
    def _log_usage(self, response: Any, ticker: str, operation: str, model: str = "claude-sonnet-4-20250514") -> None:
        """Log API usage for cost tracking"""
        usage = response.usage
        
        # Calculate costs
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cache_creation = getattr(usage, 'cache_creation_input_tokens', 0)
        cache_read = getattr(usage, 'cache_read_input_tokens', 0)
        
        # Pricing (verify against current docs)
        if "haiku" in model.lower():
            input_cost = (input_tokens * 0.80) / 1_000_000
            output_cost = (output_tokens * 4.00) / 1_000_000
        else:  # Sonnet
            input_cost = (input_tokens * 3.00) / 1_000_000
            output_cost = (output_tokens * 15.00) / 1_000_000
        
        # Cache pricing (25% premium for writes, 90% discount for reads)
        if cache_creation:
            cache_cost = (cache_creation * 3.00 * 1.25) / 1_000_000  # 25% premium
        elif cache_read:
            cache_cost = (cache_read * 3.00 * 0.1) / 1_000_000  # 90% discount
        else:
            cache_cost = 0
        
        total_cost = input_cost + output_cost + cache_cost
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "operation": operation,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_tokens": cache_creation,
            "cache_read_tokens": cache_read,
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "cache_cost": round(cache_cost, 6),
            "total_cost": round(total_cost, 6)
        }
        
        self.usage_log.append(log_entry)
    
    def get_cost_summary(self) -> Dict[str, Any]:
        """Get aggregate cost statistics"""
        if not self.usage_log:
            return {"message": "No usage logged yet"}
        
        total_cost = sum(log["total_cost"] for log in self.usage_log)
        total_input = sum(log["input_tokens"] for log in self.usage_log)
        total_output = sum(log["output_tokens"] for log in self.usage_log)
        cache_savings = sum(log["cache_cost"] for log in self.usage_log if log["cache_read_tokens"] > 0)
        
        return {
            "total_calls": len(self.usage_log),
            "total_cost": round(total_cost, 4),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "cache_hits": self.cache_hits,
            "cache_writes": self.cache_writes,
            "estimated_cache_savings": round(abs(cache_savings), 4),
            "avg_cost_per_call": round(total_cost / len(self.usage_log) if self.usage_log else 0, 4)
        }
    
    def export_usage_csv(self, filename: str = "api_logs/usage_log.csv") -> str:
        """Export detailed usage log to CSV for analysis"""
        if not self.usage_log:
            return "No usage data to export"
        
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.usage_log[0].keys())
            writer.writeheader()
            writer.writerows(self.usage_log)
        
        return f"Usage log exported to {filename}"
    
    def display_cost_metrics(self) -> str:
        """Return formatted cost metrics for Streamlit display"""
        summary = self.get_cost_summary()
        
        if "message" in summary:
            return summary["message"]
        
        metrics = f"""
╔════════════════════════════════════════════╗
║         YIELDIQ API COST METRICS           ║
╠════════════════════════════════════════════╣
║ Total API Calls:         {summary['total_calls']:>24} ║
║ Total Cost:              ${summary['total_cost']:>23.4f} ║
║ Avg Cost/Call:           ${summary['avg_cost_per_call']:>23.4f} ║
║ Cache Hits:              {summary['cache_hits']:>24} ║
║ Cache Writes:            {summary['cache_writes']:>24} ║
║ Estimated Cache Savings: ${summary['estimated_cache_savings']:>22.4f} ║
║ Total Input Tokens:      {summary['total_input_tokens']:>24} ║
║ Total Output Tokens:     {summary['total_output_tokens']:>24} ║
╚════════════════════════════════════════════╝
"""
        return metrics


# ============================================================
# QUICK START EXAMPLES
# ============================================================

def example_single_cached_analysis():
    """Example: Single stock analysis with caching"""
    optimizer = YieldIQOptimizer()
    
    company_data = {
        "revenue_ttm": 383285,
        "ebit_margin": 0.28,
        "fcf_ltm": 99803,
        "current_price": 228.72,
        "shares": 15400,
        "beta": 1.20,
        "wacc": 0.065
    }
    
    result = optimizer.analyze_stock_with_cache("AAPL", company_data)
    print(json.dumps(result, indent=2))
    print(optimizer.display_cost_metrics())

def example_model_routing():
    """Example: Route analyses by complexity"""
    optimizer = YieldIQOptimizer()
    
    tasks = [
        ("AAPL", "simple_summary", {"fair_value": 250, "price": 228}),
        ("MSFT", "multi_stock_analysis", {"stocks": ["AAPL", "MSFT", "GOOGL"]}),
    ]
    
    for ticker, task_type, context in tasks:
        result = optimizer.route_analysis(ticker, task_type, context)
        print(f"{task_type}: {result['model_used']}")

def example_batch_processing():
    """Example: Queue multiple stocks for batch processing"""
    optimizer = YieldIQOptimizer()
    
    stocks = [
        {
            "ticker": "AAPL",
            "company_data": {
                "revenue_ttm": 383285,
                "ebit_margin": 0.28,
                "fcf_ltm": 99803,
                "current_price": 228.72,
                "shares": 15400,
                "wacc": 0.065
            }
        },
        # Add more stocks...
    ]
    
    batch_id = optimizer.create_batch_analysis(stocks)
    print(f"Batch ID: {batch_id}")
    # Check back in 24 hours: optimizer.retrieve_batch_results(batch_id)

if __name__ == "__main__":
    example_single_cached_analysis()
