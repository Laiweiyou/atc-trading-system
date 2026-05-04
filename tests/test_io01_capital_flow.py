# -*- coding: utf-8 -*-
"""Tests for IO-01 老徐+小曾 CapitalFlowAnalyst / CapitalFlowSection — Phase 3 Step 4."""
import io
import sys
import unittest
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import DebateResult, SubReport
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.intelligence.io_01_capital_flow import (
    CapitalFlowAnalyst,
    CapitalFlowSection,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_gateway():
    gw = MagicMock()
    gw.get_funding_rate.return_value  = {"success": False}
    gw.get_open_interest.return_value = {"success": False}
    gw.get_account_ratio.return_value = {"success": False}
    return gw


def _fresh_section(gateway=None) -> CapitalFlowSection:
    get_bus().clear()
    gw = gateway or _make_gateway()
    return CapitalFlowSection(gateway=gw)


def _fresh_analyst(mode: str, gateway=None) -> CapitalFlowAnalyst:
    get_bus().clear()
    gw = gateway or _make_gateway()
    return CapitalFlowAnalyst(mode, gateway=gw)


def _funding_gateway(rates: list, oi: list = None, ratios: list = None):
    """Build a mock gateway with specific funding/OI/ratio data."""
    gw = _make_gateway()

    gw.get_funding_rate.return_value = {
        "success": True,
        "data": {"list": [{"fundingRate": str(r)} for r in rates]},
    }

    if oi is not None:
        gw.get_open_interest.return_value = {
            "success": True,
            "data": {"list": [{"openInterest": str(o)} for o in oi]},
        }

    if ratios is not None:
        gw.get_account_ratio.return_value = {
            "success": True,
            "data": {"list": [{"buyRatio": str(r)} for r in ratios]},
        }

    return gw


# ── Test 01 — 初始化 ──────────────────────────────────────────────────────────

class TestIO01Init(unittest.TestCase):
    """Test 01 — 兩位分析員獨立工作。"""

    def test_01_laoxu_mode_and_role(self):
        analyst = _fresh_analyst("historical_percentile")
        self.assertEqual(analyst.role_name, "老徐")
        self.assertEqual(analyst.role_code, "IO-01a")
        self.assertEqual(analyst.mode, "historical_percentile")

    def test_01_xiaozeng_mode_and_role(self):
        analyst = _fresh_analyst("trend_slope")
        self.assertEqual(analyst.role_name, "小曾")
        self.assertEqual(analyst.role_code, "IO-01b")
        self.assertEqual(analyst.mode, "trend_slope")

    def test_01_invalid_mode_raises(self):
        with self.assertRaises(AssertionError):
            CapitalFlowAnalyst("unknown_mode", gateway=_make_gateway())

    def test_01_section_creates_both(self):
        section = _fresh_section()
        self.assertEqual(section.laoxu.role_name,    "老徐")
        self.assertEqual(section.xiaozeng.role_name, "小曾")

    def test_01_no_data_returns_empty_report(self):
        analyst = _fresh_analyst("historical_percentile")
        report  = analyst.analyze("ETHUSDT")
        self.assertIsInstance(report, SubReport)
        self.assertEqual(report.direction, "neutral")
        self.assertEqual(report.sub_confidence, 0.1)
        self.assertTrue(report.staleness_flag)

    def test_01_last_analysis_stored(self):
        gw = _funding_gateway([0.001] * 15)
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        self.assertIsNone(analyst.last_analysis)
        analyst.analyze()
        self.assertIsNotNone(analyst.last_analysis)


# ── Test 02 — 老徐歷史百分位 ──────────────────────────────────────────────────

class TestIO01LaoxuHistorical(unittest.TestCase):
    """Test 02 — 老徐的歷史百分位分析。"""

    def _make_extreme_high_gateway(self):
        """90 筆 -0.001~0.001，當前 0.005（極端高位）。"""
        history = [-0.001 + i * (0.002 / 89) for i in range(90)]  # -0.001 to 0.001
        # 最新在前：current=0.005, then history
        rates = [0.005] + history
        return _funding_gateway(rates)

    def test_02_extreme_high_funding_bearish(self):
        gw      = self._make_extreme_high_gateway()
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bearish")

    def test_02_extreme_high_contains_overheat_message(self):
        gw      = self._make_extreme_high_gateway()
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("過熱", report.reasoning)

    def test_02_funding_percentile_in_data_used(self):
        gw      = self._make_extreme_high_gateway()
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("funding_percentile", report.data_used)
        self.assertGreater(report.data_used["funding_percentile"], 90)

    def test_02_low_funding_bullish(self):
        """資金費率極低 → bullish（過冷反彈）。"""
        history = [0.001 + i * (0.002 / 89) for i in range(90)]  # 0.001 to 0.003
        rates   = [-0.005] + history   # current 極低
        gw      = _funding_gateway(rates)
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bullish")
        self.assertIn("過冷", report.reasoning)

    def test_02_high_oi_adds_bearish_signal(self):
        """OI 極高位（>90%）→ 爆倉風險訊號。"""
        rates  = [0.001] * 20                       # 中性資金費率
        oi_list = list(range(1, 91)) + [100]        # 最新 OI 在前，排名極高
        gw      = _funding_gateway(rates, oi=oi_list)
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("oi_percentile", report.data_used)

    def test_02_long_ratio_extreme_high_bearish(self):
        """多空比 > 0.7 → 散戶過度看多 → bearish 反向訊號。"""
        rates  = [0.001] * 20
        ratios = [0.75] + [0.5] * 20    # 最新看多比例極高
        gw     = _funding_gateway(rates, ratios=ratios)
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("散戶過度看多", report.reasoning)

    def test_02_long_ratio_extreme_low_bullish(self):
        """多空比 < 0.4 → 散戶過度看空 → bullish 反向訊號。"""
        rates  = [0.001] * 20
        ratios = [0.3] + [0.5] * 20
        gw     = _funding_gateway(rates, ratios=ratios)
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("散戶過度看空", report.reasoning)

    def test_02_estimated_costs_in_data_used(self):
        """OI + funding 都有時應包含爆倉估算欄位。"""
        rates   = [0.005] + [-0.001 + i * (0.002 / 89) for i in range(90)]
        oi_list = list(range(1, 20))
        gw      = _funding_gateway(rates, oi=oi_list)
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("estimated_long_cost",  report.data_used)
        self.assertIn("estimated_short_cost", report.data_used)


# ── Test 03 — 小曾趨勢分析 ────────────────────────────────────────────────────

class TestIO01XiaozengTrend(unittest.TestCase):
    """Test 03 — 小曾的趨勢分析。"""

    def _make_descending_gateway(self):
        """資金費率下降序列（最新在前）：newest=0.0001（最低），oldest=0.001（最高）。
        時間序列：0.001→0.0008→...→0.0001 = 下降趨勢。"""
        rates = [0.0001, 0.0003, 0.0005, 0.0008, 0.001]  # newest first → oldest is 0.001
        return _funding_gateway(rates)

    def test_03_descending_funding_bearish(self):
        gw      = self._make_descending_gateway()
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bearish")

    def test_03_descending_contains_trend_message(self):
        gw      = self._make_descending_gateway()
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("下降趨勢", report.reasoning)

    def test_03_ascending_funding_bullish(self):
        """資金費率上升序列 → bullish。newest=0.001（最高），oldest=0.0001（最低）。
        時間序列：0.0001→0.0003→...→0.001 = 上升趨勢。"""
        rates   = [0.001, 0.0008, 0.0005, 0.0003, 0.0001]   # newest first → oldest is 0.0001
        gw      = _funding_gateway(rates)
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        self.assertEqual(report.direction, "bullish")
        self.assertIn("上升趨勢", report.reasoning)

    def test_03_funding_slope_in_data_used(self):
        gw      = self._make_descending_gateway()
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("funding_slope", report.data_used)
        self.assertLess(report.data_used["funding_slope"], -0.0001)

    def test_03_oi_increasing_bullish(self):
        """OI 5 筆中最新比最舊增加 >5% → 資金湧入。"""
        rates = [0.001] * 5
        # 最新在前：OI 最新=110, 最舊=100，增加 10%
        oi    = [110, 108, 105, 102, 100]
        gw    = _funding_gateway(rates, oi=oi)
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("資金湧入", report.reasoning)

    def test_03_oi_decreasing_bearish(self):
        """OI 減少 >5% → 資金撤離。"""
        rates = [0.001] * 5
        oi    = [90, 93, 96, 98, 100]  # 最新=90, 最舊=100，下降 10%
        gw    = _funding_gateway(rates, oi=oi)
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("資金撤離", report.reasoning)

    def test_03_ratio_turning_bearish(self):
        """散戶多空比從 0.5 升至 0.6（change=0.1 > 0.05）→ 散戶轉向看多（反向 bearish）。"""
        rates  = [0.001] * 5
        ratios = [0.6, 0.58, 0.55, 0.52, 0.5]  # 最新在前
        gw     = _funding_gateway(rates, ratios=ratios)
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("散戶轉向看多", report.reasoning)

    def test_03_ratio_turning_bullish(self):
        """散戶多空比從 0.6 降至 0.5 → 散戶轉向看空（反向 bullish）。"""
        rates  = [0.001] * 5
        ratios = [0.5, 0.52, 0.55, 0.58, 0.6]  # 最新在前
        gw     = _funding_gateway(rates, ratios=ratios)
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("散戶轉向看空", report.reasoning)

    def test_03_flat_funding_neutral(self):
        """資金費率持平 → slope ≈ 0 → 無訊號。"""
        rates   = [0.001, 0.001, 0.001, 0.001, 0.001]
        gw      = _funding_gateway(rates)
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        # slope=0 → no signal → neutral
        self.assertEqual(report.direction, "neutral")


# ── Test 04 — 共識：兩人 bearish agreed ───────────────────────────────────────

class TestIO01Consensus(unittest.TestCase):
    """Test 04 — 共識：兩人都看到資金費率異常高 → bearish agreed。"""

    def _make_both_bearish_gateway(self):
        """
        老徐：最新費率 0.002 在歷史 89 筆 (-0.001~0.0001) 中排 ~96% → bearish (0.4)
        小曾：recent_5 (newest first) = [0.002, 0.003, 0.004, 0.005, 0.006]
               時間序列 (oldest→newest) = [0.006, 0.005, 0.004, 0.003, 0.002] → 下降 → bearish (0.3)
        conf_diff = |0.4-0.3| = 0.1 ≤ 0.2 → agreed
        """
        history_89 = [-0.001 + i * (0.0011 / 88) for i in range(89)]  # -0.001 to 0.0001
        # newest first: newest=0.002 (lower than older → declining over time)
        recent_5   = [0.002, 0.003, 0.004, 0.005, 0.006]
        rates      = recent_5 + history_89
        return _funding_gateway(rates)

    def test_04_both_bearish_agreed(self):
        gw      = self._make_both_bearish_gateway()
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        self.assertEqual(debate.report_a.direction, "bearish")
        self.assertEqual(debate.report_b.direction, "bearish")
        self.assertEqual(debate.consensus_type, "agreed")

    def test_04_final_direction_bearish(self):
        gw      = self._make_both_bearish_gateway()
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        self.assertEqual(debate.final_direction, "bearish")

    def test_04_final_confidence_is_average(self):
        gw      = self._make_both_bearish_gateway()
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        expected = (debate.report_a.sub_confidence + debate.report_b.sub_confidence) / 2
        self.assertAlmostEqual(debate.final_confidence, expected, places=5)

    def test_04_no_key_disagreement(self):
        gw      = self._make_both_bearish_gateway()
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        self.assertIsNone(debate.key_disagreement)


# ── Test 05 — 大分歧（均值回歸 vs 動量延續）─────────────────────────────────

class TestIO01DualTrack(unittest.TestCase):
    """Test 05 — 大分歧：老徐 bearish（高位）vs 小曾 bullish（剛開始上升）。"""

    def _make_divergent_gateway(self):
        """
        老徐：歷史 89 筆在較高範圍（0.003~0.005），最新 0.006 → 仍然偏高
              但要讓老徐看到 >90% 的高位才觸發 bearish
        小曾：最近 5 筆上升（0.001→0.002→0.003→0.004→0.005，最新在前=0.005）→ slope>0 → bullish

        設計：
        - 歷史 89 筆：0.001 ~ 0.003（老徐的對比基準）
        - 最新 5 筆（小曾用）：0.005, 0.004, 0.003, 0.002, 0.001（最新在前 → 上升趨勢）
          但要讓老徐看到 0.005 在 [0.001..0.003] 歷史中排 100% → bearish
        """
        history_89 = [0.001 + i * (0.002 / 88) for i in range(89)]  # 0.001 to 0.003
        # 小曾看到的最近 5 筆（最新在前）: 上升趨勢 → slope > 0
        recent_5   = [0.005, 0.004, 0.003, 0.002, 0.001]
        rates      = recent_5 + history_89
        return _funding_gateway(rates)

    def test_05_dual_track(self):
        gw      = self._make_divergent_gateway()
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        # 老徐：0.005 在 history_89 中排 100% → bearish (0.4)
        # 小曾：recent_5 上升 → slope > 0 → bullish (0.3)
        self.assertEqual(debate.consensus_type, "dual_track")

    def test_05_laoxu_bearish(self):
        gw      = self._make_divergent_gateway()
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        self.assertEqual(debate.report_a.direction, "bearish")

    def test_05_xiaozeng_bullish(self):
        gw      = self._make_divergent_gateway()
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        self.assertEqual(debate.report_b.direction, "bullish")

    def test_05_conservative_takes_bearish(self):
        """大分歧時採保守（severity: bearish=2 > bullish=0）→ final = bearish。"""
        gw      = self._make_divergent_gateway()
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        self.assertEqual(debate.final_direction, "bearish")

    def test_05_key_disagreement_populated(self):
        gw      = self._make_divergent_gateway()
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        self.assertIsNotNone(debate.key_disagreement)
        self.assertIn("老徐", debate.key_disagreement)
        self.assertIn("小曾", debate.key_disagreement)

    def test_05_confidence_is_0_8_of_bearish(self):
        """dual_track 時 confidence = bearish.confidence × 0.8。"""
        gw      = self._make_divergent_gateway()
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        expected = debate.report_a.sub_confidence * 0.8
        self.assertAlmostEqual(debate.final_confidence, expected, places=5)


# ── Test 06 — 真實 API 測試（DRY-RUN）────────────────────────────────────────

class TestIO01RealAPI(unittest.TestCase):
    """Test 06 — 真實 Bybit API（DRY-RUN）。"""

    def test_06_real_api_debate_returns_result(self):
        section = CapitalFlowSection()  # real gateway
        debate  = section.conduct_debate("ETHUSDT")
        self.assertIsInstance(debate, DebateResult)

    def test_06_real_api_debate_id_prefix(self):
        section = CapitalFlowSection()
        debate  = section.conduct_debate("ETHUSDT")
        self.assertTrue(debate.debate_id.startswith("IO-01-"))

    def test_06_real_api_directions_valid(self):
        section = CapitalFlowSection()
        debate  = section.conduct_debate("ETHUSDT")
        for d in (debate.report_a.direction, debate.report_b.direction, debate.final_direction):
            self.assertIn(d, ("bullish", "neutral", "bearish"))

    def test_06_real_api_consensus_valid(self):
        section = CapitalFlowSection()
        debate  = section.conduct_debate("ETHUSDT")
        self.assertIn(debate.consensus_type, ("agreed", "discussed_agreed", "dual_track"))

    def test_06_real_api_confidence_in_range(self):
        section = CapitalFlowSection()
        debate  = section.conduct_debate("ETHUSDT")
        self.assertGreater(debate.final_confidence, 0)
        self.assertLessEqual(debate.final_confidence, 0.95)


# ── Test 07 — 資料不足（< 10 筆）─────────────────────────────────────────────

class TestIO01InsufficientData(unittest.TestCase):
    """Test 07 — 資料不足時分析員不 crash。"""

    def test_07_only_3_funding_rates_no_crash(self):
        """只有 3 筆 funding_rate（不足 10）→ 老徐跳過，不 crash。"""
        gw = _funding_gateway([0.001, 0.002, 0.003])
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        report  = analyst.analyze()
        self.assertIsInstance(report, SubReport)
        # funding_percentile should NOT be in data_used (< 10 points)
        self.assertNotIn("funding_percentile", report.data_used)

    def test_07_only_3_funding_trend_no_crash(self):
        """只有 3 筆 funding_rate（不足 5）→ 小曾跳過，不 crash。"""
        gw = _funding_gateway([0.001, 0.002, 0.003])
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        self.assertIsInstance(report, SubReport)
        # < 5 points → no funding_slope
        self.assertNotIn("funding_slope", report.data_used)

    def test_07_exactly_5_rates_trend_computed(self):
        """恰好 5 筆 → 小曾計算 slope。"""
        rates   = [0.001, 0.0008, 0.0005, 0.0003, 0.0001]
        gw      = _funding_gateway(rates)
        analyst = _fresh_analyst("trend_slope", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("funding_slope", report.data_used)

    def test_07_exactly_10_rates_percentile_computed(self):
        """恰好 10 筆 → 老徐計算百分位。"""
        rates   = [0.001 * i for i in range(1, 11)]
        gw      = _funding_gateway(rates)
        analyst = _fresh_analyst("historical_percentile", gateway=gw)
        report  = analyst.analyze()
        self.assertIn("funding_percentile", report.data_used)

    def test_07_empty_data_returns_empty_report(self):
        """完全沒資料 → staleness_flag=True。"""
        analyst = _fresh_analyst("historical_percentile")
        report  = analyst.analyze()
        self.assertTrue(report.staleness_flag)
        self.assertEqual(report.sub_confidence, 0.1)

    def test_07_section_debate_no_crash_with_3_rates(self):
        """Section.conduct_debate 在少量資料下不 crash。"""
        gw      = _funding_gateway([0.001, 0.002, 0.003])
        section = _fresh_section(gateway=gw)
        debate  = section.conduct_debate()
        self.assertIsInstance(debate, DebateResult)


# ── Test 08 — 完整流程（連續 5 次辯論）────────────────────────────────────────

class TestIO01FullFlow(unittest.TestCase):
    """Test 08 — 連續 5 次辯論，debate_history 正確記錄。"""

    def test_08_five_debates_recorded(self):
        section = _fresh_section()
        for _ in range(5):
            section.conduct_debate()
        self.assertEqual(len(section.debate_history), 5)

    def test_08_debate_history_contains_debate_results(self):
        section = _fresh_section()
        for _ in range(5):
            section.conduct_debate()
        for d in section.debate_history:
            self.assertIsInstance(d, DebateResult)

    def test_08_debate_ids_unique(self):
        section = _fresh_section()
        debates = [section.conduct_debate() for _ in range(5)]
        ids = [d.debate_id for d in debates]
        self.assertEqual(len(set(ids)), 5)

    def test_08_get_status_keys(self):
        section = _fresh_section()
        section.conduct_debate()
        status = section.get_status()
        for key in ("section", "debate_count", "latest_debate", "consensus_rate"):
            self.assertIn(key, status)

    def test_08_get_status_count(self):
        section = _fresh_section()
        for _ in range(3):
            section.conduct_debate()
        self.assertEqual(section.get_status()["debate_count"], 3)

    def test_08_debate_result_fields(self):
        section = _fresh_section()
        debate  = section.conduct_debate()
        self.assertIsInstance(debate.report_a, SubReport)
        self.assertIsInstance(debate.report_b, SubReport)
        self.assertIn(debate.consensus_type, ("agreed", "discussed_agreed", "dual_track"))
        self.assertIn(debate.final_direction, ("bullish", "neutral", "bearish"))
        self.assertGreater(debate.final_confidence, 0)

    def test_08_deque_maxlen_50(self):
        """maxlen=50 確保超過 50 筆時舊的被丟棄。"""
        section = _fresh_section()
        for _ in range(55):
            section.conduct_debate()
        self.assertEqual(len(section.debate_history), 50)

    def test_08_to_dict_serializable(self):
        section = _fresh_section()
        debate  = section.conduct_debate()
        d = debate.to_dict()
        self.assertIn("debate_id", d)
        self.assertIn("final_direction", d)
        self.assertIn("consensus_type", d)


# ── Additional Unit Tests ──────────────────────────────────────────────────────

class TestIO01CalcSlope(unittest.TestCase):
    """Unit tests for _calc_slope."""

    def setUp(self):
        self.analyst = _fresh_analyst("trend_slope")

    def test_calc_slope_ascending(self):
        slope = self.analyst._calc_slope([1, 2, 3, 4, 5])
        self.assertGreater(slope, 0)

    def test_calc_slope_descending(self):
        slope = self.analyst._calc_slope([5, 4, 3, 2, 1])
        self.assertLess(slope, 0)

    def test_calc_slope_flat(self):
        slope = self.analyst._calc_slope([3, 3, 3, 3, 3])
        self.assertAlmostEqual(slope, 0, places=10)

    def test_calc_slope_single_value(self):
        slope = self.analyst._calc_slope([5])
        self.assertEqual(slope, 0.0)


class TestIO01CompareReports(unittest.TestCase):
    """Unit tests for _compare_reports logic."""

    def _make_report(self, direction: str, confidence: float, role: str = "老徐", code: str = "IO-01a") -> SubReport:
        from datetime import datetime
        return SubReport(
            role_name=role, role_code=code,
            direction=direction, sub_confidence=confidence,
            reasoning="test", data_used={},
            timestamp=datetime.now(), staleness_flag=False,
        )

    def test_agreed_same_direction_close_confidence(self):
        section = _fresh_section()
        a = self._make_report("bearish", 0.4)
        b = self._make_report("bearish", 0.3, "小曾", "IO-01b")
        ctype, direction, conf, _ = section._compare_reports(a, b)
        self.assertEqual(ctype, "agreed")
        self.assertEqual(direction, "bearish")
        self.assertAlmostEqual(conf, 0.35, places=5)

    def test_discussed_agreed_same_direction_large_diff(self):
        section = _fresh_section()
        a = self._make_report("bullish", 0.9)
        b = self._make_report("bullish", 0.3, "小曾", "IO-01b")
        ctype, direction, conf, _ = section._compare_reports(a, b)
        self.assertEqual(ctype, "discussed_agreed")
        self.assertEqual(direction, "bullish")

    def test_dual_track_bearish_wins(self):
        section = _fresh_section()
        a = self._make_report("bearish", 0.4)
        b = self._make_report("bullish", 0.3, "小曾", "IO-01b")
        ctype, direction, conf, _ = section._compare_reports(a, b)
        self.assertEqual(ctype, "dual_track")
        self.assertEqual(direction, "bearish")
        self.assertAlmostEqual(conf, 0.32, places=5)

    def test_dual_track_neutral_vs_bullish_neutral_wins(self):
        """neutral(1) > bullish(0) → neutral wins in dual_track."""
        section = _fresh_section()
        a = self._make_report("neutral", 0.4)
        b = self._make_report("bullish", 0.5, "小曾", "IO-01b")
        ctype, direction, conf, _ = section._compare_reports(a, b)
        self.assertEqual(ctype, "dual_track")
        self.assertEqual(direction, "neutral")


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    for cls in [
        TestIO01Init,
        TestIO01LaoxuHistorical,
        TestIO01XiaozengTrend,
        TestIO01Consensus,
        TestIO01DualTrack,
        TestIO01RealAPI,
        TestIO01InsufficientData,
        TestIO01FullFlow,
        TestIO01CalcSlope,
        TestIO01CompareReports,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
