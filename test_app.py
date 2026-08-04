import unittest
import pandas as pd
from quant_engine import QuantitativeEngine
from pattern_detector import PatternDetector

class TestTradingApp(unittest.TestCase):

    def setUp(self):
        # Create a mock dataframe of 30 candles representing a downward-trending stock to trigger RSI oversold
        self.candles_down = pd.DataFrame({
            "open":  [100.0 - i * 1.5 for i in range(30)],
            "high":  [102.0 - i * 1.5 for i in range(30)],
            "low":   [99.0 - i * 1.5 for i in range(30)],
            "close": [100.0 - i * 1.5 for i in range(30)],
            "volume": [1000 + i * 10 for i in range(30)]
        })

    def test_quantitative_engine_indicators(self):
        df_indicators = QuantitativeEngine.calculate_indicators(self.candles_down.copy())
        
        # Verify indicators are added
        self.assertIn("rsi", df_indicators.columns)
        self.assertIn("sma_20", df_indicators.columns)
        self.assertIn("ema_50", df_indicators.columns)
        self.assertIn("vwap", df_indicators.columns)
        self.assertIn("bb_width", df_indicators.columns)
        self.assertIn("pivot", df_indicators.columns)
        
        # Verify the calculation is non-empty for values after the window length
        self.assertFalse(df_indicators['rsi'].iloc[-1] is None)

    def test_pattern_detection(self):
        df_patterns = PatternDetector.detect_candlesticks(self.candles_down.copy())
        self.assertIn("pattern_doji", df_patterns.columns)
        self.assertIn("pattern_hammer", df_patterns.columns)
        self.assertIn("pattern_shooting_star", df_patterns.columns)

    def test_support_resistance(self):
        levels = QuantitativeEngine.detect_support_resistance(self.candles_down, window=5)
        self.assertIn("supports", levels)
        self.assertIn("resistances", levels)

if __name__ == "__main__":
    unittest.main()
