"""
Test DCF edge cases - Simplified version
"""
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from screener.dcf_engine import DCFEngine

def test_edge_case(test_name, **params):
    """Test a specific edge case"""
    print(f"\n{'='*60}")
    print(f"🧪 Test: {test_name}")
    print('='*60)
    
    wacc = params.pop('wacc', 0.10)  # Remove wacc from params
    engine = DCFEngine(discount_rate=wacc, terminal_growth=0.03)
    
    try:
        result = engine.intrinsic_value_per_share(**params)
        
        print(f"\n📊 Reliability Score: {engine.edge_flags.reliability_score}/100")
        print(f"🏷️  Category: {engine.edge_flags.get_category()}")
        
        if engine.edge_flags.flags:
            print(f"\n⚠️  Edge Case Warnings ({len(engine.edge_flags.flags)}):")
            for i, flag in enumerate(engine.edge_flags.flags, 1):
                print(f"   {i}. {flag}")
        else:
            print("\n✅ No edge case warnings")
        
        iv = result.get('intrinsic_value', 0)
        cp = result.get('current_price', 0)
        mos = result.get('margin_of_safety', 0)
        
        print(f"\n💰 Intrinsic Value: ${iv:,.2f}")
        print(f"📈 Current Price: ${cp:,.2f}")
        print(f"🎯 MoS: {mos:.1f}%")
        
        return True
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 DCF Edge Case Detection Testing")
    print("="*60)
    
    # Test 1: Negative FCF
    test_edge_case(
        "Negative FCF - Loss Company",
        projected_fcfs=[-1000, -800, -500, 0, 200, 400, 600, 800, 1000, 1200],
        terminal_fcf_norm=1200,
        total_debt=5000000000,
        total_cash=2000000000,
        shares_outstanding=100000000,
        current_price=50.0,
        ticker="LOSS_CO",
        beta=1.8,
        pe_ratio=-15.0
    )
    
    # Test 2: Extreme P/E
    test_edge_case(
        "Extreme P/E - High Growth",
        projected_fcfs=[500, 800, 1200, 1800, 2500, 3200, 4000, 5000, 6000, 7000],
        terminal_fcf_norm=7000,
        total_debt=1000000000,
        total_cash=8000000000,
        shares_outstanding=200000000,
        current_price=200.0,
        ticker="HYPE",
        beta=2.2,
        pe_ratio=150.0
    )
    
    # Test 3: High Debt
    test_edge_case(
        "High Debt - Overleveraged",
        projected_fcfs=[1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900],
        terminal_fcf_norm=1900,
        total_debt=20000000000,
        total_cash=500000000,
        shares_outstanding=150000000,
        current_price=80.0,
        ticker="DEBT",
        beta=1.5,
        pe_ratio=25.0,
        total_equity=5000000000
    )
    
    # Test 4: Recent IPO
    test_edge_case(
        "Recent IPO - Limited History",
        projected_fcfs=[100, 200, 400, 800, 1600, 3200, 6400, 12800, 25600, 51200],
        terminal_fcf_norm=51200,
        total_debt=100000000,
        total_cash=1000000000,
        shares_outstanding=50000000,
        current_price=150.0,
        ticker="NEW_IPO",
        beta=1.3,
        pe_ratio=80.0,
        ipo_date="2024-01-15"
    )
    
    # Test 5: High Volatility
    test_edge_case(
        "High Volatility - Beta 3.5",
        projected_fcfs=[100, 150, 200, 300, 400, 500, 600, 700, 800, 900],
        terminal_fcf_norm=900,
        total_debt=200000000,
        total_cash=300000000,
        shares_outstanding=80000000,
        current_price=120.0,
        ticker="VOLATILE",
        beta=3.5,
        pe_ratio=200.0
    )
    
    print("\n" + "="*60)
    print("✅ Testing Complete!")
    print("="*60 + "\n")