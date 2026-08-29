from typing import List, Dict, Any

class RiskEngine:
    @staticmethod
    def calculate_trade_setup(
        close_price: float, 
        atr: float, 
        supports: List[float], 
        resistances: List[float], 
        capital: float = 100000.0, 
        risk_pct: float = 1.0
    ) -> Dict[str, Any]:
        """
        Calculates trade setup including Entry, Target, Stop Loss, Risk-Reward (R:R), and Position Sizing.
        """
        # Default ATR SL at 2 * ATR
        atr_sl = close_price - 2.0 * atr
        
        # Align with nearest support level if reasonable (within 2% to 5% below entry)
        supports_below = [s for s in supports if s < close_price]
        if supports_below:
            nearest_support = max(supports_below)
            if 0.95 * close_price <= nearest_support <= 0.98 * close_price:
                sl = nearest_support
            else:
                sl = atr_sl
        else:
            sl = atr_sl
            
        # Clamp SL to minimum -1.5% and maximum -6% to avoid extreme swings
        min_sl_price = close_price * 0.985
        max_sl_price = close_price * 0.94
        if sl > min_sl_price:
            sl = min_sl_price
        elif sl < max_sl_price:
            sl = max_sl_price
            
        sl = round(sl, 2)
        risk_per_share = close_price - sl
        
        # Default Target at 2.0x Risk
        target = close_price + 2.0 * risk_per_share
        
        # Align with nearest resistance if reasonable (within 4% to 10% above entry)
        resistances_above = [r for r in resistances if r > close_price]
        if resistances_above:
            nearest_resistance = min(resistances_above)
            if 1.04 * close_price <= nearest_resistance <= 1.10 * close_price:
                target = nearest_resistance
                
        # Clamp Target to minimum +3.5% and maximum +12%
        min_target_price = close_price * 1.035
        max_target_price = close_price * 1.12
        if target < min_target_price:
            target = min_target_price
        elif target > max_target_price:
            target = max_target_price
            
        target = round(target, 2)
        
        # Compute exact R:R
        reward = target - close_price
        rr_ratio = round(reward / risk_per_share, 2) if risk_per_share > 0 else 0.0
        
        # Calculate Position Size based on risk capital (e.g. Risk 1% of Capital)
        risk_amount = capital * (risk_pct / 100.0)
        position_size = int(risk_amount // risk_per_share) if risk_per_share > 0 else 0
        total_investment = round(position_size * close_price, 2)
        
        return {
            "entry_price": round(close_price, 2),
            "stop_loss": sl,
            "target_price": target,
            "rr_ratio": rr_ratio,
            "position_size": position_size,
            "total_investment": total_investment,
            "risk_amount": round(risk_amount, 2)
        }
