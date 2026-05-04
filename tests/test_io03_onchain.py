# -*- coding: utf-8 -*-
"""Tests for IO-03 小魏+蓮姐（鏈上監控）— Phase 3 Step 6."""
import io
import sys
import time
import unittest
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import DebateResult, SubReport
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.intelligence.io_03_onchain import (
    OnChainAnalyst,
    OnChainSection,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_transfer(value_eth: float, is_inflow: bool = True) -> dict:
    return {
        "hash":      "0x" + "a" * 64,
        "from":      "0xSender",
        "to":        "0xBinance",
        "value_eth": value_eth,
        "timestamp": int(time.time()),
        "is_inflow": is_inflow,
    }


def _fresh_section() -> OnChainSection:
    get_bus().clear()
    return OnChainSection(gateway=MagicMock())


def _analyst(mode: str) -> OnChainAnalyst:
    return OnChainAnalyst(mode, gateway=MagicMock())


def _populate_history(section: OnChainSection, changes: dict) -> None:
    """Populate balance_history with (old_balance, new_balance) per wallet name."""
    now = time.time()
    for name, (old_bal, new_bal) in changes.items():
        section.xiaowei.balance_history[name].extend([
            (now - 3600, old_bal),
            (now,        new_bal),
        ])


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestIO03OnChain(unittest.TestCase):

    # ── 01: 初始化與共用 balance_history ─────────────────────────────────────

    def test_01_init_roles_and_shared_history(self):
        section = _fresh_section()

        self.assertEqual(section.xiaowei.role_name, "小魏")
        self.assertEqual(section.xiaowei.role_code, "IO-03a")
        self.assertEqual(section.lianjie.role_name, "蓮姐")
        self.assertEqual(section.lianjie.role_code, "IO-03b")
        self.assertIs(section.xiaowei.balance_history, section.lianjie.balance_history)
        self.assertEqual(len(section.debate_history), 0)

    # ── 02: 小魏 巨額流入 → bearish 0.6 ──────────────────────────────────────

    def test_02_xiaowei_large_inflow_bearish(self):
        a = _analyst("single_whale")
        result = a._whale_analysis({}, [_make_transfer(60000, True)])

        self.assertIsInstance(result, SubReport)
        self.assertEqual(result.direction, "bearish")
        self.assertAlmostEqual(result.sub_confidence, 0.6)
        self.assertIn("巨鯨流入", result.reasoning)

    # ── 03: 小魏 中等流入（20k-50k）→ bearish 0.4 ────────────────────────────

    def test_03_xiaowei_medium_inflow_bearish(self):
        a = _analyst("single_whale")
        result = a._whale_analysis({}, [_make_transfer(30000, True)])

        self.assertEqual(result.direction, "bearish")
        self.assertAlmostEqual(result.sub_confidence, 0.4)

    # ── 04: 小魏 小額流入（5k-20k）→ bearish 0.2 ─────────────────────────────

    def test_04_xiaowei_small_inflow_bearish(self):
        a = _analyst("single_whale")
        result = a._whale_analysis({}, [_make_transfer(6000, True)])

        self.assertEqual(result.direction, "bearish")
        self.assertAlmostEqual(result.sub_confidence, 0.2)

    # ── 05: 小魏 巨額流出 → bullish 0.5 ──────────────────────────────────────

    def test_05_xiaowei_large_outflow_bullish(self):
        a = _analyst("single_whale")
        result = a._whale_analysis({}, [_make_transfer(60000, False)])

        self.assertEqual(result.direction, "bullish")
        self.assertAlmostEqual(result.sub_confidence, 0.5)

    # ── 06: 小魏 中等流出（20k-50k）→ bullish 0.3 ────────────────────────────

    def test_06_xiaowei_medium_outflow_bullish(self):
        a = _analyst("single_whale")
        result = a._whale_analysis({}, [_make_transfer(25000, False)])

        self.assertEqual(result.direction, "bullish")
        self.assertAlmostEqual(result.sub_confidence, 0.3)

    # ── 07: 小魏 近 5 筆 ≥4 流入 → bearish 0.3 ───────────────────────────────

    def test_07_xiaowei_pattern_4_inflows_bearish(self):
        a = _analyst("single_whale")
        # value 200 < whale_alert_threshold (5000): no whale signal; pattern fires only
        transfers = [_make_transfer(200, True)] * 5
        result = a._whale_analysis({}, transfers)

        self.assertEqual(result.direction, "bearish")
        self.assertAlmostEqual(result.sub_confidence, 0.3)
        self.assertIn("近 5 筆", result.reasoning)

    # ── 08: 小魏 近 5 筆 ≤1 流入 → bullish 0.3 ───────────────────────────────

    def test_08_xiaowei_pattern_low_inflow_bullish(self):
        a = _analyst("single_whale")
        transfers = [
            _make_transfer(200, False),
            _make_transfer(200, False),
            _make_transfer(200, False),
            _make_transfer(200, False),
            _make_transfer(200, True),   # only 1 inflow out of 5
        ]
        result = a._whale_analysis({}, transfers)

        self.assertEqual(result.direction, "bullish")
        self.assertAlmostEqual(result.sub_confidence, 0.3)

    # ── 09: 小魏 無轉帳資料 → neutral ────────────────────────────────────────

    def test_09_xiaowei_neutral_no_transfers(self):
        a = _analyst("single_whale")
        result = a._whale_analysis({}, [])

        self.assertEqual(result.direction, "neutral")
        self.assertAlmostEqual(result.sub_confidence, 0.3)

    # ── 10: 蓮姐 餘額下降 >3% → bullish 0.5 ──────────────────────────────────

    def test_10_lianjie_balance_decrease_bullish(self):
        section = _fresh_section()
        _populate_history(section, {
            "Binance_14": (10000, 9500),   # -5%
            "Binance_15": (10000, 9500),   # -5%
        })
        result = section.lianjie._aggregate_analysis({}, [])

        self.assertEqual(result.direction, "bullish")
        self.assertAlmostEqual(result.sub_confidence, 0.5)
        self.assertIn("資金大量流出", result.reasoning)

    # ── 11: 蓮姐 餘額上升 >3% → bearish 0.5 ──────────────────────────────────

    def test_11_lianjie_balance_increase_bearish(self):
        section = _fresh_section()
        _populate_history(section, {
            "Binance_14": (10000, 10400),   # +4%
            "Binance_15": (10000, 10400),   # +4%
        })
        result = section.lianjie._aggregate_analysis({}, [])

        self.assertEqual(result.direction, "bearish")
        self.assertAlmostEqual(result.sub_confidence, 0.5)
        self.assertIn("資金湧入", result.reasoning)

    # ── 12: 蓮姐 淨流入 >30000 ETH → bearish 0.4 ─────────────────────────────

    def test_12_lianjie_net_inflow_bearish(self):
        section = _fresh_section()
        result = section.lianjie._aggregate_analysis(
            {}, [_make_transfer(40000, True)]
        )

        self.assertEqual(result.direction, "bearish")
        self.assertAlmostEqual(result.sub_confidence, 0.4)

    # ── 13: 蓮姐 淨流出 >30000 ETH → bullish 0.4 ─────────────────────────────

    def test_13_lianjie_net_outflow_bullish(self):
        section = _fresh_section()
        result = section.lianjie._aggregate_analysis(
            {}, [_make_transfer(40000, False)]
        )

        self.assertEqual(result.direction, "bullish")
        self.assertAlmostEqual(result.sub_confidence, 0.4)

    # ── 14: 蓮姐 無資料 → neutral ────────────────────────────────────────────

    def test_14_lianjie_neutral_no_data(self):
        section = _fresh_section()
        result = section.lianjie._aggregate_analysis({}, [])

        self.assertEqual(result.direction, "neutral")
        self.assertAlmostEqual(result.sub_confidence, 0.3)

    # ── 15: Section agreed bearish ────────────────────────────────────────────
    # 小魏: 60000 ETH inflow → bearish 0.6
    # 蓮姐: net_flow 60000 > 30000, no balance history → bearish 0.4
    # diff = 0.2 ≤ 0.2 → agreed; final = (0.6+0.4)/2 = 0.5

    def test_15_section_agreed_bearish(self):
        section = _fresh_section()
        transfers = [_make_transfer(60000, True)]
        section.xiaowei.fetch_wallet_balances = lambda: {}
        section.xiaowei.fetch_recent_transfers = lambda: transfers

        result = section.conduct_debate()

        self.assertIsInstance(result, DebateResult)
        self.assertEqual(result.consensus_type, "agreed")
        self.assertEqual(result.final_direction, "bearish")
        self.assertAlmostEqual(result.final_confidence, 0.5)

    # ── 16: Section dual_track ────────────────────────────────────────────────
    # 小魏: 6000 ETH inflow (>5000) → bearish 0.2
    # 蓮姐: balance -5% → bullish 0.5; 6000 ETH < 30000 → no net_flow signal
    # → dual_track; bearish(severity=2) beats bullish(0); final = 0.2 × 0.8 = 0.16

    def test_16_section_dual_track(self):
        section = _fresh_section()
        transfers = [_make_transfer(6000, True)]
        _populate_history(section, {
            "Binance_14": (10000, 9500),   # -5%
            "Binance_15": (10000, 9500),   # -5%
        })
        section.xiaowei.fetch_wallet_balances = lambda: {}
        section.xiaowei.fetch_recent_transfers = lambda: transfers

        result = section.conduct_debate()

        self.assertEqual(result.consensus_type, "dual_track")
        self.assertEqual(result.final_direction, "bearish")
        self.assertAlmostEqual(result.final_confidence, 0.16, places=5)

    # ── 17: Section discussed_agreed ─────────────────────────────────────────
    # 小魏: 60000 ETH inflow → bearish 0.6
    # 蓮姐: balance +4% → bearish 0.5; net_flow 60000 → bearish 0.4; total = 0.9
    # diff = |0.6 - 0.9| = 0.3 > 0.2 → discussed_agreed

    def test_17_section_discussed_agreed(self):
        section = _fresh_section()
        transfers = [_make_transfer(60000, True)]
        _populate_history(section, {
            "Binance_14": (10000, 10400),   # +4%
            "Binance_15": (10000, 10400),   # +4%
        })
        section.xiaowei.fetch_wallet_balances = lambda: {}
        section.xiaowei.fetch_recent_transfers = lambda: transfers

        result = section.conduct_debate()

        self.assertEqual(result.consensus_type, "discussed_agreed")
        self.assertEqual(result.final_direction, "bearish")
        expected = (0.6 ** 2 + 0.9 ** 2) / (0.6 + 0.9)   # ≈ 0.78
        self.assertAlmostEqual(result.final_confidence, expected, places=5)

    # ── 18: debate_id 格式 & debate_history 累積 ──────────────────────────────

    def test_18_debate_id_and_history(self):
        section = _fresh_section()
        section.xiaowei.fetch_wallet_balances = lambda: {}
        section.xiaowei.fetch_recent_transfers = lambda: []

        r1 = section.conduct_debate()
        r2 = section.conduct_debate()

        self.assertTrue(r1.debate_id.startswith("IO-03-"))
        self.assertTrue(r2.debate_id.startswith("IO-03-"))
        self.assertNotEqual(r1.debate_id, r2.debate_id)
        self.assertEqual(len(section.debate_history), 2)

    # ── 19: 共用 balance_history（寫入 xiaowei 立即可從 lianjie 讀到）─────────

    def test_19_shared_balance_history_reference(self):
        section = _fresh_section()
        self.assertIs(section.xiaowei.balance_history, section.lianjie.balance_history)

        now = time.time()
        section.xiaowei.balance_history["Binance_14"].append((now, 50000.0))

        self.assertEqual(
            section.lianjie.balance_history["Binance_14"][-1][1], 50000.0
        )

    # ── 20: get_status 必要欄位 ───────────────────────────────────────────────

    def test_20_get_status_keys(self):
        section = _fresh_section()
        section.xiaowei.fetch_wallet_balances = lambda: {}
        section.xiaowei.fetch_recent_transfers = lambda: []
        section.conduct_debate()

        status = section.get_status()

        for key in ("section", "debate_count", "latest_debate", "consensus_rate"):
            self.assertIn(key, status)
        self.assertEqual(status["debate_count"], 1)
        self.assertIsNotNone(status["latest_debate"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
