"""
Test momentum scoring system
"""
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from screener.momentum import MomentumScorer, calculate_momentum

def generate_test_data(days=200, trend='bullish'):
    """Generate synthetic price data for testing"""
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    
    if trend == 'bullish':
        # Strong uptrend
        prices = 100 + np.cumsum(np.random.randn(days) * 2 + 0.5)
        volumes = 1000000 + np.random.randint(-200000, 500000, days)
    elif trend == 'bearish':
        # Downtrend
        prices = 150 - np.cumsum(np.random.randn(days) * 2 + 0.3)
        volumes = 1000000 + np.random.randint(-200000, 300000, days)
    elif trend == 'sideways':
        # Sideways/choppy
        prices = 100 + np.random.randn(days) * 3
        volumes = 1000000 + np.random.randint(-300000, 300000, days)
    else:  # volatile
        # High volatility
        prices = 100 + np.cumsum(np.random.randn(days) * 5)
        volumes = 1000000 + np.random.randint(-400000, 800000, days)
    
    # Ensure no negative prices
    prices = np.maximum(prices, 10)
    volumes = np.maximum(volumes, 100000)
    
    df = pd.DataFrame({
        'Date': dates,
        'Close': prices,
        'High': prices * 1.02,
        'Low': prices * 0.98,
        'Volume': volumes
    })
    
    return df

def test_scenario(name, trend):
    """Test a specific market scenario"""
    print(f"\n{'='*60}")
    print(f"🧪 Test: {name}")
    print('='*60)
    
    # Generate data
    df = generate_test_data(days=200, trend=trend)
    
    # Calculate momentum
    result = calculate_momentum(df)
    
    # Print results
    print(f"\n📊 Momentum Score: {result['momentum_score']}/100")
    print(f"🏆 Grade: {result['grade']}")
    print(f"🚦 Signal: {result['signal']}")
    
    print(f"\n📈 Component Breakdown:")
    for component, score in result['components'].items():
        print(f"   • {component.replace('_', ' ').title()}: {score}/100")
    
    if result['indicators']:
        print(f"\n📉 Technical Indicators:")
        rsi = result['indicators'].get('rsi_14')
        if rsi:
            print(f"   • RSI (14): {rsi:.1f}")
        for ma_period in ['ma_20', 'ma_50', 'ma_200']:
            ma_val = result['indicators'].get(ma_period)
            if ma_val:
                print(f"   • {ma_period.upper()}: ${ma_val:.2f}")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 Momentum Scoring System Tests")
    print("="*60)
    
    # Test different market conditions
    test_scenario("Strong Bullish Trend", "bullish")
    test_scenario("Bearish Downtrend", "bearish")
    test_scenario("Sideways/Choppy Market", "sideways")
    test_scenario("High Volatility", "volatile")
    
    print("\n" + "="*60)
    print("✅ All momentum tests complete!")
    print("="*60 + "\n")