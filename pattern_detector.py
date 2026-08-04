import pandas as pd
import numpy as np
from typing import List, Dict, Any

class PatternDetector:
    """
    Mathematical Price Action and Candlestick Pattern Detector.
    Strictly mathematical with zero assumptions or hallucinations.
    """

    @staticmethod
    def detect_candlesticks(df: pd.DataFrame) -> pd.DataFrame:
        """
        Detects standard candlestick patterns mathematically.
        Adds boolean columns to the dataframe indicating presence.
        """
        # Ensure lowercase columns
        df.columns = [col.lower() for col in df.columns]
        
        # Helper metrics
        body = (df['close'] - df['open']).abs()
        candle_range = df['high'] - df['low']
        # Avoid division by zero
        candle_range = candle_range.replace(0, 0.00001)
        
        # 1. Doji (Very small body relative to range)
        df['pattern_doji'] = body <= (candle_range * 0.1)
        
        # 2. Hammer (Small body near top, long lower wick, tiny/no upper wick)
        lower_wick = df[['open', 'close']].min(axis=1) - df['low']
        upper_wick = df['high'] - df[['open', 'close']].max(axis=1)
        
        df['pattern_hammer'] = (
            (lower_wick >= body * 2) & 
            (upper_wick <= body * 0.2) & 
            (body > 0)
        )
        
        # 3. Shooting Star (Small body near bottom, long upper wick, tiny/no lower wick)
        df['pattern_shooting_star'] = (
            (upper_wick >= body * 2) & 
            (lower_wick <= body * 0.2) & 
            (body > 0)
        )
        
        # 4. Engulfing Patterns (Requires lookback of 1 candle)
        df['pattern_bullish_engulfing'] = False
        df['pattern_bearish_engulfing'] = False
        
        for i in range(1, len(df)):
            prev_open = df['open'].iloc[i-1]
            prev_close = df['close'].iloc[i-1]
            curr_open = df['open'].iloc[i]
            curr_close = df['close'].iloc[i]
            
            # Bullish Engulfing: previous was bearish, current is bullish and engulfs previous body
            if (prev_close < prev_open) and (curr_close > curr_open):
                if (curr_open <= prev_close) and (curr_close >= prev_open):
                    df.loc[df.index[i], 'pattern_bullish_engulfing'] = True
                    
            # Bearish Engulfing: previous was bullish, current is bearish and engulfs previous body
            if (prev_close > prev_open) and (curr_close < curr_open):
                if (curr_open >= prev_close) and (curr_close <= prev_open):
                    df.loc[df.index[i], 'pattern_bearish_engulfing'] = True
                    
        return df

    @staticmethod
    def detect_double_tops_bottoms(df: pd.DataFrame, threshold_percent: float = 1.0) -> Dict[str, List[int]]:
        """
        Find Double Tops (bearish reversal) and Double Bottoms (bullish reversal)
        by finding consecutive peaks/troughs of similar height.
        """
        # Find peaks and troughs
        peaks = []
        troughs = []
        
        # Lookback/lookforward windows
        w = 5 
        for i in range(w, len(df) - w):
            if df['high'].iloc[i] == df['high'].iloc[i-w:i+w+1].max():
                peaks.append((i, df['high'].iloc[i]))
            if df['low'].iloc[i] == df['low'].iloc[i-w:i+w+1].min():
                troughs.append((i, df['low'].iloc[i]))
                
        double_tops = []
        double_bottoms = []
        
        # Match consecutive peaks for double tops
        for j in range(len(peaks) - 1):
            p1_idx, p1_val = peaks[j]
            p2_idx, p2_val = peaks[j+1]
            
            # Check similarity within threshold
            price_diff = abs(p1_val - p2_val) / p1_val * 100
            if price_diff <= threshold_percent:
                # Ensure there is a significant trough in between them
                in_between_trough = df['low'].iloc[p1_idx:p2_idx].min()
                trough_depth = (p1_val - in_between_trough) / p1_val * 100
                if trough_depth > 2.0: # At least a 2% drop between peaks
                    double_tops.append(p2_idx)
                    
        # Match consecutive troughs for double bottoms
        for j in range(len(troughs) - 1):
            t1_idx, t1_val = troughs[j]
            t2_idx, t2_val = troughs[j+1]
            
            price_diff = abs(t1_val - t2_val) / t1_val * 100
            if price_diff <= threshold_percent:
                # Ensure there is a significant peak in between them
                in_between_peak = df['high'].iloc[t1_idx:t2_idx].max()
                peak_height = (in_between_peak - t1_val) / t1_val * 100
                if peak_height > 2.0: # At least 2% rally between troughs
                    double_bottoms.append(t2_idx)
                    
        return {
            "double_tops": double_tops,
            "double_bottoms": double_bottoms
        }

    @staticmethod
    def detect_cup_and_handle(df: pd.DataFrame) -> bool:
        """
        Mathematical Cup & Handle Breakout approximation.
        Requires rounded cup shape + short consolidation handle + volume breakout.
        """
        if len(df) < 30:
            return False
            
        close = df['close'].values
        high = df['high'].values
        volume = df['volume'].values
        
        # 1. Look for cup left peak 15 to 30 days ago
        left_peak_window = high[-30:-15]
        if len(left_peak_window) == 0:
            return False
        left_peak_idx = int(np.argmax(left_peak_window)) + (len(df) - 30)
        left_peak_val = high[left_peak_idx]
        
        # 2. Check for a rounded cup bottom in the middle
        cup_mid_window = close[left_peak_idx:-5]
        if len(cup_mid_window) == 0:
            return False
        cup_bottom = np.min(cup_mid_window)
        
        # Bottom must be at least 5% lower than the left peak
        if (left_peak_val - cup_bottom) / left_peak_val < 0.05:
            return False
            
        # 3. Handle consolidation (last 3 to 7 days)
        # Handle high should be near the left peak (within 3%)
        handle_window = high[-7:-1]
        handle_high = np.max(handle_window)
        if abs(handle_high - left_peak_val) / left_peak_val > 0.03:
            return False
            
        # Handle pullback must be shallow (< 15% retracement)
        handle_low = np.min(df['low'].values[-7:-1])
        handle_drawdown = (handle_high - handle_low) / handle_high
        if handle_drawdown > 0.15:
            return False
            
        # 4. Breakout: Latest close breaks above handle high on above-average volume
        latest_close = close[-1]
        avg_vol = df['volume_avg_20'].iloc[-1] if 'volume_avg_20' in df.columns else np.mean(volume[-20:])
        
        is_breakout = latest_close > handle_high and volume[-1] > avg_vol
        return bool(is_breakout)

    @staticmethod
    def detect_bull_flag(df: pd.DataFrame) -> bool:
        """
        Mathematical Bull Flag / Pennant breakout detection.
        Flagpole (sharp spike) followed by consolidation on lower volume, breaking out.
        """
        if len(df) < 15:
            return False
            
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values
        
        # 1. Flagpole: Impulsive rally of >= 7% within 5 to 10 days
        # Check maximum price increase in the window [-12 to -5]
        flagpole_win = close[-12:-4]
        if len(flagpole_win) < 2:
            return False
        min_price = np.min(flagpole_win)
        max_price = np.max(flagpole_win)
        flagpole_rise = (max_price - min_price) / min_price
        
        if flagpole_rise < 0.07:
            return False
            
        # 2. Consolidation Flag: Last 3 to 5 days should be trading in a tight range
        flag_highs = high[-5:-1]
        flag_lows = low[-5:-1]
        flag_range = (np.max(flag_highs) - np.min(flag_lows)) / np.max(flag_highs)
        
        # Consolidation should be tight (< 8% high-to-low range)
        if flag_range > 0.08:
            return False
            
        # Volume should be declining during consolidation compared to flagpole
        flag_avg_vol = np.mean(volume[-5:-1])
        flagpole_avg_vol = np.mean(volume[-12:-5])
        if flag_avg_vol > flagpole_avg_vol:
            return False
            
        # 3. Breakout: Latest close breaks out above flag consolidation high
        latest_close = close[-1]
        flag_limit = np.max(flag_highs)
        avg_vol = df['volume_avg_20'].iloc[-1] if 'volume_avg_20' in df.columns else np.mean(volume[-20:])
        
        is_breakout = latest_close > flag_limit and volume[-1] > avg_vol * 1.1
        return bool(is_breakout)
