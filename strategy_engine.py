from typing import Optional, Dict, Any

class StrategyEngine:
    @staticmethod
    def evaluate_strategies(latest: Dict[str, Any], prev: Dict[str, Any]) -> Optional[str]:
        """
        Evaluates deterministic rules for 4 core swing strategies.
        Returns the name of the strategy triggered, or None.
        """
        import math
        import pandas as pd

        def safe_float(val, default=0.0):
            if val is None or pd.isna(val):
                return default
            try:
                return float(val)
            except Exception:
                return default

        close_val = safe_float(latest.get('close'))
        high_val = safe_float(latest.get('high'))
        low_val = safe_float(latest.get('low'))
        
        # Moving Averages
        sma_20 = safe_float(latest.get('sma_20'), close_val)
        ema_50 = safe_float(latest.get('ema_50'), close_val)
        ema_200 = safe_float(latest.get('ema_200'), close_val)
        
        # Momentum & Volatility
        rsi = safe_float(latest.get('rsi'), 50.0)
        adx = safe_float(latest.get('adx'), 25.0)
        bb_width = safe_float(latest.get('bb_width'), 0.10)
        bb_upper = safe_float(latest.get('bb_upper'), close_val)
        
        # Volume
        volume = safe_float(latest.get('volume'), 1.0)
        volume_avg_20 = safe_float(latest.get('volume_avg_20'), 1.0)
        rel_volume = volume / volume_avg_20 if volume_avg_20 > 0 else 1.0
        
        # Price Structure
        high_20 = safe_float(latest.get('high_20'), close_val)
        
        # Patterns
        is_bullish_engulfing = bool(latest.get('pattern_bullish_engulfing', False))
        is_hammer = bool(latest.get('pattern_hammer', False))
        
        # NIFTY Relative Strength
        rs_nifty = safe_float(latest.get('relative_strength_nifty'), 0.0)
        
        # Strategy A — Trend Breakout
        if (close_val > ema_50 and 
            ema_50 > ema_200 and 
            close_val >= high_20 and 
            rel_volume > 1.5 and 
            adx > 20):
            return "Strategy A: Trend Breakout"
            
        # Strategy B — Trend Pullback
        elif (close_val > ema_200 and 
              ema_50 > ema_200 and 
              (abs(close_val - ema_50) / ema_50 <= 0.02 or abs(low_val - ema_50) / ema_50 <= 0.02) and 
              (is_bullish_engulfing or is_hammer) and 
              rsi > 40):
            return "Strategy B: Trend Pullback"
            
        # Strategy C — Momentum
        elif (rs_nifty > 2.0 and 
              close_val > sma_20 and 
              close_val > ema_50 and 
              rel_volume > 1.2):
            return "Strategy C: Momentum"
            
        # Strategy D — Volatility Breakout
        elif (bb_width < 0.08 and 
              close_val >= bb_upper and 
              rel_volume > 1.5):
            return "Strategy D: Volatility Breakout"
            
        return None
