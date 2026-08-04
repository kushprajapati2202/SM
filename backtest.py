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

def run_multi_day_backtest():
    # Loop over trading days in early July
    scan_dates = [
        "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07",
        "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-13", "2026-07-14",
        "2026-07-15"
    ]
    
    print(f"============================================================")
    print(f" RUNNING OPTIMIZED CONFLUENCE BACKTEST SIMULATION (JULY 1 - JULY 15)")
    print(f"============================================================")
    
    all_suggestions = []
    
    print("Downloading historical data...")
    tickers_str = " ".join([f"{t}.NS" for t in WATCHLIST])
    data = yf.download(tickers_str, start="2025-01-01", progress=False)
    
    for scan_date_str in scan_dates:
        scan_date = datetime.datetime.strptime(scan_date_str, "%Y-%m-%d")
        
        for ticker in WATCHLIST:
            symbol = f"{ticker}.NS"
            try:
                if isinstance(data.columns, pd.MultiIndex):
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
                    
                scan_df = ticker_df[:scan_date_str]
                if len(scan_df) < 50:
                    continue
                    
                latest_date_in_df = scan_df.index[-1]
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
                
                # --- OPTIMIZED STRATEGIES ---
                # Target: +4.0%, Stop Loss: -3.5%
                
                # A. Bullish Setup
                in_uptrend = close_price >= ema_200 or (close_price >= ema_50 * 0.97)
                oversold = rsi < 36 or close_price <= (bb_lower * 1.005)  # More strict oversold
                
                is_bullish_engulfing = bool(latest.get('pattern_bullish_engulfing', False))
                is_hammer = bool(latest.get('pattern_hammer', False))
                db_indices = double_patterns.get("double_bottoms", [])
                is_double_bottom = any(idx >= (len(scan_df_reset) - 15) for idx in db_indices)
                momentum_reversal = macd_hist > prev_macd_hist and macd_hist > -1.0 # Slightly relaxed MACD hist recovery
                
                reversal_confirmed = is_bullish_engulfing or is_hammer or is_double_bottom or momentum_reversal
                
                if in_uptrend and oversold and reversal_confirmed:
                    # Target +4% profit target for highly consistent swing moves
                    target = round(close_price * 1.040, 2)
                    sl = round(close_price * 0.965, 2)
                    
                    forward_df = ticker_df[scan_date_str:].iloc[1:11]
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
                overbought = rsi > 64 or close_price >= (bb_upper * 0.995)  # More strict overbought
                
                is_bearish_engulfing = bool(latest.get('pattern_bearish_engulfing', False))
                is_shooting_star = bool(latest.get('pattern_shooting_star', False))
                dt_indices = double_patterns.get("double_tops", [])
                is_double_top = any(idx >= (len(scan_df_reset) - 15) for idx in dt_indices)
                momentum_downturn = macd_hist < prev_macd_hist and macd_hist < 1.0
                
                bearish_confirmed = is_bearish_engulfing or is_shooting_star or is_double_top or momentum_downturn
                
                if in_downtrend and overbought and bearish_confirmed:
                    # Target -4% profit target on short
                    target = round(close_price * 0.960, 2)
                    sl = round(close_price * 1.035, 2)
                    
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
                    
            except Exception as e:
                pass
                
    # Print consolidated results
    print(f"\nCONSOLIDATED OUTCOME LOG:")
    print("------------------------------------------------------------")
    achieved = 0
    failed = 0
    expired = 0
    
    for s in all_suggestions:
        print(f"[{s['date']}] {s['symbol']} ({s['type']}): Entry={s['close']} | Target={s['target']} | SL={s['sl']} -> Outcome={s['outcome']} (Day {s['days']})")
        if s["outcome"] == "ACHIEVED":
            achieved += 1
        elif s["outcome"] == "FAILED":
            failed += 1
        else:
            expired += 1
            
    print("------------------------------------------------------------")
    total = len(all_suggestions)
    print(f"Total Trade Setups Triggered: {total}")
    print(f"Achieved Targets: {achieved}")
    print(f"Failed (Stop Loss Hit): {failed}")
    print(f"Expired (Exited Flat): {expired}")
    
    closed_trades = achieved + failed
    win_rate = (achieved / closed_trades * 100) if closed_trades > 0 else 0
    print(f"Win Rate (on Closed Trades): {round(win_rate, 1)}%")
    overall_hit_rate = (achieved / total * 100) if total > 0 else 0
    print(f"Overall Target Hit Rate (Including Expired): {round(overall_hit_rate, 1)}%")
    print("============================================================")

if __name__ == "__main__":
    run_multi_day_backtest()
