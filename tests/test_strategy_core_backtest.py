# -*- coding: utf-8 -*-
"""tests/test_strategy_core_backtest.py — 10 個測試組，覆蓋策略核心回測所有邏輯。"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from unittest.mock import MagicMock, patch

from trading_system.common.message_bus import reset_bus
from trading_system.evolution.strategy_core_backtest import StrategyCoreBacktest


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_flat_klines(n: int = 100, price: float = 3000.0) -> list:
    """Flat klines: price unchanged, ATR = 6, MA20 = MA50 = price, RSI = 50."""
    return [{
        "timestamp": 1700000000000 + i * 3600000,
        "open":      price,
        "high":      price + 3.0,
        "low":       price - 3.0,
        "close":     price,
        "volume":    1000.0,
    } for i in range(n)]


def _make_trending_klines(n: int = 200, start: float = 2700.0) -> list:
    """Declining then rising klines — triggers RSI / MA signals."""
    klines = []
    for i in range(n):
        if i < 80:
            p = start + i * (-2.5)          # 2700 → 2500 (declining)
        else:
            p = (start - 80 * 2.5) + (i - 80) * 3.0   # 2500 → rising
        noise = ((i * 7) % 11 - 5) * 2.0
        p = max(1.0, p + noise)
        klines.append({
            "timestamp": 1700000000000 + i * 3600000,
            "open":      p * 0.999,
            "high":      p * 1.008,
            "low":       p * 0.992,
            "close":     p,
            "volume":    1000.0,
        })
    return klines


def _fresh_bt() -> StrategyCoreBacktest:
    reset_bus()
    gw = MagicMock()
    gw.get_market_kline.return_value = {"success": False}
    return StrategyCoreBacktest(gateway=gw)


def _inject_trades(bt: StrategyCoreBacktest,
                   wins: int, win_pnl: float,
                   losses: int, loss_pnl: float) -> None:
    """Inject synthetic trade records directly into bt.trades."""
    template = {
        "direction": "long", "entry_price": 3000.0, "size_usd": 60.0,
        "entry_idx": 50, "exit_idx": 51, "exit_price": 3000.0,
        "stop_loss": 2940.0, "take_profit": 3120.0,
    }
    for _ in range(wins):
        bt.trades.append({**template, "pnl_usd": win_pnl, "exit_reason": "take_profit"})
    for _ in range(losses):
        bt.trades.append({**template, "pnl_usd": loss_pnl, "exit_reason": "stop_loss"})


# ─── Group 01: 初始化 ─────────────────────────────────────────────────────────

class TestGroup01_Initialization(unittest.TestCase):

    def setUp(self):
        self.bt = _fresh_bt()

    def test_01_role_name(self):
        self.assertEqual(self.bt.role_name, "Strategy-Core-Backtest")

    def test_02_initial_capital(self):
        self.assertEqual(self.bt.initial_capital, 200.0)

    def test_03_max_position_usd(self):
        self.assertEqual(self.bt.max_position_usd, 100.0)

    def test_04_empty_trades_on_init(self):
        self.assertEqual(len(self.bt.trades), 0)

    def test_05_empty_curves_on_init(self):
        self.assertEqual(len(self.bt.equity_curve), 0)
        self.assertEqual(len(self.bt.bh_curve), 0)


# ─── Group 02: 指標計算 ───────────────────────────────────────────────────────

class TestGroup02_IndicatorCalculation(unittest.TestCase):

    def setUp(self):
        self.bt = _fresh_bt()
        self.klines = _make_flat_klines(70, 3000.0)

    def test_01_returns_none_when_index_below_50(self):
        self.assertIsNone(self.bt.calculate_indicators(self.klines, 49))

    def test_02_returns_none_at_index_49(self):
        self.assertIsNone(self.bt.calculate_indicators(self.klines, 30))

    def test_03_returns_dict_at_index_50(self):
        result = self.bt.calculate_indicators(self.klines, 50)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_04_ma20_correct_for_flat(self):
        result = self.bt.calculate_indicators(self.klines, 60)
        self.assertAlmostEqual(result["ma_20"], 3000.0)

    def test_05_ma50_correct_for_flat(self):
        result = self.bt.calculate_indicators(self.klines, 60)
        self.assertAlmostEqual(result["ma_50"], 3000.0)

    def test_06_rsi_is_50_for_flat(self):
        result = self.bt.calculate_indicators(self.klines, 60)
        self.assertAlmostEqual(result["rsi_14"], 50.0)

    def test_07_atr_positive_when_candles_have_range(self):
        result = self.bt.calculate_indicators(self.klines, 60)
        self.assertGreater(result["atr_14"], 0)

    def test_08_current_price_matches_close(self):
        result = self.bt.calculate_indicators(self.klines, 60)
        self.assertAlmostEqual(result["current_price"], 3000.0)


# ─── Group 03: 方向判斷 ───────────────────────────────────────────────────────

class TestGroup03_DirectionDerivation(unittest.TestCase):

    def setUp(self):
        self.bt = _fresh_bt()

    def _ind(self, price, ma20, ma50, rsi):
        return {"current_price": price, "ma_20": ma20, "ma_50": ma50,
                "rsi_14": rsi, "atr_14": 50.0}

    def test_01_bullish_rsi_and_ma_alignment(self):
        # RSI < 35 → (+0.3) and price > ma20 > ma50 → (+0.4) = bullish_w 0.7
        direction, conf = self.bt.derive_direction(
            self._ind(3100.0, 3050.0, 3000.0, 30.0))
        self.assertEqual(direction, "bullish")
        self.assertGreater(conf, 0)

    def test_02_bearish_rsi_and_ma_alignment(self):
        # RSI > 65 → (+0.3) and price < ma20 < ma50 → (+0.4) = bearish_w 0.7
        direction, conf = self.bt.derive_direction(
            self._ind(2900.0, 2950.0, 3000.0, 70.0))
        self.assertEqual(direction, "bearish")
        self.assertGreater(conf, 0)

    def test_03_neutral_when_rsi_mid_and_no_ma_divergence(self):
        direction, conf = self.bt.derive_direction(
            self._ind(3000.0, 3000.0, 3000.0, 50.0))
        self.assertEqual(direction, "neutral")
        self.assertEqual(conf, 0)

    def test_04_none_indicator_returns_neutral(self):
        direction, conf = self.bt.derive_direction(None)
        self.assertEqual(direction, "neutral")
        self.assertEqual(conf, 0)

    def test_05_confidence_bounded_at_0_95(self):
        _, conf = self.bt.derive_direction(
            self._ind(3100.0, 3050.0, 3000.0, 30.0))
        self.assertLessEqual(conf, 0.95)

    def test_06_only_rsi_below_35_returns_bullish(self):
        # Only RSI signal, no MA alignment (flat)
        direction, _ = self.bt.derive_direction(
            self._ind(3000.0, 3000.0, 3000.0, 25.0))
        self.assertEqual(direction, "bullish")

    def test_07_only_rsi_above_65_returns_bearish(self):
        direction, _ = self.bt.derive_direction(
            self._ind(3000.0, 3000.0, 3000.0, 75.0))
        self.assertEqual(direction, "bearish")


# ─── Group 04: 回測結果結構 ───────────────────────────────────────────────────

class TestGroup04_BacktestStructure(unittest.TestCase):

    def setUp(self):
        self.bt = _fresh_bt()
        with patch.object(self.bt, "fetch_historical_klines",
                          return_value=_make_flat_klines(150, 3000.0)):
            self.result = self.bt.run_backtest()

    def test_01_returns_success_true(self):
        self.assertTrue(self.result.get("success"))

    def test_02_has_total_trades_key(self):
        self.assertIn("total_trades", self.result)

    def test_03_has_win_rate_key(self):
        self.assertIn("win_rate", self.result)

    def test_04_has_expected_value_key(self):
        self.assertIn("expected_value", self.result)

    def test_05_has_criteria_dict(self):
        self.assertIn("criteria", self.result)
        self.assertIsInstance(self.result["criteria"], dict)

    def test_06_has_all_required_keys(self):
        for key in ("total_trades", "wins", "losses", "win_rate",
                    "avg_win_usd", "avg_loss_usd", "profit_loss_ratio",
                    "expected_value", "total_pnl_usd", "total_return_pct",
                    "max_drawdown_pct", "bh_return_pct", "diff_vs_bh_pct"):
            self.assertIn(key, self.result)

    def test_07_insufficient_data_returns_failure(self):
        bt = _fresh_bt()
        with patch.object(bt, "fetch_historical_klines", return_value=_make_flat_klines(50)):
            result = bt.run_backtest()
        self.assertFalse(result.get("success"))


# ─── Group 05: 止損觸發 ───────────────────────────────────────────────────────

class TestGroup05_StopLossTrigger(unittest.TestCase):

    def _run_with_stop(self):
        """Run backtest where stop_loss fires at candle 51."""
        bt = _fresh_bt()
        price = 3000.0
        klines = _make_flat_klines(110, price)   # must be >= 100
        # Candle 51: low drops below stop_loss (3000 * 0.98 = 2940)
        klines[51]["low"]   = 2929.0
        klines[51]["close"] = 2929.0

        signal_given = [False]
        def mock_dir(ind):
            if not signal_given[0]:
                signal_given[0] = True
                return ("bullish", 0.6)
            return ("neutral", 0)

        mock_ind = {"current_price": price, "ma_20": 2950.0,
                    "ma_50": 2900.0, "rsi_14": 30.0, "atr_14": 30.0}

        with patch.object(bt, "fetch_historical_klines", return_value=klines):
            with patch.object(bt, "calculate_indicators", return_value=mock_ind):
                with patch.object(bt, "derive_direction", side_effect=mock_dir):
                    bt.run_backtest()
        return bt

    def test_01_stop_loss_trade_recorded(self):
        bt = self._run_with_stop()
        stop_trades = [t for t in bt.trades if t["exit_reason"] == "stop_loss"]
        self.assertGreater(len(stop_trades), 0)

    def test_02_exit_reason_is_stop_loss(self):
        bt = self._run_with_stop()
        first_stop = next(t for t in bt.trades if t["exit_reason"] == "stop_loss")
        self.assertEqual(first_stop["exit_reason"], "stop_loss")

    def test_03_exit_price_at_stop_loss_level(self):
        bt = self._run_with_stop()
        first_stop = next(t for t in bt.trades if t["exit_reason"] == "stop_loss")
        # stop_loss = 3000 * 0.98 = 2940
        self.assertAlmostEqual(first_stop["exit_price"], 3000.0 * 0.98, places=2)

    def test_04_pnl_is_negative_for_stop_loss(self):
        bt = self._run_with_stop()
        first_stop = next(t for t in bt.trades if t["exit_reason"] == "stop_loss")
        self.assertLess(first_stop["pnl_usd"], 0)


# ─── Group 06: 止盈觸發 ───────────────────────────────────────────────────────

class TestGroup06_TakeProfitTrigger(unittest.TestCase):

    def _run_with_tp(self):
        """Run backtest where take_profit fires at candle 51."""
        bt = _fresh_bt()
        price = 3000.0
        klines = _make_flat_klines(110, price)   # must be >= 100
        # Candle 51: high exceeds take_profit (3000 * 1.04 = 3120)
        # low stays at 2997 > 2940, so stop_loss does NOT trigger first
        klines[51]["high"]  = 3150.0
        klines[51]["close"] = 3150.0

        signal_given = [False]
        def mock_dir(ind):
            if not signal_given[0]:
                signal_given[0] = True
                return ("bullish", 0.6)
            return ("neutral", 0)

        mock_ind = {"current_price": price, "ma_20": 2950.0,
                    "ma_50": 2900.0, "rsi_14": 30.0, "atr_14": 30.0}

        with patch.object(bt, "fetch_historical_klines", return_value=klines):
            with patch.object(bt, "calculate_indicators", return_value=mock_ind):
                with patch.object(bt, "derive_direction", side_effect=mock_dir):
                    bt.run_backtest()
        return bt

    def test_01_take_profit_trade_recorded(self):
        bt = self._run_with_tp()
        tp_trades = [t for t in bt.trades if t["exit_reason"] == "take_profit"]
        self.assertGreater(len(tp_trades), 0)

    def test_02_exit_reason_is_take_profit(self):
        bt = self._run_with_tp()
        first_tp = next(t for t in bt.trades if t["exit_reason"] == "take_profit")
        self.assertEqual(first_tp["exit_reason"], "take_profit")

    def test_03_exit_price_at_take_profit_level(self):
        bt = self._run_with_tp()
        first_tp = next(t for t in bt.trades if t["exit_reason"] == "take_profit")
        # take_profit = 3000 * 1.04 = 3120
        self.assertAlmostEqual(first_tp["exit_price"], 3000.0 * 1.04, places=2)

    def test_04_pnl_is_positive_for_take_profit(self):
        bt = self._run_with_tp()
        first_tp = next(t for t in bt.trades if t["exit_reason"] == "take_profit")
        self.assertGreater(first_tp["pnl_usd"], 0)


# ─── Group 07: 期望值計算 ─────────────────────────────────────────────────────

class TestGroup07_ExpectedValue(unittest.TestCase):

    def setUp(self):
        self.bt = _fresh_bt()
        # 5 wins × $4, 3 losses × -$2 → win_rate=0.625, ratio=2.0, EV=1.25
        _inject_trades(self.bt, wins=5, win_pnl=4.0, losses=3, loss_pnl=-2.0)
        self.bt.equity_curve = [{"idx": 0, "timestamp": 0, "equity": 200.0}]
        self.bt.bh_curve     = [{"idx": 0, "value": 200.0}]
        # final_capital = 200 + 5*4 - 3*2 = 200 + 14 = 214
        self.result = self.bt.compute_results(214.0, [])

    def test_01_expected_value_above_1(self):
        self.assertGreater(self.result["expected_value"], 1.0)

    def test_02_win_rate_correct(self):
        self.assertAlmostEqual(self.result["win_rate"], 5 / 8)

    def test_03_avg_win_correct(self):
        self.assertAlmostEqual(self.result["avg_win_usd"], 4.0)

    def test_04_avg_loss_correct(self):
        self.assertAlmostEqual(self.result["avg_loss_usd"], 2.0)

    def test_05_profit_loss_ratio_correct(self):
        self.assertAlmostEqual(self.result["profit_loss_ratio"], 2.0)

    def test_06_passed_is_true_when_ev_above_1(self):
        self.assertTrue(self.result["passed"])

    def test_07_passed_is_false_when_ev_below_1(self):
        bt = _fresh_bt()
        # 2 wins × $1, 5 losses × -$3 → EV = (2/7)*(1/3) ≈ 0.095 < 1
        _inject_trades(bt, wins=2, win_pnl=1.0, losses=5, loss_pnl=-3.0)
        bt.equity_curve = [{"idx": 0, "timestamp": 0, "equity": 200.0}]
        bt.bh_curve     = [{"idx": 0, "value": 200.0}]
        result = bt.compute_results(200 + 2 - 15, [])
        self.assertFalse(result["passed"])


# ─── Group 08: 完整回測執行（模擬真實資料）────────────────────────────────────

class TestGroup08_FullBacktestRun(unittest.TestCase):

    def setUp(self):
        self.bt = _fresh_bt()
        with patch.object(self.bt, "fetch_historical_klines",
                          return_value=_make_trending_klines(200)):
            self.result = self.bt.run_backtest()

    def test_01_returns_success_true(self):
        self.assertTrue(self.result.get("success"))

    def test_02_all_required_keys_present(self):
        for key in ("total_trades", "wins", "losses", "win_rate",
                    "profit_loss_ratio", "expected_value", "total_pnl_usd",
                    "max_drawdown_pct", "bh_return_pct", "diff_vs_bh_pct",
                    "criteria", "passed"):
            self.assertIn(key, self.result)

    def test_03_equity_curve_populated(self):
        self.assertGreater(len(self.bt.equity_curve), 0)

    def test_04_bh_curve_populated(self):
        self.assertGreater(len(self.bt.bh_curve), 0)

    def test_05_total_trades_non_negative(self):
        self.assertGreaterEqual(self.result["total_trades"], 0)

    def test_06_win_rate_between_0_and_1(self):
        wr = self.result["win_rate"]
        self.assertGreaterEqual(wr, 0)
        self.assertLessEqual(wr, 1)


# ─── Group 09: 最大回撤計算 ───────────────────────────────────────────────────

class TestGroup09_MaxDrawdown(unittest.TestCase):

    def test_01_zero_drawdown_for_flat_equity(self):
        bt = _fresh_bt()
        bt.equity_curve = [{"idx": i, "timestamp": i, "equity": 200.0} for i in range(5)]
        bt.bh_curve     = [{"idx": 0, "value": 200.0}]
        result = bt.compute_results(200.0, [])
        self.assertAlmostEqual(result["max_drawdown_pct"], 0.0)

    def test_02_correct_drawdown_for_known_curve(self):
        bt = _fresh_bt()
        # Equity: 200 → 220 (peak) → 190 → drawdown = (220-190)/220 * 100
        bt.equity_curve = [
            {"idx": 0, "timestamp": 0, "equity": 200.0},
            {"idx": 1, "timestamp": 1, "equity": 220.0},
            {"idx": 2, "timestamp": 2, "equity": 190.0},
        ]
        bt.bh_curve = [{"idx": 0, "value": 200.0}]
        result = bt.compute_results(190.0, [])
        expected_dd = (220.0 - 190.0) / 220.0 * 100
        self.assertAlmostEqual(result["max_drawdown_pct"], expected_dd, places=4)

    def test_03_drawdown_always_non_negative(self):
        bt = _fresh_bt()
        # Rising equity → no drawdown
        bt.equity_curve = [{"idx": i, "timestamp": i, "equity": 200.0 + i * 5} for i in range(10)]
        bt.bh_curve = [{"idx": 0, "value": 200.0}]
        result = bt.compute_results(245.0, [])
        self.assertGreaterEqual(result["max_drawdown_pct"], 0)

    def test_04_drawdown_uses_initial_capital_as_starting_peak(self):
        bt = _fresh_bt()
        # Equity immediately drops to 180
        bt.equity_curve = [{"idx": 0, "timestamp": 0, "equity": 180.0}]
        bt.bh_curve = [{"idx": 0, "value": 200.0}]
        result = bt.compute_results(180.0, [])
        # Peak starts at initial_capital=200 → dd = (200-180)/200 * 100 = 10%
        self.assertAlmostEqual(result["max_drawdown_pct"], 10.0, places=4)


# ─── Group 10: vs Buy & Hold 比較 ────────────────────────────────────────────

class TestGroup10_VsBuyAndHold(unittest.TestCase):

    def _result_with_bh(self, final_capital: float, bh_final: float) -> dict:
        bt = _fresh_bt()
        bt.equity_curve = [{"idx": 0, "timestamp": 0, "equity": final_capital}]
        bt.bh_curve     = [{"idx": 0, "value": bh_final}]
        return bt.compute_results(final_capital, [])

    def test_01_correct_diff_when_system_beats_bh(self):
        # system +10% = 220, bh +5% = 210 → diff = +5%
        result = self._result_with_bh(220.0, 210.0)
        self.assertAlmostEqual(result["diff_vs_bh_pct"], 5.0, places=3)

    def test_02_negative_diff_when_bh_beats_system(self):
        # system 0% = 200, bh +10% = 220 → diff = -10%
        result = self._result_with_bh(200.0, 220.0)
        self.assertAlmostEqual(result["diff_vs_bh_pct"], -10.0, places=3)

    def test_03_zero_diff_when_tied(self):
        result = self._result_with_bh(220.0, 220.0)
        self.assertAlmostEqual(result["diff_vs_bh_pct"], 0.0, places=3)

    def test_04_acceptable_vs_bh_true_when_within_5pct(self):
        result = self._result_with_bh(200.0, 208.0)   # diff = -4% > -5
        self.assertTrue(result["criteria"]["acceptable_vs_bh"])

    def test_05_acceptable_vs_bh_false_when_below_minus5(self):
        result = self._result_with_bh(200.0, 215.0)   # diff = -7.5% < -5
        self.assertFalse(result["criteria"]["acceptable_vs_bh"])

    def test_06_bh_return_pct_calculated_correctly(self):
        result = self._result_with_bh(200.0, 220.0)
        self.assertAlmostEqual(result["bh_return_pct"], 10.0, places=3)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("StrategyCoreBacktest Tests  (10 groups)")
    print("=" * 60)
    unittest.main(verbosity=2)
