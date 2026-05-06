# -*- coding: utf-8 -*-
"""tests/test_baseline_comparator.py — 12 個測試組，覆蓋阿柯（BaselineComparator）所有核心邏輯。"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from unittest.mock import MagicMock, patch

import trading_system.common.config as _cfg
from trading_system.common.message_bus import get_bus, reset_bus
from trading_system.evolution.baseline_comparator import BaselineComparator


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_kline_result(price: float) -> dict:
    return {
        "success": True,
        "data": {"list": [["1700000000000", "0", "0", "0", str(price), "0"]]},
    }


def _make_failed_result() -> dict:
    return {"success": False}


def _fresh(initial_eth_price: float = 2000.0, current_eth_price: float = 2000.0):
    """Reset bus + create fresh BaselineComparator with mocked gateway."""
    reset_bus()
    gw = MagicMock()
    gw.get_market_kline.return_value = _make_kline_result(current_eth_price)
    comp = BaselineComparator(gateway=gw, initial_eth_price=initial_eth_price)
    return comp, gw


# ─── Group 01: 初始化與訂閱 ────────────────────────────────────────────────────

class TestGroup01_Initialization(unittest.TestCase):

    def setUp(self):
        self.comp, self.gw = _fresh()

    def test_01_role_name(self):
        self.assertEqual(self.comp.role_name, "阿柯")

    def test_02_role_code(self):
        self.assertEqual(self.comp.role_code, "TO-03")

    def test_03_initial_capital(self):
        self.assertEqual(self.comp.initial_capital, _cfg.INITIAL_CAPITAL_USD)

    def test_04_bh_initial_eth_amount(self):
        # 200 USD / 2000 USD-per-ETH = 0.1 ETH
        self.assertAlmostEqual(self.comp.bh_initial_eth_amount, 0.1)

    def test_05_subscribes_to_daily_pnl(self):
        subscribers = get_bus().get_subscribers("au01.daily_pnl")
        self.assertIn("TO-03", subscribers)

    def test_06_subscribes_to_status_update(self):
        subscribers = get_bus().get_subscribers("au01.status_update")
        self.assertIn("TO-03", subscribers)

    def test_07_initial_counters_zero(self):
        self.assertEqual(self.comp.consecutive_losses_to_zero, 0)
        self.assertEqual(self.comp.system_beats_bh_count, 0)
        self.assertEqual(self.comp.system_beats_zero_count, 0)

    def test_08_comparison_history_empty(self):
        self.assertEqual(len(self.comp.comparison_history), 0)


# ─── Group 02: 初始 ETH 價格取得 ─────────────────────────────────────────────

class TestGroup02_InitialEthPrice(unittest.TestCase):

    def test_01_price_respected_when_passed_directly(self):
        reset_bus()
        gw = MagicMock()
        gw.get_market_kline.return_value = _make_kline_result(1800.0)
        comp = BaselineComparator(gateway=gw, initial_eth_price=2500.0)
        self.assertEqual(comp.initial_eth_price, 2500.0)

    def test_02_price_fetched_when_not_provided(self):
        reset_bus()
        gw = MagicMock()
        gw.get_market_kline.return_value = _make_kline_result(1800.0)
        comp = BaselineComparator(gateway=gw)
        self.assertAlmostEqual(comp.initial_eth_price, 1800.0)

    def test_03_price_none_when_gateway_fails(self):
        reset_bus()
        gw = MagicMock()
        gw.get_market_kline.return_value = _make_failed_result()
        comp = BaselineComparator(gateway=gw)
        self.assertIsNone(comp.initial_eth_price)

    def test_04_bh_eth_amount_none_when_price_none(self):
        reset_bus()
        gw = MagicMock()
        gw.get_market_kline.return_value = _make_failed_result()
        comp = BaselineComparator(gateway=gw)
        self.assertIsNone(comp.bh_initial_eth_amount)

    def test_05_bh_eth_amount_correct_from_param(self):
        reset_bus()
        gw = MagicMock()
        gw.get_market_kline.return_value = _make_kline_result(3000.0)
        comp = BaselineComparator(gateway=gw, initial_eth_price=1000.0)
        # 200 / 1000 = 0.2
        self.assertAlmostEqual(comp.bh_initial_eth_amount, 0.2)


# ─── Group 03: 系統完勝（beats BH and zero）────────────────────────────────────

class TestGroup03_SystemBeatsAll(unittest.TestCase):

    def test_01_beats_bh_and_zero(self):
        # initial: 200 USD, 0.1 ETH @ 2000 → BH at 1500 = 150
        # system: 200 + 50 = 250 > 150 AND > 200
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=1500.0)
        result = comp.compute_daily_comparison("2024-01-01", 50.0)
        self.assertTrue(result["beats_bh"])
        self.assertTrue(result["beats_zero"])

    def test_02_system_value_correct(self):
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=1500.0)
        result = comp.compute_daily_comparison("2024-01-01", 50.0)
        self.assertAlmostEqual(result["system_value"], 250.0)

    def test_03_bh_value_correct(self):
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=1500.0)
        result = comp.compute_daily_comparison("2024-01-01", 50.0)
        self.assertAlmostEqual(result["bh_value"], 150.0)

    def test_04_system_beats_bh_count_increments(self):
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=1500.0)
        comp.compute_daily_comparison("2024-01-01", 50.0)
        self.assertEqual(comp.system_beats_bh_count, 1)

    def test_05_beats_zero_resets_consecutive_losses(self):
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=1500.0)
        comp.consecutive_losses_to_zero = 5
        comp.compute_daily_comparison("2024-01-01", 50.0)
        self.assertEqual(comp.consecutive_losses_to_zero, 0)

    def test_06_comment_contains_winning_word(self):
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=1500.0)
        result = comp.compute_daily_comparison("2024-01-01", 50.0)
        self.assertIn("贏", result["comment"])


# ─── Group 04: 輸給 Buy & Hold 但贏零操作 ─────────────────────────────────────

class TestGroup04_BeatsZeroNotBH(unittest.TestCase):

    def test_01_beats_zero_not_bh(self):
        # initial: 200 USD, 0.1 ETH @ 2000 → BH at 2500 = 250
        # system: 200 + 10 = 210 > 200 but < 250
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=2500.0)
        result = comp.compute_daily_comparison("2024-01-01", 10.0)
        self.assertFalse(result["beats_bh"])
        self.assertTrue(result["beats_zero"])

    def test_02_bh_value_correct(self):
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=2500.0)
        result = comp.compute_daily_comparison("2024-01-01", 10.0)
        self.assertAlmostEqual(result["bh_value"], 250.0)

    def test_03_system_beats_bh_count_not_incremented(self):
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=2500.0)
        comp.compute_daily_comparison("2024-01-01", 10.0)
        self.assertEqual(comp.system_beats_bh_count, 0)

    def test_04_system_beats_zero_count_incremented(self):
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=2500.0)
        comp.compute_daily_comparison("2024-01-01", 10.0)
        self.assertEqual(comp.system_beats_zero_count, 1)

    def test_05_comment_mentions_bh_insult(self):
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=2500.0)
        result = comp.compute_daily_comparison("2024-01-01", 10.0)
        # Should be the B&H-specific insult (bh_value is not None, beats_zero True)
        self.assertIn("ETH", result["comment"])


# ─── Group 05: 全輸（系統輸給零操作）────────────────────────────────────────────

class TestGroup05_BeatsNeither(unittest.TestCase):

    def test_01_beats_neither(self):
        # system: 200 + (-10) = 190 < 200
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=2000.0)
        result = comp.compute_daily_comparison("2024-01-01", -10.0)
        self.assertFalse(result["beats_bh"])
        self.assertFalse(result["beats_zero"])

    def test_02_consecutive_losses_increments(self):
        comp, gw = _fresh()
        comp.compute_daily_comparison("2024-01-01", -10.0)
        self.assertEqual(comp.consecutive_losses_to_zero, 1)

    def test_03_system_beats_zero_count_not_incremented(self):
        comp, gw = _fresh()
        comp.compute_daily_comparison("2024-01-01", -10.0)
        self.assertEqual(comp.system_beats_zero_count, 0)

    def test_04_comment_is_negative_insult(self):
        comp, gw = _fresh()
        result = comp.compute_daily_comparison("2024-01-01", -10.0)
        self.assertNotIn("贏了", result["comment"])
        self.assertTrue(len(result["comment"]) > 0)

    def test_05_zero_pnl_also_loses(self):
        # system_value == zero_value → beats_zero = False (not strictly greater)
        comp, gw = _fresh()
        result = comp.compute_daily_comparison("2024-01-01", 0.0)
        self.assertFalse(result["beats_zero"])


# ─── Group 06: consecutive_losses_to_zero 重置 ────────────────────────────────

class TestGroup06_ConsecutiveLossesReset(unittest.TestCase):

    def test_01_counter_accumulates_multiple_losses(self):
        comp, gw = _fresh()
        comp.compute_daily_comparison("2024-01-01", -5.0)
        comp.compute_daily_comparison("2024-01-02", -3.0)
        comp.compute_daily_comparison("2024-01-03", -1.0)
        self.assertEqual(comp.consecutive_losses_to_zero, 3)

    def test_02_counter_resets_on_win(self):
        comp, gw = _fresh()
        comp.compute_daily_comparison("2024-01-01", -5.0)
        comp.compute_daily_comparison("2024-01-02", -3.0)
        comp.compute_daily_comparison("2024-01-03", 10.0)
        self.assertEqual(comp.consecutive_losses_to_zero, 0)

    def test_03_counter_in_result_dict(self):
        comp, gw = _fresh()
        comp.compute_daily_comparison("2024-01-01", -5.0)
        result = comp.compute_daily_comparison("2024-01-02", -3.0)
        self.assertEqual(result["consecutive_losses_to_zero"], 2)

    def test_04_history_grows_correctly(self):
        comp, gw = _fresh()
        for i in range(5):
            comp.compute_daily_comparison(f"2024-01-0{i+1}", -1.0)
        self.assertEqual(len(comp.comparison_history), 5)

    def test_05_result_dict_has_date(self):
        comp, gw = _fresh()
        result = comp.compute_daily_comparison("2024-03-15", 5.0)
        self.assertEqual(result["date"], "2024-03-15")


# ─── Group 07: OVERHAUL 觸發（連續 28 天輸給零操作）──────────────────────────

class TestGroup07_OverhaulTrigger(unittest.TestCase):

    def test_01_overhaul_triggered_at_28(self):
        comp, gw = _fresh()
        with patch("trading_system.evolution.baseline_comparator.send_flash") as mock_flash:
            for i in range(28):
                comp.compute_daily_comparison(f"2024-{i+1:02d}-01", -1.0)
            self.assertTrue(mock_flash.called)

    def test_02_overhaul_uses_anomaly_flash_type(self):
        comp, gw = _fresh()
        with patch("trading_system.evolution.baseline_comparator.send_flash") as mock_flash:
            for i in range(28):
                comp.compute_daily_comparison(f"2024-{i+1:02d}-01", -1.0)
            alert = mock_flash.call_args[0][0]
            self.assertEqual(alert.alert_type, "ANOMALY_FLASH")

    def test_03_overhaul_level_is_critical(self):
        comp, gw = _fresh()
        with patch("trading_system.evolution.baseline_comparator.send_flash") as mock_flash:
            for i in range(28):
                comp.compute_daily_comparison(f"2024-{i+1:02d}-01", -1.0)
            alert = mock_flash.call_args[0][0]
            self.assertEqual(alert.alert_level, "critical")

    def test_04_overhaul_requires_acknowledgment(self):
        comp, gw = _fresh()
        with patch("trading_system.evolution.baseline_comparator.send_flash") as mock_flash:
            for i in range(28):
                comp.compute_daily_comparison(f"2024-{i+1:02d}-01", -1.0)
            alert = mock_flash.call_args[0][0]
            self.assertTrue(alert.requires_acknowledgment)

    def test_05_overhaul_related_data_count(self):
        comp, gw = _fresh()
        with patch("trading_system.evolution.baseline_comparator.send_flash") as mock_flash:
            for i in range(28):
                comp.compute_daily_comparison(f"2024-{i+1:02d}-01", -1.0)
            alert = mock_flash.call_args[0][0]
            self.assertEqual(alert.related_data["consecutive_losses_to_zero"], 28)

    def test_06_sender_is_to03(self):
        comp, gw = _fresh()
        with patch("trading_system.evolution.baseline_comparator.send_flash") as mock_flash:
            for i in range(28):
                comp.compute_daily_comparison(f"2024-{i+1:02d}-01", -1.0)
            alert = mock_flash.call_args[0][0]
            self.assertEqual(alert.sender, "TO-03")


# ─── Group 08: OVERHAUL 不提前觸發 ────────────────────────────────────────────

class TestGroup08_OverhaulNotPremature(unittest.TestCase):

    def test_01_no_overhaul_at_27(self):
        comp, gw = _fresh()
        with patch("trading_system.evolution.baseline_comparator.send_flash") as mock_flash:
            for i in range(27):
                comp.compute_daily_comparison(f"2024-{i+1:02d}-01", -1.0)
            self.assertFalse(mock_flash.called)

    def test_02_no_overhaul_when_counter_resets_before_28(self):
        comp, gw = _fresh()
        with patch("trading_system.evolution.baseline_comparator.send_flash") as mock_flash:
            for i in range(27):
                comp.compute_daily_comparison(f"2024-{i+1:02d}-01", -1.0)
            # Win on day 28 → counter resets to 0
            comp.compute_daily_comparison("2024-28-01", 10.0)
            self.assertFalse(mock_flash.called)

    def test_03_counter_is_27_after_27_losses(self):
        comp, gw = _fresh()
        with patch("trading_system.evolution.baseline_comparator.send_flash"):
            for i in range(27):
                comp.compute_daily_comparison(f"2024-{i+1:02d}-01", -1.0)
        self.assertEqual(comp.consecutive_losses_to_zero, 27)


# ─── Group 09: Bus 訂閱 au01.daily_pnl 觸發比對 ─────────────────────────────

class TestGroup09_BusSubscription(unittest.TestCase):

    def test_01_daily_pnl_message_triggers_compute(self):
        comp, gw = _fresh()
        get_bus().publish("au01.daily_pnl",
                          {"cumulative_pnl": 10.0, "date": "2024-01-01"},
                          sender="AU-01")
        self.assertEqual(len(comp.comparison_history), 1)

    def test_02_correct_pnl_extracted_from_message(self):
        comp, gw = _fresh()
        get_bus().publish("au01.daily_pnl",
                          {"cumulative_pnl": 25.0, "date": "2024-01-01"},
                          sender="AU-01")
        self.assertAlmostEqual(comp.comparison_history[0]["system_value"], 225.0)

    def test_03_non_dict_payload_ignored(self):
        comp, gw = _fresh()
        get_bus().publish("au01.daily_pnl", "invalid string", sender="AU-01")
        self.assertEqual(len(comp.comparison_history), 0)

    def test_04_dict_without_cumulative_pnl_ignored(self):
        comp, gw = _fresh()
        get_bus().publish("au01.daily_pnl", {"date": "2024-01-01"}, sender="AU-01")
        self.assertEqual(len(comp.comparison_history), 0)

    def test_05_status_update_observed_without_compute(self):
        comp, gw = _fresh()
        get_bus().publish("au01.status_update",
                          {"alert_level": "RED", "consecutive_losses": 10},
                          sender="AU-01")
        self.assertEqual(len(comp.comparison_history), 0)


# ─── Group 10: baseline.comparison 廣播 ─────────────────────────────────────

class TestGroup10_BusPublish(unittest.TestCase):

    def test_01_comparison_published_to_channel(self):
        comp, gw = _fresh()
        comp.compute_daily_comparison("2024-01-01", 5.0)
        history = get_bus().get_message_history("baseline.comparison", limit=10)
        self.assertEqual(len(history), 1)

    def test_02_published_payload_is_dict(self):
        comp, gw = _fresh()
        comp.compute_daily_comparison("2024-01-01", 5.0)
        history = get_bus().get_message_history("baseline.comparison", limit=10)
        self.assertIsInstance(history[0].payload, dict)

    def test_03_published_payload_has_required_keys(self):
        comp, gw = _fresh()
        comp.compute_daily_comparison("2024-01-01", 5.0)
        payload = get_bus().get_message_history("baseline.comparison", limit=10)[0].payload
        for key in ("date", "system_value", "bh_value", "zero_value",
                    "beats_bh", "beats_zero", "consecutive_losses_to_zero", "comment"):
            self.assertIn(key, payload)

    def test_04_sender_is_to03(self):
        comp, gw = _fresh()
        comp.compute_daily_comparison("2024-01-01", 5.0)
        msg = get_bus().get_message_history("baseline.comparison", limit=10)[0]
        self.assertEqual(msg.sender, "TO-03")

    def test_05_multiple_computes_publish_multiple_messages(self):
        comp, gw = _fresh()
        for i in range(3):
            comp.compute_daily_comparison(f"2024-01-0{i+1}", 5.0 * i)
        history = get_bus().get_message_history("baseline.comparison", limit=10)
        self.assertEqual(len(history), 3)


# ─── Group 11: get_recent_summary ────────────────────────────────────────────

class TestGroup11_RecentSummary(unittest.TestCase):

    def test_01_empty_history_returns_zeroes(self):
        comp, gw = _fresh()
        summary = comp.get_recent_summary()
        self.assertEqual(summary["days"], 0)
        self.assertEqual(summary["system_beats_bh"], 0)
        self.assertEqual(summary["system_beats_zero"], 0)

    def test_02_empty_history_returns_empty_comments(self):
        comp, gw = _fresh()
        summary = comp.get_recent_summary()
        self.assertEqual(summary["recent_comments"], [])

    def test_03_summary_counts_beats_zero(self):
        # current=1500 → BH=150, system=210 → beats both
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=1500.0)
        comp.compute_daily_comparison("2024-01-01", 10.0)
        comp.compute_daily_comparison("2024-01-02", 10.0)
        summary = comp.get_recent_summary(days=7)
        self.assertEqual(summary["system_beats_zero"], 2)

    def test_04_summary_limited_by_days(self):
        comp, gw = _fresh()
        for i in range(10):
            comp.compute_daily_comparison(f"2024-01-{i+1:02d}", 5.0)
        summary = comp.get_recent_summary(days=5)
        self.assertEqual(summary["days"], 5)

    def test_05_summary_has_consecutive_losses(self):
        comp, gw = _fresh()
        comp.compute_daily_comparison("2024-01-01", -5.0)
        comp.compute_daily_comparison("2024-01-02", -3.0)
        summary = comp.get_recent_summary()
        self.assertEqual(summary["consecutive_losses_to_zero"], 2)

    def test_06_recent_comments_at_most_three(self):
        comp, gw = _fresh()
        for i in range(5):
            comp.compute_daily_comparison(f"2024-01-0{i+1}", 5.0)
        summary = comp.get_recent_summary()
        self.assertLessEqual(len(summary["recent_comments"]), 3)

    def test_07_beats_bh_count_in_summary(self):
        # BH = 0.1 ETH * 2000 = 200; day1: 250 > 200; day2: 195 < 200
        comp, gw = _fresh(initial_eth_price=2000.0, current_eth_price=2000.0)
        comp.compute_daily_comparison("2024-01-01", 50.0)  # system=250 > BH=200 → beats
        comp.compute_daily_comparison("2024-01-02", -5.0)  # system=195 < BH=200 → no
        summary = comp.get_recent_summary()
        self.assertEqual(summary["system_beats_bh"], 1)


# ─── Group 12: ETH 價格不可用時的行為 ────────────────────────────────────────

class TestGroup12_NoPriceData(unittest.TestCase):

    def test_01_bh_value_none_when_current_price_unavailable(self):
        reset_bus()
        gw = MagicMock()
        gw.get_market_kline.return_value = _make_failed_result()
        comp = BaselineComparator(gateway=gw, initial_eth_price=2000.0)
        result = comp.compute_daily_comparison("2024-01-01", 10.0)
        self.assertIsNone(result["bh_value"])

    def test_02_beats_bh_false_when_no_current_price(self):
        reset_bus()
        gw = MagicMock()
        gw.get_market_kline.return_value = _make_failed_result()
        comp = BaselineComparator(gateway=gw, initial_eth_price=2000.0)
        result = comp.compute_daily_comparison("2024-01-01", 10.0)
        self.assertFalse(result["beats_bh"])

    def test_03_beats_zero_still_works_without_price(self):
        reset_bus()
        gw = MagicMock()
        gw.get_market_kline.return_value = _make_failed_result()
        comp = BaselineComparator(gateway=gw, initial_eth_price=2000.0)
        result = comp.compute_daily_comparison("2024-01-01", 10.0)
        self.assertTrue(result["beats_zero"])

    def test_04_comment_still_generated_without_price(self):
        reset_bus()
        gw = MagicMock()
        gw.get_market_kline.return_value = _make_failed_result()
        comp = BaselineComparator(gateway=gw, initial_eth_price=2000.0)
        result = comp.compute_daily_comparison("2024-01-01", 10.0)
        # beats_zero=True, bh_value=None → "勉強沒虧" branch
        self.assertIn("ETH", result["comment"])

    def test_05_no_bh_amount_when_no_initial_price(self):
        reset_bus()
        gw = MagicMock()
        gw.get_market_kline.return_value = _make_failed_result()
        comp = BaselineComparator(gateway=gw)
        self.assertIsNone(comp.bh_initial_eth_amount)

    def test_06_no_bh_value_when_no_bh_eth_amount(self):
        reset_bus()
        gw = MagicMock()
        # Init fails, but compute succeeds with a price
        gw.get_market_kline.side_effect = [
            _make_failed_result(),          # init fetch → None
            _make_kline_result(2000.0),     # compute fetch → 2000
        ]
        comp = BaselineComparator(gateway=gw)
        result = comp.compute_daily_comparison("2024-01-01", 10.0)
        # bh_initial_eth_amount is None → bh_value must be None
        self.assertIsNone(result["bh_value"])


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("BaselineComparator Tests  (12 groups)")
    print("=" * 60)
    unittest.main(verbosity=2)
