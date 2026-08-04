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
                
                if in_uptrend and oversold and reversal_confirmed:
                    target = round(close_price * (1.0 + target_pct / 100.0), 2)
                    sl = round(close_price * (1.0 - stop_loss_pct / 100.0), 2)
                    
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
                in_downtrend = close_price <= ema_50 or close_price <= ema_200
                overbought = rsi > 64 or close_price >= (bb_upper * 0.995)
                
                is_bearish_engulfing = bool(latest.get('pattern_bearish_engulfing', False))
                is_shooting_star = bool(latest.get('pattern_shooting_star', False))
                dt_indices = double_patterns.get("double_tops", [])
                is_double_top = any(idx >= (len(scan_df_reset) - 15) for idx in dt_indices)
                momentum_downturn = macd_hist < prev_macd_hist and macd_hist < 1.0
                
                bearish_confirmed = is_bearish_engulfing or is_shooting_star or is_double_top or momentum_downturn
                
                if in_downtrend and overbought and bearish_confirmed:
                    target = round(close_price * (1.0 - target_pct / 100.0), 2)
                    sl = round(close_price * (1.0 + stop_loss_pct / 100.0), 2)
                    
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
