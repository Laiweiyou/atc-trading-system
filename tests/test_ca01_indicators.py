# -*- coding: utf-8 -*-
"""Tests for CA-01 阿盧+伶伶（指標計算 + 覆核）— Phase 3 Step 8."""
import io
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import SubReport
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.technical.ca_01_indicators import (
    IndicatorCalculator,
    IndicatorReviewer,
    IndicatorSection,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_klines(n: int, start: float = 100.0, delta: float = 0.0) -> list:
    """Build n chronological klines: close = start + i*delta."""
    return [
        {
            "timestamp": i * 1000,
            "open":  start + i * delta,
            "high":  start + i * delta + 1.0,
            "low":   start + i * delta - 1.0,
            "close": start + i * delta,
            "volume": 1000.0,
        }
        for i in range(n)
    ]


def _to_bybit_raw(klines: list) -> list:
    """Convert chronological klines → Bybit newest-first raw list format."""
    return [
        [k["timestamp"], k["open"], k["high"], k["low"], k["close"], k["volume"], 0]
        for k in reversed(klines)
    ]


def _make_gateway(main_klines, eth24=None, btc24=None):
    """Mock gateway whose get_market_kline dispatches by (symbol, limit)."""
    gw = MagicMock()

    def side_effect(symbol, interval, limit=200):
        if limit == 200:
            return {"success": True, "data": {"list": _to_bybit_raw(main_klines)}}
        if symbol == "ETHUSDT":
            return ({"success": True, "data": {"list": _to_bybit_raw(eth24)}}
                    if eth24 is not None else {"success": False})
        return ({"success": True, "data": {"list": _to_bybit_raw(btc24)}}
                if btc24 is not None else {"success": False})

    gw.get_market_kline.side_effect = side_effect
    return gw


def _fresh_alu(main_klines=None, eth24=None, btc24=None) -> IndicatorCalculator:
    get_bus().clear()
    gw = _make_gateway(main_klines or _make_klines(200, 100.0), eth24, btc24)
    return IndicatorCalculator(gateway=gw)


def _fresh_section(main_klines=None, eth24=None, btc24=None) -> IndicatorSection:
    get_bus().clear()
    gw = _make_gateway(main_klines or _make_klines(200, 100.0), eth24, btc24)
    return IndicatorSection(gateway=gw)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCA01Indicators(unittest.TestCase):

    # ── 01: RSI=100 for all-up klines ────────────────────────────────────────

    def test_01_rsi_all_up_returns_100(self):
        alu = _fresh_alu()
        klines = _make_klines(20, 100.0, 1.0)   # closes rise each bar
        rsi = alu.calculate_rsi(klines, period=14)
        self.assertIsNotNone(rsi)
        self.assertAlmostEqual(rsi, 100.0)

    # ── 02: RSI=0 for all-down klines ────────────────────────────────────────

    def test_02_rsi_all_down_returns_0(self):
        alu = _fresh_alu()
        klines = _make_klines(20, 200.0, -1.0)  # closes fall each bar
        rsi = alu.calculate_rsi(klines, period=14)
        self.assertIsNotNone(rsi)
        self.assertAlmostEqual(rsi, 0.0)

    # ── 03: RSI returns None when insufficient data ───────────────────────────

    def test_03_rsi_insufficient_data_returns_none(self):
        alu = _fresh_alu()
        klines = _make_klines(10, 100.0)        # need period+1 = 15
        rsi = alu.calculate_rsi(klines, period=14)
        self.assertIsNone(rsi)

    # ── 04: MA equals price for flat klines ──────────────────────────────────

    def test_04_ma_flat_klines_equals_price(self):
        alu = _fresh_alu()
        klines = _make_klines(200, 100.0, 0.0)   # 200 bars needed for MA-200
        ma20  = alu.calculate_ma(klines, 20)
        ma50  = alu.calculate_ma(klines, 50)
        ma200 = alu.calculate_ma(klines, 200)
        self.assertAlmostEqual(ma20,  100.0)
        self.assertAlmostEqual(ma50,  100.0)
        self.assertAlmostEqual(ma200, 100.0)

    # ── 05: MA returns None when insufficient data ────────────────────────────

    def test_05_ma_insufficient_data_returns_none(self):
        alu = _fresh_alu()
        klines = _make_klines(10, 100.0)
        self.assertIsNone(alu.calculate_ma(klines, 20))

    # ── 06: EMA equals price for flat klines ─────────────────────────────────

    def test_06_ema_flat_klines_equals_price(self):
        alu = _fresh_alu()
        klines = _make_klines(50, 100.0, 0.0)
        ema = alu.calculate_ema(klines, 26)
        self.assertIsNotNone(ema)
        self.assertAlmostEqual(ema, 100.0, places=5)

    # ── 07: Bollinger Bands lower < middle < upper ────────────────────────────

    def test_07_bollinger_bounds_ordered(self):
        alu = _fresh_alu()
        # alternating prices ensure std > 0
        klines = [
            {"timestamp": i * 1000, "open": 100.0, "high": 101.0, "low": 99.0,
             "close": 100.0 + (i % 3) - 1.0, "volume": 1000.0}
            for i in range(50)
        ]
        bb = alu.calculate_bollinger(klines, 20, 2.0)
        self.assertIsNotNone(bb)
        self.assertLess(bb["lower"],  bb["middle"])
        self.assertLess(bb["middle"], bb["upper"])
        self.assertIn("bandwidth", bb)

    # ── 08: ETH/BTC ratio structure and ETH stronger ─────────────────────────

    def test_08_eth_btc_ratio_structure(self):
        alu = _fresh_alu()
        eth_klines = _make_klines(24, 2000.0, 5.0)    # rising ETH
        btc_klines = _make_klines(24, 60000.0, 0.0)   # flat BTC

        # mock fetch_klines directly (avoids gateway raw-format complexity)
        def mock_fetch(symbol, interval, limit=200):
            return eth_klines if symbol == "ETHUSDT" else btc_klines
        alu.fetch_klines = mock_fetch

        result = alu.calculate_eth_btc_ratio()

        self.assertIsNotNone(result)
        for key in ("eth_change_24h", "btc_change_24h", "relative_strength"):
            self.assertIn(key, result)
        self.assertGreater(result["relative_strength"], 0)   # ETH outperforms BTC

    # ── 09: Reviewer catches invalid RSI ─────────────────────────────────────

    def test_09_reviewer_invalid_rsi_fails(self):
        reviewer = IndicatorReviewer(MagicMock())
        indicators = {
            "rsi_14":        120.0,   # invalid — must be 0-100
            "current_price": 2000.0,
            "bollinger":     None,
            "macd":          None,
        }
        result = reviewer.review_indicators(indicators)
        self.assertEqual(result["status"], "failed")
        self.assertGreater(result["issue_count"], 0)
        self.assertTrue(any("RSI" in msg for msg in result["issues"]))

    # ── 10: Reviewer passes clean indicators ─────────────────────────────────

    def test_10_reviewer_clean_indicators_passes(self):
        reviewer = IndicatorReviewer(MagicMock())
        indicators = {
            "rsi_14":        55.0,
            "current_price": 2000.0,
            "ma_20":         1950.0,
            "ma_50":         1900.0,
            "ma_200":        1800.0,
            "bollinger":     {"lower": 1850.0, "middle": 1950.0,
                              "upper": 2050.0, "bandwidth": 5.0},
            "macd":          {"macd": 30.0, "ema_12": 2010.0, "ema_26": 1980.0},
            "eth_btc":       None,
        }
        result = reviewer.review_indicators(indicators)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["issue_count"], 0)

    # ── 11: _derive_direction: perfect bullish alignment ─────────────────────

    def test_11_derive_perfect_bullish_alignment(self):
        section = _fresh_section()
        ind = {
            "current_price": 100.0,
            "rsi_14":        55.0,    # no RSI signal
            "ma_20":          90.0,
            "ma_50":          80.0,
            "ma_200":         70.0,
            "macd":           None,
            "bollinger":      None,
            "eth_btc":        None,
        }
        direction, confidence, reasoning = section._derive_direction(ind)
        self.assertEqual(direction, "bullish")
        self.assertIn("多頭", reasoning)

    # ── 12: _derive_direction: perfect bearish alignment ─────────────────────

    def test_12_derive_perfect_bearish_alignment(self):
        section = _fresh_section()
        ind = {
            "current_price": 70.0,
            "rsi_14":        45.0,    # no RSI signal
            "ma_20":          80.0,
            "ma_50":          90.0,
            "ma_200":        100.0,
            "macd":           None,
            "bollinger":      None,
            "eth_btc":        None,
        }
        direction, confidence, reasoning = section._derive_direction(ind)
        self.assertEqual(direction, "bearish")
        self.assertIn("空頭", reasoning)

    # ── 13: _derive_direction: RSI oversold → bullish signal ─────────────────

    def test_13_derive_rsi_oversold_bullish(self):
        section = _fresh_section()
        ind = {
            "current_price": 100.0,
            "rsi_14":         20.0,   # < 30 → oversold bullish 0.3
            "ma_20":         None,
            "ma_50":         None,
            "ma_200":        None,
            "macd":          None,
            "bollinger":     None,
            "eth_btc":       None,
        }
        direction, confidence, reasoning = section._derive_direction(ind)
        self.assertEqual(direction, "bullish")
        self.assertIn("超賣", reasoning)

    # ── 14: compute_with_review returns valid SubReport ───────────────────────

    def test_14_compute_with_review_returns_subreport(self):
        main  = _make_klines(200, 2000.0, 0.5)
        eth24 = _make_klines(24,  2000.0, 5.0)
        btc24 = _make_klines(24, 60000.0, 0.0)
        section = _fresh_section(main, eth24, btc24)

        report = section.compute_with_review()

        self.assertIsInstance(report, SubReport)
        self.assertFalse(report.staleness_flag)
        self.assertIn("indicators",    report.data_used)
        self.assertIn("review_result", report.data_used)
        self.assertIn(report.direction, ("bullish", "bearish", "neutral"))
        self.assertGreaterEqual(report.sub_confidence, 0.0)

    # ── 15: compute_with_review applies review penalty when issues found ──────

    def test_15_review_penalty_applied_on_issues(self):
        section = _fresh_section()
        # inject bad indicators (RSI=120) so reviewer fires
        bad_ind = {
            "symbol": "ETHUSDT", "interval": "60",
            "current_price": 2000.0,
            "rsi_14":        120.0,        # out of range → review fail
            "ma_20":         1990.0,
            "ma_50":         1980.0,
            "ma_200":        1970.0,
            "ema_12": 2010.0, "ema_26": 1980.0,
            "macd":    {"macd": 30.0, "ema_12": 2010.0, "ema_26": 1980.0},
            "bollinger": {"lower": 1900.0, "middle": 1990.0,
                          "upper": 2080.0, "bandwidth": 4.5},
            "kline_count": 200,
            "timestamp": datetime.now(),
            "eth_btc": None,
        }
        section.alu.compute_all_indicators = MagicMock(return_value=bad_ind)

        report = section.compute_with_review()

        review = report.data_used["review_result"]
        self.assertEqual(review["status"], "failed")
        self.assertGreater(review["issue_count"], 0)
        # penalty should be reflected in the reasoning suffix
        self.assertIn("覆核發現", report.reasoning)

    # ── 16: compute_with_review returns stale SubReport if no klines ─────────

    def test_16_no_klines_returns_stale_subreport(self):
        gw = MagicMock()
        gw.get_market_kline.return_value = {"success": False}
        get_bus().clear()
        section = IndicatorSection(gateway=gw)

        report = section.compute_with_review()

        self.assertIsInstance(report, SubReport)
        self.assertTrue(report.staleness_flag)
        self.assertEqual(report.direction, "neutral")

    # ── 17: fetch_klines reverses Bybit newest-first order ───────────────────

    def test_17_fetch_klines_reverses_bybit_order(self):
        # Bybit sends newest-first: [ts=3, ts=2, ts=1]
        # fetch_klines must reverse → [ts=1, ts=2, ts=3] (chronological)
        gw = MagicMock()
        gw.get_market_kline.return_value = {
            "success": True,
            "data": {"list": [
                [3000, 103, 104, 102, 103, 1000, 0],   # newest
                [2000, 102, 103, 101, 102, 1000, 0],
                [1000, 101, 102, 100, 101, 1000, 0],   # oldest
            ]},
        }
        get_bus().clear()
        alu = IndicatorCalculator(gateway=gw)
        klines = alu.fetch_klines("ETHUSDT", "60", limit=3)

        self.assertEqual(len(klines), 3)
        self.assertEqual(klines[0]["timestamp"], 1000)   # oldest first
        self.assertEqual(klines[-1]["timestamp"], 3000)  # newest last


if __name__ == "__main__":
    unittest.main(verbosity=2)
