# -*- coding: utf-8 -*-
"""Tests for IO-02 阿賴+珊珊 SentimentAnalyst / SentimentSection — Phase 3 Step 5."""
import io
import sys
import unittest
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import DebateResult, SubReport
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.intelligence.io_02_sentiment import (
    SentimentAnalyst,
    SentimentSection,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_gateway():
    gw = MagicMock()
    gw.get_open_interest.return_value = {"success": False}
    return gw


def _fresh_section(gateway=None) -> SentimentSection:
    get_bus().clear()
    gw = gateway or _make_gateway()
    return SentimentSection(gateway=gw)


def _fresh_analyst(mode: str, gateway=None) -> SentimentAnalyst:
    get_bus().clear()
    gw = gateway or _make_gateway()
    return SentimentAnalyst(mode, gateway=gw)


def _with_data(analyst: SentimentAnalyst, data: dict) -> SentimentAnalyst:
    """Override fetch_data so analyst uses controlled data in unit tests."""
    analyst.fetch_data = lambda: data
    return analyst


def _section_with_data(
    alai_data: dict,
    shanshan_data: dict,
    gateway=None,
) -> SentimentSection:
    """Build a SentimentSection where each analyst uses controlled data."""
    section = _fresh_section(gateway=gateway)
    section.alai.fetch_data     = lambda: alai_data
    section.shanshan.fetch_data = lambda: shanshan_data
    return section


# ── Shared data builders ───────────────────────────────────────────────────────

def _extreme_fear_data() -> dict:
    """FGI=15（極度恐懼）+ 穩定幣 280B + OI +5%。"""
    return {
        "fgi_current":          15,
        "fgi_classification":   "Extreme Fear",
        "fgi_history":          [15, 18, 22, 25, 30],   # newest first
        "total_stablecoin_mcap": 280_000_000_000,
        "usdt_mcap":             200_000_000_000,
        "usdc_mcap":              80_000_000_000,
        "oi_change_24h":         5.0,
    }


def _rising_fgi_data(fgi_now: int = 50, fgi_start: int = 25) -> dict:
    """FGI 5 天從 fgi_start 升到 fgi_now（珊珊讀心型數據）。"""
    step = (fgi_now - fgi_start) // 4
    history = [fgi_now, fgi_now - step, fgi_now - 2*step, fgi_now - 3*step, fgi_start]
    return {
        "fgi_current":           fgi_now,
        "fgi_history":           history,
        "total_stablecoin_mcap": 270_000_000_000,
    }


# ── Test 01 — 初始化 ──────────────────────────────────────────────────────────

class TestIO02Init(unittest.TestCase):
    """Test 01 — 兩位分析員獨立工作。"""

    def test_01_alai_mode_and_role(self):
        analyst = _fresh_analyst("probability")
        self.assertEqual(analyst.role_name, "阿賴")
        self.assertEqual(analyst.role_code, "IO-02a")
        self.assertEqual(analyst.mode, "probability")

    def test_01_shanshan_mode_and_role(self):
        analyst = _fresh_analyst("context_reading")
        self.assertEqual(analyst.role_name, "珊珊")
        self.assertEqual(analyst.role_code, "IO-02b")
        self.assertEqual(analyst.mode, "context_reading")

    def test_01_invalid_mode_raises(self):
        with self.assertRaises(AssertionError):
            SentimentAnalyst("wrong_mode", gateway=_make_gateway())

    def test_01_section_creates_both(self):
        section = _fresh_section()
        self.assertEqual(section.alai.role_name,     "阿賴")
        self.assertEqual(section.shanshan.role_name, "珊珊")

    def test_01_no_data_returns_empty_report(self):
        analyst = _with_data(_fresh_analyst("probability"), {})
        report  = analyst.analyze()
        self.assertIsInstance(report, SubReport)
        self.assertEqual(report.direction, "neutral")
        self.assertEqual(report.sub_confidence, 0.1)
        self.assertTrue(report.staleness_flag)

    def test_01_no_data_shanshan_returns_empty(self):
        analyst = _with_data(_fresh_analyst("context_reading"), {})
        report  = analyst.analyze()
        self.assertTrue(report.staleness_flag)
        self.assertEqual(report.sub_confidence, 0.1)


# ── Test 02 — 阿賴機率分析 ────────────────────────────────────────────────────

class TestIO02AlaiProbability(unittest.TestCase):
    """Test 02 — 阿賴的機率分析。"""

    def test_02_extreme_fear_bullish(self):
        analyst = _with_data(_fresh_analyst("probability"), _extreme_fear_data())
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bullish")

    def test_02_reasoning_contains_prob_phrase(self):
        analyst = _with_data(_fresh_analyst("probability"), _extreme_fear_data())
        report  = analyst.analyze()
        self.assertIn("上漲機率", report.reasoning)

    def test_02_fgi_in_data_used(self):
        analyst = _with_data(_fresh_analyst("probability"), _extreme_fear_data())
        report  = analyst.analyze()
        self.assertIn("fgi", report.data_used)
        self.assertEqual(report.data_used["fgi"], 15)

    def test_02_combined_prob_in_data_used(self):
        analyst = _with_data(_fresh_analyst("probability"), _extreme_fear_data())
        report  = analyst.analyze()
        self.assertIn("combined_probability", report.data_used)
        self.assertGreater(report.data_used["combined_probability"], 0.6)

    def test_02_extreme_greed_bearish(self):
        """FGI=85（極度貪婪）→ bearish。"""
        data    = {"fgi_current": 85}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bearish")

    def test_02_neutral_fgi_neutral(self):
        """FGI=50（中性）→ neutral（prob=0.5, conf=0.3）。"""
        data    = {"fgi_current": 50}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "neutral")
        self.assertAlmostEqual(report.sub_confidence, 0.3, places=5)

    def test_02_fear_fgi_bullish(self):
        """FGI=25（恐懼）→ bullish（prob=0.6）。"""
        data    = {"fgi_current": 25}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bullish")

    def test_02_greed_fgi_bearish(self):
        """FGI=65（貪婪）→ bearish（prob=0.4）。"""
        data    = {"fgi_current": 65}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bearish")

    def test_02_large_stablecoin_adds_bullish(self):
        """穩定幣 > 270B → prob=0.6 signal 加入。"""
        data    = {"fgi_current": 50, "total_stablecoin_mcap": 280_000_000_000}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertIn("stablecoin_mcap", report.data_used)

    def test_02_small_stablecoin_bearish_signal(self):
        """穩定幣 < 240B → prob=0.4 bearish signal。"""
        data = {
            "fgi_current":           80,
            "total_stablecoin_mcap": 230_000_000_000,
        }
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bearish")

    def test_02_high_oi_adds_bullish_prob(self):
        """OI 24h > 10% → prob=0.55 signal。"""
        data = {"fgi_current": 50, "oi_change_24h": 15.0}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertIn("oi_change_pct", report.data_used)

    def test_02_confidence_within_bounds(self):
        analyst = _with_data(_fresh_analyst("probability"), _extreme_fear_data())
        report  = analyst.analyze()
        self.assertGreater(report.sub_confidence, 0)
        self.assertLessEqual(report.sub_confidence, 0.95)

    def test_02_staleness_false_when_data_present(self):
        analyst = _with_data(_fresh_analyst("probability"), _extreme_fear_data())
        report  = analyst.analyze()
        self.assertFalse(report.staleness_flag)


# ── Test 03 — 珊珊脈絡分析 ────────────────────────────────────────────────────

class TestIO02ShanshanContext(unittest.TestCase):
    """Test 03 — 珊珊的脈絡分析。"""

    def test_03_rising_fgi_bullish(self):
        """FGI 5 天從 25 升到 50（change=25）→ bullish。"""
        analyst = _with_data(_fresh_analyst("context_reading"), _rising_fgi_data(50, 25))
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bullish")

    def test_03_rising_fgi_contains_warming_message(self):
        analyst = _with_data(_fresh_analyst("context_reading"), _rising_fgi_data(50, 25))
        report  = analyst.analyze()
        self.assertIn("情緒回暖", report.reasoning)

    def test_03_fgi_change_in_data_used(self):
        analyst = _with_data(_fresh_analyst("context_reading"), _rising_fgi_data(50, 25))
        report  = analyst.analyze()
        self.assertIn("fgi_change_5d", report.data_used)
        self.assertGreater(report.data_used["fgi_change_5d"], 15)

    def test_03_falling_fgi_bearish(self):
        """FGI 5 天從 70 降到 45（change=-25）→ bearish。"""
        data = {
            "fgi_current": 45,
            "fgi_history": [45, 52, 58, 64, 70],   # newest first, declining
        }
        analyst = _with_data(_fresh_analyst("context_reading"), data)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bearish")
        self.assertIn("情緒惡化", report.reasoning)

    def test_03_slow_rise_bullish(self):
        """FGI 5 天上升 10 點（8 < change ≤ 15）→ bullish（緩慢）。"""
        data = {
            "fgi_current": 50,
            "fgi_history": [50, 47, 45, 42, 40],   # change=10 > 8
        }
        analyst = _with_data(_fresh_analyst("context_reading"), data)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bullish")

    def test_03_fear_plus_stable_stablecoin_bullish(self):
        """FGI < 35 + 穩定幣 > 260B → 情緒恐懼但資金未撤 → bullish。"""
        data = {
            "fgi_current":           30,
            "fgi_history":           [30, 30, 30, 30, 30],   # flat, no FGI trend
            "total_stablecoin_mcap": 265_000_000_000,
        }
        analyst = _with_data(_fresh_analyst("context_reading"), data)
        report  = analyst.analyze()
        self.assertIn("情緒恐懼但資金未撤", report.reasoning)
        self.assertEqual(report.direction, "bullish")

    def test_03_greed_plus_low_stablecoin_bearish(self):
        """FGI > 65 + 穩定幣 < 250B → 情緒貪婪但資金已轉移 → bearish。"""
        data = {
            "fgi_current":           70,
            "fgi_history":           [70, 70, 70, 70, 70],   # flat
            "total_stablecoin_mcap": 245_000_000_000,
        }
        analyst = _with_data(_fresh_analyst("context_reading"), data)
        report  = analyst.analyze()
        self.assertIn("情緒貪婪但資金已轉移", report.reasoning)
        self.assertEqual(report.direction, "bearish")

    def test_03_oi_increase_high_fgi_bullish(self):
        """OI 增加 + FGI > 50 → 多頭累積 → bullish signal 加入。"""
        data = {
            "fgi_current":  60,
            "fgi_history":  [60, 58, 56, 54, 52],   # change=8, between 8-15
            "oi_change_24h": 8.0,
        }
        analyst = _with_data(_fresh_analyst("context_reading"), data)
        report  = analyst.analyze()
        self.assertIn("多頭累積", report.reasoning)

    def test_03_oi_increase_low_fgi_bearish(self):
        """OI 增加 + FGI < 40 → 空頭累積 → bearish signal。"""
        data = {
            "fgi_current":   35,
            "fgi_history":   [35, 35, 35, 35, 35],
            "oi_change_24h":  8.0,
        }
        analyst = _with_data(_fresh_analyst("context_reading"), data)
        report  = analyst.analyze()
        self.assertIn("空頭累積", report.reasoning)

    def test_03_insufficient_fgi_history_no_crash(self):
        """只有 3 筆 FGI 歷史 → 珊珊跳過 FGI 趨勢，不 crash。"""
        data = {
            "fgi_current": 45,
            "fgi_history": [45, 42, 38],
        }
        analyst = _with_data(_fresh_analyst("context_reading"), data)
        report  = analyst.analyze()
        self.assertIsInstance(report, SubReport)
        self.assertNotIn("fgi_change_5d", report.data_used)


# ── Test 04 — 共識 ────────────────────────────────────────────────────────────

class TestIO02Consensus(unittest.TestCase):
    """Test 04 — 共識：兩人都看到情緒偏多 → bullish agreed。"""

    def _build_agreed_bullish(self):
        """
        阿賴：FGI=10（極度恐懼）→ prob=0.75, conf=0.50 (bullish)
        珊珊：FGI 從 24→40，change=16 > 15 → bullish conf=0.4
        conf_diff = |0.50 - 0.40| = 0.10 ≤ 0.2 → agreed
        """
        alai_data = {"fgi_current": 10}
        shanshan_data = {
            "fgi_current": 40,
            "fgi_history": [40, 36, 32, 28, 24],   # change = 40-24 = 16 > 15
        }
        return _section_with_data(alai_data, shanshan_data)

    def test_04_both_bullish_agreed(self):
        section = self._build_agreed_bullish()
        debate  = section.conduct_debate()
        self.assertEqual(debate.report_a.direction, "bullish")
        self.assertEqual(debate.report_b.direction, "bullish")
        self.assertEqual(debate.consensus_type, "agreed")

    def test_04_final_direction_bullish(self):
        section = self._build_agreed_bullish()
        debate  = section.conduct_debate()
        self.assertEqual(debate.final_direction, "bullish")

    def test_04_final_confidence_is_average(self):
        section = self._build_agreed_bullish()
        debate  = section.conduct_debate()
        expected = (debate.report_a.sub_confidence + debate.report_b.sub_confidence) / 2
        self.assertAlmostEqual(debate.final_confidence, expected, places=5)

    def test_04_no_key_disagreement(self):
        section = self._build_agreed_bullish()
        debate  = section.conduct_debate()
        self.assertIsNone(debate.key_disagreement)

    def test_04_combined_reasoning_has_both_names(self):
        section = self._build_agreed_bullish()
        debate  = section.conduct_debate()
        self.assertIn("阿賴", debate.combined_reasoning)
        self.assertIn("珊珊", debate.combined_reasoning)


# ── Test 05 — 大分歧 ──────────────────────────────────────────────────────────

class TestIO02DualTrack(unittest.TestCase):
    """Test 05 — 大分歧：阿賴 neutral（FGI=45）vs 珊珊 bullish（FGI 持續上升）。"""

    def _build_divergent(self):
        """
        阿賴：FGI=45（中性，prob=0.5, conf=0.3, neutral）
        珊珊：FGI 從 30→46（change=16 > 15 → bullish 0.4）
        neutral vs bullish → dual_track → neutral(1) >= bullish(0) → neutral wins
        """
        alai_data = {"fgi_current": 45}
        shanshan_data = {
            "fgi_current": 46,
            "fgi_history": [46, 42, 38, 34, 30],   # change = 16 > 15 → bullish 0.4
        }
        return _section_with_data(alai_data, shanshan_data)

    def test_05_dual_track(self):
        section = self._build_divergent()
        debate  = section.conduct_debate()
        self.assertEqual(debate.consensus_type, "dual_track")

    def test_05_alai_neutral(self):
        section = self._build_divergent()
        debate  = section.conduct_debate()
        self.assertEqual(debate.report_a.direction, "neutral")

    def test_05_shanshan_bullish(self):
        section = self._build_divergent()
        debate  = section.conduct_debate()
        self.assertEqual(debate.report_b.direction, "bullish")

    def test_05_conservative_takes_neutral(self):
        """dual_track: neutral(severity=1) > bullish(0) → neutral wins。"""
        section = self._build_divergent()
        debate  = section.conduct_debate()
        self.assertEqual(debate.final_direction, "neutral")

    def test_05_confidence_is_0_8_of_neutral(self):
        section = self._build_divergent()
        debate  = section.conduct_debate()
        expected = debate.report_a.sub_confidence * 0.8
        self.assertAlmostEqual(debate.final_confidence, expected, places=5)

    def test_05_key_disagreement_populated(self):
        section = self._build_divergent()
        debate  = section.conduct_debate()
        self.assertIsNotNone(debate.key_disagreement)
        self.assertIn("阿賴", debate.key_disagreement)
        self.assertIn("珊珊", debate.key_disagreement)

    def test_05_bearish_vs_bullish_bearish_wins(self):
        """bearish(2) > bullish(0) → bearish wins。"""
        alai_data     = {"fgi_current": 90}   # 極度貪婪 → bearish
        shanshan_data = {
            "fgi_current": 46,
            "fgi_history": [46, 42, 38, 34, 30],
        }
        section = _section_with_data(alai_data, shanshan_data)
        debate  = section.conduct_debate()
        self.assertEqual(debate.consensus_type, "dual_track")
        self.assertEqual(debate.final_direction, "bearish")

    def test_05_discussed_agreed_same_direction_large_diff(self):
        """Same direction but conf_diff > 0.2 → discussed_agreed。
        阿賴: FGI=5 → prob=0.75, conf=0.50 (bullish)
        珊珊: FGI 上升 9 點 (>8) → bullish 0.2, conf=0.2
        conf_diff = |0.50 - 0.20| = 0.30 > 0.2 → discussed_agreed
        """
        alai_data = {"fgi_current": 5}
        shanshan_data = {
            "fgi_current": 49,
            "fgi_history": [49, 45, 43, 41, 40],   # change=9 > 8 → bullish 0.2
        }
        section = _section_with_data(alai_data, shanshan_data)
        debate  = section.conduct_debate()
        self.assertEqual(debate.consensus_type, "discussed_agreed")
        self.assertEqual(debate.final_direction, "bullish")


# ── Test 06 — 真實 API 測試 ───────────────────────────────────────────────────

class TestIO02RealAPI(unittest.TestCase):
    """Test 06 — 真實 API（Alternative.me FGI + CoinGecko stablecoin）。"""

    def test_06_real_api_debate_returns_result(self):
        section = SentimentSection()
        debate  = section.conduct_debate()
        self.assertIsInstance(debate, DebateResult)

    def test_06_real_api_debate_id_prefix(self):
        section = SentimentSection()
        debate  = section.conduct_debate()
        self.assertTrue(debate.debate_id.startswith("IO-02-"))

    def test_06_real_api_directions_valid(self):
        section = SentimentSection()
        debate  = section.conduct_debate()
        for d in (debate.report_a.direction, debate.report_b.direction, debate.final_direction):
            self.assertIn(d, ("bullish", "neutral", "bearish"))

    def test_06_real_api_consensus_valid(self):
        section = SentimentSection()
        debate  = section.conduct_debate()
        self.assertIn(debate.consensus_type, ("agreed", "discussed_agreed", "dual_track"))

    def test_06_real_api_confidence_positive(self):
        section = SentimentSection()
        debate  = section.conduct_debate()
        self.assertGreater(debate.final_confidence, 0)


# ── Test 07 — 資料不足容錯 ────────────────────────────────────────────────────

class TestIO02InsufficientData(unittest.TestCase):
    """Test 07 — 資料不足時不 crash。"""

    def test_07_empty_data_returns_empty_report(self):
        analyst = _with_data(_fresh_analyst("probability"), {})
        report  = analyst.analyze()
        self.assertIsInstance(report, SubReport)
        self.assertTrue(report.staleness_flag)

    def test_07_only_fgi_no_crash(self):
        data    = {"fgi_current": 50}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertIsInstance(report, SubReport)
        self.assertFalse(report.staleness_flag)

    def test_07_shanshan_only_fgi_history_3_no_crash(self):
        data    = {"fgi_current": 45, "fgi_history": [45, 42, 38]}
        analyst = _with_data(_fresh_analyst("context_reading"), data)
        report  = analyst.analyze()
        self.assertIsInstance(report, SubReport)

    def test_07_missing_stablecoin_no_crash(self):
        data    = {"fgi_current": 20}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertNotIn("stablecoin_mcap", report.data_used)

    def test_07_section_debate_no_crash_empty_data(self):
        section = _section_with_data({}, {})
        debate  = section.conduct_debate()
        self.assertIsInstance(debate, DebateResult)
        self.assertTrue(debate.report_a.staleness_flag)
        self.assertTrue(debate.report_b.staleness_flag)

    def test_07_only_stablecoin_no_fgi_probability(self):
        """只有穩定幣數據時阿賴仍能出報告。"""
        data    = {"total_stablecoin_mcap": 280_000_000_000}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertFalse(report.staleness_flag)
        self.assertIn("stablecoin_mcap", report.data_used)

    def test_07_exactly_5_fgi_history_context_works(self):
        """恰好 5 筆 FGI 歷史 → 珊珊計算 change。"""
        data = {
            "fgi_current": 50,
            "fgi_history": [50, 44, 38, 32, 25],
        }
        analyst = _with_data(_fresh_analyst("context_reading"), data)
        report  = analyst.analyze()
        self.assertIn("fgi_change_5d", report.data_used)
        self.assertEqual(report.data_used["fgi_change_5d"], 25)


# ── Test 08 — 完整流程 ────────────────────────────────────────────────────────

class TestIO02FullFlow(unittest.TestCase):
    """Test 08 — 連續辯論 + debate_history 記錄。"""

    def test_08_five_debates_recorded(self):
        section = _section_with_data({"fgi_current": 50}, {"fgi_current": 50})
        for _ in range(5):
            section.conduct_debate()
        self.assertEqual(len(section.debate_history), 5)

    def test_08_debate_ids_unique(self):
        section = _section_with_data({"fgi_current": 50}, {"fgi_current": 50})
        debates = [section.conduct_debate() for _ in range(5)]
        ids = [d.debate_id for d in debates]
        self.assertEqual(len(set(ids)), 5)

    def test_08_deque_maxlen_50(self):
        section = _section_with_data({"fgi_current": 50}, {"fgi_current": 50})
        for _ in range(55):
            section.conduct_debate()
        self.assertEqual(len(section.debate_history), 50)

    def test_08_get_status_keys(self):
        section = _section_with_data({"fgi_current": 50}, {"fgi_current": 50})
        section.conduct_debate()
        status = section.get_status()
        for key in ("section", "debate_count", "latest_debate", "consensus_rate"):
            self.assertIn(key, status)

    def test_08_get_status_count(self):
        section = _section_with_data({"fgi_current": 50}, {"fgi_current": 50})
        for _ in range(3):
            section.conduct_debate()
        self.assertEqual(section.get_status()["debate_count"], 3)

    def test_08_debate_result_fields(self):
        section = _section_with_data({"fgi_current": 50}, {"fgi_current": 50})
        debate  = section.conduct_debate()
        self.assertIsInstance(debate.report_a, SubReport)
        self.assertIsInstance(debate.report_b, SubReport)
        self.assertIn(debate.consensus_type, ("agreed", "discussed_agreed", "dual_track"))
        self.assertIn(debate.final_direction, ("bullish", "neutral", "bearish"))
        self.assertGreater(debate.final_confidence, 0)

    def test_08_to_dict_serializable(self):
        section = _section_with_data({"fgi_current": 50}, {"fgi_current": 50})
        debate  = section.conduct_debate()
        d = debate.to_dict()
        self.assertIn("debate_id",       d)
        self.assertIn("final_direction", d)
        self.assertIn("consensus_type",  d)


# ── Additional Unit Tests ──────────────────────────────────────────────────────

class TestIO02CompareReports(unittest.TestCase):
    """Unit tests for _compare_reports logic in SentimentSection."""

    def _make_report(
        self,
        direction: str,
        confidence: float,
        role: str = "阿賴",
        code: str = "IO-02a",
    ) -> SubReport:
        return SubReport(
            role_name=role, role_code=code,
            direction=direction, sub_confidence=confidence,
            reasoning="test", data_used={},
            timestamp=__import__("datetime").datetime.now(), staleness_flag=False,
        )

    def test_agreed_same_direction_close_confidence(self):
        section = _fresh_section()
        a = self._make_report("bullish", 0.5)
        b = self._make_report("bullish", 0.4, "珊珊", "IO-02b")
        ctype, direction, conf, _ = section._compare_reports(a, b)
        self.assertEqual(ctype, "agreed")
        self.assertEqual(direction, "bullish")
        self.assertAlmostEqual(conf, 0.45, places=5)

    def test_discussed_agreed_same_direction_large_diff(self):
        section = _fresh_section()
        a = self._make_report("bearish", 0.9)
        b = self._make_report("bearish", 0.3, "珊珊", "IO-02b")
        ctype, direction, conf, _ = section._compare_reports(a, b)
        self.assertEqual(ctype, "discussed_agreed")
        self.assertEqual(direction, "bearish")

    def test_dual_track_bearish_wins(self):
        section = _fresh_section()
        a = self._make_report("bearish", 0.4)
        b = self._make_report("bullish", 0.6, "珊珊", "IO-02b")
        ctype, direction, conf, _ = section._compare_reports(a, b)
        self.assertEqual(ctype, "dual_track")
        self.assertEqual(direction, "bearish")

    def test_dual_track_neutral_vs_bullish(self):
        """neutral(1) > bullish(0) → neutral wins。"""
        section = _fresh_section()
        a = self._make_report("neutral", 0.4)
        b = self._make_report("bullish", 0.5, "珊珊", "IO-02b")
        ctype, direction, conf, _ = section._compare_reports(a, b)
        self.assertEqual(ctype, "dual_track")
        self.assertEqual(direction, "neutral")


class TestIO02ProbabilityMath(unittest.TestCase):
    """Verify probability calculation math for 阿賴。"""

    def test_prob_extreme_fear_fgi_only(self):
        """FGI=10 only → prob=0.75, conf=(0.75-0.5)*2=0.50。"""
        data    = {"fgi_current": 10}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertAlmostEqual(report.sub_confidence, 0.50, places=5)
        self.assertEqual(report.direction, "bullish")

    def test_prob_extreme_greed_fgi_only(self):
        """FGI=85 only → prob=0.25, conf=(0.5-0.25)*2=0.50。"""
        data    = {"fgi_current": 85}
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertAlmostEqual(report.sub_confidence, 0.50, places=5)
        self.assertEqual(report.direction, "bearish")

    def test_weighted_prob_all_three_signals(self):
        """FGI=15(0.75,w=0.35) + stbl=280B(0.60,w=0.30) + OI=5%(0.50,w=0.15)
        weighted_prob = (0.75*0.35 + 0.60*0.30 + 0.50*0.15) / 0.80
                      = (0.2625 + 0.18 + 0.075) / 0.80 = 0.646875
        conf = (0.646875 - 0.5) * 2 = 0.29375"""
        data    = _extreme_fear_data()
        analyst = _with_data(_fresh_analyst("probability"), data)
        report  = analyst.analyze()
        self.assertAlmostEqual(
            report.data_used["combined_probability"], 0.646875, places=4
        )
        self.assertAlmostEqual(report.sub_confidence, 0.29375, places=4)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    for cls in [
        TestIO02Init,
        TestIO02AlaiProbability,
        TestIO02ShanshanContext,
        TestIO02Consensus,
        TestIO02DualTrack,
        TestIO02RealAPI,
        TestIO02InsufficientData,
        TestIO02FullFlow,
        TestIO02CompareReports,
        TestIO02ProbabilityMath,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
