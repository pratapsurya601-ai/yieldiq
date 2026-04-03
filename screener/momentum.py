"""
Momentum Scoring System
Combines price trends, volume, RSI, and moving averages into 0-100 score
"""
from typing import Dict, Optional, List, Tuple
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

class MomentumScorer:
    """Calculate momentum score (0-100) for stocks"""
    
    def __init__(self):
        self.weights = {
            'price_trend': 0.30,      # 30 points
            'volume': 0.20,            # 20 points
            'rsi': 0.25,               # 25 points
            'ma_strength': 0.25        # 25 points
        }
    
    def calculate_momentum(self, price_data: pd.DataFrame) -> Dict:
        """
        Calculate comprehensive momentum score
        
        Args:
            price_data: DataFrame with columns ['Date', 'Close', 'Volume', 'High', 'Low']
                       Must have at least 200 days of data for accurate calculation
        
        Returns:
            Dict with momentum score, grade, and component breakdown
        """
        if price_data is None or len(price_data) < 50:
            return self._empty_result("Insufficient data (need 50+ days)")
        
        # Sort by date to ensure chronological order
        df = price_data.copy()
        df = df.sort_values('Date').reset_index(drop=True)
        
        # Calculate components
        price_score = self._price_trend_score(df)
        volume_score = self._volume_score(df)
        rsi_score = self._rsi_score(df)
        ma_score = self._ma_strength_score(df)
        
        # Weighted total
        total_score = (
            price_score * self.weights['price_trend'] * 100 +
            volume_score * self.weights['volume'] * 100 +
            rsi_score * self.weights['rsi'] * 100 +
            ma_score * self.weights['ma_strength'] * 100
        )
        
        # Cap at 0-100
        total_score = max(0, min(100, total_score))
        
        return {
            'momentum_score': round(total_score, 1),
            'grade': self._assign_grade(total_score),
            'signal': self._assign_signal(total_score),
            'components': {
                'price_trend': round(price_score * 100, 1),
                'volume': round(volume_score * 100, 1),
                'rsi': round(rsi_score * 100, 1),
                'ma_strength': round(ma_score * 100, 1)
            },
            'indicators': {
                'rsi_14': self._calculate_rsi(df['Close'], 14),
                'ma_20': df['Close'].rolling(20).mean().iloc[-1] if len(df) >= 20 else None,
                'ma_50': df['Close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else None,
                'ma_200': df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else None,
            }
        }
    
    def _price_trend_score(self, df: pd.DataFrame) -> float:
        """
        Score based on price trends and MA crossovers (0-1)
        
        Checks:
        - Price vs 20-day MA (short-term trend)
        - Price vs 50-day MA (medium-term trend)
        - Price vs 200-day MA (long-term trend)
        - 20-day vs 50-day crossover (golden cross indicator)
        """
        score = 0.0
        current_price = df['Close'].iloc[-1]
        
        # Calculate moving averages
        ma_20 = df['Close'].rolling(20).mean()
        ma_50 = df['Close'].rolling(50).mean()
        ma_200 = df['Close'].rolling(200).mean()
        
        # Short-term: Price vs 20-day MA (25% weight)
        if len(ma_20) >= 20:
            if current_price > ma_20.iloc[-1]:
                score += 0.25
        
        # Medium-term: Price vs 50-day MA (25% weight)
        if len(ma_50) >= 50:
            if current_price > ma_50.iloc[-1]:
                score += 0.25
                
            # Golden Cross: 20-day > 50-day (15% weight)
            if ma_20.iloc[-1] > ma_50.iloc[-1]:
                score += 0.15
        
        # Long-term: Price vs 200-day MA (25% weight)
        if len(ma_200) >= 200:
            if current_price > ma_200.iloc[-1]:
                score += 0.25
        
        # Trend strength: 5-day vs 20-day (10% weight)
        if len(df) >= 20:
            ma_5 = df['Close'].rolling(5).mean()
            if ma_5.iloc[-1] > ma_20.iloc[-1]:
                score += 0.10
        
        return score
    
    def _volume_score(self, df: pd.DataFrame) -> float:
        """
        Score based on volume trends (0-1)
        
        Checks:
        - Current volume vs 20-day average
        - Volume trend (increasing/decreasing)
        """
        score = 0.0
        
        if 'Volume' not in df.columns or len(df) < 20:
            return 0.5  # Neutral if no volume data
        
        current_volume = df['Volume'].iloc[-1]
        avg_volume_20 = df['Volume'].rolling(20).mean().iloc[-1]
        
        # Volume vs average (60% weight)
        volume_ratio = current_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0
        
        if volume_ratio > 1.5:      # 50% above average
            score += 0.60
        elif volume_ratio > 1.2:    # 20% above average
            score += 0.40
        elif volume_ratio > 0.8:    # Normal range
            score += 0.20
        # else: Low volume = 0 points
        
        # Volume trend: last 5 days vs previous 15 days (40% weight)
        if len(df) >= 20:
            recent_vol = df['Volume'].iloc[-5:].mean()
            prev_vol = df['Volume'].iloc[-20:-5].mean()
            
            if recent_vol > prev_vol * 1.1:  # Increasing volume
                score += 0.40
            elif recent_vol > prev_vol * 0.9:  # Stable volume
                score += 0.20
            # else: Decreasing volume = 0 points
        
        return score
    
    def _rsi_score(self, df: pd.DataFrame) -> float:
        """
        Score based on RSI (0-1)
        
        RSI interpretation:
        - 70-100: Overbought (caution)
        - 50-70: Strong momentum
        - 40-50: Neutral/weak momentum
        - 30-40: Oversold (potential reversal)
        - 0-30: Extremely oversold
        """
        rsi = self._calculate_rsi(df['Close'], period=14)
        
        if rsi is None:
            return 0.5  # Neutral if can't calculate
        
        # Optimal RSI range: 50-70 (strong momentum without overbought)
        if 55 <= rsi <= 65:
            return 1.0   # Perfect momentum
        elif 50 <= rsi < 55:
            return 0.85
        elif 65 < rsi <= 70:
            return 0.85
        elif 45 <= rsi < 50:
            return 0.60
        elif 70 < rsi <= 75:
            return 0.60  # Overbought but still strong
        elif 40 <= rsi < 45:
            return 0.40
        elif 75 < rsi <= 80:
            return 0.40  # Very overbought
        elif 30 <= rsi < 40:
            return 0.30  # Oversold
        elif rsi > 80:
            return 0.20  # Extremely overbought (risky)
        else:  # rsi < 30
            return 0.25  # Extremely oversold (potential bounce)
    
    def _ma_strength_score(self, df: pd.DataFrame) -> float:
        """
        Score based on moving average alignment (0-1)
        
        Perfect alignment: MA5 > MA20 > MA50 > MA200 (all trending up)
        """
        score = 0.0
        
        # Calculate all MAs
        ma_5 = df['Close'].rolling(5).mean()
        ma_20 = df['Close'].rolling(20).mean()
        ma_50 = df['Close'].rolling(50).mean()
        ma_200 = df['Close'].rolling(200).mean()
        
        # Check alignment (40% weight)
        if len(df) >= 200:
            mas = [ma_5.iloc[-1], ma_20.iloc[-1], ma_50.iloc[-1], ma_200.iloc[-1]]
            
            # Perfect alignment: each MA > next MA
            if mas[0] > mas[1] > mas[2] > mas[3]:
                score += 0.40
            elif mas[0] > mas[1] > mas[2]:  # Partial alignment
                score += 0.25
            elif mas[0] > mas[1]:  # Short-term alignment only
                score += 0.15
        
        # MA slope: Are MAs trending up? (30% weight)
        if len(ma_20) >= 25:
            # 20-day MA slope
            ma20_slope = (ma_20.iloc[-1] - ma_20.iloc[-5]) / ma_20.iloc[-5]
            if ma20_slope > 0.02:  # 2% increase over 5 days
                score += 0.30
            elif ma20_slope > 0:
                score += 0.15
        
        # Recent crossover signal (30% weight)
        if len(df) >= 50:
            # Check for golden cross (20 crossing above 50)
            ma20_current = ma_20.iloc[-1]
            ma50_current = ma_50.iloc[-1]
            ma20_prev = ma_20.iloc[-10] if len(ma_20) >= 10 else ma_20.iloc[0]
            ma50_prev = ma_50.iloc[-10] if len(ma_50) >= 10 else ma_50.iloc[0]
            
            # Golden cross in last 10 days
            if ma20_prev <= ma50_prev and ma20_current > ma50_current:
                score += 0.30
            elif ma20_current > ma50_current:  # Already in golden cross
                score += 0.20
        
        return score
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> Optional[float]:
        """Calculate RSI (Relative Strength Index)"""
        if len(prices) < period + 1:
            return None
        
        # Calculate price changes
        delta = prices.diff()
        
        # Separate gains and losses
        gains = delta.where(delta > 0, 0)
        losses = -delta.where(delta < 0, 0)
        
        # Calculate average gains and losses
        avg_gain = gains.rolling(window=period).mean()
        avg_loss = losses.rolling(window=period).mean()
        
        # Calculate RS and RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else None
    
    def _assign_grade(self, score: float) -> str:
        """Convert score to letter grade"""
        if score >= 90:
            return "A+"
        elif score >= 85:
            return "A"
        elif score >= 80:
            return "A-"
        elif score >= 75:
            return "B+"
        elif score >= 70:
            return "B"
        elif score >= 65:
            return "B-"
        elif score >= 60:
            return "C+"
        elif score >= 55:
            return "C"
        elif score >= 50:
            return "C-"
        elif score >= 45:
            return "D+"
        elif score >= 40:
            return "D"
        else:
            return "F"
    
    def _assign_signal(self, score: float) -> str:
        """Convert score to signal with emoji"""
        if score >= 80:
            return "Strong 🚀"
        elif score >= 60:
            return "Moderate ⬆️"
        elif score >= 40:
            return "Neutral ➡️"
        elif score >= 20:
            return "Weak ⬇️"
        else:
            return "Very Weak 📉"
    
    def _empty_result(self, reason: str) -> Dict:
        """Return empty result with reason"""
        return {
            'momentum_score': 0,
            'grade': 'N/A',
            'signal': 'N/A ⬜',
            'components': {
                'price_trend': 0,
                'volume': 0,
                'rsi': 0,
                'ma_strength': 0
            },
            'indicators': {},
            'error': reason
        }


# Helper function for easy imports
def calculate_momentum(price_data: pd.DataFrame) -> Dict:
    """
    Quick helper to calculate momentum score
    
    Args:
        price_data: DataFrame with ['Date', 'Close', 'Volume', 'High', 'Low']
    
    Returns:
        Dict with momentum_score, grade, signal, components
    """
    scorer = MomentumScorer()
    return scorer.calculate_momentum(price_data)