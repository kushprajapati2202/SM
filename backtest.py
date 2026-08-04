import os
import datetime
import yfinance as yf
import pandas as pd
import numpy as np

from quant_engine import QuantitativeEngine
from pattern_detector import PatternDetector

WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "TATASTEEL", 
    "ITC", "BHARTIARTL", "LT", "M&M", "HINDUNILVR", "KOTAKBANK", "AXISBANK", 
    "MARUTI", "SUNPHARMA", "ADANIENT", "WIPRO", "POWERGRID", "NTPC", 
    "ONGC", "COALINDIA", "HCLTECH", "BAJFINANCE", "ASIANPAINT", "JSWSTEEL",
    "TATAELXSI", "JIOFIN", "TITAN", "ULTRACEMCO"
]

def run_backtest_simulation(start_date_str: str, end_date_str: str, target_pct: float = 4.0, stop_loss_pct: float = 3.5) -> dict:
    # Generate business day range
    try:
        all_dates = pd.date_range(start=start_date_str, end=end_date_str, freq="B")
        scan_dates = [d.strftime("%Y-%m-%d") for d in all_dates]
    except Exception as e:
        return {"error": f"Invalid date format: {str(e)}", "all_suggestions": []}

    all_suggestions = []
    
    # Download data from start of 2025 up to end of the range
    tickers_str = " ".join([f"{t}.NS" for t in WATCHLIST])
    
    # Add buffer days before the start date to calculate indicators (e.g. 1 year back)
    start_dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
    buffer_start = (start_dt - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
    
    try:
        data = yf.download(tickers_str, start=buffer_start, end=end_date_str, progress=False)
    except Exception as e:
        return {"error": f"Failed to download backtest data: {str(e)}", "all_suggestions": []}
    
    for scan_date_str in scan_dates:
        scan_date = datetime.datetime.strptime(scan_date_str, "%Y-%m-%d")
        
        for ticker in WATCHLIST:
            symbol = f"{ticker}.NS"
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if symbol not in data['Open'].columns:
                        continue
                    ticker_df = pd.DataFrame({
                        "Open": data['Open'][symbol],
                        "High": data['High'][symbol],
                        "Low": data['Low'][symbol],
                        "Close": data['Close'][symbol],
                        "Volume": data['Volume'][symbol]
                    }).dropna()
                else:
                    continue
                    
                if ticker_df.empty:
                    continue
                
                # Slice data up to scan date
                scan_df = ticker_df[:scan_date_str]
                if len(scan_df) < 50:
                    continue
                    
                latest_date_in_df = scan_df.index[-1]
                # If the latest date in df is too far from the scan date, skip (e.g. holiday or weekend)
                if abs((latest_date_in_df - scan_date).days) > 4:
                    continue
                    
                scan_df_reset = scan_df.reset_index()
                scan_df_reset.columns = [col.lower() for col in scan_df_reset.columns]
                
                df_indicators = QuantitativeEngine.calculate_indicators(scan_df_reset)
                df_patterns = PatternDetector.detect_candlesticks(df_indicators)
                double_patterns = PatternDetector.detect_double_tops_bottoms(scan_df_reset)
                
                latest = df_patterns.iloc[-1]
                prev = df_patterns.iloc[-2]
                
                close_price = float(latest['close'])
                ema_50 = float(latest['ema_50']) if pd.notna(latest.get('ema_50')) else close_price
                ema_200 = float(latest['ema_200']) if pd.notna(latest.get('ema_200')) else close_price
                bb_lower = float(latest['bb_lower']) if pd.notna(latest.get('bb_lower')) else close_price
                bb_upper = float(latest['bb_upper']) if pd.notna(latest.get('bb_upper')) else close_price
                
                rsi_col = [c for c in df_indicators.columns if 'rsi' in c]
                rsi = float(latest[rsi_col[0]]) if rsi_col and pd.notna(latest[rsi_col[0]]) else 50.0
                
                macd_hist = float(latest['macd_hist']) if pd.notna(latest.get('macd_hist')) else 0.0
                prev_macd_hist = float(prev['macd_hist']) if pd.notna(prev.get('macd_hist')) else 0.0
                
                # A. Bullish Setup
                in_uptrend = close_price >= ema_200 or (close_price >= ema_50 * 0.97)
                oversold = rsi < 36 or close_price <= (bb_lower * 1.005)
                
                is_bullish_engulfing = bool(latest.get('pattern_bullish_engulfing', False))
                is_hammer = bool(latest.get('pattern_hammer', False))
                db_indices = double_patterns.get("double_bottoms", [])
                is_double_bottom = any(idx >= (len(scan_df_reset) - 15) for idx in db_indices)
                momentum_reversal = macd_hist > prev_macd_hist and macd_hist > -1.0
                
                reversal_confirmed = is_bullish_engulfing or is_hammer or is_double_bottom or momentum_reversal
                
                # Extract variables for strategy matching
                adx = float(latest['adx']) if pd.notna(latest.get('adx')) else 25.0
                volume = float(latest['volume']) if pd.notna(latest.get('volume')) else 1.0
                volume_avg_20 = float(latest['volume_avg_20']) if pd.notna(latest.get('volume_avg_20')) else 1.0
                high_20 = float(latest['high_20']) if pd.notna(latest.get('high_20')) else close_price
                low_20 = float(latest['low_20']) if pd.notna(latest.get('low_20')) else close_price
                
                is_bullish_engulfing = bool(latest.get('pattern_bullish_engulfing', False))
                is_hammer = bool(latest.get('pattern_hammer', False))
                db_indices = double_patterns.get("double_bottoms", [])
                is_double_bottom = any(idx >= (len(scan_df_reset) - 15) for idx in db_indices)
                is_cup_and_handle = PatternDetector.detect_cup_and_handle(df_patterns)
                is_bull_flag = PatternDetector.detect_bull_flag(df_patterns)
                
                support_resistance = QuantitativeEngine.detect_support_resistance(scan_df_reset)
                
                # A. Bullish Swing Setup Identification
                strategy_triggered = None
                
                if (close_price > ema_200 and ema_50 > ema_200 and 
                    abs(close_price - ema_50) / ema_50 <= 0.015 and 
                    (is_bullish_engulfing or is_hammer) and 
                    rsi > 45 and volume > volume_avg_20 and adx > 25):
                    strategy_triggered = "EMA 50 Pullback Reversal"
                elif (close_price >= high_20 and volume > 2.0 * volume_avg_20 and 
                      rsi >= 55 and rsi <= 70 and macd_hist > 0):
                    strategy_triggered = "Volume Breakout"
                elif is_cup_and_handle:
                    strategy_triggered = "Cup & Handle Breakout"
                elif is_double_bottom and volume > volume_avg_20 and macd_hist > prev_macd_hist:
                    strategy_triggered = "Double Bottom Rebound"
                elif is_bull_flag:
                    strategy_triggered = "Bull Flag Breakout"
                elif rsi < 38:
                    strategy_triggered = "Oversold RSI Rebound"
                elif close_price <= bb_lower * 1.015 and rsi < 45:
                    strategy_triggered = "Bollinger Band Lower Support"
                elif macd_hist > 0 and prev_macd_hist <= 0 and rsi < 55:
                    strategy_triggered = "MACD Bullish Crossover"
                elif (close_price > ema_200 and 
                      abs(latest['low'] - ema_50) / ema_50 <= 0.015 and 
                      (is_bullish_engulfing or is_hammer)):
                    strategy_triggered = "EMA Support Bounce"

                if strategy_triggered:
                    score = 0
                    if close_price > ema_50 and ema_50 > ema_200:
                        score += 25
                    elif close_price > ema_200:
                        score += 15
                    elif abs(close_price - ema_50) / ema_50 < 0.02:
                        score += 20
                        
                    rel_vol = volume / volume_avg_20 if volume_avg_20 > 0 else 1.0
                    if rel_vol > 2.0:
                        score += 20
                    elif rel_vol > 1.2:
                        score += 12
                    elif rel_vol > 0.8:
                        score += 6
                        
                    momentum_pts = 0
                    if 45 <= rsi <= 68:
                        momentum_pts += 10
                    elif rsi < 38:
                        momentum_pts += 10
                    if macd_hist > prev_macd_hist:
                        momentum_pts += 10
                    elif macd_hist > 0:
                        momentum_pts += 5
                    score += momentum_pts
                        
                    if any(p in strategy_triggered for p in ["Cup & Handle", "Bull Flag", "Double Bottom"]):
                        score += 20
                    elif any(p in strategy_triggered for p in ["Engulfing", "Hammer", "Crossover"]):
                        score += 15
                    else:
                        score += 10
                        
                    bb_width = float(latest['bb_width']) if pd.notna(latest.get('bb_width')) else 0.0
                    vol_pts = 0
                    if adx > 22:
                        vol_pts += 8
                    if bb_width > 0 and bb_width < 0.06:
                        vol_pts += 7
                    elif bb_width > 0.12:
                        vol_pts += 3
                    score += vol_pts
                    
                    if score >= 60:
                        # Compute Target & SL
                        if target_pct > 0 and stop_loss_pct > 0:
                            target = round(close_price * (1.0 + target_pct / 100.0), 2)
                            sl = round(close_price * (1.0 - stop_loss_pct / 100.0), 2)
                        else:
                            # Dynamic logic
                            atr_val = float(latest['atr']) if pd.notna(latest.get('atr')) else close_price * 0.02
                            if atr_val <= 0:
                                atr_val = close_price * 0.02
                            target_sl_atr = close_price - 1.5 * atr_val
                            supports_below_close = [s for s in support_resistance.get("supports", []) if s < close_price]
                            if supports_below_close:
                                nearest_support = max(supports_below_close)
                                if 0.94 * close_price <= nearest_support <= 0.985 * close_price:
                                    sl = nearest_support
                                else:
                                    sl = target_sl_atr
                            else:
                                sl = target_sl_atr
                            sl = round(sl, 2)
                            
                            min_sl = round(close_price * 0.985, 2)
                            max_sl = round(close_price * 0.95, 2)
                            if sl > min_sl:
                                sl = min_sl
                            elif sl < max_sl:
                                sl = max_sl
                                
                            risk = close_price - sl
                            target_tp_atr = close_price + 1.8 * risk
                            resistances_above_close = [r for r in support_resistance.get("resistances", []) if r > close_price]
                            if resistances_above_close:
                                nearest_resistance = min(resistances_above_close)
                                if 1.03 * close_price <= nearest_resistance <= 1.08 * close_price:
                                    target = nearest_resistance
                                else:
                                    target = target_tp_atr
                            else:
                                target = target_tp_atr
                            target = round(target, 2)
                            
                            min_target = round(close_price * 1.035, 2)
                            max_target = round(close_price * 1.085, 2)
                            if target < min_target:
                                target = min_target
                            elif target > max_target:
                                target = max_target
                        
                        forward_df = ticker_df[scan_date_str:].iloc[1:11] # 10 trading day forward window
                        outcome = "EXPIRED"
                        hit_day = 0
                        
                        for day_idx, (_, row) in enumerate(forward_df.iterrows(), 1):
                            h = float(row["High"])
                            l = float(row["Low"])
                            if h >= target:
                                outcome = "ACHIEVED"
                                hit_day = day_idx
                                break
                            elif l <= sl:
                                outcome = "FAILED"
                                hit_day = day_idx
                                break
                                
                        all_suggestions.append({
                            "date": scan_date_str,
                            "symbol": ticker,
                            "type": "BUY",
                            "close": close_price,
                            "target": target,
                            "sl": sl,
                            "outcome": outcome,
                            "days": hit_day
                        })
                        
                # B. Bearish Setup
                is_overbought = rsi > 62
                is_bearish_engulfing = bool(latest.get('pattern_bearish_engulfing', False))
                is_shooting_star = bool(latest.get('pattern_shooting_star', False))
                dt_indices = double_patterns.get("double_tops", [])
                is_double_top = any(idx >= (len(scan_df_reset) - 15) for idx in dt_indices)

                bearish_strategy = None
                if (close_price < ema_200 and rsi > 55 and 
                    (is_bearish_engulfing or is_shooting_star) and adx > 25):
                    bearish_strategy = "Bearish Pullback Rejection"
                elif close_price <= low_20 and volume > 1.5 * volume_avg_20 and rsi < 45:
                    bearish_strategy = "Volume Breakdown"
                elif is_double_top and volume > volume_avg_20 and macd_hist < prev_macd_hist:
                    bearish_strategy = "Double Top Rebound"
                elif rsi > 62:
                    bearish_strategy = "Overbought RSI Pullback"
                elif close_price >= bb_upper * 0.985 and rsi > 55:
                    bearish_strategy = "Bollinger Band Upper Rejection"
                elif macd_hist < 0 and prev_macd_hist >= 0:
                    bearish_strategy = "MACD Bearish Crossover"

                if bearish_strategy:
                    score = 0
                    if close_price < ema_50 and ema_50 < ema_200:
                        score += 25
                    elif close_price < ema_200:
                        score += 15
                    elif abs(close_price - ema_50) / ema_50 < 0.02:
                        score += 20
                        
                    rel_vol = volume / volume_avg_20 if volume_avg_20 > 0 else 1.0
                    if rel_vol > 2.0:
                        score += 20
                    elif rel_vol > 1.2:
                        score += 12
                    elif rel_vol > 0.8:
                        score += 6
                        
                    momentum_pts = 0
                    if 35 <= rsi <= 55:
                        momentum_pts += 10
                    elif rsi > 62:
                        momentum_pts += 10
                    if macd_hist < prev_macd_hist:
                        momentum_pts += 10
                    elif macd_hist < 0:
                        momentum_pts += 5
                    score += momentum_pts
                        
                    if any(p in bearish_strategy for p in ["Double Top"]):
                        score += 20
                    elif any(p in bearish_strategy for p in ["Engulfing", "Shooting Star", "Crossover"]):
                        score += 15
                    else:
                        score += 10
                        
                    bb_width = float(latest['bb_width']) if pd.notna(latest.get('bb_width')) else 0.0
                    vol_pts = 0
                    if adx > 22:
                        vol_pts += 8
                    if bb_width > 0 and bb_width < 0.06:
                        vol_pts += 7
                    score += vol_pts
                    
                    if score >= 60:
                        if target_pct > 0 and stop_loss_pct > 0:
                            target = round(close_price * (1.0 - target_pct / 100.0), 2)
                            sl = round(close_price * (1.0 + stop_loss_pct / 100.0), 2)
                        else:
                            # Dynamic logic
                            atr_val = float(latest['atr']) if pd.notna(latest.get('atr')) else close_price * 0.02
                            if atr_val <= 0:
                                atr_val = close_price * 0.02
                            target_sl_atr = close_price + 1.5 * atr_val
                            resistances_above_close = [r for r in support_resistance.get("resistances", []) if r > close_price]
                            if resistances_above_close:
                                nearest_resistance = min(resistances_above_close)
                                if 1.015 * close_price <= nearest_resistance <= 1.05 * close_price:
                                    sl = nearest_resistance
                                else:
                                    sl = target_sl_atr
                            else:
                                sl = target_sl_atr
                            sl = round(sl, 2)
                            
                            min_sl = round(close_price * 1.015, 2)
                            max_sl = round(close_price * 1.05, 2)
                            if sl < min_sl:
                                sl = min_sl
                            elif sl > max_sl:
                                sl = max_sl
                                
                            risk = sl - close_price
                            target_tp_atr = close_price - 1.8 * risk
                            supports_below_close = [s for s in support_resistance.get("supports", []) if s < close_price]
                            if supports_below_close:
                                nearest_support = max(supports_below_close)
                                if 0.92 * close_price <= nearest_support <= 0.965 * close_price:
                                    target = nearest_support
                                else:
                                    target = target_tp_atr
                            else:
                                target = target_tp_atr
                            target = round(target, 2)
                            
                            min_target = round(close_price * 0.965, 2)
                            max_target = round(close_price * 0.915, 2)
                            if target > min_target:
                                target = min_target
                            elif target < max_target:
                                target = max_target
                        
                        forward_df = ticker_df[scan_date_str:].iloc[1:11]
                        outcome = "EXPIRED"
                        hit_day = 0
                        
                        for day_idx, (_, row) in enumerate(forward_df.iterrows(), 1):
                            h = float(row["High"])
                            l = float(row["Low"])
                            if l <= target:
                                outcome = "ACHIEVED"
                                hit_day = day_idx
                                break
                            elif h >= sl:
                                outcome = "FAILED"
                                hit_day = day_idx
                                break
                                
                        all_suggestions.append({
                            "date": scan_date_str,
                            "symbol": ticker,
                            "type": "SHORT",
                            "close": close_price,
                            "target": target,
                            "sl": sl,
                            "outcome": outcome,
                            "days": hit_day
                        })
                        
            except Exception:
                pass
                
    # Calculate stats
    achieved = sum(1 for s in all_suggestions if s["outcome"] == "ACHIEVED")
    failed = sum(1 for s in all_suggestions if s["outcome"] == "FAILED")
    expired = sum(1 for s in all_suggestions if s["outcome"] == "EXPIRED")
    total = len(all_suggestions)
    closed = achieved + failed
    win_rate = round((achieved / closed * 100), 1) if closed > 0 else 0.0
    hit_rate = round((achieved / total * 100), 1) if total > 0 else 0.0
    
    return {
        "total_setups": total,
        "achieved_count": achieved,
        "failed_count": failed,
        "expired_count": expired,
        "win_rate": win_rate,
        "hit_rate": hit_rate,
        "suggestions": all_suggestions
    }

if __name__ == "__main__":
    # Fallback/default runner for CLI
    res = run_backtest_simulation("2026-07-01", "2026-07-15")
    print(f"Total Trade Setups Triggered: {res['total_setups']}")
    print(f"Achieved Targets: {res['achieved_count']}")
    print(f"Failed: {res['failed_count']}")
    print(f"Expired: {res['expired_count']}")
    print(f"Win Rate: {res['win_rate']}%")
